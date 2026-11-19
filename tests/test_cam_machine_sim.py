"""问渠CAM C1 第 2 步：整机仿真（ADR-0104 第 2、4 节）——凸体碰撞、刀具 / 刀柄 / 机床部件 / 夹具 / 剩余材料、程序扣下、指纹。"""

from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from analysis import cam
from analysis.cam import collide as CL
from analysis.cam import kinematics as K
from analysis.cam import machine_sim as MS
from analysis.cam import machines

MILL = {"mode": "mill", "machine": "EX-VMC", "stock": {"box": [0, 0, 100, 60], "height": 40},
        "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8, "tool_d": 10}]}
OK = {"work_offset_mm": [0, 0, 40], "tools": {"1": {"tool": "EM10", "length_mm": 120}}}


def _run(setup):
    r = cam.run(setup)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["programs"][0]


def _errors(p):
    return [c["text"] for c in p["checks"] if c["level"] == "error"]


# ---------------- 凸体碰撞（GJK）与精确判据对照 ----------------

def _sat(a: CL.Box, b: CL.Box) -> bool:
    """两个斜放长方体的分离轴定理（15 根轴），精确判据"""
    axes = [a.R[:, i] for i in range(3)] + [b.R[:, i] for i in range(3)] + \
        [np.cross(a.R[:, i], b.R[:, j]) for i in range(3) for j in range(3)]
    for L in axes:
        n = np.linalg.norm(L)
        if n < 1e-9:
            continue
        L = L / n
        if abs((b.c - a.c) @ L) > np.abs(a.R.T @ L) @ a.h + np.abs(b.R.T @ L) @ b.h:
            return False
    return True


def test_gjk_matches_separating_axis_for_random_boxes():
    rng = np.random.default_rng(7)
    for _ in range(3000):
        a = CL.Box(rng.uniform(-2, 2, 3), K.rot(rng.normal(size=3), rng.uniform(0, 360)), rng.uniform(0.2, 1, 3))
        b = CL.Box(rng.uniform(-2, 2, 3), K.rot(rng.normal(size=3), rng.uniform(0, 360)), rng.uniform(0.2, 1, 3))
        assert CL.hit(a, b) == _sat(a, b)


def test_gjk_by_hand_with_margin():
    a = CL.Box.from_minmax([0, 0, 0, 10, 10, 10])
    b = CL.Box.from_minmax([10.5, 0, 0, 20, 10, 10])
    assert not CL.hit(a, b) and CL.hit(a, b, margin=0.6) and not CL.hit(a, b, margin=0.4)
    # 圆柱轴线在 x = 15、半径 4：离长方体 1 mm
    c = CL.Cylinder(np.array([15.0, 5, 0]), np.array([15.0, 5, 10]), 4.0)
    assert not CL.hit(a, c) and CL.hit(a, c, margin=1.01) and not CL.hit(a, c, margin=0.99)
    # 圆柱斜着插进角上
    d = CL.Cylinder(np.array([12.0, 12, 12]), np.array([9.0, 9, 9]), 0.5)
    assert CL.hit(a, d)
    assert CL.shape({"mesh": "x.stl"}) is None


# ---------------- 整机仿真 ----------------

def test_clean_program_passes_and_has_fingerprint():
    p = _run({**MILL, "machine_sim": OK})
    assert p["machine_sim"]["status"] == "pass" and p["gcode"] and len(p["machine_sim"]["fingerprint"]) == 16
    assert p["machine_sim"]["samples"] > 100
    # 指纹：同样的输入一样；改刀长、夹具、程序都会变
    p2 = _run({**MILL, "machine_sim": copy.deepcopy(OK)})
    assert p2["machine_sim"]["fingerprint"] == p["machine_sim"]["fingerprint"]
    p3 = _run({**MILL, "machine_sim": {**OK, "tools": {"1": {"tool": "EM10", "length_mm": 121}}}})
    assert p3["machine_sim"]["fingerprint"] != p["machine_sim"]["fingerprint"]


def test_clamp_in_the_way_withholds_program():
    p = _run({**MILL, "machine_sim": {**OK, "fixtures": [{"id": "clamp", "name": "压板", "box_mm": [25, 10, 0, 35, 25, 12]}]}})
    assert p["machine_sim"]["status"] == "error" and p["gcode"] is None
    errs = _errors(p)
    assert any("刀具刃部碰到夹具“压板”" in e and "同样的问题共" in e for e in errs)
    assert any("程序没有输出" in e for e in errs)
    assert sum("压板" in e and "刃部" in e for e in errs) == 1          # 同一对只报一条


def test_cutter_into_table_and_overtravel():
    # 工件零点只比工作台高 5 mm，型腔 8 mm 深：刀切进工作台
    p = _run({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, 5]}})
    assert any("刀具刃部碰到机床的工作台" in e for e in _errors(p))
    # 刀太短：Z 轴到底也够不着
    p = _run({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, 0], "tools": {"1": {"tool": "EM10", "length_mm": 50}}}})
    assert any("机床走不到" in e and "超程" in e for e in _errors(p)) and p["gcode"] is None


