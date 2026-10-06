"""BOM 面板的整理（ADR-0051 第 2 条）：由场景组成 BOM，与 export_system 一致；质量缺失时总质量未知。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freecad_addon.core import bom_view
from freecad_addon.core.live_check import system_from_layout
from kb.library import JsonLibrary
from mcp_server import tools

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R = "reducer.harmonic-drive-llc.csf-25-100-2uh"
D = "drive.yaskawa-america-inc.sgd7s-1r6a"


def layout(*items):
    return {"instances": [{"instance": n, "component": c} for n, c in items],
            "connections": [{"a": "motor.mount_flange", "b": "reducer.motor_flange"}]}


JOINT = layout(("motor", M), ("reducer", R), ("drive", D))


def test_empty_scene_has_no_rows():
    b = bom_view.bom({"instances": []}, LIB.get)
    assert b == {"rows": [], "total_mass_kg": 0.0, "count": 0, "custom_requirements": []}
    assert bom_view.total_text(b) == "场景中还没有零件"
    with pytest.raises(ValueError, match="还没有零件"):
        bom_view.export_text({"instances": []}, LIB.get, "csv")


def test_joint_bom_rows_and_total_mass():
    b = bom_view.bom(JOINT, LIB.get)
    assert [r["component_id"] for r in b["rows"]] == [M, R, D]
    masses = [r["total_mass_kg"] for r in b["rows"]]
    assert None not in masses
    assert b["total_mass_kg"] == pytest.approx(sum(masses))
    cells = bom_view.cells(b["rows"][0])
    assert len(cells) == len(bom_view.HEADERS)
    assert cells[1] == "电机" and "SGM7J-02A" in cells[3] and cells[4] == "1" and cells[6] == "0.8 kg"
    assert "src-yaskawa-sgm7-rotary-manual" in cells[8]
    assert bom_view.total_text(b).startswith("共 3 种、3 件；总质量 ")


def test_same_model_is_merged_and_missing_mass_makes_total_unknown():
    lib_get = LIB.get

    def no_mass(cid):
        comp = lib_get(cid)
        if comp is not None and cid == D:
            comp = {**comp, "params": {k: v for k, v in comp["params"].items() if k != "mass_kg"}}
        return comp

    lay = {"instances": [{"instance": "motor", "component": M}, {"instance": "motor2", "component": M},
                         {"instance": "drive", "component": D}], "connections": []}
    b = bom_view.bom(lay, no_mass)
    assert b["rows"][0]["quantity"] == 2 and b["rows"][0]["instances"] == ["motor", "motor2"]
    assert b["total_mass_kg"] is None and "未知" in bom_view.total_text(b)
    assert bom_view.cells(b["rows"][1])[6] == "未知"


@pytest.mark.parametrize(("fmt", "tool_fmt"), [("csv", "bom_csv"), ("json", "bom_json")])
def test_export_matches_export_system_tool(fmt, tool_fmt):
    name, text = bom_view.export_text(JOINT, LIB.get, fmt)
    system, _ = system_from_layout(JOINT, LIB.get)
    want = tools.export_system(LIB, system, format=tool_fmt)
    assert name == want["filename"]
    if fmt == "csv":
        assert text == want["content"]
    else:
        assert json.loads(text) == want["content"]


def test_unknown_format_is_refused():
    with pytest.raises(ValueError, match="格式"):
        bom_view.export_text(JOINT, LIB.get, "xlsx")
