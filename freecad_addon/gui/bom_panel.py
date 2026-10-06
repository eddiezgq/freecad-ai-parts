"""BOM 面板（ADR-0051 第 2 条）：由当前场景列出物料清单（厂商、型号、数量、质量、出处、复核状态、许可、原厂 CAD），
场景每次改动后自动刷新，可导出 CSV / JSON。整理在 core/bom_view.py（纯函数）。
"""

from __future__ import annotations

from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.core import bom_view
from freecad_addon.gui.host import ToolsHost, get_host


class BomPanel(QtWidgets.QDockWidget):
    changed = QtCore.Signal()  # 后台线程中布局变化后，排队回到界面线程刷新

    def __init__(self, parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None):
        super().__init__("AI Parts BOM", parent)
        self.setObjectName("FapBomPanel")
        self.host = host or get_host()
        self.layout_state: dict = dict(self.host.layout)
        self.result: dict = {"rows": [], "total_mass_kg": 0.0, "count": 0}
        self.host.listeners.append(self._on_tool)

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        self.table = QtWidgets.QTableWidget(0, len(bom_view.HEADERS))
        self.table.setHorizontalHeaderLabels(bom_view.HEADERS)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.total = QtWidgets.QLabel("")
        self.note = QtWidgets.QLabel("价格、交期等采购信息尚未收录。")
        self.note.setWordWrap(True)
        self.csv_button = QtWidgets.QPushButton("导出 CSV")
        self.json_button = QtWidgets.QPushButton("导出 JSON")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.csv_button)
        row.addWidget(self.json_button)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.total)
        lay.addWidget(self.note)
        lay.addLayout(row)
        lay.addWidget(self.status)
        self.setWidget(body)

        self.changed.connect(self.refresh, QtCore.Qt.QueuedConnection)
        self.csv_button.clicked.connect(lambda *_: self.export("csv"))
        self.json_button.clicked.connect(lambda *_: self.export("json"))
        self.refresh()

    def _on_tool(self, name: str, info: dict) -> None:
        layout = (info.get("result") or {}).get("layout")
        if isinstance(layout, dict):
            self.layout_state = layout
            self.changed.emit()

    def refresh(self) -> dict:
        try:
            self.result = bom_view.bom(self.layout_state, self.host.library().get)
            self.status.setText("")
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.result = {"rows": [], "total_mass_kg": None, "count": 0}
            self.status.setText(f"不能生成 BOM：{exc}")
        rows = self.result["rows"]
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, text in enumerate(bom_view.cells(r)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        self.total.setText(bom_view.total_text(self.result) if rows or not self.status.text() else "")
        enabled = bool(rows)
        self.csv_button.setEnabled(enabled)
        self.json_button.setEnabled(enabled)
        return self.result

    def export(self, fmt: str, path: str | None = None) -> str | None:
        """导出到 path；不给 path 时弹出保存对话框。返回写入的路径。"""
        try:
            name, text = bom_view.export_text(self.layout_state, self.host.library().get, fmt)
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.status.setText(f"不能导出：{exc}")
            return None
        if path is None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "导出 BOM", str(Path.home() / name),
                                                            "CSV (*.csv)" if fmt == "csv" else "JSON (*.json)")
            if not path:
                return None
        Path(path).write_text(text, encoding="utf-8", newline="")
        self.status.setText(f"已导出：{path}")
        return path

    def closeEvent(self, event) -> None:
        if self._on_tool in self.host.listeners:
            self.host.listeners.remove(self._on_tool)
        super().closeEvent(event)
