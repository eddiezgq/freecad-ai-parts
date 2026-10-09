# -*- coding: utf-8 -*-
"""推演（第 17 轮 C 期 C1–C5）：班次日历、快照、快进副本、7 种改动、成本与校验。

- 班次日历存在 shift_calendar 表，由枢纽经总线发给仿真车间（set_calendar）。
- 快照：教学模式向仿真车间要精确快照（sim.snapshot）；生产模式从总线上各设备最近的状态消息近似重建。
- 推演：从快照恢复一个引擎（仿真车间同一套代码），换上改动，用虚拟时钟快进到相关工单做完（最多 10 个工作日），
  不发总线消息、不影响真车间；同一快照、同一改动、同一种子，结果完全相同。"""
import copy
import datetime as dt
import json
import threading
import time
import uuid

from psycopg.types.json import Jsonb

from factory import data as F
from sim.calendar import MAX_OT_MIN, Calendar
from sim.engine import OP_UNITS, Engine, routing_for

SCHEMA = """
create table if not exists shift_calendar (
    mode     text primary key,
    value    jsonb not null,
    updated_at timestamptz not null default now(),
    updated_by text
);
create table if not exists sim_snapshot (
    id      bigserial primary key,
    mode    text not null,
    ts      timestamptz not null,
    exact   boolean not null,
    state   jsonb not null
);
create index if not exists sim_snapshot_ts on sim_snapshot (mode, ts);
create table if not exists scenario (
    id          bigserial primary key,
    mode        text not null,
    title       text not null,
    snapshot_id bigint,
    changes     jsonb not null default '[]',
    seed        bigint,
    result      jsonb,
    created_by  text,
    anomaly_id  bigint,
    created_at  timestamptz not null default now()
);
"""
CHANGE_TYPES = {
    "reassign": "改派", "reorder": "调序 / 插单", "insert_order": "插单", "overtime": "加班", "expedite": "维修加急",
    "urgent_purchase": "紧急采购", "outsource": "外协", "split_delivery": "分批交货",
    "breakdown": "假设停机",            # 第 17 轮 D 期：只用于推演（AI 代理、复盘），不能变成动作
    "lockout": "停机挂牌整改",          # 第 18 轮 E2：重大隐患（可延后：先临时防护，delay_minutes 后停）
    "pm_order": "保养（停机挂牌）",     # 第 18 轮 E3：和停机挂牌一样推演，费用按保养人工算
    "staff": "排班（调人 / 学徒 / 加班顶班）",   # 第 18 轮 E4：改某天某班某台设备的人员等级（0 没人 / 1 学徒 / 2 熟练）
    "material_arrival": "到料日",                # 第 18 轮 E5：来料不合格时按方案改到料日（费用另算）
    "energy_setting": "节能设定（空闲自动待机）",  # 第 18 轮 E6：units、standby_min（0 = 取消）
    "tou_rule": "错峰（峰时不开新炉）",           # 第 18 轮 E6：units（热处理炉）、on
}
ENERGY_WINDOW_H = 24              # 第 18 轮 E6：推演里电量、电费按快照起的 24 小时比较
RECTIFY_RATE = 45.0               # 安全整改 / 保养人工（美元 / 小时）
PM_MATERIAL = 80.0                # 一次保养的油、脂、滤芯（美元）
OT_RATE = 1.5                     # 加班费倍数
WAGE_RATE = 30.0                  # 操作工工时（美元 / 小时；加班按 1.5 倍）
EXPEDITE_COST = 300.0             # 维修加急默认费用（美元，可在改动里改）
URGENT_PCT = 0.15                 # 紧急采购加急费：货值的 15%
OUTSOURCE_MARKUP = 1.3            # 外协单价：本厂工时成本 × 1.3 + 每批运费
OUTSOURCE_FREIGHT = 50.0
# 违约金按客户合同的条款算（第 18 轮 E1-3，hub/crm.py）：context() 给每张订单带上 penalty_per_day；没有合同不算
DOWNSTREAM_DAYS = {"WQR-105": 1}  # 输出轴做完后：装配、跑合、出厂检验（与看板估算一致）
HORIZON_DAYS = 10
LIMIT_S = 30.0
_slots = threading.BoundedSemaphore(2)          # 同时最多 2 个推演


class PlanError(ValueError):
    pass


def init(db):
    db.x(SCHEMA)


