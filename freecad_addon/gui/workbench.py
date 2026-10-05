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


class LibraryBrowserCommand:
    """零件库浏览器（ADR-0048）：搜零件、看参数出处与复核状态、放入布局；与对话面板共用一个场景。"""

    def GetResources(self):
        return {"MenuText": "零件库", "ToolTip": "按品类、型号与参数搜零件，查看出处与复核状态，放入布局"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.browser import LibraryBrowser

        dock = _state.get("browser")
        if dock is None:
            dock = LibraryBrowser(parent=_main_window())
            _main_window().addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
            _state["browser"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class CheckPanelCommand:
    """校验窗口（ADR-0048）：场景每次改动后自动校验，接口标记按结论着色。"""

    def GetResources(self):
        return {"MenuText": "校验", "ToolTip": "装配即校验：逐项列出结论；接口标记按结论着色（红不通过、黄待确认、绿通过）"}

    def Activated(self):
        _check_panel(show=True)

    def IsActive(self):
        return True


def _check_panel(show: bool = False):
    from PySide import QtCore

    from freecad_addon.gui.check_panel import CheckPanel

    dock = _state.get("checks")
    if dock is None:
        dock = CheckPanel(parent=_main_window())
        _main_window().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        _state["checks"] = dock
    if show:
        dock.show()
        dock.raise_()
    return dock


class ConnectPortsCommand:
    """连接接口（ADR-0048）：选两个接口标记，按端口坐标系对接；与 AI 用同一个 connect_ports。"""

    def GetResources(self):
        return {"MenuText": "连接接口", "ToolTip": "在 3D 视图中按住 Ctrl 选两个接口标记（先选的不动），对接这两个接口"}

    def Activated(self):
        from freecad_addon.gui.check_panel import PortConnector

        _check_panel(show=True)  # 连接后的结论显示在校验窗口
        conn = _state.setdefault("connector", PortConnector())
        conn.connect_selected()

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


class RecordCommand:
    """开始 / 停止操作录制（ADR-0042）：默认关闭，录制时状态栏显示“● 录制中”，会话包只存本机。"""

    video = False

    def GetResources(self):
        return {"MenuText": "开始 / 停止录制",
                "ToolTip": "录下操作过程（命令、文档改动、对话、截图）供 AI 学习；只存本机，去掉密钥"}

    def Activated(self):
        from freecad_addon.gui import recording

        if recording.recorder().active:
            rating, note = recording.ask_rating()
            path = recording.stop(rating, note)
            FreeCAD.Console.PrintMessage(f"AI Parts 录制已保存：{path}\n")
        else:
            path = recording.start(video=self.video)
            FreeCAD.Console.PrintMessage(f"AI Parts 开始录制：{path}\n")
            if recording._video_note:
                FreeCAD.Console.PrintWarning(f"AI Parts 未录视频：{recording._video_note}；其他内容照常录制\n")


class RecordVideoCommand(RecordCommand):
    """同上，另用 ffmpeg 录 FreeCAD 主窗口的视频（可选，ADR-0042）。"""

    video = True

    def GetResources(self):
        return {"MenuText": "开始 / 停止录制（含视频）",
                "ToolTip": "同“开始 / 停止录制”，另用 ffmpeg 录下 FreeCAD 主窗口的视频（需要 ffmpeg；Linux X11 与 Windows）"}

    def IsActive(self):
        return True


class AiPartsWorkbench(FreeCADGui.Workbench):
    MenuText = "AI Parts"
    ToolTip = "AI 原生零件选型、校验与布局"

    def Initialize(self):
        FreeCADGui.addCommand("FAP_ChatPanel", ChatPanelCommand())
        FreeCADGui.addCommand("FAP_Browser", LibraryBrowserCommand())
        FreeCADGui.addCommand("FAP_Connect", ConnectPortsCommand())
        FreeCADGui.addCommand("FAP_Checks", CheckPanelCommand())
        FreeCADGui.addCommand("FAP_Bridge", BridgeCommand())
        FreeCADGui.addCommand("FAP_Record", RecordCommand())
        FreeCADGui.addCommand("FAP_RecordVideo", RecordVideoCommand())
        tools = ["FAP_ChatPanel", "FAP_Browser", "FAP_Connect", "FAP_Checks", "FAP_Bridge", "FAP_Record"]
        self.appendToolbar("AI Parts", tools)
        self.appendMenu("AI Parts", [*tools, "FAP_RecordVideo"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def register() -> None:
    FreeCADGui.addWorkbench(AiPartsWorkbench())
