"""PDF 文本与表格提取（issue #28）的测试。"""

from __future__ import annotations

import json
import os

import pytest

from ingest.pdf_extract import ExtractError, clean_cell, extract, main
from ingest.synthetic import FontMissing, datasheets, find_font, row_label

pytest.importorskip("pdfplumber")


def _need_render():
    pytest.importorskip("reportlab")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        (None, None),
        ("", ""),
        ("  \n ", ""),
        ("Rated torque", "Rated torque"),
        ("Rated torque (at input\nspeed 2000 rpm)", "Rated torque (at input speed 2000 rpm)"),
        ("额定扭矩（输入转\n速 2000 r/min 时）", "额定扭矩（输入转速 2000 r/min 时）"),
        ("额定扭矩（输入转速\n2000 r/min 时）", "额定扭矩（输入转速 2000 r/min 时）"),
        ("×10⁻⁴\nkg·m²", "×10⁻⁴ kg·m²"),
        ("a \t b", "a b"),
    ],
)
def test_clean_cell(raw, want):
    assert clean_cell(raw) == want


@pytest.mark.parametrize("sheet", datasheets(0) + datasheets(1), ids=lambda s: s.id)
def test_synthetic_tables_fully_extracted(sheet, tmp_path):
    """验收：模拟规格书的表格全部提取（逐行原文一致），页码正确。"""
    _need_render()
    ans = sheet.answer
    doc = extract(sheet.render(tmp_path / "sheet.pdf"))
    assert [p.page for p in doc.pages] == list(range(1, len(ans["sections"]) + 1))
    for page in doc.pages:
        assert len(page.tables) == 1
        assert all(t.page == page.page for t in page.tables)
        assert page.tables[0].rows[0] == ans["headers"][: len(page.tables[0].rows[0])]
    for e in ans["fields"]:
        row = [row_label(e, ans["lang"], ans["layout"]), e["text"]]
        if ans["layout"] == "three_col":
            row.append(e["unit"] or "—")
        hits = [t.page for t in doc.tables if row in t.rows]
        assert hits == [e["page"]], (e["key"], row)
    assert sum(len(t.rows) - 1 for t in doc.tables) == len(ans["fields"])
    assert ans["title"] in doc.pages[0].text


def test_wrapped_cells_are_rejoined(tmp_path):
    """窄列中折行的中英文单元格合并后与原文一致。"""
    _need_render()
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    from ingest.synthetic import _fonts, _markup

    latin, _ = _fonts()
    style = ParagraphStyle("s", fontName=latin, fontSize=9, leading=11)
    cells = [
        "Rated torque at input speed 2000 rpm and 25 °C",
        "额定扭矩（输入转速 2000 r/min、环境温度 25 °C 时）",
        "×10⁻⁴ kg·m²",
    ]
    table = Table([[Paragraph(_markup(c), style)] for c in cells], colWidths=[70])
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    path = tmp_path / "wrap.pdf"
    SimpleDocTemplate(str(path)).build([table])
    rows = extract(path).tables[0].rows
    assert [r[0] for r in rows] == cells


def test_document_metadata_and_prompt(tmp_path):
    _need_render()
    sheet = datasheets(0)[0]
    path = sheet.render(tmp_path / "s.pdf")
    a, b = extract(path), extract(path)
    assert a == b
    assert len(a.sha256) == 64
    data = json.loads(json.dumps(a.to_dict(), ensure_ascii=False))
    assert data["pages"][0]["tables"][0]["page"] == 1
    prompt = a.to_prompt_text()
    assert "=== 第 1 页 / page 1 ===" in prompt
    assert "=== 第 2 页 / page 2 ===" in prompt
    first = sheet.answer["fields"][0]
    assert first["text"] in prompt


def test_page_without_table(tmp_path):
    _need_render()
    from reportlab.pdfgen import canvas

    path = tmp_path / "plain.pdf"
    c = canvas.Canvas(str(path))
    c.drawString(72, 720, "Notes only")
    c.showPage()
    c.showPage()  # 空白页
    c.save()
    doc = extract(path)
    assert [(p.page, p.text, p.tables) for p in doc.pages] == [(1, "Notes only", []), (2, "", [])]


def test_rejects_non_pdf(tmp_path):
    bad = tmp_path / "x.pdf"
    bad.write_text("not a pdf", encoding="utf-8")
    with pytest.raises(ExtractError):
        extract(bad)
    with pytest.raises(ExtractError):
        extract(tmp_path / "missing.pdf")


def test_rejects_truncated_pdf(tmp_path):
    bad = tmp_path / "t.pdf"
    bad.write_bytes(b"%PDF-1.4\n1 0 obj\n<<")
    with pytest.raises(ExtractError):
        extract(bad)


def test_cli(tmp_path, capsys):
    _need_render()
    path = datasheets(0)[0].render(tmp_path / "s.pdf")
    assert main([str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["pages"][0]["page"] == 1
    assert main([str(path), "--format", "prompt"]) == 0
    assert "page 1" in capsys.readouterr().out
    assert main([str(tmp_path / "none.pdf")]) == 1
