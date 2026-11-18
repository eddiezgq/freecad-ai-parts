"""多体动力学 D7a（ADR-0097 补充十七）：执行器与控制器的标准题。不联网、不调用 LLM。

参考：二阶系统 Jθ̈ + kd·θ̇ + kp·θ = kp·r 的阶跃响应 θ = r[1 − e^(−ζωn t)(cos ωd t + ζ/√(1−ζ²) sin ωd t)]，
ωn = √(kp/J)、ζ = kd/(2√(kp·J))；恒定扰动 T 下 PD 稳态误差 T/kp，PID 为 0（任一自动控制原理教材）。
"""

from __future__ import annotations

import copy
import math
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import model as M
from analysis.mbd.dae import run as R
from tests.verification import record

J = 0.02                     # kg·m²
WN, ZETA = 20.0, 0.5
KP = J * WN * WN             # N·m/rad
KD = 2 * ZETA * math.sqrt(KP * J)
DEG = math.pi / 180
REF = 10.0                   # °
FMU_DIR = Path(__file__).resolve().parent / "fixtures" / "fmu"


def table(controllers, end=0.6, steps=60, extra_forces=(), method="DOP853"):
    return {"format": "mbd-model/1", "name": "转台", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "table", "mass_kg": 2, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": 0.01, "iyy": 0.01, "izz": J}}],
            "joints": [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "table", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "forces": [{"id": "motor", "type": "actuator", "joint": "r"}, *extra_forces],
            "measures": [{"id": "th", "type": "joint_angle", "joint": "r"}, {"id": "w", "type": "joint_speed", "joint": "r"}],
            "controllers": controllers,
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "rtol": 1e-10, "atol": 1e-12,
                         "integrator": method}}


def pd(**kw):
    return {"id": "pos", "type": "pid", "sensor": "th", "rate_sensor": "w", "setpoint": str(REF), "actuator": "motor",
            "kp": KP * DEG, "kd": KD * DEG, **kw}


def step_ref(t):
    wd = WN * math.sqrt(1 - ZETA ** 2)
    return REF * (1 - math.exp(-ZETA * WN * t) * (math.cos(wd * t) + ZETA / math.sqrt(1 - ZETA ** 2) * math.sin(wd * t)))


def test_pd_step_response_matches_second_order_solution():
    data, _ = R.run_model(table([pd()]))
    th = np.array(data["measures"]["th"]["values"])
    ref = np.array([step_ref(t) for t in data["times_s"]])
    record(("转角与二阶系统阶跃响应的最大差", "max angle difference from second-order step response"), float(np.max(np.abs(th - ref))), 0.0, tol=1e-6, rel=False, unit="°", formula="二阶系统阶跃响应闭式解")
    assert np.max(np.abs(th - ref)) < 1e-6
    u0 = data["actuators"]["motor"][0]
    assert u0 == pytest.approx(KP * REF * DEG, rel=1e-9)                     # 初始误差 10°：u = kp·e
    assert next(v for v in data["verification"] if v["key"] == "energy_drift")["status"] == "unknown"


def test_disturbance_pd_offset_and_pid_removes_it():
    T = 0.5
    dist = [{"id": "load", "type": "torque", "body": "table", "tz_n_m": -T}]
    a, _ = R.run_model(table([pd()], end=1.5, steps=30, extra_forces=dist))
    record(("PD 稳态转角", "PD steady-state angle"), a["measures"]["th"]["values"][-1], REF - T / KP / DEG, tol=1e-3, rel=False, unit="°", formula="θ_ref − T/kp")
    assert a["measures"]["th"]["values"][-1] == pytest.approx(REF - T / KP / DEG, abs=1e-3)
    b, _ = R.run_model(table([pd(ki=20.0 * DEG)], end=4.0, steps=40, extra_forces=dist))
    record(("PID 稳态转角", "PID steady-state angle"), b["measures"]["th"]["values"][-1], REF, tol=1e-3, rel=False, unit="°", formula="积分项消除稳态误差")
    assert b["measures"]["th"]["values"][-1] == pytest.approx(REF, abs=1e-3)
    assert b["actuators"]["motor"][-1] == pytest.approx(T, rel=1e-3)          # 积分项顶住扰动


