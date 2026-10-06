"""数字孪生窗口（ADR-0057，M10 第五步）：当前布局中的减速器与轴承 + 运行记录（CSV）→ 已用寿命、剩余寿命、报警；
“假如”负载变了怎么样。参数取自零件库（公共库或企业库），缺的为待确认，可用“补数据”或“导入规格书”补。
"""

from __future__ import annotations

from PySide import QtGui, QtWidgets

STATUS = {"ok": ("正常", "#2e7d32"), "warn": ("警告", "#b26a00"), "severe": ("严重", "#c62828"),
          "unknown": ("待确认", "#6d6d6d")}
HEADERS = ["零件", "型号", "状态", "已用寿命", "剩余（小时）", "假如", "说明"]


class TwinPanel(QtWidgets.QDockWidget):
    def __init__(self, parent=None, host=None):
        super().__init__("数字孪生", parent)
        self.setObjectName("FapTwinPanel")
        self._host = host
        self.records: list[dict] = []
        self.result: dict | None = None
        w = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.csv_label = QtWidgets.QLabel("（未读入运行记录）")
        self.csv_button = QtWidgets.QPushButton("读运行记录 CSV")
        self.csv_button.setToolTip("列：instance, hours, output_torque_avg_nm, output_torque_max_nm, output_speed_rpm,"
                                   " radial_load_n, speed_rpm")
        row.addWidget(self.csv_label, 1)
        row.addWidget(self.csv_button)
        lay.addLayout(row)
        form = QtWidgets.QFormLayout()
        self.load_factor = QtWidgets.QLineEdit()
        self.load_factor.setPlaceholderText("如 0.8（空 = 不做假如）")
        form.addRow("假如负载 ×", self.load_factor)
        lay.addLayout(form)
        self.run_button = QtWidgets.QPushButton("按当前布局建孪生并计算")
        lay.addWidget(self.run_button)
        self.table = QtWidgets.QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel("把设备的运行记录导成 CSV，读入后计算。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.setWidget(w)
        self.csv_button.clicked.connect(lambda *_: self._browse())
        self.run_button.clicked.connect(lambda *_: self.compute())

    def host(self):
        from freecad_addon.gui.host import get_host

        return self._host or get_host()

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "运行记录", "", "CSV (*.csv)")
        if path:
            self.load_csv(path)

    def load_csv(self, path: str) -> bool:
        from pathlib import Path

        from analysis import twin

        try:
            self.records = twin.read_csv(path)
        except (OSError, ValueError) as exc:
            self.status.setText(f"读不了：{exc}")
            return False
        self.csv_label.setText(f"{Path(path).name}：{len(self.records)} 条")
        return True

    def compute(self) -> bool:
        from analysis import twin

        host = self.host()
        system = {"components": [{"instance": i["instance"], "component": i["component"]}
                                 for i in host.layout.get("instances", [])]}
        parts = twin.parts_from_system(system, host.library().get)
        if not parts:
            self.status.setText("当前布局中没有减速器或轴承")
            return False
        setup: dict = {"parts": parts, "records": self.records}
        if self.load_factor.text().strip():
            try:
                setup["whatif"] = {"load_factor": float(self.load_factor.text())}
            except ValueError:
                self.status.setText("假如负载须为数字")
                return False
        import analysis

        out = analysis.run("twin", setup)
        if out["status"] != "ok":
            self.status.setText("；".join(out["messages"]))
            return False
        self.result = out
        self._fill(out["data"])
        return True

    def _fill(self, data: dict) -> None:
        parts = data["parts"]
        wi = {p["instance"]: p for p in (data.get("whatif") or {}).get("parts", [])}
        self.table.setRowCount(len(parts))
        for i, p in enumerate(parts):
            text, color = STATUS[p["status"]]
            used = f"{p['used_ratio']:.1%}" if p.get("used_ratio") is not None else "—"
            rem = f"{p['remaining_h']:,.0f}" if p.get("remaining_h") is not None else "—"
            w = wi.get(p["instance"])
            whatif = f"{w['remaining_h']:,.0f} h" if w and w.get("remaining_h") is not None else "—"
            note = p.get("note") or "；".join(a["text"] for a in p.get("alerts", []))
            for j, t in enumerate((p["instance"], p["model"], text, used, rem, whatif, note)):
                item = QtWidgets.QTableWidgetItem(t)
                if j == 2:
                    item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()
        overall = STATUS[data["overall"]][0]
        first = f"，最先到期：{data['first_due']}" if data.get("first_due") else ""
        unknown = sum(p["status"] == "unknown" for p in parts)
        hint = f"；{unknown} 个零件缺样本参数（待确认），可在校验窗口用“补数据”补" if unknown else ""
        self.status.setText(f"整体：{overall}{first}{hint}")
