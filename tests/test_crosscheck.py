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
