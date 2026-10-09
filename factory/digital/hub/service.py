# -*- coding: utf-8 -*-
"""客户服务（第 18 轮 E1）：投诉、服务工程师与排班、服务方案估算、服务工单（派工）、回访与满意度、教学模拟器。

- 投诉存在平台的 complaint 表；同时在 ERPNext 开一张 Issue（类别“投诉”），售后和财务在 ERPNext 里也看得到（E1-1）。
- 服务工程师先用 6 位虚拟工程师（东部、南部、北部各 2 位），人员领域包（E4）上线后并入员工与技能矩阵（E1-8）。
- 服务方案用排班估算，不进车间仿真（E1-7）：每位工程师每天在本区域最多 2 单、去外区域 1 单（当天只做这一单）。
- 时间：服务的“哪天上门”用现场日（数字孪生的现场时钟，教学模式下比真实时间快）；投诉响应时限按真实小时算。"""
import datetime as dt
import json
import logging
import random
import zlib

from psycopg.types.json import Jsonb

from factory import data as F
from hub import crm

log = logging.getLogger("service")

SCHEMA = """
create table if not exists complaint (
    id          bigserial primary key,
    mode        text not null,
    customer    text,
    serial      text,
    subject     text not null,
    detail      text,
    severity    text not null default 'normal',      -- normal 一般 / serious 严重 / urgent 紧急
    channel     text,                                -- 电话 / 邮件 / 现场 / 模拟器
    contact     text,
    photo_ids   jsonb,
    status      text not null default 'open',        -- open 新 / doing 处理中 / closed 已关闭
    anomaly_id  bigint,
    issue       text,
    created_by  text,
    created_at  timestamptz not null default now(),
    responded_at timestamptz,
    closed_at   timestamptz,
    field_day   date,
    note        text
);
create index if not exists complaint_mode on complaint (mode, status);
create table if not exists engineer (
    id      text not null,
    mode    text not null,
    name    text not null,
    region  text not null,
    skills  jsonb,
    active  boolean not null default true,
    primary key (mode, id)
);
create table if not exists service_job (
    id          bigserial primary key,
    mode        text not null,
    serial      text not null,
    customer    text,
    kind        text not null,                       -- inspect 点检 / repair:<动作>
    engineer    text,
    day         date,                                -- 计划上门日（现场日）
    status      text not null default 'planned',     -- planned / done / cancelled
    warranty    boolean,
    cost        jsonb,
    issue       text,
    proposal_id text,
    batch_id    bigint,
    complaint_id bigint,
    anomaly_id  bigint,
    action_id   bigint,
    created_at  timestamptz not null default now(),
    done_day    date,
    done_by     text,
    result      text
);
create index if not exists service_job_mode on service_job (mode, status, day);
create table if not exists service_batch (
    id          bigserial primary key,
    mode        text not null,
    anomaly_id  bigint,
    kind        text not null,                       -- repair_one / repair_plus_check / batch_check
    units       jsonb not null,
    status      text not null default 'open',
    created_at  timestamptz not null default now()
);
create table if not exists follow_up (
    id          bigserial primary key,
    mode        text not null,
    job_id      bigint,
    serial      text,
    customer    text,
    due_day     date,
    score       numeric,
    comment     text,
    by_name     text,
    done_at     timestamptz,
    created_at  timestamptz not null default now()
);
create table if not exists customer_notice (
    id          bigserial primary key,
    mode        text not null,
    customer    text,
    email       text,
    subject     text,
    body        text,
    status      text not null default 'draft',       -- draft / sent / recorded
    action_id   bigint,
    created_at  timestamptz not null default now(),
    sent_at     timestamptz
);
create table if not exists crm_sim (
    mode        text primary key,
    state       jsonb not null default '{}'
);
"""
SITE_REGION = {"mine": "北部", "port": "东部", "food": "南部"}
ENGINEERS = [("E01", "周海", "东部"), ("E02", "陈蓝", "东部"), ("E03", "林青", "南部"), ("E04", "黄禾", "南部"),
             ("E05", "赵岩", "北部"), ("E06", "孙川", "北部")]
SKILLS = ["轴承更换", "润滑", "散热", "振动检测"]
SAME_REGION_PER_DAY = 2
LABOR_PER_JOB = 480.0          # 每单人工（$）：一人一天按 $480 的一半；外区域整天
TRAVEL_OTHER = 150.0           # 去外区域的差旅（$/单）
BEARING_KIT = ["BRG-6205", "BRG-6206", "BRG-6207"]
KIND_LABEL = {"inspect": "上门点检", "repair:oil": "换油", "repair:cooling": "清洁散热、修风扇", "repair:bearing": "更换轴承"}
SEVERITY = {"normal": "一般", "serious": "严重", "urgent": "紧急"}
STATUS = {"open": "新投诉", "doing": "处理中", "closed": "已关闭"}


def init(db):
    if getattr(db, "_service_ready", False):             # 记在库对象上（不用 id(db)：测试里删库重建后 id 可能复用）
        return
    db.x(SCHEMA)
    try:
        db._service_ready = True
    except AttributeError:
        pass


