# -*- coding: utf-8 -*-
"""
WenQuest FreeCAD Lab · 阶梯轴（参数化，带倒角和平键槽）
数字工厂版：与 freecad-lab/macros/wq_shaft.py 相同，另外 build() 可指定输出目录和文件名，供发布宏 wq_publish.py 调用。
PARAMS 的默认值就是输出轴 SH-301。

用法：
  - FreeCAD 界面：宏 → 宏… → 选中本文件 → 执行
  - 命令行（不开界面）："C:\\Program Files\\FreeCAD 1.1\\bin\\FreeCADCmd.exe" macros\\wq_shaft.py
修改下面 PARAMS，再运行一次。轴线沿 Z 轴，从左端面 z=0 开始。
"""
import os

PARAMS = {
    # 各轴段 (直径 mm, 长度 mm)，从左到右
    "segments": [(30, 40), (35, 12), (40, 60), (35, 25), (30, 30)],
    "chamfer": 1.5,        # 两端倒角 mm（0 表示不倒角）
    # 平键槽：放在第几段（从 0 数）、键宽 b、槽深 t、槽长 L；None 表示不开键槽
    # 尺寸请按 GB/T 1095 查表，例如 d=40 时 b=12、t=5.0
    "keyway": {"segment": 2, "b": 12.0, "t": 5.0, "L": 45.0},
}

OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "freecad-lab-output")


# ---------------------------------------------------------------- 纯计算与校核
def shaft_layout(segments):
    """返回每段的 (起点 z, 终点 z, 直径) 和总长。"""
    z = 0.0
    out = []
    for d, length in segments:
        if d <= 0 or length <= 0:
            raise ValueError("轴段直径和长度必须为正：{}".format((d, length)))
        out.append((z, z + length, d))
        z += length
    return out, z


def check_keyway(segments, keyway):
    """校核键槽能否放进指定轴段，返回问题列表（空列表表示没问题）。"""
    if not keyway:
        return []
    problems = []
    layout, _ = shaft_layout(segments)
    i = keyway["segment"]
    if not 0 <= i < len(layout):
        return ["键槽所在轴段编号 {} 超出范围 0–{}".format(i, len(layout) - 1)]
    z0, z1, d = layout[i]
    if keyway["L"] > (z1 - z0) - 2:
        problems.append("键槽长 {} mm 超过该轴段长度 {} mm（两端各留至少 1 mm）".format(keyway["L"], z1 - z0))
    if keyway["L"] < keyway["b"]:
        problems.append("键槽长度不能小于键宽")
    if keyway["t"] >= d / 2:
        problems.append("槽深 {} mm 不能达到轴半径 {} mm".format(keyway["t"], d / 2))
    if keyway["b"] >= d:
        problems.append("键宽 {} mm 不能大于轴径 {} mm".format(keyway["b"], d))
    return problems


# ---------------------------------------------------------------- FreeCAD 建模
def build(params=PARAMS, out_dir=None, name="Shaft"):
    import FreeCAD as App
    import Part

    layout, total = shaft_layout(params["segments"])
    problems = check_keyway(params["segments"], params["keyway"])
    if problems:
        raise ValueError("；".join(problems))

    shaft = None
    for z0, z1, d in layout:
        cyl = Part.makeCylinder(d / 2, z1 - z0, App.Vector(0, 0, z0))
        shaft = cyl if shaft is None else shaft.fuse(cyl)
    shaft = shaft.removeSplitter()

    # 两端面外圆倒角：找 z=0 和 z=总长 处的圆形边
    c = params["chamfer"]
    if c > 0:
        ends = [e for e in shaft.Edges
                if hasattr(e.Curve, "Radius")
                and abs(e.BoundBox.ZMin - e.BoundBox.ZMax) < 1e-6
                and (abs(e.BoundBox.ZMin) < 1e-6 or abs(e.BoundBox.ZMin - total) < 1e-6)]
        if ends:
            shaft = shaft.makeChamfer(c, ends)

    # 平键槽：两端半圆的长圆槽，从轴的 +Y 侧往下切 t 深
    kw = params["keyway"]
    if kw:
        z0, z1, d = layout[kw["segment"]]
        b, t, length = kw["b"], kw["t"], kw["L"]
        zc = (z0 + z1) / 2
        y_bottom = d / 2 - t
        height = t + 1.0      # 多切 1 mm 保证切透外圆
        box = Part.makeBox(b, height, length - b,
                           App.Vector(-b / 2, y_bottom, zc - (length - b) / 2))
        # 两端的半圆：竖直方向的圆柱（轴线沿 Y）
        cyl1 = Part.makeCylinder(b / 2, height, App.Vector(0, y_bottom, zc - (length - b) / 2), App.Vector(0, 1, 0))
        cyl2 = Part.makeCylinder(b / 2, height, App.Vector(0, y_bottom, zc + (length - b) / 2), App.Vector(0, 1, 0))
        slot = box.fuse([cyl1, cyl2])
        shaft = shaft.cut(slot).removeSplitter()

    doc = App.ActiveDocument or App.newDocument("WQ_Shaft")
    obj = doc.addObject("Part::Feature", "Shaft")
    obj.Shape = shaft
    doc.recompute()

    out_dir = out_dir or OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, name)
    shaft.exportStep(base + ".step")
    shaft.exportStl(base + ".stl")

    mass_kg = shaft.Volume * 7.85e-6   # 钢 7.85 g/cm³
    App.Console.PrintMessage(
        "阶梯轴：{} 段，总长 {:.1f} mm，体积 {:.0f} mm³，钢制约 {:.2f} kg\n  已导出：{}.step / .stl\n".format(
            len(layout), total, shaft.Volume, mass_kg, base))

    if App.GuiUp:
        import FreeCADGui as Gui
        Gui.activeDocument().activeView().viewIsometric()
        Gui.SendMsgToActiveView("ViewFit")
    return obj, base


if __name__ == "__main__":
    build()
