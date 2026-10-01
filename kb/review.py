"""人工复核队列（issue #30，ADR-0023）。

抽取结果入队 → 需复核项逐一决定（决定只增不改，可改判）→ 全部决定后组装组件并写入知识库（留修改历史）
→ 按错误分类统计。命令行：python -m kb.review --help
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from ingest.assemble import assemble, component_id, values_from_component
from ingest.llm_extract import targets
from kb.db import require_autocommit
from kb.sources import TEST_DOC, SourceRegistry
from kb.store import ImportRejected, get_component, import_component
from kb.validation import errors, validator_for_ref

LOW_CONFIDENCE = 0.9
ERROR_CATEGORIES = ("none", "wrong_value", "wrong_unit", "wrong_target", "wrong_page", "wrong_condition",
                    "enum_mapping", "hallucinated", "missed", "false_reject", "withdrawn", "other")
_READ_ERRORS = ("wrong_value", "wrong_unit", "wrong_target", "wrong_page", "wrong_condition", "enum_mapping",
                "other")
# 每种复核项、每种动作允许的错误分类；第一个是缺省值（None 表示必须明确选择）
ALLOWED: dict[tuple[str, str], tuple] = {
    ("item", "accept"): ("none",),
    ("item", "correct"): (None, *_READ_ERRORS),
    ("item", "reject"): (None, "hallucinated", "wrong_target", "other"),
    ("rejected", "dismiss"): (None, "hallucinated", *_READ_ERRORS),
    ("rejected", "correct"): (None, "false_reject", *_READ_ERRORS),
    ("missing", "absent"): ("none",),
    ("missing", "correct"): ("missed",),
    ("added", "correct"): ("missed",),
    ("added", "reject"): ("withdrawn",),  # 复核员撤回自己补的值，不算 LLM 的错
}
ACTIONS = {kind: tuple(a for k, a in ALLOWED if k == kind) for kind in ("item", "rejected", "missing", "added")}
NOT_LLM_ERRORS = {"withdrawn"}
_VALUE_KEYS = ("value", "min", "max", "nominal", "tol_upper", "tol_lower", "condition")


class ReviewError(ValueError):
    """复核操作不合法。"""


class ReviewIncomplete(ReviewError):
    def __init__(self, problems: list[str]):
        super().__init__("；".join(problems))
        self.problems = problems


# ---------------------------------------------------------------- 入队


def enqueue(conn: psycopg.Connection, result: dict, *, created_by: str, registry: SourceRegistry,
            allow_test: bool = False, low_confidence: float = LOW_CONFIDENCE) -> int:
    """把一份抽取结果放入复核队列，返回抽取 id。"""
    require_autocommit(conn)
    if not (created_by or "").strip():
        raise ReviewError("必须给出操作人")
    errs = errors("extraction.schema.json", result)
    if errs:
        raise ReviewError("抽取结果不符合 schema：" + "；".join(errs[:3]))
    doc = result["document"]["doc"]
    if result["extractor"].get("simulated") and doc != TEST_DOC:
        raise ReviewError("模拟响应只能用于测试专用来源，不得作为真实数据入队（ADR-0021）")
    why = registry.check_document(doc, vendor=result.get("vendor"), allow_test=allow_test)
    if why:
        raise ReviewError(why)
    tmap = targets(result["category"])
    rows: list[tuple] = []
    for item in result["items"]:
        reasons = []
        if tmap[item["target"]][0].key:
            reasons.append("key_field")
        if item["value"]["confidence"] < low_confidence:
            reasons.append("low_confidence")
        if item.get("issues"):
            reasons.append("has_issue")
        rows.append(("item", item["target"], item["value"], item["printed"], item.get("issues", []), reasons))
    for r in result["rejected"]:
        rows.append(("rejected", r.get("target"), None, r.get("printed"), [r["reason"]], ["rejected"]))
    for t in result["missing_key_fields"]:
        rows.append(("missing", t, None, None, [], ["missing_key_field"]))
    ext = result["extractor"]
    try:
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                "INSERT INTO extractions (doc, sha256, pages, category, vendor, model, llm_model, prompt_version,"
                " simulated, result, created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (doc, result["document"]["sha256"], result["document"]["pages"], result["category"],
                 result.get("vendor"), result.get("model"),
                 ext["model"], ext["prompt_version"], bool(ext.get("simulated")), Jsonb(result), created_by),
            )
            eid = cur.fetchone()[0]
            for kind, target, proposed, printed, issues, reasons in rows:
                cur.execute(
                    "INSERT INTO review_items (extraction_id, kind, target, proposed, printed, issues, reasons,"
                    " needs_review) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (eid, kind, target, Jsonb(proposed) if proposed is not None else None,
                     Jsonb(printed) if printed is not None else None, Jsonb(issues), reasons, bool(reasons)),
                )
    except psycopg.errors.UniqueViolation as exc:
        raise ReviewError("这份抽取结果（同一文档、文件、模型与提示词版本）已经入队") from exc
    return eid


# ---------------------------------------------------------------- 查询


def _extraction(conn: psycopg.Connection, eid: int, lock: str = "") -> dict:
    """lock 为 " FOR SHARE" 或 " FOR UPDATE" 时在当前事务中锁住该行。"""
    row = conn.execute(
        "SELECT id, doc, pages, category, vendor, model, status, component_id, simulated FROM extractions"
        f" WHERE id=%s{lock}", (eid,),
    ).fetchone()
    if row is None:
        raise ReviewError(f"没有抽取 #{eid}")
    keys = ("id", "doc", "pages", "category", "vendor", "model", "status", "component_id", "simulated")
    return dict(zip(keys, row, strict=True))


def items(conn: psycopg.Connection, extraction_id: int) -> list[dict]:
    """抽取的全部复核项，含当前决定（最新的一条）。"""
    rows = conn.execute(
        "SELECT i.id, i.kind, i.target, i.proposed, i.printed, i.issues, i.reasons, i.needs_review,"
        " d.action, d.value, d.error_category, d.reviewer, d.note"
        " FROM review_items i LEFT JOIN LATERAL ("
        "   SELECT * FROM review_decisions WHERE item_id = i.id ORDER BY id DESC LIMIT 1) d ON true"
        " WHERE i.extraction_id=%s ORDER BY i.id",
        (extraction_id,),
    ).fetchall()
    keys = ("id", "kind", "target", "proposed", "printed", "issues", "reasons", "needs_review",
            "action", "value", "error_category", "reviewer", "note")
    return [dict(zip(keys, r, strict=True)) for r in rows]


def pending(conn: psycopg.Connection, extraction_id: int | None = None) -> list[dict]:
    """需复核且还没有决定的项。"""
    eids = [extraction_id] if extraction_id is not None else [
        r[0] for r in conn.execute("SELECT id FROM extractions WHERE status='open' ORDER BY id").fetchall()]
    out = []
    for eid in eids:
        out += [dict(i, extraction_id=eid) for i in items(conn, eid) if i["needs_review"] and i["action"] is None]
    return out


def history(conn: psycopg.Connection, item_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT action, value, error_category, reviewer, note, decided_at FROM review_decisions"
        " WHERE item_id=%s ORDER BY id", (item_id,)).fetchall()
    keys = ("action", "value", "error_category", "reviewer", "note", "decided_at")
    return [dict(zip(keys, r, strict=True)) for r in rows]


# ---------------------------------------------------------------- 决定


def manual_value(category: str, target: str, spec: dict, *, doc: str, page: int, pages: int) -> dict:
    """复核员给出的值 → 参数值对象（method manual、confidence 1、reviewed true），并按字段 schema 校验。"""
    tmap = targets(category)
    if target not in tmap:
        raise ReviewError(f"target {target!r} 不属于品类 {category}")
    if not isinstance(spec, dict) or not spec or set(spec) - set(_VALUE_KEYS):
        raise ReviewError(f"值须为对象，只能含 {', '.join(_VALUE_KEYS)}")
    if not isinstance(page, int) or isinstance(page, bool) or not 1 <= page <= pages:
        raise ReviewError(f"人工给出的值须注明来源页码（1–{pages}）")
    for k, v in spec.items():
        if isinstance(v, float) and not math.isfinite(v):
            raise ReviewError(f"{k} 不是有限数值")
    pv = {**spec, "source": {"doc": doc, "page": page}, "method": "manual", "confidence": 1, "reviewed": True}
    refs = tmap[target][1]
    errs = [[e.message for e in validator_for_ref(r).iter_errors(pv)] for r in refs]
    if all(errs):
        raise ReviewError("值不符合字段 schema：" + "；".join(errs[0][:3]))
    if "min" in pv and "max" in pv and pv["min"] > pv["max"]:
        raise ReviewError("下限大于上限")
    if "tol_upper" in pv and "tol_lower" in pv and pv["tol_lower"] > pv["tol_upper"]:
        raise ReviewError("下偏差大于上偏差")
    return pv


def decide(conn: psycopg.Connection, item_id: int, action: str, *, reviewer: str,
           error_category: str | None = None, value: dict | None = None, page: int | None = None,
           target: str | None = None, note: str | None = None) -> None:
    """记录一个复核决定（追加；同一项再次决定即改判）。与组装互斥：锁住所属抽取后再检查状态。"""
    require_autocommit(conn)
    if not (reviewer or "").strip():
        raise ReviewError("必须给出复核人")
    with conn.transaction():
        row = conn.execute("SELECT kind, target, extraction_id FROM review_items WHERE id=%s", (item_id,)).fetchone()
        if row is None:
            raise ReviewError(f"没有复核项 #{item_id}")
        kind, item_target, eid = row
        ext = _extraction(conn, eid, " FOR SHARE")
        if ext["status"] != "open":
            raise ReviewError(f"抽取 #{eid} 已组装入库，不能再改")
        allowed = ALLOWED.get((kind, action))
        if allowed is None:
            raise ReviewError(f"{kind} 项只能 {' / '.join(ACTIONS[kind])}")
        category_ = error_category or allowed[0]
        if category_ is None:
            raise ReviewError(f"{action} 须选错误分类：{', '.join(a for a in allowed if a)}")
        if category_ not in allowed:
            raise ReviewError(f"{kind} 项 {action} 的错误分类只能是 {', '.join(a for a in allowed if a)}")
        stored = None
        if action == "correct":
            tgt = target or item_target
            if not tgt:
                raise ReviewError("被拒提议没有合法的 target，须用 --target 指定")
            if value is None or page is None:
                raise ReviewError("correct 须给出值与来源页码")
            pv = manual_value(ext["category"], tgt, value, doc=ext["doc"], page=page, pages=ext["pages"])
            stored = {"target": tgt, "value": pv}
        elif value is not None or target is not None:
            raise ReviewError(f"{action} 不接受值或 target")
        conn.execute(
            "INSERT INTO review_decisions (item_id, action, value, error_category, reviewer, note)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            (item_id, action, Jsonb(stored) if stored else None, category_, reviewer, note),
        )


def add(conn: psycopg.Connection, extraction_id: int, target: str, value: dict, *, page: int, reviewer: str,
        note: str | None = None) -> int:
    """补一个抽取没给出的字段，返回新复核项 id。"""
    require_autocommit(conn)
    with conn.transaction():
        ext = _extraction(conn, extraction_id, " FOR SHARE")
        if ext["status"] != "open":
            raise ReviewError(f"抽取 #{extraction_id} 已组装入库，不能再改")
        manual_value(ext["category"], target, value, doc=ext["doc"], page=page, pages=ext["pages"])
        item_id = conn.execute(
            "INSERT INTO review_items (extraction_id, kind, target, reasons, needs_review)"
            " VALUES (%s,'added',%s,%s,true) RETURNING id", (extraction_id, target, ["added"])).fetchone()[0]
        decide(conn, item_id, "correct", reviewer=reviewer, value=value, page=page, note=note)
    return item_id


# ---------------------------------------------------------------- 组装与写回


def effective_values(conn: psycopg.Connection, extraction_id: int) -> tuple[dict[str, dict], list[str]]:
    """当前有效的 target → 参数值，以及尚未解决的问题。"""
    values: dict[str, dict] = {}
    problems: list[str] = []

    def put(target: str, pv: dict, item_id: int):
        old = values.get(target)
        if old is not None:
            same = all(old.get(k) == pv.get(k) for k in _VALUE_KEYS)
            if not same:
                problems.append(f"{target} 有互相矛盾的值（复核项 #{item_id}）")
                return
        values[target] = pv

    for it in items(conn, extraction_id):
        action = it["action"]
        if it["needs_review"] and action is None:
            problems.append(f"复核项 #{it['id']}（{it['kind']} {it['target'] or ''}）还没有决定")
            continue
        if it["kind"] == "item" and action in (None, "accept"):
            pv = dict(it["proposed"])
            pv["reviewed"] = action == "accept"
            put(it["target"], pv, it["id"])
        elif action == "correct":
            put(it["value"]["target"], it["value"]["value"], it["id"])
    return values, problems


def _merge(old: dict[str, dict], new: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """以原组件为底合并本次的值：未复核的新值不得改动已复核的旧值；值相同时保留原记录（含复核状态）。"""
    merged = dict(old)
    conflicts = []
    for t, pv in new.items():
        prev = old.get(t)
        if prev is not None and all(prev.get(k) == pv.get(k) for k in _VALUE_KEYS):
            if prev.get("reviewed") and not pv.get("reviewed"):
                continue
        elif prev is not None and prev.get("reviewed") and not pv.get("reviewed"):
            conflicts.append(f"{t} 会被未复核的新值改动（原值已复核），须先复核该项")
            continue
        merged[t] = pv
    return merged, conflicts


def plan_hash(component: dict) -> str:
    """组装计划的指纹：确认时须提交同一指纹，保证复核员确认的就是将要写入的内容。"""
    canonical = json.dumps(component, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def commit(conn: psycopg.Connection, extraction_id: int, *, reviewer: str, registry: SourceRegistry,
           vendor: str | None = None, model: str | None = None, confirm: str | None = None,
           update: bool = False, license: str = "params-only", allow_test: bool = False) -> dict:
    """组装组件并写入知识库。

    不带 confirm 时只返回计划（组件、端口坐标系、需确认事项、指纹），不写入；confirm 须等于计划的指纹。
    组件已存在时须 update=True：以原组件为底，只替换本次复核涉及的字段，并要求厂商、型号一致。
    整个过程在一个事务里，锁住该抽取，与复核决定互斥。
    """
    require_autocommit(conn)
    if not (reviewer or "").strip():
        raise ReviewError("必须给出复核人")
    with conn.transaction():
        ext = _extraction(conn, extraction_id, " FOR UPDATE")
        if ext["status"] != "open":
            raise ReviewError(f"抽取 #{extraction_id} 已组装入库")
        if ext["simulated"] and not allow_test:
            raise ReviewError("模拟响应的抽取不得写入正式库")
        values, problems = effective_values(conn, extraction_id)
        vendor = vendor or ext["vendor"]
        model = model or ext["model"]
        if not vendor or not model:
            problems.append("缺少厂商或型号（规格书上读不到时用 --vendor / --model 指定）")
        if problems:
            raise ReviewIncomplete(problems)
        test = ext["doc"] == TEST_DOC
        note = f"由抽取 #{extraction_id}（{ext['doc']}）复核后组装（ADR-0023）"
        try:
            cid = component_id(ext["category"], vendor, model, test=test)
        except ValueError as exc:
            raise ReviewIncomplete([str(exc)]) from exc
        existing = get_component(conn, cid)
        fallback = frames_before = None
        if existing is not None:
            if not update:
                raise ReviewError(f"组件 {cid} 已在库中；确认要更新请加 --update")
            if (existing["vendor"], existing["model"]) != (vendor, model):
                raise ReviewError(f"组件 id {cid} 已属于 {existing['vendor']} {existing['model']}，"
                                  "与本次的厂商、型号不一致（id 冲突）")
            values, conflicts = _merge(values_from_component(existing), values)
            if conflicts:
                raise ReviewIncomplete(conflicts)
            fallback = existing["envelope"]
            frames_before = {p["id"]: p["frame"] for p in existing["ports"] if "frame" in p}
        comp, problems, notes = assemble(ext["category"], vendor, model, values, test=test, note=note,
                                         license=license, fallback_envelope=fallback,
                                         fallback_frames=frames_before)
        if comp is None:
            raise ReviewIncomplete(problems)
        frames = {p["id"]: p["frame"] for p in comp["ports"] if "frame" in p}
        digest = plan_hash(comp)
        plan = {"status": "needs_confirmation", "plan": digest, "frames": frames, "notes": notes,
                "update": existing is not None, "component": comp}
        if confirm != digest:
            if confirm is not None:
                raise ReviewError("确认的指纹与当前计划不一致（复核内容有变化），请重新查看计划")
            return plan
        result = import_component(conn, comp, registry=registry, changed_by=reviewer,
                                  reason=f"复核抽取 #{extraction_id}（{ext['doc']}）", allow_test=allow_test)
        cur = conn.execute(
            "UPDATE extractions SET status='committed', component_id=%s, committed_by=%s, committed_at=now()"
            " WHERE id=%s AND status='open'", (comp["id"], reviewer, extraction_id))
        if cur.rowcount != 1:
            raise ReviewError(f"抽取 #{extraction_id} 状态已变化，未提交")
        return {**result, "frames": frames, "notes": notes}


# ---------------------------------------------------------------- 统计


def stats(conn: psycopg.Connection, extraction_id: int | None = None, *, include_simulated: bool = False) -> dict:
    """按错误分类、target、品类统计当前决定；自动采纳的项记为 auto。默认不计模拟响应。"""
    where = []
    params: list[Any] = []
    if extraction_id is not None:
        where.append("e.id=%s")
        params.append(extraction_id)
    if not include_simulated:
        where.append("NOT e.simulated")
    sql = (
        "SELECT e.category, i.target, i.needs_review, d.error_category FROM review_items i"
        " JOIN extractions e ON e.id = i.extraction_id LEFT JOIN LATERAL ("
        "   SELECT error_category FROM review_decisions WHERE item_id = i.id ORDER BY id DESC LIMIT 1) d ON true"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    out: dict = {"by_error": {}, "by_target": {}, "by_category": {}, "pending": 0}
    for cat, target, needs, err in conn.execute(sql, params).fetchall():
        if err is None:
            if needs:
                out["pending"] += 1
                continue
            err = "auto"
        if err in NOT_LLM_ERRORS:
            continue
        out["by_error"][err] = out["by_error"].get(err, 0) + 1
        out["by_target"].setdefault(target or "?", {}).setdefault(err, 0)
        out["by_target"][target or "?"][err] += 1
        out["by_category"].setdefault(cat, {}).setdefault(err, 0)
        out["by_category"][cat][err] += 1
    return out


# ---------------------------------------------------------------- 命令行


def _print(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None, conn: psycopg.Connection | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kb.review", description="人工复核队列（ADR-0023）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("enqueue", help="抽取结果入队")
    p.add_argument("file")
    p.add_argument("--by", required=True)
    p.add_argument("--allow-test", action="store_true", help="允许测试专用来源（模拟规格书）")
    p = sub.add_parser("list", help="列出待复核项")
    p.add_argument("--extraction", type=int)
    p.add_argument("--all", action="store_true", help="列出该抽取的全部项（含已决定、自动采纳）")
    p = sub.add_parser("show", help="查看一项及其决定历史")
    p.add_argument("item", type=int)
    p = sub.add_parser("decide", help="记录复核决定")
    p.add_argument("item", type=int)
    p.add_argument("action", choices=("accept", "correct", "reject", "dismiss", "absent"))
    p.add_argument("--error", choices=ERROR_CATEGORIES)
    p.add_argument("--value", help='JSON：{"value": 1.2} 或 {"min": 200, "max": 240}')
    p.add_argument("--page", type=int)
    p.add_argument("--target")
    p.add_argument("--note")
    p.add_argument("--by", required=True)
    p = sub.add_parser("add", help="补一个抽取没给出的字段")
    p.add_argument("extraction", type=int)
    p.add_argument("target")
    p.add_argument("--value", required=True)
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--note")
    p.add_argument("--by", required=True)
    p = sub.add_parser("commit", help="组装组件并写入知识库")
    p.add_argument("extraction", type=int)
    p.add_argument("--by", required=True)
    p.add_argument("--vendor")
    p.add_argument("--model")
    p.add_argument("--confirm", metavar="PLAN", help="确认计划：填上一次不带 --confirm 运行时给出的计划指纹")
    p.add_argument("--update", action="store_true", help="组件已在库中时更新（以原组件为底合并）")
    p.add_argument("--license", default="params-only", choices=("params-only", "open", "partner", "standard"))
    p.add_argument("--allow-test", action="store_true")
    p = sub.add_parser("stats", help="错误分类统计")
    p.add_argument("--extraction", type=int)
    p.add_argument("--include-simulated", action="store_true")
    args = parser.parse_args(argv)

    if conn is None:
        from kb.db import connect, migrate

        conn = connect()
        migrate(conn)
    try:
        if args.cmd == "enqueue":
            with open(args.file, encoding="utf-8") as f:
                result = json.load(f)
            eid = enqueue(conn, result, created_by=args.by, registry=SourceRegistry.load(),
                          allow_test=args.allow_test)
            print(f"已入队：抽取 #{eid}，待复核 {len(pending(conn, eid))} 项")
        elif args.cmd == "list":
            if args.all and args.extraction is None:
                raise ReviewError("--all 须与 --extraction 一起用")
            rows = items(conn, args.extraction) if args.all else pending(conn, args.extraction)
            for it in rows:
                printed = it["printed"] or {}
                print(f"#{it['id']}\t{it['kind']}\t{it['target'] or '?'}\t{printed.get('text', '')} "
                      f"{printed.get('unit', '')}\t{','.join(it['reasons'])}\t{it['action'] or ''}")
        elif args.cmd == "show":
            row = conn.execute("SELECT extraction_id FROM review_items WHERE id=%s", (args.item,)).fetchone()
            if row is None:
                raise ReviewError(f"没有复核项 #{args.item}")
            it = next(i for i in items(conn, row[0]) if i["id"] == args.item)
            _print({**it, "history": history(conn, args.item)})
        elif args.cmd == "decide":
            value = json.loads(args.value) if args.value else None
            decide(conn, args.item, args.action, reviewer=args.by, error_category=args.error, value=value,
                   page=args.page, target=args.target, note=args.note)
            print("已记录")
        elif args.cmd == "add":
            item_id = add(conn, args.extraction, args.target, json.loads(args.value), page=args.page,
                          reviewer=args.by, note=args.note)
            print(f"已补充：复核项 #{item_id}")
        elif args.cmd == "commit":
            out = commit(conn, args.extraction, reviewer=args.by, registry=SourceRegistry.load(),
                         vendor=args.vendor, model=args.model, confirm=args.confirm, update=args.update,
                         license=args.license, allow_test=args.allow_test)
            if out.get("status") == "needs_confirmation":
                print(f"组装计划 {out['plan']}（{'更新已有组件' if out['update'] else '新建组件'} "
                      f"{out['component']['id']}）。端口坐标系按品类约定生成，请核对：")
                _print({"frames": out["frames"], "notes": out["notes"]})
                print(f"确认无误后加 --confirm {out['plan']} 再运行一次")
                return 3
            print(f"已写入知识库：{out['id']}（{out['status']}）")
        elif args.cmd == "stats":
            _print(stats(conn, args.extraction, include_simulated=args.include_simulated))
    except (ReviewError, ImportRejected, json.JSONDecodeError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
