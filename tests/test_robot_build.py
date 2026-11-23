"""整机：构型 → 载荷 → 选件（analysis/robot/mjcf.py、assist/robot_build.py，ADR-0115 44.3）。

标准题：杆件质量 = 截面 × 长度 × 密度；水平伸直的两杆臂，肩部重力矩 = Σ m·g·x（手算）；吊装重力反向。
"""

from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path

import pytest

if os.environ.get("CI"):
    import mujoco  # noqa: F401 — CI 中必须装（ADR-0056）
else:
    pytest.importorskip("mujoco")

import analysis
from analysis.robot import kinematics as K
from analysis.robot import mjcf
from assist import robot_build as RB

G = 9.81                    # analysis.mbd 的重力加速度
CASE_A = Path(__file__).parents[1] / "examples" / "robots" / "teaching-arm" / "out" / "concept-result.json"


def two_link(mount="table"):
    """j1 竖轴；j2、j3 绕 y；上臂 300、前臂 200（铝管 Ø40/34、Ø30/24）；工具点在前臂末端"""
    tube = {"shape": "tube", "material": "6061-T6"}
    return {"format": "robot-concept/1", "name": "两杆臂", "kind": "serial_arm", "base": {"mount": mount},
            "links": [dict(tube, id="turret", length_mm=50, section={"od_mm": 60, "id_mm": 50}),
                      dict(tube, id="upper", length_mm=300, section={"od_mm": 40, "id_mm": 34}),
                      dict(tube, id="fore", length_mm=200, section={"od_mm": 30, "id_mm": 24})],
            "joints": [{"id": "j1", "type": "revolute", "parent": "base", "child": "turret", "origin_mm": [0, 0, 0],
                        "axis": [0, 0, 1], "range_deg": [-170, 170]},
                       {"id": "j2", "type": "revolute", "parent": "turret", "child": "upper", "origin_mm": [0, 0, 50],
                        "axis": [0, 1, 0], "range_deg": [-10, 120]},
                       {"id": "j3", "type": "revolute", "parent": "upper", "child": "fore", "origin_mm": [0, 0, 300],
                        "axis": [0, 1, 0], "range_deg": [-130, 130]}],
            "end_effector": {"type": "gripper", "parent": "fore", "offset_mm": [0, 0, 200]}}


def test_link_mass_is_section_times_length_times_density():
    c = two_link()
    m, probs = mjcf.link_masses(c)
    assert not probs
    assert m["upper"] == pytest.approx(math.pi / 4 * (40 ** 2 - 34 ** 2) * 300 * 2700e-9, rel=1e-9)
    box = {"id": "b", "shape": "box", "length_mm": 100, "material": "6061-T6",
           "section": {"width_mm": 20, "height_mm": 30, "wall_mm": 2}}
    assert mjcf.link_mass_kg(box) == pytest.approx((20 * 30 - 16 * 26) * 100 * 2700e-9)
    assert mjcf.link_mass_kg({"id": "p", "shape": "profile", "length_mm": 100, "material": "6061-T6",
                              "section": {"width_mm": 20, "height_mm": 20}}) is None      # 型材截面积要看样本：不估
    assert mjcf.link_mass_kg({"id": "t", "shape": "tube", "length_mm": 100, "section": {"od_mm": 20}}) is None  # 没材料


def test_missing_link_mass_is_an_error_not_a_guess():
    c = two_link()
    c["links"][1]["material"] = "unobtainium"
    with pytest.raises(K.ConceptError, match="upper"):
        mjcf.mjcf(c)


def _gravity(c, q, mods=None, payload=0.0):
    xml = mjcf.mjcf(c, module_masses_kg=mods, payload_kg=payload)
    drives = [{"joint": j, "kind": "hold"} for j in ("j1", "j2", "j3")]
    r = analysis.run("mbd", {"model": {"kind": "mjcf", "xml": xml}, "duration_s": 0.01, "initial": q, "drives": drives})
    assert r["status"] == "ok", r.get("error")
    return r["data"]["static"]["gravity_torque_nm"]


