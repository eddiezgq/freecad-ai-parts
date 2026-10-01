"""M4a #66：find_compatible 与单连接校验。"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from engine.golden import GOLDEN
from engine.link import check_link
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
M200, M400 = "test.servo_motor.test-vendor.m200", "test.servo_motor.test-vendor.m400"


def _ids(r):
    return [(x["component_id"].split(".", 2)[-1], x["port_id"], x["status"],
             (x.get("via") or {}).get("adapter", "").split(".", 2)[-1]) for x in r["results"]]


def test_shaft_direct_and_via_sleeve():
    r = tools.find_compatible(LIB, M200, "shaft", include_unknown=False)
    got = _ids(r)
    assert ("test-vendor.r14-100", "input_bore", "pass", "") in got
    assert ("test-vendor.r25-100", "input_bore", "pass", "test-vendor.sleeve-11-19") in got
    assert not any(g[0] == "test-vendor.r20-100" for g in got)  # 11 ≠ 14，也没有合适的轴套
    via = next(x for x in r["results"] if x.get("via"))
    assert via["via"] == {"adapter": "test.adapter.test-vendor.sleeve-11-19", "in": "inner", "out": "outer"}
    assert len(via["findings"]) > 2  # 两段连接的判定都在


def test_no_fail_and_order():
    r = tools.find_compatible(LIB, M200, "mount_flange", include_unknown=True)
    ranks = [{"pass": 0, "warn": 1, "unknown": 2}[x["status"]] for x in r["results"]]
    assert ranks == sorted(ranks)
    assert all(x["status"] != "fail" for x in r["results"])
    assert not any(x["component_id"].endswith("pcd63") for x in r["results"])


def test_electrical_and_signal_links():
    r = tools.find_compatible(LIB, "test.drive.test-vendor.d200", "motor_out", category="servo_motor")
    ids = {x["component_id"] for x in r["results"]}
    assert M200 in ids and M400 not in ids  # d200 额定 1.6 A < m400 2.8 A
    r = tools.find_compatible(LIB, M400, "encoder")
    assert all(x["status"] == "pass" for x in r["results"])
    r = tools.find_compatible(LIB, "test.servo_motor.test-vendor.m400-ssi", "encoder")
    assert r["total"] == 0
    r = tools.find_compatible(LIB, "test.drive.test-vendor.d400-lowpeak", "motor_out", category="servo_motor")
    assert {x["status"] for x in r["results"] if x["component_id"] == M400} == {"warn"}


def test_check_link_c1_failure():
    m, d = LIB.get(M400), LIB.get("test.drive.test-vendor.d400")
    r = check_link(m, "encoder", d, "motor_out")
    assert r["status"] == "fail" and r["findings"][0]["message"].startswith("C1")
    r = check_link(m, "shaft", LIB.get("test.reducer.test-vendor.r20-100"), "input_bore")
    assert r["status"] == "pass" and any(M400 in p for p in r["findings"][0]["ports"])


def test_errors_and_limit():
    with pytest.raises(tools.ToolInputError, match="没有端口"):
        tools.find_compatible(LIB, M400, "nope")
    with pytest.raises(tools.ToolInputError, match="组件不存在"):
        tools.find_compatible(LIB, "nope", "shaft")
    r = tools.find_compatible(LIB, M200, "mount_flange", limit=2)
    assert len(r["results"]) == 2 and r["truncated"]


def test_via_adapters_off():
    r = tools.find_compatible(LIB, M200, "shaft", via_adapters=False)
    assert not any("via" in x for x in r["results"])


def test_mcp_tool():
    async def run():
        async with Client(create_server(lambda: LIB)) as client:
            return (await client.call_tool("find_compatible", {"component_id": M200, "port_id": "shaft"})).data
    assert asyncio.run(run())["total"] == tools.find_compatible(LIB, M200, "shaft")["total"]
