"""由布局场景生成 FreeCAD 实体（ADR-0032）：包络各段合并，减去 cyl_female 孔，再按实例位姿放置。

只能在 FreeCAD 的 Python 中导入。
"""

from __future__ import annotations

import FreeCAD
import Part

from freecad_addon.core.geometry import bores, part_extent, parts
from freecad_addon.core.pose import Pose, dot

# 孔从孔口前 MARGIN 处开始、贯穿时多切 MARGIN，避免与包络端面共面导致布尔运算残片
MARGIN_MM = 1.0


def vec(v) -> FreeCAD.Vector:
    return FreeCAD.Vector(float(v[0]), float(v[1]), float(v[2]))


def placement(pose: Pose) -> FreeCAD.Placement:
    w, x, y, z = pose.rotation
    return FreeCAD.Placement(vec(pose.translation), FreeCAD.Rotation(x, y, z, w))


def part_solid(p) -> Part.Shape:
    if p.shape == "cylinder":
        return Part.makeCylinder(p.diameter / 2, p.length, FreeCAD.Vector(0, 0, p.z_start))
    return Part.makeBox(p.width, p.height, p.length, FreeCAD.Vector(-p.width / 2, -p.height / 2, p.z_start))


def _fuse(solids: list) -> Part.Shape:
    shape = solids[0]
    for s in solids[1:]:
        shape = shape.fuse(s)
    return shape.removeSplitter() if len(solids) > 1 else shape


def bore_solid(comp: dict, bore) -> Part.Shape:
    """孔的切除体：从孔口前 MARGIN 起，长度为 depth（未知时贯穿包络）。"""
    if bore.depth is not None:
        length = bore.depth
    else:
        far = max(part_extent(p, Pose(), bore.axis)[1] for p in parts(comp))
        length = max(0.0, far - dot(bore.origin, bore.axis))
    start = vec(bore.origin) - vec(bore.axis) * MARGIN_MM
    extra = MARGIN_MM * (2 if bore.depth is None else 1)
    return Part.makeCylinder(bore.diameter / 2, length + extra, start, vec(bore.axis))


def component_shape(comp: dict) -> Part.Shape:
    """组件坐标系中的包络实体（已减去孔）。"""
    shape = _fuse([part_solid(p) for p in parts(comp)])
    for b in bores(comp):
        shape = shape.cut(bore_solid(comp, b))
    return shape


def instance_shape(comp: dict, pose: Pose) -> Part.Shape:
    shape = component_shape(comp).copy()
    shape.Placement = placement(pose)
    return shape
