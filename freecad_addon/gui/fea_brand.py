"""问渠有限元版的界面（ADR-0096 第 5 步）：不加零件库工作台，只在 FEM 工作台里加按钮，在“帮助”菜单里加授权、设置、关于。

- “求解”菜单与工具栏：一句话起草、计算并核查、出报告（fem_commands），菜单里另有热分析 · 疲劳；
- “帮助”菜单（“关于”前面）：授权、设置 AI 密钥、关于问渠有限元；
- 第一次启动把 FreeCAD 的启动工作台设成 FEM（以后用户自己改了就不再动）。
免费 / 专业两档的判断在 assist/fea_edition.py；这里只显示。所有显示文字经 T() 中英切换。
"""

from __future__ import annotations

import os

import FreeCAD
import FreeCADGui

from assist import fea_edition
from assist.i18n import tr as T

NAME = "问渠有限元"
HELP_ANCHOR = "Std_About"
HELP_CMDS = ("FAP_FeaLicense", "FAP_FeaSetup", "FAP_FeaAbout")
PARAMS = "User parameter:BaseApp/Preferences/Mod/FreecadAiParts"


def _mw():
    return FreeCADGui.getMainWindow()


def tier_text() -> str:
    """现在是哪一档、为什么（给界面与关于页）"""
    from licensing import runtime

    if not runtime.license_path().is_file():
        why = "还没有导入专业版授权。"
    else:
        v = runtime.current()
        if v.allows(fea_edition.PRO):
            return T(f"专业版：{v.licensee}，到 {v.expires}")
        why = v.reason if not v.valid else "授权文件里没有问渠有限元专业版（fea_pro）"
    return T("免费版：单个实体零件的静力、模态、线性屈曲与可信度核查。") + "\n" + T(why)


def _version() -> str:
    import json
    from pathlib import Path

    try:
        m = json.loads((Path(fea_edition.EDITION_FILE).parent / "BUNDLE.json").read_text(encoding="utf-8"))
        return str(m.get("commit") or "")
    except (OSError, ValueError):
        return ""


class LicenseDialog:
    """授权：现在的档位、本机激活码、导入授权文件"""

    def __init__(self, parent=None):
        from PySide import QtWidgets

        from licensing.fingerprint import activation_code

        self.dlg = QtWidgets.QDialog(parent)
        self.dlg.setWindowTitle(T("问渠有限元：授权"))
        self.dlg.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self.dlg)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        form = QtWidgets.QFormLayout()
        code = QtWidgets.QLineEdit()
        code.setReadOnly(True)
        try:
            code.setText(activation_code())
        except RuntimeError as exc:
            code.setText(T(str(exc)))
        copy = QtWidgets.QPushButton(T("复制"))
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(code.text()))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(code)
        row.addWidget(copy)
        form.addRow(T("本机激活码"), row)
        lay.addLayout(form)
        hint = QtWidgets.QLabel(T("购买专业版后，把激活码发给我们；收到授权文件后点“导入授权文件”。授权只决定能不能用专业版功能，"
                                  "不改变任何计算结果和核查结论。"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        imp = QtWidgets.QPushButton(T("导入授权文件…"))
        imp.clicked.connect(self.import_file)
        lay.addWidget(imp)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.dlg.reject)
        lay.addWidget(close)
        self.refresh()

    def refresh(self) -> None:
        self.status.setText(tier_text())

    def import_file(self, path: str | None = None) -> bool:
        """导入授权文件（path 给了就不弹选择框，测试用）；校验通过才复制到本机用户目录"""
        import shutil
        from pathlib import Path

        from PySide import QtWidgets

        from licensing import runtime

        if not path:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self.dlg, T("选择授权文件"), "", T("授权文件 (*.json);;所有文件 (*)"))
        if not path:
            return False
        v = runtime.current(Path(path))
        if not v.allows(fea_edition.PRO):
            why = v.reason if not v.valid else "这份授权里没有问渠有限元专业版（fea_pro）"
            QtWidgets.QMessageBox.warning(self.dlg, T("授权"), T(f"这个授权文件不能用：{why}"))
            return False
        dest = runtime.license_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        self.refresh()
        return True