# ------------------------------------------------------------------ 班次日历
def default_calendar(mode):
    import os
    return Calendar("continuous" if mode == "teach" else "shift", tz=os.environ.get("WQ_TZ", "America/New_York"))


def calendar(db, mode):
    r = db.one("select value from shift_calendar where mode=%s", (mode,))
    return Calendar.from_dict(r["value"]) if r else default_calendar(mode)


def save_calendar(db, mode, cal, who):
    db.x("insert into shift_calendar (mode, value, updated_by) values (%s,%s,%s) on conflict (mode) do update set "
         "value=excluded.value, updated_at=now(), updated_by=excluded.updated_by", (mode, Jsonb(cal.to_dict()), who))


def push_calendar(mes, db, mode, who="hub"):
    """发给仿真车间（两种模式都接受）"""
    mes.command("sim", "set_calendar", mode, who, calendar=calendar(db, mode).to_dict())


# ------------------------------------------------------------------ 快照
class Snapshots:
    """向仿真车间要快照：发 snapshot 指令，等 sim.snapshot 回来（总线回调里 deliver）"""

    def __init__(self, db, mes):
        self.db, self.mes = db, mes
        self.wait = {}

    def deliver(self, msg):
        d = msg["data"]
        mode = msg.get("mode") or "teach"
        st = d["snapshot"]
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), true, %s) returning id", (mode, Jsonb(st)))
        ev = self.wait.get(d.get("request") or "")
        if ev:
            ev["id"] = r["id"]
            ev["e"].set()

    def take(self, mode, timeout=5.0):
        """拍一张：教学模式等仿真车间回精确快照，等不到或生产模式就近似重建。返回 (id, state, exact)"""
        if mode == "teach" and self.mes is not None:
            req = uuid.uuid4().hex[:12]
            ev = {"e": threading.Event()}
            self.wait[req] = ev
            try:
                self.mes.command("sim", "snapshot", mode, "hub", request=req)
                if ev["e"].wait(timeout):
                    r = self.db.one("select id, state from sim_snapshot where id=%s", (ev["id"],))
                    return r["id"], r["state"], True
            finally:
                self.wait.pop(req, None)
        st = approx_snapshot(self.db, mode)
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), false, %s) returning id", (mode, Jsonb(st)))
        return r["id"], st, False


