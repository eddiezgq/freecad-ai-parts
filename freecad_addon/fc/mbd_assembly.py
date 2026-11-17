"""FreeCAD Assembly 工作台装配体 → 中性描述 → 多体模型（ADR-0097 D5a，补充九）。需要 FreeCAD，不需要界面。

只读 FreeCAD 里的事实（实体、材料、运动副坐标系），换算和检查都在 analysis/mbd/assembly.py。
"""

from __future__ import annotations

import FreeCAD as App
import Part

from analysis.mbd import assembly as A

SKIP_TYPES = {"Assembly::JointGroup", "Assembly::ViewGroup", "Assembly::BomGroup", "App::Origin", "App::Line", "App::Plane",
              "App::Point", "App::DocumentObjectGroup"}


def find_assembly(doc):
    for o in doc.Objects:
        if o.TypeId == "Assembly::AssemblyObject" and not any(p.TypeId == "Assembly::AssemblyObject" for p in o.InList):
            return o
    return None


def _density(obj):
    """(材料名, 密度 kg/m³)；没有材料属性时 (None, None)"""
    mat = getattr(obj, "ShapeMaterial", None)
    if mat is None:
        return None, None
    rho = mat.PhysicalProperties.get("Density") if hasattr(mat, "PhysicalProperties") else None
    if not rho:
        return mat.Name, None
    return mat.Name, float(App.Units.Quantity(rho).getValueAs("kg/m^3"))


def _leaves(obj):
    """一个装配件里带形状的“叶子”零件（App::Part 往下找；被别的子对象用掉的中间特征不算）"""
    lk = obj.getLinkedObject(True) if hasattr(obj, "getLinkedObject") else obj
    if lk.TypeId == "App::Part":
        group = [c for c in lk.Group if c.TypeId not in SKIP_TYPES]
        names = {c.Name for c in group}
        out = []
        for c in group:
            if any(p.Name in names for p in c.InList if p is not lk):
                continue                      # 被组里别的对象用掉了（例如布尔运算的输入）
            out += [(f"{c.Name}.{s}", leaf) for s, leaf in _leaves(c)] if c.TypeId == "App::Part" else [(f"{c.Name}.", c)]
        return out
    return [("", lk)]


def _solid_props(assembly, top, sub, leaf):
    shape = Part.getShape(assembly, f"{top.Name}.{sub}", needSubElement=False, transform=True)
    solids = shape.Solids
    if not solids:
        return None
    V = sum(s.Volume for s in solids)
    c = App.Vector()
    for s in solids:
        c += s.CenterOfMass * s.Volume
    c = c * (1.0 / V)
    I = [[0.0] * 3 for _ in range(3)]
    for s in solids:                          # 各实体对自身质心的张量 + 平行轴移到总质心（单位密度）
        M = s.MatrixOfInertia
        d = s.CenterOfMass - c
        dd = d.x * d.x + d.y * d.y + d.z * d.z
        dv = (d.x, d.y, d.z)
        for r in range(3):
            for k in range(3):
                I[r][k] += M.A[4 * r + k] + s.Volume * ((dd if r == k else 0.0) - dv[r] * dv[k])
    mat, rho = _density(leaf)
    return {"label": leaf.Label, "volume_mm3": V, "cm_mm": [c.x, c.y, c.z], "inertia_unit_mm5": I,
            "material": mat, "density_kg_m3": rho}


def describe(assembly, mass_overrides=None) -> dict:
    """装配体 → 中性描述（见 analysis/mbd/assembly.py）"""
    import JointObject
    import UtilsAssembly

    mass_overrides = mass_overrides or {}
    grounded, joints = set(), []
    for o in assembly.OutListRecursive:
        proxy = getattr(o, "Proxy", None)
        if isinstance(proxy, JointObject.GroundedJoint) and o.ObjectToGround is not None:
            grounded.add(o.ObjectToGround.Name)
        elif isinstance(proxy, JointObject.Joint):
            if getattr(o, "Suppressed", False) or getattr(o, "Activated", True) is False:
                continue
            p1 = UtilsAssembly.getMovingPart(assembly, o.Reference1)
            p2 = UtilsAssembly.getMovingPart(assembly, o.Reference2)
            g1 = UtilsAssembly.getJcsGlobalPlc(o.Placement1, o.Reference1)
            g2 = UtilsAssembly.getJcsGlobalPlc(o.Placement2, o.Reference2)
            joints.append({"id": o.Name, "label": o.Label, "type": o.JointType,
                           "part1": p1.Name if p1 else None, "part2": p2.Name if p2 else None,
                           "frame1": _frame(g1), "frame2": _frame(g2)})
    parts = []
    for top in assembly.Group:
        if top.TypeId in SKIP_TYPES or top.TypeId.startswith("Assembly::"):
            continue
        if getattr(top, "Proxy", None) is not None and not hasattr(top, "Shape"):
            continue
        if not hasattr(top, "Shape") and top.TypeId != "App::Link":
            continue
        solids = [sp for sp in (_solid_props(assembly, top, sub, leaf) for sub, leaf in _leaves(top)) if sp]
        part = {"id": top.Name, "label": top.Label, "grounded": top.Name in grounded, "solids": solids}
        if top.Name in mass_overrides:
            part["mass_kg"] = float(mass_overrides[top.Name])
        parts.append(part)
    return {"name": assembly.Label, "parts": parts, "joints": joints}


def _frame(plc):
    r = plc.Rotation
    z, x = r.multVec(App.Vector(0, 0, 1)), r.multVec(App.Vector(1, 0, 0))
    return {"origin_mm": [plc.Base.x, plc.Base.y, plc.Base.z], "z": [z.x, z.y, z.z], "x": [x.x, x.y, x.z]}


def model_from_assembly(assembly, **kw):
    """装配体 → (mbd-model/1, 消息)；有问题抛 analysis.mbd.assembly.AssemblyError（列出全部问题）"""
    return A.to_model(describe(assembly, kw.pop("mass_overrides", None)), **kw)
