"""导入规格书（M9 第三步，ADR-0055）：拖入厂商 PDF 或 Excel → AI 抽取 → 代码核对 → 人逐项确认 → 写入企业库。

- 抽取与核对沿用 ingest.llm_extract（AI 只报印出的内容；单位换算、原文引用、枚举与范围由代码核对）
- 本模块只做三件事：读文件、把抽取结果列成确认表、把勾选的项组成有依据的参数值写入企业库
- 未勾选、未通过核对的值一律不写；外形尺寸（dims/）只用于包络，这里不写
"""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from freecad_addon.core.fill import NAMES, UNIT_TEXT, value_text
from ingest.llm_extract import LLMClient, extract_document, targets
from ingest.pdf_extract import Document, Page, Table

SUFFIXES = (".pdf", ".xlsx", ".xlsm")


class SpecImportError(ValueError):
    """不能导入；消息说明原因。"""


# ---------------------------------------------------------------- 读文件


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def load_xlsx(path: str | Path) -> Document:
    """Excel 选型表 → 文档：每张工作表一页，表格原样保留；每行按单元格以空格连成一行文字。"""
    from openpyxl import load_workbook

    p = Path(path)
    wb = load_workbook(p, read_only=True, data_only=True)
    pages = []
    for n, ws in enumerate(wb.worksheets, start=1):
        rows = [[_cell(v) for v in r] for r in ws.iter_rows(values_only=True)]
        rows = [r for r in rows if any(r)]
        width = max((max((i for i, v in enumerate(r) if v), default=-1) for r in rows), default=-1) + 1
        rows = [r[:width] + [""] * (width - len(r[:width])) for r in rows]
        text = "\n".join(" ".join(v for v in r if v) for r in rows)
        tables = [Table(page=n, index=0, rows=[list(r) for r in rows], bbox=(0.0, 0.0, 0.0, 0.0))] if rows else []
        pages.append(Page(page=n, text=f"{ws.title}\n{text}" if text else ws.title, tables=tables, layout_rows=rows))
    wb.close()
    if not pages:
        raise SpecImportError("Excel 文件里没有工作表")
    return Document(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest(), pages=pages,
                    extractor="openpyxl-rows/1")


def load_document(path: str | Path) -> Document:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in SUFFIXES:
        raise SpecImportError(f"只支持 PDF 与 Excel（.xlsx）：{p.name}")
    if suffix == ".pdf":
        from ingest.pdf_extract import extract

        return extract(p)
    return load_xlsx(p)


# ---------------------------------------------------------------- 抽取


def run(enterprise, comp: Mapping, file: str | Path, actor: str, client: LLMClient, *, title: str | None = None,
        target_model: str | None = None, pages: list[int] | None = None) -> dict:
    """登记资料（企业库 docs/，记哈希）→ 读文件 → AI 抽取并由代码核对。返回抽取结果（extraction/1）。"""
    if enterprise is None:
        raise SpecImportError("还没有企业库：请先选择企业库文件夹")
    document = load_document(file)
    if not document.pages:
        raise SpecImportError("文件里读不到任何页面")
    doc = enterprise.register_document(file, title or Path(file).stem, actor)
    return extract_document(document, comp["category"], doc["id"], client, pages=pages or None,
                            target_model=(target_model or "").strip() or None)


# ---------------------------------------------------------------- 确认表


@dataclass(frozen=True)
class Row:
    target: str
    label: str
    value: str  # 标准单位下的值（文字）
    unit: str
    printed: str  # 规格书上印的（原文）
    page: int
    quote: str
    current: str  # 组件现有值的文字；缺时为空
    issues: tuple[str, ...]
    writable: bool  # 能否写入（外形尺寸、组件没有的端口不能）
    why_not: str = ""

    @property
    def changes(self) -> bool:
        return self.current != self.value

    @property
    def default_checked(self) -> bool:
        """默认勾选：能写、与现有值不同、除单位换算说明外没有需要复核的问题。"""
        return self.writable and self.changes and not self.attention

    @property
    def attention(self) -> tuple[str, ...]:
        """需要人特别核对的问题（单位换算只是说明，不算）。"""
        return tuple(i for i in self.issues if not i.startswith("单位换算"))


