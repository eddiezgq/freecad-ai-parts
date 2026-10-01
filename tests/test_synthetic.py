"""模拟规格书生成器（issue #27）的测试。"""

from __future__ import annotations

import json
import os
import re
from collections import Counter

import pytest

from ingest.synthetic import (
    FIELDS,
    UNIT_OPTIONS,
    VOCAB,
    FontMissing,
    datasheets,
    find_font,
    main,
    row_label,
)
from ingest.synthetic_catalog import CATALOG
from ingest.units import to_standard
from kb.sources import SourceRegistry
from kb.store import check_component

V1_CATEGORIES = ("servo_motor", "reducer", "drive", "bearing")
SHEETS = datasheets(0) + datasheets(1) + datasheets(2)


def _get(comp: dict, path: str) -> dict:
    head, *rest = path.split("/")
    if head == "params":
        return comp["params"][rest[0]]
    if head == "ports":
        return next(p for p in comp["ports"] if p["id"] == rest[0])["spec"][rest[1]]
    return comp["envelope"]["parts"][int(rest[0])][rest[1]]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def test_at_least_five_per_category():
    counts = Counter(s.answer["category"] for s in datasheets(0))
    for cat in V1_CATEGORIES:
        assert counts[cat] >= 5, cat


def test_ids_unique_and_fictional():
    ids = [s.answer["component_id"] for s in datasheets(0)]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("test.") for i in ids)


def test_both_languages_in_every_category():
    for cat in V1_CATEGORIES:
        langs = {s.answer["lang"] for s in datasheets(0) if s.answer["category"] == cat}
        assert langs == {"en", "zh"}, cat


def test_generation_is_deterministic():
    a = [s.answer for s in datasheets(1)]
    b = [s.answer for s in datasheets(1)]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_variants_differ():
    v0 = {s.id.rsplit(".", 1)[0]: s.answer for s in datasheets(0)}
    v1 = {s.id.rsplit(".", 1)[0]: s.answer for s in datasheets(1)}
    assert v0.keys() == v1.keys()
    assert any(v0[k]["lang"] != v1[k]["lang"] for k in v0)
    assert any(v0[k]["fields"] != v1[k]["fields"] for k in v0)


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda s: s.id)
def test_answer_component_passes_import_checks(sheet):
    reasons = check_component(sheet.answer["component"], SourceRegistry.load(), allow_test=True)
    assert reasons == []


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda s: s.id)
def test_answer_matches_component(sheet):
    """答案里每一行的期望值、页码、工况都与组件一致。"""
    ans = sheet.answer
    comp = ans["component"]
    for e in ans["fields"]:
        for path in e["paths"]:
            pv = _get(comp, path)
            for k, v in e["expected"].items():
                assert pv[k] == v, (path, k)
            assert pv["source"]["page"] == e["page"]
            assert pv.get("condition") == e.get("condition")
    for path in ans["implicit"]:
        _get(comp, path)


@pytest.mark.parametrize("category", V1_CATEGORIES)
def test_answer_covers_catalog_row(category):
    """目录中写了的每个字段都印在规格书上；没写的字段组件里也没有（不编造）。"""
    for i, sheet in enumerate(s for s in datasheets(0) if s.answer["category"] == category):
        row = CATALOG[category][i]
        printed = {e["key"] for e in sheet.answer["fields"]}
        assert printed == {f.key for f in FIELDS[category] if f.key in row}
        comp_paths = set()
        comp = sheet.answer["component"]
        comp_paths |= {f"params/{k}" for k in comp["params"]}
        for p in comp["ports"]:
            comp_paths |= {f"ports/{p['id']}/{k}" for k in p["spec"]}
        for n, part in enumerate(comp["envelope"]["parts"]):
            comp_paths |= {f"envelope/{n}/{k}" for k in part if k.endswith("_mm") and k != "z_start_mm"}
        answered = {p for e in sheet.answer["fields"] for p in e["paths"]} | set(sheet.answer["implicit"])
        assert comp_paths == answered


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda s: s.id)
def test_rendered_numbers_convert_back(sheet):
    """印出的数值按印出的单位换算回标准单位，与期望值相差不超过 0.1%。"""
    for e in sheet.answer["fields"]:
        if not e["unit"] and not e["key"].endswith("_ratio"):
            continue
        field = e["paths"][0].rsplit("/", 1)[-1]
        texts = re.split(r"–| ~ ", e["text"])
        keys = ["min", "max"] if "min" in e["expected"] else ["value"]
        assert len(texts) == len(keys), e
        for k, t in zip(keys, texts, strict=True):
            got = to_standard(float(t), e["unit"], field)
            want = e["expected"][k]
            assert got == pytest.approx(want, rel=1e-3), (e["key"], t, e["unit"])