def seed_engineers(db, mode):
    init(db)
    for eid, name, region in ENGINEERS:
        db.x("insert into engineer (id, mode, name, region, skills) values (%s,%s,%s,%s,%s) on conflict do nothing",
             (eid, mode, name, region, Jsonb(SKILLS)))


def engineers(db, mode):
    seed_engineers(db, mode)
    return db.q("select * from engineer where mode=%s and active order by id", (mode,))


def field_today(db, mode):
    c = db.one("select * from field_clock where mode=%s", (mode,))
    if c is None:
        return dt.date.today()
    if c["paused"]:
        return c["anchor_day"]
    mins = (dt.datetime.now(dt.timezone.utc) - c["anchor_real"]).total_seconds() / 60
    return c["anchor_day"] + dt.timedelta(days=int(mins * c["days_per_min"]))


def region_of(site):
    return SITE_REGION.get(site, "东部")


def units(db, mode):
    """现场设备（孪生机队）加上服务要用的：区域、保修到期、风险分"""
    from hub import twin as TW
    try:
        fl = TW.fleet(db, mode)
    except Exception:  # noqa: BLE001
        return {}
    cache = crm.contracts(db, mode)
    today = field_today(db, mode)
    out = {}
    for u in fl:
        wb = u["summary"]["worst_bearing"]
        wu = crm.warranty_until(db, mode, u["customer"], u["start_day"], cache)
        risk = {"red": 3, "yellow": 2}.get(u["health"], 1) + min(1.0, float(wb["used"]))
        out[u["serial"]] = {"serial": u["serial"], "customer": u["customer"], "site": u["site"], "region": region_of(u["site"]),
                            "health": u["health"], "alerts": [a["title"] for a in u["alerts"]], "alert_kinds": [a.get("kind") for a in u["alerts"]],
                            "worst_bearing": {"id": wb["id"], "name": wb["name"], "model": wb["model"], "used": round(float(wb["used"]), 3)},
                            "start_day": u["start_day"], "warranty_until": wu.isoformat() if wu else None,
                            "in_warranty": bool(wu and today <= wu), "risk": round(risk, 2)}
    return out


def needs_bearing(u):
    return u["health"] == "red" or u["worst_bearing"]["used"] >= 0.7 or "bearing" in (u.get("alert_kinds") or [])


def is_high(u):
    """高风险：健康度红 / 黄，或最先到期的轴承寿命已用 50% 以上"""
    return u["health"] in ("red", "yellow") or u["worst_bearing"]["used"] >= 0.5


def repair_kind(u):
    """投诉的那台：按孪生的报警决定修什么"""
    kinds = u.get("alert_kinds") or []
    if "bearing" in kinds or u["worst_bearing"]["used"] >= 0.7:
        return "repair:bearing:" + u["worst_bearing"]["id"]
    if "cooling" in kinds:
        return "repair:cooling"
    if "oil" in kinds:
        return "repair:oil"
    return "inspect"


def kind_label(kind):
    if kind.startswith("repair:bearing:"):
        from twin import models as M
        b = M.BRG.get(kind.split(":")[2])
        return "更换{}（{}）".format(b[1], b[2]) if b else "更换轴承"
    return KIND_LABEL.get(kind, kind)


# ---------------------------------------------------------------- 排班
def booked(db, mode, start, days):
    """已排的单：(工程师, 日) → [单]"""
    init(db)
    rows = db.q("select engineer, day, serial, kind, id, customer from service_job where mode=%s and status='planned' and day >= %s and day < %s",
                (mode, start, start + dt.timedelta(days=days)))
    out = {}
    for r in rows:
        out.setdefault((r["engineer"], r["day"]), []).append(r)
    return out


def schedule(db, mode, start=None, days=14):
    """排班日历：每位工程师每天（休息 / 空闲 / 已排 N 单）"""
    start = start or field_today(db, mode)
    bk = booked(db, mode, start, days)
    out = []
    for e in engineers(db, mode):
        row = {"id": e["id"], "name": e["name"], "region": e["region"], "days": []}
        for i in range(days):
            d = start + dt.timedelta(days=i)
            jobs = bk.get((e["id"], d), [])
            row["days"].append({"day": d.isoformat(), "off": d.weekday() >= 5,
                                "jobs": [{"id": j["id"], "serial": j["serial"], "kind": kind_label(j["kind"]), "customer": j["customer"]} for j in jobs]})
        out.append(row)
    return {"start": start.isoformat(), "days": days, "engineers": out}