class SetupDialog:
    """设置：AI 服务的密钥（只存本机用户目录）。不填也能用免费版和专业版的计算、报告；AI 起草与解释要密钥"""

    def __init__(self, parent=None):
        from PySide import QtWidgets

        from freecad_addon.core import first_run
        from llm_gateway import load_dotenv

        load_dotenv()
        status = first_run.key_status(os.environ)
        self.dlg = QtWidgets.QDialog(parent)
        self.dlg.setWindowTitle(T("问渠有限元：设置 AI 密钥"))
        self.dlg.setMinimumWidth(520)
        lay = QtWidgets.QVBoxLayout(self.dlg)
        note = QtWidgets.QLabel(T("AI 一句话起草和 AI 解释（专业版）要用 AI 服务的密钥：中国用 DeepSeek，其他地方用 Claude，"
                                  "出错自动换另一家。密钥只存在本机用户目录。调用 AI 时只发你写的那句话和程序识别出的零件特征清单，"
                                  "不发模型文件。"))
        note.setWordWrap(True)
        lay.addWidget(note)
        form = QtWidgets.QFormLayout()
        self.provider = QtWidgets.QComboBox()
        names = {"deepseek": "DeepSeek（国内推荐）", "claude": "Claude（Anthropic）"}
        for pid in first_run.PROVIDERS:
            self.provider.addItem(T(names.get(pid, pid)) + (T("（已设置）") if status[pid] else ""), pid)
        self.key = QtWidgets.QLineEdit()
        self.key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key.setPlaceholderText(T("粘贴密钥；留空则不改"))
        form.addRow(T("AI 服务"), self.provider)
        form.addRow(T("密钥"), self.key)
        lay.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox()
        save = buttons.addButton(T("保存"), QtWidgets.QDialogButtonBox.AcceptRole)
        later = buttons.addButton(T("以后再说"), QtWidgets.QDialogButtonBox.RejectRole)
        save.clicked.connect(self.save)
        later.clicked.connect(self.dlg.reject)
        lay.addWidget(buttons)

    def save(self) -> None:
        from freecad_addon.core import first_run

        first_run.save(self.provider.currentData(), self.key.text(), "", "")
        self.key.clear()
        self.dlg.accept()


def about_text() -> str:
    lines = [T("问渠有限元"), T(f"版本 {_version()}") if _version() else "", "",
             tier_text(), "",
             T("求解器 CalculiX、网格 Gmsh，运行在 FreeCAD 的 FEM 工作台里。每次计算带网格收敛、反力平衡、奇异点核查；"
               "AI 只起草与解释，数字由程序填，算例由工程师确认。"),
             T("验证手册与许可证说明在安装目录里。")]
    return "\n".join(x for x in lines if x is not None)


def _exec(dlg) -> None:
    dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()


class FeaLicenseCommand:
    def GetResources(self):
        return {"MenuText": T("问渠有限元：授权…"), "ToolTip": T("看现在是免费版还是专业版；本机激活码；导入专业版授权文件")}

    def IsActive(self):
        return True

    def Activated(self):
        _exec(LicenseDialog(_mw()).dlg)


class FeaSetupCommand:
    def GetResources(self):
        return {"MenuText": T("问渠有限元：设置 AI 密钥…"), "ToolTip": T("AI 起草与解释用的密钥（DeepSeek 或 Claude），只存本机")}

    def IsActive(self):
        return True

    def Activated(self):
        _exec(SetupDialog(_mw()).dlg)


class FeaAboutCommand:
    def GetResources(self):
        return {"MenuText": T("关于问渠有限元"), "ToolTip": T("版本、授权档位、求解器与可信度核查说明")}

    def IsActive(self):
        return True

    def Activated(self):
        from PySide import QtWidgets

        QtWidgets.QMessageBox.about(_mw(), T("关于问渠有限元"), about_text())


class HelpManipulator:
    """授权、设置、关于放进“帮助”菜单的“关于 FreeCAD”前面"""

    def modifyMenuBar(self):
        return [{"insert": c, "menuItem": HELP_ANCHOR} for c in HELP_CMDS]


def _start_in_fem() -> None:
    """第一次启动时把启动工作台设成 FEM；只设一次，用户以后改了不再动"""
    mine = FreeCAD.ParamGet(PARAMS)
    if mine.GetBool("FeaStartSet", False):
        return
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").SetString("AutoloadModule", "FemWorkbench")
    mine.SetBool("FeaStartSet", True)


def register() -> None:
    from freecad_addon.gui import fem_commands
    from freecad_addon.gui.workbench import FeaCommand

    FreeCADGui.addCommand("FAP_Fea", FeaCommand())
    FreeCADGui.addCommand("FAP_FeaLicense", FeaLicenseCommand())
    FreeCADGui.addCommand("FAP_FeaSetup", FeaSetupCommand())
    FreeCADGui.addCommand("FAP_FeaAbout", FeaAboutCommand())
    fem_commands.register(extra_menu=("FAP_Fea",))
    if not hasattr(FreeCADGui, "_fap_fea_help"):
        FreeCADGui._fap_fea_help = HelpManipulator()
        FreeCADGui.addWorkbenchManipulator(FreeCADGui._fap_fea_help)
    _start_in_fem()
