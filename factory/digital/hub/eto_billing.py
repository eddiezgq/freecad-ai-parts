# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139g）：按里程碑分期开票、客户验收、作业收付与毛利。

- 里程碑（配置 eto.milestones）达成与否是确定性判断：订单确认 = 有销售订单；设计发布 = 有发布的设计；发货 = 有发货单；验收 = 登记了客户验收；
- 到了的那一期才能起草发票：提议（预览期次、比例、金额）→ 人确认 → 桥接按销售订单开 ERPNext 销售发票（一期一行，金额 = 本期金额）；
  每期只开一次；各期金额在接单时就定了（存下来的付款计划），最后一期补零头，加起来等于订单金额；
- 作业的销售订单不走“工单做完自动开票”（finance.ready_orders 跳过），免得整单金额开两遍；
- 作业收付与毛利：订单金额、已开票、已收款（ERPNext 发票的未付金额）、实际成本（139e，外协按采购单价）、毛利。
"""
import datetime as dt
import json

from hub import eto as E
from hub import eto_design as ED

SCHEMA = """
alter table eto_job add column if not exists payment_schedule jsonb;
create table if not exists eto_accept (
    mode        text not null,
    job_no      text not null,
    day         date not null,
    note        text,
    who         text,
    created_at  timestamptz not null default now(),
    primary key (mode, job_no)
);
create table if not exists eto_invoice (
    mode        text not null,
    job_no      text not null,
    key         text not null,
    amount      numeric not null,
    proposal_id text,
    invoice     text,
    created_at  timestamptz not null default now(),
    primary key (mode, job_no, key)
);
"""
ON_ZH = {"order": "订单确认", "design": "设计发布", "ship": "发货", "accept": "客户验收"}


def init(db):
    db.x(SCHEMA)


def is_eto_order(db, mode, so_name):
    """这张销售订单是不是按单设计的作业的（不走自动开票）"""
    if not db.one("select to_regclass('eto_job') is not null as x")["x"]:
        return False
    return bool(db.one("select 1 as x from eto_job where mode=%s and sales_order=%s", (mode, so_name)))


def schedule_of(db, mode, j):
    """接单时定下的付款计划（接单提议执行时存进作业）；本段上线前接的单没存，取那张执行了的接单提议里的"""
    if j.get("payment_schedule"):
        return j["payment_schedule"]
    r = db.one("select preview from ai_proposal where action='eto_order' and mode=%s and status='executed' and preview->'job'->>'job_no'=%s "
               "order by decided_at desc nulls last limit 1", (mode, j["job_no"]))
    pv = (r or {}).get("preview") or {}
    if isinstance(pv, str):
        pv = json.loads(pv)
    return (pv.get("sales_order") or {}).get("payment_schedule") or []


def reached(db, mode, j):
    """各里程碑到了没有（纯粹按事实）"""
    acc = db.one("select day from eto_accept where mode=%s and job_no=%s", (mode, j["job_no"]))
    return {"order": bool(j.get("sales_order")), "design": bool(ED.released(db, mode, j["job_no"])),
            "ship": bool(j.get("delivery_note")), "accept": bool(acc)}


def milestones(db, mode, job_no):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    sched = schedule_of(db, mode, j)
    hit = reached(db, mode, j)
    inv = {r["key"]: r for r in db.q("select * from eto_invoice where mode=%s and job_no=%s", (mode, job_no))}
    out = []
    for m in sched:
        i = inv.get(m["key"])
        if i and i["invoice"]:
            st = "invoiced"
        elif i and i["proposal_id"]:
            p = db.one("select status from ai_proposal where proposal_id=%s", (i["proposal_id"],))
            st = "drafted" if p and p["status"] in ("pending", "confirmed") else ("invoiced" if p and p["status"] == "executed" else "due")
        else:
            st = "due" if hit.get(m["on"]) else "waiting"
        out.append(dict(m, on_name=ON_ZH.get(m["on"], m["on"]), reached=hit.get(m["on"], False), state=st,
                        invoice=(i or {}).get("invoice"), proposal_id=(i or {}).get("proposal_id")))
    return out


def invoice_preview(db, mode, job_no, key, today=None):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if not j.get("sales_order"):
        raise E.EtoError("作业还没接单")
    ms = {m["key"]: m for m in milestones(db, mode, job_no)}
    m = ms.get(key)
    if not m:
        raise E.EtoError("付款计划里没有这一期")
    if m["state"] == "waiting":
        raise E.EtoError("这一期的里程碑（{}）还没到，不能开票".format(m["on_name"]))
    if m["state"] in ("drafted", "invoiced"):
        raise E.EtoError("这一期已经开过票（或开票提议在等确认）")
    today = today or dt.date.today()
    return {"job": {"job_no": job_no, "title": j["title"], "customer": j["customer"], "project": E.project_of(j)},
            "sales_order": j["sales_order"], "key": key, "description": m["description"], "pct": m["invoice_portion"],
            "amount": float(m["payment_amount"]), "posting_date": today.isoformat(),
            "due_date": max(today, dt.date.fromisoformat(m["due_date"])).isoformat()}


def mark_invoicing(db, mode, pv, pid):
    db.x("insert into eto_invoice (mode, job_no, key, amount, proposal_id) values (%s,%s,%s,%s,%s) "
         "on conflict (mode, job_no, key) do update set proposal_id=excluded.proposal_id, invoice=null",
         (mode, pv["job"]["job_no"], pv["key"], pv["amount"], pid))


def accept(db, mode, job_no, day, note, who):
    """客户验收（发货后登记）：验收那一期才能开票"""
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if not j.get("delivery_note"):
        raise E.EtoError("还没发货，不能登记验收")
    day = dt.date.fromisoformat(str(day)[:10]) if day else dt.date.today()
    db.x("insert into eto_accept (mode, job_no, day, note, who) values (%s,%s,%s,%s,%s) on conflict do nothing",
         (mode, job_no, day, str(note or "")[:500], who))


def money(db, mode, job_no, cost=None):
    """作业的收付与毛利：订单金额、已开票、已收款、实际成本、毛利（成本未知时毛利也未知）"""
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    sched = schedule_of(db, mode, j)
    order_amt = round(sum(float(m["payment_amount"]) for m in sched), 2) if sched else None
    names = {r["invoice"] for r in db.q("select invoice from eto_invoice where mode=%s and job_no=%s and invoice is not null", (mode, job_no))}
    billed = paid = 0.0
    for m in db.erp_docs("Sales Invoice", mode):
        d = m["data"]
        if d.get("name") in names and d.get("docstatus") == 1:
            tot = float(d.get("grand_total") or 0)
            billed += tot
            paid += tot - float(d.get("outstanding_amount") if d.get("outstanding_amount") is not None else tot)
    act = (cost or {}).get("actual") or {}
    total = act.get("total")
    return {"order_amount": order_amt, "invoiced": round(billed, 2), "received": round(paid, 2),
            "receivable": round(billed - paid, 2), "not_invoiced": round(order_amt - billed, 2) if order_amt is not None else None,
            "actual_cost": total, "margin": round(order_amt - total, 2) if (order_amt is not None and total is not None) else None,
            "margin_pct": round((order_amt - total) / order_amt * 100, 1) if (order_amt and total is not None) else None}


def on_proposal_done(db, action, preview, mode):
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    if action == "eto_order":
        db.x("update eto_job set payment_schedule=%s where mode=%s and job_no=%s",
             (json.dumps(pv["sales_order"].get("payment_schedule") or [], ensure_ascii=False), mode, pv["job"]["job_no"]))
    elif action == "eto_invoice":
        r = db.one("select p.result from eto_invoice i join ai_proposal p on p.proposal_id=i.proposal_id "
                   "where i.mode=%s and i.job_no=%s and i.key=%s and p.status='executed'", (mode, pv["job"]["job_no"], pv["key"]))
        name = next((n for d_, n in (((r or {}).get("result") or {}).get("created") or []) if d_ == "Sales Invoice"), None)
        if name:
            db.x("update eto_invoice set invoice=%s where mode=%s and job_no=%s and key=%s", (name, mode, pv["job"]["job_no"], pv["key"]))


def reset(db, mode):
    db.x("delete from eto_invoice where mode=%s", (mode,))
    db.x("delete from eto_accept where mode=%s", (mode,))
