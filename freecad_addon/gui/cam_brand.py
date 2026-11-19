"""问渠CAM 版的界面（ADR-0104 产品化第 2 步）：不加零件库工作台，只加“问渠CAM”工作台。

- 工具栏：新建车削 / 铣削作业、新建工序（下拉列出工序类型）、作业设置与计算、工序的重算 / 确认 / 上下移（菜单和右键另有复制、隐藏刀路）（加工树，cam_tree_panels，ADR-0106 Q1）；菜单另有检查 G 代码（ADR-0059 的检查窗口）、授权、设置 AI 密钥、关于；
- 授权、设置对话框与问渠有限元共用（fea_brand），换成本产品的文字和授权功能 cam_pro；
- 第一次启动把 FreeCAD 的启动工作台设成本工作台（以后用户自己改了就不再动）；
- 工作台内部名用 ASCII，激活后再改成本地化标题（同问渠多体动力学，避免中文菜单名乱码）。
免费 / 专业两档的判断在 assist/cam_edition.py；这里只显示。
"""

from __future__ import annotations

import FreeCAD
import FreeCADGui

from assist import cam_edition
from assist.i18n import tr as T
from freecad_addon.gui import fea_brand

WORKBENCH = "WenQuestCamWorkbench"
PARAMS = fea_brand.PARAMS
MENU = "WenQuest CAM"
ADD_MENU = "New operation"
TOOLBAR = ["FAP_CamNewTurnJob", "FAP_CamNewMillJob", "FAP_CamNewOp", "FAP_CamJob", "Separator", "FAP_CamOpRegen",
           "FAP_CamOpConfirm", "FAP_CamOpUp", "FAP_CamOpDown"]
CMDS = ("FAP_CamNewTurnJob", "FAP_CamNewMillJob", "FAP_CamJob", "Separator", "FAP_CamOpRegen", "FAP_CamOpConfirm",
        "FAP_CamOpCopy", "FAP_CamOpUp", "FAP_CamOpDown", "FAP_CamOpHide", "Separator", "FAP_CamCheck", "Separator",
        "FAP_CamLicense", "FAP_CamSetup", "FAP_CamAbout")
OP_MENU = ["FAP_CamOpRegen", "FAP_CamOpConfirm", "FAP_CamOpCopy", "FAP_CamOpUp", "FAP_CamOpDown", "FAP_CamOpHide"]


class Product(fea_brand.Product):
    pro = cam_edition.PRO
    license_title = "问渠CAM：授权"
    setup_title = "问渠CAM：设置 AI 密钥"
    free = "免费版：G 代码检查，车削和 2.5 轴铣编程，两轴车床和三轴加工中心的整机仿真，FANUC 程序。"
    missing = "授权文件里没有问渠CAM 专业版（cam_pro）"
    not_this = "这份授权里没有问渠CAM 专业版（cam_pro）"
    setup_note = ("AI 起草工艺（专业版）要用 AI 服务的密钥：中国用 DeepSeek，其他地方用 Claude，出错自动换另一家。密钥只存在本机用户目录。"
                  "调用 AI 时只发零件特征（直径、长度、槽、螺纹、孔）、材料组和候选刀具的样本范围，不发模型文件。")


def tier_text() -> str:
    return fea_brand.tier_text(Product)


def about_text() -> str:
    v = fea_brand._version()
    lines = [T("问渠CAM"), T(f"版本 {v}") if v else "", "", tier_text(), "",
             T("车削、2.5 轴铣编程：AI 起草工艺，程序逐项核对，人确认；整台机床仿真通过才出程序，程序头写仿真指纹；"
               "后处理没在实机上验证过的，程序头写明。首件须空运行、单段试切确认。"),
             T("验证手册与许可证说明在安装目录里。")]
    return "\n".join(lines)


