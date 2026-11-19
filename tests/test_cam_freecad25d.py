"""问渠CAM C1 第 8 步：2.5 轴铣用 FreeCAD CAM 出刀路，换成中间格式后走同一套仿真、整机仿真、后处理（ADR-0104）。"""

from __future__ import annotations

import pytest

from analysis import cam
from analysis.cam import machines, sim
from analysis.cam import tools as TL

LIB = TL.load()
VMC = machines.get("EX-VMC")


def test_program_mode_validates_input():
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": {"ops": [{"tool": {"n": 1}, "moves": []}]},
                 "stock": {"box": [0, 0, 10, 10]}})
    assert r["status"] == "failed" and "刀径" in r["messages"][0]
    bad = {"ops": [{"tool": {"n": 1, "d": 10}, "spindle": {"rpm": 3000}, "moves": [{"t": "feed", "x": 0, "y": 0, "z": -1}]}]}
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": bad, "stock": {"box": [0, 0, 10, 10]}})
    assert r["status"] == "failed" and "缺 f" in r["messages"][0]


def test_program_mode_hand_written_path():
    prog = {"number": 6001, "title": "手写", "ops": [{"tool": {"n": 1, "d": 10.0, "kind": "endmill"}, "spindle": {"rpm": 4000},
            "safe": 5.0, "moves": [{"t": "rapid", "x": 30, "y": 30, "z": 5}, {"t": "feed", "x": 30, "y": 30, "z": -4, "f": 200},
                                   {"t": "feed", "x": 70, "y": 30, "z": -4, "f": 600}, {"t": "rapid", "x": 70, "y": 30, "z": 5}]}]}
    r = cam.run({"mode": "program", "machine": "EX-VMC", "program": prog, "stock": {"box": [0, 0, 100, 60], "height": 40},
                 "machine_sim": {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}, "post": "fanuc"})
    p = r["data"]["programs"][0]
    assert p["machine_sim"]["status"] == "pass" and p["release"] is not None
    assert p["time"]["cut_s"] == pytest.approx(60 * (9 / 200 + 40 / 600), rel=1e-6)


@pytest.mark.freecad
def test_freecad_cam_pocket_profile_drill_end_to_end():
    import FreeCAD
    import Part

    from freecad_addon.fc import cam_fc

    blk = Part.makeBox(100, 60, 30)
    shape = blk.cut(Part.makeBox(40, 20, 8, FreeCAD.Vector(30, 20, 22))).cut(Part.makeCylinder(4.25, 30, FreeCAD.Vector(10, 10, 0)))
    em, dr = TL.get(LIB, "EM10"), TL.get(LIB, "DR8.5")
    ops = [{"type": "pocket", "tool": em, "number": 1, "rpm": 4000, "feed_mm_min": 600, "plunge_mm_min": 200, "step_down_mm": 4},
           {"type": "profile", "tool": em, "number": 1, "rpm": 4000, "feed_mm_min": 600, "plunge_mm_min": 200, "step_down_mm": 10},
           {"type": "drill", "tool": dr, "number": 2, "rpm": 2200, "feed_mm_min": 300}]
    prog, stock = cam_fc.program(shape, ops)
    assert [o["tool"]["n"] for o in prog["ops"]] == [1, 1, 2] and stock["height"] == pytest.approx(30)
    # 外轮廓的圆角（G2 / G3）拆成直线段：转角处离零件角点正好一个刀具半径
    prof = [m for m in prog["ops"][1]["moves"] if m["t"] == "feed"]
    import math
    near = min(math.hypot(m["x"] - 100, m["y"] - 60) for m in prof if m["x"] > 100 and m["y"] > 60)
    assert near == pytest.approx(5.0, abs=1e-6)
    assert any(m["t"] == "drill" for m in prog["ops"][2]["moves"])
    setup = {"mode": "program", "machine": "EX-VMC", "program": prog, "stock": stock, "post": "siemens",
             "machine_sim": {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120},
                                                                     "2": {"tool": "DR8.5", "length_mm": 140}}}}
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    p = r["data"]["programs"][0]
    assert p["release"] is not None, [c["text"] for c in p["checks"] if c["level"] == "error"]
    # 仿真结果：型腔底在 Z-8，孔打穿（Z-30）
    s = sim.simulate_mill(sim.parse(p["gcode"], VMC), {"box": stock["box"], "top": 0.0},
                          {1: {"kind": "endmill", "d": 10.0}, 2: {"kind": "drill", "d": 8.5}})
    import numpy as np

    def h_at(x, y):
        return float(s["H"][int(np.argmin(np.abs(s["x"] - x))), int(np.argmin(np.abs(s["y"] - y)))])
    assert h_at(50, 30) == pytest.approx(-8.0, abs=1e-6) and h_at(10, 10) <= -30 + 1e-6 and h_at(5, 50) == 0.0
