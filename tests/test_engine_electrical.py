"""电气、信号与包络校验 C9–C11（issue #51，ADR-0027）。"""

from __future__ import annotations

import copy
import math

import pytest
from engine_helpers import CASES, assert_golden, case, case_by_id, edited, port, resolver

from engine.checks_electrical import c9, c10, c11
from engine.result import FAIL, NA, PASS, UNKNOWN, WARN
from engine.system import load_system

M400 = "test.servo_motor.test-vendor.m400"
D400 = "test.drive.test-vendor.d400"


def _sys(req_update=None, overrides=None, edit=None, cid="valid/m400-r20-d400"):
    s = copy.deepcopy(case_by_id(cid)["system"])
    if req_update:
        s["requirement"].update(req_update)
    if edit:
        edit(s)
    return load_system(s, resolver(overrides))


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_golden_c9_c11(path):
    s = load_system(case(path)["system"], resolver())
    assert_golden(path, {r.check: r.status for r in (c9(s), c10(s), c11(s))})


def test_swapped_wiring_is_missing_connection():
    s = load_system(case_by_id("invalid/c1-swapped-wiring")["system"], resolver())
    assert c9(s).status == FAIL and "缺少动力连接" in c9(s).to_dict()["message"]
    assert c10(s).findings[0].status == FAIL


# ---------------------------------------------------------------- C9


@pytest.mark.parametrize(("volt", "want"), [(200, PASS), (240, PASS), (199.9, FAIL), (240.1, FAIL)])
def test_c9_supply_voltage_range(volt, want):
    r = c9(_sys({"supply": {"current_type": "ac", "voltage_v": volt, "phases": 1}}))
    assert next(f for f in r.findings if "供电" in f.message and "V" in f.message).status == want


def test_c9_supply_type_and_phases():
    assert c9(_sys({"supply": {"current_type": "dc", "voltage_v": 220, "phases": 0}})).status == FAIL
    assert c9(_sys({"supply": {"current_type": "ac", "voltage_v": 220, "phases": 3}})).status == FAIL


def test_c9_no_supply_in_requirement():
    def drop(s):
        s["requirement"].pop("supply")
    r = c9(_sys(edit=drop))
    assert r.status == PASS and not any("供电" in f.message for f in r.findings)


def test_c9_voltage_class_and_currents():
    over = edited(D400, lambda c: port(c, "motor_out")["spec"]["voltage_class_v"].update(value=400))
    assert c9(_sys(overrides=over)).status == FAIL
    # 额定电流刚好相等通过；峰值电流略小告警
    over = edited(D400, lambda c: (port(c, "motor_out")["spec"]["rated_current_a"].update(value=2.8),
                                   port(c, "motor_out")["spec"]["peak_current_a"].update(value=8.49)))
    r = c9(_sys(overrides=over))
    assert r.status == WARN and "峰值扭矩受限" in r.to_dict()["message"]
    over = edited(M400, lambda c: port(c, "power_in")["spec"].pop("peak_current_a"))
    assert c9(_sys(overrides=over)).status == UNKNOWN


def test_c9_not_applicable_without_drive():
    def drop(s):
        s["components"] = [c for c in s["components"] if c["instance"] != "drive"]
        s["connections"] = [c for c in s["connections"] if "drive" not in c["a"] + c["b"]]
    assert c9(_sys(edit=drop)).status == NA


# ---------------------------------------------------------------- C10


def _proprietary(drive_vendor):
    def motor(c):
        enc = port(c, "encoder")["spec"]
        enc["protocol"]["value"] = "vendor_proprietary"
        enc["vendor"] = copy.deepcopy(enc["protocol"])
        enc["vendor"]["value"] = "Acme"

    def drive(c):
        spec = port(c, "encoder_in")["spec"]
        spec["protocol"]["value"] = ["biss_c", "vendor_proprietary"]
        if drive_vendor:
            spec["vendor"] = copy.deepcopy(spec["kind"])
            spec["vendor"]["value"] = drive_vendor
    return {**edited(M400, motor), **edited(D400, drive)}


def test_c10_proprietary_vendor():
    assert c10(_sys(overrides=_proprietary("acme"))).status == PASS  # 忽略大小写
    assert c10(_sys(overrides=_proprietary("Other"))).status == FAIL
    assert c10(_sys(overrides=_proprietary(None))).status == UNKNOWN


def test_c10_fieldbus_optional():
    def drop(s):
        s["requirement"].pop("fieldbus_protocol")
    r = c10(_sys(edit=drop))
    assert r.status == PASS and len(r.findings) == 1


# ---------------------------------------------------------------- C11


def test_c11_envelope_diameter_boundary():
    # 电机 60 × 60 方形截面，对角线 84.85；驱动器不计入（ADR-0027）
    diag = math.hypot(60, 60)
    r = c11(_sys({"max_envelope_diameter_mm": diag}))
    assert r.status == PASS and "motor" in r.to_dict()["message"]
    assert c11(_sys({"max_envelope_diameter_mm": diag - 0.01})).status == FAIL


def test_c11_length_not_applicable():
    r = c11(_sys({"max_envelope_length_mm": 100}))
    assert r.status == NA and "FreeCAD" in r.to_dict()["message"]
    r = c11(_sys({"max_envelope_length_mm": 100, "max_envelope_diameter_mm": 200}))
    assert r.status == PASS and any(f.status == NA for f in r.findings)


def test_c11_bearing_speed():
    import test_engine_interface as tei

    bearing = tei._bearing()
    bearing["params"]["limiting_speed_rpm"] = copy.deepcopy(bearing["params"]["width_mm"])
    bearing["params"]["limiting_speed_rpm"]["value"] = 30

    def add(s):
        s["components"].append({"instance": "bearing", "component": "test.bearing.test-vendor.b1"})
    over = {"test.bearing.test-vendor.b1": bearing}
    assert c11(_sys(overrides=over, edit=add)).status == PASS  # 需求输出 30 rpm，刚好等于
    assert c11(_sys({"output_speed_rpm": 30.1}, overrides=over, edit=add)).status == FAIL
    bearing["params"].pop("limiting_speed_rpm")
    assert c11(_sys(overrides=over, edit=add)).status == UNKNOWN
