# -*- coding: utf-8 -*-
"""算料（MRP）与工单成本。

plan_order()：一张新订单 → 多级展开 → 按“毛需求 + 其他在手订单占用 − 库存 − 在途”算净需求，
给出要建的销售订单、工单、物料请购单。第 1 轮只对输出轴 SH-301 下达工单（决定 F4），
其余自制件列出需求但注明“本轮不下达”。结果就是 AI 提议 / 计划员表单的预览内容，
人确认后原样交给桥接写入 ERPNext。

wo_cost()：按总线历史算一张工单的标准成本与实际成本，并按工序拆开，回答“为什么超了”。
"""
import datetime as dt
import math
from collections import defaultdict

from factory import data as F
from factory import plant as _plant
from sim.engine import OP_UNITS, SETUP_MIN, TOOL_CHANGE_MIN, expected_minutes, routing_for
from hub.kpi import TZ, add_working_days, explode, rate_per_hour, Overview

RELEASED_THIS_ROUND = {"SH-301"}
LOT = {"raw_kg": 50, "default": 10}
COMPANY = _plant.company()["name"]       # 工厂清单的公司（第 30 轮）；演示工厂仍是“问渠减速器厂 WenQuest Gearbox (Demo)”


def lot_size(code):
    if str(F.ITEMS[code][4] or "").startswith("lib:"):   # 选型零件库来的外购件（freecad-ai-parts）按需采购，不凑批量
        return 1
    return LOT["raw_kg"] if F.ITEMS[code][2] == "Kg" else LOT["default"]


def std_rollup(item):
    """多层标准成本（第 47 轮）：材料按物料清单逐层累加到外购件、原材料；工序分本层和含下层的合计"""
    if item not in F.BOMS:
        return {"material": float(F.ITEMS[item][3] or 0), "operations_own": 0.0, "operations": 0.0}
    mat = below = 0.0
    for c, q in F.BOMS[item][1]:
        r = std_rollup(c)
        mat += q * r["material"]
        below += q * r["operations"]
    own = sum(mins / 60 * rate_per_hour(OP_UNITS[op][0]) for op, mins in routing_for(item))
    return {"material": mat, "operations_own": own, "operations": own + below}


def std_unit_cost(item):
    """标准成本：材料（逐层累加）+ 本层各工序（工时 × 工位小时费率）。输出轴这类只有原材料的件与原来一样。"""
    r = std_rollup(item)
    return round(r["material"], 2), round(r["operations_own"], 2)


SOURCE_OF = {"make": "semi", "sub": "semi", "buy": "purchased", "raw": "raw"}   # 物料类别 → 领料仓库（桥接按它填工单）


def _source(code):
    """领料仓库：清单第 2 版写的物料按类别（期初库存按类别进库，第 45 轮）；新产品进工厂的外购件到货进原材料库，照旧从原材料库领"""
    kind = F.ITEMS[code][1]
    act = _plant.active() or {}
    if kind == "buy" and code not in (act.get("ITEMS") or {}):
        return "raw"
    return SOURCE_OF.get(kind, "raw")


