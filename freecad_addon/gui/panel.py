"""内置 AI 对话面板（ADR-0036）：FreeCAD 中的停靠窗口，作为 MCP 客户端调用本项目的工具。

- 工具：进程内创建 MCP 服务端，几何后端为本 FreeCAD（主线程执行器），布局实时显示在 FapLayout 文档中
- LLM：经 AI 模型网关（Claude / DeepSeek，ADR-0063；密钥只从环境变量读取）；对话循环在后台线程运行，不阻塞界面
- 组件库与工具：共用工具宿主（gui/host.py，ADR-0048）；组件库按 FAP_LIBRARY、DATABASE_URL、仓库 data/library、
  虚构测试组件的顺序选择，并在面板中注明
"""

from __future__ import annotations

import html
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from PySide import QtCore, QtGui, QtWidgets

from freecad_addon.core import library_choice
from freecad_addon.core.retrieval import default_hints
from freecad_addon.gui.chat import (
    LLM,
    ChatEngine,
    Event,
    default_chat,
    mcp_tools_to_anthropic,
    summarize,
)
from freecad_addon.gui.host import ToolsHost, get_host

GOLDEN_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "golden" / "fixtures"


def panel_library():
    return library_choice.load(library_choice.choose(os.environ))


def library_note() -> str:
    return library_choice.choose(os.environ).note


def key_note() -> str:
    """没有密钥时面板顶部的提示；有密钥时为空。选型、BOM、校验不需要密钥。"""
    from freecad_addon.gui.chat import _load_dotenv

    _load_dotenv()
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY"):
        return ""
    return ("未设置 AI 密钥（ANTHROPIC_API_KEY 或 DEEPSEEK_API_KEY），AI 对话不能用：在 AI Parts 菜单的“首次设置”里填写。"
            "不用对话也可以用“选型”“零件库”“校验”“BOM”。")


