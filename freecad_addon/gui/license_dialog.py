"""授权与席位（ADR-0066 第 6 项）：本机授权状态、激活码（离线激活）、导入授权文件、向企业数字工厂租浮动席位。
公开功能不需要授权；这里只管闭源功能。"""

from __future__ import annotations

import atexit
import getpass
import shutil
import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.core import library_choice
from licensing import runtime
from licensing.fingerprint import activation_code


class SeatKeeper:
    """后台租席位并定时续租，退出时归还。"""

    _instance = None

    def __init__(self, url: str, cafile: str | None):
        from licensing.seat_client import SeatClient

        self.client = SeatClient(url, cafile)
        self.state: dict = {"ok": False, "reason": "还没租"}
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        atexit.register(self.stop)

    def _run(self):
        user = getpass.getuser()
        self.state = self.client.acquire(user)
        while not self._stop.wait(5 * 60):
            self.state = self.client.renew(user)

    def stop(self):
        self._stop.set()
        self.client.release()

    @classmethod
    def start(cls, url: str, cafile: str | None) -> SeatKeeper:
        if cls._instance is None:
            cls._instance = cls(url, cafile)
            cls._instance.thread.start()
        return cls._instance


def start_seat_if_configured() -> None:
    s = library_choice.read_settings()
    if s.get("seat_auto") and s.get("factory_url") and not runtime.current().valid:
        SeatKeeper.start(s["factory_url"], s.get("factory_cafile"))


class LicenseDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("授权与席位")
        self.setMinimumWidth(560)
        lay = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel("工作台、选型校验、公开零件库、分析模块不需要授权。授权只用于企业零件库订阅等闭源功能。")
        note.setWordWrap(True)
        lay.addWidget(note)

        box = QtWidgets.QGroupBox("本机授权")
        f = QtWidgets.QFormLayout(box)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        f.addRow("状态", self.status)
        code = QtWidgets.QLineEdit()
        code.setReadOnly(True)
        try:
            code.setText(activation_code())
        except RuntimeError as exc:
            code.setText(str(exc))
        copy = QtWidgets.QPushButton("复制")
        copy.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(code.text()))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(code)
        row.addWidget(copy)
        f.addRow("激活码", row)
        hint = QtWidgets.QLabel("没有工厂服务器的单机用户：把激活码发给我们，收到授权文件后点“导入授权文件”。")
        hint.setWordWrap(True)
        f.addRow(hint)
        imp = QtWidgets.QPushButton("导入授权文件…")
        imp.clicked.connect(self._import)
        f.addRow(imp)
        lay.addWidget(box)

        pack = QtWidgets.QGroupBox("零件库订阅包")
        h = QtWidgets.QFormLayout(pack)
        self.pack_state = QtWidgets.QLabel(library_choice.read_settings().get("parts_pack") or "未选择")
        self.pack_state.setWordWrap(True)
        choose_pack = QtWidgets.QPushButton("选择订阅包…")
        choose_pack.clicked.connect(self._choose_pack)
        h.addRow(choose_pack, self.pack_state)
        h.addRow(QtWidgets.QLabel("授权里有“零件库订阅”时，重启 FreeCAD 后叠加在公共库之上。"))
        lay.addWidget(pack)

        seat = QtWidgets.QGroupBox("浮动席位（企业数字工厂服务器）")
        g = QtWidgets.QFormLayout(seat)
        s = library_choice.read_settings()
        self.factory = s.get("factory_url", "")
        g.addRow("工厂地址", QtWidgets.QLabel(self.factory or "未设置（在“首次设置”里填）"))
        self.seat_state = QtWidgets.QLabel("")
        self.seat_state.setWordWrap(True)
        self.auto = QtWidgets.QCheckBox("打开工作台时自动租席位")
        self.auto.setChecked(bool(s.get("seat_auto")))
        lease = QtWidgets.QPushButton("现在租一个席位")
        lease.setEnabled(bool(self.factory))
        lease.clicked.connect(self._lease)
        g.addRow(lease, self.seat_state)
        g.addRow(self.auto)
        lay.addWidget(seat)
        close = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        lay.addWidget(close)
        self._refresh()

    def _refresh(self):
        self.status.setText(runtime.current().reason)
        k = SeatKeeper._instance
        if k is not None:
            self.seat_state.setText(k.state.get("reason", ""))

    def _import(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择授权文件", "", "授权文件 (*.json);;所有文件 (*)")
        if not path:
            return
        v = runtime.current(Path(path))
        if not v.valid:
            QtWidgets.QMessageBox.warning(self, "授权", f"这个授权文件不能用：{v.reason}")
            return
        runtime.USER_LICENSE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, runtime.USER_LICENSE)
        self._refresh()

    def _choose_pack(self):
        from licensing import keys
        from licensing.parts_pack import PackError, verify_pack

        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择零件库订阅包", "", "订阅包 (*.zip);;所有文件 (*)")
        if not path:
            return
        try:
            info = verify_pack(Path(path), keys.PUBLIC_KEYS)
        except PackError as exc:
            QtWidgets.QMessageBox.warning(self, "零件库订阅包", f"这个订阅包不能用：{exc}")
            return
        library_choice.write_setting("parts_pack", path)
        self.pack_state.setText(f"{path}（{info['customer']}，版本 {info['version']}，{info['count']} 条）")

    def _lease(self):
        SeatKeeper.start(self.factory, library_choice.read_settings().get("factory_cafile"))
        self.seat_state.setText("正在租…")
        QtCore.QTimer.singleShot(1500, self._refresh)

    def reject(self):
        library_choice.write_setting("seat_auto", self.auto.isChecked())
        super().reject()


def show(parent=None) -> LicenseDialog:
    dlg = LicenseDialog(parent)
    dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
    return dlg
