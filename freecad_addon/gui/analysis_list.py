"""分析模块一览（ADR-0056）：菜单“AI Parts → 分析模块”，列出本机各分析模块是否可用、缺什么、怎么装。"""

from __future__ import annotations

from PySide import QtWidgets


class AnalysisListDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        import analysis

        self.setWindowTitle("分析模块（本机运行）")
        self.resize(760, 360)
        self.rows = analysis.modules()
        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel("每个模块在本机计算，不联网；结果是计算，不写入零件参数。"))
        self.table = QtWidgets.QTableWidget(len(self.rows), 3)
        self.table.setHorizontalHeaderLabels(["模块", "状态", "说明"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        for i, m in enumerate(self.rows):
            state = "可用" if m["available"] else "缺 " + "、".join(m["missing"])
            note = m["description"] if m["available"] else m["install"]
            for j, text in enumerate((m["name"], state, note)):
                self.table.setItem(i, j, QtWidgets.QTableWidgetItem(text))
        self.table.resizeColumnsToContents()
        lay.addWidget(self.table, 1)
        if not self.rows:
            lay.addWidget(QtWidgets.QLabel("第一批模块（多体动力学、有限元 + 疲劳、热分析 + 设计优化、数字孪生）开发中。"))
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
