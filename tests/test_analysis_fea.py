"""有限元强度 · 固有频率 · 疲劳寿命（ADR-0056，M10 第三步）：标准题。不联网。

门槛沿用数字工厂第 11 轮：悬臂梁挠度 < 3%、光滑轴扭转应力与手算 < 3%、悬臂梁一阶固有频率 < 3%；
疲劳恒幅与手算 < 0.1%、雨流计数核对 ASTM E1049 的重复历程例子。
"""

from __future__ import annotations

import math
import os

import pytest

import analysis
from analysis import fatigue
from analysis.common import materials
from analysis.common.solvers import find_ccx

STEEL = materials.get("45-QT")
E = STEEL["elastic_modulus_mpa"]


def _need_fea():
    if os.environ.get("CI"):
        import gmsh  # noqa: F401 — CI 中必须装
        assert find_ccx(), "CI 中没有 ccx"
        return
    pytest.importorskip("gmsh")
    pytest.importorskip("scipy")
    if find_ccx() is None:
        pytest.skip("本机没有 CalculiX")


def _step(tmp_path, kind):
    import gmsh

    path = tmp_path / f"{kind}.step"
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(kind)
    if kind == "box":
        gmsh.model.occ.addBox(0, 0, 0, 100, 10, 10)
    else:
        gmsh.model.occ.addCylinder(0, 0, 0, 0, 0, 100, 17.5)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()
    return str(path)


def _face(faces, axis, value, kind="plane"):
    return next(f["id"] for f in faces if f["kind"] == kind and abs(f["center"][axis] - value) < 1e-6)


@pytest.fixture(scope="module")
def box(tmp_path_factory):
    _need_fea()
    path = _step(tmp_path_factory.mktemp("fea"), "box")
    faces = analysis.run("fea", {"analysis": "faces", "step_path": path})["data"]["faces"]
    return path, _face(faces, 0, 0), _face(faces, 0, 100)


def test_faces_listing(box):
    path, root, tip = box
    out = analysis.run("fea", {"analysis": "faces", "step_path": path})
    assert out["status"] == "ok" and out["data"]["solid"]["faces"] == 6
    assert out["data"]["solid"]["volume_mm3"] == pytest.approx(100 * 10 * 10)
    assert root != tip


def test_cantilever_deflection(box):
    path, root, tip = box
    r = analysis.run("fea", {"step_path": path, "material": "45-QT", "mesh": {"size_mm": 2.5},
                             "loads": [{"type": "fixed", "faces": [root]},
                                       {"type": "force", "faces": [tip], "vector_n": [0, 0, -100]}]})
    assert r["status"] == "ok", r["messages"]
    theory = 100 * 100 ** 3 / (3 * E * 10 * 10 ** 3 / 12)  # PL³/3EI
    assert r["data"]["u_max_mm"] == pytest.approx(theory, rel=0.03)
    assert r["data"]["safety_factor"] == pytest.approx(355 / r["data"]["vm_max_mpa"], rel=1e-3)
    assert r["solver"]["name"] == "CalculiX" and r["limitations"]
    s = r["data"]["surface"]
    assert len(s["positions"]) == len(s["vm"]) and len(s["triangles"][0]) == 3


