"""M4a 演示（#70）：经 MCP 客户端走一遍“需求 → 候选方案 → 校验与说明 → BOM”。

在外部客户端（如 Claude Desktop）里，是由客户端的 LLM 把一句话需求转成结构化需求；
本脚本用于离线复现同一流程：读入结构化需求 JSON，经 MCP 协议调用本服务的工具并打印结果。

    python -m mcp_server.demo examples/joint2-requirement.json [--lang en] [--top 3]

组件库按 FAP_LIBRARY / DATABASE_URL 配置；未配置时用 golden 虚构组件库（tests/golden/fixtures）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from fastmcp import Client

from kb.library import JsonLibrary, default_library
from mcp_server.server import create_server

GOLDEN_FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "golden" / "fixtures"


def _library():
    if os.environ.get("FAP_LIBRARY") or os.environ.get("DATABASE_URL"):
        return default_library()
    return JsonLibrary(GOLDEN_FIXTURES)


async def run(requirement: dict, *, lang: str = "zh", top: int = 3) -> dict:
    async with Client(create_server(_library)) as client:
        composed = (await client.call_tool("compose_chain",
                                           {"requirement": requirement, "top_n": top, "lang": lang})).data
        if not composed["candidates"]:
            return {"composed": composed}
        best = composed["candidates"][0]["system"]
        verified = (await client.call_tool("verify_system", {"system": best, "lang": lang})).data
        bom = (await client.call_tool("export_system", {"system": best, "format": "bom_csv"})).data
        return {"composed": composed, "verified": verified, "bom": bom}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4a 演示：需求 → 候选方案 → 校验 → BOM")
    parser.add_argument("requirement", type=Path, help="结构化需求 JSON（schema/requirement.schema.json）")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args(argv)
    requirement = json.loads(args.requirement.read_text(encoding="utf-8"))
    out = asyncio.run(run(requirement, lang=args.lang, top=args.top))
    print(out["composed"]["explanation"])
    if "verified" in out:
        print("\n# 选定方案 1 的复核\n" if args.lang == "zh" else "\n# Re-check of option 1\n")
        print(out["verified"]["explanation"])
        print("\n# BOM\n")
        print(out["bom"]["content"])
    return 0 if out["composed"]["candidates"] else 1


if __name__ == "__main__":
    sys.exit(main())
