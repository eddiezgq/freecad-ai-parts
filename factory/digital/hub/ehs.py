# -*- coding: utf-8 -*-
"""安全环保（第 18 轮 E2）：隐患随手拍、作业许可与资质、挂牌上锁停机、事故与未遂、培训、化学品与废弃物、教学模拟器。

- 数据全部在平台自己的表里（E2-1）；整改工单经桥接进 ERPNext（沿用服务工单的 Issue，类别“安全整改”）。
- 挂牌上锁（E2-4）：批准后经车间（MES）发 lockout，仿真车间里这台设备停下、不能复位，直到验收解锁（unlock）。
- 12 位虚拟员工和他们的培训记录（E2-3），人员领域包上线后并入员工档案。
- 风险 = 可能性 × 严重度（各 1–5）：≥15 重大、8–14 较大、其余一般（E2-7）。"""
import datetime as dt
import logging
import random
import zlib

from psycopg.types.json import Jsonb

from wqbus import UNITS

log = logging.getLogger("ehs")

SCHEMA = """
create table if not exists ehs_person (
    id     text not null,
    mode   text not null,
    name   text not null,
    post   text not null,
    team   text,
    active boolean not null default true,
    primary key (id, mode)
);
create table if not exists ehs_training (
    id           bigserial primary key,
    mode         text not null,
    person_id    text not null,
    kind         text not null,
    done_day     date not null,
    valid_months integer not null,
    note         text
);
create table if not exists hazard (
    id         text not null,
    mode       text not null,
    name       text not null,
    unit       text,
    area       text,
    likelihood integer not null,
    severity   integer not null,
    controls   jsonb not null default '[]',
    primary key (id, mode)
);
create table if not exists safety_issue (
    id          bigserial primary key,
    mode        text not null,
    unit        text,
    area        text,
    hazard_id   text,
    kind        text,
    level       text not null default 'general',          -- general 一般 / major 重大
    subject     text not null,
    photo_ids   jsonb not null default '[]',
    status      text not null default 'open',             -- open / assigned / fixed / closed
    owner       text,
    due_day     date,
    fix_minutes integer,
    found_by    text,
    found_at    timestamptz not null default now(),
    fixed_by    text,
    fixed_at    timestamptz,
    verified_by text,
    closed_at   timestamptz,
    permit_id   bigint,
    note        text
);
create index if not exists safety_issue_mode on safety_issue (mode, status);
create table if not exists work_permit (
    id          bigserial primary key,
    mode        text not null,
    kind        text not null,                            -- hot 动火 / height 高处 / confined 受限空间 / loto 挂牌上锁
    unit        text,
    holder_id   text,
    status      text not null default 'requested',        -- requested / blocked / active / closed / rejected
    minutes     integer,
    delay_minutes integer,
    reason      text,
    issue_id    bigint,
    requested_by text,
    approver    text,
    closed_by   text,
    valid_from  timestamptz,
    valid_to    timestamptz,
    closed_at   timestamptz,
    created_at  timestamptz not null default now(),
    block_reason text
);
create table if not exists incident (
    id          bigserial primary key,
    mode        text not null,
    kind        text not null,                            -- near_miss 未遂 / injury 受伤 / property 财产损失 / env 环境
    severity    text not null default 'minor',
    unit        text,
    day         date not null,
    description text,
    root_cause  text,
    actions     jsonb not null default '[]',
    created_by  text,
    created_at  timestamptz not null default now()
);
create table if not exists chemical (
    code     text not null,
    mode     text not null,
    name     text not null,
    stock_kg numeric not null,
    min_kg   numeric not null,
    max_kg   numeric not null,
    sds      text,
    primary key (code, mode)
);
create table if not exists waste (
    id            bigserial primary key,
    mode          text not null,
    kind          text not null,
    qty_kg        numeric not null,
    produced_day  date not null,
    disposed_day  date,
    disposed_by   text,
    hazardous     boolean not null default true
);
create table if not exists ehs_sim (
    mode  text primary key,
    state jsonb not null default '{}'
);
"""

PEOPLE = [("P01", "王强", "操作工", "机加一班"), ("P02", "李娜", "操作工", "机加一班"), ("P03", "张伟", "操作工", "机加二班"),
          ("P04", "刘洋", "操作工", "机加二班"), ("P05", "陈静", "操作工", "热处理"), ("P06", "赵刚", "维修工", "设备组"),
          ("P07", "孙磊", "维修工", "设备组"), ("P08", "周敏", "维修工", "设备组"), ("P09", "吴平", "安全员", "安环部"),
          ("P10", "郑红", "安全员", "安环部"), ("P11", "钱进", "班组长", "机加一班"), ("P12", "冯涛", "班组长", "机加二班")]
TRAININGS = {"induction": ("入厂三级安全教育", 36), "hot": ("动火作业", 12), "height": ("高处作业", 12), "confined": ("受限空间作业", 12),
             "loto": ("挂牌上锁", 24), "forklift": ("叉车", 24)}
