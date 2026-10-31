# -*- coding: utf-8 -*-
"""人员与组织（第 18 轮 E4）：部门岗位、员工档案、技能矩阵、排班、出勤、加班、缺人时设备开不了。

- 员工、部门、岗位以 ERPNext 为准（Employee、Department、Designation，E4-1），台账第一次用到时整批建（提议 people_setup，自动确认）；
  平台里的员工档案就是安全环保那张表（ehs_person，E2 的 12 人工号不变），这里补上部门、班次、电话等（E4-9）。
- 技能矩阵（员工 × 设备，1 学徒 / 2 熟练 / 3 可带徒）、排班、出勤、加班在平台（E4-1、E4-3、E4-5）。
- 两个班：早班 06:00–18:00、晚班 18:00–06:00（sim/staffing.py）。固定岗位（谁哪班开哪台）+ 某天的调整（调班、顶班）= 当天的排班。
- 平台按排班、出勤、技能算出每天每班每台设备的“人员等级”，下发给仿真车间：没人就停在“缺人”，只有学徒按 60% 速度（E4-4）。
  教学模式默认打开，情景重载后关闭；生产模式默认关闭（工厂接上自己的真实排班后再开）。
- 出勤只记“请假 / 迟到 / 缺勤”，不记原因（E4-5）。"""
import datetime as dt
import logging
import random

from psycopg.types.json import Jsonb

from sim import staffing as STF
from wqbus import UNITS

log = logging.getLogger("people")

SCHEMA = """
alter table ehs_person add column if not exists dept text;
alter table ehs_person add column if not exists shift text;
alter table ehs_person add column if not exists phone text;
alter table ehs_person add column if not exists hired date;
alter table ehs_person add column if not exists gender text;
create table if not exists skill (
    mode        text not null,
    emp_id      text not null,
    unit        text not null,
    level       integer not null,                 -- 1 学徒 / 2 熟练 / 3 可带徒
    valid_until date,
    primary key (mode, emp_id, unit)
);
create table if not exists roster_post (
    mode   text not null,
    shift  text not null,                         -- day 早班 / night 晚班
    unit   text not null,
    emp_id text not null,
    primary key (mode, shift, unit)
);
create table if not exists roster (
    mode      text not null,
    day       date not null,
    shift     text not null,
    unit      text not null,
    emp_id    text not null default '',           -- '' 表示这一班这台设备空着（人被调走了）
    source    text not null default 'swap',       -- swap 调班 / overtime 加班顶班 / apprentice 学徒带教
    action_id bigint,
    primary key (mode, day, shift, unit)
);
create table if not exists attendance (
    id           bigserial primary key,
    mode         text not null,
    day          date not null,
    shift        text not null,
    emp_id       text not null,
    status       text not null,                   -- leave 请假 / late 迟到 / absent 缺勤（不记原因）
    minutes_late integer,
    by_name      text,
    at           timestamptz not null default now(),
    unique (mode, day, shift, emp_id)
);
create table if not exists overtime_log (
    id        bigserial primary key,
    mode      text not null,
    day       date not null,
    emp_id    text not null,
    minutes   integer not null,
    action_id bigint,
    at        timestamptz not null default now()
);
create table if not exists skill_training (
    id        bigserial primary key,
    mode      text not null,
    emp_id    text not null,
    unit      text not null,
    hours     numeric not null,
    status    text not null default 'doing',      -- doing 带教中 / passed 考核通过
    action_id bigint,
    by_name   text,
    started_at timestamptz not null default now(),
    passed_at timestamptz
);
create table if not exists people_sim (
    mode  text primary key,
    state jsonb not null default '{}'
);
"""

DEPTS = [("机加一班", "Machining crew 1"), ("机加二班", "Machining crew 2"), ("热处理", "Heat treatment"), ("装配检验", "Assembly & inspection"),
         ("设备组", "Maintenance"), ("安环部", "EHS"), ("计划物流", "Planning & logistics")]
POSTS = {"操作工": "Machine operator", "学徒": "Apprentice", "班组长": "Shift lead", "维修工": "Maintenance technician", "安全员": "Safety officer",
         "装配工": "Assembler", "检验员": "Inspector", "计划员": "Planner", "仓管员": "Storekeeper"}
# 第 18 轮 E2 的 12 人（P01–P12）+ E4 新增 18 人：工号、姓名、岗位、部门、班次（全部是虚构的人名）
NEW_PEOPLE = [("P13", "黄磊", "操作工", "机加一班"), ("P14", "杨帆", "操作工", "机加一班"), ("P15", "何敏", "操作工", "机加一班"),
              ("P16", "高峰", "操作工", "机加二班"), ("P17", "罗军", "操作工", "机加二班"), ("P18", "梁晨", "操作工", "机加二班"),
              ("P19", "宋雨", "操作工", "热处理"), ("P20", "唐亮", "装配工", "装配检验"), ("P21", "许静", "装配工", "装配检验"),
              ("P22", "韩冰", "操作工", "机加二班"), ("P23", "曹阳", "学徒", "机加一班"), ("P24", "邓佳", "学徒", "机加二班"),
              ("P25", "彭飞", "检验员", "装配检验"), ("P26", "曾琳", "计划员", "计划物流"), ("P27", "萧然", "仓管员", "计划物流"),
              ("P28", "田野", "操作工", "机加一班"), ("P29", "董洁", "装配工", "装配检验"), ("P30", "袁博", "装配工", "装配检验")]
