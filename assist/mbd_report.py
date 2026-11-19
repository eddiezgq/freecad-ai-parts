"""多体动力学计算报告（ADR-0097 D8b，补充二十二）：事实清单 → Markdown 报告 + 曲线图 + 出处账；AI 只写解释，数字用占位符。

和有限元报告（assist/fea_report.py）同一规矩：报告里每个数字都由程序从结果文件取，旁边写一份出处账（`*.ledger.json`），
记着每个数来自结果的哪个 JSON 指针、做了什么运算（取值、最大绝对值、最大模长、均方根）；测试把报告里的数字逐个对回结果。
AI 的段落里出现数字、写“合格 / 满足要求 / 安全”，或用了不存在的占位符，那一段就退回不用。报告页眉写“草稿，须工程师审核”。
"""

from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

PROMPT_VERSION = "mbd-explain/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
TOOL_NAME = "write_mbd_explanation"
DRAFT_MARK = "草稿，须工程师审核"
VERDICT = {"pass": "通过", "fail": "不通过", "unknown": "不判"}
ANALYSIS_ZH = {"kinematic": "运动学", "dynamic": "动力学", "static": "静平衡", "static_then_dynamic": "先静平衡再动力学",
               "linear": "线性化", "static_then_linear": "先静平衡再线性化"}
FORBIDDEN = ("合格", "满足要求", "安全", "可以放心", "没有问题")
SYSTEM_PROMPT = (
    "你是机械工程师，给一份多体动力学计算报告写解释段落。只能用给你的事实，数字一律写成占位符 {{键}}，"
    "不能自己写数字；不判定合格与否（合格要工程师对照要求判），核查没通过的要如实说。每段两三句话。")


def fmt(v: float) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "—"
    a = abs(v)
    if a != 0 and (a >= 1e5 or a < 1e-3):
        return f"{v:.4g}"
    return f"{v:.4g}"


def _get(doc, ptr):
    cur = doc
    for p in ptr.split("/")[1:]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    return cur


def apply_op(doc, ptr, op):
    """出处账里的运算：value、max_abs、max_norm、rms_abs、min、max"""
    x = _get(doc, ptr)
    if op == "value":
        return float(x)
    a = np.asarray([v for v in x if v is not None], float)
    if op == "max_abs":
        return float(np.max(np.abs(a)))
    if op == "max_norm":
        return float(np.max(np.linalg.norm(a, axis=1)))
    if op == "max":
        return float(np.max(a))
    if op == "min":
        return float(np.min(a))
    raise ValueError(op)


