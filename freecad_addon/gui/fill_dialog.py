"""补数据对话框（M9 第二步）：为场景中的一个零件补一项数据，附企业资料、页码、原文与录入人，写入企业库。

字段列表与参数值的组成在 core/fill.py（纯函数）；写入、校验与历史记录在 kb/enterprise.py。
"""

from __future__ import annotations

from PySide import QtWidgets

from freecad_addon.core import fill, library_choice

NEW_DOC = "登记新资料…"


class FillDialog(QtWidgets.QDialog):
    def __init__(self, library, component_id: str, focus_ports=frozenset(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("补数据（写入企业库）")
        self.library, self.component_id = library, component_id
        self.enterprise = getattr(library, "top", None)
        self.saved: dict | None = None
        comp = library.get(component_id)
        self.rows = fill.fields(comp, set(focus_ports))

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"<b>{comp.get('vendor', '')} {comp.get('model', '')}</b>"
                                       f"<br><span style='color:#666'>{component_id}</span>"))
        form = QtWidgets.QFormLayout()
        self.field = QtWidgets.QComboBox()
        for r in self.rows:
            self.field.addItem(r.title(), r.target)
        self.current = QtWidgets.QLabel("")
        self.value = QtWidgets.QLineEdit()
        self.tol_upper, self.tol_lower = QtWidgets.QLineEdit(), QtWidgets.QLineEdit()
        tol = QtWidgets.QHBoxLayout()
        for w, ph in ((self.tol_upper, "上偏差（可空）"), (self.tol_lower, "下偏差（可空）")):
            w.setPlaceholderText(ph)
            tol.addWidget(w)
        self.condition = QtWidgets.QLineEdit()
        self.condition.setPlaceholderText("工况（规格书写了就填，如“额定、25 °C”）")
        self.doc = QtWidgets.QComboBox()
        self.page = QtWidgets.QSpinBox()
        self.page.setRange(0, 9999)
        self.page.setSpecialValueText("（页码）")
        self.quote = QtWidgets.QLineEdit()
        self.quote.setPlaceholderText("照抄规格书原文，如 “Pilot dia. 50 h7”")
        self.actor = QtWidgets.QLineEdit(library_choice.read_settings().get("actor", ""))
        self.actor.setPlaceholderText("录入人姓名")
        form.addRow("字段", self.field)
        form.addRow("当前值", self.current)
        form.addRow("值", self.value)
        form.addRow("公差", tol)
        form.addRow("工况", self.condition)
        form.addRow("资料", self.doc)
        form.addRow("页码", self.page)
        form.addRow("原文", self.quote)
        form.addRow("录入人", self.actor)
        lay.addLayout(form)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(lambda *_: self.save())
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.field.currentIndexChanged.connect(lambda *_: self._show_field())
        self.doc.activated.connect(lambda *_: self._doc_chosen())
        self._load_docs()
        self._show_field()
        if self.enterprise is None:
            self.status.setText("还没有企业库：请先在菜单“AI Parts → 企业库”中选择企业库文件夹，重启 FreeCAD 后再补数据。")
            buttons.button(QtWidgets.QDialogButtonBox.Save).setEnabled(False)

    def row(self) -> fill.FieldRow | None:
        i = self.field.currentIndex()
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def _show_field(self) -> None:
        r = self.row()
        if r is None:
            return
        note = "（缺）" if r.missing else r.current
        if r.configurable_port:
            note += "；此端口按配套件定制，填的是贵公司订货时确定的尺寸"
        if r.enum:
            note += f"；可选：{'、'.join(map(str, r.enum))}"
        self.current.setText(note)

    def _load_docs(self, select: str | None = None) -> None:
        self.doc.clear()
        for d in (self.enterprise.documents() if self.enterprise is not None else []):
            self.doc.addItem(f"{d['title']}（{d['id']}）", d["id"])
        self.doc.addItem(NEW_DOC, None)
        if select is not None:
            self.doc.setCurrentIndex(max(0, self.doc.findData(select)))

    def _doc_chosen(self) -> None:
        if self.doc.currentData() is None and self.enterprise is not None:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择规格书", "", "规格书 (*.pdf *.xlsx *.xls *.csv)")
            if path:
                self.register(path)

    def register(self, path: str, title: str | None = None) -> str | None:
        from pathlib import Path

        actor = self.actor.text().strip()
        if not actor:
            self.status.setText("请先填录入人，再登记资料")
            return None
        try:
            d = self.enterprise.register_document(path, title or Path(path).stem, actor)
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.status.setText(f"不能登记：{exc}")
            return None
        self._load_docs(d["id"])
        return d["id"]

    def save(self) -> bool:
        r = self.row()
        if r is None or self.enterprise is None:
            return False
        try:
            pv = fill.build_pv(r, self.value.text(), doc=self.doc.currentData(), page=self.page.value() or None,
                               quote=self.quote.text(), actor=self.actor.text(), tol_upper=self.tol_upper.text(),
                               tol_lower=self.tol_lower.text(), condition=self.condition.text())
            base = getattr(self.library, "base", self.library)
            self.enterprise.set_value(self.component_id, r.target, pv, self.actor.text().strip(), base.get)
        except Exception as exc:  # noqa: BLE001 — 显示给用户，不写
            self.status.setText(f"没有写入：{exc}")
            return False
        library_choice.write_setting("actor", self.actor.text().strip())
        self.saved = {"target": r.target, "value": pv}
        self.accept()
        return True
