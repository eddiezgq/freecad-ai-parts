"""时间函数的过渡点是必经时刻：短脉冲不会被大步长跨过。

《多体动力学》书第 18 章线索第 24 条（问渠 CAD 0.3.8 细则）。单摆（1 kg、1 m）+ 水平力
STEP5(time,t0,0,t0+0.001,100) − STEP5(time,t0+0.002,0,t0+0.003,100)（3 ms、100 N、冲量 0.2 N·s），2 s：
静止 / 30° 起步 × DOP853 / HHT × 输出 10、40、400 点 × t0 = 0.53、1.27 s，原来 24 例中 17 例完全漏掉（终了摆角与没有冲击相同），无提示。
参考值是书里按必经时刻分段、rtol 1e-12 积分的结果。
"""
import math

import numpy as np
import pytest

from analysis.mbd.dae.expr import compile_expr
from analysis.mbd.dae.run import run_model

REF = {("rest", 0.53): -0.06345068013509447, ("rest", 1.27): 0.0484205638708984,
       ("swing", 0.53): 0.45578572205337975, ("swing", 1.27): 0.5671320760554822}


def _model(th0, t0p, integ, steps):
    x, y = 1000 * math.sin(th0), -1000 * math.cos(th0)
    expr = f"STEP5(time,{t0p},0,{t0p + 0.001:.3f},100)-STEP5(time,{t0p + 0.002:.3f},0,{t0p + 0.003:.3f},100)"
    an = {"type": "dynamic", "end_time_s": 2.0, "output_steps": steps}
    if integ == "HHT":
        an["integrator"] = "HHT"
    return {"format": "mbd-model/1", "name": "单摆", "gravity_mm_s2": [0, -9810, 0],
            "bodies": [{"id": "bob", "mass_kg": 1.0, "cm_mm": [x, y, 0], "inertia_kg_m2": {"ixx": 1e-6, "iyy": 1e-6, "izz": 1e-6}}],
            "joints": [{"id": "O", "type": "revolute", "body_i": "ground", "body_j": "bob", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "forces": [{"id": "P", "type": "force", "body": "bob", "point_mm": [x, y, 0], "frame": "ground", "fx_n": expr}],
            "analysis": an}


def test_breaks_parsed():
    e = compile_expr("STEP5(time,0.53,0,0.531,100)-STEP5(time,0.532,0,0.533,100)")
    assert e.time_breaks() == [(0.53, 0.531), (0.532, 0.533)]
    assert compile_expr("STEP(sin(time),0,0,1,1)").time_breaks() == []      # 自变量不是 time：不当必经时刻


@pytest.mark.parametrize("integ", ["DOP853", "HHT"])
@pytest.mark.parametrize("steps", [10, 40, 400])
@pytest.mark.parametrize("start,t0p", [("rest", 0.53), ("rest", 1.27), ("swing", 0.53), ("swing", 1.27)])
def test_pulse_is_caught(start, t0p, integ, steps):
    d, msgs = run_model(_model(0.0 if start == "rest" else math.radians(30), t0p, integ, steps))
    c = np.asarray(d["bodies"]["bob"]["cm_mm"], float)
    th = math.atan2(c[-1, 0], -c[-1, 1])
    tol = 1e-6 if integ == "DOP853" else 2e-4          # HHT 缺省容差 1e-6、二阶精度
    assert th == pytest.approx(REF[(start, t0p)], abs=tol)
    assert any("必经时刻 4 个" in m for m in msgs)


@pytest.mark.parametrize("steps", [10, 400])
def test_cost_at_most_double(steps):
    # 书里验证题：计算量不超过没有冲击时的两倍（实测约 1.2–1.4 倍）
    m = _model(math.radians(30), 0.53, "DOP853", steps)
    d, _ = run_model(m)
    m["forces"][0]["fx_n"] = "0*time"
    d0, _ = run_model(m)
    assert d["solver"]["rhs"] <= 2 * d0["solver"]["rhs"]
