"""发布到工厂对话框（ADR-0058，M10 第 6c 项）：把当前方案（BOM、需求、校验结论、布局 STEP）发到本地工厂枢纽，
工厂工作台“CAD 方案”页列出。内容组成与通信在 core/factory_link.py；发布在后台线程中进行。
"""

from __future__ import annotations

import datetime
import tempfile
import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.core import factory_link, library_choice


def export_layout_step(doc_name: str = "FapLayout") -> str | None:
    """把布局文档里的实体导出为一个 STEP（文件名只用字母数字，便于上传）；没有布局时为 None。"""
    try:
        import FreeCAD
        import Part
    except ImportError:
        return None
    if doc_name not in FreeCAD.listDocuments():
        return None
    objs = [o for o in FreeCAD.getDocument(doc_name).Objects if getattr(o, "Shape", None) is not None
            and not o.Shape.isNull() and o.Shape.Solids]
    if not objs:
        return None
    path = Path(tempfile.mkdtemp(prefix="fap-pub-")) / "layout.step"
    Part.export(objs, str(path))
    return str(path)


class PublishDialog(QtWidgets.QDialog):
    done = QtCore.Signal(object)

    def __init__(self, host, check_panel=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("发布到工厂")
        self.host, self.check_panel = host, check_panel
        self.result: dict | None = None
        self.busy = False
        settings = library_choice.read_settings()
        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.url = QtWidgets.QLineEdit(settings.get("factory_url", factory_link.DEFAULT_URL))
        self.mode = QtWidgets.QComboBox()
        self.mode.addItem("演示（仿真车间）", "teach")
        self.mode.addItem("生产", "prod")
        self.code = QtWidgets.QLineEdit("DESIGN-" + datetime.datetime.now().astimezone().strftime("%Y%m%d"))
        self.name = QtWidgets.QLineEdit()
        self.name.setPlaceholderText("方案名称，如“六轴臂第 2 关节”")
        self.note = QtWidgets.QLineEdit()
        self.note.setPlaceholderText("改动说明（可空）")
        self.author = QtWidgets.QLineEdit(settings.get("actor", ""))
        self.author.setPlaceholderText("发布人（企业版工厂填用户名）")
        self.password = QtWidgets.QLineEdit()           # 企业版工厂（ADR-0063）；不保存
        self.password.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password.setPlaceholderText("企业版工厂才要填")
        self.with_step = QtWidgets.QCheckBox("附上布局的 STEP 模型")
        self.with_step.setChecked(True)
        for label, w in (("工厂地址", self.url), ("模式", self.mode), ("方案编号", self.code), ("名称", self.name),
                         ("说明", self.note), ("发布人", self.author), ("密码", self.password),
                         ("", self.with_step)):
            form.addRow(label, w)
        lay.addLayout(form)
        self.status = QtWidgets.QLabel("本地工厂用 factory/local/start 启动；发布后到工厂工作台“CAD 方案”页查看。")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        self.publish_button = buttons.addButton("发布", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(lambda *_: self.publish())
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.done.connect(self._done, QtCore.Qt.QueuedConnection)

    def data(self) -> dict:
        lib = self.host.library()
        cp = self.check_panel
        return factory_link.payload(self.host.layout, lib.get, code=self.code.text(), name=self.name.text(),
                                    origin=getattr(lib, "origin", None), requirement=getattr(cp, "requirement", None),
                                    checks=getattr(cp, "result", None), note=self.note.text())

    def publish(self) -> bool:
        if self.busy:
            return False
        try:
            data = self.data()
        except factory_link.FactoryError as exc:
            self.status.setText(str(exc))
            return False
        step = export_layout_step() if self.with_step.isChecked() else None
        url, author, mode = self.url.text().strip(), self.author.text(), self.mode.currentData()
        self.busy = True
        self.publish_button.setEnabled(False)
        self.status.setText("正在发布 …")

        def work() -> None:
            try:
                out = factory_link.publish(factory_link.HubClient(url, cafile=library_choice.read_settings().get("factory_cafile")), author, mode, data, step,
                                           password=self.password.text() or None)
            except factory_link.FactoryError as exc:
                out = exc
            self.done.emit(out)

        threading.Thread(target=work, name="fap-publish", daemon=True).start()
        return True

    def _done(self, out) -> None:
        self.busy = False
        self.publish_button.setEnabled(True)
        if isinstance(out, Exception):
            self.status.setText(f"没有发布：{out}")
            return
        self.result = out
        library_choice.write_setting("factory_url", self.url.text().strip())
        library_choice.write_setting("actor", self.author.text().strip())
        self.status.setText(f"已发布 {out['code']} 第 {out['revision']} 版。到工厂工作台“CAD 方案”页查看。")
