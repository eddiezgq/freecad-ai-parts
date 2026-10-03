"""多型号目录抽取（ADR-0040，issue #125）：页码范围、目标型号与型号列核对。不联网，只用模拟响应。"""

from __future__ import annotations

import copy
import os

import pytest

from ingest.evaluate import score
from ingest.llm_extract import build_request, extract_document, request_key, verify
from ingest.llm_simulate import SimulatedClient, proposals_from_answer, simulated_response
from ingest.pdf_extract import Document, ExtractError, Page, Table, parse_pages
from ingest.synthetic import FontMissing, find_font
from ingest.synthetic_multi import build_catalog, catalogs

DOC_ID = "src-test-fixture"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    from ingest.pdf_extract import extract

    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    d = tmp_path_factory.mktemp("catalogs")
    return [(c, extract(c.render(d / f"{c.id}.pdf"))) for v in (0, 1) for c in catalogs(v)]


def _run(cat, doc, model, answer=None, proposals=None):
    answer = answer or cat.answers[model]
    client = SimulatedClient(simulated_response(answer, proposals))
    return extract_document(doc, cat.category, DOC_ID, client, pages=answer["pages"], target_model=model)


# ---------------------------------------------------------------- 目录与答案


def test_catalog_is_deterministic_and_complete():
    for cat in catalogs(0) + catalogs(1):
        assert build_catalog(cat.category, int(cat.id[-1])) == cat
        assert set(cat.answers) == set(cat.models) and len(cat.models) >= 5
        for model, ans in cat.answers.items():
            assert ans["target_model"] == model and ans["component"]["model"] == model
            assert set(ans["pages"]) <= {2, 3} and ans["fields"]
            for e in ans["fields"]:
                assert e["row"][2 + cat.models.index(model)] == e["text"]  # 印在本型号那一列


def test_both_languages_used():
    assert {c.lang for c in catalogs(0) + catalogs(1)} == {"en", "zh"}


# ---------------------------------------------------------------- 抽取


def test_perfect_simulated_extraction_every_model(rendered):
    for cat, doc in rendered:
        assert len(doc.pages) == 4
        for model in cat.models:
            result = _run(cat, doc, model)
            assert result["rejected"] == [], (cat.id, model, result["rejected"])
            assert result["model"] == model and result["extractor"]["simulated"] is True
            assert all(r["outcome"] == "correct" for r in score(cat.answers[model], result).values())
            assert result["document"]["pages"] == len(cat.answers[model]["pages"])
            # 已确认在型号列中，不再提示“须核对型号列”
            assert not any("型号列" in i for it in result["items"] for i in it.get("issues", []))


def test_value_from_another_model_column_rejected(rendered):
    cat, doc = rendered[0]
    a, b = cat.models[0], cat.models[1]
    # 目标是型号 a，但每一项都报型号 b 的值（换上 b 的答案）
    wrong = proposals_from_answer(cat.answers[b])
    a_text = {t: e["text"] for e in cat.answers[a]["fields"] for t in e["paths"]}
    differs = {p["target"] for p in wrong if a_text.get(p["target"]) not in (None, p["printed_text"])}
    result = _run(cat, doc, a, proposals=wrong)
    got = {i["target"] for i in result["items"]}
    assert differs and not (differs & got)
    assert any(r["reason"] == "数值不在目标型号所在的列" for r in result["rejected"])


def test_pages_outside_selection_rejected(rendered):
    cat, doc = rendered[0]
    model = cat.models[0]
    ans = copy.deepcopy(cat.answers[model])
    ans["pages"] = [2]  # 只给规格页：接口页上的项应因页码不存在被拒
    result = _run(cat, doc, model, answer=ans)
    iface = [e for e in cat.answers[model]["fields"] if e["page"] == 3]
    assert iface and sum("页码" in r["reason"] for r in result["rejected"]) >= len(iface)


def test_reported_model_differs_from_target(rendered):
    cat, doc = rendered[0]
    a, b = cat.models[0], cat.models[1]
    resp = simulated_response(cat.answers[a])
    resp["tool_input"]["model"] = b
    result = extract_document(doc, cat.category, DOC_ID, SimulatedClient(resp), pages=[2, 3], target_model=a)
    assert result["model"] == a
    assert any(r["target"] == "model" and a in r["reason"] for r in result["rejected"])


# ---------------------------------------------------------------- 型号列核对（纯函数）


