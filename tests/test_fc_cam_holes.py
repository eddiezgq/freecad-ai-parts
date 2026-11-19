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
        job.ToolLengths = json.dumps({k: 130 for k in ("EM6", "DR8.5", "DR6.6", "DR6.8", "DR9", "CM90", "TAP-M10", "TAP-M8", "TM6")})
        d = CO.draft(job)
        s = CO.setups(job)[0]
        kinds = [o.OpKind for o in CO.ops(s)]
        assert kinds.count("drill") == 4 and kinds[-2:] == ["cbore", "csink"], kinds
        # 螺纹孔是推测的：起草不加攻丝，只在说明里提；人确认后新建“攻丝”工序（同一种螺纹的孔一道）
        assert sum("推测是螺纹孔" in n for n in d["notes"]) == 2, d["notes"]
        tm = CO.add_op(s, "thread_mill")                # 铣螺纹（M8：Ø6 单齿螺纹铣刀比小径 6.65 − 0.5 小；M10 同一把刀）
        assert tm.ToolId == "TM6" and "推测" in tm.Reason and json.loads(tm.HoleData)["pitch"] == pytest.approx(1.25)
        CO.confirm(tm)
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


def test_face_milling_removes_stock_allowance():
    """面铣余量 2 mm：起草第一道是面铣（分两层），算完毛坯顶面整个落到零件顶面 Z0，去除体积 = 100 × 60 × 2"""
    import json

    import FreeCAD as App
    import numpy as np
    import Part

    from analysis.cam import machines, sim
    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camface")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = Part.makeBox(100, 60, 30)
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.StockTop = 2.0
        job.ToolLengths = json.dumps({"EM10": 120})
        CO.draft(job)
        s = CO.setups(job)[0]
        assert [o.OpKind for o in CO.ops(s)] == ["face"]
        CO.confirm(CO.ops(s)[0])
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert not [c for c in p["checks"] if c["level"] == "error"], [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert p["release"] is not None
        vmc = machines.get(job.Machine)
        tools = {int(k): v for k, v in p["tools"].items()}
        res = sim.simulate_mill(sim.parse(p["gcode"], vmc), {"box": [0, 0, 100, 60], "top": 2.0}, tools)
        H = res["H"][res["inside"]]
        assert float(np.abs(H).max()) < 1e-9
    finally:
        App.closeDocument(doc.Name)


def chamfer_block():
    """100×60×20 的块，中间 40×20 深 8 的型腔；外轮廓顶边、型腔口都倒 1×45°"""
    import FreeCAD as App
    import Part

    b = Part.makeBox(100, 60, 20).cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 12)))
    return b.makeChamfer(1.0, [e for e in b.Edges if abs(e.BoundBox.ZMin - 20) < 1e-6 and abs(e.BoundBox.ZMax - 20) < 1e-6])


def test_chamfers_model_to_program():
    """顶边倒角从模型读出（8 个 1×45° 斜面），起草出“倒角”工序（90° 倒角刀）；算完三维比对不过切；
    外轮廓边上的截面：离边 x 处的顶面高度 = −(1 − x)（仿真网格 0.05，差不超过一格）"""
    import json

    import FreeCAD as App

    from freecad_addon.fc import cam_doc
    from freecad_addon.fc import cam_objects as CO

    cf = cam_doc.chamfer_faces(chamfer_block())
    assert len(cf) == 8 and all(c["width"] == pytest.approx(1.0) and c["angle"] == pytest.approx(90.0) for c in cf)
    doc = App.newDocument("camchamfer")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = chamfer_block()
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps({"EM10": 120, "EM6": 110, "CM90": 100})
        CO.draft(job)
        s = CO.setups(job)[0]
        assert [o.OpKind for o in CO.ops(s)] == ["pocket", "chamfer"]
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        assert p["release"] is not None
        import numpy as np

        from analysis.cam import machines, sim
        tools = {int(k): v for k, v in p["tools"].items()}
        res = sim.simulate_mill(sim.parse(p["gcode"], machines.get(job.Machine)), {"box": [0, 0, 100, 60], "top": 0.0}, tools, h=0.05)
        ix = int(np.argmin(np.abs(res["y"] - 30.0)))
        sel = (res["x"] > 0.05) & (res["x"] < 0.95)
        err = float(np.abs(res["H"][sel, ix] - (-(1 - res["x"][sel]))).max())
        assert err <= 0.05
    finally:
        App.closeDocument(doc.Name)


def test_adaptive_roughing_keeps_width_of_cut():
    """自适应开粗（FreeCAD Adaptive，Ø10 刀、切宽 20% = 2 mm、一层 8 mm 到底）：仿真逐段量出的切宽中位数不超过设定值、
    最宽不超过设定的 1.5 倍 + 一格（不报“切宽没保持住”；只看切到半层以上深的段）；切深 8 ≤ 样本 15，不报错；三维比对不过切"""
    import json

    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camadaptive")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = Part.makeBox(100, 60, 30).cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22)))
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps({"EM10": 120})
        s = CO.setups(job)[0]
        op = CO.add_op(s, "adaptive")
        assert op.ToolId == "EM10" and op.StepOver == pytest.approx(0.2)
        CO.confirm(op)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        a = p["sim"]["adaptive"][0]
        h = p["sim"]["cell_mm"]
        assert a["ae_set"] == pytest.approx(2.0) and a["ae_median"] <= 2.0 + h, a
        assert a["ae_max"] <= 1.5 * 2.0 + h, a
        assert not [c for c in p["checks"] if "切宽没保持住" in c["text"]]
    finally:
        App.closeDocument(doc.Name)


