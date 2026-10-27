# -*- coding: utf-8 -*-
"""设备维护与资产（第 18 轮 E3）：台账与保养计划（ERPNext 资产维护模块为准）、点检（扫码）、失效率与风险、
保养与维修（自动挂牌上锁，沿用 E2）、备件、教学模拟器。

- 资产（Asset）、维护计划（Asset Maintenance）、保养记录（Asset Maintenance Log）、维修（Asset Repair）经桥接写进 ERPNext（E3-1）；
  台账第一次用到时整批建（提议 maint_setup，自动确认）。
- 失效率模型和仿真车间是同一套参数（sim/reliability.py）；“自上次保养以来的运行小时”来自车间状态（machine.status.run_h_pm）。
- 保养、维修都开挂牌上锁许可（E3-4，hub/ehs.py）：做完由另一个人验收解锁。"""
import datetime as dt
import logging
import random

from psycopg.types.json import Jsonb

from sim import reliability as REL
from wqbus import UNITS

log = logging.getLogger("maint")

SCHEMA = """
create table if not exists maint_checklist (
    mode  text not null,
    unit  text not null,
    items jsonb not null,
    primary key (mode, unit)
);
create table if not exists maint_inspection (
    id         bigserial primary key,
    mode       text not null,
    unit       text not null,
    by_name    text,
    at         timestamptz not null default now(),
    results    jsonb not null,
    abnormal   jsonb not null default '[]',
    photo_ids  jsonb not null default '[]',
    repair_id  bigint,
    status     text not null default 'ok',          -- ok 正常 / open 异常待处理 / handled 已开维修单 / watch 观察
    note       text
);
create table if not exists maint_failure (
    id        bigserial primary key,
    mode      text not null,
    unit      text not null,
    seq       bigint,
    code      text,
    name      text,
    part      text,
    at        timestamptz not null default now(),
    run_h     numeric,
    down_min  numeric,
    repair_id bigint
);
create table if not exists maint_repair (
    id          bigserial primary key,
    mode        text not null,
    unit        text not null,
    source      text not null,                       -- failure 故障 / inspection 点检 / manual
    title       text not null,
    parts       jsonb not null default '[]',
    status      text not null default 'open',         -- open / doing / waiting_parts / fixed / closed
    permit_id   bigint,
    proposal_id text,
    erp_repair  text,
    fixed_by    text,
    verified_by text,
    created_at  timestamptz not null default now(),
    started_at  timestamptz,
    fixed_at    timestamptz,
    closed_at   timestamptz,
    cost        jsonb,
    action_id   bigint
);
create table if not exists maint_pm (
    id          bigserial primary key,
    mode        text not null,
    unit        text not null,
    status      text not null default 'planned',      -- planned / doing / fixed / closed
    minutes     integer not null,
    delay_minutes integer not null default 0,
    permit_id   bigint,
    action_id   bigint,
    run_h       numeric,
    fixed_by    text,
    verified_by text,
    created_at  timestamptz not null default now(),
    fixed_at    timestamptz,
    closed_at   timestamptz,
    proposal_id text
);
create table if not exists maint_sim (
    mode  text primary key,
    state jsonb not null default '{}'
);
"""

# 资产：名称、原值 $、购置年份
ASSETS = {"saw-01": 18000, "cnc-l01-a": 62000, "cnc-l01-b": 68000, "ht-01": 95000, "key-01": 26000, "grd-01": 120000, "hob-01": 88000,
          "vmc-01": 110000, "hmc-01": 160000, "press-01": 22000, "asm-01": 15000, "test-01": 48000, "qc-01": 36000}
BOUGHT = {"saw-01": 2019, "cnc-l01-a": 2020, "cnc-l01-b": 2022, "ht-01": 2018, "key-01": 2021, "grd-01": 2017, "hob-01": 2019,
          "vmc-01": 2023, "hmc-01": 2024, "press-01": 2021, "asm-01": 2020, "test-01": 2022, "qc-01": 2021}
PM_TEXT = {"grd-01": "换液压油、查主轴轴承、校砂轮平衡", "cnc-l01-a": "换主轴润滑脂、查刀塔定位、清冷却箱", "cnc-l01-b": "换主轴润滑脂、查冷却泵、清冷却箱",
           "ht-01": "校热电偶、查循环风机轴承、清炉膛", "key-01": "换主轴润滑脂、调进给丝杠间隙", "hob-01": "换润滑油、调滚刀主轴间隙",
           "saw-01": "换液压油、查锯条张紧", "vmc-01": "换主轴润滑脂、查导轨", "hmc-01": "换主轴润滑脂、查交换台",
           "press-01": "换液压油、查密封", "asm-01": "校电动扳手扭矩", "test-01": "校扭矩传感器", "qc-01": "校测头"}
PM_MIN = {"grd-01": 180, "ht-01": 240, "hob-01": 150}           # 保养要停多久（分钟），其余 120
CHECK = {"*": ["设备外观、防护罩完好", "急停按钮有效", "润滑油位在刻度内", "没有异响、异常振动", "没有漏油、漏液"],
         "grd-01": ["砂轮无裂纹、防护罩紧固", "液压油位、油温正常"], "ht-01": ["炉温仪表正常", "淬火油位、油温正常"],
         "hob-01": ["滚刀刃口完好"], "cnc-l01-a": ["卡盘夹紧可靠"], "cnc-l01-b": ["卡盘夹紧可靠"], "saw-01": ["锯条张紧适当"]}