PERMITS = {"hot": "动火", "height": "高处", "confined": "受限空间", "loto": "挂牌上锁"}
PERMIT_TRAINING = {"hot": "hot", "height": "height", "confined": "confined", "loto": "loto"}
HAZARDS = [("HZ-01", "砂轮破裂飞出", "grd-01", 2, 5, ["砂轮防护罩", "开机前空转 1 分钟", "核对砂轮线速度"]),
           ("HZ-02", "磨削粉尘", "grd-01", 3, 2, ["吸尘装置", "戴防尘口罩"]),
           ("HZ-03", "卡盘夹伤", "cnc-l01-a", 2, 4, ["防护门联锁", "装夹时停主轴"]),
           ("HZ-04", "切屑飞溅", "cnc-l01-b", 3, 3, ["防护门", "戴防护眼镜"]),
           ("HZ-05", "高温烫伤", "ht-01", 3, 4, ["隔热手套", "出炉区警示线"]),
           ("HZ-06", "淬火油着火", "ht-01", 2, 5, ["油温联锁", "灭火毯和干粉灭火器"]),
           ("HZ-07", "炉膛检修（受限空间）", "ht-01", 2, 5, ["受限空间作业许可", "气体检测", "专人监护"]),
           ("HZ-08", "锯条断裂", "saw-01", 2, 3, ["锯条张紧检查", "防护罩"]),
           ("HZ-09", "铣刀卷入", "key-01", 2, 4, ["不戴手套操作", "扎紧袖口"]),
           ("HZ-10", "齿轮啮合区夹伤", "hob-01", 2, 4, ["防护门联锁"]),
           ("HZ-11", "AGV 碰撞", "agv-01", 2, 3, ["激光避障", "地面通道标线"]),
           ("HZ-12", "压装工位挤压", "press-01", 2, 4, ["双手按钮", "光幕"])]
# 隐患种类：名称、默认等级、整改标准工时（分钟）——处理方案里估停机时长用
ISSUE_KINDS = {"guard": ("防护罩松动 / 缺失", "major", 120), "estop": ("急停按钮失灵", "major", 90), "wiring": ("电线破损裸露", "major", 60),
               "interlock": ("防护门联锁失效", "major", 90), "oil_leak": ("地面漏油", "general", 30), "chips": ("地面切屑堆积", "general", 20),
               "extinguisher": ("灭火器过期 / 缺失", "general", 20), "label": ("安全标识缺失", "general", 15), "ppe": ("没戴防护眼镜", "general", 10),
               "other": ("其他", "general", 30)}
CHEMICALS = [("CL-01", "乳化切削液", 180, 50, 400, "SDS-CL-01：避免长期皮肤接触；废液按危险废物处置"),
             ("QO-01", "淬火油", 600, 200, 1000, "SDS-QO-01：闪点 > 200 ℃；远离明火"),
             ("LO-01", "导轨润滑油", 90, 40, 200, "SDS-LO-01：一般化学品")]
WASTES = {"coolant": ("废切削液", True), "oil": ("废油", True), "rags": ("含油抹布、手套", True), "chips": ("钢屑", False)}
LEVEL = {"general": "一般", "major": "重大"}
STATUS = {"open": "待指派", "assigned": "整改中", "fixed": "待验收", "closed": "已关闭"}
PERMIT_STATUS = {"requested": "待批准", "blocked": "缺资质", "active": "作业中", "closed": "已关闭", "rejected": "已驳回", "planned": "已批准，待开始"}
INCIDENT_KINDS = {"near_miss": "未遂", "injury": "受伤", "property": "财产损失", "env": "环境事件"}
WASTE_LIMIT_DAYS = 90


def init(db):
    if getattr(db, "_ehs_ready", False):
        return
    db.x(SCHEMA)
    try:
        db._ehs_ready = True
    except AttributeError:
        pass


def today():
    from hub import kpi
    return dt.datetime.now(kpi.TZ).date()


def seed(db, mode):
    """虚拟员工、培训记录、危险源、化学品、一条旧的危险废物（教学数据；已有就不动）"""
    init(db)
    if db.one("select 1 as x from ehs_person where mode=%s limit 1", (mode,)):
        return False
    d0 = today()
    for pid, name, post, team in PEOPLE:
        db.x("insert into ehs_person (id, mode, name, post, team) values (%s,%s,%s,%s,%s) on conflict do nothing", (pid, mode, name, post, team))
        kinds = ["induction"] + {"操作工": ["forklift"] if pid in ("P03", "P04") else [], "维修工": ["hot", "height", "confined", "loto"],
                                 "安全员": ["hot", "height", "confined", "loto"], "班组长": ["loto"]}[post]
        for i, k in enumerate(kinds):
            months = TRAININGS[k][1]
            age = (int(zlib.crc32((pid + k).encode())) % (months * 20)) + 30          # 已经过去的天数，大多还在有效期内
            if pid == "P07" and k == "confined":
                age = months * 30 + 10                                          # 故事二：孙磊的受限空间作业已过期 10 天
            if pid == "P08" and k == "hot":
                age = months * 30 - 20                                          # 周敏的动火作业 20 天后到期
            if pid == "P05" and k == "induction":
                age = months * 30 - 12
            db.x("insert into ehs_training (mode, person_id, kind, done_day, valid_months) values (%s,%s,%s,%s,%s)",
                 (mode, pid, k, d0 - dt.timedelta(days=age), months))
    for hid, name, unit, li, se, ctl in HAZARDS:
        db.x("insert into hazard (id, mode, name, unit, area, likelihood, severity, controls) values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
             (hid, mode, name, unit, UNITS.get(unit, ("", unit))[1], li, se, Jsonb(ctl)))
    for code, name, stock, lo, hi, sds in CHEMICALS:
        db.x("insert into chemical (code, mode, name, stock_kg, min_kg, max_kg, sds) values (%s,%s,%s,%s,%s,%s,%s) on conflict do nothing",
             (code, mode, name, stock, lo, hi, sds))
    db.x("insert into waste (mode, kind, qty_kg, produced_day, hazardous) values (%s,'coolant',120,%s,true), (%s,'rags',15,%s,true), "
         "(%s,'chips',300,%s,false)", (mode, d0 - dt.timedelta(days=WASTE_LIMIT_DAYS + 2), mode, d0 - dt.timedelta(days=20), mode, d0 - dt.timedelta(days=5)))
    return True


