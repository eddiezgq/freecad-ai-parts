"""轴的校核（ADR-0100 42.1）：标准题——《机械设计》33.11 平缝机上轴 LS-101 的书中结果，与三道解析解。"""

from __future__ import annotations

import math
import re

import pytest

import analysis
from analysis import shaft
from analysis.common import materials

MAT = materials.get("45-QT")

# 《机械设计》33.11（问渠教材，ex33_11.py 的输出）：台阶的 kt 是书中有限元算的（33.5.4 节的程序），这里照用
BOOK = {"S5": 2.7460819736691437, "S55": 2.2737180429648154, "SB5": 3.414164880740697, "SB55": 2.8236925752555306,
        "St5": 3.9773522292535572, "nc1": 25139.379755046655, "nc2": 48170.26045333266,
        "q_s": 0.6708050012086405, "q_t": 0.7296812072214579, "eps": 0.9692184776895287, "beta": 0.9122876363018027}
KT_I, KT_II = (2.0405327466155305, 1.4933575966450117), (2.3306613715159963, 1.6070317843068973)


def ls101_setup() -> dict:
    return {
        "material": "45-QT",
        "segments": [{"diameter_mm": d, "length_mm": length} for d, length in [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]],
        "supports": [27, 252], "speeds_rpm": [5000, 5500], "drive_z_mm": 282,
        "masses": [{"name": n, "z_mm": z, "mass_kg": m} for n, z, m in [
            ("针杆曲柄与平衡块", 11, 0.15), ("挑线凸轮", 45, 0.05), ("送布偏心轮", 150, 0.08), ("同步带轮", 262, 0.06),
            ("手轮与电机转子", 282, 0.45)]],
        "loads": [{"type": "crank_slider", "z_mm": 11, "crank_radius_mm": 15.5, "rod_length_mm": 55,
                   "reciprocating_mass_kg": 0.12, "balance_ratio": 0.45},
                  {"type": "torque_load", "z_mm": 11, "power_w": 150},
                  {"type": "force", "z_mm": 262, "fx_n": 0, "fy_n": -120}],
        "sections": [
            {"name": "截面 I（Ø10→Ø12）", "z_mm": 22, "diameter_mm": 10, "fillet_mm": 0.5, "kt_bending": KT_I[0],
             "kt_torsion": KT_I[1], "kt_source": "《机械设计》33.11（有限元）", "surface": "ground"},
            {"name": "截面 II（Ø12→Ø16）", "z_mm": 32, "diameter_mm": 12, "fillet_mm": 0.5, "kt_bending": KT_II[0],
             "kt_torsion": KT_II[1], "kt_source": "《机械设计》33.11（有限元）", "surface": "ground"}],
        "required_safety": 1.5, "critical_ratio": 1.3,
    }


@pytest.fixture(scope="module")
def ls101():
    r = analysis.run("shaft", ls101_setup())
    assert r["status"] == "ok", r["messages"]
    return r["data"]


def test_module_registered():
    st = next(m for m in analysis.modules() if m["id"] == "shaft")
    assert st["available"]


def test_factors_match_book():
    assert shaft.notch_sensitivity(0.5, 640) == pytest.approx(BOOK["q_s"], rel=1e-9)
    assert shaft.notch_sensitivity(0.5, 640, torsion=True) == pytest.approx(BOOK["q_t"], rel=1e-9)
    assert shaft.size_factor(10) == pytest.approx(BOOK["eps"], rel=1e-9)
    assert shaft.surface_factor("ground", 640) == pytest.approx(BOOK["beta"], rel=1e-9)


def test_ls101_safety_within_2pct_of_book(ls101):
    """书里取截面弯矩用的是 0.495 mm 的网格（截面 I 落在 z = 21.78），本模块按 z = 22 精确算，差约 1 %"""
    s5, s55 = ls101["speeds"]
    got = {"S5": s5["sections"][0]["S"], "S55": s55["sections"][0]["S"], "SB5": s5["sections"][1]["S"],
           "SB55": s55["sections"][1]["S"], "St5": s5["sections"][0]["S_tau"]}
    for k, v in got.items():
        assert v == pytest.approx(BOOK[k], rel=0.02), k
    assert got["St5"] == pytest.approx(BOOK["St5"], rel=1e-4)          # 转矩不受网格影响：几乎相同
    assert got["S5"] < got["SB5"]                                       # 截面 I 最危险，与书一致
    assert all(v["status"] == "pass" for v in ls101["verdicts"])


def test_ls101_critical_speed_within_2pct_of_book(ls101):
    """书里取 E = 206 GPa，材料库 45-QT 是 210 GPa：临界转速差 √(210/206) − 1 ≈ 0.97 %"""
    nc1, nc2 = ls101["critical_speeds_rpm"]
    assert nc1 == pytest.approx(BOOK["nc1"], rel=0.02) and nc2 == pytest.approx(BOOK["nc2"], rel=0.02)
    assert nc1 / BOOK["nc1"] == pytest.approx(math.sqrt(210 / 206), rel=1e-3)
    assert ls101["critical_ratio"] > 4                                  # 刚性轴


def _uniform(d=20.0, length=300.0, **kw):
    return {"material": "45-QT", "segments": [{"diameter_mm": d, "length_mm": length}], "supports": [0, length],
            "speeds_rpm": [1000], **kw}


