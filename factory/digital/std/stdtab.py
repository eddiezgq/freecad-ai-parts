"""Digitized standard and handbook tables (第 11、13 轮): one copy, read by the book's programs, the labs and the factory.

A table is a YAML file in ``textbook/<book>/std/`` or ``library/std_tables/`` in the parts-library format: ``standard``
(code, title), ``sources`` (key, title, url, note), ``columns`` ([name, 中文, English, unit]), ``rows`` (each with ``key``
and ``src``), ``checked`` (spot checks against a second source), ``excluded`` and ``notes``. A program that takes a
value from a table also takes its citation, so the calculation sheet and the text say where every number came from.

    from stdtab import table
    it = table("it_grades")                    # searched in every book's std/ folder, then library/std_tables
    row = it.find(size_over_mm__lt=35, size_to_mm__ge=35)
    it.value(row, "IT7_um")                    # 25
    it.cite(row)                               # "GB/T 1800.1-2020（修改采用 ISO 286-1:2010）表1"
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# the digital factory carries a synced copy of this module and the tables it needs next to each other (factory/digital/std)
SEARCH = [HERE, *sorted((ROOT / "textbook").glob("*/std")), ROOT / "library" / "std_tables"]
REQUIRED = ("standard", "sources", "columns", "rows")


class TableError(ValueError):
    pass


class Table:
    def __init__(self, name: str, path: Path, data: dict):
        self.name, self.path, self.data = name, path, data
        self.standard = data["standard"]
        self.sources = {s["key"]: s for s in data["sources"]}
        self.columns = {c[0]: {"zh": c[1], "en": c[2], "unit": c[3] if len(c) > 3 else ""} for c in data["columns"]}
        self.rows = data["rows"] or []
        self.notes = data.get("notes") or []

    # ------------------------------------------------------------ lookup
    def row(self, key: str) -> dict:
        for r in self.rows:
            if str(r.get("key")) == str(key):
                return r
        raise KeyError(f"{self.name}: no row {key!r}")

    def find(self, **cond) -> dict:
        """The one row meeting every condition; ``col__lt=x`` means row[col] < x (also le, gt, ge, ne), plain
        ``col=x`` means equal. Raises when no row or more than one row matches."""
        ops = {"lt": lambda a, b: a < b, "le": lambda a, b: a <= b, "gt": lambda a, b: a > b,
               "ge": lambda a, b: a >= b, "ne": lambda a, b: a != b, "eq": lambda a, b: a == b}
        hit = []
        for r in self.rows:
            ok = True
            for k, v in cond.items():
                col, _, op = k.partition("__")
                if col not in r or r[col] is None or not ops[op or "eq"](r[col], v):
                    ok = False
                    break
            if ok:
                hit.append(r)
        if len(hit) != 1:
            raise KeyError(f"{self.name}: {len(hit)} rows match {cond}")
        return hit[0]

    def value(self, row: dict, col: str):
        if col not in self.columns:
            raise KeyError(f"{self.name}: no column {col!r}")
        v = row.get(col)
        if v is None:
            raise KeyError(f"{self.name}: row {row.get('key')!r} has no value in {col!r} (标准中无此值或未收录)")
        return v

    # ------------------------------------------------------------ citation
    def cite(self, row: dict | None = None, lang: str = "zh") -> str:
        """Standard code (and table), plus the row's source keys when the table holds data from several sources."""
        code = self.standard.get("code", self.name)
        if row is None or len(self.sources) <= 1:
            return code
        return f"{code}［{'数据出处' if lang == 'zh' else 'data from'} {row.get('src', '')}］"

    def label(self) -> str:
        """A short name for messages (standard.short when the full code is long)."""
        return self.standard.get("short") or self.standard.get("code", self.name)

    def source_list(self) -> list[str]:
        return [f"{k}: {s['title']} {s.get('url', '')}".strip() for k, s in self.sources.items()]


def path_of(name: str) -> Path:
    for d in SEARCH:
        p = d / f"{name}.yaml"
        if p.exists():
            return p
    raise FileNotFoundError(f"standard table {name!r} not found in {', '.join(str(d.relative_to(ROOT)) for d in SEARCH)}")


def table(name: str) -> Table:
    p = path_of(name)
    return Table(name, p, yaml.safe_load(p.read_text(encoding="utf-8")))


def check(path: Path) -> list[str]:
    """Problems with one table file (used by the build and the tests): required keys, every row's source exists, every
    value column is declared, enough spot checks (at least 10, or every row when the table is smaller)."""
    probs: list[str] = []
    try:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:                                          # noqa: PERF203
        return [f"YAML 格式错误：{e}"]
    for k in REQUIRED:
        if k not in d:
            probs.append(f"缺少 {k}")
    if probs:
        return probs
    srcs = {s.get("key") for s in d["sources"]}
    for s in d["sources"]:
        if not str(s.get("url", "")).startswith(("https://", "http://")) and "isbn" not in str(s).lower():
            probs.append(f"出处 {s.get('key')} 没有网址")
    cols = {c[0] for c in d["columns"]}
    meta = {"key", "size", "src", "src_detail", "check", "ref", "note"}
    rows = d["rows"] or []
    for r in rows:
        for part in str(r.get("src", "")).split("+"):
            if part.strip() and part.strip() not in srcs:
                probs.append(f"行 {r.get('key')} 的出处 {part} 不在 sources 里")
        for k in r:
            if k not in cols and k not in meta:
                probs.append(f"行 {r.get('key')} 有未声明的列 {k}")
    n = len(d.get("checked") or [])
    if rows and n < min(10, len(rows)):
        probs.append(f"抽查只有 {n} 条，至少要 {min(10, len(rows))} 条")
    return probs
