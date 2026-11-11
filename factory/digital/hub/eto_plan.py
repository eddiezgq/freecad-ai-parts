# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮 139d）：从交期倒排、工位负荷、报价时能否按期。

都是确定性计算（纯函数 + 读库），一天按 8 小时（480 分钟）算，只算工作日（周一至周五）：
- schedule()：设计发布后，按物料清单从交期往回排——发货预留 → 作业本身的工序 → 下一层自制件 → …，
  外购件、原材料的“最晚到货日” = 用它的那个件开工前一天；同时从今天往后排“最早能做完”的日子
  （设计没发布先加设计工时，采购按提前期，各件按工序时间），两者一比得出松紧，晚了说出卡在哪一段；
- load()：各工作站每周的负荷（本作业按倒排的日子 + 其他在制工单按计划日期摊开）对能力（台数 × 480 分钟 × 5 天），超了标出来；
- feasibility()：报价时（还没设计）按估算行粗算：设计工时 + 最长的采购提前期 + 工序总工时 + 发货预留 → 最早交期，和客户要的交期比。
假设（写在结果的 basis 里）：设计按一个人每天 8 小时；工序按单件分钟 × 件数串行，不细排到台；发货预留缺省 1 个工作日（清单 eto.ship_days）。
"""
import datetime as dt
import math
from collections import defaultdict

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub.kpi import add_working_days, working_days_between

DAY_MIN = 480
SHIP_DAYS = 1


def sub_working_days(d, n):
    while n > 0:
        d -= dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _workday(d, back=False):
    while d.weekday() >= 5:
        d += dt.timedelta(days=-1 if back else 1)
    return d


def _days(minutes):
    return max(1, math.ceil(minutes / DAY_MIN)) if minutes > 0 else 0


def _lead_days(code):
    """采购提前期（日历天 → 工作日）；不知道返回 None"""
    sup = (F.SUPPLIERS.get(F.ITEMS[code][4] or "") or {}) if code in F.ITEMS else {}
    lead = sup.get("lead")
    return None if lead is None else (lead * 5 // 7 or 1)


def _cfg_ship():
    return int(E.config().get("ship_days") or SHIP_DAYS)


def schedule_tree(top, qty, due, today, eng_days=0, ship_days=SHIP_DAYS):
    """纯函数：物料清单树的倒排和顺排。返回 {make: [...], buy: [...], earliest, latest_start, slack, critical}"""
    need = defaultdict(float)
    parent_of = defaultdict(set)

    def walk(n, q):
        need[n] += q
        for c, cq in (F.BOMS.get(n) or ("", []))[1]:
            parent_of[c].add(n)
            walk(c, cq * q)
    walk(top, float(qty))
    mins = {n: sum(m for _, m in F.ROUTINGS[F.BOMS[n][0]]) * need[n] for n in need if n in F.BOMS}
    dur = {n: _days(m) for n, m in mins.items()}
    # 倒排：父件开工前一天子件要做完 / 到货
    ship = _workday(due, back=True)
    finish = {top: sub_working_days(ship, ship_days)}
    start = {}
    order = [top]
    seen = set()
    while order:
        n = order.pop(0)
        if n in seen:
            continue
        if any(p not in start for p in parent_of.get(n, ())):
            order.append(n)
            continue
        seen.add(n)
        if n != top:
            finish[n] = sub_working_days(min(start[p] for p in parent_of[n]), 1)
        if n in F.BOMS:
            start[n] = sub_working_days(finish[n], dur[n] - 1) if dur[n] else finish[n]
            order.extend(c for c, _ in F.BOMS[n][1])
    # 顺排：最早能做完
    base = _workday(today)
    design_done = add_working_days(base, eng_days) if eng_days else base
    efin, why = {}, {}
    unknown = []

    def early(n):
        if n in efin:
            return efin[n]
        if n not in F.BOMS:
            lead = _lead_days(n)
            if lead is None:
                unknown.append(n)
                lead = 0
            efin[n] = add_working_days(design_done, lead) if lead else design_done
            why[n] = ("采购", n, lead)
            return efin[n]
        kids = [(early(c), c) for c, _ in F.BOMS[n][1]]
        ready = max([design_done] + [add_working_days(k, 1) for k, _ in kids])
        st = ready
        efin[n] = add_working_days(st, dur[n] - 1) if dur[n] > 1 else st
        last = max(kids)[1] if kids and max(kids)[0] >= design_done else None
        why[n] = ("加工", n, last)
        return efin[n]
    early(top)
    earliest = add_working_days(efin[top], ship_days)
    # 关键路径：从作业往下沿最晚就绪的子件走
    crit, n = [], top
    while n is not None:
        crit.append(n)
        w = why.get(n)
        n = w[2] if w and w[0] == "加工" else None
    slack = working_days_between(earliest, ship)
    make = [{"item_code": n, "name": F.ITEMS[n][0], "qty": round(need[n], 4), "minutes": round(mins[n], 1), "days": dur[n],
             "latest_start": start[n].isoformat(), "latest_finish": finish[n].isoformat(), "earliest_finish": efin[n].isoformat(),
             "late_days": max(0, working_days_between(start[n], base))}
            for n in sorted(start, key=lambda x: start[x])]
    buy = [{"item_code": n, "name": F.ITEMS[n][0], "qty": round(need[n], 4), "lead_days": _lead_days(n),
            "need_by": finish[n].isoformat(), "earliest": efin[n].isoformat(),
            "late_days": max(0, working_days_between(finish[n], efin[n]))}
           for n in sorted(need) if n not in F.BOMS and n in finish]
    return {"make": make, "buy": buy, "earliest": earliest.isoformat(), "due": due.isoformat(), "slack_days": slack,
            "design_done": design_done.isoformat(), "critical": crit, "unknown_lead": sorted(set(unknown))}


def _bottleneck(tree, eng_days):
    """晚了卡在哪：关键路径最底下是采购还是加工，设计占多少"""
    if tree["slack_days"] >= 0:
        return None
    crit = tree["critical"]
    last = crit[-1]
    parts = []
    if eng_days:
        parts.append("设计 {} 个工作日".format(eng_days))
    b = next((x for x in tree["buy"] if x["item_code"] == last), None)
    if b:
        parts.append("采购 {}（提前期 {} 个工作日）".format(last, b["lead_days"]))
    by = {x["item_code"]: x for x in tree["make"]}
    mk = [by[c] for c in reversed(crit) if c in by]
    if mk:
        parts.append("加工 {}（共 {} 个工作日）".format("→".join(x["item_code"] for x in mk), sum(x["days"] for x in mk)))
    return "晚 {} 个工作日，关键路径：{}".format(-tree["slack_days"], "；".join(parts))


def schedule(db, mode, job_no, today=None):
    j = E.job(db, mode, job_no)
    if not j:
        raise KeyError(job_no)
    if not ED.released(db, mode, job_no) or job_no not in F.BOMS:
        raise E.EtoError("设计还没发布：先看“报价时能否按期”的粗算")
    if not j.get("due_date"):
        raise E.EtoError("作业没有交期")
    today = today or dt.date.today()
    t = schedule_tree(job_no, j["qty"], dt.date.fromisoformat(j["due_date"]), today, 0, _cfg_ship())
    t["bottleneck"] = _bottleneck(t, 0)
    t["late"] = [x["item_code"] for x in t["make"] if x["late_days"]] + [x["item_code"] for x in t["buy"] if x["late_days"]]
    t["basis"] = ("从交期倒排：发货预留 {} 个工作日，父件开工前一天子件做完或到货；每件工期 = 单件分钟 × 件数 ÷ 480（一天 8 小时，串行），"
                  "采购按供应商提前期").format(_cfg_ship())
    return t


def feasibility(job, lines, today=None):
    """报价时粗算能否按期（纯函数）：设计工时 ÷ 8 + 最长采购提前期 + 工序总工时 ÷ 480 + 发货预留"""
    today = today or dt.date.today()
    qty = int(job["qty"])
    eng_h = sum(float(x.get("hours") or 0) for x in lines if x.get("kind") == "engineering")
    eng = math.ceil(eng_h / 8) if eng_h else 0
    leads, unknown = [], []
    for x in lines:
        if x.get("kind") in ("material", "buyout"):
            code = x.get("item_code")
            lt = _lead_days(code) if code in F.ITEMS else (math.ceil(float(x["lead_days"]) * 5 / 7) if x.get("lead_days") else None)
            (leads if lt is not None else unknown).append((lt, code or x.get("desc")))
        elif x.get("kind") == "outside":
            if x.get("lead_days"):
                leads.append((math.ceil(float(x["lead_days"]) * 5 / 7), x.get("desc")))
            else:
                unknown.append((None, x.get("desc")))
    buy = max(leads) if leads else (0, None)
    mfg_min = sum(float(x.get("setup_min") or 0) + float(x.get("run_min") or 0) * qty for x in lines if x.get("kind") == "operation")
    mfg = _days(mfg_min)
    ship = _cfg_ship()
    total = eng + buy[0] + mfg + ship
    earliest = add_working_days(_workday(today), total)
    out = {"engineering_days": eng, "purchase_days": buy[0], "purchase_item": buy[1], "manufacturing_days": mfg, "ship_days": ship,
           "earliest": earliest.isoformat(), "unknown": [u[1] for u in unknown],
           "basis": "粗算：设计 + 最长采购 + 全部工序串行 + 发货，一天 8 小时；设计后才采购、到齐才加工（偏保守）"}
    if job.get("due_date"):
        due = dt.date.fromisoformat(job["due_date"])
        out["due"] = due.isoformat()
        out["slack_days"] = working_days_between(earliest, _workday(due, back=True))
        out["ok"] = out["slack_days"] >= 0 and not unknown
    return out


def load(db, mode, job_no=None, today=None):
    """各工作站每周负荷：其他在制工单（未完成数 × 工序分钟，按计划开工到计划完工的工作日摊开）+ 本作业（按倒排）"""
    from hub.kpi import Overview
    today = today or dt.date.today()
    o = Overview(db, None, mode)
    week = lambda d: (d - dt.timedelta(days=d.weekday())).isoformat()  # noqa: E731
    used = defaultdict(lambda: defaultdict(float))
    mine = defaultdict(lambda: defaultdict(float))

    def spread(bucket, item, qty, a, b):
        if item not in F.BOMS or qty <= 0:
            return
        days, d = [], _workday(a)
        while d <= b or not days:
            if d.weekday() < 5:
                days.append(d)
            d += dt.timedelta(days=1)
        for op, m in F.ROUTINGS[F.BOMS[item][0]]:
            ws = F.OPERATIONS.get(op)
            for d in days:
                bucket[ws][week(d)] += m * qty / len(days)
    proj = E.project_of(E.job(db, mode, job_no)) if job_no else None
    for w in o.wos:
        d = w["data"]
        if d.get("status") in ("Completed", "Stopped", "Closed", "Cancelled") or d.get("docstatus") == 2:
            continue
        if proj and d.get("project") == proj:
            continue
        try:
            a = dt.date.fromisoformat(str(d.get("planned_start_date"))[:10])
            b = dt.date.fromisoformat(str(d.get("expected_delivery_date") or d.get("planned_start_date"))[:10])
        except ValueError:
            continue
        left = float(d.get("qty", 0)) - float(d.get("produced_qty", 0) or 0)
        spread(used, d.get("production_item"), left, max(a, today), max(b, a, today))
    if job_no:
        t = schedule(db, mode, job_no, today)
        for x in t["make"]:
            spread(mine, x["item_code"], x["qty"], max(dt.date.fromisoformat(x["latest_start"]), today),
                   max(dt.date.fromisoformat(x["latest_finish"]), today))
    rows = []
    for ws, (count, _) in F.WORKSTATIONS.items():
        par = (getattr(F, "WORKSTATION_PARALLEL", {}) or {}).get(ws) or count
        cap = par * DAY_MIN * 5
        for wk in sorted(set(used[ws]) | set(mine[ws])):
            tot = used[ws][wk] + mine[ws][wk]
            if mine[ws][wk] or tot > cap:
                rows.append({"workstation": ws, "week": wk, "others_min": round(used[ws][wk]), "job_min": round(mine[ws][wk]),
                             "capacity_min": cap, "load_pct": round(tot / cap * 100), "over": tot > cap})
    return {"rows": rows, "basis": "能力 = 同时开工数 × 480 分钟 × 5 天；工单按计划开工到计划完工的工作日平均摊开"}
