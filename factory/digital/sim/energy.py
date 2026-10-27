# -*- coding: utf-8 -*-
"""能源与环境（第 18 轮 E6）：仿真车间按设备状态和功率记电量，每 15 分钟（工厂时间）发一个计量读数。

- 每台设备四档功率（kW）：运行、空闲（开着没活，空转）、待机、关机 0；热处理炉空闲 = 保温（不关、不待机）。
- 设备什么时候“关机”：空闲且这一班没人（按班次下班，或排班里这台这一班没人）——下班的人顺手关掉；“忘关”的照样空转。
- 空闲 N 分钟自动待机（节能设定）：待机后再开要预热 3 分钟（按调整算）。
- 错峰：设定的设备（热处理炉）峰时不开新炉，等峰时结束再开。
- 公用：空压机 = 卸载 2 kW + 6 kW ×（每分钟用气 m³）；照明空调 4 kW，有人上班再加 6 kW；自来水按装配清洗件数和人。
- 车间环境：机加区油雾（按开着的湿式加工设备数），车间噪声（运行设备声级叠加）。
- 教学的“会出问题”：忘关（某台没人时照样开着）、漏气（空压机多出一截负荷）、劣化（某台运行功率慢慢升高）、
  峰时开炉（下一个峰时段热处理炉整段升温）、油雾收集器故障（油雾翻倍）。
关闭（enabled=False）时完全不参与，车间和以前一样。"""
import datetime as dt
import math

# 设备代号 → (运行, 空闲, 待机) kW
POWER = {
    "saw-01": (7.5, 2.0, 0.3), "cnc-l01-a": (15.0, 5.5, 0.6), "cnc-l01-b": (11.0, 4.5, 0.5), "vmc-01": (15.0, 5.0, 0.6),
    "hmc-01": (18.0, 6.0, 0.7), "key-01": (5.5, 2.0, 0.3), "hob-01": (7.5, 2.5, 0.4), "ht-01": (110.0, 35.0, 35.0),
    "grd-01": (11.0, 4.0, 0.5), "qc-01": (1.5, 0.8, 0.2), "asm-01": (3.0, 1.0, 0.2), "test-01": (15.0, 1.5, 0.3),
}
NO_STANDBY = ("ht-01",)                     # 热处理炉保温，不待机
AUTO = ("qc-01", "test-01")                 # 自动设备：不按班次关机
AIR_USERS = ("cnc-l01-a", "cnc-l01-b", "vmc-01", "hmc-01", "key-01", "hob-01", "grd-01", "asm-01")
WET = ("cnc-l01-a", "cnc-l01-b", "vmc-01", "hmc-01", "key-01", "hob-01", "grd-01")
NOISE = {"saw-01": 80, "grd-01": 78, "test-01": 78, "hob-01": 76, "cnc-l01-a": 74, "cnc-l01-b": 74, "vmc-01": 74, "hmc-01": 74,
         "key-01": 74, "asm-01": 68, "ht-01": 65, "qc-01": 60}
NOISE_BG = 62.0
AIR_UNLOAD_KW, AIR_KW_PER_M3, AIR_PER_USER = 2.0, 6.0, 0.15     # 空压机：卸载、每 m³/min 的电、每台运行设备用气 m³/min
LEAK_M3 = 1.0                                # 漏气：每分钟多耗 1 m³（约多 6 kW）
LIGHT_BASE, LIGHT_SHIFT = 4.0, 6.0
WATER_PER_PART, WATER_PER_H = 0.03, 0.2      # 装配清洗每件、有人上班每小时（m³）
WARM_MIN = 3.0                               # 待机后再开的预热（分钟）
READ_S = 900                                 # 计量读数间隔（工厂时间 15 分钟）
DEGRADE_RAMP_S = 7200                        # 劣化：2 小时内升到设定的幅度
PEAK = ((8, 11), (18, 21))                   # 峰时（本地时间，时）
VALLEY = ((23, 24), (0, 7))                  # 谷时


def meter_of(unit):
    return "E-" + unit.upper()


METERS = [meter_of(u) for u in POWER] + ["E-AIR", "E-TOTAL", "F-AIR", "W-MAIN"]


