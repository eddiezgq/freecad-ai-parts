"""引擎独立评审（M3 #52 前）发现问题的回归测试（ADR-0028）。"""

from __future__ import annotations

import copy

import pytest
from engine_helpers import case_by_id, edited, port, resolver

from engine.checks_electrical import c9, c10
from engine.checks_interface import c2, c3
from engine.checks_performance import c4, c6, c7, c8
from engine.result import FAIL, PASS, UNKNOWN, WARN, CheckResult, overall
from engine.system import load_system
from engine.validate import validate
from engine.values import bounds, capacity, demand

M400 = "test.servo_motor.test-vendor.m400"
R20 = "test.reducer.test-vendor.r20-100"
D400 = "test.drive.test-vendor.d400"


def _sys(overrides=None, edit=None, req=None):
    s = copy.deepcopy(case_by_id("valid/m400-r20-d400")["system"])
    if req:
        s["requirement"].update(req)
    if edit:
        edit(s)
    return load_system(s, resolver(overrides))


def _as_range(pv, lo, hi):
    pv.pop("value", None)
    pv.update(min=lo, max=hi)


def _add(name, cid):
    return lambda s: s["components"].append({"instance": name, "component": cid})


# ---------------------------------------------------------------- 取数


def test_bounds_forms():
    assert bounds({"value": 2}) == (2, 2)
    assert bounds({"min": 1, "max": 3}) == (1, 3)
    assert bounds({"nominal": 0.7, "tol_lower": -0.05, "tol_upper": 0.02}) == pytest.approx((0.65, 0.72))
    assert bounds({"min": 1}) == (1, None)
    assert capacity({"nominal": 10, "tol_lower": -1}) == 9 and demand({"nominal": 10, "tol_upper": 2}) == 12
    assert bounds({"value": float("inf")}) == (None, None) and bounds({"value": 10**400}) == (None, None)


# ---------------------------------------------------------------- H1 多实例


@pytest.mark.parametrize(("extra", "checks"), [
    (("motor2", M400), ("C4", "C5", "C6", "C7", "C9", "C10")),
    (("reducer2", R20), ("C4", "C5", "C6", "C7")),
    (("drive2", D400), ("C9", "C10")),
])
def test_multiple_instances_unknown(extra, checks):
    s = copy.deepcopy(case_by_id("valid/m400-r20-d400")["system"])
    _add(*extra)(s)
    report = validate(s, resolver())
    status = {c["check"]: c["status"] for c in report["checks"]}
    for chk in checks:
        assert status[chk] == UNKNOWN, (chk, status[chk])
    assert report["overall"] in (UNKNOWN, FAIL)


# ---------------------------------------------------------------- H2 需求侧取上端


def test_motor_current_range_uses_upper():
    over = edited(M400, lambda c: _as_range(port(c, "power_in")["spec"]["rated_current_a"], 2.5, 3.2))
    assert c9(_sys(over)).status == FAIL  # 驱动器 2.8 < 3.2


def test_motor_peak_range_in_c6_uses_upper():
    over = edited(M400, lambda c: _as_range(c["params"]["peak_torque_nm"], 0.5, 5.73))
    over.update(edited(R20, lambda c: c["params"]["momentary_max_torque_nm"].update(value=300)))
    assert c6(_sys(over)).status == WARN  # 5.73 × 100 × 0.7 = 401 > 300


def test_ratio_range():
    over = edited(R20, lambda c: _as_range(c["params"]["ratio"], 50, 200))
    s = _sys(over, req={"output_speed_rpm": 40})
    assert c7(s).findings[0].status == FAIL  # 40 × 200 = 8000 > 6000
    r4 = c4(_sys(over, req={"output_torque_cont_nm": 10}))
    assert r4.findings[0].measured == pytest.approx(12 / (50 * 0.7))  # 电机侧取下端


def test_input_inertia_range_uses_upper():
    j = (10 * 2.6e-5 - 6.9e-6) * 1e4  # 按 6.9e-6 刚好等于 10
    over = edited(R20, lambda c: _as_range(c["params"]["input_inertia_kgm2"], 6.0e-6, 6.9e-6))
    assert c8(_sys(over, req={"load_inertia_kgm2": j})).status == PASS
    over = edited(R20, lambda c: _as_range(c["params"]["input_inertia_kgm2"], 6.0e-6, 7.0e-6))
    assert c8(_sys(over, req={"load_inertia_kgm2": j})).status == WARN


def test_efficiency_tolerance_form():
    def tol(c):
        pv = c["params"]["efficiency_ratio"]
        pv.pop("value")
        pv.update(nominal=0.7, tol_lower=-0.1, tol_upper=0.05)
    r = c4(_sys(edited(R20, tol), req={"output_torque_cont_nm": 10}))
    assert r.status != UNKNOWN and r.findings[0].measured == pytest.approx(12 / 60)


