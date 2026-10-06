# -*- coding: utf-8 -*-
"""供应链：W1 缺料 / 低于安全库存（原 AI 提醒）、W2 采购单逾期到货"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("stock_short")
def stock_short(c, p, r):
    out = []
    for mt in c.ov["materials"]:
        if mt["tone"] != "bad":
            continue
        out.append(Finding(
            mt["code"], "{} {}".format(mt["code"], mt["status"]),
            "{} 库存 {}，安全库存 {}，在手工单与订单还需 {:g}".format(mt["name"], mt["qty_text"], mt["safety"] if mt["safety"] is not None else "—", mt["need"]),
            subject=("Item", mt["code"]), evidence=[{"topic": "wq/gearbox/office/erp/bin", "item": mt["code"]}], hint="起草请购单",
            values={"qty": mt.get("qty"), "safety": mt.get("safety"), "need": mt.get("need")}, alert_key="stock:" + mt["code"]))
    return out


@rule("po_late")
def po_late(c, p, r):
    from hub import kpi
    today = c.now.astimezone(kpi.TZ).date()
    out = []
    for w in c.db.erp_docs("Purchase Order", c.mode):
        d = w["data"]
        if d.get("status") in ("Completed", "Closed", "Cancelled", "To Bill") or d.get("docstatus") == 2:
            continue
        late = []
        for i in d.get("items") or []:
            sd = i.get("schedule_date")
            if sd and float(i.get("received_qty") or 0) < float(i.get("qty") or 0) and dt.date.fromisoformat(str(sd)[:10]) < today:
                late.append((i["item_code"], (today - dt.date.fromisoformat(str(sd)[:10])).days, i.get("qty"), i.get("received_qty") or 0))
        if late:
            out.append(Finding(d["name"], "采购单 {} 逾期到货（{}）".format(d["name"], d.get("supplier") or "供应商"),
                               "；".join("{} 晚 {} 天，已到 {} / {}".format(a, b, rq, q) for a, b, q, rq in late),
                               subject=("PurchaseOrder", d["name"]), hint="催货；评估是否影响工单，必要时找替代供应商",
                               about=[("PurchaseOrder", d["name"])] + [("Item", x[0]) for x in late] +
                                     ([("Supplier", d["supplier"])] if d.get("supplier") else []),
                               evidence=[{"topic": w.get("_topic") or "wq/gearbox/office/erp/purchase_order", "id": w.get("id"), "seq": w.get("_seq")}],
                               values={"lines": [{"item": a, "late_days": b} for a, b, _, _ in late]}))
    return out