def test_horizontal_arm_gravity_torque_matches_hand_calculation():
    c = two_link()
    lm, _ = mjcf.link_masses(c)
    mods, payload = {"j3": 0.8}, 0.5
    g = _gravity(c, {"j2": 90}, mods, payload)                    # j2 = 90°：上臂、前臂沿 +x 水平伸直
    hand = G * (lm["upper"] * 0.150 + lm["fore"] * 0.400 + 0.8 * 0.300 + payload * 0.500)
    assert abs(g["j2"]) == pytest.approx(hand, rel=1e-6)
    assert abs(g["j3"]) == pytest.approx(G * (lm["fore"] * 0.100 + payload * 0.200), rel=1e-6)
    assert g["j1"] == pytest.approx(0.0, abs=1e-9)
    up = _gravity(two_link("ceiling"), {"j2": 90}, mods, payload)  # 吊装：重力反向，力矩反号
    assert up["j2"] == pytest.approx(-g["j2"], rel=1e-9)


def test_wall_mount_and_mobile_base_are_not_modelled():
    with pytest.raises(K.ConceptError, match="判不了"):
        mjcf.mjcf(two_link("wall"))


def test_stretched_pose_and_duty():
    c = two_link()
    _q, p = RB.stretched_pose(c)
    assert p[0] == pytest.approx(500, abs=1.0) and p[2] == pytest.approx(50)
    dt = RB.duty(c)
    d = {x["joint"]: x for x in dt["drives"]}
    assert d["j1"]["to"] == pytest.approx(90)
    assert d["j2"]["to"] == pytest.approx(dt["initial"]["j2"] - 90)          # +90 会超出 120° 的行程：往另一侧转
    for x in dt["drives"]:
        j = next(j for j in c["joints"] if j["id"] == x["joint"])
        assert j["range_deg"][0] <= x["to"] <= j["range_deg"][1]


def test_group_requirement_takes_the_max_in_group():
    res = {"data": {"drives": [
        {"joint": "a", "unit_force": "N·m", "peak": 5.0, "rms": 1.0, "speed_max": 30.0, "inertia_max_kgm2": 0.01},
        {"joint": "b", "unit_force": "N·m", "peak": 3.0, "rms": 2.0, "speed_max": 10.0, "inertia_max_kgm2": 0.02}]}}
    r = RB.group_requirement(res, ["a", "b"], RB.BASE_REQ)
    assert (r["output_torque_peak_nm"], r["output_torque_cont_nm"], r["output_speed_rpm"], r["load_inertia_kgm2"]) == (5, 2, 30, 0.02)
    assert "a、b" in r["statement"]


