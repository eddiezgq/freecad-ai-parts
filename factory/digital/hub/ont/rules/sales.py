# -*- coding: utf-8 -*-
"""销售交付与计划：S1 订单可能延期（原 AI 提醒）、S2 工单逾期"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("order_late")
def order_late(c, p, r):
    out = []
    for o in c.ov["orders"]:
        if o["tone"] != "bad":
            continue
        late_d = None
        if o.get("projected"):
            late_d = (dt.date.fromisoformat(o["projected"][:10]) - dt.date.fromisoformat(o["delivery_date"][:10])).days
        out.append(Finding(
            o["name"], "{} 可能延期：{}".format(o["name"], o["risk"]),
            "{} {} 台，交期 {}，预计 {} 完成；{}".format(o["customer"].split(" ")[0], o["qty"], o["delivery_date"], o["projected"], o["work_orders"]),
            severity="critical" if late_d is not None and late_d > p["critical_days"] else "warn", subject=("SalesOrder", o["name"]),
            evidence=[{"topic": "wq/gearbox/office/erp/sales_order", "name": o["name"]}],
            hint="考虑加班、调整优先级或与客户沟通交期", about=[("SalesOrder", o["name"]), ("Customer", o["customer"])],
            values={"delivery_date": o["delivery_date"], "projected": o["projected"], "late_days": late_d, "short": o.get("short")},
            alert_key="late:" + o["name"]))
    return out


@rule("wo_overdue")
def wo_overdue(c, p, r):
    from hub import kpi
    today = c.now.astimezone(kpi.TZ).date()
    out = []
    for w in c.db.erp_docs("Work Order", c.mode):
        d = w["data"]
        due = d.get("expected_delivery_date")
        if not due or d.get("status") in ("Completed", "Cancelled", "Stopped", "Closed") or d.get("demo"):
            continue
        days = (today - dt.date.fromisoformat(str(due)[:10])).days
        if days > 0:
            out.append(Finding(d["name"], "工单 {} 逾期 {} 天（{} × {}）".format(d["name"], days, d.get("production_item"), d.get("qty")),
                               "计划完工 {}，已完工 {} / {}".format(str(due)[:10], d.get("produced_qty") or 0, d.get("qty")),
                               subject=("WorkOrder", d["name"]),
                               evidence=[{"topic": w.get("_topic") or "wq/gearbox/office/erp/work_order", "id": w.get("id"), "seq": w.get("_seq")}],
                               values={"days": days, "due": str(due)[:10]}))
    return out
