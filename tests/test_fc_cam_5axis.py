"""问渠CAM C3b 五轴联动刀路的几何（ADR-0106 C3b）：从 FreeCAD 的面、边取直纹线、曲面接触点、边上的点和法向。"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

pytestmark = pytest.mark.freecad


def _frustum():
    """NAS 979 圆锥台（简化）：底 Ø150 在 Z −15、顶在 Z0、半锥角 15°，加一块底座"""
    import FreeCAD as App
    import Part

    rt = 75.0 - 15.0 * math.tan(math.radians(15))
    cone = Part.makeCone(75.0, rt, 15.0, App.Vector(0, 0, -15))
    return cone.fuse(Part.makeBox(200, 200, 10, App.Vector(-100, -100, -25))).removeSplitter()


def test_cone_face_rails_and_swarf():
    """圆锥面是直纹面：导轨两端在 Z −15 / Z0；swarf 刀位到直纹线的距离 = 刀具半径、在锥面外侧（按面外法向）"""
    from analysis.cam import fiveaxis as FA
    from freecad_addon.fc import cam_5axis as C5

    s = _frustum()
    face = next(f for f in s.Faces if f.Surface.__class__.__name__ == "Cone")
    bot, top, nrm = C5.ruled_rails(face, 72)
    assert np.allclose(bot[:, 2], -15.0, atol=1e-6) and np.allclose(top[:, 2], 0.0, atol=1e-6)
    tips, axes = FA.swarf(bot, top, 5.0, normals=nrm)
    for p, a, b in zip(tips, axes, bot):
        assert np.linalg.norm(np.cross(p - b, a)) == pytest.approx(5.0, abs=1e-6)
        assert math.hypot(p[0], p[1]) > math.hypot(b[0], b[1])
        assert FA.angle_deg(a, [0, 0, 1]) == pytest.approx(15.0, abs=1e-6)


def test_non_ruled_face_refused():
    import Part

    from freecad_addon.fc import cam_5axis as C5

    sph = Part.makeSphere(30.0)
    with pytest.raises(C5.Cam5AxisError, match="不是直纹面"):
        C5.ruled_rails(sph.Faces[0])


def test_sphere_rows_contacts_and_normals():
    """球冠面：接触点都在球面上、法向沿半径朝外；行距、点距按弧长取"""
    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_5axis as C5

    sph = Part.makeSphere(60.0, App.Vector(0, 0, -60), App.Vector(0, 0, 1), 70, 90, 360)
    face = sph.Faces[0]
    rows = C5.surface_rows(face, stepover=2.0, step=1.0)
    assert len(rows) >= 10
    for pts, nrm in rows:
        r = pts - [0, 0, -60]
        assert np.allclose(np.linalg.norm(r, axis=1), 60.0, atol=1e-6)
        assert np.allclose(nrm, r / 60.0, atol=1e-6)
        assert float(np.max(np.linalg.norm(np.diff(pts, axis=0), axis=1))) <= 1.0 + 0.05


def test_edge_points_on_cylinder():
    """圆柱顶边：点在 R40 圆上，法向取圆柱面外法向（沿半径）"""
    import Part

    from freecad_addon.fc import cam_5axis as C5

    cyl = Part.makeCylinder(40.0, 20.0)
    face = next(f for f in cyl.Faces if f.Surface.__class__.__name__ == "Cylinder")
    edge = next(e for e in face.Edges if e.Curve.__class__.__name__ == "Circle" and abs(e.Vertexes[0].Point.z - 20.0) < 1e-9)
    pts, nrm = C5.edge_points(edge, face, 2.0)
    assert np.allclose(np.linalg.norm(pts[:, :2], axis=1), 40.0, atol=1e-6)
    assert np.allclose(nrm[:, :2] * 40.0, pts[:, :2], atol=1e-6) and np.allclose(nrm[:, 2], 0.0, atol=1e-9)


# ---------------------------------------------------------------- 加工树里的五轴工序（ADR-0106 C3d）
def _job(doc, shape, machine="EX-5AX-AC"):
    import json

    from freecad_addon.fc import cam_objects as CO

    m = doc.addObject("Part::Feature", "Part")
    m.Shape = shape
    doc.recompute()
    job = CO.new_job(doc, m, "mill", machine=machine, post="fanuc")
    job.ToolLengths = json.dumps({"EM10": 120, "BN6": 110})
    return m, job


def _face(m, cls):
    return next(f"Face{i + 1}" for i, f in enumerate(m.Shape.Faces) if f.Surface.__class__.__name__ == cls)


def test_swarf_op_on_cone_to_rtcp_program():
    """带底座的圆锥台：点锥面建五轴侧刃铣（刃长 22 盖住 15.5 长的直纹线，挑 EM10），出 G43.4 程序；刀路线框带刀轴短线"""
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    doc = App.newDocument("c3dswarf")
    try:
        m, job = _job(doc, _frustum())
        op = P.FiveOpCommand("swarf5").run(m, [_face(m, "Cone")])
        assert op.OpKind == "swarf5" and op.ToolId == "EM10" and op.Below == 0.0
        mv = json.loads(op.Moves)
        assert all(len(x["axis"]) == 3 for x in mv if x["t"] in ("rapid", "feed"))
        sh = CO.path_shape(op)
        assert len(sh.Edges) > len([x for x in mv if x["t"] in ("rapid", "feed")]) - 1        # 加了刀轴短线
        CO.confirm(op)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert "G43.4" in p["release"]["text"] and "G49" in p["release"]["text"]
    finally:
        App.closeDocument(doc.Name)


def _cap_block():
    """60 × 60 × 20 的块，顶上一个球冠（球半径 60，冠高 5）"""
    import FreeCAD as App
    import Part

    box = Part.makeBox(60, 60, 20)
    sph = Part.makeSphere(60.0, App.Vector(30, 30, -35))
    cap = sph.common(Part.makeBox(60, 60, 5, App.Vector(0, 0, 20)))
    return box.fuse(cap).removeSplitter()


def test_surface_op_on_cap_no_overcut():
    """方块上的球冠：点球面建五轴曲面精加工（球头刀 BN6，前倾 10°），出程序，三维比对不过切"""
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    doc = App.newDocument("c3dsurf")
    try:
        m, job = _job(doc, _cap_block())
        op = P.FiveOpCommand("surface5").run(m, [_face(m, "Sphere")])
        assert op.ToolId == "BN6" and op.Lead == 10.0 and op.AvoidCollision
        if not op.Moves:                                     # BN6 没有切削参数：填上再重算
            op.Vc, op.Feed = 150.0, 0.04
            CO.regenerate(op)
        assert "刀柄外形" in op.Reason                       # BN6 没写刀柄外形：这部分碰撞没查，写进理由
        CO.confirm(op)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not any("过切" in c["text"] for c in p["checks"] if c["level"] == "error")
    finally:
        App.closeDocument(doc.Name)


def test_curve_op_on_boss_edge():
    """块上 Ø30 凸台的顶边：五轴沿曲线，刀轴取边旁边朝上的面（凸台顶面）的法向 = 竖直"""
    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    doc = App.newDocument("c3dcurve")
    try:
        shape = Part.makeBox(60, 60, 20).fuse(Part.makeCylinder(15, 10, App.Vector(30, 30, 20))).removeSplitter()
        m = _job(doc, shape)[0]
        e = next(f"Edge{i + 1}" for i, ed in enumerate(m.Shape.Edges)
                 if ed.Curve.__class__.__name__ == "Circle" and abs(ed.Vertexes[0].Point.z - 30) < 1e-9)
        op = P.FiveOpCommand("curve5").run(m, [e])
        if not op.Moves:
            op.Vc, op.Feed = 150.0, 0.04
            CO.regenerate(op)
        feeds = [x for x in json.loads(op.Moves) if x["t"] == "feed"]
        assert feeds and all(abs(x["axis"][2] - 1.0) < 1e-6 for x in feeds)
        assert all(abs(x["z"] - (-0.2)) < 1e-6 for x in feeds if x["z"] < 0)                # 沿边进 0.2（Z0 在凸台顶面）
    finally:
        App.closeDocument(doc.Name)


def test_five_op_needs_rotary_machine():
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    doc = App.newDocument("c3d3ax")
    try:
        m = _job(doc, _frustum(), machine="EX-VMC")[0]
        with pytest.raises(CO.CamObjError, match="没有回转轴"):
            P.FiveOpCommand("swarf5").run(m, [_face(m, "Cone")])
    finally:
        App.closeDocument(doc.Name)
