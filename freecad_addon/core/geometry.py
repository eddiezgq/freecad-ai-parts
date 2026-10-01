"""组件的布局几何（ADR-0032）：端口坐标系、包络各段、要从包络中减去的孔，以及包络在某方向上的投影范围。

尺寸按名义值取（engine.values.nominal）：单值或名义值；只有范围的尺寸视为缺失，报错而不猜测。
包络坐标约定见 schema/component.schema.json：原点在安装法兰面中心，各段沿 z 从 z_start_mm 起延伸；
长方体的 width_mm 沿 x、height_mm 沿 y，以 z 轴为中心。
"""

from __future__ import annotations

from dataclasses import dataclass

from engine.geometry import envelope_extent
from engine.values import nominal
from freecad_addon.core.pose import Pose, Vec, dot, norm, unit

MECHANICAL = ("mechanical.cyl_male", "mechanical.cyl_female", "mechanical.flange", "mechanical.mount_face")


class LayoutError(ValueError):
    """布局请求无法执行：给出原因，由调用方（agent）改正后重试。"""


@dataclass(frozen=True)
class Port:
    id: str
    type: str
    origin: Vec
    axis: Vec
    spec: dict


@dataclass(frozen=True)
class Part:
    """包络的一段，坐标在组件坐标系中。"""

    shape: str  # cylinder / box
    z_start: float
    length: float
    diameter: float | None = None
    width: float | None = None
    height: float | None = None
    label: str | None = None

    def to_dict(self) -> dict:
        d = {"shape": self.shape, "z_start_mm": self.z_start, "length_mm": self.length}
        if self.shape == "cylinder":
            d["diameter_mm"] = self.diameter
        else:
            d["width_mm"], d["height_mm"] = self.width, self.height
        if self.label:
            d["label"] = self.label
        return d


@dataclass(frozen=True)
class Bore:
    """要从包络中减去的孔（cyl_female 端口）：孔口在 origin，沿 axis 延伸 depth；depth 为 None 表示贯穿。"""

    port: str
    origin: Vec
    axis: Vec
    diameter: float
    depth: float | None

    def to_dict(self) -> dict:
        return {"port": self.port, "origin_mm": list(self.origin), "axis": list(self.axis),
                "diameter_mm": self.diameter, "depth_mm": self.depth}


def port(comp: dict, port_id: str) -> Port:
    p = next((p for p in comp.get("ports", []) if p.get("id") == port_id), None)
    if p is None:
        raise LayoutError(f"组件 {comp.get('id')} 没有端口 {port_id}")
    if p.get("type") not in MECHANICAL or "frame" not in p:
        raise LayoutError(f"端口 {comp.get('id')}.{port_id}（{p.get('type')}）不是机械端口，不参与布局")
    f = p["frame"]
    try:
        axis = unit(tuple(float(c) for c in f["axis"]))  # type: ignore[arg-type]
    except ValueError as exc:
        raise LayoutError(f"端口 {comp.get('id')}.{port_id} 的轴向为零向量") from exc
    return Port(port_id, p["type"], tuple(float(c) for c in f["origin_mm"]), axis,  # type: ignore[arg-type]
                p.get("spec", {}))


def spec_nominal(p: Port, field: str) -> float | None:
    return nominal(p.spec.get(field))


def parts(comp: dict) -> list[Part]:
    out = []
    for i, raw in enumerate(comp.get("envelope", {}).get("parts", [])):
        shape = raw.get("shape")
        fields = ["length_mm"] + (["diameter_mm"] if shape == "cylinder" else ["width_mm", "height_mm"])
        vals = {f: nominal(raw.get(f)) for f in fields}
        missing = [f for f, v in vals.items() if v is None or v <= 0]
        if missing:
            raise LayoutError(f"组件 {comp.get('id')} 包络第 {i} 段缺少可用的 {'、'.join(missing)}（只有范围或非正数时视为缺失）")
        z0 = raw.get("z_start_mm")
        if isinstance(z0, bool) or not isinstance(z0, (int, float)):
            raise LayoutError(f"组件 {comp.get('id')} 包络第 {i} 段缺少 z_start_mm")
        out.append(Part(shape, float(z0), vals["length_mm"], vals.get("diameter_mm"), vals.get("width_mm"),
                        vals.get("height_mm"), raw.get("label")))
    if not out:
        raise LayoutError(f"组件 {comp.get('id')} 没有包络")
    return out


def bores(comp: dict) -> list[Bore]:
    out = []
    for raw in comp.get("ports", []):
        if raw.get("type") != "mechanical.cyl_female":
            continue
        p = port(comp, raw["id"])
        d = spec_nominal(p, "diameter_mm")
        if d is None or d <= 0:
            raise LayoutError(f"组件 {comp.get('id')} 的孔 {p.id} 缺少名义直径，无法生成包络")
        depth = spec_nominal(p, "depth_mm")
        out.append(Bore(p.id, p.origin, p.axis, d, depth if depth and depth > 0 else None))
    return out


def part_extent(part: Part, pose: Pose, direction: Vec) -> tuple[float, float]:
    """一段包络（经位姿变换后）在方向 direction 上的投影范围（engine.geometry.envelope_extent）。"""
    return envelope_extent(part.shape, part.z_start, part.length, pose, direction, diameter=part.diameter,
                           width=part.width, height=part.height)


def distance_to_line(p: Vec, origin: Vec, axis: Vec) -> float:
    v = (p[0] - origin[0], p[1] - origin[1], p[2] - origin[2])
    t = dot(v, axis)
    return norm((v[0] - t * axis[0], v[1] - t * axis[1], v[2] - t * axis[2]))