def facts(data: dict) -> dict[str, dict]:
    """键 → {label, value, unit, ptr, op}"""
    F: dict[str, dict] = {}

    def add(key, label, ptr, op, unit=""):
        try:
            v = apply_op(data, ptr, op)
        except (KeyError, IndexError, ValueError, TypeError):
            return
        if math.isfinite(v):
            F[key] = {"label": label, "value": v, "unit": unit, "ptr": ptr, "op": op}

    add("dof", "自由度", "/dof", "value")
    if data.get("times_s"):
        add("t_end", "仿真时长", "/times_s", "max", "s")
    for k, v in enumerate(data.get("verification", [])):
        if isinstance(v.get("value"), (int, float)):
            add(f"check_{v['key']}", v["name"], f"/verification/{k}/value", "value")
    for mid, m in (data.get("motions") or {}).items():
        add(f"drive_{mid}_peak", f"驱动 {mid} 峰值", f"/motions/{mid}/effort", "max_abs", m.get("unit", ""))
    for jid in (data.get("joints") or {}):
        add(f"joint_{jid}_force", f"运动副 {jid} 最大反力", f"/joints/{jid}/force_n", "max_norm", "N")
        add(f"joint_{jid}_torque", f"运动副 {jid} 最大反力矩", f"/joints/{jid}/torque_n_m", "max_norm", "N·m")
    for aid in (data.get("actuators") or {}):
        add(f"act_{aid}_peak", f"执行器 {aid} 峰值", f"/actuators/{aid}", "max_abs")
    for cid in (data.get("contacts") or {}):
        add(f"contact_{cid}_peak", f"接触 {cid} 最大法向力", f"/contacts/{cid}/normal_force_n", "max_abs", "N")
    for bid, f in (data.get("flex") or {}).items():
        if f.get("type") == "nonlinear_beam":                 # 大变形梁（ADR-0101）：截面内力和应力
            if f.get("max_stress_mpa"):
                add(f"beam_{bid}_stress", f"大变形梁 {bid} 最大正应力", f"/flex/{bid}/max_stress_mpa", "max", "MPa")
            add(f"beam_{bid}_axial", f"大变形梁 {bid} 最大轴力", f"/flex/{bid}/axial_n", "max_abs", "N")
            add(f"beam_{bid}_my", f"大变形梁 {bid} 最大弯矩（y 轴）", f"/flex/{bid}/moment_y_n_m", "max_abs", "N·m")
            add(f"beam_{bid}_mz", f"大变形梁 {bid} 最大弯矩（z 轴）", f"/flex/{bid}/moment_z_n_m", "max_abs", "N·m")
            continue
        if f.get("stress"):
            add(f"flex_{bid}_stress", f"柔性构件 {bid} 最大 von Mises 应力", f"/flex/{bid}/stress/peak_mpa", "value", "MPa")
        add(f"flex_{bid}_elastic", f"柔性构件 {bid} 最大弹性能", f"/flex/{bid}/elastic_energy_j", "max", "J")
    lin = data.get("linear")
    if lin:
        nz = [k for k, m in enumerate(lin["modes"]) if m["frequency_hz"] > 1e-6]
        for n, k in enumerate(nz[:6], 1):
            add(f"mode{n}_hz", f"第 {n} 阶固有频率", f"/linear/modes/{k}/frequency_hz", "value", "Hz")
            add(f"mode{n}_zeta", f"第 {n} 阶阻尼比", f"/linear/modes/{k}/damping_ratio", "value")
    return F


def build_request(data: dict, F: dict, *, model: str = DEFAULT_MODEL) -> dict:
    lines = [f"- {{{{{k}}}}}：{v['label']} = {fmt(v['value'])} {v['unit']}" for k, v in F.items()]
    checks = [f"- {v['name']}：{VERDICT.get(v['status'], v['status'])}" for v in data.get("verification", [])]
    user = (f"模型：{data.get('model', '')}；分析：{ANALYSIS_ZH.get(data.get('analysis'), data.get('analysis'))}\n"
            f"事实（写解释时数字只能用左边的占位符）：\n" + "\n".join(lines) + "\n核查：\n" + "\n".join(checks))
    return {"model": model, "prompt_version": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": user,
            "tool": {"name": TOOL_NAME, "description": "提交解释段落",
                     "input_schema": {"type": "object", "properties": {"paragraphs": {"type": "array", "items": {"type": "string"}}},
                                      "required": ["paragraphs"]}}}


def check_paragraph(text: str, F: dict) -> str | None:
    """不合规返回原因，合规返回 None"""
    for k in re.findall(r"\{\{([^}]+)\}\}", text):
        if k not in F:
            return f"用了不存在的占位符 {k}"
    bare = re.sub(r"\{\{[^}]+\}\}", "", text)
    if re.search(r"\d", bare):
        return "段落里直接写了数字"
    for w in FORBIDDEN:
        if w in bare:
            return f"段落里判定了“{w}”"
    return None


def explain(data: dict, F: dict, client=None, *, model: str = DEFAULT_MODEL) -> dict:
    if client is None:
        return {"paragraphs": [], "rejected": [], "by": "没有用 AI"}
    resp = client.complete(build_request(data, F, model=model))
    paras = (resp.get("tool_input") or {}).get("paragraphs") or []
    ok, bad = [], []
    for p in paras:
        why = check_paragraph(str(p), F)
        (bad.append({"text": p, "why": why}) if why else ok.append(str(p)))
    return {"paragraphs": ok, "rejected": bad, "by": f"AI {resp.get('model', '')}（提示词 {PROMPT_VERSION}，响应 {resp.get('id', '')}）"}


