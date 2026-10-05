"""库浏览器（ADR-0048 第 3 条）：在 FreeCAD 中按品类、文字、参数范围搜零件，看参数出处与复核状态，放入布局。

筛选与详情的整理在 core/browser.py（纯函数）；“放入布局”经共用工具宿主调用 place_component，与 AI 走同一套工具。
"""

from __future__ import annotations

import html

from PySide import QtCore, QtWidgets

from freecad_addon.core import browser as core
from freecad_addon.gui.host import ToolsHost, get_host

ALL = "全部品类"


class LibraryBrowser(QtWidgets.QDockWidget):
    placed = QtCore.Signal(object)  # 后台线程中工具调用完成后，排队回到界面线程

    def __init__(self, parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None):
        super().__init__("AI Parts 零件库", parent)
        self.setObjectName("FapLibraryBrowser")
        self.host = host or get_host()
        self.instances: set[str] = set()  # 场景中已有的实例名（人或 AI 放入的都算）
        self.host.listeners.append(self._on_scene)

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        self.header = QtWidgets.QLabel(self.host.note)
        self.header.setWordWrap(True)
        self.category = QtWidgets.QComboBox()
        self.category.addItem(ALL, None)
        for key, name in core.CATEGORIES.items():
            self.category.addItem(name, key)
        self.text = QtWidgets.QLineEdit()
        self.text.setPlaceholderText("型号或厂商，如 csf 25、sgm7j")
        self.param = QtWidgets.QComboBox()
        self.lo, self.hi = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        self.lo.setPlaceholderText("最小")
        self.hi.setPlaceholderText("最大")
        rng = QtWidgets.QHBoxLayout()
        for w in (self.param, self.lo, self.hi):
            rng.addWidget(w)
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.detail = QtWidgets.QTextBrowser()
        self.place_button = QtWidgets.QPushButton("放入布局")
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        for w in (self.header, self.category, self.text):
            lay.addWidget(w)
        lay.addLayout(rng)
        lay.addWidget(self.table, 2)
        lay.addWidget(self.detail, 3)
        lay.addWidget(self.place_button)
        lay.addWidget(self.status)
        self.setWidget(body)

        self.category.currentIndexChanged.connect(lambda *_: self._category_changed())
        for w in (self.text, self.lo, self.hi):
            w.textChanged.connect(lambda *_: self.refresh())
        self.param.currentIndexChanged.connect(lambda *_: self.refresh())
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.place_button.clicked.connect(lambda *_: self.place_selected())
        self.placed.connect(self._placed, QtCore.Qt.QueuedConnection)
        self._rows: list[core.Row] = []
        self._category_changed()

    # ------------------------------------------------------------ 列表

    def _category_changed(self) -> None:
        cat = self.category.currentData()
        self.param.blockSignals(True)
        self.param.clear()
        self.param.addItem("按参数范围（不限）", None)
        for label, path in core.KEY_FIELDS.get(cat or "", []):
            unit = core.unit_of(path)
            self.param.addItem(f"{label}{f'（{unit}）' if unit else ''}", path)
        self.param.blockSignals(False)
        self.refresh()

    @staticmethod
    def _num(text: str) -> float | None:
        try:
            return float(text) if text.strip() else None
        except ValueError:
            return None

    def refresh(self) -> None:
        cat, path = self.category.currentData(), self.param.currentData()
        lo, hi = self._num(self.lo.text()), self._num(self.hi.text())
        ranges = {path: (lo, hi)} if path and (lo is not None or hi is not None) else None
        self._rows = core.rows(self.host.library().all(), cat, self.text.text(), ranges)
        labels = [label for label, _ in core.KEY_FIELDS.get(cat or "", [])]
        heads = ["厂商", "型号"] + (labels if cat else ["品类"])
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        self.table.setRowCount(len(self._rows))
        for i, r in enumerate(self._rows):
            cells = [r.vendor, r.model] + ([v for _, v in r.key] if cat else [core.CATEGORIES.get(r.category, "")])
            for j, text in enumerate(cells):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.status.setText(f"{len(self._rows)} 个组件")
        self._show_detail()

    def selected(self) -> core.Row | None:
        idx = self.table.currentRow()
        return self._rows[idx] if 0 <= idx < len(self._rows) and self.table.selectedItems() else None

    # ------------------------------------------------------------ 详情

    def _show_detail(self) -> None:
        row = self.selected()
        self.place_button.setEnabled(row is not None)
        if row is None:
            self.detail.setHtml("<p style='color:#666'>选一个组件查看参数出处与复核状态。</p>")
            return
        self.detail.setHtml(render_detail(core.detail(self.host.library().get(row.id))))

    # ------------------------------------------------------------ 放入布局

    def _on_scene(self, name: str, info: dict) -> None:
        if name == "place_component":
            self.instances.add(info["args"]["instance"])

    def place_selected(self) -> str | None:
        row = self.selected()
        if row is None:
            return None
        inst = core.instance_name(row.category, self.instances)
        self.place_button.setEnabled(False)
        self.status.setText(f"正在放入 {inst} …")
        self.host.call_in_background("place_component", {"instance": inst, "component_id": row.id},
                                     lambda out: self.placed.emit((inst, out)))
        return inst

    def _placed(self, item) -> None:
        inst, out = item
        self.place_button.setEnabled(self.selected() is not None)
        if isinstance(out, Exception) or out.is_error:
            text = str(out) if isinstance(out, Exception) else "；".join(out.texts)
            self.status.setText(f"没有放入 {inst}：{text}")
        else:
            self.status.setText(f"已放入 {inst}（显示在 FapLayout 文档中）")

    def closeEvent(self, event) -> None:
        if self._on_scene in self.host.listeners:
            self.host.listeners.remove(self._on_scene)
        super().closeEvent(event)


def render_detail(d: dict) -> str:
    esc = html.escape

    def table(items: list[dict]) -> str:
        if not items:
            return "<p style='color:#666'>（无）</p>"
        rows = "".join(
            f"<tr><td>{esc(i['name'])}</td><td><b>{esc(i['value'])}</b></td><td>{esc(i['condition'])}</td>"
            f"<td>{esc(i['source'])}</td><td>{esc(i['review'])}</td></tr>" for i in items)
        return ("<table cellspacing='0' cellpadding='3' border='1'>"
                "<tr><th>项</th><th>值</th><th>工况</th><th>来源</th><th>复核</th></tr>" + rows + "</table>")

    parts = [f"<h3>{esc(d['title'])}</h3>",
             (f"<p>{esc(d['category'])} · <code>{esc(d['id'])}</code><br>"
              f"来源：{esc('、'.join(d['docs']) or '—')} · 已复核 {esc(d['reviewed'])} · 许可 {esc(d['license'])}</p>"),
             "<h4>参数</h4>", table(d["params"]), "<h4>端口</h4>"]
    for p in d["ports"]:
        extra = "，按配套件定制（厂商不规定）" if p["configurable"] else ""
        parts.append(f"<p><b>{esc(p['id'])}</b> {esc(p['kind'])} · {esc(p['type'])} · {esc(p['dir'])}{esc(extra)}</p>")
        parts.append(table(p["spec"]))
    return "".join(parts)
