# -*- coding: utf-8 -*-
"""能源与环境（第 18 轮 E6）：计量点、读数入库、分时电费、需量、碳核算、车间环境、单件能耗与空转；
节能设定（自动待机）、错峰；教学模拟器（下班忘关、漏气、劣化、峰时开炉、油雾收集器故障）。

数据都在平台自己的表（E6-1），不进 ERPNext：
- 教学模式由仿真车间按设备状态和功率每 15 分钟（工厂时间）发一个读数（energy.reading，sim/energy.py）；
- 生产模式默认不计量（以后接电表网关或导入 CSV，写进同一张 energy_read）。
读数的时间是工厂时间（教学模式车间可能倍速运行），“现在”按 people.factory_now。"""
import datetime as dt
import logging
import random

from psycopg.types.json import Jsonb

from sim import energy as EN

log = logging.getLogger("energy")

SCHEMA = """
create table if not exists meter (
    mode    text not null,
    code    text not null,
    medium  text not null,
    unit    text not null,
    machine text,
    label   text not null,
    primary key (mode, code)
);
create table if not exists energy_read (
    mode    text not null,
    meter   text not null,
    ts      timestamptz not null,
    seconds real not null,
    value   double precision not null,
    kw      double precision,
    bucket  text,
    s       jsonb,
    k       jsonb,
    parts   jsonb,
    primary key (mode, meter, ts)
);
create index if not exists energy_read_ts on energy_read (mode, ts);
create table if not exists env_read (
    mode    text not null,
    point   text not null,
    ts      timestamptz not null,
    value   double precision not null,
    primary key (mode, point, ts)
);
create table if not exists energy_param (
    mode    text not null,
    key     text not null,
    value   jsonb not null,
    primary key (mode, key)
);
create table if not exists energy_sim (
    mode    text primary key,
    state   jsonb not null default '{}'::jsonb
);
"""

UNIT_NAME = {"saw-01": "带锯床", "cnc-l01-a": "数控车床 A", "cnc-l01-b": "数控车床 B", "vmc-01": "立式加工中心", "hmc-01": "卧式加工中心",
             "key-01": "键槽铣床", "hob-01": "滚齿机", "ht-01": "热处理炉", "grd-01": "外圆磨床", "qc-01": "检验站", "asm-01": "装配工位",
             "test-01": "跑合试验台"}
try:                                    # 第 59 轮：清单写了产品的厂（机器人厂等）：设备名取清单
    from factory import equip as _EQ
    _E = _EQ.active()
except ImportError:
    _E = None
if _E:
    UNIT_NAME = {u: d["name"] for u, d in _E.items()}
# 教学模拟器挑哪几台出问题：下班忘关（晚班没岗位的设备）、劣化（主力加工设备）
FORGOT_UNITS = [u for u in (["hmc-01", "hob-01", "key-01", "vmc-01"] if not _E else [u for u, d in _E.items() if not d["auto"]]) if u in EN.POWER]
DEGRADE_UNITS = [u for u in (["grd-01", "cnc-l01-a", "vmc-01"] if not _E else [u for u, d in _E.items() if d["kind"] in ("lathe", "mc", "grinder")])
                 if u in EN.POWER] or list(EN.POWER)[:1]
NOISY_UNITS = sorted(EN.NOISE, key=lambda u: -EN.NOISE[u])[:2] if _E else ["saw-01", "grd-01"]
METERS = [(EN.meter_of(u), "电", "kWh", u, "{} 电表".format(UNIT_NAME[u])) for u in EN.POWER] + [
    ("E-AIR", "电", "kWh", None, "空压机电表"), ("E-TOTAL", "电", "kWh", None, "车间总表"),
    ("F-AIR", "压缩空气", "m³", None, "压缩空气流量计"), ("W-MAIN", "水", "m³", None, "自来水总表"),
    ("ENV-MIST", "油雾", "mg/m³", None, "机加区油雾监测点"), ("ENV-NOISE", "噪声", "dB(A)", None, "车间噪声监测点")]
ENV_POINTS = {"mist": ("机加区油雾", "mg/m³"), "noise": ("车间噪声", "dB(A)")}
PARAMS = {
    "price": {"peak": 0.15, "flat": 0.10, "valley": 0.05},     # 分时电价 $/kWh（E6-4）
    "contract_kw": 220.0,                                      # 合同需量（最大 15 分钟平均功率）
    "co2_factor": 0.5306,                                      # 全国电力平均二氧化碳排放因子 kg CO2 / kWh（生态环境部、国家统计局公布的 2023 年度值，可改）
    "mist_limit": 5.0,                                         # 油雾 mg/m³
    "noise_limit": 85.0,                                       # 噪声 dB(A)
}
if _E:                                  # 第 59 轮：合同需量按这座厂设备的运行功率估（示例值）
    PARAMS["contract_kw"] = float(round(sum(v[0] for v in EN.POWER.values()) * 0.7 + 20, -1))
BUCKET_NAME = {"peak": "峰", "flat": "平", "valley": "谷"}
STATE_NAME = {"run": "运行", "idle": "空转", "setup": "调整", "standby": "待机", "off": "关机", "down": "停机"}
FAULT_NAME = {"forgot": "下班忘关", "leak": "压缩空气泄漏", "degrade": "设备劣化（单耗上升）", "ht_peak": "峰时开炉", "mist": "油雾收集器故障"}
STANDBY_UNITS = [u for u in EN.POWER if u not in EN.NO_STANDBY]
PUSH_EVERY_S = 300
AUTO_EVERY_S = 1800              # 教学模拟器：大约每 30 分钟（真实时间）可能出一个问题
AUTO_FIX_S = 7200                # 没人处理的问题 2 小时后由模拟器“修好”（漏气、油雾、劣化）
REPAIR_RATE = 45.0               # 整改 / 维修人工 $/小时（与推演一致）


def init(db):
    db.x(SCHEMA)


def _state(db, mode):
    init(db)
    r = db.one("select state from energy_sim where mode=%s", (mode,))
    return (r or {}).get("state") or {}