DEPT_OF = {"P05": "热处理", "P06": "设备组", "P07": "设备组", "P08": "设备组", "P09": "安环部", "P10": "安环部"}
NIGHT = {"P03", "P04", "P07", "P10", "P12", "P16", "P17", "P18", "P19", "P21", "P22", "P24", "P30"}     # 晚班；其余早班
FEMALE = {"P02", "P05", "P08", "P10", "P15", "P18", "P19", "P21", "P22", "P24", "P26", "P27", "P29"}
# 技能矩阵：工号 → {设备: 等级}（1 学徒 / 2 熟练 / 3 可带徒）。键槽铣、滚齿、卧加、压装机只有一个熟练的人（单点依赖，只开早班）
SKILLS = {
    "P01": {"grd-01": 3, "cnc-l01-a": 2}, "P02": {"hob-01": 2, "cnc-l01-b": 1}, "P03": {"grd-01": 2, "saw-01": 2},
    "P04": {"cnc-l01-a": 2, "cnc-l01-b": 2, "saw-01": 2}, "P05": {"ht-01": 3}, "P11": {"cnc-l01-a": 3, "cnc-l01-b": 3, "saw-01": 2},
    "P12": {"vmc-01": 3, "cnc-l01-a": 2, "cnc-l01-b": 2}, "P13": {"cnc-l01-a": 2, "cnc-l01-b": 2}, "P14": {"saw-01": 2, "key-01": 1},
    "P15": {"key-01": 2, "saw-01": 1}, "P16": {"cnc-l01-a": 2, "cnc-l01-b": 2}, "P17": {"saw-01": 2}, "P18": {"vmc-01": 2, "hmc-01": 1},
    "P19": {"ht-01": 2}, "P20": {"asm-01": 2}, "P21": {"asm-01": 2}, "P22": {"vmc-01": 2, "hob-01": 1},
    "P23": {"grd-01": 1, "cnc-l01-a": 1}, "P24": {"grd-01": 1, "saw-01": 1}, "P28": {"vmc-01": 2, "hmc-01": 2},
    "P29": {"press-01": 2, "asm-01": 2}, "P30": {"asm-01": 2},
}
# 固定岗位：(班次, 设备) → 工号。键槽铣、滚齿、卧加、压装机晚班不开（只有一个人会）
POSTS_TEMPLATE = {
    ("day", "saw-01"): "P14", ("day", "cnc-l01-a"): "P13", ("day", "cnc-l01-b"): "P13", ("day", "ht-01"): "P05", ("day", "key-01"): "P15",
    ("day", "grd-01"): "P01", ("day", "hob-01"): "P02", ("day", "vmc-01"): "P28", ("day", "hmc-01"): "P28", ("day", "press-01"): "P29",
    ("day", "asm-01"): "P20",
    ("night", "saw-01"): "P17", ("night", "cnc-l01-a"): "P16", ("night", "cnc-l01-b"): "P16", ("night", "ht-01"): "P19",
    ("night", "grd-01"): "P03", ("night", "vmc-01"): "P18", ("night", "asm-01"): "P21",
}
try:                                    # 第 61 轮：清单写了产品的厂（机器人厂等）：按车间设备生成的示例人员，只排白班（factory/staff.py）
    from factory import staff as _ST
    _S = _ST.active()
except ImportError:
    _S = None
if _S:
    from hub import ehs as _EH
    _ehs_ids = {p[0] for p in _EH.PEOPLE}
    NEW_PEOPLE = [p for p in _S["people"] if p[0] not in _ehs_ids]
    DEPTS = list(_S["depts"])
    DEPT_OF = {}
    NIGHT = set()
    FEMALE = set(_S["female"])
    SKILLS = {k: dict(v) for k, v in _S["skills"].items()}
    POSTS_TEMPLATE = dict(_S["posts"])
SHIFTS_USED = ("day",) if _S else ("day", "night")                # 第 61 轮：只排白班的厂，夜间不下发人员等级（车间照工厂日历）
N_EHS = 12 if not _S else len(_S["people"]) - len(NEW_PEOPLE)        # 安全环保那边已经建的人数
LEVELS = {1: "学徒", 2: "熟练", 3: "可带徒"}
ATT = {"leave": "请假", "late": "迟到", "absent": "缺勤"}
SHIFT_NAME = {"day": "早班", "night": "晚班"}
if _S:
    SHIFT_NAME = {"day": "白班", "night": "夜间（不排班）"}
WAGE = 30.0                 # 操作工工时 $/小时（加班 1.5 倍）
OT_RATE = 1.5
TRAIN_HOURS = 40            # 技能培训（带教）标准小时
TRAINER_RATE = 0.25         # 带教期间师傅分出去的时间（按工时算钱）
OT_WEEK_LIMIT_H = 12        # 每人每周加班上限（规则 H4 的默认参数）


def init(db):
    if getattr(db, "_people_ready", False):
        return
    from hub import ehs as EH
    EH.init(db)
    db.x(SCHEMA)
    try:
        db._people_ready = True
    except AttributeError:
        pass


def today(mode=None):
    from hub import kpi
    return dt.datetime.now(kpi.TZ).date()


def tz():
    from hub import kpi
    return kpi.TZ


def factory_now(db=None, mode=None):
    """工厂时间：教学模式车间可能倍速运行，按最近一条车间事件里的工厂时间推算（和真实时间差多少）；生产模式就是现在"""
    now = dt.datetime.now(dt.timezone.utc)
    if db is None or mode != "teach":
        return now
    try:
        r = db.one("select ts, payload->'data'->>'factory_ts' as f from bus_message where mode=%s and type in ('machine.status','machine.event') "
                   "and payload->'data' ? 'factory_ts' order by seq desc limit 1", (mode,))         # 运转中的设备每 2 秒发一次状态
    except Exception:  # noqa: BLE001
        return now
    if not r or not r["f"] or (now - r["ts"]).total_seconds() > 3600:
        return now
    return now + (dt.datetime.fromisoformat(r["f"].replace("Z", "+00:00")) - r["ts"])


def now_shift(now=None, db=None, mode=None):
    """现在（工厂时间）是哪天的哪个班"""
    now = now or factory_now(db, mode)
    return STF.shift_of(now.astimezone(tz()))


# ---------------------------------------------------------------- 初始数据
def _fake(pid):
    n = int(pid[1:])
    born = dt.date(1970 + (n * 7) % 30, 1 + (n * 5) % 12, 1 + (n * 3) % 27)
    hired = dt.date(2010 + (n * 3) % 15, 1 + (n * 7) % 12, 1 + (n * 11) % 27)
    return born, hired, "555-01{:02d}".format(n)


