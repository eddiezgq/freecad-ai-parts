"""M4b 演示（#88）：经 MCP 工具按 joint_layout 提示的流程，确定地完成“候选方案 → 布局 → 消除干涉 → 截图 → 复核与导出”。

在 FreeCAD 内置面板或外部客户端里，这些步骤由 LLM 调用工具完成；本脚本按同样的规则离线复现，
用于验证工具足以让 agent 独立完成布局并消除干涉（M4b 验收）。

    FAP_FREECAD=headless python -m mcp_server.layout_demo examples/joint2-requirement.json [--out 目录]

未设置 FAP_FREECAD 时只做布局与按布局的校验，跳过干涉检查与截图并说明。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from collections.abc import Callable
from pathlib import Path

from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server.demo import _library
from mcp_server.layout import Backend, default_backend
from mcp_server.server import create_server

FACE_TYPES = ("mechanical.flange", "mechanical.mount_face")
MECH_TYPES = (*FACE_TYPES, "mechanical.cyl_male", "mechanical.cyl_female")


def _port_type(components: dict, system: dict, ref: str) -> str | None:
    inst, _, pid = ref.partition(".")
    cid = next(c["component"] for c in system["components"] if c["instance"] == inst)
    return next((p["type"] for p in components[cid]["ports"] if p["id"] == pid), None)


def _resolve_moves(layout: dict, interferences: list, gap_mm: float) -> tuple[list[dict], list[dict]]:
    """不在同一刚性组的干涉：移动较小的一组（同样大小时移名称靠后的），沿 +x 移到其他实例包围盒之外。
    同组内的干涉无法靠移动消除，原样返回。"""
    by_name = {i["instance"]: i for i in layout["instances"]}
    moves, stuck, moved_groups = [], [], set()
    for hit in interferences:
        if hit["same_group"]:
            stuck.append(hit)
            continue
        ga, gb = by_name[hit["a"]]["group"], by_name[hit["b"]]["group"]
        mover = hit["b"] if (len(gb), hit["b"]) <= (len(ga), hit["a"]) else hit["a"]
        group = tuple(by_name[mover]["group"])
        if group in moved_groups:
            continue
        moved_groups.add(group)
        others = [i for n, i in by_name.items() if n not in group and i["bbox_mm"]]
        g_min = min(by_name[n]["bbox_mm"]["min_mm"][0] for n in group)
        target = max(o["bbox_mm"]["max_mm"][0] for o in others) + gap_mm
        dx = target - g_min
        cur = by_name[mover]
        pos = [cur["position_mm"][0] + dx, cur["position_mm"][1], cur["position_mm"][2]]
        moves.append({"instance": mover, "position_mm": pos, "rotation_axis": cur["rotation"]["axis"],
                      "rotation_deg": cur["rotation"]["angle_deg"]})
    return moves, stuck


async def run(requirement: dict, *, lang: str = "zh", gap_mm: float = 20.0, max_rounds: int = 5,
              backend_factory: Callable[[], Backend | None] = default_backend) -> dict:
    out: dict = {"steps": [], "rounds": [], "notes": []}
    async with Client(create_server(_library, backend_factory)) as c:
        async def call(name: str, args: dict):
            res = await c.call_tool(name, args)
            out["steps"].append({"tool": name, "args": args})
            return res

        composed = (await c.call_tool("compose_chain", {"requirement": requirement, "top_n": 1, "lang": lang})).data
        if not composed["candidates"]:
            out["error"] = "没有候选方案"
            return out
        system = composed["candidates"][0]["system"]
        out["system"] = system
        components = {}
        for item in system["components"]:
            cid = item["component"]
            if cid not in components:
                components[cid] = (await c.call_tool("get_component", {"component_id": cid})).data
            await call("place_component", {"instance": item["instance"], "component_id": cid})

        mech = [x for x in system["connections"]
                if all(_port_type(components, system, r) in MECH_TYPES for r in (x["a"], x["b"]))]
        mech.sort(key=lambda x: 0 if _port_type(components, system, x["a"]) in FACE_TYPES else 1)
        for x in mech:
            res = (await call("connect_ports", {"a": x["a"], "b": x["b"]})).data
            if res.get("note"):
                out["notes"].append(f"{x['a']} ↔ {x['b']}：{res['note']}")

        layout = None
        for _ in range(max_rounds):
            try:
                result = (await call("check_interference", {})).data
            except ToolError as exc:
                out["notes"].append(f"跳过干涉检查与截图：{exc}")
                out["interference_checked"] = False
                break
            out["interference_checked"] = True
            out["rounds"].append(result)
            if result["ok"]:
                break
            layout = (await c.call_tool("place_component", {"instance": system["components"][0]["instance"],
                                                            "position_mm": [0, 0, 0]})).data["layout"]
            moves, stuck = _resolve_moves(layout, result["interferences"], gap_mm)
            if stuck:
                out["stuck"] = stuck
                out["notes"].append("同一刚性组内有干涉，无法靠移动消除，需换候选方案")
                break
            for m in moves:
                await call("place_component", m)
        if out.get("interference_checked") and out["rounds"] and out["rounds"][-1]["ok"]:
            snap = await call("snapshot", {"view": "iso", "width": 800, "height": 600})
            out["snapshot_png"] = base64.b64decode(snap.content[0].data)
        out["layout"] = (await c.call_tool("place_component", {"instance": system["components"][0]["instance"],
                                                                "position_mm": [0, 0, 0]})).data["layout"]
        out["verified"] = (await call("verify_system", {"system": system, "use_layout": True, "lang": lang})).data
        out["urdf"] = (await call("export_system", {"system": system, "format": "urdf", "use_layout": True})).data
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M4b 演示：候选方案 → 布局 → 消除干涉 → 截图 → 复核与导出")
    parser.add_argument("requirement", type=Path, help="结构化需求 JSON（schema/requirement.schema.json）")
    parser.add_argument("--lang", choices=("zh", "en"), default="zh")
    parser.add_argument("--out", type=Path, help="保存截图（layout-iso.png）与 URDF 的目录")
    parser.add_argument("--gap", type=float, default=20.0, help="移开干涉件时留的间隙，mm")
    args = parser.parse_args(argv)
    requirement = json.loads(args.requirement.read_text(encoding="utf-8"))
    out = asyncio.run(run(requirement, lang=args.lang, gap_mm=args.gap))
    if "error" in out:
        print(out["error"])
        return 1
    print("# 方案：" + "、".join(f"{c['instance']}={c['component']}" for c in out["system"]["components"]))
    print("\n# 工具调用")
    for s in out["steps"]:
        args_ = {k: (f"<系统 {v['id']}>" if k == "system" else v) for k, v in s["args"].items()}
        print(f"- {s['tool']} {json.dumps(args_, ensure_ascii=False)}")
    for i, r in enumerate(out["rounds"], 1):
        pairs = "、".join(f"{h['a']}–{h['b']} {h['volume_mm3']:g} mm³" for h in r["interferences"]) or "无"
        print(f"\n# 干涉检查第 {i} 轮：{'通过' if r['ok'] else '有干涉'}；干涉：{pairs}")
        for p in r["pass_through"]:
            print(f"  需有通孔：{p['instance']}（{', '.join(p['shaft'])} 穿过）")
    for n in out["notes"]:
        print(f"\n注意：{n}")
    print("\n# 最终布局")
    for i in out["layout"]["instances"]:
        print(f"- {i['instance']}：位置 {i['position_mm']} mm，转角 {i['rotation']['angle_deg']}°")
    print("\n# 按布局复核\n")
    print(out["verified"]["explanation"])
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / out["urdf"]["filename"]).write_text(out["urdf"]["content"], encoding="utf-8")
        if "snapshot_png" in out:
            (args.out / "layout-iso.png").write_bytes(out["snapshot_png"])
        print(f"\n已保存到 {args.out}")
    if not out.get("interference_checked"):
        return 2
    return 0 if out["rounds"][-1]["ok"] and "stuck" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
