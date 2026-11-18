"""通道 B：企业物料表 → 分类、查重、对应已有组件、待补清单（ADR-0099 41.3）。

分工：
- AI 做两件事：认列（物料编码、名称、规格型号、厂商、数量、单位、类别各在哪一列）、给每行提议品类；
- 代码做其余：读表、核对 AI 的认列与分类（列名必须是表里有的、品类必须是已有品类、未能分类必须写原因）、
  规范化型号、查重合并、对应公共库与企业库、按型号特征核对品类（对不上的标“待人确认”）、生成待补清单；
- 人确认列的对应、分类与对应关系。物料表本身不进企业库（价格、供应商是商业信息），只记文件名和 SHA-256。

发给 AI 的内容：认列只发表头和前 3 行（每格截断到 40 字）；分类只发认出来的编码、名称、型号、厂商、类别五列，
价格、供应商、数量等其余列不发。

核对与查重是纯函数：不联网、不调用 AI。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

PROMPT_VERSION = "bom/1"
DEFAULT_MODEL = "claude-sonnet-5-5"
ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = ROOT / "tests" / "recordings" / "bom"
BATCH_ROWS = 60                                         # 一次分类最多发多少行
SAMPLE_ROWS = 3
CELL_CHARS = 40

ROLES = ("code", "name", "model", "vendor", "quantity", "unit", "category")
ROLE_NAMES = {"code": "物料编码", "name": "名称", "model": "规格型号", "vendor": "厂商", "quantity": "数量",
              "unit": "单位", "category": "企业自己的类别"}
CATEGORIES = ("servo_motor", "stepper_motor", "drive", "reducer", "bearing", "adapter", "fastener",
              "purchased_part", "custom_part")
CATEGORY_NAMES = {"servo_motor": "伺服电机", "stepper_motor": "步进电机", "drive": "伺服驱动器", "reducer": "减速器",
                  "bearing": "滚动轴承", "adapter": "转接件（轴套、适配法兰）", "fastener": "标准紧固件",
                  "purchased_part": "其他外购件（同步带、带轮、电磁铁、传感器、机针、旋梭……）",
                  "custom_part": "自制件（企业自己设计加工：轴、曲柄、凸轮、支架、壳体……）"}
UNCLASSIFIED = "unclassified"


class BomError(ValueError):
    pass


# ---------------------------------------------------------------- 读表


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def read_table(path: str | Path, sheet: str | None = None) -> dict:
    """读 Excel / CSV：找表头行（前 20 行里第一行有 ≥3 个非空格且多数不是数字的），返回表头和数据行（带原表行号）"""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook

        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb[sheet] if sheet else wb.worksheets[0]
        raw = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        wb.close()
    elif path.suffix.lower() in (".csv", ".txt"):
        data = path.read_bytes()
        for enc in ("utf-8-sig", "gb18030"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise BomError(f"{path.name}：认不出文字编码（试过 UTF-8、GB18030）")
        raw = [[_cell(v) for v in row] for row in csv.reader(text.splitlines())]
    else:
        raise BomError(f"{path.name}：只认 .xlsx / .csv")
    header_at = None
    for i, row in enumerate(raw[:20]):
        filled = [c for c in row if c]
        if len(filled) >= 3 and sum(not _numeric(c) for c in filled) > len(filled) / 2:
            header_at = i
            break
    if header_at is None:
        raise BomError(f"{path.name}：前 20 行里找不到表头（至少 3 个非空的列名）")
    headers = raw[header_at]
    width = max(len(headers), *(len(r) for r in raw)) if raw else 0
    headers = [h or f"第{j + 1}列" for j, h in enumerate(headers + [""] * (width - len(headers)))]
    if len(set(headers)) != len(headers):
        seen: dict[str, int] = {}
        out = []
        for h in headers:
            seen[h] = seen.get(h, 0) + 1
            out.append(h if seen[h] == 1 else f"{h}（{seen[h]}）")
        headers = out
    rows = []
    for i, row in enumerate(raw[header_at + 1:], start=header_at + 2):   # 原表行号（从 1 起）
        row = row + [""] * (width - len(row))
        if any(row):
            rows.append({"row": i, "cells": dict(zip(headers, row, strict=True))})
    return {"file": path.name, "sha256": sha256_file(path), "headers": headers, "rows": rows}


def _numeric(s: str) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 规范化与特征（纯函数）

_SEP = str.maketrans({"－": "-", "—": "-", "–": "-", "‐": "-", "_": "-", "／": "/", "＊": "*", "×": "X", "ｘ": "X"})
_SUFFIX = re.compile(r"\b(co|corp|corporation|inc|ltd|llc|gmbh|ag|kk|limited|company|electric|america)\b\.?", re.IGNORECASE)


def norm_model(text: str) -> str:
    """型号的比较写法：全角转半角、统一分隔符、去空格、大写。只用于比较，不改原文"""
    t = unicodedata.normalize("NFKC", text or "").translate(_SEP).upper()
    t = re.sub(r"\s*-\s*", "-", t)
    return re.sub(r"\s+", "", t)


def norm_vendor(text: str) -> str:
    """厂商名的比较写法：去公司后缀与标点（“Yaskawa America, Inc.” 与 “YASKAWA” 同一家）"""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = re.sub(r"(株式会社|有限公司|股份有限公司|公司|集团)", "", t)
    t = _SUFFIX.sub("", t)
    return re.sub(r"[\s.,()（）&\-]+", "", t)


# 型号特征：只用来“发现对不上”，不用来分类。每条：(品类, 正则, 说明)
FEATURES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("bearing", re.compile(r"^(6|16|NU|NJ|NUP|N|7|72|73|32|30|22|23|51|52|UC|UCP|HK|NK|NA)\d{2,4}[A-Z]?"
                           r"(-?(ZZ|2Z|2RS|2RS1|2RZ|DDU|VV|LLU|LLB|RS|Z|C3|P5|P6))*(/[A-Z0-9]+)?$"), "像滚动轴承代号"),
    ("fastener", re.compile(r"^(GB/?T?|ISO|DIN|JIS|GB)[- ]?\d+.*M\d|^M\d+(\.\d+)?[X*]\d+"), "像紧固件规格（M×长度或标准号）"),
)


def model_feature(model: str, name: str = "") -> tuple[str, str] | None:
    m = norm_model(model)
    for cat, rx, why in FEATURES:
        if m and rx.search(m):
            return cat, why
    return None


# ---------------------------------------------------------------- AI 请求


SYSTEM_COLUMNS = (
    "你在帮机械企业整理物料表（BOM）。给你表头和前几行，认出每种信息在哪一列。"
    "只能填表头里原样出现的列名；表里没有这种信息就不填。不要猜，不要改列名。"
)
SYSTEM_CLASSIFY = (
    "你在帮机械企业整理物料表（BOM）。给每一行提议一个品类。品类只能从清单里选；"
    "看不出来、或不属于任何品类的，品类填 unclassified 并写明原因（例如“名称和型号都看不出是什么”）。"
    "企业自己设计加工的零件（图号、轴、曲柄、凸轮、支架等）是 custom_part；"
    "买来的、但不是电机、驱动器、减速器、轴承、转接件、标准紧固件的，是 purchased_part。"
    "part_kind 写通用叫法的英文小写（如 shaft、timing_belt、solenoid），可以不填。"
)
TOOL_INSTRUCTION = "\n必须调用一次工具 {name} 提交结果。"

COLUMNS_TOOL = {
    "name": "map_columns",
    "description": "提交每种信息所在的列名",
    "input_schema": {"type": "object", "properties": {
        "columns": {"type": "object", "properties": {r: {"type": "string", "description": ROLE_NAMES[r]} for r in ROLES},
                    "additionalProperties": False}}, "required": ["columns"]},
}
CLASSIFY_TOOL = {
    "name": "classify_rows",
    "description": "提交每一行的品类提议",
    "input_schema": {"type": "object", "properties": {"rows": {"type": "array", "items": {
        "type": "object", "properties": {
            "row": {"type": "integer"}, "category": {"enum": [*CATEGORIES, UNCLASSIFIED]},
            "part_kind": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["row", "category"]}}}, "required": ["rows"]},
}


def _clip(s: str) -> str:
    return s if len(s) <= CELL_CHARS else s[:CELL_CHARS] + "…"


def columns_request(table: dict, *, model: str = DEFAULT_MODEL) -> dict:
    lines = ["表头：" + json.dumps(table["headers"], ensure_ascii=False)]
    for r in table["rows"][:SAMPLE_ROWS]:
        lines.append(f"第 {r['row']} 行：" + json.dumps([_clip(r["cells"][h]) for h in table["headers"]], ensure_ascii=False))
    roles = "\n".join(f"- {r}：{ROLE_NAMES[r]}" for r in ROLES)
    return {"model": model, "prompt_version": PROMPT_VERSION,
            "system": SYSTEM_COLUMNS + TOOL_INSTRUCTION.format(name=COLUMNS_TOOL["name"]),
            "user": f"要认的信息：\n{roles}\n\n" + "\n".join(lines), "tool": COLUMNS_TOOL}


def classify_requests(table: dict, columns: dict[str, str], *, model: str = DEFAULT_MODEL) -> list[dict]:
    keep = [r for r in ("code", "name", "model", "vendor", "category") if r in columns]
    cats = "\n".join(f"- {c}：{CATEGORY_NAMES[c]}" for c in CATEGORIES)
    out = []
    rows = table["rows"]
    for i in range(0, len(rows), BATCH_ROWS):
        lines = []
        for r in rows[i:i + BATCH_ROWS]:
            vals = {ROLE_NAMES[k]: _clip(r["cells"][columns[k]]) for k in keep if r["cells"][columns[k]]}
            lines.append(f"{r['row']}：" + json.dumps(vals, ensure_ascii=False))
        out.append({"model": model, "prompt_version": PROMPT_VERSION,
                    "system": SYSTEM_CLASSIFY + TOOL_INSTRUCTION.format(name=CLASSIFY_TOOL["name"]),
                    "user": f"品类清单：\n{cats}\n\n各行（行号：内容）：\n" + "\n".join(lines), "tool": CLASSIFY_TOOL})
    return out


# ---------------------------------------------------------------- 核对 AI 的提议（纯函数）


def check_columns(proposal: Any, headers: list[str]) -> tuple[dict[str, str], list[str]]:
    """列的对应：只收表里原样有的列名、已知的信息种类、一列只对一种信息；必须认出名称或型号"""
    notes: list[str] = []
    cols = proposal.get("columns") if isinstance(proposal, dict) else None
    if not isinstance(cols, dict):
        raise BomError("AI 没有给出列的对应")
    out: dict[str, str] = {}
    used: dict[str, str] = {}
    for role, h in cols.items():
        if role not in ROLES:
            notes.append(f"不认识的信息种类 {role!r}，未采用")
        elif not isinstance(h, str) or h not in headers:
            notes.append(f"{ROLE_NAMES[role]}：列名 {h!r} 不在表头里，未采用")
        elif h in used:
            notes.append(f"{ROLE_NAMES[role]}：列 {h!r} 已对应{ROLE_NAMES[used[h]]}，未采用")
        else:
            out[role] = h
            used[h] = role
    if "name" not in out and "model" not in out:
        raise BomError("认不出名称列，也认不出规格型号列，没法分类；请人指定列的对应")
    return out, notes


def check_classes(proposals: Iterable[Any], row_numbers: set[int]) -> tuple[dict[int, dict], list[str]]:
    notes: list[str] = []
    out: dict[int, dict] = {}
    for p in proposals:
        if not isinstance(p, dict) or not isinstance(p.get("row"), int) or isinstance(p.get("row"), bool):
            notes.append(f"分类提议格式不对：{p!r}")
            continue
        n = p["row"]
        if n not in row_numbers:
            notes.append(f"第 {n} 行不在表里，提议未采用")
            continue
        if n in out:
            notes.append(f"第 {n} 行给了两次分类，只用第一次")
            continue
        cat = p.get("category")
        reason = (p.get("reason") or "").strip() if isinstance(p.get("reason"), str) else ""
        if cat not in (*CATEGORIES, UNCLASSIFIED):
            out[n] = {"category": UNCLASSIFIED, "reason": f"AI 给的品类 {cat!r} 不在清单里"}
            continue
        if cat == UNCLASSIFIED and not reason:
            reason = "AI 没写原因"
        item = {"category": cat}
        if reason:
            item["reason"] = reason
        kind = p.get("part_kind")
        if isinstance(kind, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,40}", kind.strip()):
            item["part_kind"] = kind.strip()
        out[n] = item
    return out, notes


# ---------------------------------------------------------------- 查重、对应、核对（纯函数）


def dedupe(rows: list[dict], columns: dict[str, str]) -> list[list[int]]:
    """同一厂商 + 规范化型号，或同一物料编码 → 一组（并查集；返回各组的原表行号）"""
    parent = {r["row"]: r["row"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen: dict[tuple, int] = {}
    for r in rows:
        c = r["cells"]
        keys = []
        if "code" in columns and c[columns["code"]]:
            keys.append(("code", norm_model(c[columns["code"]])))
        if "model" in columns and c[columns["model"]]:
            vendor = norm_vendor(c[columns["vendor"]]) if "vendor" in columns else ""
            keys.append(("model", vendor, norm_model(c[columns["model"]])))
        for k in keys:
            if k in seen:
                parent[find(r["row"])] = find(seen[k])
            else:
                seen[k] = r["row"]
    groups: dict[int, list[int]] = {}
    for r in rows:
        groups.setdefault(find(r["row"]), []).append(r["row"])
    return sorted(groups.values(), key=lambda g: g[0])


def match_library(vendor: str, model: str, components: list[dict]) -> tuple[list[str], str]:
    """厂商 + 型号对上已有组件。返回（组件 id 列表, 怎么对上的）：
    厂商与型号都对上 → 对应；只有型号对上（物料表没写厂商或厂商写法不同）→ 候选，待人确认"""
    m = norm_model(model)
    if not m:
        return [], ""
    same_model = [c for c in components if norm_model(c.get("model", "")) == m]
    if not same_model:
        return [], ""
    v = norm_vendor(vendor)
    exact = [c["id"] for c in same_model if v and (norm_vendor(c.get("vendor", "")) == v
                                                   or norm_vendor(c.get("vendor", "")).startswith(v)
                                                   or v.startswith(norm_vendor(c.get("vendor", ""))))]
    if exact:
        return exact, "matched"
    return [c["id"] for c in same_model], "candidate"


def build(table: dict, columns: dict[str, str], classes: dict[int, dict], components: list[dict],
          gaps: Callable[[dict], list[dict]] | None = None) -> dict:
    """合成结果：每行的分类结论、查重分组、对应关系、待人确认、待补清单"""
    by_id = {c["id"]: c for c in components}
    rows_by_no = {r["row"]: r for r in table["rows"]}

    def val(r, role):
        return r["cells"][columns[role]] if role in columns else ""

    items = []
    for group in dedupe(table["rows"], columns):
        first = rows_by_no[group[0]]
        cats = {classes.get(n, {}).get("category", UNCLASSIFIED) for n in group}
        cls = classes.get(group[0]) or {"category": UNCLASSIFIED, "reason": "AI 没给这一行的分类"}
        item = {"rows": group, "code": val(first, "code"), "name": val(first, "name"), "model": val(first, "model"),
                "vendor": val(first, "vendor"), "category": cls["category"], "confirm": []}
        for k in ("reason", "part_kind"):
            if k in cls:
                item[k] = cls[k]
        if len(cats) > 1:
            item["confirm"].append("同一物料的几行分到了不同品类：" + "、".join(sorted(cats)))
        if len(group) > 1:
            q = [val(rows_by_no[n], "quantity") for n in group] if "quantity" in columns else []
            item["duplicates"] = f"第 {'、'.join(map(str, group))} 行是同一物料（同厂商同型号或同编码），合并成一条" + (
                f"；数量分别是 {'、'.join(x or '—' for x in q)}" if q else "")
        ids, how = match_library(item["vendor"], item["model"], components)
        if how == "matched" and len(ids) == 1:
            item["component"] = ids[0]
        elif ids:
            item["candidates"] = ids
            item["confirm"].append("型号对上了库里的组件，厂商没对上或对上不止一个：请人确认" if how == "candidate"
                                   else "对上了不止一个组件：请人选")
        lib_cat = by_id[ids[0]]["category"] if ids and ids[0] in by_id else None
        if lib_cat and item["category"] not in (lib_cat, UNCLASSIFIED):
            item["confirm"].append(f"AI 分成 {item['category']}，库里对上的组件是 {lib_cat}")
        feat = model_feature(item["model"], item["name"])
        if feat and item["category"] not in (feat[0], UNCLASSIFIED):
            item["confirm"].append(f"型号{feat[1]}，AI 却分成 {item['category']}")
        if item["category"] == UNCLASSIFIED:
            item["confirm"].append("未能分类：" + item.get("reason", "AI 没写原因"))
        items.append(item)
    to_fill = []
    for it in items:
        if it["category"] == UNCLASSIFIED:
            continue
        if "component" in it:
            if gaps is not None:
                miss = gaps(by_id[it["component"]])
                if miss:
                    to_fill.append({"rows": it["rows"], "component": it["component"], "missing": miss})
        else:
            to_fill.append({"rows": it["rows"], "category": it["category"], "model": it["model"], "vendor": it["vendor"],
                            "missing": "库里没有，新建组件：按通道 A（规格书 / 目录）或通道 C（三维模型）补数据"})
    return {"source": {"file": table["file"], "sha256": table["sha256"], "note": "物料表不进企业库，只记文件名和 SHA-256"},
            "columns": columns, "items": items, "to_fill": to_fill,
            "summary": {"rows": len(table["rows"]), "items": len(items),
                        "classified": sum(len(i["rows"]) for i in items if i["category"] != UNCLASSIFIED),
                        "matched": sum("component" in i for i in items),
                        "confirm": sum(bool(i["confirm"]) for i in items)}}


# ---------------------------------------------------------------- 流程


def run(path: str | Path, client, components: list[dict], *, model: str = DEFAULT_MODEL, sheet: str | None = None,
        columns: dict[str, str] | None = None, gaps: Callable[[dict], list[dict]] | None = None) -> dict:
    """读表 → AI 认列（人已指定 columns 时跳过）→ AI 分类 → 代码核对、查重、对应。结果都是“待人确认”的草稿"""
    table = read_table(path, sheet)
    notes: list[str] = []
    calls = []
    if columns is None:
        resp = client.complete(columns_request(table, model=model))
        calls.append(_call(resp))
        columns, n = check_columns(resp["tool_input"], table["headers"])
        notes += n
    else:
        columns, n = check_columns({"columns": columns}, table["headers"])
        notes += n
    proposals: list = []
    for req in classify_requests(table, columns, model=model):
        resp = client.complete(req)
        calls.append(_call(resp))
        rows = resp["tool_input"].get("rows") if isinstance(resp["tool_input"], dict) else None
        proposals += rows if isinstance(rows, list) else []
    classes, n = check_classes(proposals, {r["row"] for r in table["rows"]})
    notes += n
    out = build(table, columns, classes, components, gaps)
    out["notes"] = notes
    out["ai"] = calls
    out["confirmed"] = False
    return out


def _call(resp: dict) -> dict:
    return {k: resp[k] for k in ("id", "provider", "model", "simulated") if k in resp}


def to_excel(result: dict, path: str | Path) -> Path:
    """分类结果给人看、给人改：每条物料一行"""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "分类"
    ws.append(["原表行号", "物料编码", "名称", "规格型号", "厂商", "品类", "零件类型", "对应组件", "待人确认"])
    for it in result["items"]:
        ws.append(["、".join(map(str, it["rows"])), it["code"], it["name"], it["model"], it["vendor"],
                   CATEGORY_NAMES.get(it["category"], "未能分类"), it.get("part_kind", ""),
                   it.get("component") or "、".join(it.get("candidates", [])), "；".join(it["confirm"])])
    ws2 = wb.create_sheet("待补")
    ws2.append(["原表行号", "组件 / 型号", "缺什么"])
    for t in result["to_fill"]:
        miss = t["missing"] if isinstance(t["missing"], str) else "、".join(g["field"] for g in t["missing"])
        ws2.append(["、".join(map(str, t["rows"])), t.get("component") or f"{t['vendor']} {t['model']}".strip(), miss])
    for s in (ws, ws2):
        for c in s[1]:
            c.font = Font(bold=True)
        s.freeze_panes = "A2"
    path = Path(path)
    wb.save(path)
    return path


# ---------------------------------------------------------------- 命令行


def _client(args):
    from ingest.llm_extract import RecordedClient

    if args.record is not None or args.live:
        from assist.llm import GatewayClient

        return GatewayClient(args.provider, record_dir=args.record)
    return RecordedClient(args.replay or RECORDINGS_DIR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingest.bom", description="物料表分类、查重、对应已有组件（ADR-0099 通道 B）")
    ap.add_argument("table", type=Path)
    ap.add_argument("--sheet")
    ap.add_argument("--library", type=Path, action="append", default=[],
                    help="组件库目录（JSON），可给多个；缺省用公共库 data/library")
    ap.add_argument("-o", "--out", type=Path, default=None, help="结果 JSON；.xlsx 结尾则导出 Excel")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path, default=None)
    mode.add_argument("--record", type=Path, nargs="?", const=RECORDINGS_DIR, default=None)
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--provider", choices=("claude", "deepseek"), default=None)
    a = ap.parse_args(argv)
    from kb import completeness
    from kb.library import JsonLibrary

    comps: list[dict] = []
    for d in a.library or [ROOT / "data" / "library"]:
        comps += JsonLibrary(d).all()
    client = _client(a)
    model = getattr(client, "model", None) or DEFAULT_MODEL
    try:
        r = run(a.table, client, comps, model=model, sheet=a.sheet, gaps=completeness.component_gaps)
    except BomError as ex:
        print(f"没有分类：{ex}", file=sys.stderr)
        return 2
    if a.out and a.out.suffix.lower() == ".xlsx":
        to_excel(r, a.out)
    elif a.out:
        a.out.write_text(json.dumps(r, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    s = r["summary"]
    print(f"{s['rows']} 行 → {s['items']} 条物料；已分类 {s['classified']} 行；对上已有组件 {s['matched']} 条；"
          f"待人确认 {s['confirm']} 条（AI 提议，未确认）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