def reset(db, mode):
    init(db)
    for t in ("ehs_person", "ehs_training", "hazard", "safety_issue", "work_permit", "incident", "chemical", "waste", "ehs_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    seed(db, mode)


# ---------------------------------------------------------------- 风险、人员、资质
def risk(likelihood, severity):
    li, se = int(likelihood), int(severity)
    if not (1 <= li <= 5 and 1 <= se <= 5):
        raise ValueError("可能性、严重度都是 1–5 分")
    s = li * se
    lv = "重大" if s >= 15 else ("较大" if s >= 8 else "一般")
    return {"likelihood": li, "severity": se, "score": s, "level": lv}


def people(db, mode):
    seed(db, mode)
    rows = db.q("select * from ehs_person where mode=%s and active order by id", (mode,))
    tr = trainings(db, mode)
    out = []
    for p in rows:
        mine = [t for t in tr if t["person_id"] == p["id"]]
        out.append(dict(p, trainings=mine, expired=[t["kind"] for t in mine if t["days_left"] < 0],
                        expiring=[t["kind"] for t in mine if 0 <= t["days_left"] <= 30]))
    return out


def _add_months(d, m):
    y, mm = divmod(d.month - 1 + m, 12)
    return dt.date(d.year + y, mm + 1, min(d.day, 28))


def trainings(db, mode, on=None):
    """每人每类只取最新一次"""
    init(db)
    on = on or today()
    rows = db.q("select distinct on (person_id, kind) * from ehs_training where mode=%s order by person_id, kind, done_day desc", (mode,))
    out = []
    for r in rows:
        until = _add_months(r["done_day"], r["valid_months"])
        out.append({"id": r["id"], "person_id": r["person_id"], "kind": r["kind"], "label": TRAININGS.get(r["kind"], (r["kind"],))[0],
                    "done_day": r["done_day"].isoformat(), "valid_until": until.isoformat(), "days_left": (until - on).days})
    return out


def qualified(db, mode, person_id, permit_kind, on=None):
    """(能否, 原因)：作业许可要求的培训在有效期内"""
    need = PERMIT_TRAINING.get(permit_kind)
    p = db.one("select * from ehs_person where id=%s and mode=%s", (person_id, mode))
    if p is None:
        return False, "没有这个人：{}".format(person_id)
    if not need:
        return True, ""
    t = next((x for x in trainings(db, mode, on) if x["person_id"] == person_id and x["kind"] == need), None)
    if t is None:
        return False, "{}没有“{}”培训记录".format(p["name"], TRAININGS[need][0])
    if t["days_left"] < 0:
        return False, "{}的“{}”培训 {} 已过期".format(p["name"], TRAININGS[need][0], t["valid_until"])
    return True, ""


def qualified_people(db, mode, permit_kind):
    return [p for p in people(db, mode) if qualified(db, mode, p["id"], permit_kind)[0]]


# ---------------------------------------------------------------- 隐患
def create_issue(H, mode, body, who):
    db = H.db
    seed(db, mode)
    unit = (body.get("unit") or "").strip() or None
    if unit and unit not in UNITS:
        raise ValueError("没有这台设备：" + unit)
    kind = body.get("kind") or "other"
    if kind not in ISSUE_KINDS:
        raise ValueError("隐患种类不对")
    subject = (body.get("subject") or "").strip() or ISSUE_KINDS[kind][0]
    level = body.get("level") or ISSUE_KINDS[kind][1]
    if level not in LEVEL:
        raise ValueError("等级只能是一般或重大")
    due = today() + dt.timedelta(days=1 if level == "major" else 7)
    r = db.one("insert into safety_issue (mode, unit, area, hazard_id, kind, level, subject, photo_ids, found_by, due_day, fix_minutes) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, unit, body.get("area") or (UNITS[unit][1] if unit else None), body.get("hazard_id"), kind, level, subject[:200],
                Jsonb(body.get("photo_ids") or []), who, due, int(body.get("fix_minutes") or ISSUE_KINDS[kind][2])))
    return r["id"]