def test_case_a_builds_from_the_requirement():
    """案例 A（需求：60°/s、±1 mm，项目负责人 2026-11-22 定）：检验动作按需求的关节最高角速度；选一体化模组，比伺服链轻得多；
    重复定位在臂展点上算、满足 ±1 mm；连续力矩判待确认（厂商没给连续额定）"""
    cr = json.loads(CASE_A.read_text(encoding="utf-8"))
    cond = cr["conditions"]
    move_s = RB.move_s_for(cond["joint_speed"])
    assert move_s == pytest.approx(2.0)                                  # 60°/s：每 90° 用 2 s（加减速各 25%）
    out = RB.build(copy.deepcopy(cr["chosen"]), cond["payload"], move_s=move_s, repeatability_mm=cond["repeatability"],
                   points_mm=[[cond["reach"], 0.0, 0.0]])
    assert out["status"] == "pass", out.get("note")
    assert 2 <= len(out["rounds"]) <= RB.MAX_ROUNDS
    assert out["rounds"][-1]["picks"] == out["rounds"][-2]["picks"]
    (_g, p), = out["picks"].items()
    assert p["joints"] == ["j1", "j2", "j3", "j4", "j5"] and p["report"]["overall"] != "fail"
    d = {x["joint"]: x for x in out["rounds"][-1]["drives"]}
    assert p["requirement"]["output_torque_peak_nm"] == pytest.approx(max(x["peak"] for x in d.values()), rel=1e-3)
    assert max(x["speed_max"] for x in d.values()) == pytest.approx(10.0, rel=0.02)
    assert p["chain"] == "smart" and set(p["options"]) == {"servo", "smart"}
    assert p["module_mass_kg"] < p["options"]["servo"]["module_mass_kg"] / 4
    s2 = next(c for c in p["report"]["checks"] if c["check"] == "S2")
    assert s2["status"] == "unknown" and any("S2" in x for x in out["open_items"])
    r = out["repeatability"]
    assert r["status"] == "pass" and r["worst_mm"] <= cond["repeatability"] and "350" in r["pose"]
    lk = out["links"]
    assert lk["overall"] == "pass" and lk["dynamic_factor"] >= 1.0
    st = out["rounds"][-1]["static"]["gravity_torque_nm"]
    upper = next(i for i in lk["items"] if i["item"] == "杆件 upper_arm")
    assert upper["bending_nm"] == pytest.approx(abs(st["j2"]), rel=1e-3)          # 杆件根部弯矩 = 多体动力学的肩部静重力矩
    ft = out["fit"]                                                    # 腕部共线轴转用 X540 装不上（ADR-0115 44.3 之二第 3 步）
    assert ft["overall"] == "fail" and {x["joint"]: x for x in ft["joints"]}["j5"]["status"] == "fail"
    assert out["cost"]["status"] == "unknown"
    assert all(r["qty"] == 5 for r in out["bom"]["purchased"]) and out["bom"]["notes"]


def test_case_a_faster_duty_rules_out_smart_actuators():
    """检验动作加快到 120°/s：一体化模组一个都不行，选伺服链，并写明卡在哪（ADR-0117）"""
    cr = json.loads(CASE_A.read_text(encoding="utf-8"))
    out = RB.build(copy.deepcopy(cr["chosen"]), cr["conditions"]["payload"], move_s=1.0)
    assert out["status"] == "pass", out.get("note")
    (_g, p), = out["picks"].items()
    assert p["chain"] == "servo" and "smart" not in p["options"]
    assert "都不通过" in p["smart_shortfall"] and "S1" in p["smart_shortfall"]
    assert "120°/s" in out["assumptions"][0]


def test_repeatability_from_output_resolution_hand_calculation():
    """两杆臂水平伸直、三个关节都用规格表分辨率 4096 的一体化模组：最坏 = Σ (π / 4096) × 力臂（j1 500、j2 500、j3 200 mm）"""
    c = two_link()
    dt = RB.duty(c)
    picks = {"g": {"joints": ["j1", "j2", "j3"], "chain": "smart", "components": ["smart_actuator.robotis.xm430-w350"]}}
    r = RB.repeatability(RB._library(), c, dt, picks, 0.5)
    lever = {x["joint"]: x["lever_mm"] for x in r["rows"]}
    assert lever == pytest.approx({"j1": 500, "j2": 500, "j3": 200}, abs=1.0)
    assert r["worst_mm"] == pytest.approx(math.pi / 4096 * sum(lever.values()), rel=1e-3)
    assert r["status"] == "fail" and r["backlash_lost_motion_mm"] == pytest.approx(math.radians(0.25) * 1200, rel=1e-2)
    picks["g"]["chain"], picks["g"]["components"] = "servo", ["servo_motor.yaskawa-electric-corporation.sgm7j-01a"]
    assert RB.repeatability(RB._library(), c, dt, picks, 0.5)["status"] == "unknown"   # 编码器位数库里没有：不判
    picks["g"]["chain"], picks["g"]["components"] = "smart", ["smart_actuator.robotis.xm430-w350"]
    near = RB.repeatability(RB._library(), c, dt, picks, 0.5, points_mm=[[300, 0, 50]])  # 需求点上算：力臂小
    assert "需求点" in near["pose"] and near["worst_mm"] < r["worst_mm"]
