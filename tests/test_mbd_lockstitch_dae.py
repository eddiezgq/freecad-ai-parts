"""高速闭环机构的驱动力矩改由 DAE 内核算；MuJoCo 路线报跟踪误差和恒速一转平均力矩。

《多体动力学》书第 42 章线索第 71 条（问渠 CAD 0.3.9 细则）：直驱平缝机针杆机构（C-LNK-SLIDER，曲柄 17.5 mm、连杆 60 mm、
宽 8 mm、厚 5 mm），主轴 5000 rpm，0.06 s、5000 Hz。原来峰值 3.940 N·m、恒速一转平均功率 367 W；精确值（DAE 与书一致）
峰值 2.650、均方根 1.584、盈亏功 2.201 J、一转平均力矩 0。一转 12 ms 只有给定运动约束时间常数（1 ms）的 12 倍。
"""
import math

import pytest

import analysis
from analysis.mbd import mechanisms

P = {"crank_m": 0.0175, "rod_m": 0.06, "link_width_m": 0.008, "link_thickness_m": 0.005}


def _run(rpm=5000):
    return analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER", "params": P}, "duration_s": 0.06,
                                "sample_hz": 5000, "drives": [{"joint": "crank", "kind": "speed", "value": rpm}]})


def test_lockstitch_5000rpm_exact():
    res = _run()
    assert res["status"] == "ok"
    d = res["data"]["drives"][0]
    assert d["peak"] == pytest.approx(2.650, rel=0.01)
    assert d["speed_max"] == pytest.approx(5000, rel=1e-9)
    sw = analysis.mbd.energy_swing(res, "crank")
    assert abs(sw["mean_torque_nm"]) < 0.01 * 2.650
    assert sw["delta_e_j"] == pytest.approx(2.201, rel=0.01)
    assert res["data"]["force_solver"]["name"] == "DAE"
    assert any("DAE 内核" in x for x in res["limitations"])


def test_mujoco_route_reports_tracking_and_cycle_mean(monkeypatch):
    # 不改道，并把 τ、步长固定回 0.3.8 实际用的值（2 ms、0.2 ms），看 MuJoCo 路线自己的核对能不能把偏差报出来
    monkeypatch.setattr(mechanisms, "DAE_RATIO", 0.0)
    monkeypatch.setattr(mechanisms, "loop_tau", lambda mid, given, w: (mechanisms.LOOP_TAU_MAX, mechanisms.DT_MAX))
    res = _run()
    assert math.degrees(res["data"]["tracking_error"]) > 1.0
    assert any("跟踪误差" in x for x in res["messages"])
    assert any("一整转的平均驱动力矩" in x for x in res["messages"])


def test_route_skipped_with_reactions_says_so():
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER", "params": P}, "duration_s": 0.06,
                               "sample_hz": 5000, "reactions": ["rod"], "drives": [{"joint": "crank", "kind": "speed", "value": 5000}]})
    assert "force_solver" not in res["data"]
    assert any("没有改用 DAE 内核" in x for x in res["messages"])
