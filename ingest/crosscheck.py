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
CONFIRMED_FILE = REVIEW_DIR / "confirmed.yaml"
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


def _numbers(text: str) -> list[float]:
    import re

    return [float(x) for x in re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", text or "")]


def apply_confirmations(primary: dict, check: dict, cmp: dict, confirms: list[dict], model: str) -> list[str]:
    """人工确认与人工录入（ADR-0044 第 4 条）。

    - 确认：已通过引用核对的项，确认值须等于它的值；被拒收的项（如只印在图纸上的尺寸），确认值须出现在
      它印出的文字中，页码一致
    - 录入：没有任何抽取读到时，由人对照规格书填写，须给出页码与照抄的原文 quote
    - 给出 tol_upper / tol_lower 时按名义值加公差记录
    - 只给 min、max 时为范围值，只能人工录入；可附 condition（工况，如润滑方式）
    确认或录入的值记为 reviewed，来源注明确认人与日期。返回说明。
    """
    from ingest.units import to_standard

    doc = primary["document"]["doc"]
    notes = []
    for c in confirms:
        if c.get("doc") != doc or c.get("model") != model or c.get("target") in cmp["agreed"]:
            continue
        t, v, who, day = c.get("target"), c.get("value"), c.get("confirmed_by"), c.get("date")
        curve = _curve(c)
        if curve is not None:  # 效率曲线读点（ADR-0047）：只能人工录入，须给图所在页码、图号原文与工况
            if not (who and day):
                notes.append(f"人工确认写法不全，未采用：{t}")
                continue
            curve["source"] = {"doc": doc, "page": c["page"],
                               "note": f"人工录入：{who}（{day}），规格书第 {c['page']} 页“{c['quote'].strip()}”按网格读点"}
            cmp["agreed"][t] = curve
            cmp["pending"] = [row for row in cmp["pending"] if row["target"] != t]
            notes.append(f"{t} 由 {who} 按第 {c['page']} 页曲线读点录入（{len(curve['points'])} 点）")
            continue
        rng = _range(c)
        if rng is not None:
            v = f"{rng[0]:g}–{rng[1]:g}"  # 范围只能人工录入（须给页码与原文），见 ADR-0046 第 5 条
        if not (isinstance(t, str) and isinstance(v, (int, float, str)) and not isinstance(v, bool) and who and day):
            notes.append(f"人工确认写法不全，未采用：{c}")
            continue
        field = t.rsplit("/", 1)[-1]
        pv = None
        for ext in (primary, check) if rng is None else ():
            for it in ext["items"]:
                got = it["value"].get("value", it["value"].get("nominal"))
                same = (got == v) if isinstance(v, str) else (
                    isinstance(got, (int, float)) and not isinstance(got, bool) and math.isclose(got, v, rel_tol=1e-6))
                if it["target"] == t and same:
                    pv = copy.deepcopy(it["value"])
            if isinstance(v, str):
                continue  # 文字值只能确认已通过引用核对的读数
            for r in ext["rejected"]:
                printed = r.get("printed") or {}
                if pv is None and r.get("target") == t and r.get("page") == c.get("page"):
                    try:
                        factor = to_standard(1.0, printed.get("unit") or "mm", field)
                    except ValueError:
                        continue
                    if any(math.isclose(n * factor, v, rel_tol=1e-6) for n in _numbers(printed.get("text", ""))):
                        pv = {"value": v, "source": {"doc": doc, "page": r["page"]}, "method": "manual",
                              "confidence": 1}
        quote = c.get("quote")
        manual = pv is None and isinstance(c.get("page"), int) and isinstance(quote, str) and quote.strip()
        if manual:
            pv = {"value": v, "source": {"doc": doc, "page": c["page"]}, "method": "manual", "confidence": 1}
            if rng is not None:
                pv.pop("value")
                pv.update(min=rng[0], max=rng[1])
        if pv is None:
            notes.append(f"{t} 的人工确认值 {v} 不是任何一次抽取在该页读到的数，也没有给出页码与原文，未采用")
            continue
        tol = (c.get("tol_upper"), c.get("tol_lower"))
        if all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in tol) and not isinstance(v, str):
            for k in ("value", "min", "max"):
                pv.pop(k, None)
            pv.update(nominal=v, tol_upper=tol[0], tol_lower=tol[1])
        pv["reviewed"] = True
        if isinstance(c.get("condition"), str) and c["condition"].strip():
            pv["condition"] = c["condition"].strip()
        how = f"人工录入：{who}（{day}），规格书第 {c['page']} 页原文“{quote.strip()}”" if manual else \
            f"人工确认：{who}（{day}），对照规格书第 {pv['source'].get('page')} 页"
        pv["source"]["note"] = how
        cmp["agreed"][t] = pv
        cmp["pending"] = [row for row in cmp["pending"] if row["target"] != t]
        notes.append(f"{t} = {v} 由 {who} {'人工录入' if manual else '人工确认'}")
    return notes


