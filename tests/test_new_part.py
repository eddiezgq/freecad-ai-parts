"""新建零件向导（M9 第四步）：规格书抽取 + 人工补录 → 按品类模板组装 → 存企业库 → 可选型、可出 BOM。不联网。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from engine.export import bom_rows
from freecad_addon.core import fill, new_part, spec_import
from ingest.assemble import values_from_component
from ingest.llm_simulate import SimulatedClient, simulated_response
from ingest.synthetic import FontMissing, datasheets, find_font
from kb.enterprise import EnterpriseLibrary
from kb.library import JsonLibrary, LayeredLibrary, WithGenerated
from kb.validation import errors

ROOT = Path(__file__).resolve().parent.parent
PUBLIC = JsonLibrary(ROOT / "data" / "library")
TODAY = "2026-10-06"
CSF25 = "reducer.harmonic-drive-llc.csf-25-100-2uh"


def _fonts():
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")


@pytest.mark.parametrize("category", ["reducer", "servo_motor", "drive", "bearing"])
def test_new_part_from_datasheet(category, tmp_path):
    _fonts()
    sheet = datasheets(0, [category])[0]
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    ext = spec_import.run(ent, {"category": category}, sheet.render(tmp_path / "d.pdf"), "张工",
                          SimulatedClient(simulated_response(sheet.answer)))
    rows = spec_import.rows(ext, None)
    assert all(r.writable and r.current == "" for r in rows)  # 新零件：外形尺寸也可写
    chosen = [r.target for r in rows]
    vals = new_part.values(ext, chosen, {}, "张工", TODAY)
    comp, problems, _ = new_part.draft(category, ext["vendor"], ext["model"], vals)
    assert comp is not None, problems
    assert errors("component.schema.json", comp) == []
    assert comp["id"] == new_part.new_id(category, ext["vendor"], ext["model"])
    new_part.save(ent, comp, "张工", PUBLIC.get)
    lib = LayeredLibrary(ent, PUBLIC)
    assert lib.origin(comp["id"]) == "enterprise" and comp["id"] in {c["id"] for c in lib.all(category)}
    # 来源都指向企业登记的资料，值都经人确认
    doc = ent.documents()[0]["id"]
    for pv in comp["params"].values():
        if pv["method"] == "extracted":
            assert pv["source"]["doc"] == doc and pv["reviewed"] is True and "确认人：张工" in pv["source"]["note"]
    # 可出 BOM
    system = {"id": "s", "components": [{"instance": "x", "component": comp["id"]}], "connections": []}
    row = bom_rows(system, lib.get)[0]
    assert row["component_id"] == comp["id"] and doc in row["source_docs"]


def test_missing_envelope_is_listed_not_saved(tmp_path):
    _fonts()
    sheet = datasheets(0, ["reducer"])[0]
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    ext = spec_import.run(ent, {"category": "reducer"}, sheet.render(tmp_path / "d.pdf"), "张工",
                          SimulatedClient(simulated_response(sheet.answer)))
    chosen = [i["target"] for i in ext["items"] if not i["target"].startswith("dims/")]
    comp, problems, _ = new_part.draft("reducer", ext["vendor"], ext["model"],
                                       new_part.values(ext, chosen, {}, "张工", TODAY))
    assert comp is None and any("包络" in p for p in problems)
    # 人工补录外形尺寸（附资料、页码、原文、录入人）后组装成功
    doc = ent.documents()[0]["id"]
    rows = {r.target: r for r in new_part.field_rows("reducer")}
    manual = {t: fill.build_pv(rows[t], v, doc=doc, page=1, quote=f"{t} {v}", actor="张工", today=TODAY)
              for t, v in (("dims/overall_length_mm", "60"), ("dims/outer_diameter_mm", "90"))}
    comp, problems, _ = new_part.draft("reducer", ext["vendor"], ext["model"],
                                       new_part.values(ext, chosen, manual, "张工", TODAY))
    assert comp is not None, problems
    assert comp["envelope"]["parts"][0]["length_mm"]["value"] == 60.0


def test_new_part_is_selectable(tmp_path):
    """企业按规格书新建的减速器（数值同 CSF-25，型号不同）在选型中作为候选出现。"""
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    csf = PUBLIC.get(CSF25)
    body = csf["envelope"]["parts"][0]
    vals = values_from_component(csf)
    vals["dims/overall_length_mm"], vals["dims/outer_diameter_mm"] = body["length_mm"], body["diameter_mm"]
    comp, problems, _ = new_part.draft("reducer", "Enterprise Test Gear", "ETG-25-100", vals, open_ports=True)
    assert comp is not None, problems
    new_part.save(ent, comp, "张工", PUBLIC.get)
    from mcp_server.tools import compose_chain

    req = {"output_torque_cont_nm": 25, "output_torque_peak_nm": 50, "output_speed_rpm": 30,
           "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3}}
    out = compose_chain(WithGenerated(LayeredLibrary(ent, PUBLIC)), req, top_n=10, include_unknown=True)
    used = {i["component"] for c in out["candidates"] for i in c["system"]["components"]}
    assert comp["id"] in used


def test_save_rules(tmp_path):
    ent = EnterpriseLibrary(tmp_path / "ent", create=True)
    csf = PUBLIC.get(CSF25)
    with pytest.raises(spec_import.SpecImportError, match="公共库已有"):
        new_part.save(ent, csf, "张工", PUBLIC.get)
    with pytest.raises(spec_import.SpecImportError, match="企业库"):
        new_part.save(None, csf, "张工", PUBLIC.get)
    assert new_part.draft("reducer", " ", "X", {})[1] == ["请填写厂商与型号"]
    with pytest.raises(spec_import.SpecImportError):
        new_part.values({"items": []}, ["params/mass_kg"], {}, "张工")
    with pytest.raises(spec_import.SpecImportError):
        new_part.field_rows("gearbox")
    rows = new_part.field_rows("servo_motor")
    assert rows[0].key and any(r.target.startswith("dims/") for r in rows)