def issue_row(r):
    return {"id": r["id"], "key": "SI-{:05d}".format(r["id"]), "unit": r["unit"], "unit_name": UNITS[r["unit"]][1] if r["unit"] in UNITS else None,
            "area": r["area"], "hazard_id": r["hazard_id"], "kind": r["kind"], "kind_label": ISSUE_KINDS.get(r["kind"], ("其他",))[0],
            "level": r["level"], "level_label": LEVEL[r["level"]], "subject": r["subject"], "photo_ids": r["photo_ids"] or [],
            "status": r["status"], "status_label": STATUS[r["status"]], "owner": r["owner"], "due_day": r["due_day"].isoformat() if r["due_day"] else None,
            "overdue": bool(r["due_day"] and r["status"] != "closed" and r["due_day"] < today()), "fix_minutes": r["fix_minutes"],
            "found_by": r["found_by"], "found_at": r["found_at"].isoformat(), "fixed_by": r["fixed_by"],
            "fixed_at": r["fixed_at"].isoformat() if r["fixed_at"] else None, "verified_by": r["verified_by"],
            "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None, "permit_id": r["permit_id"], "note": r["note"]}


def assign(db, iid, owner, due=None, who=None):
    r = db.one("select * from safety_issue where id=%s", (iid,))
    if r is None:
        raise KeyError(iid)
    if r["status"] == "closed":
        raise ValueError("隐患已关闭")
    db.x("update safety_issue set owner=%s, due_day=coalesce(%s, due_day), status=case when status='open' then 'assigned' else status end, "
         "note=coalesce(note,'') || %s where id=%s", (owner, due, "{} 指派给 {}；".format(who or "", owner), iid))


def fix(db, iid, who, note=""):
    r = db.one("select * from safety_issue where id=%s", (iid,))
    if r is None:
        raise KeyError(iid)
    if r["status"] in ("fixed", "closed"):
        raise ValueError("这条隐患已经{}".format(STATUS[r["status"]]))
    db.x("update safety_issue set status='fixed', fixed_by=%s, fixed_at=now(), note=coalesce(note,'') || %s where id=%s",
         (who, "整改完成：{}；".format(note) if note else "整改完成；", iid))


def verify(H, mode, iid, who):
    """验收关闭：不能是整改人自己；挂着锁的，验收同时解锁（关闭许可、设备恢复）"""
    db = H.db
    r = db.one("select * from safety_issue where id=%s and mode=%s", (iid, mode))
    if r is None:
        raise KeyError(iid)
    if r["status"] != "fixed":
        raise ValueError("先整改完成，再验收")
    if r["fixed_by"] and r["fixed_by"] == who:
        raise PermissionError("整改人不能验收自己的整改")
    db.x("update safety_issue set status='closed', verified_by=%s, closed_at=now() where id=%s", (who, iid))
    out = {"closed": "SI-{:05d}".format(iid)}
    p = db.one("select * from work_permit where issue_id=%s and kind='loto' and status in ('active','planned') order by id desc limit 1", (iid,))
    if p:
        out["unlock"] = close_permit(H, mode, p["id"], who)
    return out


# ---------------------------------------------------------------- 作业许可
def request_permit(db, mode, body, who):
    seed(db, mode)
    kind = body.get("kind")
    if kind not in PERMITS:
        raise ValueError("作业种类只能是动火 / 高处 / 受限空间 / 挂牌上锁")
    unit = body.get("unit") or None
    if unit and unit not in UNITS:
        raise ValueError("没有这台设备：" + unit)
    holder = body.get("holder_id")
    ok, why = qualified(db, mode, holder, kind)
    r = db.one("insert into work_permit (mode, kind, unit, holder_id, status, minutes, delay_minutes, reason, issue_id, requested_by, block_reason) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, kind, unit, holder, "requested" if ok else "blocked", int(body.get("minutes") or 120), int(body.get("delay_minutes") or 0),
                (body.get("reason") or "")[:300], body.get("issue_id"), who, None if ok else why))
    return {"id": r["id"], "key": "PTW-{:05d}".format(r["id"]), "status": "requested" if ok else "blocked", "why": why}


def approve_permit(H, mode, pid, who):
    db = H.db
    p = db.one("select * from work_permit where id=%s and mode=%s", (pid, mode))
    if p is None:
        raise KeyError(pid)
    if p["status"] not in ("requested", "blocked"):
        raise ValueError("这张许可已经{}".format(PERMIT_STATUS[p["status"]]))
    ok, why = qualified(db, mode, p["holder_id"], p["kind"])
    if not ok:
        db.x("update work_permit set status='blocked', block_reason=%s where id=%s", (why, pid))
        raise PermissionError("不能批：" + why + "。先安排复训，或换有资质的人")
    db.x("update work_permit set status='active', approver=%s, valid_from=now() where id=%s", (who, pid))
    if p["kind"] == "loto" and p["unit"]:
        _send(H, mode, p["unit"], "lockout", who, permit="PTW-{:05d}".format(pid), minutes=p["minutes"] or 120,
              delay_minutes=p["delay_minutes"] or 0, reason=p["reason"] or "整改")
        if p["issue_id"]:
            db.x("update safety_issue set permit_id=%s, status=case when status='open' then 'assigned' else status end where id=%s", (pid, p["issue_id"]))
    return {"id": pid, "key": "PTW-{:05d}".format(pid), "status": "active"}


