# -*- coding: utf-8 -*-
"""按单设计（ETO，第 150 轮 150a）：设计变更处理。

设计出新版本并发布后，挂在作业上、还没完的工单、请购单、采购单逐条列出并给建议（确定性规则），人逐条选，
一份提议交桥接在 ERPNext 里执行（取消 / 停止 / 改量 / 关闭），“照用”只在平台记下。

- 比对：上一版发布的设计（旧）和最新发布的设计（新）。每个件的“物料清单 + 工艺”有没有变；按作业件数展开的需求量有没有减。
- 工单（用的是旧版物料清单的）：件没变 → 照用；变了、没开工 → 换新版（取消，再算料按新版下）；
  变了、已开工 → 照用到完工（已做的件按旧版，记让步），可改选“停止”（再算料按新版补，已花的工序成本记变更损失）；
  新版不再需要这个件 → 没开工取消、已开工停止。
- 请购单 / 采购单：只看需求减少的物料（新需求 < 旧需求），按减少的量从请购单开始、再从最新的采购单往前扣，不扣到已到货以下；
  请购单要扣 → 取消（再算料按新需求补请）；采购单 → 改量，全扣光且没到货 → 取消，扣光但有到货 → 关闭；
  已到货、新版用不上的：本单专用件记变更损失（到货数 × 单价，单价缺为未知），通用件转普通库存、不算损失。
- 没处理完的变更挡住：再算料、再发布设计。
纯函数：bom_map、changed、explode、suggest；读数据库的：plan、preview、record。
"""
import datetime as dt
import json

from factory import data as F
from hub import eto as E
from hub import eto_design as ED

SCHEMA = """
create table if not exists eto_change (
    mode         text not null,
    job_no       text not null,
    rev          integer not null,
    doctype      text not null,
    name         text not null,
    action       text not null,
    lines        jsonb,
    loss         numeric,
    loss_unknown boolean not null default false,
    note         text,
    decided_by   text,
    proposal_id  text,
    decided_at   timestamptz not null default now(),
    primary key (mode, job_no, rev, doctype, name)
);
"""
ACTION_ZH = {"keep": "照用", "renew": "换新版", "cancel": "取消", "stop": "停止", "qty": "改量", "close": "关闭"}
DONE = ("Completed", "Closed", "Cancelled", "Stopped")


def init(db):
    db.x(SCHEMA)


# ---------------------------------------------------------------- 纯函数
def bom_map(spec, base=None):
    """工厂主数据的物料清单，叠上一版设计里的（件 → (工艺 [(工序, 分钟)], 子件 [(件, 用量)])）"""
    base = F.BOMS if base is None else base
    m = {it: ([tuple(s) for s in F.ROUTINGS[rt]], [tuple(c) for c in comps]) for it, (rt, comps) in base.items() if rt in F.ROUTINGS}
    for b in (spec or {}).get("boms") or []:
        m[b["item"]] = ([(op, float(mn)) for op, mn in b["routing"]], [(c, float(q)) for c, q in b["components"]])
    return m


def changed(old, new, item):
    """这个件在新旧两版里的物料清单或工艺是否不同（不在新版里也算变了）"""
    return old.get(item) != new.get(item)


def explode(top, qty, boms):
    """按件数展开的总需求（不扣库存）：件 → 数量"""
    need = {}

    def walk(n, q, depth=0):
        if depth > 30:
            return
        need[n] = need.get(n, 0.0) + q
        for c, per in (boms.get(n) or ((), ()))[1]:
            walk(c, per * q, depth + 1)
    walk(top, float(qty))
    return need


