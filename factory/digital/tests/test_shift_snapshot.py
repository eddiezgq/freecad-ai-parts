# -*- coding: utf-8 -*-
"""第 17 轮 C 期第 1–2 步：班次日历、快照与从快照恢复（快进副本）。"""
import datetime as dt
import json
from zoneinfo import ZoneInfo

import wqbus
from sim.calendar import Calendar
from sim.engine import Engine
from tests.test_sim import FakeClock, dispatch_all

TZ = ZoneInfo("America/New_York")


def make(epoch, cal=None, seed=1):
    out = []
    clock = FakeClock()
    eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, ty, data)), clock, mode="teach", auto_start=True, seed=seed,
                 status_every_s=1e9)
    eng.epoch = epoch
    if cal:
        eng.calendar = cal
    return eng, clock, out


def run_until(eng, clock, t):
    while eng.q and eng.q[0][0] <= t:
        clock.t = max(clock.t, eng.q[0][0])
        eng.run_due()
    clock.t = t
    eng.run_due()


def starts(out):
    return [(d["part_serial"], d["operation"], tp.split("/")[3]) for tp, ty, d in out if ty == "machine.event" and d["event"] == "cycle_start"]


# ---------------------------------------------------------------- 班次日历
def test_calendar_windows_and_overtime():
    c = Calendar("shift", tz="America/New_York")
    mon = dt.datetime(2026, 10, 19, 12, 0, tzinfo=TZ)                  # 周一中午
    assert c.is_open("grd-01", mon)
    assert not c.is_open("grd-01", mon.replace(hour=17, minute=30))
    nxt = c.next_open("grd-01", mon.replace(hour=18))
    assert nxt.astimezone(TZ) == dt.datetime(2026, 10, 20, 8, 0, tzinfo=TZ)
    fri = dt.datetime(2026, 10, 23, 18, 0, tzinfo=TZ)
    assert c.next_open("grd-01", fri).astimezone(TZ).date() == dt.date(2026, 10, 26)        # 周末不开
    c.add_overtime("2026-10-19", "grd-01", 120)
    assert c.is_open("grd-01", mon.replace(hour=18, minute=30)) and not c.is_open("saw-01", mon.replace(hour=18, minute=30))
    c.add_overtime("2026-10-19", "*", 60)
    assert c.is_open("saw-01", mon.replace(hour=17, minute=30))
    assert Calendar.from_dict(json.loads(json.dumps(c.to_dict()))).to_dict() == c.to_dict()
    try:
        c.add_overtime("2026-10-19", "*", 300)
        assert False, "加班超过 4 小时应报错"
    except ValueError:
        pass
    assert Calendar().is_open("grd-01", fri)                                                  # 连续模式永远开


def test_shift_mode_stops_new_parts_after_hours_and_resumes_next_morning():
    epoch = dt.datetime(2026, 10, 19, 14, 0, tzinfo=TZ).astimezone(dt.timezone.utc)      # 周一 14:00 开工
    eng, clock, out = make(epoch, Calendar("shift", tz="America/New_York"))
    dispatch_all(eng, wo="WO-SH-1", qty=10)
    run_until(eng, clock, 21 * 3600)                                                        # 到周二 11:00
    for tp, ty, d in out:
        if ty == "machine.event" and d["event"] == "cycle_start":
            ft = dt.datetime.fromisoformat(d["factory_ts"]).astimezone(TZ)
            assert 8 <= ft.hour < 17, ("下班时间开了新件", d["part_serial"], ft)
    # 夜里有过停工：周一 17:00 后到周二 08:00 之间没有新件
    ts = [dt.datetime.fromisoformat(d["factory_ts"]).astimezone(TZ) for tp, ty, d in out if ty == "machine.event" and d["event"] == "cycle_start"]
    assert any(t.date() == dt.date(2026, 10, 20) for t in ts)
    # 连续模式下同样时长做得更多
    eng2, clock2, out2 = make(epoch)
    dispatch_all(eng2, wo="WO-SH-1", qty=10)
    run_until(eng2, clock2, 21 * 3600)
    def last_end(o):
        return max(dt.datetime.fromisoformat(d["factory_ts"]) for tp, ty, d in o if ty == "machine.event" and d["event"] == "cycle_end")
    assert last_end(out2).astimezone(TZ).date() == dt.date(2026, 10, 19)                   # 连续：当天夜里做完
    assert last_end(out).astimezone(TZ).date() == dt.date(2026, 10, 20) and last_end(out) > last_end(out2)


