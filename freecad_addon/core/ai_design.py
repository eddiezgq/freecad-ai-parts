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
PART_TYPES = ("阶梯轴",)
COLORS = {"pass": "#1b7f3b", "unknown": "#a26b00", "fail": "#b3261e"}
STATUS = {"pass": "通过", "unknown": "待确认", "fail": "不通过"}
RESULT = {"pass": "全部通过", "pass_pending_data": "通过，只剩零件库缺数据的待确认", "stuck": "4 轮仍没通过，停下交给人",
          "needs_input": "条件不齐，先补原话"}


class ConfirmError(ValueError):
    pass


def example_text() -> str:
    """示例原话。Windows 上 git 检出可能把换行变成 \\r\\n，录制是按 \\n 录的：统一成 \\n，否则回放对不上（2026-11-18）"""
    return EXAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")


def example_client():
    """没有密钥时用的录制回放（只对示例原话有效）"""
    from assist import design as D
    from ingest.llm_extract import RecordedClient

    c = RecordedClient(D.RECORDINGS_DIR)
    c.model = D.DEFAULT_MODEL
    return c


def bearings(library) -> list[dict]:
    return [c for c in library.all() if c.get("category") == "bearing"]


def run(statement: str, client, library, out_dir: str | Path | None = None, *, replay: bool = False,
        progress=None) -> dict:
    """设计并（通过时）生成模型。返回 {"result", "model"（generate 的摘要或 None）, "out_dir", "replay"}"""
    from assist import design as D
    from assist import shaft_model

    statement = statement.replace("\r\n", "\n")
    model = getattr(client, "model", None) or D.DEFAULT_MODEL
    res = D.design(statement, client, bearings(library), library.get, model=model, progress=progress)
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="wq-ai-design-"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "design-record.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=_finite) + "\n", encoding="utf-8")
    gen = None
    if str(res.get("status", "")).startswith("pass"):
        if progress is not None:
            progress("生成三维模型并测量回读", None, None)
        gen = shaft_model.generate(res, out, library.get)
    return {"result": res, "model": gen, "out_dir": str(out), "replay": replay}


def _finite(x):
    return None if isinstance(x, float) else str(x)


def segments(result: dict, get) -> list[dict]:
    """最后一轮方案经代码补齐后的轴段（直径、长度、圆角、轴承）"""
    from assist import shaft_design as SD

    segs, _ = SD.check_proposal(result["rounds"][-1]["proposal"], get)
    return segs


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
        html.append(f"<h3>{escape(T(f'第 {k} 轮') + T('：'))}<span style='color:{COLORS.get(st, '#000')}'>"
                    f"{escape(T(STATUS.get(st, str(st))))}</span></h3>")
        segs = rd.get("segments") or []
        if segs:
            cells = "".join(f"<tr><td>{i}</td><td>{escape(T(s.get('role', '')))}</td><td>Ø{s['d']:g}</td><td>{s['L']:g}</td>"
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
    comp = measure.to_component(meas, enterprise=enterprise, drawing_no=drawing_no, doc=step_doc["id"], part_kind="shaft",
                                kind_doc_note=f"零件类型：AI 设计阶梯轴，{actor} 确认")
    comp["note"] += f"；名称：{name}；AI 设计、代码校核，设计记录见企业资料 {rec_doc['id']}"
    if enterprise_lib.get(comp["id"]) is not None:
        raise ConfirmError(f"企业库里已有 {comp['id']}，换一个图号")
    enterprise_lib.save_component(comp, actor, f"AI 设计零件，人确认入库（设计记录 {rec_doc['id']}）")
    return comp
