"""直线模组（linear_module）对一个移动关节需求的校验与选件（ADR-0129 129.3，ADR-0115 44.5.4）。纯函数：不联网、不调用 AI、不读数据库。

需求（数都用标准单位）：行程 stroke_mm、最高速度 speed_m_s、最大加速度 accel_m_s2、沿运动方向的最大推力 thrust_n（多体动力学算的，
含加速力与重力分量），滑台上的载荷（侧向力 force_lateral_n、法向力 force_normal_n、滚转 / 俯仰 / 偏摆力矩 moment_*_nm，取绝对值的最大），
安全系数 safety_factor（乘在推力与载荷上）。
  L1 行程：按行程分型号的，需求 ≤ 有效行程；行程任选的，需求 ≤ 最大工作行程
  L2 速度：需求 ≤ 最高速度（厂商按行程降速的，condition 原话附在结论里，由人看）
  L3 加速度：需求 ≤ 最大加速度
  L4 推力：需求 × 安全系数 ≤ 最大推力（没给最大推力时用额定推力）
  L5 滑台载荷：载荷比较系数 fv = Σ |F| / F允许 + Σ |M| / M允许（各项 × 安全系数）≤ 1——费斯托目录给的组合公式
     （EGC 目录第 15 页），各项单独都在允许值内时偏保守；需求里不为 0 的一项厂商没给允许值 → unknown
  L6 重复定位精度：只报数（整机合成）
缺任何一项数据，该项为 unknown，不判通过。
行程任选的模组，选定行程后的质量 = 行程 0 mm 的基本质量 + 每 10 mm 增重 × 行程 / 10（mass_at_stroke）。
"""

from __future__ import annotations

from collections.abc import Mapping

from engine.result import FAIL, PASS, UNKNOWN, CheckResult, Finding, not_applicable, overall
from engine.values import nominal

LOADS = (("force_lateral_n", "侧向力 Fy", "N"), ("force_normal_n", "法向力 Fz", "N"), ("moment_roll_nm", "滚转力矩 Mx", "N·m"),
         ("moment_pitch_nm", "俯仰力矩 My", "N·m"), ("moment_yaw_nm", "偏摆力矩 Mz", "N·m"))


def _p(comp: Mapping, name: str) -> float | None:
    return nominal((comp.get("params") or {}).get(name))


def _cond(comp: Mapping, name: str) -> str:
    c = ((comp.get("params") or {}).get(name) or {}).get("condition")
    return f"（厂商：{c}）" if c else ""


def _le(check: str, need, cap, unit: str, what: str, missing: str) -> CheckResult:
    if need is None or cap is None:
        return CheckResult(check, [Finding(UNKNOWN, missing)])
    st = PASS if need <= cap + 1e-12 else FAIL
    return CheckResult(check, [Finding(st, f"{what}：需要 {need:.4g} {unit}，能力 {cap:.4g} {unit}", measured=float(need),
                                       limit=float(cap), unit=unit)])


def mass_at_stroke(comp: Mapping, stroke_mm: float | None) -> float | None:
    """选定行程后的本体质量（kg）。按行程分型号的直接取 mass_kg；行程任选的按基本质量加行程增重；缺数据为 None"""
    m = _p(comp, "mass_kg")
    if m is None or _p(comp, "max_stroke_mm") is None:
        return m
    per10 = _p(comp, "mass_per_10mm_stroke_kg")
    if per10 is None or stroke_mm is None:
        return None
    return m + per10 * stroke_mm / 10.0


