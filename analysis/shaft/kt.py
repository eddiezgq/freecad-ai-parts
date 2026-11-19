"""阶梯轴台阶圆角的理论应力集中系数（有限元，与《机械设计》33.5.4 节同一种做法）。

模型：小径 d 段长 2.5d、大径 D 段长 1.5D，交界处圆角 r；大径端面固定，小径端面加远端力矩（纯弯）或转矩（纯扭），
按面上线性分布（Gmsh 二阶四面体 + CalculiX，`analysis.fea.solve`）。在受拉一侧的圆角弧上布 31 个探针，取主应力：
  α_σ = 最大主应力（按绝对值）/ (M·(d/2)/I)；α_τ = 最大切应力 (σ1 − σ3)/2 / (T·(d/2)/J)，名义应力都按小径。
圆角附近局部加密到 r/5（球内），其余 d/5。r/5 与 r/8 两层网格相差约 0.7 %（10/12/0.5 的算例），结果偏安全一侧（随加密略增）。

要本机有 CalculiX 与 gmsh；不联网。
"""

from __future__ import annotations

import math
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from analysis.common import materials
from analysis.common.solvers import find_ccx

PROBES = 31
METHOD = "有限元：阶梯圆杆纯弯、纯扭，圆角弧上取主应力（analysis.shaft.kt，Gmsh 二阶四面体 + CalculiX）"


class KtError(RuntimeError):
    pass


def _bar(d: float, big: float, r: float, path: Path, bore: float = 0.0) -> tuple[float, float]:
    from analysis.fea.geometry import _LOCK, _gmsh

    ld, lb = 2.5 * d, 1.5 * big
    with _LOCK:
        g = _gmsh()
        g.clear()
        g.model.add("kt")
        occ = g.model.occ
        a = occ.addCylinder(0, 0, 0, 0, 0, ld, d / 2)
        b = occ.addCylinder(0, 0, ld, 0, 0, lb, big / 2)
        out, _ = occ.fuse([(3, a)], [(3, b)])
        occ.synchronize()
        edges = []
        for _, t in g.model.getEntities(1):
            bb = g.model.getBoundingBox(1, t)
            if abs(bb[2] - ld) < 1e-6 and abs(bb[5] - ld) < 1e-6 and abs((bb[3] - bb[0]) / 2 - d / 2) < 1e-6:
                edges.append(t)
        occ.fillet([out[0][1]], edges, [r])
        occ.synchronize()
        if bore > 0:                                      # 空心轴：贯通内孔（机器人关节输出轴，ADR-0100 42.5）
            body = g.model.getEntities(3)
            occ.cut(body, [(3, occ.addCylinder(0, 0, -1, 0, 0, ld + lb + 2, bore / 2))])
            occ.synchronize()
        g.write(str(path))
        g.clear()
    return ld, lb


def _principal(s: dict) -> np.ndarray:
    t = np.array([[s["xx"], s["xy"], s["zx"]], [s["xy"], s["yy"], s["yz"]], [s["zx"], s["yz"], s["zz"]]])
    return np.linalg.eigvalsh(t)


@lru_cache(maxsize=256)
def stepped_bar(d: float, big: float, r: float, bore: float = 0.0) -> dict:
    """返回 {"kt_bending", "kt_torsion", "method", "elements"}；d < big，0 < r；bore > 0 为空心轴（名义应力按空心截面）"""
    from analysis.fea import geometry, solve

    if not 0 < d < big or r <= 0:
        raise KtError("要 0 < d < D、r > 0")
    if not 0 <= bore < d - 2 * 1e-6:
        raise KtError("内孔要小于小径")
    if r >= (big - d) / 2 - 1e-9:
        raise KtError(f"圆角 r {r:g} 不小于台阶高度 {(big - d) / 2:g}，做不出来")
    ccx = find_ccx()
    if ccx is None:
        raise KtError("本机没有 CalculiX（ccx），算不了应力集中系数")
    with tempfile.TemporaryDirectory() as tmp:
        step = Path(tmp) / "bar.step"
        ld, lb = _bar(d, big, r, step, bore)
        faces, _ = geometry.faces(str(step))
        small = next(f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][2]) < 1e-6)
        end = next(f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][2] - (ld + lb)) < 1e-6)
        fil = [f["id"] for f in faces if f["kind"] not in ("plane", "cylinder")]
        i_ = math.pi * (d ** 4 - bore ** 4) / 64
        moment = 1.0e5                                                   # N·mm；线弹性，按比例
        probes = []
        for k in range(PROBES):
            a = math.radians(90 * k / (PROBES - 1))
            probes.append({"id": f"p{k}", "point_mm": [0.0, d / 2 + r - r * math.cos(a), ld - r + r * math.sin(a)]})
        out = {"method": METHOD, "d_mm": d, "D_mm": big, "r_mm": r, **({"bore_mm": bore} if bore else {})}
        for case, vec in (("bending", [moment, 0, 0]), ("torsion", [0, 0, moment])):
            setup = {"material": materials.get("45-QT"),
                     "loads": [{"type": "fixed", "faces": [end]},
                               {"type": "remote_load", "faces": [small], "point_mm": [0, 0, 0], "vector_nmm": vec}],
                     "mesh": {"size_mm": d / 5}, "refine_faces": fil, "probes": probes,
                     "refine": {"center_mm": [0, d / 2 + r * 0.3, ld - r * 0.3], "radius_mm": 1.5 * r + d / 40, "size_mm": r / 5}}
            stats, _, _ = solve.solve(str(step), setup, ccx)
            peak = 0.0
            for p in stats["probes"]:
                w = _principal(p["stress_mpa"])
                v = (w[2] if abs(w[2]) >= abs(w[0]) else abs(w[0])) if case == "bending" else (w[2] - w[0]) / 2
                peak = max(peak, float(v))
            nom = moment * (d / 2) / i_ if case == "bending" else moment * (d / 2) / (2 * i_)
            out[f"kt_{case}"] = peak / nom
            out[f"elements_{case}"] = stats.get("elements") or stats.get("mesh", {}).get("elements")
    return out
