"""规格书下载与批量抽取（ADR-0040，issue #124）。不联网：下载函数用替身，LLM 用模拟响应。"""

from __future__ import annotations

import json
import os
import re

import pytest
import yaml

from ingest import fetch as fx
from ingest import jobs as jx
from ingest.llm_simulate import simulated_response

PDF = b"%PDF-1.4\n% fake\n"
SHA = __import__("hashlib").sha256(PDF).hexdigest()

SOURCES_TEXT = """\
# 注释保留
sources:
  - id: acme
    vendor: Acme
    license: params-only
    terms_checked: true
    documents:
      - id: src-acme-cat
        title: Acme catalog
        url: https://example.com/acme.pdf
      - id: src-acme-old
        title: Old
        url: https://example.com/old.pdf
        sha256: %s
  - id: pending-co
    vendor: Pending
    license: pending
    terms_checked: false
    documents:
      - id: src-pending-cat
        url: https://example.com/p.pdf
""" % ("a" * 64)


def _dl(content=PDF):
    calls = []

    def download(url, dest):
        calls.append(url)
        dest.write_bytes(content)

    download.calls = calls
    return download


# ---------------------------------------------------------------- 下载


def test_registered_documents():
    docs = fx.registered_documents(yaml.safe_load(SOURCES_TEXT))
    assert [(d["id"], d["source"]) for d in docs] == [
        ("src-acme-cat", "acme"), ("src-acme-old", "acme"), ("src-pending-cat", "pending-co")]


def test_fetch_downloads_once_and_reuses(tmp_path):
    doc = {"id": "src-acme-cat", "url": "https://example.com/acme.pdf"}
    dl = _dl()
    path, sha, fresh = fx.fetch_document(doc, tmp_path, dl)
    assert fresh and sha == SHA and path.read_bytes() == PDF
    assert fx.fetch_document({**doc, "sha256": SHA}, tmp_path, dl)[2] is False
    assert len(dl.calls) == 1 and not list(tmp_path.glob("*.part"))


def test_fetch_sha_mismatch_rejected_and_removed(tmp_path):
    doc = {"id": "src-acme-old", "url": "https://example.com/old.pdf", "sha256": "a" * 64}
    with pytest.raises(fx.FetchError, match="SHA-256"):
        fx.fetch_document(doc, tmp_path, _dl())
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(("doc", "content", "msg"), [
    ({"id": "src-x", "url": "http://example.com/x.pdf"}, PDF, "https"),
    ({"id": "src-x", "url": "https://example.com/x.pdf"}, b"<html>login</html>", "不是 PDF"),
    ({"id": "src-x", "url": "https://example.com/x.pdf", "sha256": "abc"}, PDF, "格式"),
])
def test_fetch_rejects(tmp_path, doc, content, msg):
    with pytest.raises(fx.FetchError, match=msg):
        fx.fetch_document(doc, tmp_path, _dl(content))
    assert not list(tmp_path.glob("*.pdf"))


def test_pin_sha256_keeps_comments_and_is_idempotent():
    out = fx.pin_sha256(SOURCES_TEXT, "src-acme-cat", SHA)
    assert out.startswith("# 注释保留") and out.count(SHA) == 1
    docs = {d["id"]: d for d in fx.registered_documents(yaml.safe_load(out))}
    assert docs["src-acme-cat"]["sha256"] == SHA and docs["src-acme-old"]["sha256"] == "a" * 64
    assert fx.pin_sha256(out, "src-acme-cat", SHA) == out
    with pytest.raises(ValueError, match="不同"):
        fx.pin_sha256(SOURCES_TEXT, "src-acme-old", SHA)
    with pytest.raises(ValueError, match="没有文档"):
        fx.pin_sha256(SOURCES_TEXT, "src-nope", SHA)


def test_fetch_main_skips_unapproved_and_pins(tmp_path, monkeypatch, capsys):
    src = tmp_path / "sources.yaml"
    src.write_text(SOURCES_TEXT, encoding="utf-8")
    dl = _dl()
    monkeypatch.setattr(fx, "_download", dl)
    monkeypatch.setattr(fx, "PAUSE_S", 0)
    code = fx.main(["--sources", str(src), "--raw-dir", str(tmp_path / "raw"), "--pin", "--doc", "src-acme-cat",
                    "--doc", "src-pending-cat"])
    out = capsys.readouterr().out
    assert code == 0 and "跳过 src-pending-cat" in out and dl.calls == ["https://example.com/acme.pdf"]
    assert f"sha256: \"{SHA}\"" in src.read_text(encoding="utf-8")
    assert fx.main(["--sources", str(src), "--doc", "src-unknown"]) == 2


# ---------------------------------------------------------------- 抽取任务


