"""导入规格书对话框（M9 第三步）：为场景中的一个零件选 PDF / Excel，AI 抽取、代码核对，逐项勾选后写入企业库。

抽取在后台线程中进行（不卡界面）；确认表与写入在 core/spec_import.py（纯函数 + 企业库规则）。
"""

from __future__ import annotations

import html
import threading
from pathlib import Path

from PySide import QtCore, QtWidgets

from freecad_addon.core import library_choice, spec_import


def default_client():
    """真实 LLM 客户端；密钥只从环境变量或本地 .env 读取。"""
    from ingest.llm_extract import AnthropicClient

    return AnthropicClient()


class ImportDialog(QtWidgets.QDialog):
    extracted = QtCore.Signal(object)  # 后台抽取完成：抽取结果或错误文字

    def __init__(self, library, component_id: str, client_factory=default_client, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入规格书（写入企业库）")
        self.resize(980, 640)
        self.library, self.component_id, self.client_factory = library, component_id, client_factory
        self.enterprise = getattr(library, "top", None)
        self.comp = library.get(component_id)
        self.extraction: dict | None = None
        self.rows: list[spec_import.Row] = []
        self.written: list[str] = []
        self.busy = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.addWidget(QtWidgets.QLabel(f"<b>{html.escape(self.comp.get('vendor', ''))} "
                                       f"{html.escape(self.comp.get('model', ''))}</b>"
                                       f"<br><span style='color:#666'>{component_id}</span>"))
        form = QtWidgets.QFormLayout()
        pick = QtWidgets.QHBoxLayout()
        self.file = QtWidgets.QLineEdit()
        self.file.setPlaceholderText("厂商规格书 PDF，或选型表 Excel（.xlsx）")
        browse = QtWidgets.QPushButton("选择文件…")
        pick.addWidget(self.file, 1)
        pick.addWidget(browse)
        self.target_model = QtWidgets.QLineEdit()
        self.target_model.setPlaceholderText("一份样本列了多个型号时填要导入的型号，否则留空")
        self.pages = QtWidgets.QLineEdit()
        self.pages.setPlaceholderText("只看这些页，如 3,4（留空为全部）")
        self.actor = QtWidgets.QLineEdit(library_choice.read_settings().get("actor", ""))
        self.actor.setPlaceholderText("确认人姓名")
        form.addRow("规格书", pick)
        form.addRow("目标型号", self.target_model)
        form.addRow("页码", self.pages)
        form.addRow("确认人", self.actor)
        lay.addLayout(form)
        self.extract_button = QtWidgets.QPushButton("AI 抽取并核对")
        lay.addWidget(self.extract_button)
        self.note = QtWidgets.QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["写入", "字段", "抽取值（标准单位）", "现有值", "规格书原文", "页"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QtWidgets.QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        self.save_button = buttons.addButton("写入企业库", QtWidgets.QDialogButtonBox.AcceptRole)
        self.save_button.setEnabled(False)
        buttons.accepted.connect(lambda *_: self.save())
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        browse.clicked.connect(lambda *_: self._browse())
        self.extract_button.clicked.connect(lambda *_: self.extract())
        self.extracted.connect(self._extracted, QtCore.Qt.QueuedConnection)
        if self.enterprise is None:
            self.status.setText("还没有企业库：请先在菜单“AI Parts → 企业库”中选择企业库文件夹，重启 FreeCAD 后再导入。")
            self.extract_button.setEnabled(False)

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择规格书", "", "规格书 (*.pdf *.xlsx *.xlsm)")
        if path:
            self.file.setText(path)

    def _pages(self) -> list[int] | None:
        text = self.pages.text().replace("，", ",").strip()
        if not text:
            return None
        return [int(x) for x in text.split(",") if x.strip()]

    # ------------------------------------------------------------ 抽取（后台）

    def extract(self) -> bool:
        if self.busy or self.enterprise is None:
            return False
        path, actor = self.file.text().strip(), self.actor.text().strip()
        if not path or not Path(path).is_file():
            self.status.setText("请先选择规格书文件")
            return False
        if not actor:
            self.status.setText("请先填确认人")
            return False
        try:
            pages = self._pages()
            client = self.client_factory()
        except ValueError:
            self.status.setText("页码写成 3,4 这样的数字")
            return False
        except Exception as exc:  # noqa: BLE001 — 没有密钥等，显示给用户
            self.status.setText(f"AI 不可用：{exc}")
            return False
        self.busy = True
        self.extract_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.status.setText("AI 正在读规格书，代码逐项核对原文……")
        target = self.target_model.text()

        def work() -> None:
            try:
                out = spec_import.run(self.enterprise, self.comp, path, actor, client, target_model=target, pages=pages)
            except Exception as exc:  # noqa: BLE001 — 传回界面线程显示
                out = f"没有抽取：{exc}"
            self.extracted.emit(out)

        threading.Thread(target=work, daemon=True).start()
        return True

    def _extracted(self, out) -> None:
        self.busy = False
        self.extract_button.setEnabled(True)
        if isinstance(out, str):
            self.status.setText(out)
            return
        self.extraction = out
        self.rows = spec_import.rows(out, self.comp)
        self._fill_table()
        notes = [spec_import.identity_note(out, self.comp)]
        if out.get("rejected"):
            notes.append(f"另有 {len(out['rejected'])} 项与原文对不上，已由代码拒绝，不会写入")
        if out.get("extractor", {}).get("simulated"):
            notes.append("（模拟响应，仅供测试）")
        self.note.setText("；".join(n for n in notes if n))
        n = sum(r.default_checked for r in self.rows)
        self.status.setText(f"核对通过 {len(self.rows)} 项，默认勾选 {n} 项（与现有值不同、无须特别核对）。"
                            "请逐项对照原文，确认后写入企业库。")
        self.save_button.setEnabled(any(r.writable for r in self.rows))

    def _fill_table(self) -> None:
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            box = QtWidgets.QTableWidgetItem("")
            flags = QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled if r.writable else QtCore.Qt.NoItemFlags
            box.setFlags(flags)
            box.setCheckState(QtCore.Qt.Checked if r.default_checked else QtCore.Qt.Unchecked)
            self.table.setItem(i, 0, box)
            label = r.label + (f"（{r.unit}）" if r.unit else "")
            cells = [label, r.value, r.current or "（缺）", r.printed, str(r.page)]
            tips = list(r.attention) + ([r.why_not] if r.why_not else [])
            for j, text in enumerate(cells, start=1):
                item = QtWidgets.QTableWidgetItem(text)
                item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
                item.setToolTip("\n".join([f"原文：{r.quote}"] + list(r.issues) + ([r.why_not] if r.why_not else [])))
                if tips and j == 1:
                    item.setText("⚠ " + text)
                self.table.setItem(i, j, item)
        self.table.resizeColumnsToContents()

    def chosen(self) -> list[str]:
        return [r.target for i, r in enumerate(self.rows)
                if r.writable and self.table.item(i, 0).checkState() == QtCore.Qt.Checked]

    def set_checked(self, target: str, on: bool) -> None:
        i = next(i for i, r in enumerate(self.rows) if r.target == target)
        self.table.item(i, 0).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)

    # ------------------------------------------------------------ 写入

    def save(self) -> bool:
        if self.extraction is None or self.enterprise is None:
            return False
        chosen = self.chosen()
        if not chosen:
            self.status.setText("没有勾选任何一项")
            return False
        actor = self.actor.text().strip()
        try:
            base = getattr(self.library, "base", self.library)
            self.written = spec_import.apply(self.enterprise, self.component_id, self.extraction, chosen, actor,
                                             base.get)
        except Exception as exc:  # noqa: BLE001 — 显示给用户
            self.status.setText(f"没有写入：{exc}")
            return False
        library_choice.write_setting("actor", actor)
        self.accept()
        return True
