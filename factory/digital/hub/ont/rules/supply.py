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


# ---------------------------------------------------------------- 第 18 轮 E5：来料、供应商、批次
def _has(c, t):
    return c.get("has_" + t, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (t,))["ok"]))


@rule("incoming_rejected")
def incoming_rejected(c, p, r):
    if not _has(c, "lot"):
        return []
    out = []
    for x in c.db.q("select * from lot where mode=%s and status='rejected' order by id", (c.mode,)):
        bad = (x["inspection"] or {}).get("bad") or []
        out.append(Finding(x["lot"] or "LOT-{}".format(x["id"]), "来料不合格：{} 批 {}（{:g} 件，{}）".format(x["item"], x["lot"], float(x["qty"]), x["supplier"].split(" ")[0]),
                           "抽检 {} 件，{} 处超差；这批料进不了库".format((x["inspection"] or {}).get("sample_size", "—"), len(bad)),
                           severity="critical" if x["item"].startswith("BRG-") else "warn", subject=("Item", x["item"]),
                           about=[("Batch", x["lot"]), ("Supplier", x["supplier"]), ("Item", x["item"])], hint=r.get("hint"),
                           values={"lot_id": x["id"], "lot": x["lot"], "item": x["item"], "supplier": x["supplier"], "qty": float(x["qty"])}))
    return out


@rule("supplier_late")
def supplier_late(c, p, r):
    from hub import supply as SP
    if not _has(c, "lot"):
        return []
    out = []
    for s in SP.scorecard(c.db, c.mode, int(p.get("days", 30))):
        if s["arrived"] < int(p.get("min_lots", 3)) or s["on_time"] is None or s["on_time"] >= float(p.get("on_time", 0.8)):
            continue
        out.append(Finding(s["supplier"], "{} 准时率 {:.0%}（近 {} 天到货 {} 批）".format(s["supplier"].split(" ")[0], s["on_time"], int(p.get("days", 30)), s["arrived"]),
                           "供应 {}；准时率低于 {:.0%}".format(s["cat_name"], float(p.get("on_time", 0.8))), severity="warn", subject=("Supplier", s["supplier"]),
                           hint=r.get("hint"), values={"supplier": s["supplier"], "cat": s["cat"], "on_time": s["on_time"], "arrived": s["arrived"]}))
    return out


@rule("supplier_quality")
def supplier_quality(c, p, r):
    from hub import supply as SP
    if not _has(c, "lot"):
        return []
    out = []
    for s in SP.scorecard(c.db, c.mode, int(p.get("days", 30))):
        if s["inspected"] < int(p.get("min_lots", 3)) or s["pass_rate"] is None or s["pass_rate"] >= float(p.get("pass_rate", 0.95)):
            continue
        out.append(Finding(s["supplier"], "{} 来料合格率 {:.0%}（近 {} 天检验 {} 批）".format(s["supplier"].split(" ")[0], s["pass_rate"], int(p.get("days", 30)), s["inspected"]),
                           "供应 {}".format(s["cat_name"]), severity="warn", subject=("Supplier", s["supplier"]), hint=r.get("hint"),
                           values={"supplier": s["supplier"], "cat": s["cat"], "pass_rate": s["pass_rate"], "inspected": s["inspected"]}))
    return out


@rule("single_source")
def single_source(c, p, r):
    from hub import supply as SP
    if not _has(c, "supplier_profile"):
        return []
    out = []
    for x in SP.single_source(c.db, c.mode):
        out.append(Finding(x["cat"], "{}只有一家供应商：{}".format(x["cat_name"], (x["supplier"] or "—").split(" ")[0]),
                           "物料 {}{}".format("、".join(x["items"][:6]), "；有可开发的备选" if x["has_alt"] else "；还没有备选"),
                           severity="info", subject=("Supplier", x["supplier"] or x["cat"]), hint=r.get("hint"),
                           values={"cat": x["cat"], "supplier": x["supplier"], "items": x["items"], "has_alt": x["has_alt"]}))
    return out


@rule("suspect_batch_used")
def suspect_batch_used(c, p, r):
    if not _has(c, "lot"):
        return []
    out = []
    for x in c.db.q("select * from lot where mode=%s and status='suspect' order by id", (c.mode,)):
        n = c.db.one("select count(distinct part_serial) as n from batch_use where mode=%s and lot=%s", (c.mode, x["lot"]))["n"]
        if not n:
            continue
        out.append(Finding(x["lot"], "可疑批次 {} 已用到 {} 个零件上（{}）".format(x["lot"], n, x["item"]),
                           "{}；要追查这些零件和装了它们的设备".format(x["note"] or ""), severity="critical", subject=("Item", x["item"]),
                           about=[("Batch", x["lot"]), ("Supplier", x["supplier"])], hint=r.get("hint"),
                           values={"lot_id": x["id"], "lot": x["lot"], "item": x["item"], "parts": n}))
    return out
