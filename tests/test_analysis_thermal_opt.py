"""热分析 · 热应力 · 设计优化（ADR-0056，M10 第四步）：标准题。不联网。

门槛沿用数字工厂第 14 轮：平壁一维导热 < 1%、圆柱肋片散热量 < 3%、集总参数冷却一个时间常数处 < 3%、
两端固定杆热应力 σ = E·α·ΔT < 3%（中段）、悬臂梁定强度最轻截面与解析解 < 3%、轴优化比现行轻且满足要求。
"""

from __future__ import annotations

import math
import os

import pytest

import analysis
from analysis.common import materials
from analysis.common.solvers import find_ccx


def _need():
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        import optuna  # noqa: F401
        assert find_ccx(), "CI 中没有 ccx"
        return
    pytest.importorskip("gmsh")
    pytest.importorskip("scipy")
    if find_ccx() is None:
        pytest.skip("本机没有 CalculiX")


def _step(tmp_path, name, fn):
    import gmsh

    path = tmp_path / f"{name}.step"
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(name)
    fn(gmsh)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()
    return str(path)


def _faces(path):
    return analysis.run("fea", {"analysis": "faces", "step_path": path})["data"]["faces"]


def _at(faces, axis, value):
    return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][axis] - value) < 1e-6]


def test_plane_wall_conduction(tmp_path):
    _need()
    path = _step(tmp_path, "wall", lambda g: g.model.occ.addBox(0, 0, 0, 100, 20, 20))
    fs = _faces(path)
    r = analysis.run("thermal", {"step_path": path, "material": "45-QT", "mesh": {"size_mm": 5},
                                 "thermal": [{"type": "temperature", "faces": _at(fs, 0, 0), "value_c": 20},
                                             {"type": "heat_flux", "faces": _at(fs, 0, 100), "power_w": 10}]})
    assert r["status"] == "ok", r["messages"]
    k = materials.get("45-QT")["thermal_conductivity_w_per_m_k"]
    assert r["data"]["t_max_c"] == pytest.approx(20 + 10 / 400e-6 * 0.1 / k, rel=0.01)  # T = T0 + qL/k


def test_pin_fin_heat(tmp_path):
    _need()
    path = _step(tmp_path, "fin", lambda g: g.model.occ.addCylinder(0, 0, 0, 0, 0, 50, 5))
    fs = _faces(path)
    r = analysis.run("thermal", {"step_path": path, "material": "6061-T6", "mesh": {"size_mm": 1.5},
                                 "thermal": [{"type": "temperature", "faces": _at(fs, 2, 0), "value_c": 100},
                                             {"type": "convection", "faces": "rest", "h_w_m2k": 50, "t_inf_c": 20}]})
    assert r["status"] == "ok", r["messages"]
    k, h, d, length = materials.get("6061-T6")["thermal_conductivity_w_per_m_k"], 50.0, 0.01, 0.05
    p, a = math.pi * d, math.pi * d * d / 4
    m = math.sqrt(h * p / (k * a))
    big = math.sqrt(h * p * k * a) * 80
    q = big * (math.sinh(m * length) + h / (m * k) * math.cosh(m * length)) / (
        math.cosh(m * length) + h / (m * k) * math.sinh(m * length))  # 端部对流的肋片
    assert r["data"]["heat_out_convection_w"] == pytest.approx(q, rel=0.03)


def test_lumped_cooling(tmp_path):
    _need()
    path = _step(tmp_path, "cube", lambda g: g.model.occ.addBox(0, 0, 0, 20, 20, 20))
    m = materials.get("6061-T6")
    tau = m["density_kg_m3"] * m["specific_heat_j_per_kg_k"] * 0.02 ** 3 / (10 * 6 * 0.02 ** 2)  # ρcV/(hA)
    r = analysis.run("thermal", {"step_path": path, "material": "6061-T6", "mesh": {"size_mm": 10},
                                 "thermal": [{"type": "convection", "faces": "rest", "h_w_m2k": 10, "t_inf_c": 20}],
                                 "transient": {"duration_s": tau, "steps": 10, "t0_c": 100}})
    assert r["status"] == "ok", r["messages"]
    t_end, _t_max, t_mean = r["data"]["series"][-1]
    assert t_end == pytest.approx(tau, rel=1e-3)
    assert t_mean == pytest.approx(20 + 80 * math.exp(-1), rel=0.03)


