"""运动学 · 多体动力学模块（ADR-0056，M10 第二步）：标准题与“动力学 → 选型”。不联网。

标准题（误差门槛沿用数字工厂第 12 轮）：单摆周期、曲柄滑块驱动力矩与虚功原理（< 1%）、四杆位置与解析解（< 1%）、
机械臂静止重力矩与 Σm·g·r（< 2%）。
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

if os.environ.get("CI"):
    import mujoco  # noqa: F401 — CI 中必须装（ADR-0056）
else:
    pytest.importorskip("mujoco")

import numpy as np

import analysis
from analysis import mbd
from analysis.mbd import arm, core, mechanisms

ROOT = Path(__file__).resolve().parent.parent
G = 9.81
ARM = {"kind": "arm", "base_height_mm": 160, "links": [{"length_mm": 300, "mass_kg": 3.0}, {"length_mm": 250, "mass_kg": 1.2}],
       "joint_masses_kg": [0, 1.0], "payload_kg": 1.5}


def test_pendulum_period():
    L, r, m = 0.5, 0.005, 1.0
    xml = (f'<mujoco><option timestep="0.0002"/><worldbody><body name="bob"><joint name="pivot" type="hinge" axis="0 1 0"/>'
           f'<geom type="sphere" pos="0 0 {-L}" size="{r}" mass="{m}"/></body></worldbody></mujoco>')
    _summ, ch, _ = core.simulate(core.load_spec(xml=xml), {"duration_s": 3.0, "initial": {"pivot": math.radians(2)},
                                                          "drives": [], "sample_hz": 200})
    q, t = ch["q.pivot"], ch["t"]
    up = [t[i] - q[i] * (t[i + 1] - t[i]) / (q[i + 1] - q[i]) for i in range(len(q) - 1) if q[i] < 0 <= q[i + 1]]
    period = float(np.mean(np.diff(up)))
    inertia = m * L * L + 0.4 * m * r * r  # 物理摆
    theory = 2 * math.pi * math.sqrt(inertia / (m * G * L)) * (1 + math.radians(2) ** 2 / 16)
    assert period == pytest.approx(theory, rel=1e-3)


def test_slider_crank_torque_matches_virtual_work():
    F = 200.0
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER"}, "duration_s": 2.0, "gravity": False,
                               "drives": [{"joint": "crank", "kind": "speed", "value": 6}],  # 慢速：准静态
                               "forces": [{"body": "slider", "force_n": [-F, 0, 0]}], "sample_hz": 200})
    assert res["status"] == "ok", res["messages"]
    s = res["data"]["series"]["crank"]
    p = mechanisms.params("C-LNK-SLIDER")
    errs = []
    for q_deg, tau in zip(s["q"], s["drive"], strict=True):
        th = math.radians(q_deg)
        dx = (mechanisms.slider_crank_x(p, th + 1e-6) - mechanisms.slider_crank_x(p, th - 1e-6)) / 2e-6
        expected = F * dx  # 虚功原理（准静态）：τ·dθ + F_x·dx = 0，F_x = −F → τ = F·dx/dθ
        if abs(expected) > 0.5:
            errs.append(abs(tau - expected) / abs(expected))
    assert errs and max(errs) < 0.01


def test_four_bar_position_matches_analytic():
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-4BAR"}, "duration_s": 1.0, "gravity": False,
                               "drives": [{"joint": "crank", "kind": "speed", "value": 30}], "sample_hz": 100})
    assert res["status"] == "ok", res["messages"]
    # 摇杆角不在驱动里：用核心通道核对
    spec = core.load_spec(xml=mechanisms.mjcf("C-LNK-4BAR"))
    setup = mechanisms.prepare_setup("C-LNK-4BAR", None, {"duration_s": 1.0, "gravity": False,
                                                          "drives": [{"joint": "crank", "kind": "speed", "value": math.pi}]})
    _, ch, _ = core.simulate(spec, setup)
    p = mechanisms.params("C-LNK-4BAR")
    worst = 0.0
    for th, rocker in zip(ch["q.crank"], ch["q.rocker"], strict=True):
        worst = max(worst, abs(rocker - mechanisms.four_bar_solve(p, th)[3]))
    assert worst < 1e-3  # rad


def test_arm_gravity_torque_static():
    links = ARM["links"]
    hand_j2 = G * (3.0 * 0.150 + 1.0 * 0.300 + 1.2 * (0.300 + 0.125) + 1.5 * 0.550)
    model, _ = core.build(core.load_spec(xml=arm.mjcf(ARM)), {"drives": []})
    geo = core.gravity_torques(model, np.zeros(model.nq))
    assert -geo["j2"] == pytest.approx(hand_j2, rel=1e-9)
    res = analysis.run("mbd", {"model": ARM, "duration_s": 0.5,
                               "drives": [{"joint": j, "kind": "hold"} for j in ("j1", "j2", "j3")]})
    d = {x["joint"]: x for x in res["data"]["drives"]}
    assert d["j2"]["peak"] == pytest.approx(hand_j2, rel=0.02)
    assert res["data"]["static"]["gravity_torque_nm"]["j2"] == pytest.approx(hand_j2, rel=1e-9)
    assert len(links) == 2


def test_motion_result_and_requirement_select_real_parts():
    from kb.library import JsonLibrary, WithGenerated
    from mcp_server.tools import compose_chain

    res = analysis.run("mbd", {"model": ARM, "duration_s": 1.5,
                               "drives": [{"joint": "j1", "kind": "move", "to": 90, "t1_s": 1.2},
                                          {"joint": "j2", "kind": "move", "to": 30, "t1_s": 1.2},
                                          {"joint": "j3", "kind": "hold"}]})
    assert res["status"] == "ok" and res["solver"]["name"] == "MuJoCo"
    j2 = next(d for d in res["data"]["drives"] if d["joint"] == "j2")
    assert j2["peak"] >= j2["rms"] > 0 and j2["speed_max"] > 0 and j2["unit_speed"] == "rpm"
    # 匀速段转速：30° 在 1.2 s 内（加减速各 25%）→ 最高转速 = 30°/(0.9 s) = 5.556 rpm
    assert j2["speed_max"] == pytest.approx(30 / 360 / 0.9 * 60, rel=0.01)
    req = mbd.requirement(res, "j2", base={"supply": {"current_type": "ac", "voltage_v": 200, "phases": 3}})
    assert req["output_torque_peak_nm"] == round(j2["peak"], 3) and req["load_inertia_kgm2"] > 0
    out = compose_chain(WithGenerated(JsonLibrary(ROOT / "data" / "library")), req, top_n=5, include_unknown=True)
    assert out["count"] > 0
    used = {i["component"] for c in out["candidates"] for i in c["system"]["components"]}
    assert any(u.startswith("servo_motor.") for u in used) and any(u.startswith("reducer.") for u in used)


def test_setup_errors_are_reported():
    bad = analysis.run("mbd", {"model": {"kind": "arm", "links": [{"length_mm": 300, "mass_kg": 0}]}})
    assert bad["status"] == "failed" and "mass_kg" in bad["messages"][0]
    bad = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "nope"}})
    assert bad["status"] == "failed"
    bad = analysis.run("mbd", {"model": ARM, "drives": [{"joint": "j9", "kind": "hold"}]})
    assert bad["status"] == "failed" and "j9" in bad["messages"][0]
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-SCN-LEAD"}, "duration_s": 0.5,
                               "drives": [{"joint": "screw", "kind": "speed", "value": 60}]})
    with pytest.raises(mbd.SetupError):
        mbd.requirement(res, "nut")
    assert analysis.modules()[0]["id"] == "mbd"


def test_energy_swing_matches_kinetic_energy():
    """标准题（ADR-0062）：不计重力、恒速驱动的曲柄滑块，一转内驱动力矩做功的起伏等于连杆、滑块动能的起伏。
    动能按精确运动学（连杆质心平动 + 转动、滑块平动）与模型里的质量逐点计算，取最大值减最小值。"""
    import numpy as np

    from analysis import mbd
    from analysis.mbd.mechanisms import RHO

    r, l, w, t, rpm = 0.0175, 0.06, 0.008, 0.005, 3000
    res = mbd.run({"model": {"kind": "mechanism", "id": "C-LNK-SLIDER",
                             "params": {"crank_m": r, "rod_m": l, "link_width_m": w, "link_thickness_m": t}},
                   "duration_s": 0.045, "gravity": False, "sample_hz": 5000,
                   "drives": [{"joint": "crank", "kind": "speed", "value": rpm}]})
    sw = mbd.energy_swing(res, "crank")
    assert sw["points_per_rev"] >= 90 and abs(sw["mean_torque_nm"]) < 0.02
    m_r, i_r = RHO * l * t * w, RHO * l * t * w * (l ** 2 + w ** 2) / 12          # 连杆：长 l、宽 w（运动平面内）、厚 t
    m_s = RHO * (2.4 * w) * (3 * t) * (2 * w)                                      # 滑块：模型里的方块
    om = rpm * 2 * np.pi / 60
    th = np.linspace(0, 2 * np.pi, 4001)
    ax, az = r * np.cos(th), r * np.sin(th)
    xb = ax + np.sqrt(l ** 2 - az ** 2)
    phi = np.arcsin(az / l)
    d = lambda f: np.gradient(f, th) * om
    ke = 0.5 * m_r * (d((ax + xb) / 2) ** 2 + d(az / 2) ** 2) + 0.5 * i_r * d(phi) ** 2 + 0.5 * m_s * d(xb) ** 2
    exact = ke.max() - ke.min()
    assert abs(sw["delta_e_j"] - exact) / exact < 0.03, (sw, exact)
    sparse = mbd.run({"model": {"kind": "mechanism", "id": "C-LNK-SLIDER",
                                "params": {"crank_m": r, "rod_m": l, "link_width_m": w, "link_thickness_m": t}},
                      "duration_s": 0.045, "gravity": False, "sample_hz": 200,
                      "drives": [{"joint": "crank", "kind": "speed", "value": rpm}]})
    with pytest.raises(mbd.SetupError, match="太稀"):                             # 200 Hz 记 3000 rpm：每转 4 个点
        mbd.energy_swing(sparse, "crank")
