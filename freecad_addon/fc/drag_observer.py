"""拖动回写（ADR-0049 第 3 条）：用户在 FreeCAD 中移动 AI Parts 零件后，按新位置调用 place_component。

- 只看零件对象（带 FapComponent）的 Placement；接口标记跟随零件，拖动标记不回写
- 同步显示造成的改动不回写（snapshot.syncing）
- 用户改动停止 0.4 秒后回写一次（拖动过程中会连续改动）；已连接的零件由 place_component 按刚性组整体移动
- 回写调用记为 user；只在 FreeCAD 界面中导入
"""

from __future__ import annotations

import FreeCAD
from PySide import QtCore

from freecad_addon.core.drag import place_args
from freecad_addon.fc import snapshot

DELAY_MS = 400


class DragWriter(QtCore.QObject):
    def __init__(self, host, current_layout):
        """current_layout：返回当前布局状态的函数（校验窗口持有的 layout_state）。"""
        super().__init__()
        self.host = host
        self.current_layout = current_layout
        self.pending: dict[str, tuple] = {}
        self.last: str = ""
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.flush)
        FreeCAD.addDocumentObserver(self)

    def close(self) -> None:
        FreeCAD.removeDocumentObserver(self)

    # FreeCAD 文档观察者
    def slotChangedObject(self, obj, prop):  # FreeCAD 文档观察者的回调名
        if prop != "Placement" or snapshot.syncing() or not hasattr(obj, "FapComponent"):
            return
        if obj.Document.Name != snapshot._target["name"]:
            return
        p = obj.Placement
        self.pending[obj.FapInstance] = ((p.Base.x, p.Base.y, p.Base.z),
                                         (p.Rotation.Axis.x, p.Rotation.Axis.y, p.Rotation.Axis.z), p.Rotation.Angle)
        self.timer.start(DELAY_MS)

    def flush(self) -> list[dict]:
        """把停止后的位姿回写到场景；同一刚性组只回写最后改动的一件（整组随它移动）。"""
        layout = self.current_layout() or {}
        current = {i["instance"]: i for i in layout.get("instances", [])}
        group_of = {i["instance"]: tuple(i.get("group") or [i["instance"]]) for i in layout.get("instances", [])}
        chosen: dict[tuple, dict] = {}
        for inst, (base, axis, angle) in self.pending.items():
            args = place_args(inst, base, axis, angle, current.get(inst))
            if args is not None:
                chosen[group_of.get(inst, (inst,))] = args
        self.pending.clear()
        sent = list(chosen.values())
        for args in sent:
            self.last = f"按拖动后的位置更新 {args['instance']}"
            self.host.call_in_background("place_component", args, lambda out: None, source="user")
        return sent
