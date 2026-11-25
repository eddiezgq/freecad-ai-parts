"""带传动核打滑、蠕滑和轴上拉力；没给初拉力、摩擦系数判 unknown。

《多体动力学》书第 24 章线索第 38 条（问渠 CAD 0.3.8 细则）。库里的带（D 60 / 120 mm、中心距 250 mm）原来按 1:2 刚性传动：
30 N·m 照样传，而 μ 0.3、初拉力 150 N 时欧拉极限（折到大带轮）只有 7.37 N·m；带轮轴反力只有自重，带的拉力合力 298 N 没有。
"""
import math

import pytest

import analysis
from analysis.mbd import mechanisms

GIVEN = {"initial_tension_n": 150.0, "mu": 0.3}


def test_euler_limit_numbers():
    bc = mechanisms.belt_check(GIVEN, 0.0)
    assert bc["slip_ratio_e_mu_alpha"] == pytest.approx(2.388, abs=1e-3)       # 书：打滑时 F1/F2 = e^{μα} = 2.388
    assert bc["torque_limit_driven_nm"] == pytest.approx(7.37, abs=0.01)
    beta = math.asin(0.06 / 0.5)
    assert bc["shaft_load_n"] == pytest.approx(2 * 150 * math.cos(beta), rel=1e-9)   # 不传力时两边都是 F0：≈ 298 N
    assert bc["status"] == "pass"


def test_creep_ratio():
    bc = mechanisms.belt_check(GIVEN | {"ea_n": 20000.0}, 2.0)
    F = 2.0 / 0.03
    e1, e2 = (150 + F / 2) / 20000, (150 - F / 2) / 20000
    assert bc["transmission_ratio_with_creep"] == pytest.approx(2 * (1 + e1) / (1 + e2), rel=1e-12)
    assert bc["transmission_ratio_with_creep"] > 2.0


def _run(params, load_nm):
    return analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-BLT-BELT", "params": params}, "duration_s": 0.2,
                                "gravity": False, "drives": [{"joint": "pulley1", "kind": "speed", "value": 300},
                                                             {"joint": "pulley2", "kind": "torque", "value": -load_nm}]})


def test_overload_reports_slip():
    res = _run(GIVEN, 30.0)                      # 原来照样按 1:2 传
    assert res["data"]["belt"]["status"] == "fail"
    assert any("带会打滑" in m for m in res["messages"])


def test_light_load_passes():
    # 按主动轮力矩峰值核（含起步时约 5.8 N·m 的过渡）：初拉力 600 N 时极限 14.7 N·m（主动轮）
    res = _run({"initial_tension_n": 600.0, "mu": 0.3}, 2.0)
    assert res["data"]["belt"]["status"] == "pass"
    assert res["data"]["belt"]["safety_factor"] > 1


def test_missing_tension_is_unknown():
    res = _run({}, 2.0)
    assert res["data"]["belt"]["status"] == "unknown"
    assert any("打滑没有核查" in m for m in res["messages"])
