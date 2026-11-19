"""典型铣削件 5 件（ADR-0106 Q3b 验收）：从模型到正式程序不用手填——型腔、沉孔、锪孔口、倒角、孔都从模型读出，
规则起草；推测的螺纹孔由人确认后点“新建工序”（攻丝或铣螺纹），不填数；全部确认后算：没有错误（含三维比对不过切），出正式程序。"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.freecad

LENGTHS = {k: 130 for k in ("EM10", "EM6", "DR8.5", "DR6.6", "DR6.8", "DR9", "DR10", "CM90", "TAP-M10", "TAP-M8", "TM6")}


def plate():
    """1 带沉孔、螺纹孔的板 120×80×15：四角 Ø6.6 通孔 + Ø11 深 6.5 沉孔（M6 内六角螺钉），中间两个 Ø8.5 通孔（M10 螺纹底孔）"""
    import FreeCAD as App
    import Part

    V = App.Vector
    b = Part.makeBox(120, 80, 15)
    for x, y in ((12, 12), (108, 12), (12, 68), (108, 68)):
        b = b.cut(Part.makeCylinder(3.3, 15, V(x, y, 0))).cut(Part.makeCylinder(5.5, 6.5, V(x, y, 8.5)))
    for x in (45, 75):
        b = b.cut(Part.makeCylinder(4.25, 15, V(x, 40, 0)))
    return b.removeSplitter()


def housing():
    """2 多型腔壳体 140×90×30：大型腔 80×50 深 12、小型腔 30×20 深 6（在大型腔外），各自圆角 R6"""
    import FreeCAD as App
    import Part

    V = App.Vector

    def pocket(x, y, w, h, d, r):                 # 竖边倒圆角 r 的长方体，挖掉就是带圆角的型腔
        box = Part.makeBox(w, h, d, V(x, y, 30 - d))
        return box.makeFillet(r, [e for e in box.Edges if abs(e.BoundBox.ZLength - d) < 1e-6])

    b = Part.makeBox(140, 90, 30).cut(pocket(10, 20, 80, 50, 12, 6.0)).cut(pocket(100, 35, 30, 20, 6, 6.0))
    return b.removeSplitter()


def flange():
    """3 带倒角的法兰盘 Ø120×16：顶边 1×45° 倒角；Ø100 分布圆上 6 个 Ø9 通孔，孔口 90° 锪到 Ø13"""
    import math

    import FreeCAD as App
    import Part

    V = App.Vector
    d = Part.makeCylinder(60, 16, V(60, 60, 0))
    d = d.makeChamfer(1.0, [e for e in d.Edges if abs(e.BoundBox.ZMin - 16) < 1e-6])
    for k in range(6):
        x, y = 60 + 50 * math.cos(k * math.pi / 3), 60 + 50 * math.sin(k * math.pi / 3)
        d = d.cut(Part.makeCylinder(4.5, 16, V(x, y, 0))).cut(Part.makeCone(4.5, 6.5, 2.0, V(x, y, 14)))
    return d.removeSplitter()


def thread_block():
    """4 铣螺纹孔的块 80×60×25：中间 Ø17.5 通孔（M20×2.5 底孔，没有这个直径的钻头 → 螺旋铣孔），再铣 M20 螺纹"""
    import FreeCAD as App
    import Part

    return Part.makeBox(80, 60, 25).cut(Part.makeCylinder(8.75, 25, App.Vector(40, 30, 0))).removeSplitter()


def open_slot():
    """5 开放槽 100×60×20：沿 Y 贯通的 22 宽、8 深的槽"""
    import FreeCAD as App
    import Part

    return Part.makeBox(100, 60, 20).cut(Part.makeBox(22, 60, 8, App.Vector(39, 0, 12))).removeSplitter()


PARTS = {"plate": (plate, {"cbore", "drill"}, ["tap"]), "housing": (housing, {"pocket"}, []),
         "flange": (flange, {"chamfer", "csink", "drill"}, []), "thread_block": (thread_block, {"helix"}, ["thread_mill"]),
         "open_slot": (open_slot, {"pocket"}, [])}


@pytest.mark.parametrize("name", list(PARTS))
def test_model_to_program_without_typing(name):
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    make, expect, confirm = PARTS[name]
    doc = App.newDocument(f"mill_{name}")
    try:
        m = doc.addObject("Part::Feature", name)
        m.Shape = make()
        doc.recompute()
        job = CO.new_job(doc, m, "mill", post="fanuc")
        job.ToolLengths = json.dumps(LENGTHS)
        d = CO.draft(job)
        s = CO.setups(job)[0]
        for kind in confirm:                      # 推测的螺纹孔：人确认后新建工序（不填数）
            CO.add_op(s, kind)
        kinds = {o.OpKind for o in CO.ops(s)}
        assert expect <= kinds, (kinds, d["notes"])
        for o in CO.ops(s):
            CO.confirm(o)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        errs = [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not errs, errs
        assert p.get("release"), [c["text"] for c in p["checks"]]
    finally:
        App.closeDocument(doc.Name)
