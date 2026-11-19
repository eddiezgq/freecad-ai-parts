"""典型车削件 5 件（ADR-0106 Q3a 验收）：从模型到正式程序不用手填——外圆、倒角、退刀槽、锥面、端面槽、内孔仿形都从模型读出，
规则起草、全部确认、计算，两次装夹都出正式程序，检查清单里没有错误。"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.freecad


def _rev(pts):
    """XZ 半平面上的轮廓（x ≥ 0，沿轴线 Z）绕 Z 轴转一圈"""
    import FreeCAD as App
    import Part

    V = App.Vector
    poly = Part.makePolygon([V(x, 0, z) for x, z in pts] + [V(pts[0][0], 0, pts[0][1])])
    return Part.Face(poly).revolve(V(0, 0, 0), V(0, 0, 1), 360)


PARTS = {
    # 1 阶梯轴：Ø30×40、Ø40×60，右端 1×45° 倒角，Ø30 段右端 4 宽、底径 Ø26 的退刀槽
    "stepped_shaft": [(0, 0), (15, 0), (15, 36), (13, 36), (13, 40), (20, 40), (20, 99), (19, 100), (0, 100)],
    # 2 套：Ø40×30，孔口倒角、Ø20、锥面到 Ø16、平底
    "bush": [(0, 0), (20, 0), (20, 30), (11, 30), (10, 29), (10, 15), (8, 10), (8, 4), (0, 4)],
    # 3 法兰：左边 Ø40×20 的轴颈，右边 Ø80×12 的法兰盘；右端面 Ø50 ~ Ø62、深 4 的端面槽
    "flange": [(0, 0), (20, 0), (20, 20), (40, 20), (40, 32), (31, 32), (31, 28), (25, 28), (25, 32), (0, 32)],
    # 4 锥面轴：Ø40×30，再 1:… 锥面 Ø40 → Ø28（长 20），Ø28×25，右端 1.5×45°，左端 0.5×45°
    "taper_shaft": [(0, 0), (19.5, 0), (20, 0.5), (20, 30), (14, 50), (14, 73.5), (12.5, 75), (0, 75)],
    # 5 接头：外圆 Ø50×25 + 锥面 + Ø36×20；右端端面槽 Ø40? 不——内孔：孔口倒角、Ø24、锥面到 Ø18，深 30
    "fitting": [(0, 0), (25, 0), (25, 25), (18, 35), (18, 55), (13, 55), (12, 54), (12, 40), (9, 35), (9, 25), (0, 25)],
}


@pytest.mark.parametrize("name", list(PARTS))
def test_model_to_program_without_typing(name):
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument(f"part_{name}")
    try:
        m = doc.addObject("Part::Feature", name)
        m.Shape = _rev(PARTS[name])
        doc.recompute()
        job = CO.new_job(doc, m, "turn", post="fanuc")
        CO.draft(job)
        kinds = sorted({o.OpKind for s in CO.setups(job) for o in CO.ops(s)})
        for s in CO.setups(job):
            for o in CO.ops(s):
                CO.confirm(o)
        r = CO.calculate(job)
        progs = r["data"]["programs"]
        errs = [(p["title"], c["text"]) for p in progs for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        assert progs and all(p.get("release") for p in progs), [p["title"] for p in progs if not p.get("release")]
        expect = {"stepped_shaft": {"groove"}, "bush": {"bore"}, "flange": {"face_groove"}, "taper_shaft": {"finish"},
                  "fitting": {"bore"}}[name]
        assert expect <= set(kinds), kinds
    finally:
        App.closeDocument(doc.Name)
