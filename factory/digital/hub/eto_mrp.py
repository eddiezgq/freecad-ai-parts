# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139c）：按作业号专料专用的算料。

plan()：设计发布后，从作业逐层往下算（按低层码，一个件所有父件算完才算它）：
- 本单专用件（编号以作业号开头）：不用库存，只认已经挂在这个作业上的工单、请购单、采购单；
- 通用件：先用自由库存（实有 − 安全库存 − 其他在手订单的占用），再认挂在本作业上的在途；
- 自制件的净需求下工单（挂作业号），它的子件按净需求往下展开；外购件、原材料的净需求下请购（挂作业号，按批量取整）；
- 设计里的外协：按作业件数请购外协服务（不进库存的服务物料，编号 = 作业号-OS序号）。
结果是“作业算料”提议的预览，人确认后桥接写入 ERPNext（工单、请购单都挂 Project）。

early_buy_preview()：长周期件提前采购——设计还没发布时，从当前设计草稿里挑外购件、原材料先请购（要人确认，单独留记录）。
"""
import datetime as dt
import math
from collections import defaultdict

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub import mrp
from hub.kpi import TZ, Overview, add_working_days


def _pegged(o, job_no):          # job_no：作业在 ERPNext 里的项目名（E.project_of）
    """已经挂在这个作业上的供应：工单（未完成数）、请购单与采购单（未收数）"""
    sup = defaultdict(float)
    for w in o.wos:
        d = w["data"]
        if d.get("project") == job_no and d.get("status") not in ("Stopped", "Closed", "Cancelled") and d.get("docstatus") != 2:
            sup[d.get("production_item")] += float(d.get("qty", 0))
    for r in o.mrs:          # 请购单转了采购单（Ordered）之后按采购单算，和通用算料一样
        d = r["data"]
        if d.get("project") == job_no and d.get("status") not in ("Ordered", "Stopped", "Cancelled", "Transferred") and d.get("docstatus") != 2:
            for it in d.get("items", []):
                sup[it["item_code"]] += float(it.get("qty", 0))
    for p in o.pos:
        d = p["data"]
        if d.get("project") == job_no and d.get("status") not in ("Closed", "Cancelled") and d.get("docstatus") != 2:
            for it in d.get("items", []):
                sup[it["item_code"]] += float(it.get("qty", 0))          # 收到的进了库也是这一单的（专料专用），整单都算
    return sup


def _llc(top):
    """低层码：一个件出现在物料清单里的最深层数"""
    lv = {top: 0}

    def walk(n, d):
        for c, _ in (F.BOMS.get(n) or ("", []))[1]:
            if lv.get(c, -1) < d + 1:
                lv[c] = d + 1
                walk(c, d + 1)
    walk(top, 0)
    return lv


def _lead(code):
    sup = F.SUPPLIERS.get(F.ITEMS[code][4]) if F.ITEMS[code][4] else None
    return (sup or {}).get("lead"), (sup or {}).get("name")


def plan(db, mode, job_no, now=None):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    rel = ED.released(db, mode, job_no)
    if not rel or job_no not in F.BOMS:
        raise E.EtoError("作业 {} 的设计还没发布，不能算料".format(job_no))
    if not j.get("sales_order"):
        raise E.EtoError("作业还没接单")
    o = Overview(db, now, mode)
    today = o.now.astimezone(TZ).date()
    start = today if o.now.astimezone(TZ).hour < 12 and today.weekday() < 5 else add_working_days(today, 1)
    due = dt.date.fromisoformat(j["due_date"]) if j.get("due_date") else None
    # 第 139d 段：工单、请购的日期按从交期倒排的结果（没有交期时从今天起）
    from hub import eto_plan as EP
    sch = EP.schedule_tree(job_no, j["qty"], due, start, 0, EP._cfg_ship()) if due else None
    smk = {x["item_code"]: x for x in (sch or {}).get("make", [])}
    sby = {x["item_code"]: x for x in (sch or {}).get("buy", [])}
    stock = o.stock()
    on_order, committed = mrp.supply_demand(o, exclude_project=E.project_of(j))
    proj = E.project_of(j)
    pegged = _pegged(o, proj)
    own = lambda c: c == job_no or c.startswith(job_no + "-")  # noqa: E731
    lv = _llc(job_no)
    gross = defaultdict(float)
    gross[job_no] = float(j["qty"])
    rows, wos, mrs, warns = [], [], [], []
    for code in sorted(lv, key=lambda c: (lv[c], c)):
        g = gross[code]
        if g <= 0:
            continue
        kind = F.ITEMS[code][1]
        make = code in F.BOMS
        peg = pegged.get(code, 0.0)
        free = 0.0 if own(code) else max(0.0, stock.get(code, {}).get("actual", 0.0) - F.SAFETY_STOCK.get(code, 0) - max(0.0, committed.get(code, 0.0)))
        net = max(0.0, g - peg - free)
        action = "够用"
        if net > 1e-9:
            if make:
                q = math.ceil(net)
                mins = sum(m for _, m in F.ROUTINGS[F.BOMS[code][0]]) * q
                days = max(1, math.ceil(mins / 480))
                ws_ = start
                if code in smk:
                    ls = dt.date.fromisoformat(smk[code]["latest_start"])
                    if ls < start:
                        warns.append("{} 按交期倒排应在 {} 开工，已经晚了 {} 个工作日".format(code, ls.isoformat(), smk[code]["late_days"]))
                    ws_ = max(ls, start)
                wos.append({"production_item": code, "qty": q, "planned_start_date": ws_.isoformat(),
                            "expected_delivery_date": add_working_days(ws_, days - 1).isoformat(), "est_minutes": round(mins, 1),
                            "warehouse": "fg" if code == job_no else "semi",
                            "sources": {c: ("semi" if c in F.BOMS else ("raw" if F.ITEMS[c][1] == "raw" else "purchased"))
                                        for c, _ in F.BOMS[code][1]}})
                for c, qq in F.BOMS[code][1]:
                    gross[c] += qq * q
                action = "工单 {:g}".format(q)
            else:
                q = net if own(code) else math.ceil(net / mrp.lot_size(code)) * mrp.lot_size(code)
                q = round(q, 4)
                lead, sup = _lead(code)
                arrive = add_working_days(start, lead * 5 // 7 or 1) if lead is not None else None
                need_by = dt.date.fromisoformat(sby[code]["need_by"]) if code in sby else None
                if lead is None:
                    sched = max(need_by or start, start)
                    warns.append("{} 的采购交期待确认（没有供应商或提前期），需求日按 {}".format(code, sched.isoformat()))
                else:
                    sched = max(need_by or arrive, arrive)       # 需求日 = 倒排的最晚到货日；来不及就按最早能到的日子
                    if need_by and arrive > need_by:
                        warns.append("{} 采购提前期 {} 天，最早 {} 到货，晚于倒排要求的 {}".format(code, lead, arrive.isoformat(), need_by.isoformat()))
                mrs.append({"item_code": code, "qty": q, "uom": F.ITEMS[code][2], "schedule_date": sched.isoformat(), "wh": "raw" if kind == "raw" else "purchased",
                            "supplier": sup, "reason": "作业 {} 净需求 {:g}".format(job_no, round(net, 4))})
                action = "请购 {:g}".format(q)
        rows.append({"item_code": code, "name": F.ITEMS[code][0], "kind": kind, "level": lv[code], "own": own(code),
                     "gross": round(g, 4), "free_stock": round(free, 4), "pegged": round(peg, 4), "net": round(net, 4), "action": action})
    services = []
    for i, x in enumerate(rel["spec"].get("outside") or [], start=1):
        code = "{}-OS{:02d}".format(job_no, i)
        have = pegged.get(code, 0.0)
        need = float(j["qty"]) - have
        services.append({"code": code, "name": "外协 {}".format(x.get("desc") or code)[:140]})
        if need > 1e-9:
            lead = x.get("lead_days")
            mrs.append({"item_code": code, "qty": need, "uom": "Nos", "service": True, "wh": "purchased",
                        "schedule_date": (add_working_days(start, int(lead) * 5 // 7 or 1) if lead else start).isoformat(),
                        "supplier": None, "reason": "外协（{}）".format(x.get("desc") or "")})
            if not lead:
                warns.append("外协 {} 没写周期，需求日暂按 {}".format(x.get("desc") or code, start.isoformat()))
    return {"job": {"job_no": job_no, "title": j["title"], "qty": j["qty"], "design_rev": rel["rev"], "sales_order": j["sales_order"],
                    "project": proj},
            "mrp": rows, "work_orders": wos, "material_requests": mrs, "service_items": services, "warnings": warns,
            "basis": "本单专用件只认挂在作业上的工单、请购单；通用件先用自由库存（实有 − 安全库存 − 其他订单占用），再认挂在作业上的在途"}


LONG_LEAD_DAYS = 15        # 缺省：提前期 ≥ 15 天算长周期件（工厂清单 eto.long_lead_days 可改）


def early_buy_preview(db, mode, job_no, codes):
    """设计还没发布时先买长周期件：只从当前设计草稿里挑外购件、原材料；作业要已接单；数量 = 每件用量 × 作业件数（不按批量）"""
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if not j.get("sales_order"):
        raise E.EtoError("作业还没接单，不能提前采购")
    d = ED.latest(db, mode, job_no)
    if not d:
        raise E.EtoError("还没有设计")
    if d["status"] == "released":
        raise E.EtoError("设计已经发布：请用“作业算料”")
    spec = d["spec"]
    new = {i["code"]: i for i in spec.get("items") or []}
    use = defaultdict(float)
    for b in spec.get("boms") or []:
        for c, q in b["components"]:
            use[c] += float(q)
    th = int((E.config().get("long_lead_days") or LONG_LEAD_DAYS))
    rows = []
    for c in codes:
        if c in new:
            if new[c]["kind"] == "make":
                raise E.EtoError("{} 是自制件，不能提前采购".format(c))
            sup = F.SUPPLIERS.get(new[c].get("supplier") or "", {})
            name, uom = new[c]["name"], new[c]["uom"]
        elif c in F.ITEMS and F.ITEMS[c][1] in ("buy", "raw"):
            sup = F.SUPPLIERS.get(F.ITEMS[c][4] or "", {})
            name, uom = F.ITEMS[c][0], F.ITEMS[c][2]
        else:
            raise E.EtoError("{} 不是设计里的外购件或原材料".format(c))
        if c not in use:
            raise E.EtoError("{} 没用在设计的物料清单里".format(c))
        lead = sup.get("lead")
        if lead is None or lead < th:
            raise E.EtoError("{} 的提前期 {} 天，不算长周期件（≥ {} 天才能提前买）".format(c, lead if lead is not None else "未知", th))
        kind = new[c]["kind"] if c in new else F.ITEMS[c][1]
        rows.append({"item_code": c, "name": name, "qty": round(use[c] * j["qty"], 4), "uom": uom, "new": c in new, "wh": "raw" if kind == "raw" else "purchased",
                     "new_item": dict(new[c], item_group=F.KIND_GROUP[new[c]["kind"]], supplier=sup.get("name"), lead=lead) if c in new else None,
                     "schedule_date": add_working_days(dt.date.today(), lead * 5 // 7 or 1).isoformat(), "supplier": sup.get("name"),
                     "reason": "长周期件提前采购（设计第 {} 版{}）".format(d["rev"], "，未发布" if d["status"] != "released" else "")})
    if not rows:
        raise E.EtoError("没有选物料")
    return {"job": {"job_no": job_no, "title": j["title"], "design_rev": d["rev"], "design_status": d["status"], "project": E.project_of(j)},
            "material_requests": rows}


def early_candidates(db, mode, job_no):
    """当前设计里能提前采购的长周期件（外购件、原材料，提前期达到门槛）"""
    d = ED.latest(db, mode, job_no)
    if not d:
        return {"threshold": int(E.config().get("long_lead_days") or LONG_LEAD_DAYS), "items": []}
    th = int(E.config().get("long_lead_days") or LONG_LEAD_DAYS)
    new = {i["code"]: i for i in d["spec"].get("items") or []}
    out, seen = [], set()
    for b in d["spec"].get("boms") or []:
        for c, _ in b["components"]:
            if c in seen:
                continue
            seen.add(c)
            if c in new:
                kind, sup = new[c]["kind"], new[c].get("supplier")
                name = new[c]["name"]
            elif c in F.ITEMS:
                kind, sup, name = F.ITEMS[c][1], F.ITEMS[c][4], F.ITEMS[c][0]
            else:
                continue
            lead = (F.SUPPLIERS.get(sup or "") or {}).get("lead")
            if kind in ("buy", "raw") and lead is not None and lead >= th:
                out.append({"item_code": c, "name": name, "lead": lead, "new": c in new})
    return {"threshold": th, "items": out, "design_rev": d["rev"], "design_status": d["status"]}
