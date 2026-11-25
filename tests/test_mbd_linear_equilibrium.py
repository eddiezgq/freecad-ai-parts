"""线性化前查工作点是不是平衡点。

《多体动力学》书第 32 章线索第 48 条（问渠 CAD 0.3.8 细则）：关节柔性两杆臂（电机制动），零位装配、关节弹簧不受力，
重力下角加速度 24.5 rad/s²。原来 linear 直接在这里线性化、无提示、稳定性判“通过”；关节刚度 ×0.01 时
linear 给第一阶 0.765 Hz，平衡点上是 0.934 Hz（差 18 %）。
"""
import math

from analysis.mbd.dae.run import run_model

DEG = math.pi / 180
L1 = 0.4
M1B, M2, C2, I2 = 3.0, 3.0, 0.2, 0.03          # 小臂 = 2 kg 杆 + 末端 1 kg（书里 link_props(2.0, 0.3, m_tip=1.0)）
ME = 0.5
JR, KJ, CJ = (0.3, 0.08), (4000.0, 1500.0), (2.0, 0.5)


def _arm(kscale, typ):
    def inert(i):
        return {"ixx": 1e-4, "iyy": 1e-4, "izz": i}
    e = [L1 * 1000, 0, 0]
    return {"format": "mbd-model/1", "name": "关节柔性两杆臂", "gravity_mm_s2": [0, -9810, 0],
            "bodies": [{"id": "l1", "mass_kg": M1B, "cm_mm": [L1 / 2 * 1000, 0, 0], "inertia_kg_m2": inert(M1B * L1 * L1 / 12)},
                       {"id": "l2", "mass_kg": M2, "cm_mm": [(L1 + C2) * 1000, 0, 0], "inertia_kg_m2": inert(I2)},
                       {"id": "r1", "mass_kg": 0.5, "cm_mm": [0, 0, 0], "inertia_kg_m2": inert(JR[0])},
                       {"id": "r2", "mass_kg": ME, "cm_mm": e, "inertia_kg_m2": inert(JR[1])}],
            "joints": [{"id": "j1", "type": "revolute", "body_i": "ground", "body_j": "l1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "j2", "type": "revolute", "body_i": "l1", "body_j": "l2", "point_mm": e, "axis": [0, 0, 1]},
                       {"id": "m1", "type": "fixed", "body_i": "ground", "body_j": "r1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                       {"id": "m2", "type": "fixed", "body_i": "l1", "body_j": "r2", "point_mm": e, "axis": [0, 0, 1]}],
            "forces": [{"id": "k1", "type": "rotational_spring_damper", "body_i": "r1", "body_j": "l1", "axis": [0, 0, 1],
                        "stiffness_n_m_per_deg": KJ[0] * kscale * DEG, "damping_n_m_s_per_deg": CJ[0] * DEG},
                       {"id": "k2", "type": "rotational_spring_damper", "body_i": "r2", "body_j": "l2", "axis": [0, 0, 1],
                        "stiffness_n_m_per_deg": KJ[1] * kscale * DEG, "damping_n_m_s_per_deg": CJ[1] * DEG}],
            "analysis": {"type": typ}}


def _item(d, key):
    return next(v for v in d["verification"] if v["key"] == key)


def _f1(d):
    return min(m["frequency_hz"] for m in d["linear"]["modes"] if m["frequency_hz"] > 1e-3)


def test_linear_off_equilibrium_is_flagged():
    d, msgs = run_model(_arm(0.01, "linear"))
    eq = _item(d, "equilibrium")
    assert eq["status"] == "fail"
    assert eq["value"] > 20                       # 角加速度 24.5 rad/s²
    assert _item(d, "stability")["status"] == "unknown"
    assert any("不是平衡点" in m and "static_then_linear" in m for m in msgs)


def test_static_then_linear_gives_equilibrium_frequency():
    d, msgs = run_model(_arm(0.01, "static_then_linear"))
    assert abs(_f1(d) / 0.933515367790661 - 1) < 1e-4
    assert _item(d, "equilibrium")["status"] == "pass"
    assert not any("不是平衡点" in m for m in msgs)


def test_stiff_arm_still_flagged():
    # 原刚度时第一阶只差 3.4e-5，看频率看不出来，但工作点照样不是平衡点
    d, _ = run_model(_arm(1.0, "linear"))
    assert _item(d, "equilibrium")["status"] == "fail"
