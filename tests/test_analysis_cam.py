"""数控编程（ADR-0059，M11 第二步）：标准题与检查。不联网。

门槛：车削基本时间与手算 t = L/(f·n)、n = 1000·v_c/(π·d)（< 0.1%）；Kienzle 切削功率与手算（< 0.1%）；
生成的阶梯轴程序仿真无过切、残留 < 0.05 mm；读入 FreeCAD CAM 工作台风格的程序能算时间。
"""

from __future__ import annotations

import math

import pytest

import analysis
from analysis.cam import machines, paths, power, sim

pytest.importorskip("numpy")
LATHE = machines.get("EX-LATHE")
VMC = machines.get("EX-VMC")


def test_turning_time_matches_hand_formula():
    # 一刀纵车 L = 100 mm，f = 0.2 mm/r：G97 定转速 1000 rpm 与 G96 恒线速（d = 40 时 n = 1000）都应为 0.5 min
    hand_s = 100 / (0.2 * 1000) * 60
    assert paths.basic_time_min(100, 1, math.pi * 40, 40, 0.2) * 60 == pytest.approx(hand_s, rel=1e-12)
    for spindle in ("G97 S1000 M03", f"G50 S3000\nG96 S{math.pi * 40:.6f} M03"):
        g = f"G21 G18 G99\nT0101\n{spindle}\nG00 X40.0 Z2.0\nG01 Z0.0 F0.2\nZ-100.0\nG00 X50.0\nM30\n"
        p = sim.parse(g, LATHE)
        cut = sum(sim.move_time(m, LATHE, True) for m in p["moves"] if m["t"] == "feed" and m["a"][2] == 0.0)
        assert cut == pytest.approx(hand_s, rel=1e-3), spindle


def test_kienzle_power_matches_hand_calc():
    r = power.row("C45E")
    assert (r["kc11_mpa"], r["mc"]) == (2220, 0.14) and r["source"]
    # 车削：F_c = 2220·2·0.3^0.86 = 1576.6 N，P = F_c·120/60000 = 3.153 kW（手算）
    assert power.turning_kw(2220, 0.14, 2.0, 0.3, 120) == pytest.approx(3.1533, rel=1e-3)
    # 钻孔：h = 0.06，k_c = 2220·0.06^−0.14 = 3292 MPa，P = 0.12·10·3292·20/240000 = 0.3292 kW
    assert power.drilling_kw(2220, 0.14, 0.12, 10, 20) == pytest.approx(0.3292, rel=1e-3)
    # 表的自洽：s1 原表 h = 0.4 列 2520 与 k_c1.1·0.4^−m_c = 2524 相差 < 1%
    assert 2220 * 0.4 ** -0.14 == pytest.approx(2520, rel=0.01)
    # 功率不够时报错，没选材料行时待确认
    items = [("粗车", "turn", {"vc": 200, "f": 0.6, "ap": 6})]
    assert power.check("C45E", LATHE, items)[0][0]["level"] == "error"
    assert power.check(None, LATHE, items)[0][0]["level"] == "unknown"


def test_stepped_shaft_program_is_clean():
    r = analysis.run("cam", {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60], [35, 25], [30, 30]],
                             "chamfer_mm": 1, "kienzle": "C45E", "item": "测试轴"})
    assert r["status"] == "ok", r["messages"]
    d = r["data"]
    assert [p["side"] for p in d["programs"]] == ["right", "left"] and d["verdict"] == "ok"
    for p in d["programs"]:
        assert p["checks"] == []
        assert p["sim"]["dev_min_mm"] > -0.01 and p["sim"]["under_mm"] < 0.05
        assert p["sim"]["ap_max_mm"]["rough"] <= 2.5 + 1e-6
        assert "G50 S3000" in p["gcode"] and p["gcode"].startswith("%\nO100")
    assert d["programs"][0]["sim"]["reach_mm"] + d["programs"][1]["sim"]["reach_mm"] == pytest.approx(155)
    assert any("示例机床" in m for m in r["messages"])


def test_milling_features_and_residuals():
    feats = [{"type": "contour", "rect": [0, 0, 100, 60], "corner_r": 5, "depth": 10},
             {"type": "pocket", "rect": [20, 15, 60, 45], "corner_r": 6, "depth": 5},
             {"type": "slot", "a": [75, 20], "b": [75, 45], "width": 8, "depth": 4},
             {"type": "holes", "d": 6.6, "points": [[8, 8], [92, 8], [92, 52], [8, 52]], "depth": 12}]
    r = analysis.run("cam", {"mode": "mill", "machine": "EX-VMC", "kienzle": "MD22", "stock": {"box": [-5, -5, 105, 65]},
                             "features": feats})
    p = r["data"]["programs"][0]
    assert r["data"]["verdict"] == "ok" and p["sim"]["over_cells"] == 0 and p["sim"]["under_cells"] == 0
    assert p["tools"]["2"]["d"] == 12 and "G81" in p["gcode"]  # 型腔取不大于 2×圆角的最大标准刀；浅孔一次钻到底
    # 尖角型腔：转角留料要报出来
    sharp = analysis.run("cam", {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 60, 40]},
                                 "features": [{"type": "pocket", "rect": [10, 10, 50, 30], "depth": 3}]})
    texts = [c["text"] for c in sharp["data"]["programs"][0]["checks"]]
    assert any(t.startswith("残留") for t in texts) and any("待确认" in t for t in texts)
    assert sharp["data"]["verdict"] == "warn"
    bad = analysis.run("cam", {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 60, 40]},
                               "features": [{"type": "slot", "a": [5, 5], "b": [30, 5], "width": 6, "depth": 2, "tool_d": 8}]})
    assert bad["status"] == "failed" and "槽宽" in bad["messages"][0]


