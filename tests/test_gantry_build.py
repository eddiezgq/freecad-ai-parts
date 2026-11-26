"""龙门取放机器人的整机（ADR-0115 44.5.5 第一步）：节拍、多体动力学推力与滑台载荷、直线模组与抓手选件。不联网、不调用 AI。

手算对照：X 轴推力 = X 上全部运动质量 × X 加速度；Z 轴推力 = Z 上运动质量 ×（g + Z 加速度）；Z 滑台偏摆力矩 = Σ m × a × 质心到滑台的距离。
质量全部取零件库与方案里的数（模组质量、滑台质量、杆件截面 × 长度 × 密度、单片质量）。
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

if os.environ.get("CI"):
    import mujoco  # noqa: F401
else:
    pytest.importorskip("mujoco")

from assist import gantry_build as GB

ROOT = Path(__file__).resolve().parent.parent
CASE = ROOT / "examples" / "robots" / "sewing-loader" / "out"
G = 9.80665


def _cr():
    return json.loads((CASE / "concept-result.json").read_text(encoding="utf-8"))


def test_cycle_matches_screening_and_maps_to_axes():
    cr = _cr()
    c = GB.cycle(cr["chosen"])
    assert c["total_s"] == pytest.approx(2.8)
    assert c["axes"]["j1_x"]["speed_m_s"] == pytest.approx(1.5 / (0.8 * 0.75), rel=1e-4)        # 2.5 m/s
    assert c["axes"]["j1_x"]["accel_m_s2"] == pytest.approx(2.5 / 0.2, rel=1e-4)                # 12.5 m/s²
    assert c["axes"]["j2_z"]["speed_m_s"] == pytest.approx(0.13 / (0.25 * 0.75), rel=1e-4)
    assert c["initial"] == {"j1_x": 0.0, "j2_z": -100.0}           # 取料点（台面上一叠最底下一片）：Z 在下限
    assert c["axes"]["j2_z"]["travel_mm"] == [-100.0, 30.0]
    x = next(d for d in c["drives"] if d["joint"] == "j1_x")
    assert [s["to"] for s in x["segments"]] == [1500.0, 0.0]
    assert c["tool"]["accel_m_s2"] == pytest.approx(12.5, rel=1e-4)
    with pytest.raises(GB.BuildError, match="没有轴的方向"):
        GB.joint_values(cr["chosen"], [0, 50, 0])
    with pytest.raises(GB.BuildError, match="超出行程"):
        GB.joint_values(cr["chosen"], [1700, 0, 0])
    bad = copy.deepcopy(cr["chosen"])
    bad["tasks"][0]["to_mm"] = [0, 0, 120]
    with pytest.raises(GB.BuildError, match="首尾相连"):
        GB.cycle(bad)
    scara = cr["rounds"][0]["proposal"]["candidates"][1]
    with pytest.raises(GB.BuildError, match="只做全部是移动关节"):
        GB.axes(scara)


def test_case_b_build_thrust_loads_and_picks_match_hand_calc():
    cr = _cr()
    out = GB.build(cr["chosen"], cr["conditions"])
    assert out["status"] == "pass", out.get("note")
    px, pz = out["picks"]["j1_x"], out["picks"]["j2_z"]
    assert px["model"] == "EGC-80-TB-KF-GK" and pz["model"] == "EGC-80-BS-KF-20P-GK"
    lib = GB._library()
    from analysis.robot import mjcf as RM

    lm = RM.link_masses(cr["chosen"])[0]
    part = cr["conditions"]["part_mass"]
    car_x = GB._pv(lib.get(px["component"]), "carriage_mass_kg")
    car_z = GB._pv(lib.get(pz["component"]), "carriage_mass_kg")
    mz = car_z + lm["z_slide"] + part                                # 抓手质量厂商没给，不计
    mx = car_x + lm["x_carriage"] + pz["mass_kg"] + lm["z_slide"] + part
    assert pz["mass_kg"] == pytest.approx(2.7 + 0.08 * 200 / 10)      # 本体 + 每 10 mm 增重 × 行程
    ld = out["loads"]
    ax, az = 12.5, 0.13 / (0.25 * 0.75) / (0.25 * 0.25)
    assert ld["j1_x"]["thrust_n"] == pytest.approx(mx * ax, rel=0.01)
    assert ld["j2_z"]["thrust_n"] == pytest.approx(mz * (G + az), rel=0.01)
    assert ld["j1_x"]["thrust_peak_raw_n"] > ld["j1_x"]["thrust_n"]
    assert ld["j2_z"]["force_lateral_n"] == pytest.approx(mz * ax, rel=0.01)       # 竖直轴滑台面朝 +y：X 加速是侧向力
    yaw = (lm["z_slide"] * 0.2 + part * 0.4) * ax                                    # 杆件质心在 200 mm、工件在 400 mm 处
    assert ld["j2_z"]["moment_yaw_nm"] == pytest.approx(yaw, rel=0.01)
    assert ld["j1_x"]["force_normal_n"] == pytest.approx(mx * G + mz * az, rel=0.01)  # 法向：重力 + Z 加速的反力
    for p in (px, pz):
        assert p["check"]["overall"] == "pass"
        assert p["requirement"]["safety_factor"] == GB.SAFETY
    assert px["requirement"]["stroke_mm"] == 1600 and pz["requirement"]["stroke_mm"] == 200
    why = {r["component"].split(".")[-1]: " ".join(r["why"]) for r in px["rejected"]}
    assert "L4" in why["egc-70-tb-kf-gk"] and "L4" in why["egc-50-tb-kf-gk"]       # 推力不够
    assert all(r["component"].endswith("gk") and "-bs-" in r["component"] for r in pz["rejected"])
    assert "L2" in " ".join(r["why"][0] for r in pz["rejected"] if "egc-70-bs" in r["component"])   # 0.5 m/s 不够
    g = out["gripper"]
    assert g["model"] == "SPF 15" and g["required_force_n"] == pytest.approx(0.1 * (G + 12.5) * 2, rel=1e-4)
    assert {r["type"] for r in g["compare"]} == {"needle", "suction_cup"}
    assert out["repeatability"]["status"] == "pass" and out["repeatability"]["worst_mm"] == pytest.approx(0.1)
    assert out["cycle_time"]["status"] == "pass"
    assert out["motors"]["j1_x"]["torque_nm"] == pytest.approx(ld["j1_x"]["thrust_n"] * 1.2 * 0.09 / (2 * 3.141592653589793),
                                                               rel=1e-3)
    assert any("抓手质量" in x for x in out["open_items"]) and any("抱闸" in x for x in out["open_items"])
    assert out["cost"]["status"] == "unknown"
    saved = json.loads((CASE / "build-result.json").read_text(encoding="utf-8"))   # 示例里存的结果就是这样算出来的
    assert saved["format"] == GB.FORMAT
    assert {j: p["component"] for j, p in saved["picks"].items()} == {j: p["component"] for j, p in out["picks"].items()}
    for j, ld_j in out["loads"].items():
        for k, v in ld_j.items():
            assert saved["loads"][j][k] == pytest.approx(v, rel=1e-6), (j, k)