def approx_snapshot(db, mode, now=None):
    """生产模式（没有仿真车间的内存）：从各设备最近一条状态消息重建。
    各工序完成数取派工清单；零件位置按“上一道完成数 − 本道完成数”推算；正在加工的件按进度估剩余时间。"""
    now = now or dt.datetime.now(dt.timezone.utc)
    blank = Engine(lambda *a: None, _Clock(0.0), mode=mode, auto_start=True, seed=0)
    blank.epoch = now
    blank.calendar = calendar(db, mode)
    st = blank.snapshot()
    st["approx"] = True
    status = {}
    for tp, m in db.latest_per_topic(["machine.status"], mode=mode).items():
        status[tp.split("/")[3]] = m["data"]
    items = {}
    for w in db.erp_docs("Work Order", mode):
        items[w["data"]["name"]] = w["data"].get("production_item") or "SH-301"
    # 工单 → 每道工序的（设备、完成数、数量、已开工）
    wos = {}
    for u, d in status.items():
        for j in d.get("dispatched") or []:
            w = wos.setdefault(j["work_order"], {"item": items.get(j["work_order"], d.get("item") or "SH-301"), "ops": {}})
            w["ops"][j["operation"]] = {"unit": u, "done": j["done"], "qty": j["qty"], "started": j["started"]}
    q = []
    seq = 0
    for name, w in wos.items():
        ops = routing_for(w["item"])
        qty = max(x["qty"] for x in w["ops"].values())
        done = []
        for i, (op, mins) in enumerate(ops):
            x = w["ops"].get(op)
            if x is not None:
                done.append(x["done"])
            else:                                       # 不在清单里：后面有进度就算已做完，否则没派工
                later = any(w["ops"].get(o2) for o2, _ in ops[i + 1:])
                done.append(qty if later else None)
        # 每件零件走到第几道：完成数单调不增（先做完的件先往后走）
        dn, prev = [], qty
        for x in done:
            prev = min(prev, x if x is not None else 0)
            dn.append(prev)
        parts = []
        tag = name.split("-")[-1]
        for k in range(qty):
            oi = sum(1 for v in dn if v > k)
            parts.append({"serial": "{}-{}-{:02d}".format(w["item"].replace("-", ""), tag, k + 1), "op_index": oi, "grind_wear": 0.0,
                          "result": None, "err": {}})
        jobs = {}
        for i, (op, mins) in enumerate(ops):
            x = w["ops"].get(op)
            if x is None:
                continue
            jobs[str(i)] = {"unit": x["unit"], "started": True, "done": x["done"], "good": x["done"], "time_s": 0.0,
                            "first_start": 0.0, "qty": qty, "outsource": None}
        st["wos"][name] = {"item": w["item"], "qty": qty, "ops": [list(o) for o in ops], "corr": name, "parts": parts, "jobs": jobs}
        for i, j in jobs.items():
            if j["done"] < j["qty"]:
                st["machines"][j["unit"]]["jobs"].append([name, int(i)])
        # 零件放到设备上：该工序的设备（派了工的）队列；正在加工的件按状态里的进度估剩余
        for k, p in enumerate(parts):
            if p["op_index"] >= len(ops):
                continue
            job = jobs.get(str(p["op_index"]))
            if job is None:
                continue
            mst = st["machines"][job["unit"]]
            sd = status.get(job["unit"]) or {}
            busy = mst["active"]
            if sd.get("state") == "run" and sd.get("work_order") == name and sd.get("operation") == ops[p["op_index"]][0] and not busy:
                std = ops[p["op_index"]][1] * 60
                rem = std * (1 - float(sd.get("progress") or 0))
                tok = 1000 + seq
                mst["active"].append([tok, name, p["serial"], p["op_index"], 0.0 - (std - rem), rem])
                q.append([rem, seq, "cycle_end", {"unit": job["unit"], "token": tok}])
                seq += 1
            else:
                mst["inbox"].append([name, p["serial"]])
    for u, d in status.items():
        if u not in st["machines"]:
            continue
        mst = st["machines"][u]
        mst["tool_life"] = float(d.get("tool_life_left") or 1.0)
        if d.get("state") in ("down", "fault") and d.get("down_until_s"):
            mst["state"] = d["state"]
            mst["down_until"] = float(d["down_until_s"])
            mst["down_since"] = -float(d.get("down_for_s") or 0)
            mst["down_reason"] = d.get("reason") or ""
            mst["down_kind"] = d["state"]
            q.append([mst["down_until"], seq, "recover", {"unit": u, "until": mst["down_until"]}])
            seq += 1
        elif mst["active"]:
            mst["state"] = "run"
    # 派工顺序按状态清单
    for u, d in status.items():
        if u in st["machines"]:
            order = [(j["work_order"], j["operation"]) for j in d.get("dispatched") or []]
            jl = st["machines"][u]["jobs"]
            jl.sort(key=lambda x: next((k for k, (wn, op) in enumerate(order)
                                        if wn == x[0] and op == st["wos"][x[0]]["ops"][x[1]][0]), 99))
    st["queue"] = q
    st["seq"] = seq + 1
    st["tokens"] = 5000
    return st


class _Clock:
    def __init__(self, t):
        self.t = float(t)

    def now(self):
        return self.t


# ------------------------------------------------------------------ 推演
def simulate(snap, changes=None, context=None, horizon_days=HORIZON_DAYS, limit_s=LIMIT_S):
    """snap：快照；changes：改动清单；context：{sales_orders: [{name, delivery_date, item, qty, work_orders}], releases: [...]}。
    返回结果 dict（工单、订单、设备、成本、校验、甘特图）"""
    if not _slots.acquire(timeout=limit_s):
        raise PlanError("推演排队太久，请稍后再试")
    try:
        return _simulate(snap, changes or [], context or {}, horizon_days, limit_s)
    finally:
        _slots.release()


