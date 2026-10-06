# -*- coding: utf-8 -*-
"""产品与研发：D1 设计改版后在制工单仍按旧版加工"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("rev_in_wip")
def rev_in_wip(c, p, r):
    rel = {}
    for m in c.db.messages(["design.release"], mode=c.mode):
        rel[m["data"]["item"]] = m
    out = []
    for item, m in rel.items():
        for w in c.db.erp_docs("Work Order", c.mode):
            d = w["data"]
            if d.get("production_item") != item or d.get("status") in ("Completed", "Cancelled", "Stopped", "Closed"):
                continue
            starts = [e for e in c.db.messages(["machine.event"], corr=d["name"], mode=c.mode, until=m["ts"])
                      if e["data"].get("event") == "cycle_start"]
            if not starts:
                continue
            n = len({e["data"]["part_serial"] for e in starts})
            out.append(Finding("{}:{}".format(d["name"], m["data"]["revision"]),
                               "{} 发布第 {} 版时，工单 {} 已有 {} 件按旧版开工".format(item, m["data"]["revision"], d["name"], n),
                               "已开工的零件按旧版继续还是返工，需要工艺员决定", subject=("WorkOrder", d["name"]),
                               about=[("WorkOrder", d["name"]), ("Item", item)],
                               evidence=[{"topic": m["_topic"], "id": m["id"], "seq": m["_seq"]}],
                               values={"revision": m["data"]["revision"], "started": n}))
    return out
