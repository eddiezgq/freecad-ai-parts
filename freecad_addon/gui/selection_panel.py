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

    parsed = QtCore.Signal(object)  # 后台线程中一句话需求解析完成

    def __init__(self, parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None,
                 client_factory=None):
        super().__init__("AI Parts 选型", parent)
        self.setObjectName("FapSelectionPanel")
        self.host = host or get_host()
        self.rows: list[selection.CandidateRow] = []
        self.summary = ""
        self.extra: dict = {}  # 一句话需求带入、表单中没有栏位的指标（ADR-0054）
        self._client_factory = client_factory  # 测试注入；缺省真实调用（密钥只从环境变量或 .env 读取）

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        # 一句话需求（ADR-0054）：LLM 解析、代码核对，只填表单
        self.sentence = QtWidgets.QPlainTextEdit()
        self.sentence.setPlaceholderText("一句话需求，例如：六轴机械臂第 2 关节，连续 25 N·m、峰值 50 N·m，30 rpm，200 V 三相")
        self.sentence.setMaximumHeight(60)
        self.parse_button = QtWidgets.QPushButton("解析（填入下表，核对后再查找）")
        self.parse_note = QtWidgets.QLabel("")
        self.parse_note.setWordWrap(True)
        self.parse_note.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.clear_button = QtWidgets.QPushButton("清除")
        prow = QtWidgets.QHBoxLayout()
        prow.addWidget(self.parse_button, 1)
        prow.addWidget(self.clear_button)
        lay.addWidget(self.sentence)
        lay.addLayout(prow)
        lay.addWidget(self.parse_note)
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
        self.parse_button.clicked.connect(lambda *_: self.parse())
        self.clear_button.clicked.connect(lambda *_: self.clear())
        self.parsed.connect(self._parsed, QtCore.Qt.QueuedConnection)
        self.parsing = False

    # ------------------------------------------------------------ 查找

    def requirement(self) -> tuple[dict | None, str | None]:
        req, err = requirement_form.from_texts({k: e.text() for k, e in self.inputs.items()})
        return requirement_form.with_extra(req, self.extra), err

    # ------------------------------------------------------------ 一句话需求（ADR-0054）

    def parse(self) -> bool:
        text = self.sentence.toPlainText().strip()
        if not text or self.parsing:
            return False
        try:
            if self._client_factory is not None:
                client = self._client_factory()
            else:
                from ingest.llm_extract import AnthropicClient

                client = AnthropicClient()
        except Exception as exc:  # noqa: BLE001 — 缺密钥、缺依赖等
            self.parse_note.setText(f"不能解析：{exc}。可以直接在下表填数。")
            return False
        self.parsing = True
        self.parse_button.setEnabled(False)
        self.parse_note.setText("正在解析 …")

        def work() -> None:
            from engine import requirement_parse

            try:
                self.parsed.emit(requirement_parse.parse(text, client))
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                self.parsed.emit(exc)

        threading.Thread(target=work, name="fap-parse", daemon=True).start()
        return True

    def _parsed(self, out) -> None:
        self.parsing = False
        self.parse_button.setEnabled(True)
        if isinstance(out, Exception):
            self.parse_note.setText(f"解析失败：{out}。可以直接在下表填数。")
            return
        texts, self.extra, lines = requirement_form.merge_parsed(out)
        for key, text in texts.items():
            self.inputs[key].setText(text)
        shown = {k: v for k, v in self.extra.items() if k != "statement"}
        if shown:
            lines.append("表单外一并带入：" + "，".join(
                f"{requirement_form.FIELD_NAMES.get(k, k)} {v}" for k, v in shown.items()))
        head = "解析完成，请核对下表后点“查找方案”" if out.get("status") == "ok" else "还缺必填项，请补充后再查找"
        self.parse_note.setText(head + ("\n" + "\n".join(lines) if lines else ""))

    def clear(self) -> None:
        self.extra = {}
        self.sentence.clear()
        self.parse_note.setText("")
        for e in self.inputs.values():
            e.clear()

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
