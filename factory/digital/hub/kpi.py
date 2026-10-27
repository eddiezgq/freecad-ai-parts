# -*- coding: utf-8 -*-
"""看板指标：全部从历史库计算（附录 A.4 第 3 条）。

overview() 返回首页八个区域需要的数据；AI 助手回答问题、写今日简报也用这里的结果，
所以每个数字都带上来源（主题、单号或消息编号），方便追问和核对。
"""
import datetime as dt
import math
import os
from collections import defaultdict
from zoneinfo import ZoneInfo

from factory import data as F
from wqbus import MACHINES, UNITS
from wqbus.topics import unit_topic

TZ = ZoneInfo(os.environ.get("WQ_TZ", "America/New_York"))
SHIFT_MIN = 480
TARGET = {"on_time": 0.95, "oee": 0.75, "fpy": 0.97}
from factory import plant as _plant  # noqa: E402  工厂清单（第 30 轮；freecad-ai-parts ADR-0064）
if _plant.active():
    SHIFT_MIN, TARGET = _plant.active()["SHIFT_MIN"], dict(_plant.active()["TARGET"])
KEY_MATERIALS = ["BRG-6207", "RM-45-D50", "RM-40CR-F225", "OIL-CKC220"]
CHARTS = {"bearing_seat_d35": "SH-301 轴承位 Ø35k6"}


def rate_per_hour(unit):
    ws = UNITS[unit][3]
    return float(sum(F.WORKSTATIONS[ws][1])) if ws in F.WORKSTATIONS else 0.0


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def local_day_start(t):
    lt = t.astimezone(TZ)
    return dt.datetime(lt.year, lt.month, lt.day, tzinfo=TZ).astimezone(dt.timezone.utc)


def week_start(t):
    d0 = local_day_start(t)
    return d0 - dt.timedelta(days=t.astimezone(TZ).weekday())


def add_working_days(d, n):
    """从日期 d 往后数 n 个工作日（周一至周五）。"""
    while n > 0:
        d += dt.timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def working_days_between(a, b):
    """a < b 时 b 比 a 晚几个工作日（负数表示提前）。"""
    if a == b:
        return 0
    sign, (x, y) = (1, (a, b)) if a < b else (-1, (b, a))
    n = 0
    while x < y:
        x += dt.timedelta(days=1)
        if x.weekday() < 5:
            n += 1
    return sign * n


def unit_label(uom):
    return {"Kg": "kg", "Nos": "件", "Litre": "L"}.get(uom, uom)


def explode(item, qty):
    """多级展开到外购件和原材料：{物料: 数量}。"""
    out = defaultdict(float)
    if item not in F.BOMS:
        out[item] += qty
        return out
    for c, q in F.BOMS[item][1]:
        for k, v in explode(c, q * qty).items():
            out[k] += v
    return out