def _patch(db, mode, d):
    """只改给出的几个键（和别的线程同时改不同的键时不会互相覆盖）"""
    init(db)
    db.x("insert into energy_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=energy_sim.state || excluded.state", (mode, Jsonb(d)))


def _patch_in(db, mode, key, sub, val):
    """改 state[key][sub]（val=None 删除）"""
    init(db)
    db.x("insert into energy_sim (mode, state) values (%s, '{}'::jsonb) on conflict (mode) do nothing", (mode,))
    if val is None:
        db.x("update energy_sim set state = state || jsonb_build_object(%s::text, coalesce(state->%s, '{}'::jsonb) - %s::text) where mode=%s",
             (key, key, sub, mode))
    else:
        db.x("update energy_sim set state = state || jsonb_build_object(%s::text, coalesce(state->%s, '{}'::jsonb) || jsonb_build_object(%s::text, %s::jsonb)) "
             "where mode=%s", (key, key, sub, Jsonb(val), mode))


def _save_state(db, mode, st):
    db.x("insert into energy_sim (mode, state) values (%s,%s) on conflict (mode) do update set state=excluded.state", (mode, Jsonb(st)))


def seed(db, mode):
    init(db)
    if db.one("select 1 as x from meter where mode=%s limit 1", (mode,)):
        return False
    for code, med, unit, mach, label in METERS:
        db.x("insert into meter (mode, code, medium, unit, machine, label) values (%s,%s,%s,%s,%s,%s) on conflict do nothing",
             (mode, code, med, unit, mach, label))
    return True


def meters(db, mode):
    seed(db, mode)
    return [dict(r, power=list(EN.POWER[r["machine"]]) if r.get("machine") in EN.POWER else None)       # 第 59 轮：功率随工厂变，页面不再写死
            for r in db.q("select * from meter where mode=%s order by code", (mode,))]


def params(db, mode):
    init(db)
    p = {k: (dict(v) if isinstance(v, dict) else v) for k, v in PARAMS.items()}
    for r in db.q("select key, value from energy_param where mode=%s", (mode,)):
        p[r["key"]] = r["value"]
    return p


def set_params(db, mode, body):
    cur = params(db, mode)
    for k in PARAMS:
        if k not in body:
            continue
        v = body[k]
        if k == "price":
            v = {b: float(v.get(b, cur["price"][b])) for b in ("peak", "flat", "valley")}
            if not all(0 <= x <= 5 for x in v.values()):
                raise ValueError("电价应在 0–5 $/kWh 之间")
        else:
            v = float(v)
            if v <= 0:
                raise ValueError("{} 应大于 0".format(k))
        db.x("insert into energy_param (mode, key, value) values (%s,%s,%s) on conflict (mode, key) do update set value=excluded.value",
             (mode, k, Jsonb(v)))
    return params(db, mode)


# ---------------------------------------------------------------- 开关与下发
def measuring(db, mode):
    """计量开没开：教学模式默认一直开（只记数，不改车间）；生产模式默认关（接上真电表后再开）"""
    st = _state(db, mode)
    return bool(st["enabled"]) if "enabled" in st else mode == "teach"


def sim_on(db, mode):
    """教学模拟器（会出问题）：教学模式默认开；情景重载后关；生产模式不模拟"""
    if mode != "teach":
        return False
    st = _state(db, mode)
    return bool(st["sim"]) if "sim" in st else True


def set_sim(db, mode, on):
    _patch(db, mode, {"sim": bool(on)})
    return {"sim": bool(on)}


def settings(db, mode):
    st = _state(db, mode)
    return {"standby": dict(st.get("standby") or {}), "tou": list(st.get("tou") or []), "quiet": list(st.get("quiet") or [])}


def push(H, mode, who="系统", inject=None, clear=None):
    """把开关和节能设定下发给车间（定期重发，车间重启、重载情景后也能对上）"""
    mes = getattr(H, "mes", None)
    if mes is None:
        return None
    on = measuring(H.db, mode)
    s = settings(H.db, mode)
    extra = {}
    if inject:
        extra["inject"] = inject
    if clear:
        extra["clear"] = clear
    mes.command("sim", "set_energy", mode, who, enabled=on, standby=s["standby"] if on else {}, tou=s["tou"] if on else [],
                quiet=s["quiet"], **extra)
    _patch(H.db, mode, {"pushed_at": dt.datetime.now(dt.timezone.utc).timestamp()})
    return {"enabled": on}


def reset(db, mode):
    """情景重置：读数清空；节能设定、错峰、隔声罩回到初始；问题清空；模拟器关闭（老师开始实验后打开）"""
    init(db)
    for t in ("energy_read", "env_read", "energy_sim"):
        db.x("delete from {} where mode=%s".format(t), (mode,))
    _save_state(db, mode, {"sim": False, "standby": {}, "tou": [], "quiet": [], "faults": {}})
    seed(db, mode)


# ---------------------------------------------------------------- 读数
def _ts(s):
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def ingest(db, mode, d):
    """车间（或电表网关）的一条 energy.reading → 每个计量点一行；环境两行"""
    init(db)
    ts, secs = _ts(d["ts"]), float(d["seconds"])
    for code, m in (d.get("meters") or {}).items():
        db.x("insert into energy_read (mode, meter, ts, seconds, value, kw, bucket, s, k, parts) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
             "on conflict (mode, meter, ts) do update set value=excluded.value, kw=excluded.kw, s=excluded.s, k=excluded.k, parts=excluded.parts",
             (mode, code, ts, secs, float(m.get("value") or 0), m.get("kw"), d.get("bucket"), Jsonb(m.get("s") or {}), Jsonb(m.get("k") or {}),
              Jsonb(m.get("parts") or {})))
    for p, v in (d.get("env") or {}).items():
        if p in ENV_POINTS and v is not None:
            db.x("insert into env_read (mode, point, ts, value) values (%s,%s,%s,%s) on conflict (mode, point, ts) do update set value=excluded.value",
                 (mode, p, ts, float(v)))
    if d.get("faults") is not None:
        st = _state(db, mode)
        if st.get("live") != d["faults"]:
            _patch(db, mode, {"live": d["faults"]})


