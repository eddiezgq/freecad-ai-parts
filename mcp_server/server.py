"""FreeCAD AI Parts 的 MCP 服务端入口。

M0 阶段只提供一个示例工具 `server_info`，用于验证外部 MCP 客户端
（如 Claude Desktop）能连上并调用工具。V1 的 10 个正式工具在 M4a 实现，
清单见 docs/README.md 中链接的架构文档。
"""

from __future__ import annotations

from fastmcp import FastMCP

from mcp_server import __version__

mcp = FastMCP("freecad-ai-parts")

# V1 计划的 10 个工具（M4a/M4b 实现），此处仅作说明，不注册。
PLANNED_TOOLS: list[str] = [
    "search_components",
    "get_component",
    "find_compatible",
    "compose_chain",
    "verify_system",
    "place_component",
    "connect_ports",
    "check_interference",
    "snapshot",
    "export_system",
]


@mcp.tool
def server_info() -> dict:
    """返回服务端名称、版本、当前阶段和计划中的工具清单。"""
    return {
        "name": "freecad-ai-parts",
        "version": __version__,
        "stage": "M0",
        "planned_tools": PLANNED_TOOLS,
    }


def main() -> None:
    """以 stdio 方式运行，供 MCP 客户端启动。"""
    mcp.run()


if __name__ == "__main__":
    main()