def test_analytic_critical_speed_simply_supported():
    """简支等直轴一阶临界转速 n = 30/π·(π/L)²·√(EI/ρA)（解析解）"""
    d, length = 20.0, 300.0
    r = shaft.run(_uniform(d, length))
    e, rho = MAT["elastic_modulus_mpa"] * 1e6, MAT["density_kg_m3"]
    i_, a_ = math.pi * (d / 1000) ** 4 / 64, math.pi * (d / 1000) ** 2 / 4
    w = (math.pi / (length / 1000)) ** 2 * math.sqrt(e * i_ / (rho * a_))
    assert r["data"]["critical_speeds_rpm"][0] == pytest.approx(w * 60 / (2 * math.pi), rel=0.005)


def test_analytic_safety_rotating_bending_with_steady_torque():
    """简支轴中点受空间固定的力 F，截面在中点：σa = (FL/4)/W、σm = 0；平均功率传过截面：τa = 0、τm = T/Wt"""
    d, length, f, p, n = 20.0, 300.0, 1000.0, 1500.0, 1000.0
    sec = {"name": "中点", "z_mm": 150, "diameter_mm": d, "fillet_mm": 1.0, "kt_bending": 1.8, "kt_torsion": 1.4,
           "surface": "machined"}
    r = shaft.run(_uniform(d, length, drive_z_mm=length, sections=[sec],
                           loads=[{"type": "force", "z_mm": 150, "fx_n": 0, "fy_n": -f},
                                  {"type": "torque_load", "z_mm": 0, "power_w": p}]))
    s = r["data"]["speeds"][0]["sections"][0]
    sb, s1, t1 = MAT["ultimate_strength_mpa"], MAT["fatigue_limit_bending_mpa"], MAT["fatigue_limit_torsion_mpa"]
    sa = f * length / 4 / (math.pi * d ** 3 / 32)
    tm = p / (2 * math.pi * n / 60) * 1000 / (math.pi * d ** 3 / 16)
    eps, beta = shaft.size_factor(d), shaft.surface_factor("machined", sb)
    ks = (1 + shaft.notch_sensitivity(1.0, sb) * 0.8) / eps + 1 / beta - 1
    s_s = s1 / (ks * sa)
    s_t = t1 / (t1 / (sb / math.sqrt(3)) * tm)
    assert s["sigma_a_mpa"] == pytest.approx(sa, rel=1e-6) and abs(s["sigma_m_mpa"]) < 1e-6 * sa
    assert s["tau_m_mpa"] == pytest.approx(tm, rel=1e-9) and s["tau_a_mpa"] == pytest.approx(0, abs=1e-9)
    assert s["S"] == pytest.approx(s_s * s_t / math.hypot(s_s, s_t), rel=1e-4)
    reac = r["data"]["speeds"][0]["reactions"]
    assert [x["max_n"] for x in reac] == pytest.approx([f / 2, f / 2], rel=1e-9)


def test_analytic_deflection_center_load():
    """简支等直轴中点集中力：δ = FL³/(48EI)，支点转角 θ = FL²/(16EI)"""
    d, length, f = 20.0, 300.0, 1000.0
    r = shaft.run(_uniform(d, length, loads=[{"type": "force", "z_mm": 150, "fx_n": f, "fy_n": 0}]))
    df = r["data"]["speeds"][0]["deflection"]
    ei = MAT["elastic_modulus_mpa"] * math.pi * d ** 4 / 64
    assert df["max_deflection_mm"] == pytest.approx(f * length ** 3 / (48 * ei), rel=1e-6)
    assert df["slope_at_supports_rad"][0] == pytest.approx(f * length ** 2 / (16 * ei), rel=1e-6)


@pytest.mark.parametrize("patch,msg", [
    ({"supports": [27]}, "两个"), ({"speeds_rpm": []}, "转速"), ({"material": "HT200"}, "fatigue_limit|elastic"),
    ({"loads": [{"type": "magic", "z_mm": 1}]}, "不认识"),
    ({"sections": [{"name": "x", "z_mm": 22, "diameter_mm": 10, "fillet_mm": 0.5, "kt_bending": 2}]}, "kt_torsion"),
    ({"supports": [27, 400]}, "不在轴上"),
])
def test_bad_setup_fails_with_reason(patch, msg):
    r = shaft.run({**ls101_setup(), **patch})
    assert r["status"] == "failed" and any(re.search(msg, m) for m in r["messages"])


def test_verdict_fail_reported():
    s = ls101_setup()
    s["required_safety"] = 3.0
    r = shaft.run(s)
    assert any(v["status"] == "fail" for v in r["data"]["verdicts"]) and "不满足" in r["messages"][0]


def test_kt_fea_matches_book_within_3pct():
    """台阶 Ø10→Ø12、r = 0.5：本模块的有限元 α 与书中（33.5.4 节程序）相差 ≤ 3 %（两者网格不同；本模块随加密略增）"""
    from analysis.common.solvers import find_ccx
    from analysis.shaft import kt

    if find_ccx() is None:
        if __import__("os").environ.get("CI"):
            raise AssertionError("CI 中没有 ccx")
        pytest.skip("本机没有 CalculiX")
    k = kt.stepped_bar(10.0, 12.0, 0.5)
    assert k["kt_bending"] == pytest.approx(KT_I[0], rel=0.03)
    assert k["kt_torsion"] == pytest.approx(KT_I[1], rel=0.03)
    assert k["kt_bending"] > k["kt_torsion"] > 1