def _short(data, limit: int = 160) -> str:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ChatPanel(QtWidgets.QDockWidget):
    event_posted = QtCore.Signal(object)
    turn_done = QtCore.Signal()

    def __init__(self, llm_factory: Callable[[], LLM] = default_chat, library_factory=None,
                 parent: QtWidgets.QWidget | None = None, host: ToolsHost | None = None):
        super().__init__("AI Parts 对话", parent)
        self.setObjectName("FapChatPanel")
        self._llm_factory = llm_factory
        self._engine: ChatEngine | None = None
        self._images = 0
        self._busy = False

        # 指定组件库时（测试）自建宿主；否则与库浏览器、接口命令共用一个（ADR-0048 第 1 条）
        self._own_host = host is None and library_factory is not None  # 只关闭自己建的宿主
        self.host = host or (ToolsHost(library_factory) if library_factory else get_host())
        self.executor = self.host.executor
        self.tools = self.host.tools

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        self.header = QtWidgets.QLabel(self.host.note)
        self.header.setWordWrap(True)
        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.input = QtWidgets.QPlainTextEdit()
        self.input.setPlaceholderText("例如：给六轴机械臂第 2 关节选一套驱动，输出连续扭矩 25 N·m、输出转速 30 rpm，"
                                      "并在 FreeCAD 里布局")
        self.input.setMaximumHeight(90)
        self.input.setToolTip("回车发送，Shift+回车换行")
        self.input.installEventFilter(self)
        self.review = QtWidgets.QCheckBox("AI 改动先审阅")
        self.review.setChecked(True)
        self.review.setToolTip("AI 每轮改动布局后，在校验窗口中列为提案，接受才保留，拒绝就恢复原状（ADR-0049）")
        self.send_button = QtWidgets.QPushButton("发送")
        self.status = QtWidgets.QLabel("")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.review)
        row.addWidget(self.send_button)
        self.key_note = QtWidgets.QLabel(key_note())
        self.key_note.setWordWrap(True)
        self.key_note.setStyleSheet("color:#b00")
        self.key_note.setVisible(bool(self.key_note.text()))
        for w in (self.header, self.key_note, self.transcript, self.input):
            lay.addWidget(w)
        lay.addLayout(row)
        self.setWidget(body)

        self.send_button.clicked.connect(lambda *_: self.send())  # clicked 会带上 checked（PySide6 / FreeCAD 1.1）
        self.event_posted.connect(self._show_event, QtCore.Qt.QueuedConnection)
        self.turn_done.connect(self._finish_turn, QtCore.Qt.QueuedConnection)

    def eventFilter(self, obj, event) -> bool:
        """输入框中回车发送，Shift+回车换行；输入法组字时的回车交给输入法。"""
        if obj is self.input and event.type() == QtCore.QEvent.KeyPress \
                and event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) \
                and not event.modifiers() & QtCore.Qt.ShiftModifier:
            self.send()
            return True
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.input.setFocus()

    # ------------------------------------------------------------ 对话

    def _ensure_engine(self) -> ChatEngine:
        if self._engine is None:
            tools = mcp_tools_to_anthropic(self.tools.list_tools())
            call = lambda name, args: self.host.call(name, args, source="ai")  # AI 的改动同样通知监听者
            self._engine = ChatEngine(self._llm_factory(), tools, call, context=default_hints())
        return self._engine

    def send(self, text: str | None = None) -> bool:
        """发送一条消息；对话在后台线程进行。正在进行时返回 False。"""
        if self._busy:
            return False
        text = (text if isinstance(text, str) else self.input.toPlainText()).strip()
        if not text:
            return False
        try:
            engine = self._ensure_engine()
        except Exception as exc:  # noqa: BLE001 — 密钥缺失等，显示给用户
            self._show_event(Event("error", str(exc)))
            return False
        self.input.clear()
        self._busy = True
        self.send_button.setEnabled(False)
        self.status.setText("思考中…")

        before = json.loads(json.dumps(self.host.layout))  # 本轮开始前的场景快照（ADR-0049 第 4 条）
        review = self.review.isChecked()
        said: list[str] = []
        self.host.settle("accepted")  # 新的对话视为接受尚未处理的提案

        def on_event(e: Event) -> None:
            from freecad_addon.gui import recording

            recording.chat_event(e)  # 录制中时写入会话包（ADR-0042），并标出 AI 工具调用的时间段
            if e.kind == "assistant" and e.text:
                said.append(e.text)
            self.event_posted.emit(e)

        def work() -> None:
            try:
                engine.send(text, on_event=on_event)
            finally:
                if review:
                    from freecad_addon.core import project

                    d = project.diff(before, self.host.layout)
                    if d["changed"]:
                        self.host.propose({"before": before, "diff": d, "request": text,
                                           "explanation": said[-1] if said else ""})
                self.turn_done.emit()

        threading.Thread(target=work, name="fap-chat", daemon=True).start()
        return True

    @property
    def busy(self) -> bool:
        return self._busy

    def _finish_turn(self) -> None:
        self._busy = False
        self.send_button.setEnabled(True)
        self.status.setText("")

    # ------------------------------------------------------------ 显示

    def _append(self, fragment: str) -> None:
        self.transcript.append(fragment)
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _add_image(self, png: bytes) -> str:
        self._images += 1
        url = QtCore.QUrl(f"fap-image:snapshot-{self._images}")
        self.transcript.document().addResource(QtGui.QTextDocument.ImageResource, url, QtGui.QImage.fromData(png))
        return f'<img src="{url.toString()}" width="360">'

    def _show_event(self, e: Event) -> None:
        esc = html.escape
        if e.kind == "user":
            self._append(f"<p><b>你：</b>{esc(e.text)}</p>")
        elif e.kind == "assistant":
            self._append(f"<p><b>助手：</b>{esc(e.text).replace(chr(10), '<br>')}</p>")
        elif e.kind == "tool_call":
            self._append(f'<p style="color:#666">调用 {esc(e.name or "")} {esc(_short(e.data))}</p>')
        elif e.kind == "tool_result":
            color = "#b00" if e.data else "#666"
            self._append(f'<p style="color:{color}">→ {esc(summarize(e.name or "", e.text, bool(e.data)))}</p>')
            for png in e.images:
                self._append(f"<p>{self._add_image(png)}</p>")
        elif e.kind == "info":
            self._append(f'<p style="color:#666"><i>{esc(e.text)}</i></p>')
        else:
            self._append(f'<p style="color:#b00"><b>出错：</b>{esc(e.text)}</p>')

    def closeEvent(self, event) -> None:
        if self._own_host:  # 共用宿主与调用方传入的宿主由别处关闭
            self.tools.close()
        super().closeEvent(event)
