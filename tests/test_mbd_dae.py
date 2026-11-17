"""多体动力学精确求解器（ADR-0097 D1）：标准题与核查。不联网、不调用 LLM。

参考值出处：
- 物理摆大摆角周期 T = 4√(I_O / (m g L)) · K(sin(θ0/2))（K 为第一类完全椭圆积分；任一理论力学教材）
- 曲柄滑块、四杆机构位置（几何关系）、万向节传动比 ω2/ω1 在 cos β 与 1/cos β 之间（《机械原理》）
- Andrews 挤压机构：Test Set for IVP Solvers II.13（见 tests/mbd_bench/andrews.py）
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy.special import ellipk

import analysis
from analysis.mbd.dae import expr as X
from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R
from analysis.mbd.dae import solve as S

sys.path.insert(0, str(Path(__file__).resolve().parent / "mbd_bench"))
import andrews

G = 9.81


def box(i, m, cm, iz=1e-4, ix=None):
    ix = iz if ix is None else ix
    return {"id": i, "mass_kg": m, "cm_mm": list(cm), "inertia_kg_m2": {"ixx": ix, "iyy": ix, "izz": iz}}


def model(bodies, joints=(), motions=(), forces=(), analysis_=None, gravity=None, requests=()):
    m = {"format": "mbd-model/1", "name": "t", "bodies": list(bodies), "joints": list(joints), "motions": list(motions),
         "forces": list(forces), "requests": list(requests), "analysis": analysis_ or {"type": "dynamic", "end_time_s": 1}}
    if gravity is not None:
        m["gravity_mm_s2"] = gravity
    return m


def rev(i, a, b, p, axis=(0, 0, 1)):
    return {"id": i, "type": "revolute", "body_i": a, "body_j": b, "point_mm": list(p), "axis": list(axis)}


def zrot(q, k):
    return np.unwrap([2 * math.atan2(x[7 * k + 6], x[7 * k + 3]) for x in q])


# ---------------------------------------------------------------- 表达式
def test_expression_values_and_exact_derivatives():
    f = X.compile_expr("360*time + 10*sin(2*PI*time) + STEP(time, 0.2, 0, 0.6, 30) + 2^time")
    for t in (0.1, 0.35, 0.7):
        v, d, dd = f.jet(t)
        h = 1e-5
        assert v == pytest.approx(f(t))
        assert d == pytest.approx((f(t + h) - f(t - h)) / (2 * h), rel=1e-7)
        assert dd == pytest.approx((f(t + h) - 2 * f(t) + f(t - h)) / h ** 2, rel=1e-4)
    assert X.compile_expr("STEP5(time,0,0,1,1)")(0.5) == pytest.approx(0.5)
    assert X.compile_expr("HAVSIN(time,0,0,1,2)")(0.5) == pytest.approx(1.0)
    assert X.compile_expr("atan2(1, 1)*RTOD")(0) == pytest.approx(45)


@pytest.mark.parametrize("bad", ["__import__('os')", "time.real", "foo(1)", "sin(1,2)", "1+", "STEP(time,1,0,0,1)"])
def test_expression_rejects_bad_input(bad):
    with pytest.raises(X.ExprError):
        X.compile_expr(bad)(0.5)


# ---------------------------------------------------------------- 雅可比、加速度右端（解析 vs 射流 / 差分）
def _all_joints_model():
    bodies = [box(f"b{k}", 1 + k * 0.1, (100 * k, 10 * k, -5 * k), iz=1e-3 + 1e-4 * k) for k in range(1, 7)]
    joints = [rev("r", "ground", "b1", (50, 0, 0), (0.2, 0.3, 1)),
              {"id": "t", "type": "translational", "body_i": "b1", "body_j": "b2", "point_mm": [150, 15, -7], "axis": [1, 0.5, 0]},
              {"id": "c", "type": "cylindrical", "body_i": "b2", "body_j": "b3", "point_mm": [250, 25, -12], "axis": [0, 1, 0.3]},
              {"id": "s", "type": "spherical", "body_i": "b3", "body_j": "b4", "point_mm": [350, 35, -17]},
              {"id": "u", "type": "universal", "body_i": "b4", "body_j": "b5", "point_mm": [450, 45, -22],
               "axis_i": [0, 1, 0], "axis_j": [0, 0, 1]},
              {"id": "f", "type": "fixed", "body_i": "b5", "body_j": "b6", "point_mm": [550, 55, -27]}]
    motions = [{"id": "m1", "joint": "r", "dof": "rotation", "function": "30*sin(3*time) + 100*time^2"},
               {"id": "m2", "joint": "c", "dof": "translation", "function": "5*STEP5(time,0,0,1,1)"}]
    return model(bodies, joints, motions)


def test_jacobian_and_gamma_match_jets_and_differences():
    s = M.build(_all_joints_model())
    rng = np.random.default_rng(7)
    q = s.q0() + rng.normal(scale=0.02, size=s.n)
    qd = rng.normal(size=s.n)
    t = 0.37
    J = s.jac(q, t)
    d = np.array([j.d for j in s.phi_jets(q, qd, t, 0.0)])
    assert np.max(np.abs(J @ qd - d)) < 1e-12
    # Φ(q + ε q̇, t + ε) 的二阶导（q̈ = 0）= −γ
    h = 1e-4
    f = [s.phi(q + e * h * qd, t + e * h) for e in (-1, 0, 1)]
    second = (f[2] - 2 * f[1] + f[0]) / h ** 2
    assert np.max(np.abs(second + s.gamma(q, qd, t))) < 1e-4 * max(1.0, np.max(np.abs(second)))
    nu = s.nu(q, t)
    dphi_dt = (s.phi(q, t + h) - s.phi(q, t - h)) / (2 * h)
    assert np.max(np.abs(nu + dphi_dt)) < 1e-6


# ---------------------------------------------------------------- 动力学
def test_pendulum_large_amplitude_period():
    L, m, iz = 0.5, 1.0, 1e-5
    md = model([box("bob", m, (L * 1000, 0, 0), iz)], [rev("O", "ground", "bob", (0, 0, 0), (0, 1, 0))],
               gravity=[0, 0, -9810], analysis_={"type": "dynamic", "end_time_s": 3.5, "output_steps": 700, "rtol": 1e-10,
                                                 "atol": 1e-12})
    data, _ = R.run_model(md)
    q = np.array([np.r_[np.zeros(3), e] for e in data["bodies"]["bob"]["euler_parameters"]])
    th = np.unwrap([2 * math.atan2(x[5], x[3]) for x in q])     # 绕 y 转，从水平向下摆到 π
    t = np.array(data["times_s"])
    half = math.pi / 2
    up = [t[i] + (half - th[i]) * (t[i + 1] - t[i]) / (th[i + 1] - th[i]) for i in range(len(th) - 1)
          if (th[i] - half) * (th[i + 1] - half) < 0]
    period = 2 * float(np.mean(np.diff(up)))
    i_o = m * L * L + iz
    theory = 4 * math.sqrt(i_o / (m * G * L)) * ellipk(math.sin(math.pi / 4) ** 2)
    assert period == pytest.approx(theory, rel=1e-5)
    v = {x["key"]: x for x in data["verification"]}
    assert v["energy_drift"]["status"] == "pass" and v["constraint_residual"]["status"] == "pass"


def test_double_pendulum_conserves_energy_and_matches_mujoco():
    mujoco = pytest.importorskip("mujoco")
    L, m = 0.3, 1.0
    md = model([box("a", m, (L * 1000, 0, 0), 1e-4), box("b", m, (2 * L * 1000, 0, 0), 1e-4)],
               [rev("O", "ground", "a", (0, 0, 0), (0, 1, 0)), rev("P", "a", "b", (L * 1000, 0, 0), (0, 1, 0))],
               gravity=[0, 0, -9810], analysis_={"type": "dynamic", "end_time_s": 0.6, "output_steps": 60, "rtol": 1e-10,
                                                 "atol": 1e-12})
    data, _ = R.run_model(md)
    v = {x["key"]: x for x in data["verification"]}
    assert v["energy_drift"]["value"] < 1e-8
    # 同一个双摆在 MuJoCo 里（质点挂在杆端，铰链绕 y）
    xml = (f'<mujoco><option timestep="0.00005" integrator="RK4" gravity="0 0 -9.81"/><worldbody>'
           f'<body name="a"><joint name="j1" type="hinge" axis="0 1 0"/>'
           f'<inertial pos="{L} 0 0" mass="{m}" diaginertia="1e-4 1e-4 1e-4"/>'
           f'<body name="b" pos="{L} 0 0"><joint name="j2" type="hinge" axis="0 1 0"/>'
           f'<inertial pos="{L} 0 0" mass="{m}" diaginertia="1e-4 1e-4 1e-4"/></body></body></worldbody></mujoco>')
    mm = mujoco.MjModel.from_xml_string(xml)
    dd = mujoco.MjData(mm)
    while dd.time < 0.6 - 1e-9:
        mujoco.mj_step(mm, dd)
    pa = [np.r_[np.zeros(3), e] for e in data["bodies"]["a"]["euler_parameters"]]
    pb = [np.r_[np.zeros(3), e] for e in data["bodies"]["b"]["euler_parameters"]]
    th1 = np.unwrap([2 * math.atan2(x[5], x[3]) for x in pa])[-1]
    th2 = np.unwrap([2 * math.atan2(x[5], x[3]) for x in pb])[-1]
    assert th1 == pytest.approx(dd.qpos[0], abs=1e-3)
    assert th2 - th1 == pytest.approx(dd.qpos[1], abs=1e-3)


def test_andrews_squeezing_mechanism_reference_solution():
    """IFToMM / Hairer–Wanner 公认考题：7 个构件、10 个转动副（空间写法，冗余约束 9 条由程序删掉），t = 0.03 s 的参考解"""
    md = andrews.model(steps=30, rtol=1e-8, atol=1e-10)
    s = M.build(md)
    rec, info = S.dynamic(s, andrews.REF_T, 30, rtol=1e-8, atol=1e-10)
    assert info["dof"] == 1 and len(info["redundant"]) == 9
    got = andrews.angles(rec.q)
    for g, r in zip(got, andrews.REF, strict=True):
        assert g == pytest.approx(r, rel=1e-6, abs=1e-7)
    assert max(rec.resid) < 1e-9


# ---------------------------------------------------------------- 运动学（逆动力学）
def _slider_crank(F=0.0, rpm=120):
    r, l = 40.0, 140.0
    return model([box("crank", 0.3, (r / 2, 0, 0), 4e-5), box("rod", 0.6, ((r + r + l) / 2, 0, 0), 1e-3),
                  box("slider", 1.2, (r + l, 0, 0), 2e-4)],
                 [rev("A", "ground", "crank", (0, 0, 0)), rev("B", "crank", "rod", (r, 0, 0)),
                  rev("C", "rod", "slider", (r + l, 0, 0)),
                  {"id": "D", "type": "translational", "body_i": "ground", "body_j": "slider", "point_mm": [r + l, 0, 0],
                   "axis": [1, 0, 0]}],
                 [{"id": "drive", "joint": "A", "dof": "rotation", "speed": rpm}],
                 [{"id": "F", "type": "force", "body": "slider", "point_mm": [r + l, 0, 0], "fx_n": -F}] if F else [],
                 {"type": "kinematic", "end_time_s": 0.5, "output_steps": 400})


def test_slider_crank_position_and_power_balance():
    F = 150.0
    data, msgs = R.run_model(_slider_crank(F))
    r, l = 0.04, 0.14
    t = np.array(data["times_s"])
    w = 120 * 2 * math.pi / 60
    x = np.array(data["bodies"]["slider"]["cm_mm"])[:, 0] / 1000
    th = w * t
    assert np.max(np.abs(x - (r * np.cos(th) + np.sqrt(l * l - (r * np.sin(th)) ** 2)))) < 1e-10
    tau = np.array(data["motions"]["drive"]["effort"])
    ke = np.array(data["energy"]["kinetic_j"])
    v = np.array(data["bodies"]["slider"]["v_mm_s"])[:, 0] / 1000
    dke = np.gradient(ke, t, edge_order=2)
    p_in = tau * w
    p_need = dke + F * v          # 外力 −F 沿 x：克服它要的功率 F·v
    err = np.abs(p_in - p_need)[5:-5]
    assert np.max(err) < 1e-3 * np.max(np.abs(p_in))
    assert data["redundant_constraints"] and msgs   # 平面机构空间写法有冗余约束，结果里报出来


def test_four_bar_follower_angle_matches_geometry():
    a, b, c, d = 40.0, 120.0, 80.0, 100.0           # 曲柄、连杆、摇杆、机架（mm）
    th0 = math.radians(60)
    Bx, By = a * math.cos(th0), a * math.sin(th0)
    # 初始摇杆端点 C：圆 (B, b) 与圆 (D, c) 的交点（取上方）
    Dx = d
    dd = math.hypot(Dx - Bx, -By)
    al = math.acos((b * b + dd * dd - c * c) / (2 * b * dd))
    base = math.atan2(-By, Dx - Bx)
    Cx, Cy = Bx + b * math.cos(base + al), By + b * math.sin(base + al)
    if Cy < 0:
        Cx, Cy = Bx + b * math.cos(base - al), By + b * math.sin(base - al)
    md = model([box("crank", 0.1, (Bx / 2, By / 2, 0)), box("coupler", 0.2, ((Bx + Cx) / 2, (By + Cy) / 2, 0)),
                box("rocker", 0.15, ((Cx + Dx) / 2, Cy / 2, 0))],
               [rev("A", "ground", "crank", (0, 0, 0)), rev("B", "crank", "coupler", (Bx, By, 0)),
                rev("C", "coupler", "rocker", (Cx, Cy, 0)), rev("D", "ground", "rocker", (Dx, 0, 0))],
               [{"id": "m", "joint": "A", "dof": "rotation", "speed": 60}], analysis_={"type": "kinematic", "end_time_s": 1,
                                                                                    "output_steps": 72})
    data, _ = R.run_model(md)
    e = [np.r_[np.zeros(3), x] for x in data["bodies"]["rocker"]["euler_parameters"]]
    phi = zrot(e, 0)
    phi0 = math.atan2(Cy, Cx - Dx)
    for k, tt in enumerate(data["times_s"]):
        th = th0 + 2 * math.pi * tt
        bx, by = a * math.cos(th), a * math.sin(th)
        # 摇杆角：解 |C − B| = b，C = D + c(cos φ, sin φ)，取与上一步连续的那支
        A_ = 2 * c * (Dx - bx)
        B_ = -2 * c * by
        C_ = (Dx - bx) ** 2 + by ** 2 + c * c - b * b
        rr = math.hypot(A_, B_)
        g = math.atan2(B_, A_)
        sols = [g + math.acos(-C_ / rr), g - math.acos(-C_ / rr)]
        want = phi0 + phi[k]
        best = min(sols, key=lambda s_: abs(math.remainder(s_ - want, 2 * math.pi)))
        assert abs(math.remainder(best - want, 2 * math.pi)) < 1e-9


def test_universal_joint_speed_ratio_bounds():
    beta = math.radians(30)
    ax2 = (math.cos(beta), math.sin(beta), 0)
    md = model([box("in", 0.5, (-50, 0, 0), 1e-4), box("out", 0.5, (50 * ax2[0], 50 * ax2[1], 0), 1e-4)],
               [rev("A", "ground", "in", (-100, 0, 0), (1, 0, 0)), rev("B", "ground", "out", (100 * ax2[0], 100 * ax2[1], 0), ax2),
                {"id": "U", "type": "universal", "body_i": "in", "body_j": "out", "point_mm": [0, 0, 0], "axis_i": [0, 1, 0],
                 "axis_j": [0, 0, 1]}],
               [{"id": "m", "joint": "A", "dof": "rotation", "speed": 60}],
               analysis_={"type": "kinematic", "end_time_s": 1, "output_steps": 360})
    data, _ = R.run_model(md)
    w2 = np.array(data["bodies"]["out"]["w_deg_s"]) @ np.array(ax2)
    ratio = w2 / 360.0
    assert ratio.max() == pytest.approx(1 / math.cos(beta), rel=1e-4)
    assert ratio.min() == pytest.approx(math.cos(beta), rel=1e-4)


def test_kinematic_needs_zero_dof():
    md = model([box("bob", 1, (100, 0, 0))], [rev("O", "ground", "bob", (0, 0, 0))],
               analysis_={"type": "kinematic", "end_time_s": 1})
    with pytest.raises(S.SolveError, match="自由度为 0"):
        R.run_model(md)


# ---------------------------------------------------------------- 静平衡
def test_static_spring_mass_and_pendulum_with_side_force():
    k, m = 2.0, 3.0                                  # N/mm、kg
    md = model([box("m", m, (0, 0, 0))],
               [{"id": "T", "type": "translational", "body_i": "ground", "body_j": "m", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
               forces=[{"id": "k", "type": "spring_damper", "body_i": "ground", "point_i_mm": [0, 0, 100], "body_j": "m",
                        "point_j_mm": [0, 0, 0], "stiffness_n_per_mm": k}],
               gravity=[0, 0, -9810], analysis_={"type": "static"})
    data, _ = R.run_model(md)
    assert data["bodies"]["m"]["cm_mm"][0][2] == pytest.approx(-m * G / k, rel=1e-9)

    L, F = 200.0, 4.0
    md = model([box("bob", m, (0, 0, -L))], [rev("O", "ground", "bob", (0, 0, 0), (0, 1, 0))],
               forces=[{"id": "F", "type": "force", "body": "bob", "point_mm": [0, 0, -L], "fx_n": F}],
               gravity=[0, 0, -9810], analysis_={"type": "static"})
    data, _ = R.run_model(md)
    x, _, z = data["bodies"]["bob"]["cm_mm"][0]
    assert math.atan2(x, -z) == pytest.approx(math.atan(F / (m * G)), rel=1e-9)


# ---------------------------------------------------------------- 模型出错、对外接口
def test_model_errors_are_reported():
    with pytest.raises(M.ModelError, match="schema"):
        M.build({"format": "mbd-model/1", "name": "x", "bodies": [], "analysis": {"type": "static"}})
    md = model([box("bob", 1, (100, 0, 0))], [rev("O", "ground", "bob", (0, 0, 0))],
               [{"id": "m", "joint": "O", "dof": "rotation", "function": "10 + time"}])
    with pytest.raises(M.ModelError, match="t = 0"):
        M.build(md)
    md = model([box("bob", 1, (100, 0, 0))], [rev("O", "ground", "bob", (0, 0, 0))],
               [{"id": "m", "joint": "O", "dof": "translation", "speed": 1}])
    with pytest.raises(M.ModelError, match="不能加"):
        M.build(md)


def test_run_through_analysis_registry_without_mujoco_requirement():
    res = analysis.run("mbd", {"model": _slider_crank()})
    assert res["status"] == "ok", res["messages"]
    assert res["data"]["motions"]["drive"]["peak"] > 0
    assert analysis.get("mbd").needs({"model": _slider_crank()}) == ["numpy", "scipy"]
    bad = analysis.run("mbd", {"model": {**_slider_crank(), "analysis": {"type": "dynamic", "end_time_s": 1}}})
    assert bad["status"] == "failed" and "运动学" in bad["messages"][0]
