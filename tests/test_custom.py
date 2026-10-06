"""可配置接口的定制要求（ADR-0053）：照录对方端口规格与出处，缺失列为待确认，不改校验结论。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from engine import export
from engine.custom import custom_requirements, requirement_for
from engine.validate import validate
from freecad_addon.core.live_check import check, system_from_layout
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R = "reducer.harmonic-drive-llc.csf-25-100-2uh"
D = "drive.yaskawa-america-inc.sgd7s-1r6a"
REQ = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))
LAYOUT = {"instances": [{"instance": "motor", "component": M}, {"instance": "reducer", "component": R},
                        {"instance": "drive", "component": D}],
          "connections": [{"a": "motor.mount_flange", "b": "reducer.motor_flange"},
                          {"a": "motor.shaft", "b": "reducer.input_bore"}]}


def _port(cid, pid):
    return next(p for p in LIB.get(cid)["ports"] if p["id"] == pid)


def test_real_joint_flange_requirement_copies_motor_values_with_pages():
    system, _ = system_from_layout(LAYOUT, LIB.get)
    reqs = custom_requirements(system, LIB.get)
    assert len(reqs) == 1
    r = reqs[0]
    assert (r["instance"], r["component_id"], r["port"]) == ("reducer", R, "motor_flange")
    assert r["mate"]["component_id"] == M and r["mate"]["port"] == "mount_flange"
    items = {i["field"]: (i["value"], i["source"]) for i in r["items"]}
    spec = _port(M, "mount_flange")["spec"]
    for field, want in (("pcd_mm", "70"), ("hole_count", "4"), ("hole_kind", "通孔"), ("hole_diameter_mm", "5.5"),
                        ("pilot_diameter_mm", "50（+0 / -0.025）"), ("pilot_kind", "凸")):
        assert items[field][0] == want
        assert items[field][1] == f"{spec[field]['source']['doc']} 第 {spec[field]['source']['page']} 页"
    assert "thread" not in items  # 通孔时不列螺纹
    assert r["missing"] == []  # 止口按第 65 页 LB 栏录入后，法兰要求齐全
    assert r["text"].startswith("Harmonic Drive LLC CSF-25-100-2UH 的 motor_flange")


def test_missing_mate_values_are_listed_not_filled():
    target, mate = copy.deepcopy(LIB.get(R)), copy.deepcopy(LIB.get(M))
    tp = next(p for p in target["ports"] if p["id"] == "motor_flange")
    mp = next(p for p in mate["ports"] if p["id"] == "mount_flange")
    del mp["spec"]["pilot_diameter_mm"]
    r = requirement_for(target, tp, mate, mp)
    assert r["missing"] == ["止口直径"] and "订货前须与厂商确认" in r["text"]
    assert "pilot_diameter_mm" not in {i["field"] for i in r["items"]}


def test_direction_of_the_connection_does_not_matter():
    flipped = {**LAYOUT, "connections": [{"a": "reducer.motor_flange", "b": "motor.mount_flange"}]}
    a, _ = system_from_layout(LAYOUT, LIB.get)
    b, _ = system_from_layout(flipped, LIB.get)
    assert custom_requirements(a, LIB.get) == custom_requirements(b, LIB.get)


def test_check_results_are_unchanged_and_noted():
    system, _ = system_from_layout(LAYOUT, LIB.get)
    report = validate({**system, "requirement": REQ}, LIB.get)
    assert {c["check"]: c["status"] for c in report["checks"]}["C3"] == "unknown"
    r = check(LAYOUT, LIB.get, REQ)
    assert {c["check"]: c["status"] for c in r["checks"]}["C3"] == "unknown"
    assert any("定制要求见 BOM" in n for n in r["notes"])


def test_no_requirement_without_configurable_ports():
    system = {"id": "x", "requirement": REQ,
              "components": [{"instance": "motor", "component": M}, {"instance": "motor2", "component": M}],
              "connections": [{"a": "motor.mount_flange", "b": "motor2.mount_flange"}]}
    assert custom_requirements(system, LIB.get) == []


def test_threaded_mate_lists_thread_and_missing_items():
    target, mate = copy.deepcopy(LIB.get(R)), copy.deepcopy(LIB.get(M))
    tp = next(p for p in target["ports"] if p["id"] == "motor_flange")
    mp = next(p for p in mate["ports"] if p["id"] == "mount_flange")
    mp["spec"] = {"hole_kind": {"value": "threaded"}, "thread": {"value": "M5"},
                  "pilot_diameter_mm": {"nominal": 50.0, "tol_upper": 0.0, "tol_lower": -0.025,
                                        "source": {"doc": "src-x", "page": 3}}}
    r = requirement_for(target, tp, mate, mp)
    items = {i["field"]: i for i in r["items"]}
    assert items["thread"]["value"] == "M5" and "hole_diameter_mm" not in items
    assert items["pilot_diameter_mm"]["value"] == "50（+0 / -0.025）"
    assert items["pilot_diameter_mm"]["source"] == "src-x 第 3 页"
    assert items["hole_kind"]["source"] == "（无出处）"
    assert r["missing"] == ["分度圆直径", "孔数"]


def test_bom_json_carries_requirements_and_csv_columns_are_unchanged():
    system, _ = system_from_layout(LAYOUT, LIB.get)
    b = export.bom_json(system, LIB.get)
    assert b["custom_requirements"] == custom_requirements(system, LIB.get)
    assert export.bom_csv(system, LIB.get).splitlines()[0] == ",".join(export.BOM_COLUMNS)
