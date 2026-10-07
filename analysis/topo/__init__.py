"""拓扑优化（ADR-0059，M11 第一步）：平面件 SIMP（固体各向同性材料惩罚），按 Andreassen 等 2011《Efficient topology
optimization in MATLAB using 88 lines of code》的经典算法（numpy / scipy），搬自问渠数字工厂第 14 轮。给定材料用量（体积比）下
刚度最大（柔度最小）。

设置：
  preset: "mbb" | "cantilever" | "bridge" | "bracket" | "custom"
  nelx, nely（单元数，缺省按预设）；volfrac（0.1–0.9，缺省 0.5）；penal（缺省 3）；rmin（过滤半径，单元，缺省 1.5）；
  max_iter（≤ 300，缺省 200）；tol（缺省 0.01）
  custom 时：supports: [{"edge": "left|right|top|bottom", "span": [a, b], "fix": "xy|x|y"}]，
             loads: [{"edge": ..., "at": t, "fx": .., "fy": ..}]；a、b、t 是沿边的位置 0–1（上下边从左量，左右边从下量）
  板件（可选）：length_mm（板长，单元边长 = 长 / nelx）、thickness_mm；有板长时给出轮廓，可生成板件 STEP
结果 data：density（[行，自上而下][列，自左而右]，0–1）、history（[迭代, 柔度, 体积比, 变化]）、compliance（无量纲：E = 1、
  载荷合力 1）、converged、grey（中间密度单元比例）；有板长时 outline（mm，y 向上，原点左下角：[{"outer": [[x, y], ..],
  "holes": [[[x, y], ..], ..]}]）、area_mm2、volume_mm3。
"""

from __future__ import annotations

import math
import time
from pathlib import Path

from analysis.common import result

MODULE = {
    "id": "topo", "name": "拓扑优化", "version": "1",
    "description": "平面件给定材料用量下刚度最大的构形（SIMP），结果拉伸成板件可接着做有限元",
    "python": ["numpy", "scipy"], "solvers": [],
    "install": '安装：pip install -e ".[fea]"（numpy、scipy；生成板件 STEP 另需 gmsh）',
}
EDGES = ("left", "right", "top", "bottom")
PRESETS = {
    "mbb": {"label": "MBB 梁（简支梁的一半，经典算例）", "nelx": 60, "nely": 20,
            "supports": [{"edge": "left", "span": [0, 1], "fix": "x"}, {"edge": "bottom", "span": [1, 1], "fix": "y"}],
            "loads": [{"edge": "top", "at": 0, "fx": 0, "fy": -1}]},
    "cantilever": {"label": "悬臂梁（左边固定，右端中点向下的力）", "nelx": 64, "nely": 32,
                   "supports": [{"edge": "left", "span": [0, 1], "fix": "xy"}],
                   "loads": [{"edge": "right", "at": 0.5, "fx": 0, "fy": -1}]},
    "bridge": {"label": "桥 / 简支梁（两端支承，下边中点向下的力）", "nelx": 80, "nely": 30,
               "supports": [{"edge": "bottom", "span": [0, 0], "fix": "xy"}, {"edge": "bottom", "span": [1, 1], "fix": "y"}],
               "loads": [{"edge": "bottom", "at": 0.5, "fx": 0, "fy": -1}]},
    "bracket": {"label": "支架（左边固定，右下角向下的力）", "nelx": 60, "nely": 40,
                "supports": [{"edge": "left", "span": [0, 1], "fix": "xy"}],
                "loads": [{"edge": "right", "at": 0, "fx": 0, "fy": -1}]},
}
MAX_ELEMENTS = 6000
MBB_REFERENCE = 203.0  # Andreassen 等 2011，60×20、体积比 0.5、p = 3、r_min = 1.5（灵敏度过滤）
LIMITS = ["二维平面应力、线弹性、单一载荷工况；结果是构形建议，尺寸与强度须再用有限元校核",
          "柔度为无量纲值（E = 1、载荷合力 1），只用于比较同一网格下的方案",
          "轮廓按密度 0.5 取单元边界，是阶梯形；加工前宜圆顺"]