@pytest.mark.parametrize("sheet", SHEETS, ids=lambda s: s.id)
def test_rendered_enums_use_known_variants(sheet):
    lang = sheet.answer["lang"]
    fields = {f.key: f for f in FIELDS[sheet.answer["category"]]}
    for e in sheet.answer["fields"]:
        vocab = fields[e["key"]].vocab
        if vocab in (None, "ratio"):
            continue
        expected = e["expected"]["value"]
        items = expected if isinstance(expected, list) else [expected]
        parts = re.split(r", | / ", e["text"]) if isinstance(expected, list) else [e["text"]]
        assert len(parts) == len(items)
        for text, item in zip(parts, items, strict=True):
            assert text in VOCAB[vocab][item][lang]


def test_unit_options_are_convertible():
    from ingest.units import SUFFIX_UNITS

    assert set(UNIT_OPTIONS) <= set(SUFFIX_UNITS)
    for suffix, units in UNIT_OPTIONS.items():
        for u in units:
            to_standard(1.0, u, f"x{suffix}")


def test_unit_variety_across_sheets():
    """单位写法确实在变：每类量在全部规格书中至少出现两种写法（只有一种标准写法的除外）。"""
    seen: dict[str, set[str]] = {}
    for s in SHEETS:
        for e in s.answer["fields"]:
            if e["unit"]:
                seen.setdefault(e["key"], set()).add(e["unit"])
    for key in ("rated_torque_nm", "rotor_inertia_kgm2", "max_speed_rpm", "peak_current_a", "mass_kg"):
        assert len(seen[key]) >= 2, key


# ---------------------------------------------------------------- PDF


def _font_or_skip():
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")


@pytest.mark.parametrize("sheet", datasheets(0) + datasheets(1), ids=lambda s: s.id)
def test_pdf_round_trip(sheet, tmp_path):
    """PDF 中每一行（叫法、数值、单位）都在答案标注的那一页上，单位符号不丢字。"""
    pdfplumber = pytest.importorskip("pdfplumber")
    _font_or_skip()
    pdf_path = sheet.render(tmp_path / f"{sheet.id}.pdf")
    ans = sheet.answer
    with pdfplumber.open(pdf_path) as pdf:
        assert len(pdf.pages) == len(ans["sections"])
        tables = {}
        for n, page in enumerate(pdf.pages, start=1):
            found = page.extract_tables()
            assert len(found) == 1, f"第 {n} 页应恰有一张表"
            tables[n] = [[_squash(c) for c in r] for r in found[0][1:]]
            assert _squash(ans["title"]) in _squash(page.extract_text())
    for e in ans["fields"]:
        row = [_squash(row_label(e, ans["lang"], ans["layout"])), _squash(e["text"])]
        if ans["layout"] == "three_col":
            row.append(_squash(e["unit"] or "—"))
        assert row in tables[e["page"]], (e["key"], row)
    assert sum(len(t) for t in tables.values()) == len(ans["fields"])


def test_pdf_is_reproducible(tmp_path):
    _font_or_skip()
    sheet = datasheets(0)[0]
    a = sheet.render(tmp_path / "a.pdf").read_bytes()
    b = sheet.render(tmp_path / "b.pdf").read_bytes()
    assert a == b


def test_cli_writes_pdf_and_answer(tmp_path):
    _font_or_skip()
    assert main(["--out", str(tmp_path), "--variants", "1"]) == 0
    pdfs = sorted(tmp_path.glob("*.pdf"))
    answers = sorted(tmp_path.glob("*.answer.json"))
    assert len(pdfs) == len(answers) == len(datasheets(0))
    data = json.loads(answers[0].read_text(encoding="utf-8"))
    assert data["format"] == "synthetic-answer/1"