def plan_jobs(db, mode, wanted, start=None, horizon=21, extra_booked=None):
    """wanted：[{serial, region, kind, ...}]（按优先级排好）。贪心：先本区域、最早的有空日；本区域排不下再找外区域。
    返回 [{..., engineer, engineer_name, day, other_region}]"""
    start = start or field_today(db, mode)
    bk = {k: len(v) for k, v in booked(db, mode, start, horizon).items()}
    for k, n in (extra_booked or {}).items():
        bk[k] = bk.get(k, 0) + n
    away = set()                                           # (工程师, 日)：去外区域，这天不再接单
    engs = engineers(db, mode)
    out = []
    for w in wanted:
        best = None
        for i in range(horizon):
            d = start + dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            for e in engs:
                same = e["region"] == w["region"]
                if (e["id"], d) in away:
                    continue
                n = bk.get((e["id"], d), 0)
                if same and n < SAME_REGION_PER_DAY:
                    best = (e, d, False)
                    break
            if best:
                break
            for e in engs:                              # 本区域这天满了：外区域、当天空着的工程师
                if (e["id"], d) in away or bk.get((e["id"], d), 0):
                    continue
                best = (e, d, True)
                break
            if best:
                break
        if best is None:
            out.append(dict(w, engineer=None, engineer_name=None, day=None, other_region=False))
            continue
        e, d, other = best
        bk[(e["id"], d)] = bk.get((e["id"], d), 0) + 1
        if other:
            away.add((e["id"], d))
        out.append(dict(w, engineer=e["id"], engineer_name=e["name"], day=d.isoformat(), other_region=other))
    return out


def price(item):
    return float((F.ITEMS.get(item) or [None, None, None, 0])[3] or 0)


def job_cost(u, kind, other_region):
    labor = LABOR_PER_JOB * (2 if other_region else 1)
    travel = TRAVEL_OTHER if other_region else 0.0
    parts = {}
    if kind.startswith("repair:bearing:"):
        from twin import models as M
        b = M.BRG.get(kind.split(":")[2])
        code = "BRG-" + b[2].split("-")[0] if b else "BRG-6207"
        parts[code] = 2                                   # 一根轴两端的轴承一起换
    elif kind == "repair:oil":
        pass
    return {"labor": labor, "travel": travel, "parts": parts, "parts_usd": round(sum(price(k) * q for k, q in parts.items()), 2)}


def estimate(db, mode, wanted, start=None):
    """服务方案估算（E1-7）：wanted [{serial, kind}] → 派工计划、天数、人天、备件、费用（保修内由工厂承担）"""
    us = units(db, mode)
    rows = []
    for w in wanted:
        u = us.get(w["serial"])
        if u is None:
            continue
        rows.append(dict(w, region=u["region"], customer=u["customer"], in_warranty=u["in_warranty"], health=u["health"], risk=u["risk"]))
    start = start or field_today(db, mode)
    plan = plan_jobs(db, mode, rows, start)
    spares, labor, travel, parts_usd, warranty_cost, billable = {}, 0.0, 0.0, 0.0, 0.0, 0.0
    unplanned = []
    for p in plan:
        if not p["day"]:
            unplanned.append(p["serial"])
            continue
        c = job_cost(us[p["serial"]], p["kind"], p["other_region"])
        p["cost"] = c
        p["kind_label"] = kind_label(p["kind"])
        for k, q in c["parts"].items():
            spares[k] = spares.get(k, 0) + q
        tot = c["labor"] + c["travel"] + c["parts_usd"]
        labor += c["labor"]
        travel += c["travel"]
        parts_usd += c["parts_usd"]
        if p["in_warranty"]:
            warranty_cost += tot
        else:
            billable += tot
    days = [dt.date.fromisoformat(p["day"]) for p in plan if p["day"]]
    finish = max(days) if days else None
    person_days = sum((1.0 if p["other_region"] else 0.5) for p in plan if p["day"])
    return {"jobs": plan, "start": start.isoformat(), "finish": finish.isoformat() if finish else None,
            "days": ((finish - start).days + 1) if finish else 0, "person_days": person_days, "engineers": sorted({p["engineer_name"] for p in plan if p["day"]}),
            "spares": spares, "customers": sorted({p["customer"] for p in plan}),
            "cost": {"labor": round(labor, 2), "travel": round(travel, 2), "parts": round(parts_usd, 2),
                     "warranty": round(warranty_cost, 2), "billable": round(billable, 2), "total": round(labor + travel + parts_usd, 2)},
            "unplanned": unplanned, "units": len(plan)}


# ---------------------------------------------------------------- 处理方案（预案：C1 投诉、C4 / V2 批次、V1 报警、C3 超时）
def scope_units(db, mode, a):
    """异常 → (出问题的设备, 排查范围里的其他设备)"""
    from hub.ont import anomaly as A
    from hub.ont import chain as CH
    v = (a.get("detail") or {}).get("values") or {}
    serials = list(v.get("units") or [])
    if a.get("subject_type") == "FieldUnit" and a.get("subject_key"):
        serials = [a["subject_key"]] + [s for s in serials if s != a["subject_key"]]
    if not serials and v.get("serial"):
        serials = [v["serial"]]
    if not serials:
        return [], []
    ch = a.get("chain")
    if not ch or (ch.get("kind") != "field"):
        ch = CH.chain_field(A.Ctx(db, mode), serials).out()
    others = [s for s in ((ch or {}).get("scope") or {}).get("check_units", []) if s not in serials]
    return serials, others


