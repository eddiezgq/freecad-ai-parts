"""问渠 CAD「AI 设计零件」面板（ADR-0100 42.4，§3.1）。

逻辑在 `freecad_addon/core/ai_design.py`（设计、页签内容、入库）与 `freecad_addon/fc/ai_design_doc.py`（模型、工程图、BOM 放进文档）；
这里只管输入、后台线程与显示。
"""

from __future__ import annotations

import time

import FreeCAD
import FreeCADGui

from assist.i18n import tr as T
from freecad_addon.core import ai_design as C
from freecad_addon.gui.fem_commands import _in_background

_LAST_PANEL = None                # 最近打开的面板（测试、录屏用）
_DOCK = None                      # 面板所在的停靠窗口（只建一个，再点按钮就把它调到前面）


def _client():
    from freecad_addon.fc import fem_flow

    return fem_flow.llm_client()


class AiDesignPanel:
    def __init__(self, library, enterprise=None, client_factory=_client):
        from PySide import QtCore, QtWidgets

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
        self.kind.currentIndexChanged.connect(self._kind_changed)
        row.addWidget(self.kind, 1)
        lay.addLayout(row)
        need = QtWidgets.QLabel(T("需求原话（转速、电机、机构参数、轴向位置、材料……；轴承型号可以不指定）"))
        need.setWordWrap(True)
        lay.addWidget(need)
        self.text = QtWidgets.QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QtWidgets.QHBoxLayout()
        self.example = QtWidgets.QPushButton(T("载入示例：") + T(C.EXAMPLE_NAMES[C.PART_TYPES[0]]))
        self.example.clicked.connect(self.load_example)
        self.go = QtWidgets.QPushButton(T("开始设计"))
        self.go.clicked.connect(self.start)
        self.go.setDefault(True)
        row.addWidget(self.go)                     # 紧挨着“载入示例”放在左边：面板窄时也看得见（2026-11-18）
        row.addWidget(self.example)
        row.addStretch(1)
        lay.addLayout(row)
        self.progress = QtWidgets.QLabel("")
        self.progress.setWordWrap(True)
        lay.addWidget(self.progress)
        self.bar = QtWidgets.QProgressBar()                # 当前这一步的进度；步数不定时来回走（忙）
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        self._status: tuple | None = None                  # 后台线程写（说明, 已做, 总数），界面定时读
        self._t0 = 0.0
        self.ticker = QtCore.QTimer(self.form)
        self.ticker.timeout.connect(self._tick)
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

    def part_type(self) -> str:
        return C.PART_TYPES[max(0, self.kind.currentIndex())]

    def _kind_changed(self, _index=None):
        """换零件类型：示例按钮、默认名称跟着换；已经载入的示例原话清掉（示例只对本类型的录制有效）"""
        k = self.part_type()
        self.example.setText(T("载入示例：") + T(C.EXAMPLE_NAMES[k]))
        if self.name.text().strip() in {T(n) for n in C.DEFAULT_NAMES.values()}:
            self.name.setText(T(C.DEFAULT_NAMES[k]))
        if self.replay:
            self.text.setPlainText("")
            self.replay = False

    def _enterprise_name(self) -> str:
        names = {c.get("vendor") for c in (self.enterprise.all("custom_part") if self.enterprise is not None else [])}
        names.discard(None)
        return next(iter(sorted(names)), "")

    def _refresh_browser(self) -> None:
        """入库后零件库浏览器立刻列出新零件，标题里的企业库组件数也跟着变（2026-11-18：入了库却看不到）"""
        import re

        from PySide import QtWidgets

        dock = FreeCADGui.getMainWindow().findChild(QtWidgets.QDockWidget, "FapLibraryBrowser")
        if dock is None:
            return
        if self.enterprise is not None and hasattr(dock, "header"):
            n = len(self.enterprise.all())
            dock.header.setText(re.sub(r"企业库 \d+ 个组件", f"企业库 {n} 个组件", dock.header.text()))
        if hasattr(dock, "refresh"):
            dock.refresh()

    # ------------------------------------------------------------ 动作

    def load_example(self):
        self.text.setPlainText(C.example_text(self.part_type()))
        self.replay = True

    def start(self):
        statement = self.text.toPlainText().strip()
        if not statement:
            self.progress.setText(T("先写需求原话"))
            return
        kind = self.part_type()
        use_replay = self.replay and statement == C.example_text(kind).strip()
        if use_replay:
            statement = C.example_text(kind)       # 原样（含末尾换行）：录制按示例文件原文算请求键（2026-11-18）
        try:
            client = C.example_client(kind) if use_replay else self.client_factory()
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.progress.setText(T(f"没有开始：{exc}（没有密钥时可以“载入示例”回放录制）"))
            return
        self.go.setEnabled(False)
        self.ok.setEnabled(False)
        self._status = (T("开始"), None, None)
        self._t0 = time.monotonic()
        self.bar.show()
        self._tick()
        self.ticker.start(500)

        def report(text, done, total):
            self._status = (text, done, total)

        _in_background(lambda: C.run(statement, client, self.library, kind=kind, replay=use_replay, progress=report), self.done)

    def _tick(self):
        """每半秒刷新：当前一步、已用时间、这一步的进度（有限元一个台阶约 40 秒，见过的台阶直接用缓存）"""
        if self._status is None:
            return
        text, done, total = self._status
        sec = int(time.monotonic() - self._t0)
        extra = T(f"（第 {done + 1} / {total} 个台阶）") if total else ""
        self.progress.setText(T(text) + extra + T(f"　已用 {sec // 60} 分 {sec % 60:02d} 秒"))
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        else:
            self.bar.setRange(0, 0)

    def done(self, out):
        self.ticker.stop()
        self.bar.hide()
        self._status = None
        sec = int(time.monotonic() - self._t0)
        self.go.setEnabled(True)
        if isinstance(out, Exception):
            self.progress.setText(T(f"设计中断：{out}"))
            return
        self.out = out
        res = out["result"]
        head = T("【录制回放，不是这次真实调用】") if out.get("replay") else ""
        self.progress.setText(head + T(f"结论：{C.RESULT.get(res.get('status'), res.get('status'))}；{len(res.get('rounds') or [])} 轮")
                              + T(f"；用时 {sec // 60} 分 {sec % 60:02d} 秒"))
        self.views["conditions"].setHtml(C.conditions_html(res))
        self.views["rounds"].setHtml(C.rounds_html(res))
        self.views["questions"].setHtml(C.questions_html(res))
        self.tabs.setCurrentIndex(1)
        self.model_info.setText(C.model_line(out.get("model")))
        if out.get("model") and out["model"].get("readback") == "pass":
            self.place()

    def place(self):
        from PySide import QtWidgets

        from freecad_addon.fc import ai_design_doc as D

        self.model_info.setText(self.model_info.text() + "\n" + T("放进文档：三维模型、工程图、BOM……"))
        QtWidgets.QApplication.processEvents()

        doc = FreeCAD.ActiveDocument or FreeCAD.newDocument("AiDesign")
        try:
            segs = C.segments(self.out["result"], self.library.get)
            kind = self.out.get("kind") or C.PART_TYPES[0]
            self.placed = D.place(doc, self.out, segs, name=self.name.text().strip() or T(C.DEFAULT_NAMES[kind]),
                                  drawing_no=self.drawing_no.text().strip(), **C.drawing_extras(self.out["result"]))
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
        self._refresh_browser()
        self.ok.setEnabled(False)



