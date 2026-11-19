"""机器人关节输出空心轴的结构与校核（ADR-0100 42.5，对照《机械设计》33.10 的 RJ-201）。

方案（AI 提议，代码核对）：{"bearing": 库里的深沟球轴承 id, "bore_mm": 内孔, "fillet_mm": 法兰台阶圆角, "reason": ...}。
轴承位直径 = 轴承内径、宽度 = 轴承宽度（取库里的值，不让 AI 给）；其余各段按 `joint_rules.yaml` 的结构规则由代码算：
  减速器法兰（轴承位 + 20，长 10）— 内侧轴承位 — 隔套段 24 — 外侧轴承位 — 花键段（按小径计，长 20）— 螺纹段（长 10）。

条件（来自需求原话与动力学，代码核对过）：
  T_peak_nm、T_min_nm（一个节拍内驱动力矩的最大、最小绝对值）、F_peak_n（大臂传来的力）、T_stop_nm（急停：减速器瞬时允许最大转矩）、
  reach_mm（工作半径）、budget_mm（末端偏移预算）、required_safety、bearing_life_h、speed_avg_rpm（输出轴平均转速）、
  F_series_n（一个节拍内的力，可缺；算轴承当量载荷用）、material、surface

校核项（pass / fail / unknown，缺数据为 unknown）：装配；刚度（1.2·δ ≤ 预算）；静强度（轴承位、花键段，正常工作）；
急停不屈服；花键齿面挤压（正常、急停）；法兰台阶的扭转疲劳（无限寿命，kt 用有限元算空心台阶）；两个轴承的寿命。

纯计算（kt 的有限元调本机 gmsh + CalculiX）：不联网、不调用 AI。
"""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

from analysis.shaft import torsion as TS


class JointProposalInvalid(ValueError):
    pass


@lru_cache(maxsize=1)
def rules() -> dict:
    return yaml.safe_load((Path(__file__).with_name("joint_rules.yaml")).read_text(encoding="utf-8"))


def spline(seat: float) -> dict:
    """花键：齿数、分度圆、大径、小径（mm）"""
    m = rules()["spline"]["module_mm"]
    z = int((seat - 3) / m) - 1
    return {"module_mm": m, "z": z, "d_mm": m * z, "D_ee_mm": m * (z + 1), "D_ie_mm": m * (z - 1.5)}


def thread(seat: float) -> float | None:
    """圆螺母螺纹（大径）：比花键小径小 0.5 mm 以上的最大一档；没有就 None"""
    ok = [t for t in rules()["lock_nut"]["threads_mm"] if t < spline(seat)["D_ie_mm"] - 0.5]
    return max(ok) if ok else None


def layout(seat: float, bearing_width: float) -> list[dict]:
    """轴段 [{name, d, L}]，z 从减速器法兰端面起"""
    st = rules()["structure"]
    th = thread(seat)
    segs = [{"name": "减速器法兰", "d": seat + st["flange_extra_mm"], "L": st["flange_length_mm"]},
            {"name": "轴承位（内侧）", "d": seat, "L": bearing_width},
            {"name": "隔套段", "d": seat, "L": st["spacer_length_mm"]},
            {"name": "轴承位（外侧）", "d": seat, "L": bearing_width},
            {"name": "花键段", "d": spline(seat)["D_ie_mm"], "L": st["spline_length_mm"]}]
    if th is not None:
        segs.append({"name": f"螺纹段 M{th:g}×1.5", "d": th, "L": st["thread_length_mm"]})
    z = 0.0
    for s in segs:
        s["z0"], s["z1"] = z, z + s["L"]
        z += s["L"]
    return segs


def _item(name, status, value=None, limit=None, note="", **kw):
    return {"item": name, "status": status, **({"value": value} if value is not None else {}),
            **({"limit": limit} if limit is not None else {}), **({"note": note} if note else {}), **kw}


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) else None


def _pv(comp: dict, key: str):
    return ((comp.get("params") or {}).get(key) or {}).get("value")


def check_proposal(proposal, get: Callable[[str], dict | None]) -> dict:
    if not isinstance(proposal, dict):
        raise JointProposalInvalid("方案不是对象")
    comp = get(str(proposal.get("bearing", "")))
    if comp is None or comp.get("category") != "bearing":
        raise JointProposalInvalid(f"轴承 {proposal.get('bearing')!r} 不在零件库里")
    ports = {p["id"]: p for p in comp.get("ports", [])}
    seat = _num(((ports.get("inner") or {}).get("spec") or {}).get("diameter_mm", {}).get("value"))
    width = _num(_pv(comp, "width_mm"))
    if seat is None or width is None:
        raise JointProposalInvalid(f"轴承 {comp['id']} 缺内径或宽度")
    bore, r = _num(proposal.get("bore_mm")), _num(proposal.get("fillet_mm"))
    if bore is None or bore < 0:
        raise JointProposalInvalid("要给内孔直径 bore_mm（≥ 0）")
    if r is None or r <= 0:
        raise JointProposalInvalid("要给法兰台阶的圆角 fillet_mm（> 0）")
    return {"bearing": comp, "seat": seat, "width": width, "bore": bore, "fillet": r}


