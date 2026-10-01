"""M4a #68：export_system。"""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json

import pytest
import yaml
from fastmcp import Client

from engine.golden import GOLDEN
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
SYS = yaml.safe_load((GOLDEN / "valid" / "m200-adapters-r25-d400.yaml").read_text(encoding="utf-8"))["system"]


def test_bom_csv_traceable():
    out = tools.export_system(LIB, SYS)
    assert out["filename"] == "m200-adapters-r25-d400-bom.csv" and out["media_type"] == "text/csv"
    rows = list(csv.DictReader(io.StringIO(out["content"])))
    assert [r["component_id"] for r in rows] == [c["component"] for c in SYS["components"]]
    assert all(r["source_docs"] == "src-test-fixture" for r in rows)
    assert rows[0]["vendor"] == "Test Vendor" and rows[0]["quantity"] == "1"
    assert out["overall"] == "pass"


def test_bom_json_totals_and_grouping():
    s = copy.deepcopy(SYS)
    s["components"].append({"instance": "sleeve_2", "component": "test.adapter.test-vendor.sleeve-11-19"})
    bom = tools.export_system(LIB, s, format="bom_json")["content"]
    sleeve = next(r for r in bom["rows"] if r["component_id"].endswith("sleeve-11-19"))
    assert sleeve["quantity"] == 2 and sleeve["instances"] == ["sleeve", "sleeve_2"]
    assert sleeve["total_mass_kg"] == pytest.approx(0.06)
    assert bom["total_mass_kg"] == pytest.approx(0.8 + 1.5 + 0.8 + 0.06 + 0.2)


def test_bom_missing_mass():
    s = copy.deepcopy(SYS)
    s["components"][0]["component"] = "test.servo_motor.test-vendor.m200"
    lib = JsonLibrary(GOLDEN / "fixtures")
    lib._comps["test.servo_motor.test-vendor.m200"] = copy.deepcopy(lib.get("test.servo_motor.test-vendor.m200"))
    lib._comps["test.servo_motor.test-vendor.m200"]["params"].pop("mass_kg")
    bom = tools.export_system(lib, s, format="bom_json")["content"]
    assert bom["total_mass_kg"] is None and bom["rows"][0]["unit_mass_kg"] is None


def test_system_json_reproducible():
    out = tools.export_system(LIB, SYS, format="system_json")["content"]
    assert out["report"]["overall"] == "pass" and set(out["components"]) == {c["component"] for c in SYS["components"]}
    # 用导出的组件数据即可复现校验
    from engine.validate import validate
    assert validate(out["system"], out["components"].get) == out["report"]
    json.dumps(out, allow_nan=False)


def test_errors():
    with pytest.raises(tools.ToolInputError, match="URDF"):
        tools.export_system(LIB, SYS, format="urdf")
    with pytest.raises(tools.ToolInputError, match="schema"):
        tools.export_system(LIB, {"id": "x"})


def test_mcp_export():
    async def run():
        async with Client(create_server(lambda: LIB)) as client:
            return (await client.call_tool("export_system", {"system": SYS, "format": "bom_json"})).data
    assert asyncio.run(run())["content"]["rows"][0]["component_id"] == "test.servo_motor.test-vendor.m200"
