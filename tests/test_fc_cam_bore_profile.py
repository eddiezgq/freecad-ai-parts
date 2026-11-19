"""内孔仿形（ADR-0106 Q3a）：带孔口倒角、锥面的内孔，从模型截面读出内轮廓，按轮廓镗，不报残留、过切。"""

from __future__ import annotations

import itertools

import pytest

pytestmark = pytest.mark.freecad


def _bush():
    """Ø40×30 的套，右端开孔：孔口 1×45° 倒角（Ø22 → Ø20）、Ø20 深 15、锥面 Ø20 → Ø16（长 5）、Ø16 到深 26，平底"""
    import FreeCAD as App
    import Part

    V = App.Vector
    pts = [(0, 0), (20, 0), (20, 30), (11, 30), (10, 29), (10, 15), (8, 10), (8, 4), (0, 4)]
    poly = Part.makePolygon([V(x, 0, z) for x, z in pts] + [V(0, 0, 0)])
    return Part.Face(poly).revolve(V(0, 0, 0), V(0, 0, 1), 360)


def test_bore_profile_from_section():
    from freecad_addon.fc import cam_doc

    ft = cam_doc.turn_features(_bush())
    prof = ft["bore_profile"]
    assert prof[0] == pytest.approx([0.0, 22.0], abs=1e-3)
    assert prof[1] == pytest.approx([-1.0, 20.0], abs=1e-3)
    assert [-15.0, 20.0] == pytest.approx(prof[2], abs=1e-3)
    assert [-20.0, 16.0] == pytest.approx(prof[3], abs=1e-3)
    assert prof[-1] == pytest.approx([-26.0, 16.0], abs=1e-3)


def test_bore_profile_job_runs_clean():
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("cambore")
    try:
        m = doc.addObject("Part::Feature", "Bush")
        m.Shape = _bush()
        doc.recompute()
        job = CO.new_job(doc, m, "turn")
        CO.draft(job)
        for s in CO.setups(job):
            for o in CO.ops(s):
                CO.confirm(o)
        r = CO.calculate(job)
        errs = [c["text"] for p in r["data"]["programs"] for c in p["checks"] if c["level"] == "error"]
        assert not [e for e in errs if "内孔" in e or "过切" in e or "残留" in e], errs
        bore = next(o for s in CO.setups(job) for o in CO.ops(s) if o.OpKind == "bore")
        import json

        mv = json.loads(bore.Moves)
        # 锥面那一段：精镗走斜线（X 与 Z 一起变）
        assert any(m["t"] == "feed" and abs(m["x"] - 20 + 0.8) < 0.5 for m in mv)
        sl = [(a, b) for a, b in itertools.pairwise(mv) if b["t"] == "feed" and abs(b["x"] - a["x"]) > 1 and abs(b["z"] - a["z"]) > 1]
        assert sl
    finally:
        App.closeDocument(doc.Name)
