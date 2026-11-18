"""库的完整度报告（ADR-0099 41.3）：缺哪些字段、缺了哪些校验变成 unknown——由引擎在标准题上试出来，不手写清单。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from kb import completeness as C
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lib():
    return {c["id"]: c for c in JsonLibrary(ROOT / "data" / "library").all()}


def _without(comp, where, name, port=None):
    c = copy.deepcopy(comp)
    if where == "params":
        del c["params"][name]
    else:
        del next(p for p in c["ports"] if p["id"] == port)["spec"][name]
    return c


def test_check_names_match_live_check():
    from freecad_addon.core.live_check import CHECK_NAMES

    assert C.CHECK_NAMES == CHECK_NAMES


@pytest.mark.parametrize("where,name,port,check", [
    ("params", "rated_torque_nm", None, "C4"),
    ("params", "rotor_inertia_kgm2", None, "C8"),
    ("ports", "pcd_mm", "mount_flange", "C3"),
    ("ports", "diameter_mm", "shaft", "C2"),
    ("ports", "rated_current_a", "power_in", "C9"),
])
def test_removed_field_maps_to_its_check(lib, where, name, port, check):
    full = lib["servo_motor.yaskawa-electric-corporation.sgm7j-02a"]
    assert C.component_gaps(full) == []
    gaps = {g["field"]: g for g in C.component_gaps(_without(full, where, name, port))}
    key = f"params.{name}" if where == "params" else f"ports.{port}.{name}"
    assert check in gaps[key]["checks"]


def test_alternative_data_counts(lib):
    """有效率曲线就不缺效率值（ADR-0047）；通孔法兰不要求螺纹"""
    red = lib["reducer.harmonic-drive-llc.csf-20-100-2uh"]
    assert "efficiency_curve" in red["params"] and "efficiency_ratio" not in red["params"]
    fields = {g["field"] for g in C.component_gaps(red)}
    assert "params.efficiency_ratio" not in fields
    servo = lib["servo_motor.yaskawa-electric-corporation.sgm7j-02a"]
    assert "ports.mount_flange.thread" not in {g["field"] for g in C.component_gaps(servo)}


def test_missing_port_is_not_demanded(lib):
    servo = copy.deepcopy(lib["servo_motor.yaskawa-electric-corporation.sgm7j-02a"])
    servo["ports"] = [p for p in servo["ports"] if p["id"] != "encoder"]
    assert not any(g["field"].startswith("ports.encoder.") for g in C.component_gaps(servo))


def test_new_categories_use_key_fields():
    part = {"id": "custom_part.demo.ls-101", "category": "custom_part", "vendor": "示范", "model": "LS-101",
            "params": {}, "ports": [], "envelope": {}}
    gaps = {g["field"]: g for g in C.component_gaps(part)}
    assert set(gaps) == {"params.part_kind", "params.mass_kg", "envelope"}
    assert gaps["params.mass_kg"]["hint"].startswith("按材料密度") and gaps["envelope"]["checks"] == ["C11"]


def test_report_ranks_and_exports(lib, tmp_path):
    comps = list(lib.values())
    r = C.report(comps)
    assert r["count"] == len(comps)
    affected = [len(x["checks_affected"]) for x in r["components"]]
    assert affected == sorted(affected, reverse=True)
    first = r["fill_first"][0]
    assert first["checks"] and first["hint"] and first["components"]
    # 库里实际缺的：谐波减速器组合型的电机法兰由用户自定 → C3 待确认
    csf = next(x for x in r["components"] if x["id"] == "reducer.harmonic-drive-llc.csf-14-100-2uh")
    assert "C3" in csf["checks_affected"]
    p = C.to_excel(r, tmp_path / "c.xlsx")
    from openpyxl import load_workbook

    wb = load_workbook(p)
    assert wb.sheetnames == ["零件", "缺项", "先补"]
    assert wb["缺项"].max_row == 1 + sum(len(x["missing"]) for x in r["components"])


def test_impacts_follow_rules_not_a_list():
    """表是从标准题试出来的：每个有标准题的品类都至少有一个字段影响校验"""
    _, by_cat = C._golden()
    for cat in ("servo_motor", "reducer", "drive"):
        assert by_cat[cat], cat
