"""连续 PID 抗积分饱和改用反算法；积分卡住时停下报原因。

《多体动力学》书第 31 章线索第 46 条（问渠 CAD 0.3.8 细则）。单关节转台 J = 0.05 kg·m²，恒定扰动 2 N·m，限幅 ±3 N·m，设定 30°。
原来的条件积分（饱和且误差同向就停积分）在 B 组增益（kp 10、ki 100、kd 1，N·m/rad 制，线性闭环稳定）下贴着限幅来回切换，
2 s 仿真 90 s 算不完；书里的反算法（T_t = 0.05 s）RK45 1490 次算完，超调 11.76°。
"""
import math

import pytest

from analysis.mbd.dae import solve as S
from analysis.mbd.dae.run import run_model

DEG = math.pi / 180
J, UMAX, TD, REF = 0.05, 3.0, 2.0, 30.0


def _table(kp, ki, kd, steps=2000):
    return {"format": "mbd-model/1", "name": "转台", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "b", "mass_kg": 2, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": 0.01, "iyy": 0.01, "izz": J}}],
            "joints": [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "forces": [{"id": "m", "type": "actuator", "joint": "r"}, {"id": "d", "type": "torque", "body": "b", "tz_n_m": -TD}],
            "measures": [{"id": "th", "type": "joint_angle", "joint": "r"}, {"id": "w", "type": "joint_speed", "joint": "r"}],
            "controllers": [{"id": "c", "type": "pid", "sensor": "th", "rate_sensor": "w", "setpoint": str(REF), "actuator": "m",
                             "kp": kp * DEG, "ki": ki * DEG, "kd": kd * DEG, "output_min": -UMAX, "output_max": UMAX}],
            "analysis": {"type": "dynamic", "end_time_s": 2.0, "output_steps": steps, "rtol": 1e-8, "atol": 1e-10}}


def _overshoot(d):
    return max(d["measures"]["th"]["values"]) - REF


def test_chattering_gains_finish_with_back_calculation():
    d, _ = run_model(_table(10.0, 100.0, 1.0))          # 原来 90 s 算不完
    assert _overshoot(d) == pytest.approx(11.762083601014794, abs=0.01)
    assert d["solver"]["rhs"] < 20000


def test_back_calculation_overshoot_gain_a():
    d, _ = run_model(_table(20.0, 100.0, 2.0))
    assert _overshoot(d) == pytest.approx(2.1159829227739095, abs=0.01)   # 条件积分是 2.688°，不做抗饱和 13.13°


def test_stall_is_reported(monkeypatch):
    # 滑块受 5 − 10·sign(v) N：v > 0 时减速、v < 0 时加速，解贴着 v = 0 来回切换（滑模），变步长积分步长持续过小
    monkeypatch.setattr(S, "STALL_RHS", 3000)
    m = {"format": "mbd-model/1", "name": "滑模", "gravity_mm_s2": [0, 0, 0],
         "bodies": [{"id": "s", "mass_kg": 1.0, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": 1e-3, "iyy": 1e-3, "izz": 1e-3}}],
         "joints": [{"id": "p", "type": "translational", "body_i": "ground", "body_j": "s", "point_mm": [0, 0, 0], "axis": [1, 0, 0]}],
         "measures": [{"id": "v", "type": "joint_velocity", "joint": "p"}],
         "forces": [{"id": "f", "type": "force", "body": "s", "point_mm": [0, 0, 0], "fx_n": "5-10*sign(v)"}],
         "analysis": {"type": "dynamic", "end_time_s": 1.0, "output_steps": 10}}
    with pytest.raises(S.SolveError, match="积分卡住"):
        run_model(m)
