"""首次设置对话框（ADR-0066 第 3 项）：AI 密钥（存本机用户目录）、可选的企业数字工厂地址与测试连接。
单机安装版第一次打开 AI Parts 工作台时弹出；以后在菜单“首次设置”里再打开。逻辑在 core/first_run.py。
"""

from __future__ import annotations

import os

from PySide import QtWidgets

from freecad_addon.core import first_run, library_choice


class FirstRunDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Parts 首次设置")
        self.setMinimumWidth(520)
        settings = library_choice.read_settings()
        from llm_gateway import load_dotenv

        load_dotenv()
        status = first_run.key_status(os.environ)
        lay = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel("选型、零件库、校验、BOM、有限元等不需要设置就能用。下面两项可以以后再填。")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        ai = QtWidgets.QGroupBox("1. AI 对话的密钥（只存在本机用户目录，不进安装目录）")
        f1 = QtWidgets.QFormLayout(ai)
        self.provider = QtWidgets.QComboBox()
        for pid, (label, _) in first_run.PROVIDERS.items():
            self.provider.addItem(label + ("（已设置）" if status[pid] else ""), pid)
        self.key = QtWidgets.QLineEdit()
        self.key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key.setPlaceholderText("粘贴密钥；留空则不改")
        f1.addRow("AI 服务", self.provider)
        f1.addRow("密钥", self.key)
        lay.addWidget(ai)

        fac = QtWidgets.QGroupBox("2. 企业数字工厂（可选：发布方案到工厂、在工厂服务器上算流体）")
        f2 = QtWidgets.QFormLayout(fac)
        self.url = QtWidgets.QLineEdit(settings.get("factory_url", ""))
        self.url.setPlaceholderText("例如 https://factory.你的公司.com")
        self.cafile = QtWidgets.QLineEdit(settings.get("factory_cafile", ""))
        self.cafile.setPlaceholderText("内网自签证书时，工厂的根证书文件（可空）")
        pick = QtWidgets.QPushButton("选择…")
        pick.clicked.connect(self._pick_cafile)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.cafile)
        row.addWidget(pick)
        self.test = QtWidgets.QPushButton("测试连接")
        self.test.clicked.connect(self._test)
        self.test_result = QtWidgets.QLabel("")
        self.test_result.setWordWrap(True)
        f2.addRow("工厂地址", self.url)
        f2.addRow("根证书", row)
        f2.addRow(self.test, self.test_result)
        lay.addWidget(fac)

        buttons = QtWidgets.QDialogButtonBox()
        self.save_button = buttons.addButton("保存", QtWidgets.QDialogButtonBox.AcceptRole)
        later = buttons.addButton("以后再说", QtWidgets.QDialogButtonBox.RejectRole)
        self.save_button.clicked.connect(self._save)
        later.clicked.connect(self._later)
        lay.addWidget(buttons)
        self.saved: list[str] = []

    def _pick_cafile(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择工厂的根证书", "", "证书 (*.crt *.pem *.cer);;所有文件 (*)")
        if path:
            self.cafile.setText(path)

    def _test(self):
        ok, msg = first_run.check_factory(self.url.text(), self.cafile.text().strip() or None)
        self.test_result.setText(("✓ " if ok else "✗ ") + msg)

    def _save(self):
        self.saved = first_run.save(self.provider.currentData(), self.key.text(), self.url.text(), self.cafile.text())
        self.key.clear()
        self.accept()

    def _later(self):
        library_choice.write_setting("first_run_done", True)
        self.reject()


def show(parent=None) -> FirstRunDialog:
    dlg = FirstRunDialog(parent)
    dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
    return dlg


def show_if_needed(parent=None) -> None:
    """只在单机安装版（自包含包，ADR-0066）里自动弹出；从仓库开发运行时只在菜单里。"""
    if first_run.is_standalone() and first_run.needed(library_choice.read_settings()):
        show(parent)