class Overview:
    """一次计算用一个实例：把本次要用的消息一次取出，避免重复查询。"""

    def __init__(self, db, now=None, mode="teach"):
        self.db = db
        self.now = now or dt.datetime.now(dt.timezone.utc)
        self.mode = mode
        self.day0 = local_day_start(self.now)
        self.week0 = week_start(self.now)
        self.month0 = local_day_start(self.now).astimezone(TZ).replace(day=1).astimezone(dt.timezone.utc)
        since = min(self.week0, self.now - dt.timedelta(days=30))
        self.events = db.messages(["machine.event"], since=since, until=self.now, mode=mode)
        self.meas = db.messages(["quality.measurement"], since=self.week0 - dt.timedelta(days=7),
                                until=self.now, mode=mode)
        st = db.latest_per_topic(["machine.status"], mode=mode, topic_like="wq/gearbox/%/status")
        self.status = {t.split("/")[3]: m for t, m in st.items()}
        ag = db.latest_per_topic(["logistics.status"], mode=mode)
        self.agvs = {t.split("/")[3]: m for t, m in ag.items()}
        self.sos = [m for m in db.erp_docs("Sales Order", mode) if m["data"].get("status") not in ("Cancelled",)]
        self.wos = [m for m in db.erp_docs("Work Order", mode) if m["data"].get("status") not in ("Cancelled",)]
        self.bins = db.erp_docs("Bin", mode)
        self.pos = db.erp_docs("Purchase Order", mode)
        self.mrs = db.erp_docs("Material Request", mode)
        self.ncr_open = db.q("select * from ncr where status='open' and (mode=%s or mode is null) order by created_at",
                             (mode,))
        self.started_wos, self.done_by_wo = set(), defaultdict(int)
        for m in self.events:
            d = m["data"]
            if d["event"] == "cycle_start" and d.get("op_index") == 0:
                self.started_wos.add(d.get("work_order"))
            elif d["event"] == "cycle_end" and d.get("n_ops") and d.get("op_index") == d["n_ops"] - 1 and d.get("good", True):
                self.done_by_wo[d.get("work_order")] += 1
        self.demo = bool(db.one("select 1 as x from bus_message where source like 'demo%%' and mode=%s limit 1", (mode,)))

    # ------------------------------------------------------------ 公共小工具
    def _ev(self, name, since=None, unit=None):
        out = []
        for m in self.events:
            if m["data"]["event"] != name:
                continue
            if since and parse_ts(m["ts"]) < since:
                continue
            if unit and m["_topic"].split("/")[3] != unit:
                continue
            out.append(m)
        return out

    def _state_durations(self, unit, since, until=None):
        until = until or self.now
        rows = self.db.q("select ts, state from machine_state_log where unit=%s and mode=%s and ts < %s "
                         "and ts >= %s order by ts", (unit, self.mode, until, since))
        prev = self.db.one("select state from machine_state_log where unit=%s and mode=%s and ts < %s "
                           "order by ts desc limit 1", (unit, self.mode, since))
        dur = defaultdict(float)
        cur_t, cur_s = since, prev["state"] if prev else None
        for r in rows:
            if cur_s:
                dur[cur_s] += (r["ts"] - cur_t).total_seconds()
            cur_t, cur_s = r["ts"], r["state"]
        if cur_s:
            dur[cur_s] += (until - cur_t).total_seconds()
        return dur

    # ------------------------------------------------------------ 各项指标
    def oee(self, since=None):
        since = since or self.day0
        fp = self.fpy(since)
        q = fp["value"] if fp["value"] is not None else 1.0
        per, tot_load, tot_w = {}, 0.0, 0.0
        for u in MACHINES:
            d = self._state_durations(u, since)
            load = d["run"] + d["setup"] + d["down"] + d["fault"]
            if load < 60:
                continue
            a = d["run"] / load
            ends = [e for e in self._ev("cycle_end", since, u)]
            std = sum(e["data"].get("std_time_s", 0) for e in ends)
            act = sum(e["data"].get("cycle_time_s", 0) for e in ends)
            p = min(1.0, std / act) if act else 1.0
            val = a * p * q
            per[u] = {"oee": val, "availability": a, "performance": p, "quality": q, "loading_s": load,
                      "down_s": d["down"] + d["fault"], "setup_s": d["setup"], "run_s": d["run"]}
            tot_load += load
            tot_w += val * load
        plant = tot_w / tot_load if tot_load else None
        return {"value": plant, "machines": per}

    def fpy(self, since):
        first = {}
        for m in self.meas:
            if parse_ts(m["ts"]) < since:
                continue
            d = m["data"]
            ok = d["result"] == "pass"
            first[d["part_serial"]] = first.get(d["part_serial"], True) and ok
        if not first:
            return {"value": None, "parts": 0, "failed": 0}
        good = sum(1 for v in first.values() if v)
        return {"value": good / len(first), "parts": len(first), "failed": len(first) - good}

    def wip(self, at=None):
        at = at or self.now
        started, finished = set(), set()
        for m in self.events:
            if parse_ts(m["ts"]) > at:
                continue
            d = m["data"]
            if d["event"] == "cycle_start" and d.get("op_index") == 0:
                started.add(d["part_serial"])
            elif d["event"] == "cycle_end" and d.get("n_ops") and d.get("op_index") == d["n_ops"] - 1:
                finished.add(d["part_serial"])
        return len(started - finished)

    def completions(self, since, until=None):
        """每个本地日期完工（最后一道工序完成且合格）的件数，按物料分。"""
        out = defaultdict(lambda: defaultdict(int))
        for e in self._ev("cycle_end", since):
            d = e["data"]
            if until and parse_ts(e["ts"]) > until:
                continue
            if d.get("n_ops") and d.get("op_index") == d["n_ops"] - 1 and d.get("good", True):
                out[d.get("item", "?")][parse_ts(e["ts"]).astimezone(TZ).date()] += 1
        return out

    def wo_plan(self):
        """每个工作日计划完工件数：工单数量平摊到计划开工—计划完工之间的工作日。"""
        plan = defaultdict(lambda: defaultdict(float))
        for w in self.wos:
            d = w["data"]
            if d.get("docstatus", 1) != 1 and d.get("status") not in ("Not Started", "In Process", "Completed"):
                continue
            try:
                a = dt.date.fromisoformat(str(d.get("planned_start_date"))[:10])
                b = dt.date.fromisoformat(str(d.get("expected_delivery_date") or d.get("planned_start_date"))[:10])
            except ValueError:
                continue
            days = [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]
            days = [x for x in days if x.weekday() < 5] or [a]
            for x in days:
                plan[d.get("production_item", "?")][x] += float(d.get("qty", 0)) / len(days)
        return plan

    def cost(self, since):
        std = act = setup = 0.0
        for e in self._ev("cycle_end", since):
            u = e["_topic"].split("/")[3]
            r = rate_per_hour(u) / 3600
            std += e["data"].get("std_time_s", 0) * r
            act += e["data"].get("cycle_time_s", 0) * r
        for u in MACHINES:
            setup += self._state_durations(u, since)["setup"] * rate_per_hour(u) / 3600
        done = sum(sum(v.values()) for v in self.completions(since).values())
        if std <= 0:
            return {"value": None}
        var = (act + setup - std) / std
        return {"value": var, "std": std, "actual": act + setup, "setup": setup, "overrun": act - std,
                "per_unit": (act + setup - std) / done if done else None, "units": done,
                "driver": "调整与换刀工时" if setup >= (act - std) else "加工超时"}

    # ------------------------------------------------------------ 订单
    def produced(self, wo):
        """工单已完工数：ERPNext 的 produced_qty 与总线上最后一道工序合格完工数取大者。"""
        return max(float(wo.get("produced_qty", 0)), float(self.done_by_wo.get(wo.get("name"), 0)))

    def _linked_wos(self, so_name):
        return [w["data"] for w in self.wos if w["data"].get("sales_order") == so_name]

    def orders(self):
        today = self.now.astimezone(TZ).date()
        down_extra = {}
        for u, m in self.status.items():
            if m["data"]["state"] in ("down", "fault") and m["data"].get("down_until_s"):
                down_extra[u] = m["data"]["down_until_s"] / 60
        bins = self.stock()
        out = []
        for s in self.sos:
            d = s["data"]
            if d.get("status") in ("Completed", "Closed", "Cancelled") or d.get("per_delivered", 0) >= 100:
                continue
            item = (d.get("items") or [{}])[0]
            qty = float(item.get("qty", 0))
            due = dt.date.fromisoformat(str(d.get("delivery_date"))[:10])
            wos = self._linked_wos(d["name"])
            produced = sum(self.produced(w) for w in wos)
            planned = sum(float(w.get("qty", 0)) for w in wos)
            short = [c for c, q in F.BOMS.get(item.get("item_code", ""), ("", []))[1]
                     if c in F.SAFETY_STOCK and bins.get(c, {}).get("actual", 0) < q * qty]
            if not wos:
                risk, tone = "待排产", "warn"
                progress = 0.0
                proj = None
            else:
                remaining = max(0.0, planned - produced)
                from sim.engine import routing_for
                w0 = wos[0]
                ops = routing_for(w0.get("production_item", "SH-301"))
                bott = max(m for op, m in ops if not op.startswith("调质"))
                flow = sum(m for _, m in ops)
                mins = (remaining * bott + (flow if remaining else 0)) if remaining else 0
                mins += sum(v for u, v in down_extra.items())
                days = math.ceil(mins / SHIFT_MIN) if mins else 0
                downstream = 1 if item.get("item_code") == "WQR-105" else 0   # 装配、跑合、出厂检验
                proj = add_working_days(today, days + downstream) if days + downstream else today
                late = working_days_between(due, proj)
                progress = produced / planned if planned else 0
                if late > 0:
                    risk, tone = "预计晚 {} 天".format(late), "bad"
                elif working_days_between(proj, due) < 1:
                    risk, tone = "有风险", "warn"
                else:
                    risk, tone = "正常", "good"
            wo_txt = "；".join("{} {} 已完工 {:g}/{:g}".format(w["name"], w.get("production_item"),
                                                         self.produced(w), float(w.get("qty", 0)))
                              for w in wos) or "尚未下达工单"
            if short and not wos:
                risk = "待排产，缺 " + short[0]
            out.append({
                "name": d["name"], "customer": d.get("customer", ""), "item": item.get("item_code"),
                "qty": qty, "delivery_date": due.isoformat(), "progress": round(progress, 3),
                "risk": risk, "tone": tone, "projected": proj.isoformat() if proj else None,
                "work_orders": wo_txt, "short": short,
                "src": "office/erp/sales_order · " + d["name"],
            })
        out.sort(key=lambda o: o["delivery_date"])
        return out

    def on_time(self):
        done = []
        for s in self.sos:
            d = s["data"]
            if d.get("delivered_date") and parse_ts(d["delivered_date"] + "T12:00:00Z") >= self.month0:
                done.append(d["delivered_date"] <= str(d.get("delivery_date"))[:10])
        return (sum(done) / len(done), len(done)) if done else (None, 0)

    # ------------------------------------------------------------ 物料
    def stock(self):
        agg = defaultdict(lambda: {"actual": 0.0, "ordered": 0.0, "projected": 0.0})
        for b in self.bins:
            d = b["data"]
            a = agg[d.get("item_code")]
            a["actual"] += float(d.get("actual_qty", 0))
            a["ordered"] += float(d.get("ordered_qty", 0))
            a["projected"] += float(d.get("projected_qty", 0))
        return agg

    def materials(self):
        st = self.stock()
        need = defaultdict(float)
        for w in self.wos:
            d = w["data"]
            if d.get("status") in ("Completed", "Stopped", "Closed"):
                continue
            if d.get("name") in self.started_wos:
                continue                      # 已下料：原材料已领用
            rem = float(d.get("qty", 0)) - self.produced(d)
            for c, q in F.BOMS.get(d.get("production_item"), ("", []))[1]:
                need[c] += q * rem
        for s in self.sos:
            d = s["data"]
            if d.get("status") in ("Completed", "Closed") or self._linked_wos(d["name"]):
                continue
            for it in d.get("items", []):
                for c, q in explode(it.get("item_code"), float(it.get("qty", 0))).items():
                    need[c] += q
        transit = {}
        for p in self.pos:
            d = p["data"]
            if d.get("status") in ("Completed", "Closed", "Cancelled"):
                continue
            for it in d.get("items", []):
                left = float(it.get("qty", 0)) - float(it.get("received_qty", 0))
                if left > 0:
                    t = transit.setdefault(it["item_code"], {"qty": 0.0, "date": it.get("schedule_date")})
                    t["qty"] += left
                    t["date"] = min(t["date"] or "9999", it.get("schedule_date") or "9999")
        out = []
        for code in KEY_MATERIALS:
            name, kind, uom = F.ITEMS[code][0], F.ITEMS[code][1], F.ITEMS[code][2]
            if code not in st:
                out.append({"code": code, "name": name.split(" ")[0], "qty": None, "uom": unit_label(uom),
                            "qty_text": "—", "safety": F.SAFETY_STOCK.get(code), "need": round(need[code], 2),
                            "cover_days": None, "status": "无库存数据", "tone": "mute", "src": "office/erp/bin · " + code})
                continue
            s = st[code]
            qty = s["actual"]
            safety = F.SAFETY_STOCK.get(code)
            daily = need[code] / 5 if need[code] else 0
            cover = qty / daily if daily else None
            tr = transit.get(code)
            if safety is not None and qty < safety:
                status, tone = "低于安全库存", "bad"
            elif need[code] > qty and not tr:
                status, tone = "不够本批需求", "bad"
            elif tr:
                status, tone = "{} 到货".format(tr["date"][5:]), "info"
            elif cover is not None and cover < 5:
                status, tone = "约 {:.0f} 天".format(max(1, cover)), "warn"
            else:
                status, tone = "正常", "good"
            qty_txt = "{:g} {}".format(round(qty, 1), unit_label(uom))
            if tr:
                qty_txt += " · 在途 {:g}".format(round(tr["qty"], 1))
            out.append({"code": code, "name": name.split(" ")[0], "qty": qty, "uom": unit_label(uom),
                        "qty_text": qty_txt, "safety": safety, "need": round(need[code], 2),
                        "cover_days": round(cover, 1) if cover else None,
                        "status": status, "tone": tone, "src": "office/erp/bin · " + code})
        return out

    # ------------------------------------------------------------ 质量
    def control_chart(self, characteristic="bearing_seat_d35", n=20):
        pts = [m for m in self.meas if m["data"]["characteristic"] == characteristic][-n:]
        if not pts:
            return {"characteristic": characteristic, "title": CHARTS.get(characteristic, characteristic),
                    "points": []}
        d0 = pts[-1]["data"]
        vals = [m["data"]["value_mm"] for m in pts]
        last5 = vals[-5:]
        lo, hi = d0["lower_tol_mm"], d0["upper_tol_mm"]
        center = (lo + hi) / 2
        mean5 = sum(last5) / len(last5)
        return {"characteristic": characteristic, "title": CHARTS.get(characteristic, characteristic),
                "name": d0.get("name"), "lower": lo, "upper": hi, "center": center,
                "points": [{"serial": m["data"]["part_serial"], "value": m["data"]["value_mm"],
                            "result": m["data"]["result"], "ts": m["ts"], "id": m["id"], "seq": m.get("_seq")} for m in pts],
                "mean_last5": round(mean5, 4), "shift_um": round((mean5 - center) * 1000, 1),
                "margin_um": round((hi - max(last5)) * 1000, 1),
                "src": unit_topic("qc-01", "measurement")}

    def inspections_today(self):
        return len({m["data"]["part_serial"] for m in self.meas if parse_ts(m["ts"]) >= self.day0})

    # ------------------------------------------------------------ 车间
    def machines(self):
        out = []
        for u in MACHINES:
            m = self.status.get(u)
            d = m["data"] if m else {"state": "idle"}
            out.append({"unit": u, "code": u.upper(), "name": UNITS[u][1], "state": d["state"],
                        "work_order": d.get("work_order"), "operation": d.get("operation"),
                        "item": d.get("item"), "part_serial": d.get("part_serial"),
                        "progress": d.get("progress", 0), "qty_done": d.get("qty_done", 0),
                        "qty": d.get("qty", 0), "queue": d.get("queue", 0),
                        "tool_life_left": d.get("tool_life_left"), "reason": d.get("reason"), "locked": d.get("locked"), "run_h_pm": d.get("run_h_pm"),
                        "no_staff": d.get("no_staff"), "staff_level": d.get("staff_level"),
                        "down_until_s": d.get("down_until_s"), "down_for_s": d.get("down_for_s"), "dispatched": d.get("dispatched", []),
                        "ts": m["ts"] if m else None})
        return out

    def agv_list(self):
        return [{"unit": u, **m["data"]} for u, m in sorted(self.agvs.items())]


