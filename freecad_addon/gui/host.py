"""共用工具宿主（ADR-0048 第 1 条）：对话面板、库浏览器、接口命令共用一个 MCP 服务端与布局场景。

人在 FreeCAD 中的“放入布局”“连接接口”与 AI 一样调用这里的工具，所以看到、改动的是同一个场景。
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from freecad_addon.core import library_choice
from freecad_addon.gui.tools_client import InProcessTools


class ToolsHost:
    def __init__(self, library_factory: Callable | None = None, note: str | None = None):
        from freecad_addon.fc.inprocess import InProcessBackend
        from freecad_addon.fc.mainthread import MainThreadExecutor
        from mcp_server.server import create_server

        if library_factory is None:
            choice = library_choice.choose(os.environ)
            library_factory, note = (lambda: library_choice.load(choice)), choice.note
        self.note = note or "组件库：由调用方指定（未按 FAP_LIBRARY 查找）"
        self._lib = None
        self._factory = library_factory
        self.executor = MainThreadExecutor()
        self.tools = InProcessTools(create_server(self.library, lambda: InProcessBackend(self.executor)))
        self.listeners: list[Callable[[str, dict], None]] = []  # 场景改动后通知（浏览器、校验窗口）

    def library(self):
        if self._lib is None:
            self._lib = self._factory()
        return self._lib

    def call(self, name: str, args: dict, source: str = "user"):
        """调用工具；改动场景的工具调用后通知监听者。source 标明来自用户还是 AI（ADR-0042）。"""
        out = self.tools.call(name, args)
        if not out.is_error and name in SCENE_TOOLS:
            for fn in list(self.listeners):
                fn(name, {"args": args, "source": source})
        return out


SCENE_TOOLS = {"place_component", "connect_ports"}

_lock = threading.Lock()
_host: ToolsHost | None = None


def get_host() -> ToolsHost:
    global _host
    with _lock:
        if _host is None:
            _host = ToolsHost()
        return _host
