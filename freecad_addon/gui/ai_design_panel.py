"""问渠 CAD「AI 设计零件」面板（ADR-0100 42.4，§3.1）。

逻辑在 `freecad_addon/core/ai_design.py`（设计、页签内容、入库）与 `freecad_addon/fc/ai_design_doc.py`（模型、工程图、BOM 放进文档）；
这里只管输入、后台线程与显示。
"""

from __future__ import annotations

import FreeCAD
import FreeCADGui

from assist.i18n import tr as T
from freecad_addon.core import ai_design as C
from freecad_addon.gui.fem_commands import _in_background

_LAST_PANEL = None                # 最近打开的面板（测试、录屏用）


def _client():
    from freecad_addon.fc import fem_flow

    return fem_flow.llm_client()


class AiDesignPanel:
    def __init__(self, library, enterprise=None, client_factory=_client):
        from PySide import QtWidgets

        self.library, self.enterprise, self.client_factory = library, enterprise, client_factory
        self.out: dict | None = None
        self.placed: dict | None = None
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(T("AI 设计零件（AI 设计，代码校核，人确认）"))
        lay = QtWidgets.QVBoxLayout(self.form)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel(T("零件类型")))
        self.kind = QtWidgets.QComboBox()
        self.kind.addItems([T(k) for k in C.PART_TYPES])
        row.addWidget(self.kind, 1)
        lay.addLayout(row)
        lay.addWidget(QtWidgets.QLabel(T("需求原话（转速、电机、机构参数、轴向位置、材料……；轴承型号可以不指定）")))
        self.text = QtWidgets.QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QtWidgets.QHBoxLayout()
        self.example = QtWidgets.QPushButton(T("载入示例：平缝机上轴"))
        self.example.clicked.connect(self.load_example)
        row.addWidget(self.example)
        row.addStretch(1)
        self.go = QtWidgets.QPushButton(T("开始设计"))
        self.go.clicked.connect(self.start)
        row.addWidget(self.go)
        lay.addLayout(row)
        self.progress = QtWidgets.QLabel("")
        self.progress.setWordWrap(True)
        lay.addWidget(self.progress)
        self.tabs = QtWidgets.QTabWidget()
        self.views = {}
        for key, title in (("conditions", "条件"), ("rounds", "每一轮"), ("questions", "AI 的问题")):
            v = QtWidgets.QTextBrowser()
            self.views[key] = v
            self.tabs.addTab(v, T(title))
        lay.addWidget(self.tabs, 3)
        self.model_info = QtWidgets.QLabel("")
        self.model_info.setWordWrap(True)
        lay.addWidget(self.model_info)
        grid = QtWidgets.QFormLayout()
        self.drawing_no = QtWidgets.QLineEdit()
        self.name = QtWidgets.QLineEdit(T("上轴"))
        self.vendor = QtWidgets.QLineEdit(self._enterprise_name())
        self.by = QtWidgets.QLineEdit()
        for label, w in (("图号", self.drawing_no), ("名称", self.name), ("企业", self.vendor), ("确认人", self.by)):
            grid.addRow(T(label), w)
        lay.addLayout(grid)
        self.ok = QtWidgets.QPushButton(T("确认入企业库"))
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.confirm)
        lay.addWidget(self.ok)
        self.replay = False

    def _enterprise_name(self) -> str:
        names = {c.get("vendor") for c in (self.enterprise.all("custom_part") if self.enterprise is not None else [])}
        names.discard(None)
        return next(iter(sorted(names)), "")

    # ------------------------------------------------------------ 动作

    def load_example(self):
        self.text.setPlainText(C.example_text())
        self.replay = True

    def start(self):
        statement = self.text.toPlainText().strip()
        if not statement:
            self.progress.setText(T("先写需求原话"))
            return
        use_replay = self.replay and statement == C.example_text().strip()
        try:
            client = C.example_client() if use_replay else self.client_factory()
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.progress.setText(T(f"没有开始：{exc}（没有密钥时可以“载入示例”回放录制）"))
            return
        self.go.setEnabled(False)
        self.ok.setEnabled(False)
        self.progress.setText(T("AI 列条件、提方案，代码逐项校核（强度要算有限元，每个新台阶约 40 秒）……"))
        _in_background(lambda: C.run(statement, client, self.library, replay=use_replay), self.done)

    def done(self, out):
        self.go.setEnabled(True)
        if isinstance(out, Exception):
            self.progress.setText(T(f"设计中断：{out}"))
            return
        self.out = out
        res = out["result"]
        head = T("【录制回放，不是这次真实调用】") if out.get("replay") else ""
        self.progress.setText(head + T(f"结论：{C.RESULT.get(res.get('status'), res.get('status'))}；{len(res.get('rounds') or [])} 轮"))
        self.views["conditions"].setHtml(C.conditions_html(res))
        self.views["rounds"].setHtml(C.rounds_html(res))
        self.views["questions"].setHtml(C.questions_html(res))
        self.tabs.setCurrentIndex(1)
        self.model_info.setText(C.model_line(out.get("model")))
        if out.get("model") and out["model"].get("readback") == "pass":
            self.place()

    def place(self):
        from freecad_addon.fc import ai_design_doc as D

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("AiDesign")
        try:
            segs = C.segments(self.out["result"], self.library.get)
            self.placed = D.place(doc, self.out, segs, name=self.name.text().strip() or T("上轴"),
                                  drawing_no=self.drawing_no.text().strip())
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.model_info.setText(self.model_info.text() + "\n" + T(f"没有放进文档：{exc}"))
            return
        n = len(self.placed["dimension_checks"])
        self.model_info.setText(self.model_info.text() + "\n" + T(f"已放进文档：三维模型、工程图（{n} 个尺寸与设计数据一致）、BOM 表"))
        if FreeCADGui.activeDocument() is not None and FreeCADGui.activeDocument().activeView() is not None:
            FreeCADGui.SendMsgToActiveView("ViewFit")
        self.ok.setEnabled(not self.out.get("replay") and self.enterprise is not None)
        if self.enterprise is None:
            self.model_info.setText(self.model_info.text() + "\n" + T("没有设企业库（菜单“企业库”），不能入库"))
        elif self.out.get("replay"):
            self.model_info.setText(self.model_info.text() + "\n" + T("录制回放的示例不入企业库"))

    def confirm(self):
        try:
            comp = C.confirm(self.enterprise, self.out, drawing_no=self.drawing_no.text(), name=self.name.text(),
                             enterprise=self.vendor.text(), actor=self.by.text())
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.model_info.setText(self.model_info.text() + "\n" + T(f"没有入库：{exc}"))
            return
        if self.placed:
            tpl = self.placed["page"].Template
            texts = dict(tpl.EditableTexts)
            if "approval_person" in texts:
                texts["approval_person"] = self.by.text().strip()
                texts["identification_number"] = self.drawing_no.text().strip()
                tpl.EditableTexts = texts
        self.model_info.setText(self.model_info.text() + "\n" + T(f"已入企业库：{comp['id']}（确认人 {self.by.text().strip()}）"))
        self.ok.setEnabled(False)

    # ------------------------------------------------------------ 任务面板

    def accept(self):
        FreeCADGui.Control.closeDialog()
        return True

    def reject(self):
        FreeCADGui.Control.closeDialog()
        return True

    def getStandardButtons(self):
        from PySide import QtWidgets

        return int(QtWidgets.QDialogButtonBox.Close)


def open_panel(library=None, enterprise=None) -> AiDesignPanel:
    global _LAST_PANEL
    if library is None:
        from freecad_addon.gui.host import get_host

        library = get_host().library()
    if enterprise is None:
        enterprise = getattr(library, "top", None)
    panel = AiDesignPanel(library, enterprise)
    _LAST_PANEL = panel
    FreeCADGui.Control.showDialog(panel)
    return panel


class AiDesignCommand:
    def GetResources(self):
        return {"MenuText": T("AI 设计零件…"), "ToolTip": T("写需求原话，AI 设计零件、代码逐项校核，通过后生成三维模型、工程图和 BOM，人确认后入企业库")}

    def Activated(self):
        open_panel()

    def IsActive(self):
        return True
