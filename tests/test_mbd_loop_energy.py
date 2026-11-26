"""力矩驱动的闭环机构：τ 按步长收紧，并核能量平衡。

《多体动力学》书第 1 章线索第 8 条（问渠 CAD 0.3.9 细则）：机构库曲柄滑块（缺省参数）曲柄上恒力矩 0.05 N·m 从静止起步 0.5 s，
参照解（一维方程 DOP853 rtol 1e-11，DAE 内核同）转 36.230 rad；问渠 MuJoCo 路线原来 29.620 rad（少 18 %），闭环软约束
耗掉输入功的 48 %，状态 ok、没有能量核查。
"""
import math

import pytest

import analysis
from analysis.mbd import mechanisms


def _run(T=0.5):
    return analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER"}, "duration_s": T, "sample_hz": 200,
                                "drives": [{"joint": "crank", "kind": "torque", "value": 0.05}]})


def test_torque_driven_slider_crank_end_angle():
    res = _run()
    th = math.radians(res["data"]["series"]["crank"]["q"][-1])
    assert th == pytest.approx(36.230, rel=0.01)
    eb = res["data"]["energy_balance"]
    assert eb["status"] == "pass" and eb["rel_error"] <= 0.03
    assert not any("能量平衡差" in m for m in res["messages"])


def test_energy_balance_flags_dissipation(monkeypatch):
    # 把闭环 τ、步长放回原来的 2 ms、0.2 ms：约束耗能超过 3 %，要报
    monkeypatch.setattr(mechanisms, "loop_tau", lambda mid, given, w: (mechanisms.LOOP_TAU_MAX, mechanisms.DT_MAX))
    res = _run()
    assert res["data"]["energy_balance"]["status"] == "fail"
    assert any("能量平衡差" in m for m in res["messages"])


def test_energy_balance_unknown_with_friction():
    res = analysis.run("mbd", {"model": {"kind": "mechanism", "id": "C-LNK-SLIDER"}, "duration_s": 0.2, "sample_hz": 200,
                               "friction": {"crank": {"frictionloss": 0.001}},
                               "drives": [{"joint": "crank", "kind": "torque", "value": 0.05}]})
    assert res["data"]["energy_balance"]["status"] == "unknown"
