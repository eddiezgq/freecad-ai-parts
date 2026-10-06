"""选型面板（ADR-0051 第 1 条）：填需求、查找方案、看候选与说明、一键放入布局。不经过对话。

查找经共用工具宿主调用 compose_chain（来源 user），校验窗口随之拿到需求；放入布局经 place_component /
connect_ports，与人工、AI 的改动走同一套工具。候选整理与调用序列在 core/selection.py（纯函数）。
"""

from __future__ import annotations

import html
import threading

from PySide import QtCore, QtWidgets

from freecad_addon.core import requirement_form, selection
from freecad_addon.gui.host import ToolsHost, _parse, get_host


class SelectionPanel(QtWidgets.QDockWidget):
    found = QtCore.Signal(object)  # 后台线程中查找完成后，排队回到界面线程
    placed = QtCore.Signal(object)  # 后台线程中放入完成后（None 表示成功，否则为错误文字）

    def __init__(self, parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None):
        super().__init__("AI Parts 选型", parent)
        self.setObjectName("FapSelectionPanel")
        self.host = host or get_host()
        self.rows: list[selection.CandidateRow] = []
        self.summary = ""

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        form = QtWidgets.QFormLayout()
        self.inputs: dict[str, QtWidgets.QLineEdit] = {}
        for key, label in requirement_form.FIELDS:
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("必填" if key in requirement_form.REQUIRED else "可空")
            form.addRow(label, edit)
            self.inputs[key] = edit
        self.include_unknown = QtWidgets.QCheckBox("包含待确认的方案（数据缺失或接口可配置）")
        self.include_unknown.setChecked(True)
        self.find_button = QtWidgets.QPushButton("查找方案")
        self.table = QtWidgets.QTableWidget(0, len(selection.HEADERS))
        self.table.setHorizontalHeaderLabels(selection.HEADERS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.detail = QtWidgets.QTextBrowser()
        self.place_button = QtWidgets.QPushButton("放入布局")
        self.place_button.setEnabled(False)
        self.status = QtWidgets.QLabel("填连续扭矩与输出转速，点“查找方案”。")
        self.status.setWordWrap(True)
        lay.addLayout(form)
        lay.addWidget(self.include_unknown)
        lay.addWidget(self.find_button)
        lay.addWidget(self.table, 2)
        lay.addWidget(self.detail, 3)
        lay.addWidget(self.place_button)
        lay.addWidget(self.status)
        self.setWidget(body)

        self.find_button.clicked.connect(lambda *_: self.find())
        self.place_button.clicked.connect(lambda *_: self.place_selected())
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.found.connect(self._found, QtCore.Qt.QueuedConnection)
        self.placed.connect(self._placed, QtCore.Qt.QueuedConnection)

    # ------------------------------------------------------------ 查找

    def requirement(self) -> tuple[dict | None, str | None]:
        return requirement_form.from_texts({k: e.text() for k, e in self.inputs.items()})

    def set_requirement(self, req: dict | None) -> None:
        for key, text in requirement_form.to_texts(req).items():
            self.inputs[key].setText(text)

    def find(self) -> bool:
        req, err = self.requirement()
        if err:
            self.status.setText(err)
            return False
        self.find_button.setEnabled(False)
        self.place_button.setEnabled(False)
        self.status.setText("正在查找 …")
        args = {"requirement": req, "top_n": 5, "include_unknown": self.include_unknown.isChecked()}
        self.host.call_in_background("compose_chain", args, self.found.emit)
        return True

    def _found(self, out) -> None:
        self.find_button.setEnabled(True)
        if isinstance(out, Exception) or out.is_error:
            self.rows, self.summary = [], ""
            self.status.setText(f"查找失败：{out if isinstance(out, Exception) else '；'.join(out.texts)}")
        else:
            result = _parse(out) or {}
            self.rows = selection.candidate_rows(result, self.host.library().get)
            self.summary = result.get("explanation", "")
            self.status.setText(f"找到 {len(self.rows)} 个方案" if self.rows else
                                "没有满足需求的方案；可勾选“包含待确认的方案”或放宽需求")
        self.table.setRowCount(len(self.rows))
        for i, row in enumerate(self.rows):
            for j, text in enumerate(selection.cells(row)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        if self.rows:
            self.table.selectRow(0)
        self._show_detail()

    def selected(self) -> selection.CandidateRow | None:
        idx = self.table.currentRow()
        return self.rows[idx] if 0 <= idx < len(self.rows) and self.table.selectedItems() else None

    def _show_detail(self) -> None:
        row = self.selected()
        self.place_button.setEnabled(row is not None)
        if row is None:
            self.detail.setHtml("<p style='color:#666'>" + html.escape(self.summary or "选一个方案查看说明。") + "</p>")
            return
        self.detail.setHtml(f"<p><b>方案 {row.rank}：{html.escape(row.status)}</b></p>"
                            f"<pre style='white-space:pre-wrap'>{html.escape(row.explanation)}</pre>")

    # ------------------------------------------------------------ 放入布局

    def place_selected(self, confirm: bool = True) -> bool:
        row = self.selected()
        if row is None:
            return False
        current = self.host.layout
        if confirm and current.get("instances"):
            ans = QtWidgets.QMessageBox.question(self, "放入布局", "放入前会清空当前场景中的零件和连接，继续吗？")
            if ans != QtWidgets.QMessageBox.Yes:
                return False
        try:
            calls, unmated = selection.place_calls(row.system, current, self.host.library().get)
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.status.setText(f"不能放入：{exc}")
            return False
        self.place_button.setEnabled(False)
        self.find_button.setEnabled(False)
        self.status.setText(f"正在放入方案 {row.rank} …")

        def work() -> None:
            try:
                for name, args in calls:
                    out = self.host.call(name, args)
                    if out.is_error:
                        raise RuntimeError(f"{name} {args}：{'；'.join(out.texts)}")
                for name, args in selection.side_calls(self.host.layout, unmated):
                    out = self.host.call(name, args)
                    if out.is_error:
                        raise RuntimeError(f"{name} {args}：{'；'.join(out.texts)}")
                self.placed.emit(None)
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                self.placed.emit(str(exc))

        threading.Thread(target=work, name="fap-place-candidate", daemon=True).start()
        return True

    def _placed(self, err) -> None:
        self.find_button.setEnabled(True)
        self.place_button.setEnabled(self.selected() is not None)
        self.status.setText(f"放入中断：{err}" if err else "已放入布局；结论见“校验”窗口，清单见“BOM”窗口")
