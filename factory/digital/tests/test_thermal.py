# -*- coding: utf-8 -*-
"""第 14 轮 热分析：标准题与解析解对比（平壁导热、圆柱肋片、集总参数冷却、热应力、热伸长），计算服务的热分析任务。"""
import math
import os
import tempfile
import time

import numpy as np
import pytest

pytest.importorskip("gmsh")
bd = pytest.importorskip("build123d")
import shutil  # noqa: E402

if not shutil.which(os.environ.get("WQ_CCX", "ccx")):
    pytest.skip("没有 CalculiX（ccx）", allow_module_level=True)

from cae import geometry as G  # noqa: E402
from cae import materials as M  # noqa: E402
from cae import thermal as TH  # noqa: E402


def step(shape):
    f = tempfile.mktemp(suffix=".step")
    bd.export_step(shape, f)
    data = open(f, "rb").read()
    os.remove(f)
    return data


def planes_at(faces, axis, val):
    return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][axis] - val) < 1e-6]


@pytest.fixture(scope="module")
def bar():
    s = step(bd.Box(100, 10, 10, align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.CENTER)))
    return s, G.faces(s)[0]


def test_materials_have_thermal_properties():
    for m in M.public():
        assert m["k_w_mk"] > 0 and m["c_j_kgk"] > 0 and m["alpha_1e6"] > 0 and any("热物性" in x for x in m["sources"])
    assert M.get("45-QT")["k_w_mk"] == pytest.approx(49.8) and M.FILM[0]["h"] == pytest.approx(8.15)


def test_plane_wall_conduction(bar):
    """一维导热：一端面输入 10 W（热流 10⁵ W/m²），另一端 20 ℃：T = 20 + q·L/k"""
    s, F = bar
    st, surf, _ = TH.solve(s, {"material": M.get("45-QT"), "mesh": {"size_mm": 3}, "thermal": [
        {"type": "heat_flux", "faces": planes_at(F, 0, 0), "power_w": 10},
        {"type": "temperature", "faces": planes_at(F, 0, 100), "value_c": 20}]})
    assert st["t_max_c"] == pytest.approx(20 + 1e5 * 0.1 / 49.8, rel=0.01)
    assert len(surf["temp"]) == len(surf["positions"])


def test_pin_fin():
    """圆柱肋片 Ø10×100（45 钢），根部 100 ℃，其余表面 h = 25、20 ℃：散热量与肋片公式（端部对流）比"""
    s = step(bd.Cylinder(5, 100, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN)))
    F = G.faces(s)[0]
    st, _, _ = TH.solve(s, {"material": M.get("45-QT"), "mesh": {"size_mm": 3}, "thermal": [
        {"type": "temperature", "faces": planes_at(F, 2, 0), "value_c": 100},
        {"type": "convection", "faces": "rest", "h_w_m2k": 25, "t_inf_c": 20}]})
    h, k, D, L = 25, 49.8, 0.01, 0.1
    P, A = math.pi * D, math.pi * D * D / 4
    m = math.sqrt(h * P / (k * A))
    r = h / (m * k)
    Q = math.sqrt(h * P * k * A) * 80 * (math.sinh(m * L) + r * math.cosh(m * L)) / (math.cosh(m * L) + r * math.sinh(m * L))
    assert st["heat_out_convection_w"] == pytest.approx(Q, rel=0.03)


def test_lumped_cooling():
    """10 mm 铝块从 120 ℃ 在 20 ℃ 空气里冷却（h = 50，Bi ≈ 0.003）：θ = θ₀·exp(−t/τ)，τ = ρcV/(hA)"""
    s = step(bd.Box(10, 10, 10))
    al = M.get("6061-T6")
    st, _, _ = TH.solve(s, {"material": al, "mesh": {"size_mm": 3}, "transient": {"duration_s": 300, "steps": 30, "t0_c": 120},
                            "thermal": [{"type": "convection", "faces": "rest", "h_w_m2k": 50, "t_inf_c": 20}]})
    tau = al["density"] * 1000 * al["c_j_kgk"] * (0.01 / 6) / 50
    ser = st["series"]
    assert ser[0] == [0.0, 120.0, 120.0] and ser[-1][0] == pytest.approx(300)
    for t, _, tm in ser[1:]:                       # 误差按初始温差算：后向欧拉每步 1.5 s，偏差 < 1% θ₀
        assert abs((tm - 20) - 100 * math.exp(-t / tau)) < 1.0
    t, _, tm = min(ser, key=lambda r: abs(r[0] - tau))    # 一个时间常数处：θ/θ₀ = e⁻¹，相对误差 < 3%
    assert (tm - 20) == pytest.approx(100 * math.exp(-t / tau), rel=0.03)


