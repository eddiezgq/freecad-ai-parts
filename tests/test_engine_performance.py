"""性能链校验 C4–C8（issue #50，ADR-0026）：公式逐项单测，含刚好等于限值与稍微超出。"""

from __future__ import annotations

import copy

import pytest
from engine_helpers import CASES, assert_golden, case, case_by_id, edited, resolver

from engine.checks_performance import c4, c5, c6, c7, c8
from engine.result import FAIL, NA, PASS, UNKNOWN, WARN
from engine.system import load_system

M400 = "test.servo_motor.test-vendor.m400"
R20 = "test.reducer.test-vendor.r20-100"
# m400：额定 1.27、峰值 3.82 N·m、最高 6000 rpm、转子惯量 2.6e-5；
# r20-100：i = 100、η = 0.7、额定 34、启停峰值 54、瞬间最大 98 N·m、最高输入 6500、平均 3500 rpm、输入惯量 6.9e-6


def _sys(req=None, overrides=None, drop=()):
    s = copy.deepcopy(case_by_id("valid/m400-r20-d400")["system"])
    if req is not None:
        s["requirement"] = req
    s["components"] = [c for c in s["components"] if c["instance"] not in drop]
    s["connections"] = [c for c in s["connections"] if not any(c[k].split(".")[0] in drop for k in ("a", "b"))]
    return load_system(s, resolver(overrides))


def _req(**kw):
    base = {"output_torque_cont_nm": 10, "output_speed_rpm": 10}
    return {**base, **kw}


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_golden_c4_c8(path):
    s = load_system(case(path)["system"], resolver())
    assert_golden(path, {r.check: r.status for r in (c4(s), c5(s), c6(s), c7(s), c8(s))})


# ---------------------------------------------------------------- C4


@pytest.mark.parametrize(("t_cont", "want"), [(34 / 1.2, PASS), (34 / 1.2 * 1.001, FAIL)])
def test_c4_reducer_rated_boundary(t_cont, want):
    """(2) SF·T ≤ 34：刚好等于通过，超出 0.1% 失败。"""
    r = c4(_sys(_req(output_torque_cont_nm=t_cont)))
    assert r.findings[1].status == want


@pytest.mark.parametrize(("t_cont", "want"), [(1.27 * 70 / 1.2, PASS), (1.27 * 70 / 1.2 * 1.001, FAIL)])
def test_c4_motor_side_boundary(t_cont, want):
    """(1) SF·T/(i·η) ≤ 1.27：把减速器额定调大，只看电机侧。"""
    big = edited(R20, lambda c: c["params"]["rated_torque_nm"].update(value=1000))
    r = c4(_sys(_req(output_torque_cont_nm=t_cont), big))
    assert r.findings[0].status == want
    assert r.findings[0].measured == pytest.approx(1.2 * t_cont / 70)


def test_c4_safety_factor_from_requirement():
    r = c4(_sys(_req(output_torque_cont_nm=20, safety_factor=2.0)))
    assert r.findings[1].measured == 40 and r.status == FAIL


def test_c4_direct_drive_and_no_motor():
    r = c4(_sys(_req(output_torque_cont_nm=1.0), drop=("reducer",)))
    assert len(r.findings) == 1 and r.findings[0].measured == pytest.approx(1.2)  # i = 1、η = 1
    assert r.status == PASS
    r = c4(_sys(_req(output_torque_cont_nm=20), drop=("motor",)))
    assert len(r.findings) == 1 and r.findings[0].limit == 34
    assert c4(_sys(drop=("motor", "reducer"))).status == NA


def test_c4_efficiency_range_uses_lower_bound():
    rng = edited(R20, lambda c: c["params"].update(efficiency_ratio={**c["params"]["efficiency_ratio"],
                                                                    "min": 0.6, "max": 0.8}) or
                 c["params"]["efficiency_ratio"].pop("value"))
    r = c4(_sys(_req(output_torque_cont_nm=10), rng))
    assert r.findings[0].measured == pytest.approx(12 / 60)


