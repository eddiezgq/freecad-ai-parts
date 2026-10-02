"""按 data/extract_jobs.yaml 批量抽取真实规格书（ADR-0040，issue #124）。

    python -m ingest.jobs run [--record] [--doc src-...]
    python -m ingest.jobs index      # 页码索引：每页有几张表、哪些检索词出现在哪页（不含原文）
    python -m ingest.jobs list

每个任务指定来源文档、品类、页码范围与目标型号（多型号目录，issue #125）。规格书须先用 python -m ingest.fetch
下载到 data/raw/，SHA-256 须与登记的一致。抽取结果写到 data/extracted/<文档 id>/<型号>.json，之后进复核队列。

- --record：真实调用 LLM（需要 ANTHROPIC_API_KEY），录制写到 data/recordings/llm/
- 不加 --record：只回放 data/recordings/llm/ 中的录制（仍需要本地有规格书，用来重建请求并核对引用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from ingest.fetch import RAW_DIR, registered_documents, sha256_file

ROOT = Path(__file__).resolve().parent.parent
JOBS_FILE = ROOT / "data" / "extract_jobs.yaml"
OUT_DIR = ROOT / "data" / "extracted"
REAL_RECORDINGS = ROOT / "data" / "recordings" / "llm"
SOURCES_FILE = ROOT / "data" / "sources.yaml"


class JobError(ValueError):
    pass


def load_jobs(data: dict) -> list[dict]:
    """展开为每个（文档, 品类, 页码, 型号）一项，并检查写法。"""
    from ingest.llm_extract import CATEGORIES
    from ingest.pdf_extract import parse_pages

    out = []
    for i, job in enumerate((data or {}).get("jobs") or []):
        where = f"第 {i + 1} 个任务"
        if not isinstance(job, dict):
            raise JobError(f"{where} 不是对象")
        doc, category = job.get("doc"), job.get("category")
        if not isinstance(doc, str) or not doc.startswith("src-"):
            raise JobError(f"{where}：doc 须为登记的来源文档 id")
        if category not in CATEGORIES:
            raise JobError(f"{where}：品类 {category!r} 不支持")
        pages = parse_pages(str(job.get("pages", "")))
        targets = job.get("targets")
        if not isinstance(targets, list) or not targets or not all(isinstance(t, str) and t.strip() for t in targets):
            raise JobError(f"{where}：targets 须为非空的型号列表")
        out += [{"doc": doc, "category": category, "pages": pages, "target": t.strip()} for t in targets]
    seen = set()
    for j in out:
        key = (j["doc"], j["target"])
        if key in seen:
            raise JobError(f"{j['doc']} 的型号 {j['target']} 重复")
        seen.add(key)
    return out


def output_path(job: dict, out_dir: Path = OUT_DIR) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", job["target"]).strip("_") or "model"
    return out_dir / job["doc"] / f"{slug}.json"


def run(jobs: list[dict], client, *, raw_dir: Path = RAW_DIR, out_dir: Path = OUT_DIR,
        sources: dict | None = None) -> list[dict]:
    """逐个任务抽取，写出结果；返回每项的摘要。任务之间互不影响，单个失败只记在摘要里。"""
    from ingest.llm_extract import RecordingMissing, extract_document
    from ingest.pdf_extract import ExtractError, extract
    from kb.sources import SourceRegistry

    sources = sources if sources is not None else yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    registry = SourceRegistry.from_dict(sources)
    shas = {d["id"]: d.get("sha256") for d in registered_documents(sources)}
    loaded: dict[str, object] = {}
    summary = []
    for job in jobs:
        row = {"doc": job["doc"], "target": job["target"], "category": job["category"]}
        why = registry.check_document(job["doc"])
        pdf = raw_dir / f"{job['doc']}.pdf"
        if why:
            row["error"] = why
        elif not pdf.is_file():
            row["error"] = f"没有 {pdf}：先运行 python -m ingest.fetch"
        elif shas.get(job["doc"]) and sha256_file(pdf) != shas[job["doc"]]:
            row["error"] = "规格书的 SHA-256 与登记的不符"
        if "error" in row:
            summary.append(row)
            continue
        try:
            if job["doc"] not in loaded:
                loaded[job["doc"]] = extract(pdf)
            result = extract_document(loaded[job["doc"]], job["category"], job["doc"], client,
                                      pages=job["pages"], target_model=job["target"])
        except (RecordingMissing, ExtractError, ValueError, RuntimeError) as exc:
            row["error"] = str(exc)
            summary.append(row)
            continue
        path = output_path(job, out_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        row.update(out=str(path), items=len(result["items"]), rejected=len(result["rejected"]),
                   missing_key_fields=result["missing_key_fields"])
        summary.append(row)
    return summary


def page_index(document, terms: list[str]) -> list[dict]:
    """每页的表格数、文字量和出现的检索词，用来确定抽取任务的页码范围；不含规格书原文。"""
    def norm(t: str) -> str:
        return re.sub(r"\s+", "", t or "").casefold()

    out = []
    for p in document.pages:
        body = norm(p.text) + "".join(norm(c or "") for t in p.tables for row in t.rows for c in row)
        out.append({"page": p.page, "tables": len(p.tables), "chars": len(p.text),
                    "terms": [t for t in terms if norm(t) and norm(t) in body]})
    return out


def load_index_requests(data: dict) -> list[dict]:
    out = []
    for i, req in enumerate((data or {}).get("index") or []):
        if not isinstance(req, dict) or not str(req.get("doc", "")).startswith("src-"):
            raise JobError(f"第 {i + 1} 个索引请求须写 doc")
        terms = req.get("terms") or []
        if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
            raise JobError(f"第 {i + 1} 个索引请求的 terms 须为字符串列表")
        out.append({"doc": req["doc"], "terms": terms})
    return out


def render_index(doc: str, index: list[dict]) -> str:
    lines = [f"### {doc}（共 {len(index)} 页）", "", "| 页 | 表格 | 字数 | 检索词 |", "| --- | --- | --- | --- |"]
    for r in index:
        if r["tables"] or r["terms"]:
            lines.append(f"| {r['page']} | {r['tables']} | {r['chars']} | {'、'.join(r['terms'])} |")
    return "\n".join(lines) + "\n"


def render_summary(summary: list[dict]) -> str:
    lines = ["| 文档 | 型号 | 品类 | 通过核对 | 被拒 | 缺关键字段 | 说明 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in summary:
        if "error" in r:
            lines.append(f"| {r['doc']} | {r['target']} | {r['category']} | | | | 失败：{r['error']} |")
        else:
            miss = "、".join(m.rsplit("/", 1)[-1] for m in r["missing_key_fields"]) or "无"
            lines.append(f"| {r['doc']} | {r['target']} | {r['category']} | {r['items']} | {r['rejected']} | {miss} | |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按 data/extract_jobs.yaml 抽取真实规格书（ADR-0040）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出全部抽取任务")
    p_index = sub.add_parser("index", help="为 index 中列出的规格书生成页码索引（不含原文）")
    p_index.add_argument("--summary", type=Path, help="把索引（Markdown）写到此文件")
    p_run = sub.add_parser("run", help="运行抽取任务")
    p_run.add_argument("--record", action="store_true", help="真实调用 LLM 并录制（需要 ANTHROPIC_API_KEY）")
    p_run.add_argument("--doc", action="append", default=[], help="只运行这些文档的任务（可重复）")
    p_run.add_argument("--summary", type=Path, help="把摘要（Markdown）写到此文件")
    args = parser.parse_args(argv)

    data = yaml.safe_load(JOBS_FILE.read_text(encoding="utf-8")) if JOBS_FILE.is_file() else {}
    try:
        jobs = load_jobs(data)
        index_requests = load_index_requests(data)
    except (JobError, ValueError) as exc:
        print(f"data/extract_jobs.yaml 写法不对：{exc}", file=sys.stderr)
        return 2
    if args.cmd == "index":
        from ingest.pdf_extract import ExtractError, extract

        texts, code = [], 0
        for req in index_requests:
            pdf = RAW_DIR / f"{req['doc']}.pdf"
            try:
                index = page_index(extract(pdf), req["terms"])
            except ExtractError as exc:
                print(f"失败 {req['doc']}：{exc}", file=sys.stderr)
                code = 1
                continue
            path = OUT_DIR / req["doc"] / "index.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            texts.append(render_index(req["doc"], index))
        text = "\n".join(texts)
        print(text, end="")
        if args.summary:
            args.summary.write_text(text, encoding="utf-8")
        return code
    if args.cmd == "list":
        for j in jobs:
            print(f"{j['doc']}  {j['category']}  第 {j['pages'][0]}–{j['pages'][-1]} 页  {j['target']}")
        return 0
    jobs = [j for j in jobs if not args.doc or j["doc"] in args.doc]
    from ingest.llm_extract import AnthropicClient, RecordedClient

    client = AnthropicClient(record_dir=REAL_RECORDINGS) if args.record else RecordedClient(REAL_RECORDINGS)
    summary = run(jobs, client)
    text = render_summary(summary)
    print(text, end="")
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    return 1 if any("error" in r for r in summary) else 0


if __name__ == "__main__":
    raise SystemExit(main())
