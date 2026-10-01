"""进程内后端（ADR-0036）：面板中的 MCP 服务端直接在本 FreeCAD 中做几何查询，经主线程执行器调用 worker 的方法。"""

from __future__ import annotations

from freecad_addon.fc.client import WorkerError
from freecad_addon.fc.mainthread import MainThreadExecutor, MainThreadTimeout


class InProcessBackend:
    syncs_view = True  # 布局变化后在当前 FreeCAD 中同步显示

    def __init__(self, executor: MainThreadExecutor, timeout_s: float = 180.0):
        self.executor = executor
        self.timeout_s = timeout_s

    def call(self, method: str, params: dict | None = None) -> dict:
        from freecad_addon.fc.worker import handle

        try:
            resp = self.executor.run(handle, {"id": 0, "method": method, "params": params or {}},
                                     timeout_s=self.timeout_s)
        except MainThreadTimeout as exc:
            raise WorkerError("timeout", str(exc)) from exc
        if "error" in resp:
            raise WorkerError(resp["error"].get("kind", "internal"), resp["error"].get("message", "未知错误"))
        return resp["result"]

    def close(self) -> None:
        pass
