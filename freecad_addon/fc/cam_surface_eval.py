"""问渠CAM Q3c 三维曲面评估（ADR-0106）：用 FreeCAD 3D Surface（平行）、Waterline（等高）出球头刀刀路，
按高度图仿真（球头刀）算出加工后的表面，与零件模型（细三角化后按竖直方向取顶面高度）比：
残留高度 = 加工后 − 零件（正），过切 = 零件 − 加工后（正）。只看零件中间一块（细网格），离窗口边 2 mm 以内不算。

理论残留高度（球头刀半径 R，行距 s）：平面 h = R − √(R² − (s/2)²)；
行距方向上斜 θ 的斜面，法向残留 R − √(R² − (s/(2cos θ))²)，竖直方向再除以 cos θ；
等高（层距 Δz）在斜 θ 的面上，两条等高线沿面相距 Δz / sin θ，法向残留 R − √(R² − (Δz/(2 sin θ))²)，竖直再除以 cos θ。"""

from __future__ import annotations

import math
import time

import numpy as np

from analysis.cam import machines, post, sim
from freecad_addon.fc import cam_fc


def slope_part(theta_deg: float, length: float = 60.0, width: float = 60.0, h0: float = 5.0):
    """顶面沿 +Y 升高 θ 的楔块（θ = 0 是平面）"""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    h1 = h0 + length * math.tan(math.radians(theta_deg))
    f = Part.Face(Part.makePolygon([V(0, 0, 0), V(0, length, 0), V(0, length, h1), V(0, 0, h0), V(0, 0, 0)]))
    return f.extrude(V(width, 0, 0))


def dome_part():
    """80×80×20 的块上一个半径 60 的球冠（顶高 30）"""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    return Part.makeBox(80, 80, 20).fuse(Part.makeSphere(60, V(40, 40, -30)).common(Part.makeBox(80, 80, 40, V(0, 0, 20)))).removeSplitter()


def free_part():
    """80×80 的块，顶面是 5×5 个点插值的 B 样条曲面（起伏 ±2）"""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    pts = [[V(x * 20, y * 20, 12 + 2 * math.sin(0.9 * x) * math.cos(0.7 * y)) for y in range(5)] for x in range(5)]
    srf = Part.BSplineSurface()
    srf.interpolate(pts)
    return Part.makeBox(80, 80, 20).cut(srf.toShape().extrude(V(0, 0, 30)))


def part_height(shape, xs, ys, top: float, tess: float = 0.002) -> np.ndarray:
    """零件在网格 (xs, ys) 上的顶面高度（程序坐标，Z0 在零件顶面）：细三角化后逐个三角形按重心坐标取最高"""
    pts, faces = shape.tessellate(tess)
    P = np.array([[p.x, p.y, p.z - top] for p in pts])
    T = P[np.array(faces)]
    H = np.full((len(xs), len(ys)), -np.inf)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    keep = (T[:, :, 0].max(1) >= xs[0]) & (T[:, :, 0].min(1) <= xs[-1]) & (T[:, :, 1].max(1) >= ys[0]) & (T[:, :, 1].min(1) <= ys[-1])
    for a, b, c in T[keep]:
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-14:
            continue
        i0, i1 = np.searchsorted(xs, min(a[0], b[0], c[0])), np.searchsorted(xs, max(a[0], b[0], c[0]), side="right")
        j0, j1 = np.searchsorted(ys, min(a[1], b[1], c[1])), np.searchsorted(ys, max(a[1], b[1], c[1]), side="right")
        if i1 <= i0 or j1 <= j0:
            continue
        x, y = X[i0:i1, j0:j1], Y[i0:i1, j0:j1]
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / det
        l2 = ((c[1] - a[1]) * (x - c[0]) + (a[0] - c[0]) * (y - c[1])) / det
        l3 = 1 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        sub = H[i0:i1, j0:j1]
        H[i0:i1, j0:j1] = np.where(inside, np.maximum(sub, l1 * a[2] + l2 * b[2] + l3 * c[2]), sub)
    return H


