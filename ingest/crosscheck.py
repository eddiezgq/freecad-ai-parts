"""AI 复核：两次独立抽取逐项比对（ADR-0040 第 7 条，issue #127）。

同一份规格书、同一型号，用两个不同的模型各抽取一次：
- 主抽取：python -m ingest.jobs run（缺省模型）
- 复核抽取：python -m ingest.jobs run --check（FAP_CHECK_MODEL，缺省 claude-opus-5-5）

两次都通过代码核对、且值一致的项视为已复核（复核人记为“claude（AI 复核）”）；不一致或只有一次报出的项
不入库，列入待人工核对清单。一致的项组装成组件，通过入库把关（kb.store.check_component）后写到
data/library/<品类>/<组件 id>.json，作为真实组件库（FAP_LIBRARY 可直接指向该目录）。

    python -m ingest.crosscheck [--doc src-...]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = ROOT / "data" / "library"
REVIEW_DIR = ROOT / "data" / "review"
REVIEWER = "claude（AI 复核）"
_KEYS = ("value", "min", "max", "nominal", "tol_upper", "tol_lower")


def _same(a: dict, b: dict) -> bool:
    """两次抽取的值是否一致：数值键与数值逐个相等（相对误差 1e-6），文字与列表忽略顺序；工况有无须一致。"""
    if {k for k in _KEYS if k in a} != {k for k in _KEYS if k in b}:
        return False
    for k in _KEYS:
        if k not in a:
            continue
        x, y = a[k], b[k]
        if isinstance(x, (int, float)) and not isinstance(x, bool) and isinstance(y, (int, float)) \
                and not isinstance(y, bool):
            if not math.isclose(x, y, rel_tol=1e-6, abs_tol=1e-12):
                return False
        elif isinstance(x, list) and isinstance(y, list):
            if sorted(map(str, x)) != sorted(map(str, y)):
                return False
        elif x != y:
            return False
    return ("condition" in a) == ("condition" in b)


def compare(primary: dict, check: dict) -> dict:
    """逐项比对两次抽取结果，返回 {agreed: {target: 参数值}, pending: [{target, reason, primary?, check?}]}。"""
    if primary["document"] != check["document"] or primary["category"] != check["category"]:
        raise ValueError("两次抽取的规格书或品类不同，不能比对")
    if primary["extractor"].get("model") == check["extractor"].get("model"):
        raise ValueError("两次抽取用的是同一个模型，不算独立复核")
    a = {i["target"]: i["value"] for i in primary["items"]}
    b = {i["target"]: i["value"] for i in check["items"]}
    agreed: dict[str, dict] = {}
    pending: list[dict] = []
    for t in sorted(set(a) | set(b)):
        if t in a and t in b and _same(a[t], b[t]):
            pv = copy.deepcopy(a[t])
            pv["reviewed"] = True
            note = f"{REVIEWER}：{primary['extractor']['model']} 与 {check['extractor']['model']} 两次独立抽取一致"
            pv["source"]["note"] = note
            if "condition" in b[t] and b[t]["condition"] != a[t].get("condition"):
                pv["source"]["note"] += f"；复核抽取的工况写法：{b[t]['condition']}"
            agreed[t] = pv
            continue
        row: dict = {"target": t}
        if t in a:
            row["primary"] = {k: v for k, v in a[t].items() if k in (*_KEYS, "condition")}
        if t in b:
            row["check"] = {k: v for k, v in b[t].items() if k in (*_KEYS, "condition")}
        row["reason"] = ("两次的值不一致" if t in a and t in b else
                         "只有主抽取报出" if t in a else "只有复核抽取报出")
        pending.append(row)
    return {"agreed": agreed, "pending": pending}


def build(primary: dict, check: dict, *, vendor: str, model: str, registry) -> dict:
    """比对并组装组件；返回 {component?, problems, notes, agreed, pending}。组件通过入库把关才返回。"""
    from ingest.assemble import assemble
    from kb.store import check_component

    cmp = compare(primary, check)
    doc = primary["document"]["doc"]
    note = (f"参数取自厂商公开资料 {doc}（ADR-0040），经两次独立抽取比对一致（{REVIEWER}）；"
            "不一致的项未收录，见 data/review/")
    comp, problems, notes = assemble(primary["category"], vendor, model, cmp["agreed"], note=note)
    out = {"agreed": sorted(cmp["agreed"]), "pending": cmp["pending"], "problems": problems, "notes": notes}
    if comp is not None:
        reasons = check_component(comp, registry)
        if reasons:
            out["problems"] = reasons
        else:
            out["component"] = comp
    return out


def _jobs_with_vendor(data: dict, sources: dict) -> list[dict]:
    from ingest.fetch import registered_documents
    from ingest.jobs import load_jobs

    owner = {d["id"]: d["source"] for d in registered_documents(sources)}
    vendors = {s["id"]: s["vendor"] for s in sources.get("sources", [])}
    raw = {(j.get("doc"), j.get("category")): j for j in (data or {}).get("jobs") or []}
    out = []
    for j in load_jobs(data):
        spec = raw.get((j["doc"], j["category"]), {})
        j["vendor"] = spec.get("vendor") or vendors.get(owner.get(j["doc"], ""), "")
        out.append(j)
    return out


def render(rows: list[dict]) -> str:
    lines = ["| 文档 | 型号 | 一致 | 待人工核对 | 结果 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        result = f"入库 {r['component_id']}" if r.get("component_id") else "未入库：" + "；".join(r["problems"][:3])
        lines.append(f"| {r['doc']} | {r['target']} | {r['agreed']} | {r['pending']} | {result} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from ingest.jobs import JOBS_FILE, OUT_DIR, SOURCES_FILE, output_path
    from kb.sources import SourceRegistry

    parser = argparse.ArgumentParser(description="两次独立抽取比对、组装组件（ADR-0040 第 7 条）")
    parser.add_argument("--doc", action="append", default=[])
    parser.add_argument("--library", type=Path, default=LIBRARY_DIR)
    parser.add_argument("--review", type=Path, default=REVIEW_DIR)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)

    sources = yaml.safe_load(SOURCES_FILE.read_text(encoding="utf-8"))
    registry = SourceRegistry.from_dict(sources)
    jobs = _jobs_with_vendor(yaml.safe_load(JOBS_FILE.read_text(encoding="utf-8")), sources)
    rows = []
    for job in jobs:
        if args.doc and job["doc"] not in args.doc:
            continue
        p_path = output_path(job, OUT_DIR)
        c_path = p_path.with_suffix(".check.json")
        if not (p_path.is_file() and c_path.is_file()):
            continue
        primary = json.loads(p_path.read_text(encoding="utf-8"))
        check = json.loads(c_path.read_text(encoding="utf-8"))
        res = build(primary, check, vendor=job["vendor"], model=primary.get("model") or job["target"],
                    registry=registry)
        review = args.review / job["doc"] / p_path.name
        review.parent.mkdir(parents=True, exist_ok=True)
        body = {k: res[k] for k in ("agreed", "pending", "problems", "notes")}
        body.update(reviewer=REVIEWER, primary_model=primary["extractor"]["model"],
                    check_model=check["extractor"]["model"])
        row = {"doc": job["doc"], "target": job["target"], "agreed": len(res["agreed"]),
               "pending": len(res["pending"]), "problems": res["problems"]}
        if "component" in res:
            comp = res["component"]
            path = args.library / comp["category"] / f"{comp['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(comp, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            body["component"] = comp["id"]
            row["component_id"] = comp["id"]
        review.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rows.append(row)
    text = render(rows)
    print(text, end="")
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
