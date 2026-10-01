"""轴的穿过通道（ADR-0033）：圆柱配合中，轴从根部到孔口之间穿过的同组实例（如转接板）须有供轴穿过的孔；
V1 包络不建模这些孔，因此这一段的重叠不算干涉，而是列为“需有通孔”，供人核对。
"""

from __future__ import annotations

from dataclasses import dataclass

from freecad_addon.core.geometry import parts, port
from freecad_addon.core.pose import Vec, add, dot, scale, sub
from freecad_addon.core.scene import Scene, split_ref

_EPS = 1e-6


@dataclass(frozen=True)
class Corridor:
    male: str  # 轴端口引用 实例.端口
    female: str  # 孔端口引用
    start: Vec  # 世界坐标：轴根部
    end: Vec  # 世界坐标：孔口
    diameter: float

    @property
    def male_instance(self) -> str:
        return split_ref(self.male)[0]

    @property
    def female_instance(self) -> str:
        return split_ref(self.female)[0]

    def to_dict(self) -> dict:
        return {"male": self.male, "female": self.female, "start_mm": list(self.start), "end_mm": list(self.end),
                "diameter_mm": self.diameter}


def _shaft_root_z(comp: dict, port_id: str) -> float | None:
    """轴伸段（与轴端口同轴、同径、终点在轴端的圆柱段）的起点 z；找不到时为 None。"""
    p = port(comp, port_id)
    d = p.spec.get("diameter_mm", {})
    dia = d.get("value", d.get("nominal"))
    if abs(p.origin[0]) > _EPS or abs(p.origin[1]) > _EPS or abs(abs(p.axis[2]) - 1) > _EPS or dia is None:
        return None
    for part in parts(comp):
        if part.shape != "cylinder" or abs(part.diameter - dia) > _EPS:
            continue
        lo, hi = part.z_start, part.z_start + part.length
        tip = p.origin[2]
        if (p.axis[2] > 0 and abs(hi - tip) <= _EPS) or (p.axis[2] < 0 and abs(lo - tip) <= _EPS):
            return lo if p.axis[2] > 0 else hi
    return None


def corridors(scene: Scene) -> list[Corridor]:
    out = []
    for c in scene.connections:
        if c.kind != "cylinder":
            continue
        pa, _, _ = scene.port_world(c.a)
        male, female = (c.a, c.b) if pa.type == "mechanical.cyl_male" else (c.b, c.a)
        im, pid = split_ref(male)
        root = _shaft_root_z(scene.component(im), pid)
        if root is None:
            continue
        mp, _, axis_w = scene.port_world(male)
        _, entrance_w, _ = scene.port_world(female)
        start = scene.pose(im).apply((mp.origin[0], mp.origin[1], root))
        # 只取轴根部到孔口这一段；孔口在根部之后（轴全部在孔内）时没有穿过段
        length = dot(sub(entrance_w, start), axis_w)
        if length <= _EPS:
            continue
        end = add(start, scale(axis_w, length))
        d = mp.spec["diameter_mm"]
        out.append(Corridor(male, female, start, end, float(d.get("value", d.get("nominal")))))
    return out
