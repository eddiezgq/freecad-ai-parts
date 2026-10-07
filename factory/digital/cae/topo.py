# -*- coding: utf-8 -*-
"""平面件拓扑优化（第 14 轮 H6）：SIMP 方法（固体各向同性材料惩罚），按 Andreassen 等 2011《Efficient topology optimization in
MATLAB using 88 lines of code》的经典算法；迭代只留一份，在本仓库 analysis/topo（ADR-0060）。目标：给定材料用量（体积比）下刚度最大（柔度最小）。

单元：平面应力四节点正方形单元，网格 nelx × nely；材料插值 E = Emin + x^p (E0 − Emin)；灵敏度过滤（半径 rmin）；
更新：最优准则法（OC），每步变化不超过 0.2。结果：每个单元的密度 0–1（1 = 有材料），柔度随迭代的变化，以及按密度 0.5 取轮廓
拉伸成板件的 STEP（可以送“仿真与分析”校核）。"""
import numpy as np

PRESETS = {
    "mbb": {"label": "MBB 梁（简支梁的一半，经典算例）", "nelx": 60, "nely": 20,
            "note": "左边是对称面（只限制水平），右下角滚动支座，左上角向下的力"},
    "cantilever": {"label": "悬臂梁（左边固定，右端中点向下的力）", "nelx": 64, "nely": 32, "note": "机械臂连杆、支架"},
    "bridge": {"label": "桥 / 简支梁（两端支承，下边中点向下的力）", "nelx": 80, "nely": 30, "note": "看材料怎么长成拱"},
    "bracket": {"label": "支架（左边固定，右下角向下的力）", "nelx": 60, "nely": 40, "note": "常见的电机、轴承座支架"},
}
MAX_ELEMENTS = 6000


def run(preset="mbb", nelx=None, nely=None, volfrac=0.5, penal=3.0, rmin=1.5, max_iter=200, tol=0.01, frames=24):
    """SIMP 迭代只留一份，在本仓库 analysis/topo（ADR-0060）；支承、载荷按预设（与 analysis 的预设相同）"""
    from analysis import topo as _T
    if preset not in PRESETS:
        raise ValueError("不认识的算例 {}".format(preset))
    nelx = int(nelx or PRESETS[preset]["nelx"])
    nely = int(nely or PRESETS[preset]["nely"])
    spec = _T.PRESETS[preset]
    r = _T.simp(nelx, nely, spec["supports"], spec["loads"], volfrac, penal, rmin, max_iter, tol, frames=frames)
    return {"preset": preset, "label": PRESETS[preset]["label"], "nelx": nelx, "nely": nely, "volfrac": volfrac, "penal": penal,
            "rmin": rmin, "iterations": r["iterations"], "converged": r["converged"], "compliance": r["compliance"],
            "history": r["history"], "grey": r["grey"], "density": r["density"], "frames": r.get("frames", [])}


def layout(preset, density, length_mm):
    """做有限元校核用的平面布置（mm，y 向上，原点在左下角）：MBB 梁按对称面镜像成整根简支梁；支承和载荷处各加一小块“垫块”，
    这样约束、载荷落在一个独立的面上，不会出现一个点上的奇异应力。返回 (密度, 单元边长, 垫块列表, 说明)"""
    d = np.asarray(density, float)
    if preset == "mbb":
        d = np.hstack([d[:, ::-1], d])
    ny, nx = d.shape
    c = float(length_mm) / nx
    W, H = nx * c, ny * c
    a, t = 3 * c, 1.5 * c                     # 垫块：沿边 3 格长、1.5 格厚
    pads = []

    def pad(role, side, x, y):              # 垫块向零件里多伸一格，保证和零件连成一体
        if side == "top":
            r, f = (x - a / 2, H - c, x + a / 2, H + t), (x, H + t, 0, 1)
        elif side == "bottom":
            r, f = (max(0.0, x - a / 2), -t, min(W, x + a / 2), c), (x, -t, 0, -1)
        else:                                  # right
            r, f = (W - c, max(0.0, y - a / 2), W + t, y + a / 2), (W + t, y, 1, 0)
        pads.append({"role": role, "rect": list(r), "face": f})
    if preset in ("mbb", "bridge"):
        pad("support", "bottom", a / 2, 0)
        pad("support", "bottom", W - a / 2, 0)
        pad("load", "top" if preset == "mbb" else "bottom", W / 2, 0)
        note = ("两端支座下的垫块底面按“固定”（比真正的简支——一端可以水平滑动——略刚一点，下弦拉力会小一些）；"
                + ("MBB 梁是简支梁的一半，这里已按对称面镜像成整根梁，载荷加在梁顶中间的垫块上" if preset == "mbb" else "载荷加在下边中间的垫块上"))
    else:
        y = H / 2 if preset == "cantilever" else a / 2
        pad("load", "right", 0, y)
        note = "左边整个端面固定；载荷加在{}的垫块上".format("右端中间" if preset == "cantilever" else "右下角")
    return d, c, pads, note


