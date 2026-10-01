"""方案解释（issue #54，ADR-0030）：由校验结果生成中英文说明。确定性模板，不调用 LLM。

- 中文：结论、每个非 pass 项的原因（取自校验判定）、涉及端口、测量值与限值、余量
- 英文：同样的结构；原因用各项校验的英文描述加上数值与端口。逐字的英文措辞由 M4a 的 LLM 润色
"""

from __future__ import annotations

CHECK_NAMES = {
    "C1": ("端口兼容", "Port compatibility"),
    "C2": ("圆柱配合", "Shaft–bore fit"),
    "C3": ("法兰配合", "Flange fit"),
    "C4": ("连续扭矩", "Continuous torque"),
    "C5": ("峰值扭矩", "Peak torque"),
    "C6": ("减速器过载保护", "Reducer overload protection"),
    "C7": ("转速", "Speed"),
    "C8": ("惯量比", "Inertia ratio"),
    "C9": ("电气匹配", "Electrical match"),
    "C10": ("信号匹配", "Signal match"),
    "C11": ("轴承与包络", "Bearing and envelope"),
}
STATUS = {
    "pass": ("通过", "pass"),
    "warn": ("告警", "warning"),
    "fail": ("不通过", "fail"),
    "unknown": ("待确认（数据缺失）", "unknown (missing data)"),
    "not_applicable": ("不适用", "not applicable"),
}
OVERALL = {
    "pass": ("可用：全部适用项通过。", "Usable: all applicable checks pass."),
    "warn": ("有条件可用：没有不通过项，但以下告警须在方案中处理。",
             "Usable with conditions: no failures, but the warnings below must be addressed."),
    "fail": ("不可用：有不通过的校验项。", "Not usable: at least one check fails."),
    "unknown": ("待确认：有数据缺失，不能判定为可用。",
                "To be confirmed: data is missing, so the design cannot be confirmed as usable."),
}
# 英文原因：各项校验在非 pass 时的一般描述（具体数值与端口另附）
EN_REASON = {
    "C1": "port type, direction or motion does not match",
    "C2": "shaft and bore do not fit (diameter, tolerance, feature/clamping or key)",
    "C3": "flanges do not match (bolt circle, hole count, clearance holes or pilot)",
    "C4": "continuous torque exceeds the rating",
    "C5": "peak torque exceeds the rating",
    "C6": "motor peak torque through the reducer exceeds its momentary limit; set a torque limit in the drive",
    "C7": "required speed exceeds a limit",
    "C8": "load-to-motor inertia ratio exceeds the threshold",
    "C9": "drive and motor do not match electrically",
    "C10": "encoder or fieldbus protocol does not match",
    "C11": "bearing speed or envelope limit is exceeded",
}
UNITS = {"N*m": "N·m", "rpm": "rpm", "mm": "mm", "A": "A", "1": ""}


def _fmt(x: float) -> str:
    return f"{x:.4g}"


def _numbers(f: dict) -> str:
    if f.get("measured") is None:
        return ""
    unit = UNITS.get(f.get("unit") or "", f.get("unit") or "")
    tail = f" {unit}" if unit else ""
    text = f"measured {_fmt(f['measured'])}{tail} vs limit {_fmt(f['limit'])}{tail}"
    if f.get("margin_ratio") is not None:
        text += f", margin {f['margin_ratio'] * 100:.1f}%"
    return text


def _findings(check: dict) -> list[dict]:
    return check.get("findings") or [check]


def explain(report: dict, lang: str = "zh") -> str:
    """一个方案的说明。"""
    if lang not in ("zh", "en"):
        raise ValueError("lang 须为 zh 或 en")
    z = lang == "zh"
    lines = [OVERALL[report["overall"]][0 if z else 1]]
    order = {"fail": 0, "unknown": 1, "warn": 2}
    issues = sorted((c for c in report["checks"] if c["status"] in order),
                    key=lambda c: (order[c["status"]], int(c["check"][1:])))
    for c in issues:
        name = CHECK_NAMES[c["check"]][0 if z else 1]
        status = STATUS[c["status"]][0 if z else 1]
        lines.append(f"- {c['check']} {name}：{status}" if z else f"- {c['check']} {name}: {status}")
        for f in _findings(c):
            if f["status"] != c["status"]:
                continue
            ports = "、".join(f.get("ports", [])) if z else ", ".join(f.get("ports", []))
            nums = _numbers(f)
            if z:
                detail = f["message"]
                if ports:
                    detail += f"（端口：{ports}）"
                if f.get("margin_ratio") is not None:
                    detail += f"，余量 {f['margin_ratio'] * 100:.1f}%"
            else:
                detail = EN_REASON[c["check"]] if c["status"] != "unknown" else "required data is missing"
                if nums:
                    detail += f" ({nums})"
                if ports:
                    detail += f"; ports: {ports}"
            lines.append(f"  - {detail}")
    passed = [c["check"] for c in report["checks"] if c["status"] == "pass"]
    na = [c for c in report["checks"] if c["status"] == "not_applicable"]
    if passed:
        lines.append(f"通过：{'、'.join(passed)}" if z else f"Passed: {', '.join(passed)}")
    for c in na:
        name = CHECK_NAMES[c["check"]][0 if z else 1]
        lines.append(f"不适用：{c['check']} {name}（{c['message']}）" if z
                     else f"Not applicable: {c['check']} {name}")
    return "\n".join(lines)


def explain_candidates(candidates, lang: str = "zh") -> str:
    """候选方案列表的说明：每个方案的组成、排名依据（ADR-0029）与校验说明。"""
    z = lang == "zh"
    if not candidates:
        return "没有找到可用的方案。" if z else "No usable design was found."
    out = []
    for n, cand in enumerate(candidates, start=1):
        parts = "、".join(f"{c['instance']}={c['component']}" for c in cand.system["components"]) if z else \
            ", ".join(f"{c['instance']}={c['component']}" for c in cand.system["components"])
        warns = sum(1 for c in cand.report["checks"] if c["status"] == "warn")
        mass = "—" if cand.mass_kg is None else f"{cand.mass_kg:.3g} kg"
        margin = "—" if cand.min_margin is None else f"{cand.min_margin * 100:.1f}%"
        if z:
            out.append(f"## 方案 {n}\n组成：{parts}\n排序依据：结论 {STATUS[cand.overall][0]}，转接件 {cand.adapters} 个，"
                       f"告警 {warns} 项，总质量 {mass}，最小余量 {margin}")
        else:
            out.append(f"## Option {n}\nComponents: {parts}\nRanking basis: overall {STATUS[cand.overall][1]}, "
                       f"{cand.adapters} adapter(s), {warns} warning(s), total mass {mass}, minimum margin {margin}")
        out.append(explain(cand.report, lang))
    return "\n\n".join(out)
