"""STEP 装配 → 运动副候选 → 草稿 → Assembly → 多体模型（ADR-0097 D5b 验收）。需要 FreeCAD。

验收件：平缝机挑线机构（《缝纫机设计与制造》第 4 章四连杆 LK0：曲柄 r = 20.7、相位 −6.8°，挑线连杆铰点 Q = (z 21.5, y −45.5)，
挑线杆 P→M = 43.4，挑线连杆 Q→M = 40.9；坐标同问渠平缝机样机：x 沿上轴、yz 是机构平面）。
零件用销、孔造型，导出成 STEP 再导入（导入后只剩几何，没有任何约束），程序找出四个转动副，建成装配体，转一圈：
挑线杆上 M 点的轨迹与四连杆解析解（两圆交点）一致到 1e-6 mm。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytestmark = pytest.mark.freecad

LK = {"r": 20.7, "d": -6.8, "Qz": 21.5, "Qy": -45.5, "a": 43.4, "b": 40.9}
STEEL = "06ae5c92-de7b-46c9-984d-4dd87964bc5c"


def _yz(y, z):
    return np.array([0.0, y, z])


def circle_meet(P, rp, Q, rq, near):
    d = Q - P
    L = np.linalg.norm(d)
    a = (rp * rp - rq * rq + L * L) / (2 * L)
    h = math.sqrt(max(rp * rp - a * a, 0.0))
    base = P + a * d / L
    perp = np.array([0.0, -d[2], d[1]]) / L
    s1, s2 = base + h * perp, base - h * perp
    return s1 if np.linalg.norm(s1 - near) < np.linalg.norm(s2 - near) else s2


def geometry():
    q = math.radians(LK["d"])
    P = _yz(-LK["r"] * math.cos(q), -LK["r"] * math.sin(q))
    Q = _yz(LK["Qy"], LK["Qz"])
    M = circle_meet(P, LK["a"], Q, LK["b"], near=_yz(-10, 60))
    return P, Q, M


def build_parts(doc):
    import FreeCAD as App
    import Part

    V = App.Vector
    X = V(1, 0, 0)

    def cyl(r, x0, x1, p):
        return Part.makeCylinder(r, x1 - x0, V(x0, p[1], p[2]), X)

    def bar(p1, p2, w, x0, x1):
        d = (p2 - p1) / np.linalg.norm(p2 - p1)
        n = np.array([0.0, -d[2], d[1]]) * w / 2
        pts = [p1 + n, p2 + n, p2 - n, p1 - n, p1 + n]
        wire = Part.makePolygon([V(x0, p[1], p[2]) for p in pts])
        return Part.Face(wire).extrude(V(x1 - x0, 0, 0))

    P, Q, M = geometry()
    O = np.zeros(3)
    frame = Part.makeBox(5, 70, 45, V(0, -55, -15)).fuse(Part.makeBox(20, 30, 30, V(0, -15, -15)))
    frame = frame.fuse(cyl(3, -12, 0, Q)).cut(cyl(6, -1, 21, O)).removeSplitter()
    crank = cyl(6, -6, 25, O).fuse(cyl(26, -10.5, -6, O)).fuse(cyl(3, -17, -10.5, P)).removeSplitter()
    lever = cyl(7, -16, -12, P).fuse(cyl(5, -16, -12, M)).fuse(bar(P, M, 8, -16, -12))
    lever = lever.cut(cyl(3, -17, -11, P)).cut(cyl(2.2, -17, -11, M)).removeSplitter()
    link = cyl(6, -11, -7, Q).fuse(cyl(4.5, -11, -7, M)).fuse(bar(Q, M, 7, -11, -7)).cut(cyl(3, -12, -6, Q))
    link = link.fuse(cyl(2.2, -17, -11, M)).removeSplitter()
    objs = []
    for name, label, s in (("Frame", "机壳", frame), ("Crank", "上轴挑线曲柄", crank), ("Lever", "挑线杆", lever),
                           ("Link", "挑线连杆", link)):
        o = doc.addObject("Part::Feature", name)
        o.Shape = s
        o.Label = label
        objs.append(o)
    doc.recompute()
    return objs


@pytest.fixture
def imported(tmp_path):
    import FreeCAD as App
    import Import

    from freecad_addon.fc import mbd_mates as MM

    src = App.newDocument("takeup_src")
    objs = build_parts(src)
    path = tmp_path / "takeup.step"
    Import.export(objs, str(path))
    App.closeDocument(src.Name)
    doc = App.newDocument("takeup")
    parts = MM.import_step(str(path), doc)
    yield doc, parts
    App.closeDocument(doc.Name)


def test_takeup_mechanism_from_step(imported):
    import FreeCAD as App
    import Materials

    from analysis.mbd import mates as MT
    from analysis.mbd.dae import run as R
    from assist import mbd_mates as AM
    from freecad_addon.fc import mbd_assembly as MA
    from freecad_addon.fc import mbd_mates as MM

    doc, objs = imported
    assert sorted(o.Label for o in objs) == sorted(["机壳", "上轴挑线曲柄", "挑线杆", "挑线连杆"])
    lab = {o.Name: o.Label for o in objs}
    parts, found = MM.find(objs)
    pairs = sorted(tuple(sorted((lab[c["part1"]], lab[c["part2"]]))) + (c["type"],) for c in found["candidates"])
    assert pairs == sorted([("上轴挑线曲柄", "机壳", "revolute"), ("上轴挑线曲柄", "挑线杆", "revolute"),
                            ("挑线杆", "挑线连杆", "revolute"), ("挑线连杆", "机壳", "revolute")])
    assert lab[found["ground"]["part"]] == "机壳" and found["unconnected"] == []
    draft = AM.draft(parts, found)                       # 规则草稿（不调 LLM）；人确认 = 全部采用
    joints = MT.to_assembly_joints(found, draft["accept"])
    asm = MM.build_assembly(doc, objs, draft["ground"], joints)
    mat = Materials.MaterialManager().getMaterial(STEEL)
    for o in objs:
        o.ShapeMaterial = mat
    doc.recompute()
    model, _ = MA.model_from_assembly(asm)
    crank = next(o.Name for o in objs if o.Label == "上轴挑线曲柄")
    lever = next(o.Name for o in objs if o.Label == "挑线杆")
    frame = next(o.Name for o in objs if o.Label == "机壳")
    drive = next(j for j in model["joints"] if {j["body_i"], j["body_j"]} == {"ground", crank})
    P, Q, M = geometry()
    model["motions"] = [{"id": "upper_shaft", "joint": drive["id"], "dof": "rotation", "speed": 60}]
    model["requests"] = [{"id": "M", "type": "point", "body": lever, "point_mm": M.tolist()}, {"id": "P", "type": "point", "body": crank, "point_mm": P.tolist()}]
    model["analysis"] = {"type": "kinematic", "end_time_s": 1.0, "output_steps": 36}
    data, _ = R.run_model(model)
    assert next(v for v in data["verification"] if v["key"] == "constraint_residual")["status"] == "pass"
    assert data["dof"] == 0
    near = M
    worst = 0.0
    for p, m in zip(data["requests"]["P"]["pos_mm"], data["requests"]["M"]["pos_mm"], strict=True):
        ref = circle_meet(np.array(p), LK["a"], Q, LK["b"], near)
        worst = max(worst, float(np.linalg.norm(np.array(m) - ref)))
        near = ref
    assert worst < 1e-6
    ang = [math.atan2(p[2], p[1]) for p in data["requests"]["P"]["pos_mm"]]
    assert max(abs(math.remainder(b - a, 2 * math.pi)) for a, b in zip(ang, ang[1:])) == pytest.approx(math.radians(10), rel=1e-6)
    assert frame not in {b["id"] for b in model["bodies"]}
    assert App.ActiveDocument is not None
