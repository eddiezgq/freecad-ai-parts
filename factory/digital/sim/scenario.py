# -*- coding: utf-8 -*-
"""教学情景“实验 7”：让工厂从一个真实感的状态开始。

仿真引擎把前两个工作日和今天上午的生产实际“跑”一遍，消息带过去的时间戳发到总线，
历史库照常入库；跑到“现在”后引擎无缝转为实时运行。于是学生打开首页看到的是：
- 本月已交付的订单（有一单晚交）、在手订单 SAL-ORD-2026-00019（峰顶，8 台，2 个工作日后交）
  和 SAL-ORD-2026-00020（海港，12 台，缺轴承 BRG-6207 待排产）；
- 今天的输出轴工单 MFG-WO-2026-00016 正在加工，磨床 GRD-01 半小时前停机换砂轮；
- 45 钢 60 kg（够学生这一批，但加上海港订单就不够），BRG-6207 低于安全库存，40Cr 锻坯有一张采购单在途。
学生在实验里接的新订单（绿谷输送设备 10 台）就排在这些之后。

ERP 单据由情景以 source=demo/erp 发出，只在教学模式出现；看板会标“含演示数据”，
工作台的“清空演示数据”会把它们从历史库删掉。
"""
import datetime as dt
from zoneinfo import ZoneInfo

from factory import data as F
from sim.engine import OP_UNITS, routing_for, torque_record
from wqbus.topics import topic, unit_topic

CUST = {"gv": F.CUSTOMERS[0], "summit": F.CUSTOMERS[1], "harbor": F.CUSTOMERS[2]}


class ScenarioClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


