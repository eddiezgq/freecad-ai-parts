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
                           subject=("WorkOrder", d["name"]), hint="在“经营与成本”页看分解：调整、换刀工时还是废品",
                           values={"std": k["std_cost"], "actual": k["actual_cost"], "variance_pct": k["variance_pct"]}))
    return out