def suggest(job_no, wos, buys, need_old, need_new, changed_items):
    """建议（纯函数）。
    wos：用旧版物料清单、还没完的工单 [{name, item, qty, started, spent}]（spent = 已花的工序成本，可为 None）；
    buys：挂作业的请购单、采购单（请购单在前，采购单按新到旧）[{doctype, name, lines: [{item_code, qty, received, rate}]}]；
    返回 [{doctype, name, item, suggest, options, reason, lines?, loss, loss_unknown, needs}]"""
    own = lambda c: c == job_no or str(c).startswith(job_no + "-")  # noqa: E731
    rows = []
    for w in wos:
        it, gone = w["item"], need_new.get(w["item"], 0) <= 0
        if gone:
            s, opts = ("stop", ["stop", "keep"]) if w["started"] else ("cancel", ["cancel", "keep"])
            why = "新版不再用这个件" + ("，已开工：停止（已花的工序成本记变更损失）" if w["started"] else "：取消")
        elif it in changed_items:
            if w["started"]:
                s, opts = "keep", ["keep", "stop"]
                why = "这个件新版改了，已开工：按旧版做完（记让步）；要按新版做就选停止，再算料补新版工单"
            else:
                s, opts = "renew", ["renew", "keep"]
                why = "这个件新版改了，还没开工：取消，再算料按新版下工单"
        else:
            s, opts, why = "keep", ["keep"], "这个件新版没变"
        stop_loss = w.get("spent")
        rows.append({"doctype": "Work Order", "name": w["name"], "item": it, "qty": w["qty"], "suggest": s, "options": opts, "reason": why,
                     "loss": {"stop": stop_loss, "cancel": 0.0, "renew": 0.0, "keep": 0.0}, "needs": True})
    # 请购、采购：只扣需求减少的量
    cut = {}
    for c in set(need_old) | set(need_new):
        d = need_old.get(c, 0.0) - need_new.get(c, 0.0)
        if d > 1e-9:
            cut[c] = need_old.get(c, 0.0) if need_new.get(c, 0.0) <= 0 else d
    for b in buys:
        new_lines, any_cut, loss, unknown = [], False, 0.0, False
        for ln in b["lines"]:
            c, q, rec = ln["item_code"], float(ln["qty"]), float(ln.get("received") or 0)
            want = cut.get(c, 0.0)
            take = min(want, q)                       # 这一行能扣的量
            if take <= 1e-9:
                new_lines.append(dict(ln, new_qty=q))
                continue
            any_cut = True
            cut[c] = want - take
            nq = q - take
            if nq < rec:                              # 不扣到已到货以下；多出的到货
                extra = rec - nq
                nq = rec
                if own(c):
                    if ln.get("rate") is None:
                        unknown = True
                    else:
                        loss += extra * float(ln["rate"])
            new_lines.append(dict(ln, new_qty=round(nq, 4)))
        if not any_cut:
            rows.append({"doctype": b["doctype"], "name": b["name"], "item": ", ".join(ln["item_code"] for ln in b["lines"]),
                         "suggest": "keep", "options": ["keep"], "reason": "用量没减", "loss": {"keep": 0.0}, "needs": False})
            continue
        received_any = any(float(ln.get("received") or 0) > 0 for ln in b["lines"])
        all_zero = all(ln["new_qty"] <= 1e-9 for ln in new_lines)
        if b["doctype"] == "Material Request":
            s, opts, why = "cancel", ["cancel", "keep"], "新版用量减少：取消这张请购，再算料按新需求补请"
        elif all_zero and not received_any:
            s, opts, why = "cancel", ["cancel", "keep"], "新版不再用这些料，也还没到货：取消"
        elif all(abs(ln["new_qty"] - float(ln.get("received") or 0)) <= 1e-9 for ln in new_lines):
            s, opts, why = "close", ["close", "keep"], "新版用量减少，已到的够了：关闭剩下没到的"
        else:
            s, opts, why = "qty", ["qty", "keep"], "新版用量减少：改量（不少于已到货）"
        lines = [{"item_code": ln["item_code"], "qty": float(ln["qty"]), "received": float(ln.get("received") or 0),
                  "new_qty": ln["new_qty"], "rate": ln.get("rate"), "own": own(ln["item_code"])} for ln in new_lines]
        lv = None if unknown else round(loss, 2)
        rows.append({"doctype": b["doctype"], "name": b["name"], "item": ", ".join(ln["item_code"] for ln in b["lines"]),
                     "suggest": s, "options": opts, "reason": why, "lines": lines,
                     "loss": {k: (lv if k != "keep" else 0.0) for k in opts}, "loss_unknown": unknown, "needs": True})
    return rows


# ---------------------------------------------------------------- 读数据库
def _released_revs(db, mode, job_no):
    return [r for r in ED.revisions(db, mode, job_no) if r["status"] == "released"]