def test_thermal_stress_and_expansion():
    """热—结构耦合：两端固定的长杆均匀升温 100 ℃，中段 σ = E·α·ΔT；一端固定时自由伸长 α·L·ΔT"""
    s = step(bd.Box(300, 10, 10, align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.CENTER)))
    F = G.faces(s)[0]
    m = M.get("45-QT")
    ends = planes_at(F, 0, 0) + planes_at(F, 0, 300)
    st, _, aux = TH.solve(s, {"analysis": "thermo_mech", "material": m, "mesh": {"size_mm": 4}, "ref_temp_c": 20,
                              "thermal": [{"type": "temperature", "faces": "rest", "value_c": 120}],
                              "loads": [{"type": "fixed", "faces": ends}]})
    mid = [aux["vm"][n] for n, p in aux["nodes"].items() if abs(p[0] - 150) < 2 and n in aux["vm"]]
    assert np.mean(mid) == pytest.approx(m["E_mpa"] * m["alpha_1e6"] * 1e-6 * 100, rel=0.02)
    assert st["safety_factor"] > 0
    st, _, aux = TH.solve(s, {"analysis": "thermo_mech", "material": m, "mesh": {"size_mm": 4}, "ref_temp_c": 20,
                              "thermal": [{"type": "temperature", "faces": "rest", "value_c": 120}],
                              "loads": [{"type": "fixed", "faces": planes_at(F, 0, 0)}]})
    U, P = aux["U"], aux["nodes"]
    far = np.mean([U[n][0] for n, p in P.items() if abs(p[0] - 300) < 1e-6 and n in U])
    half = np.mean([U[n][0] for n, p in P.items() if abs(p[0] - 150) < 2 and n in U])
    assert far - half == pytest.approx(m["alpha_1e6"] * 1e-6 * 150 * 100, rel=0.01)


def test_errors():
    s = step(bd.Box(10, 10, 10))
    with pytest.raises(ValueError):
        TH.solve(s, {"material": M.get("45-QT"), "thermal": [{"type": "heat_body", "power_w": 5}]})


def test_service_thermal_job(tmp_path, monkeypatch, bar):
    from fastapi.testclient import TestClient
    from cae import service
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    s, _ = bar
    with TestClient(service.app) as c:
        assert c.get("/materials").json()["films"][0]["id"] == "air-still"
        g = c.post("/geometry", content=s).json()
        x0 = planes_at(g["faces"], 0, 0)
        assert c.post("/jobs", json={"step_sha": g["sha"], "setup": {"analysis": "thermal", "material_id": "45-QT",
                                                                    "thermal": [{"type": "heat_body", "power_w": 5}]}}).status_code == 400
        j = c.post("/jobs", json={"step_sha": g["sha"], "factory": "wq_test", "setup": {
            "analysis": "thermal", "material_id": "45-QT", "mesh": {"size_mm": 4},
            "thermal": [{"type": "heat_body", "power_w": 5}, {"type": "temperature", "faces": x0, "value_c": 20}]}}).json()
        for _ in range(240):
            j = c.get("/jobs/" + j["id"]).json()
            if j["status"] in ("done", "failed"):
                break
            time.sleep(0.5)
        assert j["status"] == "done", j.get("error")
        # 体积均匀发热 q、一端定温：T_max = 20 + q·L²/(2k)，q = 5 W / 10⁻⁵ m³
        assert j["stats"]["t_max_c"] == pytest.approx(20 + 5e5 * 0.01 / (2 * 49.8), rel=0.02)
        surf = service.read_surface(os.path.join(str(tmp_path), "jobs", j["id"], "surface.bin"))
        assert surf["temp"].max() == pytest.approx(j["stats"]["t_max_c"], rel=1e-3)