def test_holder_hits_remaining_material_in_deep_pocket():
    deep = {**MILL, "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 38, "tool_d": 10}]}
    p = _run({**deep, "machine_sim": OK})
    errs = [e for e in _errors(p) if e.startswith("刀柄碰到工件")]
    assert len(errs) == 1 and "加长伸出或换刀" in errs[0]
    # 浅一点（刀柄底面在 35 mm，型腔 30 mm 深）就没事
    ok = {**MILL, "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 30, "tool_d": 10}]}
    assert not [e for e in _errors(_run({**ok, "machine_sim": OK})) if "刀柄" in e]


def test_spindle_head_hits_stock(tmp_path):
    """没有刀柄外形的短刀：主轴头直接压到毛坯上"""
    lib = {"format": "cam-tool/1", "name": "测试", "example": True,
           "tools": [{"id": "STUB10", "number": 1, "kind": "flat_endmill", "diameter_mm": 10.0, "flute_length_mm": 4.0,
                      "source": {"kind": "example", "ref": "测试"}}]}
    f = tmp_path / "lib.json"
    f.write_text(json.dumps(lib, ensure_ascii=False), encoding="utf-8")
    # 刀长 5：Z 到底时刀尖在机床 z = 95，工件零点抬到 110（毛坯 70–110 放在垫块上）才够得着
    p = _run({**MILL, "machine_sim": {**OK, "work_offset_mm": [0, 0, 110], "tool_library": str(f),
                                      "tools": {"1": {"tool": "STUB10", "length_mm": 5}}}})
    errs = _errors(p)
    assert any("机床的主轴头碰到毛坯" in e for e in errs)
    assert any("没写刀柄外形" in c["text"] for c in p["checks"] if c["level"] == "unknown")


def test_missing_data_is_unknown_not_pass():
    p = _run({**MILL, "machine_sim": {**OK, "tools": {"1": {"tool": "EM10"}}}})
    assert p["machine_sim"]["status"] == "unknown" and p["gcode"]
    p = _run({**MILL, "machine_sim": {"work_offset_mm": [0, 0, 40]}})
    assert p["machine_sim"]["status"] == "unknown" and any("没对应到刀具库" in c["text"] for c in p["checks"])
    # 程序按 Ø12 算、刀具库对应的是 Ø10：报错
    p = _run({**MILL, "features": [dict(MILL["features"][0], tool_d=12)], "machine_sim": OK})
    assert any("程序按 Ø12 算" in e for e in _errors(p))


def test_check_mode_reports_but_keeps_program():
    g = "%\nO0001\nG21 G17 G90\nT1 M06\nS3000 M03\nG00 X30 Y20 Z5\nG01 Z-10 F200\nX70\nG00 Z50\nM30\n%\n"
    setup = {"mode": "check", "machine": "EX-VMC", "gcode": g, "stock": {"box": [0, 0, 100, 60]},
             "tools": {"1": {"kind": "endmill", "d": 10}},
             "machine_sim": {**OK, "fixtures": [{"id": "stop", "name": "定位块", "box_mm": [45, 15, -20, 55, 25, 10]}]}}
    p = _run(setup)
    assert p["gcode"] == g and any("定位块" in e for e in _errors(p))


def test_lathe_tip_into_chuck_jaw():
    setup = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60]], "chamfer_mm": 1,
             "machine_sim": {"tools": {"1": {"tool": "TR-CNMG"}, "2": {"tool": "TR-CNMG"}},
                             "fixtures": [{"id": "jaw", "name": "卡爪", "cylinder_mm": {"p0": [0, 0, -140], "p1": [0, 0, -30], "r": 30}}]}}
    r = cam.run(setup)
    progs = r["data"]["programs"]
    assert any("卡爪" in e for p in progs for e in _errors(p))
    assert any(p["gcode"] is None for p in progs)
    assert any("刀头外形各家不同" in c["text"] for p in progs for c in p["checks"])   # Q2：刀杆按 ISO 5608 查了，刀头仍是未知


def test_component_poses_follow_axis_chain():
    """部件跟着它的轴动：摇篮 A = -90° 时，摇篮长方体绕 A 轴（过 z = -100）转"""
    ac = machines.model("EX-5AX-AC")
    T = MS._prefix_pose(ac, "A", {"A": -90, "C": 30, "X": 50})
    assert np.allclose(T[:3, :3], K.rot([1, 0, 0], -90)) and np.allclose(T[:3, 3], [0, 100, -100])
    # C 上的转台还要再转 C
    T2 = MS._prefix_pose(ac, "C", {"A": 0, "C": 90})
    assert np.allclose(T2[:3, :3], K.rot([0, 0, 1], 90))
    # 主轴头跟整条刀具链：X 50 → 平移 50
    assert np.allclose(MS._prefix_pose(ac, "spindle", {"X": 50})[:3, 3], [50, 0, 0])
    with pytest.raises(MS.SimSetupError):
        MS._prefix_pose(ac, "Q", {})