def close_permit(H, mode, pid, who):
    """关闭许可；挂牌上锁的：解锁、设备恢复（申请人不能自己解锁）"""
    db = H.db
    p = db.one("select * from work_permit where id=%s and mode=%s", (pid, mode))
    if p is None:
        raise KeyError(pid)
    if p["status"] not in ("active", "planned"):
        raise ValueError("这张许可不在作业中")
    if p["kind"] == "loto" and p["requested_by"] and p["requested_by"] == who and not who.startswith("教学模拟器"):
        raise PermissionError("挂牌上锁要另一个人验收后解锁，申请人不能自己解锁")
    db.x("update work_permit set status='closed', closed_by=%s, closed_at=now(), valid_to=now() where id=%s", (who, pid))
    if p["kind"] == "loto" and p["unit"]:
        _send(H, mode, p["unit"], "unlock", who)
    return {"id": pid, "key": "PTW-{:05d}".format(pid), "status": "closed"}


def _send(H, mode, unit, cmd, who, **extra):
    mes = getattr(H, "mes", None)
    if mes is None:
        log.warning("没有车间连接，%s %s 只记录", cmd, unit)
        return
    mes.command(unit, cmd, mode, who, **extra)


def permit_row(db, r, names=None):
    names = names if names is not None else {p["id"]: p["name"] for p in db.q("select id, name from ehs_person where mode=%s", (r["mode"],))}
    return {"id": r["id"], "key": "PTW-{:05d}".format(r["id"]), "kind": r["kind"], "kind_label": PERMITS[r["kind"]], "unit": r["unit"],
            "holder_id": r["holder_id"], "holder": names.get(r["holder_id"]), "status": r["status"], "status_label": PERMIT_STATUS[r["status"]],
            "minutes": r["minutes"], "delay_minutes": r["delay_minutes"], "reason": r["reason"], "issue_id": r["issue_id"],
            "requested_by": r["requested_by"], "approver": r["approver"], "closed_by": r["closed_by"], "block_reason": r["block_reason"],
            "valid_from": r["valid_from"].isoformat() if r["valid_from"] else None, "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
            "created_at": r["created_at"].isoformat()}


def active_locks(db, mode):
    init(db)
    return db.q("select * from work_permit where mode=%s and kind='loto' and status='active' order by id", (mode,))


# ---------------------------------------------------------------- 事故、化学品、废弃物
def create_incident(db, mode, body, who):
    init(db)
    kind = body.get("kind") or "near_miss"
    if kind not in INCIDENT_KINDS:
        raise ValueError("种类只能是未遂 / 受伤 / 财产损失 / 环境事件")
    r = db.one("insert into incident (mode, kind, severity, unit, day, description, root_cause, actions, created_by) "
               "values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, kind, body.get("severity") or "minor", body.get("unit"), body.get("day") or today(), (body.get("description") or "")[:2000],
                (body.get("root_cause") or "")[:1000] or None, Jsonb(body.get("actions") or []), who))
    return r["id"]


def chemicals(db, mode):
    seed(db, mode)
    return [dict(r, stock_kg=float(r["stock_kg"]), min_kg=float(r["min_kg"]), max_kg=float(r["max_kg"]))
            for r in db.q("select * from chemical where mode=%s order by code", (mode,))]


def wastes(db, mode):
    seed(db, mode)
    d0 = today()
    out = []
    for r in db.q("select * from waste where mode=%s order by produced_day desc, id desc limit 200", (mode,)):
        age = ((r["disposed_day"] or d0) - r["produced_day"]).days
        out.append({"id": r["id"], "kind": r["kind"], "label": WASTES.get(r["kind"], (r["kind"],))[0], "qty_kg": float(r["qty_kg"]),
                    "produced_day": r["produced_day"].isoformat(), "disposed_day": r["disposed_day"].isoformat() if r["disposed_day"] else None,
                    "disposed_by": r["disposed_by"], "hazardous": r["hazardous"], "age_days": age,
                    "over_limit": bool(r["hazardous"] and not r["disposed_day"] and age > WASTE_LIMIT_DAYS)})
    return out


def dispose(db, mode, wid, by):
    r = db.one("select * from waste where id=%s and mode=%s", (wid, mode))
    if r is None:
        raise KeyError(wid)
    if r["disposed_day"]:
        raise ValueError("已经处置过了")
    if not (by or "").strip():
        raise ValueError("填处置单位（有资质的危废处置公司）")
    db.x("update waste set disposed_day=%s, disposed_by=%s where id=%s", (today(), by.strip()[:100], wid))


# ---------------------------------------------------------------- 处理方案（E2-6）：重大隐患 → 车间推演
def fix_minutes_of(db, a):
    v = (a.get("detail") or {}).get("values") or {}
    if v.get("fix_minutes"):
        return int(v["fix_minutes"])
    iid = v.get("issue_id")
    r = db.one("select fix_minutes, kind from safety_issue where id=%s", (iid,)) if iid else None
    return int((r or {}).get("fix_minutes") or 120)


