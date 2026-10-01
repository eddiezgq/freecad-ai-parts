"""布局场景（ADR-0032）：实例、位姿与端口配合。场景以 MCP 服务端为准，FreeCAD 文档只是它的视图。

配合约定（ADR-0032 第 2 节）：
- 相配端口的轴向在世界坐标中相同（装配插入方向）
- 面配合（flange↔flange、mount_face↔mount_face）：原点重合，绕轴转角 roll_deg
- 圆柱配合（cyl_male↔cyl_female）：同轴；只有圆柱配合时孔口放在“轴端 − 插入深度”处，
  插入深度取轴的 usable_length_mm 与孔的 depth_mm 中较小的一个，都缺时为 0 并提示；offset_mm 沿轴向平移
- connect(a, b) 移动 b 所在的刚性组；a、b 已在同一组时不移动，只核对对齐并给出偏差
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from freecad_addon.core.geometry import LayoutError, Port, distance_to_line, port, spec_nominal
from freecad_addon.core.pose import (
    Pose,
    add,
    angle_deg,
    dot,
    norm,
    quat_axis_angle,
    scale,
    shortest_arc,
    sub,
)

FACE = {"mechanical.flange": "mechanical.flange", "mechanical.mount_face": "mechanical.mount_face"}
CYL = {"mechanical.cyl_male": "mechanical.cyl_female", "mechanical.cyl_female": "mechanical.cyl_male"}

INSTANCE_RE = re.compile(r"[a-z][a-z0-9_]*")
TOL_MM = 0.01
TOL_DEG = 0.01


def mate_kind(type_a: str, type_b: str) -> str:
    if FACE.get(type_a) == type_b:
        return "face"
    if CYL.get(type_a) == type_b:
        return "cylinder"
    raise LayoutError(f"端口类型 {type_a} 与 {type_b} 不能配合")


def split_ref(ref: str) -> tuple[str, str]:
    inst, sep, pid = ref.partition(".")
    if not sep or not inst or not pid:
        raise LayoutError(f"端口引用须写成 实例.端口，收到 {ref!r}")
    return inst, pid


@dataclass
class Connection:
    a: str
    b: str
    kind: str
    roll_deg: float = 0.0
    offset_mm: float = 0.0

    def to_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "kind": self.kind, "roll_deg": self.roll_deg, "offset_mm": self.offset_mm}


def _engagement(male: Port, female: Port) -> tuple[float, str | None]:
    known = [v for v in (spec_nominal(male, "usable_length_mm"), spec_nominal(female, "depth_mm")) if v is not None]
    if known:
        return min(known), None
    return 0.0, "插入深度未知（轴无 usable_length_mm、孔无 depth_mm），孔口按轴端放置，请用 offset_mm 指定"


class Scene:
    def __init__(self, tol_mm: float = TOL_MM, tol_deg: float = TOL_DEG):
        self.tol_mm = tol_mm
        self.tol_deg = tol_deg
        self.instances: dict[str, dict] = {}  # 名称 → {"component": 组件, "pose": Pose}
        self.connections: list[Connection] = []

    # ------------------------------------------------------------ 查询

    def component(self, instance: str) -> dict:
        if instance not in self.instances:
            raise LayoutError(f"场景中没有实例 {instance}")
        return self.instances[instance]["component"]

    def pose(self, instance: str) -> Pose:
        self.component(instance)
        return self.instances[instance]["pose"]

    def port_world(self, ref: str) -> tuple[Port, tuple, tuple]:
        inst, pid = split_ref(ref)
        p = port(self.component(inst), pid)
        pose = self.pose(inst)
        return p, pose.apply(p.origin), pose.apply_dir(p.axis)

    def group(self, instance: str, connections: list[Connection] | None = None) -> set[str]:
        """经配合连在一起的实例（刚性组）。"""
        self.component(instance)
        conns = self.connections if connections is None else connections
        seen, todo = {instance}, [instance]
        while todo:
            cur = todo.pop()
            for c in conns:
                ends = (split_ref(c.a)[0], split_ref(c.b)[0])
                if cur in ends:
                    other = ends[1] if ends[0] == cur else ends[0]
                    if other not in seen:
                        seen.add(other)
                        todo.append(other)
        return seen

    # ------------------------------------------------------------ 修改

    def place(self, instance: str, component: dict | None = None, pose: Pose | None = None) -> dict:
        """新增实例，或把已有实例（连同其刚性组）移到给定位姿。"""
        pose = pose or Pose()
        if instance not in self.instances:
            if component is None:
                raise LayoutError(f"新实例 {instance} 须给出组件")
            if not INSTANCE_RE.fullmatch(instance):
                raise LayoutError(f"实例名 {instance!r} 须为小写字母开头，只含小写字母、数字与下划线（同系统 schema）")
            self.instances[instance] = {"component": copy.deepcopy(component), "pose": pose}
            return {"instance": instance, "moved": [instance]}
        if component is not None and component.get("id") != self.component(instance).get("id"):
            raise LayoutError(f"实例 {instance} 已是 {self.component(instance).get('id')}，换组件须先删除")
        delta = pose.compose(self.pose(instance).inverse())
        moved = sorted(self.group(instance))
        for name in moved:
            self.instances[name]["pose"] = delta.compose(self.instances[name]["pose"])
        return {"instance": instance, "moved": moved}

    def remove(self, instance: str) -> dict:
        self.component(instance)
        del self.instances[instance]
        dropped = [c.to_dict() for c in self.connections if instance in (split_ref(c.a)[0], split_ref(c.b)[0])]
        self.connections = [c for c in self.connections
                            if instance not in (split_ref(c.a)[0], split_ref(c.b)[0])]
        return {"removed": instance, "dropped_connections": dropped}

    def connect(self, a: str, b: str, roll_deg: float = 0.0, offset_mm: float = 0.0) -> dict:
        ia, ib = split_ref(a)[0], split_ref(b)[0]
        if ia == ib:
            raise LayoutError("不能连接同一实例的两个端口")
        pa, _, _ = self.port_world(a)
        pb, _, _ = self.port_world(b)
        kind = mate_kind(pa.type, pb.type)
        for c in self.connections:
            if {c.a, c.b} == {a, b}:
                raise LayoutError(f"{a} 与 {b} 已经连接")
        if kind == "face" and offset_mm:
            raise LayoutError("面配合不支持 offset_mm（原点须重合）")
        result: dict = {"a": a, "b": b, "kind": kind}
        conn = Connection(a, b, kind, float(roll_deg), float(offset_mm))

        if ib not in self.group(ia):
            result.update(self._mate(a, b, kind, roll_deg, offset_mm, sorted(self.group(ib))))
            self.connections.append(conn)
            return result

        # 已在同一刚性组。面配合时，若两实例只经它们之间的圆柱配合相连，则由面配合重定轴向位置
        cyl_between = [c for c in self.connections
                       if c.kind == "cylinder" and {split_ref(c.a)[0], split_ref(c.b)[0]} == {ia, ib}]
        rest = [c for c in self.connections if c not in cyl_between]
        movable = self.group(ib, rest)
        if kind == "face" and cyl_between and ia not in movable:
            saved = {n: v["pose"] for n, v in self.instances.items()}
            result.update(self._mate(a, b, kind, roll_deg, 0.0, sorted(movable)))
            checks = []
            for c in cyl_between:
                try:
                    checks.append({"a": c.a, "b": c.b, **self._check(c.a, c.b, "cylinder")})
                except LayoutError:
                    for n, pose in saved.items():
                        self.instances[n]["pose"] = pose
                    raise
            result["rechecked"] = checks
            result["note"] = "两实例此前只经圆柱配合相连，已按面配合重定轴向位置，并核对圆柱配合同轴"
            self.connections.append(conn)
            return result

        if roll_deg or offset_mm:
            raise LayoutError(f"{ia} 与 {ib} 已在同一刚性组，不能再用 roll_deg、offset_mm 调整")
        result.update(moved=[], check=self._check(a, b, kind))
        self.connections.append(conn)
        return result

    def _mate(self, a: str, b: str, kind: str, roll_deg: float, offset_mm: float, movable: list[str]) -> dict:
        """把 movable（含 b 的实例）整体移到与 a 配合的位置。"""
        pa, oa, aa = self.port_world(a)
        pb, _, _ = self.port_world(b)
        ib = split_ref(b)[0]
        out: dict = {}
        rot = quat_axis_angle(aa, roll_deg) if roll_deg else (1.0, 0.0, 0.0, 0.0)
        r = Pose(rot).compose(Pose(shortest_arc(pb.axis, aa)))
        target_origin = oa
        if kind == "cylinder":
            male, female = (pa, pb) if pa.type == "mechanical.cyl_male" else (pb, pa)
            e, note = _engagement(male, female)
            # a 为轴：孔口在轴端后退 e；a 为孔：轴端在孔口前进 e
            target_origin = add(oa, scale(aa, -e if pa.type == "mechanical.cyl_male" else e))
            target_origin = add(target_origin, scale(aa, offset_mm))
            out["engagement_mm"] = e
            if note and not offset_mm:
                out["note"] = note
        target = Pose(r.rotation, sub(target_origin, r.apply(pb.origin)))
        delta = target.compose(self.pose(ib).inverse())
        for name in movable:
            self.instances[name]["pose"] = delta.compose(self.instances[name]["pose"])
        out["moved"] = movable
        return out

    def _check(self, a: str, b: str, kind: str) -> dict:
        """核对已在同一刚性组的两端口是否对齐；超出容差则报错。"""
        pa, oa, aa = self.port_world(a)
        _, ob, ab = self.port_world(b)
        ang = angle_deg(aa, ab)
        dev = norm(sub(ob, oa)) if kind == "face" else distance_to_line(ob, oa, aa)
        check = {"position_deviation_mm": round(dev, 6), "angle_deviation_deg": round(ang, 6)}
        if kind == "cylinder":
            # 实际插入深度 = 轴端到孔口沿轴向的距离
            depth = dot(sub(oa, ob), aa) if pa.type == "mechanical.cyl_male" else dot(sub(ob, oa), aa)
            check["engagement_mm"] = round(depth, 6)
        if dev > self.tol_mm or ang > self.tol_deg:
            raise LayoutError(f"{a} 与 {b} 未对齐：{'位置' if kind == 'face' else '同轴'}偏差 {dev:.4f} mm、"
                              f"角度偏差 {ang:.4f}°（容差 {self.tol_mm} mm、{self.tol_deg}°）")
        return check

    # ------------------------------------------------------------ 序列化

    def to_dict(self) -> dict:
        return {
            "tolerance": {"position_mm": self.tol_mm, "angle_deg": self.tol_deg},
            "instances": [{"instance": n, "component": v["component"], "pose": v["pose"].to_dict()}
                          for n, v in sorted(self.instances.items())],
            "connections": [c.to_dict() for c in self.connections],
        }

    @staticmethod
    def from_dict(d: dict) -> Scene:
        tol = d.get("tolerance", {})
        s = Scene(tol.get("position_mm", TOL_MM), tol.get("angle_deg", TOL_DEG))
        for item in d.get("instances", []):
            s.instances[item["instance"]] = {"component": item["component"], "pose": Pose.from_dict(item["pose"])}
        s.connections = [Connection(c["a"], c["b"], c["kind"], c.get("roll_deg", 0.0), c.get("offset_mm", 0.0))
                         for c in d.get("connections", [])]
        return s
