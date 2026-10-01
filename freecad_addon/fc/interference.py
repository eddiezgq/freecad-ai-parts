"""干涉检查（ADR-0032 第 3 节、ADR-0033）。只能在 FreeCAD 的 Python 中导入。

每对实例先比包围盒，再求布尔交集体积：
- 交集体积不大于阈值（缺省 1 mm³）的不报，用来吸收同径轴孔、贴合面的数值残余
- 轴穿过通道内、与同组其他实例的重叠单独列为“需有通孔”，不计为干涉
"""

from __future__ import annotations

import itertools

import FreeCAD  # noqa: F401  须先于 Part 导入，否则在普通 Python 中会段错误
import Part

from freecad_addon.core.corridors import Corridor, corridors
from freecad_addon.core.pose import norm, sub
from freecad_addon.core.scene import Scene
from freecad_addon.fc.shapes import instance_shape, vec

DEFAULT_THRESHOLD_MM3 = 1.0


def _r(x: float, nd: int = 3) -> float:
    v = round(x, nd)
    return 0.0 if v == 0 else v


def _bbox(shape: Part.Shape) -> dict:
    b = shape.BoundBox
    return {"min_mm": [_r(b.XMin), _r(b.YMin), _r(b.ZMin)], "max_mm": [_r(b.XMax), _r(b.YMax), _r(b.ZMax)]}


def _corridor_solid(c: Corridor, margin: float) -> Part.Shape:
    axis = vec(sub(c.end, c.start))
    length = norm(sub(c.end, c.start))
    axis.normalize()
    return Part.makeCylinder(c.diameter / 2 + margin, length, vec(c.start), axis)


def check(scene: Scene, threshold_mm3: float = DEFAULT_THRESHOLD_MM3) -> dict:
    names = sorted(scene.instances)
    shapes = {n: instance_shape(scene.component(n), scene.pose(n)) for n in names}
    groups = {n: frozenset(scene.group(n)) for n in names}
    cors = corridors(scene)
    interferences, pass_through, connected = [], [], set()
    for c in scene.connections:
        connected.add(frozenset((c.a.split(".")[0], c.b.split(".")[0])))

    for a, b in itertools.combinations(names, 2):
        if not shapes[a].BoundBox.intersect(shapes[b].BoundBox):
            continue
        common = shapes[a].common(shapes[b])
        vol = common.Volume
        if vol <= threshold_mm3:
            continue
        excused = []
        for c in cors:
            im, iff = c.male_instance, c.female_instance
            other = b if a == im else a if b == im else None
            if other is None or other == iff or other not in groups[im]:
                continue
            common = common.cut(_corridor_solid(c, scene.tol_mm))
            excused.append(c)
        rest = common.Volume if excused else vol
        if excused and vol - rest > threshold_mm3:
            pass_through.append({
                "instance": b if a in {c.male_instance for c in excused} else a,
                "shaft": sorted({c.male for c in excused}),
                "volume_mm3": _r(vol - rest),
                "note": "轴从此处穿过；V1 包络未建模通孔，请确认该零件有供轴穿过的孔",
            })
        if rest > threshold_mm3:
            interferences.append({
                "a": a, "b": b, "volume_mm3": _r(rest), "bbox": _bbox(common),
                "connected": frozenset((a, b)) in connected,
                "same_group": b in groups[a],
            })
    return {
        "ok": not interferences,
        "threshold_mm3": threshold_mm3,
        "interferences": interferences,
        "pass_through": pass_through,
        "instances": names,
    }


def check_dict(scene_dict: dict, threshold_mm3: float = DEFAULT_THRESHOLD_MM3) -> dict:
    return check(Scene.from_dict(scene_dict), threshold_mm3)