def plan_order(db, customer, item, qty, delivery_date, mode="teach", now=None):
    o = Overview(db, now, mode)
    today = o.now.astimezone(TZ).date()
    qty = int(qty)
    due = dt.date.fromisoformat(str(delivery_date)[:10])
    stock = o.stock()
    # 在途：未收完的采购单 + 已提交未转采购的请购单
    on_order = defaultdict(float)
    for p in o.pos:
        if p["data"].get("status") not in ("Completed", "Closed", "Cancelled"):
            for it in p["data"].get("items", []):
                on_order[it["item_code"]] += float(it.get("qty", 0)) - float(it.get("received_qty", 0))
    for r in o.mrs:
        if r["data"].get("status") not in ("Ordered", "Stopped", "Cancelled", "Transferred"):
            for it in r["data"].get("items", []):
                on_order[it["item_code"]] += float(it.get("qty", 0))
    # 其他在手订单的占用：未下工单的订单按成品展开；已下工单按工单未完成量展开
    committed = defaultdict(float)
    for s in o.sos:
        d = s["data"]
        if d.get("status") in ("Completed", "Closed", "Cancelled"):
            continue
        for it in d.get("items", []):
            left = float(it.get("qty", 0)) - float(it.get("delivered_qty", 0))
            for c, q in explode(it["item_code"], left).items():
                committed[c] += q
    for w in o.wos:
        d = w["data"]
        if d.get("status") in ("Completed", "Stopped", "Closed", "Cancelled"):
            continue
        started = any(e["data"].get("work_order") == d["name"] for e in o.events
                      if e["data"]["event"] == "cycle_start" and e["data"].get("op_index") == 0)
        if started:          # 已开始下料，原材料已领用，不再占用
            for c, q in F.BOMS.get(d.get("production_item"), ("", []))[1]:
                committed[c] -= q * float(d.get("qty", 0))
    gross = explode(item, qty)
    rows, mrs, warnings = [], [], []
    start = today if o.now.astimezone(TZ).hour < 12 and today.weekday() < 5 else add_working_days(today, 1)
    for code in sorted(gross, key=lambda c: (F.ITEMS[c][1], c)):
        g = gross[code]
        st = stock.get(code, {}).get("actual", 0.0)
        oo = on_order.get(code, 0.0)
        cm = max(0.0, committed.get(code, 0.0))
        safety = F.SAFETY_STOCK.get(code, 0)
        net = g + cm + safety - st - oo
        action = "库存够用"
        if net > 1e-6:
            q = math.ceil(net / lot_size(code)) * lot_size(code)
            sup = F.SUPPLIERS[F.ITEMS[code][4]]
            if sup.get("lead") is None:      # 清单或登记的产品里供应商没填交期：不估，标待确认
                sched = start
                warnings.append("{} 的采购交期待确认（{} 没有登记提前期），请购单需求日暂按 {}".format(
                    code, sup["name"], start.isoformat()))
            else:
                sched = add_working_days(start, sup["lead"] * 5 // 7 or 1)
            mrs.append({"item_code": code, "qty": q, "uom": F.ITEMS[code][2], "schedule_date": sched.isoformat(),
                        "supplier": sup["name"], "reason": "净需求 {:g}，按批量 {} 取整".format(round(net, 2), lot_size(code))})
            action = "请购 {:g}".format(q)
            if sup.get("lead") is not None and sched > due:
                warnings.append("{} 采购提前期 {} 天，预计 {} 到货，晚于交期 {}".format(
                    code, sup["lead"], sched.isoformat(), due.isoformat()))
        rows.append({"item_code": code, "name": F.ITEMS[code][0], "kind": F.ITEMS[code][1],
                     "uom": F.ITEMS[code][2], "gross": round(g, 3), "committed": round(cm, 3),
                     "stock": st, "on_order": oo, "safety": safety, "net": round(max(0.0, net), 3),
                     "action": action})
    # 自制件：演示产品 WQR-105 按教学只下达 SH-301；其他产品（企业登记的新产品等）下达全部自制件和产品本身
    wos, deferred = [], []
    whole = item != "WQR-105" and item in F.BOMS
    makes = explode_make(item, qty)
    if whole:
        makes[item] = qty
    for code, q in makes.items():
        if code in RELEASED_THIS_ROUND or whole:
            mins = expected_minutes(code, int(q))
            days = max(1, math.ceil(mins / 480))
            end = add_working_days(start, days - 1) if days > 1 else start
            w = {"production_item": code, "qty": int(q), "bom_no": None, "planned_start_date": start.isoformat(),
                 "expected_delivery_date": end.isoformat(), "est_minutes": mins,
                 "routing": [op for op, _ in routing_for(code)]}
            if whole:   # 成品进成品库、自制件进半成品库；领料：自制件、部件从半成品库，外购件从外购件库，原材料从原材料库
                w["warehouse"] = "fg" if code == item else "semi"
                w["sources"] = {c: _source(c) for c, _ in F.BOMS[code][1]}
            wos.append(w)
        else:
            deferred.append({"item_code": code, "qty": q, "name": F.ITEMS[code][0]})
    std = None
    if _plant.is_demo():                # 演示工厂的输出轴标准成本；企业工厂没有这道工艺
        mat, ops = std_unit_cost("SH-301")
        std = {"material": mat, "operations": ops, "total": round(mat + ops, 2)}
    # 售价：可接单成品的售价（清单 products；演示工厂 WQR-105 = FG_SELLING_PRICE），没有再取物料主数据（都没有就不填）
    price = F.PRODUCTS.get(item) if F.PRODUCTS.get(item) is not None else (F.ITEMS.get(item) or (None,) * 4)[3]
    preview = {
        "sales_order": {"customer": customer, "company": COMPANY, "item_code": item, "qty": qty,
                        "rate": price, "amount": price * qty if price is not None else None,
                        "delivery_date": due.isoformat(), "transaction_date": today.isoformat()},
        "mrp": rows,
        "work_orders": wos,
        "material_requests": mrs,
        "deferred": deferred,
        "warnings": warnings,
        "std_cost_sh301": std,
        "basis": "库存取自 office/erp/bin 最新快照；在途取自采购单与请购单；占用取自在手订单与未开工工单",
    }
    return preview


def explode_make(item, qty):
    """展开出所有自制件（含部件）的数量。"""
    out = defaultdict(float)
    if item not in F.BOMS:
        return out
    for c, q in F.BOMS[item][1]:
        if F.ITEMS[c][1] in ("make", "sub"):
            out[c] += q * qty
            for k, v in explode_make(c, q * qty).items():
                out[k] += v
    return out


def wo_cost(db, work_order, mode="teach"):
    """一张工单的标准与实际成本（只算已完成的加工；材料按标准用量计）。"""
    evs = db.messages(["machine.event"], corr=work_order, mode=mode)
    ends = [e for e in evs if e["data"]["event"] == "cycle_end"]
    if not ends:
        return None
    item = ends[0]["data"].get("item", "SH-301")
    by_op = {}
    for e in ends:
        d = e["data"]
        unit = e["_topic"].split("/")[3]
        r = rate_per_hour(unit) / 3600
        k = (d.get("op_index", 0), d["operation"], unit)
        row = by_op.setdefault(k, {"op_index": k[0], "operation": k[1], "unit": unit, "rate_h": rate_per_hour(unit),
                                   "parts": 0, "std_s": 0.0, "cycle_s": 0.0, "setup_s": 0.0, "tool_change_s": 0.0})
        row["parts"] += 1
        row["std_s"] += d.get("std_time_s", 0)
        row["cycle_s"] += d.get("cycle_time_s", 0)
    for row in by_op.values():
        row["setup_s"] = SETUP_MIN.get(row["unit"], 5) * 60
    for e in evs:
        if e["data"]["event"] == "tool_change":
            unit = e["_topic"].split("/")[3]
            for row in by_op.values():
                if row["unit"] == unit:
                    row["tool_change_s"] += TOOL_CHANGE_MIN.get(unit, 5) * 60
                    break
    std = act = 0.0
    lines = []
    for row in sorted(by_op.values(), key=lambda r: r["op_index"]):
        r = row["rate_h"] / 3600
        s = row["std_s"] * r
        a = (row["cycle_s"] + row["setup_s"] + row["tool_change_s"]) * r
        std += s
        act += a
        lines.append(dict(row, std_cost=round(s, 2), actual_cost=round(a, 2), variance=round(a - s, 2)))
    finished = sum(1 for e in ends if e["data"].get("op_index") == e["data"].get("n_ops", 0) - 1)
    mat = sum(q * (F.ITEMS[c][3] or 0) for c, q in F.BOMS[item][1])
    setup_total = sum((l["setup_s"] + l["tool_change_s"]) * l["rate_h"] / 3600 for l in lines)
    overrun_total = sum((l["cycle_s"] - l["std_s"]) * l["rate_h"] / 3600 for l in lines)
    worst = max(lines, key=lambda l: l["variance"]) if lines else None
    return {
        "work_order": work_order, "item": item, "parts_finished": finished,
        "std_cost": round(std, 2), "actual_cost": round(act, 2), "variance": round(act - std, 2),
        "variance_pct": round((act - std) / std * 100, 1) if std else None,
        "material_std_per_unit": round(mat, 2),
        "setup_cost": round(setup_total, 2), "overrun_cost": round(overrun_total, 2),
        "worst_operation": worst["operation"] if worst else None,
        "lines": lines,
        "note": "加工成本 = 工时 × 工位小时费率（折旧 + 人工 + 能耗）；标准只含单件工时，实际另含调整与换刀。材料按 BOM 标准用量计。",
        "evidence": {"topic": "wq/gearbox/machining/+/event", "corr": work_order, "messages": len(ends)},
    }