def _iso(t):
    return t.astimezone(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _wd_add(d, n):
    step = 1 if n >= 0 else -1
    while n:
        d += dt.timedelta(days=step)
        if d.weekday() < 5:
            n -= step
    return d


def load(engine, publish, now=None, tz="America/New_York", fault_left_min=90):
    """engine：刚启动、空的仿真引擎；publish(topic, type, source, data, corr, ts)。
    跑完后 engine 停在“现在”的仿真时刻，返回该时刻（仿真秒），调用方据此接实时时钟。"""
    tzi = ZoneInfo(tz)
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(tzi).date()
    d1, d2 = _wd_add(today, -1), _wd_add(today, -2)

    def at_local(day, hh, mm=0):
        return dt.datetime(day.year, day.month, day.day, hh, mm, tzinfo=tzi).astimezone(dt.timezone.utc)

    start_today = now - dt.timedelta(hours=3)
    t0 = min(at_local(d2, 8), start_today) - dt.timedelta(minutes=5)
    clock = ScenarioClock()
    old_clock, old_pub = engine.clock, engine.pub

    def ts_of(sim_t):
        return _iso(t0 + dt.timedelta(seconds=sim_t))

    engine.clock = clock
    engine.epoch = t0
    engine.pub = lambda tp, ty, src, data, corr: publish(tp, ty, src, data, corr, ts_of(clock.t))
    auto = engine.auto_start
    engine.auto_start = True

    def erp(doctype, name, when, action, **fields):
        publish(topic("office", "erp", doctype.lower().replace(" ", "_")), "erp.doc", "demo/erp",
                dict({"doctype": doctype, "name": name, "action": action, "demo": True}, **fields), name, _iso(when))

    # ---- 本月已交付的订单（11 单准时，1 单晚 1 天）
    month0 = today.replace(day=1)
    past = [month0 + dt.timedelta(days=i) for i in range((today - month0).days)]
    past = [d for d in past if d.weekday() < 5]
    recent = past[-12:]
    for i, day in enumerate(recent):
        name = "SAL-ORD-2026-{:05d}".format(5 + i)
        due = day if i != 7 else day - dt.timedelta(days=1)
        erp("Sales Order", name, at_local(day, 9), "updated", status="Completed", docstatus=1,
            customer=list(CUST.values())[i % 3], delivery_date=due.isoformat(), delivered_date=day.isoformat(),
            per_delivered=100, items=[{"item_code": "WQR-105", "qty": 2 + i % 4, "delivered_qty": 2 + i % 4}])
        # 最近 3 单的减速器出厂前做过跑合试验：留下输出轴转矩记录（第 11 轮实验 8 的疲劳载荷谱）
        if i >= len(recent) - 3:
            wo = "MFG-WO-2026-{:05d}".format(i - 1)
            for k in range(2 + i % 4):
                serial = "WQR-105-{:02d}{:02d}-{:02d}".format(day.month, day.day, k + 1)
                publish(unit_topic("test-01", "torque"), "test.torque", "sim/test-01",
                        torque_record(serial, wo, "WQR-105"), wo,
                        _iso(at_local(day - dt.timedelta(days=1), 13) + dt.timedelta(minutes=40 * k)))

    # ---- 在手订单
    due19 = _wd_add(today, 2)
    erp("Sales Order", "SAL-ORD-2026-00019", at_local(d2, 9), "submitted", status="To Deliver and Bill", docstatus=1,
        customer=CUST["summit"], delivery_date=due19.isoformat(), transaction_date=d2.isoformat(), per_delivered=0,
        items=[{"item_code": "WQR-105", "qty": 8, "delivered_qty": 0}])
    erp("Sales Order", "SAL-ORD-2026-00020", at_local(d1, 10), "submitted", status="To Deliver and Bill", docstatus=1,
        customer=CUST["harbor"], delivery_date=_wd_add(today, 12).isoformat(), transaction_date=d1.isoformat(),
        per_delivered=0, items=[{"item_code": "WQR-105", "qty": 12, "delivered_qty": 0}])

    # ---- 采购在途
    erp("Purchase Order", "PUR-ORD-2026-00008", at_local(d2, 11), "submitted", status="To Receive and Bill",
        docstatus=1, supplier=F.SUPPLIERS["forgings"]["name"],
        items=[{"item_code": "RM-40CR-F225", "qty": 12, "received_qty": 0,
                "schedule_date": _wd_add(today, 2).isoformat()}])

    # ---- 工单：前两天各一张（已完工），今天一张（加工中）
    ops = routing_for("SH-301")
    wos = [("MFG-WO-2026-00014", 10, at_local(d2, 8), "SAL-ORD-2026-00016"),
           ("MFG-WO-2026-00015", 8, at_local(d1, 8), "SAL-ORD-2026-00017"),
           ("MFG-WO-2026-00016", 8, start_today, "SAL-ORD-2026-00019")]
    for name, qty, when, so in wos:
        day = when.astimezone(tzi).date()
        erp("Work Order", name, when - dt.timedelta(minutes=30), "submitted", status="Not Started", docstatus=1,
            production_item="SH-301", qty=qty, produced_qty=0, sales_order=so, bom_no="BOM-SH-301-001",
            planned_start_date=day.isoformat(), expected_delivery_date=day.isoformat())

    def dispatch(name, qty, so):
        for op, _ in ops:
            engine.command(OP_UNITS[op][0], {"command": "dispatch", "work_order": name, "operation": op,
                                             "qty": qty, "item": "SH-301", "routing": ops}, name)

    end = (now - t0).total_seconds()
    fault_at = end - 35 * 60
    plan = sorted([((w[2] - t0).total_seconds(), "wo", w) for w in wos] + [(fault_at, "fault", None)],
                  key=lambda x: x[0])
    for when, kind, w in plan:
        _advance(engine, clock, when)
        if kind == "wo":
            dispatch(w[0], w[1], w[3])
        else:
            engine.command("grd-01", {"command": "inject_fault", "minutes": 35 + fault_left_min,
                                      "reason": "换砂轮"}, None)
    _advance(engine, clock, end)

    # 前两天的工单已完工：补发 ERP 完工状态
    for name, qty, when, so in wos[:2]:
        erp("Work Order", name, now - dt.timedelta(hours=7), "updated", status="Completed", docstatus=1,
            production_item="SH-301", qty=qty, produced_qty=qty, sales_order=so, bom_no="BOM-SH-301-001",
            planned_start_date=when.astimezone(tzi).date().isoformat(),
            expected_delivery_date=when.astimezone(tzi).date().isoformat())
    erp("Work Order", wos[2][0], start_today, "updated", status="In Process", docstatus=1,
        production_item="SH-301", qty=8, produced_qty=0, sales_order="SAL-ORD-2026-00019",
        bom_no="BOM-SH-301-001", planned_start_date=today.isoformat(), expected_delivery_date=today.isoformat())

    # ---- 库存快照
    stock = F.TEACH_STOCK
    for code, qty in stock.items():
        kind = F.ITEMS[code][1]
        wh = "{} - WQ".format(F.KIND_WAREHOUSE[kind])
        ordered = 12 if code == "RM-40CR-F225" else 0
        erp("Bin", "{}@{}".format(code, wh), now - dt.timedelta(minutes=10), "snapshot", item_code=code,
            warehouse=wh, actual_qty=qty, ordered_qty=ordered, reserved_qty=0, projected_qty=qty + ordered,
            stock_uom=F.ITEMS[code][2])

    engine.clock, engine.pub = old_clock, old_pub
    engine.auto_start = auto
    return clock.t


def _advance(engine, clock, until):
    while engine.q and engine.q[0][0] <= until:
        clock.t = max(clock.t, engine.q[0][0])
        engine.run_due()
    clock.t = until
    engine.run_due()
    # 情景推进时每个状态变化都已发出；这里补一次全部状态，让保留消息是“现在”的
    for m in engine.machines.values():
        engine._status(m, force=True)
    for a in engine.agvs.values():
        engine._agv_status(a)

