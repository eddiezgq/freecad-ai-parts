"""问渠CAM C1 第 3 步：车削补全——切槽、车螺纹（G32）、钻孔、镗孔，内外径一起仿真（ADR-0104 第 3 节 C1）。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis import cam
from analysis.cam import machines, sim
from analysis.cam import paths as P

LATHE = machines.get("EX-LATHE")
PART = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60], [35, 25], [24, 30]], "chamfer_mm": 1}
FULL = {**PART, "grooves": [{"z": -27, "width": 3, "d": 20}], "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}],
        "bore": {"segments": [[16, 20], [12, 15]], "drill_d": 10}}


def _progs(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


def test_thread_infeeds_and_iso_root():
    # ISO 965-1：M24×1.5 外螺纹小径 d3 = 24 − 1.22687 × 1.5 = 22.160
    mv = P.turn_thread(0, -26, 24, 1.5)
    th = [m for m in mv if m["t"] == "thread"]
    depth = 1.22687 * 1.5 / 2
    n = math.ceil((depth / 0.25) ** 2)                   # 第一刀不超过 0.25 mm
    assert len(th) == n + 1                               # 加一刀光刀
    assert th[-1]["x"] == pytest.approx(24 - 1.22687 * 1.5, abs=1e-9) and th[-2]["x"] == th[-1]["x"]
    a = [(24 - m["x"]) / 2 for m in th[:-1]]
    assert a[0] == pytest.approx(depth / math.sqrt(n)) and a[0] <= 0.25 + 1e-12
    # 等面积递减：a_i² 等差
    sq = np.diff(np.square(a))
    assert np.allclose(sq, sq[0])


def test_full_part_clean_and_thread_time_by_hand():
    progs = _progs(FULL)
    right = progs[0]
    assert not _errors(right), _errors(right)
    assert right["sim"]["inner_dev_min_mm"] == pytest.approx(0.0, abs=0.02)
    assert right["sim"]["inner_dev_max_mm"] == pytest.approx(0.0, abs=0.02)
    g = right["gcode"]
    assert "G32 Z-26.0 F1.5" in g and "T0404" in g and "T0505" in g and "T0606" in g
    # 车螺纹那一段用 G97 恒转速：S = 1000·60/(π·24) = 796
    seg = g.split("T0404")[1].split("T05")[0]
    assert "G97 S796 M03" in seg and "G96" not in seg
    # 车螺纹时间手算：每刀 (26 + 3) mm，每转 1.5 mm，796 r/min
    parsed = sim.parse(g, LATHE)
    sim.timing(parsed, LATHE)
    t = sum(m["dt"] for m in parsed["moves"] if m["t"] == "thread")
    passes = sum(1 for m in parsed["moves"] if m["t"] == "thread")
    assert t == pytest.approx(passes * 60 * 29 / (1.5 * 796), rel=1e-6)


def test_final_shape_has_groove_root_and_bore():
    progs = _progs(FULL)
    g = progs[0]["gcode"]
    parsed = sim.parse(g, LATHE)
    stock = {"d": 44.0, "z_right": 1.0, "z_left": -156.0}
    tools = {1: {"kind": "turn"}, 2: {"kind": "turn"}, 3: {"kind": "groove", "w": 3.0}, 4: {"kind": "thread"},
             5: {"kind": "drill", "d": 10.0}, 6: {"kind": "bore"}}
    s = sim.simulate_turn(parsed, stock, tools)
    z, r, ri = s["z"], s["r"], s["ri"]

    def at(zz):
        return int(np.argmin(np.abs(z - zz)))
    assert r[at(-28.5)] == pytest.approx(10.0, abs=0.02)                      # 槽底 Ø20
    assert r[at(-10)] == pytest.approx((24 - 1.22687 * 1.5) / 2, abs=0.02)    # 螺纹按整圈切到牙底
    assert ri[at(-10)] == pytest.approx(8.0, abs=0.02) and ri[at(-27)] == pytest.approx(6.0, abs=0.02)
    # 钻尖：Z-(35 + 5/tan59°) 以里是实心
    tip = -(35 + 5 / math.tan(math.radians(59)))
    assert ri[at(tip - 0.5)] == 0.0 and ri[at(tip + 0.5)] == pytest.approx(5.0)


def test_left_end_features_go_to_second_setup():
    # 左端 Ø30 段（零件坐标 Z-115 ~ Z-155）：靠轴肩的退刀槽、从左端面车起的螺纹，都放在调头装夹，坐标翻过来
    setup = {**PART, "grooves": [{"z": -115, "width": 4, "d": 26}],
             "threads": [{"z_start": -117, "z_end": -155, "d": 30, "pitch": 2}]}
    right, left = _progs(setup)
    assert "T0303" not in right["gcode"] and "T0303" in left["gcode"] and "T0404" in left["gcode"]
    assert not _errors(left), _errors(left)
    # 调头后：槽右边 z' = -(−115 − 4 + 155) = −36，螺纹 Z0 ~ Z-38
    assert "Z-36.0" in left["gcode"].split("T0303")[1].split("T04")[0]
    assert "G32 Z-38.0 F2.0" in left["gcode"]
    # 螺纹起刀处既不在端面也没有退刀槽：不出程序，说清楚
    r = cam.run({**PART, "threads": [{"z_start": -5, "z_end": -20, "d": 24, "pitch": 1.5}]})
    assert r["status"] == "failed" and "没有退刀槽" in r["messages"][0]
    with pytest.raises(AssertionError):
        _progs({**PART, "grooves": [{"z": -110, "width": 10, "d": 30}]})        # 跨两次装夹：报错


def test_checks_catch_thread_on_css_and_rapid_into_hole():
    g = "%\nO0001\nG21 G18 G99\nT0404\nG50 S2000\nG96 S60 M03\nG00 X28 Z3\nX23.\nG32 Z-20 F1.5\nG00 X28\nM30\n%\n"
    p = cam.run({"mode": "check", "machine": "EX-LATHE", "gcode": g})["data"]["programs"][0]
    assert any("恒线速" in e and "G97" in e for e in _errors(p))
    # 没钻孔就快移进孔里
    g2 = "%\nO0002\nG21 G18 G99\nT0606\nG97 S800 M03\nG00 X14 Z2\nZ-10.\nG00 Z2\nM30\n%\n"
    p = cam.run({"mode": "check", "machine": "EX-LATHE", "gcode": g2, "stock": {"d": 40, "z_right": 0, "z_left": -60},
                 "tools": {"6": {"kind": "bore"}}})["data"]["programs"][0]
    assert any("快移撞到工件" in e for e in _errors(p))


def test_bad_inputs():
    with pytest.raises(P.CamError):
        P.turn_bore(P.inner_profile([[16, 20]]), 18, 1, 0.1)                  # 预钻孔比内孔大
    with pytest.raises(P.CamError):
        P.turn_thread(-20, 0, 24, 1.5)                                          # 方向反了
    r = cam.run({**PART, "threads": [{"z_start": -5, "z_end": 0, "d": 24, "pitch": 1.5}]})
    assert r["status"] == "failed"
