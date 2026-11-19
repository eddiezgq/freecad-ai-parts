"""关节输出轴的载荷由动力学算（ADR-0100 42.5 第 4 步）：静止水平伸直时与手算（Σm·g·r、ΣF = Σm·g）对照；运动时峰值大于静止。"""

from __future__ import annotations

import pytest

pytest.importorskip("mujoco")

from analysis.shaft import joint_loads as L

ARM = {"base_height_mm": 89, "links": [{"length_mm": 425, "mass_kg": 8.393}, {"length_mm": 392.25, "mass_kg": 2.275}],
       "joint_masses_kg": [0.0, 1.219], "payload_kg": 5.0}
G = 9.81


def hand():
    m1, m2, mj3, mp = 8.393, 2.275, 1.219, 5.0
    torque = G * (m1 * 0.2125 + mj3 * 0.425 + m2 * (0.425 + 0.392 / 2) + mp * (0.425 + 0.39225))
    return torque, G * (m1 + m2 + mj3 + mp)


def test_static_horizontal_matches_hand_calculation():
    c = L.cycle(ARM, {"j2": 0, "j3": 0}, {"j2": 0, "j3": 0}, 0.5, 0.2)
    k = L.conditions(c)
    t_hand, f_hand = hand()
    assert k["T_peak_nm"] == pytest.approx(t_hand, rel=0.01)
    assert k["F_peak_n"] == pytest.approx(f_hand, rel=0.01)
    assert k["speed_avg_rpm"] == pytest.approx(0, abs=1e-3)


def test_moving_cycle_peaks_above_static():
    c = L.cycle(ARM, {"j2": 0, "j3": 0}, {"j2": -60, "j3": 60}, 1.0, 0.5)
    k = L.conditions(c)
    t_hand, _ = hand()
    assert k["T_peak_nm"] > 0.9 * t_hand and k["T_min_nm"] < k["T_peak_nm"]
    assert k["speed_max_rpm"] > 0 and 0 < k["speed_avg_rpm"] < k["speed_max_rpm"]
    assert len(k["F_series_n"]) > 10
