"""多体动力学 D2（ADR-0097）：力元、运动副摩擦、间隙、测量量、IMPACT / SPLINE 的标准题。不联网、不调用 LLM。

参考值出处（任一理论力学 / 材料力学 / 机械振动教材）：
- 有阻尼单自由度自由振动 x(t) = x0·e^(−ζωn t)(cos ωd t + ζ/√(1−ζ²)·sin ωd t)
- 斜面滑块：tanθ > μs 时 a = g(sinθ − μd cosθ)；tanθ < μs 时不滑
- 转动副销轴摩擦：摩擦力矩 μ·N·R，匀减速 α = μ m g R / I
- 悬臂梁端部受力：δ = PL³/(3EI)，θ = PL²/(2EI)；扭转 φ = TL/(GJ)
- 扭簧：ωn = √(k/I)
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
from scipy.interpolate import CubicSpline

from analysis.mbd.dae import expr as X
from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R

G = 9.81
FIX = Path(__file__).resolve().parent / "fixtures" / "mbd-model" / "valid" / "d2_force_elements.json"


def box(i, m, cm, iz=1e-4, ix=None, iy=None, w0=None):
    ix = iz if ix is None else ix
    iy = iz if iy is None else iy
    b = {"id": i, "mass_kg": m, "cm_mm": list(cm), "inertia_kg_m2": {"ixx": ix, "iyy": iy, "izz": iz}}
    if w0 is not None:
        b["w0_deg_s"] = list(w0)
    return b


def model(bodies, joints=(), forces=(), analysis_=None, gravity=(0, 0, 0), measures=(), splines=()):
    m = {"format": "mbd-model/1", "name": "t", "bodies": list(bodies), "joints": list(joints), "forces": list(forces),
         "analysis": analysis_ or {"type": "dynamic", "end_time_s": 1}, "gravity_mm_s2": list(gravity)}
    if measures:
        m["measures"] = list(measures)
    if splines:
        m["splines"] = list(splines)
    return m


def slider(axis=(0, 0, 1), friction=None):
    j = {"id": "s", "type": "translational", "body_i": "ground", "body_j": "m", "point_mm": [0, 0, 0], "axis": list(axis)}
    if friction:
        j["friction"] = friction
    return j


def ver(data, key):
    return next(v for v in data["verification"] if v["key"] == key)


# ---------------------------------------------------------------- 弹簧阻尼、测量量当变量
def damped(t, x0, k, c, m):
    wn = math.sqrt(k / m)
    z = c / (2 * math.sqrt(k * m))
    wd = wn * math.sqrt(1 - z * z)
    return x0 * math.exp(-z * wn * t) * (math.cos(wd * t) + z / math.sqrt(1 - z * z) * math.sin(wd * t))


def test_damped_spring_mass_matches_closed_form():
    k, c, m = 1.0, 0.01, 1.0            # N/mm、N·s/mm、kg → 1000 N/m、10 N·s/m
    data, _ = R.run_model(model(
        [box("m", m, (0, 0, 0))], [slider()],
        [{"id": "k", "type": "spring_damper", "body_i": "ground", "point_i_mm": [0, 0, 100], "body_j": "m",
          "point_j_mm": [0, 0, 0], "stiffness_n_per_mm": k, "damping_n_s_per_mm": c, "free_length_mm": 90}],
        {"type": "dynamic", "end_time_s": 0.5, "output_steps": 50, "rtol": 1e-10, "atol": 1e-12}))
    z = np.array([p[2] for p in data["bodies"]["m"]["cm_mm"]])
    ref = np.array([10 + damped(t, -10, k * 1000, c * 1000, m) for t in data["times_s"]])
    assert np.max(np.abs(z - ref)) < 1e-6
    assert ver(data, "energy_drift")["status"] == "unknown"


def test_force_expression_can_use_measure():
    """fx = −1·x（x 为测量量 mm）等于 1 N/mm 的弹簧：ωn = √(1000/1)"""
    data, _ = R.run_model(model(
        [{**box("m", 1.0, (0, 0, 0)), "v0_mm_s": [100, 0, 0]}], [slider(axis=(1, 0, 0))],
        [{"id": "f", "type": "force", "body": "m", "point_mm": [0, 0, 0], "fx_n": "-1*x"}],
        {"type": "dynamic", "end_time_s": 0.3, "output_steps": 30, "rtol": 1e-10, "atol": 1e-12},
        measures=[{"id": "x", "type": "joint_displacement", "joint": "s"}, {"id": "v", "type": "joint_velocity", "joint": "s"}]))
    wn = math.sqrt(1000.0)
    xs = np.array(data["measures"]["x"]["values"])
    ref = np.array([100 / wn * math.sin(wn * t) for t in data["times_s"]])
    assert np.max(np.abs(xs - ref)) < 1e-6
    vs = np.array(data["measures"]["v"]["values"])
    assert np.max(np.abs(vs - np.array([100 * math.cos(wn * t) for t in data["times_s"]]))) < 1e-4
    assert data["measures"]["x"]["unit"] == "mm"


# ---------------------------------------------------------------- 摩擦
def incline(theta_deg, end, method="DOP853"):
    th = math.radians(theta_deg)
    fr = {"mu_static": 0.3, "mu_dynamic": 0.2, "stiction_speed": 1.0, "transition_speed": 2.0}
    return model([box("m", 2.0, (0, 0, 0))], [slider(axis=(1, 0, 0), friction=fr)],
                 analysis_={"type": "dynamic", "end_time_s": end, "output_steps": 20, "integrator": method,
                            "rtol": 1e-8, "atol": 1e-10},
                 gravity=(G * 1000 * math.sin(th), 0, -G * 1000 * math.cos(th)),
                 measures=[{"id": "v", "type": "joint_velocity", "joint": "s"}])


def test_block_slides_on_steep_incline_with_dynamic_friction():
    th = math.radians(30)
    data, _ = R.run_model(incline(30, 0.5))
    a = G * (math.sin(th) - 0.2 * math.cos(th))
    v_end = data["measures"]["v"]["values"][-1] / 1000
    assert v_end == pytest.approx(a * 0.5, rel=2e-4)


def test_block_sticks_on_shallow_incline():
    data, _ = R.run_model(incline(10, 0.2, method="Radau"))
    assert max(abs(v) for v in data["measures"]["v"]["values"]) < 1.0       # 不超过 stiction_speed（mm/s）
    assert abs(data["bodies"]["m"]["cm_mm"][-1][0]) < 0.2


def test_pin_friction_spins_flywheel_down_linearly():
    m, I, R_mm, mu = 1.0, 0.01, 10.0, 0.1
    w0 = 360.0
    data, _ = R.run_model(model(
        [box("disc", m, (0, 0, 0), iz=0.02, ix=I, iy=0.02, w0=(w0, 0, 0))],
        [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "disc", "point_mm": [0, 0, 0], "axis": [1, 0, 0],
          "friction": {"mu_static": 0.15, "mu_dynamic": mu, "stiction_speed": 1, "transition_speed": 2,
                       "pin_radius_mm": R_mm}}],
        analysis_={"type": "dynamic", "end_time_s": 1.0, "output_steps": 10, "rtol": 1e-10, "atol": 1e-12},
        gravity=(0, 0, -G * 1000)))
    alpha = mu * m * G * R_mm / 1000 / I
    w_end = math.radians(data["bodies"]["disc"]["w_deg_s"][-1][0])
    assert w_end == pytest.approx(math.radians(w0) - alpha * 1.0, rel=1e-6)


# ---------------------------------------------------------------- 衬套、梁
def test_bushing_static_deflection_is_force_over_stiffness():
    data, _ = R.run_model(model(
        [box("m", 1.0, (0, 0, 0))], [],
        [{"id": "b", "type": "bushing", "body_i": "ground", "body_j": "m", "point_mm": [0, 0, 0],
          "stiffness_n_per_mm": [10, 20, 50], "rot_stiffness_n_m_per_deg": [1, 1, 1]},
         {"id": "F", "type": "force", "body": "m", "point_mm": [0, 0, 0], "fx_n": 10}],
        {"type": "static"}, gravity=(0, 0, -G * 1000)))
    x, y, z = data["bodies"]["m"]["cm_mm"][0]
    assert x == pytest.approx(1.0, rel=1e-6)
    assert z == pytest.approx(-G / 50, rel=1e-6)
    assert abs(y) < 1e-9


def rot_angle(p):
    return 2 * math.asin(min(1.0, float(np.linalg.norm(p[1:]))))


@pytest.mark.parametrize("load", ["bend_z", "bend_y", "torsion"])
def test_cantilever_beam_matches_beam_theory(load):
    L, d, E, Gs = 100.0, 10.0, 2e5, 8e4
    A, I, J = math.pi * d * d / 4, math.pi * d ** 4 / 64, math.pi * d ** 4 / 32
    P, T = 1.0, 1.0
    f = {"id": "F", "type": "force", "body": "tip", "point_mm": [L, 0, 0]}
    if load == "bend_z":
        f["fz_n"] = P
    elif load == "bend_y":
        f["fy_n"] = P
    else:
        f = {"id": "T", "type": "torque", "body": "tip", "tx_n_m": T}
    data, _ = R.run_model(model(
        [box("tip", 0.1, (L, 0, 0), iz=1e-6)], [],
        [{"id": "beam", "type": "beam", "body_i": "ground", "body_j": "tip", "point_i_mm": [0, 0, 0], "point_j_mm": [L, 0, 0],
          "y_axis": [0, 1, 0], "youngs_modulus_mpa": E, "shear_modulus_mpa": Gs, "area_mm2": A,
          "iyy_mm4": I, "izz_mm4": I, "ixx_mm4": J}, f],
        {"type": "static"}))
    pos = data["bodies"]["tip"]["cm_mm"][0]
    p = np.array(data["bodies"]["tip"]["euler_parameters"][0])
    if load == "torsion":
        assert rot_angle(p) == pytest.approx(T * 1000 * L / (Gs * J), rel=1e-3)
        assert abs(pos[1]) + abs(pos[2]) < 1e-8
        return
    k = 2 if load == "bend_z" else 1
    assert pos[k] == pytest.approx(P * L ** 3 / (3 * E * I), rel=1e-3)
    assert rot_angle(p) == pytest.approx(P * L ** 2 / (2 * E * I), rel=1e-3)


# ---------------------------------------------------------------- 扭簧、间隙
def test_rotational_spring_frequency_and_energy():
    k_deg, I, w0 = 0.01, 1e-3, 10.0
    data, _ = R.run_model(model(
        [box("r", 1.0, (0, 0, 0), iz=I, w0=(0, 0, w0))],
        [{"id": "j", "type": "revolute", "body_i": "ground", "body_j": "r", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
        [{"id": "k", "type": "rotational_spring_damper", "body_i": "ground", "body_j": "r", "axis": [0, 0, 1],
          "stiffness_n_m_per_deg": k_deg}],
        {"type": "dynamic", "end_time_s": 0.5, "output_steps": 25, "rtol": 1e-10, "atol": 1e-12},
        measures=[{"id": "a", "type": "joint_angle", "joint": "j"}]))
    wn = math.sqrt(k_deg * 180 / math.pi / I)
    ang = np.array(data["measures"]["a"]["values"])
    ref = np.array([w0 / wn * math.sin(wn * t) for t in data["times_s"]])
    assert np.max(np.abs(ang - ref)) < 1e-6
    assert ver(data, "energy_drift")["status"] == "pass"


def test_revolute_clearance_settles_at_gap_plus_hertz_penetration():
    c, k, e = 0.05, 1e4, 1.5
    data, _ = R.run_model(model(
        [box("w", 1.0, (0, 0, 0), ix=1e-3)],
        [{"id": "j", "type": "revolute", "body_i": "ground", "body_j": "w", "point_mm": [0, 0, 0], "axis": [1, 0, 0],
          "clearance": {"radial_mm": c, "stiffness_n_per_mm": k, "exponent": e, "damping_n_s_per_mm": 2.0}}],
        [{"id": "rs", "type": "rotational_spring_damper", "body_i": "ground", "body_j": "w", "axis": [1, 0, 0],
          "stiffness_n_m_per_deg": 1.0}],
        {"type": "dynamic", "end_time_s": 0.1, "output_steps": 10, "integrator": "Radau", "rtol": 1e-7, "atol": 1e-11},
        gravity=(0, 0, -G * 1000)))
    z_end = data["bodies"]["w"]["cm_mm"][-1][2]
    assert z_end == pytest.approx(-(c + (G / k) ** (1 / e)), rel=1e-3)


# ---------------------------------------------------------------- IMPACT、SPLINE
def test_impact_values_and_derivatives():
    f = X.compile_expr("IMPACT(time, -2, 1, 100, 1.5, 3, 0.1)")
    assert f(1.2) == 0.0
    t = 0.95                                  # 在 d 过渡区内：100·0.05^1.5 − STEP(..)·(−2)
    s = (t - 0.9) / 0.1
    step = 3 * s * s * (3 - 2 * s)
    assert f(t) == pytest.approx(100 * 0.05 ** 1.5 + 2 * step, rel=1e-12)
    v, d, _ = f.jet(0.5)
    h = 1e-6
    assert d == pytest.approx((f(0.5 + h) - f(0.5 - h)) / (2 * h), rel=1e-6)
    assert v == pytest.approx(100 * 0.5 ** 1.5 + 6, rel=1e-12)


def test_spline_matches_scipy_and_has_exact_derivatives():
    xs, ys = [0, 0.25, 0.5, 0.75, 1.0], [0, 1, 0.5, 2, 1]
    sp = X.Spline(xs, ys, "cubic")
    f = X.compile_expr("2*SPLINE(cam, time)", splines={"cam": sp})
    ref = CubicSpline(xs, ys)
    for t in (0.1, 0.4, 0.9):
        v, d, dd = f.jet(t)
        assert v == pytest.approx(2 * ref(t), rel=1e-12)
        assert d == pytest.approx(2 * ref(t, 1), rel=1e-10)
        assert dd == pytest.approx(2 * ref(t, 2), rel=1e-10)
    with pytest.raises(X.ExprError):
        X.compile_expr("SPLINE(nope, time)", splines={"cam": sp})


def test_measure_variable_not_allowed_in_motion():
    m = model([box("m", 1.0, (0, 0, 0))], [slider()], measures=[{"id": "x", "type": "joint_displacement", "joint": "s"}])
    m["motions"] = [{"id": "d", "joint": "s", "dof": "translation", "function": "x*0"}]
    with pytest.raises(M.ModelError):
        M.build(m)


def test_full_d2_fixture_runs():
    inst = json.loads(FIX.read_text())["instance"]
    inst["analysis"] = {**inst.get("analysis", {}), "type": "dynamic", "end_time_s": 0.05, "output_steps": 5,
                        "integrator": "Radau"}
    data, _ = R.run_model(inst)
    assert ver(data, "constraint_residual")["status"] == "pass"
    assert data["measures"]
