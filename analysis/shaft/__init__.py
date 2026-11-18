"""阶梯轴的校核（ADR-0100 42.1，ADR-0056 的分析模块）：载荷 → 弯矩、转矩 → 旋转轴上一点一转之内的应力循环 →
无限寿命安全系数；梁单元 + 集中质量求临界转速；静挠度与轴承处转角；轴承支反力。

做法与《机械设计》33.11（平缝机上轴 LS-101）相同，标准题与书中结果对照（tests/test_analysis_shaft.py）。

设置（长度 mm、力 N、质量 kg、转速 r/min、功率 W）：
  material：材料库 id（要 E、密度、抗拉强度、σ₋₁、τ₋₁）
  segments：[{diameter_mm, length_mm}]，从 z = 0 起首尾相接
  supports：两个轴承中点的 z（简支）
  speeds_rpm：要算的转速（如 [5000, 5500]）
  masses：[{name, z_mm, mass_kg}]——装在轴上的零件（临界转速用）
  loads：
    {type: crank_slider, z_mm, crank_radius_mm, rod_length_mm, reciprocating_mass_kg, balance_ratio}
        曲柄滑块：往复惯性力一、二阶 + 平衡块离心力（滑块方向为 y），转矩波动取级数到三阶；θ = 0 为滑块在上止点
    {type: force, z_mm, fx_n, fy_n}：在空间里方向不变的力（如带的拉力）
    {type: torque_load, z_mm, power_w}：在这一点消耗的平均功率（转矩 = P/ω）
  drive_z_mm：动力输入的位置（电机）。截面上的转矩 = 截面另一侧（离开动力那一侧）全部转矩负载之和
  sections：[{name, z_mm, diameter_mm, fillet_mm, kt_bending, kt_torsion, kt_source, surface}]——要校核的截面；
            理论应力集中系数 kt 由调用方给出并写明出处（有限元或手册），本模块不估
  required_safety：要求的安全系数（缺省不判）；critical_ratio：一阶临界转速与最高转速之比的下限（缺省不判）

不联网、不调用 AI；结果不写入零件参数。
"""

from __future__ import annotations

import math
import time
from functools import cache
from itertools import pairwise
from pathlib import Path

import numpy as np
import yaml

from analysis.common import materials, result

MODULE = {
    "id": "shaft", "name": "轴的校核", "version": "1",
    "description": "阶梯轴：应力循环与无限寿命安全系数、临界转速、挠度与转角、支反力",
    "python": ["numpy", "scipy"], "solvers": [], "install": "",
}
LIMITS = ["名义应力法：截面应力按材料力学公式，台阶处乘疲劳缺口系数（kt 由调用方给出）",
          "两个轴承按简支，不计轴承刚度与游隙；临界转速只计横向弯曲振动，集中质量不计转动惯量",
          "安全系数按 σ₋₁/(Kσ·σa + ψσ·σm) 与 τ₋₁/(Kτ·τa + ψτ·τm) 合成（ψ = σ₋₁/σb，τ 的按 σb/√3），只判无限寿命",
          "修正系数用 Shigley 的公式拟合，对表面状态与圆角很敏感"]
N_THETA = 720                   # 一转分多少个转角
N_PHI = 72                      # 截面圆周上取多少个点
BEAM_H_MM = 2.0                 # 梁单元最大长度
MPA_PER_KPSI = 6.894757


class ShaftError(ValueError):
    pass


@cache
def factors() -> dict:
    return yaml.safe_load((Path(__file__).with_name("factors.yaml")).read_text(encoding="utf-8"))


def surface_factor(finish: str, sigma_b: float) -> float:
    rows = factors()["surface_factor"]["rows"]
    if finish not in rows:
        raise ShaftError(f"表面状态 {finish!r} 不认识；可用：{'、'.join(rows)}")
    c = rows[finish]
    return c["a"] * sigma_b ** c["b"]


def size_factor(d: float) -> float:
    for r in factors()["size_factor"]["ranges"]:
        if r["d_min"] <= d <= r["d_max"]:
            return r["c"] * d ** r["e"]
    raise ShaftError(f"尺寸系数公式不适用于 d = {d} mm")


