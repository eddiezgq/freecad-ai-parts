# -*- coding: utf-8 -*-
"""机器人厂的客户与服务——现场的机器人（第 64 轮）：已装机台账、现场模拟器、预警、投诉与服务工单、回访。

- 建档：车间里一台 WQ-CR5 做完整机标定（quality.measurement cr_abs），平台给它建档：6 个关节按规格先进先出配上关节测试台测过的关节
  （序列号、谐波减速器批号、出厂背隙），记下标定后绝对定位误差。这张工单的销售订单开了票 = 发出，到客户现场（现场日从那天起）。
  情景开始前已经在用的 8 台（示例）一开始就在三个客户那里。
- 现场模拟器（教学模式，1 分钟真实时间 = 1 个现场日，WQ_FIELD_DAYS_PER_MIN）：每台每天一条运行摘要——运行小时、每个关节的背隙、温度峰值、
  电流均方根、碰撞次数。背隙随运行小时磨损增长；**问题批次的谐波减速器磨得快**（来料里判过“其实有问题”的批次、被隔离的批次、
  出厂背隙偏大的）。润滑脂老化让温度慢慢升。全部是示例值。
- 预警：AI 巡检规则 RS1（背隙接近上限、过热、碰撞突增）、RS2（同一批减速器多台报警）读这里的数据。
- 投诉进 ERPNext Issue（沿用 complaint_issue）；服务工单三种：远程重新标定、上门换关节模组（备件 = 本厂的 WQJ-L / M / S，出库沿用 spare_ship）、
  上门补润滑脂；4 位服务工程师（示例）每人每个现场日一单；做完回访打满意度。
数据都在平台自己的表；ERPNext 只进 Issue 和备件出库。"""
import datetime as dt
import logging
import os
import random
import time
import zlib

from psycopg.types.json import Jsonb

from factory import data as F

log = logging.getLogger("rfield")

SCHEMA = """
create table if not exists rf_robot (
    serial    text not null,
    mode      text not null,
    item      text not null,
    wo        text,
    sales_order text,
    customer  text,
    status    text not null default 'built',     -- built 出厂待发 / field 在客户现场
    seeded    boolean not null default false,
    built_at  timestamptz not null default now(),
    start_day date,
    last_day  date,
    as_built  jsonb not null default '{}',
    state     jsonb not null default '{}',
    primary key (mode, serial)
);
create table if not exists rf_day (
    mode   text not null,
    serial text not null,
    day    date not null,
    data   jsonb not null,
    primary key (mode, serial, day)
);
create table if not exists rf_pool (
    mode    text not null,
    serial  text not null,
    item    text not null,
    lot     text,
    backlash double precision,
    used_by text,
    seq     bigint,
    primary key (mode, serial)
);
create table if not exists rf_complaint (
    id        bigserial primary key,
    mode      text not null,
    serial    text,
    customer  text not null,
    subject   text not null,
    joint     text,
    status    text not null default 'open',      -- open 新投诉 / doing 处理中 / closed 已关闭
    created   timestamptz not null default now(),
    field_day date,
    by_name   text,
    proposal  text,
    job_id    bigint,
    score     int,
    comment   text
);
create table if not exists rf_job (
    id        bigserial primary key,
    mode      text not null,
    serial    text not null,
    kind      text not null,                     -- recalib 远程重新标定 / swap 上门换关节模组 / lube 上门补润滑脂
    joint     text,
    status    text not null default 'planned',   -- planned 已派工 / done 已完成
    engineer  text,
    plan_day  date,
    done_day  date,
    cost      jsonb,
    complaint_id bigint,
    by_name   text,
    note      text,
    spare_pid text,
    created   timestamptz not null default now()
);
create table if not exists rf_state (
    mode  text primary key,
    state jsonb not null default '{}'
);
"""

JOINTS = ("J1", "J2", "J3", "J4", "J5", "J6")
JOINT_SIZE = ("L", "L", "M", "S", "S", "S")
JOINT_ITEM = {"L": "WQJ-L", "M": "WQJ-M", "S": "WQJ-S"}
BACKLASH_NOM = {"L": 0.6, "M": 0.6, "S": 0.7}           # 出厂背隙名义值（arcmin，清单的关节测试特性）
BACKLASH_LIM = {"L": 1.0, "M": 1.0, "S": 1.2}           # 上限
WEAR_PER_H = {"L": 2.6e-5, "M": 2.2e-5, "S": 2.4e-5}    # 正常批次每运行小时背隙增长（arcmin/h，示例：约 15000 h 到上限）
BAD_FACTOR = 6.0                                        # 问题批次磨得快（示例）
CURRENT_NOM = {"L": 3.0, "M": 2.0, "S": 1.0}            # 电流均方根名义值 A（示例）
TEMP_LIMIT = 70.0                                       # 关节温度峰值上限 ℃
LUBE_DAYS = 540                                         # 润滑脂寿命（现场日，示例）：过了温度慢慢升
WARN_FRAC = 0.9                                         # 背隙到上限的 90% 预警
DAYS_PER_MIN = float(os.environ.get("WQ_FIELD_DAYS_PER_MIN", "1"))
MAX_DAYS_PER_TICK = 30
KEEP_DAYS = 180
# 客户现场（示例）：每天运行小时、负载系数、碰撞率（每天）
SITES = [{"hours": 16, "load": 0.8, "collide": 0.03, "what": "汽车零部件装配线上下料"},
         {"hours": 10, "load": 0.5, "collide": 0.02, "what": "电子装配线螺丝锁付"},
         {"hours": 20, "load": 0.9, "collide": 0.06, "what": "仓储中心拆码垛"}]