def open_panel(library=None, enterprise=None) -> AiDesignPanel:
    """单独的工具窗口（挂在主窗口上、始终在它前面，可拖动、可缩放）。
    - 不用任务面板：有的布局里任务面板是隐藏的，面板看不见、菜单却被锁住（2026-11-18）；
    - 不用右侧停靠：问渠 CAD 1.1.4（Qt 6、英文界面、主窗口比屏幕宽）里放进右侧停靠区、与“校验”叠成页签时界面卡死（2026-11-19），
      而同一个面板单独开窗正常。单独的窗口不参与主窗口的布局，不会再把主窗口拖住。"""
    global _LAST_PANEL, _DOCK
    from PySide import QtCore, QtWidgets

    if _DOCK is not None and _LAST_PANEL is not None:
        _DOCK.show()
        _DOCK.raise_()
        _DOCK.activateWindow()
        return _LAST_PANEL
    if library is None:
        from freecad_addon.gui.host import get_host

        library = get_host().library()
    if enterprise is None:
        enterprise = getattr(library, "top", None)
    panel = AiDesignPanel(library, enterprise)
    mw = FreeCADGui.getMainWindow()
    win = QtWidgets.QWidget(mw, QtCore.Qt.Tool)
    win.setObjectName("FapAiDesignPanel")
    win.setWindowTitle(T("AI 设计零件"))
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)   # 滚动条不来回出现、消失（换行文字的高度随宽度变）
    scroll.setWidget(panel.form)
    lay = QtWidgets.QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(scroll)
    screen = (mw.screen() if hasattr(mw, "screen") else None) or QtWidgets.QApplication.primaryScreen()
    area = screen.availableGeometry()                  # 按屏幕而不是主窗口定大小、位置：主窗口可能比屏幕宽
    w, h = min(640, area.width() - 40), min(900, area.height() - 80)
    win.resize(w, h)
    win.move(area.right() - w - 20, area.top() + 40)
    win.show()
    win.raise_()
    win.activateWindow()
    _LAST_PANEL, _DOCK = panel, win
    return panel


class AiDesignCommand:
    def GetResources(self):
        return {"MenuText": T("AI 设计零件…"), "ToolTip": T("写需求原话，AI 设计零件、代码逐项校核，通过后生成三维模型、工程图和 BOM，人确认后入企业库")}

    def Activated(self):
        try:
            open_panel()
        except Exception as exc:  # noqa: BLE001 — 打不开就说原因，并把详情写进本机日志
            import traceback
            from pathlib import Path

            from PySide import QtWidgets

            log = Path.home() / ".freecad-ai-parts" / "ai-design.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding="utf-8")
            QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), T("AI 设计零件"), T(f"打不开：{exc}（详情在 {log}）"))

    def IsActive(self):
        return True
