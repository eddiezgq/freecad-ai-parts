"""换件建议（ADR-0052）：同品类候选整体重算、排序、结论变化；换上的调用序列；MCP 工具。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from freecad_addon.core import swap
from freecad_addon.core.live_check import check
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server
from mcp_server.tools import ToolInputError

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
PLAIN = "servo_motor.yaskawa-electric-corporation.sgm7j-02a"  # 光轴
KEYED = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"  # 带键
R25 = "reducer.harmonic-drive-llc.csf-25-100-2uh"
D = "drive.yaskawa-america-inc.sgd7s-1r6a"
REQ = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))


def layout(motor=PLAIN):
    return {"instances": [{"instance": "motor", "component": motor, "position_mm": [0, 0, 0],
                           "rotation": {"axis": [0, 0, 1], "angle_deg": 0}},
                          {"instance": "reducer", "component": R25, "position_mm": [0, 0, 120],
                           "rotation": {"axis": [1, 0, 0], "angle_deg": 180}},
                          {"instance": "drive", "component": D}],
            "connections": [{"a": "motor.mount_flange", "b": "reducer.motor_flange", "roll_deg": 15.0,
                             "offset_mm": 0.0},
                            {"a": "motor.shaft", "b": "reducer.input_bore", "roll_deg": 0.0, "offset_mm": 0.0}]}


def test_plain_shaft_fails_and_keyed_variant_is_the_top_suggestion():
    assert check(layout(), LIB.get)["overall"] == "fail"  # 光轴配键槽孔
    out = swap.suggest(layout(), "motor", LIB.get, LIB.all("servo_motor"))
    assert out["current"] == {"component_id": PLAIN, "overall": "fail"}
    ids = [s["component_id"] for s in out["suggestions"]]
    assert ids[0] == KEYED and PLAIN not in ids
    top = out["suggestions"][0]
    assert top["overall"] != "fail" and any(c.startswith("C2 圆柱配合：不通过 → 通过") for c in top["changes"])
    assert all(s["overall"] != "fail" for s in out["suggestions"])


def test_requirement_is_part_of_the_recheck():
    out = swap.suggest(layout(), "motor", LIB.get, LIB.all("servo_motor"), REQ, top_n=20)
    # 按需求重算：每个候选的整体结论都与直接校验换件后的布局一致
    for s in out["suggestions"]:
        lay = layout(s["component_id"])
        assert check(lay, LIB.get, REQ)["overall"] == s["overall"]


def test_ranking_prefers_better_status_then_fewer_unknowns_then_lighter():
    out = swap.suggest(layout(), "motor", LIB.get, LIB.all("servo_motor"), REQ, top_n=20)
    rank = {"pass": 0, "warn": 1, "unknown": 2}
    keys = [(rank[s["overall"]], s["unknown_count"], s["mass_kg"] if s["mass_kg"] is not None else float("inf"))
            for s in out["suggestions"]]
    assert keys == sorted(keys)


def test_other_categories_and_unknown_instance():
    out = swap.suggest(layout(), "motor", LIB.get, LIB.all())  # 混入其他品类也只取同品类
    assert all(LIB.get(s["component_id"])["category"] == "servo_motor" for s in out["suggestions"])
    with pytest.raises(ValueError, match="没有实例"):
        swap.suggest(layout(), "nope", LIB.get, [])


def test_swap_calls_rebuild_connections_at_the_same_pose():
    calls = swap.swap_calls(layout(), "reducer", "reducer.harmonic-drive-llc.csf-32-100-2uh")
    assert calls[0] == ("place_component", {"instance": "reducer", "remove": True})
    assert calls[1] == ("place_component", {"instance": "reducer",
                                            "component_id": "reducer.harmonic-drive-llc.csf-32-100-2uh",
                                            "position_mm": [0, 0, 120], "rotation_axis": [1, 0, 0],
                                            "rotation_deg": 180})
    assert calls[2:] == [("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange",
                                            "roll_deg": 15.0, "offset_mm": 0.0}),
                         ("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore",
                                            "roll_deg": 0.0, "offset_mm": 0.0})]
    assert swap.swap_calls(layout(), "drive", D)[2:] == []  # 没有机械连接
    with pytest.raises(ValueError):
        swap.swap_calls(layout(), "nope", D)


def test_tool_validates_inputs():
    with pytest.raises(ToolInputError, match="没有实例"):
        tools.suggest_replacements(LIB, layout(), "nope")
    with pytest.raises(ToolInputError, match="top_n"):
        tools.suggest_replacements(LIB, layout(), "motor", top_n=0)
    with pytest.raises(ToolInputError):
        tools.suggest_replacements(LIB, layout(), "motor", requirement={"output_speed_rpm": 30})


def test_mcp_tool_reads_the_session_layout_and_swap_fixes_c2():
    async def run():
        async with Client(create_server(lambda: LIB)) as client:
            for inst, cid in (("motor", PLAIN), ("reducer", R25)):
                await client.call_tool("place_component", {"instance": inst, "component_id": cid})
            await client.call_tool("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"})
            await client.call_tool("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"})
            out = (await client.call_tool("suggest_replacements", {"instance": "motor"})).data
            top = out["suggestions"][0]["component_id"]
            state = None
            for name, args in swap.swap_calls(json.loads(json.dumps(
                    (await client.call_tool("place_component", {"instance": "motor"})).data["layout"])), "motor", top):
                state = (await client.call_tool(name, args)).data["layout"]
            return out, top, state

    out, top, state = asyncio.run(run())
    assert out["current"]["overall"] == "fail" and top == KEYED
    assert {i["component"] for i in state["instances"] if i["instance"] == "motor"} == {KEYED}
    assert len(state["connections"]) == 2
    r = check(state, LIB.get)
    assert {c["check"]: c["status"] for c in r["checks"]}["C2"] == "pass"
