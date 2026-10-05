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
        self.listeners: list[Callable[[str, dict], None]] = []  # 工具调用成功后通知（浏览器、校验窗口），在调用线程中

    def library(self):
        if self._lib is None:
            self._lib = self._factory()
        return self._lib

    def call(self, name: str, args: dict, source: str = "user"):
        """调用工具；成功后通知监听者 fn(工具名, {args, source, result})。source 标明来自用户还是 AI（ADR-0042）。
        不能在界面（主）线程调用，否则与主线程执行器互等；界面上请用 call_in_background。"""
        if threading.current_thread() is self.executor._thread:
            raise RuntimeError("不能在界面线程直接调用工具，请用 call_in_background")
        out = self.tools.call(name, args)
        if not out.is_error:
            info = {"args": args, "source": source, "result": _parse(out)}
            for fn in list(self.listeners):
                fn(name, info)
        return out

    def call_in_background(self, name: str, args: dict, done: Callable, source: str = "user") -> None:
        """在后台线程调用工具，完成后调用 done(结果或异常)。界面线程不能直接调 call：工具要回到主线程更新
        FreeCAD 文档，主线程若在等待就会互相等死（ADR-0036 的主线程执行器）。done 在后台线程中调用，
        界面应通过 Qt 排队信号处理它。"""
        def work() -> None:
            try:
                done(self.call(name, args, source))
            except Exception as exc:  # noqa: BLE001 — 交给界面显示
                done(exc)

        threading.Thread(target=work, name=f"fap-{name}", daemon=True).start()


SCENE_TOOLS = {"place_component", "connect_ports"}  # 返回结果中带当前布局（layout）的工具


def _parse(out) -> dict | None:
    """工具结果的 JSON 文本解析为字典；不是 JSON 时返回 None。"""
    import json

    for text in getattr(out, "texts", []):
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            return data
    return None

_lock = threading.Lock()
_host: ToolsHost | None = None


def get_host() -> ToolsHost:
    global _host
    with _lock:
        if _host is None:
            _host = ToolsHost()
        return _host
