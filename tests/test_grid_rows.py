"""无边框、按行列出型号的表（轴承目录式）：按词的横坐标对齐成列再核对（ADR-0099 41.6）。虚构数据。"""

from __future__ import annotations

import pytest

from ingest.llm_extract import verify
from ingest.pdf_extract import extract

DOC = "src-test-grid"
# 列的横坐标（左对齐）：内径 d、外径 D、宽 B、倒角 r、Cr（千位窄空格）、C0r、型号、质量
X = [40, 75, 95, 110, 140, 180, 250, 300]
HEAD = [["", "(mm)", "", "", "Basic Load Ratings (N)", "", "Bearing", "Mass"],
        ["d", "D", "B", "r min.", "C r", "C 0r", "Numbers", "(kg)"]]
ROWS = [["10", "26", "8", "0.3", "5 050", "1 970", "9000", "0.018"],
        ["", "30", "9", "0.6", "5 600", "2 390", "9200", "0.032"],
        ["12", "28", "8", "0.3", "5 600", "2 370", "9001", "0.022"],
        ["", "32", "10", "0.6", "7 500", "3 050", "9201", "0.037"]]


def _draw(c, x, y, text):
    if " " in text and text.replace(" ", "").isdigit():       # 千位用窄空格：两段分开印、间隔约 2 pt
        a, b = text.split(" ")
        c.drawString(x, y, a)
        c.drawString(x + c.stringWidth(a, "Helvetica", 9) + 2.2, y, b)
    else:
        c.drawString(x, y, text)


@pytest.fixture(scope="module")
def doc(tmp_path_factory):
    from reportlab.pdfgen import canvas

    p = tmp_path_factory.mktemp("g") / "cat.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 9)
    c.drawString(40, 760, "SINGLE-ROW TEST BALL BEARINGS (fictional)")
    y = 720
    for row in HEAD:
        for x, t in zip(X, row, strict=True):
            if t:
                _draw(c, x, y, t)
        y -= 10
    y -= 6
    for row in ROWS:
        for x, t in zip(X, row, strict=True):
            if t:
                _draw(c, x, y, t)
        y -= 12
    c.save()
    return extract(p)


def test_grid_rows(doc):
    rows = doc.pages[0].grid_rows
    data = [r for r in rows if r[0][:1].isdigit()]
    assert data[1][:6] == ["10", "30", "9", "0.6", "5 600", "2 390"]            # 内径跨行，补上
    assert data[3][4] == "7 500" and data[3][6] == "9201"
    head = rows[0]
    assert "C r" in head[4] and "0r" in head[5] and head[1] == "(mm) D"
    assert "(N)" in head[4] and "(N)" in head[5]          # 跨两列的表头归到两列


def test_group_header_between_two_columns(tmp_path):
    """“da”印在 min、max 两列之间（不压在任一列上）：归到左右两列"""
    from reportlab.pdfgen import canvas

    p = tmp_path / "da.pdf"
    c = canvas.Canvas(str(p))
    c.setFont("Helvetica", 9)
    c.drawString(118, 730, "da")
    for x, t in ((40, "Model"), (100, "min."), (140, "max.")):
        c.drawString(x, 718, t)
    for y, row in ((700, ("9201", "16", "17")), (688, ("9202", "19", "20.5"))):
        for x, t in zip((40, 100, 140), row, strict=True):
            c.drawString(x, y, t)
    for y in (676, 664, 652):
        for x, t in zip((40, 100, 140, 180, 220, 260), ("9300", "21", "23", "1", "2", "3"), strict=True):
            c.drawString(x, y, t)
    c.save()
    rows = extract(p).pages[0].grid_rows
    head = rows[0]
    assert "da" in head[1] and "min." in head[1] and "da" in head[2] and "max." in head[2] and "da" not in head[0]


def _p(target, text, value, label, unit):
    return {"target": target, "printed_text": text, "printed_unit": unit, "printed_label": label, "page": 1,
            "quote": "32 10 0.6 7 500 3 050 9201 0.037", "confidence": 0.9, "value": value}


def test_values_in_target_row_and_column_pass(doc):
    r = verify({"items": [_p("params/dynamic_load_rating_n", "7 500", 7500, "C r", "N"),
                          _p("params/width_mm", "10", 10, "B", "mm"),
                          _p("ports/outer/diameter_mm", "32", 32, "D", "mm")]},
               doc, "bearing", DOC, target_model="9201")
    got = {i["target"]: i["value"]["value"] for i in r["items"]}
    assert got == {"params/dynamic_load_rating_n": 7500, "params/width_mm": 10, "ports/outer/diameter_mm": 32}, r["rejected"]


@pytest.mark.parametrize("text,value,label,unit", [
    ("5 600", 5600, "C r", "N"),          # 另一个型号那一行的值
    ("3 050", 3050, "C r", "N"),          # 同一行、别的列（C0r）
])
def test_wrong_row_or_column_rejected(doc, text, value, label, unit):
    r = verify({"items": [_p("params/dynamic_load_rating_n", text, value, label, unit)]}, doc, "bearing", DOC,
               target_model="9201")
    assert not r["items"]


def test_heading_names_the_kind(doc):
    p = {"target": "params/bearing_kind", "printed_text": "SINGLE-ROW TEST BALL BEARINGS", "printed_unit": "",
         "printed_label": "SINGLE-ROW TEST BALL BEARINGS", "quote": "SINGLE-ROW TEST BALL BEARINGS (fictional)",
         "page": 1, "confidence": 0.8, "value": "deep_groove"}
    r = verify({"items": [p]}, doc, "bearing", DOC, target_model="9201")
    assert r["items"] and "枚举映射" in " ".join(r["items"][0].get("issues", []))


def test_bore_from_first_row_of_group(doc):
    """内径只印在同内径的第一行：引用第一行（另一型号）也算，因为目标型号那一行（补上内径后）同一列是同一个数"""
    p = {"target": "ports/inner/diameter_mm", "printed_text": "12", "printed_unit": "mm", "printed_label": "d", "page": 1,
         "quote": "12 28 8 0.3 5 600 2 370 9001 0.022", "confidence": 0.9, "value": 12}
    assert verify({"items": [p]}, doc, "bearing", DOC, target_model="9201")["items"]
    wrong = dict(p, printed_text="10", value=10, quote="10 26 8 0.3 5 050 1 970 9000 0.018")
    assert not verify({"items": [wrong]}, doc, "bearing", DOC, target_model="9201")["items"]


def test_confirmation_from_same_source_other_doc(monkeypatch):
    """人工确认可以引用同一来源登记的另一份资料（如目录 Part A 的精度等级说明）；别的来源的资料不收"""
    from ingest import crosscheck as C

    assert C._same_source("src-nsk-e1103c-part-c", "src-nsk-e1103c-part-a")
    assert not C._same_source("src-nsk-e1103c-part-c", "src-hd-csg-csf-gear-units")
