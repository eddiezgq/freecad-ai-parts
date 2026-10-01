"""FreeCAD AI Parts 的 MCP 服务端入口。

M4a 实现不依赖 FreeCAD 的工具（ADR-0003“先外后内”）；FreeCAD 组的工具在 M4b 实现。
组件库按 kb.library.default_library() 配置：FAP_LIBRARY（JSON 目录）或 DATABASE_URL（知识库）。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from kb.library import Library, default_library
from mcp_server import __version__, rest, tools

# V1 计划的 10 个工具
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


def _guard(fn: Callable) -> Callable:
    """把入参错误转成 MCP 的工具错误（客户端能看到原因）。"""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except tools.ToolInputError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def create_server(library_factory: Callable[[], Library] = default_library) -> FastMCP:
    """创建 MCP 服务端；组件库在第一次用到时才连接。"""
    mcp = FastMCP("freecad-ai-parts", instructions=(
        "机电零件选型与校验工具。组件是“端口 + 参数 + 包络”的黑箱；凡影响能不能用的判断都由确定性校验完成。"
        "参数一律用标准单位（mm、N·m、rpm、kg、kg·m²、W、V、A 有效值）。"))
    state: dict[str, Any] = {}

    def lib() -> Library:
        if "lib" not in state:
            state["lib"] = library_factory()
        return state["lib"]

    def info() -> dict:
        return {"name": "freecad-ai-parts", "version": __version__, "stage": "M4a", "planned_tools": PLANNED_TOOLS}

    @mcp.tool
    def server_info() -> dict:
        """返回服务端名称、版本、当前阶段和计划中的工具清单。"""
        return info()

    rest.register(mcp, lib, info)

    @mcp.prompt
    def joint_selection(statement: Annotated[str, Field(description="用户的一句话需求")]) -> str:
        """关节模组选型的工作流程提示：把一句话需求转成结构化需求，调用工具，交付校验过的方案。"""
        return (
            f"用户需求：{statement}\n\n"
            "请按以下步骤完成关节模组选型：\n"
            "1. 把需求转成 schema/requirement.schema.json 的结构化需求，一律用标准单位"
            "（扭矩 N·m、转速 rpm、惯量 kg·m²、长度 mm、电压 V）。输出连续扭矩与输出转速是必填项；"
            "缺少这两项或含义不清时先问用户，不要猜。用户没说安全系数时用 1.2。\n"
            "2. 调用 compose_chain 得到候选方案；没有方案时，说明是哪类约束无法满足，并建议放宽哪一项。\n"
            "3. 向用户展示前几个方案：组成、整体结论、告警与待确认项，以及工具返回的说明。"
            "能不能用以工具的校验结果为准，不要自行改判。\n"
            "4. 用户选定后，可用 verify_system 复核，用 export_system 导出 BOM。"
        )

    @mcp.tool
    @_guard
    def search_components(
        category: Annotated[str | None, Field(description="品类：servo_motor / reducer / drive / bearing / adapter")] = None,
        vendor: Annotated[str | None, Field(description="厂商名称（不分大小写）")] = None,
        text: Annotated[str | None, Field(description="关键词，须全部出现在 id、厂商、型号、系列中")] = None,
        params: Annotated[dict | None, Field(description="参数范围筛选 {参数名: {min, max}}，标准单位；须同时指定品类")] = None,
        limit: Annotated[int, Field(description="最多返回几个", ge=1, le=tools.SEARCH_LIMIT_MAX)] = 50,
    ) -> dict:
        """按品类、厂商、关键词与参数范围筛选组件，返回摘要（含关键参数）。"""
        return tools.search_components(lib(), category=category, vendor=vendor, text=text, params=params,
                                       limit=limit)

    @mcp.tool
    @_guard
    def get_component(component_id: Annotated[str, Field(description="组件 id")]) -> dict:
        """返回组件的完整参数、端口与包络（参数值含来源、置信度与复核状态）。"""
        return tools.get_component(lib(), component_id)

    @mcp.tool
    @_guard
    def find_compatible(
        component_id: Annotated[str, Field(description="组件 id")],
        port_id: Annotated[str, Field(description="该组件的端口 id，如 shaft、mount_flange、encoder")],
        category: Annotated[str | None, Field(description="只在该品类中找")] = None,
        include_unknown: Annotated[bool, Field(description="是否包含数据缺失、待确认的连接")] = True,
        via_adapters: Annotated[bool, Field(description="直连不通时是否找转接件")] = True,
        limit: Annotated[int, Field(ge=1, le=tools.SEARCH_LIMIT_MAX)] = 50,
    ) -> dict:
        """找能连到某个端口的组件及端口，附单连接校验结果；需经转接件的注明 via。"""
        return tools.find_compatible(lib(), component_id, port_id, category=category,
                                     include_unknown=include_unknown, via_adapters=via_adapters, limit=limit)

    @mcp.tool
    @_guard
    def compose_chain(
        requirement: Annotated[dict, Field(description="需求（schema/requirement.schema.json）：输出连续扭矩 N·m、"
                                                       "峰值扭矩、输出转速 rpm、安全系数、负载惯量 kg·m²、外径上限 mm、"
                                                       "供电、总线等，标准单位")],
        top_n: Annotated[int, Field(ge=1, le=20)] = 5,
        include_unknown: Annotated[bool, Field(description="是否包含数据缺失、待确认的方案")] = False,
        lang: Annotated[str, Field(description="说明语言：zh 或 en")] = "zh",
    ) -> dict:
        """按需求组合电机、减速器、驱动器（必要时加转接件），全部校验后排序返回候选方案与说明。"""
        return tools.compose_chain(lib(), requirement, top_n=top_n, include_unknown=include_unknown, lang=lang)

    @mcp.tool
    @_guard
    def verify_system(
        system: Annotated[dict, Field(description="系统（schema/system.schema.json）：需求、组件实例、端口连接")],
        lang: Annotated[str, Field(description="说明语言：zh 或 en")] = "zh",
    ) -> dict:
        """对一个系统做全部 11 项校验，返回逐项结果、整体结论与说明。"""
        return tools.verify_system(lib(), system, lang=lang)

    @mcp.tool
    @_guard
    def export_system(
        system: Annotated[dict, Field(description="系统（schema/system.schema.json）")],
        format: Annotated[str, Field(description="bom_csv / bom_json / system_json")] = "bom_csv",
    ) -> dict:
        """导出方案的 BOM（含原厂模型链接与数据来源）或系统 JSON（含校验报告与组件数据）。"""
        return tools.export_system(lib(), system, format=format)

    return mcp


mcp = create_server()


def main(argv: list[str] | None = None) -> None:
    """默认以 stdio 运行，供 MCP 客户端启动；--http 时同时提供 MCP（/mcp）与 REST（/api）。"""
    import argparse

    parser = argparse.ArgumentParser(prog="freecad-ai-parts-mcp", description="FreeCAD AI Parts MCP / REST 服务")
    parser.add_argument("--http", action="store_true", help="以 HTTP 方式运行（MCP 在 /mcp，REST 在 /api）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.http:
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