def notch_sensitivity(r: float, sigma_b: float, torsion: bool = False) -> float:
    f = factors()["notch_sensitivity"]
    s = sigma_b / MPA_PER_KPSI
    lo, hi = f["valid_kpsi"]
    if not lo <= s <= hi:
        raise ShaftError(f"缺口敏感系数拟合式只适用于抗拉强度 {lo * MPA_PER_KPSI:.0f}–{hi * MPA_PER_KPSI:.0f} MPa")
    c = f["torsion_sqrt_a_inch" if torsion else "bending_sqrt_a_inch"]
    sqrt_a_mm = sum(ci * s ** i for i, ci in enumerate(c)) * math.sqrt(25.4)
    return 1.0 / (1.0 + sqrt_a_mm / math.sqrt(r))


# ---------------------------------------------------------------- 几何与载荷


def layout(segments: list[dict]) -> list[tuple[float, float, float]]:
    out, z = [], 0.0
    for s in segments:
        d, length = float(s["diameter_mm"]), float(s["length_mm"])
        if d <= 0 or length <= 0:
            raise ShaftError("轴段的直径和长度要大于 0")
        out.append((z, z + length, d))
        z += length
    if not out:
        raise ShaftError("没有轴段")
    return out


def diameter_at(lay, z: float) -> float:
    for z0, z1, d in lay:
        if z0 - 1e-9 <= z <= z1 + 1e-9:
            return d
    raise ShaftError(f"z = {z} mm 不在轴上")


def omega(n_rpm: float) -> float:
    return n_rpm * 2 * math.pi / 60


def _crank(ld: dict, th: np.ndarray, n: float):
    r, lr = float(ld["crank_radius_mm"]), float(ld["rod_length_mm"])
    m, bal = float(ld["reciprocating_mass_kg"]), float(ld.get("balance_ratio", 0.0))
    lam = r / lr
    a = m * r / 1000 * omega(n) ** 2
    fy = a * ((1 - bal) * np.cos(th) + lam * np.cos(2 * th))
    fx = -a * bal * np.sin(th)
    b = m * (r / 1000) ** 2 * omega(n) ** 2 * 1000                   # N·mm
    tq = b * (lam / 4 * np.sin(th) - 0.5 * np.sin(2 * th) - 3 * lam / 4 * np.sin(3 * th))
    return fx, fy, tq


def point_forces(loads: list[dict], th: np.ndarray, n: float) -> list[tuple[float, np.ndarray, np.ndarray]]:
    """[(z, Fx(θ), Fy(θ))]：作用在轴上的横向力（空间固定坐标）"""
    out = []
    for ld in loads:
        if ld["type"] == "crank_slider":
            fx, fy, _ = _crank(ld, th, n)
            out.append((float(ld["z_mm"]), fx, fy))
        elif ld["type"] == "force":
            out.append((float(ld["z_mm"]), np.full_like(th, float(ld.get("fx_n", 0))), np.full_like(th, float(ld.get("fy_n", 0)))))
    return out


def moment_at(z_sec: float, forces, za: float, zb: float):
    """截面 z 处两平面的弯矩（N·mm）：Mx 由 x 向力产生，My 由 y 向力产生（与 33.11 程序同一约定）"""
    res = []
    for k in (1, 2):
        rb = -sum(f[k] * (f[0] - za) for f in forces) / (zb - za)
        ra = -sum(f[k] for f in forces) - rb
        pts = [(f[0], f[k]) for f in forces] + [(za, ra), (zb, rb)]
        res.append(sum(p * max(z_sec - zp, 0.0) for zp, p in pts))
    return res[0], res[1], res


def torque_at(z_sec: float, loads: list[dict], drive_z: float, th: np.ndarray, n: float) -> np.ndarray:
    """截面传的转矩（N·mm）：截面离开动力一侧的转矩负载之和"""
    t = np.zeros_like(th)
    for ld in loads:
        z = float(ld["z_mm"])
        beyond = (z < z_sec <= drive_z) or (drive_z <= z_sec < z)
        if not beyond:
            continue
        if ld["type"] == "crank_slider":
            t = t + _crank(ld, th, n)[2]
        elif ld["type"] == "torque_load":
            t = t + float(ld["power_w"]) / omega(n) * 1000
    return t


# ---------------------------------------------------------------- 疲劳


