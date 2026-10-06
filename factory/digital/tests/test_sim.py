# -*- coding: utf-8 -*-
import pytest

import wqbus
from sim.engine import Engine, OP_UNITS, routing_for, expected_minutes


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t


def make_engine(auto=True, mode="teach", seed=1):
    out = []

    def pub(topic, type_, source, data, corr):
        out.append((topic, wqbus.make(type_, source, data, mode=mode, corr=corr)))   # 每条都按规范校验
    clock = FakeClock()
    eng = Engine(pub, clock, mode=mode, auto_start=auto, seed=seed, status_every_s=1e9)
    return eng, clock, out


def run_to_end(eng, clock, limit_s=3 * 86400):
    while eng.q and clock.t < limit_s:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()


def dispatch_all(eng, wo="WO-2026-00017", qty=10):
    ops = routing_for("SH-301")
    for i, (op, _) in enumerate(ops):
        ok, why = eng.command(OP_UNITS[op][0], {"command": "dispatch", "work_order": wo, "operation": op,
                                                "qty": qty, "item": "SH-301", "routing": ops}, wo)
        assert ok, why
    return ops


def events(out, name):
    return [m for t, m in out if m["type"] == "machine.event" and m["data"]["event"] == name]


def test_ten_shafts_flow_through_all_seven_operations():
    eng, clock, out = make_engine()
    ops = dispatch_all(eng)
    run_to_end(eng, clock)
    done = events(out, "op_complete")
    assert [e["data"]["operation"] for e in done] == [op for op, _ in ops]
    assert all(e["data"]["qty"] == 10 for e in done)
    assert done[-1]["data"]["last_op"] is True
    ends = events(out, "cycle_end")
    assert len(ends) == 70
    meas = [m for t, m in out if m["type"] == "quality.measurement"]
    assert len(meas) == 60 and {m["data"]["characteristic"] for m in meas} == {        # 第 13 轮：每件 6 项
        "bearing_seat_d35", "gear_seat_d40", "keyway_width_12", "bearing_seat_d35_r", "runout_bearing", "keyway_sym"}
    # 每件零件的工序顺序正确
    by_part = {}
    for e in ends:
        by_part.setdefault(e["data"]["part_serial"], []).append(e["data"]["op_index"])
    assert len(by_part) == 10 and all(v == list(range(7)) for v in by_part.values())
    # 全部消息都带同一关联号
    assert all(e["corr"] == "WO-2026-00017" for e in ends)
    # 完工时间与理论值同一量级（有调整、搬运、换刀，允许多出 60%）
    total_min = clock.t / 60
    assert expected_minutes("SH-301", 10) * 0.9 < total_min < expected_minutes("SH-301", 10) * 1.6, total_min


def test_teach_mode_waits_for_operator_start():
    eng, clock, out = make_engine(auto=False)
    dispatch_all(eng)
    run_to_end(eng, clock)
    assert events(out, "cycle_start") == []
    ok, _ = eng.command("saw-01", {"command": "start", "work_order": "WO-2026-00017", "operation": "下料"})
    assert ok
    run_to_end(eng, clock)
    assert len(events(out, "cycle_end")) == 10          # 只有锯床开工，零件停在车床前
    assert eng.machines["cnc-l01-a"].inbox and len(eng.machines["cnc-l01-a"].inbox) == 10


def test_grinding_wheel_wear_drives_bearing_seat_upward_and_tool_change_resets():
    eng, clock, out = make_engine(seed=7)
    dispatch_all(eng, qty=40)
    run_to_end(eng, clock, limit_s=10 * 86400)
    vals = [m["data"]["value_mm"] for t, m in out
            if m["type"] == "quality.measurement" and m["data"]["characteristic"] == "bearing_seat_d35"]
    assert len(vals) == 40
    assert sum(vals[20:28]) / 8 > sum(vals[:8]) / 8 + 0.004      # 砂轮磨损，直径上移
    changes = [e for e in events(out, "tool_change") if e["source"] == "sim/grd-01"]
    assert changes, "磨床应当修整过砂轮"


def test_inject_fault_delays_and_recovers_only_in_teach_mode():
    eng, clock, out = make_engine()
    dispatch_all(eng)
    clock.t = 3600
    eng.run_due()
    ok, _ = eng.command("grd-01", {"command": "inject_fault", "minutes": 35, "reason": "换砂轮"})
    assert ok and eng.machines["grd-01"].state == "down"
    run_to_end(eng, clock)
    assert events(out, "recover") and len(events(out, "op_complete")) == 7
    eng2, _, _ = make_engine(mode="prod")
    ok, why = eng2.command("grd-01", {"command": "inject_fault", "minutes": 5})
    assert not ok and "生产模式" in why