def options(db, mode, a):
    """三个方案：只修出问题的、修 + 高风险点检、整批排查。每个都估算派工、天数、备件、费用、受影响客户"""
    us = units(db, mode)
    bad, others = scope_units(db, mode, a)
    bad = [s for s in bad if s in us]
    others = sorted([s for s in others if s in us], key=lambda s: -us[s]["risk"])
    if not bad:
        return {"options": [], "reason": "这个异常没有关联到现场设备（序列号查不到出厂数据），按投诉内容人工处理"}
    high = [s for s in others if is_high(us[s])]
    fix = [{"serial": s, "kind": repair_kind(us[s])} for s in bad]

    def chk(s):
        return {"serial": s, "kind": "repair:bearing:" + us[s]["worst_bearing"]["id"] if needs_bearing(us[s]) else "inspect"}
    plans = [("repair_one", "只修出问题的", fix, "排查范围里的其他设备先不动，等它们自己报警")]
    if others:
        plans.append(("repair_plus_check", "修出问题的 + 高风险的上门点检", fix + [chk(s) for s in high],
                      "高风险 = 孪生健康度红 / 黄，或最先到期的轴承已用 50% 以上：{} 台".format(len(high))))
        plans.append(("batch_check", "整批排查（全部点检）", fix + [chk(s) for s in others], "同一片砂轮磨的轴装在 {} 台设备上，全部上门点检".format(len(others))))
    out = []
    for i, (kind, label, wanted, note) in enumerate(plans):
        est = estimate(db, mode, wanted)
        left_high = [s for s in high if s not in {w["serial"] for w in wanted}]
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "service": est,
                    "uncovered_high": left_high, "changes": [{"type": "service_batch", "kind": kind, "jobs": [{"serial": j["serial"], "kind": j["kind"]} for j in est["jobs"]],
                                                              "spares": est["spares"]}] + ([{"type": "spare_ship", "items": [{"item_code": k, "qty": q} for k, q in est["spares"].items()]}]
                                                                                           if est["spares"] else [])
                    + ([{"type": "customer_notice", "customers": [c for c in est["customers"] if c not in {us[b]["customer"] for b in bad}]
                                                     or est["customers"]}] if kind != "repair_one" else []),
                    "result": {"sales_orders": [], "cost_total": est["cost"]["total"], "costs": [], "overtime_min": 0, "overtime_units": 0,
                               "ok": not est["unplanned"], "checks": [{"ok": False, "text": "{} 台排不进 21 天".format(len(est["unplanned"]))}] if est["unplanned"] else [],
                               "service": est}})
    # 推荐：先把高风险的都覆盖到，再比花的钱、天数
    best = min(out, key=lambda o: (len(o["uncovered_high"]) > 0, len(o["uncovered_high"]), o["service"]["cost"]["total"], o["service"]["days"]))
    for o in out:
        o["recommended"] = o is best
    s = best["service"]
    reason = "建议 {} {}：派 {} 位工程师（{}），{} 天做完（到 {}），备件 {} 件，花 ${:,.0f}（保修内由工厂承担 ${:,.0f}，向客户收 ${:,.0f}），涉及 {} 个客户。".format(
        best["key"], best["label"], len(s["engineers"]), "、".join(s["engineers"]), s["days"], s["finish"],
        sum(s["spares"].values()), s["cost"]["total"], s["cost"]["warranty"], s["cost"]["billable"], len(s["customers"]))
    if best["uncovered_high"]:
        reason += "注意：还有 {} 台高风险设备没覆盖。".format(len(best["uncovered_high"]))
    return {"options": out, "reason": reason, "recommended": best["key"], "affected": [], "scope": {"bad": bad, "others": others, "high": high}}


SERVICE_RULES = ("C1", "C3", "C4", "V1", "V2")


def anomaly_options(db, mode, a):
    """指挥台和 AI 代理共用：异常 → 服务方案，动作参数里带上投诉号和是否全在保修内"""
    r = options(db, mode, a)
    cid = ((a.get("detail") or {}).get("values") or {}).get("complaint")
    for o in r["options"]:
        for c in o["changes"]:
            if c["type"] == "service_batch":
                c["complaint_id"] = int(cid[3:]) if cid else None
                c["in_warranty"] = bool(c["jobs"]) and all(x.get("in_warranty") for x in o["service"]["jobs"])
    r["service"] = True
    return r