def overview(db, now=None, mode="teach"):
    o = Overview(db, now, mode)
    today = o.now.astimezone(TZ).date()
    oee_today = o.oee()
    fpy_week = o.fpy(o.week0)
    cost = o.cost(o.week0)
    ot, ot_n = o.on_time()
    orders = o.orders()
    wip_now, wip_y = o.wip(), o.wip(o.now - dt.timedelta(days=1))
    machines = o.machines()

    # 本周计划与实际：按本轮生产的物料（工单里出现最多的那个）
    plan = o.wo_plan()
    comp = o.completions(o.week0)
    items = sorted(set(plan) | set(comp), key=lambda i: -sum(plan.get(i, {}).values()) - sum(comp.get(i, {}).values()))
    item = items[0] if items else "SH-301"
    week_days = [(o.week0.astimezone(TZ).date() + dt.timedelta(days=i)) for i in range(5)]
    week = []
    for dday in week_days:
        p = round(plan.get(item, {}).get(dday, 0))
        a = comp.get(item, {}).get(dday, 0) if dday <= today else None
        week.append({"date": dday.isoformat(), "day": "周" + "一二三四五"[dday.weekday()], "plan": p, "actual": a})
    plan_week = sum(w["plan"] for w in week)
    plan_to_date = sum(w["plan"] for w in week if w["date"] <= today.isoformat())
    actual_week = sum(w["actual"] or 0 for w in week)

    # 瓶颈：本周负荷率最高的设备
    load = {}
    for u in MACHINES:
        d = o._state_durations(u, o.week0)
        busy = d["run"] + d["setup"] + d["down"] + d["fault"]
        if busy > 0:
            load[u] = busy
    bott = max(load, key=load.get) if load else None
    for mm in machines:
        mm["bottleneck"] = mm["unit"] == bott

    # 关键指标
    worst = min(oee_today["machines"].items(), key=lambda kv: kv[1]["oee"]) if oee_today["machines"] else None
    risky = [x for x in orders if x["tone"] in ("bad", "warn")]
    q_bott = next((m for m in machines if m["unit"] == bott), None)
    kpis = [
        {"key": "on_time", "label": "准时交付率（本月）", "value": ot, "fmt": "pct0",
         "note": "目标 95% · {} 单延期风险".format(len(risky)) if ot_n else "本月尚无交付 · {} 单延期风险".format(len(risky)),
         "tone": "bad" if risky and any(x["tone"] == "bad" for x in risky) else ("warn" if risky else "good")},
        {"key": "wip", "label": "在制品", "value": wip_now, "fmt": "int", "unit": "件",
         "note": "比昨天 {:+d}".format(wip_now - wip_y) + (
             "（{} 前排队 {} 件）".format(q_bott["code"], q_bott["queue"]) if q_bott and q_bott["queue"] else ""),
         "tone": "warn" if wip_now - wip_y > 3 else "mute"},
        {"key": "oee", "label": "设备综合效率 OEE（今日）", "value": oee_today["value"], "fmt": "pct0",
         "note": "目标 75%" + (" · {} 仅 {:.0f}%".format(worst[0].upper(), worst[1]["oee"] * 100) if worst else " · 今日尚未开机"),
         "tone": "mute" if oee_today["value"] is None else ("good" if oee_today["value"] >= TARGET["oee"] else
                                                            ("warn" if oee_today["value"] >= 0.6 else "bad"))},
        {"key": "fpy", "label": "一次合格率（本周）", "value": fpy_week["value"], "fmt": "pct1",
         "note": "目标 97% · " + ("达标" if (fpy_week["value"] or 0) >= TARGET["fpy"] else "未达标") +
                 " · {} 件".format(fpy_week["parts"]) if fpy_week["parts"] else "本周尚未检验",
         "tone": "mute" if fpy_week["value"] is None else ("good" if fpy_week["value"] >= TARGET["fpy"] else "bad")},
        {"key": "output", "label": "本周完工 {}".format(item), "value": actual_week, "fmt": "ratio",
         "total": plan_week, "note": "计划到今天 {} 件".format(plan_to_date),
         "tone": "good" if actual_week >= plan_to_date else "warn"},
        {"key": "cost", "label": "实际成本偏差（本周）", "value": cost["value"], "fmt": "pct_signed",
         "note": ("每件高 ${:.0f} · 主要是{}".format(cost["per_unit"], cost["driver"])
                  if cost.get("per_unit") and cost["value"] > 0 else
                  ("与标准成本一致" if cost["value"] is not None else "本周尚无加工")),
         "tone": "mute" if cost["value"] is None else ("good" if cost["value"] <= 0.02 else
                                                      ("warn" if cost["value"] <= 0.08 else "bad"))},
    ]
    chart = o.control_chart()
    running = sum(1 for m in machines if m["state"] == "run")
    return {
        "now": o.now.isoformat(), "local_time": o.now.astimezone(TZ).strftime("%Y-%m-%d %H:%M"),
        "weekday": "周" + "一二三四五六日"[o.now.astimezone(TZ).weekday()],
        "mode": mode, "demo": o.demo,
        "kpis": kpis,
        "machines": machines,
        "machine_counts": {s: sum(1 for m in machines if m["state"] == s) for s in ("run", "idle", "setup", "down", "fault")},
        "agvs": o.agv_list(),
        "wip": {"now": wip_now, "yesterday": wip_y, "running": running},
        "bottleneck": bott,
        "orders": orders,
        "week": {"item": item, "days": week, "plan": plan_week, "actual": actual_week, "bottleneck": bott,
                 "bottleneck_name": UNITS[bott][1] if bott else None},
        "quality": {"chart": chart, "fpy_week": fpy_week, "ncr_open": len(o.ncr_open),
                    "ncr": [{"ncr_id": n["ncr_id"], "part_serial": n["part_serial"], "detail": n["detail"],
                             "created_at": n["created_at"].isoformat()} for n in o.ncr_open],
                    "inspected_today": o.inspections_today()},
        "materials": o.materials(),
        "oee": {"value": oee_today["value"], "machines": oee_today["machines"]},
        "cost": cost,
        "on_time": {"value": ot, "delivered": ot_n},
    }
