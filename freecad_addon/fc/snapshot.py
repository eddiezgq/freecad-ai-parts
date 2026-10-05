"""场景截图（ADR-0032 第 4 节）：在 FreeCAD 界面中重建场景并保存视图为 PNG。

需要显示环境（桌面或 Xvfb）；只能在 FreeCAD 的 Python 中导入。
"""

from __future__ import annotations

import base64
import os
import tempfile

import FreeCAD

from freecad_addon.core.port_markers import PART_TRANSPARENCY, TYPE_COLORS, Marker, markers
from freecad_addon.core.scene import Scene
from freecad_addon.fc.shapes import instance_shape, vec

VIEWS = {
    "iso": "viewIsometric",
    "front": "viewFront",
    "rear": "viewRear",
    "left": "viewLeft",
    "right": "viewRight",
    "top": "viewTop",
    "bottom": "viewBottom",
}

# 按品类着色，便于在截图中区分
COLORS = {
    "servo_motor": (0.25, 0.45, 0.85),
    "reducer": (0.90, 0.55, 0.15),
    "drive": (0.35, 0.65, 0.35),
    "bearing": (0.75, 0.30, 0.55),
    "adapter": (0.60, 0.60, 0.60),
}
DOC_NAME = "FapLayout"
_gui_started = False


class SnapshotError(RuntimeError):
    pass


def _gui():
    if FreeCAD.GuiUp:  # 用户打开的 FreeCAD（gui 后端）：直接用已有界面
        import FreeCADGui

        return FreeCADGui
    if not os.environ.get("DISPLAY") and os.name != "nt" and not os.environ.get("WAYLAND_DISPLAY"):
        raise SnapshotError("没有显示环境，无法截图；headless 模式请在 Xvfb 下运行 FreeCAD worker")
    import FreeCADGui

    global _gui_started
    if not _gui_started and getattr(FreeCADGui, "getMainWindow", lambda: None)() is None:
        FreeCADGui.showMainWindow()
    _gui_started = True
    return FreeCADGui


def _matte(vo, color) -> None:
    """哑光材质：正对视线的面不再被高光冲淡（如前视图）。"""
    try:
        mat = FreeCAD.Material()
        mat.DiffuseColor = color
        mat.AmbientColor = tuple(c * 0.5 for c in color)
        mat.SpecularColor = (0.0, 0.0, 0.0)
        mat.EmissiveColor = (0.0, 0.0, 0.0)
        mat.Shininess = 0.0
        vo.ShapeAppearance = [mat]
    except (AttributeError, TypeError, ValueError):
        pass  # 旧版 FreeCAD 没有 ShapeAppearance，保留缺省材质


def _prop(obj, name: str, value: str, doc: str) -> None:
    obj.addProperty("App::PropertyString", name, "AI Parts", doc)
    setattr(obj, name, value)
    obj.setEditorMode(name, 1)  # 只读：由场景决定，改它不会改场景


def _marker_shape(m: Marker):
    """接口标记：端口面上的薄圆盘，加沿端口轴向的小箭头。"""
    import Part

    base, axis = vec(m.origin), vec(m.axis)
    r = m.diameter / 2
    disc = Part.makeCylinder(r, 1.0, base - axis * 0.5, axis)
    tip = min(12.0, max(4.0, r))
    cone = Part.makeCone(min(3.0, r * 0.4), 0.0, tip, base + axis * 0.5, axis)
    return disc.fuse(cone)


def build_document(scene: Scene):
    """重建（或新建）布局文档（ADR-0048 第 4 条）：每个实例一组，含零件（名称为实例名，带组件 id、实例名、
    品类属性）与各机械端口的接口标记（名称 <实例>__<端口>，标签 <实例>.<端口>，带端口属性）。"""
    if DOC_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOC_NAME)
    doc = FreeCAD.newDocument(DOC_NAME)
    by_inst: dict[str, list[Marker]] = {}
    for m in markers(scene):
        by_inst.setdefault(m.instance, []).append(m)
    for name in sorted(scene.instances):
        comp = scene.component(name)
        group = doc.addObject("App::DocumentObjectGroup", f"{name}_group")
        group.Label = f"{name}（{comp.get('model', '')}）"
        obj = doc.addObject("Part::Feature", name)
        obj.Label = name
        obj.Shape = instance_shape(comp, scene.pose(name))
        _prop(obj, "FapInstance", name, "实例名")
        _prop(obj, "FapComponent", comp.get("id", ""), "组件 id")
        _prop(obj, "FapCategory", comp.get("category", ""), "品类")
        group.addObject(obj)
        for m in by_inst.get(name, []):
            mk = doc.addObject("Part::Feature", m.object_name)
            mk.Label = m.ref
            mk.Shape = _marker_shape(m)
            _prop(mk, "FapInstance", m.instance, "实例名")
            _prop(mk, "FapPort", m.port, "端口 id")
            _prop(mk, "FapPortType", m.type, "端口类型")
            _prop(mk, "FapPortDir", m.dir, "方向")
            _prop(mk, "FapConnected", "是" if m.connected else "否", "是否已连接")
            group.addObject(mk)
    doc.recompute()
    return doc


def show(scene: Scene, fit: bool = True):
    """在 FreeCAD 界面中重建布局文档并着色，返回其视图。"""
    gui = _gui()
    doc = build_document(scene)
    gui.updateGui()
    gdoc = gui.getDocument(doc.Name)
    for name in scene.instances:
        vo = gdoc.getObject(name)
        color = COLORS.get(scene.component(name).get("category"), (0.7, 0.7, 0.7))
        vo.ShapeColor = color
        vo.DisplayMode = "Shaded"
        _matte(vo, color)
        vo.Transparency = PART_TRANSPARENCY
    for m in markers(scene):
        vo = gdoc.getObject(m.object_name)
        color = TYPE_COLORS.get(m.type, (0.7, 0.7, 0.7))
        vo.ShapeColor = color
        vo.DisplayMode = "Shaded"
        _matte(vo, color)
    gui.setActiveDocument(doc.Name)
    v = gdoc.activeView()
    gui.updateGui()
    if fit:
        v.fitAll()
        gui.updateGui()
    return gui, v


def sync(scene: Scene) -> dict:
    """gui 后端：把场景显示在用户的 FreeCAD 中（ADR-0036），等轴测视角并适配。"""
    gui, v = show(scene, fit=False)
    v.viewIsometric()
    gui.updateGui()
    v.fitAll()
    gui.updateGui()
    return {"document": DOC_NAME, "instances": sorted(scene.instances)}


def snapshot(scene: Scene, view: str = "iso", width: int = 800, height: int = 600) -> dict:
    if view not in VIEWS:
        raise SnapshotError(f"未知视角 {view}，可选：{'、'.join(VIEWS)}")
    if not (64 <= width <= 4096 and 64 <= height <= 4096):
        raise SnapshotError("宽高须在 64–4096 像素之间")
    gui, v = show(scene, fit=False)
    # 每步之后处理界面事件，否则视角与适配在保存前不生效
    getattr(v, VIEWS[view])()
    gui.updateGui()
    v.fitAll()
    gui.updateGui()
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        v.saveImage(path, width, height, "White")
        with open(path, "rb") as f:
            data = f.read()
    finally:
        os.remove(path)
    if not data.startswith(b"\x89PNG"):
        raise SnapshotError("FreeCAD 未能生成 PNG")
    return {"view": view, "width": width, "height": height, "png_base64": base64.b64encode(data).decode()}
