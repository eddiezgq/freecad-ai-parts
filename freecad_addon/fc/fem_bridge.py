"""算例 ↔ FreeCAD FEM 工作台对象（ADR-0093 补充十二第 1 步）。需要 FreeCAD（Part、ObjectsFem），不需要界面。

- `study_to_fem(doc, study)`：每个实体导入成零件对象，建 FEM“分析”节点、固体材料、约束与载荷。
  语义与 FEM 工作台一致的，用它自带的对象；对不上的，用本仓库的 FeaturePython 对象（`Fap` 开头），挂在同一个节点下。
- `fem_to_study(analysis)`：从节点读回算例。人在 FreeCAD 里改过的，以 FreeCAD 里的为准，依据记为“人工”；
  AI 起草的算例被改过，就要重新确认。人手加的 FEM 对象能转换的转换，不能的列出来、不计算，不悄悄丢掉。

面的对应：FreeCAD 的 FaceN ↔ STEP 面号（gmsh 读同一个 STEP 的编号），按面中心与面积一一对应；对不上或一对多时拒绝转换，不猜。
每个对象另存一份原始条目（`FapItem`，JSON），读回时如果 FreeCAD 里的值与它一致，就原样用它，保证往返不丢精度、不丢字段。
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import FreeCAD
import ObjectsFem
import Part

REL = 1e-9
# 与 FEM 工作台对象语义一致的条目类型
NATIVE = {"fixed", "displacement", "cyl_support", "force", "pressure", "gravity", "centrifugal", "bonded", "contact"}
# FEM 对象类型 → 读回时认得的（人手加的也能转）
KNOWN_FEM = {"Fem::ConstraintFixed", "Fem::ConstraintDisplacement", "Fem::ConstraintForce", "Fem::ConstraintPressure",
             "Fem::ConstraintTransform", "Fem::ConstraintContact"}
KNOWN_PY = {"Fem::ConstraintSelfWeight", "Fem::ConstraintCentrif", "Fem::ConstraintTie"}


class BridgeError(ValueError):
    pass


# ---------------------------------------------------------------- 面的对应


def face_table(step_path: str) -> list[dict]:
    from analysis.fea.geometry import faces

    return faces(step_path)[0]


def face_map(shape, table: list[dict], tol: float = 1e-3) -> dict[int, int]:
    """STEP 面号 → FreeCAD 的面序号（从 1 起）。按中心与面积一一对应；对不上就拒绝"""
    bb = shape.BoundBox
    scale = max(bb.DiagonalLength, 1.0)
    out: dict[int, int] = {}
    used: set[int] = set()
    for i, f in enumerate(shape.Faces, 1):
        c, a = f.CenterOfMass, f.Area
        cands = [t for t in table if abs(t["area_mm2"] - a) <= max(1e-3, 1e-4 * a)
                 and math.dist(t["center"], (c.x, c.y, c.z)) <= tol * scale]
        if len(cands) != 1:
            raise BridgeError(f"FreeCAD 的 Face{i}（面积 {a:.3f} mm²）在 STEP 面表里对上 {len(cands)} 个面，不能一一对应")
        sid = int(cands[0]["id"])
        if sid in used:
            raise BridgeError(f"STEP 面 {sid} 对上了不止一个 FreeCAD 面")
        used.add(sid)
        out[sid] = i
    if len(out) != len(table):
        raise BridgeError(f"STEP 有 {len(table)} 个面，FreeCAD 里有 {len(shape.Faces)} 个，对不齐")
    return out


# ---------------------------------------------------------------- 小工具


def _prop(obj, name: str, value: str, group: str = "Fap") -> None:
    if name not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", name, group, "零件库 / 有限元：原始数据（JSON）")
        obj.setEditorMode(name, 2)
    setattr(obj, name, value)


def _jget(obj, name: str) -> Any:
    return json.loads(getattr(obj, name)) if name in obj.PropertiesList and getattr(obj, name) else None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=REL, abs_tol=1e-12)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def _unit(v) -> list[float]:
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v] if n else [0.0, 0.0, 0.0]


def _q(qty, unit: str) -> float:
    return float(qty.getValueAs(unit).Value) if hasattr(qty, "getValueAs") else float(qty)


class _Fap:
    """本仓库的 FEM 条目（FEM 工作台没有对应对象的：扭矩、轴承载荷、螺栓预紧、附加质量……）"""

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def _fap_object(doc, analysis, name: str):
    obj = doc.addObject("Fem::ConstraintPython", name)
    _Fap(obj)
    analysis.addObject(obj)
    return obj


# ---------------------------------------------------------------- 算例 → FEM


def study_to_fem(doc, study: dict, *, base_dir: Path | None = None, tables: dict[str, list] | None = None):
    """在文档里建 FEM 分析。返回分析节点对象"""
    base = Path(base_dir) if base_dir else Path.cwd()
    analysis = ObjectsFem.makeAnalysis(doc, "FapAnalysis")
    analysis.Label = f"有限元：{study.get('name', '')}"
    rest = {k: v for k, v in study.items() if k not in ("supports", "loads", "connections")}
    _prop(analysis, "FapStudy", json.dumps(rest, ensure_ascii=False))
    parts, fmaps = {}, {}
    helpers = doc.addObject("App::DocumentObjectGroup", "FapHelpers")
    helpers.Label = "有限元辅助几何"
    for b in study["bodies"]:
        p = Path(b["step_path"])
        p = p if p.is_absolute() else base / p
        if not p.is_file():
            raise BridgeError(f"STEP 文件不存在：{b['step_path']}")
        shape = Part.Shape()
        shape.read(str(p))
        part = doc.addObject("Part::Feature", f"Fap_{b['id']}")
        part.Shape = shape
        part.Label = f"{b['id']}：{p.name}"
        _prop(part, "FapBody", json.dumps(b, ensure_ascii=False))
        table = (tables or {}).get(b["id"]) or face_table(str(p))
        fmaps[b["id"]] = face_map(shape, table)
        parts[b["id"]] = part
        if b.get("material"):
            _material(doc, analysis, part, b["material"])
    doc.recompute()

    def refs(body, faces):
        fm = fmaps[body]
        missing = [f for f in faces if f not in fm]
        if missing:
            raise BridgeError(f"实体 {body} 没有 STEP 面 {missing}")
        return [(parts[body], tuple(f"Face{fm[f]}" for f in faces))]

    def line(name, origin, direction):
        o = doc.addObject("Part::Line", name)
        o.X1, o.Y1, o.Z1 = origin
        d = _unit(direction)
        o.X2, o.Y2, o.Z2 = (origin[0] + 10 * d[0], origin[1] + 10 * d[1], origin[2] + 10 * d[2])
        o.Visibility = False
        helpers.addObject(o)
        return o

    for key in ("supports", "loads", "connections"):
        for i, it in enumerate(study.get(key) or []):
            name = f"Fap_{key}_{i}"
            obj = _native(doc, analysis, it, refs, line, name) if _is_native(it) else None
            if obj is None:
                obj = _fap_object(doc, analysis, name)
                fr = []
                if it.get("faces") and it.get("body"):
                    fr = refs(it["body"], it["faces"])
                for side in ("a", "b"):
                    if isinstance(it.get(side), dict):
                        fr += refs(it[side]["body"], it[side]["faces"])
                if fr:
                    obj.References = fr
                obj.Label = f"{_ZH.get(it['type'], it['type'])}（零件库）"
            _prop(obj, "FapItem", json.dumps(it, ensure_ascii=False))
            _prop(obj, "FapKey", f"{key}/{i}")
    doc.recompute()
    return analysis


_ZH = {"fixed": "固定", "displacement": "强制位移", "cyl_support": "圆柱面支承", "symmetry": "对称面", "elastic_support": "弹性支承",
       "force": "力", "pressure": "压力", "torque": "扭矩", "moment": "力矩", "gravity": "重力", "centrifugal": "离心",
       "remote_load": "远端载荷", "bearing_load": "轴承载荷", "temperature": "温度变化", "mass": "附加质量", "bonded": "绑定",
       "contact": "接触", "bolt_preload": "螺栓预紧"}


def _is_native(it: dict) -> bool:
    t = it["type"]
    if t not in NATIVE:
        return False
    if t == "displacement" and (it.get("edges") or not it.get("faces")):
        return False
    if t in ("bonded", "contact"):                       # Tie / Contact：每侧一个面
        return len(it["a"]["faces"]) == 1 and len(it["b"]["faces"]) == 1
    return not (t in ("fixed", "force", "pressure", "cyl_support") and not it.get("faces"))


def _native(doc, analysis, it, refs, line, name):
    t = it["type"]
    if t == "fixed":
        o = ObjectsFem.makeConstraintFixed(doc, name)
        o.References = refs(it["body"], it["faces"])
    elif t == "displacement":
        o = ObjectsFem.makeConstraintDisplacement(doc, name)
        o.References = refs(it["body"], it["faces"])
        for ax in "xyz":
            v = it.get(f"u{ax}_mm")
            setattr(o, f"{ax}Free", v is None)
            if v is not None:
                setattr(o, f"{ax}Displacement", FreeCAD.Units.Quantity(f"{v!r} mm"))
    elif t == "cyl_support":
        tr = ObjectsFem.makeConstraintTransform(doc, name + "_cyl")
        tr.TransformType = "Cylindrical"
        tr.References = refs(it["body"], it["faces"])
        analysis.addObject(tr)
        _prop(tr, "FapPartOf", name)
        o = ObjectsFem.makeConstraintDisplacement(doc, name)
        o.References = refs(it["body"], it["faces"])
        dofs = set(it.get("dofs") or ["radial", "tangential", "axial"])
        o.xFree, o.yFree, o.zFree = ("radial" not in dofs, "tangential" not in dofs, "axial" not in dofs)
        for ax in "xyz":
            setattr(o, f"{ax}Displacement", FreeCAD.Units.Quantity("0 mm"))
    elif t == "force":
        o = ObjectsFem.makeConstraintForce(doc, name)
        o.References = refs(it["body"], it["faces"])
        v = it["vector_n"]
        o.Force = FreeCAD.Units.Quantity(f"{math.sqrt(sum(x * x for x in v))!r} N")
        o.Direction = (line(name + "_dir", [0, 0, 0], v), ["Edge1"])
        o.Reversed = False
    elif t == "pressure":
        o = ObjectsFem.makeConstraintPressure(doc, name)
        o.References = refs(it["body"], it["faces"])
        o.Pressure = FreeCAD.Units.Quantity(f"{abs(it['value_mpa'])!r} MPa")
        o.Reversed = it["value_mpa"] < 0
    elif t == "gravity":
        o = ObjectsFem.makeConstraintSelfWeight(doc, name)
        a = it["acceleration_m_s2"]
        o.GravityAcceleration = FreeCAD.Units.Quantity(f"{math.sqrt(sum(x * x for x in a))!r} m/s^2")
        o.GravityDirection = FreeCAD.Vector(*_unit(a))
    elif t == "centrifugal":
        o = ObjectsFem.makeConstraintCentrif(doc, name)
        o.RotationFrequency = FreeCAD.Units.Quantity(f"{it['speed_rpm'] / 60.0!r} Hz")
        o.RotationAxis = [(line(name + "_axis", it["axis"]["origin_mm"], it["axis"]["dir"]), "Edge1")]
    elif t in ("bonded", "contact"):
        o = (ObjectsFem.makeConstraintTie if t == "bonded" else ObjectsFem.makeConstraintContact)(doc, name)
        o.References = refs(it["a"]["body"], it["a"]["faces"]) + refs(it["b"]["body"], it["b"]["faces"])
        if t == "contact" and it.get("friction_coefficient") is not None:
            o.Friction = True
            o.FrictionCoefficient = float(it["friction_coefficient"])
    else:
        return None
    o.Label = _ZH[t]
    analysis.addObject(o)
    return o


def _material(doc, analysis, part, mid: str):
    from analysis.common import materials

    m = materials._table().get(mid)
    if not m:
        raise BridgeError(f"材料 {mid} 不在材料库里")
    o = ObjectsFem.makeMaterialSolid(doc, f"FapMat_{part.Name}")
    card = {"Name": f"{mid}（{m['name']}）"}
    if "elastic_modulus_mpa" in m:
        card["YoungsModulus"] = f"{m['elastic_modulus_mpa']} MPa"
    if "poisson_ratio" in m:
        card["PoissonRatio"] = str(m["poisson_ratio"])
    if "density_kg_m3" in m:
        card["Density"] = f"{m['density_kg_m3']} kg/m^3"
    o.Material = card
    o.References = [(part, "Solid1")]
    o.Label = f"材料：{mid}（零件库材料库，出处见报告）"
    _prop(o, "FapMaterialId", mid)
    analysis.addObject(o)
    return o


# ---------------------------------------------------------------- FEM → 算例


def fem_to_study(analysis, *, tables: dict[str, list] | None = None) -> tuple[dict, dict]:
    """读回算例。返回（算例, 说明 {"changed": [...], "added": [...], "unsupported": [...]}）"""
    rest = _jget(analysis, "FapStudy") or {"format": "fea-study/1", "name": analysis.Label, "steps": [{"id": "s1", "type": "static"}]}
    study = copy.deepcopy(rest)
    note: dict[str, list] = {"changed": [], "added": [], "unsupported": []}
    doc = analysis.Document
    parts = {}
    for o in doc.Objects:
        b = _jget(o, "FapBody")
        if b:
            parts[b["id"]] = o
    if not parts:
        raise BridgeError("分析里没有零件库的实体（由 study_to_fem 建立）")
    rev = {}
    for bid, part in parts.items():
        b = _jget(part, "FapBody")
        table = (tables or {}).get(bid) or face_table(_abs(b["step_path"], doc))
        rev[part.Name] = {v: k for k, v in face_map(part.Shape, table).items()}
    by_name = {p.Name: bid for bid, p in parts.items()}
    bodies = []
    for b in rest.get("bodies") or []:
        bb = copy.deepcopy(b)
        mat = next((o for o in analysis.Group if "FapMaterialId" in o.PropertiesList
                    and any(r[0] is parts.get(b["id"]) for r in o.References)), None)
        if mat is not None and mat.FapMaterialId != b.get("material"):
            note["changed"].append(f"/bodies/{len(bodies)}/material")
            bb["material"] = mat.FapMaterialId
        bodies.append(bb)
    study["bodies"] = bodies

    def faces_of(refs_):
        """References → [(body, [STEP 面号])]"""
        out = []
        for obj, subs in refs_:
            if obj.Name not in rev:
                raise BridgeError(f"约束引用了不是零件库实体的对象 {obj.Label}")
            subs = subs if isinstance(subs, (list, tuple)) else [subs]
            ids = []
            for s in subs:
                if not s.startswith("Face"):
                    raise BridgeError(f"约束引用了 {s}（只认面）")
                ids.append(rev[obj.Name][int(s[4:])])
            out.append((by_name[obj.Name], ids))
        return out

    groups: dict[str, list[tuple[int, dict]]] = {"supports": [], "loads": [], "connections": []}
    transforms = {o.FapPartOf for o in analysis.Group if "FapPartOf" in o.PropertiesList}
    for o in analysis.Group:
        if "FapPartOf" in o.PropertiesList or "FapMaterialId" in o.PropertiesList:
            continue
        if o.TypeId.startswith("Fem::FemMesh") or o.TypeId.startswith("Fem::FemSolver") or "Result" in o.TypeId \
                or o.TypeId.startswith("App::MaterialObject") or o.TypeId == "Fem::FemSolverObjectPython":
            continue
        stored = _jget(o, "FapItem")
        key = getattr(o, "FapKey", "") if "FapKey" in o.PropertiesList else ""
        if stored is not None and not _is_native(stored):
            item = copy.deepcopy(stored)
            if "faces" in stored and stored.get("body") and o.References:
                (_body, ids), *_ = faces_of(o.References)
                if sorted(ids) != sorted(stored["faces"]):
                    item["faces"] = ids
                    note["changed"].append(key)
            groups[key.split("/")[0]].append((int(key.split("/")[1]), item))
            continue
        kind_type = _fem_type(o)
        if kind_type is None:
            note["unsupported"].append(f"{o.Label}（{o.TypeId}）：本仓库的求解链不支持，不计算")
            continue
        try:
            item = _read_native(o, kind_type, faces_of, stored, o.Name in transforms)
        except BridgeError as e:
            note["unsupported"].append(f"{o.Label}：{e}")
            continue
        if stored is not None:
            if not _same(_core(item), _core(stored)):
                note["changed"].append(key)
                item = {**{k: v for k, v in stored.items() if k == "case"}, **item}
            else:
                item = stored
            groups[key.split("/")[0]].append((int(key.split("/")[1]), item))
        else:
            k = "supports" if kind_type in ("fixed", "displacement", "cyl_support") else \
                "connections" if kind_type in ("bonded", "contact") else "loads"
            groups[k].append((10 ** 6 + len(groups[k]), item))
            note["added"].append(f"{o.Label} → {kind_type}")
    for k, rows in groups.items():
        items = [it for _, it in sorted(rows, key=lambda x: x[0])]
        if items or k != "connections":
            study[k] = items
        elif "connections" in study:
            study.pop("connections")
    if not study.get("connections"):
        study.pop("connections", None)
    _mark_human_edits(study, note)
    return study, note


def _abs(p: str, doc) -> str:
    q = Path(p)
    if q.is_absolute():
        return str(q)
    base = Path(doc.FileName).parent if doc.FileName else Path.cwd()
    return str(base / q) if (base / q).is_file() else str(Path.cwd() / q)


def _fem_type(o) -> str | None:
    t = o.TypeId
    if t == "Fem::ConstraintFixed":
        return "fixed"
    if t == "Fem::ConstraintDisplacement":
        return "displacement"
    if t == "Fem::ConstraintForce":
        return "force"
    if t == "Fem::ConstraintPressure":
        return "pressure"
    if t == "Fem::ConstraintContact":
        return "contact"
    if t == "Fem::ConstraintPython":
        pt = getattr(getattr(o, "Proxy", None), "Type", "")
        return {"Fem::ConstraintSelfWeight": "gravity", "Fem::ConstraintCentrif": "centrifugal", "Fem::ConstraintTie": "bonded"}.get(pt)
    return None


def _core(it: dict) -> dict:
    """比较用：去掉 FreeCAD 里表达不了的附带字段"""
    return {k: v for k, v in it.items() if k not in ("case", "band_mm", "tolerance_mm", "id", "axis")}


def _read_native(o, t: str, faces_of, stored: dict | None, has_transform: bool) -> dict:
    if t == "gravity":
        g = _q(o.GravityAcceleration, "m/s^2")
        d = o.GravityDirection
        body = (stored or {}).get("body")
        if body is None:
            raise BridgeError("重力在本仓库按实体加：人手加的重力请用起草或在算例里指明实体")
        return {"type": "gravity", "body": body, "acceleration_m_s2": [g * d.x, g * d.y, g * d.z]}
    if t == "centrifugal":
        body = (stored or {}).get("body")
        if body is None or not o.RotationAxis:
            raise BridgeError("离心载荷要指明实体与转轴")
        e = o.RotationAxis[0][0].Shape.Edges[0]
        p0, p1 = e.Vertexes[0].Point, e.Vertexes[-1].Point
        return {"type": "centrifugal", "body": body, "speed_rpm": _q(o.RotationFrequency, "Hz") * 60.0,
                "axis": (stored or {}).get("axis") or {"origin_mm": [p0.x, p0.y, p0.z], "dir": _unit([p1.x - p0.x, p1.y - p0.y, p1.z - p0.z])}}
    refs = faces_of(o.References)
    if t in ("bonded", "contact"):
        if len(refs) != 2:
            raise BridgeError("绑定 / 接触要两侧各一组面")
        it = {"type": t, "a": {"body": refs[0][0], "faces": refs[0][1]}, "b": {"body": refs[1][0], "faces": refs[1][1]}}
        if stored and stored.get("id"):
            it = {"type": t, "id": stored["id"], **{k: it[k] for k in ("a", "b")}}
        if t == "contact" and o.Friction:
            it["friction_coefficient"] = float(o.FrictionCoefficient)
        return it
    if len(refs) != 1:
        raise BridgeError("一个约束只能作用在一个实体上")
    body, ids = refs[0]
    if t == "fixed":
        return {"type": "fixed", "body": body, "faces": ids}
    if t == "displacement":
        if has_transform:
            dofs = [n for n, free in (("radial", o.xFree), ("tangential", o.yFree), ("axial", o.zFree)) if not free]
            axis = (stored or {}).get("axis") or _cyl_axis(o)
            it = {"type": "cyl_support", "body": body, "faces": ids, "axis": axis, "dofs": dofs}
            return it
        it = {"type": "displacement", "body": body, "faces": ids}
        for ax in "xyz":
            if not getattr(o, f"{ax}Free"):
                it[f"u{ax}_mm"] = _q(getattr(o, f"{ax}Displacement"), "mm")
        return it
    if t == "force":
        f = _q(o.Force, "N")
        d = o.DirectionVector
        if d.Length == 0:
            raise BridgeError("力没有方向")
        d = d * (1 / d.Length)
        if o.Reversed:
            d = d * -1
        return {"type": "force", "body": body, "faces": ids, "vector_n": [f * d.x, f * d.y, f * d.z]}
    if t == "pressure":
        p = _q(o.Pressure, "MPa")
        return {"type": "pressure", "body": body, "faces": ids, "value_mpa": -p if o.Reversed else p}
    raise BridgeError(f"不认识的类型 {t}")


def _cyl_axis(o) -> dict:
    obj, subs = o.References[0]
    f = obj.Shape.getElement(subs[0] if isinstance(subs, (list, tuple)) else subs)
    s = f.Surface
    if not hasattr(s, "Axis"):
        raise BridgeError("圆柱面支承选的不是圆柱面")
    c, a = s.Center, s.Axis
    return {"origin_mm": [c.x, c.y, c.z], "dir": _unit([a.x, a.y, a.z])}


def _mark_human_edits(study: dict, note: dict) -> None:
    """在 FreeCAD 里改过 / 加过的：依据记为人工；AI 起草的算例被改过就要重新确认"""
    pv = study.get("provenance")
    if not pv or not (note["changed"] or note["added"]):
        return
    basis = [b for b in pv.get("basis") or [] if b["target"] not in set(note["changed"])]
    for k in note["changed"]:
        basis.append({"target": "/" + k if not k.startswith("/") else k, "source": "human", "note": "在 FreeCAD 里改过"})
    for key in ("supports", "loads", "connections"):
        n_before = {b["target"] for b in basis}
        for i in range(len(study.get(key) or [])):
            if f"/{key}/{i}" not in n_before:
                basis.append({"target": f"/{key}/{i}", "source": "human", "note": "在 FreeCAD 里人手加的"})
    pv["basis"] = basis
    if pv.get("drafted_by") == "ai" and pv.get("confirmed_by_human"):
        pv["confirmed_by_human"] = False
        pv.pop("confirmed_by", None)
        pv.pop("confirmed_at", None)
        pv["questions"] = list(pv.get("questions") or [])