def _simulate(snap, changes, ctx, horizon_days, limit_s):
    snap = copy.deepcopy(snap)
    events = []
    clock = _Clock(snap["t"])

    def pub(tp, ty, src, data, corr):
        if ty in ("machine.event",):
            events.append((clock.t, tp.split("/")[3], data))
    eng = Engine.from_snapshot(snap, pub, clock)
    t0 = snap["t"]
    start_dt = eng.factory_dt(t0)
    checks, costs, applied = [], [], []
    releases = [dict(r) for r in ctx.get("releases") or []]
    # ---- 改动
    cal = Calendar.from_dict(eng.calendar.to_dict())
    staff_changed = False
    ectx = ctx.get("energy")
    if ectx or any(c.get("type") in ("energy_setting", "tou_rule") for c in changes):
        if not eng.energy.enabled:                # 第 18 轮 E6：近似快照没有计量，推演里打开（不改车间节拍）
            eng.set_energy({"enabled": True})
        eng._emark_all(t0)                        # 从快照时刻起算
        eng.energy.tot = {}
        eng.at(t0 + ENERGY_WINDOW_H * 3600, "energy_capture")
    for c in changes:
        typ = c.get("type")
        if typ not in CHANGE_TYPES:
            raise PlanError("不认识的改动：{}".format(typ))
        if typ == "breakdown":
            m = eng.machines.get(str(c.get("unit") or "").lower())
            mins = float(c.get("minutes") or 0)
            if m is None or not 0 < mins <= 14 * 24 * 60:
                checks.append({"ok": False, "text": "假设停机：设备或时长不对"})
                continue
            if m.state in ("down", "fault") and m.down_until:
                m.down_until = m.down_until + mins * 60
                eng.at(m.down_until, "recover", unit=m.unit, until=m.down_until)
            else:
                eng._go_down(m, clock.now(), mins * 60, c.get("reason") or "假设停机", "down")
            applied.append(c)
            continue
        if typ in ("lockout", "pm_order"):
            m = eng.machines.get(str(c.get("unit") or "").lower())
            mins = float(c.get("minutes") or 0)
            delay = float(c.get("delay_minutes") or 0)
            if m is None or not 0 < mins <= 14 * 24 * 60:
                checks.append({"ok": False, "text": "停机挂牌：设备或时长不对"})
                continue
            permit = c.get("permit") or "推演"
            if delay > 0:
                eng.at(clock.now() + delay * 60, "lockout_due", unit=m.unit, permit=permit, minutes=mins, reason="挂牌上锁（推演）")
            else:
                eng._lock(m, clock.now(), permit, mins, "挂牌上锁（推演）")
            # 推演里整改按时做完：到时自动解锁
            eng.at(clock.now() + (delay + mins) * 60 + 1, "unlock_due", unit=m.unit)
            applied.append(c)
            if typ == "pm_order":
                costs.append({"what": "保养人工 {:.0f} 分钟、油脂滤芯".format(mins), "usd": round(mins / 60 * RECTIFY_RATE + PM_MATERIAL, 2)})
            else:
                costs.append({"what": "安全整改人工 {:.0f} 分钟".format(mins), "usd": round(mins / 60 * RECTIFY_RATE, 2)})
            if delay > 0 and c.get("temp_cost"):
                costs.append({"what": "临时防护、专人看守", "usd": float(c["temp_cost"])})
            checks.append({"ok": True, "text": "{} {}停机挂牌，{} {:.0f} 分钟".format(m.unit.upper(), "{:.0f} 分钟后".format(delay) if delay else "立即",
                                                                          "保养" if typ == "pm_order" else "整改", mins)})
            continue
        if typ == "staff":
            lv = {str(k): int(v) for k, v in (c.get("levels") or {}).items() if int(v) in (0, 1, 2)}
            if not lv:
                checks.append({"ok": False, "text": "排班：没有要改的班"})
                continue
            eng.staffing.enabled = True
            eng.staffing.levels.update(lv)
            staff_changed = True
            applied.append(c)
            if c.get("overtime_min"):
                costs.append({"what": "加班顶班 {}（{:.0f} 小时）".format(c.get("who") or "", float(c["overtime_min"]) / 60),
                              "usd": round(float(c["overtime_min"]) / 60 * WAGE_RATE * OT_RATE, 2)})
            if any(v == 1 for v in lv.values()):
                checks.append({"ok": True, "text": "学徒开机：按 60% 速度，要班组长带着"})
            continue
        if typ == "overtime":
            if cal.mode != "shift":
                checks.append({"ok": False, "text": "车间是 24 小时连续运转，加班没有意义（先在教师控制台切到按班次）"})
                continue
            try:
                cal.add_overtime(c["day"], c.get("unit") or "*", int(c["minutes"]))
            except ValueError as e:
                checks.append({"ok": False, "text": str(e)})
                continue
            applied.append(c)
        elif typ == "expedite":
            ok, why = eng.command(c["unit"], {"command": "expedite_repair", "factor": c.get("factor", 0.5)})
            checks.append({"ok": ok, "text": "维修加急 {}：{}".format(c["unit"].upper(), why)})
            if ok:
                applied.append(c)
                costs.append({"what": "维修加急 {}".format(c["unit"].upper()), "usd": float(c.get("cost", EXPEDITE_COST))})
        elif typ == "reassign":
            ok, why = eng.command(c["from_unit"], {"command": "reassign", "work_order": c["work_order"], "operation": c["operation"],
                                                   "to_unit": c["to_unit"]})
            checks.append({"ok": ok, "text": "改派：{}".format(why)})
            if ok:
                applied.append(c)
        elif typ == "reorder":
            ok, why = eng.command(c["unit"], {"command": "reorder", "work_order": c["work_order"], "operation": c.get("operation")})
            checks.append({"ok": ok, "text": "调序 {}：{}".format(c["unit"].upper(), why)})
            if ok:
                applied.append(c)
        elif typ == "outsource":
            ok, why = eng.command(c["unit"], {"command": "outsource", "work_order": c["work_order"], "operation": c["operation"],
                                              "qty": c["qty"], "days": c.get("days", 2)})
            checks.append({"ok": ok, "text": "外协：{}".format(why)})
            if ok:
                applied.append(c)
                wo = eng.wos[c["work_order"]]
                mins = next(m for o, m in wo.ops if o == c["operation"] or o.split(" ")[0] == c["operation"])
                from hub.kpi import rate_per_hour
                unit_cost = mins / 60 * rate_per_hour(c["unit"]) * OUTSOURCE_MARKUP
                costs.append({"what": "外协 {} 件（{}）".format(c["qty"], c["operation"]), "usd": round(unit_cost * int(c["qty"]) + OUTSOURCE_FREIGHT, 2)})
        elif typ == "insert_order":
            releases.append({"work_order": c["work_order"], "item": c.get("item", "SH-301"), "qty": int(c["qty"]),
                             "at": c.get("at"), "sales_order": c.get("sales_order"), "material": c.get("material")})
            applied.append(c)
        elif typ == "urgent_purchase":
            hit = [r for r in releases if c["item"] in (r.get("short") or [r.get("material")])]
            if not hit:
                checks.append({"ok": False, "text": "紧急采购 {}：没有在等这个物料的工单".format(c["item"])})
                continue
            for r in hit:
                arr = dict(r.get("arrivals") or {r.get("material"): r.get("at")})
                arr[c["item"]] = c["arrive"]
                r["arrivals"] = arr
                r["at"] = max(arr.values())
                if max(arr.values()) > c["arrive"]:
                    checks.append({"ok": True, "text": "紧急采购 {} 后，{} 仍要等 {}（{} 到货）".format(
                        c["item"], r["work_order"], "、".join(k for k, v in arr.items() if v == max(arr.values())), max(arr.values()))})
            applied.append(c)
            price = (F.ITEMS.get(c["item"]) or [None, None, None, 0])[3] or 0
            costs.append({"what": "紧急采购 {} × {}".format(c["item"], c["qty"]), "usd": round(float(price) * float(c["qty"]) * URGENT_PCT, 2)})
        elif typ == "material_arrival":
            hit = [r for r in releases if c["item"] in (r.get("short") or [r.get("material")])]
            for r in hit:
                arr = dict(r.get("arrivals") or {r.get("material"): r.get("at")})
                arr[c["item"]] = c["arrive"]
                r["arrivals"] = arr
                r["at"] = max(arr.values())
            checks.append({"ok": True, "text": "{} {} 到料{}".format(c["item"], c["arrive"], "" if hit else "（现在没有在等这种料的工单）")})
            applied.append(c)
        elif typ == "split_delivery":
            applied.append(c)                    # 不影响生产，只影响订单的判定
        elif typ == "energy_setting":
            sb = dict(eng.energy.standby)
            m = float(c.get("standby_min") or 0)
            for u in c.get("units") or []:
                if m:
                    sb[u] = m
                else:
                    sb.pop(u, None)
            eng.set_energy({"standby": sb})
            applied.append(c)
        elif typ == "tou_rule":
            tou = set(eng.energy.tou)
            tou = tou | set(c.get("units") or []) if c.get("on", True) else tou - set(c.get("units") or [])
            eng.set_energy({"tou": sorted(tou)})
            applied.append(c)
    if cal.to_dict() != eng.calendar.to_dict():
        eng.set_calendar(cal)                     # 只有加班改了日历才重设（重设会让每台设备重新判断一次开工）
    if staff_changed:
        eng.set_staffing({})                      # 人员等级改了：每台设备重新判断能不能开工
    # 待下达的工单（等料、插单）：到时刻下达
    for r in releases:
        at = r.get("at")
        when = max(start_dt, dt.datetime.fromisoformat(at) if isinstance(at, str) and "T" in at else
                   (dt.datetime.combine(dt.date.fromisoformat(at), dt.time(8, 0), tzinfo=cal.tzi).astimezone(dt.timezone.utc) if at else start_dt))
        eng.at(eng.sim_t(when), "release", work_order=r["work_order"], item=r["item"], qty=r["qty"])
    # ---- 快进
    watch = set(eng.wos) | {r["work_order"] for r in releases}
    end_t = t0 + horizon_days * 86400 * 1.4          # 10 个工作日约 14 个日历日
    wall = time.time()
    while eng.q:
        nt = eng.q[0][0]
        if nt > end_t:
            break
        clock.t = max(clock.t, nt)
        eng.run_due()
        if time.time() - wall > limit_s:
            raise PlanError("推演超过 {:.0f} 秒，方案太大".format(limit_s))
        if _all_done(eng, watch) and (not eng.energy.enabled or eng.energy_capture is not None):
            break                                 # 第 18 轮 E6：算电量时至少推到 24 小时
    r = _result(eng, events, t0, start_dt, watch, ctx, applied, checks, costs, cal, changes)
    if eng.energy.enabled:
        from sim import energy as EN
        cap = eng.energy_capture if eng.energy_capture is not None else (eng._emark_all(), eng.energy.totals())[1]
        e = ectx or {}
        r["energy"] = dict(EN.summarize({}, cap, e.get("price"), e.get("factor", 0.5306)), hours=ENERGY_WINDOW_H)
    return r