def bucket(local, peak=PEAK, valley=VALLEY):
    """本地时间 → 'peak' / 'flat' / 'valley'"""
    h = local.hour
    if any(a <= h < b for a, b in peak):
        return "peak"
    if any(a <= h < b for a, b in valley):
        return "valley"
    return "flat"


def peak_window(local, peak=PEAK):
    """local 时刻所在或之后的第一个峰时段（本地 datetime 起止）；正在峰时段里就从 local 起"""
    day = local.replace(hour=0, minute=0, second=0, microsecond=0)
    for k in range(3):
        d = day + dt.timedelta(days=k)
        for a, b in peak:
            s, e = d + dt.timedelta(hours=a), d + dt.timedelta(hours=b)
            if e > local:
                return max(s, local), e
    return None, None


def noise_db(running, quiet=()):
    s = 10 ** (NOISE_BG / 10) + sum(10 ** ((NOISE.get(u, 60) - (6 if u in quiet else 0)) / 10) for u in running)
    return 10 * math.log10(s)


def mist_mg(running, collector_fault=False):
    n = sum(1 for u in running if u in WET)
    return (0.3 + 0.75 * n) * (2.0 if collector_fault else 1.0)


class Energy:
    def __init__(self):
        self.enabled = False
        self.power = {u: list(v) for u, v in POWER.items()}
        self.standby = {}            # 设备 → 空闲 N 分钟自动待机
        self.tou = []                # 错峰的设备（峰时不开新炉）
        self.quiet = []              # 加了隔声罩的设备（噪声低 6 dB）
        self.faults = {}             # forgot: {unit: until_t}；leak: {"until": t}；degrade: {unit: {pct, t0}}；ht_peak: [s, e]；mist: {"until": t}
        self.cur = {}                # 计量对象 → [t, 档, kW]（设备代号，或 "air" / "light"）
        self.acc = {}                # 本次读数期间：对象 → {kwh, s: {档: 秒}, parts: {物料: [件, 运行 kWh]}}
        self.tot = {}                # 累计：对象 → {kwh, peak, flat, valley, run, idle, ...}
        self.env = {"t": None, "mist": 0.0, "noise": 0.0, "mist_i": 0.0, "noise_i": 0.0, "s": 0.0, "max_mist": 0.0, "max_noise": 0.0,
                    "air_m3": 0.0, "water": 0.0}
        self.idle_since = {}
        self.iv_start = None         # 本次读数期间的开始（仿真秒）
        self.next_read = None

    # ---------------------------------------------------------------- 设定
    def update(self, d):
        if d.get("power"):
            for u, v in d["power"].items():
                if u in self.power and len(v) == 3:
                    self.power[u] = [float(x) for x in v]
        if "standby" in d:
            self.standby = {u: float(m) for u, m in (d.get("standby") or {}).items() if m and u in POWER and u not in NO_STANDBY}
        if "tou" in d:
            self.tou = [u for u in d.get("tou") or [] if u in POWER]
        if "quiet" in d:
            self.quiet = [u for u in d.get("quiet") or [] if u in POWER]

    def to_dict(self):
        return {"enabled": self.enabled, "power": self.power, "standby": self.standby, "tou": self.tou, "quiet": self.quiet, "faults": self.faults,
                "cur": self.cur, "acc": self.acc, "tot": self.tot, "env": self.env, "idle_since": self.idle_since,
                "iv_start": self.iv_start, "next_read": self.next_read}

    @classmethod
    def from_dict(cls, d):
        e = cls()
        if not d:
            return e
        e.enabled = bool(d.get("enabled"))
        e.power = {u: list(v) for u, v in (d.get("power") or {}).items()} or e.power
        e.standby, e.tou, e.quiet = dict(d.get("standby") or {}), list(d.get("tou") or []), list(d.get("quiet") or [])
        e.faults = dict(d.get("faults") or {})
        e.cur = {k: list(v) for k, v in (d.get("cur") or {}).items()}
        e.acc = {k: {"kwh": v["kwh"], "s": dict(v["s"]), "k": dict(v.get("k") or {}), "parts": {i: list(x) for i, x in v.get("parts", {}).items()}}
                 for k, v in (d.get("acc") or {}).items()}
        e.tot = {k: dict(v) for k, v in (d.get("tot") or {}).items()}
        e.env = dict(e.env, **(d.get("env") or {}))
        e.idle_since = dict(d.get("idle_since") or {})
        e.iv_start, e.next_read = d.get("iv_start"), d.get("next_read")
        return e

    # ---------------------------------------------------------------- 问题
    def forgot(self, unit, t):
        return t < float((self.faults.get("forgot") or {}).get(unit, -1))

    def leak(self, t):
        x = self.faults.get("leak")
        return bool(x) and t < float(x.get("until", 1e18))

    def mist_fault(self, t):
        x = self.faults.get("mist")
        return bool(x) and t < float(x.get("until", 1e18))

    def degrade(self, unit, t):
        x = (self.faults.get("degrade") or {}).get(unit)
        if not x:
            return 1.0
        return 1.0 + float(x["pct"]) * max(0.0, min(1.0, (t - float(x["t0"])) / DEGRADE_RAMP_S))

    def ht_peak(self, t):
        w = self.faults.get("ht_peak")
        return bool(w) and w[0] <= t < w[1]

    # ---------------------------------------------------------------- 累计
    def _slot(self, key):
        return self.acc.setdefault(key, {"kwh": 0.0, "s": {}, "k": {}, "parts": {}})

    def accrue(self, key, t, bucket_of):
        """把 key 从上次记到 t 这一段按当时的档位记上（bucket_of(t0) → 峰 / 平 / 谷）"""
        c = self.cur.get(key)
        if not c:
            return
        t0, ps, kw = c
        d = t - t0
        if d <= 0:
            return
        bkt = bucket_of(t0)
        kwh = kw * d / 3600.0
        a = self._slot(key)
        a["kwh"] += kwh
        a["s"][ps] = a["s"].get(ps, 0.0) + d
        a.setdefault("k", {})[ps] = a.get("k", {}).get(ps, 0.0) + kwh
        tt = self.tot.setdefault(key, {})
        for k in ("kwh", bkt, ps):
            tt[k] = tt.get(k, 0.0) + kwh
        c[0] = t

    def accrue_env(self, t):
        e = self.env
        if e["t"] is None:
            e["t"] = t
            return
        d = t - e["t"]
        if d <= 0:
            return
        e["mist_i"] += e["mist"] * d
        e["noise_i"] += 10 ** (e["noise"] / 10) * d
        e["s"] += d
        e["air_m3"] += e.get("air_flow", 0.0) * d / 60.0
        e["water"] += e.get("water_h", 0.0) * d / 3600.0
        e["t"] = t

    def totals(self):
        return {k: dict(v) for k, v in self.tot.items()}


