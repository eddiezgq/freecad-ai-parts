"""静平衡、线性化计入控制器。

《多体动力学》书第 32 章线索第 47 条（问渠 CAD 0.3.8 细则）。关节柔性两杆臂（零位），电机转子用转动副 + 执行器 + PID（只有 kp、kd，
kd 用转速测量量）：原来 static_then_linear 报“静平衡没找到（残差 10.6）”，linear 给出的模态与“电机完全自由、没有控制器”一致到 1.7e-13。
验证：同一个 PD 写成地面—转子、大臂—转子的转动弹簧阻尼器，两种写法的极点一致（书里弹簧写法与 mini-mbd 一致到 1e-9）。
"""
import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

DEG = math.pi / 180
L1, M1B, M2, C2, I2, ME = 0.4, 3.0, 3.0, 0.2, 0.03, 0.5
JR, KJ, CJ = (0.3, 0.08), (4000.0, 1500.0), (2.0, 0.5)
KP, KD = (692.0, 92.0), (69.2, 9.2)                 # N·m/rad、N·m·s/rad（书第 32 章）


def _arm(mode, typ="static_then_linear"):
    def inert(i):
        return {"ixx": 1e-4, "iyy": 1e-4, "izz": i}
    e = [L1 * 1000, 0, 0]
    bodies = [{"id": "l1", "mass_kg": M1B, "cm_mm": [L1 / 2 * 1000, 0, 0], "inertia_kg_m2": inert(M1B * L1 * L1 / 12)},
              {"id": "l2", "mass_kg": M2, "cm_mm": [(L1 + C2) * 1000, 0, 0], "inertia_kg_m2": inert(I2)},
              {"id": "r1", "mass_kg": 0.5, "cm_mm": [0, 0, 0], "inertia_kg_m2": inert(JR[0])},
              {"id": "r2", "mass_kg": ME, "cm_mm": e, "inertia_kg_m2": inert(JR[1])}]
    joints = [{"id": "j1", "type": "revolute", "body_i": "ground", "body_j": "l1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
              {"id": "j2", "type": "revolute", "body_i": "l1", "body_j": "l2", "point_mm": e, "axis": [0, 0, 1]},
              {"id": "m1", "type": "revolute", "body_i": "ground", "body_j": "r1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
              {"id": "m2", "type": "revolute", "body_i": "l1", "body_j": "r2", "point_mm": e, "axis": [0, 0, 1]}]
    forces = [{"id": "k1", "type": "rotational_spring_damper", "body_i": "r1", "body_j": "l1", "axis": [0, 0, 1],
               "stiffness_n_m_per_deg": KJ[0] * DEG, "damping_n_m_s_per_deg": CJ[0] * DEG},
              {"id": "k2", "type": "rotational_spring_damper", "body_i": "r2", "body_j": "l2", "axis": [0, 0, 1],
               "stiffness_n_m_per_deg": KJ[1] * DEG, "damping_n_m_s_per_deg": CJ[1] * DEG}]
    ctrl = []
    if mode == "spring":
        forces += [{"id": "s1", "type": "rotational_spring_damper", "body_i": "ground", "body_j": "r1", "axis": [0, 0, 1],
                    "stiffness_n_m_per_deg": KP[0] * DEG, "damping_n_m_s_per_deg": KD[0] * DEG},
                   {"id": "s2", "type": "rotational_spring_damper", "body_i": "l1", "body_j": "r2", "axis": [0, 0, 1],
                    "stiffness_n_m_per_deg": KP[1] * DEG, "damping_n_m_s_per_deg": KD[1] * DEG}]
    else:
        forces += [{"id": "a1", "type": "actuator", "joint": "m1"}, {"id": "a2", "type": "actuator", "joint": "m2"}]
        ctrl = [{"id": f"c{i}", "type": "pid", "sensor": f"tm{i + 1}", "rate_sensor": f"wm{i + 1}", "setpoint": "0",
                 "actuator": f"a{i + 1}", "kp": KP[i] * DEG, "kd": KD[i] * DEG} for i in range(2)]
    meas = [{"id": "tm1", "type": "joint_angle", "joint": "m1"}, {"id": "tm2", "type": "joint_angle", "joint": "m2"},
            {"id": "wm1", "type": "joint_speed", "joint": "m1"}, {"id": "wm2", "type": "joint_speed", "joint": "m2"}]
    return {"format": "mbd-model/1", "name": "关节柔性两杆臂（伺服）", "gravity_mm_s2": [0, -9810, 0], "bodies": bodies,
            "joints": joints, "forces": forces, "measures": meas, "controllers": ctrl, "analysis": {"type": typ}}


def _poles(d):
    return sorted((complex(*m["eigenvalue"]) for m in d["linear"]["modes"] if not m.get("rigid_body")),
                  key=lambda z: (round(abs(z), 6), z.imag))


def test_pid_and_spring_pd_have_same_poles():
    dp, _ = run_model(_arm("pid"))                  # 原来静平衡没找到
    ds, _ = run_model(_arm("spring"))
    a, b = _poles(dp), _poles(ds)
    assert len(a) == len(b) == 5
    assert max(abs(x - y) / abs(y) for x, y in zip(a, b, strict=True)) < 1e-6
    # 伺服闭环最高那阶 33.45 Hz、ζ 0.067（书里 mini-mbd）；原来 linear 给的是电机自由时的 21.86、34.34 Hz
    f = sorted(m["frequency_hz"] for m in dp["linear"]["modes"] if not m.get("rigid_body"))
    assert f[-1] == pytest.approx(33.45372772166092, rel=1e-6)


def test_linear_with_controller_is_not_free_motor():
    d, _ = run_model(_arm("pid", typ="linear"))
    f = [m["frequency_hz"] for m in d["linear"]["modes"] if not m.get("rigid_body")]
    assert not any(abs(x - 21.857001929849787) < 1e-3 for x in f)       # 不再是电机自由时的频率
    assert not [m for m in d["linear"]["modes"] if m["frequency_hz"] < 1e-3 and not m.get("rigid_body")]


def test_static_with_pid_integral_reaches_zero_error():
    m = _arm("pid", typ="static_then_linear")
    for c in m["controllers"]:
        c["ki"] = c["kp"] * 5.0                       # 有积分：平衡时误差为 0（电机转子回到设定 0°）
    d, _ = run_model(m)
    for k in ("tm1", "tm2"):
        assert d["measures"][k]["values"][-1] == pytest.approx(0.0, abs=1e-7)
    assert np.all(np.isfinite(np.array(d["linear"]["A"])))
