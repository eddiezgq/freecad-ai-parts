"""把 FreeCAD 中的操作交给录制器（ADR-0042，issue #146）。只能在 FreeCAD 的 Python 中导入。

- DocumentObserver：对象的增加、删除、属性改动（跳过形体等大数据和纯显示属性），重算后按限频截图
- SelectionObserver：选择（需界面）
- 命令：界面上每个 FreeCAD 命令（QAction，名称如 PartDesign_Pad）被触发时记下（需界面）
"""

from __future__ import annotations

import FreeCAD

from freecad_addon.core.session_log import SessionRecorder

# 不记录的属性：形体数据量大且由其他属性决定；其余是内部或纯显示状态
SKIP_PROPS = frozenset({"Shape", "Proxy", "ExpressionEngine", "Label2", "Visibility", "AttacherEngine",
                        "_Body", "Content", "Shape2DView"})


def _doc_name(obj) -> str:
    doc = getattr(obj, "Document", None)
    return getattr(doc, "Name", "") if doc is not None else ""


def _value(obj, prop):
    try:
        v = obj.getPropertyByName(prop)
    except Exception:  # noqa: BLE001 — 个别属性读取会抛出 FreeCAD 内部异常
        return "?"
    if hasattr(v, "Base") and hasattr(v, "Rotation"):  # Placement：位置与转角写清楚
        r = v.Rotation
        return {"position_mm": [round(c, 6) for c in v.Base], "axis": [round(c, 6) for c in r.Axis],
                "angle_deg": round(r.Angle * 180 / 3.141592653589793, 6)}
    if hasattr(v, "Value") and hasattr(v, "Unit"):  # Quantity：str 为 "25.0 mm"，写成 "25 mm"
        unit = str(v).partition(" ")[2]
        return f"{v.Value:g} {unit}".strip()
    return v


class DocumentObserver:
    """FreeCAD.addDocumentObserver 的回调对象。snapshot 为截图函数（路径 → 是否成功），无界面时为 None。"""

    def __init__(self, recorder: SessionRecorder, snapshot=None):
        self.recorder = recorder
        self.snapshot = snapshot

    def slotCreatedObject(self, obj):
        self.recorder.doc_change(_doc_name(obj), obj.Name, "created", type_id=obj.TypeId)

    def slotDeletedObject(self, obj):
        self.recorder.doc_change(_doc_name(obj), obj.Name, "deleted")

    def slotChangedObject(self, obj, prop):
        if prop in SKIP_PROPS:
            return
        self.recorder.doc_change(_doc_name(obj), obj.Name, "changed", prop, _value(obj, prop))

    def slotRecomputedDocument(self, doc):
        if self.snapshot is None:
            return
        path = self.recorder.next_snapshot()
        if path is not None and self.snapshot(path):
            self.recorder.snapshot_saved(path, view=doc.Name)


class SelectionObserver:
    def __init__(self, recorder: SessionRecorder):
        self.recorder = recorder

    def addSelection(self, doc, obj, sub, pnt):
        self.recorder.event("selection", doc=doc, object=obj, sub=sub or "")


def gui_snapshot(path) -> bool:
    """保存当前 3D 视图（640×480）；没有活动视图时返回 False。"""
    import FreeCADGui

    gdoc = FreeCADGui.ActiveDocument
    view = getattr(gdoc, "ActiveView", None) if gdoc is not None else None
    if view is None or not hasattr(view, "saveImage"):
        return False
    try:
        view.saveImage(str(path), 640, 480, "White")
    except Exception:  # noqa: BLE001
        return False
    return True


class Attachment:
    """把录制器接到 FreeCAD：文档观察者（总是）、选择与命令（有界面时）。detach 后全部解除。"""

    def __init__(self, recorder: SessionRecorder, *, gui: bool | None = None):
        self.recorder = recorder
        self.gui = FreeCAD.GuiUp if gui is None else gui
        self.doc_observer = DocumentObserver(recorder, gui_snapshot if self.gui else None)
        self.sel_observer = SelectionObserver(recorder) if self.gui else None
        self._actions: list = []

    def attach(self) -> None:
        FreeCAD.addDocumentObserver(self.doc_observer)
        if not self.gui:
            return
        import FreeCADGui
        from PySide import QtGui

        FreeCADGui.Selection.addObserver(self.sel_observer)
        mw = FreeCADGui.getMainWindow()
        for action in mw.findChildren(QtGui.QAction):
            name = action.objectName()
            if "_" not in name or not name[:1].isupper():
                continue

            def fire(_checked=False, name=name):
                self.recorder.event("command", name=name)

            action.triggered.connect(fire)
            self._actions.append((action, fire))

    def detach(self) -> None:
        FreeCAD.removeDocumentObserver(self.doc_observer)
        if not self.gui:
            return
        import FreeCADGui

        FreeCADGui.Selection.removeObserver(self.sel_observer)
        for action, fire in self._actions:
            try:
                action.triggered.disconnect(fire)
            except (RuntimeError, TypeError):
                pass
        self._actions.clear()
