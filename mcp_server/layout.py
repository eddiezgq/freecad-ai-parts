"""FreeCAD 组工具的会话（M4b #85，ADR-0032）：场景由服务端持有，FreeCAD worker 只做干涉检查与截图。

后端由环境变量 FAP_FREECAD 选择：
- headless：按需启动 FreeCAD 子进程（freecad_addon.fc.client.HeadlessWorker）
- 未设置或 none：位姿类工具（place_component、connect_ports）照常可用，干涉检查与截图报“未连接 FreeCAD”
一个服务端进程一个场景（stdio 下即一个客户端）；HTTP 下多个客户端共用同一场景。
"""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Callable
from typing import Any, Protocol

from freecad_addon.core.geometry import LayoutError
from freecad_addon.core.pose import Pose, quat_axis_angle
from freecad_addon.core.scene import Scene
from freecad_addon.fc.client import VIEW_NAMES, HeadlessWorker, WorkerError
from mcp_server.tools import ToolInputError

DEFAULT_THRESHOLD_MM3 = 1.0


class Backend(Protocol):
    def call(self, method: str, params: dict | None = None) -> dict: ...

    def close(self) -> None: ...


class ToolBackendError(ToolInputError):
    """FreeCAD 后端不可用或执行失败（REST 返回 503）。"""


def default_backend() -> Backend | None:
    mode = (os.environ.get("FAP_FREECAD") or "none").lower()
    if mode == "headless":
        return HeadlessWorker()
    if mode == "none":
        return None
    raise ToolBackendError(f"FAP_FREECAD={mode!r} 无效，可选 headless、none（gui 后端随 FreeCAD 面板提供）")


def _vec3(v: Any, what: str) -> tuple[float, float, float]:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise ToolInputError(f"{what} 须为 3 个数 [x, y, z]")
    out = []
    for c in v:
        if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c):
            raise ToolInputError(f"{what} 须为 3 个有限的数")
        out.append(float(c))
    return out[0], out[1], out[2]


def _num(v: Any, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ToolInputError(f"{what} 须为有限的数")
    return float(v)


class LayoutSession:
    def __init__(self, library: Callable[[], Any], backend_factory: Callable[[], Backend | None] = default_backend):
        self._library = library
        self._backend_factory = backend_factory
        self._backend: Backend | None = None
        self._backend_ready = False
        self._lock = threading.RLock()
        self.scene = Scene()

    # ------------------------------------------------------------ 状态

    def state(self) -> dict:
        return {
            "instances": [{"instance": n, "component": v["component"]["id"], **v["pose"].to_dict()}
                          for n, v in sorted(self.scene.instances.items())],
            "connections": [c.to_dict() for c in self.scene.connections],
        }

    def _backend_or_error(self) -> Backend:
        if not self._backend_ready:
            self._backend = self._backend_factory()
            self._backend_ready = True
        if self._backend is None:
            raise ToolBackendError("未连接 FreeCAD：干涉检查与截图需要 FreeCAD。设置环境变量 FAP_FREECAD=headless"
                                   "（并用 scripts/fetch_freecad.sh 准备 FreeCAD，或设置 FAP_FREECAD_PYTHON）后重启服务端")
        return self._backend

    def _call(self, method: str, params: dict) -> dict:
        backend = self._backend_or_error()
        try:
            return backend.call(method, params)
        except WorkerError as exc:
            if exc.kind in ("input", "snapshot"):
                raise ToolInputError(str(exc)) from exc
            raise ToolBackendError(f"FreeCAD 后端出错（{exc.kind}）：{exc}") from exc

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()

    # ------------------------------------------------------------ 工具

    def place(self, instance: str, component_id: str | None = None, position_mm: Any = None,
              rotation_axis: Any = None, rotation_deg: Any = 0.0, remove: bool = False) -> dict:
        with self._lock:
            try:
                if remove:
                    if component_id is not None or position_mm is not None or rotation_axis is not None or rotation_deg:
                        raise ToolInputError("remove 时不能同时给出组件或位姿")
                    out = self.scene.remove(instance)
                    return {**out, "layout": self.state()}
                comp = None
                if component_id is not None:
                    comp = self._library().get(component_id)
                    if comp is None:
                        raise ToolInputError(f"组件不存在：{component_id}")
                pos = _vec3(position_mm if position_mm is not None else [0, 0, 0], "position_mm")
                axis = _vec3(rotation_axis if rotation_axis is not None else [0, 0, 1], "rotation_axis")
                deg = _num(rotation_deg, "rotation_deg")
                if deg and math.sqrt(sum(c * c for c in axis)) < 1e-12:
                    raise ToolInputError("rotation_axis 不能是零向量")
                rot = quat_axis_angle(axis, deg) if deg else (1.0, 0.0, 0.0, 0.0)
                out = self.scene.place(instance, comp, Pose(rot, pos))
            except LayoutError as exc:
                raise ToolInputError(str(exc)) from exc
            return {**out, "layout": self.state()}

    def connect(self, a: str, b: str, roll_deg: Any = 0.0, offset_mm: Any = 0.0) -> dict:
        with self._lock:
            try:
                out = self.scene.connect(a, b, _num(roll_deg, "roll_deg"), _num(offset_mm, "offset_mm"))
            except LayoutError as exc:
                raise ToolInputError(str(exc)) from exc
            return {**out, "layout": self.state()}

    def interference(self, threshold_mm3: Any = DEFAULT_THRESHOLD_MM3) -> dict:
        thr = _num(threshold_mm3, "threshold_mm3")
        if thr < 0:
            raise ToolInputError("threshold_mm3 不能为负")
        with self._lock:
            if not self.scene.instances:
                raise ToolInputError("场景为空：先用 place_component 放置组件")
            return self._call("interference", {"scene": self.scene.to_dict(), "threshold_mm3": thr})

    def snapshot(self, view: str = "iso", width: Any = 800, height: Any = 600) -> dict:
        if view not in VIEW_NAMES:
            raise ToolInputError(f"未知视角 {view}，可选：{'、'.join(VIEW_NAMES)}")
        for v, what in ((width, "width"), (height, "height")):
            if isinstance(v, bool) or not isinstance(v, int) or not 64 <= v <= 4096:
                raise ToolInputError(f"{what} 须为 64–4096 的整数像素")
        with self._lock:
            if not self.scene.instances:
                raise ToolInputError("场景为空：先用 place_component 放置组件")
            return self._call("snapshot", {"scene": self.scene.to_dict(), "view": view, "width": width,
                                           "height": height})
