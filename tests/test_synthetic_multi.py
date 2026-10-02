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
