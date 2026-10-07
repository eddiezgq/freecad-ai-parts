"""拓扑优化（ADR-0059，M11 第一步）：标准题。不联网。

门槛：MBB 梁 60×20、体积比 0.5、p = 3、r_min = 1.5 的柔度与 Andreassen 等 2011 的结果（203）差 < 2%，体积比守住；
得到桁架形状；轮廓面积与单元数一致；板件 STEP 能做有限元。
"""

from __future__ import annotations

import os

import pytest

import analysis
from analysis import topo
from analysis.common.solvers import find_ccx

np = pytest.importorskip("numpy")
pytest.importorskip("scipy")


def test_mbb_classic_benchmark():
    r = analysis.run("topo", {"preset": "mbb"})
    assert r["status"] == "ok"
    d = r["data"]
    chk = {c["name"].split("（")[0]: c for c in r["checks"]}
    assert chk["MBB 梁柔度"]["relative_error_ratio"] < 0.02, d["compliance"]
    assert abs(d["history"][-1][2] - 0.5) < 0.005 and d["converged"] and d["iterations"] < 200
    c = [h[1] for h in d["history"]]
    assert c[-1] < 0.25 * c[0]
    g = np.array(d["density"]) >= 0.5
    ny, nx = g.shape
    assert (ny, nx) == (20, 60)
    assert g[0, : nx // 2].all() and g[-1].all()          # 上弦、下弦连续
    assert (~g[1:-1, 1:-1]).sum() > 0.3 * (ny - 2) * (nx - 2)  # 中间挖空成桁架
    assert d["grey"] < 0.25


def test_presets_custom_and_errors():
    r = topo.run({"preset": "cantilever", "nelx": 32, "nely": 16, "volfrac": 0.4})
    g = np.array(r["data"]["density"]) >= 0.5
    assert g[0, 0] and g[-1, 0]                            # 固定端上下两角（弯矩最大处）有材料
    # 自定的支承、载荷与预设等价时结果相同
    same = topo.run({"preset": "custom", "nelx": 32, "nely": 16, "volfrac": 0.4,
                     "supports": [{"edge": "left", "span": [0, 1], "fix": "xy"}],
                     "loads": [{"edge": "right", "at": 0.5, "fy": -1}]})
    assert same["data"]["compliance"] == r["data"]["compliance"]
    for bad in ({"preset": "nope"}, {"preset": "mbb", "nelx": 200, "nely": 100}, {"preset": "mbb", "volfrac": 0.95},
                {"preset": "custom", "supports": [], "loads": []},
                {"preset": "custom", "supports": [{"edge": "middle"}], "loads": [{"edge": "top", "at": 0, "fy": -1}]},
                {"preset": "custom", "nelx": 16, "nely": 8, "supports": [{"edge": "left", "span": [0, 1], "fix": "y"}],
                 "loads": [{"edge": "right", "at": 0, "fy": -1}]}):
        out = analysis.run("topo", bad)
        assert out["status"] == "failed" and out["messages"], bad


def test_outline_polygons():
    # 一个 6×4 的框（中间 2×2 空）+ 一个只在角点相接的单元 + 一个孤立小块（去掉）
    d = [[1, 1, 1, 1, 1, 1, 0, 0],
         [1, 0, 0, 1, 1, 1, 0, 0],
         [1, 0, 0, 1, 1, 1, 0, 0],
         [1, 1, 1, 1, 1, 1, 0, 0],
         [0, 0, 0, 0, 0, 0, 1, 0]]
    pieces = topo.outline(d, 2.0, min_cells=1)
    assert len(pieces) == 2                                # 角点相接按两块
    big = pieces[0]
    assert len(big["holes"]) == 1 and topo._area([tuple(p) for p in big["outer"]]) == 6 * 4 * 4
    assert sorted(map(tuple, big["holes"][0])) == [(2.0, 4.0), (2.0, 8.0), (6.0, 4.0), (6.0, 8.0)]
    assert topo.outline_area(pieces) == pytest.approx((24 - 4 + 1) * 4)
    assert len(topo.outline(d, 2.0)) == 1                  # 小于 4 个单元的碎块去掉
    r = topo.run({"preset": "mbb", "length_mm": 120, "thickness_mm": 5})
    cells = (np.array(r["data"]["density"]) >= 0.5).sum()
    assert r["data"]["area_mm2"] == pytest.approx(cells * 4.0) and r["data"]["volume_mm3"] == pytest.approx(cells * 20.0)


def test_plate_step_goes_to_fea(tmp_path):
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        assert find_ccx()
    else:
        pytest.importorskip("gmsh")
        if find_ccx() is None:
            pytest.skip("本机没有 CalculiX")
    r = topo.run({"preset": "cantilever", "nelx": 32, "nely": 16, "volfrac": 0.5, "length_mm": 64, "thickness_mm": 4})
    step = topo.plate_step(r["data"]["outline"], 4, tmp_path / "plate.step")
    faces = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]
    left = [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0]) < 1e-6]
    right = [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0] - 64) < 1e-6]
    assert left and right
    out = analysis.run("fea", {"step_path": step, "material": "6061-T6", "mesh": {"size_mm": 2},
                               "loads": [{"type": "fixed", "faces": left},
                                         {"type": "force", "faces": right, "vector_n": [0, -200, 0]}]})
    assert out["status"] == "ok", out["messages"]
    assert out["data"]["u_max_mm"] > 0 and out["data"]["applied_force_n"][1] == pytest.approx(-200)