def bearing_reactions(f_n: np.ndarray, z1: float, z2: float, zf: float) -> tuple[np.ndarray, np.ndarray]:
    """两支点（轴承中心 z1 < z2），力作用在 zf（外伸）：两支点的反力绝对值"""
    r2 = f_n * (zf - z1) / (z2 - z1)
    r1 = f_n * (zf - z2) / (z2 - z1)
    return np.abs(r1), np.abs(r2)


def evaluate(proposal, cond: dict, get: Callable[[str], dict | None], *, kt: Callable | None = None) -> dict:
    """全部校核。返回 {"segments", "items", "overall", "mass_kg", "theta_rad", "delta_mm"}"""
    from analysis import shaft
    from analysis.common import materials

    p = check_proposal(proposal, get)
    seat, bore, width, r = p["seat"], p["bore"], p["width"], p["fillet"]
    segs = layout(seat, width)
    mat = materials.get(cond["material"])
    e, nu = mat.get("elastic_modulus_mpa"), mat.get("poisson_ratio")
    sy = mat.get("yield_strength_mpa")
    items: list[dict] = []
    sp = spline(seat)
    th = thread(seat)

    # 装配：两个轴承从大臂一端装入（花键大径 < 轴承内径）；螺纹存在；内孔小于最细段
    ok = sp["D_ee_mm"] < seat - 1e-9
    items.append(_item("两个轴承从大臂一端装入（花键大径 < 轴承内径）", "pass" if ok else "fail", sp["D_ee_mm"], f"< {seat:g}"))
    items.append(_item("锁紧圆螺母螺纹", "pass" if th is not None else "fail", th, None,
                       "" if th is not None else "规则表里没有比花键小径小的螺纹"))
    thinnest = min(s["d"] for s in segs)
    items.append(_item("内孔小于最细的一段", "pass" if bore < thinnest - 1e-9 else "fail", bore, f"< {thinnest:g}"))
    if bore >= thinnest - 1e-9:
        return {"segments": segs, "items": items, "overall": "fail"}

    # 刚度：减速器法兰到花键段（不含螺纹段），两端段算一半
    t_peak = _num(cond.get("T_peak_nm"))
    twist_segs = [(s["d"], s["L"]) for s in segs[:5]]
    theta = delta = None
    margin = rules()["stiffness"]["hand_margin"]
    if t_peak is None or e is None or nu is None:
        items.append(_item("刚度：末端偏移", "unknown", note="缺峰值力矩或材料弹性常数"))
    else:
        g = TS.shear_modulus(e, nu)
        theta = TS.twist(t_peak * 1e3, twist_segs, g, bore)
        reach, budget = _num(cond.get("reach_mm")), _num(cond.get("budget_mm"))
        if reach is None or budget is None:
            items.append(_item("刚度：末端偏移", "unknown", note="需求里没有工作半径或偏移预算"))
        else:
            delta = TS.tip_displacement(theta, reach)
            items.append(_item(f"刚度：{margin:g} × 末端偏移", "pass" if margin * delta <= budget + 1e-12 else "fail",
                               round(margin * delta, 4), f"≤ {budget:g}",
                               f"扭转角 {theta * 1e6:.1f} μrad、末端偏移 {delta:.4f} mm（{margin:g} 倍留给台阶法兰的局部变形）"))

    # 静强度（正常工作）：大臂的力对外侧轴承的弯矩，偏于安全地也加在花键段上
    f_peak = _num(cond.get("F_peak_n"))
    z_outer = segs[3]["z0"] + width / 2
    z_arm = segs[4]["z1"]                                    # 大臂连接面 = 花键段外端
    need = _num(cond.get("required_safety"))
    if t_peak is not None and f_peak is not None and sy is not None:
        m_b = f_peak * (z_arm - z_outer)
        for name, d in (("轴承位", seat), ("花键段（按小径）", sp["D_ie_mm"])):
            s = TS.static_safety(sy, d, bore, m_b, t_peak * 1e3)
            st = "unknown" if need is None else ("pass" if s["safety"] >= need else "fail")
            items.append(_item(f"静强度：{name}", st, round(s["safety"], 2), need,
                               f"σ {s['sigma_mpa']:.2f} MPa、τ {s['tau_mpa']:.2f} MPa" + ("" if need else "；需求里没有安全系数要求")))
    else:
        items.append(_item("静强度", "unknown", note="缺峰值力矩、大臂的力或材料屈服强度"))

    # 急停：减速器瞬时允许最大转矩，花键段不屈服；花键齿面挤压
    t_stop = _num(cond.get("T_stop_nm"))
    spl = rules()["spline"]
    area = spl["load_factor_psi"] * sp["z"] * sp["module_mm"] * rules()["structure"]["spline_length_mm"] * sp["d_mm"] / 2
    allow = spl["allowable_bearing_pressure_mpa"]
    if t_stop is not None and sy is not None:
        tau = t_stop * 1e3 / (2 * TS.section_modulus(sp["D_ie_mm"], bore))
        s = sy / (math.sqrt(3) * tau)
        items.append(_item("急停：花键段不屈服", "pass" if s >= 1 else "fail", round(s, 2), "≥ 1", f"τ {tau:.1f} MPa"))
    else:
        items.append(_item("急停：花键段不屈服", "unknown", note="缺减速器瞬时允许最大转矩"))
    for label, t in (("峰值力矩", t_peak), ("急停", t_stop)):
        if t is None:
            items.append(_item(f"花键齿面挤压（{label}）", "unknown", note="缺转矩"))
            continue
        sig_p = t * 1e3 / area
        items.append(_item(f"花键齿面挤压（{label}）", "pass" if sig_p <= allow else "fail", round(sig_p, 2), f"≤ {allow:g}"))

    # 法兰台阶的扭转疲劳（无限寿命）：转矩在 T_min..T_peak 之间脉动；法兰一侧不受大臂的弯矩（两个轴承之外）
    t_min = _num(cond.get("T_min_nm"))
    d_small, d_big = seat, seat + rules()["structure"]["flange_extra_mm"]
    if r >= (d_big - d_small) / 2:
        items.append(_item("法兰台阶圆角", "fail", r, f"< {(d_big - d_small) / 2:g}", "圆角不小于台阶高度"))
    elif t_peak is None or t_min is None:
        items.append(_item("法兰台阶扭转疲劳", "unknown", note="缺一个节拍内的力矩范围"))
    else:
        if kt is None:
            from analysis.shaft.kt import stepped_bar as kt
        try:
            k = kt(d_small, d_big, r, bore)
        except Exception as ex:  # noqa: BLE001 — 有限元算不出：待确认，写原因
            items.append(_item("法兰台阶扭转疲劳", "unknown", note=f"应力集中系数没算出来：{ex}"))
        else:
            sb, t1 = mat["ultimate_strength_mpa"], mat.get("fatigue_limit_torsion_mpa")
            if t1 is None:
                items.append(_item("法兰台阶扭转疲劳", "unknown", note="材料库没有扭转疲劳极限"))
            else:
                q = shaft.notch_sensitivity(r, sb, torsion=True)
                kf = 1 + q * (k["kt_torsion"] - 1)
                big_k = kf / shaft.size_factor(d_small) + 1 / shaft.surface_factor(cond.get("surface", "machined"), sb) - 1
                wt = 2 * TS.section_modulus(d_small, bore)
                ta, tm = (t_peak - t_min) * 1e3 / 2 / wt, (t_peak + t_min) * 1e3 / 2 / wt
                psi = t1 / (sb / math.sqrt(3))
                s = t1 / (big_k * ta + psi * tm)
                st = "unknown" if need is None else ("pass" if s >= need else "fail")
                items.append(_item(f"法兰台阶 Ø{d_small:g}→Ø{d_big:g} 扭转疲劳", st, round(s, 2), need,
                                   f"τa {ta:.2f}、τm {tm:.2f} MPa，αt {k['kt_torsion']:.3f}（{k.get('method', '')}）"))

    # 轴承寿命：两轴承支承，大臂的力作用在花键段外端
    comp = p["bearing"]
    c = _num(_pv(comp, "dynamic_load_rating_n"))
    life = _num(cond.get("bearing_life_h"))
    n = _num(cond.get("speed_avg_rpm"))
    f_series = cond.get("F_series_n")
    f_arr = np.abs(np.asarray(f_series, float)) if f_series else (np.array([f_peak]) if f_peak is not None else None)
    if c is None or f_arr is None or n is None or life is None:
        items.append(_item("轴承寿命", "unknown", note="缺额定动载荷、力、平均转速或寿命要求"))
    else:
        z_inner = segs[1]["z0"] + width / 2
        r1, r2 = bearing_reactions(f_arr, z_inner, z_outer, z_arm)
        for name, rr in (("内侧", r1), ("外侧", r2)):
            pp = float(np.cbrt(np.mean(rr ** 3)))
            l10 = 1e6 / (60 * n) * (c / pp) ** 3 if pp > 0 and n > 0 else math.inf
            items.append(_item(f"轴承 {comp.get('model')}（{name}）寿命", "pass" if l10 >= life else "fail",
                               round(l10) if math.isfinite(l10) else None, f"≥ {life:g}", f"当量载荷 P = {pp:.0f} N，C = {c:.0f} N"))

    rho = mat.get("density_kg_m3")
    mass = TS.mass([(s["d"], s["L"]) for s in segs], rho / 1000, bore) if rho else None
    mass_model = TS.mass(twist_segs, rho / 1000, bore) if rho else None        # 不含螺纹段（与书中 33.10 的计算模型同）
    worst = "fail" if any(i["status"] == "fail" for i in items) else ("unknown" if any(i["status"] == "unknown" for i in items)
                                                                     else "pass")
    return {"segments": segs, "items": items, "overall": worst, "mass_kg": mass, "mass_model_kg": mass_model,
            "theta_rad": theta, "delta_mm": delta,
            "spline": sp, "thread_mm": th}