def now_of(db, mode):
    from hub import people as PE
    return PE.factory_now(db, mode)


def latest_ts(db, mode):
    r = db.one("select max(ts) as t from energy_read where mode=%s and meter='E-TOTAL'", (mode,))
    return r["t"] if r else None


def rows(db, mode, meter, t0, t1):
    return db.q("select * from energy_read where mode=%s and meter=%s and ts >= %s and ts < %s order by ts", (mode, meter, t0, t1))


def _end(db, mode, now=None):
    """分析窗口的终点：最新读数的结束（工厂时间）；没有读数就用现在"""
    t = latest_ts(db, mode)
    if t is not None:
        return t + dt.timedelta(minutes=15)
    return now or now_of(db, mode)


def cost_of(rows_, price):
    return sum(float(r["value"]) * float(price.get(r["bucket"] or "flat", price["flat"])) for r in rows_)


def series(db, mode, meter, hours=24, end=None):
    end = end or _end(db, mode)
    rs = rows(db, mode, meter, end - dt.timedelta(hours=hours), end)
    return [{"ts": r["ts"].isoformat(), "value": round(float(r["value"]), 3), "kw": r["kw"], "bucket": r["bucket"],
             "s": r["s"], "k": r["k"]} for r in rs]


def day_bounds(day):
    from hub import kpi
    t0 = dt.datetime(day.year, day.month, day.day, tzinfo=kpi.TZ).astimezone(dt.timezone.utc)
    return t0, t0 + dt.timedelta(days=1)


def overview(db, mode, day=None):
    """某天（工厂本地日）：总表曲线（峰平谷）、电量、电费、峰时占比、碳、每台设备分档电量；本月需量"""
    from hub import kpi
    seed(db, mode)
    p = params(db, mode)
    end = _end(db, mode)
    if day is None:                             # 默认最近一天；刚过半夜（不到 6 小时）就看前一天
        day = (end - dt.timedelta(seconds=1)).astimezone(kpi.TZ).date()
        if (end - day_bounds(day)[0]).total_seconds() < 6 * 3600 and \
                db.one("select 1 as x from energy_read where mode=%s and meter='E-TOTAL' and ts < %s limit 1", (mode, day_bounds(day)[0])):
            day = day - dt.timedelta(days=1)
    t0, t1 = day_bounds(day)
    tot = rows(db, mode, "E-TOTAL", t0, t1)
    by = {b: sum(float(r["value"]) for r in tot if r["bucket"] == b) for b in ("peak", "flat", "valley")}
    kwh = sum(by.values())
    units = []
    for u in EN.POWER:
        rs = rows(db, mode, EN.meter_of(u), t0, t1)
        k = {}
        for r in rs:
            for st_, v in (r["k"] or {}).items():
                k[st_] = k.get(st_, 0.0) + float(v)
        parts = sum(n for r in rs for n, _ in (r["parts"] or {}).values())
        total = sum(float(r["value"]) for r in rs)
        units.append({"unit": u, "name": UNIT_NAME[u], "kwh": round(total, 2), "by_state": {s: round(v, 2) for s, v in k.items()},
                      "idle_share": round(k.get("idle", 0.0) / total, 3) if total else 0.0, "parts": parts,
                      "kwh_per_part": round(total / parts, 3) if parts else None})
    air = sum(float(r["value"]) for r in rows(db, mode, "E-AIR", t0, t1))
    m0 = day_bounds(day.replace(day=1))[0]
    dem = db.one("select max(kw) as kw from energy_read where mode=%s and meter='E-TOTAL' and ts >= %s and ts < %s", (mode, m0, t1))
    demand = float(dem["kw"]) if dem and dem["kw"] is not None else 0.0
    idle = sum(u["by_state"].get("idle", 0.0) for u in units if u["unit"] not in EN.NO_STANDBY)
    return {"day": day.isoformat(), "hours": round(sum(float(r["seconds"]) for r in tot) / 3600, 2), "kwh": round(kwh, 1),
            "by_bucket": {b: round(v, 1) for b, v in by.items()}, "cost": round(cost_of(tot, p["price"]), 2),
            "peak_share": round(by["peak"] / kwh, 3) if kwh else 0.0, "co2_kg": round(kwh * float(p["co2_factor"]), 1),
            "idle_kwh": round(idle, 1), "idle_share": round(idle / kwh, 3) if kwh else 0.0, "air_kwh": round(air, 1),
            "demand_kw": round(demand, 1), "contract_kw": float(p["contract_kw"]), "demand_ratio": round(demand / float(p["contract_kw"]), 3),
            "series": [{"ts": r["ts"].isoformat(), "kw": r["kw"], "bucket": r["bucket"]} for r in tot], "units": units,
            "price": p["price"], "factor": p["co2_factor"]}


def _parts_rows(db, mode, t0, t1):
    return db.q("select meter, ts, p.key as item, (p.value->>0)::int as n, (p.value->>1)::float as k from energy_read r, "
                "jsonb_each(r.parts) p where r.mode=%s and r.ts >= %s and r.ts < %s and r.meter like 'E-%%' order by ts", (mode, t0, t1))


def std_kwh(unit, item):
    """标准单件运行电量：运行功率 × 这台设备上这个物料各工序的标准工时"""
    from factory import data as F
    from sim.engine import OP_UNITS
    try:
        ops = F.ROUTINGS[F.BOMS[item][0]]
    except (KeyError, IndexError):
        return None
    mins = sum(m for op, m in ops if (OP_UNITS.get(op) or [None])[0] == unit)
    return EN.POWER[unit][0] * mins / 60 if mins else None