def _table_doc():
    rows = [["Item", "Unit", "M-1", "M-2"], ["Rated torque", "N·m", "1.3", "2.4"], ["Model", "", "", ""]]
    return Document("x", "0" * 64, [Page(1, "", [Table(1, 0, rows, (0, 0, 1, 1))])])


def _p(text, value):
    return {"target": "params/rated_torque_nm", "printed_text": text, "printed_unit": "N·m",
            "printed_label": "Rated torque", "quote": "Rated torque N·m 1.3 2.4", "page": 1,
            "confidence": 0.9, "value": value}


def test_model_column_check():
    doc = _table_doc()
    ok = verify({"items": [_p("2.4", 2.4)]}, doc, "servo_motor", DOC_ID, target_model="M-2")
    assert ok["items"][0]["value"]["value"] == 2.4 and ok["model"] == "M-2"
    bad = verify({"items": [_p("1.3", 1.3)]}, doc, "servo_motor", DOC_ID, target_model="M-2")
    assert bad["items"] == [] and bad["rejected"][0]["reason"] == "数值不在目标型号所在的列"
    # 没有目标型号时（单型号规格书）行为不变：接受，但提示核对型号列
    plain = verify({"items": [_p("1.3", 1.3)]}, doc, "servo_motor", DOC_ID)
    assert any("型号列" in i for i in plain["items"][0]["issues"])


def test_row_per_model_layout():
    rows = [["Model", "Rated torque (N·m)"], ["M-1", "1.3"], ["M-2", "2.4"]]
    doc = Document("x", "0" * 64, [Page(1, "", [Table(1, 0, rows, (0, 0, 1, 1))])])
    p = {"target": "params/rated_torque_nm", "printed_text": "2.4", "printed_unit": "N·m", "printed_label": "Rated torque",
         "quote": "M-2 2.4", "page": 1, "confidence": 0.9, "value": 2.4}
    assert verify({"items": [p]}, doc, "servo_motor", DOC_ID, target_model="M-2")["items"]


def test_target_model_must_be_printed():
    r = verify({"items": []}, _table_doc(), "servo_motor", DOC_ID, target_model="M-9")
    assert "model" not in r and any(x["target"] == "model" for x in r["rejected"])


# ---------------------------------------------------------------- 请求、页码与命令行


def test_request_unchanged_without_target():
    doc = _table_doc()
    plain = build_request(doc, "servo_motor")
    assert build_request(doc, "servo_motor", target_model=None, excerpt=False) == plain
    targeted = build_request(doc, "servo_motor", target_model="M-2", excerpt=True)
    assert "目标型号：M-2" in targeted["user"] and "第 1 页" in targeted["user"]
    assert request_key(targeted) != request_key(plain)


@pytest.mark.parametrize(("spec", "want"), [("2-5,8", [2, 3, 4, 5, 8]), ("3", [3]), (" 4–5，1 ", [1, 4, 5])])
def test_parse_pages(spec, want):
    assert parse_pages(spec) == want


@pytest.mark.parametrize("spec", ["", "0", "5-2", "a", "1-"])
def test_parse_pages_rejects(spec):
    with pytest.raises(ValueError):
        parse_pages(spec)


def test_select_out_of_range():
    with pytest.raises(ExtractError):
        _table_doc().select([2])
    assert [p.page for p in _table_doc().select([1]).pages] == [1]


def test_blank_target_rejected():
    with pytest.raises(ValueError):
        extract_document(_table_doc(), "servo_motor", DOC_ID, SimulatedClient({"tool_input": {}}), target_model=" ")


def test_cli_pages_and_target(rendered, tmp_path, monkeypatch):
    from ingest import llm_extract as lx

    cat, _ = rendered[0]
    model = cat.models[0]
    pdf = cat.render(tmp_path / "c.pdf")
    seen = {}

    def fake(document, category, doc_id, client, **kw):
        seen.update(kw, pages_in=[p.page for p in document.pages])
        return {"ok": True}

    monkeypatch.setattr(lx, "extract_document", fake)
    assert lx.main([str(pdf), "--category", cat.category, "--doc", DOC_ID, "--pages", "2-3",
                    "--target", model, "--out", str(tmp_path / "o.json")]) == 0
    assert seen["pages"] == [2, 3] and seen["target_model"] == model


