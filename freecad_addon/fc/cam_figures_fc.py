"""问渠CAM 工艺卡零件图的投影（ADR-0106 Q6a）：零件模型 → 主视、俯视、左视三个视图的可见线（折线），程序坐标。

程序坐标与模型坐标：X、Y 相同，Z 平移 z_shift（铣削程序 Z0 在零件顶面：z_shift = −零件最高点）。
投影用 TechDraw.projectEx（隐藏线消除），先把零件转到“视线朝 −Z”的姿态，再沿 Z 投影，平面坐标就是图上的 (u, v)：
- 俯视：(u, v) = (X, Y)，从上往下看；
- 主视：(u, v) = (X, Z)，从 −Y 往 +Y 看；
- 左视（第一角画法放在主视右边）：(u, v) = (−Y, Z)，从 −X 往 +X 看。
"""

from __future__ import annotations

# 视图 → 3×3 旋转（行：新 x、新 y、新 z = 朝观察者）
_ROT = {"top": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
        "front": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
        "left": ((0, -1, 0), (0, 0, 1), (-1, 0, 0))}
_VISIBLE = (0, 1, 3)        # projectEx：可见的硬边、光滑边、轮廓线
_HIDDEN = (5, 6, 8)         # 看不见的（画虚线）


def part_views(shape, z_shift: float = 0.0, deflection: float = 0.05) -> dict:
    import FreeCAD as App
    import TechDraw

    sh = shape.copy()
    sh.translate(App.Vector(0, 0, z_shift))
    bb = sh.BoundBox
    out = {"bbox": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]}
    for name, rot in _ROT.items():
        m = App.Matrix(rot[0][0], rot[0][1], rot[0][2], 0, rot[1][0], rot[1][1], rot[1][2], 0,
                       rot[2][0], rot[2][1], rot[2][2], 0, 0, 0, 0, 1)
        s2 = sh.copy()
        s2.transformShape(m)
        res = TechDraw.projectEx(s2, App.Vector(0, 0, 1))
        for key, idx in ((name, _VISIBLE), (name + "_hidden", _HIDDEN)):
            lines = []
            for k in idx:
                for e in getattr(res[k], "Edges", []):
                    pts = e.discretize(Deflection=deflection)
                    if len(pts) >= 2:
                        lines.append([[round(p.x, 4), round(p.y, 4)] for p in pts])
            out[key] = lines
    return out