def test_state_space_controller_equals_pid():
    ss = {"id": "ss", "type": "state_space", "inputs": [{"expression": str(REF)}, {"measure": "th"}, {"measure": "w"}],
          "outputs": ["motor"], "D": [[KP * DEG, -KP * DEG, -KD * DEG]]}
    a, _ = R.run_model(table([ss]))
    b, _ = R.run_model(table([pd()]))
    assert np.allclose(a["measures"]["th"]["values"], b["measures"]["th"]["values"], atol=1e-9)
    # 带状态：一阶低通 ẋ = (u − x)/τ 接在指令后面，与手写的等价 PID 不同但稳态相同
    lp = {"id": "lp", "type": "state_space", "inputs": [{"expression": str(REF)}, {"measure": "th"}, {"measure": "w"}],
          "outputs": ["motor"], "A": [[-200.0]], "B": [[200 * KP * DEG, -200 * KP * DEG, -200 * KD * DEG]], "C": [[1.0]],
          "D": [[0.0, 0.0, 0.0]], "x0": [0.0]}
    c, _ = R.run_model(table([lp], end=1.0, steps=10))
    assert c["measures"]["th"]["values"][-1] == pytest.approx(REF, abs=1e-3)


def test_output_limit_gives_constant_acceleration_at_start():
    umax = 0.1
    data, _ = R.run_model(table([pd(output_max=umax, output_min=-umax)], end=0.02, steps=4))
    t = np.array(data["times_s"])
    th = np.array(data["measures"]["th"]["values"])
    assert data["actuators"]["motor"][1] == pytest.approx(umax)
    assert th[1:] == pytest.approx(0.5 * umax / J * t[1:] ** 2 / DEG, rel=1e-6)


def test_fmu_cosimulation_matches_continuous_pd():
    pytest.importorskip("fmpy")
    fmu = {"id": "fmu", "type": "fmu", "path": "StateSpace.fmu", "sample_time_s": 5e-4,
           "structural_parameters": {"m": 3, "n": 1, "r": 1},
           "parameters": {"A": [0.0], "B": [0.0, 0.0, 0.0], "C": [0.0], "D": [KP * DEG, -KP * DEG, -KD * DEG], "x0": [0.0]},
           "inputs": [{"variable": "u", "index": 0, "expression": str(REF)}, {"variable": "u", "index": 1, "measure": "th"},
                      {"variable": "u", "index": 2, "measure": "w"}],
           "outputs": [{"variable": "y", "index": 0, "actuator": "motor"}]}
    data, _ = R.run_model(table([fmu], end=0.3, steps=30), base_dir=FMU_DIR)
    th = np.array(data["measures"]["th"]["values"])
    ref = np.array([step_ref(t) for t in data["times_s"]])
    # 采样 0.5 ms、零阶保持：相当于约 h/2 的延迟
    record(("转角与连续 PD 解的最大差", "max angle difference from continuous PD"), float(np.max(np.abs(th - ref))), 0.0, tol=0.01 * REF, rel=False, unit="°", formula="采样 0.5 ms 零阶保持")
    assert np.max(np.abs(th - ref)) < 0.01 * REF                              # 实测 0.03°（0.3 %）
    assert np.max(np.abs(th - ref)) > 0                                      # 真的是采样（不是连续）
    assert data["actuators"]["motor"][0] == pytest.approx(KP * REF * DEG, rel=1e-9)


def test_bad_controller_references_are_reported():
    m = table([pd(sensor="nope")])
    with pytest.raises(M.ModelError, match="nope"):
        M.build(m)
    m = table([pd()])
    m2 = copy.deepcopy(m)
    m2["controllers"][0]["actuator"] = "ghost"
    with pytest.raises(M.ModelError, match="ghost"):
        M.build(m2)