def section_safety(sec: dict, mat: dict, forces, za, zb, tau: np.ndarray, th: np.ndarray) -> dict:
    d = float(sec["diameter_mm"])
    w, wt = math.pi * d ** 3 / 32, math.pi * d ** 3 / 16
    mx, my, _ = moment_at(float(sec["z_mm"]), forces, za, zb)
    sb, s1, t1 = mat["ultimate_strength_mpa"], mat["fatigue_limit_bending_mpa"], mat["fatigue_limit_torsion_mpa"]
    r = float(sec["fillet_mm"])
    q_s, q_t = notch_sensitivity(r, sb), notch_sensitivity(r, sb, torsion=True)
    k_s = 1 + q_s * (float(sec["kt_bending"]) - 1)
    k_t = 1 + q_t * (float(sec["kt_torsion"]) - 1)
    eps, beta = size_factor(d), surface_factor(sec.get("surface", "ground"), sb)
    big_ks, big_kt = k_s / eps + 1 / beta - 1, k_t / eps + 1 / beta - 1
    ps, pt = s1 / sb, t1 / (sb / math.sqrt(3))
    tau = tau / wt
    ta, tm = (tau.max() - tau.min()) / 2, (tau.max() + tau.min()) / 2
    s_t = t1 / (big_kt * ta + pt * abs(tm)) if (big_kt * ta + pt * abs(tm)) > 0 else math.inf
    worst = None
    for phi in np.linspace(0, 2 * np.pi, N_PHI, endpoint=False):
        psi = phi - th
        sig = (mx * np.cos(psi) + my * np.sin(psi)) / w
        sa, sm = (sig.max() - sig.min()) / 2, (sig.max() + sig.min()) / 2
        den = big_ks * sa + ps * abs(sm)
        s_s = s1 / den if den > 0 else math.inf
        s = s_s * s_t / math.hypot(s_s, s_t) if math.isfinite(s_s) and math.isfinite(s_t) else min(s_s, s_t)
        if worst is None or s < worst["S"]:
            worst = {"S": s, "S_sigma": s_s, "phi_deg": math.degrees(phi), "sigma_a_mpa": sa, "sigma_m_mpa": sm,
                     "sigma_max_mpa": float(np.abs(sig).max())}
    return {**worst, "S_tau": s_t, "tau_a_mpa": ta, "tau_m_mpa": tm, "tau_max_mpa": float(np.abs(tau).max()),
            "q_bending": q_s, "q_torsion": q_t, "kf_bending": k_s, "kf_torsion": k_t, "size_factor": eps, "surface_factor": beta,
            "K_sigma": big_ks, "K_tau": big_kt, "psi_sigma": ps, "psi_tau": pt}


# ---------------------------------------------------------------- 梁单元


def _mesh(lay, supports, extra, h=BEAM_H_MM):
    length = lay[-1][1]
    pts = {0.0, length, *supports, *extra}
    for z0, z1, _ in lay:
        pts |= {z0, z1}
    pts = sorted(p for p in pts if 0 <= p <= length)
    z = [pts[0]]
    for a, b in pairwise(pts):
        k = max(1, math.ceil((b - a) / h))
        z += list(np.linspace(a, b, k + 1)[1:])
    return np.array(z)


def beam_matrices(lay, z: np.ndarray, e_mpa: float, rho_t_mm3: float):
    n = len(z)
    kk, mm = np.zeros((2 * n, 2 * n)), np.zeros((2 * n, 2 * n))
    for e in range(n - 1):
        le = z[e + 1] - z[e]
        d = diameter_at(lay, (z[e] + z[e + 1]) / 2)
        i_, a_ = math.pi * d ** 4 / 64, math.pi * d ** 2 / 4
        k = e_mpa * i_ / le ** 3 * np.array([[12, 6 * le, -12, 6 * le], [6 * le, 4 * le * le, -6 * le, 2 * le * le],
                                             [-12, -6 * le, 12, -6 * le], [6 * le, 2 * le * le, -6 * le, 4 * le * le]])
        m = rho_t_mm3 * a_ * le / 420 * np.array([[156, 22 * le, 54, -13 * le], [22 * le, 4 * le * le, 13 * le, -3 * le * le],
                                                  [54, 13 * le, 156, -22 * le], [-13 * le, -3 * le * le, -22 * le, 4 * le * le]])
        idx = [2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3]
        kk[np.ix_(idx, idx)] += k
        mm[np.ix_(idx, idx)] += m
    return kk, mm