def hypothesis(snap, unit, minutes, reason="假设停机"):
    """“假如某台设备（再）停 N 分钟”（第 17 轮 D 期，AI 代理和复盘用）：返回一张改过的快照。
    设备正在停机就把恢复时刻往后推，否则从快照时刻起停机。只用于推演，不能变成动作。"""
    if unit not in (snap.get("machines") or {}):
        raise PlanError("没有这台设备：{}".format(unit))
    minutes = float(minutes)
    if not 0 < minutes <= 14 * 24 * 60:
        raise PlanError("假设停机时长应在 0–14 天之间")
    clock = _Clock(snap["t"])
    eng = Engine.from_snapshot(copy.deepcopy(snap), lambda *a: None, clock)
    m = eng.machines[unit]
    t = clock.now()
    if m.state in ("down", "fault") and m.down_until:
        m.down_until = m.down_until + minutes * 60
        eng.at(m.down_until, "recover", unit=unit, until=m.down_until)
    else:
        eng._go_down(m, t, minutes * 60, reason, "down")
    st = eng.snapshot()
    st["hypothesis"] = {"unit": unit, "minutes": minutes}
    if snap.get("approx"):
        st["approx"] = True
    return st


def _all_done(eng, watch):
    for n in watch:
        w = eng.wos.get(n)
        if w is None or any(p.op_index < len(w.ops) for p in w.parts):
            return False
    return True