def load_factor(req: Mapping, comp: Mapping, sf: float) -> CheckResult:
    """L5 载荷比较系数"""
    terms, missing, given = [], [], False
    for key, name, unit in LOADS:
        need = req.get(key)
        if need is None:
            continue
        given = True
        if abs(need) < 1e-12:
            continue
        cap = _p(comp, key)
        if not cap:
            missing.append(name)
            continue
        terms.append((name, abs(need) * sf, cap, unit))
    if not given:
        return CheckResult("L5", [Finding(UNKNOWN, "滑台载荷（力与力矩）需求缺数据")])
    if missing:
        return CheckResult("L5", [Finding(UNKNOWN, f"厂商没给 {'、'.join(missing)} 的允许值，滑台载荷判待确认")])
    fv = sum(n / c for _, n, c, _ in terms)
    parts = "，".join(f"{name} {n:.3g}/{c:.4g} {u}" for name, n, c, u in terms) or "各项为 0"
    st = PASS if fv <= 1 + 1e-12 else FAIL
    return CheckResult("L5", [Finding(st, f"载荷比较系数 fv = Σ 载荷 × 安全系数 / 允许值 = {fv:.3f}（{parts}）≤ 1"
                                          f"{_cond(comp, 'moment_roll_nm') or _cond(comp, 'force_lateral_n')}",
                                      measured=fv, limit=1.0, unit="")])


def check(req: Mapping, comp: Mapping) -> dict:
    """返回 {"component", "overall", "checks": [...], "mass_kg"}（mass_kg 是按需求行程算的本体质量，缺数据为 None）"""
    sf = float(req.get("safety_factor") or 1.0)
    stroke, v, a, f = (req.get(k) for k in ("stroke_mm", "speed_m_s", "accel_m_s2", "thrust_n"))
    fixed, free = _p(comp, "stroke_mm"), _p(comp, "max_stroke_mm")
    res = [
        _le("L1", stroke, fixed if fixed is not None else free, "mm",
            "行程 ≤ 有效行程" if fixed is not None else "行程 ≤ 最大工作行程（订货时任选）", "行程需求或模组行程缺数据"),
        _le("L2", v, _p(comp, "max_speed_m_s"), "m/s", f"最高速度{_cond(comp, 'max_speed_m_s')}", "速度需求或最高速度缺数据"),
        _le("L3", a, _p(comp, "max_accel_m_s2"), "m/s²", "最大加速度",
            "加速度需求缺数据" if a is None else "厂商没给最大加速度，判待确认"),
    ]
    cap_f = _p(comp, "max_thrust_n")
    what = "推力 × 安全系数 ≤ 最大推力"
    if cap_f is None:
        cap_f, what = _p(comp, "rated_thrust_n"), "推力 × 安全系数 ≤ 额定推力"
    res.append(_le("L4", None if f is None else abs(f) * sf, cap_f, "N", what, "推力需求或模组推力缺数据"))
    res.append(load_factor(req, comp, sf))
    rp = _p(comp, "repeatability_mm")
    res.append(not_applicable("L6", f"重复定位精度 ±{rp:g} mm（只报数，整机合成）" if rp is not None else "重复定位精度：厂商没给"))
    return {"component": comp["id"], "overall": overall(res), "checks": [r.to_dict() for r in res],
            "mass_kg": mass_at_stroke(comp, stroke)}


def candidates(req: Mapping, comps, *, top: int = 10, drive_types=None) -> list[dict]:
    """库里的直线模组逐个校验；没有“不通过”的按选定行程后的质量从轻到重排（没有质量的排在最后），同样重时按 id。
    drive_types：只看这几种驱动方式（如 {"belt"}），不给就全看"""
    out = []
    for c in comps:
        if c.get("category") != "linear_module":
            continue
        if drive_types and ((c.get("params") or {}).get("drive_type") or {}).get("value") not in drive_types:
            continue
        r = check(req, c)
        if r["overall"] != FAIL:
            out.append(r)
    out.sort(key=lambda r: (r["overall"] != PASS, r["mass_kg"] is None, r["mass_kg"] or 0.0, r["component"]))
    return out[:top]


def rejected(req: Mapping, comps) -> list[dict]:
    """不通过的模组（报告里说明为什么不选）"""
    return [r for c in comps if c.get("category") == "linear_module" for r in [check(req, c)] if r["overall"] == FAIL]
