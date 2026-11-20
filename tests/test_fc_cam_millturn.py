"""问渠CAM C2b 车铣作业（ADR-0106 C2b 界面）：车削作业的机床选车铣中心，点端面槽底、键槽底加动力刀工序；
计算时车削之后接动力刀铣削，出 G12.1 / G7.1 程序（后处理配置写了车铣 M 代码）；去料体积与解析值差 < 1%。"""

from __future__ import annotations

import json
import math

import pytest

pytestmark = pytest.mark.freecad


def _shaft():
    """Ø40 × 30 + Ø50 × 40 的阶梯轴（右端 Z0）；右端面长圆槽（圆心 (±10, 0)、宽 6、深 3）；Ø50 上 +Y 方向键槽（宽 6、深 3、圆心 z −10、−30）"""
    import FreeCAD as App
    import Part

    v = App.Vector
    shaft = Part.makeCylinder(25, 40, v(0, 0, -40)).fuse(Part.makeCylinder(20, 30, v(0, 0, -70)))
    slot = Part.makeBox(20, 6, 3, v(-10, -3, -3)).fuse(Part.makeCylinder(3, 3, v(-10, 0, -3))).fuse(Part.makeCylinder(3, 3, v(10, 0, -3)))
    kw = Part.makeBox(6, 10, 20, v(-3, 22, -30)).fuse(Part.makeCylinder(3, 10, v(0, 22, -10), v(0, 1, 0))).fuse(
        Part.makeCylinder(3, 10, v(0, 22, -30), v(0, 1, 0)))
    return shaft.cut(slot).cut(kw).removeSplitter()


def _keyway_volume(r=25.0, r_bot=22.0, w=6.0, L=20.0, n=4000):
    h = w / n
    return sum((math.sqrt(r * r - x * x) - r_bot) * (L + 2 * math.sqrt(w * w / 4 - x * x)) * h
               for x in (-w / 2 + (i + 0.5) * h for i in range(n)))


def test_mill_turn_job_face_slot_and_keyway(tmp_path, monkeypatch):
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    d = tmp_path / "posts"
    d.mkdir()
    (d / "mt.json").write_text(json.dumps({"format": "cam-post/1", "id": "mt", "name": "FANUC mill-turn", "family": "fanuc", "kinds": ["lathe"],
                                           "source": "测试", "millturn": {"live_on": ["M13"], "live_off": ["M15"], "c_on": ["M18"],
                                                                        "c_off": ["M19"]}}), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))
    doc = App.newDocument("mt")
    try:
        part = _shaft()
        m = doc.addObject("Part::Feature", "Shaft")
        m.Shape = part
        doc.recompute()

        def plane(pred):
            return next(f"Face{i + 1}" for i, f in enumerate(part.Faces) if type(f.Surface).__name__ == "Plane" and pred(f))

        s_face = plane(lambda f: f.normalAt(0, 0).z > 0.99 and abs(f.BoundBox.ZMin + 3) < 1e-6)
        s_kw = plane(lambda f: f.normalAt(0, 0).y > 0.99 and abs(f.BoundBox.YMin - 22) < 1e-6)
        job = CO.new_job(doc, m, "turn", machine="EX-MT-CY", post="mt")
        assert json.loads(job.PartData)["segments"] == [[40.0, 30.0], [50.0, 40.0]]   # 槽、键槽不影响车削轮廓
        CO.draft(job)                                              # 车削工序按规则起草（粗车、精车）
        right, left = CO.setups(job)
        a = CO.add_live_op(right, "live_face", s_face)
        b = CO.add_live_op(right, "live_keyway", s_kw)
        assert json.loads(a.HoleData)["feature"] == {"type": "slot", "a": [-10.0, 0.0], "b": [10.0, 0.0], "width": 6.0, "z0": 0.0, "depth": 3.0}
        assert json.loads(b.HoleData)["feature"] == {"type": "keyway", "angle": 90.0, "width": 6.0, "za": -10.0, "zb": -30.0,
                                                     "r_outer": 25.0, "depth": 3.0}
        assert a.ToolId == b.ToolId == "EM6" and a.ToolNumber == b.ToolNumber
        with pytest.raises(CO.CamObjError, match="不朝左端"):           # 右端面上的槽不能放进调头装夹
            CO.add_live_op(left, "live_face", s_face)
        job.ToolLengths = json.dumps({"EM6": 40})
        for s in (right, left):
            for o in CO.ops(s):
                CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        exact = 3 * (20 * 6 + math.pi * 9) + _keyway_volume()
        assert p["sim"]["mill_removed_mm3"] == pytest.approx(exact, rel=0.01)
        t = p["release"]["text"]
        assert "G12.1" in t and "G07.1 C25.0" in t and "M13" in t
        assert any(k.startswith("O1002") for k in json.loads(job.Programs))
        # 普通车床上不能加动力刀工序
        job.Machine = "EX-LATHE"
        with pytest.raises(CO.CamObjError, match="车铣中心"):
            CO.add_live_op(right, "live_face", s_face)
    finally:
        App.closeDocument(doc.Name)