@pytest.mark.parametrize("cmd,why", [
    ({"command": "dispatch", "work_order": "WO-X", "operation": "下料"}, "工艺路线"),
    ({"command": "start", "work_order": "WO-NONE"}, "没有该工序"),
])
def test_bad_commands_are_rejected_with_ack(cmd, why):
    eng, clock, out = make_engine()
    ok, reason = eng.command("saw-01", cmd)
    assert not ok and why in reason
    ack = [m for t, m in out if m["type"] == "machine.ack"][-1]
    assert ack["data"]["accepted"] is False


def test_wrong_machine_rejected():
    eng, clock, out = make_engine()
    ops = routing_for("SH-301")
    ok, reason = eng.command("grd-01", {"command": "dispatch", "work_order": "W", "operation": "下料 Sawing",
                                        "qty": 1, "routing": ops})
    assert not ok and "不能做" in reason


def test_agv_moves_parts_and_reports_position():
    eng, clock, out = make_engine()
    dispatch_all(eng, qty=2)
    run_to_end(eng, clock)
    agv = [m for t, m in out if m["type"] == "logistics.status" and m["data"]["load"]]
    assert agv and all(0 <= m["data"]["x_m"] <= 50 and 0 <= m["data"]["y_m"] <= 28 for m in agv)


def test_scenario_builds_history_and_leaves_grinder_down_now():
    import datetime as dt
    from sim import scenario
    eng, clock, _ = make_engine(auto=False)
    out = []
    now = dt.datetime(2026, 10, 6, 14, 30, tzinfo=dt.timezone.utc)       # 周二 10:30 纽约

    def pub(tp, ty, src, data, corr, ts):
        out.append((tp, wqbus.make(ty, src, data, corr=corr, ts=ts)))
    t = scenario.load(eng, pub, now=now)
    assert t > 0 and eng.machines["grd-01"].state == "down"
    ts = [m["ts"] for _, m in out]
    assert max(ts) <= "2026-10-06T14:30:00.000Z" and min(ts) < "2026-10-02"     # 从上周五开始
    wo_done = [m for _, m in out if m["type"] == "machine.event" and m["data"]["event"] == "op_complete"
               and m["data"]["last_op"]]
    assert {m["data"]["work_order"] for m in wo_done} == {"MFG-WO-2026-00014", "MFG-WO-2026-00015"}
    sos = {m["data"]["name"] for _, m in out if m["type"] == "erp.doc" and m["data"]["doctype"] == "Sales Order"}
    assert {"SAL-ORD-2026-00019", "SAL-ORD-2026-00020"} <= sos
    assert eng.auto_start is False and eng.clock is clock


def test_run_in_rig_publishes_torque_log():
    """第 11 轮：跑合试验台每台减速器出一条输出轴转矩记录（疲劳寿命的载荷谱），同一件每次一样；
    实验 7 情景里最近交付的减速器也留有记录（实验 8 一开始就有载荷谱可用）"""
    import wqbus
    from sim.engine import Engine
    from sim import scenario
    out = []
    eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, wqbus.make(ty, src, data, corr=corr))), None, seed=1)

    class P:
        serial = "WQR-105-0001"

    class W:
        name = "MFG-WO-1"
        item = "WQR-105"

    class J:
        wo = W
    eng._torque_log(P, J, "c")
    eng._torque_log(P, J, "c")
    (tp, m), (_, m2) = out
    s = m["data"]["samples_nm"]
    assert tp.endswith("/test-01/torque") and m["type"] == "test.torque" and m["data"]["rate_hz"] == 10
    assert len(s) == 750 and 1.5 * 350 <= max(s) <= 1.7 * 350 and min(s) > -30
    assert s == m2["data"]["samples_nm"]
    got = []
    from tests_helpers import make_engine
    e2, _, _ = make_engine(auto=False)
    import datetime as dt
    scenario.load(e2, lambda tp, ty, src, data, corr, ts: got.append(wqbus.make(ty, src, data, corr=corr, ts=ts)),
                  now=dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc))
    logs = [g for g in got if g["type"] == "test.torque"]
    assert len(logs) >= 6 and len({g["data"]["part_serial"] for g in logs}) == len(logs)