# ---------------------------------------------------------------- 执行：建服务工单、出库、通知
def create_jobs(H, mode, jobs, who, anomaly_id=None, action_id=None, complaint_id=None, batch_kind="repair_one"):
    """排进日历、在孪生里记维修单、经桥接在 ERPNext 开 Issue（指派工程师）"""
    db = H.db
    init(db)
    us = units(db, mode)
    plan = plan_jobs(db, mode, [dict(j, region=us[j["serial"]]["region"]) for j in jobs if j["serial"] in us])
    b = db.one("insert into service_batch (mode, anomaly_id, kind, units) values (%s,%s,%s,%s) returning id",
               (mode, anomaly_id, batch_kind, Jsonb([p["serial"] for p in plan])))
    orders, ids = [], []
    for p in plan:
        u = us[p["serial"]]
        c = job_cost(u, p["kind"], p["other_region"])
        r = db.one("insert into service_job (mode, serial, customer, kind, engineer, day, warranty, cost, batch_id, complaint_id, anomaly_id, action_id) "
                   "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                   (mode, p["serial"], u["customer"], p["kind"], p["engineer"], p["day"], u["in_warranty"], Jsonb(c), b["id"], complaint_id,
                    anomaly_id, action_id))
        ids.append(r["id"])
        what = kind_label(p["kind"])
        orders.append({"subject": "[{}] {}：{}".format(p["serial"], u["customer"], what)[:140], "serial": p["serial"], "customer": u["customer"],
                       "engineer": p["engineer_name"] or "", "day": p["day"], "kind": "点检 inspection" if p["kind"] == "inspect" else "维修 repair",
                       "description": "服务工单 SJ-{:05d}：{}。工程师 {}，计划 {} 上门。{}".format(r["id"], what, p["engineer_name"] or "待定", p["day"] or "待定",
                                                                                     "保修期内" if u["in_warranty"] else "已过保修期")})
        try:
            db.x("insert into twin_event (serial, mode, day, kind, level, title, status, detail) values (%s,%s,%s,'order','info',%s,'ordered',%s)",
                 (p["serial"], mode, field_today(db, mode), "服务工单 SJ-{:05d}：{}（{} {}）".format(r["id"], what, p["engineer_name"] or "", p["day"] or ""),
                  Jsonb({"action": _twin_action(p["kind"]), "job_id": r["id"], "what": what, "by": who})))
            if p["kind"] != "inspect":
                db.x("update twin_event set status='ordered' where serial=%s and mode=%s and status='open' and kind not in ('maint','order')",
                     (p["serial"], mode))
        except Exception:  # noqa: BLE001
            log.exception("孪生维修单记录失败")
    pid = None
    if orders and H.ai is not None:
        pid = H.ai.propose("service_orders", {"orders": orders}, mode, who, "服务工单 {} 张".format(len(orders)), source="service")
        H.ai.decide(pid, who, True)
        db.x("update service_job set proposal_id=%s where id = any(%s)", (pid, ids))
    return {"batch_id": b["id"], "jobs": ids, "proposal_id": pid, "plan": plan}


def _twin_action(kind):
    if kind.startswith("repair:bearing:"):
        return "bearing:" + kind.split(":")[2]
    if kind.startswith("repair:"):
        return kind.split(":")[1]
    return "inspect"


def issue_of(db, job):
    """服务工单对应的 ERPNext Issue 号（桥接执行提议后回填）"""
    if job.get("issue"):
        return job["issue"]
    p = db.one("select result from ai_proposal where proposal_id=%s", (job.get("proposal_id"),)) if job.get("proposal_id") else None
    res = (p or {}).get("result") or {}
    if isinstance(res, str):
        res = json.loads(res)
    issues = [c[1] for c in res.get("created", []) if c[0] == "Issue"]
    same = db.q("select id from service_job where proposal_id=%s order by id", (job["proposal_id"],)) if job.get("proposal_id") else []
    idx = next((i for i, r in enumerate(same) if r["id"] == job["id"]), None)
    if idx is not None and idx < len(issues):
        db.x("update service_job set issue=%s where id=%s", (issues[idx], job["id"]))
        return issues[idx]
    return None


def complete_job(H, mode, job_id, who, note="", day=None):
    """工程师完工：孪生寿命复位 / 故障消失；ERPNext 的 Issue 改为已解决；生成回访任务"""
    db = H.db
    j = db.one("select * from service_job where id=%s and mode=%s", (job_id, mode))
    if j is None:
        raise KeyError(job_id)
    if j["status"] != "planned":
        raise ValueError("这张服务工单已经{}".format({"done": "完成", "cancelled": "取消"}.get(j["status"], j["status"])))
    day = day or field_today(db, mode)
    us = units(db, mode)
    u = us.get(j["serial"])
    act = _twin_action(j["kind"])
    result = note or ""
    if act == "inspect" and u and needs_bearing(u):
        act = "bearing:" + u["worst_bearing"]["id"]
        result = (result + "；" if result else "") + "点检发现{}已用 {:.0%}，当场更换".format(u["worst_bearing"]["name"], u["worst_bearing"]["used"])
    if act != "inspect" and getattr(H, "twin", None) is not None:
        try:
            H.twin.repair(mode, j["serial"], act, day.isoformat() if hasattr(day, "isoformat") else day)
        except Exception:  # noqa: BLE001
            log.exception("孪生维修回写失败")
    db.x("update service_job set status='done', done_day=%s, done_by=%s, result=%s where id=%s", (day, who, result or "已完成", job_id))
    db.x("update twin_event set status='done' where mode=%s and kind='order' and (detail->>'job_id')::bigint=%s", (mode, job_id))
    db.x("insert into follow_up (mode, job_id, serial, customer, due_day) values (%s,%s,%s,%s,%s)",
         (mode, job_id, j["serial"], j["customer"], day + dt.timedelta(days=1)))
    iss = issue_of(db, j)
    if iss and H.ai is not None:
        pid = H.ai.propose("service_order_done", {"issue": iss, "text": "已完成：{}。{}（问渠数字工厂 · 客户服务）".format(kind_label(j["kind"]), result)},
                           mode, who, "完成服务工单 " + iss, source="service")
        H.ai.decide(pid, who, True)
    if j["complaint_id"]:
        left = db.one("select count(*) as n from service_job where complaint_id=%s and status='planned'", (j["complaint_id"],))["n"]
        if not left:
            db.x("update complaint set status='closed', closed_at=now(), note=coalesce(note,'') || %s where id=%s and status<>'closed'",
                 ("服务完成，自动关闭；", j["complaint_id"]))
    return {"ok": True, "issue": iss, "result": result}


