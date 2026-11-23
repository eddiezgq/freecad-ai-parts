"""装不装得下（analysis/robot/fit.py，ADR-0115 44.3 之二第 3 步之一）。

标准题（平面几何）：
  · U 底板离轴线很远（d ≫ 外形）时，碰到下面父杆的角度由 d·sin φ = (b + w)/2 决定（φ = 180° − 最大转角，b 底板宽、w 父杆宽）
  · d 小于轴线到壳体顶面的距离时，伸直位就碰上
  · 共线轴转装不上；关节距不够时判不通过
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from analysis.robot import fit
from kb.library import JsonLibrary

ROOT = Path(__file__).parents[1]
H = {"half_width": 16.75, "bottom": -44.75, "top": 13.75, "axis_to_bottom": 44.75, "horn_diameter": 26.0}


def test_separating_axis_overlap():
    a = fit._rect(0, 1, 0, 1)
    assert fit._overlap(a, fit._rect(0.5, 2, 0.5, 2))
    assert not fit._overlap(a, fit._rect(1, 2, 0, 1))                    # 只接触不算
    assert not fit._overlap(a, fit._rot(fit._rect(2, 3, 0, 1), 0))


def test_far_plate_reach_matches_geometry():
    b, w, d = 33.5, 40.0, 250.0
    phi = math.degrees(math.asin((b + w) / (2 * d)))
    assert fit.clevis_reach(d, b, H, w) == pytest.approx(180 - phi, abs=fit.STEP_DEG)


def test_plate_inside_housing_top_collides_at_straight():
    assert fit.clevis_reach(H["top"] - 1, 33.5, H, 33.5) < 0
    assert fit.clevis_reach(H["top"] + 1, 33.5, H, 33.5) >= 0


def test_d_min_is_monotone_and_none_beyond_limit():
    d1, d2 = fit.d_min(90, 33.5, H, 40), fit.d_min(140, 33.5, H, 40)
    assert d1 is not None and d2 is not None and d1 < d2
    assert fit.clevis_reach(d2, 33.5, H, 40) >= 140 > fit.clevis_reach(d2 - 0.5, 33.5, H, 40)
    assert fit.d_min(179, 33.5, H, 40) is None


def _arm(wrist=None):
    """竖直零位的五轴臂（上一版案例 A 的几何）：j2、j3、j4 侧摆，j5 在腕杆末端绕杆轴转（共线）"""
    tube = {"shape": "tube", "material": "6061-T6"}
    c = {"format": "robot-concept/1", "name": "五轴臂", "kind": "serial_arm", "base": {"mount": "table"},
         "links": [dict(tube, id="turret", length_mm=80, section={"od_mm": 70, "id_mm": 60}),
                   dict(tube, id="upper", length_mm=170, section={"od_mm": 40, "id_mm": 34}),
                   dict(tube, id="fore", length_mm=160, section={"od_mm": 34, "id_mm": 28}),
                   dict(tube, id="wrist", length_mm=40, section={"od_mm": 30, "id_mm": 24}),
                   dict(tube, id="flange", length_mm=60, section={"od_mm": 30, "id_mm": 24})],
         "joints": [{"id": "j1", "type": "revolute", "parent": "base", "child": "turret", "origin_mm": [0, 0, 0], "axis": [0, 0, 1], "range_deg": [-170, 170]},
                    {"id": "j2", "type": "revolute", "parent": "turret", "child": "upper", "origin_mm": [0, 0, 80], "axis": [0, 1, 0], "range_deg": [-60, 120]},
                    {"id": "j3", "type": "revolute", "parent": "upper", "child": "fore", "origin_mm": [0, 0, 170], "axis": [0, 1, 0], "range_deg": [-20, 140]},
                    {"id": "j4", "type": "revolute", "parent": "fore", "child": "wrist", "origin_mm": [0, 0, 160], "axis": [0, 1, 0], "range_deg": [-120, 120]},
                    {"id": "j5", "type": "revolute", "parent": "wrist", "child": "flange", "origin_mm": wrist or [0, 0, 40], "axis": [0, 0, 1], "range_deg": [-180, 180]}],
         "end_effector": {"type": "gripper", "parent": "flange", "offset_mm": [0, 0, 80]}}
    return c


def _comp(ref="xm540-w270"):
    return JsonLibrary(ROOT / "data" / "library").get(f"smart_actuator.robotis.{ref}")


def test_collinear_wrist_roll_cannot_be_mounted():
    c, comp = _arm(), _comp()
    r = fit.check(c, {j["id"]: comp for j in c["joints"]})
    j = {x["joint"]: x for x in r["joints"]}
    assert j["j5"]["status"] == "fail" and "共线" in j["j5"]["note"]
    assert j["j2"]["status"] == "pass" and j["j2"]["d_min_mm"] > H["axis_to_bottom"]
    links = {x["link"]: x for x in r["links"]}
    assert links["upper"]["status"] == "pass"
    assert links["upper"]["spare_mm"] == pytest.approx(170 - 44.75 - j["j2"]["d_min_mm"], abs=0.1)   # 上臂长 − 轴线到底面 − d_min
    assert links["wrist"]["status"] == "unknown" and r["overall"] == "fail"


def test_offset_wrist_roll_too_close_to_the_wrist_pitch():
    """腕部轴转偏开 50 mm 但只往前 40 mm：j5 的壳体伸进 j4 的 U 形支架转动范围（真实 AI 第二轮的改法，ADR-0115）"""
    c = _arm(wrist=[50, 0, 40])                                   # j5 轴仍沿杆（z），轴线沿 x 偏开 50 mm
    c["joints"][3]["range_deg"] = [-20, 20]                       # 零位时腕杆已斜出去：j4 行程收小，免得先在转角上不通过
    r = fit.check(c, {j["id"]: _comp() for j in c["joints"]})
    w = {x["link"]: x for x in r["links"]}["wrist"]
    assert {x["joint"]: x for x in r["joints"]}["j5"]["status"] == "pass"
    assert w["status"] == "fail" and "伸进" in w["note"]
    c["joints"][4]["origin_mm"] = [24.5, 0, 160]                  # 横置滚转、往前推到 U 底板之外，壳体中心落在杆轴上
    c["joints"][4]["axis"] = [1, 0, 0]
    c["end_effector"]["offset_mm"] = [0, 0, 0]
    c["links"][3]["length_mm"] = 160
    w = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["links"]}["wrist"]
    assert w["status"] == "pass", w["note"]


def test_short_link_fails_and_missing_interfaces_unknown():
    c = _arm()
    c["joints"][2]["origin_mm"] = [0, 0, 60]                    # 上臂只有 60 mm：放不下 U 底板与下一个壳体
    r = fit.check(c, {j["id"]: _comp() for j in c["joints"]})
    assert {x["link"]: x for x in r["links"]}["upper"]["status"] == "fail"
    r = fit.check(c, {j["id"]: _comp("xm430-w350") for j in c["joints"]})      # 430 没有接口数据
    assert all(x["status"] == "unknown" for x in r["joints"])


def test_base_mounted_housing_must_stay_above_the_table():
    """j1 的输出舵盘在原点（贴着桌面）时，壳体在它后面 2.5–46.5 mm，钻到桌面下；抬高 j1 原点就过；吊装方向相反"""
    c = _arm()
    r = fit.check(c, {j["id"]: _comp() for j in c["joints"]})
    j1 = {x["joint"]: x for x in r["joints"]}["j1"]
    assert j1["status"] == "fail" and "46.5" in j1["note"]
    c["joints"][0]["origin_mm"] = [0, 0, 50]
    j1 = {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}["j1"]
    assert j1["status"] == "pass" and j1["base_clear_mm"] == pytest.approx(3.5)
    c["base"]["mount"] = "ceiling"                                   # 吊装：安装面在上，壳体要在下面——抬高 50 就错了
    j1 = {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}["j1"]
    assert j1["status"] == "fail"
    c["base"]["mount"] = "wall"
    assert {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}["j1"]["status"] == "unknown"


def test_links_are_straight_tubes():
    """下一关节的壳体底面要正对本杆：轴转关节的轴线斜着（偏开又沿杆向）就接不上直管；轴线垂直于杆、壳体中心落在杆轴上才行"""
    c = _arm(wrist=[0, 0, 40])
    c["joints"][0]["origin_mm"] = [0, 0, 50]
    c["joints"][4]["origin_mm"] = [-45, 0, 100]                  # 真实 AI 一轮的改法：偏开 45 mm、轴线仍沿 z（与腕杆斜交）
    r = fit.check(c, {j["id"]: _comp() for j in c["joints"]})
    w = {x["link"]: x for x in r["links"]}["wrist"]
    assert w["status"] == "fail" and "不垂直" in w["note"]
    c["joints"][4]["axis"] = [1, 0, 0]                           # 横置滚转：轴线沿 x，垂直于腕杆（z）
    c["joints"][4]["origin_mm"] = [0, 0, 100]                    # 原点在舵盘端面，壳体中心在它后面 24.5：偏出杆轴
    c["end_effector"]["offset_mm"] = [0, 0, 0]
    c["links"][4]["length_mm"] = 60
    w = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["links"]}["wrist"]
    assert w["status"] == "fail" and "24.5" in w["note"]           # 壳体中心偏出杆轴：杆向斜了
    c["joints"][4]["origin_mm"] = [24.5, 0, 100]                 # 壳体中心回到杆轴上
    w = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["links"]}["wrist"]
    assert w["status"] == "pass", w["note"]


def test_zero_pose_offset_counts_in_the_joint_range():
    """零位时子杆已经横着（相对伸直 −90°）：行程 ±120° 相对伸直就是 [−210°, 30°]，转不到；改成 [−60°, 120°] 就是 [−150°, 30°]"""
    c = _arm()
    c["joints"][0]["origin_mm"] = [0, 0, 50]
    c["joints"][4]["origin_mm"] = [-105, 0, 24.5]                # 腕部滚转在腕关节的 −x 一侧（壳体中心 (−105, 0, 0)）
    r = {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}
    assert r["j4"]["status"] == "fail" and r["j4"]["zero_offset_deg"] == pytest.approx(-90.0) and "−90" not in r["j4"]["note"]
    assert "-210" in r["j4"]["note"]
    c["joints"][3]["range_deg"] = [-60, 120]
    r = {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}
    assert r["j4"]["status"] == "pass" and r["j4"]["required_deg"] == pytest.approx(150)


def test_min_spare_for_brackets():
    c = _arm()
    c["joints"][0]["origin_mm"] = [0, 0, 50]
    links = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]}, min_spare_mm=200)["links"]}
    assert links["upper"]["status"] == "fail" and "放不下" in links["upper"]["note"]
    spare = links["upper"]["spare_mm"]
    by_kind = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]},
                                               min_spare_mm={"clevis": spare + 1, "flange": 0.0})["links"]}
    assert by_kind["upper"]["status"] == "fail" and f"至少 {spare + 1:g} mm" in by_kind["upper"]["note"]   # upper 从侧摆关节 j2 起
    by_kind = {x["link"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]},
                                               min_spare_mm={"clevis": spare, "flange": 1e6})["links"]}
    assert by_kind["upper"]["status"] == "pass"


def test_child_origin_offset_along_the_axis_is_a_design_error():
    """侧摆关节的下一关节原点沿本关节轴线偏了（AI 把轴转关节的 24.5 mm 用到了侧摆关节上）：做不了，判不通过并说明改法"""
    c = _arm()
    c["joints"][0]["origin_mm"] = [0, 0, 50]
    c["joints"][2]["origin_mm"] = [0, 24.5, 170]                # j3 原点沿 j2 的轴线（y）偏 24.5
    j2 = {x["joint"]: x for x in fit.check(c, {j["id"]: _comp() for j in c["joints"]})["joints"]}["j2"]
    assert j2["status"] == "fail" and "24.5" in j2["note"] and "沿轴偏移为 0" in j2["note"]