SPARE_MIN = {"BRG-6205": 4, "BRG-6206": 4, "BRG-6207": 4}       # 维修备件的最低库存（与生产用料共用一个库存）
LABOR_RATE = 45.0                                                # 维修 / 保养人工 $/小时
HORIZON_H = 80.0                                                 # “未来两周”按单班约 80 运行小时
REPAIR_USD = {"grd-01": 1200, "cnc-l01-a": 700, "cnc-l01-b": 700, "hob-01": 900, "ht-01": 800, "key-01": 500}   # 一次故障的修理费（人工、件、外协），其余 400
LOST_PER_H = {"grd-01": 200, "hob-01": 120}                     # 停机每小时少挣的毛利（瓶颈设备高），其余 60
PM_MATERIAL = 80.0                                               # 一次保养的油、脂、滤芯
PART_PRICE = {"BRG-6205": 5.2, "BRG-6206": 6.5, "BRG-6207": 8.0}
STATUS = {"open": "待处理", "doing": "维修中", "waiting_parts": "等备件", "fixed": "待验收", "closed": "已关闭"}
PM_STATUS = {"planned": "已排定", "doing": "保养中", "fixed": "待验收", "closed": "已完成"}


def init(db):
    if getattr(db, "_maint_ready", False):
        return
    db.x(SCHEMA)
    try:
        db._maint_ready = True
    except AttributeError:
        pass


def units():
    return [u for u in REL.PARAMS if u in UNITS]


def pm_minutes(unit):
    return PM_MIN.get(unit, 120)


def seed(db, mode):
    init(db)
    for u in units():
        items = CHECK["*"] + CHECK.get(u, [])
        db.x("insert into maint_checklist (mode, unit, items) values (%s,%s,%s) on conflict do nothing", (mode, u, Jsonb(items)))