# 情景开始前已经在用的 8 台（示例）：(客户序号, 出厂距今天数, 有问题批次的关节)
SEED = [(0, 420, None), (0, 300, "J2"), (0, 120, None), (1, 520, None), (1, 200, None), (2, 380, "J2"), (2, 260, None), (2, 90, None)]
SEED_BAD_LOT = "HD-L-SEED-07"
ENGINEERS = [("SE01", "柯明"), ("SE02", "孟夏"), ("SE03", "葛川"), ("SE04", "黎音")]     # 服务工程师（示例，虚构）
KIND = {"recalib": "远程重新标定", "swap": "上门换关节模组", "lube": "上门补润滑脂"}
COST = {"recalib": {"labor": 150.0, "travel": 0.0}, "swap": {"labor": 600.0, "travel": 200.0}, "lube": {"labor": 300.0, "travel": 200.0}}
STATUS = {"open": "新投诉", "doing": "处理中", "closed": "已关闭"}
JOB_STATUS = {"planned": "已派工", "done": "已完成"}


def robot_items():
    """有关节模组的成品（物料清单里有 WQJ- 开头的子件）"""
    return [k for k in F.PRODUCTS if any(str(c).startswith("WQJ-") for c, _ in (F.BOMS.get(k) or ("", []))[1])]


def enabled():
    return bool(robot_items())


def init(db):
    if getattr(db, "_rf_ready", False):
        return
    db.x(SCHEMA)
    try:
        db._rf_ready = True
    except AttributeError:
        pass


