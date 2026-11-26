"""问渠 CAD「AI 设计整机」面板（ADR-0115 44.4）：在“AI 设计零件”之上加一层，从一句需求跑到整机结果。

逻辑在 `freecad_addon/core/robot_design.py`（六步、回放判定、有限元复用、页签内容、入库），
`freecad_addon/fc/robot_doc.py`（装配与 BOM 放进文档）；这里只管输入、后台线程与显示。
单独的工具窗口，不进停靠区（2026-11-19：停靠区里与“校验”叠成页签时界面卡死）。
"""

from __future__ import annotations

import time
from pathlib import Path

import FreeCAD
import FreeCADGui

from assist.i18n import tr as T
from freecad_addon.core import robot_design as C
from freecad_addon.gui.fem_commands import _in_background

_LAST_PANEL = None
_WIN = None
FEA_LOG = Path.home() / ".freecad-ai-parts" / "robot-fea-time.json"


def _client():
    from freecad_addon.fc import fem_flow

    return fem_flow.llm_client()


class RobotDesignPanel:
    def __init__(self, library=None, enterprise=None, client_factory=_client, fea_log=FEA_LOG):
        from PySide import QtCore, QtWidgets

        self.library, self.enterprise, self.client_factory, self.fea_log = library, enterprise, client_factory, fea_log
        self.out: dict | None = None
        self.placed: dict | None = None
        self.replay = False
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(T("AI 设计整机（AI 提构型，代码选件、装配、仿真、校核，人确认）"))
        lay = QtWidgets.QVBoxLayout(self.form)
        need = QtWidgets.QLabel(T("需求原话（自由度、负载、臂展、精度、速度、加工与成本要求……）"))
        need.setWordWrap(True)
        lay.addWidget(need)
        self.text = QtWidgets.QPlainTextEdit()
        lay.addWidget(self.text, 1)
        row = QtWidgets.QHBoxLayout()
        self.go = QtWidgets.QPushButton(T("开始设计"))
        self.go.clicked.connect(self.start)
        self.go.setDefault(True)
        row.addWidget(self.go)
        self.examples = {}
        for name in C.EXAMPLES:
            b = QtWidgets.QPushButton(T("载入示例：") + T(name))
            b.clicked.connect(lambda _=False, n=name: self.load_example(n))
            row.addWidget(b)
            self.examples[name] = b
        self.example = self.examples[C.EXAMPLE_NAME]
        row.addStretch(1)
        lay.addLayout(row)
        self.do_fea = QtWidgets.QCheckBox(T("做有限元（机械臂：支架；龙门：门架）"))
        self.do_fea.setChecked(True)
        lay.addWidget(self.do_fea)
        self.fea_hint = QtWidgets.QLabel("")
        self.fea_hint.setWordWrap(True)
        lay.addWidget(self.fea_hint)
        self._hint()
        self.steps = QtWidgets.QTextBrowser()
        self.steps.setMinimumHeight(150)
        lay.addWidget(self.steps)
        self.progress = QtWidgets.QLabel("")
        self.progress.setWordWrap(True)
        lay.addWidget(self.progress)
        self.bar = QtWidgets.QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.hide()
        lay.addWidget(self.bar)
        self._status: tuple | None = None                  # 后台线程写（步骤表, 说明, 已做, 总数），界面定时读
        self._t0 = 0.0
        self.ticker = QtCore.QTimer(self.form)
        self.ticker.timeout.connect(self._tick)
        self.tabs = QtWidgets.QTabWidget()
        self.views = {}
        for title, _ in C.TABS:
            v = QtWidgets.QTextBrowser()
            v.setOpenExternalLinks(True)
            self.views[title] = v
            self.tabs.addTab(v, T(title))
        lay.addWidget(self.tabs, 3)
        self.model_info = QtWidgets.QLabel("")
        self.model_info.setWordWrap(True)
        lay.addWidget(self.model_info)
        grid = QtWidgets.QFormLayout()
        self.drawing_no = QtWidgets.QLineEdit()
        self.name = QtWidgets.QLineEdit(T("整机"))
        self.vendor = QtWidgets.QLineEdit(self._enterprise_name())
        self.by = QtWidgets.QLineEdit()
        for label, w in (("图号", self.drawing_no), ("名称", self.name), ("企业", self.vendor), ("确认人", self.by)):
            grid.addRow(T(label), w)
        lay.addLayout(grid)
        self.ok = QtWidgets.QPushButton(T("确认入企业库"))
        self.ok.setEnabled(False)
        self.ok.clicked.connect(self.confirm)
        lay.addWidget(self.ok)

    def _hint(self):
        self.fea_hint.setText(T("回放示例时有限元用案例已算的结果（几何与载荷的指纹一样才用）；机械臂支架现算时：")
                              + T(C.fea_estimate(self.fea_log)) + T("；龙门门架现算约 3 分钟。不勾时强度、变形判待确认，不算通过。"))

    def _enterprise_name(self) -> str:
        names = {c.get("vendor") for c in (self.enterprise.all("custom_part") if self.enterprise is not None else [])}
        names.discard(None)
        return next(iter(sorted(names)), "")

    # ------------------------------------------------------------ 动作

    def load_example(self, name: str = C.EXAMPLE_NAME):
        self.text.setPlainText(C.example_text(name))
        self.replay = True

    def start(self):
        statement = self.text.toPlainText().strip()
        if not statement:
            self.progress.setText(T("先写需求原话"))
            return
        ex = C.which_example(statement) if self.replay else None
        use_replay = ex is not None
        if use_replay:
            statement = C.example_text(ex)             # 原样（含末尾换行）：录制按示例文件原文算请求键
        try:
            client = C.example_client() if use_replay else self.client_factory()
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.progress.setText(T(f"没有开始：{exc}（没有密钥时可以“载入示例”回放录制）"))
            return
        self.go.setEnabled(False)
        self.ok.setEnabled(False)
        self.out = self.placed = None
        for v in self.views.values():
            v.clear()
        self.model_info.setText("")
        self._status = (None, T("开始"), None, None)
        self._t0 = time.monotonic()
        self.bar.show()
        self._tick()
        self.ticker.start(500)
        do_fea = self.do_fea.isChecked()

        def report(table, text, done, total):
            self._status = (table, text, done, total)

        _in_background(lambda: C.run(statement, client, replay=use_replay, do_fea=do_fea, progress=report, fea_log=self.fea_log),
                       self.done)

    def _tick(self):
        if self._status is None:
            return
        table, text, done, total = self._status
        if table:
            self.steps.setHtml(C.steps_html(table))
        sec = int(time.monotonic() - self._t0)
        extra = T(f"（第 {done + 1} / {total} 个）") if total else ""
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
        self._hint()
        if isinstance(out, Exception):
            self.progress.setText(T(f"设计中断：{out}"))
            return
        self.out = out
        self.steps.setHtml(C.steps_html(out["steps"]))
        head = T("【录制回放，不是这次真实调用】") if out.get("replay") else ""
        verdict = {"pass": "全部通过", "unknown": "跑完了，有待确认的项（见各页签）", "fail": "没有跑完"}[out["status"]]
        stop = T(f"；停在“{out['stopped_at']}”") if out.get("stopped_at") else ""
        self.progress.setText(head + T(f"结论：{verdict}") + stop + T(f"；用时 {sec // 60} 分 {sec % 60:02d} 秒"))
        for title, md in C.tabs(out["out_dir"], out.get("kind", "arm")):
            self.views[title].setMarkdown(md or T("这一步还没有结果"))
        if C.cad_result(out).exists() and out["steps"][2]["status"] != "fail":
            self.place()

    def place(self):
        from PySide import QtWidgets

        from freecad_addon.fc import robot_doc as D

        self.model_info.setText(T("放进文档：整机装配、BOM……"))
        QtWidgets.QApplication.processEvents()
        doc = FreeCAD.newDocument("AiRobot")
        try:
            self.placed = D.place(doc, self.out["out_dir"], self.out.get("kind", "arm"))
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.model_info.setText(T(f"没有放进文档：{exc}"))
            return
        n = len(self.placed["objects"])
        bom = T(f"、BOM 表 {self.placed['bom_rows']} 行") if self.placed["sheet"] is not None else ""
        colors = (T("直线模组与吸盘灰色、自制件铝色，门架按有限元结论着色") if self.out.get("kind") == "gantry"
                  else T("外购模组灰色、自制件铝色，支架按有限元结论着色"))
        self.model_info.setText(T(f"已放进文档：整机装配 {n} 个零件（") + colors + T("）") + bom
                                + T(f"；结果文件在 {self.out['out_dir']}"))
        if FreeCADGui.activeDocument() is not None and FreeCADGui.activeDocument().activeView() is not None:
            FreeCADGui.SendMsgToActiveView("ViewFit")
            FreeCADGui.activeDocument().activeView().viewIsometric()
        ok = not self.out.get("replay") and self.enterprise is not None and self.out["status"] != "fail"
        self.ok.setEnabled(ok)
        if self.enterprise is None:
            self.model_info.setText(self.model_info.text() + "\n" + T("没有设企业库（菜单“企业库”），不能入库"))
        elif self.out.get("replay"):
            self.model_info.setText(self.model_info.text() + "\n" + T("录制回放的示例不入企业库"))

    def confirm(self):
        try:
            docs = C.confirm(self.enterprise, self.out, drawing_no=self.drawing_no.text(), name=self.name.text(),
                             enterprise=self.vendor.text(), actor=self.by.text())
        except Exception as exc:  # noqa: BLE001 — 显示给人
            self.model_info.setText(self.model_info.text() + "\n" + T(f"没有入库：{exc}"))
            return
        self.model_info.setText(self.model_info.text() + "\n"
                                + T(f"已入企业库：{len(docs)} 份资料（确认人 {self.by.text().strip()}）"))
        self.ok.setEnabled(False)