def unit_energy(db, mode, end=None, recent_parts=3, recent_h=24, base_days=7):
    """每台设备每个物料的单件运行电量：最近 recent_parts 件（recent_h 小时内）vs 更早的基线（近 base_days 天，不够 5 件就用标准值 × 1.08）"""
    end = end or _end(db, mode)
    rs = _parts_rows(db, mode, end - dt.timedelta(days=base_days), end)
    by = {}
    for r in rs:
        u = r["meter"][2:].lower()
        if u in EN.POWER:
            by.setdefault((u, r["item"]), []).append(r)
    out = []
    t_lim = end - dt.timedelta(hours=recent_h)
    for (u, item), lst in sorted(by.items()):
        lst.sort(key=lambda r: r["ts"], reverse=True)
        a = {"rn": 0, "rk": 0.0, "bn": 0, "bk": 0.0}
        for r in lst:
            if a["rn"] < recent_parts and r["ts"] >= t_lim:
                a["rn"] += r["n"]
                a["rk"] += r["k"]
            else:
                a["bn"] += r["n"]
                a["bk"] += r["k"]
        std = std_kwh(u, item)
        base = a["bk"] / a["bn"] if a["bn"] >= 5 else (std * 1.08 if std else None)
        recent = a["rk"] / a["rn"] if a["rn"] else None
        out.append({"unit": u, "name": UNIT_NAME[u], "item": item, "recent_parts": a["rn"], "recent": round(recent, 3) if recent else None,
                    "base_parts": a["bn"], "base": round(base, 3) if base else None, "base_from": "history" if a["bn"] >= 5 else "standard",
                    "std": round(std, 3) if std else None,
                    "change": round(recent / base - 1, 3) if recent and base else None})
    return out


def idle_by_unit(db, mode, hours=12, end=None):
    end = end or _end(db, mode)
    t0 = end - dt.timedelta(hours=hours)
    out = []
    for u in STANDBY_UNITS:
        rs = rows(db, mode, EN.meter_of(u), t0, end)
        tot = sum(float(r["value"]) for r in rs)
        idle = sum(float((r["k"] or {}).get("idle", 0.0)) for r in rs)
        idle_s = sum(float((r["s"] or {}).get("idle", 0.0)) for r in rs)
        out.append({"unit": u, "name": UNIT_NAME[u], "kwh": round(tot, 2), "idle_kwh": round(idle, 2), "idle_h": round(idle_s / 3600, 2),
                    "idle_share": round(idle / tot, 3) if tot else 0.0})
    return out


def peak_share(db, mode, hours=24, end=None):
    end = end or _end(db, mode)
    rs = rows(db, mode, "E-TOTAL", end - dt.timedelta(hours=hours), end)
    kwh = sum(float(r["value"]) for r in rs)
    pk = sum(float(r["value"]) for r in rs if r["bucket"] == "peak")
    ht = sum(float(r["value"]) for r in rows(db, mode, "E-HT-01", end - dt.timedelta(hours=hours), end) if r["bucket"] == "peak")
    return {"hours": round(sum(float(r["seconds"]) for r in rs) / 3600, 2), "kwh": round(kwh, 1), "peak_kwh": round(pk, 1),
            "share": round(pk / kwh, 3) if kwh else 0.0, "ht_peak_kwh": round(ht, 1)}


def air_excess(db, mode, hours=4, end=None):
    """空压机比按开着的用气设备该用的多出多少（kW）：多出一截往往是漏气"""
    end = end or _end(db, mode)
    t0 = end - dt.timedelta(hours=hours)
    air = rows(db, mode, "E-AIR", t0, end)
    if not air:
        return {"hours": 0, "excess_kw": 0.0, "actual_kw": 0.0, "expected_kw": 0.0}
    run_s = {}
    for u in EN.AIR_USERS:
        for r in rows(db, mode, EN.meter_of(u), t0, end):
            run_s[r["ts"]] = run_s.get(r["ts"], 0.0) + float((r["s"] or {}).get("run", 0.0))
    secs = sum(float(r["seconds"]) for r in air)
    actual = sum(float(r["value"]) for r in air) * 3600 / secs
    exp = sum((EN.AIR_UNLOAD_KW * float(r["seconds"]) + EN.AIR_KW_PER_M3 * EN.AIR_PER_USER * run_s.get(r["ts"], 0.0)) for r in air) / secs
    return {"hours": round(secs / 3600, 2), "actual_kw": round(actual, 2), "expected_kw": round(exp, 2), "excess_kw": round(actual - exp, 2)}


def demand(db, mode, end=None):
    from hub import kpi
    end = end or _end(db, mode)
    p = params(db, mode)
    day = (end - dt.timedelta(seconds=1)).astimezone(kpi.TZ).date()
    m0 = day_bounds(day.replace(day=1))[0]
    r = db.one("select ts, kw from energy_read where mode=%s and meter='E-TOTAL' and ts >= %s and ts < %s and kw is not null "
               "order by kw desc limit 1", (mode, m0, end))
    kw = float(r["kw"]) if r else 0.0
    return {"kw": round(kw, 1), "at": r["ts"].isoformat() if r else None, "contract_kw": float(p["contract_kw"]),
            "ratio": round(kw / float(p["contract_kw"]), 3)}


def env_now(db, mode, hours=1, end=None):
    end = end or _end(db, mode)
    p = params(db, mode)
    out = {}
    for pt, (label, unit) in ENV_POINTS.items():
        r = db.one("select avg(value) as v, count(*) as n, max(value) as mx from env_read where mode=%s and point=%s and ts >= %s and ts < %s",
                   (mode, pt, end - dt.timedelta(hours=hours), end))
        lim = float(p["mist_limit"] if pt == "mist" else p["noise_limit"])
        v = float(r["v"]) if r and r["v"] is not None else None
        out[pt] = {"label": label, "unit": unit, "value": round(v, 2) if v is not None else None, "max": round(float(r["mx"]), 2) if r and r["mx"] else None,
                   "limit": lim, "over": v is not None and v > lim, "n": r["n"] if r else 0}
    return out


def env_series(db, mode, hours=24, end=None):
    end = end or _end(db, mode)
    out = {}
    for pt in ENV_POINTS:
        out[pt] = [{"ts": r["ts"].isoformat(), "value": round(float(r["value"]), 2)} for r in db.q(
            "select ts, value from env_read where mode=%s and point=%s and ts >= %s and ts < %s order by ts", (mode, pt, end - dt.timedelta(hours=hours), end))]
    return out