FREECAD_STYLE = """(Exported by FreeCAD)
(Post Processor: linuxcnc_post)
G17 G54 G40 G49 G80 G90
G21
(begin operation: Profile)
N10 M6 T1
G43 H1
M3 S5000
G0 Z15.000
G0 X0.000 Y0.000
G1 Z-1.000 F300.000
G1 X50.000 Y0.000 F300.000
G2 X50.000 Y0.000 I0.000 J10.000 F300.000
G0 Z15.000
M5
M2
"""


def test_check_reads_freecad_cam_program():
    r = analysis.run("cam", {"mode": "check", "machine": "EX-VMC", "gcode": FREECAD_STYLE})
    assert r["status"] == "ok", r["messages"]
    p = r["data"]["programs"][0]
    hand = (16 + 50 + 2 * math.pi * 10) / 300 * 60  # Z15 下刀到 Z−1 共 16 mm + 直线 50 mm + 整圆 R10，F300 mm/min
    assert p["time"]["cut_s"] == pytest.approx(hand, rel=1e-3)
    assert p["tools_used"] == [1] and r["data"]["verdict"] == "ok"
    # 给毛坯与刀具就仿真：快移撞料、超程、没开主轴都能报
    crash = "G21 G90 G94\nT1 M06\nS3000 M03\nG00 X0 Y0 Z5\nG00 Z-3\nG01 X500 F200\nM30\n"
    r2 = analysis.run("cam", {"mode": "check", "machine": "EX-VMC", "gcode": crash, "stock": {"box": [-20, -20, 20, 20]},
                              "tools": {"1": {"kind": "endmill", "d": 10}}})
    texts = [c["text"] for c in r2["data"]["programs"][0]["checks"]]
    assert any("快移撞到工件" in t for t in texts) and any("超程" in t for t in texts)
    nospin = analysis.run("cam", {"mode": "check", "machine": "EX-VMC", "gcode": "G90 G94\nG01 X10 F100\n"})
    assert any("主轴没有转" in c["text"] for c in nospin["data"]["programs"][0]["checks"])
    assert analysis.run("cam", {"mode": "check", "machine": "EX-VMC", "gcode": ""})["status"] == "failed"


def test_machines_file(tmp_path):
    f = tmp_path / "machines.yaml"
    f.write_text("machines:\n  - {id: EX-LATHE, kind: lathe, name: 我的车床, max_rpm: 2500, power_kw: 7.5, eff: 0.85,\n"
                 "     x: [0, 300], z: [-500, 200], rapid: {x: 8000, z: 10000}, home: [150, 100], tool_change_s: 2}\n",
                 encoding="utf-8")
    env = {"FAP_MACHINES": str(f)}
    m = machines.get("EX-LATHE", env)
    assert m["name"] == "我的车床" and m["example"] is False
    assert {x["id"] for x in machines.all_machines(env)} == {"EX-LATHE", "EX-VMC"}
    f.write_text("machines:\n  - {id: X, kind: mill, name: 缺参数}\n", encoding="utf-8")
    with pytest.raises(machines.MachineError):
        machines.all_machines(env)
    r = analysis.run("cam", {"mode": "turn", "machine": "EX-VMC", "segments": [[20, 10]]})
    assert r["status"] == "failed" and "不是车床" in r["messages"][0]


def test_window_input_parsing():
    from freecad_addon.core import cam_input

    feats = cam_input.parse_features("外轮廓 0 0 100 60 5 10\n# 注释\n型腔 20,15,60,45,6,5\n槽 75 20 75 45 8 4\n孔 6.6 12 8 8 92 8")
    assert [f["type"] for f in feats] == ["contour", "pocket", "slot", "holes"]
    assert feats[3]["points"] == [[8, 8], [92, 8]] and feats[1]["rect"] == [20, 15, 60, 45]
    for bad in ("圆 1 2 3", "型腔 1 2 3", "孔 6 12 8", "外轮廓 a b c d e f", ""):
        with pytest.raises(cam_input.InputError):
            cam_input.parse_features(bad)
    assert cam_input.parse_box("-5 -5 105 65") == [-5, -5, 105, 65]
    with pytest.raises(cam_input.InputError):
        cam_input.parse_box("0 0 -1 5")
    assert cam_input.summary({"status": "failed", "messages": ["x"]}) == "没有算出：x"