def run_case(shape, kind: str, *, d: float = 6.0, s: float = 2.0, dz: float = 0.5, sample: float = cam_fc.SURF_SAMPLE,
             center=None, win: float = 8.0, h: float = 0.05, stock_top: float = 1.0) -> dict:
    """出一种刀路（surface | waterline），在中间 2win×2win 的窗口里量残留高度与过切"""
    import FreeCAD
    import Path.Tool.Controller as TC
    from Path.Main import Job as PathJob
    from Path.Op import Surface, Waterline

    cam_fc._reload_draft_for_gui()
    doc = FreeCAD.newDocument("WenQuestSurfEval")
    try:
        m = doc.addObject("Part::Feature", "P")
        m.Shape = shape
        doc.recompute()
        job = PathJob.Create("Job", [m])
        op = (Surface if kind == "surface" else Waterline).Create("S")
        tc = TC.Create("T1", cam_fc._bit({"id": "BALL", "kind": "ball_endmill", "diameter_mm": d}), 1)
        tc.HorizFeed, tc.VertFeed = "1000 mm/min", "300 mm/min"
        job.Proxy.addToolController(tc)
        op.ToolController = tc
        op.StepOver = 100 * s / d
        op.SampleInterval = sample
        if kind == "waterline":
            op.LayerMode = "Multi-pass"
            op.setExpression("StepDown", None)
            op.StepDown = dz
        t0 = time.time()
        gui = FreeCAD.GuiUp
        try:
            FreeCAD.GuiUp = 0
            op.touch()
            doc.recompute()
        finally:
            FreeCAD.GuiUp = gui
        t_gen = time.time() - t0
        bb = m.Shape.BoundBox
        top = bb.ZMax
        mv = cam_fc.commands_to_moves(op.Path.Commands, top)
        cx, cy = center or ((bb.XMin + bb.XMax) / 2, (bb.YMin + bb.YMax) / 2)
        box = [cx - win, cy - win, cx + win, cy + win]
        prog = {"number": 1, "title": "eval", "ops": [{"tool": {"n": 1, "d": d}, "spindle": {"rpm": 8000}, "safe": 5.0, "moves": mv}]}
        vmc = machines.get("EX-VMC")
        parsed = sim.parse(post.post(prog, vmc), vmc)
        res = sim.simulate_mill(parsed, {"box": box, "top": stock_top}, {1: {"kind": "ballend", "d": d}}, h=h)
        xs, ys, H = res["x"], res["y"], res["H"]
        P = part_height(m.Shape, xs, ys, top)
        X, Y = np.meshgrid(xs, ys, indexing="ij")
        inner = (X > box[0] + 2) & (X < box[2] - 2) & (Y > box[1] + 2) & (Y < box[3] - 2) & np.isfinite(P)
        dev = (H - P)[inner]
        return {"op": kind, "moves": len(mv), "gen_s": round(t_gen, 1), "over_mm": round(max(0.0, -float(dev.min())), 4),
                "scallop_max_mm": round(float(dev.max()), 4), "scallop_p95_mm": round(float(np.percentile(dev, 95)), 4),
                "cell_mm": h, "sample_mm": sample}
    finally:
        FreeCAD.closeDocument(doc.Name)


def theory_parallel(r: float, s: float, theta_deg: float = 0.0) -> float:
    """平行刀路的竖直残留高度（行距方向上斜 θ）"""
    c = math.cos(math.radians(theta_deg))
    return (r - math.sqrt(r * r - (s / (2 * c)) ** 2)) / c


def theory_waterline(r: float, dz: float, theta_deg: float) -> float:
    """等高刀路在斜 θ 的面上的竖直残留高度"""
    th = math.radians(theta_deg)
    return (r - math.sqrt(r * r - (dz / (2 * math.sin(th))) ** 2)) / math.cos(th)
