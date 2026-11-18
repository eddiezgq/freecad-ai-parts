"""大变形梁（ADR-0101，对标 ADAMS FE Part）：离散 Cosserat 杆 = 节点构件 + 几何精确梁单元。

展开：`flex.type == "nonlinear_beam"` 的构件换成 elements + 1 个节点构件（id 为 梁id__n0 … 梁id__nN，模型里也可以直接引用），质量和转动惯量按相邻单元各一半
（ρAL/2、ρI·L/2，截面轴）；模型里挂在这个梁上的运动副、力、输出点、测量量换到离指定点最近的节点上。

单元（两节点 i、j，材料系 Λ = R·B，B 是 t = 0 的截面系 [e₁ 梁轴, e₂ = y, e₃ = z]）：
    θ = log(Λᵢᵀ Λⱼ)（截面坐标），Λₘ = Λᵢ exp(θ/2)
    Γ = Λₘᵀ(pⱼ − pᵢ)/L₀ − e₁，K = θ/L₀
    n = diag(EA, κGA, κGA)(Γ + c Γ̇)，m = diag(GJ, EIy, EIz)(K + c K̇)
    fⱼ = −Λₘ n，fᵢ = −fⱼ；Mⱼ = −Λₘ m − ½ d × fⱼ，Mᵢ = +Λₘ m − ½ d × fⱼ（d = pⱼ − pᵢ）
这是应变能 ½L₀(ΓᵀCΓ + KᵀDK) 的负梯度（Λₘ 随两端转动各转一半）；对整体刚体运动不变。
"""

from __future__ import annotations

import copy
import math

import numpy as np

MM = 1e-3
SNAP_MM = 1e-6            # 指定点到节点的距离超过 梁长 × 这个比例 + 网格半段 就报错（见 _snap）


class NlBeamError(ValueError):
    pass


def _frame(f):
    a = np.asarray(f["from_mm"], float)
    b = np.asarray(f["to_mm"], float)
    ex = b - a
    L = float(np.linalg.norm(ex))
    if L <= 0:
        raise NlBeamError("大变形梁的起点和终点重合")
    ex /= L
    y = np.asarray(f["y_axis"], float)
    y = y - ex * (y @ ex)
    if np.linalg.norm(y) < 1e-9:
        raise NlBeamError("y_axis 与梁轴平行")
    ey = y / np.linalg.norm(y)
    return a, ex, L, np.column_stack([ex, ey, np.cross(ex, ey)])


def expand(model: dict):
    """返回 (新模型, 单元表, 梁信息)；没有大变形梁时原样返回"""
    beams = [b for b in model.get("bodies", []) if (b.get("flex") or {}).get("type") == "nonlinear_beam"]
    if not beams:
        return model, [], {}
    model = copy.deepcopy(model)
    elems, info = [], {}
    new_bodies = []
    for b in model["bodies"]:
        f = b.get("flex") or {}
        if f.get("type") != "nonlinear_beam":
            new_bodies.append(b)
            continue
        a, ex, L, B = _frame(f)
        ne = int(f.get("elements", 20))
        le = L / ne
        rho = f["density_kg_m3"]
        A = f["area_mm2"] * MM ** 2
        Iy, Iz, J = (f[k] * MM ** 4 for k in ("iyy_mm4", "izz_mm4", "ixx_mm4"))
        ids = [f"{b['id']}__n{k}" for k in range(ne + 1)]
        nodes = [a + ex * le * k for k in range(ne + 1)]
        for k in range(ne + 1):
            share = (0.5 if k in (0, ne) else 1.0) * le * MM
            m = rho * A * share
            Js = B @ np.diag([rho * J * share, rho * Iy * share, rho * Iz * share]) @ B.T     # 地面轴
            # 端节点只有半段：转动惯量也减半，太小会让节点自转频率很高，HHT 能扛
            new_bodies.append({"id": ids[k], "mass_kg": m, "cm_mm": nodes[k].tolist(),
                               "inertia_kg_m2": {"ixx": Js[0, 0], "iyy": Js[1, 1], "izz": Js[2, 2],
                                                 "ixy": Js[0, 1], "ixz": Js[0, 2], "iyz": Js[1, 2]},
                               "source": f"大变形梁 {b['id']} 的节点 {k}（ADR-0101）"})
        E, G = f["youngs_modulus_mpa"] * 1e6, f["shear_modulus_mpa"] * 1e6
        kap = float(f.get("shear_factor", 5 / 6))
        C = np.array([E * A, kap * G * A, kap * G * A])
        D = np.array([G * J, E * Iy, E * Iz])
        for k in range(ne):
            elems.append({"beam": b["id"], "k": k, "i_name": ids[k], "j_name": ids[k + 1], "L0": le * MM, "B": B,
                          "C": C, "D": D, "c": float(f.get("stiffness_damping_s", 0.0))})
        info[b["id"]] = {"nodes": ids, "nodes_mm": [n.tolist() for n in nodes], "L_mm": L, "B": B,
                         "area_m2": A, "I": (Iy, Iz), "fiber": (f.get("fiber_y_mm"), f.get("fiber_z_mm"))}
    model["bodies"] = new_bodies
    _remap(model, info)
    return model, elems, info


