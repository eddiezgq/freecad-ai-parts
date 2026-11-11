# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139e）：车间执行与作业成本。

- 作业的工单（ERPNext 里挂这个作业项目的）：完工数、所用物料清单是不是发布的那一版（按指纹）；
- 下达车间：设计改过版、工单用的还是旧版物料清单的，不许下达（要先处理）；其余走原来的“下达工单”提议，车间（仿真）按工艺路线逐道做；
- 作业单（traveler）：作业号、客户、设计版本和指纹、工序与标准工时、子件、检验点；
- 设计工时：工程师登记小时数 → ERPNext Timesheet（挂项目），属于数据录入，提议后自动确认，留记录；
- 作业成本：估算（报出去的那一版、按订单件数）对实际——
  工序：总线上每件的实际节拍 + 调整 + 换刀 × 工位费率（和工单成本同一算法）；
  材料：已完工件数 × 物料清单标准用量 × 单价（没有单价的标“未知”，不当 0）；
  设计：登记的工时 × 设计费率；外协：要等采购发票（139g 之后），现在标“未知”。
"""
import datetime as dt
import json
import uuid

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub import mrp
from hub.kpi import Overview

SCHEMA = """
create table if not exists eto_hours (
    id          bigserial primary key,
    mode        text not null,
    job_no      text not null,
    hours       numeric not null,
    note        text,
    who         text,
    day         date not null,
    proposal_id text,
    created_at  timestamptz not null default now()
);
"""
INSPECT_OPS = getattr(F, "INSPECTION_OPS", set())


def init(db):
    db.x(SCHEMA)


def _bom_fp(db, mode, bom):
    for m in db.erp_docs("BOM", mode):
        if m["data"].get("name") == bom:
            return m["data"].get("wq_fingerprint")
    return None


def work_orders(db, mode, job_no):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    proj = E.project_of(j)
    rel = ED.released(db, mode, job_no)
    fp = rel["fingerprint"] if rel else None
    from hub import eto_change as EC
    o = Overview(db, None, mode)
    out = []
    for w in o.wos:
        d = w["data"]
        if d.get("project") != proj or d.get("docstatus") == 2:
            continue
        bfp = _bom_fp(db, mode, d.get("bom_no"))
        out.append({"name": d["name"], "item": d.get("production_item"), "qty": float(d.get("qty", 0)), "produced": o.produced(d),
                    "status": d.get("status"), "bom_no": d.get("bom_no"), "planned_start_date": d.get("planned_start_date"),
                    "started": d["name"] in o.started_wos,
                    "current_design": (bfp == fp) if (bfp and fp) else None,
                    "kept": EC.kept(db, mode, job_no, d["name"]) if (bfp and fp and bfp != fp) else False,
                    "own": str(d.get("production_item") or "").startswith(job_no)})
    out.sort(key=lambda x: (x["planned_start_date"] or "", x["name"]))
    return out


def release_check(db, mode, job_no, work_order):
    wos = {w["name"]: w for w in work_orders(db, mode, job_no)}
    w = wos.get(work_order)
    if not w:
        raise E.EtoError("工单 {} 不是这个作业的".format(work_order))
    from hub import eto_change as EC
    if w["current_design"] is False and not EC.kept(db, mode, job_no, work_order):
        raise E.EtoError("工单 {} 用的是旧版物料清单（设计已改版），先在 ERPNext 里处理这张工单再下达".format(work_order))
    if w["status"] in ("Completed", "Stopped", "Closed"):
        raise E.EtoError("工单 {} 已经{}".format(work_order, w["status"]))
    return w


def traveler(db, mode, job_no, work_order):
    """作业单：车间拿着做的那张纸（网页版）"""
    j = E.job(db, mode, job_no)
    w = next((x for x in work_orders(db, mode, job_no) if x["name"] == work_order), None)
    if not j or not w:
        raise KeyError(work_order)
    rel = ED.released(db, mode, job_no)
    item = w["item"]
    if item not in F.BOMS:
        raise E.EtoError("{} 没有物料清单".format(item))
    rt, comps = F.BOMS[item]
    return {"job_no": job_no, "title": j["title"], "customer": j["customer"], "due_date": j["due_date"], "sales_order": j.get("sales_order"),
            "work_order": work_order, "item": item, "item_name": F.ITEMS[item][0], "qty": w["qty"],
            "design_rev": rel["rev"] if rel else None, "fingerprint": (rel or {}).get("fingerprint"),
            "drawing": ((rel or {}).get("drawings") or {}).get(item),          # 第 150 轮 150d：按哪张批准的图做
            "operations": [{"seq": i + 1, "operation": op, "workstation": F.OPERATIONS.get(op), "std_min": m,
                            "total_min": round(m * w["qty"], 1), "inspection": op in INSPECT_OPS} for i, (op, m) in enumerate(F.ROUTINGS[rt])],
            "components": [{"item_code": c, "name": F.ITEMS[c][0], "per": q, "qty": round(q * w["qty"], 4), "uom": F.ITEMS[c][2]} for c, q in comps],
            "printed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}


# ---------------------------------------------------------------- 设计工时
def hours_preview(db, mode, job_no, hours, note, who, day=None):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    try:
        h = float(hours)
    except (TypeError, ValueError):
        raise E.EtoError("工时要写数字")
    if not 0 < h <= 24:
        raise E.EtoError("一次登记 0–24 小时")
    day = dt.date.fromisoformat(str(day)[:10]) if day else dt.date.today()
    return {"key": uuid.uuid4().hex[:12], "job": {"job_no": job_no, "project": E.project_of(j)}, "hours": h, "note": str(note or "")[:500], "day": day.isoformat(),
            "who": who}


def record_hours(db, mode, pv, pid):
    db.x("insert into eto_hours (mode, job_no, hours, note, who, day, proposal_id) values (%s,%s,%s,%s,%s,%s,%s)",
         (mode, pv["job"]["job_no"], pv["hours"], pv["note"], pv["who"], pv["day"], pid))


def hours(db, mode, job_no):
    return [dict(r, hours=float(r["hours"]), day=r["day"].isoformat(), created_at=r["created_at"].isoformat())
            for r in db.q("select id, hours, note, who, day, proposal_id, created_at from eto_hours where mode=%s and job_no=%s order by day, id",
                          (mode, job_no))]


# ---------------------------------------------------------------- 作业成本
def cost(db, mode, job_no):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    cfg = E.config()
    # 估算：报出去的那一版，按订单件数
    est = None
    if j.get("quoted_rev"):
        r = db.one("select lines from eto_estimate where mode=%s and job_no=%s and rev=%s", (mode, job_no, j["quoted_rev"]))
        res = E.compute(r["lines"], [j["qty"]], cfg)
        b = res["breaks"][0]
        est = {"material": b["material"], "operations": b["operations"], "outside": b["outside"], "engineering": b["engineering"],
               "cost": b["cost"], "price": b["price"], "rev": j["quoted_rev"]}
    wos = work_orders(db, mode, job_no)
    rev_of = {r["fingerprint"]: r["rev"] for r in ED.revisions(db, mode, job_no) if r.get("fingerprint")}   # 第 150 轮：变更前后分开
    ops_act = ops_std = 0.0
    mat, mat_unknown, lines = 0.0, [], []
    pl = purchase_lines(db, mode, j)                   # 第 150 轮 150b：本单专料按发票（没发票按采购单）
    own = lambda c: str(c).startswith(job_no + "-")  # noqa: E731
    no_invoice = set()
    for w in wos:
        c = mrp.wo_cost(db, w["name"], mode)
        if c:
            ops_act += c["actual_cost"]
            ops_std += c["std_cost"]
        done = c["parts_finished"] if c else 0
        m = 0.0
        if w["item"] in F.BOMS:
            for comp, q in F.BOMS[w["item"]][1]:
                if comp in F.BOMS:
                    continue                           # 自制的子件：它自己的工单里算材料
                price = F.ITEMS[comp][3] if comp in F.ITEMS else None
                if own(comp):
                    bp, src = buy_price(pl, comp)
                    if bp is not None:
                        price = bp
                        if src == "po" and done:
                            no_invoice.add(comp)
                if price in (None, ""):
                    if done:
                        mat_unknown.append(comp)
                    continue
                m += q * float(price) * done
        mat += m
        lines.append({"work_order": w["name"], "item": w["item"], "done": done, "qty": w["qty"],
                      "operations_actual": round(c["actual_cost"], 2) if c else 0.0, "operations_std": round(c["std_cost"], 2) if c else 0.0,
                      "material": round(m, 2), "worst_operation": (c or {}).get("worst_operation"),
                      "design_rev": rev_of.get(_bom_fp(db, mode, w["bom_no"]))})
    hrs = sum(h["hours"] for h in hours(db, mode, job_no))
    rate = cfg.get("engineering_rate_per_h")
    eng = round(hrs * float(rate), 2) if rate is not None else None
    out_amt, out_unknown, out_po = outside_actual(db, mode, j, pl)
    actual = {"material": None if mat_unknown else round(mat, 2), "operations": round(ops_act, 2), "outside": out_amt,
              "engineering": eng, "engineering_hours": hrs}
    known = [v for k, v in actual.items() if k != "engineering_hours"]
    actual["total"] = None if any(v is None for v in known) else round(sum(known), 2)
    from hub import eto_change as EC
    by_rev = {}
    for ln in lines:
        k = ln["design_rev"]
        by_rev.setdefault(k, {"design_rev": k, "operations_actual": 0.0, "material": 0.0})
        by_rev[k]["operations_actual"] = round(by_rev[k]["operations_actual"] + ln["operations_actual"], 2)
        by_rev[k]["material"] = round(by_rev[k]["material"] + ln["material"], 2)
    return {"estimate": est, "actual": actual, "operations_std": round(ops_std, 2), "work_orders": lines,
            "by_design_rev": sorted(by_rev.values(), key=lambda x: (x["design_rev"] is None, x["design_rev"] or 0)),
            "change_loss": EC.loss(db, mode, job_no),
            "purchases": pl, "invoice_pending": sorted(no_invoice | set(out_po)),
            "unknown": (["材料单价缺：" + "、".join(sorted(set(mat_unknown)))] if mat_unknown else []) +
                       out_unknown + ([] if rate is not None else ["设计费率没有配置"]),
            "basis": "工序按总线上每件实际节拍 + 调整 + 换刀 × 工位费率；材料按已完工件数 × 标准用量 × 单价；"
                     "外协和本单专料按供应商发票（发票没到的按采购单，标“发票未到”）；设计按登记工时 × 设计费率"}


def purchase_lines(db, mode, j):
    """第 150 轮 150b：挂在作业上的采购单逐行，对上供应商发票（已提交的采购发票，按采购单 + 物料对行）。
    每行：采购单数量、单价、金额；已开票数量与金额；差额 = 发票金额 − 采购单价 × 已开票数量（正数是多付）"""
    proj = E.project_of(j)
    inv = {}
    for m in db.erp_docs("Purchase Invoice", mode):
        d = m["data"]
        if d.get("docstatus") != 1:
            continue
        for it in d.get("items") or []:
            k = (it.get("purchase_order"), it.get("item_code"))
            if not k[0]:
                continue
            r = inv.setdefault(k, {"qty": 0.0, "amount": 0.0, "names": []})
            q = float(it.get("qty") or 0)
            r["qty"] += q
            r["amount"] += float(it["amount"]) if it.get("amount") is not None else q * float(it.get("rate") or 0)
            if d["name"] not in r["names"]:
                r["names"].append(d["name"])
    out = []
    for m in db.erp_docs("Purchase Order", mode):
        d = m["data"]
        if d.get("docstatus") != 1 or d.get("project") != proj:
            continue
        for it in d.get("items") or []:
            q, rate = float(it.get("qty") or 0), it.get("rate")
            v = inv.get((d["name"], it.get("item_code")), {"qty": 0.0, "amount": 0.0, "names": []})
            iq = round(v["qty"], 4)
            diff = round(v["amount"] - iq * float(rate), 2) if (rate is not None and iq) else None
            out.append({"purchase_order": d["name"], "supplier": d.get("supplier"), "item_code": it.get("item_code"), "qty": q,
                        "rate": rate, "po_amount": round(q * float(rate), 2) if rate is not None else None,
                        "invoiced_qty": iq, "invoice_amount": round(v["amount"], 2), "invoices": v["names"],
                        "invoice_rate": round(v["amount"] / iq, 4) if iq else None, "diff": diff,
                        "status": "invoiced" if iq >= q - 1e-9 else ("partly" if iq else "pending")})
    return out


def buy_price(lines, code):
    """一个物料的实际单价：有发票按发票（加权平均），没有按采购单；都没有为 (None, None)"""
    rows = [r for r in lines if r["item_code"] == code]
    iq = sum(r["invoiced_qty"] for r in rows)
    if iq:
        return round(sum(r["invoice_amount"] for r in rows) / iq, 4), "invoice"
    po = [r for r in rows if r["rate"] is not None and r["qty"]]
    if po:
        return round(sum(r["qty"] * float(r["rate"]) for r in po) / sum(r["qty"] for r in po), 4), "po"
    return None, None


def outside_actual(db, mode, j, lines=None):
    """外协实际：已发布设计里的每项外协（作业号-OS序号）。第 150 轮 150b 起按发票：开了票的按发票金额，没开票的部分按采购单（标“发票未到”）；
    哪一项还没下采购单或采购单没单价，外协实际就是未知。返回 (金额, 未知原因, 发票未到的外协编号)"""
    rel = ED.released(db, mode, j["job_no"])
    n = len((rel or {}).get("spec", {}).get("outside") or [])
    if not n:
        return 0.0, [], []
    lines = purchase_lines(db, mode, j) if lines is None else lines
    codes = ["{}-OS{:02d}".format(j["job_no"], i) for i in range(1, n + 1)]
    amt, seen, norate, pending = 0.0, set(), set(), []
    for r in lines:
        c = r["item_code"]
        if c not in codes:
            continue
        seen.add(c)
        rest = max(0.0, r["qty"] - r["invoiced_qty"])
        if rest > 1e-9 and r["rate"] is None:
            norate.add(c)
            continue
        amt += r["invoice_amount"] + rest * float(r["rate"] or 0)
        if rest > 1e-9 and c not in pending:
            pending.append(c)
    miss = [c for c in codes if c not in seen]
    msgs = (["外协还没下采购单：" + "、".join(miss)] if miss else []) + (["外协采购单没有单价：" + "、".join(sorted(norate))] if norate else [])
    return (None if msgs else round(amt, 2)), msgs, pending


def on_proposal_done(db, action, preview, mode):
    if action != "eto_hours":
        return
    pv = preview if isinstance(preview, dict) else json.loads(preview)
    r = db.one("select proposal_id from ai_proposal where action='eto_hours' and mode=%s and preview->>'key'=%s", (mode, pv.get("key")))
    pid = r["proposal_id"] if r else None
    if pid and db.one("select 1 as x from eto_hours where proposal_id=%s", (pid,)):
        return
    record_hours(db, mode, pv, pid)


def reset(db, mode):
    db.x("delete from eto_hours where mode=%s", (mode,))