def _node(z, zq):
    return int(np.argmin(abs(z - zq)))


def critical_speeds(lay, supports, masses, e_mpa, rho_kg_m3, n_modes=2):
    from scipy.linalg import eigh

    z = _mesh(lay, supports, [m["z_mm"] for m in masses])
    kk, mm = beam_matrices(lay, z, e_mpa, rho_kg_m3 * 1e-12)          # kg/m³ → t/mm³
    for m in masses:
        i = 2 * _node(z, float(m["z_mm"]))
        mm[i, i] += float(m["mass_kg"]) / 1000.0                       # kg → t
    fixed = {2 * _node(z, zs) for zs in supports}
    free = [i for i in range(2 * len(z)) if i not in fixed]
    w2, _ = eigh(kk[np.ix_(free, free)], mm[np.ix_(free, free)], subset_by_index=[0, n_modes - 1])
    return [float(math.sqrt(abs(x)) * 60 / (2 * math.pi)) for x in w2]


def static_deflection(lay, supports, point_loads: list[tuple[float, float]], e_mpa):
    """点力 [(z, F)]（一个平面）作用下的挠度与转角：返回 z、y、θ"""
    z = _mesh(lay, supports, [p[0] for p in point_loads])
    kk, _ = beam_matrices(lay, z, e_mpa, 1.0)
    f = np.zeros(2 * len(z))
    for zp, p in point_loads:
        f[2 * _node(z, zp)] += p
    fixed = {2 * _node(z, zs) for zs in supports}
    free = [i for i in range(2 * len(z)) if i not in fixed]
    u = np.zeros(2 * len(z))
    u[free] = np.linalg.solve(kk[np.ix_(free, free)], f[free])
    return z, u[0::2], u[1::2]


# ---------------------------------------------------------------- 入口


def _check_setup(setup: dict):
    lay = layout(setup.get("segments") or [])
    length = lay[-1][1]
    sup = [float(x) for x in setup.get("supports") or []]
    if len(sup) != 2 or sup[0] == sup[1]:
        raise ShaftError("要两个不同位置的支点（轴承中点的 z）")
    for z in sup:
        if not 0 <= z <= length:
            raise ShaftError(f"支点 z = {z} mm 不在轴上（轴长 {length} mm）")
    speeds = [float(x) for x in setup.get("speeds_rpm") or []]
    if not speeds or min(speeds) <= 0:
        raise ShaftError("要给转速（r/min）")
    for ld in setup.get("loads") or []:
        if ld.get("type") not in ("crank_slider", "force", "torque_load"):
            raise ShaftError(f"不认识的载荷类型 {ld.get('type')!r}")
        if not 0 <= float(ld["z_mm"]) <= length:
            raise ShaftError(f"载荷位置 z = {ld['z_mm']} mm 不在轴上")
    for m in setup.get("masses") or []:
        if not 0 <= float(m["z_mm"]) <= length or float(m["mass_kg"]) < 0:
            raise ShaftError(f"集中质量 {m.get('name', '')} 的位置或质量不对")
    for s in setup.get("sections") or []:
        for k in ("z_mm", "diameter_mm", "fillet_mm", "kt_bending", "kt_torsion"):
            if k not in s:
                raise ShaftError(f"截面 {s.get('name', '')} 缺 {k}（kt 要写明出处，本模块不估）")
        if float(s["kt_bending"]) < 1 or float(s["kt_torsion"]) < 1 or float(s["fillet_mm"]) <= 0:
            raise ShaftError(f"截面 {s.get('name', '')}：kt 不能小于 1，圆角要大于 0")
    return lay, sorted(sup), speeds