def _state(db, mode):
    init(db)
    r = db.one("select state from rf_state where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _patch(db, mode, d):
    db.x("insert into rf_state (mode, state) values (%s,%s) on conflict (mode) do update set state=rf_state.state || excluded.state", (mode, Jsonb(d)))


def field_today(db, mode):
    """现场日：从第一次用起，每 1/DAYS_PER_MIN 分钟真实时间过一天"""
    st = _state(db, mode)
    return dt.date.fromisoformat(st["day"]) if st.get("day") else dt.date.today()


def customers():
    return list(F.CUSTOMERS)


def _rng(*k):
    return random.Random(zlib.crc32("|".join(str(x) for x in k).encode()))


# ---------------------------------------------------------------- 建档
def _joint(j, size, serial, lot, backlash, bad):
    return {"joint": j, "size": size, "item": JOINT_ITEM[size], "serial": serial, "lot": lot, "backlash0": round(float(backlash), 3),
            "limit": BACKLASH_LIM[size], "bad": bool(bad)}


def _bad_lots(db, mode):
    """来料里“其实有问题”的批次、被判不合格 / 可疑 / 退货的批次"""
    try:
        return {r["lot"] for r in db.q("select lot from lot where mode=%s and lot is not null and (truth_bad or status in ('rejected','suspect','returned'))",
                                        (mode,))}
    except Exception:  # noqa: BLE001
        return set()


def _init_state(as_built):
    return {"run_h": 0.0, "lube_day": 0, "collisions": 0, "joints": [{"joint": j["joint"], "wear": 0.0, "backlash": j["backlash0"]} for j in as_built["joints"]],
            "recalib_needed": False}


def seed(db, mode):
    """情景开始前已经在用的 8 台（示例）"""
    init(db)
    if not enabled() or db.one("select 1 as x from rf_robot where mode=%s and seeded limit 1", (mode,)):
        return False
    today = field_today(db, mode)
    cs = customers()
    item = robot_items()[0]
    for i, (ci, age, bad_j) in enumerate(SEED):
        serial = "{}-F{:03d}".format(item, i + 1)
        rng = _rng("seed", serial)
        joints = []
        for j, size in zip(JOINTS, JOINT_SIZE):
            bad = j == bad_j
            lot = SEED_BAD_LOT if bad else "HD-{}-SEED-{:02d}".format(size, 1 + (i + JOINTS.index(j)) % 5)
            joints.append(_joint(j, size, "{}-{}".format(serial, j), lot, rng.gauss(BACKLASH_NOM[size], 0.05), bad))
        ab = {"joints": joints, "cr_abs": round(rng.gauss(0.12, 0.015), 3), "source": "情景开始前已在用（示例）"}
        start = today - dt.timedelta(days=age)
        st = _init_state(ab)
        db.x("insert into rf_robot (serial, mode, item, customer, status, seeded, start_day, last_day, as_built, state) "
             "values (%s,%s,%s,%s,'field',true,%s,%s,%s,%s) on conflict do nothing",
             (serial, mode, item, cs[ci % len(cs)], start, start, Jsonb(ab), Jsonb(st)))
        advance_one(db, mode, serial, age, store_from=today - dt.timedelta(days=60))
    return True


def scan(db, mode):
    """读车间消息：关节测试台测过的关节进备用池；整机标定做完的机器人建档（关节按规格先进先出配）"""
    init(db)
    st = _state(db, mode)
    last = int(st.get("seq") or 0)
    rows = db.q("select seq, corr, payload from bus_message where mode=%s and type='quality.measurement' and seq > %s "
                "and payload->'data'->>'characteristic' in ('joint_backlash','cr_abs') order by seq limit 2000", (mode, last))
    if not rows:
        return []
    made = []
    bad_lots = None
    for r in rows:
        d = r["payload"]["data"]
        last = r["seq"]
        if d["characteristic"] == "joint_backlash":
            db.x("insert into rf_pool (mode, serial, item, lot, backlash, seq) values (%s,%s,%s,%s,%s,%s) on conflict do nothing",
                 (mode, d["part_serial"], d.get("item"), d.get("lot"), float(d["value_mm"]), r["seq"]))
            continue
        serial = d["part_serial"]
        if db.one("select 1 as x from rf_robot where mode=%s and serial=%s", (mode, serial)):
            continue
        if bad_lots is None:
            bad_lots = _bad_lots(db, mode)
        rng = _rng("built", serial)
        joints = []
        for j, size in zip(JOINTS, JOINT_SIZE):
            p = db.one("select * from rf_pool where mode=%s and item=%s and used_by is null order by seq limit 1", (mode, JOINT_ITEM[size]))
            if p:
                db.x("update rf_pool set used_by=%s where mode=%s and serial=%s", (serial, mode, p["serial"]))
                b0 = float(p["backlash"])
                bad = (p["lot"] in bad_lots) or b0 > BACKLASH_NOM[size] + 0.15
                joints.append(_joint(j, size, p["serial"], p["lot"], b0, bad))
            else:
                joints.append(_joint(j, size, "{}-{}".format(serial, j), None, rng.gauss(BACKLASH_NOM[size], 0.05), False))
        ab = {"joints": joints, "cr_abs": round(float(d["value_mm"]), 4), "calib": d.get("calib"), "source": "车间"}
        db.x("insert into rf_robot (serial, mode, item, wo, status, as_built, state) values (%s,%s,%s,%s,'built',%s,%s) on conflict do nothing",
             (serial, mode, d.get("item"), d.get("work_order") or r["corr"], Jsonb(ab), Jsonb(_init_state(ab))))
        made.append(serial)
    _patch(db, mode, {"seq": last})
    return made


def ship(db, mode):
    """出厂待发的机器人：它的工单所属销售订单开了票 = 发到客户现场"""
    from hub import finance as FN
    rows = db.q("select * from rf_robot where mode=%s and status='built'", (mode,))
    if not rows:
        return []
    so_of = {}
    for so, ws in FN.wo_by_so(db, mode).items():
        for w in ws:
            so_of[w["data"]["name"]] = so
    billed = {r["ref"] for r in db.q("select ref from invoice where mode=%s and kind='ar' and ref is not null", (mode,))} if \
        db.one("select to_regclass('invoice') is not null as ok")["ok"] else set()
    out = []
    today = field_today(db, mode)
    for r in rows:
        so = so_of.get(r["wo"])
        if not so or so not in billed:
            continue
        doc = FN.so_doc(db, mode, so) or {"data": {}}
        cust = doc["data"].get("customer") or customers()[0]
        db.x("update rf_robot set status='field', sales_order=%s, customer=%s, start_day=%s, last_day=%s where mode=%s and serial=%s",
             (so, cust, today, today, mode, r["serial"]))
        out.append(r["serial"])
    return out


# ---------------------------------------------------------------- 现场模拟
def _site(customer):
    cs = customers()
    i = cs.index(customer) if customer in cs else zlib.crc32(str(customer).encode()) % len(SITES)
    return SITES[i % len(SITES)]


def day_summary(serial, ab, st, site, day):
    """这一天的运行摘要（改 st）"""
    rng = _rng("day", serial, day.isoformat())
    hours = max(0.0, site["hours"] * rng.uniform(0.85, 1.05))
    st["run_h"] = st.get("run_h", 0.0) + hours
    st["lube_day"] = st.get("lube_day", 0) + 1
    hit = 1 if rng.random() < site["collide"] else 0
    st["collisions"] = st.get("collisions", 0) + hit
    if hit and rng.random() < 0.05:
        st["recalib_needed"] = True                 # 撞得重的一下：零位偏了，定位不准，要重新标定
    lube_over = max(0, st["lube_day"] - LUBE_DAYS)
    joints = []
    for jd, js in zip(ab["joints"], st["joints"]):
        rate = WEAR_PER_H[jd["size"]] * (BAD_FACTOR if jd.get("bad") else 1.0) * (0.6 + 0.5 * site["load"]) * (1.3 if lube_over else 1.0)
        js["wear"] = js.get("wear", 0.0) + rate * hours
        js["backlash"] = round(jd["backlash0"] + js["wear"] + rng.gauss(0, 0.005), 4)
        frac = max(0.0, (js["backlash"] - jd["backlash0"]) / max(1e-6, jd["limit"] - jd["backlash0"]))
        temp = 32 + 18 * site["load"] * (1.0 if jd["size"] == "L" else 0.8) + 0.02 * lube_over + 6 * frac + rng.gauss(0, 0.8)
        cur = CURRENT_NOM[jd["size"]] * (0.7 + 0.4 * site["load"]) * (1 + 0.25 * frac) * rng.uniform(0.97, 1.03)
        joints.append({"joint": jd["joint"], "backlash": js["backlash"], "limit": jd["limit"], "temp_max": round(temp, 1), "i_rms": round(cur, 2)})
    return {"day": day.isoformat(), "run_h": round(hours, 1), "collisions": hit, "joints": joints, "recalib_needed": bool(st.get("recalib_needed")),
            "lube_days": st["lube_day"]}


def advance_one(db, mode, serial, days, store_from=None):
    r = db.one("select * from rf_robot where mode=%s and serial=%s", (mode, serial))
    if not r or r["status"] != "field" or days <= 0:
        return 0
    ab, st, site = r["as_built"], r["state"], _site(r["customer"])
    day = r["last_day"]
    for _ in range(int(days)):
        day = day + dt.timedelta(days=1)
        s = day_summary(serial, ab, st, site, day)
        if store_from is None or day >= store_from:
            db.x("insert into rf_day (mode, serial, day, data) values (%s,%s,%s,%s) on conflict (mode, serial, day) do update set data=excluded.data",
                 (mode, serial, day, Jsonb(s)))
    db.x("update rf_robot set state=%s, last_day=%s where mode=%s and serial=%s", (Jsonb(st), day, mode, serial))
    db.x("delete from rf_day where mode=%s and serial=%s and day < %s", (mode, serial, day - dt.timedelta(days=KEEP_DAYS)))
    return int(days)


def advance(db, mode, days):
    """现场时钟往前走 days 天：每台在现场的机器人各出 days 条摘要"""
    init(db)
    days = int(days)
    if days <= 0:
        return 0
    today = field_today(db, mode) + dt.timedelta(days=days)
    _patch(db, mode, {"day": today.isoformat()})
    for r in db.q("select serial, last_day from rf_robot where mode=%s and status='field'", (mode,)):
        advance_one(db, mode, r["serial"], (today - r["last_day"]).days)
    return days


# ---------------------------------------------------------------- 健康、预警
def latest(db, mode, serial):
    r = db.one("select data from rf_day where mode=%s and serial=%s order by day desc limit 1", (mode, serial))
    return r["data"] if r else None


def health(ab, last, collisions_7d=0):
    """绿 / 黄 / 红 + 原因"""
    if not last:
        return "green", []
    why, level = [], "green"
    for j, jd in zip(last["joints"], ab["joints"]):
        if j["backlash"] > j["limit"]:
            why.append({"joint": j["joint"], "kind": "backlash", "text": "{} 背隙 {:.2f}′ 超过上限 {:g}′".format(j["joint"], j["backlash"], j["limit"]),
                        "lot": jd.get("lot"), "bad_lot": jd.get("bad"), "over": True})
            level = "red"
        elif j["backlash"] > WARN_FRAC * j["limit"]:
            why.append({"joint": j["joint"], "kind": "backlash", "text": "{} 背隙 {:.2f}′ 接近上限 {:g}′".format(j["joint"], j["backlash"], j["limit"]),
                        "lot": jd.get("lot"), "bad_lot": jd.get("bad")})
            level = "yellow" if level == "green" else level
        if j["temp_max"] > TEMP_LIMIT:
            why.append({"joint": j["joint"], "kind": "temp", "text": "{} 温度峰值 {:.0f} ℃ 超过 {:g} ℃（润滑脂老化？）".format(j["joint"], j["temp_max"], TEMP_LIMIT)})
            level = "yellow" if level == "green" else level
    if collisions_7d >= 3:
        why.append({"joint": None, "kind": "collision", "text": "近 7 天碰撞 {} 次（零位可能偏了）".format(collisions_7d)})
        level = "yellow" if level == "green" else level
    if last.get("recalib_needed"):
        why.append({"joint": None, "kind": "recalib", "text": "撞过一次重的：定位精度下降，建议远程重新标定"})
        level = "yellow" if level == "green" else level
    return level, why


def _coll_7d(db, mode, serial):
    r = db.one("select coalesce(sum((data->>'collisions')::int),0) as n from (select data from rf_day where mode=%s and serial=%s "
               "order by day desc limit 7) t", (mode, serial))
    return int(r["n"] or 0)


def fleet(db, mode):
    init(db)
    seed(db, mode)
    out = []
    for r in db.q("select * from rf_robot where mode=%s order by status desc, serial", (mode,)):
        last = latest(db, mode, r["serial"])
        lv, why = health(r["as_built"], last, _coll_7d(db, mode, r["serial"]))
        worst = max(last["joints"], key=lambda j: j["backlash"] / j["limit"]) if last else None
        out.append({"serial": r["serial"], "item": r["item"], "customer": r["customer"], "status": r["status"], "seeded": r["seeded"],
                    "wo": r["wo"], "sales_order": r["sales_order"], "start_day": r["start_day"].isoformat() if r["start_day"] else None,
                    "last_day": r["last_day"].isoformat() if r["last_day"] else None, "run_h": round(r["state"].get("run_h", 0.0)),
                    "health": lv, "why": why, "worst": worst, "cr_abs": r["as_built"].get("cr_abs"),
                    "site": _site(r["customer"])["what"] if r["customer"] else None})
    return out


def detail(db, mode, serial, days=120):
    r = db.one("select * from rf_robot where mode=%s and serial=%s", (mode, serial))
    if not r:
        raise KeyError(serial)
    rows = db.q("select data from rf_day where mode=%s and serial=%s and day > %s order by day", (mode, serial, (r["last_day"] or dt.date.today()) - dt.timedelta(days=days)))
    last = rows[-1]["data"] if rows else None
    lv, why = health(r["as_built"], last, _coll_7d(db, mode, serial))
    same = []
    for j in r["as_built"]["joints"]:
        if j.get("lot"):
            n = db.one("select count(*) as n from rf_robot where mode=%s and serial<>%s and as_built->'joints' @> %s", (mode, serial, Jsonb([{"lot": j["lot"]}])))["n"]
            same.append({"joint": j["joint"], "lot": j["lot"], "others": n})
    return {"serial": serial, "item": r["item"], "customer": r["customer"], "status": r["status"], "as_built": r["as_built"], "wo": r["wo"],
            "sales_order": r["sales_order"], "health": lv, "why": why, "series": [x["data"] for x in rows], "same_lot": same,
            "jobs": [job_row(x) for x in db.q("select * from rf_job where mode=%s and serial=%s order by id desc", (mode, serial))],
            "site": _site(r["customer"]) if r["customer"] else None, "run_h": round(r["state"].get("run_h", 0.0))}


def alarms(db, mode):
    """在现场、健康为黄或红的机器人（规则 RS1 读这里）"""
    return [x for x in fleet(db, mode) if x["status"] == "field" and x["health"] != "green"]


# ---------------------------------------------------------------- 投诉、工单
def suggest(why):
    """按报警原因给服务方案"""
    kinds = {w["kind"] for w in why}
    if "backlash" in kinds:
        j = next(w["joint"] for w in why if w["kind"] == "backlash")
        return "swap", j
    if "temp" in kinds:
        return "lube", next(w["joint"] for w in why if w["kind"] == "temp")
    if kinds & {"collision", "recalib"}:
        return "recalib", None
    return "recalib", None


def create_complaint(H, mode, body, who):
    db = H.db
    init(db)
    serial = (body.get("serial") or "").strip() or None
    r = db.one("select customer from rf_robot where mode=%s and serial=%s", (mode, serial)) if serial else None
    customer = (body.get("customer") or "").strip() or (r or {}).get("customer")
    subject = (body.get("subject") or "").strip()
    if not subject:
        raise ValueError("写一句投诉的现象，例如“J2 异响、定位不准”")
    if not customer:
        raise ValueError("填客户，或填机器人序列号（会自动带出客户）")
    x = db.one("insert into rf_complaint (mode, serial, customer, subject, joint, field_day, by_name) values (%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, serial, customer, subject[:200], body.get("joint"), field_today(db, mode), who))
    cid = x["id"]
    if getattr(H, "ai", None) is not None:
        pid = H.ai.propose("complaint_issue", {"complaint_id": cid, "subject": "【投诉】{}：{}".format(customer, subject)[:140], "serial": serial,
                                                "customer": customer, "description": body.get("detail") or ""},
                           mode, who, "投诉 RC-{:05d} 进 ERPNext".format(cid), source="rfield")
        H.ai.decide(pid, who, True)
        db.x("update rf_complaint set proposal=%s where id=%s", (pid, cid))
    return cid


def _issue_name(db, pid):
    if not pid:
        return None
    r = db.one("select result from ai_proposal where proposal_id=%s", (pid,))
    res = (r or {}).get("result") or {}
    return next((n for d, n in res.get("created") or [] if d == "Issue"), None)


def complaint_row(db, c):
    return {"id": c["id"], "key": "RC-{:05d}".format(c["id"]), "serial": c["serial"], "customer": c["customer"], "subject": c["subject"],
            "joint": c["joint"], "status": c["status"], "status_label": STATUS.get(c["status"], c["status"]),
            "field_day": c["field_day"].isoformat() if c["field_day"] else None, "issue": _issue_name(db, c["proposal"]),
            "job_id": c["job_id"], "score": c["score"], "comment": c["comment"]}


def complaints(db, mode):
    init(db)
    return [complaint_row(db, c) for c in db.q("select * from rf_complaint where mode=%s order by id desc limit 200", (mode,))]


def _engineer(db, mode, day):
    busy = {r["engineer"] for r in db.q("select engineer from rf_job where mode=%s and plan_day=%s and kind<>'recalib'", (mode, day))}
    return next((e for e, _ in ENGINEERS if e not in busy), None)


def plan_job(H, mode, serial, kind, who, joint=None, complaint_id=None):
    """派工：远程标定当天；上门的排给当天或之后第一个有空的工程师"""
    db = H.db
    init(db)
    if kind not in KIND:
        raise ValueError("服务方案只能是：" + "、".join(KIND.values()))
    r = db.one("select * from rf_robot where mode=%s and serial=%s", (mode, serial))
    if not r:
        raise KeyError(serial)
    if kind == "swap" and joint not in JOINTS:
        raise ValueError("换哪个关节（J1–J6）？")
    day = field_today(db, mode)
    eng = "远程" if kind == "recalib" else None
    for k in range(14):
        if eng:
            break
        eng = _engineer(db, mode, day + dt.timedelta(days=k + 1))
        if eng:
            day = day + dt.timedelta(days=k + 1)
    cost = dict(COST[kind])
    if kind == "swap":
        size = JOINT_SIZE[JOINTS.index(joint)]
        cost["parts"] = float(F.PRODUCTS.get(JOINT_ITEM[size]) or 0)
    x = db.one("insert into rf_job (mode, serial, kind, joint, engineer, plan_day, cost, complaint_id, by_name) values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
               (mode, serial, kind, joint, eng, day, Jsonb(cost), complaint_id, who))
    if complaint_id:
        db.x("update rf_complaint set status='doing', job_id=%s where id=%s and mode=%s", (x["id"], complaint_id, mode))
    return x["id"]


def complete_job(H, mode, jid, who, note=""):
    db = H.db
    j = db.one("select * from rf_job where mode=%s and id=%s", (mode, jid))
    if not j:
        raise KeyError(jid)
    if j["status"] == "done":
        return job_row(j)
    r = db.one("select * from rf_robot where mode=%s and serial=%s", (mode, j["serial"]))
    ab, st = r["as_built"], r["state"]
    pid = None
    if j["kind"] == "swap":
        i = JOINTS.index(j["joint"])
        size = JOINT_SIZE[i]
        p = db.one("select * from rf_pool where mode=%s and item=%s and used_by is null order by seq limit 1", (mode, JOINT_ITEM[size]))
        if p:
            db.x("update rf_pool set used_by=%s where mode=%s and serial=%s", (j["serial"], mode, p["serial"]))
            new = _joint(j["joint"], size, p["serial"], p["lot"], float(p["backlash"]), p["lot"] in _bad_lots(db, mode))
        else:
            new = _joint(j["joint"], size, "SP-{}-{}".format(j["serial"], jid), "备件库存", BACKLASH_NOM[size], False)
        new["replaced"] = {"serial": ab["joints"][i]["serial"], "lot": ab["joints"][i]["lot"], "backlash0": ab["joints"][i]["backlash0"],
                           "day": field_today(db, mode).isoformat()}
        ab["joints"][i] = new
        st["joints"][i] = {"joint": j["joint"], "wear": 0.0, "backlash": new["backlash0"]}
        if getattr(H, "ai", None) is not None:
            from hub import service as SV
            try:
                pid = SV.ship_spares(H, mode, [{"item_code": JOINT_ITEM[size], "qty": 1}], who, "现场机器人 {} 换 {}".format(j["serial"], j["joint"]))
            except Exception:  # noqa: BLE001
                log.exception("备件出库没发出去")
    elif j["kind"] == "lube":
        st["lube_day"] = 0
    st["recalib_needed"] = False                        # 上门、远程做完都重新标定一遍
    db.x("update rf_robot set as_built=%s, state=%s where mode=%s and serial=%s", (Jsonb(ab), Jsonb(st), mode, j["serial"]))
    db.x("update rf_job set status='done', done_day=%s, note=%s, spare_pid=%s where id=%s", (field_today(db, mode), note or "按服务规程完成", pid, jid))
    if j["complaint_id"]:
        db.x("update rf_complaint set status='closed' where id=%s and mode=%s", (j["complaint_id"], mode))
    return job_row(db.one("select * from rf_job where id=%s", (jid,)))


def _job(serial, kind, joint=None):
    c = dict(COST[kind])
    if kind == "swap":
        c["parts"] = float(F.PRODUCTS.get(JOINT_ITEM[JOINT_SIZE[JOINTS.index(joint)]]) or 0)
    return {"serial": serial, "kind": kind, "joint": joint, "cost_usd": round(sum(c.values()), 2)}


def _opt(key, label, note, jobs, rec):
    cost = round(sum(j["cost_usd"] for j in jobs), 2)
    ch = [{"type": "robot_service", "jobs": jobs}] if jobs else []
    return {"key": key, "kind": "robot_service" if jobs else "none", "label": label, "note": note, "changes": ch, "recommended": rec,
            "result": {"sales_orders": [], "cost_total": cost, "costs": [{"what": "服务费用（人工、差旅、备件）", "usd": cost}] if cost else [],
                       "overtime_min": 0, "checks": [], "ok": True}}


def anomaly_options(db, mode, a):
    """第 67 轮：RS1（一台报警）、RS2（同批多台报警）的处理方案——派工三种，或暂不处理"""
    init(db)
    v = ((a.get("detail") or {}).get("values") or {})
    if a["rule"] == "RS2":
        lot = v.get("lot") or a.get("subject_key")
        rows = [r for r in db.q("select serial, as_built from rf_robot where mode=%s and status='field'", (mode,))
                if any(j.get("lot") == lot for j in r["as_built"]["joints"])]
        al = set(v.get("serials") or [])
        hit = [(r["serial"], next(j["joint"] for j in r["as_built"]["joints"] if j.get("lot") == lot)) for r in rows]
        all_jobs = [_job(s, "swap", j) for s, j in hit]
        only = [_job(s, "swap", j) for s, j in hit if s in al]
        out = [_opt("A", "同批全部换（预防性）：{} 台".format(len(all_jobs)), "用了 {} 的关节都换，报警的和还没报警的一起".format(lot), all_jobs, True),
               _opt("B", "只换报警的 {} 台".format(len(only)), "其余同批的等报警了再说（会陆续出问题）", only, False),
               _opt("C", "暂不处理", "客户会陆续投诉", [], False)]
        return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：同一批磨得快，没报警的迟早也会到上限；一次排工比一台台被投诉划算", "service": True}
    serial = a.get("subject_key")
    r = db.one("select * from rf_robot where mode=%s and serial=%s", (mode, serial))
    if not r:
        raise KeyError(serial)
    lv, why = health(r["as_built"], latest(db, mode, serial), _coll_7d(db, mode, serial))
    kind, joint = suggest(why)
    label = {"swap": "上门换关节模组 {}".format(joint), "lube": "上门补润滑脂", "recalib": "远程重新标定"}
    out = [_opt("A", label[kind], "；".join(w["text"] for w in why) or "按报警原因", [_job(serial, kind, joint)], True)]
    for k in ("recalib", "lube", "swap"):
        if k != kind and len(out) < 3:
            j = joint or ("J1" if k == "swap" else None)
            out.append(_opt(chr(ord("A") + len(out)), label[k] if k != "swap" else "上门换关节模组 {}".format(j), "不对症时只是花钱", [_job(serial, k, j)], False))
    out.append(_opt(chr(ord("A") + len(out)), "暂不处理", "继续观察", [], False))
    return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：对症（{}）".format(why[0]["text"] if why else "报警原因"), "service": True}


def job_row(j):
    c = j["cost"] or {}
    return {"id": j["id"], "key": "RS-{:05d}".format(j["id"]), "serial": j["serial"], "kind": j["kind"], "kind_label": KIND[j["kind"]], "joint": j["joint"],
            "status": j["status"], "status_label": JOB_STATUS.get(j["status"], j["status"]), "engineer": dict(ENGINEERS).get(j["engineer"], j["engineer"]),
            "plan_day": j["plan_day"].isoformat() if j["plan_day"] else None, "done_day": j["done_day"].isoformat() if j["done_day"] else None,
            "cost_usd": round(sum(float(v) for v in c.values()), 2), "cost": c, "complaint_id": j["complaint_id"], "note": j["note"]}


def jobs(db, mode):
    init(db)
    return [job_row(j) for j in db.q("select * from rf_job where mode=%s order by id desc limit 200", (mode,))]


def score(db, mode, cid, sc, comment, who):
    if not 1 <= int(sc) <= 5:
        raise ValueError("满意度 1–5 分")
    db.x("update rf_complaint set score=%s, comment=%s where id=%s and mode=%s", (int(sc), (comment or "")[:500], cid, mode))
    return {"id": cid, "score": int(sc)}


def kpis(db, mode):
    init(db)
    fl = fleet(db, mode)
    sc = db.one("select avg(score) as s, count(score) as n from rf_complaint where mode=%s", (mode,))
    return {"in_field": sum(1 for x in fl if x["status"] == "field"), "built": sum(1 for x in fl if x["status"] == "built"),
            "red": sum(1 for x in fl if x["health"] == "red"), "yellow": sum(1 for x in fl if x["health"] == "yellow"),
            "complaints": db.one("select count(*) as n from rf_complaint where mode=%s", (mode,))["n"],
            "open_complaints": db.one("select count(*) as n from rf_complaint where mode=%s and status<>'closed'", (mode,))["n"],
            "open_jobs": db.one("select count(*) as n from rf_job where mode=%s and status<>'done'", (mode,))["n"],
            "satisfaction": round(float(sc["s"]), 2) if sc["s"] is not None else None, "field_day": field_today(db, mode).isoformat()}


# ---------------------------------------------------------------- 教学模拟器
def tick(H, mode, now=None, rng=None):
    """教学模式：建档、发出；现场时钟往前走；红色的机器人客户来投诉（每台一次）；派过的上门单到日子由工程师做完；做完的打满意度"""
    if mode != "teach" or not enabled():
        return {}
    db = H.db
    init(db)
    seed(db, mode)
    rng = rng or random.Random()
    now = now or time.time()
    out = {"built": scan(db, mode), "shipped": ship(db, mode), "days": 0, "complaints": [], "done": []}
    st = _state(db, mode)
    last = float(st.get("tick_at") or 0)
    if not last:
        _patch(db, mode, {"tick_at": now})
        return out
    days = min(MAX_DAYS_PER_TICK, int((now - last) / 60.0 * DAYS_PER_MIN))
    if days >= 1:
        out["days"] = advance(db, mode, days)
        _patch(db, mode, {"tick_at": last + days * 60.0 / DAYS_PER_MIN})
    today = field_today(db, mode)
    for x in alarms(db, mode):                                   # 背隙超限：客户发现了，来投诉（每台只来一次，没关闭前不重复）
        if x["health"] != "red" or db.one("select 1 as x from rf_complaint where mode=%s and serial=%s and status<>'closed'", (mode, x["serial"])):
            continue
        j = next((w["joint"] for w in x["why"] if w["kind"] == "backlash"), None)
        out["complaints"].append(create_complaint(H, mode, {"serial": x["serial"], "joint": j,
                                                            "subject": "{} 有异响，抓取位置偏了".format(j or "机器人")}, "客户（教学模拟器）"))
    for j in db.q("select * from rf_job where mode=%s and status='planned' and plan_day <= %s", (mode, today)):
        out["done"].append(complete_job(H, mode, j["id"], "服务工程师（教学模拟器）")["id"])
    for c in db.q("select c.id, j.done_day, c.field_day from rf_complaint c join rf_job j on j.id=c.job_id where c.mode=%s and c.status='closed' "
                  "and c.score is null and j.done_day is not null", (mode,)):
        wait = (c["done_day"] - c["field_day"]).days
        score(db, mode, c["id"], 5 if wait <= 2 else (4 if wait <= 5 else 3), "回访（教学模拟器）：处理用了 {} 个现场日".format(wait), "回访（教学模拟器）")
    return out


def reset(db, mode):
    init(db)
    for t in ("rf_robot", "rf_day", "rf_pool", "rf_complaint", "rf_job", "rf_state"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    seed(db, mode)
