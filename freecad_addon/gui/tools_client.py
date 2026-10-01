"""面板的工具调用（ADR-0036）：在后台事件循环中持有 FastMCP 内存客户端，同步地列出与调用工具。

不依赖 FreeCAD 与 Qt；面板中传入进程内创建的 MCP 服务端（mcp_server.server.create_server）。
"""

from __future__ import annotations

import asyncio
import base64
import threading
from typing import Any

from fastmcp import Client

from freecad_addon.gui.chat import ToolOutcome


class InProcessTools:
    def __init__(self, server: Any, timeout_s: float = 600.0):
        self.timeout_s = timeout_s
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="fap-mcp", daemon=True)
        self._thread.start()
        self._client = Client(server)
        self._run(self._client.__aenter__())

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(self.timeout_s)

    def list_tools(self) -> list:
        return self._run(self._client.list_tools())

    def call(self, name: str, args: dict) -> ToolOutcome:
        res = self._run(self._client.call_tool(name, args, raise_on_error=False))
        texts, images = [], []
        for block in res.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "image":
                images.append(base64.b64decode(block.data))
        return ToolOutcome(texts, images, bool(res.is_error))

    def close(self) -> None:
        try:
            self._run(self._client.__aexit__(None, None, None))
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5)
