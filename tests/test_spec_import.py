"""导入规格书（M9 第三步）：模拟响应回放下抽取 → 核对 → 确认 → 入企业库全流程。不联网、不调用真实 LLM。"""

from __future__ import annotations

import copy
import os

import pytest

from freecad_addon.core import spec_import
from ingest.llm_simulate import SimulatedClient, proposals_from_answer, simulated_response
from ingest.synthetic import FontMissing, datasheets, find_font, row_label
from kb.enterprise import EnterpriseError, EnterpriseLibrary

TODAY = "2026-10-06"


@pytest.fixture(scope="module")
def sheet():
    return next(s for s in datasheets(0, ["reducer"]) if s.answer["layout"] == "two_col")


def _base(answer):
    """公共库里的这个零件：缺几项参数（模拟“待补”）。"""
    comp = copy.deepcopy(answer["component"])
    for k in ("rated_torque_nm", "mass_kg", "backlash_arcmin"):
        comp["params"].pop(k, None)
    return comp


def _pdf(sheet, tmp_path):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    return sheet.render(tmp_path / "datasheet.pdf")


def _xlsx(sheet, tmp_path):
    from openpyxl import Workbook

    a = sheet.answer
    wb = Workbook()
    wb.remove(wb.active)
    for page in sorted({e["page"] for e in a["fields"]}):
        ws = wb.create_sheet(f"P{page}")
        ws.append([a["title"]])
        for e in a["fields"]:
            if e["page"] == page:
                ws.append([row_label(e, a["lang"], a["layout"]), e["text"]])
    path = tmp_path / "selection.xlsx"
    wb.save(path)
    return path


def _flow(sheet, tmp_path, file):
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    base = _base(sheet.answer)
    client = SimulatedClient(simulated_response(sheet.answer))
    ext = spec_import.run(ent, base, file, "张工", client)
    return ent, base, ext


def test_pdf_extract_confirm_write(sheet, tmp_path):
    ent, base, ext = _flow(sheet, tmp_path, _pdf(sheet, tmp_path))
    doc = ent.documents()[0]
    assert ext["document"]["doc"] == doc["id"] and doc["id"].startswith("src-ent-")
    assert not ext["rejected"]
    rows = spec_import.rows(ext, base)
    by = {r.target: r for r in rows}
    assert by["params/rated_torque_nm"].current == "" and by["params/rated_torque_nm"].default_checked
    assert rows[0].writable and rows[0].changes  # 可写且有变化的在前
    dims = [r for r in rows if r.target.startswith("dims/")]
    assert all(not r.writable and not r.default_checked for r in dims)
    assert spec_import.identity_note(ext, base) == ""

    chosen = ["params/rated_torque_nm", "params/mass_kg"]
    written = spec_import.apply(ent, base["id"], ext, chosen, "张工", lambda cid: base, TODAY)
    assert written == sorted(chosen)
    comp = ent.get(base["id"])
    pv = comp["params"]["rated_torque_nm"]
    assert pv["method"] == "extracted" and pv["reviewed"] is True
    assert pv["source"]["doc"] == doc["id"] and pv["source"]["page"] >= 1
    assert "确认人：张工" in pv["source"]["note"] and "原文“" in pv["source"]["note"]
    truth = sheet.answer["component"]["params"]["rated_torque_nm"]["value"]  # 标准单位下的真值
    assert pv["value"] == pytest.approx(truth, rel=1e-3)
    # 未勾选的不写
    assert "backlash_arcmin" not in comp["params"]
    actions = [h["action"] for h in ent.history()]
    assert actions.count("set_value") == 2 and actions[0] == "register_document"


def test_unconfirmed_or_unverified_values_never_written(sheet, tmp_path):
    ent, base, ext = _flow(sheet, tmp_path, _pdf(sheet, tmp_path))
    with pytest.raises(spec_import.SpecImportError):
        spec_import.apply(ent, base["id"], ext, ["params/not_extracted"], "张工", lambda cid: base, TODAY)
    dim = next(i["target"] for i in ext["items"] if i["target"].startswith("dims/"))
    with pytest.raises(spec_import.SpecImportError):
        spec_import.apply(ent, base["id"], ext, [dim], "张工", lambda cid: base, TODAY)
    with pytest.raises(spec_import.SpecImportError):
        spec_import.apply(ent, base["id"], ext, ["params/mass_kg"], " ", lambda cid: base, TODAY)
    assert ent.get(base["id"]) is None  # 什么都没写


def test_wrong_reading_is_rejected_by_code(sheet, tmp_path):
    """AI 读错的数（与印出的不一致）由代码核对拒掉，不出现在确认表里。"""
    props = proposals_from_answer(sheet.answer)
    bad = next(p for p in props if p["target"] == "params/rated_torque_nm")
    bad["value"] = bad["value"] * 2 + 1
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    base = _base(sheet.answer)
    ext = spec_import.run(ent, base, _pdf(sheet, tmp_path), "张工",
                          SimulatedClient(simulated_response(sheet.answer, props)))
    assert "params/rated_torque_nm" not in {r.target for r in spec_import.rows(ext, base)}
    assert any(r.get("target") == "params/rated_torque_nm" for r in ext["rejected"])


def test_xlsx_selection_table(sheet, tmp_path):
    ent, base, ext = _flow(sheet, tmp_path, _xlsx(sheet, tmp_path))
    targets = {i["target"] for i in ext["items"]}
    assert "params/rated_torque_nm" in targets and "params/ratio" in targets
    spec_import.apply(ent, base["id"], ext, ["params/rated_torque_nm"], "张工", lambda cid: base, TODAY)
    assert ent.get(base["id"])["params"]["rated_torque_nm"]["source"]["doc"].startswith("src-ent-")


def test_rejects_other_files_and_missing_library(sheet, tmp_path):
    txt = tmp_path / "a.txt"
    txt.write_text("x")
    with pytest.raises(spec_import.SpecImportError):
        spec_import.load_document(txt)
    with pytest.raises(spec_import.SpecImportError):
        spec_import.run(None, _base(sheet.answer), txt, "张工", SimulatedClient({}))


def test_identity_note(sheet):
    base = _base(sheet.answer)
    assert "没有核对到型号" in spec_import.identity_note({}, base)
    assert "不一致" in spec_import.identity_note({"model": "XYZ-1"}, base)


def test_enterprise_rule_still_applies(sheet, tmp_path):
    """写入仍走企业库的规则：资料未登记时拒绝。"""
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    item = {"target": "params/mass_kg", "printed": {"text": "410", "quote": "Weight 410"},
            "value": {"value": 0.41, "source": {"doc": "src-ent-nope", "page": 1}, "method": "extracted",
                      "confidence": 0.9, "reviewed": False}}
    ext = {"category": "reducer", "items": [item]}
    with pytest.raises(EnterpriseError):
        spec_import.apply(ent, "x", ext, ["params/mass_kg"], "张工", lambda cid: _base(sheet.answer), TODAY)