class TopoError(ValueError):
    pass


def _ke(nu=0.3):
    import numpy as np

    k = [1 / 2 - nu / 6, 1 / 8 + nu / 8, -1 / 4 - nu / 12, -1 / 8 + 3 * nu / 8,
         -1 / 4 + nu / 12, -1 / 8 - nu / 8, nu / 6, 1 / 8 - 3 * nu / 8]
    return 1 / (1 - nu ** 2) * np.array([
        [k[0], k[1], k[2], k[3], k[4], k[5], k[6], k[7]],
        [k[1], k[0], k[7], k[6], k[5], k[4], k[3], k[2]],
        [k[2], k[7], k[0], k[5], k[6], k[3], k[4], k[1]],
        [k[3], k[6], k[5], k[0], k[7], k[2], k[1], k[4]],
        [k[4], k[5], k[6], k[7], k[0], k[1], k[2], k[3]],
        [k[5], k[4], k[3], k[2], k[1], k[0], k[7], k[6]],
        [k[6], k[3], k[4], k[1], k[2], k[7], k[0], k[5]],
        [k[7], k[2], k[1], k[4], k[3], k[6], k[5], k[0]]])


def _edge_nodes(edge: str, a: float, b: float, nelx: int, nely: int) -> list[tuple[int, int]]:
    """沿边位置 a–b（0–1）上的节点 (i, j)；i 向右 0..nelx，j 向下 0..nely。上下边从左量，左右边从下量。"""
    if edge not in EDGES:
        raise TopoError(f"边只能是 {', '.join(EDGES)}：{edge!r}")
    if not (0 <= a <= b <= 1):
        raise TopoError(f"沿边位置要在 0–1 且起点不大于终点：{a}–{b}")
    if edge in ("top", "bottom"):
        j = 0 if edge == "top" else nely
        return [(i, j) for i in range(round(a * nelx), round(b * nelx) + 1)]
    i = 0 if edge == "left" else nelx
    return [(i, nely - k) for k in range(round(a * nely), round(b * nely) + 1)]


def boundary(supports: list, loads: list, nelx: int, nely: int):
    """支承、载荷 → (固定的自由度, 载荷向量)；节点号 = i·(nely+1) + j，自由度 2n（x）、2n+1（y）。"""
    import numpy as np

    def node(i, j):
        return i * (nely + 1) + j

    if not supports or not loads:
        raise TopoError("要有支承和载荷")
    fixed = set()
    for s in supports:
        a, b = s.get("span", [0, 1])
        fix = s.get("fix", "xy")
        if fix not in ("xy", "x", "y"):
            raise TopoError(f"支承方向只能是 xy、x、y：{fix!r}")
        for i, j in _edge_nodes(s["edge"], float(a), float(b), nelx, nely):
            if "x" in fix:
                fixed.add(2 * node(i, j))
            if "y" in fix:
                fixed.add(2 * node(i, j) + 1)
    xs, ys = {d for d in fixed if d % 2 == 0}, {d for d in fixed if d % 2 == 1}
    if not xs or not ys or len(fixed) < 3:
        raise TopoError("支承不足以限制刚体运动：x、y 两个方向都要有限制，且至少限制 3 个自由度")
    F = np.zeros(2 * (nelx + 1) * (nely + 1))
    for ld in loads:
        t = float(ld.get("at", 0))
        (i, j), = _edge_nodes(ld["edge"], t, t, nelx, nely)
        F[2 * node(i, j)] += float(ld.get("fx", 0))
        F[2 * node(i, j) + 1] += float(ld.get("fy", 0))
    if not F.any():
        raise TopoError("载荷全为 0")
    return np.array(sorted(fixed)), F