def reset(db, mode):
    """教学情景重置：点检、故障、维修、保养单清空；ERPNext 里的台账留着（只记住建过，不重复建）"""
    init(db)
    keep = {k: v for k, v in _state(db, mode).items() if k in ("setup_pid", "setup_at")}
    for t in ("maint_inspection", "maint_failure", "maint_repair", "maint_pm", "maint_sim", "maint_checklist"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    _save_state(db, mode, dict(keep, factor=0, seq=_last_seq(db, mode)))          # 车间重载情景：可靠性关闭；之前的故障事件不再开单
    seed(db, mode)


def _last_seq(db, mode):
    try:
        r = db.one("select max(seq) as s from bus_message where mode=%s", (mode,))
        return int((r or {}).get("s") or 0)
    except Exception:  # noqa: BLE001
        return 0


def _state(db, mode):
    init(db)
    r = db.one("select state from maint_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _save_state(db, mode, st):
    db.x("insert into maint_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


def factor(db, mode):
    """车间可靠性系数：教学模式默认 1（会坏），情景重载后 0（关），老师可调；生产模式 0（真设备自己会坏，不模拟）。
    算风险时 0 按 1 算，表示“打开后会怎样”"""
    return float(_state(db, mode).get("factor", 1 if mode == "teach" else 0))


# ---------------------------------------------------------------- 台账与状态
def machine_rows(db, mode):
    from hub import kpi
    try:
        return {m["unit"]: m for m in kpi.overview(db, None, mode)["machines"]}
    except Exception:  # noqa: BLE001
        return {}


def run_hours(db, mode, unit, machines=None):
    m = (machines if machines is not None else machine_rows(db, mode)).get(unit) or {}
    if m.get("run_h_pm") is not None:
        return float(m["run_h_pm"])
    r = db.one("select payload->'data'->>'run_h_pm' as h from bus_message where type='machine.status' and mode=%s and topic like %s "
               "and payload->'data' ? 'run_h_pm' order by ts desc limit 1", (mode, "%/" + unit + "/status"))
    if r and r["h"] is not None:
        return float(r["h"])
    return float(REL.params(unit)["init_h"])


def risk(db, mode, unit, horizon_h=HORIZON_H, run_h=None, f=None):
    """未来 horizon_h 运行小时坏掉的概率、预期停机、预期损失"""
    rp = REL.params(unit)
    if rp is None:
        raise KeyError(unit)
    h = run_hours(db, mode, unit) if run_h is None else float(run_h)
    f = f if f is not None else (factor(db, mode) or 1.0)
    pm_h = interval_of(db, mode, unit)
    p = REL.cond_fail(h * f, horizon_h * f, rp["beta"], rp["eta_h"])
    p_after = REL.cond_fail(0.0, horizon_h * f, rp["beta"], rp["eta_h"])
    repair_usd = float(REPAIR_USD.get(unit, 400))
    lost_usd = rp["mttr_min"] / 60 * float(LOST_PER_H.get(unit, 60))
    return {"unit": unit, "run_h": round(h, 1), "pm_h": pm_h, "overdue_h": round(max(0.0, h - pm_h), 1),
            "due_in_h": round(pm_h - h, 1), "horizon_h": horizon_h, "factor": f,
            "p_fail": round(p, 4), "p_after_pm": round(p_after, 4), "mttr_min": rp["mttr_min"],
            "expected_down_min": round(p * rp["mttr_min"], 1), "repair_usd": round(repair_usd, 2), "lost_usd": round(lost_usd, 2),
            "expected_loss_usd": round(p * (repair_usd + lost_usd), 2), "beta": rp["beta"], "eta_h": rp["eta_h"],
            "pm_usd": round(pm_minutes(unit) / 60 * LABOR_RATE + PM_MATERIAL, 2),
            "curve": [{"h": x, "F": round(REL.cdf(x * f, rp["beta"], rp["eta_h"]), 4)} for x in range(0, int(pm_h * 2) + 1, max(10, int(pm_h / 10)))]}


def asset_of(db, mode, unit):
    """ERPNext 里这台设备的资产号、维护计划（按资产名称前缀找）"""
    a = next((m["data"] for m in db.erp_docs("Asset", mode) if str(m["data"].get("asset_name") or "").startswith(unit.upper() + " ")), None)
    if not a:
        return None, None
    mt = next((m["data"] for m in db.erp_docs("Asset Maintenance", mode) if m["data"].get("asset_name") == a["name"]), None)
    return a, mt


def assets(db, mode):
    seed(db, mode)
    ms = machine_rows(db, mode)
    out = []
    for u in units():
        rk = risk(db, mode, u, run_h=run_hours(db, mode, u, ms))
        a, mt = asset_of(db, mode, u)
        last = db.one("select max(fixed_at) as t from maint_pm where mode=%s and unit=%s and status in ('fixed','closed')", (mode, u))
        fails = db.one("select count(*) as n from maint_failure where mode=%s and unit=%s and at > now() - interval '30 days'", (mode, u))["n"]
        m = ms.get(u) or {}
        out.append({"unit": u, "name": UNITS[u][1], "asset": a["name"] if a else None, "maintenance": mt["name"] if mt else None,
                    "value": ASSETS.get(u), "bought": BOUGHT.get(u), "state": m.get("state"), "locked": m.get("locked"),
                    "pm_text": PM_TEXT.get(u), "pm_minutes": pm_minutes(u), "last_pm": last["t"].isoformat() if last and last["t"] else None,
                    "failures_30d": fails, **{k: rk[k] for k in ("run_h", "pm_h", "overdue_h", "due_in_h", "p_fail", "expected_loss_usd", "mttr_min")}})
    return out


def mtbf(db, mode, unit=None, days=30, before=None):
    """平均故障间隔（运行小时近似：天数 × 16 小时 ÷ 故障次数）"""
    init(db)
    w, a = ["mode=%s", "at > now() - make_interval(days => %s)"], [mode, days + (before or 0)]
    if before:
        w.append("at <= now() - make_interval(days => %s)")
        a.append(before)
    if unit:
        w.append("unit=%s")
        a.append(unit)
    n = db.one("select count(*) as n from maint_failure where {}".format(" and ".join(w)), a)["n"]
    return round(days * 16 / n, 1) if n else None


# ---------------------------------------------------------------- 点检
def checklist(db, mode, unit):
    seed(db, mode)
    r = db.one("select items from maint_checklist where mode=%s and unit=%s", (mode, unit))
    if r is None:
        raise KeyError(unit)
    return r["items"]


def inspect(db, mode, unit, results, who, photo_ids=None, note=""):
    """results：[{item, ok, note}]；有不合格项就记成“异常待处理”"""
    items = checklist(db, mode, unit)
    got = {x["item"]: x for x in results or []}
    rows = [{"item": i, "ok": bool(got.get(i, {}).get("ok", True)), "note": got.get(i, {}).get("note") or ""} for i in items]
    bad = [x for x in rows if not x["ok"]]
    r = db.one("insert into maint_inspection (mode, unit, by_name, results, abnormal, photo_ids, status, note) values (%s,%s,%s,%s,%s,%s,%s,%s) "
               "returning id", (mode, unit, who, Jsonb(rows), Jsonb(bad), Jsonb(photo_ids or []), "open" if bad else "ok", note[:300] or None))
    return {"id": r["id"], "key": "IC-{:05d}".format(r["id"]), "abnormal": bad}


def inspection_watch(db, iid, who):
    db.x("update maint_inspection set status='watch', note=coalesce(note,'') || %s where id=%s and status='open'", ("；{} 决定先观察".format(who), iid))


# ---------------------------------------------------------------- 维修
def stock_of(db, mode, item):
    return sum(float(b["data"].get("actual_qty") or 0) for b in db.erp_docs("Bin", mode) if b["data"].get("item_code") == item)


def open_repair(H, mode, unit, source, title, parts=None, who="系统", failure_id=None, inspection_id=None):
    """开维修单：挂牌上锁（设备停着就锁住，不自动恢复）、ERPNext Asset Repair"""
    from hub import ehs as EH
    db = H.db
    init(db)
    rp = REL.params(unit)
    r = db.one("insert into maint_repair (mode, unit, source, title, parts, status) values (%s,%s,%s,%s,%s,'doing') returning id",
               (mode, unit, source, title[:200], Jsonb(parts or [])))
    rid = r["id"]
    if failure_id:
        db.x("update maint_failure set repair_id=%s where id=%s", (rid, failure_id))
    if inspection_id:
        db.x("update maint_inspection set repair_id=%s, status='handled' where id=%s", (rid, inspection_id))
    techs = [p for p in EH.qualified_people(db, mode, "loto") if p["post"] == "维修工"]
    try:                                                 # 第 18 轮 E4：优先这一班在岗的持证维修工
        from hub import people as PE
        on = PE.on_shift_ids(db, mode)
        techs = [p for p in techs if p["id"] in on] + [p for p in techs if p["id"] not in on]
    except Exception:  # noqa: BLE001
        pass
    holder = techs[0]["id"] if techs else None
    if holder:
        pr = EH.request_permit(db, mode, {"kind": "loto", "unit": unit, "holder_id": holder, "minutes": rp["mttr_min"] if rp else 120,
                                          "reason": "维修 MR-{:05d}：{}".format(rid, title)}, who)
        EH.approve_permit(H, mode, pr["id"], who)
        db.x("update maint_repair set permit_id=%s, started_at=now() where id=%s", (pr["id"], rid))
    a, _ = asset_of(db, mode, unit)
    if a and H.ai is not None:
        pid = H.ai.propose("asset_repair", {"asset": a["name"], "failure_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                            "description": "MR-{:05d} {}".format(rid, title)}, mode, who, "维修单 {} {}".format(unit.upper(), title)[:120],
                           source="maint")
        H.ai.decide(pid, who, True)
        db.x("update maint_repair set proposal_id=%s where id=%s", (pid, rid))
    short = [p for p in parts or [] if stock_of(db, mode, p["item_code"]) < p["qty"]]
    if short:
        db.x("update maint_repair set status='waiting_parts' where id=%s", (rid,))
    return rid


def _erp_name(db, proposal_id, doctype):
    if not proposal_id:
        return None
    import json
    p = db.one("select result from ai_proposal where proposal_id=%s", (proposal_id,))
    res = (p or {}).get("result") or {}
    if isinstance(res, str):
        res = json.loads(res)
    return next((c[1] for c in res.get("created", []) if c[0] == doctype), None)


def finish_repair(H, mode, rid, who, note=""):
    """维修做完：用件出库、ERPNext 维修单改为完成，待另一人验收解锁"""
    db = H.db
    r = db.one("select * from maint_repair where id=%s and mode=%s", (rid, mode))
    if r is None:
        raise KeyError(rid)
    if r["status"] in ("fixed", "closed"):
        raise ValueError("这张维修单已经{}".format(STATUS[r["status"]]))
    for p in r["parts"] or []:
        if stock_of(db, mode, p["item_code"]) < p["qty"]:
            db.x("update maint_repair set status='waiting_parts' where id=%s", (rid,))
            raise ValueError("备件 {} 不够（要 {}），先采购".format(p["item_code"], p["qty"]))
    rp = REL.params(r["unit"]) or {"mttr_min": 120}
    parts_usd = sum(PART_PRICE.get(p["item_code"], 0) * p["qty"] for p in r["parts"] or [])
    cost = {"labor": round(rp["mttr_min"] / 60 * LABOR_RATE, 2), "parts": round(parts_usd, 2)}
    db.x("update maint_repair set status='fixed', fixed_by=%s, fixed_at=now(), cost=%s where id=%s", (who, Jsonb(cost), rid))
    if H.ai is not None:
        if r["parts"]:
            from hub import service as SV
            SV.ship_spares(H, mode, [{"item_code": p["item_code"], "qty": p["qty"]} for p in r["parts"]], who, "维修 MR-{:05d} 用件".format(rid))
        ar = r["erp_repair"] or _erp_name(db, r["proposal_id"], "Asset Repair")
        if ar:
            db.x("update maint_repair set erp_repair=%s where id=%s", (ar, rid))
            pid = H.ai.propose("asset_repair_done", {"repair": ar, "actions": note or r["title"],
                                                     "completion_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                               mode, who, "维修完成 " + ar, source="maint")
            H.ai.decide(pid, who, True)
    return {"id": rid, "status": "fixed"}


def verify_repair(H, mode, rid, who):
    from hub import ehs as EH
    db = H.db
    r = db.one("select * from maint_repair where id=%s and mode=%s", (rid, mode))
    if r is None:
        raise KeyError(rid)
    if r["status"] != "fixed":
        raise ValueError("先完成维修，再验收")
    if r["fixed_by"] and r["fixed_by"] == who:
        raise PermissionError("维修人不能验收自己的维修")
    if r["permit_id"]:                                     # 先解锁（解锁人不对会被拦下，单子不关）
        p = db.one("select status from work_permit where id=%s", (r["permit_id"],))
        if p and p["status"] == "active":
            EH.close_permit(H, mode, r["permit_id"], who)
    db.x("update maint_repair set status='closed', verified_by=%s, closed_at=now() where id=%s", (who, rid))
    return {"id": rid, "status": "closed"}


# ---------------------------------------------------------------- 保养
def exec_pm(H, mode, p, u):
    """保养工单（动作执行器）：开挂牌上锁许可（可延后），排进保养表"""
    from hub import ehs as EH
    db = H.db
    init(db)
    unit = p["unit"]
    mins = int(p.get("minutes") or pm_minutes(unit))
    delay = int(p.get("delay_minutes") or 0)
    r = EH.exec_lockout(H, mode, {"unit": unit, "minutes": mins, "delay_minutes": delay, "reason": "保养：" + (PM_TEXT.get(unit) or "")}, u)
    pm = db.one("insert into maint_pm (mode, unit, status, minutes, delay_minutes, permit_id, run_h, action_id) values (%s,%s,'doing',%s,%s,%s,%s,%s) "
                "returning id", (mode, unit, mins, delay, r["permit_id"], run_hours(db, mode, unit), p.get("_action_id")))
    return {"text": "保养工单 PM-{:05d}：{}（{}）".format(pm["id"], r["text"], PM_TEXT.get(unit) or ""), "pm_id": pm["id"], "permit": r["permit"]}


def finish_pm(H, mode, pid, who, note=""):
    """保养做完：车间运行小时清零、ERPNext 保养记录，待另一人验收解锁"""
    db = H.db
    r = db.one("select * from maint_pm where id=%s and mode=%s", (pid, mode))
    if r is None:
        raise KeyError(pid)
    if r["status"] in ("fixed", "closed"):
        raise ValueError("这张保养单已经{}".format(PM_STATUS[r["status"]]))
    db.x("update maint_pm set status='fixed', fixed_by=%s, fixed_at=now() where id=%s", (who, pid))
    mes = getattr(H, "mes", None)
    if mes is not None:
        mes.command(r["unit"], "pm_done", mode, who)
    a, mt = asset_of(db, mode, r["unit"])
    if mt and H.ai is not None:
        task = (mt.get("asset_maintenance_tasks") or [{}])[0]
        pr = H.ai.propose("maint_log", {"asset_maintenance": mt["name"], "task": task.get("name"), "task_name": task.get("maintenance_task"),
                                        "periodicity": task.get("periodicity") or "Monthly", "description": task.get("description") or PM_TEXT.get(r["unit"]),
                                        "actions": note or PM_TEXT.get(r["unit"]), "date": dt.date.today().isoformat()},
                          mode, who, "保养记录 " + r["unit"].upper(), source="maint")
        H.ai.decide(pr, who, True)
        db.x("update maint_pm set proposal_id=%s where id=%s", (pr, pid))
    return {"id": pid, "status": "fixed"}


def verify_pm(H, mode, pid, who):
    from hub import ehs as EH
    db = H.db
    r = db.one("select * from maint_pm where id=%s and mode=%s", (pid, mode))
    if r is None:
        raise KeyError(pid)
    if r["status"] != "fixed":
        raise ValueError("先做完保养，再验收")
    if r["fixed_by"] and r["fixed_by"] == who:
        raise PermissionError("保养人不能验收自己的保养")
    if r["permit_id"]:                                     # 先解锁（解锁人不对会被拦下，单子不关）
        p = db.one("select status from work_permit where id=%s", (r["permit_id"],))
        if p and p["status"] == "active":
            EH.close_permit(H, mode, r["permit_id"], who)
    db.x("update maint_pm set status='closed', verified_by=%s, closed_at=now() where id=%s", (who, pid))
    return {"id": pid, "status": "closed"}


def exec_repair(H, mode, p, u):
    rid = open_repair(H, mode, p["unit"], p.get("source") or "manual", p.get("title") or "维修", p.get("parts") or [], u.get("name"),
                      inspection_id=p.get("inspection_id"))
    return {"text": "维修单 MR-{:05d}：{} 挂牌上锁，ERPNext 开维修单".format(rid, p["unit"].upper()), "repair_id": rid}


def exec_interval(H, mode, p, u):
    """调整保养周期：写进 ERPNext 维护任务的自定义字段（运行小时），平台按它算到期"""
    db = H.db
    unit, h = p["unit"], float(p["interval_h"])
    if not 50 <= h <= 5000:
        raise ValueError("保养周期应在 50–5000 运行小时之间")
    st = _state(db, mode)
    st.setdefault("interval", {})[unit] = h
    _save_state(db, mode, st)
    _, mt = asset_of(db, mode, unit)
    if mt and H.ai is not None:
        pr = H.ai.propose("maint_interval", {"asset_maintenance": mt["name"], "interval_h": h}, mode, u.get("name"),
                          "保养周期 {} → {:g} 小时".format(unit.upper(), h), source="maint")
        H.ai.decide(pr, u.get("name"), True)
        return {"text": "保养周期 {} 改为 {:g} 运行小时（ERPNext 提议 {}）".format(unit.upper(), h, pr), "proposal_id": pr}
    return {"text": "保养周期 {} 改为 {:g} 运行小时".format(unit.upper(), h)}


def interval_of(db, mode, unit):
    return float((_state(db, mode).get("interval") or {}).get(unit) or REL.params(unit)["pm_h"])


# ---------------------------------------------------------------- 处理方案（E3-6）：保养时机
def options(db, mode, a, snap, ctx):
    """不做（对照：按失效率算预期损失，并推演“如果坏了”）/ 现在保养 / 下班后（或 4 小时后）保养"""
    from hub.ont import plan as P
    from hub.ont import playbook as PB
    from sim.calendar import Calendar
    v = (a.get("detail") or {}).get("values") or {}
    unit = a["subject_key"] if a.get("subject_type") == "Machine" else v.get("unit")
    if not unit or unit not in (snap.get("machines") or {}) or not REL.params(unit):
        return {"options": [], "affected": [], "reason": "这个异常没有关联到车间设备", "recommended": None}
    rk = risk(db, mode, unit, run_h=(snap["machines"][unit].get("run_h") if snap["machines"][unit].get("run_h") is not None else None))
    mins = pm_minutes(unit)
    cal = Calendar.from_dict(snap.get("calendar"))
    delay = 240
    if cal.mode == "shift":
        now = dt.datetime.fromisoformat(snap["factory_now"]).astimezone(cal.tzi)
        w = cal.window("*", now.date())
        if w and now.hour * 60 + now.minute < w[1]:
            delay = max(10, w[1] - (now.hour * 60 + now.minute))
    pm = {"type": "pm_order", "unit": unit, "minutes": mins}
    stub = dict(a, rule="P1", subject_type="Machine", subject_key=unit)
    names = PB.affected(stub, ctx)
    plans = [("none", "不做（对照）", [], "按失效率，未来 {:g} 运行小时坏掉的概率 {:.0%}，预期停机 {:.0f} 分钟、预期损失 ${:,.0f}".format(
        rk["horizon_h"], rk["p_fail"], rk["expected_down_min"], rk["expected_loss_usd"]), rk["expected_loss_usd"]),
        ("pm_now", "现在保养（停 {} 分钟）".format(mins), [pm], "保养后失效率回到起点：未来 {:g} 运行小时坏掉的概率 {:.1%}".format(rk["horizon_h"], rk["p_after_pm"]),
         round(rk["p_after_pm"] * (rk["repair_usd"] + rk["lost_usd"]), 2)),
        ("pm_later", "{}保养".format("下班后" if cal.mode == "shift" and delay != 240 else "{:.0f} 分钟后".format(delay)), [dict(pm, delay_minutes=delay)],
         "先生产 {:.0f} 分钟再停；这段时间里坏掉的概率约 {:.0%}".format(delay, REL.cond_fail(rk["run_h"] * rk["factor"], delay / 60 * rk["factor"],
                                                                          rk["beta"], rk["eta_h"])),
         round(rk["p_after_pm"] * (rk["repair_usd"] + rk["lost_usd"]) +
               REL.cond_fail(rk["run_h"] * rk["factor"], delay / 60 * rk["factor"], rk["beta"], rk["eta_h"]) * (rk["repair_usd"] + rk["lost_usd"]), 2))]
    out = []
    for i, (kind, label, changes, note, exp_loss) in enumerate(plans):
        r = P.simulate(snap, changes, ctx)
        costs = list(r["costs"])
        if exp_loss:
            costs.append({"what": "预期故障损失（概率 × 修理与停机）", "usd": exp_loss})
        rows = [s for s in r["sales_orders"] if s["name"] in names]
        res = {"sales_orders": rows, "cost_total": round(sum(c["usd"] for c in costs), 2), "costs": costs, "overtime_min": r["overtime_min"],
               "overtime_units": r["overtime_units"], "checks": r["checks"], "ok": r["ok"]}
        if kind == "none":
            fr = P.simulate(snap, [{"type": "breakdown", "unit": unit, "minutes": rk["mttr_min"]}], ctx)
            lates = [s["late_days"] for s in fr["sales_orders"] if s["name"] in names and s["late_days"] is not None]
            res["if_fails"] = {"worst_late": max(lates) if lates else None, "mttr_min": rk["mttr_min"]}
            note += "；如果现在就坏（停 {} 分钟），订单最多晚 {} 天".format(rk["mttr_min"], max(0, max(lates)) if lates else "—")
        lates = [s["late_days"] for s in rows if s["late_days"] is not None]
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "changes": changes, "result": res,
                    "worst_late": max(lates) if lates else None, "undetermined": len(lates) < len(rows)})

    def score(o):
        wl = o["worst_late"] if o["worst_late"] is not None else 99
        return (0 if o["result"]["ok"] else 1, 1 if o["undetermined"] else 0, max(wl, 0), o["result"]["cost_total"])
    best = min(out, key=score)
    for o in out:
        o["recommended"] = o is best
    reason = "建议 {} {}：交期 {}，算上预期故障损失共 ${:,.0f}（不做的预期损失 ${:,.0f}）。".format(
        best["key"], best["label"], "；".join("{} {}".format(s["name"], "按时" if (s["late_days"] or 0) <= 0 else "晚 {} 天".format(s["late_days"]))
                                       for s in best["result"]["sales_orders"]) or "没有受影响的订单",
        best["result"]["cost_total"], out[0]["result"]["cost_total"])
    return {"options": out, "affected": names, "reason": reason, "recommended": best["key"], "risk": {k: rk[k] for k in rk if k != "curve"}}


def inspection_options(db, mode, a):
    """M3 点检异常：开维修单 / 先观察（下次点检复查）"""
    v = (a.get("detail") or {}).get("values") or {}
    unit = v.get("unit") or a.get("subject_key")
    rp = REL.params(unit) or {"mttr_min": 120, "modes": []}
    part = next((m[2] for m in rp["modes"] if m[2]), None)
    title = "点检异常：" + "、".join(x["item"] for x in v.get("abnormal") or [])[:120]
    out = [{"key": "A", "kind": "repair", "label": "开维修单（停机检修）", "note": "挂牌上锁，维修工检修；可能用到 {}".format(part or "—"),
            "changes": [{"type": "repair_order", "unit": unit, "title": title, "source": "inspection", "inspection_id": v.get("inspection_id"),
                         "parts": [{"item_code": part, "qty": 2}] if part else []}],
            "result": {"sales_orders": [], "cost_total": round(rp["mttr_min"] / 60 * LABOR_RATE, 2), "costs": [], "overtime_min": 0, "checks": [], "ok": True}},
           {"key": "B", "kind": "watch", "label": "先观察，下次点检复查", "note": "不停机；异常加重会变成故障", "changes": [],
            "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True}}]
    out[0]["recommended"], out[1]["recommended"] = True, False
    return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：点检发现的异常先查清，避免小问题变成故障停机"}


# ---------------------------------------------------------------- 故障事件 → 维修单（车间发的 fault 事件）
def scan_failures(H, mode):
    db = H.db
    init(db)
    st = _state(db, mode)
    last = int(st.get("seq") or 0)
    rows = db.q("select seq as id, ts, topic, payload from bus_message where type='machine.event' and mode=%s and seq > %s "
                "and payload->'data'->>'event'='fault' and payload->'data' ? 'failure' order by seq limit 50", (mode, last))
    made = []
    for r in rows:
        d = r["payload"]["data"]
        unit = r["topic"].split("/")[3]
        st["seq"] = r["id"]
        f = db.one("insert into maint_failure (mode, unit, seq, code, name, part, at, run_h, down_min) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                   (mode, unit, r["id"], d.get("failure"), d.get("failure_name"), d.get("part"), r["ts"], d.get("run_h_pm"),
                    round(float(d.get("expected_duration_s") or 0) / 60, 1)))
        parts = [{"item_code": d["part"], "qty": 2}] if d.get("part") else []
        made.append(open_repair(H, mode, unit, "failure", "故障：" + (d.get("failure_name") or ""), parts, "设备报故障", failure_id=f["id"]))
    if rows:
        _save_state(db, mode, st)
    return made


# ---------------------------------------------------------------- 教学模拟器（E3-8）
def tick(H, mode, now=None, rng=None):
    if mode != "teach":
        return {}
    db = H.db
    seed(db, mode)
    rng = rng or random.Random()
    now = now or dt.datetime.now(dt.timezone.utc)
    done = {"failures": scan_failures(H, mode), "repairs": [], "pms": [], "inspections": []}
    # 维修、保养：持证维修工按时做完（真实时间 = 分钟 ÷ 30，至少 1 分钟），待验收
    for r in db.q("select r.*, p.valid_from from maint_repair r left join work_permit p on p.id=r.permit_id where r.mode=%s and r.status in ('doing','waiting_parts')",
                  (mode,)):
        rp = REL.params(r["unit"]) or {"mttr_min": 120}
        t0 = r["started_at"] or r["created_at"]
        if (now - t0).total_seconds() >= max(60, rp["mttr_min"] * 2):
            try:
                finish_repair(H, mode, r["id"], "维修工（教学模拟器）", "按标准维修完成")
                done["repairs"].append(r["id"])
            except ValueError:
                pass                                        # 等备件
    for r in db.q("select p.*, w.valid_from from maint_pm p left join work_permit w on w.id=p.permit_id where p.mode=%s and p.status='doing'", (mode,)):
        if r["valid_from"] and (now - r["valid_from"]).total_seconds() >= max(60, (r["minutes"] + r["delay_minutes"]) * 2):
            finish_pm(H, mode, r["id"], "维修工（教学模拟器）", "按保养规程完成")
            done["pms"].append(r["id"])
    # 故障停机的维修单：做完后没人验收，班组长（模拟器）过一阵替你验收解锁，车间不会一直锁着
    for r in db.q("select * from maint_repair where mode=%s and status='fixed' and source='failure' and fixed_at < now() - interval '3 minutes'", (mode,)):
        try:
            verify_repair(H, mode, r["id"], "班组长（教学模拟器）")
            done["repairs"].append(r["id"])
        except (ValueError, PermissionError, KeyError):
            pass
    st = _state(db, mode)
    if now.timestamp() - float(st.get("fsync") or 0) > 600:            # 每 10 分钟把可靠性系数再发一次（仿真器重启后会回到默认）
        mes = getattr(H, "mes", None)
        if mes is not None:
            mes.command("sim", "set_reliability", mode, "系统", factor=factor(db, mode))
        _save_state(db, mode, dict(_state(db, mode), fsync=now.timestamp()))
        st = _state(db, mode)
    if now.timestamp() - float(st.get("insp") or 0) > 300:              # 每 5 分钟（真实时间）模拟器点检一台
        st["insp"] = now.timestamp()
        u = rng.choice(units())
        items = checklist(db, mode, u)
        bad = rng.random() < 0.15
        res = [{"item": i, "ok": not (bad and i == "没有异响、异常振动")} for i in items]
        done["inspections"].append(inspect(db, mode, u, res, "操作工（教学模拟器）")["id"])
        _save_state(db, mode, dict(_state(db, mode), insp=st["insp"]))
    return done


def set_factor(H, mode, f, who):
    db = H.db
    st = _state(db, mode)
    st["factor"] = float(f)
    _save_state(db, mode, st)
    mes = getattr(H, "mes", None)
    if mes is not None:
        mes.command("sim", "set_reliability", mode, who, factor=float(f))
    return {"factor": float(f)}


def inject_overdue(H, mode, unit, hours, who):
    """老师：把某台设备“自上次保养以来的运行小时”往前拨（模拟保养逾期）"""
    rp = REL.params(unit)
    if rp is None:
        raise ValueError("这台设备没有保养计划")
    st = _state(H.db, mode)
    st.setdefault("overdue", {})[unit] = float(hours)
    _save_state(H.db, mode, st)
    mes = getattr(H, "mes", None)
    if mes is not None:
        mes.command(unit, "set_run_h", mode, who, hours=float(hours))
    return {"text": "已把 {} 的运行小时设为 {:g}（保养周期 {:g}）".format(unit.upper(), hours, rp["pm_h"])}


# ---------------------------------------------------------------- 态势
def kpis(db, mode):
    seed(db, mode)
    ms = machine_rows(db, mode)
    over = [u for u in units() if run_hours(db, mode, u, ms) > interval_of(db, mode, u)]
    rep = db.one("select count(*) as n from maint_repair where mode=%s and status<>'closed'", (mode,))["n"]
    down = db.one("select coalesce(sum(down_min),0) as m from maint_failure where mode=%s and at > now() - interval '7 days'", (mode,))["m"]
    insp = db.one("select count(*) as n from maint_inspection where mode=%s and status='open'", (mode,))["n"]
    return {"overdue": len(over), "overdue_units": over, "open_repairs": rep, "failure_down_7d": float(down or 0), "mtbf": mtbf(db, mode),
            "open_inspections": insp, "factor": factor(db, mode)}


# ---------------------------------------------------------------- ERPNext 台账（E3-1）
def ensure_setup(H, mode, who="系统"):
    """ERPNext 里还没有这批设备的资产和维护计划：整批建（提议 maint_setup，自动确认）。建过或正在建就不重复"""
    db = H.db
    if H.ai is None:
        return None
    import time as _t
    st = _state(db, mode)
    pid = st.get("setup_pid")
    have = {str(m["data"].get("asset_name") or "").split(" ")[0] for m in db.erp_docs("Asset", mode)}
    have_mt = {m["data"].get("asset_name") for m in db.erp_docs("Asset Maintenance", mode)}
    have_all = all(u.upper() in have for u in units()) and len(have_mt) >= len(units())
    if have_all:
        return pid
    if pid:
        p = db.one("select status from ai_proposal where proposal_id=%s", (pid,))
        age = _t.time() - float(st.get("setup_at") or 0)
        if p is None:
            pass
        elif p["status"] == "failed":
            if age < 3600:                                              # 上次失败：一小时后再试，不刷屏
                return None
        elif age < 180:                                                 # 还在执行（13 台资产要提交，真 ERPNext 要一两分钟）
            return pid
        elif p["status"] == "executed" and age < 900:
            return pid                                                  # 执行完了，等轮询读回
        # 确认了 3 分钟还没执行（桥接没收到：ERPNext 还没就绪时发的），或执行完 15 分钟仍缺：重发缺的（桥接按名称跳过已建的）
    rows = []
    for u in units():
        if u.upper() in have and len(have_mt) >= len(units()):
            continue
        rows.append({"unit": u, "asset_name": "{} {}".format(u.upper(), UNITS[u][1]), "value": ASSETS.get(u, 20000),
                     "purchase_date": "{}-03-01".format(BOUGHT.get(u, 2020)), "task": "{:g} 小时保养：{}".format(interval_of(db, mode, u), PM_TEXT.get(u, "例行保养")),
                     "interval_h": interval_of(db, mode, u)})
    if not rows:
        return None
    pid = H.ai.propose("maint_setup", {"assets": rows}, mode, who, "设备台账与保养计划 {} 台".format(len(rows)), source="maint")
    H.ai.decide(pid, who, True)
    st = _state(db, mode)
    st["setup_pid"], st["setup_at"] = pid, _t.time()
    _save_state(db, mode, st)
    return pid


def parts_options(db, mode, a):
    """M5 维修等备件：紧急采购 / 等正常采购"""
    v = (a.get("detail") or {}).get("values") or {}
    lines = v.get("lines") or []
    arrive = (dt.date.today() + dt.timedelta(days=1 if dt.date.today().weekday() < 4 else 3)).isoformat()
    ch = [{"type": "urgent_purchase", "item": x["item"], "qty": int(x["qty"]) + SPARE_MIN.get(x["item"], 2), "arrive": arrive} for x in lines]
    cost = round(sum(PART_PRICE.get(x["item"], 0) * c["qty"] * 0.15 for x, c in zip(lines, ch)), 2)
    out = [{"key": "A", "kind": "urgent_purchase", "label": "紧急采购备件（{} 到货）".format(arrive), "note": "加急费按货值 15%；补到最低库存",
            "changes": ch, "result": {"sales_orders": [], "cost_total": cost, "costs": [{"what": "加急费", "usd": cost}], "overtime_min": 0,
                                      "checks": [], "ok": True}, "recommended": True},
           {"key": "B", "kind": "wait", "label": "等正常采购", "note": "设备一直停着，等到货", "changes": [],
            "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True}, "recommended": False}]
    return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：设备停着等备件，加急费远小于停机损失"}
