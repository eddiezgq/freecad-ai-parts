"""问渠 CAD「AI 设计零件」面板背后的逻辑（ADR-0100 42.4，§3.1）：不依赖 FreeCAD 界面，普通 pytest 可测。

- run：需求原话 → AI 设计循环（assist.design）→ 通过的话生成模型、回读、二维图、BOM（assist.shaft_model）
- 三个页签的内容（HTML）：条件（每个数 + 原话引用）、每一轮（轴段表 + 校核结论，按通过 / 待确认 / 不通过着色）、AI 的问题与假设
- confirm：人确认后入企业库——模型文件与设计记录登记为企业资料（带 SHA-256），自制件由 41.4 的测量写成组件

显示的文字照旧写中文，按界面语言在显示时翻（assist.i18n.tr）。
"""

from __future__ import annotations

import json
import tempfile
from html import escape
from pathlib import Path

from assist.i18n import tr as T

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "ai-design" / "ls-upper-shaft" / "requirement.txt"
PART_TYPES = ("阶梯轴", "关节空心轴")
EXAMPLES = {"阶梯轴": EXAMPLE, "关节空心轴": ROOT / "examples" / "ai-design" / "cobot-j2" / "requirement.txt"}
EXAMPLE_NAMES = {"阶梯轴": "平缝机上轴", "关节空心轴": "协作机器人 J2 输出轴"}
DEFAULT_NAMES = {"阶梯轴": "上轴", "关节空心轴": "关节输出轴"}
COLORS = {"pass": "#1b7f3b", "unknown": "#a26b00", "fail": "#b3261e"}
STATUS = {"pass": "通过", "unknown": "待确认", "fail": "不通过"}
RESULT = {"pass": "全部通过", "pass_pending_data": "通过，只剩零件库缺数据的待确认", "stuck": "没有通过，停下交给人（4 轮用完，或 AI 判断改轴解决不了、不再改方案）",
          "needs_input": "条件不齐，先补原话"}


class ConfirmError(ValueError):
    pass


def _kind(kind: str | None) -> str:
    kind = kind or PART_TYPES[0]
    if kind not in PART_TYPES:
        raise ValueError(f"不认识的零件类型：{kind}")
    return kind


def _module(kind: str):
    if _kind(kind) == "关节空心轴":
        from assist import joint_design as M
    else:
        from assist import design as M
    return M


def example_text(kind: str | None = None) -> str:
    """示例原话。Windows 上 git 检出可能把换行变成 \\r\\n，录制是按 \\n 录的：统一成 \\n，否则回放对不上（2026-11-18）"""
    return EXAMPLES[_kind(kind)].read_text(encoding="utf-8").replace("\r\n", "\n")


def example_client(kind: str | None = None):
    """没有密钥时用的录制回放（只对示例原话有效）"""
    from ingest.llm_extract import RecordedClient

    M = _module(kind)
    c = RecordedClient(M.RECORDINGS_DIR)
    c.model = M.DEFAULT_MODEL
    return c


def bearings(library) -> list[dict]:
    return [c for c in library.all() if c.get("category") == "bearing"]


def run(statement: str, client, library, out_dir: str | Path | None = None, *, kind: str | None = None, replay: bool = False,
        progress=None) -> dict:
    """设计并（通过时）生成模型。返回 {"result", "model"（generate 的摘要或 None）, "out_dir", "replay", "kind"}"""
    from assist import kt_record

    kind = _kind(kind)
    M = _module(kind)
    statement = statement.replace("\r\n", "\n")
    model = getattr(client, "model", None) or M.DEFAULT_MODEL
    kt = kt_record.replaying(M.RECORDINGS_DIR / "kt.json") if replay else None   # 回放：用录制时的有限元结果，提示词才对得上
    if kind == "关节空心轴":
        loads_fn = M.loads_replaying(M.RECORDINGS_DIR / M.LOADS_RECORD) if replay else None
        res = M.design(statement, client, bearings(library), library.all("reducer"), library.get, model=model, kt=kt,
                       loads_fn=loads_fn, progress=progress)
    else:
        res = M.design(statement, client, bearings(library), library.get, model=model, kt=kt, progress=progress)
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="wq-ai-design-"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "design-record.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=_finite) + "\n", encoding="utf-8")
    gen = None
    if str(res.get("status", "")).startswith("pass"):
        if progress is not None:
            progress("生成三维模型并测量回读", None, None)
        if kind == "关节空心轴":
            from assist import joint_model

            gen = joint_model.generate(res, out, library.get)
        else:
            from assist import shaft_model

            gen = shaft_model.generate(res, out, library.get)
    return {"result": res, "model": gen, "out_dir": str(out), "replay": replay, "kind": kind}