def fea_part(preset, density, length_mm, thickness_mm):
    """拓扑结果 → 带垫块的板件 STEP，外加垫块外表面的位置（读入后按位置找面号）"""
    from shapely.geometry import box
    d, c, pads, note = layout(preset, density, length_mm)
    g = to_polygon(d, c)
    for p in pads:
        g = g.union(box(*p["rect"]))
    step = _extrude(g, thickness_mm)
    return step, pads, note, {"area_mm2": round(g.area, 1), "volume_mm3": round(g.area * thickness_mm, 1),
                              "width_mm": round(d.shape[1] * c, 1), "height_mm": round(d.shape[0] * c, 1), "cell_mm": round(c, 3)}


def fea_rows(preset, pads, faces, force_n):
    """按位置找垫块的外表面和（悬臂、支架）左端面，排成“仿真与分析”的约束 / 载荷行"""
    def at(px, py, nx_, ny_):
        out = []
        for f in faces:
            n = f.get("normal") or [0, 0, 0]
            if f["kind"] != "plane" or abs(n[0] - nx_) > 1e-3 or abs(n[1] - ny_) > 1e-3:
                continue
            b = f["bbox"]
            if b[0] - 1e-3 <= px <= b[3] + 1e-3 and b[1] - 1e-3 <= py <= b[4] + 1e-3:
                out.append(f["id"])
        return out
    rows = []
    if preset in ("cantilever", "bracket"):
        left = [f["id"] for f in faces if f["kind"] == "plane" and (f.get("normal") or [0])[0] < -0.999 and abs(f["bbox"][0]) < 1e-3]
        rows.append({"kind": "fixed", "faces": left})
    for p in pads:
        fx, fy, nx_, ny_ = p["face"]
        ids = at(fx, fy, nx_, ny_)
        if not ids:
            raise ValueError("没找到垫块的面")
        rows.append({"kind": "fixed", "faces": ids} if p["role"] == "support" else
                    {"kind": "force", "faces": ids, "fx": 0, "fy": -float(force_n), "fz": 0})
    return rows


def to_polygon(density, cell_mm, threshold=0.5):
    """密度 ≥ 0.5 的单元合成多边形（mm，y 向上），去掉很小的碎块"""
    from shapely.geometry import box
    from shapely.ops import unary_union
    d = np.asarray(density)
    ny, nx = d.shape
    cells = [box(i * cell_mm, (ny - 1 - j) * cell_mm, (i + 1) * cell_mm, (ny - j) * cell_mm)
             for j in range(ny) for i in range(nx) if d[j, i] >= threshold]
    g = unary_union(cells).buffer(cell_mm * 0.01).buffer(-cell_mm * 0.01)
    parts = [p for p in getattr(g, "geoms", [g]) if p.area >= 4 * cell_mm * cell_mm]
    return unary_union(parts).simplify(cell_mm * 0.05)


def _extrude(g, thickness_mm):
    import build123d as bd
    from cae.thermal_parts import tempfile_step
    solids = []
    for p in getattr(g, "geoms", [g]):
        if p.is_empty:
            continue
        face = bd.Face(bd.Wire.make_polygon([bd.Vector(x, y, 0) for x, y in list(p.exterior.coords)[:-1]], close=True),
                       [bd.Wire.make_polygon([bd.Vector(x, y, 0) for x, y in list(h.coords)[:-1]], close=True) for h in p.interiors])
        solids.append(bd.extrude(face, thickness_mm))
    if not solids:
        raise ValueError("没有剩下材料")
    shape = solids[0]
    for s in solids[1:]:
        shape = shape + s
    return tempfile_step(shape)
