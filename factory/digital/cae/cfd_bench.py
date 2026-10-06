# -*- coding: utf-8 -*-
"""流体分析的标准题（第 16 轮 F5）：每道题都和教材公式比，测试和“流体分析”页的“标准题核对”共用。

① 平行平板间层流（Poiseuille）：dp/dx = 12·μ·U / h²
② 绕圆柱层流 Re = 40：阻力系数 C_d ≈ 1.52–1.57（Dennis & Chang 1970 数值解 1.52；Tritton 1959 实验约 1.57）
③ 平板层流强制对流：平均 Nu = 0.664·Re^½·Pr^⅓（Pohlhausen）
④ 平行平板间湍流（k-ω SST + 壁面函数）：摩擦系数按水力直径用 Blasius 公式 C_f = 0.079·Re_Dh^(−¼)；
   换热 Nu_Dh = 0.023·Re^0.8·Pr^0.4（Dittus–Boelter）
二维题用一层网格（前后为 empty）；圆柱用薄层三维网格、前后滑移。"""
import math
import os
import shutil

import numpy as np

from cae import cfd as C
from cae import foam as F

NU = C.AIR["mu"] / C.AIR["rho"]


def _empty(case):
    for f in os.listdir(os.path.join(case, "0")):
        p = os.path.join(case, "0", f)
        t = open(p).read().replace("boundaryField {\n", "boundaryField {\n  frontBack { type empty; }\n")
        open(p, "w").write(t)


def _fresh(case):
    shutil.rmtree(case, ignore_errors=True)
    os.makedirs(case)
    C._common(case, 1)


def poiseuille(case, U=0.01, h=0.02, L=1.0):
    _fresh(case)
    F.write(case, "system/blockMeshDict", """convertToMeters 1;
vertices ( (0 0 0) ({L} 0 0) ({L} {h} 0) (0 {h} 0) (0 0 0.001) ({L} 0 0.001) ({L} {h} 0.001) (0 {h} 0.001) );
blocks ( hex (0 1 2 3 4 5 6 7) (200 20 1) simpleGrading (1 1 1) );
boundary ( inlet {{ type patch; faces ((0 4 7 3)); }} outlet {{ type patch; faces ((1 2 6 5)); }}
 walls {{ type wall; faces ((0 1 5 4) (3 7 6 2)); }} frontBack {{ type empty; faces ((0 3 2 1) (4 5 6 7)); }} );
""".format(L=L, h=h))
    F.run(case, "blockMesh")
    C.flow_case(case, (U, 0, 0), ["walls"], "laminar", nu=NU, end=3000, inlet="inlet", outlet="outlet")
    _set_tight(case)
    _empty(case)
    F.run(case, "simpleFoam")
    m = F.Mesh(case)
    p, _ = F.read_field(case, F.latest_time(case), "p", m)
    x = m.C[:, 0]
    dpdx = (p[np.abs(x - 0.25 * L) < L / 400].mean() - p[np.abs(x - 0.75 * L) < L / 400].mean()) / (0.5 * L)
    theory = 12 * NU * U / h ** 2
    return {"name": "平行平板层流压降", "value": dpdx * C.AIR["rho"], "theory": theory * C.AIR["rho"], "unit": "Pa/m",
            "formula": "dp/dx = 12μU/h²", "error": dpdx / theory - 1}


def _set_tight(case):
    p = os.path.join(case, "system/fvSolution")
    s = open(p).read().replace('residualControl { p 2e-4; U 2e-5; "(k|omega)" 1e-4; }', 'residualControl { p 1e-7; U 1e-8; }')
    open(p, "w").write(s)