def simp(nelx: int, nely: int, supports: list, loads: list, volfrac: float = 0.5, penal: float = 3.0,
         rmin: float = 1.5, max_iter: int = 200, tol: float = 0.01, frames: int = 0) -> dict:
    """frames > 0 时另给迭代过程中均匀取的若干帧密度（0–255，工厂网页放动画用）。"""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import spsolve

    if nelx * nely > MAX_ELEMENTS or nelx < 8 or nely < 4:
        raise TopoError(f"网格 {nelx}×{nely} 不合适：每边至少 8×4，单元数不超过 {MAX_ELEMENTS}")
    if not 0.1 <= volfrac <= 0.9:
        raise TopoError("材料用量（体积比）要在 0.1–0.9 之间")
    if not (1 <= penal <= 5 and 1 <= rmin <= 6 and 1 <= max_iter <= 300 and 0 < tol < 1):
        raise TopoError("penal 1–5、rmin 1–6、max_iter 1–300、tol 0–1")
    Emin, E0 = 1e-9, 1.0
    KE = _ke()
    nel, ndof = nelx * nely, 2 * (nelx + 1) * (nely + 1)
    edof = np.zeros((nel, 8), dtype=int)
    for elx in range(nelx):
        for ely in range(nely):
            n1 = (nely + 1) * elx + ely
            n2 = (nely + 1) * (elx + 1) + ely
            edof[ely + elx * nely] = [2 * n1 + 2, 2 * n1 + 3, 2 * n2 + 2, 2 * n2 + 3, 2 * n2, 2 * n2 + 1, 2 * n1, 2 * n1 + 1]
    iK = np.kron(edof, np.ones((8, 1), dtype=int)).ravel()
    jK = np.kron(edof, np.ones((1, 8), dtype=int)).ravel()
    rr = math.ceil(rmin) - 1
    ih, jh, sh = [], [], []
    for i1 in range(nelx):
        for j1 in range(nely):
            for i2 in range(max(i1 - rr, 0), min(i1 + rr + 1, nelx)):
                for j2 in range(max(j1 - rr, 0), min(j1 + rr + 1, nely)):
                    ih.append(i1 * nely + j1)
                    jh.append(i2 * nely + j2)
                    sh.append(max(0.0, rmin - math.hypot(i1 - i2, j1 - j2)))
    Hf = coo_matrix((sh, (ih, jh)), shape=(nel, nel)).tocsc()
    Hs = np.asarray(Hf.sum(1)).ravel()
    fixed, F = boundary(supports, loads, nelx, nely)
    free = np.setdiff1d(np.arange(ndof), fixed)
    x = np.full(nel, float(volfrac))
    hist, snaps = [], []
    change, it = 1.0, 0
    U = np.zeros(ndof)
    while change > tol and it < max_iter:
        it += 1
        sK = (KE.ravel()[None, :] * (Emin + x ** penal * (E0 - Emin))[:, None]).ravel()
        K = coo_matrix((sK, (iK, jK)), shape=(ndof, ndof)).tocsc()
        K = (K + K.T) / 2
        U[:] = 0
        U[free] = spsolve(K[free][:, free], F[free])
        ue = U[edof]
        ce = np.einsum("ij,jk,ik->i", ue, KE, ue)
        c = float(((Emin + x ** penal * (E0 - Emin)) * ce).sum())
        if not math.isfinite(c) or not np.isfinite(ce).all() or c <= 0:
            raise TopoError("刚度矩阵奇异：支承不足以限制刚体运动（例如只限制了一个方向）")
        dc = -penal * x ** (penal - 1) * (E0 - Emin) * ce
        dc = np.asarray(Hf @ (x * dc)).ravel() / Hs / np.maximum(1e-3, x)
        l1, l2, move = 0.0, 1e9, 0.2
        while (l2 - l1) / (l1 + l2) > 1e-3:  # 最优准则法：二分找拉格朗日乘子
            lm = (l1 + l2) / 2
            xn = np.clip(x * np.sqrt(np.maximum(-dc, 0) / lm), np.maximum(0, x - move), np.minimum(1, x + move))
            if xn.mean() > volfrac:
                l1 = lm
            else:
                l2 = lm
        change = float(np.abs(xn - x).max())
        x = xn
        hist.append([it, round(c, 4), round(float(x.mean()), 4), round(change, 4)])
        if frames:
            snaps.append(x.copy())
    extra = {}
    if frames:
        pick = sorted(set(np.linspace(0, len(snaps) - 1, min(frames, len(snaps))).round().astype(int)))
        extra["frames"] = [{"it": int(k + 1), "density": (snaps[k].reshape(nelx, nely).T * 255).round().astype(np.uint8).tolist()}
                           for k in pick]
    return {**extra, "nelx": nelx, "nely": nely, "iterations": it, "converged": change <= tol, "compliance": hist[-1][1],
            "history": hist, "grey": round(float(((x > 0.1) & (x < 0.9)).mean()), 4),
            "density": x.reshape(nelx, nely).T.round(4).tolist()}