def _nearest(info, beam, P, where):
    nm = np.asarray(info[beam]["nodes_mm"])
    d = np.linalg.norm(nm - np.asarray(P, float), axis=1)
    k = int(np.argmin(d))
    tol = 1e-3 * info[beam]["L_mm"] + 1e-6
    if d[k] > tol:
        raise NlBeamError(f"{where}：点 {list(P)} 离大变形梁 {beam} 最近的节点还有 {d[k]:.4g} mm；"
                          f"运动副、力要挂在节点上（节点间距 {info[beam]['L_mm'] / (len(nm) - 1):.4g} mm）")
    return info[beam]["nodes"][k]


POINT_KEYS = {"body": ("point_mm",), "body_i": ("point_i_mm", "point_mm"), "body_j": ("point_j_mm", "point_mm")}


def _remap(model, info):
    for sec in ("joints", "forces", "requests", "measures", "geometries"):
        for it in model.get(sec) or []:
            for key, pkeys in POINT_KEYS.items():
                if it.get(key) in info:
                    P = next((it[p] for p in pkeys if p in it), None)
                    if P is None:
                        raise NlBeamError(f"{sec} {it.get('id', '')}：挂在大变形梁 {it[key]} 上要写点（{pkeys[0]}）")
                    it[key] = _nearest(info, it[key], P, f"{sec} {it.get('id', '')}")


def _rot(v):
    th = float(np.linalg.norm(v))
    if th < 1e-14:
        return np.eye(3)
    k = v / th
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(th) * K + (1 - math.cos(th)) * K @ K


def element(sysm, q, qd, f):
    """单元的 (n, m 截面内力, fⱼ, Mᵢ, Mⱼ, pᵢ, pⱼ)；力和力矩都在地面系"""
    from analysis.mbd.dae.system import A_of

    i, j = f["i"], f["j"]
    ri, pi_ = sysm.rp(q, i)
    rj = sysm.rp(q, j)[0]
    Ri = A_of(pi_)
    th_b = sysm.rel_rotvec(q, i, j)                      # 在 i 构件系
    B = f["B"]
    th = B.T @ th_b                                      # 截面坐标
    Lm = Ri @ _rot(0.5 * th_b) @ B                       # 中间材料系
    d = rj - ri
    Gam = Lm.T @ d / f["L0"] - np.array([1.0, 0, 0])
    Kap = th / f["L0"]
    if f["c"] > 0:
        vi, vj = qd[7 * i:7 * i + 3], qd[7 * j:7 * j + 3]
        wi, wj = sysm.omega(q, qd, i), sysm.omega(q, qd, j)
        wm = 0.5 * (wi + wj)
        Gd = Lm.T @ (vj - vi - np.cross(wm, d)) / f["L0"]
        Kd = Lm.T @ (wj - wi) / f["L0"]
        Gam_e, Kap_e = Gam + f["c"] * Gd, Kap + f["c"] * Kd
    else:
        Gam_e, Kap_e = Gam, Kap
    n = f["C"] * Gam_e
    m = f["D"] * Kap_e
    fj = -Lm @ n
    mw = Lm @ m
    half = 0.5 * np.cross(d, fj)
    return n, m, fj, mw - half, -mw - half, ri, rj