def cylinder(case, D=0.02, level=3):
    import build123d as bd
    from cae.thermal_parts import tempfile_step
    _fresh(case)
    stl, box, _, _ = C.stl_by_face(tempfile_step(bd.Cylinder(D * 500, D * 3000)), 1.0)
    cell = D / 4
    a, b = np.array([-15 * D, -30 * D, 0]), np.array([30 * D, 30 * D, cell])
    C.write_mesh_dicts(case, stl, box, "+x", cell, level, bounds=(a, b, D), inside=np.array([-14 * D, -29 * D, cell / 2]))
    F.run(case, "blockMesh")
    F.run(case, "snappyHexMesh", "-overwrite")
    m = F.Mesh(case)
    parts = [k for k in m.boundary if k.startswith("part")]
    U = 40 * NU / D
    C.flow_case(case, (U, 0, 0), parts, "laminar", nu=NU, end=3000, inlet="xmin", outlet="xmax",
                slips=("ymin", "ymax", "zmin", "zmax"))
    _set_tight(case)
    C.run_solver(case, "simpleFoam")
    tt = F.latest_time(case)
    p, _ = F.read_field(case, tt, "p", m)
    Uf, _ = F.read_field(case, tt, "U", m)
    Ft = np.zeros(3)
    for pn in parts:
        a1, b1 = C.wall_forces(m, p, Uf, NU, 1.0, pn)
        Ft += a1 + b1
    Cd = Ft[0] / (0.5 * U * U * D * cell)
    return {"name": "绕圆柱阻力系数（Re = 40）", "value": Cd, "theory": 1.545, "range": [1.52, 1.57], "unit": "",
            "formula": "文献 1.52（Dennis & Chang 数值解）–1.57（Tritton 实验）", "error": Cd / 1.545 - 1, "cells": m.n_cells}


def plate(case, U=1.5, L=0.1, H=0.06, Tw=75.0, Ta=25.0):
    from cae import cfd_heat as CH
    _fresh(case)
    F.write(case, "system/blockMeshDict", """convertToMeters 1;
vertices ( (-{U0} 0 0) (0 0 0) ({L} 0 0) ({L} {H} 0) (0 {H} 0) (-{U0} {H} 0)
            (-{U0} 0 0.001) (0 0 0.001) ({L} 0 0.001) ({L} {H} 0.001) (0 {H} 0.001) (-{U0} {H} 0.001) );
blocks ( hex (0 1 4 5 6 7 10 11) (60 100 1) simpleGrading (0.2 40 1) hex (1 2 3 4 7 8 9 10) (200 100 1) simpleGrading (1 40 1) );
boundary ( inlet {{ type patch; faces ((0 6 11 5)); }} outlet {{ type patch; faces ((2 3 9 8)); }}
 plate {{ type wall; faces ((1 2 8 7)); }} front0 {{ type patch; faces ((0 1 7 6)); }} top {{ type patch; faces ((5 11 10 4) (4 10 9 3)); }}
 frontBack {{ type empty; faces ((0 5 4 1) (1 4 3 2) (6 7 10 11) (7 8 9 10)); }} );
""".format(L=L, H=H, U0=L / 2))
    F.run(case, "blockMesh")
    C.flow_case(case, (U, 0, 0), ["plate"], "laminar", nu=NU, end=3000, inlet="inlet", outlet="outlet", slips=("top", "front0"))
    _set_tight(case)
    _empty(case)
    F.run(case, "simpleFoam")
    m = F.Mesh(case)
    phi, phib = F.read_field(case, F.latest_time(case), "phi", m)
    _, w = CH.solve_T(m, phi, phib, None, {"plate": Tw + 273.15}, {"inlet": Ta + 273.15, "outlet": Ta + 273.15})
    h = w["plate"]["Q"] / (w["plate"]["A"].sum() * (Tw - Ta))
    Re = U * L / NU
    Nu = h * L / C.AIR["k"]
    th = 0.664 * Re ** 0.5 * C.AIR["Pr"] ** (1 / 3)
    return {"name": "平板层流强制对流平均 Nu", "value": Nu, "theory": th, "unit": "", "formula": "Nu = 0.664·Re^½·Pr^⅓",
            "error": Nu / th - 1, "Re": Re, "h": h}


