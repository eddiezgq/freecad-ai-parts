"""多体动力学 D7b（ADR-0097 补充十九）：参数扫描、试验设计、优化、载荷谱给疲劳。不联网、不调用 LLM。

参考：二阶系统单位阶跃的误差平方积分 ISE = (1 + 4ζ²)/(4ζωn)，ζ = 0.5 时最小；超调 Mp = e^(−πζ/√(1−ζ²))（自动控制原理）。
"""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from analysis.mbd import loads as LD
from analysis.mbd import study as SY
from analysis.mbd.dae import run as R

J, WN = 0.02, 20.0
KP = J * WN * WN
DEG = math.pi / 180
REF = 10.0


def kd_of(zeta):
    return 2 * zeta * math.sqrt(KP * J) * DEG


def zeta_of(kd_deg):
    return kd_deg / DEG / (2 * math.sqrt(KP * J))


def base(end=1.5, steps=200):
    return {"format": "mbd-model/1", "name": "转台", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "table", "mass_kg": 2, "cm_mm": [0, 0, 0], "inertia_kg_m2": {"ixx": 0.01, "iyy": 0.01, "izz": J}}],
            "joints": [{"id": "r", "type": "revolute", "body_i": "ground", "body_j": "table", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "forces": [{"id": "motor", "type": "actuator", "joint": "r"}],
            "measures": [{"id": "th", "type": "joint_angle", "joint": "r"}, {"id": "w", "type": "joint_speed", "joint": "r"}],
            "controllers": [{"id": "pos", "type": "pid", "sensor": "th", "rate_sensor": "w", "setpoint": str(REF),
                             "actuator": "motor", "kp": KP * DEG, "kd": kd_of(0.3)}],
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "rtol": 1e-9, "atol": 1e-12}}


def study(method, **kw):
    return {"format": "mbd-study/1", "name": "kd", "model": base(**kw.pop("model_kw", {})), "method": method,
            "variables": [{"name": "kd", "path": "/controllers/0/kd", "low": kd_of(0.2), "high": kd_of(1.2),
                           **kw.pop("var_kw", {})}],
            "metrics": [{"id": "ise", "kind": "ise", "series": "measures.th.values", "reference": str(REF)},
                        {"id": "peak", "kind": "max", "series": "measures.th.values"}],
            "objective": {"metric": "ise", "sense": "minimize"}, **kw}


def test_ise_optimum_is_zeta_half():
    res = SY.run(study("optimize", optimizer={"algorithm": "nelder_mead", "max_evaluations": 25},
                       model_kw={"end": 1.0, "steps": 150}))
    best = res["best"][0]
    assert zeta_of(best["variables"]["kd"]) == pytest.approx(0.5, rel=2e-2)
    ise_ref = (1 + 4 * 0.25) / (4 * 0.5 * WN) * REF ** 2
    assert best["metrics"]["ise"] == pytest.approx(ise_ref, rel=1e-3)
    assert len(res["evaluations"]) <= 25 and res["n_failed"] == 0


def test_grid_overshoot_matches_formula():
    res = SY.run(study("grid", var_kw={"levels": 3}, model_kw={"end": 0.4, "steps": 400}))
    assert len(res["evaluations"]) == 3
    for ev in res["evaluations"]:
        z = zeta_of(ev["variables"]["kd"])
        if z >= 1:                                    # 过阻尼：不超调
            assert ev["metrics"]["peak"] <= REF
            continue
        mp = math.exp(-math.pi * z / math.sqrt(1 - z * z))
        assert (ev["metrics"]["peak"] - REF) / REF == pytest.approx(mp, abs=1e-3)


def test_constraint_moves_optimum_to_its_boundary():
    """超调不超过 2 %：ζ ≥ 0.7797；ISE 在 ζ > 0.5 时单调增，所以最优落在约束边界"""
    s = study("optimize", optimizer={"algorithm": "nelder_mead", "max_evaluations": 30},
              constraints=[{"metric": "peak", "max": REF * 1.02}], model_kw={"end": 0.8, "steps": 400})
    res = SY.run(s)
    z_b = -math.log(0.02) / math.sqrt(math.pi ** 2 + math.log(0.02) ** 2)
    best = res["best"][0]
    assert best["feasible"]
    assert zeta_of(best["variables"]["kd"]) == pytest.approx(z_b, rel=2e-2)


def test_latin_hypercube_strata_and_seed():
    vs = [{"name": "a", "low": 0.0, "high": 1.0}, {"name": "b", "low": 10.0, "high": 1000.0, "log": True}]
    pts = SY.latin_hypercube(vs, 8, seed=3)
    assert pts == SY.latin_hypercube(vs, 8, seed=3)
    assert sorted(int(p["a"] * 8) for p in pts) == list(range(8))
    assert sorted(int((math.log10(p["b"]) - 1) / 2 * 8) for p in pts) == list(range(8))


def test_bad_study_is_reported():
    s = study("grid")
    s["variables"][0]["path"] = "/controllers/0/nope"
    with pytest.raises(SY.StudyError, match="nope"):
        SY.run(s)
    s = study("grid")
    s["objective"] = {"metric": "ghost"}
    with pytest.raises(SY.StudyError, match="ghost"):
        SY.run(s)


def test_unbalance_reaction_to_fatigue_matches_hand_count():
    """偏心 e = 10 mm、1 kg、600 r/min 的转子：轴承反力是幅值 m e ω² 的余弦，5 转就是 5 个对称循环；
    设危险点在这个幅值下 200 MPa，Haibach 修正 Miner：损伤 = 5 / [N_D (S_D/σ)^(2k−1)]（45 钢调质，β = ε = 1）"""
    from analysis.common import materials
    from analysis.fatigue import sn_cycles

    m, e, rpm, revs = 1.0, 10.0, 600.0, 5
    w = rpm * 2 * math.pi / 60
    model = {"format": "mbd-model/1", "name": "偏心转子", "gravity_mm_s2": [0, 0, 0],
             "bodies": [{"id": "rotor", "mass_kg": m, "cm_mm": [e, 0, 0], "inertia_kg_m2": {"ixx": 1e-3, "iyy": 1e-3, "izz": 1e-3}}],
             "joints": [{"id": "brg", "type": "revolute", "body_i": "ground", "body_j": "rotor", "point_mm": [0, 0, 0],
                         "axis": [0, 0, 1]}],
             "motions": [{"id": "spin", "joint": "brg", "dof": "rotation", "speed": rpm}],
             "analysis": {"type": "kinematic", "end_time_s": revs * 60 / rpm, "output_steps": 80 * revs}}
    data, _ = R.run_model(model)
    amp = m * e / 1000 * w * w
    fx = SY.series(data, "joints.brg.force_n.0")
    assert np.max(np.abs(fx)) == pytest.approx(amp, rel=1e-9)
    res = LD.fatigue(data, "joints.brg.force_n.0", material="45-QT", stress_ref_mpa=200.0, load_ref=amp,
                     surface_factor=1.0, size_factor=1.0)
    d = res["data"]
    assert d["cycles_per_block"] == revs
    mat = materials.get("45-QT")
    n = sn_cycles(200.0, mat["fatigue_limit_bending_mpa"], mat["sn_knee_cycles"], mat["sn_exponent"], True)
    assert d["damage_per_block"] == pytest.approx(revs / n, rel=1e-6)
    assert d["life_hours"] == pytest.approx(n / revs * (revs * 60 / rpm) / 3600, rel=1e-6)
    copy.deepcopy(d)