def carbon(db, mode, month=None):
    """月度碳核算（外购电力，范围 2）：电量 × 排放因子；每台设备；每件产品的碳足迹（各工序设备的单件电量 + 公用按件数分摊）"""
    from factory import data as F
    from hub import kpi
    from sim.engine import OP_UNITS
    p = params(db, mode)
    f = float(p["co2_factor"])
    end = _end(db, mode)
    if month:
        y, m = (int(x) for x in month.split("-"))
        d0 = dt.date(y, m, 1)
    else:
        d0 = (end - dt.timedelta(seconds=1)).astimezone(kpi.TZ).date().replace(day=1)
    d1 = (d0 + dt.timedelta(days=32)).replace(day=1)
    t0, t1 = day_bounds(d0)[0], day_bounds(d1)[0]
    agg = {r["meter"]: (float(r["v"]), float(r["h"])) for r in db.q(
        "select meter, sum(value) as v, sum(seconds)/3600.0 as h from energy_read where mode=%s and ts >= %s and ts < %s group by meter", (mode, t0, t1))}
    parts = {}
    for r in _parts_rows(db, mode, t0, t1):
        parts[r["meter"][2:].lower()] = parts.get(r["meter"][2:].lower(), 0) + r["n"]
    total = agg.get("E-TOTAL", (0.0, 0.0))[0]
    shared = agg.get("E-AIR", (0.0, 0.0))[0] + max(0.0, total - sum(agg.get(EN.meter_of(u), (0.0, 0.0))[0] for u in EN.POWER) - agg.get("E-AIR", (0.0, 0.0))[0])
    n_all = sum(parts.values())
    per_unit = {u: agg.get(EN.meter_of(u), (0.0, 0.0))[0] / parts[u] for u in EN.POWER if parts.get(u)}
    shared_pp = shared / n_all if n_all else 0.0
    products = []
    for item in (("SH-301", "WQR-105") if not _E else tuple(F.PRODUCTS)):
        try:
            ops = F.ROUTINGS[F.BOMS[item][0]]
        except (KeyError, IndexError):
            continue
        units = [(OP_UNITS.get(op) or [None])[0] for op, _ in ops]
        if not units or any(u not in per_unit for u in units if u):
            known = [u for u in units if u in per_unit]
            if not known:
                continue
        kwh = sum(per_unit.get(u, 0.0) for u in units if u) + shared_pp * len([u for u in units if u])
        products.append({"item": item, "kwh": round(kwh, 2), "co2_kg": round(kwh * f, 2), "ops": len(units),
                         "missing": [u for u in units if u and u not in per_unit]})
    return {"month": d0.strftime("%Y-%m"), "hours": round(agg.get("E-TOTAL", (0.0, 0.0))[1], 1), "kwh": round(total, 1),
            "t_co2e": round(total * f / 1000, 3), "factor": f, "scope": "范围 2（外购电力）",
            "units": [{"unit": u, "name": UNIT_NAME[u], "kwh": round(agg.get(EN.meter_of(u), (0.0, 0.0))[0], 1),
                       "co2_kg": round(agg.get(EN.meter_of(u), (0.0, 0.0))[0] * f, 1), "parts": parts.get(u, 0),
                       "kwh_per_part": round(per_unit[u], 3) if u in per_unit else None} for u in EN.POWER],
            "shared_kwh": round(shared, 1), "products": products,
            "water_m3": round(agg.get("W-MAIN", (0.0, 0.0))[0], 2), "air_m3": round(agg.get("F-AIR", (0.0, 0.0))[0], 1)}


def kpis(db, mode):
    seed(db, mode)
    if not db.one("select 1 as x from energy_read where mode=%s limit 1", (mode,)):
        return None
    o = overview(db, mode)
    return {"kwh": o["kwh"], "cost": o["cost"], "peak_share": o["peak_share"], "idle_share": o["idle_share"], "co2_kg": o["co2_kg"],
            "demand_ratio": o["demand_ratio"], "day": o["day"], "measuring": measuring(db, mode), "sim": sim_on(db, mode)}


# ---------------------------------------------------------------- 方案（推演）
def energy_ctx(db, mode):
    p = params(db, mode)
    return {"price": p["price"], "factor": float(p["co2_factor"])}


def _base_changes(db, mode):
    s = settings(db, mode)
    out = []
    by_min = {}
    for u, m in s["standby"].items():
        by_min.setdefault(float(m), []).append(u)
    for m, us in by_min.items():
        out.append({"type": "energy_setting", "units": sorted(us), "standby_min": m})
    if s["tou"]:
        out.append({"type": "tou_rule", "units": s["tou"], "on": True})
    return out


