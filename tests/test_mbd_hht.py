"""隐式积分器 HHT-I3（ADR-0098 E1 验收）。

- 现有动力学样例用 HHT 算，与 DOP853 一致（质心轨迹差 ≤ 1e-4 × 运动幅度）；控制器、接触、柔性体、摩擦都接上
- α = 0（梯形法）保守系统能量漂移 < 1e-4；α < 0 有耗散但很小
- 大摆角单摆周期对椭圆积分解
- 硬系统（柔性摆）比 DOP853 快 10 倍以上
"""

from __future__ import annotations

import copy
import json
import math
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.special import ellipk

from analysis.mbd.dae.run import run_model

pytest.importorskip("scipy")
FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def _load(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    return doc.get("instance", doc)


def _hht(m, alpha=-0.05, **kw):
    m = copy.deepcopy(m)
    m["analysis"].update({"integrator": "HHT", "hht_alpha": alpha, **kw})
    m["analysis"].pop("rtol", None) if "rtol" not in kw else None
    m["analysis"].pop("atol", None) if "atol" not in kw else None
    return m


def _cm_diff(d1, d2):
    err, scale = 0.0, 1e-12
    for b in d1["bodies"]:
        a, c = np.array(d1["bodies"][b]["cm_mm"]), np.array(d2["bodies"][b]["cm_mm"])
        err = max(err, float(np.abs(a - c).max()))
        scale = max(scale, float(np.abs(a - a[0]).max()))
    return err, scale


@pytest.mark.parametrize(("name", "kw", "rel"), [
    # 缺省容差（rtol 1e-6）下大摆角单摆两秒后差 1e-4 级
    ("pendulum.json", {}, 2e-4), ("d2_force_elements.json", {}, 1e-4),
    # 硬接触（落球、方块、凸轮）对步长敏感：容差收紧到 1e-8 时与显式积分差 2e-4（ADR-0098 补充一）
    ("d3_contacts.json", {"rtol": 1e-8, "atol": 1e-11}, 5e-4)])
def test_matches_explicit(name, kw, rel):
    m = _load(name)
    d1, _ = run_model(copy.deepcopy(m), FIX)
    d2, _ = run_model(_hht(m, **kw), FIX)
    err, scale = _cm_diff(d1, d2)
    assert err <= rel * scale + 1e-9, (err, scale)
    assert d2["solver"]["integrator"] == "HHT" and d2["solver"]["steps"] > 0
    assert all(v["status"] != "fail" or v["key"] == "energy_drift" for v in d2["verification"])
    assert d2["verification"][0]["value"] <= 1e-8                      # 约束残差


def test_controller_matches_explicit():
    """PID 转台：设定值 1 ms 内阶跃、输出限幅——输入不光滑，二阶格式要收紧容差（rtol 1e-8 时差 2e-4）"""
    m = _load("d7_pid_turntable.json")
    d1, _ = run_model(copy.deepcopy(m), FIX)
    d2, _ = run_model(_hht(m, rtol=1e-8, atol=1e-11), FIX)
    a, b = np.array(d1["measures"]["th"]["values"]), np.array(d2["measures"]["th"]["values"])
    assert np.abs(a - b).max() <= 5e-4 * np.abs(a).max()
    ua, ub = (np.array(d["actuators"]["motor"]) for d in (d1, d2))
    assert np.abs(ua - ub).max() <= 5e-3 * np.abs(ua).max()


def test_trapezoid_conserves_energy_and_alpha_dissipates_little():
    m = _load("pendulum.json")
    d0, _ = run_model(_hht(m, alpha=0.0, rtol=1e-7, atol=1e-10), FIX)
    e0 = next(v for v in d0["verification"] if v["key"] == "energy_drift")
    assert e0["value"] < 1e-4
    d1, _ = run_model(_hht(m, alpha=-0.1), FIX)
    e1 = next(v for v in d1["verification"] if v["key"] == "energy_drift")
    assert e1["value"] < 2e-3                                           # 低频几乎不耗散


def test_large_swing_period_matches_elliptic_integral():
    """物理摆从 60° 放开：周期 T = 4√(L/g)·K(sin(θ₀/2))，L = I_O/(m d)"""
    th0, d, m_, ic = math.radians(60), 0.5, 1.0, 1e-5
    model = {"format": "mbd-model/1", "name": "大摆角", "gravity_mm_s2": [0, 0, -9810],
             "bodies": [{"id": "bob", "mass_kg": m_, "cm_mm": [d * 1000 * math.sin(th0), 0, -d * 1000 * math.cos(th0)],
                         "inertia_kg_m2": {"ixx": ic, "iyy": ic, "izz": ic}}],
             "joints": [{"id": "pivot", "type": "revolute", "body_i": "ground", "body_j": "bob", "point_mm": [0, 0, 0],
                         "axis": [0, 1, 0]}],
             "analysis": {"type": "dynamic", "end_time_s": 3.0, "output_steps": 3000, "integrator": "HHT", "hht_alpha": 0.0}}
    data, _ = run_model(model)
    x = np.array(data["bodies"]["bob"]["cm_mm"])[:, 0]
    t = np.array(data["times_s"])
    up = [t[k] - x[k] * (t[k + 1] - t[k]) / (x[k + 1] - x[k]) for k in range(len(x) - 1) if x[k] < 0 <= x[k + 1]]
    T = up[1] - up[0]
    L = (ic + m_ * d * d) / (m_ * d)
    ref = 4 * math.sqrt(L / 9.81) * ellipk(math.sin(th0 / 2) ** 2)
    assert T == pytest.approx(ref, rel=1e-4)


def test_stiff_flexible_pendulum_is_fast():
    m = _load("d6_flex_pendulum.json")
    t0 = time.time()
    d2, _ = run_model(_hht(m), FIX)
    t_hht = time.time() - t0
    t0 = time.time()
    d1, _ = run_model(copy.deepcopy(m), FIX)
    t_dop = time.time() - t0
    err, scale = _cm_diff(d1, d2)
    assert err <= 1e-4 * scale
    assert t_dop > 10 * t_hht, (t_dop, t_hht)


def test_pd_step_and_fmu_with_hht():
    """控制器（连续 PD）与 FMU 联合仿真（采样落在步上）用 HHT：对二阶系统阶跃响应解析解"""
    from tests.test_mbd_control import FMU_DIR, KD, KP, REF, pd, step_ref, table

    m = table([pd()], end=0.3, steps=30, method="HHT")
    m["analysis"].update({"rtol": 1e-8, "atol": 1e-11})
    data, _ = run_model(m)
    th = np.array(data["measures"]["th"]["values"])
    ref = np.array([step_ref(t) for t in data["times_s"]])
    assert np.max(np.abs(th - ref)) < 1e-4 * REF
    pytest.importorskip("fmpy")
    deg = math.pi / 180
    fmu = {"id": "fmu", "type": "fmu", "path": "StateSpace.fmu", "sample_time_s": 5e-4,
           "structural_parameters": {"m": 3, "n": 1, "r": 1},
           "parameters": {"A": [0.0], "B": [0.0, 0.0, 0.0], "C": [0.0], "D": [KP * deg, -KP * deg, -KD * deg], "x0": [0.0]},
           "inputs": [{"variable": "u", "index": 0, "expression": str(REF)}, {"variable": "u", "index": 1, "measure": "th"},
                      {"variable": "u", "index": 2, "measure": "w"}],
           "outputs": [{"variable": "y", "index": 0, "actuator": "motor"}]}
    m = table([fmu], end=0.3, steps=30, method="HHT")
    m["analysis"].update({"rtol": 1e-6, "atol": 1e-9})
    data, _ = run_model(m, base_dir=FMU_DIR)
    th = np.array(data["measures"]["th"]["values"])
    assert np.max(np.abs(th - ref)) < 0.01 * REF
    assert data["solver"]["steps"] >= 600                                    # 每个采样时刻都落在步上
