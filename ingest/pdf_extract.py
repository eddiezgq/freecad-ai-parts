"""PDF 文本与表格提取（issue #28）。

用 pdfplumber 逐页提取文本和表格，保留页码（从 1 开始），供 LLM 结构化抽取（#29）使用。
只做忠实的提取，不做任何解释：不猜单位、不合并跨页表格、不丢弃看似无用的行。

单元格里的换行是排版折行，按两侧字符合并：两侧都是中文（或中文标点）时直接相连，否则用一个空格连接。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

EXTRACTOR_VERSION = "pdfplumber-lines/1"

_CJK_CHAR = re.compile(r"[　-〿㐀-鿿＀-￯]")
_SPACES = re.compile(r"[ \t ]+")


class ExtractError(ValueError):
    """文件不是可读的 PDF。"""


@dataclass(frozen=True)
class Table:
    page: int
    index: int  # 本页第几张表，从 0 开始
    rows: list[list[str | None]]  # None 表示合并单元格占位或空单元格
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom（pt，页面左上角为原点）


@dataclass(frozen=True)
class Page:
    page: int
    text: str
    tables: list[Table] = field(default_factory=list)
    # 按文字对齐切出的行与列（pdfplumber 的“文字”策略）：没有边框的表也能分出列；只用于核对引用，不交给 LLM
    layout_rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class Document:
    path: str
    sha256: str
    pages: list[Page]
    extractor: str = EXTRACTOR_VERSION

    @property
    def tables(self) -> list[Table]:
        return [t for p in self.pages for t in p.tables]

    def to_dict(self) -> dict:
        return asdict(self)

    def select(self, pages: list[int]) -> Document:
        """只保留给定页码（原页码不变，SHA-256 仍是整份文件的）：多型号目录只把相关页交给 LLM（ADR-0040）。"""
        wanted = set(pages)
        missing = sorted(wanted - {p.page for p in self.pages})
        if missing:
            raise ExtractError(f"页码 {missing} 超出文档范围（共 {len(self.pages)} 页）")
        return replace(self, pages=[p for p in self.pages if p.page in wanted])

    def to_prompt_text(self) -> str:
        """给 LLM 的文本：逐页列出表格（Markdown）和正文，每页标明页码。"""
        out = []
        for p in self.pages:
            out.append(f"=== 第 {p.page} 页 / page {p.page} ===")
            for t in p.tables:
                out.append(f"[表 {t.index + 1} / table {t.index + 1}]")
                out.append(_markdown(t.rows))
            out.append("[正文 / text]")
            out.append(p.text)
        return "\n".join(out).strip() + "\n"


def parse_pages(spec: str) -> list[int]:
    """“2-5,8” → [2, 3, 4, 5, 8]：页码从 1 开始，升序去重。"""
    out: set[int] = set()
    for part in (spec or "").replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)|(\d+)", part)
        if not m:
            raise ValueError(f"页码写法不对：{part!r}（例：2-5,8）")
        lo, hi = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(3)), int(m.group(3)))
        if lo < 1 or hi < lo:
            raise ValueError(f"页码范围不对：{part!r}")
        out.update(range(lo, hi + 1))
    if not out:
        raise ValueError("没有给出页码")
    return sorted(out)


def clean_cell(text: str | None) -> str | None:
    """合并单元格内的排版折行，压缩空白。"""
    if text is None:
        return None
    lines = [_SPACES.sub(" ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    out = lines[0]
    for ln in lines[1:]:
        joiner = "" if _CJK_CHAR.match(out[-1]) and _CJK_CHAR.match(ln[0]) else " "
        out += joiner + ln
    return out


def _markdown(rows: list[list[str | None]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def line(r):
        cells = [(c or "").replace("|", "\\|") for c in r] + [""] * (width - len(r))
        return "| " + " | ".join(cells) + " |"

    return "\n".join([line(rows[0]), "| " + " | ".join(["---"] * width) + " |", *map(line, rows[1:])])


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_LAYOUT = {"vertical_strategy": "text", "horizontal_strategy": "text", "snap_tolerance": 3, "join_tolerance": 3,
           "intersection_tolerance": 5, "text_x_tolerance": 2}


def _layout_rows(pg) -> list[list[str]]:
    try:
        tables = pg.extract_tables(_LAYOUT) or []
    except Exception:  # noqa: BLE001 — 版面切分失败不影响文本与表格
        return []
    return [[clean_cell(c) or "" for c in row] for rows in tables for row in rows if any((c or "").strip() for c in row)]


def extract(path: str | Path) -> Document:
    """提取 PDF 的逐页文本与表格。表格用 pdfplumber 的“线框”策略：只认有边框的表。"""
    import pdfplumber
    from pdfminer.pdfparser import PDFSyntaxError

    path = Path(path)
    if not path.is_file():
        raise ExtractError(f"文件不存在：{path}")
    with path.open("rb") as f:
        if not f.read(1024).lstrip().startswith(b"%PDF-"):
            raise ExtractError(f"不是 PDF 文件：{path}")
    pages = []
    try:
        with pdfplumber.open(path) as pdf:
            for n, pg in enumerate(pdf.pages, start=1):
                tables = []
                for i, t in enumerate(pg.find_tables()):
                    rows = [[clean_cell(c) for c in row] for row in t.extract()]
                    tables.append(Table(page=n, index=i, rows=rows, bbox=tuple(round(v, 2) for v in t.bbox)))
                text = "\n".join(clean_line for ln in (pg.extract_text() or "").splitlines()
                                 if (clean_line := _SPACES.sub(" ", ln).strip()))
                pages.append(Page(page=n, text=text, tables=tables, layout_rows=_layout_rows(pg)))
    except PDFSyntaxError as exc:
        raise ExtractError(f"PDF 无法解析：{path}（{exc}）") from exc
    except Exception as exc:  # 加密、损坏等情况 pdfminer 抛出的异常类型很多
        if exc.__class__.__module__.startswith(("pdfminer", "pdfplumber")):
            raise ExtractError(f"PDF 无法读取：{path}（{exc.__class__.__name__}: {exc}）") from exc
        raise
    return Document(path=str(path), sha256=_sha256(path), pages=pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="提取 PDF 的逐页文本与表格")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--format", choices=("json", "prompt"), default="json")
    args = parser.parse_args(argv)
    try:
        doc = extract(args.pdf)
    except ExtractError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(doc.to_prompt_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
