"""AI Parts 工作台（ADR-0036）：打开对话面板、启用或停止界面桥接。由安装生成的 InitGui.py 调用 register()。"""

from __future__ import annotations

import FreeCAD
import FreeCADGui

_state: dict = {}


def _main_window():
    return FreeCADGui.getMainWindow()


class ChatPanelCommand:
    def GetResources(self):
        return {"MenuText": "AI 对话面板", "ToolTip": "用自然语言完成关节模组的选型、校验与布局"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.panel import ChatPanel

        panel = _state.get("panel")
        if panel is None:
            panel = ChatPanel(parent=_main_window())
            _main_window().addDockWidget(QtCore.Qt.RightDockWidgetArea, panel)
            _state["panel"] = panel
        panel.show()
        panel.raise_()

    def IsActive(self):
        return True


class BridgeCommand:
    def GetResources(self):
        return {"MenuText": "启用 / 停止桥接",
                "ToolTip": "让外部 MCP 客户端（FAP_FREECAD=gui）驱动当前 FreeCAD：只监听本机，令牌写在桥接文件中"}

    def Activated(self):
        from freecad_addon.fc.bridge import Bridge

        bridge = _state.get("bridge")
        if bridge is None:
            bridge = Bridge()
            port = bridge.start()
            _state["bridge"] = bridge
            FreeCAD.Console.PrintMessage(f"AI Parts 桥接已启用：127.0.0.1:{port}，连接信息在 {bridge.path}\n")
        else:
            bridge.stop()
            _state.pop("bridge")
            FreeCAD.Console.PrintMessage("AI Parts 桥接已停止\n")

    def IsActive(self):
        return True


class AiPartsWorkbench(FreeCADGui.Workbench):
    MenuText = "AI Parts"
    ToolTip = "AI 原生零件选型、校验与布局"

    def Initialize(self):
        FreeCADGui.addCommand("FAP_ChatPanel", ChatPanelCommand())
        FreeCADGui.addCommand("FAP_Bridge", BridgeCommand())
        self.appendToolbar("AI Parts", ["FAP_ChatPanel", "FAP_Bridge"])
        self.appendMenu("AI Parts", ["FAP_ChatPanel", "FAP_Bridge"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def register() -> None:
    FreeCADGui.addWorkbench(AiPartsWorkbench())