def test_load_jobs_expands_and_validates():
    jobs = jx.load_jobs({"jobs": [{"doc": "src-a", "category": "reducer", "pages": "2-3", "targets": ["X-1", "X-2"]}]})
    assert [j["target"] for j in jobs] == ["X-1", "X-2"] and jobs[0]["pages"] == [2, 3]
    for bad in ({"doc": "a", "category": "reducer", "pages": "1", "targets": ["X"]},
                {"doc": "src-a", "category": "motor", "pages": "1", "targets": ["X"]},
                {"doc": "src-a", "category": "reducer", "pages": "1", "targets": []},
                {"doc": "src-a", "category": "reducer", "pages": "x", "targets": ["X"]}):
        with pytest.raises(ValueError):
            jx.load_jobs({"jobs": [bad]})
    with pytest.raises(jx.JobError, match="重复"):
        jx.load_jobs({"jobs": [{"doc": "src-a", "category": "reducer", "pages": "1", "targets": ["X", "X"]}]})


def test_output_path_slug(tmp_path):
    assert jx.output_path({"doc": "src-a", "target": "CSF-14 / 50"}, tmp_path) == tmp_path / "src-a" / "CSF-14_50.json"


def test_project_jobs_file_is_valid():
    data = yaml.safe_load(jx.JOBS_FILE.read_text(encoding="utf-8"))
    jx.load_jobs(data)
    jx.load_index_requests(data)


@pytest.fixture(scope="module")
def catalog_pdf(tmp_path_factory):
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
    path = cat.render(raw / "src-fake-cat.pdf")
    return cat, raw, fx.sha256_file(path)


class _ByTarget:
    """按请求中的目标型号返回对应答案的模拟响应。"""

    def __init__(self, cat):
        self.cat = cat

    def complete(self, request):
        model = re.search(r"目标型号：(.+)", request["user"]).group(1).strip()
        return simulated_response(self.cat.answers[model])


def _sources(sha):
    return {"sources": [{"id": "fake", "vendor": "Synth", "license": "params-only", "terms_checked": True,
                         "documents": [{"id": "src-fake-cat", "url": "https://example.com/c.pdf", "sha256": sha}]}]}


def test_run_jobs_writes_results(catalog_pdf, tmp_path):
    cat, raw, sha = catalog_pdf
    models = cat.models[:2]
    jobs = [{"doc": "src-fake-cat", "category": "reducer", "pages": [2, 3], "target": m} for m in models]
    jobs.append({"doc": "src-missing", "category": "reducer", "pages": [2], "target": "Z"})
    summary = jx.run(jobs, _ByTarget(cat), raw_dir=raw, out_dir=tmp_path, sources=_sources(sha))
    ok = [r for r in summary if "error" not in r]
    assert [r["target"] for r in ok] == models and all(r["rejected"] == 0 for r in ok)
    result = json.loads((tmp_path / "src-fake-cat" / f"{models[0]}.json").read_text(encoding="utf-8"))
    assert result["model"] == models[0] and result["document"]["doc"] == "src-fake-cat"
    assert "未在 data/sources.yaml 登记" in summary[-1]["error"]
    table = jx.render_summary(summary)
    assert models[0] in table and "失败" in table


def test_run_jobs_refuses_changed_file(catalog_pdf, tmp_path):
    cat, raw, _ = catalog_pdf
    job = {"doc": "src-fake-cat", "category": "reducer", "pages": [2], "target": cat.models[0]}
    summary = jx.run([job], _ByTarget(cat), raw_dir=raw, out_dir=tmp_path, sources=_sources("2" * 64))
    assert summary[0]["error"] == "规格书的 SHA-256 与登记的不符"


def test_page_index_has_no_text(catalog_pdf):
    from ingest.pdf_extract import extract

    cat, raw, _ = catalog_pdf
    index = jx.page_index(extract(raw / "src-fake-cat.pdf"), [cat.models[0], "nonexistent-term"])
    assert [r["page"] for r in index] == [1, 2, 3, 4]
    assert [r["tables"] for r in index] == [0, 1, 1, 0]
    assert all(set(r) == {"page", "tables", "chars", "head", "terms"} for r in index)
    assert all(len(r["head"]) <= 2 and all(len(h) <= 60 for h in r["head"]) for r in index)
    assert cat.models[0] in index[1]["terms"] and all("nonexistent-term" not in r["terms"] for r in index)
    md = jx.render_index("src-fake-cat", index)
    assert "| 2 | 1 |" in md and cat.title[:20] in md


def test_diagnose_lists_nearest_lines(catalog_pdf, tmp_path):
    cat, raw, sha = catalog_pdf
    job = {"doc": "src-fake-cat", "category": "reducer", "pages": [2, 3], "target": cat.models[0]}
    jx.run([job], _ByTarget(cat), raw_dir=raw, out_dir=tmp_path, sources=_sources(sha))
    path = jx.output_path(job, tmp_path)
    result = json.loads(path.read_text(encoding="utf-8"))
    result["rejected"] = [{"target": "params/ratio", "page": 2, "reason": "原文引用在第 2 页的任何一行中都找不到",
                           "printed": {"text": "x", "unit": "", "quote": cat.models[0]}},
                          {"target": "params/mass_kg", "page": 2, "reason": "单位不对",
                           "printed": {"text": "x", "unit": "", "quote": "skip me"}}]
    path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    text = jx.diagnose([job], raw_dir=raw, out_dir=tmp_path)
    assert "params/ratio" in text and "表格行" in text and "skip me" not in text
    assert jx.diagnose([job], raw_dir=raw, out_dir=tmp_path, limit=0).strip() == ""