def test_overtime_lets_more_parts_start_today():
    epoch = dt.datetime(2026, 10, 19, 13, 0, tzinfo=TZ).astimezone(dt.timezone.utc)
    base, c1, o1 = make(epoch, Calendar("shift", tz="America/New_York"))
    dispatch_all(base, wo="WO-OT-1", qty=10)
    run_until(base, c1, 8 * 3600)                                                           # 到周一 21:00
    cal = Calendar("shift", tz="America/New_York")
    cal.add_overtime("2026-10-19", "*", 180)
    ot, c2, o2 = make(epoch, cal)
    dispatch_all(ot, wo="WO-OT-1", qty=10)
    run_until(ot, c2, 8 * 3600)
    assert len(starts(o2)) > len(starts(o1))


def test_set_calendar_mid_run_wakes_waiting_machines():
    epoch = dt.datetime(2026, 10, 19, 16, 0, tzinfo=TZ).astimezone(dt.timezone.utc)
    eng, clock, out = make(epoch, Calendar("shift", tz="America/New_York"))
    dispatch_all(eng, wo="WO-W-1", qty=10)
    run_until(eng, clock, 1.5 * 3600)                                                       # 17:30，已下班
    n = len(starts(out))
    cal = Calendar("shift", tz="America/New_York")
    cal.add_overtime("2026-10-19", "*", 120)
    eng.set_calendar(cal)                                                                   # 当场加班到 19:00
    run_until(eng, clock, 2.5 * 3600)
    assert len(starts(out)) > n


# ---------------------------------------------------------------- 快照与恢复
def _strip(out):
    """比业务事件（加工、测量、报警、搬运到达……）；设备和小车的定时状态按真实时间发，不比"""
    return [(tp, ty, json.dumps(d, sort_keys=True, ensure_ascii=False)) for tp, ty, d in out if not ty.endswith(".status")]


def test_snapshot_restore_runs_identically():
    epoch = dt.datetime(2026, 10, 19, 9, 0, tzinfo=TZ).astimezone(dt.timezone.utc)
    for cal in (None, Calendar("shift", tz="America/New_York")):
        eng, clock, out = make(epoch, cal, seed=5)
        dispatch_all(eng, wo="WO-SN-1", qty=10)
        eng.errors.inject("dressing_interval")
        run_until(eng, clock, 3.3 * 3600)                                                   # 中途：有在做的件、在途的 AGV
        eng.command("grd-01", {"command": "inject_fault", "minutes": 40, "reason": "测试"})
        snap = json.loads(json.dumps(eng.snapshot()))                                        # 经过 JSON，和总线、数据库里一样
        out.clear()
        copy_out = []
        cclock = FakeClock()
        cclock.t = snap["t"]
        copy = Engine.from_snapshot(snap, lambda tp, ty, src, data, corr: copy_out.append((tp, ty, data)), cclock)
        run_until(eng, clock, snap["t"] + 3600 * 6)
        run_until(copy, cclock, snap["t"] + 3600 * 6)
        assert out and _strip(out) == _strip(copy_out), "恢复的副本与原车间不一致"
        assert json.dumps(eng.snapshot(), sort_keys=True) == json.dumps(copy.snapshot(), sort_keys=True)


def test_snapshot_messages_validate_on_the_bus():
    eng, clock, out = make(dt.datetime(2026, 10, 19, 13, 0, tzinfo=dt.timezone.utc))
    dispatch_all(eng, wo="WO-V-1", qty=3)
    run_until(eng, clock, 3600)
    wqbus.make("sim.snapshot", "sim", {"snapshot": eng.snapshot(), "request": "r1"})
    wqbus.make("machine.cmd", "hub", {"command": "set_calendar", "calendar": Calendar("shift").to_dict()})
    wqbus.make("machine.cmd", "hub", {"command": "snapshot", "request": "r1"})