def seed(db, mode):
    """在安全环保的 12 人基础上补齐 30 人、部门、班次、技能矩阵、固定岗位（已有就不动）"""
    from hub import ehs as EH
    init(db)
    EH.seed(db, mode)
    has_post = bool(db.one("select 1 as x from roster_post where mode=%s limit 1", (mode,)))
    if has_post and not db.one("select 1 as x from ehs_person where mode=%s and dept is null limit 1", (mode,)) and \
            db.one("select count(*) as n from ehs_person where mode=%s", (mode,))["n"] >= N_EHS + len(NEW_PEOPLE):
        return False
    d0 = today()
    have = {r["id"] for r in db.q("select id from ehs_person where mode=%s", (mode,))}
    for pid, name, post, team in NEW_PEOPLE:
        if pid in have:
            continue
        db.x("insert into ehs_person (id, mode, name, post, team) values (%s,%s,%s,%s,%s) on conflict do nothing", (pid, mode, name, post, team))
        db.x("insert into ehs_training (mode, person_id, kind, done_day, valid_months) values (%s,%s,'induction',%s,36)",
             (mode, pid, d0 - dt.timedelta(days=60 + int(pid[1:]) * 11)))
    for p in db.q("select id, team from ehs_person where mode=%s and dept is null", (mode,)):
        born, hired, phone = _fake(p["id"])
        db.x("update ehs_person set dept=%s, shift=%s, phone=%s, hired=%s, gender=%s where id=%s and mode=%s",
             (DEPT_OF.get(p["id"]) or p["team"], "night" if p["id"] in NIGHT else "day", phone, hired, "Female" if p["id"] in FEMALE else "Male",
              p["id"], mode))
    if has_post:                                         # 技能、岗位已有（可能已被培训、调整过）：不动
        return True
    for pid, sk in SKILLS.items():
        for u, lv in sk.items():
            valid = d0 + dt.timedelta(days=200 + int(pid[1:]) * 9) if u == "ht-01" else None      # 热处理炉要年审
            if pid == "P19" and u == "ht-01":
                valid = d0 + dt.timedelta(days=20)                                                 # 宋雨的热处理炉操作证 20 天后到期
            db.x("insert into skill (mode, emp_id, unit, level, valid_until) values (%s,%s,%s,%s,%s) on conflict do nothing", (mode, pid, u, lv, valid))
    for (sh, u), pid in POSTS_TEMPLATE.items():
        db.x("insert into roster_post (mode, shift, unit, emp_id) values (%s,%s,%s,%s) on conflict do nothing", (mode, sh, u, pid))
    return True