def _spec(db, mode, job_no, rev):
    r = db.one("select spec from eto_design where mode=%s and job_no=%s and rev=%s", (mode, job_no, rev))
    return r["spec"] if r else None


def plan(db, mode, job_no):
    """当前这一次设计变更的处理表：{rev, from_rev, rows, open}；没有变更（只发布过一版）时 rows 为空"""
    from hub import eto_exec as EX
    from hub import mrp
    from hub.kpi import Overview
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    revs = _released_revs(db, mode, job_no)
    if len(revs) < 2:
        return {"rev": revs[-1]["rev"] if revs else None, "from_rev": None, "rows": [], "open": 0, "decided": {}}
    new_r, old_r = revs[-1], revs[-2]
    new_spec, old_spec = _spec(db, mode, job_no, new_r["rev"]), _spec(db, mode, job_no, old_r["rev"])
    old_b, new_b = bom_map(old_spec), bom_map(new_spec)
    need_old, need_new = explode(job_no, j["qty"], old_b), explode(job_no, j["qty"], new_b)
    ch = {i for i in set(old_b) | set(new_b) if changed(old_b, new_b, i)}
    proj = E.project_of(j)
    o = Overview(db, None, mode)
    wos = []
    for w in EX.work_orders(db, mode, job_no):
        if w["status"] in DONE or w["current_design"] is not False:
            continue
        spent = None
        if w["started"]:
            c = mrp.wo_cost(db, w["name"], mode)
            spent = round(c["actual_cost"], 2) if c else 0.0
        wos.append({"name": w["name"], "item": w["item"], "qty": w["qty"], "started": w["started"], "spent": spent})
    buys = []
    for r in o.mrs:
        d = r["data"]
        if d.get("project") == proj and d.get("docstatus") == 1 and d.get("status") not in ("Ordered", "Stopped", "Cancelled", "Transferred"):
            buys.append({"doctype": "Material Request", "name": d["name"], "created": d.get("creation") or "",
                         "lines": [{"item_code": it["item_code"], "qty": float(it.get("qty", 0)), "received": 0.0, "rate": None}
                                   for it in d.get("items") or []]})
    pos = []
    for p in o.pos:
        d = p["data"]
        if d.get("project") == proj and d.get("docstatus") == 1 and d.get("status") not in ("Closed", "Cancelled", "Completed"):
            pos.append({"doctype": "Purchase Order", "name": d["name"], "created": d.get("transaction_date") or d.get("creation") or "",
                        "lines": [{"item_code": it["item_code"], "qty": float(it.get("qty", 0)), "received": float(it.get("received_qty") or 0),
                                   "rate": it.get("rate")} for it in d.get("items") or []]})
    pos.sort(key=lambda x: (x["created"], x["name"]), reverse=True)
    rows = suggest(job_no, wos, buys + pos, need_old, need_new, ch)
    dec = decided(db, mode, job_no, new_r["rev"])
    for r in rows:
        r["decided"] = dec.get((r["doctype"], r["name"]))
    return {"rev": new_r["rev"], "from_rev": old_r["rev"], "rows": rows, "changed_items": sorted(ch),
            "open": sum(1 for r in rows if r["needs"] and not r["decided"]), "decided": len(dec),
            "pending_proposal": ED.pending(db, mode, "eto_change", job_no)}


def decided(db, mode, job_no, rev):
    return {(r["doctype"], r["name"]): {"action": r["action"], "by": r["decided_by"], "loss": None if r["loss"] is None else float(r["loss"]),
                                        "loss_unknown": r["loss_unknown"]}
            for r in db.q("select * from eto_change where mode=%s and job_no=%s and rev=%s", (mode, job_no, rev))}


def open_count(db, mode, job_no):
    """还没处理的变更行数（挡住再算料、再发布）"""
    if not db.one("select to_regclass('eto_change') is not null as x")["x"]:
        return 0
    if len(_released_revs(db, mode, job_no)) < 2:
        return 0
    p = plan(db, mode, job_no)
    return p["open"]


def kept(db, mode, job_no, work_order):
    """这张工单在设计变更处理里选了“照用”"""
    if not db.one("select to_regclass('eto_change') is not null as x")["x"]:
        return False
    return bool(db.one("select 1 as x from eto_change where mode=%s and job_no=%s and doctype='Work Order' and name=%s and action='keep'",
                       (mode, job_no, work_order)))