def test_shaft_torsion_matches_hand(tmp_path):
    _need_fea()
    path = _step(tmp_path, "cyl")
    faces = analysis.run("fea", {"analysis": "faces", "step_path": path})["data"]["faces"]
    r = analysis.run("fea", {"step_path": path, "material": "45-QT", "mesh": {"size_mm": 3},
                             "loads": [{"type": "fixed", "faces": [_face(faces, 2, 0)]},
                                       {"type": "torque", "faces": [_face(faces, 2, 100)], "value_nm": 350,
                                        "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}]})
    assert r["status"] == "ok", r["messages"]
    hand = math.sqrt(3) * 16 * 350e3 / (math.pi * 35 ** 3)  # Von Mises 的纯扭转：√3·16T/(πd³)
    assert r["data"]["vm_max_mpa"] == pytest.approx(hand, rel=0.03)


def test_cantilever_first_frequency(box):
    path, root, _ = box
    r = analysis.run("fea", {"analysis": "modal", "step_path": path, "material": "45-QT", "mesh": {"size_mm": 2.5},
                             "loads": [{"type": "fixed", "faces": [root]}], "n_modes": 4})
    assert r["status"] == "ok", r["messages"]
    e, i, a, rho, length = E * 1e6, 0.01 ** 4 / 12, 1e-4, STEEL["density_kg_m3"], 0.1
    theory = 1.875104 ** 2 / (2 * math.pi) * math.sqrt(e * i / (rho * a * length ** 4))
    assert r["data"]["freqs"][0]["hz"] == pytest.approx(theory, rel=0.03)


def test_fea_errors(box, tmp_path):
    path, root, _tip = box
    assert analysis.run("fea", {"step_path": str(tmp_path / "nope.step")})["status"] == "failed"
    out = analysis.run("fea", {"step_path": path, "material": "HT200", "loads": [{"type": "fixed", "faces": [root]}]})
    assert out["status"] == "failed" and "elastic_modulus_mpa" in out["messages"][0]  # 缺数据不估
    out = analysis.run("fea", {"step_path": path, "material": "45-QT", "loads": [{"type": "fixed", "faces": [root]}]})
    assert out["status"] == "failed" and "载荷" in out["messages"][0]


# ---------------------------------------------------------------- 疲劳


def test_rainflow_astm_repeating_history():
    """ASTM E1049-85 图 6 的历程 −2, 1, −3, 5, −1, 3, −4, 4, −2 作为重复块：4 个全循环。"""
    cycles = sorted(fatigue.rainflow([-2, 1, -3, 5, -1, 3, -4, 4, -2]))
    assert cycles == [(1.5, -0.5), (2.0, 1.0), (3.5, 0.5), (4.5, 0.5)]  # (幅值, 平均值)，即范围 3、4、7、9
    assert fatigue.rainflow([10, -10, 5, -5]) == [(5.0, 0.0), (10.0, 0.0)]


def test_constant_amplitude_matches_hand():
    for miner in ("original", "haibach"):
        r = analysis.run("fatigue", {"material": "45-QT", "stress_ref_mpa": 300, "load_ref": 1.0,
                                     "load_series": [-1.0, 1.0], "block_seconds": 1, "surface_factor": 0.92,
                                     "size_factor": 0.85, "miner": miner})
        assert r["status"] == "ok", r["messages"]
        hand = fatigue.hand_check(300, 0, STEEL, 0.92, 0.85, haibach=miner == "haibach")
        assert r["data"]["life_blocks"] == pytest.approx(hand, rel=1e-3)
    # 有平均应力：Goodman 修正
    r = analysis.run("fatigue", {"material": "45-QT", "stress_ref_mpa": 500, "load_ref": 1.0, "load_series": [0.0, 1.0],
                                 "block_seconds": 1, "surface_factor": 0.92, "size_factor": 0.85, "miner": "original"})
    assert r["data"]["life_blocks"] == pytest.approx(fatigue.hand_check(250, 250, STEEL, 0.92, 0.85), rel=1e-3)


def test_below_fatigue_limit():
    base = {"material": "45-QT", "stress_ref_mpa": 100, "load_ref": 1.0, "load_series": [-1.0, 1.0], "block_seconds": 1,
            "surface_factor": 0.92, "size_factor": 0.85}
    assert analysis.run("fatigue", {**base, "miner": "original"})["data"]["infinite"] is True
    assert analysis.run("fatigue", {**base, "miner": "haibach"})["data"]["life_blocks"] > 1e7


def test_fatigue_requires_data_and_factors():
    base = {"stress_ref_mpa": 300, "load_ref": 1.0, "load_series": [-1.0, 1.0], "block_seconds": 1}
    out = analysis.run("fatigue", {**base, "material": "Q345", "surface_factor": 0.9, "size_factor": 0.9})
    assert out["status"] == "failed" and "fatigue_limit_bending_mpa" in out["messages"][0]
    out = analysis.run("fatigue", {**base, "material": "45-QT"})
    assert out["status"] == "failed" and "surface_factor" in out["messages"][0]  # 不给缺省值