def ship_spares(H, mode, items, who, note=""):
    if not items:
        return None
    pid = H.ai.propose("spare_ship", {"items": items, "note": note or "问渠数字工厂 · 服务备件"}, mode, who,
                       "备件出库：" + "、".join("{} × {}".format(i["item_code"], i["qty"]) for i in items), source="service")
    H.ai.decide(pid, who, True)
    return pid


def notice(H, mode, customers, who, action_id=None, send=False, emails=None):
    """预防性服务通知：平台起草，人确认后才发（E1-6）；教学模式只记录，生产模式有邮箱才发"""
    from hub.ont import notify as NT
    db = H.db
    init(db)
    out = []
    for c in customers:
        body = ("{}：\n\n我们在出厂质量追溯中发现，贵方现场的部分 WQR-105 减速器所用输出轴与一台已报问题的设备出自同一批次。"
                "为保证设备可靠运行，我们将安排服务工程师上门点检，费用按合同保修条款处理。工程师会提前与您确认时间。\n\n"
                "问渠减速器厂 客户服务").format(c)
        email = (emails or {}).get(c)
        status = "recorded"
        if mode != "teach" and send and email:
            status = "sent" if NT.send_mail(email, "【问渠减速器厂】预防性服务通知", body) else "draft"
        r = db.one("insert into customer_notice (mode, customer, email, subject, body, status, action_id, sent_at) values (%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                   (mode, c, email, "预防性服务通知", body, status, action_id, dt.datetime.now(dt.timezone.utc) if status == "sent" else None))
        out.append({"id": r["id"], "customer": c, "status": status})
    return out


# ---------------------------------------------------------------- 投诉
def create_complaint(H, mode, body, who):
    db = H.db
    init(db)
    serial = (body.get("serial") or "").strip() or None
    us = units(db, mode)
    u = us.get(serial) if serial else None
    customer = (body.get("customer") or "").strip() or (u["customer"] if u else None)
    subject = (body.get("subject") or "").strip()
    if not subject:
        raise ValueError("写一句投诉的现象，例如“异响、油温高”")
    if not customer:
        raise ValueError("填客户，或填设备序列号（会自动带出客户）")
    sev = body.get("severity") or "normal"
    if sev not in SEVERITY:
        raise ValueError("严重度只能是一般 / 严重 / 紧急")
    r = db.one("insert into complaint (mode, customer, serial, subject, detail, severity, channel, contact, photo_ids, created_by, field_day) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, customer, serial, subject[:200], (body.get("detail") or "")[:2000], sev, body.get("channel") or "电话",
                (body.get("contact") or "")[:200] or None, Jsonb(body.get("photo_ids") or []), who, field_today(db, mode)))
    cid = r["id"]
    if H.ai is not None:
        pid = H.ai.propose("complaint_issue", {"complaint_id": cid, "subject": "【投诉】{}：{}".format(customer, subject)[:140], "serial": serial,
                                                "customer": customer, "description": body.get("detail") or ""},
                           mode, who, "投诉 CP-{:05d} 进 ERPNext".format(cid), source="service")
        H.ai.decide(pid, who, True)
        db.x("update complaint set note=%s where id=%s", ("proposal:" + pid, cid))
    return cid


def complaint_issue(db, c):
    note = c.get("note") or ""
    if c.get("issue") or not note.startswith("proposal:"):
        return c.get("issue")
    p = db.one("select result from ai_proposal where proposal_id=%s", (note.split(":", 1)[1].split(";")[0],))
    res = (p or {}).get("result") or {}
    if isinstance(res, str):
        res = json.loads(res)
    iss = next((x[1] for x in res.get("created", []) if x[0] == "Issue"), None)
    if iss:
        db.x("update complaint set issue=%s where id=%s", (iss, c["id"]))
    return iss


def complaint_row(db, c, us=None):
    us = us if us is not None else {}
    u = us.get(c["serial"]) if c["serial"] else None
    return {"id": c["id"], "key": "CP-{:05d}".format(c["id"]), "customer": c["customer"], "serial": c["serial"], "subject": c["subject"],
            "detail": c["detail"], "severity": c["severity"], "severity_label": SEVERITY[c["severity"]], "channel": c["channel"], "contact": c["contact"],
            "status": c["status"], "status_label": STATUS[c["status"]], "anomaly_id": c["anomaly_id"], "issue": complaint_issue(db, c),
            "created_by": c["created_by"], "created_at": c["created_at"].isoformat(),
            "responded_at": c["responded_at"].isoformat() if c["responded_at"] else None, "closed_at": c["closed_at"].isoformat() if c["closed_at"] else None,
            "field_day": c["field_day"].isoformat() if c["field_day"] else None, "traceable": bool(u), "unit": u, "photo_ids": c["photo_ids"] or []}


