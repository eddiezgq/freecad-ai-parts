"""典型车削件 6 件（ADR-0106 Q3a 验收）：从模型到正式程序不用手填——外圆、倒角、退刀槽、锥面、端面槽、内孔仿形都从模型读出
（螺纹只填螺纹表一行），规则起草、全部确认、计算，两次装夹都出正式程序，检查清单里没有错误。"""

from __future__ import annotations

import json

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
    # 5 锥螺纹接头：外圆 Ø50×25 + 锥面 + R1 管螺纹段（基面大径 Ø33.249）×20；内孔：孔口倒角、Ø24、锥面到 Ø18，深 30
    "fitting": [(0, 0), (25, 0), (25, 25), (16.6245, 35), (16.6245, 55), (13, 55), (12, 54), (12, 40), (9, 35), (9, 25), (0, 25)],
    # 6 双头螺杆：Ø30×40 + Ø24×40，右端 1×45°；Tr 式双头 M24×3
    "two_start_screw": [(0, 0), (15, 0), (15, 40), (12, 40), (12, 79), (11, 80), (0, 80)],
}
# 螺纹在 FreeCAD 零件上一般不画，是车削唯一要手填的一行（作业面板“螺纹”）
THREADS = {"fitting": "0, -15, 33.249, 2.309, R", "two_start_screw": "0, -30, 24, 3, 2 头"}


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
        if name in THREADS:
            d = json.loads(job.PartData)
            d["threads"] = CO.parse_threads(THREADS[name])
            job.PartData = json.dumps(d, ensure_ascii=False)
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
                  "fitting": {"bore", "thread"}, "two_start_screw": {"thread"}}[name]
        assert expect <= set(kinds), kinds
    finally:
        App.closeDocument(doc.Name)
