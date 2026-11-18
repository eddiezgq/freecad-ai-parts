"""问渠多体动力学版的界面（ADR-0102 第 4 步）：不加零件库工作台，只加“问渠多体动力学”工作台。

- 工具栏与菜单：装配体多体动力学（窗口在 mbd_assembly_panel）；菜单里另有授权、设置 AI 密钥、关于；
- 授权、设置对话框与问渠有限元共用（fea_brand），换成本产品的文字和授权功能 mbd_pro；
- 第一次启动把 FreeCAD 的启动工作台设成本工作台（以后用户自己改了就不再动）。
免费 / 专业两档的判断在 assist/mbd_edition.py；这里只显示。所有显示文字经 T() 中英切换。
"""

from __future__ import annotations

import FreeCAD
import FreeCADGui

from assist import mbd_edition
from assist.i18n import tr as T
from freecad_addon.gui import fea_brand

WORKBENCH = "WenQuestMbdWorkbench"
PARAMS = fea_brand.PARAMS
CMDS = ("FAP_MbdAssembly", "Separator", "FAP_MbdLicense", "FAP_MbdSetup", "FAP_MbdAbout")


class Product(fea_brand.Product):
    pro = mbd_edition.PRO
    license_title = "问渠多体动力学：授权"
    setup_title = "问渠多体动力学：设置 AI 密钥"
    free = "免费版：最多 15 个刚性构件的运动学、静平衡、动力学，曲线、动画与可信度核查。"
    missing = "授权文件里没有问渠多体动力学专业版（mbd_pro）"
    not_this = "这份授权里没有问渠多体动力学专业版（mbd_pro）"
    setup_note = ("AI 帮着挑运动副和报告里的 AI 解释（专业版）要用 AI 服务的密钥：中国用 DeepSeek，其他地方用 Claude，"
                  "出错自动换另一家。密钥只存在本机用户目录。调用 AI 时只发零件名称、体积和程序找出的候选运动副清单，"
                  "或计算结果的摘要，不发模型文件。")


def tier_text() -> str:
    return fea_brand.tier_text(Product)


def about_text() -> str:
    v = fea_brand._version()
    lines = [T("问渠多体动力学"), T(f"版本 {v}") if v else "", "",
             tier_text(), "",
             T("装配体或 STEP 直接算：程序从几何找运动副，AI 帮着挑，人确认。刚体、柔性体（模态、实体应力、大变形梁），"
               "接触、控制、线性化；每次计算带约束残差、能量等可信度核查。AI 只起草与解释，数字由程序填，结果由工程师确认。"),
             T("验证手册与许可证说明在安装目录里。")]
    return "\n".join(lines)


class MbdLicenseCommand:
    def GetResources(self):
        return {"MenuText": T("授权…"), "ToolTip": T("看现在是免费版还是专业版；本机激活码；导入专业版授权文件")}

    def IsActive(self):
        return True

    def Activated(self):
        fea_brand._exec(fea_brand.LicenseDialog(fea_brand._mw(), Product).dlg)


class MbdSetupCommand:
    def GetResources(self):
        return {"MenuText": T("设置 AI 密钥…"), "ToolTip": T("AI 挑运动副与报告解释用的密钥（DeepSeek 或 Claude），只存本机")}

    def IsActive(self):
        return True

    def Activated(self):
        fea_brand._exec(fea_brand.SetupDialog(fea_brand._mw(), Product).dlg)


class MbdAboutCommand:
    def GetResources(self):
        return {"MenuText": T("关于问渠多体动力学"), "ToolTip": T("版本、授权档位与可信度核查说明")}

    def IsActive(self):
        return True

    def Activated(self):
        from PySide import QtWidgets

        QtWidgets.QMessageBox.about(fea_brand._mw(), T("关于问渠多体动力学"), about_text())


class MbdWorkbench(FreeCADGui.Workbench):
    MenuText = "WenQuest MBD"
    ToolTip = "WenQuest MBD"

    def Initialize(self):
        name = T("问渠多体动力学")
        self.appendToolbar(name, ["FAP_MbdAssembly"])
        self.appendMenu(name, list(CMDS))

    def Activated(self):
        return

    def Deactivated(self):
        return

    def GetClassName(self):
        return "Gui::PythonWorkbench"


def _start_here() -> None:
    """第一次启动时把启动工作台设成本工作台；只设一次，用户以后改了不再动"""
    mine = FreeCAD.ParamGet(PARAMS)
    if mine.GetBool("MbdStartSet", False):
        return
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString("AutoloadModule", WORKBENCH)
    mine.SetBool("MbdStartSet", True)


def _assembly_command():
    from freecad_addon.gui.workbench import MbdAssemblyCommand

    class Cmd(MbdAssemblyCommand):
        def GetResources(self):
            return {"MenuText": T("装配体多体动力学"),
                    "ToolTip": T("用当前装配体（或导入 STEP、程序起草运动副）算运动、反力、驱动力矩、模态，播放动画")}

    return Cmd()


def register() -> None:
    FreeCADGui.addCommand("FAP_MbdAssembly", _assembly_command())
    FreeCADGui.addCommand("FAP_MbdLicense", MbdLicenseCommand())
    FreeCADGui.addCommand("FAP_MbdSetup", MbdSetupCommand())
    FreeCADGui.addCommand("FAP_MbdAbout", MbdAboutCommand())
    wb = type(WORKBENCH, (MbdWorkbench,), {"MenuText": T("问渠多体动力学"), "ToolTip": T("问渠多体动力学")})
    FreeCADGui.addWorkbench(wb())
    _start_here()
