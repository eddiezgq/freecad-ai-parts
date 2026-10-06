# -*- coding: utf-8 -*-
"""生产执行：P1 停机 / 故障、P2 刀具寿命低（P1、P2 由原 AI 提醒迁来，文字不变）、P3 OEE 低、P4 换刀频率异常、P5 在制积压"""
import datetime as dt

from wqbus.topics import unit_topic

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("machine_down")
def machine_down(c, p, r):
    out = []
    for m in c.ov["machines"]:
        if m["state"] in ("down", "fault"):
            mins = (m["down_until_s"] or 0) / 60
            out.append(Finding(
                m["unit"], "{} {}：{}".format(m["code"], "故障" if m["state"] == "fault" else "停机", m["reason"] or ""),
                "预计还要约 {:.0f} 分钟（仿真时间）；排队 {} 件{}".format(mins, m["queue"], "，是本周瓶颈" if m.get("bottleneck") else ""),
                severity="critical" if m["state"] == "fault" else "warn", subject=("Machine", m["unit"]),
                evidence=[{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}],
                hint="查看受影响的订单；必要时安排加班或转移工序",
                values={"remaining_min": round(mins, 1), "queue": m["queue"], "state": m["state"], "reason": m["reason"],
                        "bottleneck": bool(m.get("bottleneck"))},
                alert_key="down:" + m["unit"]))
    return out


@rule("tool_life_low")
def tool_life_low(c, p, r):
    out = []
    lim = p.get("below", 0.15)
    for m in c.ov["machines"]:
        if m["state"] in ("down", "fault"):
            continue                        # 原 AI 提醒：停机时只报停机
        if m["tool_life_left"] is not None and m["tool_life_left"] < lim and m["state"] != "idle":
            out.append(Finding(
                m["unit"], "{} 刀具剩余寿命 {:.0f}%".format(m["code"], m["tool_life_left"] * 100),
                "按当前节拍约再加工 {} 件后需{}".format(max(1, int(m["tool_life_left"] * 30)), "修整砂轮" if m["unit"] == "grd-01" else "换刀"),
                subject=("Machine", m["unit"]), evidence=[{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}],
                hint="提前准备刀具，安排在换件间隙", values={"tool_life_left": m["tool_life_left"]}, alert_key="tool:" + m["unit"]))
    return out


@rule("oee_low")
def oee_low(c, p, r):
    out = []
    for u, v in (c.ov["oee"]["machines"] or {}).items():
        load = (v.get("run_s") or 0) + (v.get("setup_s") or 0) + (v.get("down_s") or 0)
        if v.get("oee") is None or load < p["min_load_h"] * 3600 or v["oee"] >= p["below"]:
            continue
        worst = min(("availability", "performance", "quality"), key=lambda k: v.get(k) if v.get(k) is not None else 1)
        why = {"availability": "停机和调整多（开动率 {:.0%}）", "performance": "节拍慢于标准（性能 {:.0%}）",
               "quality": "不合格多（合格率 {:.0%}）"}[worst].format(v.get(worst) or 0)
        out.append(Finding(u, "{} 今日 OEE {:.0%}，低于目标 {:.0%}".format(u.upper(), v["oee"], p["below"]),
                           "主要损失：{}；负荷时间 {:.1f} 小时".format(why, load / 3600), subject=("Machine", u),
                           evidence=[{"topic": unit_topic(u, "status")}], values=dict(v, worst=worst)))
    return out


def _local_day(c, t):
    from hub import kpi
    return kpi.local_day_start(t)


@rule("tool_change_rate")
def tool_change_rate(c, p, r):
    today = _local_day(c, c.now)
    since = today - dt.timedelta(days=7)
    evs = [e for e in c.db.messages(["machine.event"], since=since, mode=c.mode) if e["data"].get("event") == "tool_change"]
    per = {}
    for e in evs:
        u = e["_topic"].split("/")[3]
        t = dt.datetime.fromisoformat(e["ts"])
        per.setdefault(u, {"today": [], "before": 0})
        if t >= today:
            per[u]["today"].append(e)
        else:
            per[u]["before"] += 1
    out = []
    for u, x in per.items():
        n, avg = len(x["today"]), x["before"] / 7
        if n >= p["min_count"] and n > p["times"] * avg:
            out.append(Finding(u, "{} 今天换刀 {} 次，是过去 7 天日均（{:.1f}）的 {} 倍以上".format(u.upper(), n, avg, p["times"]),
                               "可能是切削参数、材料硬度或刀具质量有问题", subject=("Machine", u),
                               evidence=[{"topic": e["_topic"], "id": e["id"], "seq": e["_seq"]} for e in x["today"][-3:]],
                               values={"today": n, "avg_7d": round(avg, 2)}))
    return out


@rule("wip_backlog")
def wip_backlog(c, p, r):
    out = []
    for m in c.ov["machines"]:
        if m.get("bottleneck") and (m["queue"] or 0) > p["above"]:
            out.append(Finding(m["unit"], "瓶颈 {} 前排队 {} 件（上限 {}）".format(m["code"], m["queue"], p["above"]),
                               "在制品积压，后续工序会断料，交期受影响", subject=("Machine", m["unit"]),
                               evidence=[{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}], values={"queue": m["queue"]}))
    return out
