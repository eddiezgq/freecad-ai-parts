"""问渠CAM 回放与色差（ADR-0106 Q2 第 5、6 步）：回放窗口、程序窗口联动、拖到撞刀那一帧、三维比对与色差图。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.freecad
EX = Path(__file__).resolve().parents[1] / "examples" / "wenquest-cam"


def _ex():
    sys.path.insert(0, str(EX))
    import build_examples as B

    return B


def _mill_job(doc, profile=False):
    from freecad_addon.fc import cam_objects as CO

    m = doc.addObject("Part::Feature", "Block")
    m.Shape = _ex().block()
    doc.recompute()
    job = CO.new_job(doc, m, "mill")
    job.ToolLengths = json.dumps({"EM10": 120, "DR8.5": 140})
    job.Fixture = "10"
    CO.draft(job)
    s = CO.setups(job)[0]
    if profile:
        CO.add_op(s, "profile")
    for o in CO.ops(s):
        CO.confirm(o)
    return m, job


def test_mill_deviation_against_model_is_clean_for_example():
    """入门例子 2：程序按 dexel 切完与零件模型比，没有过切；整机仿真通过的程序照常出"""
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO

    doc = App.newDocument("camdev")
    try:
        _m, job = _mill_job(doc)
        r = CO.calculate(job)
        p = r["data"]["programs"][0]
        assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
        assert not [c for c in p["checks"] if c["level"] == "error"]
        rep = json.loads(job.Replay)
        assert rep and rep[0]["replay_in"]["kind"] == "mill" and rep[0]["gcode"]
    finally:
        App.closeDocument(doc.Name)


def test_mill_deviation_finds_known_overcut():
    """零件是 60×40×20 的块、顶面开 5 深的槽；程序（外来刀路）把槽铣到 5.3 深：三维比对查出过切 0.30（± 半格）"""
    import FreeCAD as App
    import Part

    from analysis.cam import machines
    from analysis.cam import replay as R
    from freecad_addon.fc import cam_deviation as CD

    blk = Part.makeBox(60, 40, 20, App.Vector(0, 0, -20))
    slot = Part.makeBox(40, 10, 5, App.Vector(10, 15, -5))
    part = blk.cut(slot)
    lines = ["%", "O1", "G90 G21 G17", "T1 M6", "S3000 M3", "G0 X15 Y20 Z5", "G1 Z-5.3 F200", "G1 X45 F600", "G0 Z5", "M30", "%"]
    text = "\n".join(lines)
    rin = {"kind": "mill", "stock": {"box": [0, 0, 60, 40], "top": 0.0, "height": 20}, "tools": {"1": {"kind": "endmill", "d": 10}}}
    rp = R.Replay(text, machines.get("EX-VMC"), rin, h=0.25)
    res = CD.mill_deviation(rp, part, 0.0)
    assert res["over"] and res["over_max"] == pytest.approx(0.30, abs=0.125)
    _v, t, dev = res["mesh"]
    assert len(dev) == len(t) and dev.min() == pytest.approx(-0.30, abs=0.01)


@pytest.fixture(scope="module")
def gui():
    import os

    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def test_replay_dock_follows_program_and_clash(gui):
    """铣外轮廓撞平口钳：回放窗口里事件标在撞的那一行；点事件 → 程序窗口高亮那一行、视图里刀尖在那一段的终点；
    点程序的另一行 → 跳到那一段；点视图里的刀路 → 跳到最近的一段；拖到最后看色差"""
    import FreeCAD as App
    import FreeCADGui

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_tree_panels as P

    P.register()
    doc = App.newDocument("camreplay")
    try:
        _m, job = _mill_job(doc, profile=True)
        CO.calculate(job)
        doc.recompute()
        FreeCADGui.ActiveDocument.ActiveView.viewIsometric()
        jp = P.JobPanel(job)
        assert jp.replay.isEnabled()
        dock = jp.open_replay()
        gui.processEvents()
        assert dock.rp is not None and dock.rp.events
        ev = next(e for e in dock.rp.events if "平口钳" in e["text"] or "夹具" in e["text"])
        dock.events.setCurrentRow(dock.rp.events.index(ev))
        dock._event_clicked(dock.events.item(dock.rp.events.index(ev)))
        gui.processEvents()
        assert dock.current_line == ev["line"]
        f = dock.rp.frames[ev["i"]]
        tip = dock.tool_position()
        exp = dock._to_model(*dock.rp.tip(ev["i"], 1.0))
        assert all(abs(a - b) < 1e-3 for a, b in zip(tip, exp, strict=True))      # Coin 存单精度
        assert f["line"] == ev["line"]
        # 点程序窗口的一行
        target = next(fr for fr in dock.rp.frames if fr["line"] != ev["line"] and not fr["home"] and fr["i"] > 3)
        cur = dock.code.textCursor()
        cur.setPosition(dock.code.document().findBlockByNumber(target["line"] - 1).position())
        dock.code.setTextCursor(cur)
        gui.processEvents()
        assert dock.current_line == target["line"]
        # 点视图里的刀路：一段的中点
        mid = [(a + b) / 2 for a, b in zip(dock._to_model(*dock.rp.tip(target["i"], 0.0)),
                                           dock._to_model(*dock.rp.tip(target["i"], 1.0)), strict=True)]
        j = dock.pick(mid)
        assert j is not None
        # 在制毛坯有网格；拖到最后、切到色差
        assert dock._last_mesh and dock._last_mesh[1] > 0
        dock.dev.setChecked(True)
        gui.processEvents()
        assert "色差" in dock.legend.text() or "deviation" in dock.legend.text().lower()
        dock.close()
    finally:
        App.closeDocument(doc.Name)


def test_turn_replay_and_deviation(gui):
    import FreeCAD as App

    from freecad_addon.fc import cam_objects as CO
    from freecad_addon.gui import cam_replay

    doc = App.newDocument("camreplayturn")
    try:
        m = doc.addObject("Part::Feature", "Shaft")
        m.Shape = _ex().shaft()
        doc.recompute()
        job = CO.new_job(doc, m, "turn", threads="0, -26, 24, 1.5")
        CO.draft(job)
        for s in CO.setups(job):
            for o in CO.ops(s):
                CO.confirm(o)
        CO.calculate(job)
        dock = cam_replay.open_for(job)
        gui.processEvents()
        assert dock.rp.lathe and dock._last_mesh[1] > 0
        dock.seek(dock.rp.duration)
        res = dock.deviation()
        assert res["over_max"] < 0.02
        dock.prog.setCurrentIndex(1)                              # 调头装夹
        gui.processEvents()
        assert dock.side == "left" and dock.rp.frames
        dock.close()
    finally:
        App.closeDocument(doc.Name)
