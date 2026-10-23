# -*- coding: utf-8 -*-
"""市场与客户（第 18 轮 E1）：C1 新投诉、C2 满意度下降、C3 投诉超时没响应、C4 同批多台投诉、C5 报价快到期、R3 延期会触发违约金"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule

SEV = {"urgent": "critical", "serious": "warn", "normal": "warn"}


def _has(c, t):
    return c.get("has_" + t, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (t,))["ok"]))


def open_complaints(c):
    if not _has(c, "complaint"):
        return []
    return c.get("open_complaints", lambda: c.db.q("select * from complaint where mode=%s and status<>'closed' order by id", (c.mode,)))


@rule("complaint_new")
def complaint_new(c, p, r):
    """开着的投诉都是异常；紧急的、或客户合同有违约金（重点客户）的为严重"""
    from hub import crm
    cache = c.get("contracts", lambda: crm.contracts(c.db, c.mode))
    out = []
    for x in open_complaints(c):
        key = "CP-{:05d}".format(x["id"])
        t = crm.terms_for(c.db, c.mode, x["customer"], None, cache)
        key_account = bool(t and t["penalty_per_day"] > 0)
        sev = "critical" if x["severity"] == "urgent" or key_account else SEV.get(x["severity"], "warn")
        subj = ("FieldUnit", x["serial"]) if x["serial"] else ("Complaint", key)
        out.append(Finding(key, "客户投诉 {}：{}（{}）".format(key, x["subject"], x["customer"]),
                           "{}；渠道 {}；{}".format(x["detail"] or x["subject"], x["channel"] or "—",
                                                  "设备 " + x["serial"] if x["serial"] else "没有设备序列号，追不到出厂数据"),
                           severity=sev, subject=subj, hint="先回复客户、确认情况；看因果链里的排查范围，选处理方案",
                           about=[("Complaint", key), ("Customer", x["customer"])] + ([("FieldUnit", x["serial"])] if x["serial"] else []),
                           evidence=[{"table": "complaint", "id": x["id"]}],
                           values={"complaint": key, "serial": x["serial"], "customer": x["customer"], "severity": x["severity"],
                                   "units": [x["serial"]] if x["serial"] else [], "key_account": key_account}))
    return out


@rule("satisfaction_drop")
def satisfaction_drop(c, p, r):
    if not _has(c, "follow_up"):
        return []
    out = []
    rows = c.db.q("select customer, score from follow_up where mode=%s and score is not null order by done_at desc", (c.mode,))
    by = {}
    for x in rows:
        by.setdefault(x["customer"], []).append(float(x["score"]))
    for cust, ss in by.items():
        last = ss[:int(p["last_n"])]
        if len(last) < int(p["last_n"]):
            continue
        avg = sum(last) / len(last)
        if avg < float(p["threshold"]):
            out.append(Finding(cust, "{} 满意度下降：近 {} 次回访平均 {:.1f} 分".format(cust, len(last), avg),
                               "最近的打分：{}".format("、".join("{:g}".format(s) for s in last)), subject=("Customer", cust),
                               hint="厂长或销售主动回访，问清楚哪里不满意", values={"avg": round(avg, 2), "scores": last}))
    return out


@rule("complaint_overdue")
def complaint_overdue(c, p, r):
    """投诉超过合同响应时限还是“新投诉”（没人回复）"""
    from hub import crm
    cache = c.get("contracts", lambda: crm.contracts(c.db, c.mode))
    out = []
    for x in open_complaints(c):
        if x["status"] != "open" or x["responded_at"]:
            continue
        limit_h = crm.response_h(c.db, c.mode, x["customer"], cache)
        h = (c.now - x["created_at"]).total_seconds() / 3600
        if h > limit_h:
            key = "CP-{:05d}".format(x["id"])
            out.append(Finding(key, "投诉 {} 超过响应时限：已 {:.0f} 小时没回复（合同要求 {:g} 小时）".format(key, h, limit_h),
                               "{}：{}".format(x["customer"], x["subject"]), subject=("Complaint", key),
                               about=[("Complaint", key), ("Customer", x["customer"])],
                               hint="马上联系客户；没有工程师空着就先远程支持", values={"hours": round(h, 1), "limit_h": limit_h, "serial": x["serial"],
                                                                         "units": [x["serial"]] if x["serial"] else []}))
    return out


@rule("complaint_batch")
def complaint_batch(c, p, r):
    """开着的投诉里，至少 min_units 台设备的输出轴出自同一片砂轮或同一张工单 → 疑似批次问题"""
    from hub.ont.rules.service import shaft_batch
    serials = sorted({x["serial"] for x in open_complaints(c) if x["serial"]})
    if len(serials) < int(p["min_units"]):
        return []
    b = shaft_batch(c, serials)
    groups = {}
    for s, x in b.items():
        if x["wheel"]:
            groups.setdefault(("Tool", x["wheel"]), []).append(s)
        if x["work_order"]:
            groups.setdefault(("WorkOrder", x["work_order"]), []).append(s)
    out = []
    for (t, k), units in groups.items():
        if len(units) < int(p["min_units"]):
            continue
        what = "同一片砂轮 {}".format(k) if t == "Tool" else "同一张工单 {}".format(k)
        out.append(Finding("{}:{}".format(t, k), "疑似批次问题：{} 台被投诉的设备，输出轴出自{}".format(len(units), what),
                           "被投诉的设备：{}".format("、".join(sorted(units))), subject=("FieldUnit", sorted(units)[0]),
                           hint="按排查范围决定：只修投诉的、加上高风险点检、还是整批排查；同时查这批轴的检验数据",
                           about=[(t, k)] + [("FieldUnit", s) for s in units], values={"units": sorted(units), "by": t, "batch": k}))
    return out


@rule("quote_expiring")
def quote_expiring(c, p, r):
    from hub import kpi
    today = c.now.astimezone(kpi.TZ).date()
    out = []
    for m in c.db.erp_docs("Quotation", c.mode):
        d = m["data"]
        if d.get("status") not in ("Open", "Replied") or not d.get("valid_till"):
            continue
        left = (dt.date.fromisoformat(str(d["valid_till"])[:10]) - today).days
        if 0 <= left <= int(p["days"]):
            out.append(Finding(d["name"], "报价 {} 还有 {} 天到期（{}）".format(d["name"], left, d.get("party_name")),
                               "金额 ${:,.0f}；有效期到 {}".format(float(d.get("grand_total") or d.get("total") or 0), str(d["valid_till"])[:10]),
                               subject=("Quotation", d["name"]), hint="销售跟进客户：成交、延期报价，或标记丢单",
                               evidence=[{"topic": m.get("_topic"), "seq": m.get("_seq")}], values={"days_left": left}))
    return out


@rule("order_penalty")
def order_penalty(c, p, r):
    """看板预测会晚的订单，客户合同里有延期违约金：写出金额"""
    from hub import crm
    cache = c.get("contracts", lambda: crm.contracts(c.db, c.mode))
    out = []
    for o in c.ov["orders"]:
        if o["tone"] != "bad" or not o.get("projected"):
            continue
        t = crm.terms_for(c.db, c.mode, o["customer"], None, cache)
        if not t or t["penalty_per_day"] <= 0:
            continue
        late = (dt.date.fromisoformat(o["projected"][:10]) - dt.date.fromisoformat(o["delivery_date"][:10])).days
        if late <= 0:
            continue
        out.append(Finding(o["name"], "{} 延期会触发违约金：预计晚 {} 天 × ${:,.0f}/天 = ${:,.0f}".format(o["name"], late, t["penalty_per_day"], late * t["penalty_per_day"]),
                           "合同 {}（{}）：延期违约金 ${:,.0f}/天".format(t["name"], o["customer"].split(" ")[0], t["penalty_per_day"]),
                           severity="critical" if late * t["penalty_per_day"] >= float(p["critical_usd"]) else "warn", subject=("SalesOrder", o["name"]),
                           about=[("SalesOrder", o["name"]), ("Contract", t["name"]), ("Customer", o["customer"])],
                           hint="在指挥台推演加班、调序或外协；或与客户协商交期",
                           values={"late_days": late, "penalty_per_day": t["penalty_per_day"], "penalty": late * t["penalty_per_day"], "contract": t["name"]}))
    return out
