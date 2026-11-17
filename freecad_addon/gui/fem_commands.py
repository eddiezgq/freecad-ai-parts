"""FEM 工作台里加的三个按钮（ADR-0093 补充十二第 3 步）：一句话起草、计算并核查、出报告。

用 FreeCAD 1.0 的 `addWorkbenchManipulator` 放进 FEM 工作台的“求解”工具栏和菜单（插在“运行求解器”前面），不改 FreeCAD。
逻辑在 `freecad_addon/fc/fem_flow.py`；这里只管输入、后台线程与显示。
"""

from __future__ import annotations

import threading

import FreeCAD
import FreeCADGui

from freecad_addon.fc import fem_flow as F

ANCHOR = "FEM_SolverRun"          # 插在 FEM 工作台“运行求解器”按钮前面（只有 FEM 工作台有这个按钮）
CMDS = ("FAP_FemDraft", "FAP_FemRun", "FAP_FemReport")
_LAST_PANEL = None                # 最近打开的起草面板（录屏演示、测试用）


def _mw():
    return FreeCADGui.getMainWindow()


def _analysis():
    """当前分析：选中的分析节点，或文档里本仓库建的那个（多个时取选中的）"""
    sel = [o for o in FreeCADGui.Selection.getSelection() if o.TypeId == "Fem::FemAnalysis"]
    if sel:
        return sel[0]
    doc = FreeCAD.ActiveDocument
    found = [o for o in (doc.Objects if doc else []) if o.TypeId == "Fem::FemAnalysis"]
    return found[-1] if found else None


def _say(title: str, text: str, warn: bool = False) -> None:
    from PySide import QtWidgets

    (QtWidgets.QMessageBox.warning if warn else QtWidgets.QMessageBox.information)(_mw(), title, text)


def _in_background(work, done) -> None:
    """work() 在后台线程跑；done(结果或异常) 回到界面线程"""
    from PySide import QtCore

    box: dict = {}

    def run():
        try:
            box["out"] = work()
        except Exception as exc:  # noqa: BLE001 — 交给界面显示
            box["out"] = exc

    t = threading.Thread(target=run, name="fap-fem", daemon=True)
    t.start()
    timer = QtCore.QTimer(_mw())

    def poll():
        if not t.is_alive():
            timer.stop()
            done(box.get("out"))

    timer.timeout.connect(poll)
    timer.start(100)


class DraftPanel:
    """任务面板：一句话 → 起草 → 追问与未采用的提议 → 确认"""

    def __init__(self, parts: list, client_factory=F.llm_client):
        from PySide import QtWidgets

        self.parts, self.client_factory, self.analysis = parts, client_factory, None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("一句话起草算例（AI 起草，程序核对，人确认）")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.addWidget(QtWidgets.QLabel("零件：" + "、".join(o.Label for o in parts)))
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setPlaceholderText("例：肩关节空心轴，45 钢调质。Ø70 法兰那一端的端面固定，在 Ø42.75 花键段上加峰值扭矩 92.5 N·m。")
        lay.addWidget(self.text)
        self.go = QtWidgets.QPushButton("起草")
        self.go.clicked.connect(self.draft)
        lay.addWidget(self.go)
        self.info = QtWidgets.QTextBrowser()
        lay.addWidget(self.info)
        self.handled = QtWidgets.QCheckBox("追问都已处理（在 FEM 里补好了，或判断不需要）")
        lay.addWidget(self.handled)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("确认人："))
        self.by = QtWidgets.QLineEdit()
        row.addWidget(self.by)
        self.ok = QtWidgets.QPushButton("确认算例")
        self.ok.clicked.connect(self.confirm)
        self.ok.setEnabled(False)
        row.addWidget(self.ok)
        lay.addLayout(row)

    def draft(self):
        doc = FreeCAD.ActiveDocument
        statement = self.text.toPlainText()
        try:
            steps = F.draft_steps(doc, statement, self.parts)
            client = self.client_factory()
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.info.setPlainText(f"没有起草：{exc}")
            return
        self.go.setEnabled(False)
        self.info.setPlainText("正在识别零件特征、请 AI 起草、程序核对……")

        def done(r):
            self.go.setEnabled(True)
            if isinstance(r, Exception):
                self.info.setPlainText(f"没有起草：{r}")
                return
            out = F.place_draft(doc, statement, self.parts, r)
            self.analysis = out["analysis"]
            self.show(out)
            self.ok.setEnabled(True)

        _in_background(lambda: F.draft_study(statement, steps, client), done)

    def show(self, out: dict) -> None:
        lines = []
        if out.get("replay"):
            lines.append("【AI 回复来自录制回放（FAP_LLM_REPLAY），不是这次真实调用】")
        lines.append("已把约束、载荷放进模型树的“分析”节点，在三维视图里核对。")
        for q in out["questions"]:
            lines.append(f"追问：{q}")
        for x in out["rejected"]:
            lines.append(f"未采用：{x['type']}——{x['reason']}")
        for x in out["errors"]:
            lines.append(f"还不能算：{x}")
        self.info.setPlainText("\n".join(lines))

    def confirm(self):
        try:
            s = F.confirm_analysis(self.analysis, self.by.text(), self.handled.isChecked())
        except Exception as exc:  # noqa: BLE001
            self.info.append(f"没有确认：{exc}")
            return
        self.info.append(f"已确认：{s['provenance']['confirmed_by']} {s['provenance']['confirmed_at']}。下一步点“计算并核查”。")
        self.ok.setEnabled(False)

    def accept(self):
        FreeCADGui.Control.closeDialog()
        return True

    def reject(self):
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        from PySide import QtWidgets

        return int(QtWidgets.QDialogButtonBox.Close)


