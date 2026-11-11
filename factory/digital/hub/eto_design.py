# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139b）：接单、这一单的设计（物料清单与工艺）、设计发布。

- 接单（order_preview）：已报价的作业 → 销售订单提议（单价按报出的那一版，挂 Project，付款计划按配置的里程碑）；
- 设计（eto_design）：这一单专用的物料清单和工艺，按版本存；新物料编号一律以作业号开头；
  check() 是纯函数：工序要在本厂工序表、子件要在物料主数据或本单新物料里、自制件要有物料清单、没有循环……；
- 设计发布（release_preview）：校验通过、作业已接单 → 提议（人确认）→ 桥接在 ERPNext 建新物料、物料清单（带工序）并设为默认；
  发布的那一版存内容指纹、冻结，再改只能出新版本；发布后并入工厂主数据，算料、排产、车间照原样使用；
- require_released()：设计没发布的作业不能算料、下工单。
"""
import copy
import datetime as dt
import hashlib
import json
import re

from factory import data as F
from hub import eto as E

SCHEMA = """
alter table eto_job add column if not exists sales_order text;
create table if not exists eto_design (
    mode         text not null,
    job_no       text not null,
    rev          integer not null,
    spec         jsonb not null,
    status       text not null default 'draft',      -- draft / released
    fingerprint  text,
    created_by   text,
    created_at   timestamptz not null default now(),
    released_by  text,
    released_at  timestamptz,
    primary key (mode, job_no, rev)
);
"""
NEW_KINDS = ("make", "buy", "raw")
ACCEPT_DAYS = 10            # 缺省验收期（天）：验收那一期的计划付款日 = 交期 + 它（清单 eto.accept_days 可改）
KIND_ZH = {"make": "自制件", "buy": "外购件", "raw": "原材料"}


def init(db):
    db.x(SCHEMA)


# ---------------------------------------------------------------- 接单
def order_preview(db, mode, job_no, delivery_date=None, today=None):
    """已报价的作业 → 销售订单提议的内容（单价按报出去的那一版；付款计划按里程碑，金额最后一期补零头）"""
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if j["status"] != "quoted" or not j.get("quotation"):
        raise E.EtoError("报价单还没进 ERPNext（作业要先“已报价”），不能接单")
    if j.get("sales_order") or pending(db, mode, "eto_order", job_no):
        raise E.EtoError("这张作业已经接单（或接单提议在等确认）")
    est = db.one("select lines from eto_estimate where mode=%s and job_no=%s and rev=%s", (mode, job_no, j["quoted_rev"]))
    res = E.compute(est["lines"], j["qty_breaks"] or [j["qty"]])
    b = next(x for x in res["breaks"] if x["qty"] == j["qty"])
    if b["price"] is None:
        raise E.EtoError("报出去的那一版估算现在算不出价格（配置改过？），请重新估算报价")
    today = today or dt.date.today()
    due = dt.date.fromisoformat(str(delivery_date or j["due_date"] or "")[:10]) if (delivery_date or j["due_date"]) else None
    if due is None:
        raise E.EtoError("要写交期")
    if due < today:
        raise E.EtoError("交期 {} 早于今天".format(due.isoformat()))
    cfg = E.config()
    ms = [m for m in cfg.get("milestones") or [] if m.get("pct")]
    # 各期的计划日期：订单确认 = 下单日，设计发布 = 下单日与交期之间，发货 = 交期，验收 = 交期 + 验收期（eto.accept_days，缺省 10 天）。
    # 只是计划日期（开票看里程碑真到了没有）；ERPNext 不许两期同一天，同一天的顺延一天（2026-11-10 演练 42872216480 查出）
    accept = int(cfg.get("accept_days") or ACCEPT_DAYS)
    plan_day = {"order": today, "design": today + (due - today) / 2, "ship": due, "accept": due + dt.timedelta(days=accept)}
    sched, left, last = [], b["price"], None
    for i, m in enumerate(ms):
        amt = round(b["price"] * m["pct"] / 100, 2) if i < len(ms) - 1 else round(left, 2)
        left -= amt
        day = plan_day.get(m["on"], due)
        if last and day <= last:
            day = last + dt.timedelta(days=1)
        last = day
        sched.append({"key": m["key"], "description": m["name"], "invoice_portion": m["pct"], "payment_amount": amt,
                      "on": m["on"], "due_date": day.isoformat()})
    return {"job": {"job_no": job_no, "title": j["title"], "customer": j["customer"], "rev": j["quoted_rev"]},
            "sales_order": {"customer": j["customer"], "item_code": job_no, "qty": j["qty"], "rate": b["unit_price"], "amount": b["price"],
                            "transaction_date": today.isoformat(), "delivery_date": due.isoformat(), "project": E.project_of(j),
                            "quotation": j["quotation"], "payment_schedule": sched}}


def pending(db, mode, action, job_no):
    r = db.one("select proposal_id from ai_proposal where action=%s and mode=%s and status in ('pending','confirmed') "
               "and preview->'job'->>'job_no'=%s order by created_at desc limit 1", (action, mode, job_no))
    return r["proposal_id"] if r else None


# ---------------------------------------------------------------- 设计（纯函数）
def fingerprint(spec):
    core = {"items": spec.get("items") or [], "boms": spec.get("boms") or []}
    return hashlib.sha256(json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def check(spec, job_no):
    """返回 (错误, 提醒)。错误挡发布；提醒（单价、交期没写）由算料标“待确认”，不挡。"""
    errs, warns = [], []
    if not isinstance(spec, dict):
        return ["设计要写成 {items, boms}"], []
    items = spec.get("items") or []
    boms = spec.get("boms") or []
    new = {}
    code_re = re.compile(r"^" + re.escape(job_no) + r"-[A-Za-z0-9][A-Za-z0-9._-]{0,19}$")
    for i, it in enumerate(items):
        at = "新物料第 {} 行".format(i + 1)
        if not isinstance(it, dict):
            errs.append(at + "：格式不对")
            continue
        c = str(it.get("code") or "")
        if not code_re.match(c):
            errs.append("{}：编号要以作业号开头，如 {}-SH".format(at, job_no))
        elif c in new or c in F.ITEMS:
            errs.append("{}：编号 {} 重复".format(at, c))
        if it.get("kind") not in NEW_KINDS:
            errs.append("{}：类别要写 自制件 / 外购件 / 原材料".format(at))
        if not str(it.get("name") or "").strip():
            errs.append(at + "：要写名称")
        if not str(it.get("uom") or "").strip():
            errs.append(at + "：要写单位")
        if it.get("price") not in (None, "") and (_num(it["price"]) is None or _num(it["price"]) < 0):
            errs.append(at + "：单价要写不小于 0 的数")
        if it.get("kind") in ("buy", "raw"):
            if it.get("price") in (None, ""):
                warns.append("{} 没有单价（成本按未知）".format(c))
            sup = it.get("supplier")
            if sup and sup not in F.SUPPLIERS:
                errs.append("{}：供应商 {} 不在供应商表里".format(at, sup))
            elif not sup or F.SUPPLIERS[sup].get("lead") is None:
                warns.append("{} 没有供应商或交期（算料标“交期待确认”）".format(c))
        new[c] = it
    by_item = {}
    for i, b in enumerate(boms):
        at = "物料清单第 {} 组".format(i + 1)
        if not isinstance(b, dict):
            errs.append(at + "：格式不对")
            continue
        it = b.get("item")
        if it != job_no and (it not in new or new[it].get("kind") != "make"):
            errs.append("{}：父件 {} 要是作业号或本单的新自制件".format(at, it))
        if it in by_item:
            errs.append("{}：父件 {} 有两组物料清单".format(at, it))
        by_item[it] = b
        rt = b.get("routing") or []
        if not rt:
            errs.append("{}：{} 要有工艺（至少一道工序）".format(at, it))
        for k, step in enumerate(rt):
            op, mins = (list(step) + [None, None])[:2] if isinstance(step, (list, tuple)) else (None, None)
            if op not in F.OPERATIONS:
                errs.append("{} 第 {} 道工序 {} 不在本厂工序表里".format(it, k + 1, op))
            if _num(mins) is None or _num(mins) <= 0:
                errs.append("{} 第 {} 道工序要写每件分钟（大于 0）".format(it, k + 1))
        comps = b.get("components") or []
        if not comps:
            errs.append("{}：{} 要有子件".format(at, it))
        seen = set()
        for k, cq in enumerate(comps):
            c, q = (list(cq) + [None, None])[:2] if isinstance(cq, (list, tuple)) else (None, None)
            if c not in F.ITEMS and c not in new:
                errs.append("{} 的子件 {} 不在物料主数据里，也不是本单新物料".format(it, c))
            if c == job_no:
                errs.append("{} 的子件不能是作业本身".format(it))
            if c in seen:
                errs.append("{} 的子件 {} 写了两次".format(it, c))
            seen.add(c)
            if _num(q) is None or _num(q) <= 0:
                errs.append("{} 的子件 {} 用量要大于 0".format(it, c))
    if job_no not in by_item:
        errs.append("要有作业 {} 本身的物料清单".format(job_no))
    for c, it in new.items():
        if it.get("kind") == "make" and c not in by_item:
            errs.append("新自制件 {} 要有物料清单和工艺".format(c))
        if it.get("kind") in ("buy", "raw") and c in by_item:
            errs.append("{} 是{}，不该有物料清单".format(c, KIND_ZH[it["kind"]]))
    used = {(list(cq) + [None])[0] for b in by_item.values() for cq in (b.get("components") or []) if isinstance(cq, (list, tuple))}
    for c in new:
        if c not in used:
            warns.append("新物料 {} 没有用在任何物料清单里".format(c))
    # 循环：只可能在本单新自制件之间
    graph = {p: [(list(cq) + [None])[0] for cq in (b.get("components") or []) if isinstance(cq, (list, tuple))] for p, b in by_item.items()}

    def cyc(n, path):
        if n in path:
            return True
        return any(cyc(m, path | {n}) for m in graph.get(n, []) if m in graph)
    if not errs and cyc(job_no, frozenset()):
        errs.append("物料清单有循环（一个件直接或间接用到了自己）")
    return errs, warns


def bottom_up(spec):
    """物料清单按“子件先建”排序（桥接按这个顺序建 BOM）"""
    by = {b["item"]: b for b in spec.get("boms") or []}
    out, seen = [], set()

    def visit(n):
        if n in seen or n not in by:
            return
        seen.add(n)
        for c, _ in by[n]["components"]:
            visit(c)
        out.append(by[n])
    for n in list(by):
        visit(n)
    return out


def from_estimate(job, lines):
    """照估算起草设计：估算照现有产品起草的，取那个产品的顶层物料清单和工艺；否则估算里的材料、外购件当子件，工序当工艺。
    外协行另记（第 139c 段转采购）。估算员改动的地方由设计员在设计里改（例如把要改的件“复制为新件”）。"""
    jn = job["job_no"]
    prods = [str(x.get("source") or "")[8:] for x in lines if str(x.get("source") or "").startswith("product:")]
    base = max(set(prods), key=prods.count) if prods else None
    items, outside = [], [{"desc": x.get("desc"), "unit_price": x.get("unit_price"), "lead_days": x.get("lead_days")}
                          for x in lines if x.get("kind") == "outside"]
    if base and base in F.BOMS:
        rt, comps = F.BOMS[base]
        top = {"item": jn, "routing": [list(s) for s in F.ROUTINGS[rt]], "components": [[c, q] for c, q in comps]}
        note = "照现有产品 {} 的顶层物料清单和工艺起草；要改的件用“复制为新件”，再改它的工艺和子件。".format(base)
    else:
        comps, n = [], 0
        for x in lines:
            if x.get("kind") not in ("material", "buyout") or not x.get("qty_per"):
                continue
            code = (x.get("item_code") or "").strip()
            if code in F.ITEMS:
                comps.append([code, x["qty_per"]])
                continue
            n += 1
            code = "{}-{:02d}".format(jn, n)
            items.append({"code": code, "name": x.get("desc") or code, "kind": "raw" if x["kind"] == "material" else "buy",
                          "uom": x.get("uom") or "Nos", "price": x.get("unit_price")})
            comps.append([code, x["qty_per"]])
        top = {"item": jn, "routing": [[x["op"], x["run_min"]] for x in lines if x.get("kind") == "operation" and x.get("op") and x.get("run_min")],
               "components": comps}
        note = "照估算行起草：材料、外购件当子件，工序当工艺（每件分钟取估算的单件工时）。"
    return {"items": items, "boms": [top], "outside": outside, "note": note}


def copy_as_new(spec, job_no, parent, code, suffix):
    """把父件里的一个现有自制件“复制为新件”：新编号 = 作业号-后缀，物料清单和工艺照抄，父件改用新件"""
    spec = copy.deepcopy(spec)
    new = "{}-{}".format(job_no, suffix)
    if code not in F.BOMS:
        raise E.EtoError("{} 没有物料清单，不是自制件，不能复制".format(code))
    if any(i["code"] == new for i in spec["items"]) or new in F.ITEMS:
        raise E.EtoError("编号 {} 已经有了".format(new))
    pb = next((b for b in spec["boms"] if b["item"] == parent), None)
    if pb is None or not any(c == code for c, _ in pb["components"]):
        raise E.EtoError("{} 的子件里没有 {}".format(parent, code))
    nm, uom = F.ITEMS[code][0], F.ITEMS[code][2]
    spec["items"].append({"code": new, "name": "{}（{} 专用）".format(nm, job_no), "kind": "make", "uom": uom, "from": code})
    rt, comps = F.BOMS[code]
    spec["boms"].append({"item": new, "routing": [list(s) for s in F.ROUTINGS[rt]], "components": [[c, q] for c, q in comps]})
    pb["components"] = [[new if c == code else c, q] for c, q in pb["components"]]
    return spec


# ---------------------------------------------------------------- 设计（数据库）
def _row(r):
    if not r:
        return None
    d = dict(r)
    for k in ("created_at", "released_at"):
        d[k] = d[k].isoformat() if d.get(k) else None
    return d


def latest(db, mode, job_no):
    return _row(db.one("select * from eto_design where mode=%s and job_no=%s order by rev desc limit 1", (mode, job_no)))


def released(db, mode, job_no):
    return _row(db.one("select * from eto_design where mode=%s and job_no=%s and status='released' order by rev desc limit 1",
                       (mode, job_no)))


def revisions(db, mode, job_no):
    return [_row(r) for r in db.q("select rev, status, fingerprint, created_by, created_at, released_by, released_at from eto_design "
                                  "where mode=%s and job_no=%s order by rev", (mode, job_no))]


def save(db, mode, job_no, spec, user):
    """存设计：最新一版没发布就覆盖它；已发布（冻结）就出新版本"""
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if pending(db, mode, "eto_release", job_no):
        raise E.EtoError("设计发布提议还在等确认，确认或否决之后再改")
    if not isinstance(spec, dict):
        raise E.EtoError("设计要写成 {items, boms}")
    spec = {"items": spec.get("items") or [], "boms": spec.get("boms") or [], "outside": spec.get("outside") or [],
            "note": str(spec.get("note") or "")[:2000]}
    cur = latest(db, mode, job_no)
    rev = cur["rev"] if cur and cur["status"] == "draft" else (cur["rev"] + 1 if cur else 1)
    db.x("insert into eto_design (mode, job_no, rev, spec, created_by) values (%s,%s,%s,%s,%s) "
         "on conflict (mode, job_no, rev) do update set spec=excluded.spec, created_by=excluded.created_by, created_at=now()",
         (mode, job_no, rev, json.dumps(spec, ensure_ascii=False), user))
    return rev


def detail(db, mode, job_no):
    j = E.job(db, mode, job_no)
    if not j:
        return None
    d = latest(db, mode, job_no)
    errs, warns = check(d["spec"], job_no) if d else ([], [])
    return {"design": d, "revisions": revisions(db, mode, job_no), "errors": errs, "warnings": warns,
            "pending_proposal": pending(db, mode, "eto_release", job_no), "affected": affected(db, mode, job_no),
            "fingerprint_now": fingerprint(d["spec"]) if d else None}


def release_preview(db, mode, job_no):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if not j.get("sales_order"):
        raise E.EtoError("作业还没接单（没有销售订单），设计不能发布")
    if pending(db, mode, "eto_release", job_no):
        raise E.EtoError("已经有一份设计发布提议在等确认")
    d = latest(db, mode, job_no)
    if not d:
        raise E.EtoError("还没有设计")
    if d["status"] == "released":
        raise E.EtoError("第 {} 版设计已经发布；要改先改设计（会出新版本）".format(d["rev"]))
    errs, warns = check(d["spec"], job_no)
    if errs:
        raise E.EtoError("设计没通过检查：" + "；".join(errs[:6]))
    spec = d["spec"]
    fp = fingerprint(spec)
    items = []
    for it in spec["items"]:
        sup = it.get("supplier")
        items.append({"code": it["code"], "name": it["name"], "kind": it["kind"], "uom": it["uom"], "price": _num(it.get("price")),
                      "item_group": F.KIND_GROUP[it["kind"]], "supplier": F.SUPPLIERS[sup]["name"] if sup in F.SUPPLIERS else None,
                      "lead": F.SUPPLIERS[sup].get("lead") if sup in F.SUPPLIERS else None})
    boms, uoms = [], {i["code"]: i["uom"] for i in spec["items"]}
    for b in bottom_up(spec):
        boms.append({"item": b["item"], "components": [{"item_code": c, "qty": float(q), "new": c in uoms, "uom": uoms.get(c) or F.ITEMS[c][2]}
                                                        for c, q in b["components"]],
                     "operations": [{"operation": op, "workstation": F.OPERATIONS[op], "time_in_mins": float(m),
                                     "hour_rate": float(sum(F.WORKSTATIONS[F.OPERATIONS[op]][1]))} for op, m in b["routing"]]})
    return {"job": {"job_no": job_no, "title": j["title"], "rev": d["rev"], "project": E.project_of(j)}, "fingerprint": fp, "items": items, "boms": boms,
            "warnings": warns, "affected": affected(db, mode, job_no), "outside": spec.get("outside") or []}


def affected(db, mode, job_no):
    """已经挂在这个作业上、还没完的工单、请购单、采购单（设计改版时要人逐条处理）"""
    out, proj = [], E.project_of(E.job(db, mode, job_no))
    for dt_ in ("Work Order", "Material Request", "Purchase Order"):
        for m in db.erp_docs(dt_, mode):
            d = m["data"]
            if d.get("project") == proj and d.get("docstatus") != 2 and d.get("status") not in ("Completed", "Closed", "Cancelled", "Stopped"):
                out.append({"doctype": dt_, "name": d["name"], "status": d.get("status")})
    return out


# ---------------------------------------------------------------- 发布后并入工厂主数据
def merge(job_no, title, spec):
    """发布的设计并入工厂主数据（ITEMS、BOMS、ROUTINGS），算料、排产、车间照原样使用"""
    F.ITEMS[job_no] = (title, "fg", "Nos", None, None, None, "按单设计 " + job_no)
    for it in spec.get("items") or []:
        F.ITEMS[it["code"]] = (it["name"], it["kind"], it["uom"], _num(it.get("price")), it.get("supplier"), None, "按单设计 " + job_no)
    for b in spec.get("boms") or []:
        rt = "RT-" + b["item"]
        F.ROUTINGS[rt] = [(op, float(m)) for op, m in b["routing"]]
        F.BOMS[b["item"]] = (rt, [(c, float(q)) for c, q in b["components"]])


def load_all(db):
    """枢纽启动时把已发布的设计并回主数据（教学、生产两种模式的都并：编号带作业号，不会冲突）"""
    for r in db.q("select distinct on (d.mode, d.job_no) d.job_no, d.spec, j.title from eto_design d join eto_job j "
                  "on j.mode=d.mode and j.job_no=d.job_no where d.status='released' order by d.mode, d.job_no, d.rev desc"):
        merge(r["job_no"], r["title"], r["spec"])


def is_job(db, mode, item):
    if not db.one("select to_regclass('eto_job') is not null as x")["x"]:          # 没建过按单设计的表（老库、别的测试库）
        return False
    return bool(db.one("select 1 as x from eto_job where mode=%s and job_no=%s", (mode, item)))


def require_released(db, mode, item):
    """按单设计的作业：设计没发布不能算料、下工单"""
    if item not in F.BOMS and is_job(db, mode, item) and not released(db, mode, item):
        raise E.EtoError("作业 {} 的设计还没发布，不能算料、下工单".format(item))


def on_proposal_done(db, action, preview, mode):
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    if action == "eto_order":
        jn = pv["job"]["job_no"]
        r = db.one("select result from ai_proposal where action='eto_order' and mode=%s and status='executed' "
                   "and preview->'job'->>'job_no'=%s order by decided_at desc nulls last limit 1", (mode, jn))
        so = next((n for d_, n in ((r or {}).get("result") or {}).get("created") or [] if d_ == "Sales Order"), None)
        db.x("update eto_job set status='ordered', sales_order=%s where mode=%s and job_no=%s", (so, mode, jn))
    elif action == "eto_release":
        jn, rev = pv["job"]["job_no"], pv["job"]["rev"]
        row = db.one("update eto_design set status='released', fingerprint=%s, released_at=now(), "
                     "released_by=(select confirmed_by from ai_proposal where action='eto_release' and mode=%s and status='executed' "
                     "and preview->'job'->>'job_no'=%s order by decided_at desc nulls last limit 1) "
                     "where mode=%s and job_no=%s and rev=%s returning spec", (pv["fingerprint"], mode, jn, mode, jn, rev))
        j = E.job(db, mode, jn)
        if row and j:
            merge(jn, j["title"], row["spec"])


def reset(db, mode):
    db.x("delete from eto_design where mode=%s", (mode,))