def options(db, mode, a, snap, ctx):
    """N2 空转：自动待机 10 / 30 分钟（这台、全部）/ 不处理；N3、N5 峰时：热处理错峰 / 不处理。车间推演未来 24 小时的电量、电费、交期"""
    from hub.ont import plan as P
    from hub.ont import playbook as PB
    v = (a.get("detail") or {}).get("values") or {}
    rule = a["rule"]
    if rule == "N2":
        unit = v.get("unit")
        if unit not in STANDBY_UNITS:
            return {"options": [], "affected": [], "reason": "这个异常没有关联到某台设备", "recommended": None}
        others = [u for u in STANDBY_UNITS if u not in EN.AUTO]
        plans = [("none", "不处理（对照）", [], "空闲时照样开着", None),
                 ("standby10", "{} 空闲 10 分钟自动待机".format(unit.upper()), [{"type": "energy_setting", "units": [unit], "standby_min": 10}],
                  "待机功率约为空转的 1/10；再开要预热 3 分钟", None),
                 ("standby30", "{} 空闲 30 分钟自动待机".format(unit.upper()), [{"type": "energy_setting", "units": [unit], "standby_min": 30}],
                  "短暂停顿不待机，预热少；省得少一点", None),
                 ("all10", "全部机加设备空闲 10 分钟自动待机", [{"type": "energy_setting", "units": others, "standby_min": 10}],
                  "热处理炉保温不待机；检验站、试验台是自动设备也不设", None)]
        subj = unit
    elif rule in ("N3", "N5"):
        plans = [("none", "不处理（对照）", [], "热处理照现在的节奏开炉", None),
                 ("tou", "热处理错峰（峰时不开新炉）", [{"type": "tou_rule", "units": ["ht-01"], "on": True}],
                  "峰时 8–11、18–21 点不开新炉，工件攒着峰后一起进炉；等的件可能晚几个小时", None)]
        subj = "ht-01"
    else:
        return fix_options(db, mode, a)
    names = PB.affected(dict(a, rule="P1", subject_type="Machine", subject_key=subj), ctx)
    base = _base_changes(db, mode)
    ectx = dict(ctx, energy=energy_ctx(db, mode))
    out = []
    for i, (kind, label, sim, note, _) in enumerate(plans):
        r = P.simulate(snap, base + sim, ectx)
        rows_ = [s for s in r["sales_orders"] if s["name"] in names] if names else []
        lates = [s["late_days"] for s in rows_ if s["late_days"] is not None]
        out.append({"key": chr(ord("A") + i), "kind": kind, "label": label, "note": note, "changes": [dict(c) for c in sim], "sim_changes": sim,
                    "result": {"sales_orders": rows_, "costs": list(r["costs"]), "cost_total": round(sum(c["usd"] for c in r["costs"]), 2),
                               "overtime_min": r["overtime_min"], "overtime_units": r["overtime_units"], "checks": r["checks"], "ok": r["ok"],
                               "energy": r.get("energy")},
                    "worst_late": max(lates) if lates else None})
    none = out[0]["result"]["energy"] or {}
    for o in out:
        e = o["result"]["energy"] or {}
        if not e or o["kind"] == "none":
            continue
        dc = round(float(e.get("cost", 0)) - float(none.get("cost", 0)), 2)
        dk = round(float(e.get("kwh", 0)) - float(none.get("kwh", 0)), 1)
        o["result"]["costs"].append({"what": "电费（未来 24 小时，比不处理{}）".format("省" if dc < 0 else "多"), "usd": dc})
        o["result"]["cost_total"] = round(sum(c["usd"] for c in o["result"]["costs"]), 2)
        o["saving"] = {"kwh": -dk, "usd": -dc, "co2_kg": round(-dk * float(energy_ctx(db, mode)["factor"]), 1),
                       "peak_share": e.get("peak_share"), "peak_share_none": none.get("peak_share")}
        o["note"] = "{}；每天{} {:g} 度、${:,.2f}、碳 {:g} kg".format(o["note"], "省" if dk <= 0 else "多用", abs(dk), abs(dc), abs(o["saving"]["co2_kg"]))

    def score(o):
        wl = o["worst_late"] if o["worst_late"] is not None else -99
        return (0 if o["result"]["ok"] else 1, max(wl, 0), o["result"]["cost_total"], o["kind"] == "all10")
    best = min(out, key=score)
    for o in out:
        o["recommended"] = o is best
    if a.get("id"):                              # 实验 21 评分用：中枢对这个异常推荐了哪个
        _patch_in(db, mode, "recommended", str(a["id"]), best["kind"])
    sv = best.get("saving") or {}
    reason = ("建议 {} {}：未来 24 小时省 {:g} 度、${:,.2f}，{}".format(best["key"], best["label"], sv.get("kwh", 0), sv.get("usd", 0),
                                                              "；".join("{} {}".format(s["name"], "按时" if (s["late_days"] or 0) <= 0 else "晚 {} 天".format(s["late_days"]))
                                                                       for s in best["result"]["sales_orders"]) or "不影响交期")
              if best["kind"] != "none" else
              ("推演的未来 24 小时里各方案省不下电（这段时间{}），先不处理".format("热处理炉不在峰时开炉" if rule != "N2" else "这台设备一直有活")
               if all(abs((o.get("saving") or {}).get("usd", 0)) < 0.01 for o in out) else "各方案省下的电费抵不上交期的损失，建议先不处理"))
    return {"options": out, "affected": names, "reason": reason, "recommended": best["key"]}


