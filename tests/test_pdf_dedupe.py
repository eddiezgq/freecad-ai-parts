"""“加粗”印法的 PDF：同一个字在几乎同一位置印两遍，文字层每个字重复（NSK 目录，ADR-0099 41.6）。"""

from __future__ import annotations

from ingest.pdf_extract import extract


def _pdf(path, doubled: bool):
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    for dx in ((0, 0.3) if doubled else (0,)):
        c.drawString(72 + dx, 700, "6201 ZZ 32 10 0.6 7 500 3 050")
    c.save()
    return path


def test_doubled_text_is_deduplicated(tmp_path):
    doc = extract(_pdf(tmp_path / "bold.pdf", True))
    assert "6201 ZZ 32 10 0.6 7 500 3 050" in doc.pages[0].text
    assert "66220011" not in doc.pages[0].text


def test_plain_text_unchanged(tmp_path):
    doc = extract(_pdf(tmp_path / "plain.pdf", False))
    assert doc.pages[0].text == "6201 ZZ 32 10 0.6 7 500 3 050"