def _curve(c: dict) -> dict | None:
    """条目给 points（温度、输入转速、效率读点）时为效率曲线（ADR-0047）；须有页码、原文与工况。"""
    pts = c.get("points")
    keys = ("ambient_temp_c", "input_speed_rpm", "efficiency_ratio")
    ok = isinstance(pts, list) and len(pts) >= 2 and all(
        isinstance(p, dict) and set(p) == set(keys)
        and all(isinstance(p[k], (int, float)) and not isinstance(p[k], bool) for k in keys)
        and 0 < p["efficiency_ratio"] <= 1 for p in pts)
    if not (ok and isinstance(c.get("page"), int) and isinstance(c.get("quote"), str) and c["quote"].strip()
            and isinstance(c.get("condition"), str) and c["condition"].strip()):
        return None
    return {"points": [{k: float(p[k]) for k in keys} for p in pts], "condition": c["condition"].strip(),
            "method": "manual", "confidence": 1, "reviewed": True}


def _range(c: dict) -> tuple[float, float] | None:
    """条目只给 min、max（不给 value）时为范围值，如原文“200 VAC to 240 VAC”（ADR-0046 第 5 条）。"""
    lo, hi = c.get("min"), c.get("max")
    num = all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lo, hi))
    if "value" in c or not num or lo > hi:
        return None
    return float(lo), float(hi)


def variant_confirmations(confirms: list[dict], base: str, variant: str) -> list[dict]:
    """订货选项变体（ADR-0046 第 4 条）：沿用基本型号的确认，变体型号自己的确认按字段覆盖。"""
    own = [c for c in confirms if c.get("model") == variant]
    mine = {(c.get("doc"), c.get("target")) for c in own}
    inherited = [dict(c, model=variant) for c in confirms
                 if c.get("model") == base and (c.get("doc"), c.get("target")) not in mine]
    return own + inherited


def load_confirmations(path: Path = CONFIRMED_FILE) -> list[dict]:
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(data.get("confirmations") or [])


def build(primary: dict, check: dict, *, vendor: str, model: str, registry,
          confirms: list[dict] | None = None, configurable: dict | None = None) -> dict:
    """比对并组装组件；返回 {component?, problems, notes, agreed, pending}。组件通过入库把关才返回。"""
    from ingest.assemble import assemble
    from kb.store import check_component

    cmp = compare(primary, check)
    confirmed = apply_confirmations(primary, check, cmp, confirms or [], model)
    doc = primary["document"]["doc"]
    note = (f"参数取自厂商公开资料 {doc}（ADR-0040），经两次独立抽取比对一致（{REVIEWER}）；"
            "不一致的项未收录，见 data/review/")
    comp, problems, notes = assemble(primary["category"], vendor, model, cmp["agreed"], note=note,
                                     configurable=configurable)
    out = {"agreed": sorted(cmp["agreed"]), "pending": cmp["pending"], "problems": problems,
           "notes": confirmed + notes}
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
        j["configurable_ports"] = dict(spec.get("configurable_ports") or {})  # 端口 id → 依据（ADR-0045）
        j["variants"] = [v for v in spec.get("variants") or [] if v.get("of") == j["target"] and v.get("model")]
        out.append(j)
    return out


def render(rows: list[dict]) -> str:
    lines = ["| 文档 | 型号 | 一致 | 待人工核对 | 结果 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        result = f"入库 {r['component_id']}" if r.get("component_id") else "未入库：" + "；".join(r["problems"][:3])
        lines.append(f"| {r['doc']} | {r['target']} | {r['agreed']} | {r['pending']} | {result} |")
    return "\n".join(lines) + "\n"


def _build_one(args, job: dict, primary: dict, check: dict, model: str, review_name: str, confirms: list[dict],
               registry) -> dict:
    res = build(primary, check, vendor=job["vendor"], model=model, registry=registry, confirms=confirms,
                configurable=job.get("configurable_ports"))
    review = args.review / job["doc"] / review_name
    review.parent.mkdir(parents=True, exist_ok=True)
    body = {k: res[k] for k in ("agreed", "pending", "problems", "notes")}
    body.update(reviewer=REVIEWER, primary_model=primary["extractor"]["model"],
                check_model=check["extractor"]["model"])
    row = {"doc": job["doc"], "target": model, "agreed": len(res["agreed"]),
           "pending": len(res["pending"]), "problems": res["problems"]}
    if "component" in res:
        comp = res["component"]
        path = args.library / comp["category"] / f"{comp['id']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(comp, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        body["component"] = comp["id"]
        row["component_id"] = comp["id"]
    review.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return row


def main(argv: list[str] | None = None) -> int:
    from ingest.assemble import slug
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
        base = primary.get("model") or job["target"]
        confirms = load_confirmations()
        for model, review_name, conf in [(base, p_path.name, confirms)] + [
                (v["model"], f"{slug(v['model'])}.json", variant_confirmations(confirms, base, v["model"]))
                for v in job.get("variants", [])]:
            rows.append(_build_one(args, job, primary, check, model, review_name, conf, registry))
    text = render(rows)
    print(text, end="")
    if args.summary:
        args.summary.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