# ---------------------------------------------------------------- C5


@pytest.mark.parametrize(("t_peak", "want"), [(54, PASS), (54.06, FAIL)])
def test_c5_reducer_peak_boundary(t_peak, want):
    assert c5(_sys(_req(output_torque_peak_nm=t_peak))).findings[1].status == want


@pytest.mark.parametrize(("t_peak", "want"), [(3.82 * 70, PASS), (3.82 * 70 * 1.001, FAIL)])
def test_c5_motor_side_boundary(t_peak, want):
    big = edited(R20, lambda c: c["params"]["repeated_peak_torque_nm"].update(value=1000))
    assert c5(_sys(_req(output_torque_peak_nm=t_peak), big)).findings[0].status == want


def test_c5_not_applicable_without_peak():
    assert c5(_sys(_req())).status == NA


# ---------------------------------------------------------------- C6


@pytest.mark.parametrize(("limit", "want"), [(3.82 * 70, PASS), (3.82 * 70 * 0.999, WARN)])
def test_c6_boundary(limit, want):
    over = edited(R20, lambda c: c["params"]["momentary_max_torque_nm"].update(value=limit))
    r = c6(_sys(_req(), over))
    assert r.status == want
    if want == WARN:
        assert "扭矩限幅" in r.to_dict()["message"]


def test_c6_uses_upper_efficiency_and_needs_both():
    rng = edited(R20, lambda c: c["params"].update(efficiency_ratio={**c["params"]["efficiency_ratio"],
                                                                    "min": 0.6, "max": 0.8}) or
                 c["params"]["efficiency_ratio"].pop("value"))
    assert c6(_sys(_req(), rng)).findings[0].measured == pytest.approx(3.82 * 80)
    assert c6(_sys(_req(), drop=("reducer",))).status == NA
    miss = edited(R20, lambda c: c["params"].pop("momentary_max_torque_nm"))
    assert c6(_sys(_req(), miss)).status == UNKNOWN


# ---------------------------------------------------------------- C7


@pytest.mark.parametrize(("speed", "motor", "reducer_max"), [(60, PASS, PASS), (60.01, FAIL, PASS), (65.01, FAIL, FAIL)])
def test_c7_boundaries(speed, motor, reducer_max):
    r = c7(_sys(_req(output_speed_rpm=speed)))
    assert r.findings[0].status == motor and r.findings[1].status == reducer_max


@pytest.mark.parametrize(("speed", "want"), [(35, PASS), (35.01, WARN)])
def test_c7_average_speed_warns(speed, want):
    assert c7(_sys(_req(output_speed_rpm=speed))).findings[2].status == want


def test_c7_average_speed_optional():
    over = edited(R20, lambda c: c["params"].pop("avg_input_speed_limit_rpm"))
    r = c7(_sys(_req(), over))
    assert len(r.findings) == 2 and r.status == PASS


# ---------------------------------------------------------------- C8


def test_c8_formula_and_boundary():
    # (J/100² + 6.9e-6) / 2.6e-5 = 10 → J = (10 × 2.6e-5 − 6.9e-6) × 1e4
    j = (10 * 2.6e-5 - 6.9e-6) * 1e4
    assert c8(_sys(_req(load_inertia_kgm2=j))).status == PASS
    assert c8(_sys(_req(load_inertia_kgm2=j * 1.001))).status == WARN
    r = c8(_sys(_req(load_inertia_kgm2=j * 1.001, inertia_ratio_limit=20)))
    assert r.status == PASS and r.findings[0].limit == 20


def test_c8_not_applicable_and_unknown():
    assert c8(_sys(_req())).status == NA
    miss = edited(R20, lambda c: c["params"].pop("input_inertia_kgm2"))
    r = c8(_sys(_req(load_inertia_kgm2=1.0), miss))
    assert r.status == UNKNOWN and "输入侧惯量" in r.to_dict()["message"]
    direct = c8(_sys(_req(load_inertia_kgm2=2.6e-4), drop=("reducer",)))
    assert direct.findings[0].measured == pytest.approx(10)