def respond(db, cid, who, status, text=""):
    if status not in ("doing", "closed"):
        raise ValueError("状态只能改成处理中或已关闭")
    c = db.one("select * from complaint where id=%s", (cid,))
    if c is None:
        raise KeyError(cid)
    db.x("update complaint set status=%s, responded_at=coalesce(responded_at, now()), closed_at=case when %s='closed' then now() else closed_at end, "
         "note=coalesce(note,'') || %s where id=%s", (status, status, ";{}：{}".format(who, text)[:300] if text else "", cid))


# ---------------------------------------------------------------- 回访
def score_follow_up(db, fid, score, comment, who):
    s = float(score)
    if not 1 <= s <= 5:
        raise ValueError("满意度 1–5 分")
    db.x("update follow_up set score=%s, comment=%s, by_name=%s, done_at=now() where id=%s", (s, (comment or "")[:300], who, fid))


def satisfaction(db, mode, days=30):
    r = db.one("select avg(score) as s, count(*) as n from follow_up where mode=%s and done_at > now() - make_interval(days => %s) and score is not null",
               (mode, days))
    return {"avg": round(float(r["s"]), 2) if r["s"] is not None else None, "n": r["n"]}


def kpis(db, mode):
    """态势卡：开着的投诉、开着的服务工单、平均响应、一次修复率、保修成本、满意度"""
    init(db)
    oc = db.one("select count(*) as n from complaint where mode=%s and status<>'closed'", (mode,))["n"]
    oj = db.one("select count(*) as n from service_job where mode=%s and status='planned'", (mode,))["n"]
    rt = db.one("select avg(extract(epoch from responded_at - created_at)/3600) as h from complaint where mode=%s and responded_at is not null "
                "and created_at > now() - interval '30 days'", (mode,))["h"]
    done = db.q("select serial, done_day from service_job where mode=%s and status='done' and kind<>'inspect' and created_at > now() - interval '90 days'", (mode,))
    repeat = 0
    for d in done:
        if db.one("select 1 as x from complaint where mode=%s and serial=%s and field_day > %s and field_day <= %s",
                  (mode, d["serial"], d["done_day"], d["done_day"] + dt.timedelta(days=30))):
            repeat += 1
    wc = db.one("select coalesce(sum((cost->>'labor')::numeric + (cost->>'travel')::numeric + (cost->>'parts_usd')::numeric), 0) as v from service_job "
                "where mode=%s and warranty and status<>'cancelled' and created_at > now() - interval '30 days'", (mode,))["v"]
    sat = satisfaction(db, mode)
    return {"open_complaints": oc, "open_jobs": oj, "response_h": round(float(rt), 1) if rt is not None else None,
            "first_fix": round(1 - repeat / len(done), 3) if done else None, "warranty_cost": float(wc or 0), "satisfaction": sat["avg"], "surveys": sat["n"]}


# ---------------------------------------------------------------- 教学模拟器（E1-9）
LEAD_COMPANIES = [("江南水泥厂", "生产线输送机改造，要 6 台"), ("北岭钢铁 · 烧结车间", "皮带机减速器替换"), ("星河饲料", "包装线扩产"),
                  ("东方港务二期", "新码头输送线，预计 20 台"), ("青山矿业", "老设备更新"), ("蓝湾物流中心", "分拣线驱动"),
                  ("华达建材", "搅拌站上料皮带"), ("海川粮油", "提升机和输送机")]