# ------------------------------------------------------------ 轮廓与板件
def _area(loop) -> float:
    return 0.5 * sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1], strict=True))


def _inside(pt, loop) -> bool:
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(loop, loop[1:] + loop[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _simplify(loop):
    """去掉共线的中间点。"""
    out = []
    n = len(loop)
    for k in range(n):
        a, b, c = loop[k - 1], loop[k], loop[(k + 1) % n]
        if (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) != 0:
            out.append(b)
    return out


def outline(density, cell_mm: float, threshold: float = 0.5, min_cells: int = 4) -> list[dict]:
    """密度 ≥ 阈值的单元 → 多边形（mm，y 向上，原点左下角）；外轮廓逆时针、孔顺时针；去掉小于 min_cells 个单元的碎块。
    两个单元只在角点相接时按不相连处理（每块都是简单多边形，便于拉伸与划分网格）。"""
    ny, nx = len(density), len(density[0])

    def filled(i, j):  # i 列（向右），j 行（向下）
        return 0 <= i < nx and 0 <= j < ny and density[j][i] >= threshold

    nxt: dict = {}
    for j in range(ny):
        for i in range(nx):
            if not filled(i, j):
                continue
            y0 = ny - 1 - j
            for cond, a, b in ((not filled(i, j + 1), (i, y0), (i + 1, y0)),
                               (not filled(i + 1, j), (i + 1, y0), (i + 1, y0 + 1)),
                               (not filled(i, j - 1), (i + 1, y0 + 1), (i, y0 + 1)),
                               (not filled(i - 1, j), (i, y0 + 1), (i, y0))):
                if cond:
                    nxt.setdefault(a, []).append(b)
    loops = []
    while nxt:
        start = next(iter(nxt))
        loop, prev, cur = [start], None, start
        while True:
            outs = nxt[cur]
            if len(outs) == 1 or prev is None:
                b = outs[0]
            else:  # 角点相接：左转，使两块分开
                dx, dy = cur[0] - prev[0], cur[1] - prev[1]
                b = max(outs, key=lambda o, dx=dx, dy=dy: dx * (o[1] - cur[1]) - dy * (o[0] - cur[0]))
            outs.remove(b)
            if not outs:
                del nxt[cur]
            prev, cur = cur, b
            if cur == start and start not in nxt:
                break
            if cur == start:
                break
            loop.append(cur)
        loops.append(_simplify(loop))
    outers = [lp for lp in loops if _area(lp) > 0]
    holes = [lp for lp in loops if _area(lp) < 0]
    pieces = []
    for o in sorted(outers, key=_area, reverse=True):
        if _area(o) < min_cells:
            continue
        mine = [h for h in holes if _inside(((h[0][0] + h[1][0]) / 2, (h[0][1] + h[1][1]) / 2), o)]
        pieces.append({"outer": o, "holes": mine})
    # 孔只归最内层包含它的外轮廓（岛中岛）
    for k, p in enumerate(pieces):
        p["holes"] = [h for h in p["holes"] if not any(
            _inside(((h[0][0] + h[1][0]) / 2, (h[0][1] + h[1][1]) / 2), q["outer"]) and _area(q["outer"]) < _area(p["outer"])
            for q in pieces[k + 1:])]
    s = float(cell_mm)
    return [{"outer": [[x * s, y * s] for x, y in p["outer"]], "holes": [[[x * s, y * s] for x, y in h] for h in p["holes"]]}
            for p in pieces]


def outline_area(pieces: list[dict]) -> float:
    return sum(_area([tuple(v) for v in p["outer"]]) + sum(_area([tuple(v) for v in h]) for h in p["holes"]) for p in pieces)


def plate_step(pieces: list[dict], thickness_mm: float, path: str | Path) -> str:
    """轮廓拉伸成板件，写 STEP（与有限元共用 gmsh 会话）。"""
    from analysis.fea.geometry import _LOCK, _gmsh

    if not pieces:
        raise TopoError("没有剩下材料")
    if thickness_mm <= 0:
        raise TopoError("板厚要大于 0")
    path = str(path)
    with _LOCK:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add("topo_plate")
        occ = gmsh.model.occ

        def loop(pts):
            tags = [occ.addPoint(x, y, 0) for x, y in pts]
            lines = [occ.addLine(tags[k], tags[(k + 1) % len(tags)]) for k in range(len(tags))]
            return occ.addCurveLoop(lines)

        vols = []
        for p in pieces:
            surf = occ.addPlaneSurface([loop(p["outer"]), *(loop(h) for h in p["holes"])])
            vols += [t for d, t in occ.extrude([(2, surf)], 0, 0, float(thickness_mm)) if d == 3]
        if len(vols) > 1:
            occ.fuse([(3, vols[0])], [(3, v) for v in vols[1:]])
        occ.synchronize()
        gmsh.write(path)
        gmsh.clear()
    return path


def run(setup: dict) -> dict:
    t0 = time.time()
    preset = setup.get("preset", "mbb")
    try:
        if preset == "custom":
            spec = {"supports": setup.get("supports") or [], "loads": setup.get("loads") or [], "label": "自定"}
            nelx, nely = int(setup.get("nelx", 60)), int(setup.get("nely", 20))
        elif preset in PRESETS:
            spec = PRESETS[preset]
            nelx, nely = int(setup.get("nelx", spec["nelx"])), int(setup.get("nely", spec["nely"]))
        else:
            raise TopoError(f"不认识的算例 {preset!r}；可选 {', '.join([*PRESETS, 'custom'])}")
        params = {k: setup[k] for k in ("volfrac", "penal", "rmin", "max_iter", "tol") if k in setup}
        out = simp(nelx, nely, spec["supports"], spec["loads"], **params)
        msgs = []
        if not out["converged"]:
            msgs.append(f"{out['iterations']} 次迭代内没有收敛（最后一步变化 {out['history'][-1][3]}），可加大 max_iter")
        length = setup.get("length_mm")
        if length is not None:
            if float(length) <= 0:
                raise TopoError("板长要大于 0")
            cell = float(length) / nelx
            pieces = outline(out["density"], cell)
            area = outline_area(pieces)
            out.update(outline=pieces, cell_mm=cell, width_mm=float(length), height_mm=nely * cell, area_mm2=round(area, 3))
            if setup.get("thickness_mm") is not None:
                out["volume_mm3"] = round(area * float(setup["thickness_mm"]), 3)
            if len(pieces) > 1:
                msgs.append(f"轮廓分成 {len(pieces)} 块（有只在角点相接或孤立的材料），生成板件前请检查")
    except TopoError as exc:
        return result.failed("topo", MODULE["version"], setup, str(exc))
    out["preset"], out["label"] = preset, spec["label"]
    checks = []
    std = {"volfrac": 0.5, "penal": 3.0, "rmin": 1.5}
    if preset == "mbb" and (nelx, nely) == (60, 20) and all(float(setup.get(k, v)) == v for k, v in std.items()):
        checks.append(result.check("MBB 梁柔度（60×20、体积比 0.5、p 3、r_min 1.5）", out["compliance"], MBB_REFERENCE,
                                   "Andreassen 等 2011《88 行拓扑优化程序》算例结果"))
    checks.append(result.check("体积比", out["history"][-1][2], float(setup.get("volfrac", 0.5)), "约束：材料用量"))
    return result.make("topo", MODULE["version"], setup, out, checks=checks, limitations=LIMITS, messages=msgs,
                       elapsed_s=time.time() - t0)