class CamCheckCommand:
    def GetResources(self):
        return {"MenuText": T("检查 G 代码…"), "ToolTip": T("打开任意 FANUC 风格程序：加工时间、撞料、过切、超程、转速与切削功率")}

    def IsActive(self):
        return True

    def Activated(self):
        from freecad_addon.gui.cam_dialog import CamDialog

        dlg = CamDialog(fea_brand._mw())
        dlg.tabs.setCurrentIndex(dlg.tabs.count() - 1)
        dlg.show()


class CamLicenseCommand:
    def GetResources(self):
        return {"MenuText": T("授权…"), "ToolTip": T("看现在是免费版还是专业版；本机激活码；导入专业版授权文件")}

    def IsActive(self):
        return True

    def Activated(self):
        fea_brand._exec(fea_brand.LicenseDialog(fea_brand._mw(), Product).dlg)


class CamSetupCommand:
    def GetResources(self):
        return {"MenuText": T("设置 AI 密钥…"), "ToolTip": T("AI 起草工艺用的密钥（DeepSeek 或 Claude），只存本机")}

    def IsActive(self):
        return True

    def Activated(self):
        fea_brand._exec(fea_brand.SetupDialog(fea_brand._mw(), Product).dlg)


class CamAboutCommand:
    def GetResources(self):
        return {"MenuText": T("关于问渠CAM"), "ToolTip": T("版本、授权档位与安全检查说明")}

    def IsActive(self):
        return True

    def Activated(self):
        from PySide import QtWidgets

        QtWidgets.QMessageBox.about(fea_brand._mw(), T("关于问渠CAM"), about_text())


class CamWorkbench(FreeCADGui.Workbench):
    MenuText = "WenQuest CAM"
    ToolTip = "WenQuest CAM"

    def Initialize(self):
        # 菜单内部名用 ASCII（中文名建的顶层菜单在中文界面里会乱码），激活后再改成当前语言的标题（_retitle）
        self.appendToolbar(MENU, list(TOOLBAR))
        self.appendMenu(MENU, list(CMDS))
        from freecad_addon.gui import cam_tree_panels

        self.appendMenu([MENU, ADD_MENU], list(cam_tree_panels.ADD_OPS))

    def ContextMenu(self, recipient):
        from freecad_addon.fc import cam_objects as CO

        if any(CO.is_op(o) for o in FreeCADGui.Selection.getSelection()):
            self.appendContextMenu("", list(OP_MENU))

    def Activated(self):
        from PySide import QtCore

        QtCore.QTimer.singleShot(0, _retitle)

    def Deactivated(self):
        return

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def _retitle() -> None:
    from PySide import QtWidgets

    mw = FreeCADGui.getMainWindow()
    for a in mw.menuBar().actions():
        if a.menu() is not None and a.text() in (MENU, "&" + MENU):
            a.setText(T("问渠CAM"))
            for b in a.menu().actions():
                if b.menu() is not None and b.text() in (ADD_MENU, "&" + ADD_MENU):
                    b.setText(T("新建工序"))
    for tb in mw.findChildren(QtWidgets.QToolBar):
        if tb.windowTitle() == MENU:
            tb.setWindowTitle(T("问渠CAM"))


def _start_here() -> None:
    mine = FreeCAD.ParamGet(PARAMS)
    if mine.GetBool("CamStartSet", False):
        return
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString("AutoloadModule", WORKBENCH)
    mine.SetBool("CamStartSet", True)


def register() -> None:
    from freecad_addon.gui import cam_tree_panels

    cam_tree_panels.register()
    FreeCADGui.addCommand("FAP_CamCheck", CamCheckCommand())
    FreeCADGui.addCommand("FAP_CamLicense", CamLicenseCommand())
    FreeCADGui.addCommand("FAP_CamSetup", CamSetupCommand())
    FreeCADGui.addCommand("FAP_CamAbout", CamAboutCommand())
    if WORKBENCH not in FreeCADGui.listWorkbenches():
        wb = type(WORKBENCH, (CamWorkbench,), {"MenuText": T("问渠CAM"), "ToolTip": T("问渠CAM")})
        FreeCADGui.addWorkbench(wb())
    _start_here()