def options(db, mode, a, snap, ctx, params=None):
    """不处理（对照，安全规定不允许）/ 立即停机挂牌整改 / 限时整改（临时措施，延后停机）/ 停机整改 + 改派或加班。各推演一遍"""
    from hub.ont import plan as P
    from hub.ont import playbook as PB
    from sim.calendar import Calendar
    prm = dict({"temp_hours": 4, "temp_cost": 150}, **(params or {}))
    v = (a.get("detail") or {}).get("values") or {}
    unit = a["subject_key"] if a.get("subject_type") == "Machine" else v.get("unit")
    if not unit or unit not in (snap.get("machines") or {}):
        return {"options": [], "affected": [], "reason": "这条隐患没有关联到车间设备，按隐患整改流程处理", "recommended": None}
    mins = fix_minutes_of(db, a)
    iid = v.get("issue_id")
    lock = {"type": "lockout", "unit": unit, "minutes": mins, "issue_id": iid, "reason": v.get("subject") or "安全整改"}
    cal = Calendar.from_dict(snap.get("calendar"))
    delay = int(prm["temp_hours"]) * 60
    if cal.mode == "shift":                          # 按班次：下班后再停
        now = dt.datetime.fromisoformat(snap["factory_now"]).astimezone(cal.tzi)
        w = cal.window("*", now.date())
        if w and now.hour * 60 + now.minute < w[1]:
            delay = max(10, w[1] - (now.hour * 60 + now.minute))
    plans = [("none", "不处理（对照）", [], "带着重大隐患继续生产：安全规定不允许，只作对照"),
             ("lockout", "立即停机挂牌整改", [lock], "挂牌上锁，整改约 {} 分钟（按隐患种类的标准工时），验收后解锁".format(mins)),
             ("temp", "限时整改：临时防护，{:.0f} 分钟后停机".format(delay), [dict(lock, delay_minutes=delay, temp_cost=prm["temp_cost"])],
              "先加临时防护、降速、专人看守，{:.0f} 分钟后（{}）停机整改".format(delay, "下班后" if cal.mode == "shift" else "这一批做完")),
             ]
    extra = []
    stub = dict(a, rule="P1", subject_type="Machine", subject_key=unit)
    for o in PB.build(stub, P.hypothesis(snap, unit, mins, "挂牌上锁（推演）"), ctx):
        if o["kind"] in ("reassign", "overtime"):
            extra += o["changes"]
    if extra:
        plans.append(("lockout_plus", "停机整改 + " + "、".join(sorted({PB.LABELS[c["type"]] if c["type"] in PB.LABELS else P.CHANGE_TYPES[c["type"]]
                                                                      for c in extra})), [lock] + extra,
                      "停机整改，同时把能改派的工序改到同类设备 / 加班补回"))
    names = PB.affected(stub, ctx)
    out = []
    for i, (kind, label, changes, note) in enumerate(plans):
        r = P.simulate(snap, changes, ctx)
        rows = [s for s in r["sales_orders"] if s["name"] in names]
        lates = [s["late_days"] for s in rows if s["late_days"] is not None]
        checks = list(r["checks"])
        if kind == "none":
            checks.append({"ok": False, "text": "重大隐患不能带着生产（安全规定），只作对照"})
        res = {"sales_orders": rows, "cost_total": r["cost_total"], "costs": r["costs"], "overtime_min": r["overtime_min"],
               "overtime_units": r["overtime_units"], "checks": checks, "ok": r["ok"] and kind != "none"}
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "changes": changes, "result": res,
                    "worst_late": max(lates) if lates else None, "undetermined": len(lates) < len(rows)})

    def score(o):
        wl = o["worst_late"] if o["worst_late"] is not None else 99
        risk_rank = {"lockout": 0, "lockout_plus": 0, "temp": 1, "none": 9}[o["kind"]]
        return (0 if o["result"]["ok"] else 1, 1 if o["undetermined"] else 0, max(wl, 0), risk_rank, o["result"]["cost_total"])
    best = min(out, key=score)
    for o in out:
        o["recommended"] = o is best
    so_txt = "；".join("{} {}".format(s["name"], "按时（余 {} 天）".format(-s["late_days"]) if s["late_days"] is not None and s["late_days"] <= 0
                                    else "晚 {} 天".format(s["late_days"]) if s["late_days"] is not None else "推演范围内做不完")
                       for s in best["result"]["sales_orders"]) or "没有受影响的订单"
    reason = "建议 {} {}：{}，多花 ${:,.0f}。重大隐患先保安全，再比交期和成本。".format(best["key"], best["label"], so_txt, best["result"]["cost_total"])
    return {"options": out, "affected": names, "reason": reason, "recommended": best["key"], "fix_minutes": mins, "unit": unit}


# ---------------------------------------------------------------- 动作执行（actions.py 调）
def exec_lockout(H, mode, p, u):
    """开挂牌上锁许可（持证人：有挂牌上锁资质的维修工）并发给车间"""
    db = H.db
    seed(db, mode)
    holder = p.get("holder_id")
    if not holder or not qualified(db, mode, holder, "loto")[0]:
        cands = [x for x in qualified_people(db, mode, "loto") if x["post"] == "维修工"] or qualified_people(db, mode, "loto")
        try:                                             # 第 18 轮 E4：优先这一班在岗的
            from hub import people as PE
            on = PE.on_shift_ids(db, mode)
            cands = [x for x in cands if x["id"] in on] + [x for x in cands if x["id"] not in on]
        except Exception:  # noqa: BLE001
            pass
        if not cands:
            raise ValueError("没有挂牌上锁资质在有效期内的人")
        holder = cands[0]["id"]
    r = request_permit(db, mode, {"kind": "loto", "unit": p["unit"], "holder_id": holder, "minutes": p.get("minutes") or 120,
                                  "delay_minutes": p.get("delay_minutes") or 0, "reason": p.get("reason") or "安全整改", "issue_id": p.get("issue_id")},
                       u.get("name"))
    approve_permit(H, mode, r["id"], u.get("name"))
    if p.get("issue_id"):
        db.x("update safety_issue set owner=coalesce(owner, %s), status=case when status='open' then 'assigned' else status end where id=%s",
             (holder, int(p["issue_id"])))
    name = db.one("select name from ehs_person where id=%s and mode=%s", (holder, mode))["name"]
    when = "{} 分钟后".format(p["delay_minutes"]) if p.get("delay_minutes") else "立即"
    return {"text": "已开挂牌上锁许可 {}（持证人 {}），{}停 {}，整改约 {} 分钟".format(r["key"], name, when, p["unit"].upper(), p.get("minutes") or 120),
            "permit": r["key"], "permit_id": r["id"]}


