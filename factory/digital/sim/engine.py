# -*- coding: utf-8 -*-
"""仿真车间：离散事件仿真。

- 设备按工厂数据的工作中心建模；热处理炉可同时装 20 件，其余设备一次一件。
- 工单按工艺路线逐工序流转，零件逐件传递：上一道做完一件，AGV 就把它送到下一道。
- 每道工序要先“派工”（dispatch），再由操作工在车间终端点“开工”（start）才会加工；
  自动模式（auto_start）下派工即开工，用于生产模式演示和自动测试。
- 刀具（砂轮）随加工磨损，寿命低于 8% 自动换刀；磨床砂轮越磨损，轴承位直径越偏大，
  这就是控制图上“测量值上移、趋近上限”的来源。
- 故障注入（inject_fault）只在教学模式下接受，供教师制造“磨床停机”一类情景。

时间：仿真时钟 = 真实时间 × 倍速。信封 ts 用真实时间（消息何时发出），
cycle_time_s、duration_s 等业务时长用仿真秒（零件实际要加工多久）。
"""
import datetime as dt
import heapq
import itertools
import math
import os
import random

from sim import reliability as REL
import time
from collections import deque

from wqbus import UNITS, layout
from wqbus.topics import unit_topic

from sim import errors as ERR
from sim.calendar import Calendar
from sim.staffing import APPRENTICE_RATE, Staffing
from sim import staffing as STF
from sim import energy as EN
from wqbus.topics import topic as _topic

# 工序 → 可用设备（第一个是默认设备）
OP_UNITS = {
    "下料 Sawing": ["saw-01"],
    "粗车 Rough turning": ["cnc-l01-a", "cnc-l01-b"],
    "精车 Finish turning": ["cnc-l01-b", "cnc-l01-a"],
    "调质 Quench & temper": ["ht-01"],
    "渗碳淬火 Carburizing": ["ht-01"],
    "铣键槽 Keyway milling": ["key-01"],
    "滚齿 Gear hobbing": ["hob-01"],
    "磨外圆 Cylindrical grinding": ["grd-01"],
    "铣结合面 Face milling": ["vmc-01"],
    "钻攻螺纹孔 Drilling & tapping": ["vmc-01"],
    "合箱钻铰销孔 Pin-hole reaming": ["hmc-01"],
    "镗轴承孔 Bearing-bore boring": ["hmc-01"],
    "零件检验 Part inspection": ["qc-01"],
    "部件装配 Sub-assembly": ["asm-01"],
    "总装 Final assembly": ["asm-01"],
    "跑合试验 Run-in test": ["test-01"],
    "出厂检验 Final inspection": ["qc-01"],
    "清洗包装 Cleaning & packing": ["asm-01"],
}
CAPACITY = {"ht-01": 20}
SETUP_MIN = {"cnc-l01-a": 10, "cnc-l01-b": 10, "grd-01": 8, "key-01": 6, "saw-01": 3, "ht-01": 5, "qc-01": 2}
WEAR_PER_PART = {"saw-01": 1 / 200, "cnc-l01-a": 1 / 60, "cnc-l01-b": 1 / 60, "key-01": 1 / 40,
                 "grd-01": 1 / 30, "hob-01": 1 / 40, "vmc-01": 1 / 80, "hmc-01": 1 / 80}
SPINDLE = {"saw-01": (60, 40), "cnc-l01-a": (900, 180), "cnc-l01-b": (1400, 90), "key-01": (1200, 80),
           "grd-01": (1800, 400), "hob-01": (300, 60), "vmc-01": (2500, 600), "hmc-01": (2000, 400)}
TOOL_CHANGE_MIN = {"grd-01": 8}
RATED_TORQUE_NM = {"WQR-105": 350.0}   # 额定输出转矩（与参数配置器一致）   # 磨床“换刀”即修整或更换砂轮
AGV_SPEED = 1.0                   # m/s（仿真）
LOAD_UNLOAD_S = 30
RAW_STORE, FG_STORE = "store-01", "store-02"     # 物流小车取毛坯、送成品的地方

try:                                   # 工厂清单（第 30 轮；freecad-ai-parts ADR-0064）：工序可用设备与设备参数取自清单
    from factory import plant as _plant
    _P = _plant.active()
except ImportError:
    if __import__("os").environ.get("WQ_PLANT_FILE"):   # 指定了清单却找不到 factory 包：不能悄悄用演示工厂
        raise
    _P = None
if _P:
    OP_UNITS, CAPACITY, SETUP_MIN = _P["OP_UNITS"], _P["CAPACITY"], _P["SETUP_MIN"]
    WEAR_PER_PART, SPINDLE, TOOL_CHANGE_MIN = _P["WEAR_PER_PART"], _P["SPINDLE"], _P["TOOL_CHANGE_MIN"]
    RAW_STORE, FG_STORE = _P["STORES"]["raw"], _P["STORES"]["finished"]

# 输出轴检验特性：(特性代号, 中文, 名义, 下限, 上限)。前三项与工厂数据“零件检验-输出轴”一致；
# 第 13 轮补右轴承位、轴承位圆跳动、键槽对称度，测量值由加工误差模型合成（sim/errors.py）
SH301_CHARS = [c for c in ERR.CHARS]


class Clock:
    """仿真时钟：sim = t0_sim + (wall - t0_wall) × speed。"""

    def __init__(self, speed=20.0, wall=time.time):
        self.speed, self.wall = float(speed), wall
        self.t0_wall = wall()
        self.t0_sim = 0.0

    def now(self):
        return self.t0_sim + (self.wall() - self.t0_wall) * self.speed

    def set_speed(self, speed):
        self.t0_sim, self.t0_wall, self.speed = self.now(), self.wall(), float(speed)


class Part:
    def __init__(self, serial, wo):
        self.serial, self.wo = serial, wo
        self.op_index = 0
        self.grind_wear = 0.0     # 磨削时砂轮已磨损的比例 0–1
        self.result = None


class Job:
    """一台设备上的一道工序（某工单的第 k 道）。"""

    def __init__(self, wo, op_index, unit):
        self.wo, self.op_index, self.unit = wo, op_index, unit
        self.op, self.std_min = wo.ops[op_index]
        self.qty = wo.qty
        self.started = False
        self.done = 0
        self.good = 0
        self.time_s = 0.0        # 累计加工时长（仿真秒）
        self.first_start = None

    @property
    def key(self):
        return (self.wo.name, self.op_index)


class WorkOrder:
    def __init__(self, name, item, qty, ops, corr=None):
        self.name, self.item, self.qty = name, item, qty
        self.ops = ops            # [(工序名, 每件分钟)]
        self.corr = corr or name
        tag = name.split("-")[-1]
        self.parts = [Part("{}-{}-{:02d}".format(item.replace("-", ""), tag, i + 1), self) for i in range(qty)]
        self.jobs = {}            # op_index → Job


class Machine:
    def __init__(self, unit):
        self.unit = unit
        self.capacity = CAPACITY.get(unit, 1)
        self.jobs = []            # 已派工的 Job，按派工顺序
        self.inbox = deque()      # 已送到、等待加工的零件
        self.active = {}          # token → (part, job, start, end)
        self.state = "idle"
        self.setup_until = None
        self.setup_job = None     # 最近一次调整针对的工序，同工序连续加工不再调整
        self.down_until = None
        self.down_reason = ""
        self.down_kind = "down"
        self.tool_life = 1.0
        self.last_status = None
        self.locked = None        # 第 18 轮 E2：挂牌上锁的许可证号（挂着锁不能复位、不会自动恢复）
        self.no_staff = False     # 第 18 轮 E4：这一班没人能开
        rp = REL.params(unit)      # 第 18 轮 E3：自上次保养以来的运行小时（情景开始时已经用了一阵）
        self.run_h = float(rp["init_h"]) if rp else 0.0
        self.fail_mode = None

    # 第 18 轮 E6：状态一变，能源计量在变之前把这一段的电量记下（引擎接上钩子；没接时什么也不做）
    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, v):
        old = getattr(self, "_state", None)
        self._state = v
        hook = getattr(self, "_hook", None)
        if hook is not None and old != v:
            hook(self, old, v)


class AGV:
    def __init__(self, unit, pos):
        self.unit, self.pos = unit, pos
        self.task = None          # dict(path, start, dist, part, frm, to)
        self.battery = 0.9
        self.heading = 0.0


