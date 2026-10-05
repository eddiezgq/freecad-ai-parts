"""接口标记（ADR-0048 第 4 条）：场景中每个机械端口在世界坐标中的标记。纯函数，不依赖 FreeCAD。

电源、编码器、总线等端口在数据中没有坐标系（不参与布局），不画 3D 标记，只在校验窗口中列出。
FreeCAD 对象名不能含“.”，标记对象名写成 <实例>__<端口>，标签为 <实例>.<端口>。
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.values import nominal
from freecad_addon.core.geometry import MECHANICAL
from freecad_addon.core.scene import Scene

# 按端口类型着色（未校验时）；校验后按结论着色（ADR-0048 第 5 条）
# 避开品类色（电机蓝、减速器橙、驱动器绿）与结论色（红、黄、绿）
TYPE_COLORS = {
    "mechanical.cyl_male": (0.55, 0.20, 0.90),  # 轴：紫
    "mechanical.cyl_female": (0.10, 0.80, 0.90),  # 孔：青
    "mechanical.flange": (0.95, 0.20, 0.70),  # 法兰：品红
    "mechanical.mount_face": (0.97, 0.97, 0.97),  # 安装面：白
}
PART_TRANSPARENCY = 45  # 零件半透明，接口标记透出来
MIN_MM, MAX_MM, DEFAULT_MM = 6.0, 60.0, 20.0


@dataclass(frozen=True)
class Marker:
    object_name: str  # <实例>__<端口>
    ref: str  # <实例>.<端口>
    instance: str
    port: str
    type: str
    dir: str
    origin: tuple[float, float, float]
    axis: tuple[float, float, float]
    diameter: float  # 标记圆盘直径 mm
    connected: bool


def object_name(ref: str) -> str:
    return ref.replace(".", "__", 1)


def ref_of(object_name: str) -> str | None:
    """由标记对象名还原端口引用；不是标记对象时返回 None。"""
    inst, sep, pid = object_name.partition("__")
    return f"{inst}.{pid}" if sep and inst and pid else None


def _size(spec: dict) -> float:
    for key in ("diameter_mm", "pcd_mm"):
        v = nominal(spec.get(key)) if spec.get(key) else None
        if isinstance(v, (int, float)) and v > 0:
            return max(MIN_MM, min(MAX_MM, float(v)))
    return DEFAULT_MM


def markers(scene: Scene) -> list[Marker]:
    connected = {r for c in scene.connections for r in (c.a, c.b)}
    out = []
    for inst in sorted(scene.instances):
        comp = scene.component(inst)
        for p in comp.get("ports", []):
            if p.get("type") not in MECHANICAL or "frame" not in p:
                continue
            ref = f"{inst}.{p['id']}"
            _, origin, axis = scene.port_world(ref)
            out.append(Marker(object_name(ref), ref, inst, p["id"], p["type"], p.get("dir", ""),
                              tuple(origin), tuple(axis), _size(p.get("spec", {})), ref in connected))
    return out
