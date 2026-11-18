"""多体动力学计算报告（ADR-0097 D8b，补充二十二）：事实清单 → Markdown 报告 + 曲线图 + 出处账；AI 只写解释，数字用占位符。

和有限元报告（assist/fea_report.py）同一规矩：报告里每个数字都由程序从结果文件取，旁边写一份出处账（`*.ledger.json`），
记着每个数来自结果的哪个 JSON 指针、做了什么运算（取值、最大绝对值、最大模长、均方根）；测试把报告里的数字逐个对回结果。
AI 的段落里出现数字、写“合格 / 满足要求 / 安全”，或用了不存在的占位符，那一段就退回不用。报告页眉写“草稿，须工程师审核”。
"""

from __future__ import annotations

import json
import math
import re
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
