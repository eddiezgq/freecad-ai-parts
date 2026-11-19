"""问渠多体动力学入门例子的零件几何（ADR-0102 第 5 步）：用 FreeCAD 的 Part 直接造，导出 STEP。需要 FreeCAD。

- 曲柄滑块（例子 1）：机架（底板 + 轴承座 + 导轨）、曲柄、连杆、滑块；曲柄轴线沿 z，滑块沿 x 滑动。
- 两关节机械臂（例子 2）：底座（立柱 + 底板）、大臂、小臂；两个关节轴线沿 y（水平），手臂在 xz 平面里转，受重力。
尺寸都是演示用的示例，单位 mm。配合处半径相同（间隙 0），程序按几何找出全部运动副候选。
"""

from __future__ import annotations


def _cyl(r, p, axis, length):
    import FreeCAD as App
    import Part

    return Part.makeCylinder(r, length, App.Vector(*p), App.Vector(*axis))


def _box(x0, x1, y0, y1, z0, z1):
    import FreeCAD as App
    import Part

    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, App.Vector(x0, y0, z0))


def slider_crank():
    """[(对象名, 标签, 形状)]；曲柄半径 30，连杆中心距 100"""
    frame = _box(-40, 200, -40, 20, -30, -20)                              # 底板
    frame = frame.fuse(_box(-20, 20, -20, 20, -20, -2))                   # 轴承座
    frame = frame.fuse(_box(60, 200, -15, 20, -20, -14))                  # 导轨面 z = -14
    frame = frame.fuse(_box(60, 200, 15, 20, -14, 6))                     # 导轨侧壁 y = 15
    frame = frame.cut(_cyl(6, (0, 0, -21), (0, 0, 1), 22)).removeSplitter()
    crank = _cyl(6, (0, 0, -18), (0, 0, 1), 18).fuse(_box(-10, 40, -10, 10, 0, 6))
    crank = crank.fuse(_cyl(4, (30, 0, 6), (0, 0, 1), 6)).removeSplitter()
    rod = _box(25, 135, -6, 6, 6, 12).fuse(_cyl(6, (30, 0, 6), (0, 0, 1), 6)).fuse(_cyl(6, (130, 0, 6), (0, 0, 1), 6))
    rod = rod.cut(_cyl(4, (30, 0, 5), (0, 0, 1), 8)).cut(_cyl(4, (130, 0, 5), (0, 0, 1), 8)).removeSplitter()
    slider = _box(115, 145, -15, 15, -14, 6).fuse(_cyl(4, (130, 0, 6), (0, 0, 1), 6)).removeSplitter()
    return [("Frame", "机架", frame), ("Crank", "曲柄", crank), ("Rod", "连杆", rod), ("Slider", "滑块", slider)]


def arm():
    """[(对象名, 标签, 形状)]；肩关节在 (0, ·, 180)，肘关节在 (300, ·, 180)，轴线沿 y"""
    base = _box(-80, 80, -80, 40, -10, 0).fuse(_box(-30, 30, -40, -10, 0, 200))
    base = base.cut(_cyl(10, (0, -41, 180), (0, 1, 0), 32)).removeSplitter()
    upper = _box(-20, 320, -8, 8, 160, 200).fuse(_cyl(10, (0, -40, 180), (0, 1, 0), 32))
    upper = upper.cut(_cyl(8, (300, -9, 180), (0, 1, 0), 18)).removeSplitter()
    fore = _box(280, 520, 12, 24, 165, 195).fuse(_cyl(8, (300, -8, 180), (0, 1, 0), 20)).removeSplitter()
    return [("Base", "底座", base), ("UpperArm", "大臂", upper), ("Forearm", "小臂", fore)]


def build(doc, which):
    objs = []
    for name, label, shape in {"slider_crank": slider_crank, "arm": arm}[which]():
        o = doc.addObject("Part::Feature", name)
        o.Shape = shape
        o.Label = label
        objs.append(o)
    doc.recompute()
    return objs


def export_step(which, path):
    import FreeCAD as App
    import Import

    doc = App.newDocument(f"src_{which}")
    objs = build(doc, which)
    Import.export(objs, str(path))
    App.closeDocument(doc.Name)
    return path
