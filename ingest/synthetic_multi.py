"""多型号模拟目录（ADR-0040，issue #125）：同一品类的全部虚构型号印在一份目录里，每个型号占表格一列。

真实厂商目录通常一份含多个型号、几百页。本模块生成这种版式的 PDF，用来检验“按页码范围和目标型号抽取”：

- 第 1 页：封面与系列介绍（不含参数表）
- 第 2 页：规格参数表；第 3 页：机械接口与尺寸表。表头是“项目 / 单位 / 各型号”，缺项印“—”
- 第 4 页：选型说明（正文，不含参数）

每个型号各有一份答案，格式与单型号规格书的答案相同（ingest.synthetic），另加 target_model 与 pages。
同一行的单位与叫法对所有型号相同；各型号工况不同的行不印（无法共用一行）。
目录同样印有“虚构产品”声明；数据永不进入正式库。
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from pathlib import Path

from ingest.synthetic import (
    DISCLAIMER,
    FIELDS,
    HEADERS,
    IFACE,
    SECTION_TITLES,
    SPEC,
    TITLES,
    UNIT_OPTIONS,
    _has_unit_suffix,
    _markup,
    _render_value,
    _seed,
    build_datasheet,
    row_label,
)
from ingest.synthetic_catalog import CATALOG, VENDORS
from ingest.units import standard_unit

PAGES = {SPEC: 2, IFACE: 3}
INTRO = {
    "en": "This catalog covers the {series} series. Select the model by rated values, then check the "
          "mechanical interface. Values below are per model; '—' means not specified.",
    "zh": "本目录收录 {series} 系列。先按额定值选型，再核对机械接口。下表数值按型号列出，“—”表示未规定。",
}
NOTES = {
    "en": ("Selection notes", "Use the rated values for continuous duty. Contact the (fictional) vendor for options."),
    "zh": ("选型说明", "连续工作按额定值选型。其他选项请联系（虚构的）厂商。"),
}


@dataclass
class Catalog:
    id: str
    category: str
    lang: str
    title: str
    series: str
    headers: tuple[str, str]
    sections: list[dict]  # [{page, title, rows: [[叫法, 单位, 各型号文字…]]}]
    models: list[str]
    answers: dict[str, dict]  # 型号 → 答案

    def render(self, path: Path) -> Path:
        return render_catalog_pdf(self, Path(path))


def build_catalog(category: str, variant: int = 0) -> Catalog:
    rows = CATALOG[category]
    rng = random.Random(_seed(category, "catalog", variant))
    lang = ("en", "zh")[(_seed(category, "catalog-lang") + variant) % 2]
    sheets = [build_datasheet(category, row, variant).answer for row in rows]
    models = [r["model"] for r in rows]
    unit_choice: dict[str, str] = {}
    sections: dict[str, list[list[str]]] = {SPEC: [], IFACE: []}
    printed: dict[str, dict] = {}  # 字段 key → 共用的叫法、单位、工况
    for field in FIELDS[category]:
        present = [r for r in rows if field.key in r]
        if not present:
            continue
        conds = {r[field.condition_key][lang] for r in present} if field.condition_key else {None}
        if len(conds) > 1:  # 各型号工况不同，无法共用一行
            continue
        unit = ""
        raw0 = present[0][field.key]
        if field.vocab is None and not isinstance(raw0, (str, bool, list)) and _has_unit_suffix(field):
            suffix, _ = standard_unit(field.unit_field)
            unit = rng.choice(field.units) if field.units is not None else \
                unit_choice.setdefault(suffix, rng.choice(UNIT_OPTIONS[suffix]))
        name = rng.choice(field.en if lang == "en" else field.zh)
        entry = {"name": name, "unit": unit, "condition": next(iter(conds))}
        label = row_label(entry, lang, "catalog")
        cells = [label, unit or "—"]
        texts = {}
        for r in rows:
            if field.key in r:
                texts[r["model"]] = _render_value(field, r[field.key], unit, lang, rng)
            cells.append(texts.get(r["model"], "—"))
        sections[field.section].append(cells)
        printed[field.key] = {**entry, "texts": texts, "row": cells, "page": PAGES[field.section]}

    series = rows[0]["model"].split("-")[0].rstrip("0123456789") or rows[0]["model"]
    cid = f"{category}-catalog.v{variant}"
    answers = {}
    for sheet in sheets:
        model = sheet["component"]["model"]
        ans = copy.deepcopy(sheet)
        fields = []
        for e in ans["fields"]:
            pr = printed.get(e["key"])
            if pr is None or model not in pr["texts"]:
                continue
            e.update(page=pr["page"], name=pr["name"], unit=pr["unit"], text=pr["texts"][model], row=pr["row"])
            if pr["condition"]:
                e["condition"] = pr["condition"]
            fields.append(e)
        ans.update(datasheet_id=f"{cid}/{model}", layout="catalog", lang=lang, fields=fields,
                   target_model=model, pages=sorted({e["page"] for e in fields}), catalog_id=cid)
        answers[model] = ans
    headers = HEADERS[lang][0]
    return Catalog(
        id=cid, category=category, lang=lang,
        title=f"{VENDORS[category]} {series} {TITLES[category][lang]}" + (" Catalog" if lang == "en" else "产品目录"),
        series=series, headers=(headers[0], headers[2]),
        sections=[{"page": PAGES[s], "title": rng.choice(SECTION_TITLES[s][lang]), "rows": sections[s]}
                  for s in (SPEC, IFACE)],
        models=models, answers=answers,
    )


def catalogs(variant: int = 0, categories: list[str] | None = None) -> list[Catalog]:
    return [build_catalog(c, variant) for c in CATALOG if not categories or c in categories]


def render_catalog_pdf(cat: Catalog, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    from ingest.synthetic import _fonts

    latin, _ = _fonts()
    body = ParagraphStyle("body", fontName=latin, fontSize=8, leading=10)
    title = ParagraphStyle("title", parent=body, fontSize=15, leading=20, spaceAfter=4)
    head = ParagraphStyle("head", parent=body, fontSize=11, leading=15, spaceBefore=8, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=colors.grey)

    def m(t):
        return Paragraph(_markup(t), body)

    story: list = [Paragraph(_markup(cat.title), title), Paragraph(_markup(DISCLAIMER[cat.lang]), small),
                   Spacer(1, 8), m(INTRO[cat.lang].format(series=cat.series))]
    widths = [190, 70] + [500 // len(cat.models)] * len(cat.models)
    for section in cat.sections:
        story += [PageBreak(), Paragraph(_markup(cat.title), title), Paragraph(_markup(DISCLAIMER[cat.lang]), small),
                  Paragraph(_markup(section["title"]), head)]
        rows = [[cat.headers[0], cat.headers[1], *cat.models], *section["rows"]]
        table = Table([[m(c) for c in r] for r in rows], colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story += [Spacer(1, 4), table]
    note_title, note = NOTES[cat.lang]
    story += [PageBreak(), Paragraph(_markup(note_title), head), m(note)]

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=40, rightMargin=40, topMargin=40,
                            bottomMargin=40, title=cat.title, author="freecad-ai-parts synthetic generator",
                            invariant=True)
    doc.build(story)
    return path
