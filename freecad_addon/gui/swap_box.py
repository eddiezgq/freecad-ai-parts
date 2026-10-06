"""校验窗口中的“换件建议”区（ADR-0052）：选一个零件，列出同品类可替换的组件与结论变化，一键换上。

建议经共用工具宿主调用 suggest_replacements（与 AI 用同一工具）；换上的调用序列在 core/swap.py（纯函数），
经 place_component / connect_ports 执行。人的换件直接生效，不成提案。
"""

from __future__ import annotations

import html
import threading

from PySide import QtCore, QtWidgets

from freecad_addon.core import swap
from freecad_addon.core.live_check import STATUS_TEXT
from freecad_addon.gui.host import _parse

RANK = {"fail": 0, "unknown": 1, "warn": 2, "pass": 3}


class SwapBox(QtWidgets.QGroupBox):
    found = QtCore.Signal(object)  # 后台线程中建议计算完成
    swapped = QtCore.Signal(object)  # 后台线程中换上完成（None 或错误文字）

    def __init__(self, panel, parent: QtWidgets.QWidget | None = None):
        super().__init__("换件建议", parent)
        self.panel = panel
        self.suggestions: list[dict] = []
        self.busy = False  # 正在计算建议或换上
        lay = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.instance = QtWidgets.QComboBox()
        self.find_button = QtWidgets.QPushButton("换件建议")
        row.addWidget(QtWidgets.QLabel("零件"))
        row.addWidget(self.instance, 1)
        row.addWidget(self.find_button)
        self.list = QtWidgets.QListWidget()
        self.list.setMaximumHeight(110)
        self.detail = QtWidgets.QLabel("")
        self.detail.setWordWrap(True)
        self.swap_button = QtWidgets.QPushButton("换上")
        self.swap_button.setEnabled(False)
        self.status = QtWidgets.QLabel("选一个零件（默认结论最差的），点“换件建议”。")
        self.status.setWordWrap(True)
        lay.addLayout(row)
        for w in (self.list, self.detail, self.swap_button, self.status):
            lay.addWidget(w)
        self.find_button.clicked.connect(lambda *_: self.find())
        self.swap_button.clicked.connect(lambda *_: self.swap_selected())
        self.list.currentRowChanged.connect(lambda *_: self._show_detail())
        self.found.connect(self._found, QtCore.Qt.QueuedConnection)
        self.swapped.connect(self._swapped, QtCore.Qt.QueuedConnection)

    # ------------------------------------------------------------ 零件列表

    def refresh_instances(self, layout: dict, result: dict) -> None:
        """场景变化后更新零件下拉框；保留原选择，否则选结论最差的。"""
        names = [i["instance"] for i in layout.get("instances", [])]
        keep = self.instance.currentText()
        status = (result or {}).get("instances", {})
        self.instance.blockSignals(True)
        self.instance.clear()
        self.instance.addItems(names)
        if keep in names:
            self.instance.setCurrentText(keep)
        elif names:
            self.instance.setCurrentText(min(names, key=lambda n: (RANK.get(status.get(n, "pass"), 3), n)))
        self.instance.blockSignals(False)
        self.find_button.setEnabled(bool(names) and not self.busy)

    # ------------------------------------------------------------ 建议

    def find(self) -> bool:
        inst = self.instance.currentText()
        if not inst:
            return False
        args = {"instance": inst}
        if self.panel.requirement:
            args["requirement"] = self.panel.requirement
        self.busy = True
        self.find_button.setEnabled(False)
        self.swap_button.setEnabled(False)
        self.status.setText(f"正在为 {inst} 计算换件建议 …")
        self.panel.host.call_in_background("suggest_replacements", args, self.found.emit)
        return True

    def _found(self, out) -> None:
        self.busy = False
        self.find_button.setEnabled(True)
        self.list.clear()
        if isinstance(out, Exception) or out.is_error:
            self.suggestions = []
            self.status.setText(f"没有算出建议：{out if isinstance(out, Exception) else '；'.join(out.texts)}")
            self._show_detail()
            return
        data = _parse(out) or {}
        self.suggestions = data.get("suggestions", [])
        for s in self.suggestions:
            mass = "" if s.get("mass_kg") is None else f"，{s['mass_kg']:g} kg"
            self.list.addItem(f"{s['overall_text']}：{s['model']}{mass}")
        cur = data.get("current", {})
        self.status.setText(f"{data.get('instance')} 当前结论：{STATUS_TEXT.get(cur.get('overall', ''), cur.get('overall', ''))}；"
                            f"可替换 {data.get('total', 0)} 个（列出前 {len(self.suggestions)} 个）"
                            if self.suggestions else "同品类中没有不至于不通过的替换件")
        if self.suggestions:
            self.list.setCurrentRow(0)
        self._show_detail()

    def selected(self) -> dict | None:
        i = self.list.currentRow()
        return self.suggestions[i] if 0 <= i < len(self.suggestions) else None

    def _show_detail(self) -> None:
        s = self.selected()
        self.swap_button.setEnabled(s is not None)
        if s is None:
            self.detail.setText("")
            return
        changes = s.get("changes") or ["校验结论没有变化"]
        self.detail.setText("<br>".join(html.escape(c) for c in changes))

    # ------------------------------------------------------------ 换上

    def swap_selected(self) -> bool:
        s, inst = self.selected(), self.instance.currentText()
        if s is None or not inst:
            return False
        try:
            calls = swap.swap_calls(self.panel.host.layout, inst, s["component_id"])
        except ValueError as exc:
            self.status.setText(f"不能换上：{exc}")
            return False
        self.busy = True
        self.find_button.setEnabled(False)
        self.swap_button.setEnabled(False)
        self.status.setText(f"正在把 {inst} 换成 {s['model']} …")

        def work() -> None:
            try:
                for name, args in calls:
                    out = self.panel.host.call(name, args)
                    if out.is_error:
                        raise RuntimeError(f"{name} {args}：{'；'.join(out.texts)}")
                self.swapped.emit(None)
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                self.swapped.emit(str(exc))

        threading.Thread(target=work, name="fap-swap", daemon=True).start()
        return True

    def _swapped(self, err) -> None:
        self.busy = False
        self.find_button.setEnabled(True)
        self.list.clear()
        self.suggestions = []
        self._show_detail()
        self.status.setText(f"换件中断：{err}" if err else "已换上；结论见上方，BOM 随之更新")
