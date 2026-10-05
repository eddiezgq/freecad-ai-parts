"""效率曲线查表（ADR-0047）。"""

from __future__ import annotations

import pytest

from engine.efficiency import lookup

CURVE = {"points": [
    {"ambient_temp_c": t, "input_speed_rpm": n, "efficiency_ratio": e}
    for n, row in ((500, (0.62, 0.72, 0.78)), (3500, (0.33, 0.47, 0.58)))
    for t, e in zip((-10, 0, 10), row)]}


def test_picks_the_next_higher_speed_curve_and_interpolates():
    lo, hi, note = lookup(CURVE, 3000, 5)
    assert lo == hi == pytest.approx((0.47 + 0.58) / 2)
    assert "3500 rpm" in note and "5 °C" in note
    assert lookup(CURVE, 500, 0)[0] == pytest.approx(0.72)


def test_without_temperature_takes_the_worst_and_best_on_that_curve():
    lo, hi, note = lookup(CURVE, 1000, None)
    assert (lo, hi) == (0.33, 0.58) and "未给环境温度" in note


def test_out_of_range_is_unknown():
    assert lookup(CURVE, 4000, 0) is None  # 高于图上最高转速
    assert lookup(CURVE, 1000, 25) is None  # 超出图的温度范围
    assert lookup(None, 1000, 0) is None and lookup(CURVE, None, 0) is None


def _system_with_curve(ambient):
    import copy

    from engine_helpers import FIXTURES, case_by_id, resolver

    from engine.validate import validate

    system = copy.deepcopy(case_by_id("valid/m200-adapters-r25-d400")["system"])
    rid = next(c["component"] for c in system["components"] if c["instance"] == "reducer")
    red = copy.deepcopy(FIXTURES[rid])
    src = red["params"]["efficiency_ratio"]["source"]
    red["params"].pop("efficiency_ratio")
    red["params"]["efficiency_curve"] = {"points": CURVE["points"], "condition": "额定扭矩、脂润滑", "source": src,
                                         "method": "manual", "confidence": 1, "reviewed": True}
    if ambient is not None:
        system["requirement"]["ambient_temp_c"] = ambient
    else:
        system["requirement"].pop("ambient_temp_c", None)
    return validate(system, resolver({rid: red}))


def test_checks_use_the_curve_at_the_required_temperature():
    """ADR-0047：没有 efficiency_ratio 时按曲线取效率，C4、C5 写明取法；schema 允许曲线参数。"""
    report = _system_with_curve(5)
    c4 = next(c for c in report["checks"] if c["check"] == "C4")
    assert c4["status"] != "unknown"
    assert any("效率按曲线取" in f["message"] and "5 °C" in f["message"] for f in c4["findings"])
    cold = _system_with_curve(None)
    c4_cold = next(c for c in cold["checks"] if c["check"] == "C4")
    assert any("未给环境温度" in f["message"] for f in c4_cold["findings"])
    assert _system_with_curve(25)["checks"][3]["status"] == "unknown"  # 超出图的温度范围
