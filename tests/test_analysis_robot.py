"""整机构型初筛（analysis/robot，ADR-0115 44.1）。标准题对照解析解：平面两杆臂的工作空间（环形）、
雅可比奇异值之积 l1·l2·|sin θ2|、末端负载对肩关节的静力矩 m·g·(l1 cos θ1 + l2 cos(θ1+θ2))；龙门的逆解；结构错误。"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest

import analysis
from analysis.robot import kinematics as K
from analysis.robot import screen

FIX = Path(__file__).parent / "fixtures" / "robot-concept" / "valid"
L1, L2 = 300.0, 200.0


def two_link(points=(), tasks=(), lo=-180, hi=180):
    """平面两杆臂：绕 −Y 转（正转角抬起），杆沿 +X；末端在第二杆末端"""
    c = {"format": "robot-concept/1", "name": "两杆臂（标准题）", "kind": "serial_arm", "base": {"mount": "floor"},
            "links": [{"id": "a", "length_mm": L1, "shape": "tube"}, {"id": "b", "length_mm": L2, "shape": "tube"}],
            "joints": [{"id": "j1", "type": "revolute", "parent": "base", "child": "a", "origin_mm": [0, 0, 0],
                        "axis": [0, -1, 0], "range_deg": [lo, hi]},
                       {"id": "j2", "type": "revolute", "parent": "a", "child": "b", "origin_mm": [L1, 0, 0],
                        "axis": [0, -1, 0], "range_deg": [lo, hi]}],
            "end_effector": {"type": "none", "offset_mm": [L2, 0, 0]}, "tasks": list(tasks)}
    if points:
        c["workspace"] = {"points_mm": [list(p) for p in points]}
    return c


def test_forward_kinematics_matches_planar_formula():
    m = K.build(two_link())
    for t1, t2 in [(0, 0), (30, 45), (-60, 120), (90, -90)]:
        p = K.tool_point(m, {"j1": t1, "j2": t2})
        a, b = math.radians(t1), math.radians(t1 + t2)
        assert p == pytest.approx([L1 * math.cos(a) + L2 * math.cos(b), 0, L1 * math.sin(a) + L2 * math.sin(b)], abs=1e-9)


def test_jacobian_singular_values_product_is_l1_l2_sin():
    m = K.build(two_link())
    for t2 in (10, 45, 90, 150):
        sv = K.singular_values(m, {"j1": 20, "j2": t2})
        nz = sorted(sv)[-2:]
        assert nz[0] * nz[1] == pytest.approx(L1 * L2 * abs(math.sin(math.radians(t2))), rel=1e-9)


@pytest.mark.parametrize("r,ok", [(450, True), (150, True), (499, True), (520, False), (90, False)])
def test_workspace_is_the_annulus(r, ok):
    rep = screen(two_link(points=[(r * math.cos(0.4), 0, r * math.sin(0.4))]))
    item = next(i for i in rep["items"] if i["item"].startswith("工作空间点"))
    assert (item["status"] == "pass") is ok                       # |l1 − l2| ≤ r ≤ l1 + l2


def test_joint_range_limits_reach():
    rep = screen(two_link(points=[(0, 0, -400)], lo=0, hi=150))     # 正下方要 θ1 < 0，行程不允许
    assert rep["overall"] == "fail"


def test_payload_torque_on_shoulder_is_mgl():
    t1, t2, m_kg = 30.0, -45.0, 2.0
    rep = screen(two_link(tasks=[{"name": "停", "type": "joint_move", "from": {"j1": t1, "j2": t2},
                                  "to": {"j1": t1, "j2": t2}, "move_s": 1}]), payload_kg=m_kg)
    ref = m_kg * 9.80665 * (L1 * math.cos(math.radians(t1)) + L2 * math.cos(math.radians(t1 + t2))) / 1000
    assert rep["payload_torque_nm"]["j1"] == pytest.approx(ref, abs=1e-4)          # 结果取 4 位小数
    assert rep["payload_torque_nm"]["j2"] == pytest.approx(m_kg * 9.80665 * L2 * math.cos(math.radians(t1 + t2)) / 1000, abs=1e-4)


def test_fully_stretched_pose_is_singular():
    rep = screen(two_link(tasks=[{"name": "伸直", "type": "joint_move", "from": {"j1": 10, "j2": 0}, "to": {"j1": 40, "j2": 30},
                                  "move_s": 1}]))
    assert [i["item"] for i in rep["items"] if i["item"].startswith("奇异") and i["status"] == "fail"] == ["奇异：伸直（from）"]


def test_gantry_inverse_kinematics_is_exact():
    c = json.loads((FIX / "gantry_3axis.json").read_text(encoding="utf-8"))["instance"]
    m = K.build(c)
    q, err = K.ik(m, [500, 300, 1100])
    assert err < K.IK_TOL_MM and q["x"] == pytest.approx(500, abs=0.1) and q["y"] == pytest.approx(300, abs=0.1)
    assert q["z"] == pytest.approx(100, abs=0.1)                  # z 轴向下：1200 − 100
    rep = screen(c, payload_kg=3)
    assert rep["overall"] == "unknown" and rep["payload_torque_nm"] == {}  # 没给工作空间点；全是移动关节，没有转动关节的力矩
    assert not [i for i in rep["items"] if i["status"] == "fail"]


def test_five_axis_sample_screens_and_runs_as_module():
    c = json.loads((FIX / "serial_arm_5axis.json").read_text(encoding="utf-8"))["instance"]
    res = analysis.run("robot", {"concept": c, "payload_kg": 0.5})
    assert res["status"] == "ok"
    d = res["data"]
    assert d["overall"] in ("pass", "fail") and set(d["payload_torque_nm"]) >= {"j2", "j3"}
    assert all("item" in i and i["status"] in ("pass", "fail", "unknown") for i in d["items"])


def test_mobile_base_is_unknown_until_parts_are_chosen():
    c = json.loads((FIX / "mobile_diff_drive.json").read_text(encoding="utf-8"))["instance"]
    assert screen(c)["overall"] == "unknown"


@pytest.mark.parametrize("mut,word", [
    (lambda c: c["joints"][1].update(parent="nope"), "父件"),
    (lambda c: c["joints"][1].update(child="a"), "被 2 个关节带动"),
    (lambda c: c["joints"][0].update(axis=[0, 0, 0]), "零向量"),
    (lambda c: c["tasks"].append({"name": "超", "type": "joint_move", "from": {"j1": 200}, "to": {"j1": 0}, "move_s": 1}), "超出行程"),
    (lambda c: c["tasks"].append({"name": "无", "type": "joint_move", "from": {"j9": 0}, "to": {"j9": 0}, "move_s": 1}), "不存在"),
])
def test_structure_problems(mut, word):
    c = copy.deepcopy(two_link())
    mut(c)
    rep = screen(c)
    assert rep["overall"] == "fail" and word in rep["items"][0]["note"]


def test_bad_setup_fails_cleanly():
    assert analysis.run("robot", {})["status"] == "failed"
    assert analysis.run("robot", {"concept": two_link(), "payload_kg": -1})["status"] == "failed"
    assert np.isfinite(screen(two_link(points=[(400, 0, 0)]))["sigma_ratio_min"])