def exec_rectify(H, mode, p, u):
    """整改工单：经桥接在 ERPNext 开 Issue（类别“安全整改”）"""
    unit = p.get("unit") or ""
    o = {"subject": "【安全整改】{} {}".format(unit.upper(), p.get("subject") or "")[:140], "serial": unit, "customer": "",
         "engineer": p.get("owner") or "", "day": p.get("day") or today().isoformat(), "kind": "安全整改 safety",
         "description": "隐患 SI-{:05d}：{}。整改约 {} 分钟。".format(int(p.get("issue_id") or 0), p.get("subject") or "", p.get("minutes") or "")}
    pid = H.ai.propose("service_orders", {"orders": [o]}, mode, u.get("name"), "安全整改工单 " + unit.upper(), source="ehs")
    H.ai.decide(pid, u.get("name"), True)
    return {"text": "已交 ERPNext 开整改工单（提议 {}）".format(pid), "proposal_id": pid}


def exec_unlock(H, mode, p, u):
    db = H.db
    pid = p.get("permit_id")
    if not pid:
        r = db.one("select id from work_permit where mode=%s and kind='loto' and status='active' and unit=%s order by id desc limit 1", (mode, p.get("unit")))
        pid = r["id"] if r else None
    if not pid:
        raise ValueError("这台设备没有挂着的锁")
    r = close_permit(H, mode, int(pid), u.get("name"))
    return {"text": "已验收解锁 {}，{} 恢复".format(r["key"], (p.get("unit") or "").upper())}


def exec_training(H, mode, p, u):
    db = H.db
    kind = p.get("kind")
    if kind not in TRAININGS:
        raise ValueError("培训种类不对")
    day = p.get("day") or today().isoformat()
    ids = list(p.get("people") or [])
    for pid in ids:
        db.x("insert into ehs_training (mode, person_id, kind, done_day, valid_months, note) values (%s,%s,%s,%s,%s,%s)",
             (mode, pid, kind, day, TRAININGS[kind][1], "安排培训（{}）".format(u.get("name"))))
    return {"text": "已安排“{}”培训 {} 人（{}），有效期更新".format(TRAININGS[kind][0], len(ids), day)}


# ---------------------------------------------------------------- 态势
def kpis(db, mode):
    seed(db, mode)
    d0 = today()
    oi = db.one("select count(*) as n, count(*) filter (where level='major') as m, count(*) filter (where due_day < %s) as od "
                "from safety_issue where mode=%s and status<>'closed'", (d0, mode))
    cl = db.q("select due_day, closed_at from safety_issue where mode=%s and status='closed' and closed_at > now() - interval '30 days'", (mode,))
    from hub import kpi
    ontime = [1 if r["closed_at"].astimezone(kpi.TZ).date() <= r["due_day"] else 0 for r in cl if r["due_day"]]
    tr = trainings(db, mode)
    inc = db.one("select count(*) as n, count(*) filter (where kind='near_miss') as nm from incident where mode=%s and day > %s",
                 (mode, d0 - dt.timedelta(days=30)))
    return {"open_issues": oi["n"], "major_open": oi["m"], "overdue": oi["od"], "on_time": round(sum(ontime) / len(ontime), 3) if ontime else None,
            "locked": len(active_locks(db, mode)), "training_due": sum(1 for t in tr if t["days_left"] <= 30),
            "training_expired": sum(1 for t in tr if t["days_left"] < 0), "incidents_30d": inc["n"], "near_miss_30d": inc["nm"],
            "waste_over": sum(1 for w in wastes(db, mode) if w["over_limit"])}