class Engine:
    def __init__(self, publish, clock=None, mode="teach", auto_start=False, seed=None, status_every_s=2.0):
        """publish(topic, type, source, data, corr) —— 由 main.py 接到总线；测试里接到列表。"""
        self.pub = publish
        self.clock = clock or Clock()
        self.mode = mode
        self.auto_start = auto_start
        self.rng = random.Random(seed)
        self.status_every_s = status_every_s
        self.q = []               # 事件堆：(sim_t, seq, kind, payload)
        self.seq = itertools.count()
        self.machines = {u: Machine(u) for u in UNITS if u in _MACHINE_UNITS}
        self.agvs = {u: AGV(u, layout.AGV_HOME[u]) for u in layout.AGV_HOME}
        self.transfers = deque()  # 等 AGV 的搬运：(part, frm, to)
        self.wos = {}
        self.tokens = itertools.count(1)
        self._last_periodic = -1e9
        # 仿真 0 秒对应的工厂时间：默认为引擎创建时的真实时间；教学情景会改成情景开始的时刻
        self.epoch = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=self.clock.now())
        self.errors = ERR.ErrorModel(seed)       # 加工误差模型与问题情景（第 13 轮）
        # 班次日历（第 17 轮 C 期）：默认 24 小时连续；按班次时下班后不再开新件
        self.calendar = Calendar(tz=os.environ.get("WQ_TZ", "America/New_York"))
        self._shift_wait = {}                    # 设备 → 已排好的开工时刻（仿真秒）
        self.outsourced_done = []                # 外协回厂即完工的件：(时刻, 工单, 序列号)
        # 第 18 轮 E3：可靠性系数（0 关闭；1 正常；5 加速）。随机故障用单独的随机数，不影响原来的加工节拍和误差
        self.rel_factor = 0.0
        self.rel_rng = random.Random((seed or 0) * 7919 + 17)
        # 第 18 轮 E4：车间要有人（关闭时和以前完全一样）
        self.staffing = Staffing()
        self._staff_wait = {}                    # 设备 → 已排好的换班复查时刻（仿真秒）
        # 第 18 轮 E6：能源计量（关闭时和以前完全一样）
        self.energy = EN.Energy()
        self._e_pending, self._tou_wait = {}, {}
        self.energy_capture = None               # 推演用：某时刻的累计电量
        for m in self.machines.values():
            m._hook = self._on_state

    # ------------------------------------------------------------ 基础
    def now(self):
        return self.clock.now()

    def factory_ts(self, t=None):
        """工厂时间：仿真时刻换算成日历时间（倍速运行时比真实时间走得快）。ERPNext 的工时按它记。"""
        t = self.now() if t is None else t
        v = self.epoch + dt.timedelta(seconds=t)
        return v.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    def factory_dt(self, t=None):
        return self.epoch + dt.timedelta(seconds=self.now() if t is None else t)

    def sim_t(self, when):
        return (when - self.epoch).total_seconds()

    def set_calendar(self, cal):
        """换班次日历（加班、切换模式）：已在等开工的设备重新判断"""
        self.calendar = cal
        self._shift_wait.clear()
        for m in self.machines.values():
            self._try_start(m)
        self._emark_all()

    def _shift_closed(self, m, t):
        """按班次且现在下班：排好下次开工的事件，返回 True"""
        if self.calendar.mode == "continuous":
            return False
        now = self.factory_dt(t)
        if self.calendar.is_open(m.unit, now):
            return False
        nxt = self.calendar.next_open(m.unit, now)
        if nxt is not None:
            ts = self.sim_t(nxt)
            if self._shift_wait.get(m.unit) != ts:
                self._shift_wait[m.unit] = ts
                self.at(ts, "shift_open", unit=m.unit)
        return True

    def set_staffing(self, d):
        """平台下发排班算出的人员等级（第 18 轮 E4）；人多了的设备马上重新判断能不能开工"""
        self.staffing.update(d.get("enabled"), d.get("levels"), d.get("days"), bool(d.get("replace")))
        self._staff_wait.clear()
        for m in self.machines.values():
            self._try_start(m)
            self._status(m)
        self._emark_all()

    # ------------------------------------------------------------ 能源（第 18 轮 E6）
    def set_energy(self, d):
        """平台下发：enabled 开关、power 功率表、standby 自动待机、tou 错峰设备、inject / clear 教学问题"""
        e = self.energy
        t = self.now()
        was = e.enabled
        if was:
            self._emark_all(t)                   # 按旧设定把这一段记完
        if d.get("enabled") is not None:
            e.enabled = bool(d["enabled"])
        e.update(d)
        for x in d.get("clear") or []:
            self._eclear(x)
        for x in d.get("inject") or []:
            self._einject(x, t)
        if not e.enabled:
            e.cur, e.next_read = {}, None
            return
        if not was:
            e.cur, e.acc = {}, {}
            e.env.update({"t": None, "mist_i": 0.0, "noise_i": 0.0, "s": 0.0, "air_m3": 0.0, "water": 0.0})
            e.iv_start, e.next_read = t, None
            for m in self.machines.values():
                if m.state == "idle":
                    e.idle_since.setdefault(m.unit, t)
            self._schedule_read(t)
        self._emark_all(t)
        for m in self.machines.values():
            self._try_start(m)

    def _einject(self, x, t):
        f, k, u = self.energy.faults, x.get("kind"), x.get("unit")
        if k == "forgot" and u in self.machines:
            f.setdefault("forgot", {})[u] = t + float(x.get("hours", 12)) * 3600
            self.at(f["forgot"][u], "energy_mark", unit=u)
        elif k in ("leak", "mist"):
            f[k] = {"until": t + float(x.get("hours", 24 * 30)) * 3600}
        elif k == "degrade" and u in self.machines:
            f.setdefault("degrade", {})[u] = {"pct": float(x.get("pct", 0.3)), "t0": t}
        elif k == "ht_peak":                     # 下一个完整的峰时段（正在峰时段里就取再下一个，整段 3 小时都在以后）
            local = self.factory_dt(t).astimezone(self.calendar.tzi)
            s, e = EN.peak_window(local)
            if s is not None and s <= local:
                s, e = EN.peak_window(e)
            s, e = self.sim_t(s), self.sim_t(e)
            f["ht_peak"] = [s, e]
            for ts in (s, e, e + (e - s)):
                self.at(ts, "energy_mark", unit="ht-01")
        else:
            return
        if u in self.machines:
            self._emark(self.machines[u], t)

    def _eclear(self, x):
        f = self.energy.faults
        k, u = (x.get("kind"), x.get("unit")) if isinstance(x, dict) else (x, None)
        if k in ("forgot", "degrade") and u:
            (f.get(k) or {}).pop(u, None)
        else:
            f.pop(k, None)

    def _ebucket(self, t):
        return EN.bucket(self.factory_dt(t).astimezone(self.calendar.tzi))

    def _attended(self, m, t):
        """这一班有没有人管这台（按班次下班、排班里这一班没人 → 没人，下班的人顺手关机）"""
        now = self.factory_dt(t)
        if self.calendar.mode == "shift" and not self.calendar.is_open(m.unit, now):
            return False
        if self.staffing.enabled and self.staffing.level(m.unit, now.astimezone(self.calendar.tzi)) == 0:
            return False
        return True

    def _ht_peak_on(self, t):
        w = self.energy.faults.get("ht_peak")
        if not w:
            return False
        s, e = w
        if "ht-01" in self.energy.tou:          # 错峰：这一炉挪到峰时之后
            s, e = e, e + (e - s)
        return s <= t < e

    def _epower(self, m, t):
        """这台设备此刻的档位和功率 (档, kW)"""
        e = self.energy
        run, idle, stby = e.power.get(m.unit, (0.0, 0.0, 0.0))
        st = m.state
        if st == "run":
            return "run", run * e.degrade(m.unit, t)
        if st == "setup":
            return "setup", idle
        if st in ("down", "fault"):
            return "down", stby
        if m.unit in EN.NO_STANDBY:
            return ("run", run) if m.unit == "ht-01" and self._ht_peak_on(t) else ("idle", idle)
        if m.unit not in EN.AUTO and not self._attended(m, t) and not e.forgot(m.unit, t):
            return "off", 0.0
        n = e.standby.get(m.unit)
        if n:
            since = e.idle_since.get(m.unit, t)
            if t - since >= n * 60 - 1e-6:
                return "standby", stby
            ts = since + n * 60
            if self._e_pending.get(m.unit) != ts:
                self._e_pending[m.unit] = ts
                self.at(ts, "energy_mark", unit=m.unit)
        return "idle", idle

    def _on_state(self, m, old, new):
        e = self.energy
        if not e.enabled:
            return
        t = self.now()
        if new == "idle":
            e.idle_since[m.unit] = t
        self._emark(m, t)

    def _eshared_accrue(self, t):
        e = self.energy
        for k in ("air", "light"):
            e.accrue(k, t, self._ebucket)
        e.accrue_env(t)

    def _eshared_update(self, t):
        e = self.energy
        running = [u for u, c in e.cur.items() if u in EN.POWER and c[1] == "run"]
        on = [u for u, c in e.cur.items() if u in EN.POWER and c[1] != "off"]
        anyone = any(self._attended(m, t) for m in self.machines.values() if m.unit not in EN.AUTO)
        flow = EN.AIR_PER_USER * sum(1 for u in running if u in EN.AIR_USERS) + (EN.LEAK_M3 if e.leak(t) else 0.0)
        e.cur["air"] = [t, "run", EN.AIR_UNLOAD_KW + EN.AIR_KW_PER_M3 * flow]
        e.cur["light"] = [t, "run" if anyone else "idle", EN.LIGHT_BASE + (EN.LIGHT_SHIFT if anyone else 0.0)]
        e.env.update({"mist": EN.mist_mg(running, e.mist_fault(t)), "noise": EN.noise_db(running, e.quiet), "air_flow": flow,
                      "water_h": EN.WATER_PER_H if anyone else 0.0, "on": len(on)})
        e.env["max_mist"] = max(e.env.get("max_mist", 0.0), e.env["mist"])
        e.env["max_noise"] = max(e.env.get("max_noise", 0.0), e.env["noise"])

    def _emark(self, m, t=None):
        e = self.energy
        if not e.enabled:
            return
        t = self.now() if t is None else t
        self._eshared_accrue(t)
        e.accrue(m.unit, t, self._ebucket)
        ps, kw = self._epower(m, t)
        c = e.cur.get(m.unit)
        e.cur[m.unit] = [max(t, c[0]) if c else t, ps, kw]
        self._eshared_update(t)

    def _emark_all(self, t=None):
        if not self.energy.enabled:
            return
        t = self.now() if t is None else t
        for m in self.machines.values():
            self._emark(m, t)

    def _ev_energy_mark(self, t, unit=None):
        if self._e_pending.get(unit) is not None and self._e_pending[unit] <= t + 1e-6:
            self._e_pending.pop(unit, None)
        if unit in self.machines:
            self._emark(self.machines[unit])
        else:
            self._emark_all()

    def _ev_demo_inject(self, t, inject):
        self.set_energy({"inject": inject})

    def _ev_energy_capture(self, t):
        if self.energy.enabled:
            self._emark_all(t)
            self.energy_capture = self.energy.totals()

    def _tou_closed(self, m, t):
        """错峰：峰时不开新的（正在做的做完）；排好峰时结束再开"""
        if m.unit not in self.energy.tou:
            return False
        local = self.factory_dt(t).astimezone(self.calendar.tzi)
        if EN.bucket(local) != "peak":
            return False
        end = self.sim_t(EN.peak_window(local)[1])
        if self._tou_wait.get(m.unit) != end:
            self._tou_wait[m.unit] = end
            self.at(end + 1, "tou_open", unit=m.unit)
        return True

    def _ev_tou_open(self, t, unit):
        self._tou_wait.pop(unit, None)
        self._try_start(self.machines[unit])

    def _epart(self, m, item, ct, n_in):
        e = self.energy
        kw = e.power.get(m.unit, (0.0,))[0] * e.degrade(m.unit, self.now())
        kwh = kw * ct / 3600.0 / max(1, n_in)
        a = e._slot(m.unit)["parts"].setdefault(item, [0, 0.0])
        a[0] += 1
        a[1] += kwh
        if m.unit == "asm-01":
            e.env["water"] = e.env.get("water", 0.0) + EN.WATER_PER_PART

    def _schedule_read(self, t):
        ts = self.factory_dt(t).timestamp()
        nxt = (int(ts // EN.READ_S) + 1) * EN.READ_S
        self.energy.next_read = t + (nxt - ts)
        self.at(self.energy.next_read, "energy_read")

    def _ev_energy_read(self, t):
        e = self.energy
        if not e.enabled or e.next_read is None or t < e.next_read - 1e-6:
            return
        self._emark_all(t)
        secs = max(1e-6, t - (e.iv_start if e.iv_start is not None else t))
        meters, tot = {}, 0.0
        for u in EN.POWER:
            a = e.acc.get(u) or {"kwh": 0.0, "s": {}, "k": {}, "parts": {}}
            tot += a["kwh"]
            meters[EN.meter_of(u)] = {"value": round(a["kwh"], 4), "kw": round(a["kwh"] * 3600 / secs, 3),
                                      "s": {k: round(v, 1) for k, v in a["s"].items()}, "k": {k: round(v, 4) for k, v in (a.get("k") or {}).items()},
                                      "parts": {i: [n, round(k, 4)] for i, (n, k) in a["parts"].items()}}
        air = (e.acc.get("air") or {}).get("kwh", 0.0)
        light = (e.acc.get("light") or {}).get("kwh", 0.0)
        tot += air + light
        meters["E-AIR"] = {"value": round(air, 4), "kw": round(air * 3600 / secs, 3)}
        meters["E-TOTAL"] = {"value": round(tot, 4), "kw": round(tot * 3600 / secs, 3)}
        meters["F-AIR"] = {"value": round(e.env.get("air_m3", 0.0), 3)}
        meters["W-MAIN"] = {"value": round(e.env.get("water", 0.0), 4)}
        s_ = e.env.get("s") or 0.0
        env = {"mist": round(e.env["mist_i"] / s_, 3) if s_ else round(e.env.get("mist", 0.0), 3),
               "noise": round(10 * math.log10(e.env["noise_i"] / s_), 2) if s_ and e.env["noise_i"] > 0 else round(e.env.get("noise", 0.0), 2)}
        f = e.faults
        active = [k for k in ("leak", "mist") if (f.get(k) and t < f[k]["until"])] + \
                 ["forgot:" + u for u, until in (f.get("forgot") or {}).items() if t < until] + ["degrade:" + u for u in (f.get("degrade") or {})] + \
                 (["ht_peak"] if f.get("ht_peak") and t < f["ht_peak"][1] + (f["ht_peak"][1] - f["ht_peak"][0]) else [])
        self.pub(_topic("machining", "sim", "energy"), "energy.reading", "sim",
                 {"ts": self.factory_ts(t - secs), "end": self.factory_ts(t), "seconds": round(secs, 1), "bucket": self._ebucket(t - secs),
                  "meters": meters, "env": env, "standby": e.standby, "tou": e.tou, "faults": active}, None)
        e.acc = {}
        e.env.update({"mist_i": 0.0, "noise_i": 0.0, "s": 0.0, "air_m3": 0.0, "water": 0.0})
        e.iv_start = t
        self._schedule_read(t)

    def _staff_level(self, m, t):
        """这一班这台设备的人员等级；没人时排好换班时复查，返回 0"""
        if not self.staffing.enabled:
            return 2
        local = self.factory_dt(t).astimezone(self.calendar.tzi)
        lv = self.staffing.level(m.unit, local)
        if lv == 0:
            ts = self.sim_t(STF.next_change(local).astimezone(dt.timezone.utc))
            if self._staff_wait.get(m.unit) != ts:
                self._staff_wait[m.unit] = ts
                self.at(ts, "staff_check", unit=m.unit)
        return lv

    def _ev_staff_check(self, t, unit):
        if self._staff_wait.get(unit) is not None and self._staff_wait[unit] <= t + 1e-6:
            self._staff_wait.pop(unit, None)
        self._try_start(self.machines[unit])

    def _ev_shift_open(self, t, unit):
        if self._shift_wait.get(unit) is not None and self._shift_wait[unit] <= t + 1e-6:
            self._shift_wait.pop(unit, None)
        self._try_start(self.machines[unit])

    def at(self, t, kind, **payload):
        heapq.heappush(self.q, (t, next(self.seq), kind, payload))

    def publish_all_status(self):
        for m in self.machines.values():
            self._status(m, force=True)
        for a in self.agvs.values():
            self._agv_status(a)

    def run_due(self):
        """处理所有到期事件；定期发状态。返回处理的事件数。"""
        n = 0
        while self.q and self.q[0][0] <= self.now():
            t, _, kind, p = heapq.heappop(self.q)
            getattr(self, "_ev_" + kind)(t, **p)
            n += 1
        wall = time.time()
        if wall - self._last_periodic >= self.status_every_s:
            self._last_periodic = wall
            for m in self.machines.values():
                if m.state in ("run", "setup") or m.last_status is None:
                    self._status(m, force=True)
            for a in self.agvs.values():
                if a.task:
                    self._agv_status(a)
        return n

    def next_event_time(self):
        return self.q[0][0] if self.q else None

    # ------------------------------------------------------------ 指令
    def command(self, unit, data, corr=None):
        """处理一条 machine.cmd，返回 (accepted, reason)，并在总线上应答。"""
        ok, reason = self._command(unit, data, corr)
        if unit in self.machines:
            self.pub(unit_topic(unit, "cmd/ack"), "machine.ack", "sim/" + unit,
                     {"accepted": ok, "reason": reason, "command": data.get("command"),
                      "work_order": data.get("work_order"), "operation": data.get("operation")}, corr)
        return ok, reason

    def _command(self, unit, d, corr):
        m = self.machines.get(unit)
        if m is None:
            return False, "没有这台设备：" + unit
        cmd = d["command"]
        if cmd == "dispatch":
            wo = self.wos.get(d.get("work_order"))
            if wo is None:
                if not d.get("routing"):
                    return False, "未知工单，派工时需附工艺路线"
                wo = WorkOrder(d["work_order"], d.get("item", "SH-301"), int(d.get("qty", 1)),
                               [tuple(x) for x in d["routing"]], corr)
                self.wos[wo.name] = wo
            idx = self._op_index(wo, d.get("operation"))
            if idx is None:
                return False, "工单 {} 的工艺路线里没有工序 {}".format(wo.name, d.get("operation"))
            if unit not in OP_UNITS.get(wo.ops[idx][0], []):
                return False, "{} 不能做 {}".format(UNITS[unit][1], wo.ops[idx][0])
            if idx in wo.jobs:
                return False, "该工序已派给 {}".format(wo.jobs[idx].unit)
            job = Job(wo, idx, unit)
            wo.jobs[idx] = job
            m.jobs.append(job)
            # 已经送到别的设备、等这道工序的零件，改送到这台
            for other in self.machines.values():
                if other is not m:
                    for p in [p for p in other.inbox if p.wo is wo and p.op_index == idx]:
                        other.inbox.remove(p)
                        m.inbox.append(p)
            if idx == 0:          # 第一道：原材料在锯床旁，派工即到料
                for p in wo.parts:
                    m.inbox.append(p)
            if self.auto_start:
                job.started = True
            self._try_start(m)
            self._status(m)
            return True, "已派工"
        if cmd == "start":
            job = self._find_job(m, d)
            if job is None:
                return False, "这台设备上没有该工序的派工"
            job.started = True
            self._try_start(m)
            self._status(m)
            if m.state in ("down", "fault"):
                return True, "设备{}中，已登记开工，恢复后自动开始".format("停机" if m.state == "down" else "故障")
            return True, "已开工"
        if cmd == "pause":
            job = self._find_job(m, d)
            if job is None:
                return False, "这台设备上没有该工序的派工"
            job.started = False
            self._status(m)
            return True, "当前件做完后暂停"
        if cmd == "pm_done":                   # 第 18 轮 E3：保养做完，运行小时清零
            m.run_h = 0.0
            m.fail_mode = None
            if (self.energy.faults.get("degrade") or {}).pop(m.unit, None) is not None:   # 第 18 轮 E6：保养修好劣化
                self._emark(m)
            self._status(m, force=True)
            return True, "保养完成，运行小时清零"
        if cmd == "set_run_h":                 # 教学：老师把运行小时往前拨（模拟保养逾期）
            if self.mode != "teach":
                return False, "生产模式不接受"
            m.run_h = max(0.0, float(d.get("hours", 0)))
            self._status(m, force=True)
            return True, "运行小时设为 {:g}".format(m.run_h)
        if cmd == "set_reliability":
            self.set_reliability(d.get("factor", 1))
            return True, "可靠性系数 {:g}".format(self.rel_factor)
        if cmd == "lockout":                   # 第 18 轮 E2：挂牌上锁（生产、教学都接受）：停机，直到 unlock
            permit = str(d.get("permit") or "LOTO")
            minutes = max(1.0, float(d.get("minutes", 120)))
            reason = "挂牌上锁 {}：{}".format(permit, d.get("reason") or "整改")
            delay = float(d.get("delay_minutes") or 0)
            if delay > 0:
                self.at(self.now() + delay * 60, "lockout_due", unit=m.unit, permit=permit, minutes=minutes, reason=reason)
                return True, "{:.0f} 分钟后挂牌上锁（{}）".format(delay, permit)
            self._lock(m, self.now(), permit, minutes, reason)
            return True, "已挂牌上锁（{}），预计整改 {:.0f} 分钟".format(permit, minutes)
        if cmd == "unlock":
            if not m.locked:
                return False, "这台设备没有挂锁"
            m.locked = None
            if m.state in ("down", "fault"):
                self._recover(m, self.now(), manual=True)
            self._status(m, force=True)
            return True, "已解锁，设备恢复"
        if cmd == "reset":
            if m.locked:
                return False, "挂牌上锁中（{}），要先在“安全环保”页验收、解锁".format(m.locked)
            if m.state not in ("down", "fault"):
                return True, "设备正常，无需复位"
            self._recover(m, self.now(), manual=True)
            return True, "已复位"
        if cmd == "inject_fault":
            if self.mode != "teach":
                return False, "生产模式不接受故障注入"
            minutes = float(d.get("minutes", 30))
            kind = "fault" if d.get("kind") == "fault" else "down"
            self._go_down(m, self.now(), minutes * 60, d.get("reason", "设备故障"), kind)
            return True, "已注入：{} {} 分钟".format(d.get("reason", "故障"), minutes)
        if cmd == "reassign":                  # 第 17 轮 C 期：改派（同类设备）
            return self._reassign(m, d)
        if cmd == "reorder":                   # 调序 / 插单：把某工单的这道工序排到最前
            job = self._find_job(m, d)
            if job is None:
                return False, "这台设备上没有该工序的派工"
            m.jobs.remove(job)
            m.jobs.insert(0, job)
            first = [p for p in m.inbox if p.wo is job.wo and p.op_index == job.op_index]
            m.inbox = deque(first + [p for p in m.inbox if p not in first])
            self._try_start(m)
            self._status(m, force=True)
            return True, "已排到最前"
        if cmd == "expedite_repair":           # 维修加急：剩余停机时间按比例缩短
            if m.state not in ("down", "fault") or not m.down_until:
                return False, "设备没有停机"
            f = float(d.get("factor", 0.5))
            if not 0 < f <= 1:
                return False, "缩短比例应在 0–1 之间"
            t = self.now()
            m.down_until = t + (m.down_until - t) * f
            self.at(m.down_until, "recover", unit=m.unit, until=m.down_until)
            self._status(m, force=True)
            return True, "预计 {:.0f} 分钟后恢复".format((m.down_until - t) / 60)
        if cmd == "outsource":                 # 外协：接下来 qty 件这道工序送外面做，days 天后回来
            return self._outsource(m, d)
        return False, "不支持的指令 " + cmd

    def _reassign(self, m, d):
        """d.to_unit：把 m 上某工单某工序的派工（含已送到、还没开工的件）换到同类设备"""
        job = self._find_job(m, d)
        to = self.machines.get(d.get("to_unit"))
        if job is None:
            return False, "这台设备上没有该工序的派工"
        if to is None or to is m:
            return False, "要改派到哪台设备？"
        if to.unit not in OP_UNITS.get(job.op, []):
            return False, "{} 不能做 {}".format(UNITS[to.unit][1], job.op)
        m.jobs.remove(job)
        job.unit = to.unit
        to.jobs.append(job)
        moving = [p for p in m.inbox if p.wo is job.wo and p.op_index == job.op_index]
        for p in moving:
            m.inbox.remove(p)
            to.inbox.append(p)
        # 已经在路上送往原设备的件，改送新设备
        self.transfers = deque((p, f, to.unit if (t_ == m.unit and p.wo is job.wo and p.op_index == job.op_index) else t_)
                               for p, f, t_ in self.transfers)
        for a in self.agvs.values():
            if a.task and a.task["to"] == m.unit and a.task["part"].wo is job.wo and a.task["part"].op_index == job.op_index:
                a.task["to_override"] = to.unit
        self._try_start(to)
        self._try_start(m)
        self._status(m, force=True)
        self._status(to, force=True)
        return True, "已改派到 {}（{} 件随之转过去）".format(to.unit.upper(), len(moving))

    def _outsource(self, m, d):
        job = self._find_job(m, d)
        if job is None:
            return False, "这台设备上没有该工序的派工"
        qty, days = int(d.get("qty", 1)), float(d.get("days", 2))
        left = job.qty - job.done - sum(1 for _, (p, j, *_r) in m.active.items() if j is job)
        if not 1 <= qty <= left:
            return False, "外协件数应在 1–{} 之间".format(left)
        job.outsource = {"left": qty, "days": days, "sent": getattr(job, "outsource", {}).get("sent", 0)}
        for p in [p for p in m.inbox if p.wo is job.wo and p.op_index == job.op_index]:
            if job.outsource["left"] <= 0:
                break
            m.inbox.remove(p)
            self._send_out(job, p)
        self._status(m, force=True)
        return True, "接下来 {} 件外协，{:g} 天后回厂".format(qty, days)

    def _send_out(self, job, p):
        o = job.outsource
        o["left"] -= 1
        o["sent"] += 1
        job.qty -= 1                           # 本厂这道工序少做一件
        self.at(self.now() + o["days"] * 86400, "outsource_back", wo=job.wo.name, serial=p.serial, op_index=job.op_index)
        if job.done >= job.qty and job in self.machines[job.unit].jobs and not any(j is job for _, (pp, j, *_r) in self.machines[job.unit].active.items()):
            self.machines[job.unit].jobs.remove(job)

    def _ev_outsource_back(self, t, wo, serial, op_index):
        w = self.wos[wo]
        p = next(x for x in w.parts if x.serial == serial)
        p.op_index = op_index + 1
        nxt = w.jobs.get(p.op_index) if p.op_index < len(w.ops) else None
        to = nxt.unit if nxt else (FG_STORE if p.op_index >= len(w.ops) else OP_UNITS[w.ops[p.op_index][0]][0])
        # 外协回厂不发 machine.event（桥接会把它当本厂报工）；最后一道就是外协的件，完工时刻记在这里给推演用
        if p.op_index >= len(w.ops):
            self.outsourced_done.append((t, wo, serial))
        if to in self.machines:
            self.machines[to].inbox.append(p)
            self._try_start(self.machines[to])

    def _ev_release(self, t, work_order, item, qty, corr=None):
        """推演用：某时刻下达一张新工单（插单、等料的工单到料后下达），各工序派到首选设备"""
        ops = routing_for(item)
        for op, _ in ops:
            self.command(OP_UNITS[op][0], {"command": "dispatch", "work_order": work_order, "operation": op, "qty": int(qty),
                                           "item": item, "routing": ops}, corr or work_order)
        for op, _ in ops:
            j = self._find_job(self.machines[OP_UNITS[op][0]], {"work_order": work_order, "operation": op})
            if j and not j.started:
                j.started = True
        for m in self.machines.values():
            self._try_start(m)

    def _op_index(self, wo, op):
        if op is None:
            return None
        for i, (name, _) in enumerate(wo.ops):
            if name == op or name.split(" ")[0] == op:
                return i
        return None

    def _find_job(self, m, d):
        for j in m.jobs:
            if j.wo.name == d.get("work_order") and (d.get("operation") is None or
                                                    j.op == d["operation"] or j.op.split(" ")[0] == d["operation"]):
                return j
        return None

    # ------------------------------------------------------------ 加工
    def _startable(self, m):
        """inbox 中第一件其工序已开工的零件。"""
        for p in list(m.inbox):
            job = p.wo.jobs.get(p.op_index)
            if job and job.unit == m.unit and job.started:
                return p, job
        return None, None

    def _try_start(self, m):
        t = self.now()
        while len(m.active) < m.capacity:
            if m.state in ("down", "fault") or (m.setup_until and m.setup_until > t):
                return
            p, job = self._startable(m)
            if p is None:
                break
            if self._shift_closed(m, t):         # 下班了：正在做的件做完，不开新件
                break
            lv = self._staff_level(m, t)         # 第 18 轮 E4：这一班没人能开就停在“缺人”
            m.no_staff = lv == 0
            if lv == 0:
                break
            if self.energy.enabled and self._tou_closed(m, t):     # 第 18 轮 E6：错峰，峰时不开新炉
                break
            if self.energy.enabled and not m.active and self._epower(m, t)[0] == "standby":
                # 第 18 轮 E6：自动待机后再开，先预热（按调整算，不改原来的调整记录）
                m.setup_until = t + EN.WARM_MIN * 60
                m.state = "setup"
                self.at(m.setup_until, "setup_done", unit=m.unit)
                self._status(m)
                return
            if m.setup_job != job.key and not m.active:
                # 新工序先调整（装夹、对刀、调程序）
                m.setup_job = job.key
                dur = SETUP_MIN.get(m.unit, 5) * 60
                m.setup_until = t + dur
                m.state = "setup"
                self.at(m.setup_until, "setup_done", unit=m.unit)
                self._status(m)
                return
            m.inbox.remove(p)
            std = job.std_min * 60
            wear = 1 - m.tool_life
            factor = self.rng.uniform(0.96, 1.10) + 0.08 * wear
            dur = std * factor
            if lv == 1:                          # 只有学徒：按 60% 的速度
                dur = dur / APPRENTICE_RATE
            tok = next(self.tokens)
            m.active[tok] = (p, job, t, t + dur)
            if job.first_start is None:
                job.first_start = t
            m.state = "run"
            if m.unit == "grd-01":
                p.grind_wear = wear
            self.errors.on_process(m.unit, p, wear)
            self.at(t + dur, "cycle_end", unit=m.unit, token=tok)
            self.pub(unit_topic(m.unit, "event"), "machine.event", "sim/" + m.unit,
                     {"event": "cycle_start", "work_order": job.wo.name, "operation": job.op,
                      "op_index": job.op_index, "n_ops": len(job.wo.ops), "item": job.wo.item,
                      "part_serial": p.serial, "std_time_s": std, "factory_ts": self.factory_ts(t),
                      **({"lots": p.lots} if getattr(p, "lots", None) else {})}, job.wo.corr)   # 第 51 轮：这一件用的到货批次
        if not m.active and m.state not in ("down", "fault") and not (m.setup_until and m.setup_until > t):
            m.state = "idle"
        self._status(m)

    def _ev_setup_done(self, t, unit):
        m = self.machines[unit]
        if m.setup_until and m.setup_until <= t + 1e-6:
            m.setup_until = None
            if m.state == "setup":
                m.state = "idle"
            self._try_start(m)

    def _ev_cycle_end(self, t, unit, token):
        m = self.machines[unit]
        if token not in m.active:
            return                          # 停机时被顺延，旧事件作废
        n_in = len(m.active)
        p, job, start, end = m.active.pop(token)
        ct = end - start
        if self.energy.enabled:                 # 第 18 轮 E6：这一件的运行电量（炉子按同炉件数分摊）
            self._epart(m, job.wo.item, ct, n_in)
        job.done += 1
        job.time_s += ct
        m.tool_life = max(0.0, m.tool_life - WEAR_PER_PART.get(unit, 0))
        corr = job.wo.corr
        spec = _measure_spec(job.wo.item, job.op)     # 清单第 2 版的测量特性（第 45 轮：关节测试、整机标定……）
        if unit == "qc-01" and job.wo.item == "SH-301":
            p.result = self._measure(p, corr)
        elif spec:
            p.result = self._measure_chars(p, unit, job, spec, corr)
        if unit == "test-01":
            self._torque_log(p, job, corr)
        good = p.result != "fail" if (unit == "qc-01" or spec) else True
        if good:
            job.good += 1
        self.pub(unit_topic(unit, "event"), "machine.event", "sim/" + unit,
                 {"event": "cycle_end", "work_order": job.wo.name, "operation": job.op,
                  "op_index": job.op_index, "n_ops": len(job.wo.ops), "item": job.wo.item,
                  "part_serial": p.serial, "cycle_time_s": round(ct, 1),
                  "factory_ts": self.factory_ts(end), "factory_start_ts": self.factory_ts(start),
                  "std_time_s": job.std_min * 60, "good": good, "qty_done": job.done, "qty": job.qty}, corr)
        if job.done == job.qty:
            self.pub(unit_topic(unit, "event"), "machine.event", "sim/" + unit,
                     {"event": "op_complete", "work_order": job.wo.name, "operation": job.op,
                      "op_index": job.op_index, "qty": job.qty, "qty_good": job.good,
                      "time_s": round(job.time_s, 1), "item": job.wo.item, "factory_ts": self.factory_ts(t),
                      "last_op": job.op_index == len(job.wo.ops) - 1}, corr)
            m.jobs.remove(job)
        # 送下一道
        p.op_index += 1
        nxt_job = job.wo.jobs.get(p.op_index)
        if nxt_job is not None and getattr(nxt_job, "outsource", None) and nxt_job.outsource["left"] > 0:
            self._send_out(nxt_job, p)         # 下一道外协：直接送出厂
        elif p.op_index < len(job.wo.ops):
            nxt = job.wo.jobs.get(p.op_index)
            to = nxt.unit if nxt else OP_UNITS[job.wo.ops[p.op_index][0]][0]
            self.transfers.append((p, unit, to))
            self._dispatch_agvs()
        else:
            self.transfers.append((p, unit, FG_STORE))
            self._dispatch_agvs()
        # 换刀
        if unit in WEAR_PER_PART and m.tool_life < 0.08:
            self.pub(unit_topic(unit, "event"), "machine.event", "sim/" + unit,
                     {"event": "tool_change", "message": "砂轮修整" if unit == "grd-01" else "换刀",
                      "tool_life_before": round(m.tool_life, 3)}, corr)
            m.tool_life = 1.0
            dur = TOOL_CHANGE_MIN.get(unit, 5) * 60
            m.setup_until = t + dur
            m.state = "setup"
            self.at(m.setup_until, "setup_done", unit=unit)
        self._age(m, t, ct / 3600.0 / max(1, m.capacity))
        self._try_start(m)

    # ------------------------------------------------------------ 可靠性（第 18 轮 E3）
    def set_reliability(self, factor):
        self.rel_factor = max(0.0, min(10.0, float(factor)))

    def _age(self, m, t, dt_h):
        """运行小时累加；可靠性打开时按威布尔条件概率抽签，坏了就按故障模式停机（平均修复时间附近随机）"""
        rp = REL.params(m.unit)
        if not rp or dt_h <= 0:
            return
        t0 = m.run_h
        m.run_h += dt_h
        f = self.rel_factor
        if f <= 0 or m.state in ("down", "fault"):
            return
        p = REL.cond_fail(t0 * f, dt_h * f, rp["beta"], rp["eta_h"])
        if self.rel_rng.random() >= p:
            return
        code, name, part = self.rel_rng.choice(rp["modes"])
        dur = rp["mttr_min"] * 60 * self.rel_rng.uniform(0.6, 1.6)
        m.fail_mode = code
        self._go_down(m, t, dur, "故障：" + name, "fault",
                      extra={"failure": code, "failure_name": name, "part": part, "run_h_pm": round(m.run_h, 1)})

    def _torque_log(self, p, job, corr):
        """跑合试验台每做完一台，发一条输出轴转矩记录（第 11 轮疲劳寿命用）"""
        self.pub(unit_topic("test-01", "torque"), "test.torque", "sim/test-01",
                 torque_record(p.serial, job.wo.name, job.wo.item), corr)

    def _measure(self, p, corr):
        result = "pass"
        vals = self.errors.measure(p, self.rng)
        for code, name, nom, lo, hi, v in vals:
            r = "pass" if lo <= v <= hi else "fail"
            if r == "fail":
                result = "fail"
            self.pub(unit_topic("qc-01", "measurement"), "quality.measurement", "sim/qc-01",
                     {"part_serial": p.serial, "item": p.wo.item, "work_order": p.wo.name,
                      "characteristic": code, "name": name, "nominal_mm": nom,
                      "lower_tol_mm": lo, "upper_tol_mm": hi, "value_mm": v, "result": r,
                      "n_chars": len(vals), "factory_ts": self.factory_ts()}, corr)
        return result

    def _measure_chars(self, p, unit, job, spec, corr):
        """清单里写的测量特性（第 45 轮）：名义值 + 慢漂移 + 正态散布 σ（σ 是清单里的示例值），逐项发 quality.measurement"""
        from factory import data
        result = "pass"
        drift = self.__dict__.setdefault("_meas_drift", {})
        tmpl = (data.ITEMS.get(job.wo.item) or (None,) * 6)[5]      # ERPNext 检验模板（桥接建检验单用）
        st = getattr(p, "err", None) or {}
        trace = {k: v for k, v in (("assembled_on", st.get("_ja")), ("lot", getattr(p, "hd_lot", None))) if v}   # 分层用（第 47 轮）
        for c in spec:
            key = (job.wo.item, c["code"])
            d = drift.get(key, 0.0) * 0.95 + self.rng.gauss(0, c["sigma"] * 0.1)    # 均值慢慢游走、有回复（稳态约 0.3σ，第 47 轮从 0.75σ 调小）
            drift[key] = d
            v = round(c["nominal"] + d + self.rng.gauss(0, c["sigma"]) + self.errors.plant_offset(p, c["code"]), 4)
            extra = {}
            if c["code"] == "joint_zero":                    # 第 55 轮：零位残差记下，装整机时用
                self.errors.note_joint_zero(job.wo.item, v)
            if c["code"] == "joint_friction":                # 第 58 轮：空载摩擦力矩记下，装整机时用（负载跑合台的实测力矩）
                self.errors.note_joint_friction(job.wo.item, v)
            if c["code"] == "cr_abs":                        # 第 55 轮：整机标定真的算（sim/calib.py）：标定前、后的绝对定位误差
                from sim import calib
                zeros = self.errors.robot_zeros(p)
                st = p.err
                cal = st.get("_calib") or calib.case(p.serial, zeros)
                st["_calib"] = cal
                v = round(cal["after_mean_mm"], 4)
                extra = {"calib": {"zero_arcsec": zeros, "before_mm": cal["before_mean_mm"], "after_max_mm": cal["after_max_mm"],
                                   "cond": cal["cond"], "n": cal["n"], "friction_nm": self.errors.robot_friction(p)}}
            r = "pass" if c["lo"] <= v <= c["hi"] else "fail"
            if r == "fail":
                result = "fail"
            self.pub(unit_topic(unit, "measurement"), "quality.measurement", "sim/" + unit,
                     {"part_serial": p.serial, "item": job.wo.item, "work_order": job.wo.name, "operation": job.op,
                      "characteristic": c["code"], "name": c["name"], "unit": c.get("unit") or "mm",
                      "nominal_mm": c["nominal"], "lower_tol_mm": c["lo"], "upper_tol_mm": c["hi"], "value_mm": v, "result": r,
                      "n_chars": len(spec), "factory_ts": self.factory_ts(),
                      **({"template": tmpl, "spec": "{} ({})".format(c["name"], c.get("unit") or "mm")} if tmpl else {}),
                      **trace, **extra}, corr)
        return result

    # ------------------------------------------------------------ 停机
    def _go_down(self, m, t, dur_s, reason, kind="down", extra=None):
        m.state = kind
        m.down_reason, m.down_kind = reason, kind
        m.down_until = t + dur_s
        m.down_since = t
        self.pub(unit_topic(m.unit, "event"), "machine.event", "sim/" + m.unit,
                 dict({"event": "fault" if kind == "fault" else "alarm", "code": "E-" + m.unit.upper(),
                       "message": reason, "expected_duration_s": dur_s, "factory_ts": self.factory_ts(t)}, **(extra or {})), None)
        self.at(m.down_until, "recover", unit=m.unit, until=m.down_until)
        self._status(m, force=True)

    def _ev_recover(self, t, unit, until):
        m = self.machines[unit]
        if m.down_until == until:
            if m.locked:                       # 挂着锁：整改超时，不自动恢复，每 30 分钟顺延
                m.down_until = t + 1800
                self.at(m.down_until, "recover", unit=unit, until=m.down_until)
                self._status(m, force=True)
                return
            self._recover(m, t)

    def _lock(self, m, t, permit, minutes, reason):
        if m.state in ("down", "fault") and m.down_until:
            m.down_reason = reason
            m.down_until = max(m.down_until, t + minutes * 60)
            self.at(m.down_until, "recover", unit=m.unit, until=m.down_until)
            m.locked = permit
            self._status(m, force=True)
            return
        m.locked = permit
        self._go_down(m, t, minutes * 60, reason, "down")

    def _ev_lockout_due(self, t, unit, permit, minutes, reason):
        self._lock(self.machines[unit], t, permit, minutes, reason)

    def _ev_unlock_due(self, t, unit):
        """推演用：整改按时做完，自动解锁"""
        m = self.machines[unit]
        if m.locked:
            m.locked = None
            if m.state in ("down", "fault"):
                self._recover(m, t, manual=True)

    def _recover(self, m, t, manual=False):
        lost = t - getattr(m, "down_since", t)
        # 被打断的件顺延停机时长
        for tok, (p, job, s, e) in list(m.active.items()):
            ntok = next(self.tokens)
            del m.active[tok]
            m.active[ntok] = (p, job, s, e + lost)
            self.at(e + lost, "cycle_end", unit=m.unit, token=ntok)
        m.down_until = None
        m.state = "run" if m.active else "idle"
        self.pub(unit_topic(m.unit, "event"), "machine.event", "sim/" + m.unit,
                 {"event": "recover", "message": ("人工复位：" if manual else "") + m.down_reason,
                  "downtime_s": round(lost, 1), "factory_ts": self.factory_ts(t)}, None)
        self._try_start(m)

    # ------------------------------------------------------------ AGV
    def _dispatch_agvs(self):
        t = self.now()
        for a in self.agvs.values():
            if not self.transfers:
                return
            if a.task:
                continue
            p, frm, to = self.transfers.popleft()
            src, dst = layout.dock(frm), layout.dock(to)
            path = layout.route(a.pos, src)[:-1] + layout.route(src, dst) if a.pos != src else layout.route(src, dst)
            dist = layout.length(path)
            dur = dist / AGV_SPEED + 2 * LOAD_UNLOAD_S
            a.task = {"path": path, "start": t, "end": t + dur, "part": p, "frm": frm, "to": to, "dist": dist}
            a.battery = max(0.2, a.battery - dist / 20000)
            self.at(t + dur, "agv_arrive", unit=a.unit)
            self._agv_status(a)

    def _ev_agv_arrive(self, t, unit):
        a = self.agvs[unit]
        task = a.task
        a.pos = task["path"][-1]
        a.task = None
        self._agv_status(a)
        p, to = task["part"], task.get("to_override") or task["to"]
        if to in self.machines:
            self.machines[to].inbox.append(p)
            self._try_start(self.machines[to])
        self._dispatch_agvs()

    def _agv_status(self, a):
        t = self.now()
        if a.task:
            tk = a.task
            f = (t - tk["start"]) / max(1e-6, tk["end"] - tk["start"])
            travel = max(0.0, min(1.0, (t - tk["start"] - LOAD_UNLOAD_S) / max(1e-6, tk["end"] - tk["start"] - 2 * LOAD_UNLOAD_S)))
            (x, y), a.heading = layout.point_at(tk["path"], travel * tk["dist"])
            data = {"x_m": round(x, 2), "y_m": round(y, 2), "heading_deg": round(a.heading, 1),
                    "load": tk["part"].serial, "task": "{} → {}".format(tk["frm"], tk["to"]),
                    "from": tk["frm"], "to": tk["to"], "progress": round(max(0, min(1, f)), 3),
                    "battery": round(a.battery, 3)}
            corr = tk["part"].wo.corr
        else:
            data = {"x_m": a.pos[0], "y_m": a.pos[1], "heading_deg": round(a.heading, 1), "load": None,
                    "task": None, "battery": round(a.battery, 3)}
            corr = None
        self.pub(unit_topic(a.unit, "status"), "logistics.status", "sim/" + a.unit, data, corr)

    # ------------------------------------------------------------ 状态
    def _status(self, m, force=False):
        t = self.now()
        job, prog, serial = None, 0.0, None
        if m.active:
            vals = list(m.active.values())
            p, job, s, e = vals[0]
            serial = p.serial if len(vals) == 1 else "{} 件在炉".format(len(vals))
            prog = sum(max(0, min(1, (t - s) / max(1e-6, e - s))) for _, _, s, e in vals) / len(vals)
        elif m.jobs:
            job = next((j for j in m.jobs if j.started), m.jobs[0])
        rpm, feed = SPINDLE.get(m.unit, (0, 0))
        running = m.state == "run"
        waiting = sum(1 for p in m.inbox)
        data = {
            "state": m.state,
            "work_order": job.wo.name if job else None,
            "operation": job.op if job else None,
            "item": job.wo.item if job else None,
            "part_serial": serial,
            "progress": round(prog, 3),
            "qty_done": job.done if job else 0,
            "qty": job.qty if job else 0,
            "job_started": bool(job and job.started),
            "queue": waiting,
            "spindle_rpm": rpm if running else 0,
            "feed_mm_min": feed if running else 0,
            "tool_life_left": round(m.tool_life, 3),
            "reason": m.down_reason if m.state in ("down", "fault") else None,
            "locked": m.locked,
            "run_h_pm": round(m.run_h, 1),
            "down_until_s": round(m.down_until - t) if m.down_until else None,
            "down_for_s": round(t - m.down_since) if m.state in ("down", "fault") else None,
            "dispatched": [{"work_order": j.wo.name, "operation": j.op, "started": j.started,
                            "done": j.done, "qty": j.qty} for j in m.jobs],
            "shift": self.calendar.mode,
            "off_shift": self.calendar.mode == "shift" and not self.calendar.is_open(m.unit, self.factory_dt(t)),
        }
        data["factory_ts"] = self.factory_ts(t)   # 第 18 轮 E4：工厂时间（倍速运行时和真实时间不同；平台按它判断“现在是哪一班”）
        if self.staffing.enabled:                # 第 18 轮 E4：这一班的人员等级（0 没人 / 1 学徒 / 2 熟练）
            data["staff_level"] = self.staffing.level(m.unit, self.factory_dt(t).astimezone(self.calendar.tzi))
            data["no_staff"] = bool(getattr(m, "no_staff", False)) and data["staff_level"] == 0
        if self.energy.enabled and m.unit in self.energy.cur:     # 第 18 轮 E6：此刻功率
            data["power_kw"] = round(self.energy.cur[m.unit][2], 2)
            data["power_state"] = self.energy.cur[m.unit][1]
        key = (data["state"], data["work_order"], data["operation"], data["qty_done"], data["queue"],
               data["job_started"], len(data["dispatched"]), data["off_shift"], data.get("staff_level"), data.get("no_staff"))
        if not force and key == m.last_status:
            return
        m.last_status = key
        self.pub(unit_topic(m.unit, "status"), "machine.status", "sim/" + m.unit, data,
                 job.wo.corr if job else None)


    # ------------------------------------------------------------ 快照（第 17 轮 C 期 C2）
    def snapshot(self):
        """把内存里的全部状态原样导出（可 JSON 化）；from_snapshot 能原样恢复，恢复后的随机数序列也相同"""
        t = self.now()
        tok = next(self.tokens)
        self.tokens = itertools.count(tok)
        sq = next(self.seq)
        self.seq = itertools.count(sq)
        rs = self.rng.getstate()
        es = self.errors.rng.getstate()

        def part(p):
            return {"serial": p.serial, "op_index": p.op_index, "grind_wear": p.grind_wear, "result": p.result,
                    "err": {k: list(v) if isinstance(v, tuple) else v for k, v in (getattr(p, "err", None) or {}).items()}}
        wos = {}
        for name, wo in self.wos.items():
            wos[name] = {"item": wo.item, "qty": wo.qty, "ops": [list(o) for o in wo.ops], "corr": wo.corr,
                         "parts": [part(p) for p in wo.parts],
                         "jobs": {str(i): {"unit": j.unit, "started": j.started, "done": j.done, "good": j.good, "time_s": j.time_s,
                                           "first_start": j.first_start, "qty": j.qty, "outsource": getattr(j, "outsource", None)}
                                  for i, j in wo.jobs.items()}}
        machines = {}
        for u, m in self.machines.items():
            machines[u] = {"jobs": [[j.wo.name, j.op_index] for j in m.jobs], "inbox": [[p.wo.name, p.serial] for p in m.inbox],
                           "active": [[tk, p.wo.name, p.serial, j.op_index, st, en] for tk, (p, j, st, en) in m.active.items()],
                           "state": m.state, "setup_until": m.setup_until, "setup_job": list(m.setup_job) if m.setup_job else None,
                           "down_until": m.down_until, "down_reason": m.down_reason, "down_kind": m.down_kind,
                           "down_since": getattr(m, "down_since", None), "tool_life": m.tool_life, "locked": m.locked, "run_h": m.run_h,
                           "last_status": list(m.last_status) if m.last_status else None}
        agvs = {}
        for u, a in self.agvs.items():
            tk = a.task
            agvs[u] = {"pos": list(a.pos), "battery": a.battery, "heading": a.heading,
                       "task": None if not tk else {"path": [list(x) for x in tk["path"]], "start": tk["start"], "end": tk["end"],
                                                    "part": [tk["part"].wo.name, tk["part"].serial], "frm": tk["frm"], "to": tk["to"],
                                                    "dist": tk["dist"], "to_override": tk.get("to_override")}}
        return {"v": 1, "t": t, "epoch": self.epoch.isoformat(), "factory_now": self.factory_dt(t).isoformat(), "mode": self.mode,
                "auto_start": self.auto_start, "status_every_s": self.status_every_s,
                "rng": [rs[0], list(rs[1]), rs[2]], "err_rng": [es[0], list(es[1]), es[2]],
                "err_active": self.errors.active, "err_lots": self.errors.lot_state(), "tokens": tok, "rel_factor": self.rel_factor, "seq": sq, "calendar": self.calendar.to_dict(),
                "staffing": self.staffing.to_dict(), "staff_wait": self._staff_wait, "energy": self.energy.to_dict(),
                "shift_wait": self._shift_wait, "wos": wos, "machines": machines, "agvs": agvs,
                "transfers": [[p.wo.name, p.serial, f, to] for p, f, to in self.transfers],
                "queue": [[qt, qs, k, pl] for qt, qs, k, pl in sorted(self.q)]}

    @classmethod
    def from_snapshot(cls, s, publish, clock):
        """从快照恢复一个引擎（推演用的快进副本）。clock 的 now() 应等于快照的 t"""
        e = cls(publish, clock, mode=s["mode"], auto_start=s["auto_start"], status_every_s=s.get("status_every_s", 2.0))
        e.epoch = dt.datetime.fromisoformat(s["epoch"])
        e.rng.setstate((s["rng"][0], tuple(s["rng"][1]), s["rng"][2]))
        e.errors.rng.setstate((s["err_rng"][0], tuple(s["err_rng"][1]), s["err_rng"][2]))
        e.errors.active = {k: dict(v) for k, v in (s.get("err_active") or {}).items()}
        e.errors.load_lot_state(s.get("err_lots"))
        e.calendar = Calendar.from_dict(s.get("calendar"))
        e._shift_wait = {k: v for k, v in (s.get("shift_wait") or {}).items()}
        e.staffing = Staffing.from_dict(s.get("staffing"))
        e._staff_wait = {k: v for k, v in (s.get("staff_wait") or {}).items()}
        parts = {}
        for name, w in s["wos"].items():
            wo = WorkOrder.__new__(WorkOrder)
            wo.name, wo.item, wo.qty, wo.corr = name, w["item"], w["qty"], w["corr"]
            wo.ops = [tuple(o) for o in w["ops"]]
            wo.parts = []
            for x in w["parts"]:
                p = Part(x["serial"], wo)
                p.op_index, p.grind_wear, p.result = x["op_index"], x["grind_wear"], x["result"]
                if x.get("err"):
                    p.err = dict(x["err"])
                wo.parts.append(p)
                parts[(name, p.serial)] = p
            wo.jobs = {}
            for i, j in w["jobs"].items():
                job = Job(wo, int(i), j["unit"])
                job.started, job.done, job.good, job.time_s, job.first_start = j["started"], j["done"], j["good"], j["time_s"], j["first_start"]
                job.qty = j.get("qty", job.qty)
                if j.get("outsource"):
                    job.outsource = dict(j["outsource"])
                wo.jobs[int(i)] = job
            e.wos[name] = wo
        for u, x in s["machines"].items():
            m = e.machines[u]
            m.jobs = [e.wos[wn].jobs[i] for wn, i in x["jobs"]]
            m.inbox = deque(parts[(wn, sn)] for wn, sn in x["inbox"])
            m.active = {tk: (parts[(wn, sn)], e.wos[wn].jobs[i], st, en) for tk, wn, sn, i, st, en in x["active"]}
            m.state, m.setup_until = x["state"], x["setup_until"]
            m.setup_job = tuple(x["setup_job"]) if x["setup_job"] else None
            m.down_until, m.down_reason, m.down_kind, m.tool_life = x["down_until"], x["down_reason"], x["down_kind"], x["tool_life"]
            if x.get("down_since") is not None:
                m.down_since = x["down_since"]
            m.locked = x.get("locked")
            if x.get("run_h") is not None:
                m.run_h = x["run_h"]
            m.last_status = tuple(x["last_status"]) if x.get("last_status") else None
        for u, x in s["agvs"].items():
            a = e.agvs[u]
            a.pos, a.battery, a.heading = tuple(x["pos"]), x["battery"], x["heading"]
            tk = x["task"]
            a.task = None if not tk else {"path": [tuple(p) for p in tk["path"]], "start": tk["start"], "end": tk["end"],
                                          "part": parts[tuple(tk["part"])], "frm": tk["frm"], "to": tk["to"], "dist": tk["dist"]}
            if tk and tk.get("to_override"):
                a.task["to_override"] = tk["to_override"]
        e.transfers = deque((parts[(wn, sn)], f, to) for wn, sn, f, to in s["transfers"])
        e.q = [(qt, qs, k, pl) for qt, qs, k, pl in s["queue"]]
        heapq.heapify(e.q)
        e.seq = itertools.count(s["seq"])
        e.tokens = itertools.count(s["tokens"])
        e.energy = EN.Energy.from_dict(s.get("energy"))   # 最后恢复：恢复设备状态时钩子还不记电
        e._last_periodic = time.time()          # 定时状态按真实时间发，副本不必一开始就补发一遍
        return e


_MACHINE_UNITS = {"saw-01", "cnc-l01-a", "cnc-l01-b", "vmc-01", "hmc-01", "key-01", "hob-01",
                  "ht-01", "grd-01", "qc-01", "asm-01", "test-01"}
if _P:                                  # 工厂清单：看板上的设备就是仿真里的设备
    _MACHINE_UNITS = set(_P["MACHINES"])


def torque_record(serial, work_order, item):
    """跑合试验台的“工况模拟”段：带式输送机 启动—运行—停机 × 3，输出轴转矩 10 Hz、75 秒。同一件每次一样"""
    import math
    import zlib
    tr = RATED_TORQUE_NM.get(item, 350.0)
    rng = random.Random(zlib.crc32((serial + work_order).encode()))
    rate, out = 10.0, []
    for _ in range(3):
        peak = tr * rng.uniform(1.5, 1.7)                 # 电机起动转矩冲击
        mean = tr * rng.uniform(0.70, 0.80)               # 带上物料，稳定运行
        for i in range(int(25 * rate)):
            t = i / rate
            if t < 1:
                v = peak * t
            elif t < 2:
                v = mean + (peak - mean) * math.exp(-4 * (t - 1))
            elif t < 22:
                v = mean + 0.08 * tr * math.sin(2 * math.pi * 0.5 * t) + rng.gauss(0, 0.03 * tr)
            elif t < 23:
                v = mean * (23 - t)
            else:
                v = rng.gauss(0, 0.005 * tr)
            out.append(round(v, 1))
    return {"item": item, "part_serial": serial, "work_order": work_order, "rate_hz": rate, "samples_nm": out,
            "duration_s": len(out) / rate, "rated_nm": tr, "program": "工况模拟：带式输送机 启动—运行—停机 × 3"}


def _measure_spec(item, op):
    """某物料在某道工序上要测的特性（factory/data.py 的 MEASURE，来自清单第 2 版）；演示工厂没有"""
    from factory import data
    return data.MEASURE.get((item, op))


def routing_for(item):
    """从工厂数据取某物料的工艺路线 [(工序, 分钟)]。"""
    from factory import data
    rt = data.BOMS[item][0]
    return [list(x) for x in data.ROUTINGS[rt]]


def expected_minutes(item, qty):
    """整批按单件流动的理论完工时间（分钟），供测试和 AI 估算用：瓶颈工序 × 件数 + 其余工序各一件。"""
    ops = routing_for(item)
    t = [m for _, m in ops]
    bottleneck = max(m for op, m in ops if op != "调质 Quench & temper")
    return sum(t) + bottleneck * (qty - 1)