def open_panel(library=None, enterprise=None) -> RobotDesignPanel:
    """单独的工具窗口（挂在主窗口上、始终在它前面，可拖动、可缩放），同“AI 设计零件”"""
    global _LAST_PANEL, _WIN
    from PySide import QtCore, QtWidgets

    if _WIN is not None and _LAST_PANEL is not None:
        _WIN.show()
        _WIN.raise_()
        _WIN.activateWindow()
        return _LAST_PANEL
    if library is None:
        from freecad_addon.gui.host import get_host

        library = get_host().library()
    if enterprise is None:
        enterprise = getattr(library, "top", None)
    panel = RobotDesignPanel(library, enterprise)
    mw = FreeCADGui.getMainWindow()
    win = QtWidgets.QWidget(mw, QtCore.Qt.Tool)
    win.setObjectName("FapRobotDesignPanel")
    win.setWindowTitle(T("AI 设计整机"))
    scroll = QtWidgets.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
    scroll.setWidget(panel.form)
    lay = QtWidgets.QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(scroll)
    screen = (mw.screen() if hasattr(mw, "screen") else None) or QtWidgets.QApplication.primaryScreen()
    area = screen.availableGeometry()
    w, h = min(720, area.width() - 40), min(940, area.height() - 80)
    win.resize(w, h)
    win.move(area.right() - w - 20, area.top() + 40)
    win.show()
    win.raise_()
    win.activateWindow()
    _LAST_PANEL, _WIN = panel, win
    return panel


class RobotDesignCommand:
    def GetResources(self):
        return {"MenuText": T("AI 设计整机…"),
                "ToolTip": T("写需求原话，AI 提整机构型，代码选件、三维装配、多体动力学与有限元复核，出报告、三维模型和 BOM，人确认后入企业库")}

    def Activated(self):
        try:
            open_panel()
        except Exception as exc:  # noqa: BLE001 — 打不开就说原因，并把详情写进本机日志
            import traceback

            from PySide import QtWidgets

            log = Path.home() / ".freecad-ai-parts" / "robot-design.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(traceback.format_exc(), encoding="utf-8")
            QtWidgets.QMessageBox.warning(FreeCADGui.getMainWindow(), T("AI 设计整机"), T(f"打不开：{exc}（详情在 {log}）"))

    def IsActive(self):
        return True
