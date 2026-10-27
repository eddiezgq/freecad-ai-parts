# -*- coding: utf-8 -*-
"""设备维护：M1 同一设备反复停机"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("repeat_down")
def repeat_down(c, p, r):
    since = c.now - dt.timedelta(hours=p["hours"])
    per = {}
    for e in c.db.messages(["machine.event"], since=since, mode=c.mode):
        if e["data"].get("event") in ("alarm", "fault"):
            per.setdefault(e["_topic"].split("/")[3], []).append(e)
    out = []
    for u, evs in per.items():
        if len(evs) >= p["times"]:
            reasons = [e["data"].get("message") or "" for e in evs]
            out.append(Finding(u, "{} {} 小时内停机 {} 次".format(u.upper(), p["hours"], len(evs)), "原因：" + "；".join(reasons),
                               subject=("Machine", u), hint="安排维修人员查根因；考虑预防性维护",
                               evidence=[{"topic": e["_topic"], "id": e["id"], "seq": e["_seq"]} for e in evs[-5:]],
                               values={"times": len(evs), "reasons": reasons}))
    return out


# ---------------------------------------------------------------- 第 18 轮 E3
def _has(c, t):
    return c.get("has_" + t, lambda: bool(c.db.one("select to_regclass(%s) is not null as ok", (t,))["ok"]))


@rule("pm_overdue")
def pm_overdue(c, p, r):
    """自上次保养以来的运行小时超过保养周期（车间状态里的 run_h_pm）"""
    from hub import maint as MT
    from sim import reliability as REL
    if not _has(c, "maint_sim"):
        return []
    out = []
    for m in c.ov["machines"]:
        u = m["unit"]
        if m.get("run_h_pm") is None or not REL.params(u):
            continue
        h, iv = float(m["run_h_pm"]), MT.interval_of(c.db, c.mode, u)
        if h <= iv:
            continue
        rk = MT.risk(c.db, c.mode, u, run_h=h)
        out.append(Finding(u, "{} 保养逾期 {:.0f} 运行小时（周期 {:g} 小时）".format(u.upper(), h - iv, iv),
                           "自上次保养已运行 {:.0f} 小时；未来 {:g} 运行小时坏掉的概率 {:.0%}，坏了平均停 {} 分钟".format(
                               h, rk["horizon_h"], rk["p_fail"], rk["mttr_min"]),
                           severity="warn", subject=("Machine", u), hint=r.get("hint"),
                           values={"unit": u, "run_h": round(h, 1), "interval_h": iv, "overdue_h": round(h - iv, 1), "p_fail": rk["p_fail"],
                                   "expected_loss_usd": rk["expected_loss_usd"], "mttr_min": rk["mttr_min"]}))
    return out


@rule("inspection_abnormal")
def inspection_abnormal(c, p, r):
    if not _has(c, "maint_inspection"):
        return []
    out = []
    for x in c.db.q("select * from maint_inspection where mode=%s and status='open' order by id", (c.mode,)):
        k = "IC-{:05d}".format(x["id"])
        bad = "、".join(i["item"] for i in x["abnormal"] or [])
        out.append(Finding(k, "{} 点检异常：{}".format(x["unit"].upper(), bad), "点检人 {}；{}".format(x["by_name"] or "—", x["note"] or ""),
                           severity="warn", subject=("Machine", x["unit"]), about=[("Inspection", k), ("Machine", x["unit"])], hint=r.get("hint"),
                           values={"unit": x["unit"], "inspection_id": x["id"], "abnormal": x["abnormal"]}))
    return out


@rule("failure_risk")
def failure_risk(c, p, r):
    from hub import maint as MT
    from sim import reliability as REL
    if not _has(c, "maint_sim"):
        return []
    out = []
    for m in c.ov["machines"]:
        u = m["unit"]
        if m.get("run_h_pm") is None or not REL.params(u) or m.get("state") in ("down", "fault"):
            continue
        rk = MT.risk(c.db, c.mode, u, run_h=float(m["run_h_pm"]))
        if rk["p_fail"] < float(p["threshold"]):
            continue
        out.append(Finding(u, "{} 未来 {:g} 运行小时坏掉的概率 {:.0%}".format(u.upper(), rk["horizon_h"], rk["p_fail"]),
                           "已运行 {:.0f} 小时（保养周期 {:g}）；预期停机 {:.0f} 分钟、预期损失 ${:,.0f}".format(
                               rk["run_h"], rk["pm_h"], rk["expected_down_min"], rk["expected_loss_usd"]),
                           severity="critical" if rk["p_fail"] >= 2 * float(p["threshold"]) else "warn", subject=("Machine", u), hint=r.get("hint"),
                           values={"unit": u, "run_h": rk["run_h"], "p_fail": rk["p_fail"], "expected_loss_usd": rk["expected_loss_usd"]}))
    return out


@rule("repair_parts_short")
def repair_parts_short(c, p, r):
    from hub import maint as MT
    if not _has(c, "maint_repair"):
        return []
    out = []
    for x in c.db.q("select * from maint_repair where mode=%s and status in ('doing','waiting_parts','open') order by id", (c.mode,)):
        short = [q for q in x["parts"] or [] if MT.stock_of(c.db, c.mode, q["item_code"]) < q["qty"]]
        if not short:
            continue
        k = "MR-{:05d}".format(x["id"])
        out.append(Finding(k, "维修单 {} 等备件：{}".format(k, "、".join("{} 要 {}，库存 {:g}".format(q["item_code"], q["qty"], MT.stock_of(c.db, c.mode, q["item_code"]))
                                                               for q in short)),
                           "{}：{}".format(x["unit"].upper(), x["title"]), severity="critical", subject=("Machine", x["unit"]),
                           about=[("RepairOrder", k), ("Machine", x["unit"])] + [("Item", q["item_code"]) for q in short], hint=r.get("hint"),
                           values={"unit": x["unit"], "repair_id": x["id"], "lines": [{"item": q["item_code"], "qty": q["qty"]} for q in short]}))
    return out


@rule("repair_overdue")
def repair_overdue(c, p, r):
    from sim import reliability as REL
    if not _has(c, "maint_repair"):
        return []
    scale = float(p.get("teach_scale", 30)) if c.mode == "teach" else 1.0       # 教学模式车间倍速运行：按真实时间缩短
    out = []
    for x in c.db.q("select * from maint_repair where mode=%s and status in ('doing','waiting_parts') order by id", (c.mode,)):
        rp = REL.params(x["unit"]) or {"mttr_min": 120}
        limit_min = float(p["times"]) * rp["mttr_min"] / scale
        age = (c.now - (x["started_at"] or x["created_at"])).total_seconds() / 60
        if age <= limit_min:
            continue
        k = "MR-{:05d}".format(x["id"])
        out.append(Finding(k, "维修单 {} 超时：已 {:.0f} 分钟没修好（平均修复 {} 分钟）".format(k, age * scale, rp["mttr_min"]),
                           "{}：{}".format(x["unit"].upper(), x["title"]), severity="warn", subject=("Machine", x["unit"]),
                           about=[("RepairOrder", k), ("Machine", x["unit"])], hint=r.get("hint"), values={"unit": x["unit"], "repair_id": x["id"]}))
    return out


@rule("mtbf_drop")
def mtbf_drop(c, p, r):
    from hub import maint as MT
    if not _has(c, "maint_failure"):
        return []
    n = c.db.one("select count(*) as n from maint_failure where mode=%s and at > now() - interval '30 days'", (c.mode,))["n"]
    if n < int(p["min_failures"]):
        return []
    now, before = MT.mtbf(c.db, c.mode, days=30), MT.mtbf(c.db, c.mode, days=30, before=30)
    if now is None or before is None or now >= before * (1 - float(p["drop"])):
        return []
    return [Finding("plant", "全厂平均故障间隔下降：近 30 天 {:g} 小时，之前 {:g} 小时".format(now, before),
                    "近 30 天故障 {} 次".format(n), severity="warn", subject=("Machine", "grd-01"), hint=r.get("hint"),
                    values={"mtbf": now, "before": before, "failures": n})]