def _result(eng, events, t0, start_dt, watch, ctx, applied, checks, costs, cal, changes):
    from hub import kpi
    tz = cal.tzi
    finish = {}                                   # 工单 → [各件完成时刻]
    gantt, open_seg, downs = [], {}, []
    for t, unit, d in events:
        ev = d.get("event")
        if ev == "cycle_start":
            open_seg[(unit, d["part_serial"], d["op_index"])] = t
        elif ev == "cycle_end":
            s = open_seg.pop((unit, d["part_serial"], d["op_index"]), None)
            if s is not None:
                gantt.append({"unit": unit, "wo": d["work_order"], "op": d["operation"].split(" ")[0], "part": d["part_serial"],
                              "start": eng.factory_dt(s).isoformat(), "end": eng.factory_dt(t).isoformat()})
            if d.get("op_index") == d.get("n_ops", 0) - 1:
                finish.setdefault(d["work_order"], []).append(t)
        elif ev in ("alarm", "fault"):
            downs.append({"unit": unit, "start": eng.factory_dt(t).isoformat(), "reason": d.get("message"),
                          "end": eng.factory_dt(t + (d.get("expected_duration_s") or 0)).isoformat()})
    for t, wo, serial in eng.outsourced_done:
        finish.setdefault(wo, []).append(t)
    wos = {}
    for n in sorted(watch):
        w = eng.wos.get(n)
        qty = w.qty if w else None
        done_before = sum(1 for p in (w.parts if w else []) if p.op_index >= len(w.ops)) - len(finish.get(n, []))
        fin = sorted(finish.get(n, []))
        complete = w is not None and all(p.op_index >= len(w.ops) for p in w.parts)
        wos[n] = {"item": w.item if w else None, "qty": qty, "finished": len(fin) + max(0, done_before), "complete": complete,
                  # 快照时已经做完的工单：完工时刻按快照时刻算（推演里没有它的事件）
                  "finish": (eng.factory_dt(fin[-1]) if fin else start_dt).isoformat() if complete else None,
                  "done_before": complete and not fin,
                  "part_finish": [eng.factory_dt(x).isoformat() for x in fin]}
    # 订单
    sos = []
    split = {c["sales_order"]: c for c in changes if c.get("type") == "split_delivery"}
    for so in ctx.get("sales_orders") or []:
        ws = [wos[w] for w in so.get("work_orders") or [] if w in wos]
        if not ws:
            sos.append(dict(so, projected=None, late_days=None, note="没有在车间里的工单"))
            continue
        if not all(x["complete"] for x in ws):
            sos.append(dict(so, projected=None, late_days=None, note="推演范围内（{} 个工作日）做不完".format(HORIZON_DAYS)))
            continue
        fin = max(dt.datetime.fromisoformat(x["finish"]) for x in ws).astimezone(tz).date()
        proj = kpi.add_working_days(fin, DOWNSTREAM_DAYS.get(so.get("item"), 0))
        due = dt.date.fromisoformat(str(so["delivery_date"])[:10])
        late = kpi.working_days_between(due, proj) if proj > due else -kpi.working_days_between(proj, due)
        row = dict(so, projected=proj.isoformat(), late_days=late)
        sp = split.get(so["name"])
        if sp:
            parts = sorted(dt.datetime.fromisoformat(x) for w in ws for x in w["part_finish"])
            k = int(sp["first_qty"])
            if 0 < k <= len(parts):
                p1 = kpi.add_working_days(parts[k - 1].astimezone(tz).date(), DOWNSTREAM_DAYS.get(so.get("item"), 0))
                d1 = dt.date.fromisoformat(sp["first_date"])
                row["split"] = {"first_qty": k, "first_date": d1.isoformat(), "first_projected": p1.isoformat(),
                                "first_late_days": kpi.working_days_between(d1, p1) if p1 > d1 else 0}
                row["late_days"] = max(row["split"]["first_late_days"], kpi.working_days_between(due, proj) if proj > due else 0)
        pen = so.get("penalty_per_day")
        if pen and row["late_days"] and row["late_days"] > 0:
            costs.append({"what": "{} 违约金（晚 {} 天）".format(so["name"], row["late_days"]), "usd": pen * row["late_days"]})
        sos.append(row)
    # 加班费
    from hub.kpi import rate_per_hour
    busy_units = {g["unit"] for g in gantt}
    for (day, unit), mins in cal.overtime.items():
        if not any(c.get("type") == "overtime" and str(c["day"])[:10] == day for c in applied):
            continue
        units = [unit] if unit != "*" else sorted(u for u in busy_units if u in OP_UNITS_ALL)
        for u in units:
            costs.append({"what": "加班 {} {} {} 分钟".format(day, u.upper(), mins), "usd": round(mins / 60 * rate_per_hour(u) * OT_RATE, 2)})
    ot_items = [((day, u), m) for (day, u), m in cal.overtime.items() if any(c.get("type") == "overtime" and str(c["day"])[:10] == day for c in applied)]
    ot_min = sum(m for _, m in ot_items)                                 # 加班多长（分钟）
    ot_units = max([1 if u != "*" else max(1, len([x for x in busy_units if x in OP_UNITS_ALL])) for (d, u), m in ot_items] or [0])
    load = {}
    for g in gantt:
        s, e = dt.datetime.fromisoformat(g["start"]), dt.datetime.fromisoformat(g["end"])
        load[g["unit"]] = load.get(g["unit"], 0) + (e - s).total_seconds() / 3600
    return {"start": start_dt.isoformat(), "calendar": cal.to_dict(), "work_orders": wos, "sales_orders": sos,
            "machines": {u: {"busy_h": round(h, 2)} for u, h in sorted(load.items())}, "downtime": downs,
            "costs": costs, "cost_total": round(sum(c["usd"] for c in costs), 2), "overtime_min": ot_min, "overtime_units": ot_units,
            "checks": checks, "ok": all(c["ok"] for c in checks), "applied": applied,
            "gantt": gantt[:4000], "end": eng.factory_dt(eng.now()).isoformat()}


