# -*- coding: utf-8 -*-
"""强制对流换热的温度场（第 16 轮）：在 simpleFoam 算好的流场上解定常对流—扩散方程（自写有限体积，numpy / scipy）。

  Σ_f F_f·T_f − Σ_f Γ_f·(T_N − T_P)·|S_f|/d_f = 0      （对每个单元）
  F_f：面上的体积通量 φ（simpleFoam 写出的 phi，m³/s）；对流项用迎风格式（稳、无振荡）；
  Γ：等效热扩散率 = ν/Pr + ν_t/Pr_t（Pr = 0.73，Pr_t = 0.85）；d_f：两侧单元中心沿面法向的距离；
  边界：零件表面定温；进口来流温度；出口、侧面、对称面零梯度（出口回流时按来流温度）。
空气常物性（25 ℃）；温差不大时浮力、物性随温度变化的影响忽略（强制对流的常用假设）。
为什么不用 OpenFOAM 的 buoyantSimpleFoam：同一网格上它慢一两个数量级（测过：1.6 万单元每步约 1 秒），
而强制对流时温度不反过来影响流动，先算流场再算温度，结果相同。"""
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from cae import cfd as C

PR_T = 0.85


def solve_T(mesh, phi_int, phi_b, nut, fixed, inlet_T, nu=C.AIR["mu"] / C.AIR["rho"], Pr=C.AIR["Pr"], nut_b=None):
    """fixed：{边界名: 壁温 K}；inlet_T：{边界名: 来流温度 K}（进口；出口回流时也按它）。
    返回 (单元温度, {壁面边界: {q W/m², A m², Q W}})"""
    nC = mesh.n_cells
    nI = len(mesh.neighbour)
    own, nei = mesh.owner[:nI], mesh.neighbour
    A = mesh.magSf[:nI]
    n = mesh.Sf[:nI] / A[:, None]
    d = np.abs(((mesh.C[nei] - mesh.C[own]) * n).sum(1))
    nut = np.zeros(nC) if nut is None else np.broadcast_to(nut, (nC,))
    g = nu / Pr + 0.5 * (nut[own] + nut[nei]) / PR_T
    D = g * A / np.maximum(d, 1e-15)
    F = np.asarray(phi_int, float)
    Fp, Fm = np.maximum(F, 0), np.maximum(-F, 0)
    diag = np.zeros(nC)
    b = np.zeros(nC)
    # own 单元：出流 Fp·T_P、入流 −Fm·T_N；nei 单元反之；扩散 D(T_P − T_N)
    np.add.at(diag, own, Fp + D)
    np.add.at(diag, nei, Fm + D)
    rows = np.concatenate([own, nei])
    cols = np.concatenate([nei, own])
    vals = np.concatenate([-(Fm + D), -(Fp + D)])
    flux = {}
    for name, bd in mesh.boundary.items():
        if bd["nFaces"] == 0:
            continue
        sl = mesh.patch(name)
        o = mesh.owner[sl]
        Ab = mesh.magSf[sl]
        Fb = phi_b.get(name)
        Fb = np.zeros(len(o)) if Fb is None else np.broadcast_to(np.asarray(Fb, float), (len(o),))
        if name in fixed:
            nb = mesh.Sf[sl] / Ab[:, None]
            db = np.abs(((mesh.C[o] - mesh.Cf[sl]) * nb).sum(1))
            nw = (nut_b or {}).get(name)
            gw = nu / Pr + (np.asarray(nw, float) / PR_T if nw is not None else 0.0)
            Dw = gw * Ab / np.maximum(db, 1e-15)
            np.add.at(diag, o, Dw)
            np.add.at(b, o, Dw * fixed[name])
            flux[name] = (Dw, o, Ab)
        elif name in inlet_T:
            np.add.at(diag, o, np.maximum(Fb, 0))
            np.add.at(b, o, np.maximum(-Fb, 0) * inlet_T[name])
        else:
            np.add.at(diag, o, np.maximum(Fb, 0))                    # 零梯度：出流按单元值带走
    M = (sp.csr_matrix((vals, (rows, cols)), shape=(nC, nC)) + sp.diags(diag)).tocsr()
    T0 = np.full(nC, float(np.mean(list(inlet_T.values()))))
    try:
        ilu = spla.spilu(M.tocsc(), drop_tol=1e-5, fill_factor=10)
        pre = spla.LinearOperator(M.shape, ilu.solve)
    except Exception:  # noqa: BLE001
        pre = None
    T, info = spla.bicgstab(M, b, x0=T0, M=pre, atol=1e-10, maxiter=4000)
    if info != 0:
        T = spla.spsolve(M.tocsc(), b)
    walls = {}
    rc = C.AIR["rho"] * C.AIR["cp"]
    for name, (Dw, o, Ab) in flux.items():
        q = Dw * (fixed[name] - T[o]) * rc / Ab
        walls[name] = {"q": q, "A": Ab, "Q": float((q * Ab).sum())}
    return T, walls
