"""实体柔性体（ADR-0097 D6b，补充十五）：STEP → gmsh + CalculiX 整体矩阵 → Craig-Bampton → 多体模型，应力回放。

验收件：钢方杆 300×12×12 mm，两端端面做界面（平面界面）。参考：欧拉梁解析、同一网格 CalculiX 直接静力。
需要 gmsh 和 CalculiX（CI 单元测试作业装了）；没有就跳过。
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from analysis.mbd.dae import run as R

L, H = 300.0, 12.0
E, NU, RHO = 2e5, 0.3, 7850.0
MAT = {"elastic_modulus_mpa": E, "poisson_ratio": NU, "density_kg_m3": RHO}
EI = E * 1e6 * (H / 1000) ** 4 / 12
RA = RHO * (H / 1000) ** 2
ENDS = [{"name": "a", "center_mm": [0, 0, 0], "radius_mm": 9, "normal": [1, 0, 0]},
        {"name": "b", "center_mm": [L, 0, 0], "radius_mm": 9, "normal": [1, 0, 0]}]


@pytest.fixture(scope="module")
def bar(tmp_path_factory):
    gmsh = pytest.importorskip("gmsh")
    from analysis.common.solvers import find_ccx
    from analysis.mbd import flexsolid as FS

    if find_ccx() is None:
        pytest.skip("没有 CalculiX")
    path = str(tmp_path_factory.mktemp("bar") / "bar.step")
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        g = _gmsh()
        g.clear()
        g.model.add("bar")
        g.model.occ.addBox(0, -H / 2, -H / 2, L, H, H)
        g.model.occ.synchronize()
        g.write(path)
        g.clear()
    flex, info = FS.reduce_step(path, MAT, ENDS, size_mm=4, fixed_interface_modes=10)
    assert gmsh
    return path, flex, info


def body(flex):
    return {"format": "mbd-model/1", "name": "bar", "bodies": [{"id": "bar", "flex": flex}]}


def test_reduction_is_consistent(bar):
    _, flex, info = bar
    m = np.array(flex["node_mass_kg"])
    assert m.sum() == pytest.approx(RA * L / 1000, rel=1e-9)            # HRZ 集中质量保总质量
    assert flex["interface_nodes"] == [info["nodes"], info["nodes"] + 1]
    assert len(flex["shapes"]) == info["modes"] == len(flex["frequencies_hz"])
    f1 = 4.7300 ** 2 / (2 * math.pi) * math.sqrt(EI / (RA * (L / 1000) ** 4))
    assert flex["frequencies_hz"][0] == pytest.approx(f1, rel=2e-2)       # 自由–自由一阶（欧拉梁，未计剪切与转动惯量）


def test_pinned_pinned_frequency(bar):
    _, flex, _ = bar
    data, _ = R.run_model({**body(flex), "gravity_mm_s2": [0, 0, 0], "analysis": {"type": "linear"},
                           "joints": [{"id": "p", "type": "revolute", "body_i": "ground", "body_j": "bar", "point_mm": [0, 0, 0],
                                       "axis": [0, 0, 1]},
                                      {"id": "q", "type": "spherical", "body_i": "ground", "body_j": "bar", "point_mm": [L, 0, 0]}]})
    f = min(m["frequency_hz"] for m in data["linear"]["modes"] if m["frequency_hz"] > 1)
    ref = math.pi / 2 / (L / 1000) ** 2 * math.sqrt(EI / RA)
    assert f == pytest.approx(ref, rel=1e-2)


def _direct_ccx_tip(path):
    """同一网格的 CalculiX 直接静力（根部端面全固定、自重）：端面平均竖向位移（mm）"""
    import tempfile

    from analysis.common.solvers import find_ccx
    from analysis.fea import solve as S
    from analysis.fea.geometry import _LOCK, _gmsh, load_step
    from analysis.mbd.flexsolid import _run, _write_inp

    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        g = _gmsh()
        load_step(g, path, tmp)
        nt, xyz, tets = S.mesh(g, 4)
        fix = [int(t) for t, x in zip(nt, xyz, strict=True) if abs(x[0]) < 1e-9]
        face = [int(t) for t, x in zip(nt, xyz, strict=True) if abs(x[0] - L) < 1e-9]
        steps = ("*NSET,NSET=FIX\n" + "".join(f"{n}\n" for n in fix)
                 + "*STEP\n*STATIC\n*BOUNDARY\nFIX,1,3,0\n*DLOAD\nEALL,GRAV,9810,0,0,-1\n*NODE FILE\nU\n*END STEP\n")
        _write_inp(os.path.join(tmp, "job.inp"), nt, xyz, tets, MAT, steps)
        _run(find_ccx(), tmp)
        disp, _ = S.read_frd(os.path.join(tmp, "job.frd"))
    return float(np.mean([disp[n][2] for n in face]))


def test_cantilever_sag_matches_direct_fe_and_stress_replay(bar):
    path, flex, _ = bar
    data, _ = R.run_model({**body(flex), "gravity_mm_s2": [0, 0, -9810], "analysis": {"type": "static"},
                           "joints": [{"id": "c", "type": "fixed", "body_i": "ground", "body_j": "bar", "point_mm": [0, 0, 0]}],
                           "requests": [{"id": "tip", "type": "point", "body": "bar", "point_mm": [L, 0, 0]}]})
    tip = data["requests"]["tip"]["pos_mm"][0][2]
    assert tip == pytest.approx(_direct_ccx_tip(path), rel=1e-3)          # 与同一网格直接静力一致
    q = RA * 9.81
    assert -tip == pytest.approx(q * (L / 1000) ** 4 / (8 * EI) * 1000, rel=2e-2)
    # 应力回放：跨中上表面中线的 σx = M·c/I（M = q(L − x)²/2）
    from analysis.mbd.flexsolid import von_mises

    eta = np.array(data["flex"]["bar"]["eta"][0])
    nodes = np.array(flex["nodes_mm"])[flex["stress_nodes"]]
    j = int(np.argmin(np.linalg.norm(nodes - [L / 2, 0, H / 2], axis=1)))
    x = nodes[j][0]                                          # 离跨中最近的上表面中线节点（网格不一定正好在 150 mm）
    assert abs(nodes[j][1]) < 1e-6 and abs(nodes[j][2] - H / 2) < 1e-6 and abs(x - L / 2) < 5
    sig = np.einsum("k,ki->i", eta, np.array(flex["stress_shapes_mpa"])[:, j, :])
    ref = q * ((L - x) / 1000) ** 2 / 2 * (H / 2000) / ((H / 1000) ** 4 / 12) / 1e6
    assert sig[0] == pytest.approx(ref, rel=5e-2)                          # 上表面受拉
    assert von_mises(sig) == pytest.approx(ref, rel=5e-2)
    st = data["flex"]["bar"]["stress"]
    assert st["peak_mpa"] >= von_mises(sig) and st["peak_node_mm"][0] < L / 4         # 最大在根部附近
