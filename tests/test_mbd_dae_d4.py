"""多体动力学 D4（ADR-0097 补充七）：线性化、模态、状态空间的标准题。不联网、不调用 LLM。

参考值（任一机械振动教材）：
- 有阻尼单自由度 λ = −ζωn ± iωn√(1−ζ²)
- 单摆 ω = √(g/L)；等长等质量双摆（质点）ω² = (g/L)(2 ∓ √2)
- 地面–k–m–k–m 弹簧链 ω² = (3 ∓ √5)/2 · k/m
- 悬臂梁端部集中质量 ω = √(3EI/(mL³))
- 倒立摆在顶点：λ = ±√(g/L)，不稳定
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import run as R
from tests.verification import record

G = 9.81
FIX = Path(__file__).resolve().parent / "fixtures" / "mbd-model" / "valid" / "d4_linear_plant.json"
TINY = 1e-9


def box(i, m, cm, I=TINY, w0=None):
    b = {"id": i, "mass_kg": m, "cm_mm": list(cm), "inertia_kg_m2": {"ixx": I, "iyy": I, "izz": I}}
    if w0 is not None:
        b["w0_deg_s"] = list(w0)
    return b


def model(bodies, joints=(), forces=(), analysis_=None, gravity=(0, 0, 0), measures=()):
    return {"format": "mbd-model/1", "name": "t", "bodies": list(bodies), "joints": list(joints), "forces": list(forces),
            "measures": list(measures), "analysis": analysis_ or {"type": "linear"}, "gravity_mm_s2": list(gravity)}


def freqs(data, osc_only=True):
    return [m["frequency_hz"] * 2 * math.pi for m in data["linear"]["modes"]
            if not osc_only or m["damped_frequency_hz"] > 0]


def slider(j, bi, bj, x):
    return {"id": j, "type": "translational", "body_i": bi, "body_j": bj, "point_mm": [x, 0, 0], "axis": [1, 0, 0]}


def spring(i, bi, pi, bj, pj, k, c=0.0):
    return {"id": i, "type": "spring_damper", "body_i": bi, "point_i_mm": pi, "body_j": bj, "point_j_mm": pj,
            "stiffness_n_per_mm": k, "damping_n_s_per_mm": c, "free_length_mm": abs(pj[0] - pi[0])}


def test_damped_spring_mass_eigenvalue_and_dc_gain():
    data, _ = R.run_model(json.loads(FIX.read_text())["instance"])
    lin = data["linear"]
    k, c, m = 1000.0, 10.0, 1.0
    wn, z = math.sqrt(k / m), c / (2 * math.sqrt(k * m))
    mode = lin["modes"][0]
    record(("特征值实部", "eigenvalue real part"), mode["eigenvalue"][0], -z * wn, tol=1e-6, unit="1/s", formula="−ζωn")
    record(("特征值虚部", "eigenvalue imaginary part"), mode["eigenvalue"][1], wn * math.sqrt(1 - z * z), tol=1e-6, unit="rad/s", formula="ωn√(1−ζ²)")
    assert mode["eigenvalue"][0] == pytest.approx(-z * wn, rel=1e-6)
    assert mode["eigenvalue"][1] == pytest.approx(wn * math.sqrt(1 - z * z), rel=1e-6)
    assert mode["damping_ratio"] == pytest.approx(z, rel=1e-6)
    A, B, C = np.array(lin["A"]), np.array(lin["B"]), np.array(lin["C"])
    dc = (-C @ np.linalg.solve(A, B)).item()
    assert dc == pytest.approx(1 / k * 1000, rel=1e-6)                       # 输出 mm、输入 N：1/k = 1 mm/N
    assert mode["shape"]["m"]["translation_mm"] == pytest.approx([1, 0, 0], abs=1e-9)
    assert next(v for v in data["verification"] if v["key"] == "stability")["status"] == "pass"


def test_simple_pendulum_and_inverted_pendulum():
    L = 500.0
    pend = model([box("b", 1.0, (0, 0, -L))],
                 [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [1, 0, 0]}],
                 gravity=(0, 0, -G * 1000))
    data, _ = R.run_model(pend)
    record(("单摆圆频率", "pendulum angular frequency"), freqs(data)[0], math.sqrt(G / (L / 1000)), tol=1e-6, unit="rad/s", formula="√(g/L)")
    assert freqs(data) == pytest.approx([math.sqrt(G / (L / 1000))], rel=1e-6)
    pend["bodies"][0]["cm_mm"] = [0, 0, L]
    data, _ = R.run_model(pend)
    lam = sorted(m["eigenvalue"][0] for m in data["linear"]["modes"])
    assert lam == pytest.approx([-math.sqrt(G / (L / 1000)), math.sqrt(G / (L / 1000))], rel=1e-6)
    assert next(v for v in data["verification"] if v["key"] == "stability")["status"] == "fail"


def test_double_pendulum_two_frequencies():
    L = 300.0
    data, _ = R.run_model(model(
        [box("a", 1.0, (0, 0, -L)), box("b", 1.0, (0, 0, -2 * L))],
        [{"id": "r1", "type": "revolute", "body_i": "ground", "body_j": "a", "point_mm": [0, 0, 0], "axis": [1, 0, 0]},
         {"id": "r2", "type": "revolute", "body_i": "a", "body_j": "b", "point_mm": [0, 0, -L], "axis": [1, 0, 0]}],
        gravity=(0, 0, -G * 1000)))
    g_l = G / (L / 1000)
    for n_, (w_, r_) in enumerate(zip(sorted(freqs(data)), [math.sqrt(g_l * (2 - math.sqrt(2))), math.sqrt(g_l * (2 + math.sqrt(2)))], strict=True)):
        record((f"第 {n_ + 1} 阶圆频率", f"mode {n_ + 1} angular frequency"), w_, r_, tol=1e-6, unit="rad/s", formula="√(g/L·(2 ∓ √2))")
    assert sorted(freqs(data)) == pytest.approx([math.sqrt(g_l * (2 - math.sqrt(2))), math.sqrt(g_l * (2 + math.sqrt(2)))],
                                                rel=1e-6)
    low = data["linear"]["modes"][0]["shape"]                                 # 一阶：θ2 = √2·θ1，下摆位移是上摆的 1 + √2 倍
    assert low["b"]["translation_mm"][1] / low["a"]["translation_mm"][1] == pytest.approx(1 + math.sqrt(2), rel=1e-5)


def test_two_mass_spring_chain():
    k = 1.0
    data, _ = R.run_model(model(
        [box("a", 1.0, (100, 0, 0)), box("b", 1.0, (200, 0, 0))],
        [slider("s1", "ground", "a", 100), slider("s2", "ground", "b", 200)],
        [spring("k1", "ground", [0, 0, 0], "a", [100, 0, 0], k), spring("k2", "a", [100, 0, 0], "b", [200, 0, 0], k)],
        analysis_={"type": "static_then_linear", "modes": 2}))
    km = k * 1000
    assert sorted(freqs(data)) == pytest.approx([math.sqrt((3 - math.sqrt(5)) / 2 * km), math.sqrt((3 + math.sqrt(5)) / 2 * km)],
                                                rel=1e-6)


def test_cantilever_tip_mass_frequency():
    L, d, E = 200.0, 6.0, 2e5
    I = math.pi * d ** 4 / 64
    m = 0.5
    data, _ = R.run_model(model(
        [box("tip", m, (L, 0, 0), I=1e-12)], [],
        [{"id": "beam", "type": "beam", "body_i": "ground", "body_j": "tip", "point_i_mm": [0, 0, 0], "point_j_mm": [L, 0, 0],
          "y_axis": [0, 1, 0], "youngs_modulus_mpa": E, "shear_modulus_mpa": 8e4, "area_mm2": math.pi * d * d / 4,
          "iyy_mm4": I, "izz_mm4": I, "ixx_mm4": 2 * I}],
        analysis_={"type": "linear", "modes": 2}))
    w = math.sqrt(3 * E * 1e6 * I * 1e-12 / (m * (L / 1000) ** 3))
    record(("一阶弯曲圆频率", "first bending angular frequency"), freqs(data)[0], w, tol=1e-4, unit="rad/s", formula="√(3EI/mL³)")
    assert freqs(data)[:2] == pytest.approx([w, w], rel=1e-4)              # 两个弯曲方向同频（圆截面）


def test_free_body_on_bushing_six_modes():
    m, I = 2.0, 0.01
    K, Kr = [10.0, 20.0, 40.0], [1.0, 2.0, 3.0]
    data, _ = R.run_model(model(
        [box("b", m, (0, 0, 0), I=I)], [],
        [{"id": "bu", "type": "bushing", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0],
          "stiffness_n_per_mm": K, "rot_stiffness_n_m_per_deg": Kr}]))
    ref = sorted([math.sqrt(k * 1000 / m) for k in K] + [math.sqrt(kr * 180 / math.pi / I) for kr in Kr])
    assert sorted(freqs(data)) == pytest.approx(ref, rel=1e-6)


def test_state_space_torque_input_on_pendulum():
    """单摆，输入是对转轴的力矩，输出是转角（deg）：直流增益 1/(mgL)（rad/N·m）"""
    L, m = 400.0, 2.0
    data, _ = R.run_model(model(
        [box("b", m, (0, 0, -L))],
        [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [1, 0, 0]}],
        gravity=(0, 0, -G * 1000), measures=[{"id": "th", "type": "joint_angle", "joint": "r"}],
        analysis_={"type": "linear", "plant": {"inputs": [{"id": "T", "type": "torque", "body": "b", "direction": [1, 0, 0]}],
                                               "outputs": ["th"]}}))
    lin = data["linear"]
    A, B, C = np.array(lin["A"]), np.array(lin["B"]), np.array(lin["C"])
    dc = (-C @ np.linalg.solve(A, B)).item()
    assert dc == pytest.approx(math.degrees(1 / (m * G * L / 1000)), rel=1e-6)


def test_nonsmooth_model_gets_warning():
    inst = json.loads(FIX.read_text())["instance"]
    inst["joints"][0]["friction"] = {"mu_static": 0.1, "mu_dynamic": 0.1, "stiction_speed": 1, "transition_speed": 2}
    inst["analysis"]["type"] = "linear"
    _, msgs = R.run_model(inst)
    assert any("不光滑" in s for s in msgs)


@pytest.mark.parametrize("spin", [0.0, 3000.0, -6000.0])
def test_spinning_rotor_forward_and_backward_whirl(spin):
    """刚性转子，球铰在质心，轴上两点各四根径向弹簧给倾斜刚度 kr = 4k·a²：
    It·ω² ∓ Ip·Ω·ω − kr = 0（陀螺效应把一个频率分成正进动、反进动两支；Genta《Dynamics of Rotating Systems》第 4 章）"""
    It, Ip, k, a, Lr = 0.01, 0.02, 1.0, 50.0, 100.0
    b = {"id": "rot", "mass_kg": 1.0, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": It, "iyy": It, "izz": Ip},
         "w0_deg_s": [0, 0, spin]}
    fs = []
    for zz in (a, -a):
        for gx, gy in ((Lr, 0), (-Lr, 0), (0, Lr), (0, -Lr)):
            fs.append({"id": f"k{len(fs)}", "type": "spring_damper", "body_i": "ground", "point_i_mm": [gx, gy, zz],
                       "body_j": "rot", "point_j_mm": [0, 0, zz], "stiffness_n_per_mm": k, "free_length_mm": Lr})
    data, _ = R.run_model(model([b], [{"id": "s", "type": "spherical", "body_i": "ground", "body_j": "rot", "point_mm": [0, 0, 0]}],
                                fs))
    kr = 4 * k * 1000 * (a / 1000) ** 2
    W = abs(math.radians(spin))
    r = math.sqrt((Ip * W) ** 2 + 4 * It * kr)
    ref = sorted([(Ip * W + r) / (2 * It), (-Ip * W + r) / (2 * It)])
    got = sorted(w for w in freqs(data) if w > 1e-3)
    for n_, (w_, r_) in enumerate(zip(got, ref, strict=True)):
        record((f"转速 {spin:g}°/s 时第 {n_ + 1} 个进动频率", f"whirl frequency {n_ + 1} at spin {spin:g}°/s"), w_, r_, tol=1e-6, unit="rad/s", formula="It·ω² ∓ Ip·Ω·ω − kr = 0（Genta）")
    assert got == pytest.approx(ref, rel=1e-6)
