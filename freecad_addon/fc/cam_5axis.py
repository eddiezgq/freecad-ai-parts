"""五轴联动刀路的几何（ADR-0106 C3b）：从 FreeCAD 的面、边取刀位要的点和法向，交给 analysis.cam.fiveaxis 算刀位。

- `ruled_rails(face, n)`：直纹面（圆锥、圆柱、平面、直纹 B 样条面）的两条“导轨”——沿直纹线两端的两条边上的等参数点，第 i 点连成一条直纹线；
  另给底边各点的面法向（实体面的外法向，指向刀具一侧）。
- `surface_rows(face, stepover, step)`：曲面上一行一行的接触点和法向（沿较长的参数方向走，行距按弧长取），面的修剪区外的点去掉。
- `edge_points(edge, face, step)`：边上的点和所在面的法向（沿曲线加工）。
长度 mm；需要 FreeCAD。
"""

from __future__ import annotations

import math

import numpy as np


class Cam5AxisError(ValueError):
    pass


def _v(p):
    return np.array([p.x, p.y, p.z], float)


def _straight(curve_pts, tol=1e-6) -> bool:
    p = np.asarray(curve_pts, float)
    a, b = p[0], p[-1]
    L = float(np.linalg.norm(b - a))
    if L < 1e-9:
        return False
    u = (b - a) / L
    d = p - a
    return float(np.max(np.linalg.norm(d - np.outer(d @ u, u), axis=1))) < tol * max(1.0, L)


def ruling_direction(face) -> str:
    """哪个参数方向是直纹线（等参数线是直线）："u" 或 "v"；都不是报错"""
    u0, u1, v0, v1 = face.ParameterRange
    for which in ("v", "u"):
        ok = True
        for t in (0.1, 0.5, 0.9):
            if which == "v":
                u = u0 + t * (u1 - u0)
                pts = [_v(face.valueAt(u, v0 + s * (v1 - v0))) for s in np.linspace(0, 1, 7)]
            else:
                v = v0 + t * (v1 - v0)
                pts = [_v(face.valueAt(u0 + s * (u1 - u0), v)) for s in np.linspace(0, 1, 7)]
            if not _straight(pts):
                ok = False
                break
        if ok:
            return which
    raise Cam5AxisError("这个面不是直纹面（两个参数方向的等参数线都不是直线），不能侧刃铣")


def ruled_rails(face, n: int = 60, bottom_low: bool = True) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """直纹面 → (底边点 n×3, 顶边点 n×3, 底边各点的面外法向 n×3)。直纹线两端哪一端是“底”：bottom_low 时取 Z 低的一端（刀尖在下）"""
    which = ruling_direction(face)
    u0, u1, v0, v1 = face.ParameterRange
    a, b = [], []
    nr = []
    for t in np.linspace(0.0, 1.0, n):
        if which == "v":
            u = u0 + t * (u1 - u0)
            pa, pb, uv = face.valueAt(u, v0), face.valueAt(u, v1), (u, v0)
            uvb = (u, v1)
        else:
            v = v0 + t * (v1 - v0)
            pa, pb, uv = face.valueAt(u0, v), face.valueAt(u1, v), (u0, v)
            uvb = (u1, v)
        a.append(_v(pa))
        b.append(_v(pb))
        nr.append((_v(face.normalAt(*uv)), _v(face.normalAt(*uvb))))
    a, b = np.array(a), np.array(b)
    if bottom_low and float(np.mean(a[:, 2])) > float(np.mean(b[:, 2])):
        return b, a, np.array([x[1] for x in nr])
    return a, b, np.array([x[0] for x in nr])


def surface_rows(face, stepover: float, step: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """曲面上的接触点行：[(点 k×3, 外法向 k×3), …]。沿弧长较长的参数方向走刀，行距 stepover、行内点距 step（弧长，按中线估）"""
    u0, u1, v0, v1 = face.ParameterRange

    def length(fixed_u: bool, c: float) -> float:
        ts = np.linspace(0.0, 1.0, 41)
        pts = np.array([_v(face.valueAt(c, v0 + t * (v1 - v0)) if fixed_u else face.valueAt(u0 + t * (u1 - u0), c)) for t in ts])
        return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))

    # 弧长取最长的那条（球冠、圆锥这种一头大一头小的面，按最长的一行定点距、最宽处定行距）
    lu = max(length(False, v0 + r * (v1 - v0)) for r in (0.0, 0.5, 1.0))
    lv = max(length(True, u0 + r * (u1 - u0)) for r in (0.0, 0.5, 1.0))
    along_u = lu >= lv
    L_along, L_across = (lu, lv) if along_u else (lv, lu)
    n_rows = max(2, math.ceil(L_across / stepover) + 1)
    n_pts = max(2, math.ceil(L_along / step) + 1)
    rows = []
    for r in np.linspace(0.0, 1.0, n_rows):
        pts, nrm = [], []
        for t in np.linspace(0.0, 1.0, n_pts):
            u, v = (u0 + t * (u1 - u0), v0 + r * (v1 - v0)) if along_u else (u0 + r * (u1 - u0), v0 + t * (v1 - v0))
            p = face.valueAt(u, v)
            if not face.isInside(p, 1e-6, True):
                if len(pts) >= 2:
                    rows.append((np.array(pts), np.array(nrm)))
                pts, nrm = [], []
                continue
            pts.append(_v(p))
            nrm.append(_v(face.normalAt(u, v)))
        if len(pts) >= 2:
            rows.append((np.array(pts), np.array(nrm)))
    if not rows:
        raise Cam5AxisError("这个面上取不出刀路点（面太小或修剪区为空）")
    return rows


def edge_points(edge, face, step: float) -> tuple[np.ndarray, np.ndarray]:
    """边上的点（点距 step）和所在面在这些点的外法向"""
    pts = edge.discretize(Distance=float(step))
    if len(pts) < 2:
        raise Cam5AxisError("边太短，取不出点")
    out_p, out_n = [], []
    for p in pts:
        u, v = face.Surface.parameter(p)
        out_p.append(_v(p))
        out_n.append(_v(face.normalAt(u, v)))
    return np.array(out_p), np.array(out_n)
