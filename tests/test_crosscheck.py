"""AI 复核：两次独立抽取逐项比对（ADR-0040 第 7 条，issue #127）。不联网，用合成目录与模拟响应。"""

from __future__ import annotations

import copy
import json
import os
import re

import pytest
import yaml

from ingest import crosscheck as cx
from ingest import jobs as jx
from ingest.fetch import sha256_file
from ingest.llm_simulate import proposals_from_answer, simulated_response
from kb.sources import SourceRegistry
from kb.validation import errors


@pytest.fixture(scope="module")
def catalog(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    from ingest.synthetic import FontMissing, find_font
    from ingest.synthetic_multi import build_catalog

    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    raw = tmp_path_factory.mktemp("raw")
    cat = build_catalog("reducer", 0)
    sha = sha256_file(cat.render(raw / "src-fake-cat.pdf"))
    sources = {"sources": [{"id": "fake", "vendor": "Synth Gear", "license": "params-only", "terms_checked": True,
                            "documents": [{"id": "src-fake-cat", "url": "https://example.com/c.pdf", "sha256": sha}]}]}
    return cat, raw, sources


class _Client:
    def __init__(self, cat, tamper=None):
        self.cat, self.tamper = cat, tamper

    def complete(self, request):
        model = re.search(r"目标型号：(.+)", request["user"]).group(1).strip()
        proposals = proposals_from_answer(self.cat.answers[model])
        if self.tamper:
            proposals = self.tamper(copy.deepcopy(proposals))
        return simulated_response(self.cat.answers[model], proposals)


def _extract(catalog, out, *, tamper=None):
    cat, raw, sources = catalog
    jobs = [{"doc": "src-fake-cat", "category": "reducer", "pages": [2, 3], "target": cat.models[0]}]
    jx.run(jobs, _Client(cat), raw_dir=raw, out_dir=out, sources=sources, model="model-a")
    jx.run(jobs, _Client(cat, tamper), raw_dir=raw, out_dir=out, sources=sources, model="model-b", check=True)
    base = out / "src-fake-cat" / f"{cat.models[0]}"
    return (json.loads(base.with_suffix(".json").read_text(encoding="utf-8")),
            json.loads(base.with_suffix(".check.json").read_text(encoding="utf-8")))


def test_agreement_builds_reviewed_component(catalog, tmp_path):
    cat, _, sources = catalog
    primary, check = _extract(catalog, tmp_path)
    assert primary["extractor"]["model"] == "model-a" and check["extractor"]["model"] == "model-b"
    res = cx.build(primary, check, vendor="Synth Gear", model=cat.models[0],
                   registry=SourceRegistry.from_dict(sources))
    assert res["pending"] == [] and res["problems"] == []
    comp = res["component"]
    assert errors("component.schema.json", comp) == []
    extracted = [v for v in comp["params"].values() if v["method"] == "extracted"]
    assert extracted and all(v["reviewed"] and cx.REVIEWER in v["source"]["note"] for v in extracted)
    assert "ADR-0040" in comp["note"]


def test_disagreement_is_left_out(catalog, tmp_path):
    cat, _, sources = catalog
    victim = "params/mass_kg"
    assert any(p["target"] == victim for p in proposals_from_answer(cat.answers[cat.models[0]]))

    def tamper(ps):
        return [dict(p, page=99) if p["target"] == victim else p for p in ps]  # 复核抽取读错页：该项被核对拒绝

    primary, check = _extract(catalog, tmp_path, tamper=tamper)
    res = cx.build(primary, check, vendor="Synth Gear", model=cat.models[0],
                   registry=SourceRegistry.from_dict(sources))
    assert [p["target"] for p in res["pending"]] == [victim]
    assert res["pending"][0]["reason"] == "只有主抽取报出" and "check" not in res["pending"][0]
    comp = res.get("component")
    assert comp is None or "mass_kg" not in comp["params"]


def test_value_mismatch_detected():
    item = {"value": {"value": 10.0, "source": {"doc": "src-x", "page": 1}}}
    base = {"document": {"doc": "src-x", "sha256": "0" * 64, "pages": 1}, "category": "reducer",
            "extractor": {"model": "a"}, "items": [{"target": "params/ratio", **item}]}
    other = copy.deepcopy(base)
    other["extractor"]["model"] = "b"
    other["items"][0]["value"]["value"] = 10.5
    out = cx.compare(base, other)
    assert out["agreed"] == {} and out["pending"][0]["reason"] == "两次的值不一致"
    assert out["pending"][0]["primary"] == {"value": 10.0} and out["pending"][0]["check"] == {"value": 10.5}


def test_same_model_or_document_refused():
    base = {"document": {"doc": "src-x", "sha256": "0" * 64, "pages": 1}, "category": "reducer",
            "extractor": {"model": "a"}, "items": []}
    with pytest.raises(ValueError, match="同一个模型"):
        cx.compare(base, copy.deepcopy(base))
    other = copy.deepcopy(base)
    other["extractor"]["model"] = "b"
    other["category"] = "drive"
    with pytest.raises(ValueError, match="不同"):
        cx.compare(base, other)


@pytest.mark.parametrize(("a", "b", "same"), [
    ({"value": 1.0}, {"value": 1.0000001}, True),
    ({"value": 1.0}, {"value": 1.01}, False),
    ({"min": 200, "max": 240}, {"min": 200, "max": 240}, True),
    ({"min": 200, "max": 240}, {"value": 240}, False),
    ({"value": ["ethercat", "canopen"]}, {"value": ["canopen", "ethercat"]}, True),
    ({"value": "key"}, {"value": "clamp_ring"}, False),
    ({"value": 5, "condition": "at 2000 rpm"}, {"value": 5}, False),
    ({"value": 5, "condition": "at 2000 rpm"}, {"value": 5, "condition": "2000 r/min"}, True),
])
def test_same_rules(a, b, same):
    assert cx._same(a, b) is same


def test_main_writes_library_and_review(catalog, tmp_path, monkeypatch):
    cat, _, sources = catalog
    out = tmp_path / "extracted"
    _extract(catalog, out)
    src_file = tmp_path / "sources.yaml"
    src_file.write_text(yaml.safe_dump(sources, allow_unicode=True), encoding="utf-8")
    jobs_file = tmp_path / "jobs.yaml"
    jobs_file.write_text(yaml.safe_dump({"jobs": [{"doc": "src-fake-cat", "category": "reducer", "pages": "2-3",
                                                    "targets": [cat.models[0]]}]}), encoding="utf-8")
    monkeypatch.setattr(jx, "JOBS_FILE", jobs_file)
    monkeypatch.setattr(jx, "OUT_DIR", out)
    monkeypatch.setattr(jx, "SOURCES_FILE", src_file)
    lib, rev = tmp_path / "library", tmp_path / "review"
    assert cx.main(["--library", str(lib), "--review", str(rev), "--summary", str(tmp_path / "s.md")]) == 0
    files = list(lib.rglob("*.json"))
    assert len(files) == 1 and files[0].parent.name == "reducer"
    comp = json.loads(files[0].read_text(encoding="utf-8"))
    assert comp["vendor"] == "Synth Gear"  # 厂商取自来源登记
    review = json.loads((rev / "src-fake-cat" / f"{cat.models[0]}.json").read_text(encoding="utf-8"))
    assert review["component"] == comp["id"] and review["reviewer"] == cx.REVIEWER
    assert "入库" in (tmp_path / "s.md").read_text(encoding="utf-8")


def _ext(model, items=(), rejected=()):
    return {"document": {"doc": "src-x-doc"}, "category": "drive", "extractor": {"model": model},
            "items": list(items), "rejected": list(rejected)}


def test_human_confirmation_only_of_values_read_on_the_page():
    """人工确认（ADR-0044 第 4 条）：只能确认至少一次抽取在该页读到的数；不能凭空补数。"""
    rej = {"target": "dims/width_mm", "page": 80, "reason": "引用所在行中找不到与印出文字完全一致的数值",
           "printed": {"text": "40", "unit": "", "quote": "2 × M4 40 (75) 170"}}
    p, c = _ext("a", rejected=[rej]), _ext("b", rejected=[rej])
    ok = {"doc": "src-x-doc", "model": "D-1", "target": "dims/width_mm", "value": 40, "page": 80,
          "confirmed_by": "张国庆", "date": "2026-10-04"}
    cmp = cx.compare(p, c)
    notes = cx.apply_confirmations(p, c, cmp, [ok], "D-1")
    pv = cmp["agreed"]["dims/width_mm"]
    assert pv["value"] == 40 and pv["reviewed"] is True and pv["method"] == "manual" and "张国庆" in pv["source"]["note"]
    assert errors("common/param-value.schema.json", pv) == [] and any("人工确认" in n for n in notes)
    # 页上没读到的数、别的型号、写法不全：不采用
    for bad in (dict(ok, value=45), dict(ok, page=81), dict(ok, model="D-2"), {k: v for k, v in ok.items() if k != "date"}):
        cmp = cx.compare(p, c)
        cx.apply_confirmations(p, c, cmp, [bad], "D-1")
        assert "dims/width_mm" not in cmp["agreed"]


def test_human_confirmation_of_text_value_must_match_a_checked_reading():
    item = {"target": "ports/encoder/kind", "value": {"value": "absolute", "source": {"doc": "src-x-doc", "page": 53},
                                                      "method": "extracted", "confidence": 0.9, "reviewed": False}}
    p, c = _ext("a", items=[item]), _ext("b")
    ok = {"doc": "src-x-doc", "model": "D-1", "target": "ports/encoder/kind", "value": "absolute", "page": 53,
          "confirmed_by": "张国庆", "date": "2026-10-04"}
    cmp = cx.compare(p, c)
    cx.apply_confirmations(p, c, cmp, [ok], "D-1")
    assert cmp["agreed"]["ports/encoder/kind"]["value"] == "absolute" and not cmp["pending"]
    cmp = cx.compare(p, c)
    cx.apply_confirmations(p, c, cmp, [dict(ok, value="incremental")], "D-1")
    assert "ports/encoder/kind" not in cmp["agreed"]


def test_manual_entry_needs_page_and_quote():
    p, c = _ext("a"), _ext("b")
    entry = {"doc": "src-x-doc", "model": "D-1", "target": "dims/height_mm", "value": 160, "page": 82,
             "quote": "160", "confirmed_by": "张国庆", "date": "2026-10-04"}
    cmp = cx.compare(p, c)
    notes = cx.apply_confirmations(p, c, cmp, [entry], "D-1")
    pv = cmp["agreed"]["dims/height_mm"]
    assert pv["method"] == "manual" and pv["source"]["page"] == 82 and "人工录入" in pv["source"]["note"]
    assert any("人工录入" in n for n in notes)
    for bad in ({k: v for k, v in entry.items() if k != "quote"}, dict(entry, quote="  ")):
        cmp = cx.compare(p, c)
        cx.apply_confirmations(p, c, cmp, [bad], "D-1")
        assert "dims/height_mm" not in cmp["agreed"]
    # 名义值加公差
    shaft = dict(entry, target="ports/shaft/diameter_mm", value=14, tol_upper=0, tol_lower=-0.011, quote="14 0 -0.011")
    cmp = cx.compare(p, c)
    cx.apply_confirmations(p, c, cmp, [shaft], "D-1")
    pv = cmp["agreed"]["ports/shaft/diameter_mm"]
    assert pv["nominal"] == 14 and pv["tol_lower"] == -0.011 and "value" not in pv
    assert errors("common/param-value.schema.json", pv) == []


def test_manual_entry_of_a_range_with_condition():
    """原文印的是范围（如“200 VAC to 240 VAC”）时写 min、max，只能人工录入（ADR-0046 第 5 条）。"""
    p, c = _ext("a"), _ext("b")
    entry = {"doc": "src-x-doc", "model": "D-1", "target": "ports/power_in/voltage_v", "min": 200, "max": 240,
             "page": 62, "quote": "200 VAC to 240 VAC, 50 Hz/60 Hz", "condition": "三相",
             "confirmed_by": "张国庆", "date": "2026-10-04"}
    cmp = cx.compare(p, c)
    notes = cx.apply_confirmations(p, c, cmp, [entry], "D-1")
    pv = cmp["agreed"]["ports/power_in/voltage_v"]
    assert (pv["min"], pv["max"]) == (200, 240) and "value" not in pv and pv["condition"] == "三相"
    assert pv["method"] == "manual" and errors("common/param-value.schema.json", pv) == []
    assert any("200–240" in n for n in notes)
    # 范围不给原文、上下限颠倒、同时给 value：不采用
    for bad in ({k: v for k, v in entry.items() if k != "quote"}, dict(entry, min=250), dict(entry, value=200)):
        cmp = cx.compare(p, c)
        cx.apply_confirmations(p, c, cmp, [bad], "D-1")
        assert cmp["agreed"].get("ports/power_in/voltage_v", {}).get("min") is None


def test_variant_inherits_base_confirmations_and_overrides_its_own():
    """订货选项变体（ADR-0046 第 4 条）：沿用基本型号的确认，变体自己的确认按字段覆盖。"""
    base = {"doc": "d", "model": "M-1", "target": "ports/shaft/feature", "value": "plain"}
    other = {"doc": "d", "model": "M-1", "target": "dims/square_mm", "value": 60}
    own = {"doc": "d", "model": "M-1（轴端代码 6）", "target": "ports/shaft/feature", "value": "keyed"}
    unrelated = {"doc": "d", "model": "M-2", "target": "dims/square_mm", "value": 80}
    got = cx.variant_confirmations([base, other, own, unrelated], "M-1", "M-1（轴端代码 6）")
    by_target = {c["target"]: c for c in got}
    assert by_target["ports/shaft/feature"]["value"] == "keyed"
    assert by_target["dims/square_mm"]["value"] == 60 and by_target["dims/square_mm"]["model"] == "M-1（轴端代码 6）"
    assert len(got) == 2


def test_manual_entry_of_an_efficiency_curve():
    """ADR-0047：效率曲线按网格读点录入，须给页码、图号原文与工况；不满足就不采用。"""
    p, c = _ext("a"), _ext("b")
    pts = [{"ambient_temp_c": t, "input_speed_rpm": 3500, "efficiency_ratio": e} for t, e in ((-10, 0.33), (0, 0.47))]
    entry = {"doc": "src-x-doc", "model": "D-1", "target": "params/efficiency_curve", "points": pts, "page": 17,
             "quote": "Graph 135-6", "condition": "额定扭矩、脂润滑", "confirmed_by": "张国庆", "date": "2026-10-05"}
    cmp = cx.compare(p, c)
    notes = cx.apply_confirmations(p, c, cmp, [entry], "D-1")
    pv = cmp["agreed"]["params/efficiency_curve"]
    assert pv["points"][0] == {"ambient_temp_c": -10.0, "input_speed_rpm": 3500.0, "efficiency_ratio": 0.33}
    assert pv["source"]["page"] == 17 and "Graph 135-6" in pv["source"]["note"] and any("2 点" in n for n in notes)
    for bad in (dict(entry, quote=""), {k: v for k, v in entry.items() if k != "condition"},
                dict(entry, points=pts[:1]), dict(entry, points=[dict(pts[0], efficiency_ratio=1.5), pts[1]])):
        cmp = cx.compare(p, c)
        cx.apply_confirmations(p, c, cmp, [bad], "D-1")
        assert "params/efficiency_curve" not in cmp["agreed"]


def test_manual_entry_with_printed_unit_is_converted():
    """人工录入可写照抄的单位，按字段的标准单位换算并在来源里记下原值（ADR-0094 第 4 条）。"""
    p, c = _ext("a"), _ext("b")
    entry = {"doc": "src-x-doc", "model": "D-1", "target": "params/torsional_stiffness_k1_nm_per_arcmin", "value": 3.1,
             "unit": "×10⁴ Nm/rad", "page": 13, "quote": "K1 ×10⁴Nm/rad 0.47 1 1.6 3.1", "confirmed_by": "张国庆", "date": "2026-11-15"}
    cmp = cx.compare(p, c)
    cx.apply_confirmations(p, c, cmp, [entry], "D-1")
    pv = cmp["agreed"]["params/torsional_stiffness_k1_nm_per_arcmin"]
    assert pv["value"] == pytest.approx(3.1e4 / (180 * 60 / 3.141592653589793))       # 1 rad = 3437.75′
    assert pv["method"] == "manual" and "原值 3.1 ×10⁴ Nm/rad" in pv["source"]["note"]
    inertia = dict(entry, target="params/input_inertia_kgm2", value=0.413, unit="×10⁻⁴ kg·m²", quote="0.413 0.421")
    cmp = cx.compare(p, c)
    cx.apply_confirmations(p, c, cmp, [inertia], "D-1")
    assert cmp["agreed"]["params/input_inertia_kgm2"]["value"] == pytest.approx(4.13e-5)
    bad = dict(entry, unit="kg")                                                     # 量纲不符：不采用
    cmp = cx.compare(p, c)
    notes = cx.apply_confirmations(p, c, cmp, [bad], "D-1")
    assert "params/torsional_stiffness_k1_nm_per_arcmin" not in cmp["agreed"] and any("换算不了" in n for n in notes)


def test_library_reducers_have_catalog_stiffness_and_output_bearing():
    """零件库的 8 个谐波减速器都补了 ADR-0094 的参数，且与样本的 kgfm/arcmin 一栏互相印证。"""
    from pathlib import Path
    lib = Path(cx.LIBRARY_DIR) / "reducer"
    kgf = 9.80665
    # 样本同一表里另印的 kgfm/arcmin 值（第 13 页 K1、第 18 页力矩刚度），用来核对换算
    k1_kgfm = {"csf-14-100": 0.14, "csf-17-100": 0.3, "csf-20-100": 0.47, "csf-25-100": 0.92, "csf-32-100": 2.0}
    for f in sorted(lib.glob("reducer.harmonic-drive-llc.csf-*.json")):
        p = json.loads(f.read_text(encoding="utf-8"))["params"]
        for k in ("input_inertia_kgm2", "torsion_t1_nm", "torsion_t2_nm", "torsional_stiffness_k1_nm_per_arcmin",
                  "torsional_stiffness_k2_nm_per_arcmin", "torsional_stiffness_k3_nm_per_arcmin", "output_bearing_dynamic_load_rating_n",
                  "output_bearing_static_load_rating_n", "output_bearing_moment_load_rating_nm", "output_bearing_moment_stiffness_nm_per_arcmin",
                  "output_bearing_pitch_diameter_mm", "output_bearing_offset_mm", "rated_life_h", "rated_input_speed_rpm"):
            assert p[k]["reviewed"] and p[k]["source"]["doc"] == "src-hd-csg-csf-gear-units", (f.name, k)
        ks = [p[f"torsional_stiffness_k{i}_nm_per_arcmin"]["value"] for i in (1, 2, 3)]
        assert ks[0] < ks[1] < ks[2] and p["torsion_t1_nm"]["value"] < p["torsion_t2_nm"]["value"]
        key = next((m for m in k1_kgfm if m in f.name), None)
        if key:
            assert ks[0] == pytest.approx(k1_kgfm[key] * kgf, rel=0.05)
    p = json.loads((lib / "reducer.harmonic-drive-llc.csf-25-100-2uh.json").read_text(encoding="utf-8"))["params"]
    assert p["output_bearing_moment_stiffness_nm_per_arcmin"]["value"] == pytest.approx(7.2 * kgf, rel=0.03)
