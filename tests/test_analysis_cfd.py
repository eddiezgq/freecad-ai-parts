"""流体分析（ADR-0059，M11 第三步）：标准题。不联网。CI 中装 OpenFOAM 必须跑；本机没装时跳过。

门槛：平行平板层流压降（Poiseuille，< 3%）、平板层流换热（Pohlhausen，< 5%）、湍流平板通道摩擦与换热（Blasius、
Dittus–Boelter，< 10%）、绕圆柱 Re = 40 阻力系数在 1.52–1.57 附近（< 5%）；任意零件进虚拟风洞全流程。
"""

from __future__ import annotations

import os

import pytest

import analysis
from analysis.cfd import foam

if os.environ.get("CI"):
    assert foam.find_openfoam(), "CI 中没有 OpenFOAM"
    import gmsh  # noqa: F401
else:
    pytestmark = pytest.mark.skipif(foam.find_openfoam() is None, reason="本机没装 OpenFOAM")


def test_unavailable_without_openfoam(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.delenv("FAP_OPENFOAM_BIN", raising=False)
    st = next(m for m in analysis.modules() if m["id"] == "cfd")
    assert not st["available"] and any("OpenFOAM" in m for m in st["missing"]) and "WSL" in st["install"]
    out = analysis.run("cfd", {"step_path": "x.step"})
    assert out["status"] == "failed" and "OpenFOAM" in out["messages"][0]
    (tmp_path / "bin").mkdir()
    for n in foam.NEED:
        f = tmp_path / "bin" / n
        f.write_text("#!/bin/sh\n")
        f.chmod(0o755)
    monkeypatch.setenv("FAP_OPENFOAM_BIN", str(tmp_path / "bin"))
    assert foam.find_openfoam() == str(tmp_path / "bin")


def test_bench_laminar(tmp_path):
    out = analysis.run("cfd", {"analysis": "bench"})
    assert out["status"] == "ok", out["messages"]
    err = {c["name"]: c["relative_error_ratio"] for c in out["checks"]}
    assert err["平行平板层流压降"] < 0.03 and err["平板层流强制对流平均 Nu"] < 0.05, err


def test_turbulent_channel_friction_and_heat(tmp_path):
    from analysis.cfd import bench as B

    cf, nu = B.duct(str(tmp_path / "d"))
    assert abs(cf["error"]) < 0.10, cf
    assert abs(nu["error"]) < 0.10, nu


def test_cylinder_re40_drag(tmp_path):
    from analysis.cfd import bench as B

    r = B.cylinder(str(tmp_path / "c"))
    assert 1.52 * 0.95 < r["value"] < 1.57 * 1.05, r


def _box_step(path, dx, dy, dz):
    from analysis.fea.geometry import _LOCK, _gmsh

    with _LOCK:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add("box")
        gmsh.model.occ.addBox(-dx / 2, -dy / 2, -dz / 2, dx, dy, dz)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
        gmsh.clear()
    return str(path)


def test_wind_tunnel_box(tmp_path):
    """任意零件进虚拟风洞：100×40×20 mm 方块，侧吹 2 m/s、表面 60 ℃。"""
    step = _box_step(tmp_path / "box.step", 100, 40, 20)
    out = analysis.run("cfd", {"step_path": step, "flow": {"velocity_ms": 2, "direction": "+x", "air_t_c": 25},
                               "heat": {"wall_t_c": 60}, "mesh": {"cells_target": 40000, "level": 2},
                               "solver": {"iterations": 400}})
    assert out["status"] == "ok", out["messages"]
    d = out["data"]
    assert d["cells"] < 80000 and d["drag_n"] > 0 and 0.3 < d["Cd"] < 3
    assert d["heat_w"] > 0 and 5 < d["h_mean"] < 80
    faces = {f["id"]: f for f in d["faces"]}
    assert len(faces) == 6 and max(f["p_pa"] for f in faces.values()) > 0
    # 面编号与有限元的面编号一致（FreeCAD 中按中心、面积对应）
    fea_ids = {f["id"] for f in analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]}
    assert set(faces) == fea_ids
    bad = analysis.run("cfd", {"step_path": step, "flow": {"velocity_ms": 100}})
    assert bad["status"] == "failed" and "风速" in bad["messages"][0]
    assert analysis.run("cfd", {"step_path": step, "flow": {"direction": "up"}})["status"] == "failed"