def test_mill_turn_live_ops_on_flipped_setup(tmp_path, monkeypatch):
    """调头装夹（左端）的动力刀工序：左端面长圆槽（模型圆心 (±5, 5)、宽 6、深 3）、Ø40 上 +X 方向键槽（宽 6、深 3、模型圆心 z −50、−60）。
    调头绕 Y 轴转 180°：x → −x、z → z_left − z；键槽角度 180°；体积与解析值差 < 1%"""
    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_objects as CO

    d = tmp_path / "posts"
    d.mkdir()
    (d / "mt.json").write_text(json.dumps({"format": "cam-post/1", "id": "mt", "name": "FANUC mill-turn", "family": "fanuc", "kinds": ["lathe"],
                                           "source": "测试", "millturn": {"live_on": ["M13"], "live_off": ["M15"], "c_on": ["M18"],
                                                                        "c_off": ["M19"]}}), encoding="utf-8")
    monkeypatch.setenv("FAP_POSTS", str(d))
    v = App.Vector
    shaft = Part.makeCylinder(25, 40, v(0, 0, -40)).fuse(Part.makeCylinder(20, 30, v(0, 0, -70)))
    slot = Part.makeBox(10, 6, 3, v(-5, 2, -70)).fuse(Part.makeCylinder(3, 3, v(-5, 5, -70))).fuse(Part.makeCylinder(3, 3, v(5, 5, -70)))
    kw = Part.makeBox(10, 6, 10, v(17, -3, -60)).fuse(Part.makeCylinder(3, 10, v(17, 0, -50), v(1, 0, 0))).fuse(
        Part.makeCylinder(3, 10, v(17, 0, -60), v(1, 0, 0)))
    part = shaft.cut(slot).cut(kw).removeSplitter()
    doc = App.newDocument("mtl")
    try:
        m = doc.addObject("Part::Feature", "Shaft")
        m.Shape = part
        doc.recompute()

        def plane(pred):
            return next(f"Face{i + 1}" for i, f in enumerate(part.Faces) if type(f.Surface).__name__ == "Plane" and pred(f))

        s_face = plane(lambda f: f.normalAt(0, 0).z < -0.99 and abs(f.BoundBox.ZMax + 67) < 1e-6)
        s_kw = plane(lambda f: f.normalAt(0, 0).x > 0.99 and abs(f.BoundBox.XMin - 17) < 1e-6)
        job = CO.new_job(doc, m, "turn", machine="EX-MT-CY", post="mt")
        CO.draft(job)
        right, left = CO.setups(job)
        assert CO.live_side(job, s_face, "live_face") == CO.live_side(job, s_kw, "live_keyway") == "left"
        a = CO.add_live_op(left, "live_face", s_face)
        b = CO.add_live_op(left, "live_keyway", s_kw)
        assert json.loads(a.HoleData)["feature"] == {"type": "slot", "a": [-5.0, 5.0], "b": [5.0, 5.0], "width": 6.0, "z0": 0.0, "depth": 3.0}
        assert json.loads(b.HoleData)["feature"] == {"type": "keyway", "angle": 180.0, "width": 6.0, "za": -10.0, "zb": -20.0,
                                                     "r_outer": 20.0, "depth": 3.0}
        with pytest.raises(CO.CamObjError, match="不朝右端"):
            CO.add_live_op(right, "live_face", s_face)
        job.ToolLengths = json.dumps({"EM6": 40})
        for s in (right, left):
            for o in CO.ops(s):
                CO.confirm(o)
        r = CO.calculate(job)
        p = next(p for p in r["data"]["programs"] if p["side"] == "left")
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        exact = 3 * (10 * 6 + math.pi * 9) + _keyway_volume(r=20.0, r_bot=17.0, L=10.0)
        assert p["sim"]["mill_removed_mm3"] == pytest.approx(exact, rel=0.01)
        assert "G12.1" in p["release"]["text"] and "G07.1 C20.0" in p["release"]["text"]
    finally:
        App.closeDocument(doc.Name)
