# -*- coding: utf-8 -*-
"""处理预案（第 17 轮 C 期 C8）：按异常种类生成候选方案，各推演一遍，按“准时 → 多花的钱 → 加班工时”排序，推荐第一个。

预案目录在 digital/ontology/rules/playbooks.yaml；每种方案的参数在这里按当时的情况填（哪台停机、排着哪些工序、缺什么料）。"""
import datetime as dt
import os

import yaml

from hub.ont import plan as P
from hub.ont import schema as S
from sim.engine import OP_UNITS

LABELS = {"none": "不处理", "overtime": "恢复后加班", "reassign": "改派到同类设备", "expedite": "维修加急",
          "reorder": "插单调序（排到最前）", "outsource": "瓶颈工序外协", "urgent_purchase": "紧急采购", "split": "分批交货"}


def catalog():
    doc = yaml.safe_load(open(os.path.join(S.DIR, "rules", "playbooks.yaml"), encoding="utf-8")) or {}
    params = doc.pop("params", {})
    return doc, params


def _day(snap, cal):
    """加班的日子：快照时刻在班内（或还没上班）就是今天，已下班就是下一个工作日"""
    now = dt.datetime.fromisoformat(snap["factory_now"]).astimezone(cal.tzi)
    d = now.date()
    w = cal.window("*", d)
    if not w or now.hour * 60 + now.minute >= w[1]:
        d += dt.timedelta(days=1)
        while d.weekday() not in cal.workdays:
            d += dt.timedelta(days=1)
    return d.isoformat()


