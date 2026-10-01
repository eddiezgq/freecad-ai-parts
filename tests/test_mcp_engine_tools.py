"""M4a #67：compose_chain 与 verify_system 工具；通过 MCP 重跑全部 golden 用例，结果须与直接调用引擎一致。"""

from __future__ import annotations

import asyncio
import copy

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError

from engine.compose import compose_chain as engine_compose
from engine.golden import GOLDEN, cases, compare
from engine.validate import validate
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
CASES = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in cases()]


def _call_many(calls):
    async def run():
        out = []
        async with Client(create_server(lambda: LIB)) as client:
            for name, args in calls:
                out.append((await client.call_tool(name, args)).data)
        return out
    return asyncio.run(run())


def test_golden_via_mcp_equals_engine():
    """实施细则第九节 M4a 要求：通过 MCP 工具重跑全部 golden 用例，结果与直接调用引擎一致。"""
    results = _call_many([("verify_system", {"system": c["system"]}) for c in CASES])
    for case, res in zip(CASES, results, strict=True):
        direct = validate(case["system"], LIB.get)
        assert res["report"] == direct, case["id"]
        assert compare(case["expected"], res["report"])[0] == [], case["id"]
        assert res["explanation"].split("\n")[0]


def test_compose_via_mcp_equals_engine():
    req = CASES[-1]["system"]["requirement"]
    [res] = _call_many([("compose_chain", {"requirement": req, "top_n": 3, "lang": "en"})])
    direct = engine_compose(req, LIB.all(), top_n=3)
    assert [c["system"] for c in res["candidates"]] == [c.system for c in direct]
    assert [c["report"] for c in res["candidates"]] == [c.report for c in direct]
    assert res["explanation"].startswith("## Option 1")


@pytest.mark.parametrize(("name", "args", "msg"), [
    ("verify_system", {"system": {"id": "x"}}, "schema"),
    ("compose_chain", {"requirement": {"output_speed_rpm": 10}}, "schema"),
    ("compose_chain", {"requirement": {"output_torque_cont_nm": 1, "output_speed_rpm": 1}, "lang": "fr"}, "lang"),
])
def test_errors_via_mcp(name, args, msg):
    with pytest.raises(ToolError, match=msg):
        _call_many([(name, args)])


def test_unknown_component():
    s = copy.deepcopy(CASES[0]["system"])
    s["components"][0]["component"] = "test.servo_motor.test-vendor.none"
    with pytest.raises(tools.ToolInputError, match="找不到组件"):
        tools.verify_system(LIB, s)


def test_compose_empty_result():
    r = tools.compose_chain(LIB, {"output_torque_cont_nm": 10000, "output_speed_rpm": 1})
    assert r["count"] == 0 and r["candidates"] == [] and "没有找到" in r["explanation"]