def _state(db, mode):
    init(db)
    r = db.one("select state from crm_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _save_state(db, mode, st):
    db.x("insert into crm_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


def _rand(*k):
    return random.Random(zlib.crc32("|".join(str(x) for x in k).encode())).random()


def tick(H, mode, now=None):
    """教学模式每轮（约 20 秒）跑一次：投诉、到期的服务、回访、线索。返回本轮做了什么"""
    if mode != "teach":
        return {}
    db = H.db
    init(db)
    today = field_today(db, mode)
    st = _state(db, mode)
    done = {"complaints": [], "jobs": [], "follow_ups": [], "leads": []}
    us = units(db, mode)
    # 1 投诉：红色一定来电；黄色每个现场日 15% 概率；同一台 30 个现场日内只投诉一次。注入的批次投诉按排定的日子来
    planned = st.get("batch") or []
    for p in list(planned):
        if dt.date.fromisoformat(p["day"]) <= today and p["serial"] in us:
            cid = create_complaint(H, mode, {"serial": p["serial"], "subject": p["subject"], "severity": "serious", "channel": "电话",
                                             "detail": "客户来电（教学模拟器 · 批次投诉情景）"}, "教学模拟器")
            done["complaints"].append(cid)
            planned.remove(p)
    st["batch"] = planned
    for s, u in us.items():
        if u["health"] not in ("red", "yellow"):
            continue
        if db.one("select 1 as x from complaint where mode=%s and serial=%s and (status<>'closed' or field_day > %s)",
                  (mode, s, today - dt.timedelta(days=30))):
            continue
        if db.one("select 1 as x from service_job where mode=%s and serial=%s and status='planned'", (mode, s)):
            continue
        if u["health"] == "yellow" and _rand(s, today) > 0.15:
            continue
        subj = "；".join(u["alerts"][:2]) or ("设备异响、温度偏高" if u["health"] == "red" else "运行声音不太对")
        cid = create_complaint(H, mode, {"serial": s, "subject": "客户反映：" + subj, "severity": "urgent" if u["health"] == "red" else "normal",
                                         "channel": "电话", "detail": "客户来电（教学模拟器：现场设备健康度{}）".format("红" if u["health"] == "red" else "黄")},
                               "教学模拟器")
        done["complaints"].append(cid)
    # 2 到期的服务：工程师按计划上门完工
    for j in db.q("select id from service_job where mode=%s and status='planned' and day <= %s order by id limit 20", (mode, today)):
        try:
            complete_job(H, mode, j["id"], "教学模拟器", day=today)
            done["jobs"].append(j["id"])
        except Exception:  # noqa: BLE001
            log.exception("模拟完工出错")
    # 3 回访：到期就按“响应快慢、是否一次修好、有没有拖期”打分
    for f in db.q("select f.*, j.day as plan_day, j.done_day, j.complaint_id, j.created_at as job_created from follow_up f join service_job j on j.id=f.job_id "
                  "where f.mode=%s and f.done_at is null and f.due_day <= %s limit 20", (mode, today)):
        score = 5.0
        c = db.one("select field_day from complaint where id=%s", (f["complaint_id"],)) if f["complaint_id"] else None
        if c and c["field_day"] and f["done_day"] and (f["done_day"] - c["field_day"]).days > 3:
            score -= 1
        if f["done_day"] and f["plan_day"] and f["done_day"] > f["plan_day"]:
            score -= 1
        if db.one("select 1 as x from complaint where mode=%s and serial=%s and field_day > %s", (mode, f["serial"], f["done_day"])):
            score -= 1.5
        score -= round(_rand(f["id"], "fu") * 0.8, 1)
        score_follow_up(db, f["id"], max(1.0, round(score, 1)), "（教学模拟器回访）", "教学模拟器")
        done["follow_ups"].append(f["id"])
    # 4 线索：开着的线索少于 3 条、离上次已过 7 个现场日、真实时间至少 10 分钟 → 来一条
    last_day = dt.date.fromisoformat(st["lead_day"]) if st.get("lead_day") else None
    last_real = st.get("lead_real") or 0
    nowts = (now or dt.datetime.now(dt.timezone.utc)).timestamp()
    open_leads = sum(1 for m in db.erp_docs("Lead", mode) if m["data"].get("status") in ("Lead", "Open", "Replied", "Interested"))
    if open_leads < 3 and (last_day is None or (today - last_day).days >= 7) and nowts - last_real > 600 and H.ai is not None:
        i = int(st.get("lead_n", 0))
        name, note = LEAD_COMPANIES[i % len(LEAD_COMPANIES)]
        pid = H.ai.propose("crm_lead", {"lead_name": "采购部 · " + name, "company_name": name, "note": note + "（教学模拟器：展会 / 官网询价）"},
                           mode, "教学模拟器", "线索：" + name, source="crm")
        H.ai.decide(pid, "教学模拟器", True)
        st.update(lead_day=today.isoformat(), lead_real=nowts, lead_n=i + 1)
        done["leads"].append(name)
    _save_state(db, mode, st)
    return done


def inject_batch(H, mode, n=3):
    """老师：批次投诉情景——找同一片砂轮磨的轴所在的几台设备，给它们加“轴承早期损坏”，两天内陆续来电"""
    from hub.ont.rules.service import shaft_batch
    from hub.ont import anomaly as A
    db = H.db
    us = units(db, mode)
    b = shaft_batch(A.Ctx(db, mode), list(us))
    groups = {}
    for s, x in b.items():
        if x.get("wheel"):
            groups.setdefault(x["wheel"], []).append(s)
    if not groups:
        raise ValueError("现场设备还没有出厂追溯数据（找不到同一片砂轮的几台）")
    wheel, serials = max(groups.items(), key=lambda kv: len(kv[1]))
    serials = sorted(serials, key=lambda s: us[s]["serial"])[:n]
    today = field_today(db, mode)
    st = _state(db, mode)
    st["batch"] = [{"serial": s, "day": (today + dt.timedelta(days=i)).isoformat(), "subject": "客户反映：减速器异响，振动比以前大"}
                   for i, s in enumerate(serials)]
    _save_state(db, mode, st)
    for s in serials:
        try:
            if getattr(H, "twin", None) is None:
                raise RuntimeError("没有孪生服务")
            H.twin.set_fault(mode, s, "bearing")
        except Exception:  # noqa: BLE001
            log.exception("设故障失败")
    return {"wheel": wheel, "units": serials, "days": [p["day"] for p in st["batch"]]}


def reset(db, mode):
    """教学情景重置：投诉、服务工单、回访、通知、模拟器状态清空（工程师保留）"""
    init(db)
    for t in ("complaint", "service_job", "service_batch", "follow_up", "customer_notice", "crm_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
