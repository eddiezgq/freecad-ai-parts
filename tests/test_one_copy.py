"""M12（ADR-0060）：工厂计算服务的 cae/ 是转接层，与 FreeCAD 一侧的 analysis/ 对同一题给出同样结果。不联网。

工厂代码在 factory/digital（独立子项目），这里只导入它的转接层，与 analysis 直接算的结果逐项比较。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

import analysis
from analysis.common.solvers import find_ccx

FACTORY = Path(__file__).resolve().parent.parent / "factory" / "digital"


@pytest.fixture(scope="module")
def cae():
    pytest.importorskip("numpy")
    sys.path.insert(0, str(FACTORY))
    try:
        import cae as pkg

        yield pkg
    finally:
        sys.path.remove(str(FACTORY))


def test_kernels_are_the_same_objects(cae):
    from cae import cam_sim, cfd, cfd_heat, foam, mbd, solve
    from cae import mech_mjcf as mech

    import analysis.cam.sim
    import analysis.cfd.heat
    import analysis.cfd.solver
    import analysis.fea.solve
    import analysis.mbd.core
    import analysis.mbd.mechanisms

    assert foam.Mesh is analysis.cfd.foam.Mesh and cfd_heat.solve_T is analysis.cfd.heat.solve_T
    assert cfd.wall_forces is analysis.cfd.solver.wall_forces and solve.write_inp is analysis.fea.solve.write_inp
    assert mbd.simulate is analysis.mbd.core.simulate and mech.mjcf is analysis.mbd.mechanisms.mjcf
    assert cam_sim.simulate_turn is analysis.cam.sim.simulate_turn


def test_topology_same_result(cae):
    pytest.importorskip("scipy")
    from cae import topo

    f = topo.run("mbb", frames=0)
    a = analysis.run("topo", {"preset": "mbb"})["data"]
    assert f["compliance"] == a["compliance"] and f["density"] == a["density"]


def test_fatigue_same_cycles_and_life(cae):
    from cae import fatigue as FT

    from analysis import fatigue

    series = [0, 350, 100, 300, -50, 350, 0]
    assert sorted(FT.rainflow(series).tolist()) == sorted([list(c) for c in fatigue.rainflow(series)])
    mat = {"sigma_1": 275, "N_D": 1e7, "k": 9, "ultimate_mpa": 640}
    _, s = FT.compute([300.0], 1.0, [1, -1], 1.0, mat, surface="ground", size_factor=0.85)
    sd = 275 * 0.92 * 0.85
    assert s["life_blocks"] == pytest.approx(fatigue.sn_cycles(300, sd, 1e7, 9, True), rel=1e-12)


def test_turning_time_same(cae):
    from cae import cam_post, cam_sim

    from analysis.cam import sim

    g = "G21 G18 G99\nT0101\nG97 S1000 M03\nG00 X40.0 Z2.0\nG01 Z0.0 F0.2\nZ-100.0\nG00 X50.0\nM30\n"
    tf = cam_sim.timing(cam_sim.parse(g, "CNC-L01"), "CNC-L01")
    ta = sim.timing(sim.parse(g, cam_post.MACHINES["CNC-L01"]), cam_post.MACHINES["CNC-L01"])
    assert tf == ta and tf["cut_s"] == pytest.approx(100 / (0.2 * 1000) * 60 + 2 / (0.2 * 1000) * 60, rel=1e-3)


def test_static_fea_same_result(cae, tmp_path):
    pytest.importorskip("gmsh")
    if find_ccx() is None:
        pytest.skip("本机没有 CalculiX")
    from cae import materials as FM
    from cae import solve as S

    from analysis.fea.geometry import _LOCK, _gmsh

    path = tmp_path / "beam.step"
    with _LOCK:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add("beam")
        gmsh.model.occ.addBox(0, 0, 0, 100, 10, 10)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
        gmsh.clear()
    faces = analysis.run("fea", {"analysis": "faces", "step_path": str(path)})["data"]["faces"]
    fix = next(f["id"] for f in faces if abs(f["center"][0]) < 1e-6)
    tip = next(f["id"] for f in faces if abs(f["center"][0] - 100) < 1e-6)
    loads = [{"type": "fixed", "faces": [fix]}, {"type": "force", "faces": [tip], "vector_n": [0, -100, 0]}]
    fst, _, _ = S.solve(path.read_bytes(), {"material": FM.get("45-QT"), "loads": loads, "mesh": {"size_mm": 3}})
    a = analysis.run("fea", {"step_path": str(path), "material": "45-QT", "mesh": {"size_mm": 3}, "loads": loads})["data"]
    assert fst["u_max_mm"] == pytest.approx(a["u_max_mm"], rel=1e-6)
    assert fst["vm_max_mpa"] == pytest.approx(a["vm_max_mpa"], rel=1e-6)
    hand = 100 * 100 ** 3 / (3 * 210000 * 10 * 10 ** 3 / 12)  # 悬臂梁端部挠度 FL³/(3EI)
    assert math.isclose(a["u_max_mm"], hand, rel_tol=0.05)
