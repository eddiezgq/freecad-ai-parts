"""装配即校验（ADR-0048 第 5 条）：纯函数，用真实库组件测试。"""

from __future__ import annotations

import json
from pathlib import Path

from freecad_addon.core.live_check import check, system_from_layout
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
M6 = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
M2 = "servo_motor.yaskawa-electric-corporation.sgm7j-02a"
R25 = "reducer.harmonic-drive-llc.csf-25-100-2uh"
D = "drive.yaskawa-america-inc.sgd7s-1r6a"
REQ = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))


def layout(motor=M6, links=(("motor.shaft", "reducer.input_bore"), ("motor.mount_flange", "reducer.motor_flange"))):
    return {"instances": [{"instance": "motor", "component": motor}, {"instance": "reducer", "component": R25},
                          {"instance": "drive", "component": D}],
            "connections": [{"a": a, "b": b} for a, b in links]}


def test_electrical_links_are_added_by_convention_and_noted():
    system, notes = system_from_layout(layout(), LIB.get)
    assert {"a": "drive.motor_out", "b": "motor.power_in"} in system["connections"]
    assert {"a": "motor.encoder", "b": "drive.encoder_in"} in system["connections"]
    assert notes and "按惯例" in notes[0]


def test_without_requirement_only_interface_checks_run():
    out = check(layout(), LIB.get)
    by = {c["check"]: c for c in out["checks"]}
    assert out["mode"] == "interface"
    assert by["C1"]["status"] == "pass" and by["C10"]["status"] == "pass"
    assert by["C4"]["status"] == "not_applicable" and "需求未给出" in by["C4"]["message"]
    # 带键轴配键槽孔：键宽缺，C2 待确认；可配置法兰：C3 待确认
    assert by["C2"]["status"] == "unknown" and by["C3"]["status"] == "unknown"
    assert out["overall"] == "unknown"
    assert out["ports"]["motor.shaft"] == "unknown" and out["ports"]["reducer.motor_flange"] == "unknown"


def test_plain_shaft_on_keyed_bore_fails_and_colors_the_ports():
    out = check(layout(motor=M2), LIB.get)
    assert out["overall"] == "fail"
    assert out["ports"]["motor.shaft"] == "fail" and out["ports"]["reducer.input_bore"] == "fail"
    assert out["instances"]["motor"] == "fail"


def test_with_requirement_all_checks_run_like_the_real_example():
    out = check(layout(), LIB.get, REQ)
    by = {c["check"]: c["status"] for c in out["checks"]}
    assert out["mode"] == "full"
    assert by["C4"] == by["C5"] == by["C6"] == by["C7"] == by["C9"] == "pass"
    example = json.loads((ROOT / "examples" / "joint-real" / "system.json").read_text(encoding="utf-8"))["report"]
    assert by == {c["check"]: c["status"] for c in example["checks"]}


def test_empty_scene():
    assert check({"instances": [], "connections": []}, LIB.get)["mode"] == "empty"
