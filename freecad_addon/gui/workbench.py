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
            _check_panel()  # 校验与方案记录随场景改动更新（ADR-0049）
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
            _check_panel()  # 校验与方案记录随场景改动更新（ADR-0049）
            _main_window().addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
            _state["browser"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class SelectionCommand:
    """选型面板（ADR-0051）：填需求、查找方案、一键放入布局；不经过对话。"""

    def GetResources(self):
        return {"MenuText": "选型", "ToolTip": "填扭矩、转速等需求，列出校验过的电机 + 减速器 + 驱动器方案，一键放入布局"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.selection_panel import SelectionPanel

        dock = _state.get("selection")
        if dock is None:
            dock = SelectionPanel(parent=_main_window())
            _check_panel()  # 放入后的结论显示在校验窗口
            _main_window().addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
            _state["selection"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class BomCommand:
    """BOM 面板（ADR-0051）：由当前场景列出物料清单，随场景刷新，可导出 CSV / JSON。"""

    def GetResources(self):
        return {"MenuText": "BOM", "ToolTip": "当前场景的物料清单：厂商、型号、数量、质量、数据出处与复核状态；可导出"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.bom_panel import BomPanel

        dock = _state.get("bom")
        if dock is None:
            dock = BomPanel(parent=_main_window())
            _main_window().addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)
            _state["bom"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class EnterpriseLibraryCommand:
    """企业库（ADR-0055）：选择企业自己的零件库文件夹，叠加在公共库上；重启 FreeCAD 后生效。"""

    def GetResources(self):
        return {"MenuText": "企业库", "ToolTip": "选择或新建企业自己的零件库文件夹（数据只存在企业那边），叠加在公共库上"}

    def Activated(self):
        from PySide import QtWidgets

        from freecad_addon.core import library_choice

        current = library_choice.enterprise_dir({}, library_choice.read_settings())
        path = QtWidgets.QFileDialog.getExistingDirectory(_main_window(), "选择企业库文件夹（空文件夹将新建企业库）",
                                                          str(current or ""))
        if not path:
            return
        from pathlib import Path

        from kb.enterprise import EnterpriseLibrary

        try:
            EnterpriseLibrary(Path(path), create=True)
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            QtWidgets.QMessageBox.warning(_main_window(), "企业库", f"不能使用这个文件夹：{exc}")
            return
        library_choice.write_setting("enterprise_library", path)
        QtWidgets.QMessageBox.information(_main_window(), "企业库",
                                          f"企业库已设为：\n{path}\n\n重启 FreeCAD 后生效。企业库的数据只存在这个文件夹里。")

    def IsActive(self):
        return True


class NewPartCommand:
    """新建零件向导（M9 第四步）：从厂商规格书建企业自己的零件，存入企业库后可选型、放入、出 BOM。"""

    def GetResources(self):
        return {"MenuText": "新建零件", "ToolTip": "选品类与厂商规格书（PDF / Excel），AI 抽取、代码核对、逐项确认，生成新零件存入企业库"}

    def Activated(self):
        from freecad_addon.gui.host import get_host
        from freecad_addon.gui.import_dialog import NewPartDialog

        dlg = NewPartDialog(get_host().library(), parent=_main_window())
        if dlg.exec() and dlg.saved:
            from PySide import QtWidgets

            QtWidgets.QMessageBox.information(_main_window(), "新建零件",
                                              f"已存入企业库：{dlg.saved['id']}\n可在库浏览器、选型窗口中使用。")

    def IsActive(self):
        return True


class AnalysesCommand:
    """分析模块一览（ADR-0056）：本机各分析模块是否可用、缺什么。"""

    def GetResources(self):
        return {"MenuText": "分析模块", "ToolTip": "多体动力学、有限元、疲劳、热分析、设计优化、数字孪生：本机运行，查看可用状态"}

    def Activated(self):
        from freecad_addon.gui.analysis_list import AnalysisListDialog

        AnalysisListDialog(_main_window()).exec()

    def IsActive(self):
        return True


class MbdCommand:
    """多体动力学窗口（ADR-0056）：机械臂或机构的关节力矩、转速、功率，结果送去选型。"""

    def GetResources(self):
        return {"MenuText": "多体动力学", "ToolTip": "机械臂或常用机构在给定运动下各关节需要的力矩、转速、功率（本机 MuJoCo），可直接送去选型"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.mbd_panel import MbdPanel

        def selection():
            SelectionCommand().Activated()
            return _state.get("selection")

        dock = _state.get("mbd")
        if dock is None:
            dock = MbdPanel(parent=_main_window(), selection=selection)
            _main_window().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            _state["mbd"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class FeaCommand:
    """有限元 · 疲劳窗口（ADR-0056）：选零件、选面加约束与载荷、本机计算、着色显示、疲劳寿命。"""

    def GetResources(self):
        return {"MenuText": "有限元 · 疲劳", "ToolTip": "零件的应力、安全系数、固有频率（本机 CalculiX），并按载荷谱算疲劳寿命"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.fea_panel import FeaPanel

        dock = _state.get("fea")
        if dock is None:
            dock = FeaPanel(parent=_main_window(), mbd_result=lambda: getattr(_state.get("mbd"), "result", None))
            _main_window().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            _state["fea"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class OptimizeCommand:
    """设计优化（ADR-0056）：阶梯轴在安全系数与疲劳要求下最轻的直径，可生成到 FreeCAD。"""

    def GetResources(self):
        return {"MenuText": "设计优化", "ToolTip": "阶梯轴各段直径自动寻优：满足安全系数与疲劳要求下最轻（Optuna 驱动本机有限元）"}

    def Activated(self):
        from freecad_addon.gui.optimize_dialog import OptimizeDialog

        dlg = _state.get("optimize")
        if dlg is None:
            dlg = OptimizeDialog(_main_window())
            _state["optimize"] = dlg
        dlg.show()
        dlg.raise_()

    def IsActive(self):
        return True


class TopoCommand:
    """拓扑优化（ADR-0059）：平面件给定材料用量下刚度最大的构形，结果拉伸成板件放进 FreeCAD。"""

    def GetResources(self):
        return {"MenuText": "拓扑优化", "ToolTip": "平面件给定材料用量下刚度最大的构形（SIMP，本机计算），可生成板件做有限元校核"}

    def Activated(self):
        from freecad_addon.gui.topo_dialog import TopoDialog

        dlg = _state.get("topo")
        if dlg is None:
            dlg = TopoDialog(_main_window())
            _state["topo"] = dlg
        dlg.show()
        dlg.raise_()

    def IsActive(self):
        return True


class CamCommand:
    """数控编程（ADR-0059）：阶梯轴车削、2.5 轴铣削生成 G 代码；检查任意 FANUC 风格程序。"""

    def GetResources(self):
        return {"MenuText": "数控编程", "ToolTip": "生成车削、铣削 G 代码；检查任意程序（含 FreeCAD CAM 输出）的时间、撞料、过切、超程与切削功率"}

    def Activated(self):
        from freecad_addon.gui.cam_dialog import CamDialog

        dlg = _state.get("cam")
        if dlg is None:
            dlg = CamDialog(_main_window())
            _state["cam"] = dlg
        dlg.show()
        dlg.raise_()

    def IsActive(self):
        return True


class CfdCommand:
    """流体分析（ADR-0059）：选中零件进虚拟风洞，算阻力与散热（本机 OpenFOAM）。"""

    def GetResources(self):
        return {"MenuText": "流体分析", "ToolTip": "虚拟风洞：阻力、各面压力，强制对流散热量与散热系数（需本机装 OpenFOAM）"}

    def Activated(self):
        from freecad_addon.gui.cfd_dialog import CfdDialog

        dlg = _state.get("cfd")
        if dlg is None:
            dlg = CfdDialog(_main_window())
            _state["cfd"] = dlg
        dlg.show()
        dlg.raise_()

    def IsActive(self):
        return True


class TwinCommand:
    """数字孪生（ADR-0057）：当前布局的减速器、轴承 + 运行记录 → 已用寿命、剩余寿命、报警、假如。"""

    def GetResources(self):
        return {"MenuText": "数字孪生", "ToolTip": "按零件样本参数与运行记录算已用寿命、剩余寿命与报警，可做“假如”分析"}

    def Activated(self):
        from PySide import QtCore

        from freecad_addon.gui.twin_panel import TwinPanel

        dock = _state.get("twin")
        if dock is None:
            dock = TwinPanel(parent=_main_window())
            _main_window().addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
            _state["twin"] = dock
        dock.show()
        dock.raise_()

    def IsActive(self):
        return True


class PublishCommand:
    """发布到工厂（ADR-0058）：当前方案的 BOM、需求、校验结论与布局 STEP 发到本地工厂。"""

    def GetResources(self):
        return {"MenuText": "发布到工厂", "ToolTip": "把当前方案（BOM、需求、校验结论、布局 STEP）发到本地数字工厂"}

    def Activated(self):
        from freecad_addon.gui.host import get_host
        from freecad_addon.gui.publish_dialog import PublishDialog

        PublishDialog(get_host(), _state.get("checks"), _main_window()).exec()

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


class RestoreProjectCommand:
    """恢复方案（ADR-0049）：从打开的 .FCStd 中的方案记录重建场景，之后的改动显示在这个文档中。"""

    def GetResources(self):
        return {"MenuText": "恢复方案", "ToolTip": "从当前文档保存的 AI Parts 方案记录恢复零件、连接与需求"}

    def Activated(self):
        panel = _check_panel(show=True)
        err = panel.restore(lambda notes: [FreeCAD.Console.PrintMessage(f"AI Parts 恢复方案：{n}\n") for n in notes])
        if err:
            FreeCAD.Console.PrintWarning(f"AI Parts：{err}\n")

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None


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
        FreeCADGui.addCommand("FAP_Selection", SelectionCommand())
        FreeCADGui.addCommand("FAP_Bom", BomCommand())
        FreeCADGui.addCommand("FAP_Enterprise", EnterpriseLibraryCommand())
        FreeCADGui.addCommand("FAP_NewPart", NewPartCommand())
        FreeCADGui.addCommand("FAP_Analyses", AnalysesCommand())
        FreeCADGui.addCommand("FAP_Mbd", MbdCommand())
        FreeCADGui.addCommand("FAP_Fea", FeaCommand())
        FreeCADGui.addCommand("FAP_Optimize", OptimizeCommand())
        FreeCADGui.addCommand("FAP_Twin", TwinCommand())
        FreeCADGui.addCommand("FAP_Topo", TopoCommand())
        FreeCADGui.addCommand("FAP_Cam", CamCommand())
        FreeCADGui.addCommand("FAP_Cfd", CfdCommand())
        FreeCADGui.addCommand("FAP_Publish", PublishCommand())
        FreeCADGui.addCommand("FAP_Connect", ConnectPortsCommand())
        FreeCADGui.addCommand("FAP_Checks", CheckPanelCommand())
        FreeCADGui.addCommand("FAP_Restore", RestoreProjectCommand())
        FreeCADGui.addCommand("FAP_Bridge", BridgeCommand())
        FreeCADGui.addCommand("FAP_Record", RecordCommand())
        FreeCADGui.addCommand("FAP_RecordVideo", RecordVideoCommand())
        tools = ["FAP_ChatPanel", "FAP_Selection", "FAP_Browser", "FAP_Connect", "FAP_Checks", "FAP_Bom",
                 "FAP_Restore", "FAP_Bridge", "FAP_Record"]
        self.appendToolbar("AI Parts", tools)
        self.appendMenu("AI Parts", [*tools, "FAP_Enterprise", "FAP_NewPart", "FAP_Analyses", "FAP_Mbd", "FAP_Fea", "FAP_Optimize", "FAP_Topo", "FAP_Cam", "FAP_Cfd", "FAP_Twin", "FAP_Publish", "FAP_RecordVideo"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def register() -> None:
    FreeCADGui.addWorkbench(AiPartsWorkbench())
