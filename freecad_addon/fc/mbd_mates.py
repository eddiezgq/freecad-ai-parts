"""STEP 装配导入 → 找运动副候选 → （AI / 规则）草稿 → 人确认后建成 Assembly 工作台装配体（ADR-0097 D5b，补充十一）。
需要 FreeCAD，不需要界面。几何判断在 analysis/mbd/mates.py，AI 挑选在 assist/mbd_mates.py。
"""

from __future__ import annotations

import FreeCAD as App
import Part

from analysis.mbd import mates as MT


def import_step(path: str, doc) -> list:
    """把 STEP 装配导进 doc，返回每个实体零件（叶子 Part::Feature）"""
    import Import

    before = {o.Name for o in doc.Objects}
    Import.insert(str(path), doc.Name)
    doc.recompute()
    new = [o for o in doc.Objects if o.Name not in before]
    parts = []
    for o in new:
        if not o.isDerivedFrom("Part::Feature") or not o.Shape.Solids:
            continue
        if any(p.isDerivedFrom("Part::Feature") and p.Name not in before for p in o.InList):
            continue
        parts.append(o)
    return parts


def face_summary(obj) -> dict:
    """零件 → mates.py 要的面摘要（地面坐标）"""
    shape = obj.Shape.copy()
    shape.Placement = obj.getGlobalPlacement()          # 导入时零件可能在 App::Part 里：统一到地面坐标
    faces = []
    for f in shape.Faces:
        s = f.Surface
        u0, u1, v0, v1 = f.ParameterRange
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2
        n = f.normalAt(um, vm)
        if isinstance(s, Part.Cylinder):
            P = f.valueAt(um, vm)
            c, a = s.Center, s.Axis
            radial = (P - c) - a * ((P - c).dot(a))
            faces.append({"kind": "cylinder", "point": [c.x, c.y, c.z], "axis": [a.x, a.y, a.z], "radius": s.Radius,
                          "t": [v0, v1], "convex": radial.dot(n) > 0})
        elif isinstance(s, Part.Plane):
            P = f.CenterOfMass
            faces.append({"kind": "plane", "point": [P.x, P.y, P.z], "normal": [n.x, n.y, n.z], "area": f.Area})
        elif isinstance(s, Part.Sphere):
            P = f.valueAt(um, vm)
            c = s.Center
            faces.append({"kind": "sphere", "center": [c.x, c.y, c.z], "radius": s.Radius, "convex": (P - c).dot(n) > 0})
    return {"id": obj.Name, "label": obj.Label, "volume_mm3": shape.Volume, "faces": faces}


def find(objs) -> tuple[list[dict], dict]:
    parts = [face_summary(o) for o in objs]
    return parts, MT.find_candidates(parts)


TYPE_INDEX = {"fixed": 0, "revolute": 1, "cylindrical": 2, "translational": 3, "spherical": 4}


def build_assembly(doc, objs, ground: str, joints: list[dict], name="Assembly"):
    """把零件放进新的 Assembly，按确认过的条目（mates.to_assembly_joints 的输出）建运动副"""
    from freecad_addon.fc.assembly_modules import load

    JointObject, _ = load()
    asm = doc.addObject("Assembly::AssemblyObject", name)
    jg = asm.newObject("Assembly::JointGroup", "Joints")
    by = {o.Name: o for o in objs}
    for o in objs:
        for p in list(o.InList):                   # 从导入时的 App::Part 里挪出来
            if p.TypeId == "App::Part" and o in p.Group:
                plc = o.getGlobalPlacement()
                p.removeObject(o)
                o.Placement = plc
        asm.addObject(o)
    if ground not in by:
        raise ValueError(f"机架 {ground} 不在零件里")
    g = jg.newObject("App::FeaturePython", "GroundedJoint")
    JointObject.GroundedJoint(g, by[ground])
    for j in joints:
        o1, o2 = by[j["part1"]], by[j["part2"]]
        jo = jg.newObject("App::FeaturePython", "Joint")
        JointObject.Joint(jo, TYPE_INDEX[j["type"]])
        jo.Label = j["name"]
        rot = App.Rotation(App.Vector(0, 0, 1), App.Vector(*j["axis"]))
        gpl = App.Placement(App.Vector(*j["point_mm"]), rot)
        jo.Detach1 = jo.Detach2 = True
        jo.Reference1 = [asm, [o1.Name + ".", o1.Name + "."]]
        jo.Reference2 = [asm, [o2.Name + ".", o2.Name + "."]]
        jo.Placement1 = o1.Placement.inverse() * gpl
        jo.Placement2 = o2.Placement.inverse() * gpl
    doc.recompute()
    return asm
