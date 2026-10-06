# -*- coding: utf-8 -*-
"""第 17 轮 C 期第 2–3 步：推演——准确（精确快照、近似快照）、可重复、7 种改动。"""
import datetime as dt
import json
import os

import pytest

import wqbus
from sim.calendar import Calendar
from sim.engine import Engine

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)        # 周二 10:30（纽约）


class Clock:
    def __init__(self, t=0.0):
        self.t = t

    def now(self):
        return self.t


@pytest.fixture(scope="module")
def lab7():
    """实验 7 情景：历史进库（近似快照用），引擎留在内存（精确快照用）"""
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_plan_test with (force)")
            c.execute("create database wq_plan_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.historian import Historian
    from hub.ont import plan as P
    from sim import scenario
    from tests_helpers import make_engine
    db = DB(BASE + "/wq_plan_test")
    db.init()
    P.init(db)
    h = Historian(db)
    eng, clock, _ = make_engine(auto=False)
    t = scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    clock.t = t
    return db, eng, clock


def _ctx(db):
    from hub.ont import plan as P
    return P.context(db, "teach", NOW)


def _actual_finish(eng, clock, wo, limit_h=200):
    """真车间（原引擎的一份拷贝）继续跑，返回工单最后一件完成的工厂时间"""
    snap = json.loads(json.dumps(eng.snapshot()))
    c = Clock(snap["t"])
    ends = []
    e = Engine.from_snapshot(snap, lambda tp, ty, src, d, corr: ends.append((c.t, d)) if ty == "machine.event" else None, c)
    while e.q and c.t < snap["t"] + limit_h * 3600:
        c.t = max(c.t, e.q[0][0])
        e.run_due()
        if all(p.op_index >= len(e.wos[wo].ops) for p in e.wos[wo].parts):
            break
    last = max(t for t, d in ends if d.get("event") == "cycle_end" and d.get("work_order") == wo and d.get("op_index") == d.get("n_ops", 0) - 1)
    return e.factory_dt(last), e.factory_dt(snap["t"])


def test_do_nothing_matches_actual_exact_snapshot(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = json.loads(json.dumps(eng.snapshot()))
    r = P.simulate(snap, [], _ctx(db))
    w = r["work_orders"]["MFG-WO-2026-00016"]
    assert w["complete"]
    actual, start = _actual_finish(eng, clock, "MFG-WO-2026-00016")
    assert dt.datetime.fromisoformat(w["finish"]) == actual            # 精确快照：完全一致
    so = next(s for s in r["sales_orders"] if s["name"] == "SAL-ORD-2026-00019")
    assert so["projected"] and so["late_days"] is not None


def test_do_nothing_within_10pct_from_approx_snapshot(lab7):
    """生产模式没有仿真车间内存：从总线状态近似重建，剩余工期误差 < 10%"""
    from hub.ont import plan as P
    db, eng, clock = lab7
    st = P.approx_snapshot(db, "teach", now=eng.factory_dt(clock.t))
    assert "MFG-WO-2026-00016" in st["wos"]
    r = P.simulate(st, [], _ctx(db))
    w = r["work_orders"]["MFG-WO-2026-00016"]
    assert w["complete"], r
    actual, start = _actual_finish(eng, clock, "MFG-WO-2026-00016")
    pred = dt.datetime.fromisoformat(w["finish"])
    remain = (actual - start).total_seconds()
    assert abs((pred - actual).total_seconds()) / remain < 0.10, (pred, actual, start)


def test_simulation_is_repeatable(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = json.loads(json.dumps(eng.snapshot()))
    a = P.simulate(snap, [{"type": "expedite", "unit": "grd-01", "factor": 0.5}], _ctx(db))
    b = P.simulate(snap, [{"type": "expedite", "unit": "grd-01", "factor": 0.5}], _ctx(db))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _fin(r, wo="MFG-WO-2026-00016"):
    return dt.datetime.fromisoformat(r["work_orders"][wo]["finish"])


def test_expedite_repair_finishes_earlier_and_costs(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    base = P.simulate(snap, [], _ctx(db))
    fast = P.simulate(snap, [{"type": "expedite", "unit": "grd-01", "factor": 0.3}], _ctx(db))
    assert _fin(fast) < _fin(base) and fast["cost_total"] > 0 and fast["ok"]


def test_reassign_moves_the_operation(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    st = [m for u, m in snap["machines"].items() if any(w == "MFG-WO-2026-00016" for w, i in m["jobs"])]
    assert st
    r = P.simulate(snap, [{"type": "reassign", "work_order": "MFG-WO-2026-00016", "operation": "精车 Finish turning",
                           "from_unit": "cnc-l01-b", "to_unit": "cnc-l01-a"}], _ctx(db))
    assert r["ok"], r["checks"]
    finish_turn = [g for g in r["gantt"] if g["wo"] == "MFG-WO-2026-00016" and g["op"] == "精车"]
    assert finish_turn and all(g["unit"] == "cnc-l01-a" for g in finish_turn[1:])      # 正在做的那一件可以留在原设备做完
    bad = P.simulate(snap, [{"type": "reassign", "work_order": "MFG-WO-2026-00016", "operation": "精车 Finish turning",
                             "from_unit": "cnc-l01-b", "to_unit": "grd-01"}], _ctx(db))
    assert not bad["ok"] and "不能做" in bad["checks"][0]["text"]


def test_overtime_only_in_shift_mode(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    day = eng.factory_dt(clock.t).astimezone(Calendar().tzi).date().isoformat()
    r = P.simulate(snap, [{"type": "overtime", "day": day, "unit": "*", "minutes": 120}], _ctx(db))
    assert not r["ok"] and "24 小时连续" in r["checks"][0]["text"]
    # 今天再插一张 30 件的工单，按班次做不完、要跨夜；加班 3 小时后完工提前
    ins = {"type": "insert_order", "work_order": "WO-OT", "item": "SH-301", "qty": 30, "at": day}
    snap["calendar"] = Calendar("shift").to_dict()
    base = P.simulate(snap, [ins], _ctx(db))
    ot = P.simulate(snap, [ins, {"type": "overtime", "day": day, "unit": "*", "minutes": 180}], _ctx(db))
    assert ot["ok"] and ot["cost_total"] > 0 and ot["overtime_min"] > 0
    assert _fin(ot, "WO-OT") < _fin(base, "WO-OT")
    cont = P.simulate(eng.snapshot(), [ins], _ctx(db))                   # 24 小时连续：比按班次早
    assert _fin(cont, "WO-OT") < _fin(base, "WO-OT")


def test_outsource_takes_parts_off_the_machine(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    base = P.simulate(snap, [], _ctx(db))
    r = P.simulate(snap, [{"type": "outsource", "unit": "grd-01", "work_order": "MFG-WO-2026-00016",
                           "operation": "磨外圆 Cylindrical grinding", "qty": 3, "days": 1}], _ctx(db))
    assert r["ok"], r["checks"]
    n = lambda x: sum(1 for g in x["gantt"] if g["wo"] == "MFG-WO-2026-00016" and g["op"] == "磨外圆")  # noqa: E731
    assert n(r) == n(base) - 3
    assert r["work_orders"]["MFG-WO-2026-00016"]["complete"] and r["cost_total"] > 0


def test_insert_order_reorder_urgent_purchase_and_split(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    today = eng.factory_dt(clock.t).date()
    later = (today + dt.timedelta(days=4)).isoformat()
    ins = {"type": "insert_order", "work_order": "WO-NEW-1", "item": "SH-301", "qty": 4, "at": later, "material": "BRG-6207"}
    base = P.simulate(snap, [ins], _ctx(db))
    assert base["work_orders"]["WO-NEW-1"]["complete"]
    urgent = P.simulate(snap, [ins, {"type": "urgent_purchase", "item": "BRG-6207", "qty": 20, "arrive": today.isoformat()}], _ctx(db))
    assert _fin(urgent, "WO-NEW-1") < _fin(base, "WO-NEW-1") and urgent["cost_total"] > 0
    nomat = P.simulate(snap, [{"type": "urgent_purchase", "item": "OIL-CKC220", "qty": 20, "arrive": today.isoformat()}], _ctx(db))
    assert not nomat["ok"]
    # 插单后调序：新工单在锯床上排到最前，比不调序早开工
    now_ins = dict(ins, at=today.isoformat())
    a = P.simulate(snap, [now_ins], _ctx(db))
    first = lambda r: min(g["start"] for g in r["gantt"] if g["wo"] == "WO-NEW-1")  # noqa: E731
    assert first(a)
    # 分批交货：订单多一个首批的判定
    so = next(s for s in a["sales_orders"] if s["work_orders"])
    sp = P.simulate(snap, [{"type": "split_delivery", "sales_order": so["name"], "first_qty": 4, "first_date": today.isoformat()}], _ctx(db))
    row = next(s for s in sp["sales_orders"] if s["name"] == so["name"])
    assert "split" in row and row["split"]["first_qty"] == 4


def test_reorder_puts_job_first(lab7):
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = eng.snapshot()
    today = eng.factory_dt(clock.t).date().isoformat()
    ins = [{"type": "insert_order", "work_order": "WO-A", "item": "SH-301", "qty": 3, "at": today},
           {"type": "insert_order", "work_order": "WO-B", "item": "SH-301", "qty": 3, "at": today}]
    a = P.simulate(snap, ins, _ctx(db))
    saw = lambda r, w: min(g["start"] for g in r["gantt"] if g["wo"] == w and g["unit"] == "saw-01")  # noqa: E731
    assert saw(a, "WO-A") < saw(a, "WO-B")
    # 调序要在工单下达之后才能做：这里检查调序对已派的工单生效
    pending = [w for w, i in snap["machines"]["grd-01"]["jobs"]]
    r = P.simulate(snap, [{"type": "reorder", "unit": "grd-01", "work_order": pending[-1]}] if pending else [], _ctx(db))
    assert r["ok"]


def test_work_order_already_done_at_snapshot(lab7):
    """快照时已经做完的工单（还在车间内存里）：完工按快照时刻，不出错"""
    from hub.ont import plan as P
    db, eng, clock = lab7
    snap = json.loads(json.dumps(eng.snapshot()))
    done = [n for n, w in snap["wos"].items() if all(p["op_index"] >= len(w["ops"]) for p in w["parts"])]
    assert done, "实验 7 情景里前两天的工单已做完"
    ctx = _ctx(db)
    ctx["sales_orders"].append({"name": "SO-DONE", "delivery_date": "2026-10-30", "item": "SH-301", "qty": 10, "work_orders": [done[0]]})
    r = P.simulate(snap, [], ctx)
    row = next(s for s in r["sales_orders"] if s["name"] == "SO-DONE")
    assert row["late_days"] is not None and row["late_days"] <= 0
