"""杆件校核（analysis/robot/links.py，ADR-0115 44.3 之二）。

标准题（材料力学）：水平悬臂铝管，端部挂质量 m——根部弯矩 M = m·g·L（加上管自重 w·L²/2）、σ = M/Z、Z = π(D⁴ − d⁴)/(32D)；
端部挠度 P·L³/(3EI)；竖直杆只受轴力，没有弯矩。
"""

from __future__ import annotations

import math

import pytest

from analysis.common import materials
from analysis.robot import links, mjcf

G = 9.81


def arm(od=20.0, idd=16.0, length=300.0):
    """j1 绕 y 转的单杆：零位竖直（沿 +z），转 90° 后沿 +x 水平；工具点在杆端"""
    return {"format": "robot-concept/1", "name": "单杆", "kind": "serial_arm", "base": {"mount": "table"},
            "links": [{"id": "bar", "shape": "tube", "length_mm": length, "material": "6061-T6",
                       "section": {"od_mm": od, "id_mm": idd}}],
            "joints": [{"id": "j1", "type": "revolute", "parent": "base", "child": "bar", "origin_mm": [0, 0, 0],
                        "axis": [0, 1, 0], "range_deg": [-120, 120]}],
            "end_effector": {"type": "gripper", "parent": "bar", "offset_mm": [0, 0, length]}}


def test_horizontal_cantilever_matches_hand_calculation():
    c = arm()
    m_tip = 1.0
    r = links.check(c, {"j1": 90}, payload_kg=m_tip, required_safety=1.2)
    row = r["items"][0]
    w = mjcf.link_masses(c)[0]["bar"]
    M = m_tip * G * 0.3 + w * G * 0.15
    assert row["bending_nm"] == pytest.approx(M, rel=1e-6) and row["torsion_nm"] == pytest.approx(0, abs=1e-9)
    Z = math.pi * (20 ** 4 - 16 ** 4) / (32 * 20)
    assert row["sigma_eq_mpa"] == pytest.approx(M * 1000 / Z, abs=1e-3)          # 结果保留 3 位小数
    mat = materials.get("6061-T6")
    assert row["safety_yield"] == pytest.approx(mat["yield_strength_mpa"] / (M * 1000 / Z), rel=1e-3)
    assert row["status"] == "pass"
    inertia = math.pi * (20 ** 4 - 16 ** 4) / 64
    P = M * 1000 / 300                                              # 端部等效集中力
    assert r["tool_sag_mm"] == pytest.approx(P * 300 ** 3 / (3 * mat["elastic_modulus_mpa"] * inertia), abs=1e-4)


def test_vertical_bar_has_no_bending_and_dynamic_factor_scales_stress():
    c = arm()
    up = links.check(c, {"j1": 0}, payload_kg=1.0, required_safety=1.2)["items"][0]
    assert up["bending_nm"] == pytest.approx(0, abs=1e-9)
    a = links.check(c, {"j1": 90}, payload_kg=1.0, required_safety=1.2)["items"][0]
    b = links.check(c, {"j1": 90}, payload_kg=1.0, required_safety=1.2, dynamic_factor=2.0)["items"][0]
    assert b["sigma_eq_mpa"] == pytest.approx(2 * a["sigma_eq_mpa"], abs=2e-3)


def test_thin_tube_fails_and_missing_requirement_is_unknown():
    thin = links.check(arm(od=6, idd=5.6), {"j1": 90}, payload_kg=20.0, required_safety=1.2)
    assert thin["overall"] == "fail"
    assert links.check(arm(), {"j1": 90}, payload_kg=1.0)["items"][0]["status"] == "unknown"   # 需求没给安全系数：不判