def _finite(x):
    return None if isinstance(x, float) else str(x)


def segments(result: dict, get) -> list[dict]:
    """采用那一轮方案的建模轴段（直径、长度、圆角；阶梯轴另有轴承）"""
    if result.get("part_type") == "joint_shaft":
        from assist import joint_model

        return joint_model.model_segments(result)[0]
    from assist import shaft_design as SD

    segs, _ = SD.check_proposal(_chosen(result)["proposal"], get)
    return segs


def drawing_extras(result: dict) -> dict:
    """工程图的附加内容：空心轴的内孔直径与花键、螺纹的注"""
    if result.get("part_type") != "joint_shaft":
        return {}
    from assist import joint_model

    _, info = joint_model.model_segments(result)
    return {"bore": info["bore_mm"], "notes": joint_model.notes(info)}


# ---------------------------------------------------------------- 页签（HTML）


def _num(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float)) else str(v)


def _fillet(s: dict) -> str:
    return "" if s.get("r") is None else f"R{s['r']:g}"


def conditions_html(result: dict) -> str:
    rows = [f"<tr><td>{escape(T(q['what']))}</td><td>{escape(_num(q['value']))} {escape(q['unit'])}</td>"
            f"<td>“{escape(q.get('quote') or '')}”</td></tr>" for q in result.get("quotes") or []]
    html = [f"<p><b>{escape(T('设计条件（代码已核对：每个数都在原话里、单位换算到标准单位）'))}</b></p>",
            (f"<table border='1' cellspacing='0' cellpadding='3'><tr><th>{escape(T('条件'))}</th><th>{escape(T('值'))}</th>"
             f"<th>{escape(T('原话引用'))}</th></tr>{''.join(rows)}</table>")]
    for x in result.get("missing") or []:
        html.append(f"<p style='color:{COLORS['fail']}'>{escape(T('缺：'))}{escape(T(x))}</p>")
    for x in result.get("rejected") or []:
        html.append(f"<p style='color:{COLORS['fail']}'>{escape(T('退回：'))}{escape(T(x))}</p>")
    return "".join(html)


def rounds_html(result: dict) -> str:
    html = [f"<p><b>{escape(T('结论：'))}{escape(T(RESULT.get(result.get('status'), str(result.get('status')))))}</b></p>"]
    for k, rd in enumerate(result.get("rounds") or [], 1):
        st = rd.get("overall")
        tag = T("（采用）") if result.get("chosen_round") == k else ""
        mass = T(f"　质量 {rd['mass_kg']:.3f} kg") if isinstance(rd.get("mass_kg"), (int, float)) else ""
        html.append(f"<h3>{escape(T(f'第 {k} 轮') + T('：'))}<span style='color:{COLORS.get(st, '#000')}'>"
                    f"{escape(T(STATUS.get(st, str(st))))}</span>{escape(tag + mass)}</h3>")
        segs = rd.get("segments") or []
        p = rd.get("proposal") if isinstance(rd.get("proposal"), dict) else {}
        if "bore_mm" in p:                                 # 关节空心轴：AI 选的是轴承、内孔、法兰圆角
            dl = T(f"，末端偏移 {rd['delta_mm']:.3f} mm") if isinstance(rd.get("delta_mm"), (int, float)) else ""
            b, bore, r = p.get("bearing", ""), p["bore_mm"], p.get("fillet_mm", 0)
            html.append(f"<p>{escape(T(f'轴承 {b}，内孔 Ø{bore:g}，法兰圆角 R{r:g}') + dl)}</p>")
        if segs:
            cells = "".join(f"<tr><td>{i}</td><td>{escape(T(s.get('role') or s.get('name', '')))}</td><td>Ø{s['d']:g}</td><td>{s['L']:g}</td>"
                            f"<td>{_fillet(s)}</td><td>{escape(s.get('bearing', ''))}</td></tr>"
                            for i, s in enumerate(segs, 1))
            html.append(f"<table border='1' cellspacing='0' cellpadding='3'><tr><th>#</th><th>{escape(T('用途'))}</th>"
                        f"<th>{escape(T('直径'))}</th><th>{escape(T('长度'))}</th><th>{escape(T('圆角'))}</th>"
                        f"<th>{escape(T('轴承'))}</th></tr>{cells}</table>")
        reason = (rd.get("proposal") or {}).get("reason")
        if reason:
            html.append(f"<p><i>{escape(T('AI 的说明：'))}</i>{escape(reason)}</p>")
        for it in rd.get("items") or []:
            c = COLORS.get(it["status"], "#000")
            v = T("：") + _num(it["value"]) if "value" in it else ""
            lim = T(f"（要求 {_num(it['limit'])}）") if it.get("limit") is not None else ""
            note = T("；") + T(it["note"]) if it.get("note") else ""
            html.append(f"<div style='color:{c}'>[{escape(T(STATUS.get(it['status'], it['status'])))}] "
                        f"{escape(T(it['item']))}{escape(v)}{escape(lim)}{escape(note)}</div>")
    return "".join(html)


