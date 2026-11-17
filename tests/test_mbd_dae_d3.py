"""多体动力学 D3（ADR-0097 补充五）：接触与齿轮啮合的标准题。不联网、不调用 LLM。

参考值出处：
- Hertz 碰撞：最大压入 δmax = (5mv²/4k)^(2/5)，接触时间 2.9432·δmax/v，无阻尼时回弹速度 = 来时速度（Johnson《Contact Mechanics》§11.4）
- 球带初速、无转动在平地上：滑动阶段后纯滚，v = 5/7·v0，滑动时间 2v0/(7μg)（理论力学，刚体平面运动）
- 偏心圆凸轮 + 平底从动件：升程 R + e·cos ωt；接触力 N = mg + F_mid + (k_s·e − m·e·ω²)·cos ωt，
  ω > √((mg + F_mid + k_s·e)/(m·e)) 时在顶点脱离（《机械原理》凸轮机构动力学）
- 直齿外啮合：转速比 −z1/z2，稳态啮合力 T/r_b2，主动轮力矩 T·z1/z2；侧隙与啮合刚度的空程 (b + 2F/k)/r_b2
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import contact as C
from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R

G = 9.81
FIX = Path(__file__).resolve().parent / "fixtures" / "mbd-model" / "valid" / "d3_contacts.json"


def box(i, m, cm, iz=1e-4, ix=None, iy=None, w0=None, v0=None):
    b = {"id": i, "mass_kg": m, "cm_mm": list(cm),
         "inertia_kg_m2": {"ixx": iz if ix is None else ix, "iyy": iz if iy is None else iy, "izz": iz}}
    if w0 is not None:
        b["w0_deg_s"] = list(w0)
    if v0 is not None:
        b["v0_mm_s"] = list(v0)
    return b


def model(bodies, joints=(), forces=(), geometries=(), contacts=(), analysis_=None, gravity=(0, 0, 0), motions=()):
    return {"format": "mbd-model/1", "name": "t", "bodies": list(bodies), "joints": list(joints), "forces": list(forces),
            "motions": list(motions), "geometries": list(geometries), "contacts": list(contacts),
            "analysis": analysis_ or {"type": "dynamic", "end_time_s": 1}, "gravity_mm_s2": list(gravity)}


FLOOR = {"id": "floor", "body": "ground", "type": "plane", "point_mm": [0, 0, 0], "normal": [0, 0, 1]}


# ---------------------------------------------------------------- 几何配对（纯几何）
def test_pair_geometry_depths():
    s1 = {"c": np.zeros(3), "R": 0.01}
    s2 = {"c": np.array([0.019, 0, 0]), "R": 0.01}
    (_, _, n, d), = C.sphere_sphere(s1, s2)
    assert d == pytest.approx(0.001) and n == pytest.approx([1, 0, 0])
    pl = {"p": np.zeros(3), "n": np.array([0, 0, 1.0]), "x": np.array([1.0, 0, 0]), "half": np.array([0.01, 0.01])}
    assert C.plane_sphere(pl, {"c": np.array([0, 0, 0.009]), "R": 0.01})[0][3] == pytest.approx(0.001)
    assert C.plane_sphere(pl, {"c": np.array([0.02, 0, 0.009]), "R": 0.01}) == []      # 在有限平面外
    cy = {"c": np.zeros(3), "a": np.array([0, 0, 1.0]), "R": 0.01, "L": 0.02}
    assert C.cylinder_sphere(cy, {"c": np.array([0.015, 0, 0]), "R": 0.006})[0][3] == pytest.approx(0.001)
    rim = C.cylinder_sphere(cy, {"c": np.array([0.013, 0, 0.014]), "R": 0.006})       # 对圆边：距离 5 mm
    assert rim[0][3] == pytest.approx(0.001)
    lying = {"c": np.array([0, 0, 0.0099]), "a": np.array([1.0, 0, 0]), "R": 0.01, "L": 0.04}
    cs = C.plane_cylinder({**pl, "half": None}, lying)
    assert len(cs) == 2 and all(c[3] == pytest.approx(1e-4) for c in cs)


def test_curve_closest_point_on_circle_is_exact():
    pts = [[0.03 * math.cos(a), 0.03 * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 73)[:-1]]
    cv = C.Curve("c", -1, np.zeros(3), [0, 0, 1], [1, 0, 0], pts).placed(np.zeros(3), np.eye(3))
    (_, _, n, d), = C.curve_sphere(cv, {"c": np.array([0.02, 0.025, 0]), "R": 0.01})
    r = math.hypot(0.02, 0.025)
    assert d == pytest.approx(0.03 + 0.01 - r, abs=1e-7)          # 72 点三次样条逼近圆，误差 < 0.1 µm
    assert n == pytest.approx(np.array([0.02, 0.025, 0]) / r, abs=1e-5)


def test_unsupported_pair_is_rejected():
    m = model([box("a", 1, (0, 0, 50))],
              geometries=[{"id": "c1", "body": "a", "type": "cylinder", "center_mm": [0, 0, 50], "axis": [0, 0, 1],
                           "radius_mm": 5, "length_mm": 10},
                          {"id": "c2", "body": "ground", "type": "cylinder", "center_mm": [0, 0, 0], "axis": [0, 0, 1],
                           "radius_mm": 5, "length_mm": 10}],
              contacts=[{"id": "x", "geometry_i": "c1", "geometry_j": "c2", "stiffness_n_per_mm": 1}])
    with pytest.raises(M.ModelError, match="暂不支持"):
        M.build(m)


# ---------------------------------------------------------------- Hertz 落球
def drop(damping=0.0, steps=2000):
    m, R, v, k = 0.1, 10.0, 1000.0, 1e4
    data, _ = R_run(model([box("ball", m, (0, 0, R + 0.5), v0=(0, 0, -v))],
                          geometries=[FLOOR, {"id": "s", "body": "ball", "type": "sphere", "center_mm": [0, 0, R + 0.5],
                                              "radius_mm": R}],
                          contacts=[{"id": "c", "geometry_i": "floor", "geometry_j": "s", "stiffness_n_per_mm": k,
                                     "exponent": 1.5, "damping_n_s_per_mm": damping, "penetration_mm": 1e-3}],
                          analysis_={"type": "dynamic", "end_time_s": 0.0016, "output_steps": steps, "rtol": 1e-10,
                                     "atol": 1e-13}))
    return data, m, R, v, k


def R_run(m):
    return R.run_model(m)


def test_hertz_ball_impact_penetration_duration_and_rebound():
    data, m, R, v, k = drop()
    z = np.array([p[2] for p in data["bodies"]["ball"]["cm_mm"]])
    k_si, v_si = k * 1000 ** 1.5, v / 1000
    dmax = (5 * m * v_si ** 2 / (4 * k_si)) ** 0.4
    assert (R - z.min()) / 1000 == pytest.approx(dmax, rel=1e-3)
    t = np.array(data["times_s"])
    on = np.array(data["contacts"]["c"]["normal_force_n"]) > 0
    dt = t[1] - t[0]
    assert on.sum() * dt == pytest.approx(2.9432 * dmax / v_si, rel=1e-2)
    assert data["bodies"]["ball"]["v_mm_s"][-1][2] == pytest.approx(v, rel=1e-6)
    assert max(data["contacts"]["c"]["normal_force_n"]) == pytest.approx(k_si * dmax ** 1.5, rel=2e-3)


def test_damped_impact_loses_energy():
    data, *_ = drop(damping=0.05, steps=200)
    v_out = data["bodies"]["ball"]["v_mm_s"][-1][2]
    assert 0 < v_out < 1000 * 0.98


# ---------------------------------------------------------------- 滑动转纯滚
def test_sliding_ball_ends_rolling_at_five_sevenths():
    m, Rr, v0, k, mu = 1.0, 20.0, 1000.0, 1e5, 0.2
    I = 0.4 * m * (Rr / 1000) ** 2
    d0 = (m * G / k) ** (2 / 3)                    # mm（k 单位 N/mm^1.5）
    data, _ = R.run_model(model(
        [box("ball", m, (0, 0, Rr - d0), iz=I, v0=(v0, 0, 0))],
        geometries=[FLOOR, {"id": "s", "body": "ball", "type": "sphere", "center_mm": [0, 0, Rr - d0], "radius_mm": Rr}],
        contacts=[{"id": "c", "geometry_i": "floor", "geometry_j": "s", "stiffness_n_per_mm": k, "damping_n_s_per_mm": 1.0,
                   "friction": {"mu_static": 0.3, "mu_dynamic": mu, "stiction_speed_mm_s": 1, "transition_speed_mm_s": 2}}],
        analysis_={"type": "dynamic", "end_time_s": 0.25, "output_steps": 25, "rtol": 1e-8, "atol": 1e-11},
        gravity=(0, 0, -G * 1000)))
    t_slip = 2 * v0 / 1000 / (7 * mu * G)
    vx = [v[0] for v in data["bodies"]["ball"]["v_mm_s"]]
    assert vx[-1] == pytest.approx(5 / 7 * v0, rel=1e-3)
    wy = data["bodies"]["ball"]["w_deg_s"][-1][1]
    assert math.radians(wy) * Rr == pytest.approx(vx[-1], rel=1e-3)          # 纯滚：v = ωR
    k_mid = int(0.5 * t_slip / 0.01)                                           # 滑动阶段中点：v = v0 − μg t
    assert vx[k_mid] == pytest.approx(v0 - mu * G * 1000 * data["times_s"][k_mid], rel=2e-3)


# ---------------------------------------------------------------- 凸轮从动件跳动
CAM_R, CAM_E, KS, FMID, MF, KC = 30.0, 5.0, 1.0, 5.0, 0.2, 2e3


def cam_model(rpm, end, steps):
    pts = [[CAM_E + CAM_R * math.cos(a), CAM_R * math.sin(a)] for a in np.linspace(0, 2 * math.pi, 145)[:-1]]
    top = CAM_E + CAM_R
    L0 = (top + 5 + 200) - (FMID + KS * CAM_E) / KS                    # 顶点时弹簧拉力 F_mid + k_s·e
    return model(
        [box("cam", 1.0, (0, 0, 0), ix=1e-3), box("fol", MF, (0, 0, top + 5))],
        joints=[{"id": "rc", "type": "revolute", "body_i": "ground", "body_j": "cam", "point_mm": [0, 0, 0], "axis": [1, 0, 0]},
                {"id": "tf", "type": "translational", "body_i": "ground", "body_j": "fol", "point_mm": [0, 0, top + 5],
                 "axis": [0, 0, 1]}],
        motions=[{"id": "drive", "joint": "rc", "dof": "rotation", "speed": rpm}],
        forces=[{"id": "spr", "type": "spring_damper", "body_i": "ground", "point_i_mm": [0, 0, -200], "body_j": "fol",
                 "point_j_mm": [0, 0, top + 5], "stiffness_n_per_mm": KS, "free_length_mm": L0}],
        geometries=[{"id": "cam_c", "body": "cam", "type": "curve", "origin_mm": [0, 0, 0], "normal": [1, 0, 0],
                     "x_axis": [0, 0, 1], "points_mm": pts},
                    {"id": "face", "body": "fol", "type": "plane", "point_mm": [0, 0, top], "normal": [0, 0, -1]}],
        contacts=[{"id": "c", "geometry_i": "cam_c", "geometry_j": "face", "stiffness_n_per_mm": KC, "exponent": 1.0,
                   "damping_n_s_per_mm": 0.2, "penetration_mm": 1e-5}],
        analysis_={"type": "dynamic", "end_time_s": end, "output_steps": steps, "rtol": 1e-8, "atol": 1e-11},
        gravity=(0, 0, -G * 1000))


def omega_crit():
    return math.sqrt((MF * G + FMID + KS * 1000 * CAM_E / 1000) / (MF * CAM_E / 1000))


def test_cam_follower_follows_below_critical_speed():
    rpm = 600
    w = rpm * 2 * math.pi / 60
    assert w < omega_crit()
    data, _ = R.run_model(cam_model(rpm, 0.06, 120))
    t = np.array(data["times_s"])
    z = np.array([p[2] for p in data["bodies"]["fol"]["cm_mm"]]) - 5
    N = np.array(data["contacts"]["c"]["normal_force_n"])
    lift = CAM_R + CAM_E * np.cos(w * t) - N / KC                        # 轮廓升程减接触压入
    late = t > 0.01
    assert np.max(np.abs(z[late] - lift[late])) < 1e-4
    n_min = MF * G + FMID - abs(KS * CAM_E - MF * CAM_E / 1000 * w * w)
    assert N[late].min() == pytest.approx(n_min, rel=2e-2)
    assert N[late].min() > 0


def test_cam_follower_jumps_above_critical_speed():
    rpm = 1300
    w = rpm * 2 * math.pi / 60
    assert w > omega_crit()
    data, _ = R.run_model(cam_model(rpm, 0.03, 120))
    t = np.array(data["times_s"])
    z = np.array([p[2] for p in data["bodies"]["fol"]["cm_mm"]]) - 5
    N = np.array(data["contacts"]["c"]["normal_force_n"])
    assert (N == 0).any()                                               # 脱离
    gap = z - (CAM_R + CAM_E * np.cos(w * t))
    assert gap.max() > 0.05                                             # 从动件离开轮廓


# ---------------------------------------------------------------- 齿轮
KM = 2e4          # N/mm


def gears(motion, load, w2=None, analysis_=None, backlash=0.0, damping=1.0):
    return model(
        [box("g1", 0.5, (0, 0, 0), iz=2e-4), box("g2", 1.0, (60, 0, 0), iz=1e-3, w0=w2)],
        joints=[{"id": "r1", "type": "revolute", "body_i": "ground", "body_j": "g1", "point_mm": [0, 0, 0], "axis": [0, 0, 1]},
                {"id": "r2", "type": "revolute", "body_i": "ground", "body_j": "g2", "point_mm": [60, 0, 0], "axis": [0, 0, 1]}],
        motions=[{"id": "m1", "joint": "r1", "dof": "rotation", **motion}],
        forces=[{"id": "gm", "type": "gear_mesh", "joint_i": "r1", "joint_j": "r2", "module_mm": 2, "teeth_i": 20, "teeth_j": 40,
                 "mesh_stiffness_n_per_mm": KM, "damping_n_s_per_mm": damping, "backlash_mm": backlash},
                {"id": "load", "type": "torque", "body": "g2", "tz_n_m": load}],
        analysis_=analysis_)


def zang(q):
    return 2 * math.atan2(q[3], q[0])


def test_gear_ratio_mesh_force_and_drive_torque():
    T = 2.0
    data, _ = R.run_model(gears({"speed": 60}, T, w2=(0, 0, -180),
                                analysis_={"type": "dynamic", "end_time_s": 0.04, "output_steps": 8, "rtol": 1e-9, "atol": 1e-12},
                                damping=2.0))
    t = np.array(data["times_s"])
    late = t > 0.02
    w2 = np.array([w[2] for w in data["bodies"]["g2"]["w_deg_s"]])
    assert np.max(np.abs(w2[late] / 360 + 0.5)) < 1e-4
    rb2 = 2 * 40 * math.cos(math.radians(20)) / 2 / 1000
    Fm = np.array(data["contacts"]["gm"]["normal_force_n"])
    assert np.mean(Fm[late]) == pytest.approx(T / rb2, rel=1e-3)
    tau = np.array(data["motions"]["m1"]["effort"])
    assert np.mean(np.abs(tau[late])) == pytest.approx(T * 20 / 40, rel=1e-3)


def test_gear_backlash_and_mesh_stiffness_lost_motion():
    b, k, T = 0.05, KM, 1.0
    ang = []
    for load in (T, -T):
        data, _ = R.run_model(gears({"function": "0*time"}, load, backlash=b, analysis_={"type": "static"}))
        ang.append(zang(data["bodies"]["g2"]["euler_parameters"][0]))
    rb2 = 2 * 40 * math.cos(math.radians(20)) / 2
    F = T * 1000 / rb2                                     # N（T 单位 N·m → N·mm）
    assert abs(ang[0] - ang[1]) == pytest.approx((b + 2 * F / k) / rb2, rel=1e-4)


def test_gear_center_distance_checked():
    m = gears({"speed": 60}, 0.0)
    m["joints"][1]["point_mm"] = [61, 0, 0]
    m["bodies"][1]["cm_mm"] = [61, 0, 0]
    with pytest.raises(M.ModelError, match="中心距"):
        M.build(m)


# ---------------------------------------------------------------- 网格
CUBE_F = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4],
          [1, 5, 7], [1, 7, 3]]


def cube(cz, h=10.0):
    return [[x, y, cz + z] for x in (-h, h) for y in (-h, h) for z in (-h, h)]


def test_mesh_cube_rests_on_plane_with_four_corner_contacts():
    k, m = 1e3, 1.0
    d = m * G / 4 / k
    data, _ = R.run_model(model(
        [box("cube", m, (0, 0, 10 - d), iz=6.7e-5)],
        geometries=[FLOOR, {"id": "c", "body": "cube", "type": "mesh", "vertices_mm": cube(10 - d), "faces": CUBE_F}],
        contacts=[{"id": "k", "geometry_i": "floor", "geometry_j": "c", "stiffness_n_per_mm": k, "exponent": 1.0}],
        analysis_={"type": "static"}, gravity=(0, 0, -G * 1000)))
    assert data["bodies"]["cube"]["cm_mm"][0][2] == pytest.approx(10 - d, rel=1e-9)
    assert data["contacts"]["k"]["points"][0] == 4


def test_sphere_settles_on_mesh():
    k, m, Rr = 1e3, 0.05, 5.0
    d = m * G / k
    data, _ = R.run_model(model(
        [box("ball", m, (0, 0, 20 + Rr), iz=5e-7)],
        geometries=[{"id": "c", "body": "ground", "type": "mesh", "vertices_mm": cube(10), "faces": CUBE_F},
                    {"id": "s", "body": "ball", "type": "sphere", "center_mm": [0, 0, 20 + Rr], "radius_mm": Rr}],
        contacts=[{"id": "k", "geometry_i": "c", "geometry_j": "s", "stiffness_n_per_mm": k, "exponent": 1.0,
                   "damping_n_s_per_mm": 0.02, "penetration_mm": 1e-5}],
        analysis_={"type": "dynamic", "end_time_s": 0.05, "output_steps": 10, "rtol": 1e-8, "atol": 1e-11},
        gravity=(0, 0, -G * 1000)))
    assert data["bodies"]["ball"]["cm_mm"][-1][2] == pytest.approx(20 + Rr - d, abs=2e-4)


def test_full_d3_fixture_runs():
    inst = json.loads(FIX.read_text())["instance"]
    inst["analysis"] = {"type": "dynamic", "end_time_s": 0.002, "output_steps": 4, "integrator": "Radau"}
    data, _ = R.run_model(inst)
    assert ver_ok(data) and set(data["contacts"]) == {"c1", "c2", "c3", "gm"}


def ver_ok(data):
    return next(v for v in data["verification"] if v["key"] == "constraint_residual")["status"] == "pass"
