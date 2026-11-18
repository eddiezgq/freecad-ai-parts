"""通道 A：产品目录整张型号表成批抽取（ADR-0099 41.5，扩充 ADR-0040 的多型号目录）。

1. 代码找型号表：表格里有一行（表头）在参数列之后并排印着型号（如“项目 / 单位 / SM100 / SM200 …”），
   或安川式“型号 SGM7J- / A5A / 01A …”（前缀在行首、各列只印后缀）。列出全部型号和它们出现的页，交给人勾选。
   找不到（例如按尺寸、减速比分行的表）就说找不到，请人自己列出型号——不猜。
2. 逐型号抽取：与单型号同一套提示词和核对规则（`ingest.llm_extract.extract_document`，target_model + 页码）；
   每个型号单独一次 AI 调用，失败的型号单独列出原因，不影响别的型号。
3. 结果是每个型号一份抽取结果（extraction/1），照旧走复核再入库。

找型号表是纯函数，不联网、不调用 AI。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from ingest.llm_extract import RecordingMissing, extract_document
from ingest.pdf_extract import Document, extract, parse_pages

MODEL_CELL = re.compile(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9][A-Za-z0-9\-/.]{1,38}")
PREFIX_CELL = re.compile(r"(?:model|型号|形式|type)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-/.]*-)\s*$", re.IGNORECASE)
SUFFIX_CELL = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-/.]{0,20}")
# 像单位、不像型号的格子（有字母也有数字）：m2、kg·cm2、10-4kgm2……
UNIT_LIKE = re.compile(r"^(?:[a-zA-Z]{1,3}\d|\d+[a-zA-Z]{1,3}|10-?\d+.*)$")
MIN_MODELS = 2


class CatalogError(ValueError):
    pass


def _cell(c: str | None) -> str:
    return re.sub(r"\s+", " ", (c or "").strip())


def _model_like(c: str) -> bool:
    return bool(MODEL_CELL.fullmatch(c)) and not UNIT_LIKE.match(c)


def header_models(row: list[str | None]) -> list[str]:
    """一行表头里的型号（不认的返回空表）"""
    cells = [_cell(c) for c in row]
    filled = [(j, c) for j, c in enumerate(cells) if c]
    if not filled:
        return []
    # 安川式：行首“型号 SGM7J-”，后面各列是后缀
    m = PREFIX_CELL.search(filled[0][1])
    if m:
        suf = [c for j, c in filled[1:] if SUFFIX_CELL.fullmatch(c)]
        if len(suf) >= MIN_MODELS and len(suf) == len(filled) - 1:
            return [m.group(1) + s for s in suf]
    # 普通：除了行首叫法（和单位）列，其余全是型号
    rest = [c for j, c in filled if j >= 1]
    models = [c for c in rest if _model_like(c)]
    non_model = [c for c in rest if not _model_like(c)]
    if len(models) >= MIN_MODELS and len(non_model) <= 1:          # 允许一个“单位”列
        return models
    return []


def find_models(document: Document) -> dict:
    """{"models": [{"model", "pages"}], "tables": [...]}：按首次出现的顺序；同一型号在几页的表里出现都记上"""
    seen: dict[str, dict] = {}
    tables = []
    for p in document.pages:
        for t in p.tables:
            for i, row in enumerate(t.rows[:3]):                    # 表头在前 3 行里
                ms = header_models(row)
                if ms:
                    tables.append({"page": p.page, "row": i, "models": ms})
                    for m in ms:
                        seen.setdefault(m, {"model": m, "pages": []})
                        if p.page not in seen[m]["pages"]:
                            seen[m]["pages"].append(p.page)
                    break
    return {"models": list(seen.values()), "tables": tables}


def extract_catalog(document: Document, category: str, doc_id: str, client, *, models: list[str] | None = None,
                    pages: list[int] | None = None, model: str | None = None, prompt_version: str | None = None) -> dict:
    """逐型号抽取。models 不给时用 find_models 找到的全部；pages 不给时每个型号用它出现的页"""
    found = {m["model"]: m["pages"] for m in find_models(document)["models"]}
    if models is None:
        models = list(found)
        if not models:
            raise CatalogError("没找到型号表（表头一行并排印着型号）；请人列出要抽取的型号")
    out = {"format": "catalog-extraction/1", "document": {"doc": doc_id, "sha256": document.sha256},
           "category": category, "models": []}
    kw = {"model": model} | ({"prompt_version": prompt_version} if prompt_version else {})
    for m in models:
        use_pages = pages or found.get(m)
        entry: dict = {"model": m, "pages": use_pages}
        try:
            r = extract_document(document, category, doc_id, client, pages=use_pages, target_model=m, **kw)
        except RecordingMissing:
            raise
        except Exception as ex:  # noqa: BLE001 — 一个型号失败不影响别的型号，原因记下来
            entry.update(status="failed", reason=f"{type(ex).__name__}: {ex}")
        else:
            entry.update(status="ok", result=r, accepted=len(r["items"]), rejected=len(r["rejected"]),
                         missing_key_fields=r["missing_key_fields"])
        out["models"].append(entry)
    ok = [e for e in out["models"] if e["status"] == "ok"]
    out["summary"] = {"models": len(models), "ok": len(ok), "failed": len(models) - len(ok),
                      "values": sum(e["accepted"] for e in ok)}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingest.catalog_batch", description="产品目录整张型号表成批抽取（ADR-0099 通道 A）")
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--category", required=True)
    ap.add_argument("--doc", help="来源文档 id（src-…，在 data/sources.yaml 或企业库登记过）")
    ap.add_argument("--list", action="store_true", help="只列出找到的型号，不抽取")
    ap.add_argument("--models", help="要抽取的型号，逗号分隔（缺省全部）")
    ap.add_argument("--pages", help="页码范围，如 60-90")
    ap.add_argument("-o", "--out", type=Path)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--replay", type=Path)
    mode.add_argument("--live", action="store_true")
    ap.add_argument("--provider", choices=("claude", "deepseek"))
    a = ap.parse_args(argv)
    doc = extract(a.pdf)
    if a.pages:
        doc = doc.select(parse_pages(a.pages))
    if a.list:
        for m in find_models(doc)["models"]:
            print(f"{m['model']}\t第 {'、'.join(map(str, m['pages']))} 页")
        return 0
    if not a.doc:
        ap.error("抽取要给 --doc")
    if a.live:
        from assist.llm import GatewayClient

        client = GatewayClient(a.provider)
        llm_model = client.model
    else:
        from ingest.llm_extract import RECORDINGS_DIR, RecordedClient

        client = RecordedClient(a.replay or RECORDINGS_DIR)
        llm_model = None
    models = [m.strip() for m in a.models.split(",")] if a.models else None
    try:
        r = extract_catalog(doc, a.category, a.doc, client, models=models, model=llm_model)
    except (CatalogError, RecordingMissing) as ex:
        print(f"没有抽取：{ex}", file=sys.stderr)
        return 2
    text = json.dumps(r, ensure_ascii=False, indent=1) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    s = r["summary"]
    print(f"{s['models']} 个型号：{s['ok']} 个抽出 {s['values']} 个值，{s['failed']} 个失败（AI 提议，未复核）")
    for e in r["models"]:
        if e["status"] == "failed":
            print(f"  {e['model']}：{e['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
