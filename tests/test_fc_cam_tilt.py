"""问渠CAM C2a 3+2 倾斜面在加工树里（ADR-0106 C2a）：点零件上的斜面建倾斜面装夹，装夹里加面铣、型腔，
刀路在平面坐标里由 FreeCAD 算（真实毛坯转到平面坐标里当毛坯），计算后出 G68.2 程序；去除体积与解析值、三维比对不过切。"""

from __future__ import annotations

import json
import math

import pytest

pytestmark = pytest.mark.freecad


def _chamfer_block():
    """100 × 60 × 40 的块，后上棱 20 × 20 的 45° 斜面；斜面中间铣一个 30 × 16 深 4 的型腔"""
    import FreeCAD as App
    import Part

    prof = Part.makePolygon([App.Vector(0, 0, 0), App.Vector(0, 60, 0), App.Vector(0, 60, 20), App.Vector(0, 40, 40), App.Vector(0, 0, 40),
                             App.Vector(0, 0, 0)])
    part = Part.Face(prof).extrude(App.Vector(100, 0, 0))
    f = next(f for f in part.Faces if abs(f.normalAt(0, 0).z - math.sqrt(0.5)) < 1e-6)
    pk = Part.makeBox(30, 16, 4, App.Vector(-15, -8, -4))
    pk.Placement = App.Placement(f.CenterOfMass, App.Rotation(App.Vector(0, 0, 1), f.normalAt(0, 0)))
    return part.cut(pk).removeSplitter()


def test_tilted_setup_face_and_pocket_to_g68_2():
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    doc = App.newDocument("camtilt")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = _chamfer_block()
        doc.recompute()
        slope = next(f"Face{i + 1}" for i, f in enumerate(m.Shape.Faces)
                     if abs(f.normalAt(0, 0).z - math.sqrt(0.5)) < 1e-6 and f.Area > 1000)
        top = next(f"Face{i + 1}" for i, f in enumerate(m.Shape.Faces) if abs(f.normalAt(0, 0).z - 1) < 1e-6)
        cmd = P.TiltSetupCommand()
        with pytest.raises(CO.CamObjError, match="先给这个零件建铣削作业"):
            cmd.run(m, slope)
        job = CO.new_job(doc, m, "mill", machine="EX-5AX-AC", post="fanuc")
        job.ToolLengths = json.dumps({"EM10": 120, "EM6": 110})
        with pytest.raises(CO.CamObjError, match="朝上"):
            cmd.run(m, top)
        s = cmd.run(m, slope)
        fr = json.loads(s.Frame)
        assert fr["z"] == pytest.approx([0, math.sqrt(0.5), math.sqrt(0.5)]) and fr["x"] == pytest.approx([1, 0, 0])
        fo = CO.add_op(s, "face")
        pk = CO.add_op(s, "pocket")
        assert pk.ToolId == "EM6" and json.loads(pk.Frame)["z"] == pytest.approx(fr["z"])
        for o in (fo, pk):
            CO.confirm(o)
        assert CO.path_shape(pk).BoundBox.ZMin > 20                  # 刀路线框画在斜面上（模型坐标）
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        t = p["release"]["text"]
        assert "G68.2" in t and " J45.0 " in t.replace("J45.0\n", "J45.0 \n") and t.count("G69") == 2
        # 去除体积：斜面三棱柱 ½·20·20·100 + 型腔（30 × 16 − 四角留下的 (4 − π)·3²）× 4
        exact = 0.5 * 20 * 20 * 100 + (30 * 16 - (4 - math.pi) * 9) * 4
        assert p["sim"]["removed_mm3"] == pytest.approx(exact, rel=0.01)
        assert not any("过切" in c["text"] for c in p["checks"] if c["level"] == "error")
    finally:
        App.closeDocument(doc.Name)
