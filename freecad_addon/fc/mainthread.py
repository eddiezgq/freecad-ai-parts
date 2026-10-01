"""主线程执行器（ADR-0036）：FreeCAD 的文档与界面只能在主线程操作；其他线程提交的任务经 Qt 排队信号
交给主线程执行，提交方阻塞等待结果。须在主线程中创建，且主线程须运行 Qt 事件循环（FreeCAD 界面即是）。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide import QtCore


class MainThreadTimeout(TimeoutError):
    pass


class _Invoker(QtCore.QObject):
    submit = QtCore.Signal(object)

    def __init__(self):
        super().__init__()
        self.submit.connect(self._run, QtCore.Qt.QueuedConnection)

    def _run(self, job: Callable[[], None]) -> None:
        job()


class MainThreadExecutor:
    def __init__(self):
        self._thread = threading.current_thread()
        self._invoker = _Invoker()

    def run(self, fn: Callable[..., Any], *args: Any, timeout_s: float = 180.0) -> Any:
        if threading.current_thread() is self._thread:
            return fn(*args)
        box: dict = {}
        done = threading.Event()

        def job() -> None:
            try:
                box["result"] = fn(*args)
            except BaseException as exc:  # noqa: BLE001 — 原样交回提交方
                box["error"] = exc
            finally:
                done.set()

        self._invoker.submit.emit(job)
        if not done.wait(timeout_s):
            raise MainThreadTimeout(f"FreeCAD 主线程 {timeout_s:.0f} 秒内未执行完请求")
        if "error" in box:
            raise box["error"]
        return box["result"]
