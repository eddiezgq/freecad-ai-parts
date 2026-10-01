"""场景截图（ADR-0032 第 4 节）：在 FreeCAD 界面中重建场景并保存视图为 PNG。

需要显示环境（桌面或 Xvfb）；只能在 FreeCAD 的 Python 中导入。
"""

from __future__ import annotations

import base64
import os
import tempfile

import FreeCAD

from freecad_addon.core.scene import Scene
from freecad_addon.fc.shapes import instance_shape

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


def build_document(scene: Scene):
    """重建（或新建）布局文档：每个实例一个对象，名称为实例名。"""
    if DOC_NAME in FreeCAD.listDocuments():
        FreeCAD.closeDocument(DOC_NAME)
    doc = FreeCAD.newDocument(DOC_NAME)
    for name in sorted(scene.instances):
        comp = scene.component(name)
        obj = doc.addObject("Part::Feature", name)
        obj.Label = name
        obj.Shape = instance_shape(comp, scene.pose(name))
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
    gui.setActiveDocument(doc.Name)
    v = gdoc.activeView()
    gui.updateGui()
    if fit:
        v.fitAll()
        gui.updateGui()
    return gui, v


def sync(scene: Scene) -> dict:
    """gui 后端：把场景显示在用户的 FreeCAD 中（ADR-0036）。"""
    show(scene)
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
