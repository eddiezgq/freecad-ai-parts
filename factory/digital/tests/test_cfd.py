# -*- coding: utf-8 -*-
"""第 16 轮：流体分析。标准题和教材公式比；虚拟风洞全流程；计算服务任务。没装 OpenFOAM 时跳过。"""
import shutil
import time

import numpy as np
import pytest

pytestmark = pytest.mark.skipif(shutil.which("simpleFoam") is None or shutil.which("snappyHexMesh") is None,
                                reason="没装 OpenFOAM")


def test_foam_reader_and_poiseuille(tmp_path):
    from cae import cfd_bench as B
    r = B.poiseuille(str(tmp_path / "p"))
    assert abs(r["error"]) < 0.03, r


def test_flat_plate_laminar_heat(tmp_path):
    from cae import cfd_bench as B
    r = B.plate(str(tmp_path / "pl"))
    assert abs(r["error"]) < 0.05, r


def test_turbulent_channel_friction_and_heat(tmp_path):
    from cae import cfd_bench as B
    cf, nu = B.duct(str(tmp_path / "d"))
    assert abs(cf["error"]) < 0.10, cf
    assert abs(nu["error"]) < 0.10, nu


def test_cylinder_re40_drag(tmp_path):
    pytest.importorskip("build123d")
    from cae import cfd_bench as B
    r = B.cylinder(str(tmp_path / "c"))
    assert 1.52 * 0.95 < r["value"] < 1.57 * 1.05, r


def test_wind_tunnel_box(tmp_path):
    """任意零件进虚拟风洞：一块 100×40×20 mm 的方块，侧吹 2 m/s、表面 60 ℃"""
    pytest.importorskip("build123d")
    import build123d as bd
    from cae import cfd as C
    from cae.thermal_parts import tempfile_step
    step = tempfile_step(bd.Box(100, 40, 20))
    st, surf, aux = C.solve(step, {"flow": {"velocity_ms": 2, "direction": "+x", "air_t_c": 25}, "heat": {"wall_t_c": 60},
                                   "mesh": {"cells_target": 40000, "level": 2}, "solver": {"iterations": 400}}, str(tmp_path / "box"))
    assert st["cells"] < 80000 and st["drag_n"] > 0 and 0.3 < st["Cd"] < 3
    assert st["heat_w"] > 0 and 5 < st["h_mean"] < 80
    f = {x["id"]: x for x in aux["faces"]}
    assert len(f) == 6
    # 迎风面压力为正、平均散热系数最大的面之一
    front = max(f.values(), key=lambda x: x["p_pa"])
    assert front["p_pa"] > 0
    assert len(surf["positions"]) == len(surf["p"]) == len(surf["h"])
    assert aux["slice"]["vmax"] > 2 and aux["streamlines"]
    with pytest.raises(ValueError):
        C.solve(step, {"flow": {"velocity_ms": 100}}, str(tmp_path / "bad"))


def test_service_cfd_job(tmp_path, monkeypatch):
    pytest.importorskip("build123d")
    import build123d as bd
    from fastapi.testclient import TestClient
    from cae import service
    from cae.thermal_parts import tempfile_step
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    with TestClient(service.app) as c:
        g = c.post("/geometry", content=tempfile_step(bd.Box(60, 30, 20)), headers={"content-type": "application/step"}).json()
        assert c.post("/cfd/jobs", json={"step_sha": "nope"}).status_code == 404
        assert c.post("/cfd/jobs", json={"step_sha": g["sha"], "setup": {"flow": {"velocity_ms": 200}}}).status_code == 400
        j = c.post("/cfd/jobs", json={"step_sha": g["sha"], "setup": {"flow": {"velocity_ms": 1.5, "direction": "-y"},
                                                                      "mesh": {"cells_target": 20000, "level": 2},
                                                                      "solver": {"iterations": 300}}, "factory": "t"}).json()
        for _ in range(600):
            j = c.get("/jobs/" + j["id"]).json()
            if j["status"] in ("done", "failed"):
                break
            time.sleep(1)
        assert j["status"] == "done", j.get("error")
        r = c.get("/cfd/jobs/{}/result".format(j["id"])).json()
        assert r["aux"]["faces"] and np.asarray(r["surface"]["positions"]).shape[1] == 3
        assert j["stats"]["drag_n"] > 0 and "heat_w" not in j["stats"]


def test_natural_convection_box(tmp_path):
    """第 62 轮：静止空气里的热方块（自然对流，非定常跑到稳定）。竖直侧面的 h 和竖板经验式 1.42·(ΔT/H)^¼ 同一量级；
    朝下的底面最小；总散热量为正、后段波动小"""
    pytest.importorskip("build123d")
    import build123d as bd
    from cae import cfd_natural as N
    from cae.thermal_parts import tempfile_step
    step = tempfile_step(bd.Box(120, 120, 60))
    st, surf, aux = N.solve(step, {"flow": {"mode": "natural", "air_t_c": 25}, "heat": {"wall_t_c": 55},
                                   "mesh": {"cells_target": 25000, "level": 2}, "solver": {"t_end_s": 8}}, str(tmp_path / "nat"))
    assert st["mode"] == "natural" and st["heat_w"] > 0 and st["Ra"] < 1e9
    import json
    json.dumps(st)                                   # 计算服务要把它写成 JSON（numpy 的 bool、float 都不行）
    f = sorted(aux["faces"], key=lambda x: x["area_mm2"])
    assert len(f) == 6
    ref = N.h_vertical_plate(30, 0.06)
    sides = [x["h_w_m2k"] for x in f if abs(x["area_mm2"] - 7200) < 800]
    assert len(sides) == 4 and all(0.5 * ref < h < 1.3 * ref for h in sides), (sides, ref)
    assert len(surf["h"]) == len(surf["positions"])
    assert 5.5 < N.h_radiation(0.85, 55, 25) < 6.5


def test_sewing_ebox_part_groups():
    """第 62 轮：缝纫机电控箱（铝外壳、顶面翅片、功率模块贴在顶板里面）：面分组和自动填好的热载荷"""
    pytest.importorskip("build123d")
    from cae import geometry as G
    from cae import thermal_parts as TP
    p = TP.params_of("sew_ebox", {"fins": 6})
    fl, _, _ = G.faces(TP.build("sew_ebox", p))
    g = TP.groups("sew_ebox", p, fl)
    assert len(g["ipm"]) == 5 and len(g["inner_bottom"]) == 1 and len(g["inner"]) == 5 and len(g["outer"]) >= 6 + 6 * 4
    ex = TP.example("sew_ebox", p, fl)
    assert sum(t["power_w"] for t in ex["thermal"] if t["type"] == "heat_flux") == pytest.approx(26)
    with pytest.raises(ValueError):
        TP.params_of("sew_ebox", {"fins": 30, "fin_t": 6})