# ---------------------------------------------------------------- H3 压装须过盈或过渡


def test_press_fit_with_clearance_fails():
    def press(c):
        spec = port(c, "input_bore")["spec"]
        spec["clamping"]["value"] = "press_fit"
        spec["feature"]["value"] = "plain"
    def plain_shaft(c):
        spec = port(c, "shaft")["spec"]
        spec["feature"]["value"] = "plain"
        spec.pop("key_width_mm")
    over = {**edited(R20, press), **edited(M400, plain_shaft)}
    r = c2(_sys(over))
    assert r.status == FAIL and any("不能压装" in f.message for f in r.findings)
    over[M400]["ports"][0]["spec"]["fit"]["value"] = "p6"  # H7/p6 过盈
    assert c2(_sys(over)).status == PASS


# ---------------------------------------------------------------- 其余


def test_all_not_applicable_is_unknown():
    assert overall([CheckResult("C8"), CheckResult("C11")]) == UNKNOWN


def test_c1_bad_link_reported_as_missing_in_c2():
    over = edited(R20, lambda c: port(c, "input_bore").update(motion="stationary"))
    r = c2(_sys(over))
    assert r.status == FAIL and "缺少" in r.to_dict()["message"]


def test_missing_standard_ports_unknown():
    over = edited(D400, lambda c: c["ports"].remove(port(c, "power_in")))
    assert c9(_sys(over)).status == UNKNOWN
    over = edited(D400, lambda c: c["ports"].remove(port(c, "encoder_in")))

    def drop_enc(s):
        s["connections"] = [x for x in s["connections"] if "encoder" not in x["a"] + x["b"]]
    assert c10(_sys(over, edit=drop_enc)).findings[0].status == UNKNOWN


def test_accepted_diameter_range_warns():
    def accept(c):
        spec = port(c, "input_bore")["spec"]
        spec["accepted_diameter_range_mm"] = {**spec["diameter_mm"], "min": 8, "max": 16}
        spec["accepted_diameter_range_mm"].pop("value")
        spec["diameter_mm"]["value"] = 16
    r = c2(_sys(edited(R20, accept)))
    assert any(f.status == WARN and "轴套" in f.message for f in r.findings)


def test_equality_findings_have_no_margin():
    over = edited(R20, lambda c: port(c, "input_bore")["spec"]["diameter_mm"].update(value=11))
    d = c2(_sys(over)).to_dict()
    assert "margin_ratio" not in d


def test_bearing_outer_ring_and_boundary():
    import test_engine_interface as tei

    bearing = tei._bearing(inner_d=18)
    housing = copy.deepcopy(port(bearing, "inner"))
    housing.update(id="bore", motion="stationary", dir="bidir")
    housing["spec"] = {k: copy.deepcopy(v) for k, v in housing["spec"].items() if k != "fit_system"}
    housing["spec"]["diameter_mm"]["value"] = 35
    housing["spec"]["fit"]["value"] = "H7"
    housing["spec"]["clamping"] = copy.deepcopy(housing["spec"]["fit"])
    housing["spec"]["clamping"]["value"] = "press_fit"
    housing_comp = {**copy.deepcopy(FIX_ADAPTER), "ports": [housing, copy.deepcopy(FIX_ADAPTER["ports"][1])]}
    over = {"test.bearing.test-vendor.b1": bearing, FIX_ADAPTER["id"]: housing_comp}
    s = {"id": "x", "requirement": {"output_torque_cont_nm": 1, "output_speed_rpm": 1},
         "components": [{"instance": "bearing", "component": "test.bearing.test-vendor.b1"},
                        {"instance": "housing", "component": FIX_ADAPTER["id"]}],
         "connections": [{"a": "bearing.outer", "b": "housing.bore"}]}
    r = c2(load_system(s, resolver(over)))
    assert r.findings[1].status == PASS and "H7" in r.findings[1].message  # 外圈静止 → 轴承座 H7
    # 内圈 d = 18 属于 (0, 18]：推荐 h5、js5
    from engine.rules import bearing_fit_classes
    assert bearing_fit_classes("inner", "rotating", "deep_groove", 18) == {"h5", "js5"}
    assert "js6" in bearing_fit_classes("inner", "rotating", "deep_groove", 18.0001)


FIX_ADAPTER = __import__("engine_helpers").FIXTURES["test.adapter.test-vendor.sleeve-11-19"]


def test_c3_tolerance_float_boundary():
    over = edited(R20, lambda c: port(c, "motor_flange")["spec"]["pcd_mm"].update(value=70.05))
    assert c3(_sys(over)).findings[0].status == PASS
