"""运动副摩擦的不动点迭代：收敛慢时加速，自锁时报出来。

《多体动力学》书第 20 章线索第 29 条（问渠 CAD 0.3.8 细则）。曲柄滑块（曲柄 50 mm、连杆 150 mm，三个转动副销半径 10 mm，
导轨同一 μ，滑块阻力 200 N），曲柄是大飞轮（绕轴 10³ kg·m²、3600 °/s），在 θ = 90° 处由 A 铰反力和 O、A 销摩擦换算驱动力矩。
原来：μ = 1.5 迭代 30 次就停，给 113.3 N·m，收敛值是 127.84 N·m（书里另写的不动点迭代 355 次收敛）；
μ = 2.0 增益 > 1、没有解（自锁），照样给 35203 N·m、无提示。
"""
import math

import numpy as np

from analysis.mbd.dae.run import run_model

R, L = 50.0, 150.0
M1, M2, M3 = 0.5, 0.8, 1.0
W_DEG = 3600.0


def _fr(mu, pin=None):
    f = {"mu_static": mu, "mu_dynamic": mu, "stiction_speed": 1e-3, "transition_speed": 2e-3}
    if pin is not None:
        f["pin_radius_mm"] = pin
    return f


def _model(mu, t_end=0.025, steps=100):
    J = [{"id": "O", "type": "revolute", "body_i": "ground", "body_j": "crank", "point_mm": [0, 0, 0], "axis": [0, 0, 1],
          "initial_speed": W_DEG},
         {"id": "A", "type": "revolute", "body_i": "crank", "body_j": "rod", "point_mm": [R, 0, 0], "axis": [0, 0, 1]},
         {"id": "B", "type": "revolute", "body_i": "rod", "body_j": "sl", "point_mm": [R + L, 0, 0], "axis": [0, 0, 1]},
         {"id": "P", "type": "translational", "body_i": "ground", "body_j": "sl", "point_mm": [R + L, 0, 0], "axis": [1, 0, 0]}]
    for j in J:
        j["friction"] = _fr(mu, 10.0 if j["type"] == "revolute" else None)
    small = {"ixx": 1e-4, "iyy": 1e-4}
    return {"format": "mbd-model/1", "name": "曲柄滑块（关节摩擦）", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "crank", "mass_kg": M1, "cm_mm": [R / 2, 0, 0], "inertia_kg_m2": small | {"izz": 1e3}},
                       {"id": "rod", "mass_kg": M2, "cm_mm": [R + L / 2, 0, 0],
                        "inertia_kg_m2": small | {"izz": M2 * (L / 1000) ** 2 / 12}},
                       {"id": "sl", "mass_kg": M3, "cm_mm": [R + L, 0, 0], "inertia_kg_m2": small | {"izz": 1e-4}}],
            "joints": J, "measures": [{"id": "v", "type": "joint_velocity", "joint": "P"}],
            "forces": [{"id": "F", "type": "force", "body": "sl", "point_mm": [R + L, 0, 0], "fx_n": "-200.0*sign(v)"}],
            "analysis": {"type": "dynamic", "end_time_s": t_end, "output_steps": steps, "rtol": 1e-10, "atol": 1e-12}}


def _tau90(d, mu):
    """θ ≈ 90° 时的驱动力矩（同书里 ex20_3_wq.py 的换算）"""
    t = np.asarray(d["times_s"], float)
    FA = np.asarray(d["joints"]["A"]["force_n"], float)
    FO = np.asarray(d["joints"]["O"]["force_n"], float)
    w1 = np.asarray(d["bodies"]["crank"]["w_deg_s"], float)[:, 2]
    w2 = np.asarray(d["bodies"]["rod"]["w_deg_s"], float)[:, 2]
    ang = np.radians(np.cumsum(np.r_[0, 0.5 * (w1[1:] + w1[:-1]) * np.diff(t)]))
    k = int(np.argmin(np.abs(np.degrees(ang) - 90)))
    a = np.array([R * math.cos(ang[k]), R * math.sin(ang[k])]) / 1000
    tau = a[0] * FA[k, 1] - a[1] * FA[k, 0]
    tau += mu * 0.01 * math.hypot(*FO[k, :2]) * np.sign(w1[k]) - mu * 0.01 * math.hypot(*FA[k, :2]) * np.sign(w2[k] - w1[k])
    return float(tau)


def _item(d, key):
    return next(v for v in d["verification"] if v["key"] == key)


def test_slow_convergence_reaches_fixed_point():
    d, msgs = run_model(_model(1.5))
    # 书里不动点迭代 355 次收敛到 127.841 N·m（θ 差 0.0016° 的影响约 1e-5）；原来给 113.3
    assert abs(_tau90(d, 1.5) / 127.84124 - 1) < 1e-4
    assert _item(d, "friction_iteration")["status"] == "pass"
    assert not any("自锁" in m for m in msgs)


def test_self_locking_reported():
    d, msgs = run_model(_model(2.0))
    it = _item(d, "friction_iteration")
    assert it["status"] == "fail"
    assert any("可能自锁" in m for m in msgs)


def test_ordinary_friction_unchanged():
    # μ = 0.5 在 30 次以内收敛（书里 23 次），与原来一致：9.0113 N·m
    d, msgs = run_model(_model(0.5))
    assert abs(_tau90(d, 0.5) - 9.01133) < 1e-3
    assert _item(d, "friction_iteration")["status"] == "pass"