def _current(comp: Mapping, target: str) -> tuple[str, bool, str]:
    parts = target.split("/")
    if parts[0] == "params":
        return value_text((comp.get("params") or {}).get(parts[1])), True, ""
    if parts[0] == "ports":
        port = next((p for p in comp.get("ports", []) if p["id"] == parts[1]), None)
        if port is None:
            return "", False, f"组件没有端口 {parts[1]}"
        return value_text((port.get("spec") or {}).get(parts[2])), True, ""
    return "", False, "外形尺寸只用于包络，在新建零件时使用"


def rows(extraction: Mapping, comp: Mapping | None) -> list[Row]:
    """抽取结果 → 确认表。可写且有变化的排在前面。comp 为 None 时是新建零件：各项（含外形尺寸）都可写。"""
    tmap = targets(extraction["category"])
    out = []
    for item in extraction.get("items", []):
        tgt = item["target"]
        name = tgt.rsplit("/", 1)[-1]
        where = f"{tgt.split('/')[1]} · " if tgt.startswith("ports/") else ("外形 · " if tgt.startswith("dims/") else "")
        unit = tmap[tgt][0].unit if tgt in tmap else None
        printed = item["printed"]
        current, writable, why = ("", True, "") if comp is None else _current(comp, tgt)
        out.append(Row(
            target=tgt, label=where + NAMES.get(name, name), value=value_text(item["value"]),
            unit=UNIT_TEXT.get(unit or "", unit or ""),
            printed=" ".join(x for x in (printed.get("label"), printed["text"], printed.get("unit")) if x),
            page=item["value"]["source"]["page"], quote=printed.get("quote") or printed["text"], current=current,
            issues=tuple(item.get("issues", [])), writable=writable, why_not=why))
    return sorted(out, key=lambda r: (not r.writable, not r.changes, r.target))


def identity_note(extraction: Mapping, comp: Mapping) -> str:
    """规格书上的型号与组件型号不一致时提醒；一致或读不到时为空。"""
    model = extraction.get("model")
    if not model:
        return "规格书上没有核对到型号，请确认这份资料确实是该零件的"
    a, b = "".join(model.split()).casefold(), "".join(str(comp.get("model", "")).split()).casefold()
    if a in b or b in a:
        return ""
    return f"规格书上的型号是 {model}，与零件型号 {comp.get('model', '')} 不一致，请确认"


# ---------------------------------------------------------------- 写入


def confirmed_pv(item: Mapping, actor: str, today: str | None = None) -> dict:
    """抽取项 → 企业库参数值：保留抽取方法与核对过的原文，记确认人。"""
    actor = actor.strip()
    if not actor:
        raise SpecImportError("请写明确认人")
    pv = {k: v for k, v in item["value"].items() if k not in ("source", "reviewed")}
    quote = item["printed"].get("quote") or item["printed"]["text"]
    day = today or datetime.datetime.now().astimezone().date().isoformat()
    pv["source"] = {"doc": item["value"]["source"]["doc"], "page": item["value"]["source"]["page"],
                    "note": f"原文“{quote}”；AI 抽取、代码核对；确认人：{actor}（{day}）"}
    pv["reviewed"] = True
    return pv


def apply(enterprise, component_id: str, extraction: Mapping, chosen: Iterable[str], actor: str,
          base: Callable[[str], dict | None], today: str | None = None) -> list[str]:
    """把勾选的项写入企业库；返回写入的字段。只写抽取结果中通过核对的项。"""
    chosen = set(chosen)
    items = {i["target"]: i for i in extraction.get("items", [])}
    unknown = chosen - set(items)
    if unknown:
        raise SpecImportError(f"这些字段不在核对通过的抽取结果中：{'、'.join(sorted(unknown))}")
    written = []
    for tgt in sorted(chosen):
        if not tgt.startswith(("params/", "ports/")):
            raise SpecImportError(f"外形尺寸不在这里写：{tgt}")
        enterprise.set_value(component_id, tgt, confirmed_pv(items[tgt], actor, today), actor, base)
        written.append(tgt)
    return written