def questions_html(result: dict) -> str:
    html = [f"<p><b>{escape(T('AI 提的问题（交给工程师回答，不挡设计）'))}</b></p><ul>"]
    html += [f"<li>{escape(q)}</li>" for q in result.get("questions") or []] or [f"<li>{escape(T('没有'))}</li>"]
    html.append(f"</ul><p><b>{escape(T('本次设计的假设'))}</b></p><ul>")
    html += [f"<li>{escape(T(a))}</li>" for a in result.get("assumptions") or []]
    html.append("</ul>")
    return "".join(html)


def model_line(gen: dict | None) -> str:
    if gen is None:
        return T("设计没有通过，不生成模型")
    if gen.get("readback") != "pass":
        return T("模型回读与设计不一致，不交付：") + "；".join(gen.get("problems") or [])
    return T(f"模型回读：{gen.get('readback_rows')} 段逐段一致，质量 {gen.get('mass_kg')} kg")


# ---------------------------------------------------------------- 确认入企业库


def confirm(enterprise_lib, run_out: dict, *, drawing_no: str, name: str, enterprise: str, actor: str) -> dict:
    """人确认后入企业库：登记模型与设计记录两份资料，测量写成自制件组件。返回写入的组件"""
    from assist import measure

    drawing_no, name, enterprise, actor = (x.strip() for x in (drawing_no, name, enterprise, actor))
    if not drawing_no or not actor or not enterprise:
        raise ConfirmError("图号、企业、确认人都要填")
    gen = run_out.get("model")
    if not gen or gen.get("readback") != "pass":
        raise ConfirmError("模型没有生成或回读不一致，不能入库")
    if run_out.get("replay"):
        raise ConfirmError("这是录制回放的示例，不入企业库")
    out = Path(run_out["out_dir"])
    material = run_out["result"]["conditions"].get("material")
    step_doc = enterprise_lib.register_document(out / "shaft.step", f"{drawing_no} {name} 三维模型（AI 设计）", actor)
    rec_doc = enterprise_lib.register_document(out / "design-record.json", f"{drawing_no} {name} 设计记录（条件、各轮方案与校核）", actor)
    meas = measure.measure(out / "shaft.step", material=material)
    kind = "关节空心轴" if run_out["result"].get("part_type") == "joint_shaft" else "阶梯轴"
    comp = measure.to_component(meas, enterprise=enterprise, drawing_no=drawing_no, doc=step_doc["id"], part_kind="shaft",
                                kind_doc_note=f"零件类型：AI 设计{kind}，{actor} 确认")
    comp["note"] += f"；名称：{name}；AI 设计、代码校核，设计记录见企业资料 {rec_doc['id']}"
    if enterprise_lib.get(comp["id"]) is not None:
        raise ConfirmError(f"企业库里已有 {comp['id']}，换一个图号")
    enterprise_lib.save_component(comp, actor, f"AI 设计零件，人确认入库（设计记录 {rec_doc['id']}）")
    return comp


def _chosen(result: dict) -> dict:
    from assist.design import chosen

    return chosen(result)