class _Ledger:
    def __init__(self):
        self.items = []

    def num(self, key, F):
        f = F[key]
        s = fmt(f["value"])
        self.items.append({"text": s, "key": key, "ptr": f["ptr"], "op": f["op"], "value": f["value"]})
        return s


def _plot(data, out: Path, name: str, title: str, series: dict, unit: str) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    t = data["times_s"]
    fig, ax = plt.subplots(figsize=(6, 2.6), dpi=120)
    for lab, ys in series.items():
        ax.plot(t, ys, label=lab)
    ax.set_xlabel("t / s")
    ax.set_ylabel(unit)
    if title:
        ax.set_title(title)
    ax.grid(alpha=0.3)
    if len(series) > 1:
        ax.legend(fontsize=7)
    fig.tight_layout()
    p = out / f"{name}.png"
    fig.savefig(p)
    plt.close(fig)
    return p.name


def build(data: dict, out: str | Path, *, client=None, result_file: str = "result.json", title: str | None = None) -> dict:
    """写 out/report.md、曲线图、out/report.ledger.json；result_file 是结果文件名（出处账里引用）"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    F = facts(data)
    L = _Ledger()
    ex = explain(data, F, client)
    lines = [f"# {title or data.get('model', '多体动力学')} 计算报告", "",
             f"> {DRAFT_MARK}。本报告里的每个数字都由程序从结果文件 `{result_file}` 取得，出处见 `report.ledger.json`。", ""]
    lines += ["## 模型与分析", "", f"- 分析类型：{ANALYSIS_ZH.get(data.get('analysis'), data.get('analysis'))}"]
    if "dof" in F:
        lines.append(f"- 自由度：{L.num('dof', F)}")
    if "t_end" in F:
        lines.append(f"- 仿真时长：{L.num('t_end', F)} s")
    if data.get("redundant_constraints"):
        lines.append(f"- 删去的冗余约束：{'、'.join(data['redundant_constraints'])}")
    lines += ["", "## 核查结论", "", "| 核查 | 结论 | 数值 |", "| --- | --- | --- |"]
    for v in data.get("verification", []):
        key = f"check_{v['key']}"
        val = L.num(key, F) if key in F else "—"
        lines.append(f"| {v['name']} | {VERDICT.get(v['status'], v['status'])} | {val} |")
    keys = [k for k in F if k not in ("dof", "t_end") and not k.startswith("check_")]
    if keys:
        lines += ["", "## 主要结果", "", "| 项目 | 数值 | 单位 |", "| --- | --- | --- |"]
        lines += [f"| {F[k]['label']} | {L.num(k, F)} | {F[k]['unit']} |" for k in keys]
    figs = []
    if data.get("motions"):
        figs.append(_plot(data, out, "drives", "drive effort", {k: m["effort"] for k, m in data["motions"].items()},
                          "/".join(sorted({m["unit"] for m in data["motions"].values()}))))
    if data.get("joints") and len(data["times_s"]) > 1:
        figs.append(_plot(data, out, "reactions", "joint reaction |F|",
                          {k: np.linalg.norm(np.asarray(j["force_n"]), axis=1) for k, j in data["joints"].items()}, "N"))
    figs = [f for f in figs if f]
    if figs:
        lines += ["", "## 曲线", ""] + [f"![{f}]({f})" for f in figs]
    if ex["paragraphs"]:
        lines += ["", "## 解释（AI 起草，须审核）", ""]
        for p in ex["paragraphs"]:
            lines += [re.sub(r"\{\{([^}]+)\}\}", lambda m: f"{L.num(m.group(1), F)} {F[m.group(1)]['unit']}".strip(), p), ""]
    if data.get("limitations"):
        lines += ["", "## 局限", ""] + [f"- {x}" for x in data["limitations"]]
    lines += ["", "## 审核", "", "| 编制 | 审核 | 批准 |", "| --- | --- | --- |", "|  |  |  |", ""]
    md = "\n".join(lines)
    (out / "report.md").write_text(md, encoding="utf-8")
    labels = sorted({str(data.get("model", ""))} | set(data.get("redundant_constraints") or [])
                    | {v["name"] for v in data.get("verification", [])}
                    | {k for sec in ("motions", "joints", "actuators", "contacts", "flex", "measures") for k in (data.get(sec) or {})}
                    | ({title} if title else set()) - {""})
    ledger = {"result_file": result_file, "labels": labels, "generated": datetime.now(UTC).isoformat(timespec="seconds"),
              "explanation": {"by": ex["by"], "rejected": ex["rejected"]}, "numbers": L.items}
    (out / "report.ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"markdown": out / "report.md", "ledger": out / "report.ledger.json", "figures": figs, "explanation": ex}


# ---------------------------------------------------------------- Word / PDF 正式报告（ADR-0102 第 1 步）
JOINT_ZH = {"fixed": "固定", "revolute": "转动", "translational": "移动", "cylindrical": "圆柱", "spherical": "球",
            "universal": "万向"}
FLEX_ZH = {"beam": "模态梁", "modal": "实体模态", "nonlinear_beam": "大变形梁"}
OP_ZH = {"value": "取值", "max_abs": "最大绝对值", "max_norm": "最大模长", "max": "最大", "min": "最小"}


class _DocLedger:
    """有限元报告的出处账（assist.fea_report.Ledger）加一种“运算值”：最大绝对值、最大模长……，账上记运算名"""

    def __init__(self, sources, lang):
        from assist.fea_report import Ledger

        self.L = Ledger(sources, lang)

    def __getattr__(self, k):
        return getattr(self.L, k)

    def op(self, src, ptr, op, unit=""):
        v = apply_op(self.L.sources[src], ptr, op)
        if op == "value":
            return self.L.num(src, ptr, unit)
        s = fmt_num(v)
        self.L.entries.append({"text": s, "source": src, "pointer": ptr, "kind": "op", "op": op})
        return s + (f" {unit}" if unit else "")


def fmt_num(v):
    from assist.fea_report import fmt as _f

    return _f(float(v))


def _strip_timing(data):
    return {k: v for k, v in data.items() if k not in ("solver",)}


def checklist(model: dict, data: dict) -> list[dict]:
    """审核清单：程序能判的给结论（来自核查），其余“须人工判断”"""
    rows = []
    for v in data.get("verification", []):
        rows.append({"item": v["name"], "verdict": VERDICT.get(v["status"], v["status"]), "basis": "程序核查"})
    rows += [
        {"item": "构件质量、质心、惯量与实物一致（来自 CAD 或材料）", "verdict": "须人工判断", "basis": "模型"},
        {"item": "运动副的类型、位置、轴向与实际机构一致", "verdict": "须人工判断", "basis": "模型"},
        {"item": "驱动、载荷与实际工况一致（时间历程、大小、方向）", "verdict": "须人工判断", "basis": "模型"},
        {"item": "柔性件的取法（模态 / 实体 / 大变形梁）适合本问题", "verdict": "须人工判断", "basis": "模型"},
        {"item": "AI 解释的文字与结果一致、没有超出结果的推断", "verdict": "须人工判断", "basis": "报告"},
    ]
    return rows


def build_docx(model: dict, data: dict, out, *, number: str | None = None, revision: str = "草稿", reason: str = "首次出稿",
               explanation: dict | None = None, today=None, lang: str = "zh", company: str | None = None,
               figures_dir=None) -> dict:
    """多体动力学正式报告（Word，旁边写出处账 *.ledger.json 与改版记录 *.record.json）。
    数字一律经出处账从模型、结果、改版记录里取；AI 只写解释，数字用 {{键}} 占位（explain() 的输出）。"""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt

    from assist import i18n
    from assist.fea_report import code_version, fingerprint

    if lang not in i18n.LANGS:
        raise ValueError(f"报告语言只能是 {i18n.LANGS}")
    if data.get("model") != model.get("name"):
        raise ValueError("结果不是用这个模型算的（模型名不一致）")

    def F(x):
        return i18n.final(x, lang)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    today = today or datetime.now(UTC).date()
    rec_path = out.with_suffix(".record.json")
    record = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.is_file() else {"history": []}
    record["number"] = number or record.get("number") or "未编号（由质量体系分配）"
    files = {"model": fingerprint(model), "result": fingerprint(_strip_timing(data))}
    entry = {"revision": revision, "date": today.isoformat(), "reason": reason, "result_fingerprint": files["result"],
             "model_fingerprint": files["model"]}
    record["history"] = [h for h in record["history"] if h["revision"] != revision] + [entry]
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    env = {"code": code_version(), "integrator": str((data.get("solver") or {}).get("integrator", "—")),
           "company": company or ""}
    L = _DocLedger({"model": model, "result": data, "record": record, "files": files, "env": env,
                 "explain": explanation or {}}, lang)
    Fx = facts(data)

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "Noto Sans CJK SC"
    st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK SC")
    last = len(record["history"]) - 1
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
        hp = s.header.paragraphs[0]
        head = (L.txt("env", "/company") + "　") if company else ""
        hp.text = head + F(f"{DRAFT_MARK}　报告编号 {L.txt('record', '/number', True)}　版次 {L.txt('record', f'/history/{last}/revision', True)}")
        hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    def h(text, lvl=1):
        o = F(text)
        if lang == "en" and lvl == 1 and re.match(r"^\d+\. ", o):
            L.label(o)
        doc.add_heading(o, level=lvl)

    def p(text, style=None):
        return doc.add_paragraph(F(text), style=style) if style else doc.add_paragraph(F(text))

    def table(head, rows):
        t = doc.add_table(rows=1, cols=len(head))
        t.style = "Table Grid"
        for c, x in zip(t.rows[0].cells, head, strict=True):
            c.text = F(x)
            for r in c.paragraphs[0].runs:
                r.bold = True
        for row in rows:
            for c, x in zip(t.add_row().cells, row, strict=True):
                c.text = F(x)
        return t

    an = model["analysis"]
    doc.add_heading(F(f"多体动力学计算报告：{L.txt('model', '/name')}"), 0)
    table(["项目", "内容"], [
        ["报告编号", L.txt("record", "/number", True)], ["版次", L.txt("record", f"/history/{last}/revision", True)],
        ["出稿日期", L.txt("record", f"/history/{last}/date")], ["状态", DRAFT_MARK],
        ["编制（签字 / 日期）", ""], ["审核（签字 / 日期）", ""], ["批准（签字 / 日期）", ""]])
    p("编制、审核、批准三栏由人签字，程序不代签。")

    # 一、结论摘要
    h("一、结论摘要")
    bad = [v for v in data.get("verification", []) if v["status"] == "fail"]
    p("程序核查：" + ("全部通过或不判。" if not bad else "有不通过的项（见第三节），结果须谨慎使用。"))
    p("本报告不作合格判定，由审核人按审核清单判断。")
    keys = [k for k in Fx if not k.startswith("check_") and k not in ("dof", "t_end")]
    if keys:
        table(["项目", "数值"], [[Fx[k]["label"], L.op("result", Fx[k]["ptr"], Fx[k]["op"], Fx[k]["unit"])] for k in keys])

    # 二、模型
    h("二、模型")
    rows = [[ANALYSIS_ZH.get(an["type"], an["type"]), L.num("model", "/analysis/end_time_s", "s") if "end_time_s" in an else "—",
             L.num("model", "/analysis/output_steps") if "output_steps" in an else "—", L.txt("env", "/integrator")]]
    table(["分析类型", "时长", "输出点数", "积分器"], rows)
    if "dof" in data:
        p(f"自由度 {L.num('result', '/dof')}。")
    h("构件", 2)
    bidx = {b["id"]: i for i, b in enumerate(model["bodies"])}

    def bname(i):
        """构件名：模型里写了显示名（如装配体零件的标签）时写“显示名（id）”"""
        b = model["bodies"][i]
        if b.get("name") and b["name"] != b["id"]:
            lp, rp = ("（", "）") if lang == "zh" else (" (", ")")
            return f"{L.txt('model', f'/bodies/{i}/name')}{lp}{L.txt('model', f'/bodies/{i}/id')}{rp}"
        return L.txt("model", f"/bodies/{i}/id")

    def jbody(i, side):
        bid = model["joints"][i][side]
        return L.txt("model", f"/bodies/{bidx[bid]}/name") if bid in bidx and model["bodies"][bidx[bid]].get("name") \
            else L.txt("model", f"/joints/{i}/{side}")

    brows = []
    for i, b in enumerate(model["bodies"]):
        if b.get("flex"):
            brows.append([bname(i), F(FLEX_ZH.get(b["flex"]["type"], b["flex"]["type"])), "—", "—"])
        else:
            brows.append([bname(i), F("刚体"), L.num("model", f"/bodies/{i}/mass_kg", "kg"),
                          L.vec("model", f"/bodies/{i}/cm_mm", "mm")])
    table(["名称", "类型", "质量", "质心"], brows)
    if model.get("joints"):
        h("运动副", 2)
        table(["名称", "类型", "构件 i", "构件 j", "运动副中心"], [
            [L.txt("model", f"/joints/{i}/id"), F(JOINT_ZH.get(j["type"], j["type"])), jbody(i, "body_i"),
             jbody(i, "body_j"), L.vec("model", f"/joints/{i}/point_mm", "mm")]
            for i, j in enumerate(model["joints"])])
    if data.get("redundant_constraints"):
        names = "、".join(L.txt("result", f"/redundant_constraints/{k}") for k in range(len(data["redundant_constraints"])))
        p(f"删去的冗余约束（反力里这些方向的分量不唯一）：{names}")

    # 三、可信度核查
    h("三、可信度核查")
    table(["核查项", "结论", "数值"], [
        [L.txt("result", f"/verification/{k}/name", True), VERDICT.get(v["status"], v["status"]),
         L.num("result", f"/verification/{k}/value") if isinstance(v.get("value"), (int, float)) else "—"]
        for k, v in enumerate(data.get("verification", []))])

    # 四、结果
    h("四、结果")
    tmp = Path(figures_dir) if figures_dir else Path(tempfile.mkdtemp(prefix="mbd-report-"))
    tmp.mkdir(parents=True, exist_ok=True)
    figs = []
    if data.get("motions"):
        figs.append((_plot(data, tmp, "drives", "drive effort", {k: m["effort"] for k, m in data["motions"].items()},
                           "/".join(sorted({m["unit"] for m in data["motions"].values()}))), "驱动力 / 力矩随时间"))
    if data.get("joints") and len(data["times_s"]) > 1:
        figs.append((_plot(data, tmp, "reactions", "",
                           {k: np.linalg.norm(np.asarray(j["force_n"]), axis=1) for k, j in data["joints"].items()}, "N"),
                     "运动副反力大小随时间"))
    for mid, ms in (data.get("measures") or {}).items():
        if isinstance(ms, dict) and ms.get("values") and len(ms["values"]) == len(data["times_s"]):
            figs.append((_plot(data, tmp, f"measure-{mid}", "", {mid: ms["values"]}, ms.get("unit", "")), f"测量量 {mid} 随时间"))
    if data.get("actuators"):
        figs.append((_plot(data, tmp, "actuators", "", dict(data["actuators"].items()), ""), "执行器输出随时间"))
    for f, cap in figs:
        if f:
            doc.add_picture(str(tmp / f), width=Cm(15))
            p(f"图：{cap}（按结果文件画）".replace(cap, cap if not re.search(r"[0-9]", cap) else L.label(cap)))
    lin = data.get("linear")
    if lin:
        h("固有频率", 2)
        nz = [k for k, m in enumerate(lin["modes"]) if m["frequency_hz"] > 1e-6]
        table(["阶次", "频率（Hz）", "阻尼比"], [
            [L.label(str(n + 1)), L.num("result", f"/linear/modes/{k}/frequency_hz"),
             L.num("result", f"/linear/modes/{k}/damping_ratio") if lin["modes"][k].get("damping_ratio") is not None else "—"]
            for n, k in enumerate(nz)])
    if not figures_dir:
        shutil.rmtree(tmp, ignore_errors=True)

    # 五、解释（AI）
    h("五、解释与说明（AI 起草，须工程师判断）")
    if not explanation or not explanation.get("paragraphs"):
        p("没有生成 AI 解释（本次出稿没有调用 AI，或 AI 的段落全部不合规被退回）。")
    else:
        p("下面的文字由 AI 起草；文字里的数值由程序从结果文件填入，AI 不判定合格。")
        for t in explanation["paragraphs"]:
            p(re.sub(r"\{\{([^}]+)\}\}", lambda m_: L.op("result", Fx[m_.group(1)]["ptr"], Fx[m_.group(1)]["op"],
                                                          Fx[m_.group(1)]["unit"]), t))
    if explanation and explanation.get("rejected"):
        p(f"退回不用的 AI 段落 {L.label(str(len(explanation['rejected'])))} 段（原文与原因记在出处账）。")

    # 六、局限
    h("六、局限")
    lims = data.get("limitations") or []
    for k in range(len(lims)):
        p(L.txt("result", f"/limitations/{k}", True), "List Bullet")
    p("多体模型的结果取决于模型对实物的简化（构件、运动副、力元、柔性件的取法），这些由审核人对照实物判断。")

    # 七、审核清单
    h("七、审核清单")
    p("程序给出能确定核查的项的结论，其余标“须人工判断”；审核人逐项勾选并签字。")
    table(["项目", "程序结论", "依据", "审核人勾选", "备注"],
          [[r["item"] if not re.search(r"[0-9]", r["item"]) else L.txt("result", f"/verification/{k}/name", True),
            r["verdict"], r["basis"], "☐", ""] for k, r in enumerate(checklist(model, data))])

    # 八、可追溯信息
    h("八、可追溯信息")
    table(["项目", "内容"], [
        ["模型内容指纹（SHA-256）", L.txt("files", "/model")],
        ["结果指纹（SHA-256，同一模型重算应相同）", L.txt("files", "/result")],
        ["积分器", L.txt("env", "/integrator")],
        ["本项目代码版本（git 提交）", L.txt("env", "/code", True)]])
    h("改版记录", 2)
    table(["版次", "日期", "原因", "结果指纹"], [
        [L.txt("record", f"/history/{k}/revision", True), L.txt("record", f"/history/{k}/date"),
         L.txt("record", f"/history/{k}/reason", True), L.txt("record", f"/history/{k}/result_fingerprint")]
        for k in range(len(record["history"]))])
    if explanation and explanation.get("by"):
        p(f"解释由 {L.txt('explain', '/by')} 起草。")

    doc.save(out)
    ledger = {"report": out.name, "lang": lang, "files": files, "entries": L.entries, "labels": L.labels,
              "explanation": {"by": (explanation or {}).get("by"), "rejected": (explanation or {}).get("rejected", [])}}
    led_path = out.with_suffix(".ledger.json")
    led_path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    pdf = None
    try:
        from assist.fea_report import to_pdf

        pdf = to_pdf(out)
    except Exception:  # noqa: BLE001 — 没有 LibreOffice 或转换失败时只给 Word
        pdf = None
    return {"docx": out, "pdf": pdf, "ledger": led_path, "record": rec_path}
