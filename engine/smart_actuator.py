"""一体化关节模组（smart_actuator）对一个关节需求的校验（ADR-0117 第 117.3 步）。纯函数：不联网、不调用 AI、不读数据库。

需求用选型需求的写法（requirement.schema.json 的输出端各项：连续力矩、峰值力矩、转速，安全系数）。
  S1 峰值力矩：峰值需求 × 安全系数 ≤ 堵转力矩（厂商在推荐电压下给的瞬时最大）
  S2 连续力矩：连续需求 × 安全系数 ≤ 连续额定力矩；厂商没给连续额定 → unknown（堵转力矩不能当连续值用，ADR-0117）
  S3 转速：直流电机的力矩—转速近似为直线 n(T) = n₀ · (1 − T / Tₛ)（教材公式；n₀ 空载转速、Tₛ 堵转力矩，同一电压）。
           给了工作点（动作过程中同一时刻的 (力矩, 转速)，取绝对值）就逐点核：n ≤ n₀ · (1 − T · 安全系数 / Tₛ)；
           没给就按最不利的组合核（峰值力矩与最高转速同时出现），偏保守
  S4 回差：只报数（重复定位精度在整机里按各关节回差合成，不在单个关节判）
缺任何一项数据，该项为 unknown，不判通过。
"""

from __future__ import annotations

from collections.abc import Mapping

from engine.result import FAIL, PASS, UNKNOWN, CheckResult, Finding, not_applicable, overall
from engine.values import nominal


def _p(comp: Mapping, name: str) -> float | None:
    return nominal((comp.get("params") or {}).get(name))


def _le(check: str, need: float | None, cap: float | None, unit: str, what: str, missing: str) -> CheckResult:
    if need is None or cap is None:
        return CheckResult(check, [Finding(UNKNOWN, missing)])
    st = PASS if need <= cap + 1e-12 else FAIL
    return CheckResult(check, [Finding(st, f"{what}：需要 {need:.3g} {unit}，能力 {cap:.3g} {unit}", measured=need, limit=cap,
                                       unit=unit)])


def check(req: Mapping, comp: Mapping, points=None) -> dict:
    """返回 {"component", "overall", "checks": [...]}。points：[(力矩 N·m, 转速 rpm), ...]（同一时刻的值，可不给）"""
    sf = float(req.get("safety_factor") or 1.0)
    tc, tp, n = (req.get(k) for k in ("output_torque_cont_nm", "output_torque_peak_nm", "output_speed_rpm"))
    ts, n0, tr = _p(comp, "stall_torque_nm"), _p(comp, "no_load_speed_rpm"), _p(comp, "rated_torque_nm")
    res = [
        _le("S1", None if tp is None else tp * sf, ts, "N·m", "峰值力矩 × 安全系数 ≤ 堵转力矩",
            "堵转力矩或峰值需求缺数据"),
        _le("S2", None if tc is None else tc * sf, tr, "N·m", "连续力矩 × 安全系数 ≤ 连续额定力矩",
            ("厂商没给连续额定力矩（堵转力矩不能当连续值用），连续力矩判待确认"
             + (f"；连续需求 × 安全系数 {tc * sf:.3g} N·m，是堵转力矩的 {tc * sf / ts:.0%}" if tc is not None and ts else ""))
            if tr is None else "连续需求缺数据"),
    ]
    if ts is None or n0 is None or (not points and (n is None or tp is None)):
        res.append(CheckResult("S3", [Finding(UNKNOWN, "转速需求、峰值力矩、堵转力矩或空载转速缺数据")]))
    elif points:
        def room(t, w):                      # 转速余量：能力 − 需要（rpm）
            return n0 * (1 - abs(t) * sf / ts) - abs(w)
        t, w = min(points, key=lambda tw: room(*tw))
        cap = max(n0 * (1 - abs(t) * sf / ts), 0.0)
        res.append(_le("S3", abs(float(w)), cap, "rpm",
                       f"动作过程 {len(points)} 个工作点里最紧的一点（{abs(t):.3g} N·m）：转速 ≤ n₀(1 − T·SF/Tₛ)", ""))
    else:
        cap = max(n0 * (1 - tp * sf / ts), 0.0)
        res.append(_le("S3", float(n), cap, "rpm",
                       f"峰值力矩与最高转速同时出现（保守）：n₀(1 − T·SF/Tₛ) = {n0:g} × (1 − {tp * sf:.3g}/{ts:g})", ""))
    bl = _p(comp, "backlash_arcmin")
    res.append(not_applicable("S4", f"回差 {bl:g} arcmin（只报数，整机合成重复定位精度）" if bl is not None
                              else "回差：厂商没给"))
    return {"component": comp["id"], "overall": overall(res), "checks": [r.to_dict() for r in res]}


def candidates(req: Mapping, comps, *, top: int = 10, points=None) -> list[dict]:
    """库里的一体化模组逐个校验；没有“不通过”的按质量从轻到重排（没有质量数据的排在最后）"""
    out = []
    for c in comps:
        if c.get("category") != "smart_actuator":
            continue
        r = check(req, c, points)
        if r["overall"] == FAIL:
            continue
        r["mass_kg"] = _p(c, "mass_kg")
        s1 = next(x for x in r["checks"] if x["check"] == "S1")
        r["_margin"] = s1.get("margin_ratio") or 0.0
        out.append(r)
    # 同样重时取峰值力矩余量大的，再按 id（结果可复现）
    out.sort(key=lambda r: (r["mass_kg"] is None, r["mass_kg"] or 0.0, -r["_margin"], r["component"]))
    for r in out:
        r.pop("_margin")
    return out[:top]
