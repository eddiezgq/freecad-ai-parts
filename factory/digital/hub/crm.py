# -*- coding: utf-8 -*-
"""客户与销售（第 18 轮 E1）：合同条款、销售漏斗。

- 线索（Lead）、商机（Opportunity）、报价（Quotation）、合同（Contract）以 ERPNext 为准（E1-1）：
  平台经桥接写（提议 → 自动确认，属于数据录入，不是要审批的动作），桥接轮询读回，存在历史库的 erp.doc 里。
- 合同条款放在 ERPNext 合同的自定义字段里：wq_penalty_per_day（延期违约金 $/天）、wq_response_h（投诉响应时限，小时）、
  wq_warranty_months（保修期，月）。推演的违约金、服务的保修判定都读这里（E1-3）。"""
import datetime as dt

DEFAULT_RESPONSE_H = 24
DEFAULT_WARRANTY_MONTHS = 12
STAGES = [("lead", "线索"), ("opportunity", "商机"), ("quotation", "报价"), ("contract", "合同"), ("order", "订单")]


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def contracts(db, mode):
    """全部合同（每个合同号最新一版）"""
    out = []
    for m in db.erp_docs("Contract", mode):
        d = m["data"]
        if d.get("docstatus") == 2 or d.get("status") == "Cancelled":
            continue
        out.append({"name": d["name"], "customer": d.get("party_name"), "start": str(d.get("start_date") or "")[:10] or None,
                    "end": str(d.get("end_date") or "")[:10] or None, "signed": bool(d.get("is_signed")), "status": d.get("status"),
                    "penalty_per_day": float(d.get("wq_penalty_per_day") or 0), "response_h": float(d.get("wq_response_h") or 0) or None,
                    "warranty_months": int(d.get("wq_warranty_months") or 0) or None, "demo": bool(d.get("demo")),
                    "seq": m.get("_seq")})
    return out


def terms_for(db, mode, customer, on=None, cache=None):
    """某客户在某天生效的合同条款；没有合同返回 None"""
    on = on or dt.date.today()
    rows = cache if cache is not None else contracts(db, mode)
    best = None
    for c in rows:
        if c["customer"] != customer or not c["signed"]:
            continue
        s, e = _d(c["start"]), _d(c["end"])
        if (s and on < s) or (e and on > e):
            continue
        if best is None or (c["start"] or "") > (best["start"] or ""):
            best = c
    return best


def penalty_map(db, mode, sales_orders, on=None):
    """销售订单 → 违约金 $/天（按客户的合同；没有合同或为 0 的不算）"""
    rows = contracts(db, mode)
    out = {}
    for so in sales_orders:
        t = terms_for(db, mode, so.get("customer"), on, rows)
        if t and t["penalty_per_day"] > 0:
            out[so["name"]] = t["penalty_per_day"]
    return out


def warranty_until(db, mode, customer, start_day, cache=None):
    """现场设备的保修到期日：投运日 + 客户合同的保修期（没有合同按 12 个月）"""
    sd = _d(start_day)
    if not sd:
        return None
    t = terms_for(db, mode, customer, sd, cache)
    months = (t or {}).get("warranty_months") or DEFAULT_WARRANTY_MONTHS
    y, m = divmod(sd.month - 1 + months, 12)
    day = min(sd.day, 28)
    return dt.date(sd.year + y, m + 1, day)


def response_h(db, mode, customer, cache=None):
    t = terms_for(db, mode, customer, None, cache)
    return (t or {}).get("response_h") or DEFAULT_RESPONSE_H


# ---------------------------------------------------------------- 销售漏斗
def pipeline(db, mode):
    """线索 → 商机 → 报价 → 合同 → 订单，每张卡片带下一步可以做什么"""
    cards = []
    lead_name = {m["data"]["name"]: (m["data"].get("company_name") or m["data"].get("lead_name")) for m in db.erp_docs("Lead", mode)}
    for m in db.erp_docs("Lead", mode):
        d = m["data"]
        if d.get("status") in ("Converted", "Do Not Contact", "Opportunity", "Quotation"):
            continue
        cards.append({"stage": "lead", "doctype": "Lead", "name": d["name"], "title": d.get("company_name") or d.get("lead_name"),
                      "who": d.get("lead_name"), "status": d.get("status"), "note": d.get("wq_note"), "amount": None,
                      "date": str(d.get("creation") or "")[:10] or None})
    quoted = set()
    qts = [m["data"] for m in db.erp_docs("Quotation", mode)]
    for q in qts:
        if q.get("opportunity"):
            quoted.add(q["opportunity"])
    for m in db.erp_docs("Opportunity", mode):
        d = m["data"]
        if d.get("status") in ("Lost", "Closed", "Converted") or d["name"] in quoted:
            continue
        cards.append({"stage": "opportunity", "doctype": "Opportunity", "name": d["name"], "title": lead_name.get(d.get("party_name"), d.get("party_name")),
                      "who": d.get("opportunity_from"), "status": d.get("status"), "amount": d.get("opportunity_amount"),
                      "date": str(d.get("expected_closing") or "")[:10] or None, "lead": d.get("party_name") if d.get("opportunity_from") == "Lead" else None})
    contracted = {c.get("wq_quotation") for c in (m["data"] for m in db.erp_docs("Contract", mode)) if c.get("wq_quotation")}
    for q in qts:
        if q.get("docstatus") == 2 or q.get("status") in ("Lost", "Cancelled", "Ordered") or q["name"] in contracted:
            continue
        amt = q.get("grand_total") or q.get("total") or sum(float(i.get("qty") or 0) * float(i.get("rate") or 0) for i in q.get("items") or [])
        cards.append({"stage": "quotation", "doctype": "Quotation", "name": q["name"], "title": lead_name.get(q.get("party_name"), q.get("party_name")),
                      "quotation_to": q.get("quotation_to"), "party": q.get("party_name"), "opportunity": q.get("opportunity"),
                      "status": q.get("status"), "amount": amt, "date": str(q.get("valid_till") or "")[:10] or None,
                      "items": q.get("items")})
    ordered = {c.get("wq_sales_order") for c in (m["data"] for m in db.erp_docs("Contract", mode)) if c.get("wq_sales_order")}
    for c in contracts(db, mode):
        raw = next((m["data"] for m in db.erp_docs("Contract", mode) if m["data"]["name"] == c["name"]), {})
        if c["demo"] or c["name"] in ordered or raw.get("wq_sales_order"):
            continue
        cards.append({"stage": "contract", "doctype": "Contract", "name": c["name"], "title": c["customer"], "status": c["status"],
                      "amount": raw.get("wq_amount"), "date": c["start"], "terms": {k: c[k] for k in ("penalty_per_day", "response_h", "warranty_months")},
                      "quotation": raw.get("wq_quotation")})
    today = dt.date.today()
    month0 = today.replace(day=1)
    won = 0.0
    for m in db.erp_docs("Sales Order", mode):
        d = m["data"]
        td = _d(d.get("transaction_date"))
        if td and td >= month0 and d.get("docstatus") == 1 and not d.get("demo"):
            won += float(d.get("grand_total") or 0)
    funnel = {k: sum(float(c.get("amount") or 0) for c in cards if c["stage"] == k) for k, _ in STAGES}
    return {"cards": cards, "stages": [{"key": k, "label": l, "count": sum(1 for c in cards if c["stage"] == k)} for k, l in STAGES],
            "funnel_amount": round(sum(v for k, v in funnel.items() if k in ("opportunity", "quotation", "contract")), 2), "won_month": round(won, 2)}