def test_split_model_header_on_second_row():
    """安川式表头：第一行是电压，第二行“型号 SGM7J-”后面各列是型号后缀。"""
    rows = [["Voltage", "", "200 V", ""], ["Model SGM7J-", "", "A5A", "02A"], ["Rated torque", "N·m", "0.159", "0.637"]]
    doc = Document("x", "0" * 64, [Page(1, "", [Table(1, 0, rows, (0, 0, 1, 1))])])

    def p(text, value):
        return {"target": "params/rated_torque_nm", "printed_text": text, "printed_unit": "N·m",
                "printed_label": "Rated torque", "quote": "Rated torque N·m 0.159 0.637", "page": 1,
                "confidence": 0.9, "value": value}

    ok = verify({"items": [p("0.637", 0.637)]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-02A")
    assert ok["items"] and not any("型号列" in i for i in ok["items"][0].get("issues", []))
    bad = verify({"items": [p("0.159", 0.159)]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-02A")
    assert bad["items"] == [] and bad["rejected"][0]["reason"] == "数值不在目标型号所在的列"
    # 后缀相同但前缀不同的型号不算匹配
    other = verify({"items": [p("0.637", 0.637)]}, doc, "servo_motor", DOC_ID, target_model="SGM7A-02A")
    assert other["items"] and any("型号列" in i for i in other["items"][0]["issues"])


def _hd_doc():
    """Harmonic Drive 式的表：按尺寸、减速比分行（尺寸纵向合并）；按尺寸分列（Mass 跨 CSG、CSF 两行）。"""
    rated = [["CSF-2UH Size", "Ratio", "Rated Torque at 2000rpm", None, "Moment of Inertia", None],
             [None, None, "Nm", "kgfm", "I×10−4kgm2", "J×10−5kgfms2"],
             ["14", "30", "4.0", "0.41", "0.033", "0.034"],
             [None, "50", "5.4", "0.55", "0.033", "0.034"],
             ["17", "50", "16", "1.6", "0.079", "0.081"]]
    dims = [["Size Symbol", None, "14", "17"], ["φA", None, "73", "79"], ["B*", None, "41", "45"],
            ["Mass (kg)", "CSG Series", "0.52", "0.68"], [None, "CSF Series", "0.50", "0.66"]]
    return Document("x", "0" * 64, [Page(1, "", [Table(1, 0, rated, (0, 0, 1, 1))]),
                                    Page(2, "", [Table(2, 0, dims, (0, 0, 1, 1))])])


def _hd(target, text, value, label, quote, unit, page=1):
    p = {"target": target, "printed_text": text, "printed_unit": unit, "printed_label": label, "quote": quote,
         "page": page, "confidence": 0.9, "value": value}
    if target == "params/rated_torque_nm":
        p["condition"] = "2000rpm"
    return p


def test_size_ratio_rows_and_merged_cells():
    doc = _hd_doc()
    ok = verify({"items": [_hd("params/rated_torque_nm", "5.4", 5.4, "Rated Torque", "14 50 5.4 0.55", "Nm")]},
                doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")
    assert ok["items"] and ok["items"][0]["value"]["value"] == 5.4
    # 同一尺寸、另一个减速比的行：拒收
    bad = verify({"items": [_hd("params/rated_torque_nm", "4.0", 4.0, "Rated Torque", "14 30 4.0 0.41", "Nm")]},
                 doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")
    assert bad["items"] == [] and bad["rejected"][0]["reason"] == "数值不在目标型号所在的列"
    # 叫法在表头：数值须在叫法所在的列（0.033 在 Moment of Inertia 下；0.55 在 Rated Torque 下）
    inertia = _hd("params/input_inertia_kgm2", "0.033", 0.033, "Moment of Inertia", "14 50 5.4 0.55 0.033 0.034",
                  "×10−4kgm2")
    got = verify({"items": [inertia]}, doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")
    assert got["items"] and got["items"][0]["value"]["value"] == pytest.approx(0.033e-4)
    wrong = dict(inertia, printed_text="0.55", value=0.55)
    got = verify({"items": [wrong]}, doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")
    assert got["items"] == []


def test_size_columns_and_series_rows():
    doc = _hd_doc()
    mass = _hd("params/mass_kg", "0.50", 0.5, "Mass", "Mass (kg) CSF Series 0.50 0.66", "kg", page=2)
    ok = verify({"items": [mass]}, doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")
    assert ok["items"] and ok["items"][0]["value"]["value"] == 0.5
    other_size = verify({"items": [dict(mass, printed_text="0.66", value=0.66)]}, doc, "reducer", DOC_ID,
                        target_model="CSF-14-50-2UH")
    assert other_size["items"] == []
    csg = _hd("params/mass_kg", "0.52", 0.52, "Mass", "Mass (kg) CSG Series 0.52 0.68", "kg", page=2)
    assert verify({"items": [csg]}, doc, "reducer", DOC_ID, target_model="CSF-14-50-2UH")["items"] == []


def _yaskawa_text_doc():
    """安川式额定值页：表格只截到一部分（缺最后一列、缺叫法列），完整的数值在正文行里，带脚注标记 *1。"""
    lines = ["Voltage 200 V", "Model SGM7J- A5A 01A C2A 02A 04A",
             "Rated Output∗1 W 50 100 150 200 400", "Rated Torque*1, *2 Nm 0.159 0.318 0.477 0.637 1.27",
             "Rated Motor Speed*1 min-1 3000", "Rated Current*1 Arms 0.55 0.85 1.6 1.6"]
    text = "\n".join(lines)
    rows = [["Voltage", None, None, "200V", None], ["ModelSGM7J-", None, None, "A5A", "01A"],
            [None, None, "W", "50", "100"]]
    return Document("x", "0" * 64, [Page(1, text, [Table(1, 0, rows, (0, 0, 1, 1))])])


def _yk(target, text, value, label, quote, unit):
    return {"target": target, "printed_text": text, "printed_unit": unit, "printed_label": label, "quote": quote,
            "page": 1, "confidence": 0.9, "value": value}


def test_catalog_text_rows_by_model_column():
    doc = _yaskawa_text_doc()
    power = _yk("params/rated_power_w", "400", 400, "Rated Output", "Rated Output*1 W 50 100 150 200 400", "W")
    ok = verify({"items": [power]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-04A")
    assert ok["items"] and ok["items"][0]["value"]["value"] == 400 and ok["model"] == "SGM7J-04A"
    bad = verify({"items": [dict(power, printed_text="200", value=200)]}, doc, "servo_motor", DOC_ID,
                 target_model="SGM7J-04A")
    assert bad["items"] == [] and bad["rejected"][0]["reason"] == "数值不在目标型号所在的列"
    # 合并单元格：整行一个数，各型号共用，并注明
    speed = _yk("params/rated_speed_rpm", "3000", 3000, "Rated Motor Speed", "Rated Motor Speed*1 min-1 3000", "min-1")
    got = verify({"items": [speed]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-02A")
    assert got["items"] and any("共用" in i for i in got["items"][0]["issues"])
    # 数值个数与型号列数对不上（少了一列）：拒收，不猜
    cur = _yk("ports/power_in/rated_current_a", "1.6", 1.6, "Rated Current", "Rated Current*1 Arms 0.55 0.85 1.6 1.6",
              "Arms")
    got = verify({"items": [cur]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-C2A")
    assert got["items"] == [] and "对不上" in got["rejected"][0]["reason"]


def test_dimension_rows_identified_by_code_line():
    """安川式外形尺寸表：表格行的型号格是空的，型号代码印在表格外的同内容正文行里（A5AA2 37.9 25 …）。"""
    rows = [["ModelSGM7J-", "L*", "LL*", "LM", "Flange Dimensions", None, None],
            [None, None, None, None, "LR", "LC", "LB"],
            [None, "81.5(122)", "56.5(97)", "37.9", "25", "40", "30 0 -0.021"],
            [None, "93.5(134)", "68.5(109)", "49.9", "25", "40", "30 0 -0.021"]]
    text = "Unit: mm\nA5AA2 37.9 25 40 30 0 -0.021\n01AA2 49.9 25 40 30 0 -0.021"
    doc = Document("x", "0" * 64, [Page(1, text, [Table(1, 0, rows, (0, 0, 1, 1))])])
    lm = {"target": "dims/body_length_mm", "printed_text": "49.9", "printed_unit": "mm", "printed_label": "LM",
          "quote": "93.5(134) 68.5(109) 49.9 25 40", "page": 1, "confidence": 0.9, "value": 49.9}
    got = verify({"items": [lm]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-01A")
    assert got["items"] and got["items"][0]["value"]["value"] == 49.9
    other = verify({"items": [lm]}, doc, "servo_motor", DOC_ID, target_model="SGM7J-A5A")
    assert other["items"] == [] and other["rejected"][0]["reason"] == "数值不在目标型号所在的列"
