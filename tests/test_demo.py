"""M4a #70：离线演示与提示模板。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastmcp import Client

from engine.golden import GOLDEN
from kb.library import JsonLibrary
from kb.validation import errors
from mcp_server import demo
from mcp_server.server import create_server

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "joint2-requirement.json"


def test_example_requirement_valid():
    assert errors("requirement.schema.json", json.loads(EXAMPLE.read_text(encoding="utf-8"))) == []


def test_demo_runs(capsys, monkeypatch):
    monkeypatch.delenv("FAP_LIBRARY", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert demo.main([str(EXAMPLE), "--top", "2"]) == 0
    out = capsys.readouterr().out
    assert "## 方案 1" in out and "可用" in out and "component_id" in out
    assert demo.main([str(EXAMPLE), "--lang", "en", "--top", "1"]) == 0
    assert "## Option 1" in capsys.readouterr().out


def test_demo_no_candidates(tmp_path, capsys):
    req = tmp_path / "r.json"
    req.write_text(json.dumps({"output_torque_cont_nm": 10000, "output_speed_rpm": 1}), encoding="utf-8")
    assert demo.main([str(req)]) == 1
    assert "没有找到" in capsys.readouterr().out


def test_prompt_and_tool_list():
    async def run():
        async with Client(create_server(lambda: JsonLibrary(GOLDEN / "fixtures"))) as client:
            tools = sorted(t.name for t in await client.list_tools())
            prompt = await client.get_prompt("joint_selection", {"statement": "第 2 关节 25 N·m 30 rpm"})
            return tools, prompt
    tools, prompt = asyncio.run(run())
    assert tools == sorted(["server_info", "search_components", "get_component", "find_compatible",
                            "compose_chain", "verify_system", "export_system"])
    text = prompt.messages[0].content.text
    assert "第 2 关节" in text and "compose_chain" in text and "不要猜" in text