def duct(case, U=19.0, H=0.02, L=1.6, ny=20, Tw=75.0, Ta=25.0):
    from cae import cfd_heat as CH
    _fresh(case)
    F.write(case, "system/blockMeshDict", """convertToMeters 1;
vertices ( (0 0 0) ({L} 0 0) ({L} {H} 0) (0 {H} 0) (0 0 0.001) ({L} 0 0.001) ({L} {H} 0.001) (0 {H} 0.001) );
blocks ( hex (0 1 2 3 4 5 6 7) (400 {ny} 1) simpleGrading (1 1 1) );
boundary ( inlet {{ type patch; faces ((0 4 7 3)); }} outlet {{ type patch; faces ((1 2 6 5)); }}
 walls {{ type wall; faces ((0 1 5 4) (3 7 6 2)); }} frontBack {{ type empty; faces ((0 3 2 1) (4 5 6 7)); }} );
""".format(L=L, H=H, ny=ny))
    F.run(case, "blockMesh")
    C.flow_case(case, (U, 0, 0), ["walls"], "kOmegaSST", nu=NU, end=4000, inlet="inlet", outlet="outlet")
    _set_tight(case)
    _empty(case)
    F.run(case, "simpleFoam")
    m = F.Mesh(case)
    tt = F.latest_time(case)
    p, _ = F.read_field(case, tt, "p", m)
    x = m.C[:, 0]
    dpdx = (p[np.abs(x - 0.55 * L) < L / 800].mean() - p[np.abs(x - 0.875 * L) < L / 800].mean()) / (0.325 * L)
    Cf = dpdx * H / 2 / (0.5 * U * U)
    Dh = 2 * H
    Re = U * Dh / NU
    cf_th = 0.079 * Re ** -0.25
    phi, phib = F.read_field(case, tt, "phi", m)
    nut, nutb = F.read_field(case, tt, "nut", m)
    Uf, _ = F.read_field(case, tt, "U", m)
    T, w = CH.solve_T(m, phi, phib, nut, {"walls": Tw + 273.15}, {"inlet": Ta + 273.15, "outlet": Ta + 273.15}, nut_b={"walls": nutb["walls"]})
    sel = np.abs(x - 0.8 * L) < L / 800
    Tb = (T[sel] * Uf[sel, 0]).sum() / Uf[sel, 0].sum()
    sl = m.patch("walls")
    qx = w["walls"]["q"][np.abs(m.Cf[sl][:, 0] - 0.8 * L) < L / 800].mean()
    Nu = qx / (Tw + 273.15 - Tb) * Dh / C.AIR["k"]
    nu_th = 0.023 * Re ** 0.8 * C.AIR["Pr"] ** 0.4
    return [{"name": "湍流平板通道摩擦系数", "value": Cf, "theory": cf_th, "unit": "", "formula": "C_f = 0.079·Re_Dh^(−¼)（Blasius，按水力直径）",
             "error": Cf / cf_th - 1, "Re": Re},
            {"name": "湍流平板通道换热 Nu", "value": Nu, "theory": nu_th, "unit": "", "formula": "Nu = 0.023·Re^0.8·Pr^0.4（Dittus–Boelter）",
             "error": Nu / nu_th - 1, "Re": Re}]


def all_cases(root):
    out = [poiseuille(os.path.join(root, "poiseuille")), plate(os.path.join(root, "plate"))]
    out += duct(os.path.join(root, "duct"))
    out.append(cylinder(os.path.join(root, "cylinder")))
    return out


if __name__ == "__main__":
    import json
    import sys
    import time
    t = time.time()
    print(json.dumps(all_cases(sys.argv[1] if len(sys.argv) > 1 else "/tmp/cfdbench"), ensure_ascii=False, indent=1, default=float))
    print(round(time.time() - t, 1), "s")
    _ = math
