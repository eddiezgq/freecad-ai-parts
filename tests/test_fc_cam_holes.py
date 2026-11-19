"""问渠CAM Q3b 孔特征识别（ADR-0106）：通孔 / 盲孔深度、沉孔、锪孔口、钻尖、按攻丝底孔推测螺纹孔。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.freecad


def hole_plate():
    """100×60×20 的板，顶面 Z20：
    A (20, 20) Ø8.5 通孔 + 90° 锪孔口到 Ø12；B (50, 20) Ø6.6 通孔 + Ø11 深 6.5 沉孔；
    C (80, 20) Ø6.8 盲孔深 15、118° 钻尖；D (50, 45) Ø9 通孔（不是底孔）"""
    import FreeCAD as App
    import Part

    V = App.Vector
    b = Part.makeBox(100, 60, 20)
    b = b.cut(Part.makeCylinder(4.25, 20, V(20, 20, 0)))
    b = b.cut(Part.makeCone(4.25, 6.0, 1.75, V(20, 20, 18.25)))
    b = b.cut(Part.makeCylinder(3.3, 20, V(50, 20, 0)))
    b = b.cut(Part.makeCylinder(5.5, 6.5, V(50, 20, 13.5)))
    tip = 3.4 / 1.6643                                     # 118° 钻尖高 = r / tan(59°)
    b = b.cut(Part.makeCylinder(3.4, 15, V(80, 20, 5)))
    b = b.cut(Part.makeCone(0.0, 3.4, tip, V(80, 20, 5 - tip)))
    b = b.cut(Part.makeCylinder(4.5, 20, V(50, 45, 0)))
    return b.removeSplitter()


def test_holes_are_recognised():
    from freecad_addon.fc import cam_doc

    hs = {(h["x"], h["y"]): h for h in cam_doc.mill_holes(hole_plate())}
    assert set(hs) == {(20, 20), (50, 20), (80, 20), (50, 45)}
    a, b, c, d = hs[(20, 20)], hs[(50, 20)], hs[(80, 20)], hs[(50, 45)]
    assert a["through"] and a["d"] == pytest.approx(8.5) and a["csink"] == {"d": pytest.approx(12.0), "angle": pytest.approx(90.0)}
    assert a["thread"] == {"d": 10.0, "pitch": 1.5, "guess": True}                    # Ø8.5 正好是 M10 底孔：推测
    assert b["through"] and b["d"] == pytest.approx(6.6) and b["cbore"] == {"d": pytest.approx(11.0), "depth": pytest.approx(6.5)}
    assert b["thread"] is None and b["z_top"] == pytest.approx(20.0)
    assert not c["through"] and c["d"] == pytest.approx(6.8) and c["z_bottom"] == pytest.approx(5.0)
    assert c["z_top"] - c["z_bottom"] == pytest.approx(15.0) and c["tip"]["angle"] == pytest.approx(118.0, abs=0.01)
    assert c["thread"] == {"d": 8.0, "pitch": 1.25, "guess": True}
    assert d["thread"] is None and d["csink"] is None and d["cbore"] is None


def test_hole_plate_model_to_program():
    """孔板从模型到程序：钻孔（各直径）→ 铣沉孔 → 锪孔口；推测的螺纹孔不自动攻丝，人确认后新建攻丝工序；
    全部确认后算：没有错误，出正式程序；攻丝工序出 G84，锪孔口锪到 Ø12 的深度 (12 − 0.5)/2 = 5.75"""
    import json

    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camholes")
    try:
        m = doc.addObject("Part::Feature", "Plate")
        m.Shape = hole_plate()
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps({k: 130 for k in ("EM6", "DR8.5", "DR6.6", "DR6.8", "DR9", "CM90", "TAP-M10", "TAP-M8")})
        d = CO.draft(job)
        s = CO.setups(job)[0]
        kinds = [o.OpKind for o in CO.ops(s)]
        assert kinds.count("drill") == 4 and kinds[-2:] == ["cbore", "csink"], kinds
        # 螺纹孔是推测的：起草不加攻丝，只在说明里提；人确认后新建“攻丝”工序（同一种螺纹的孔一道）
        assert sum("推测是螺纹孔" in n for n in d["notes"]) == 2, d["notes"]
        taps = [CO.add_op(s, "tap"), CO.add_op(s, "tap")]
        assert all(o.Check == "待确认" and "推测" in o.Reason for o in taps)
        assert sorted(json.loads(o.HoleData)["d"] for o in taps) == [8.0, 10.0]
        cs = next(o for o in CO.ops(s) if o.OpKind == "csink")
        assert next(x for x in json.loads(cs.Moves) if x["t"] == "drill")["z"] == pytest.approx(-5.75)
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        assert p["release"] is not None and "G84" in p["release"]["text"] and "M29" in p["release"]["text"]
    finally:
        App.closeDocument(doc.Name)