def test_thermal_stress_fixed_bar(tmp_path):
    _need()
    import numpy as np

    path = _step(tmp_path, "bar", lambda g: g.model.occ.addBox(0, 0, 0, 300, 20, 20))
    fs = _faces(path)
    r = analysis.run("thermal", {"analysis": "thermo_mech", "step_path": path, "material": "45-QT", "mesh": {"size_mm": 5},
                                 "thermal": [{"type": "temperature", "faces": [f["id"] for f in fs], "value_c": 120}],
                                 "loads": [{"type": "fixed", "faces": _at(fs, 0, 0) + _at(fs, 0, 300)}], "ref_temp_c": 20})
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["surface"]
    pos, vm = np.array(s["positions"]), np.array(s["vm"])
    mid = vm[np.abs(pos[:, 0] - 150) < 5].mean()
    m = materials.get("45-QT")
    assert mid == pytest.approx(m["elastic_modulus_mpa"] * m["thermal_expansion_per_k"] * 100, rel=0.03)  # E·α·ΔT


def test_thermal_missing_data(tmp_path):
    _need()
    path = _step(tmp_path, "c", lambda g: g.model.occ.addBox(0, 0, 0, 10, 10, 10))
    out = analysis.run("thermal", {"analysis": "thermo_mech", "step_path": path, "material": "HT200",
                                   "thermal": [{"type": "convection", "faces": "rest", "h_w_m2k": 10, "t_inf_c": 20}]})
    assert out["status"] == "failed" and "elastic_modulus_mpa" in out["messages"][0]


def test_beam_lightest_section_matches_analytic():
    _need()
    r = analysis.run("optimize", {"problem": "beam", "beam": {"length_mm": 200, "width_mm": 20, "force_n": 1000,
                                                              "height_mm": 25},
                                  "vars": [{"name": "h", "low": 10, "high": 30, "step": 0.1}], "material": "45-QT",
                                  "constraints": {"sf_min": 2.0}, "n_trials": 16, "seed": 1})
    assert r["status"] == "ok", r["messages"]
    analytic = math.sqrt(6 * 1000 * 200 * 2.0 / (20 * 355))  # σ = 6FL/(bh²) = σs/2
    best = r["data"]["best"][0]
    assert best["x"]["h"] == pytest.approx(analytic, rel=0.03) and best["sf"] >= 2.0
    assert r["data"]["base"]["x"] == {"h": 25.0}


def test_shaft_lighter_and_meets_requirements():
    _need()
    segs = [[30, 40], [35, 12], [40, 60], [35, 25], [30, 30]]
    r = analysis.run("optimize", {"problem": "shaft", "shaft": {"segments": segs, "torque_nm": 350},
                                  "vars": [{"name": "d0", "segments": [0, 4], "low": 26, "high": 33, "step": 0.5},
                                           {"name": "d2", "low": 36, "high": 46, "step": 0.5}],
                                  "material": "45-QT", "n_trials": 8, "seed": 1,
                                  "constraints": {"sf_min": 1.3, "fatigue": {"surface_factor": 0.92, "size_factor": 0.85,
                                                                             "load_series": [0, 350], "life": "infinite"}}})
    assert r["status"] == "ok", r["messages"]
    base, best = r["data"]["base"], r["data"]["best"][0]
    assert base["x"] == {"d0": 30.0, "d2": 40.0}
    assert best["mass_kg"] < base["mass_kg"] and best["sf"] >= 1.3 and best["life_infinite"]


def test_optimize_setup_errors():
    for bad in ({"problem": "gear"}, {"problem": "beam", "beam": {}, "vars": [{"name": "w", "low": 1, "high": 2}]},
                {"problem": "shaft", "shaft": {"segments": [[30, 40]]}, "vars": [{"name": "d3", "low": 1, "high": 2}],
                 "material": "45-QT"}):
        out = analysis.run("optimize", bad) if analysis.status(analysis.get("optimize"))["available"] else None
        if out is not None:
            assert out["status"] == "failed"
