"""校验、导出时不丢需求里的条件（ADR-0099 41.0；2026-11-17 问渠 CAD 验收时发现）。

情形：需求是“220 V 单相供电”，库里的驱动器只支持三相，带供电选型找不到方案；AI 放宽供电重新选型、按布局重新校验时
给 verify_system 的需求也没带供电，“供电不符”就没进校验报告。现在由代码按会话里的需求补上。
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from mcp_server.tools import complete_requirement, requirement_note_text

ROOT = Path(__file__).resolve().parents[1]
REQ = json.loads((ROOT / "examples/joint2-requirement.json").read_text(encoding="utf-8"))


def test_missing_conditions_are_carried():
    system = {"id": "s", "requirement": {k: v for k, v in REQ.items() if k != "supply"}, "components": [], "connections": []}
    out, note = complete_requirement(system, REQ)
    assert out["requirement"]["supply"] == REQ["supply"] and note["carried"] == ["supply"]
    assert "按原需求带入：供电" in requirement_note_text(note) and "supply" in requirement_note_text(note, "en")
    assert system["requirement"].get("supply") is None                          # 不改调用方的对象


def test_conflicting_value_keeps_the_confirmed_one():
    req = dict(REQ, output_speed_rpm=60)
    out, note = complete_requirement({"id": "s", "requirement": req}, REQ)
    assert out["requirement"]["output_speed_rpm"] == 30 and note["kept"] == ["output_speed_rpm"]


def test_different_requirement_is_left_alone():
    other = {"id": "other", "statement": "另一个关节", "output_torque_cont_nm": 5, "output_speed_rpm": 100}
    out, note = complete_requirement({"id": "s", "requirement": other}, REQ)
    assert out["requirement"] == other and not note["carried"] and not note["kept"]
    out, _ = complete_requirement({"id": "s", "requirement": other}, None)
    assert out["requirement"] == other


def test_relaxed_reselection_does_not_drop_the_supply(monkeypatch):
    """经 MCP：带供电选型无方案 → 放宽供电重选 → 不带供电校验：报告里 C9 照样按单相判"""
    from fastmcp import Client

    monkeypatch.setenv("FAP_LIBRARY", str(ROOT / "data/library"))
    from mcp_server.server import mcp

    async def run():
        async with Client(mcp) as c:
            first = (await c.call_tool("compose_chain", {"requirement": REQ, "top_n": 1, "include_unknown": True})).data
            relaxed = {k: v for k, v in REQ.items() if k != "supply"}
            second = (await c.call_tool("compose_chain", {"requirement": relaxed, "top_n": 1, "include_unknown": True})).data
            system = copy.deepcopy(second["candidates"][0]["system"])
            system["requirement"].pop("supply", None)
            got = (await c.call_tool("verify_system", {"system": system})).data
            return first, got

    first, got = asyncio.run(run())
    assert first["count"] == 0                                              # 单相供电下库里没有可用方案
    assert got["requirement_carried"] == ["supply"] and got["explanation"].startswith("按原需求带入：供电")
    c9 = next(c for c in got["report"]["checks"] if c["check"] == "C9")
    assert c9["status"] == "fail", c9                                       # 三相驱动器配单相供电：不通过
    assert got["report"]["overall"] != "pass"


@pytest.fixture(autouse=True)
def _fresh_session():
    """每个测试用新的会话需求（模块级的服务端会话在测试间共用）"""
    from mcp_server import server

    st = getattr(server, "state", {})
    if st.get("layout") is not None:
        st["layout"].requirement = None
    yield