def run(setup: dict) -> dict:
    t0 = time.time()
    try:
        mat = materials.get(setup.get("material", ""))
        materials.require(mat, ["elastic_modulus_mpa", "density_kg_m3", "ultimate_strength_mpa",
                                "fatigue_limit_bending_mpa", "fatigue_limit_torsion_mpa"], "轴的校核")
        lay, (za, zb), speeds = _check_setup(setup)
        loads = setup.get("loads") or []
        drive = float(setup.get("drive_z_mm", lay[-1][1]))
        th = np.linspace(0, 2 * np.pi, N_THETA + 1)[:-1]
        per_speed = []
        for n in speeds:
            forces = point_forces(loads, th, n)
            secs = []
            for sec in setup.get("sections") or []:
                tq = torque_at(float(sec["z_mm"]), loads, drive, th, n)
                secs.append({"name": sec.get("name", f"z={sec['z_mm']}"), "z_mm": float(sec["z_mm"]),
                             "kt_source": sec.get("kt_source", ""),
                             **section_safety(sec, mat, forces, za, zb, tq, th)})
            reac = []
            if forces:
                for k, zs in ((0, za), (1, zb)):
                    rx = -sum(f[1] * (f[0] - za) for f in forces) / (zb - za)
                    ry = -sum(f[2] * (f[0] - za) for f in forces) / (zb - za)
                    if k == 0:
                        rx, ry = -sum(f[1] for f in forces) - rx, -sum(f[2] for f in forces) - ry
                    mag = np.hypot(rx, ry)
                    reac.append({"z_mm": zs, "max_n": float(mag.max()), "mean_n": float(mag.mean()),
                                 "rms_n": float(np.sqrt((mag ** 2).mean()))})
            # 静挠度：合力最大的转角下，两个平面分别算再合成
            defl = None
            if forces:
                mags = sum(np.hypot(f[1], f[2]) for f in forces)
                i = int(np.argmax(mags))
                zz, yx, tx = static_deflection(lay, (za, zb), [(f[0], float(f[1][i])) for f in forces], mat["elastic_modulus_mpa"])
                _, yy, ty = static_deflection(lay, (za, zb), [(f[0], float(f[2][i])) for f in forces], mat["elastic_modulus_mpa"])
                y, t = np.hypot(yx, yy), np.hypot(tx, ty)
                defl = {"theta_deg": float(np.degrees(th[i])), "max_deflection_mm": float(y.max()),
                        "max_deflection_z_mm": float(zz[int(np.argmax(y))]),
                        "slope_at_supports_rad": [float(t[_node(zz, za)]), float(t[_node(zz, zb)])],
                        "deflection_at_loads_mm": [{"z_mm": f[0], "mm": float(y[_node(zz, f[0])])} for f in forces]}
            per_speed.append({"speed_rpm": n, "sections": secs, "reactions": reac, "deflection": defl})
        nc = critical_speeds(lay, (za, zb), setup.get("masses") or [], mat["elastic_modulus_mpa"], mat["density_kg_m3"])
    except (materials.MissingData, ShaftError, KeyError, TypeError, ValueError) as exc:
        return result.failed("shaft", MODULE["version"], setup, f"没有算出：{exc}")
    n_max = max(speeds)
    data = {"length_mm": lay[-1][1], "supports_mm": [za, zb], "speeds": per_speed, "critical_speeds_rpm": nc,
            "critical_ratio": nc[0] / n_max, "mass_kg": float(sum(math.pi * d * d / 4 * (z1 - z0) for z0, z1, d in lay)
                                                              * mat["density_kg_m3"] * 1e-9)}
    msgs, verdicts = [], []
    req = setup.get("required_safety")
    if req is not None:
        for sp in per_speed:
            for s in sp["sections"]:
                ok = s["S"] >= float(req)
                verdicts.append({"item": f"{s['name']} {sp['speed_rpm']:.0f} r/min 安全系数", "value": s["S"],
                                 "limit": float(req), "status": "pass" if ok else "fail"})
    cr = setup.get("critical_ratio")
    if cr is not None:
        ok = data["critical_ratio"] >= float(cr)
        verdicts.append({"item": "一阶临界转速 / 最高转速", "value": data["critical_ratio"], "limit": float(cr),
                         "status": "pass" if ok else "fail"})
    if verdicts:
        data["verdicts"] = verdicts
        bad = [v["item"] for v in verdicts if v["status"] == "fail"]
        if bad:
            msgs.append("不满足：" + "；".join(bad))
    return result.make("shaft", MODULE["version"], setup, data, limitations=LIMITS, messages=msgs,
                       elapsed_s=time.time() - t0)
