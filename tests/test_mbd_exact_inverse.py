"""给定运动的开链：驱动力矩按给定轨迹的精确逆动力学算，峰值与记录频率无关，t = 0 不再是约束建立时的值。

《多体动力学》书第 11 章线索第 19 条（问渠 CAD 0.3.9 细则）：参数化臂（底座 162.5 mm，大臂 425 mm / 8.393 kg，小臂 392.25 mm /
2.275 kg，负载 7.6259 kg），j1、j2 0 → −90°、j3 0 → +90°，0.2–1.2 s 梯形速度（加减速各 25 %）。原来给定运动是软约束，
加速度跳变后过冲：sample_hz 100 → 1000 时 j1 峰值 54.68 → 60.35 N·m（精确 54.65），t = 0 处 j2 为 78.7（精确 92.5）。
"""
import pytest

import analysis

ARM = {"kind": "arm", "base_height_mm": 162.5, "links": [{"length_mm": 425.0, "mass_kg": 8.393}, {"length_mm": 392.25, "mass_kg": 2.275}],
       "payload_kg": 7.6259}
MOVE = {"kind": "move", "t0_s": 0.2, "t1_s": 1.2, "accel_ratio": 0.25}
GOAL = {"j1": -90.0, "j2": -90.0, "j3": 90.0}


def _run(hz):
    return analysis.run("mbd", {"model": ARM, "duration_s": 1.4, "sample_hz": hz,
                                "drives": [{"joint": j, **MOVE, "to": GOAL[j]} for j in GOAL]})


@pytest.mark.parametrize("hz", [100, 1000])
def test_peak_independent_of_sample_rate(hz):
    res = _run(hz)
    d = {x["joint"]: x for x in res["data"]["drives"]}
    assert d["j1"]["peak"] == pytest.approx(54.65, rel=0.01)
    assert abs(res["data"]["series"]["j2"]["drive"][0]) == pytest.approx(92.5, rel=0.01)
    assert d["j2"]["peak_at_s"] == pytest.approx(0.0, abs=1e-6)
    assert res["data"]["force_solver"]["name"] == "inverse"


def test_torque_drive_keeps_simulation():
    res = analysis.run("mbd", {"model": ARM, "duration_s": 0.2, "sample_hz": 100,
                               "drives": [{"joint": "j1", "kind": "torque", "value": 1.0}, {"joint": "j2", "kind": "hold"},
                                          {"joint": "j3", "kind": "hold"}]})
    assert "force_solver" not in res["data"]