def reset(db, mode):
    """教学情景重置：出勤、调班、加班、培训清空，技能矩阵和岗位回到初始；“要有人”关闭（老师开始实验后打开）。员工档案（ERPNext）留着"""
    init(db)
    keep = {k: v for k, v in _state(db, mode).items() if k in ("setup_pid", "setup_at")}
    for t in ("skill", "roster_post", "roster", "attendance", "overtime_log", "skill_training", "people_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    _save_state(db, mode, dict(keep, enabled=False))
    seed(db, mode)


def _state(db, mode):
    init(db)
    r = db.one("select state from people_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _save_state(db, mode, st):
    db.x("insert into people_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


def enabled(db, mode):
    """车间“要有人”开没开：教学模式默认开；情景重载后关；生产模式默认关（工厂接上自己的真实排班后再开）"""
    st = _state(db, mode)
    if "enabled" in st:
        return bool(st["enabled"])
    return mode == "teach"


def set_enabled(H, mode, on, who):
    st = _state(H.db, mode)
    st["enabled"] = bool(on)
    _save_state(H.db, mode, st)
    push(H, mode, who)
    return {"enabled": bool(on)}


# ---------------------------------------------------------------- 档案、技能
def employees(db, mode):
    seed(db, mode)
    rows = db.q("select * from ehs_person where mode=%s and active order by id", (mode,))
    sk = skills(db, mode)
    erp = {str(m["data"].get("employee_number") or ""): m["data"] for m in db.erp_docs("Employee", mode)}
    out = []
    for p in rows:
        e = erp.get(p["id"]) or {}
        out.append(dict(p, shift_name=SHIFT_NAME.get(p["shift"], "—"), skills={k: v for (e_, k), v in sk.items() if e_ == p["id"]},
                        erp_id=e.get("name"), hired=p["hired"].isoformat() if p.get("hired") else None))
    return out


def person(db, mode, pid):
    return db.one("select * from ehs_person where id=%s and mode=%s", (pid, mode))


def skills(db, mode):
    """{(工号, 设备): 等级}（过期的按学徒算）"""
    seed(db, mode)
    d0 = today()
    out = {}
    for r in db.q("select * from skill where mode=%s", (mode,)):
        lv = int(r["level"])
        if r["valid_until"] and r["valid_until"] < d0:
            lv = min(lv, 1)
        out[(r["emp_id"], r["unit"])] = lv
    return out


def skill_rows(db, mode):
    seed(db, mode)
    return db.q("select * from skill where mode=%s order by emp_id, unit", (mode,))


def matrix(db, mode):
    """技能矩阵：员工 × 设备；每台设备熟练以上几个人"""
    sk = skills(db, mode)
    emps = [e for e in employees(db, mode) if any(k[0] == e["id"] for k in sk)]
    units = list(STF.NEEDS)
    count = {u: sum(1 for (e, uu), lv in sk.items() if uu == u and lv >= 2 and _active(db, mode, e)) for u in units}
    valid = {(r["emp_id"], r["unit"]): r["valid_until"].isoformat() if r["valid_until"] else None for r in skill_rows(db, mode)}
    return {"units": [{"unit": u, "name": UNITS[u][1], "skilled": count[u], "single": count[u] == 1, "none": count[u] == 0} for u in units],
            "rows": [{"id": e["id"], "name": e["name"], "post": e["post"], "dept": e["dept"], "shift": e["shift"],
                      "cells": {u: {"level": sk.get((e["id"], u)), "valid_until": valid.get((e["id"], u))} for u in units if (e["id"], u) in sk}}
                     for e in emps]}


def _active(db, mode, pid):
    p = person(db, mode, pid)
    return bool(p and p["active"])


def single_points(db, mode):
    """熟练以上只有一个人的设备"""
    m = matrix(db, mode)
    sk = skills(db, mode)
    out = []
    for u in m["units"]:
        if u["single"]:
            who = next(e for (e, uu), lv in sk.items() if uu == u["unit"] and lv >= 2)
            out.append({"unit": u["unit"], "name": u["name"], "emp_id": who, "emp_name": person(db, mode, who)["name"]})
    return out


# ---------------------------------------------------------------- 排班、出勤
def roster_for(db, mode, day, shift):
    """这一天这一班：{设备: 工号（'' 空着）}，并标出来源"""
    seed(db, mode)
    out = {r["unit"]: {"emp_id": r["emp_id"], "source": "post"} for r in db.q("select * from roster_post where mode=%s and shift=%s", (mode, shift))}
    for r in db.q("select * from roster where mode=%s and day=%s and shift=%s", (mode, day, shift)):
        out[r["unit"]] = {"emp_id": r["emp_id"], "source": r["source"], "action_id": r["action_id"]}
    return out


def absences(db, mode, day, shift):
    return {r["emp_id"]: r for r in db.q("select * from attendance where mode=%s and day=%s and shift=%s", (mode, day, shift))}


def slot_level(sk, emp_id, unit, absent):
    if not emp_id or emp_id in absent:
        return 0
    return min(2, sk.get((emp_id, unit), 0))


def levels(db, mode, days):
    """{'日期|班|设备': 等级}：按排班、出勤、技能算（没人 0、学徒 1、熟练以上 2）"""
    sk = skills(db, mode)
    out = {}
    for d in days:
        for sh in SHIFTS_USED:
            ro = roster_for(db, mode, d, sh)
            ab = {k for k, v in absences(db, mode, d, sh).items() if v["status"] in ("leave", "absent")}
            for u in STF.NEEDS:
                r = ro.get(u)
                out["{}|{}|{}".format(d.isoformat(), sh, u)] = slot_level(sk, r["emp_id"], u, ab) if r else 0
    return out


def window_days(now=None, db=None, mode=None):
    d, _ = now_shift(now, db, mode)
    return [d + dt.timedelta(days=i) for i in range(-1, 8)]


def push(H, mode, who="系统", now=None):
    """把人员等级下发给车间（打开时）；关闭时也发一次 enabled=false"""
    mes = getattr(H, "mes", None)
    if mes is None:
        return None
    on = enabled(H.db, mode)
    lv = levels(H.db, mode, window_days(now, H.db, mode)) if on else {}
    mes.command("sim", "set_staffing", mode, who, enabled=on, levels=lv, replace=True)
    st = _state(H.db, mode)
    st["pushed_at"] = dt.datetime.now(dt.timezone.utc).timestamp()
    _save_state(H.db, mode, st)
    return {"enabled": on, "levels": len(lv)}


def week_days(day):
    mon = day - dt.timedelta(days=day.weekday())
    return [mon + dt.timedelta(days=i) for i in range(7)]


def week(db, mode, day=None):
    """一周的排班表：每天每班每台设备是谁、等级、缺口"""
    day = day or today()
    sk = skills(db, mode)
    names = {p["id"]: p["name"] for p in db.q("select id, name from ehs_person where mode=%s", (mode,))}
    out = []
    for d in week_days(day):
        for sh in SHIFTS_USED:
            ro = roster_for(db, mode, d, sh)
            ab = absences(db, mode, d, sh)
            cells = {}
            for u in STF.NEEDS:
                r = ro.get(u)
                if not r:
                    continue
                e = r["emp_id"]
                a = ab.get(e)
                lv = slot_level(sk, e, u, {k for k, v in ab.items() if v["status"] in ("leave", "absent")})
                cells[u] = {"emp_id": e, "name": names.get(e, "—") if e else "（空）", "source": r["source"], "level": lv,
                            "attendance": ATT.get(a["status"]) if a else None, "gap": lv == 0}
            out.append({"day": d.isoformat(), "shift": sh, "shift_name": SHIFT_NAME[sh], "cells": cells})
    return out


def gaps(db, mode, now=None, hours=24):
    """未来 hours 小时内（含现在这一班）有岗位、但这一班没人能开的设备"""
    now = now or factory_now(db, mode)
    local = now.astimezone(tz())
    sk = skills(db, mode)
    out = []
    d, sh = STF.shift_of(local)
    slots = []
    start = STF.shift_start(d, sh, tz())
    while start < local + dt.timedelta(hours=hours):
        slots.append((d, sh))
        start = STF.next_change(start)
        d, sh = STF.shift_of(start)
    names = {p["id"]: p["name"] for p in db.q("select id, name from ehs_person where mode=%s", (mode,))}
    for d, sh in slots:
        ro = roster_for(db, mode, d, sh)
        ab = absences(db, mode, d, sh)
        absent = {k for k, v in ab.items() if v["status"] in ("leave", "absent")}
        for u, r in ro.items():
            lv = slot_level(sk, r["emp_id"], u, absent)
            if lv == 0:
                e = r["emp_id"]
                why = ("{} {}".format(names.get(e, e), ATT[ab[e]["status"]]) if e in ab else
                       ("岗位空着（人被调走）" if not e else "{} 不会开这台设备".format(names.get(e, e))))
                out.append({"day": d.isoformat(), "shift": sh, "shift_name": SHIFT_NAME[sh], "unit": u, "emp_id": e or None,
                            "emp_name": names.get(e) if e else None, "why": why,
                            "start": STF.shift_start(d, sh, tz()).astimezone(dt.timezone.utc).isoformat()})
    return out


def on_shift_ids(db, mode, now=None):
    """这一班在岗的人（按各人的班次，去掉请假、缺勤的）"""
    seed(db, mode)
    d, sh = now_shift(now, db, mode)
    ab = {k for k, v in absences(db, mode, d, sh).items() if v["status"] in ("leave", "absent")}
    return {p["id"] for p in db.q("select id from ehs_person where mode=%s and active and shift=%s", (mode, sh)) if p["id"] not in ab}


def record_attendance(H, mode, emp_id, status, day=None, shift=None, who="系统", minutes_late=None):
    db = H.db
    if status not in ATT:
        raise ValueError("出勤只记：请假、迟到、缺勤")
    p = person(db, mode, emp_id)
    if p is None:
        raise KeyError(emp_id)
    if day is None or shift is None:
        d, sh = now_shift(None, db, mode)
        day, shift = day or d, shift or (p["shift"] or sh)
    db.x("insert into attendance (mode, day, shift, emp_id, status, minutes_late, by_name) values (%s,%s,%s,%s,%s,%s,%s) "
         "on conflict (mode, day, shift, emp_id) do update set status=excluded.status, minutes_late=excluded.minutes_late, by_name=excluded.by_name, at=now()",
         (mode, day, shift, emp_id, status, minutes_late, who))
    push(H, mode, who)
    return {"emp_id": emp_id, "day": str(day), "shift": shift, "status": status}


def clear_attendance(H, mode, emp_id, day, shift, who="系统"):
    H.db.x("delete from attendance where mode=%s and emp_id=%s and day=%s and shift=%s", (mode, emp_id, day, shift))
    push(H, mode, who)


def today_board(db, mode, now=None):
    """今天这一班：谁在岗、谁请假，岗位缺口"""
    now = now or factory_now(db, mode)
    d, sh = now_shift(now)
    ro = roster_for(db, mode, d, sh)
    ab = absences(db, mode, d, sh)
    rows = db.q("select * from ehs_person where mode=%s and active and shift=%s order by id", (mode, sh))
    on_post = {}
    for u, r in ro.items():
        if r["emp_id"]:
            on_post.setdefault(r["emp_id"], []).append(u)
    return {"day": d.isoformat(), "shift": sh, "shift_name": SHIFT_NAME[sh],
            "people": [{"id": p["id"], "name": p["name"], "post": p["post"], "units": on_post.get(p["id"], []),
                        "attendance": ATT.get(ab[p["id"]]["status"]) if p["id"] in ab else "在岗"} for p in rows],
            "gaps": [g for g in gaps(db, mode, now, hours=1) if g["day"] == d.isoformat() and g["shift"] == sh]}


def overtime_week(db, mode, day=None):
    """本周每人加班小时"""
    d = day or today()
    ds = week_days(d)
    rows = db.q("select emp_id, sum(minutes) as m from overtime_log where mode=%s and day between %s and %s group by emp_id", (mode, ds[0], ds[-1]))
    return {r["emp_id"]: round(float(r["m"]) / 60, 1) for r in rows}


def absence_rate(db, mode, days=7):
    """近 days 天各班组缺勤率（请假 + 缺勤 ÷ 排班人次）"""
    d0 = today()
    out = {}
    teams = {p["id"]: p["team"] for p in db.q("select id, team from ehs_person where mode=%s", (mode,))}
    sched, miss = {}, {}
    for i in range(days):
        d = d0 - dt.timedelta(days=i)
        for sh in ("day", "night"):
            ro = roster_for(db, mode, d, sh)
            ab = absences(db, mode, d, sh)
            for e in {r["emp_id"] for r in ro.values() if r["emp_id"]}:
                t = teams.get(e) or "—"
                sched[t] = sched.get(t, 0) + 1
                if e in ab and ab[e]["status"] in ("leave", "absent"):
                    miss[t] = miss.get(t, 0) + 1
    for t, n in sched.items():
        out[t] = {"scheduled": n, "missed": miss.get(t, 0), "rate": round(miss.get(t, 0) / n, 3) if n else 0}
    return out


# ---------------------------------------------------------------- 动作执行器
def _slot_from(p):
    day = dt.date.fromisoformat(str(p["day"])[:10])
    if p["shift"] not in ("day", "night"):
        raise ValueError("班次只能是早班或晚班")
    if p["unit"] not in STF.NEEDS:
        raise ValueError("这台设备不需要人")
    return day, p["shift"], p["unit"]


def exec_swap(H, mode, p, u):
    """调班：把某人排到某天某班某台设备（调人顶岗 / 学徒带教）；他原来这一班的岗位空出来"""
    db = H.db
    day, sh, unit = _slot_from(p)
    emp = p["emp_id"]
    if person(db, mode, emp) is None:
        raise ValueError("没有这个人：{}".format(emp))
    lv = skills(db, mode).get((emp, unit), 0)
    if lv < 1:
        raise ValueError("{} 不会开 {}".format(person(db, mode, emp)["name"], unit.upper()))
    src = "apprentice" if lv == 1 else "swap"
    aid = p.get("_action_id")
    # 他在这一天这一班原来的岗位空出来；如果他原来在另一个班，那个班的岗位也空出来
    for s2 in ("day", "night"):
        for uu, r in roster_for(db, mode, day, s2).items():
            if r["emp_id"] == emp and not (s2 == sh and uu == unit):
                db.x("insert into roster (mode, day, shift, unit, emp_id, source, action_id) values (%s,%s,%s,%s,'',%s,%s) "
                     "on conflict (mode, day, shift, unit) do update set emp_id='', source=excluded.source, action_id=excluded.action_id",
                     (mode, day, s2, uu, "swap", aid))
    db.x("insert into roster (mode, day, shift, unit, emp_id, source, action_id) values (%s,%s,%s,%s,%s,%s,%s) "
         "on conflict (mode, day, shift, unit) do update set emp_id=excluded.emp_id, source=excluded.source, action_id=excluded.action_id",
         (mode, day, sh, unit, emp, src, aid))
    push(H, mode, u.get("name") if isinstance(u, dict) else "系统")
    return {"text": "排班已改：{} {} {} 由 {} 顶岗{}，已发给车间".format(day, SHIFT_NAME[sh], unit.upper(), person(db, mode, emp)["name"],
                                                           "（学徒，班组长带着）" if lv == 1 else "")}


def sim_change(db, mode, c):
    """动作里的调班、加班顶班 → 推演里的“排班”改动（人员等级）"""
    day, sh, unit = _slot_from(c)
    emp = c["emp_id"]
    lv = min(2, skills(db, mode).get((emp, unit), 0))
    key = "{}|{}|{}".format(day.isoformat(), sh, unit)
    out = {"type": "staff", "levels": {key: lv}, "emp_id": emp, "who": (person(db, mode, emp) or {}).get("name")}
    if c["type"] == "overtime_assign":
        out["overtime_min"] = int(c.get("minutes") or 12 * 60)
        return out
    for s2 in ("day", "night"):
        for uu, r in roster_for(db, mode, day, s2).items():
            if r["emp_id"] == emp and not (s2 == sh and uu == unit):
                out["levels"]["{}|{}|{}".format(day.isoformat(), s2, uu)] = 0
    return out


def exec_overtime(H, mode, p, u):
    """加班顶班：某人在自己的班之外再顶一班（原岗位不动），记个人加班小时"""
    db = H.db
    day, sh, unit = _slot_from(p)
    emp = p["emp_id"]
    if skills(db, mode).get((emp, unit), 0) < 2:
        raise ValueError("加班顶班要熟练以上")
    mins = int(p.get("minutes") or 12 * 60)
    aid = p.get("_action_id")
    db.x("insert into roster (mode, day, shift, unit, emp_id, source, action_id) values (%s,%s,%s,%s,%s,'overtime',%s) "
         "on conflict (mode, day, shift, unit) do update set emp_id=excluded.emp_id, source='overtime', action_id=excluded.action_id",
         (mode, day, sh, unit, emp, aid))
    db.x("insert into overtime_log (mode, day, emp_id, minutes, action_id) values (%s,%s,%s,%s,%s)", (mode, day, emp, mins, aid))
    push(H, mode, u.get("name") if isinstance(u, dict) else "系统")
    return {"text": "{} {} {} 由 {} 加班顶班 {:.0f} 小时，已发给车间".format(day, SHIFT_NAME[sh], unit.upper(), person(db, mode, emp)["name"], mins / 60)}


def exec_training(H, mode, p, u):
    """技能培训（带教）：到时考核，矩阵升级为熟练"""
    db = H.db
    emp, unit = p["emp_id"], p["unit"]
    if person(db, mode, emp) is None or unit not in STF.NEEDS:
        raise ValueError("人或设备不对")
    if skills(db, mode).get((emp, unit), 0) >= 2:
        raise ValueError("{} 已经会开 {}".format(person(db, mode, emp)["name"], unit.upper()))
    hours = float(p.get("hours") or TRAIN_HOURS)
    r = db.one("insert into skill_training (mode, emp_id, unit, hours, action_id, by_name) values (%s,%s,%s,%s,%s,%s) returning id",
               (mode, emp, unit, hours, p.get("_action_id"), u.get("name") if isinstance(u, dict) else None))
    db.x("insert into skill (mode, emp_id, unit, level) values (%s,%s,%s,1) on conflict (mode, emp_id, unit) do update set level=greatest(skill.level, 1)",
         (mode, emp, unit))
    push(H, mode)
    return {"text": "技能培训 TR-{:05d}：{} 学 {}，带教 {:g} 小时（先按学徒排班）".format(r["id"], person(db, mode, emp)["name"], unit.upper(), hours),
            "training_id": r["id"]}


def pass_training(H, mode, tid, who):
    db = H.db
    r = db.one("select * from skill_training where id=%s and mode=%s", (tid, mode))
    if r is None:
        raise KeyError(tid)
    if r["status"] == "passed":
        raise ValueError("已经考核通过")
    db.x("update skill_training set status='passed', passed_at=now() where id=%s", (tid,))
    db.x("insert into skill (mode, emp_id, unit, level) values (%s,%s,%s,2) on conflict (mode, emp_id, unit) do update set level=greatest(skill.level, 2)",
         (mode, r["emp_id"], r["unit"]))
    push(H, mode, who)
    return {"id": tid, "status": "passed"}


def trainings(db, mode):
    init(db)
    names = {p["id"]: p["name"] for p in db.q("select id, name from ehs_person where mode=%s", (mode,))}
    return [dict(r, key="TR-{:05d}".format(r["id"]), emp_name=names.get(r["emp_id"]), started_at=r["started_at"].isoformat(),
                 passed_at=r["passed_at"].isoformat() if r["passed_at"] else None)
            for r in db.q("select * from skill_training where mode=%s order by id desc limit 100", (mode,))]


# ---------------------------------------------------------------- 处理方案（E4-7）
def _candidates(db, mode, day, shift, unit):
    """能顶这一班的人：同班空闲的熟练工、另一班的熟练工、学徒"""
    sk = skills(db, mode)
    ro = roster_for(db, mode, day, shift)
    other = "night" if shift == "day" else "day"
    ro2 = roster_for(db, mode, day, other)
    ab = {k for k, v in absences(db, mode, day, shift).items() if v["status"] in ("leave", "absent")}
    busy = {r["emp_id"]: uu for uu, r in ro.items() if r["emp_id"]}
    busy2 = {r["emp_id"]: uu for uu, r in ro2.items() if r["emp_id"]}
    rows = db.q("select * from ehs_person where mode=%s and active order by id", (mode,))
    free, cross, appr = [], [], []
    for p in rows:
        lv = sk.get((p["id"], unit), 0)
        if lv == 0 or p["id"] in ab:
            continue
        x = {"emp_id": p["id"], "name": p["name"], "level": lv, "shift": p["shift"], "post_unit": busy.get(p["id"]) or busy2.get(p["id"])}
        if lv == 1:
            appr.append(x)
        elif p["shift"] == shift and p["id"] not in busy:
            free.append(x)
        elif p["id"] not in busy:
            cross.append(x)
    return free, cross, appr


def options(db, mode, a, snap, ctx):
    """H2 排班缺口：不处理（对照）/ 调人顶岗 / 学徒带教 / 加班顶班，用车间推演算"""
    from hub.ont import plan as P
    from hub.ont import playbook as PB
    v = (a.get("detail") or {}).get("values") or {}
    unit, day, sh = v.get("unit"), v.get("day"), v.get("shift")
    if not (unit and day and sh) or unit not in (snap.get("machines") or {}):
        return {"options": [], "affected": [], "reason": "这个异常没有关联到某一班某台设备", "recommended": None}
    d = dt.date.fromisoformat(day)
    key = "{}|{}|{}".format(day, sh, unit)
    free, cross, appr = _candidates(db, mode, d, sh, unit)
    plans = [("none", "不处理（对照）", [{"type": "staff", "levels": {key: 0}}], "这一班 {} 停着".format(unit.upper()), None)]
    best = (free or cross)
    if best:
        x = best[0]
        lv = {key: 2}
        note = "{}（{}）来顶".format(x["name"], LEVELS[min(x["level"], 3)])
        vac = [(s2, uu) for s2 in ("day", "night") for uu, r in roster_for(db, mode, d, s2).items()
               if r["emp_id"] == x["emp_id"] and not (s2 == sh and uu == unit)]
        for s2, uu in vac:                                                    # 他原来的岗位这一天空出来
            lv["{}|{}|{}".format(day, s2, uu)] = 0
        if vac:
            note += "；他原来的 {} 这一天空出来".format("、".join("{} {}".format(SHIFT_NAME[s2], uu.upper()) for s2, uu in vac))
        plans.append(("swap", "调 {} 顶岗".format(x["name"]), [{"type": "staff", "levels": lv, "emp_id": x["emp_id"], "who": x["name"]}], note,
                      {"type": "shift_swap", "day": day, "shift": sh, "unit": unit, "emp_id": x["emp_id"]}))
    if appr:
        x = appr[0]
        plans.append(("apprentice", "学徒 {} 带教开机".format(x["name"]), [{"type": "staff", "levels": {key: 1}, "emp_id": x["emp_id"], "who": x["name"]}],
                      "按 60% 速度，要班组长带着；质量风险高一点", {"type": "shift_swap", "day": day, "shift": sh, "unit": unit, "emp_id": x["emp_id"]}))
    ot = [x for x in cross if x["shift"] != sh] or [x for x in free]
    if ot:
        x = ot[0]
        plans.append(("overtime", "{} 加班顶班".format(x["name"]),
                      [{"type": "staff", "levels": {key: 2}, "emp_id": x["emp_id"], "who": x["name"], "overtime_min": 12 * 60}],
                      "原岗位不动，加班 12 小时（本周已加班 {:g} 小时）".format(overtime_week(db, mode, d).get(x["emp_id"], 0)),
                      {"type": "overtime_assign", "day": day, "shift": sh, "unit": unit, "emp_id": x["emp_id"], "minutes": 12 * 60}))
    stub = dict(a, rule="P1", subject_type="Machine", subject_key=unit)
    names = PB.affected(stub, ctx)
    base = [{"type": "staff", "levels": levels(db, mode, window_days(None, db, mode))}] if enabled(db, mode) else []    # 先按现在的排班
    out = []
    for i, (kind, label, sim, note, action) in enumerate(plans):
        r = P.simulate(snap, base + sim, ctx)
        rows = [s for s in r["sales_orders"] if s["name"] in names]
        lates = [s["late_days"] for s in rows if s["late_days"] is not None]
        res = {"sales_orders": rows, "cost_total": round(sum(c["usd"] for c in r["costs"]), 2), "costs": r["costs"], "overtime_min": r["overtime_min"],
               "overtime_units": r["overtime_units"], "checks": r["checks"], "ok": r["ok"]}
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "changes": [action] if action else [], "sim_changes": sim,
                    "result": res, "worst_late": max(lates) if lates else None, "undetermined": len(lates) < len(rows)})

    def score(o):
        wl = o["worst_late"] if o["worst_late"] is not None else 99
        return (0 if o["kind"] != "none" else 1, 0 if o["result"]["ok"] else 1, max(wl, 0), o["result"]["cost_total"], o["kind"] == "apprentice")
    best_o = min(out, key=score)
    for o in out:
        o["recommended"] = o is best_o
    reason = "建议 {} {}：{}；多花 ${:,.0f}。".format(best_o["key"], best_o["label"], "；".join(
        "{} {}".format(s["name"], "按时" if (s["late_days"] or 0) <= 0 else "晚 {} 天".format(s["late_days"])) for s in best_o["result"]["sales_orders"])
        or "没有受影响的订单", best_o["result"]["cost_total"])
    return {"options": out, "affected": names, "reason": reason, "recommended": best_o["key"]}


def training_options(db, mode, a):
    """H1 单点依赖：安排技能培训 / 暂不处理"""
    v = (a.get("detail") or {}).get("values") or {}
    unit = v.get("unit") or a.get("subject_key")
    sk = skills(db, mode)
    rows = db.q("select * from ehs_person where mode=%s and active and post in ('操作工','学徒') order by id", (mode,))
    cand = sorted([p for p in rows if sk.get((p["id"], unit), 0) < 2], key=lambda p: (-sk.get((p["id"], unit), 0), p["post"] != "学徒", p["id"]))
    out = []
    if cand:
        x = cand[0]
        cost = round(TRAIN_HOURS * WAGE * (1 + TRAINER_RATE), 2)
        out.append({"key": "A", "kind": "training", "label": "培训 {} 开 {}".format(x["name"], unit.upper()),
                    "note": "带教 {} 小时，考核通过后可以独立开，这台设备可以开两个班".format(TRAIN_HOURS),
                    "changes": [{"type": "skill_training", "emp_id": x["id"], "unit": unit, "hours": TRAIN_HOURS}],
                    "result": {"sales_orders": [], "cost_total": cost, "costs": [{"what": "带教工时（学员 + 师傅 25%）", "usd": cost}], "overtime_min": 0,
                               "checks": [], "ok": True}, "recommended": True})
    out.append({"key": chr(ord("A") + len(out)), "kind": "none", "label": "暂不处理", "note": "这个人请假或离职时，这台设备就停",
                "changes": [], "result": {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True},
                "recommended": not out})
    return {"options": out, "affected": [], "recommended": out[0]["key"],
            "reason": "建议 A：单点依赖的设备只能开一个班，关键人一请假就停；培训一个人的花费远小于停一班的损失" if cand else "没有可以培训的人"}


# ---------------------------------------------------------------- 教学模拟器
def tick(H, mode, now=None, rng=None):
    """教学模式：每天每班开班时随机请假（3%）、迟到（5%）；带教到时考核通过；每 5 分钟把人员等级再发一次"""
    db = H.db
    seed(db, mode)
    now = now or dt.datetime.now(dt.timezone.utc)
    rng = rng or random.Random()
    out = {"absent": [], "late": [], "passed": []}
    st = _state(db, mode)
    if mode == "teach":
        d, sh = now_shift(None, db, mode)                      # 工厂时间的这一班
        k = "{}|{}".format(d.isoformat(), sh)
        if st.get("att") != k:
            st["att"] = k
            _save_state(db, mode, dict(_state(db, mode), att=k))
            ro = roster_for(db, mode, d, sh)
            for e in sorted({r["emp_id"] for r in ro.values() if r["emp_id"]}):
                x = rng.random()
                if x < 0.03:
                    db.x("insert into attendance (mode, day, shift, emp_id, status, by_name) values (%s,%s,%s,%s,'leave','班组长（教学模拟器）') "
                         "on conflict do nothing", (mode, d, sh, e))
                    out["absent"].append(e)
                elif x < 0.08:
                    db.x("insert into attendance (mode, day, shift, emp_id, status, minutes_late, by_name) values (%s,%s,%s,%s,'late',%s,'班组长（教学模拟器）') "
                         "on conflict do nothing", (mode, d, sh, e, rng.choice((10, 15, 20, 30))))
                    out["late"].append(e)
        # 带教：标准小时 ÷ 30 的真实时间（40 小时 ≈ 80 分钟）后考核通过
        for r in db.q("select * from skill_training where mode=%s and status='doing'", (mode,)):
            if (now - r["started_at"]).total_seconds() >= max(120, float(r["hours"]) * 120):
                pass_training(H, mode, r["id"], "班组长（教学模拟器）")
                out["passed"].append(r["id"])
    st = _state(db, mode)
    if out["absent"] or now.timestamp() - float(st.get("pushed_at") or 0) > 300:
        push(H, mode, "系统", now)
    return out


def leave_next_shift(H, mode, emp_id, who, now=None):
    """让某人下一个要上的班请假（现在正在上就算这一班）：返回 (日期, 班, 他这一班的设备)"""
    db = H.db
    p = person(db, mode, emp_id)
    if p is None:
        raise ValueError("没有这个人")
    local = (now or factory_now(db, mode)).astimezone(tz())
    d, sh = STF.shift_of(local)
    for _ in range(4):
        units = [uu for uu, r in roster_for(db, mode, d, sh).items() if r["emp_id"] == emp_id]
        if units:
            record_attendance(H, mode, emp_id, "leave", d, sh, who)
            return d, sh, units
        d, sh = STF.shift_of(STF.next_change(STF.shift_start(d, sh, tz())))
    raise ValueError("{} 最近两天没有排班".format(p["name"]))


# ---------------------------------------------------------------- 态势
def kpis(db, mode, now=None):
    seed(db, mode)
    now = now or factory_now(db, mode)
    d, sh = now_shift(now)
    ro = roster_for(db, mode, d, sh)
    on = {r["emp_id"] for r in ro.values() if r["emp_id"]}
    ab = absences(db, mode, d, sh)
    miss = sum(1 for e in on if e in ab and ab[e]["status"] in ("leave", "absent"))
    ot = overtime_week(db, mode)
    return {"attendance_rate": round(1 - miss / len(on), 3) if on else 1.0, "on_shift": len(on), "absent": miss,
            "gaps": len(gaps(db, mode, now)), "single_points": len(single_points(db, mode)), "overtime_h_week": round(sum(ot.values()), 1),
            "enabled": enabled(db, mode), "shift": sh, "day": d.isoformat(), "shift_names": SHIFT_NAME,
            "trainings": db.one("select count(*) as n from skill_training where mode=%s and status='doing'", (mode,))["n"]}


# ---------------------------------------------------------------- ERPNext 员工档案（E4-1）
def ensure_setup(H, mode, who="系统"):
    """ERPNext 里还没有员工、部门、岗位：整批建（提议 people_setup，自动确认）。和设备台账一样：没执行就重发，桥接按工号跳过已建的"""
    import time as _t
    db = H.db
    if H.ai is None or mode != "teach":                # 虚构的 30 人只进教学用的 ERPNext；生产模式的员工由工厂自己维护
        return None
    seed(db, mode)
    st = _state(db, mode)
    pid = st.get("setup_pid")
    have = {str(m["data"].get("employee_number") or "") for m in db.erp_docs("Employee", mode)}
    rows = db.q("select * from ehs_person where mode=%s and active order by id", (mode,))
    if all(p["id"] in have for p in rows):
        return pid
    if pid:
        p = db.one("select status from ai_proposal where proposal_id=%s", (pid,))
        age = _t.time() - float(st.get("setup_at") or 0)
        if p is None:
            pass
        elif p["status"] == "failed":
            if age < 3600:
                return None
        elif age < 180 or (p["status"] == "executed" and age < 900):
            return pid
    emps = []
    for p in rows:
        if p["id"] in have:
            continue
        born, hired, phone = _fake(p["id"])
        emps.append({"id": p["id"], "name": p["name"], "gender": p.get("gender") or "Male", "born": born.isoformat(),
                     "hired": (p.get("hired") or hired).isoformat(), "dept": p.get("dept") or p["team"], "post": p["post"], "phone": phone})
    pid = H.ai.propose("people_setup", {"departments": [{"name": d, "en": e} for d, e in DEPTS],
                                        "designations": [{"name": k, "en": v} for k, v in POSTS.items()], "employees": emps},
                       mode, who, "员工档案、部门、岗位 {} 人".format(len(emps)), source="people")
    H.ai.decide(pid, who, True)
    st = _state(db, mode)
    st["setup_pid"], st["setup_at"] = pid, _t.time()
    _save_state(db, mode, st)
    return pid
