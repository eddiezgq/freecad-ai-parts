"""M0 验收：MCP 客户端能调用示例工具。"""

import asyncio

from fastmcp import Client

from mcp_server.server import PLANNED_TOOLS, mcp


def test_server_info_tool_is_callable():
    async def run():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            assert "server_info" in [t.name for t in tools]
            result = await client.call_tool("server_info", {})
            return result.data

    data = asyncio.run(run())
    assert data["name"] == "freecad-ai-parts"
    assert data["stage"] == "M0"
    assert data["planned_tools"] == PLANNED_TOOLS
    assert len(PLANNED_TOOLS) == 10
