# -*- coding: utf-8 -*-
"""财务：F1 工单成本差异超标"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("cost_variance")
def cost_variance(c, p, r):
    from hub import mrp
    out = []
    for w in c.db.erp_docs("Work Order", c.mode):
        d = w["data"]
        if d.get("demo"):
            continue
        k = mrp.wo_cost(c.db, d["name"], c.mode)
        if not k or k.get("variance_pct") is None or k["variance_pct"] <= p["above_pct"]:
            continue
        top = sorted(k.get("lines") or [], key=lambda l: -(l.get("variance") or 0))[:2]
        why = "；".join("{} 差 {:.2f}".format(l.get("operation") or l.get("unit"), l.get("variance") or 0) for l in top)
        out.append(Finding(d["name"], "工单 {} 实际成本比标准高 {:.1f}%".format(d["name"], k["variance_pct"]),
                           "标准 ${:.2f}，实际 ${:.2f}；差异最大的工序：{}".format(k["std_cost"], k["actual_cost"], why),
                           subject=("WorkOrder", d["name"]), hint="在“经营与财务 → 生产与成本”看分解：调整、换刀工时还是废品",
                           values={"std": k["std_cost"], "actual": k["actual_cost"], "variance_pct": k["variance_pct"]}))
    return out


# ---------------------------------------------------------------- 第 18 轮 E7：经营与财务
def _has(c):
    return c.get("has_invoice", lambda: bool(c.db.one("select to_regclass('invoice') is not null as ok")["ok"]))


@rule("ar_overdue")
def ar_overdue(c, p, r):
    """F2 应收逾期"""
    from hub import finance as FN
    if not _has(c):
        return []
    out = []
    for x in FN.ar(c.db, c.mode)["invoices"]:
        if x["status"] not in ("open", "paying") or x["overdue_days"] <= float(p.get("days", 0)):
            continue
        k = x["doc"] or "INV-{:05d}".format(x["id"])
        out.append(Finding(k, "{} 欠款 ${:,.0f} 逾期 {:.0f} 天".format(x["party"].split(" ")[0], x["outstanding"], x["overdue_days"]),
                           "发票 {}（{}），到期 {}{}".format(k, "期初应收" if x["opening"] else "订单 {}".format(x["ref"]), x["due_at"][:10],
                                                         "；已催 {} 次".format(x["dunned_n"]) if x["dunned_n"] else ""),
                           severity="critical" if x["overdue_days"] > float(p.get("critical_days", 30)) else "warn",
                           subject=("Customer", x["party"]), about=[("Customer", x["party"])] + ([("Receivable", x["doc"])] if x["doc"] else []),
                           hint=r.get("hint"), values={"invoice_id": x["id"], "doc": x["doc"], "customer": x["party"], "amount": x["outstanding"], "sales_order": None if x["opening"] else x["ref"],
                                                       "days": x["overdue_days"]}))
    return out


@rule("credit_over")
def credit_over(c, p, r):
    """F3 客户信用超限"""
    from hub import finance as FN
    if not _has(c):
        return []
    out = []
    for x in FN.credit(c.db, c.mode):
        if x["hold"] or not x["limit"] or x["exposure"] <= x["limit"]:
            continue
        out.append(Finding(x["customer"], "{} 信用超限：${:,.0f} / 额度 ${:,.0f}".format(x["customer"].split(" ")[0], x["exposure"], x["limit"]),
                           "应收 ${:,.0f} + 在做没开票的订单 ${:,.0f}".format(x["balance"], x["open_orders"]), severity="warn",
                           subject=("Customer", x["customer"]), hint=r.get("hint"),
                           values={"customer": x["customer"], "limit": x["limit"], "exposure": x["exposure"]}))
    return out


@rule("cash_short")
def cash_short(c, p, r):
    """F4 未来两周应付到期、现金不够"""
    from hub import finance as FN
    if not _has(c):
        return []
    cf = FN.cashflow(c.db, c.mode, weeks=int(p.get("weeks", 2)))
    low = cf["low"]
    if not low or low["balance"] >= float(p.get("min_cash", 0)):
        return []
    return [Finding("cash", "第 {} 周现金将降到 ${:,.0f}".format(low["week"], low["balance"]),
                    "现在 ${:,.0f}；这两周应付 ${:,.0f}、预计收款 ${:,.0f}、固定开支每周 ${:,.0f}".format(
                        cf["cash"], sum(w["out"] for w in cf["weeks"]) - cf["weekly_expense"] * len(cf["weeks"]), sum(w["in"] for w in cf["weeks"]),
                        cf["weekly_expense"]),
                    severity="critical" if low["balance"] < 0 else "warn", subject=("Plant", "WQ"), hint=r.get("hint"),
                    values={"week": low["week"], "balance": low["balance"], "cash": cf["cash"]})]


@rule("margin_low")
def margin_low(c, p, r):
    """F5 订单毛利低于目标"""
    from hub import finance as FN
    if not _has(c):
        return []
    tgt = next((float(o["target"]) for o in FN.objectives(c.db, c.mode) if o["metric"] == "gross_margin"), 0.25)
    out = []
    for m in FN.margins(c.db, c.mode):
        if m["margin_pct"] is None or m["margin_pct"] >= tgt - float(p.get("below_pp", 0.05)):
            continue
        top = sorted([x for x in m["lines"] if x["key"] != "material"], key=lambda x: -x["usd"])[:2]
        out.append(Finding(m["sales_order"], "订单 {} 毛利率 {:.1%}（目标 {:.0%}）".format(m["sales_order"], m["margin_pct"], tgt),
                           "收入 ${:,.0f}，成本 ${:,.0f}；花得多的：{}".format(m["revenue"], m["cost"], "、".join("{} ${:,.0f}".format(x["label"], x["usd"]) for x in top)),
                           severity="warn", subject=("SalesOrder", m["sales_order"]), hint=r.get("hint"),
                           values={"sales_order": m["sales_order"], "margin_pct": m["margin_pct"], "target": tgt}))
    return out


@rule("budget_over")
def budget_over(c, p, r):
    """F6 预算超支（按时间进度）"""
    from hub import finance as FN
    if not _has(c):
        return []
    bv = FN.budget_view(c.db, c.mode)
    if bv["progress"] < float(p.get("min_progress", 0.05)):
        return []
    out = []
    for x in bv["rows"]:
        if x["center"] == "admin" or x["should"] <= 0 or x["actual"] < float(p.get("min_usd", 100)) or x["actual"] <= x["should"] * float(p.get("ratio", 1.1)):
            continue
        out.append(Finding("{}/{}".format(bv["month"], x["center"]), "{} 预算超支：${:,.0f}，按进度应 ${:,.0f}（超 {:.0%}）".format(
            x["name"], x["actual"], x["should"], x["actual"] / x["should"] - 1),
            "{} 预算 ${:,.0f}，本月已过 {:.0%}".format(bv["month"], x["budget"], bv["progress"]), severity="warn", subject=("Budget", "{}/{}".format(bv["month"], x["center"])),
            hint=r.get("hint"), values={"center": x["center"], "budget": x["budget"], "actual": x["actual"], "over": x["over"], "progress": bv["progress"]}))
    return out


@rule("objective_off")
def objective_off(c, p, r):
    """F7 经营指标偏离目标（这几天大多是红的）"""
    from hub import finance as FN
    if not _has(c):
        return []
    out = []
    for o in FN.objectives(c.db, c.mode):
        if o["tone"] != "bad" or o["red_days"] < int(p.get("red_days", 5)):
            continue
        out.append(Finding(o["code"], "经营指标“{}”偏离目标：{}（目标 {}{}）".format(o["name"], _fmt(o, o["value"]), "≥" if o["direction"] == "ge" else "≤", _fmt(o, o["target"])),
                           "近 {} 天里 {} 天是红的".format(len(o["history"]), o["red_days"]), severity="warn", subject=("Objective", o["code"]),
                           hint=r.get("hint"), values={"code": o["code"], "name": o["name"], "value": o["value"], "target": o["target"], "domain": o["domain"]}))
    return out


def _fmt(o, v):
    if v is None:
        return "—"
    return "{:.0%}".format(v) if o["unit"] == "pct" else "{:g}".format(round(float(v), 1))