OP_UNITS_ALL = {u for us in OP_UNITS.values() for u in us}


# ------------------------------------------------------------------ 推演的上下文（订单、待下达的工单）
def context(db, mode, now=None):
    """销售订单（交期、工单）；还没下达工单、在等料的订单作为“待下达的工单”（到料日下达，一台减速器一根输出轴）"""
    from hub import kpi
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(kpi.TZ).date()
    sos, releases = [], []
    wos = {w["data"]["name"]: w["data"] for w in db.erp_docs("Work Order", mode)}
    bins = {}
    for b in db.erp_docs("Bin", mode):
        bins[b["data"].get("item_code")] = bins.get(b["data"].get("item_code"), 0) + float(b["data"].get("actual_qty") or 0)
    pos = {}
    for p in db.erp_docs("Purchase Order", mode):
        if p["data"].get("status") in ("Completed", "Closed", "Cancelled"):
            continue
        for i in p["data"].get("items") or []:
            if i.get("schedule_date") and float(i.get("received_qty") or 0) < float(i.get("qty") or 0):
                d = str(i["schedule_date"])[:10]
                pos[i["item_code"]] = min(pos.get(i["item_code"], d), d)
    for s_ in db.erp_docs("Sales Order", mode):
        d = s_["data"]
        if d.get("status") in ("Completed", "Closed", "Cancelled") or (d.get("per_delivered") or 0) >= 100:
            continue
        item = (d.get("items") or [{}])[0]
        code, qty = item.get("item_code"), float(item.get("qty") or 0)
        linked = [n for n, w in wos.items() if (w.get("sales_order") == d["name"] or w.get("wq_sales_order") == d["name"])
                  and w.get("status") not in ("Cancelled",)]
        row = {"name": d["name"], "customer": d.get("customer"), "delivery_date": str(d.get("delivery_date"))[:10],
               "item": code, "qty": qty, "work_orders": linked}
        if not linked and code in F.BOMS:
            need = kpi.explode(code, qty)
            short = [c for c, q in need.items() if c in F.SAFETY_STOCK and bins.get(c, 0) < q]
            if short:                         # 在等料：到料日下达（推演里当作计划员会在到料后马上下达）
                arrivals = {}
                for c in short:
                    sup = F.SUPPLIERS.get((F.ITEMS.get(c) or [None] * 5)[4], {})
                    arrivals[c] = pos.get(c) or kpi.add_working_days(today, int(sup.get("lead", 7))).isoformat()
                arrive = max([today] + [dt.date.fromisoformat(a) for a in arrivals.values()])
                name = "待下达·{}".format(d["name"])
                releases.append({"work_order": name, "item": "SH-301", "qty": int(qty), "at": arrive.isoformat(),
                                 "sales_order": d["name"], "material": short[0], "short": short, "arrivals": arrivals})
                row["work_orders"] = [name]
                row["pending"] = {"short": short, "release_at": arrive.isoformat(), "arrivals": arrivals}
            else:
                row["pending"] = {"short": [], "release_at": None, "note": "待排产（不缺料，计划员还没下达）"}
        sos.append(row)
    from hub import crm
    pens = crm.penalty_map(db, mode, sos, today)
    for row in sos:
        if row["name"] in pens:
            row["penalty_per_day"] = pens[row["name"]]
    return {"sales_orders": sos, "releases": releases}