def build(a, snap, ctx):
    """异常（anomaly 行）→ [{key, kind, label, changes, note}]；不适用的方案不出现"""
    from sim.calendar import Calendar
    books, prm = catalog()
    kinds = books.get(a["rule"]) or []
    cal = Calendar.from_dict(snap.get("calendar"))
    v = (a["detail"] or {}).get("values") or {}
    sub = a["subject_key"]
    out = []

    def add(kind, changes, note=""):
        out.append({"kind": kind, "label": LABELS[kind], "changes": changes, "note": note})

    machine = sub if a["subject_type"] == "Machine" else None
    so_name = sub if a["subject_type"] == "SalesOrder" else None
    so = next((s for s in ctx["sales_orders"] if s["name"] == so_name), None) if so_name else None
    wos = list(so["work_orders"]) if so else ([sub] if a["subject_type"] == "WorkOrder" else [])
    for k in kinds:
        if k == "none":
            add("none", [])
        elif k == "overtime":
            if cal.mode != "shift":
                continue                     # 24 小时连续运转时加班没有意义
            add("overtime", [{"type": "overtime", "day": _day(snap, cal), "unit": "*", "minutes": int(prm.get("overtime_minutes", 120))}],
                "全厂加班 {} 分钟".format(int(prm.get("overtime_minutes", 120))))
        elif k == "reassign" and machine:
            m = snap["machines"].get(machine) or {}
            ch = []
            for wn, i in m.get("jobs") or []:
                op = snap["wos"][wn]["ops"][i][0]
                alt = [u for u in OP_UNITS.get(op, []) if u != machine]
                if alt:
                    ch.append({"type": "reassign", "work_order": wn, "operation": op, "from_unit": machine, "to_unit": alt[0]})
            if ch:
                add("reassign", ch, "；".join("{} {} → {}".format(c["work_order"], c["operation"].split(" ")[0], c["to_unit"].upper()) for c in ch))
        elif k == "expedite" and machine:
            m = snap["machines"].get(machine) or {}
            if m.get("state") in ("down", "fault") and m.get("down_until"):
                f = float(prm.get("expedite_factor", 0.5))
                add("expedite", [{"type": "expedite", "unit": machine, "factor": f}], "剩余停机时间缩短到 {:.0%}".format(f))
        elif k == "reorder" and wos:
            ch = []
            for u, m in snap["machines"].items():
                for wn, i in m.get("jobs") or []:
                    if wn in wos and m["jobs"][0] != [wn, i]:
                        ch.append({"type": "reorder", "unit": u, "work_order": wn, "operation": snap["wos"][wn]["ops"][i][0]})
            if ch:
                add("reorder", ch, "在 {} 台设备上排到最前".format(len({c["unit"] for c in ch})))
        elif k == "outsource" and wos:
            best = None
            for u, m in snap["machines"].items():
                for wn, i in m.get("jobs") or []:
                    if wn in wos:
                        op, mins = snap["wos"][wn]["ops"][i]
                        if not op.startswith(("调质", "零件检验")) and (best is None or mins > best[2]):
                            best = (u, wn, mins, op)
            if best:
                n = int(prm.get("outsource_qty", 3))
                add("outsource", [{"type": "outsource", "unit": best[0], "work_order": best[1], "operation": best[3], "qty": n,
                                   "days": prm.get("outsource_days", 1)}], "{} 外协 {} 件".format(best[3].split(" ")[0], n))
        elif k == "urgent_purchase":
            item = sub if a["subject_type"] == "Item" else None
            lines = v.get("lines") or []
            items = [item] if item else [x["item"] for x in lines]
            for r in ctx.get("releases") or []:
                hit = [i for i in items if i in (r.get("short") or [])]
                if not hit:
                    continue
                d = dt.datetime.fromisoformat(snap["factory_now"]).astimezone(cal.tzi).date()
                arrive = (d + dt.timedelta(days=1 if d.weekday() < 4 else 3)).isoformat()
                ch = [{"type": "urgent_purchase", "item": i, "qty": max(1, int(r["qty"])), "arrive": arrive} for i in r["short"]]
                add("urgent_purchase", ch, "{} 加急，{} 到货".format("、".join(r["short"]), arrive))
                break
        elif k == "split":
            target = so or next((s for s in ctx["sales_orders"] if s.get("pending") and (sub in (s["pending"].get("short") or []))), None)
            if target and target.get("qty"):
                first = max(1, int(float(target["qty"]) // 2))
                add("split", [{"type": "split_delivery", "sales_order": target["name"], "first_qty": first, "first_date": target["delivery_date"]}],
                    "{} 先交 {} 台（交期 {}），其余顺延".format(target["name"], first, target["delivery_date"]))
    for i, o in enumerate(out):
        o["key"] = chr(ord("A") + i)
    return out


def affected(a, ctx):
    """这个异常影响的销售订单（用来比较各方案）"""
    sc = ((a.get("chain") or {}).get("scope") or {})
    names = set(sc.get("sales_orders") or [])
    if a["subject_type"] == "SalesOrder":
        names.add(a["subject_key"])
    if a["subject_type"] == "Item":
        names |= {s["name"] for s in ctx["sales_orders"] if s.get("pending") and a["subject_key"] in (s["pending"].get("short") or [])}
    if a["subject_type"] == "WorkOrder":
        names |= {s["name"] for s in ctx["sales_orders"] if a["subject_key"] in s["work_orders"]}
    if not names:
        names = {s["name"] for s in ctx["sales_orders"] if s["work_orders"]}
    return sorted(names)


def evaluate(a, snap, ctx):
    """各方案推演，排序，推荐"""
    opts = build(a, snap, ctx)
    names = affected(a, ctx)
    for o in opts:
        r = P.simulate(snap, o["changes"], ctx)
        rows = [s for s in r["sales_orders"] if s["name"] in names]
        lates = [s["late_days"] for s in rows if s["late_days"] is not None]
        o["result"] = {"sales_orders": rows, "cost_total": r["cost_total"], "costs": r["costs"], "overtime_min": r["overtime_min"],
                       "overtime_units": r["overtime_units"],
                       "checks": r["checks"], "ok": r["ok"], "work_orders": {k: {"finish": w["finish"], "complete": w["complete"]}
                                                                              for k, w in r["work_orders"].items()}}
        o["worst_late"] = max(lates) if lates else None
        o["undetermined"] = len(lates) < len(rows)
    def score(o):
        wl = o["worst_late"] if o["worst_late"] is not None else 99
        return (0 if o["result"]["ok"] else 1, 1 if o["undetermined"] else 0, max(wl, 0), o["result"]["cost_total"], o["result"]["overtime_min"], wl)
    ranked = sorted(opts, key=score)
    best = ranked[0] if ranked else None
    for o in opts:
        o["recommended"] = o is best
    reason = None
    if best:
        base = next((o for o in opts if o["kind"] == "none"), None)
        so_txt = "；".join("{} {}".format(s["name"], "按时（余 {} 天）".format(-s["late_days"]) if s["late_days"] is not None and s["late_days"] <= 0
                                        else "晚 {} 天".format(s["late_days"]) if s["late_days"] is not None else "推演范围内做不完")
                           for s in best["result"]["sales_orders"]) or "没有受影响的订单"
        if best["kind"] == "none":
            reason = "不处理就够了：{}。其他方案多花钱或不改善交期。".format(so_txt)
        else:
            gain = ""
            if base and base["worst_late"] is not None and best["worst_late"] is not None and base["worst_late"] > best["worst_late"]:
                gain = "，比不处理早 {} 天".format(base["worst_late"] - best["worst_late"])
            reason = "建议 {} {}：{}{}，多花 ${:,.0f}{}。".format(best["key"], best["label"], so_txt, gain, best["result"]["cost_total"],
                                                         "（加班 {} 分钟 × {} 台）".format(best["result"]["overtime_min"], best["result"]["overtime_units"]) if best["result"]["overtime_min"] else "")
    return {"options": opts, "affected": names, "reason": reason, "recommended": best["key"] if best else None}
