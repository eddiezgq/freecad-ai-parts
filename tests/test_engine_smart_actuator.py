"""一体化关节模组校验（engine/smart_actuator.py，ADR-0117 117.3）。

标准题：直流电机力矩—转速直线 n(T) = n₀(1 − T/Tₛ)（教材公式）；堵转力矩不当连续额定用；缺数据判 unknown。
"""

from __future__ import annotations

import pytest

from engine.smart_actuator import candidates, check


def pv(v):
    return {"value": v, "source": {"doc": "src-test-fixture"}, "method": "manual", "confidence": 1, "reviewed": True}


def comp(cid="test.smart_actuator.v.a", ts=4.0, n0=50.0, mass=0.08, rated=None):
    p = {"stall_torque_nm": pv(ts), "no_load_speed_rpm": pv(n0), "mass_kg": pv(mass), "backlash_arcmin": pv(15)}
    if rated is not None:
        p["rated_torque_nm"] = pv(rated)
    return {"id": cid, "category": "smart_actuator", "params": p}


REQ = {"output_torque_cont_nm": 1.0, "output_torque_peak_nm": 2.0, "output_speed_rpm": 20.0, "safety_factor": 1.2}


def by(r):
    return {c["check"]: c for c in r["checks"]}


def test_speed_torque_line_conservative_without_operating_points():
    r = by(check(REQ, comp()))
    assert r["S1"]["status"] == "pass" and r["S1"]["limit"] == 4.0 and r["S1"]["measured"] == pytest.approx(2.4)
    assert r["S3"]["limit"] == pytest.approx(50 * (1 - 2.4 / 4.0))                  # 20 rpm：刚好够
    assert r["S3"]["status"] == "pass"
    assert by(check(dict(REQ, output_speed_rpm=21), comp()))["S3"]["status"] == "fail"


def test_operating_points_check_each_instant():
    # 峰值力矩出现在低速、最高转速出现在小力矩：逐点核比保守核宽松
    pts = [(2.0, 2.0), (0.5, 40.0)]
    r = by(check(dict(REQ, output_speed_rpm=40), comp(), pts))
    assert r["S3"]["status"] == "pass"
    assert r["S3"]["limit"] == pytest.approx(50 * (1 - 0.5 * 1.2 / 4.0))             # 最紧的是 (0.5, 40)
    assert by(check(dict(REQ, output_speed_rpm=40), comp()))["S3"]["status"] == "fail"


def test_stall_torque_is_not_a_continuous_rating():
    r = by(check(REQ, comp()))
    assert r["S2"]["status"] == "unknown" and "30%" in r["S2"]["message"]           # 1.2 / 4.0
    assert check(REQ, comp())["overall"] == "unknown"                               # 不判通过
    assert by(check(REQ, comp(rated=1.5)))["S2"]["status"] == "pass"
    assert by(check(REQ, comp(rated=1.0)))["S2"]["status"] == "fail"


def test_missing_data_is_unknown():
    c = comp()
    del c["params"]["no_load_speed_rpm"]
    assert by(check(REQ, c))["S3"]["status"] == "unknown"
    assert by(check({"safety_factor": 1.2}, comp()))["S1"]["status"] == "unknown"


def test_candidates_drop_failures_and_sort_by_mass_then_margin():
    lib = [comp("test.smart_actuator.v.heavy", ts=10, mass=0.165), comp("test.smart_actuator.v.light", ts=4, mass=0.08),
           comp("test.smart_actuator.v.weak", ts=2, mass=0.02), comp("test.smart_actuator.v.light-strong", ts=5, mass=0.08),
           {"id": "servo_motor.x.y", "category": "servo_motor", "params": {}}]
    ids = [r["component"] for r in candidates(REQ, lib)]
    assert ids == ["test.smart_actuator.v.light-strong", "test.smart_actuator.v.light", "test.smart_actuator.v.heavy"]
