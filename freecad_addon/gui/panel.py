"""内置 AI 对话面板（ADR-0036）：FreeCAD 中的停靠窗口，作为 MCP 客户端调用本项目的工具。

- 工具：进程内创建 MCP 服务端，几何后端为本 FreeCAD（主线程执行器），布局实时显示在 FapLayout 文档中
- LLM：AnthropicChat（密钥只从环境变量读取）；对话循环在后台线程运行，不阻塞界面
- 组件库：FAP_LIBRARY / DATABASE_URL；都没设置时用虚构测试组件库（tests/golden/fixtures），并在面板中注明
"""

from __future__ import annotations

import html
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from PySide import QtCore, QtGui, QtWidgets

from freecad_addon.fc.inprocess import InProcessBackend
from freecad_addon.fc.mainthread import MainThreadExecutor
from freecad_addon.gui.chat import (
    LLM,
    AnthropicChat,
    ChatEngine,
    Event,
    mcp_tools_to_anthropic,
    summarize,
)
from freecad_addon.gui.tools_client import InProcessTools

GOLDEN_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "golden" / "fixtures"


def panel_library():
    from kb.library import JsonLibrary, default_library

    if os.environ.get("FAP_LIBRARY") or os.environ.get("DATABASE_URL"):
        return default_library()
    return JsonLibrary(GOLDEN_FIXTURES)


def library_note() -> str:
    if os.environ.get("FAP_LIBRARY") or os.environ.get("DATABASE_URL"):
        return "组件库：按 FAP_LIBRARY / DATABASE_URL 配置"
    return "组件库：虚构测试组件（未设置 FAP_LIBRARY / DATABASE_URL）"


def _short(data, limit: int = 160) -> str:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ChatPanel(QtWidgets.QDockWidget):
    event_posted = QtCore.Signal(object)
    turn_done = QtCore.Signal()

    def __init__(self, llm_factory: Callable[[], LLM] = AnthropicChat, library_factory=panel_library,
                 parent: QtWidgets.QWidget | None = None):
        super().__init__("AI Parts 对话", parent)
        self.setObjectName("FapChatPanel")
        self._llm_factory = llm_factory
        self._engine: ChatEngine | None = None
        self._images = 0
        self._busy = False

        from mcp_server.server import create_server

        self.executor = MainThreadExecutor()
        self.tools = InProcessTools(create_server(library_factory, lambda: InProcessBackend(self.executor)))

        body = QtWidgets.QWidget()
        lay = QtWidgets.QVBoxLayout(body)
        self.header = QtWidgets.QLabel(library_note())
        self.header.setWordWrap(True)
        self.transcript = QtWidgets.QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.input = QtWidgets.QPlainTextEdit()
        self.input.setPlaceholderText("例如：给六轴机械臂第 2 关节选一套驱动，输出连续扭矩 25 N·m、输出转速 30 rpm，"
                                      "并在 FreeCAD 里布局")
        self.input.setMaximumHeight(90)
        self.send_button = QtWidgets.QPushButton("发送")
        self.status = QtWidgets.QLabel("")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.send_button)
        for w in (self.header, self.transcript, self.input):
            lay.addWidget(w)
        lay.addLayout(row)
        self.setWidget(body)

        self.send_button.clicked.connect(self.send)
        self.event_posted.connect(self._show_event, QtCore.Qt.QueuedConnection)
        self.turn_done.connect(self._finish_turn, QtCore.Qt.QueuedConnection)

    # ------------------------------------------------------------ 对话

    def _ensure_engine(self) -> ChatEngine:
        if self._engine is None:
            tools = mcp_tools_to_anthropic(self.tools.list_tools())
            self._engine = ChatEngine(self._llm_factory(), tools, self.tools.call)
        return self._engine

    def send(self, text: str | None = None) -> bool:
        """发送一条消息；对话在后台线程进行。正在进行时返回 False。"""
        if self._busy:
            return False
        text = (text if text is not None else self.input.toPlainText()).strip()
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

        def work() -> None:
            try:
                engine.send(text, on_event=self.event_posted.emit)
            finally:
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
        else:
            self._append(f'<p style="color:#b00"><b>出错：</b>{esc(e.text)}</p>')

    def closeEvent(self, event) -> None:
        self.tools.close()
        super().closeEvent(event)