# ---------------------------------------------------------------- 教学模拟器（E2-8）
def _state(db, mode):
    init(db)
    r = db.one("select state from ehs_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _save_state(db, mode, st):
    db.x("insert into ehs_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


GENERAL_UNITS = ["grd-01", "cnc-l01-a", "cnc-l01-b", "saw-01", "key-01", "ht-01", "hob-01", "press-01"]


def tick(H, mode, now=None, rng=None):
    """教学模式每轮（约 20 秒）跑一次：偶尔来一条一般隐患、很少来一条未遂、按车间运转消耗化学品和产生废物"""
    if mode != "teach":
        return {}
    db = H.db
    seed(db, mode)
    rng = rng or random.Random()
    now = now or dt.datetime.now(dt.timezone.utc)
    st = _state(db, mode)
    last = st.get("last") or 0
    done = {"issues": [], "incidents": []}
    ts = now.timestamp()
    if ts - last < 60:                      # 至少隔一分钟（真实时间）
        return done
    st["last"] = ts
    n_open = db.one("select count(*) as n from safety_issue where mode=%s and status<>'closed' and found_by='教学模拟器'", (mode,))["n"]
    if n_open < 6 and rng.random() < 0.12:
        kind = rng.choice(["oil_leak", "chips", "extinguisher", "label", "ppe", "oil_leak", "chips"])
        unit = rng.choice(GENERAL_UNITS)
        iid = create_issue(H, mode, {"unit": unit, "kind": kind, "subject": "{}（{}）".format(ISSUE_KINDS[kind][0], UNITS[unit][1])}, "教学模拟器")
        done["issues"].append(iid)
    if rng.random() < 0.015:
        unit = rng.choice(GENERAL_UNITS)
        iid = create_incident(db, mode, {"kind": "near_miss", "unit": unit, "description": "{} 附近切屑飞溅，擦过操作工的工作服，没有受伤".format(UNITS[unit][1])},
                              "教学模拟器")
        done["incidents"].append(iid)
    # 挂着锁的整改：持证的维修工做完（真实时间按整改分钟 / 30 算，至少 1 分钟）→ 待验收
    for r in db.q("select i.id, p.holder_id, p.minutes, p.delay_minutes, p.valid_from, e.name from safety_issue i "
                  "join work_permit p on p.id=i.permit_id left join ehs_person e on e.id=p.holder_id and e.mode=p.mode "
                  "where i.mode=%s and i.status in ('open','assigned') and p.status='active'", (mode,)):
        need = max(60.0, ((r["minutes"] or 120) + (r["delay_minutes"] or 0)) * 60 / 30)
        if r["valid_from"] and (now - r["valid_from"]).total_seconds() >= need:
            fix(db, r["id"], "{}（维修工）".format(r["name"] or r["holder_id"]), "按标准整改完成（教学模拟器）")
            done.setdefault("fixed", []).append(r["id"])
    # 化学品与废物：按车间在跑的设备数
    try:
        from hub import kpi
        running = sum(1 for m in kpi.overview(db, None, mode)["machines"] if m.get("state") == "run")
    except Exception:  # noqa: BLE001
        running = 0
    if running:
        db.x("update chemical set stock_kg=greatest(0, stock_kg - %s) where mode=%s and code='CL-01'", (0.2 * running, mode))
        db.x("update chemical set stock_kg=greatest(0, stock_kg - %s) where mode=%s and code='LO-01'", (0.05 * running, mode))
        d0 = today()
        r = db.one("select id from waste where mode=%s and kind='chips' and produced_day=%s and disposed_day is null", (mode, d0))
        if r:
            db.x("update waste set qty_kg=qty_kg + %s where id=%s", (0.8 * running, r["id"]))
        else:
            db.x("insert into waste (mode, kind, qty_kg, produced_day, hazardous) values (%s,'chips',%s,%s,false)", (mode, 0.8 * running, d0))
    _save_state(db, mode, st)
    return done


def inject_major(H, mode, unit="grd-01", kind="guard", who="老师"):
    if unit not in UNITS:
        raise ValueError("没有这台设备：" + unit)
    if ISSUE_KINDS.get(kind, ("", ""))[1] != "major":
        kind = "guard"
    return create_issue(H, mode, {"unit": unit, "kind": kind, "level": "major",
                                  "subject": "{}：{}（{}）".format(UNITS[unit][1], ISSUE_KINDS[kind][0], "教学情景")}, who)


def inject_bypass(H, mode, unit, who="老师"):
    """教学情景：有人没走许可就把锁拆了（许可还开着）→ 设备恢复运转 → 规则 E5"""
    if not db_one_lock(H.db, mode, unit):
        raise ValueError("{} 没有挂着的锁".format(unit.upper()))
    _send(H, mode, unit, "unlock", who)
    return {"text": "已模拟违规拆锁：{} 恢复运转，但许可没有关闭".format(unit.upper())}


def db_one_lock(db, mode, unit):
    return db.one("select * from work_permit where mode=%s and kind='loto' and status='active' and unit=%s limit 1", (mode, unit))


def permit_options(db, mode, a):
    """E3 作业许可缺资质：安排复训 / 换有资质的人（不进车间推演）"""
    v = (a.get("detail") or {}).get("values") or {}
    kind, holder = v.get("kind"), v.get("holder_id")
    need = PERMIT_TRAINING.get(kind)
    alts = [p for p in qualified_people(db, mode, kind) if p["id"] != holder]
    out = []
    if need and holder:
        out.append({"key": "A", "kind": "retrain", "label": "先安排复训（{}）".format(TRAININGS[need][0]),
                    "note": "复训完成后再申请；作业要往后推", "changes": [{"type": "training_plan", "kind": need, "people": [holder], "day": today().isoformat()}],
                    "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True}})
    out.append({"key": chr(ord("A") + len(out)), "kind": "swap", "label": "换有资质的人",
                "note": "有资质的：" + ("、".join(p["name"] for p in alts[:6]) or "没有"), "changes": [],
                "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": bool(alts)}})
    best = out[-1] if alts else out[0]
    for o in out:
        o["recommended"] = o is best
    return {"options": out, "affected": [], "recommended": best["key"],
            "reason": "建议 {} {}：{}".format(best["key"], best["label"], "作业不用等" if best["kind"] == "swap" else "没有别的有资质的人")}