class FemDraftCommand:
    def GetResources(self):
        return {"MenuText": "一句话起草（AI）", "ToolTip": "选中零件，用一句话说清材料、支承、载荷：AI 起草约束与载荷，程序逐项核对，你确认"}

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None

    def Activated(self):
        parts = [o for o in FreeCADGui.Selection.getSelection() if hasattr(o, "Shape") and o.Shape.Solids]
        if not parts:
            _say("一句话起草", "先在三维视图或模型树里选中要算的零件（实体）", warn=True)
            return
        global _LAST_PANEL
        _LAST_PANEL = DraftPanel(parts)
        FreeCADGui.Control.showDialog(_LAST_PANEL)


class FemRunCommand:
    def GetResources(self):
        return {"MenuText": "计算并核查（零件库）", "ToolTip": "按“分析”节点计算，带网格收敛、反力平衡、奇异点核查；结果进 FreeCAD 的后处理"}

    def IsActive(self):
        return _analysis() is not None

    def Activated(self):
        an = _analysis()
        try:
            study, wd = F.prepare_run(an)
        except Exception as exc:  # noqa: BLE001
            _say("计算并核查", f"不能算：{exc}", warn=True)
            return
        FreeCAD.Console.PrintMessage("零件库有限元：开始计算（带可信度核查，可能要几分钟）……\n")

        def done(res):
            if isinstance(res, Exception) or res.get("status") != "ok":
                _say("计算并核查", f"没有算出：{res if isinstance(res, Exception) else '；'.join(res['messages'])}", warn=True)
                return
            out = F.finish_run(an, res, wd)
            v = {"pass": "通过", "fail": "不通过", "unknown": "未知", None: "未知"}[res["data"].get("trust_verdict")]
            _say("计算并核查", f"算完。整体可信度：{v}。\n结果已放进“分析”节点，可用 FEM 工作台的剖切、变形放大查看。\n"
                 + ("\n".join(out["skipped"]) if out["skipped"] else ""))

        _in_background(lambda: F.compute(study, wd), done)


class FemReportCommand:
    def GetResources(self):
        return {"MenuText": "出报告（零件库）", "ToolTip": "Word / PDF 报告：结论、算例与依据、核查、云图、审核清单、可追溯信息"}

    def IsActive(self):
        an = _analysis()
        return an is not None and "FapWorkDir" in an.PropertiesList

    def Activated(self):
        from PySide import QtWidgets

        an = _analysis()
        number, ok = QtWidgets.QInputDialog.getText(_mw(), "出报告", "报告编号（质量体系分配，可空）：")
        if not ok:
            return
        revision, ok = QtWidgets.QInputDialog.getText(_mw(), "出报告", "版次：", text="A")
        if not ok:
            return
        reason, ok = QtWidgets.QInputDialog.getText(_mw(), "出报告", "出稿 / 改版原因：", text="首次出稿")
        if not ok:
            return
        explain = QtWidgets.QMessageBox.question(_mw(), "出报告", "让 AI 写“解释与建议”吗？（数字由程序填，AI 不判定合格）") \
            == QtWidgets.QMessageBox.Yes
        try:
            out = F.make_report(an, number=number or None, revision=revision or "草稿", reason=reason or "首次出稿",
                                explain_client=F.llm_client() if explain else None)
        except Exception as exc:  # noqa: BLE001
            _say("出报告", f"没有出报告：{exc}", warn=True)
            return
        _say("出报告", f"报告：{out['docx']}" + (f"\nPDF：{out['pdf']}" if out["pdf"] else "\n（本机没有 LibreOffice，只出了 Word）"))


class FemManipulator:
    """把三个按钮插到 FEM 工作台“运行求解器”前面（工具栏与菜单）"""

    def modifyToolBars(self):
        return [{"insert": c, "toolItem": ANCHOR} for c in CMDS]

    def modifyMenuBar(self):
        return [{"insert": c, "menuItem": ANCHOR} for c in CMDS]


def register() -> None:
    FreeCADGui.addCommand("FAP_FemDraft", FemDraftCommand())
    FreeCADGui.addCommand("FAP_FemRun", FemRunCommand())
    FreeCADGui.addCommand("FAP_FemReport", FemReportCommand())
    if not hasattr(FreeCADGui, "_fap_fem_manipulator"):
        FreeCADGui._fap_fem_manipulator = FemManipulator()
        FreeCADGui.addWorkbenchManipulator(FreeCADGui._fap_fem_manipulator)
