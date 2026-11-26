"""运动学分析装配不上时报时刻、驱动和原因，已算好的结果照常返回。

《多体动力学》书第 5 章线索第 14、75 条（问渠 CAD 0.3.9 细则）。原来只报“装配不上：约束‘rocker 欧拉参数归一’残差 0.00267”，
不说时刻、驱动，指向的约束不是原因（最小二乘把残差摊到所有行），0–0.56 s 已算好的结果也不返回。
"""
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mbd_dead_point import _body, _fourbar, _rev

from analysis.mbd.dae.run import run_model


def _nongrashof():
    # 书第 5 章：a 60、b 70、c 50、d 100 mm，曲柄从 60° 起 10 rpm（60 °/s）转 1 s，约 0.56 s 到极限角 93.8°
    a, b, d = 0.06, 0.07, 0.10                       # 摇杆 c = 50 mm 由 B、O4 两点定
    th0, th3 = math.radians(60.0), -0.028025551164012688     # 装配位形（摇杆角 th4 = 1.5713 rad，模型里不用）
    A = np.array([a * math.cos(th0), a * math.sin(th0)])
    B = A + b * np.array([math.cos(th3), math.sin(th3)])
    O4 = np.array([d, 0.0])
    return {"format": "mbd-model/1", "name": "非 Grashof 四杆", "gravity_mm_s2": [0, 0, 0],
            "bodies": [_body("crank", A / 2), _body("coupler", (A + B) / 2), _body("rocker", (B + O4) / 2)],
            "joints": [_rev("R1", "ground", "crank", (0, 0)), _rev("R2", "crank", "coupler", A),
                       _rev("R3", "coupler", "rocker", B), _rev("R4", "ground", "rocker", O4)],
            "motions": [{"id": "m1", "joint": "R1", "dof": "rotation", "function": "60.0*time"}],
            "analysis": {"type": "kinematic", "end_time_s": 1.0, "output_steps": 100}}


def _completed(d):
    return next((v for v in d["verification"] if v["key"] == "completed"), None)


def test_limit_position_reported_and_partial_results_returned():
    d, msgs = run_model(_nongrashof())                    # 原来直接抛“装配不上”
    msg = next(m for m in msgs if m.startswith("运动学分析在"))
    assert "极限位置" in msg and "驱动 m1（运动副 R1）" in msg
    t_stop = float(msg.split("t ≈ ")[1].split(" s")[0])
    assert t_stop == pytest.approx((93.8 - 60.0) / 60.0, abs=0.01)
    ang = float(msg.split("运动副 R1）")[1].split("°")[0])
    assert ang == pytest.approx(33.8, abs=0.2)           # 驱动值是相对起始位形的转角：93.8° − 60°
    assert d["times_s"][-1] == pytest.approx(0.56, abs=0.011)
    assert _completed(d)["status"] == "fail"


def test_drive_on_rocker_beyond_range():
    # 第 75 条：60 rpm 匀速驱动挂到 Grashof 四杆的摇杆铰上（摇杆只能摆）
    m = _fourbar(400)
    m["motions"] = [{"id": "m1", "joint": "R4", "dof": "rotation", "function": "360.0*time"}]
    _, msgs = run_model(m)
    assert any("极限位置" in x and "驱动超出了机构的运动范围" in x and "运动副 R4" in x for x in msgs)


def test_step_too_large():
    # 第 75 条：曲柄 150000 rpm（减速比乘反）算 1 s、400 个输出点（每步六圈多）
    m = _fourbar(400)
    m["motions"] = [{"id": "m1", "joint": "R1", "dof": "rotation", "function": "900000.0*time"}]
    _, msgs = run_model(m)                                # 原来静默算完、报 399 次死点
    assert any("步长相对转速太大" in x and "加密输出点" in x for x in msgs)
    dead = next(x for x in msgs if x.startswith("经过死点"))
    assert len(dead) < 1000 and dead.endswith("……")        # 死点只列前 12 个