def fix_options(db, mode, a):
    """N1 单耗突增（维修）、N4 漏气（查漏整改）、N6 环境超限（整改）：不进车间推演"""
    from sim import reliability as REL
    v = (a.get("detail") or {}).get("values") or {}
    p = params(db, mode)
    flat = float(p["price"]["flat"])
    none = {"sales_orders": [], "cost_total": 0, "costs": [], "overtime_min": 0, "checks": [], "ok": True}
    if a["rule"] == "N1":
        u = v.get("unit")
        rp = REL.params(u) or {"mttr_min": 120}
        cost = round(rp["mttr_min"] / 60 * REPAIR_RATE, 2)
        out = [{"key": "A", "kind": "repair", "label": "开维修工单：查主轴轴承、刀具 / 砂轮", "note": "单件电量比基线高 {:.0%}；停机维修约 {} 分钟（挂牌上锁）".format(
                    float(v.get("change") or 0), rp["mttr_min"]),
                "changes": [{"type": "repair_order", "unit": u, "title": "单件能耗突增：查主轴轴承、刀具 / 砂轮", "source": "energy"}],
                "result": dict(none, cost_total=cost, costs=[{"what": "维修人工", "usd": cost}]), "recommended": True},
               {"key": "B", "kind": "none", "label": "暂不处理", "note": "多用电；劣化往往越来越重，可能变成故障停机", "changes": [], "result": none, "recommended": False}]
        return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：单耗突增多半是设备在劣化，趁还没坏先查"}
    if a["rule"] == "N4":
        ex = float(v.get("excess_kw") or 0)
        cost = round(2 * REPAIR_RATE, 2)
        out = [{"key": "A", "kind": "fix", "label": "整改工单：压缩空气管路查漏", "note": "多出约 {:.1f} kW，一天约 {:.0f} 度、${:,.2f}；查漏约 2 小时，不停产".format(
                    ex, ex * 24, ex * 24 * flat),
                "changes": [{"type": "rectify_order", "unit": "air", "subject": "压缩空气管路查漏、更换漏气接头", "minutes": 120, "energy_fix": "leak"}],
                "result": dict(none, cost_total=cost, costs=[{"what": "查漏人工", "usd": cost}]), "recommended": True},
               {"key": "B", "kind": "none", "label": "暂不处理", "note": "空压机一直多出这一截", "changes": [], "result": none, "recommended": False}]
        return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：查漏花两小时人工，几天就省回来"}
    if a["rule"] == "N6":
        pt = v.get("point")
        if pt == "mist":
            ch = {"type": "rectify_order", "unit": "mist", "subject": "机加区油雾收集器检修、换滤芯", "minutes": 120, "energy_fix": "mist"}
            note = "油雾 {:.1f} mg/m³（限值 {:g}）；检修约 2 小时".format(float(v.get("value") or 0), float(v.get("limit") or 5))
        else:
            ch = {"type": "rectify_order", "unit": NOISY_UNITS[0], "subject": "{}加隔声罩；高噪声区发耳塞".format("、".join(UNIT_NAME.get(u, u) for u in NOISY_UNITS)),
                  "minutes": 240, "energy_fix": "noise", "units": list(NOISY_UNITS)}
            note = "噪声 {:.1f} dB(A)（限值 {:g}）；加隔声罩后这两台低约 6 dB".format(float(v.get("value") or 0), float(v.get("limit") or 85))
        cost = round(ch["minutes"] / 60 * REPAIR_RATE, 2)
        out = [{"key": "A", "kind": "fix", "label": "整改工单：" + ch["subject"], "note": note, "changes": [ch],
                "result": dict(none, cost_total=cost, costs=[{"what": "整改人工", "usd": cost}]), "recommended": True},
               {"key": "B", "kind": "none", "label": "暂不处理", "note": "职业健康风险", "changes": [], "result": none, "recommended": False}]
        return {"options": out, "affected": [], "recommended": "A", "reason": "建议 A：环境指标超限要整改（安全环保的整改工单）"}
    return {"options": [], "affected": [], "reason": "这类异常没有处理方案", "recommended": None}


# ---------------------------------------------------------------- 动作执行
def exec_setting(H, mode, p, u):
    db = H.db
    units = [x for x in p.get("units") or [] if x in STANDBY_UNITS]
    if not units:
        raise ValueError("没有可以设自动待机的设备（热处理炉保温，不待机）")
    m = float(p.get("standby_min") or 0)
    if m and not 1 <= m <= 240:
        raise ValueError("自动待机应在空闲 1–240 分钟之间")
    st = _state(db, mode)
    sb = dict(st.get("standby") or {})
    for x in units:
        if m:
            sb[x] = m
        else:
            sb.pop(x, None)
    _patch(db, mode, {"standby": sb})
    push(H, mode, u.get("name") or "系统")
    return {"text": "{}：{}".format("、".join(x.upper() for x in units), "空闲 {:g} 分钟自动待机".format(m) if m else "取消自动待机"), "standby": sb}


def exec_tou(H, mode, p, u):
    db = H.db
    units = [x for x in p.get("units") or ["ht-01"] if x in EN.POWER]
    st = _state(db, mode)
    tou = set(st.get("tou") or [])
    if p.get("on", True):
        tou |= set(units)
    else:
        tou -= set(units)
    st["tou"] = sorted(tou)
    _patch(db, mode, {"tou": st["tou"]})
    push(H, mode, u.get("name") or "系统")
    return {"text": "{}：{}".format("、".join(x.upper() for x in units), "峰时（8–11、18–21 点）不开新炉" if p.get("on", True) else "取消错峰"), "tou": st["tou"]}


# ---------------------------------------------------------------- 教学模拟器与注入
def inject(H, mode, kind, who="老师", unit=None, hours=None, pct=None):
    if mode != "teach":
        raise PermissionError("生产模式不模拟能源问题")
    if kind not in FAULT_NAME:
        raise ValueError("没有这种问题：{}".format(kind))
    if kind in ("forgot", "degrade") and unit not in STANDBY_UNITS:
        raise ValueError("要指定一台设备（热处理炉不行）")
    x = {"kind": kind}
    if unit:
        x["unit"] = unit
    if hours:
        x["hours"] = float(hours)
    if pct:
        x["pct"] = float(pct)
    if kind == "forgot":
        x.setdefault("hours", 12)
    _patch_in(H.db, mode, "faults", kind + (":" + unit if unit else ""), dict(x, at=dt.datetime.now(dt.timezone.utc).isoformat(), by=who))
    push(H, mode, who, inject=[x])
    return {"text": "已注入：{}{}".format(FAULT_NAME[kind], "（{}）".format(unit.upper()) if unit else ""), "fault": x}


def clear(H, mode, key, who="系统", why=""):
    f = (_state(H.db, mode).get("faults") or {}).get(key)
    _patch_in(H.db, mode, "faults", key, None)
    kind, _, unit = key.partition(":")
    push(H, mode, who, clear=[{"kind": kind, "unit": unit or None}])
    return f


def _fixed(db, mode, key, f):
    """问题有没有被处理：劣化 → 这台设备开过维修单并修好；漏气、油雾 → 对应的整改工单已批准执行"""
    at = dt.datetime.fromisoformat(f["at"])
    kind, _, unit = key.partition(":")
    if kind == "degrade":
        try:
            r = db.one("select 1 as x from maint_repair where mode=%s and unit=%s and created_at >= %s and status in ('fixed','closed') limit 1",
                       (mode, unit, at))
        except Exception:  # noqa: BLE001
            return False
        return bool(r)
    if kind in ("leak", "mist"):
        r = db.one("select 1 as x from action where mode=%s and type='rectify_order' and params->>'energy_fix'=%s and status in ('executing','done') "
                   "and executed_at >= %s limit 1", (mode, kind, at))
        return bool(r)
    return False


