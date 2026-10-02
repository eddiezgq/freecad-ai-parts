"""端到端演示（M5 #101，ADR-0037）：一句话需求 → 结构化需求 → 候选方案 → 布局与消除干涉 → 按布局复核 → 导出。

    python -m mcp_server.e2e "一句话需求" --out out/              # 解析用录制回放（--record 时真实调用并录制）
    python -m mcp_server.e2e --requirement examples/joint2-requirement.json --out out/
    FAP_FREECAD=headless python -m mcp_server.e2e ...               # 有 FreeCAD 时做干涉检查并截图

输出目录：requirement.json、bom.csv、bom.json、system.json、<方案 id>.urdf、README.md（汇总），有 FreeCAD 时另有
layout-iso.png。同一输入、同一组件库，除截图外的输出逐字节相同。
退出码：0 跑通且无干涉；1 没有方案、需追问或干涉无法消除；2 未连接 FreeCAD（未做干涉检查）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from mcp_server.layout import Backend, default_backend
from mcp_server.layout_demo import run as run_layout

FILES = ("requirement.json", "bom.csv", "bom.json", "system.json")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


GENERATED_VENDOR = "freecad-ai-parts (generated)"


def _provenance(out: dict) -> list[str]:
    """每个组件的数据来源与复核状态（ADR-0040、0041）：用的是真实数据、虚构数据还是生成件，一眼可见。"""
    comps = out.get("system_json", {}).get("content", {}).get("components", {})
    if not comps:
        return []
    lines = ["| 实例 | 厂商与型号 | 数据来源 | 复核 |", "| --- | --- | --- | --- |"]
    for c in out["system"]["components"]:
        comp = comps.get(c["component"]) or {}
        values = list(comp.get("params", {}).values()) + [
            v for p in comp.get("ports", []) for v in p.get("spec", {}).values()]
        docs = sorted({v["source"]["doc"] for v in values if v.get("source", {}).get("doc")})
        if comp.get("vendor") == GENERATED_VENDOR:
            source, review = "按两侧端口尺寸生成（ADR-0041），须加工", "加工前按图纸复核"
        elif c["component"].startswith("test."):
            source, review = "虚构测试组件（ADR-0015）", "—"
        else:
            source = "、".join(f"`{d}`" for d in docs) or "—"
            notes = {v.get("source", {}).get("note", "") for v in values}
            if values and all(v.get("reviewed") is True for v in values):
                review = "AI 复核（两次独立抽取一致）" if any("AI 复核" in n for n in notes) else "已复核"
            else:
                review = "部分未复核"
        lines.append(f"| `{c['instance']}` | {comp.get('vendor', '')} {comp.get('model', '')} | {source} | {review} |")
    return [*lines, ""]


def _summary(parsed: dict | None, requirement: dict, out: dict) -> str:
    lines = ["# 端到端演示结果", ""]
    lines += ["## 需求", "", f"原话：{requirement.get('statement', '（未给出原话，直接使用结构化需求）')}", ""]
    if parsed is not None:
        tag = "模拟响应（离线演示用）" if parsed["llm"]["simulated"] else f"{parsed['llm']['model']} 的录制响应"
        lines += [f"解析：{tag}，提示词 {parsed['llm']['prompt_version']}；每项都核对过原文依据（ADR-0037）", ""]
        lines += ["| 字段 | 值 | 原文依据 |", "| --- | --- | --- |"]
        flat = dict(requirement)
        for k, v in flat.pop("supply", {}).items():
            flat[f"supply.{k}"] = v
        for k, v in flat.items():
            if k != "statement":
                lines.append(f"| `{k}` | {v} | {parsed['basis'].get(k, '默认值' if k == 'safety_factor' else '')} |")
        lines += [""] + [f"- {d}" for d in parsed["defaults"]] + [""]
    if "error" in out:
        return "\n".join([*lines, f"**{out['error']}**", ""])
    lines += ["## 方案", ""] + [f"- `{c['instance']}`：{c['component']}" for c in out["system"]["components"]] + [""]
    lines += _provenance(out)
    lines += ["## 布局与干涉", ""]
    if not out.get("interference_checked"):
        lines.append("未连接 FreeCAD，没有做干涉检查（设置 FAP_FREECAD=headless 后重跑）。")
    for i, r in enumerate(out["rounds"], 1):
        hits = "、".join(f"{h['a']}–{h['b']} {h['volume_mm3']:g} mm³" for h in r["interferences"]) or "无"
        lines.append(f"- 第 {i} 轮：{'通过' if r['ok'] else '有干涉'}；干涉：{hits}")
        for p in r["pass_through"]:
            lines.append(f"  - 需有通孔：{p['instance']}（{', '.join(p['shaft'])} 穿过）")
    lines += [""] + [f"注意：{n}" for n in out["notes"]] + [""]
    lines += ["| 实例 | 位置 mm | 转轴 | 转角 ° |", "| --- | --- | --- | --- |"]
    for i in out["layout"]["instances"]:
        lines.append(f"| `{i['instance']}` | {i['position_mm']} | {i['rotation']['axis']} | "
                     f"{i['rotation']['angle_deg']} |")
    lines += ["", "## 按布局复核", "", out["verified"]["explanation"].strip(), ""]
    files = [*FILES, out["urdf"]["filename"]] + (["layout-iso.png"] if "snapshot_png" in out else [])
    lines += ["## 文件", ""] + [f"- `{f}`" for f in files] + [""]
    return "\n".join(lines)


async def _run(requirement: dict, backend_factory: Callable[[], Backend | None], lang: str) -> dict:
    return await run_layout(requirement, lang=lang, backend_factory=backend_factory)


def run(*, statement: str | None = None, requirement: dict | None = None, out_dir: Path, record: bool = False,
        lang: str = "zh", backend_factory: Callable[[], Backend | None] = default_backend) -> int:
    parsed = None
    if statement is not None:
        from engine.requirement_parse import RECORDINGS_DIR, parse

        client = None
        if record:
            from ingest.llm_extract import AnthropicClient

            client = AnthropicClient(record_dir=RECORDINGS_DIR)
        parsed = parse(statement, client)
        requirement = parsed["requirement"]
    out_dir.mkdir(parents=True, exist_ok=True)
    if parsed is not None and parsed["status"] != "ok":
        (out_dir / "requirement.json").write_text(_dump(parsed), encoding="utf-8")
        text = _summary(parsed, requirement, {"error": "需求不完整，需要追问：" + "；".join(parsed["questions"])})
        (out_dir / "README.md").write_text(text, encoding="utf-8")
        print(text)
        return 1
    out = asyncio.run(_run(requirement, backend_factory, lang))
    record_req = {"requirement": requirement, **({k: parsed[k] for k in ("basis", "defaults", "llm")}
                                                  if parsed else {})}
    (out_dir / "requirement.json").write_text(_dump(record_req), encoding="utf-8")
    text = _summary(parsed, requirement, out)
    if "error" not in out:
        (out_dir / "bom.csv").write_text(out["bom_csv"]["content"], encoding="utf-8")
        (out_dir / "bom.json").write_text(_dump(out["bom_json"]["content"]), encoding="utf-8")
        (out_dir / "system.json").write_text(_dump(out["system_json"]["content"]), encoding="utf-8")
        (out_dir / out["urdf"]["filename"]).write_text(out["urdf"]["content"], encoding="utf-8")
        if "snapshot_png" in out:
            (out_dir / "layout-iso.png").write_bytes(out["snapshot_png"])
    (out_dir / "README.md").write_text(text, encoding="utf-8")
    print(text)
    if "error" in out:
        return 1
    if not out.get("interference_checked"):
        return 2
    return 0 if out["rounds"][-1]["ok"] and "stuck" not in out else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="端到端演示：一句话需求 → 选型 → 布局 → 复核 → BOM / URDF")
    p.add_argument("statement", nargs="?", help="一句话需求（经需求解析，ADR-0037）")
    p.add_argument("--requirement", type=Path, help="改用结构化需求 JSON（schema/requirement.schema.json）")
    p.add_argument("--out", type=Path, required=True, help="输出目录")
    p.add_argument("--record", action="store_true", help="需求解析真实调用 LLM 并录制（需要 ANTHROPIC_API_KEY）")
    p.add_argument("--lang", choices=("zh", "en"), default="zh")
    p.add_argument("--library", type=Path,
                   help="组件库目录（同 FAP_LIBRARY），如真实组件库 data/library；不给时用 FAP_LIBRARY 或虚构测试组件")
    args = p.parse_args(argv)
    if args.library is not None:
        if not args.library.is_dir():
            p.error(f"组件库目录不存在：{args.library}")
        os.environ["FAP_LIBRARY"] = str(args.library)
    if (args.statement is None) == (args.requirement is None):
        p.error("一句话需求与 --requirement 二选一")
    req = json.loads(args.requirement.read_text(encoding="utf-8")) if args.requirement else None
    return run(statement=args.statement, requirement=req, out_dir=args.out, record=args.record, lang=args.lang)


if __name__ == "__main__":
    sys.exit(main())