def summarize(tot0, tot1, price=None, factor=0.5306):
    """两份累计之差 → 电量、分时电量、空转、电费、碳（推演和测试用）。price：{peak, flat, valley} $/kWh"""
    price = price or {"peak": 0.15, "flat": 0.10, "valley": 0.05}
    keys = set(tot0) | set(tot1)
    out = {"kwh": 0.0, "peak": 0.0, "flat": 0.0, "valley": 0.0, "idle": 0.0, "standby": 0.0, "run": 0.0, "units": {}}
    for k in keys:
        a, b = tot0.get(k, {}), tot1.get(k, {})
        dd = {x: b.get(x, 0.0) - a.get(x, 0.0) for x in set(a) | set(b)}
        for x in ("kwh", "peak", "flat", "valley"):
            out[x] += dd.get(x, 0.0)
        if k in POWER:
            out["idle"] += dd.get("idle", 0.0) if k != "ht-01" else 0.0
            out["standby"] += dd.get("standby", 0.0)
            out["run"] += dd.get("run", 0.0)
            out["units"][k] = {"kwh": round(dd.get("kwh", 0.0), 2), "idle": round(dd.get("idle", 0.0), 2)}
    out["cost"] = sum(out[b] * price[b] for b in ("peak", "flat", "valley"))
    out["co2_kg"] = out["kwh"] * factor
    out["peak_share"] = out["peak"] / out["kwh"] if out["kwh"] else 0.0
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}