def tick(H, mode, now=None, rng=None):
    """定期：重发设定；教学模拟器出问题、问题修好了就清掉；整改了噪声的加隔声罩"""
    db = H.db
    seed(db, mode)
    now = now or dt.datetime.now(dt.timezone.utc)
    rng = rng or random.Random()
    st = _state(db, mode)
    out = {"pushed": False, "injected": [], "cleared": []}
    if now.timestamp() - float(st.get("pushed_at") or 0) > PUSH_EVERY_S:
        push(H, mode)
        out["pushed"] = True
        st = _state(db, mode)
    # 噪声整改：批准后给那几台加隔声罩
    q = set(st.get("quiet") or [])
    for a in db.q("select params from action where mode=%s and type='rectify_order' and params->>'energy_fix'='noise' and status in ('executing','done')", (mode,)):
        q |= set(a["params"].get("units") or [])
    if q != set(st.get("quiet") or []):
        _patch(db, mode, {"quiet": sorted(q)})
        push(H, mode)
    if mode != "teach":
        return out
    # 问题修好了 / 到期了
    for key, f in list((st.get("faults") or {}).items()):
        age = (now - dt.datetime.fromisoformat(f["at"])).total_seconds()
        kind = key.partition(":")[0]
        if kind in ("forgot", "ht_peak") and age > 4 * 3600:
            clear(H, mode, key, why="到期")
            out["cleared"].append(key)
        elif _fixed(db, mode, key, f) or (sim_on(db, mode) and kind in ("leak", "mist", "degrade") and age > AUTO_FIX_S and not f.get("lab")):
            clear(H, mode, key, why="已处理")
            out["cleared"].append(key)
    st = _state(db, mode)
    if not sim_on(db, mode) or not measuring(db, mode):
        return out
    last = float(st.get("auto_at") or 0)
    if not last:
        _patch(db, mode, {"auto_at": now.timestamp()})
        return out
    if now.timestamp() - last < AUTO_EVERY_S:
        return out
    _patch(db, mode, {"auto_at": now.timestamp()})
    kinds = {k.partition(":")[0] for k in st.get("faults") or {}}
    x = rng.random()
    if x < 0.45:
        u = rng.choice(FORGOT_UNITS)         # 晚班没岗位的设备：下班的人忘了关
        if "forgot" not in kinds:
            out["injected"].append(inject(H, mode, "forgot", "教学模拟器", unit=u, hours=12))
    elif x < 0.65:
        if "degrade" not in kinds:
            out["injected"].append(inject(H, mode, "degrade", "教学模拟器", unit=rng.choice(DEGRADE_UNITS), pct=0.3))
    elif x < 0.85:
        if "leak" not in kinds:
            out["injected"].append(inject(H, mode, "leak", "教学模拟器"))
    elif "mist" not in kinds:
        out["injected"].append(inject(H, mode, "mist", "教学模拟器"))
    return out


def live_faults(db, mode):
    st = _state(db, mode)
    return [{"key": k, "kind": k.partition(":")[0], "name": FAULT_NAME.get(k.partition(":")[0]), "unit": f.get("unit"), "at": f.get("at"),
             "by": f.get("by")} for k, f in (st.get("faults") or {}).items()]


# ---------------------------------------------------------------- 评测沙盒、测试：用车间副本跑一段，生成过去 hours 小时的读数
def demo_readings(snap, hours=24, plan=None, staffing=None):
    """从快照起把车间副本往后跑 hours 小时（计量打开），按 plan [(第几小时, inject 列表)] 注入问题；
    返回读数（时间整体往前挪 hours 小时，正好到快照时刻为止）"""
    import copy

    from sim.engine import Engine

    class _C:
        t = 0.0

        def now(self):
            return self.t
    clock = _C()
    clock.t = snap["t"]
    got = []

    def pub(tp, ty, src, data, corr):
        if ty == "energy.reading":
            got.append(data)
    eng = Engine.from_snapshot(copy.deepcopy(snap), pub, clock)
    if staffing:
        eng.set_staffing(dict(staffing, enabled=True))
    eng.set_energy({"enabled": True})
    t0 = snap["t"]
    for h, inj in sorted(plan or [], key=lambda x: x[0]):
        eng.at(t0 + h * 3600, "demo_inject", inject=inj)
    end = t0 + hours * 3600
    while eng.q and eng.q[0][0] <= end:
        clock.t = max(clock.t, eng.q[0][0])
        eng.run_due()
    shift = dt.timedelta(hours=hours)
    out = []
    for d in got:
        d = dict(d)
        d["ts"] = (_ts(d["ts"]) - shift).isoformat()
        d["end"] = (_ts(d["end"]) - shift).isoformat()
        out.append(d)
    return out


def energy_scene(H, eng, mode="teach"):
    """评测沙盒：过去 24 小时的计量读数——卧加晚班下班忘关、热处理峰时开炉、磨床一开始就劣化、空压机最后 6 小时漏气"""
    import json
    from hub import people as PE
    seed(H.db, mode)
    if H.db.one("select 1 as x from energy_read where mode=%s limit 1", (mode,)):
        return 0
    snap = json.loads(json.dumps(eng.snapshot()))
    lv = PE.levels(H.db, mode, PE.window_days(None, H.db, mode)) if PE.enabled(H.db, mode) else {}
    # 磨床一开始就劣化：情景里磨床一天只磨几件，而且只在某个时段磨；第 2 小时才劣化时，那几件落在劣化前还是后要看是几点开跑，
    # 测试随钟点时过时不过（2026-10-18 数字工厂部署卡在这里）。基线件不够 5 件时本来就用“标准值 × 1.08”当基线
    rs = demo_readings(snap, 24, plan=[(0, [{"kind": "forgot", "unit": "hmc-01", "hours": 24}, {"kind": "ht_peak"},
                                            {"kind": "degrade", "unit": "grd-01", "pct": 0.4}]), (18, [{"kind": "leak"}])],
                       staffing={"levels": lv} if lv else None)
    for d in rs:
        ingest(H.db, mode, d)
    return len(rs)