def test_rest_machining_cleans_corners():
    """残料清角：Ø10 开粗后，直角转角圆弧上离两壁最远的点（45° 处）离壁 R5·(1 − √2/2) ≈ 1.46；加一道“残料清角”
    （Ø6，FreeCAD 残料加工，只铣开粗留下的地方），降到 R3·(1 − √2/2) ≈ 0.88（三维比对网格误差半格）；
    残料清角的刀路比整个型腔重铣一遍短得多"""
    import itertools
    import json
    import math
    import re

    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_objects as CO

    def left(r):
        """三维比对的“多留最多”与网格"""
        t = next(c["text"] for p in r["data"]["programs"] for c in p["checks"] if "多留最多" in c["text"])
        return float(re.search(r"多留最多 ([\d.]+)", t).group(1)), float(re.search(r"网格 ([\d.]+)", t).group(1))

    doc = App.newDocument("camrest")
    try:
        m = doc.addObject("Part::Feature", "Block")
        m.Shape = Part.makeBox(100, 60, 30).cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22)))
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps({"EM10": 120, "EM6": 110})
        s = CO.setups(job)[0]
        pk = CO.add_op(s, "pocket")
        CO.confirm(pk)
        r1 = CO.calculate(job)
        rest = CO.add_op(s, "rest")
        assert rest.ToolId == "EM6"
        CO.confirm(rest)
        r2 = CO.calculate(job)
        (a1, h1), (a2, h2) = left(r1), left(r2)
        assert a1 == pytest.approx(5 * (1 - math.sqrt(2) / 2), abs=h1 / 2)
        assert a2 == pytest.approx(3 * (1 - math.sqrt(2) / 2), abs=h2 / 2)
        full = CO.add_op(s, "pocket")                  # 同样 Ø6 整个型腔重铣一遍（对照）
        full.ToolId, full.ToolNumber = "EM6", rest.ToolNumber
        CO.regenerate(full)

        def length(o):
            mv = [x for x in json.loads(o.Moves) if "x" in x]
            return sum(math.dist((a["x"], a["y"]), (b["x"], b["y"])) for a, b in itertools.pairwise(mv) if b["t"] == "feed")
        assert length(rest) < 0.5 * length(full)
    finally:
        App.closeDocument(doc.Name)


def test_pocket_allowances_and_heights():
    """铣型腔留余量：底面余量 0.5 → 型腔底在 −7.5（设计 −8）；侧壁余量 0.3 → 型腔两壁之间 40 − 0.6；
    安全高度设成毛坯顶面以上 12 → 快移最高到 Z12"""
    import FreeCAD as App
    import numpy as np
    import Part

    from analysis.cam import machines, post, sim
    from analysis.cam import tools as TL
    from freecad_addon.fc import cam_fc

    shape = Part.makeBox(100, 60, 30).cut(Part.makeBox(40, 20, 8, App.Vector(30, 20, 22)))
    em = TL.get(TL.load(), "EM10")
    spec = {"type": "pocket", "tool": em, "number": 1, "rpm": 4000, "feed_mm_min": 600, "plunge_mm_min": 200, "step_down_mm": 4,
            "allow_side": 0.3, "allow_floor": 0.5, "safe_h": 12.0, "clear_h": 15.0}
    prog, stock = cam_fc.program(shape, [spec])
    mv = prog["ops"][0]["moves"]
    assert max(m["z"] for m in mv if m["t"] == "rapid") == pytest.approx(15.0)
    vmc = machines.get("EX-VMC")
    s = sim.simulate_mill(sim.parse(post.post(prog, vmc), vmc), {"box": stock["box"], "top": 0.0}, {1: {"kind": "endmill", "d": 10.0}}, h=0.05)
    H, xs, ys = s["H"], s["x"], s["y"]
    assert float(H[np.argmin(np.abs(xs - 50)), np.argmin(np.abs(ys - 30))]) == pytest.approx(-7.5)
    j = np.argmin(np.abs(ys - 30))
    cut = xs[s["inside"][:, j] & (H[:, j] < -1)]
    assert cut.max() - cut.min() == pytest.approx(40 - 0.6, abs=0.1)


def test_surface_finishing_on_dome():
    """曲面平行精铣（R3 球头刀，残留高度 0.01 → 行距 0.49）：圆顶零件从模型到程序；三维比对不过切"""
    import json

    import FreeCAD as App
    import Part

    from freecad_addon.fc import cam_doc
    from freecad_addon.fc import cam_objects as CO

    V = App.Vector
    shape = Part.makeBox(40, 40, 15).fuse(Part.makeSphere(35, V(20, 20, -15)).common(Part.makeBox(40, 40, 30, V(0, 0, 15)))).removeSplitter()
    assert cam_doc.scallop_step(3.0) == pytest.approx(2 * (2 * 3 * 0.01 - 0.0001) ** 0.5)
    doc = App.newDocument("camsurface")
    try:
        m = doc.addObject("Part::Feature", "Dome")
        m.Shape = shape
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps({"BN6": 110})
        op = CO.add_op(CO.setups(job)[0], "surface")
        assert op.ToolId == "BN6"
        CO.confirm(op)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        assert p["release"] is not None
    finally:
        App.closeDocument(doc.Name)