def test_housing_heat_balance_matches_textbook():
    """WQR-105 简化箱体（无散热筋）：内壁输入 P(1−η)，外表面 K_s = 17.45，底面绝热——外表面平均温度与教材公式一致"""
    from cae import thermal_parts as TP
    p = TP.params_of("housing")
    s = TP.build("housing", p)
    F = G.faces(s)[0]
    ex = TP.example("housing", p, F)
    assert {k: len(v) for k, v in ex["groups"].items()} == {"inner": 6, "outer": 5, "bottom": 1}
    f = ex["formula"]
    assert f["eta"] == pytest.approx(0.97 ** 2 * 0.99 ** 3, rel=1e-3) and f["loss_w"] == pytest.approx(482.6, abs=0.5)
    st, _, _ = TH.solve(s, {"material": M.get(ex["material_id"]), "thermal": ex["thermal"], "mesh": {"size_mm": ex["mesh_mm"]}})
    assert st["heat_out_convection_w"] == pytest.approx(f["loss_w"], rel=0.005)
    assert st["film_groups"][0]["mean_c"] == pytest.approx(f["t_oil_c"], abs=0.5)
    assert st["t_max_c"] > f["limit_c"]                      # 不加散热措施会超过 80 ℃：实验里要加散热筋或风扇
    p8 = TP.params_of("housing", {"fins": 8})
    assert TP.example("housing", p8, G.faces(TP.build("housing", p8))[0])["formula"]["t_oil_c"] < f["t_oil_c"] - 15


def test_heatsink_groups():
    from cae import thermal_parts as TP
    p = TP.params_of("heatsink")
    F = G.faces(TP.build("heatsink", p))[0]
    ex = TP.example("heatsink", p, F)
    assert len(ex["groups"]["pad"]) == 1 and ex["thermal"][0]["power_w"] == 65
    with pytest.raises(ValueError):
        TP.params_of("heatsink", {"fins": 30, "fin_t": 3})


def test_thermal_one_sentence_rules():
    """第 14 轮：一句话设置热边界（规则）"""
    pytest.importorskip("build123d")
    from cae import geometry as G
    from cae import thermal_parts as TP
    from hub import thermal_ai as A
    p = TP.params_of("housing", {})
    faces, _, solid = G.faces(TP.build("housing", p))
    g = TP.groups("housing", p, faces)
    r = A.rules_setup("箱体内壁发热 482.6 W，外表面自然对流通风良好，环境 25 度，HT200", faces, solid, g)
    assert r["material_id"] == "HT200" and not r["unmatched"]
    assert r["rows"][0] == {"kind": "heat_flux", "faces": g["inner"], "rest": False, "value": 482.6}
    assert r["rows"][1]["faces"] == g["outer"] and r["rows"][1]["h"] == 17.45 and r["rows"][1]["tinf"] == 25
    p = TP.params_of("heatsink", {})
    faces, _, solid = G.faces(TP.build("heatsink", p))
    g = TP.groups("heatsink", p, faces)
    r = A.rules_setup("CPU 接触面 65W，散热系数 h=40，30 分钟瞬态，初温 25 度", faces, solid, g)
    assert r["rows"][0]["faces"] == g["pad"] and r["rows"][1]["rest"] and r["rows"][1]["h"] == 40
    assert r["transient"] == {"duration_s": 1800.0, "t0_c": 25.0} and not r["unmatched"]
    r = A.rules_setup("接触面发热 65 W", faces, solid, g)                  # 没说散热：自动补其余所有面自然对流
    assert r["rows"][-1]["kind"] == "convection" and r["rows"][-1]["rest"]
    with pytest.raises(ValueError):
        A.setup(None, " ", faces, solid, g)