def preview(db, mode, job_no, choices, who):
    """人逐条选好 → 提议的内容。choices：{"Work Order/MFG-WO-…": "renew", …}；没选的按建议"""
    p = plan(db, mode, job_no)
    if not p["rows"]:
        raise E.EtoError("没有要处理的设计变更（只发布过一版，或旧单据都已处理）")
    if p.get("pending_proposal"):
        raise E.EtoError("已经有一份变更处理提议在等确认")
    choices = choices or {}
    acts = []
    for r in p["rows"]:
        if not r["needs"] or r["decided"]:
            continue
        a = choices.get("{}/{}".format(r["doctype"], r["name"])) or r["suggest"]
        if a not in r["options"]:
            raise E.EtoError("{} {} 只能选：{}".format(r["doctype"], r["name"], "、".join(ACTION_ZH[o] for o in r["options"])))
        loss = r["loss"].get(a)
        acts.append({"doctype": r["doctype"], "name": r["name"], "item": r["item"], "action": a, "action_zh": ACTION_ZH[a],
                     "lines": [{"item_code": ln["item_code"], "qty": ln["new_qty"]} for ln in r.get("lines") or []] if a == "qty" else None,
                     "loss": loss, "loss_unknown": bool(r.get("loss_unknown")) and a != "keep", "reason": r["reason"]})
    if not acts:
        raise E.EtoError("这次变更的单据都已处理")
    j = E.job(db, mode, job_no)
    return {"job": {"job_no": job_no, "title": j["title"], "project": E.project_of(j), "rev": p["rev"], "from_rev": p["from_rev"]},
            "actions": acts, "who": who}


def record(db, mode, pv, pid=None):
    for a in pv["actions"]:
        db.x("insert into eto_change (mode, job_no, rev, doctype, name, action, lines, loss, loss_unknown, note, decided_by, proposal_id) "
             "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) on conflict (mode, job_no, rev, doctype, name) do update set "
             "action=excluded.action, lines=excluded.lines, loss=excluded.loss, loss_unknown=excluded.loss_unknown, proposal_id=excluded.proposal_id, "
             "decided_at=now()",
             (mode, pv["job"]["job_no"], pv["job"]["rev"], a["doctype"], a["name"], a["action"],
              json.dumps(a.get("lines"), ensure_ascii=False) if a.get("lines") else None, a.get("loss"), bool(a.get("loss_unknown")),
              a.get("reason"), pv.get("who"), pid))


def loss(db, mode, job_no):
    """变更损失合计：{amount, unknown, rows}（金额缺时 amount 为 None）"""
    if not db.one("select to_regclass('eto_change') is not null as x")["x"]:
        return {"amount": 0.0, "unknown": False, "rows": []}
    rows = [dict(r) for r in db.q("select rev, doctype, name, action, loss, loss_unknown, decided_by, decided_at from eto_change "
                                  "where mode=%s and job_no=%s order by rev, decided_at", (mode, job_no))]
    for r in rows:
        r["loss"] = None if r["loss"] is None else float(r["loss"])
        r["decided_at"] = r["decided_at"].isoformat() if isinstance(r["decided_at"], dt.datetime) else r["decided_at"]
    unknown = any(r["loss_unknown"] or (r["loss"] is None and r["action"] != "keep") for r in rows)
    amt = round(sum(r["loss"] or 0 for r in rows), 2)
    return {"amount": None if unknown else amt, "unknown": unknown, "rows": rows}


def on_proposal_done(db, action, preview, mode):
    if action != "eto_change":
        return
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    r = db.one("select proposal_id, confirmed_by from ai_proposal where action='eto_change' and mode=%s and status='executed' "
               "and preview->'job'->>'job_no'=%s order by decided_at desc nulls last limit 1", (mode, pv["job"]["job_no"]))
    record(db, mode, dict(pv, who=(r or {}).get("confirmed_by") or pv.get("who")), (r or {}).get("proposal_id"))


def reset(db, mode):
    if db.one("select to_regclass('eto_change') is not null as x")["x"]:
        db.x("delete from eto_change where mode=%s", (mode,))
