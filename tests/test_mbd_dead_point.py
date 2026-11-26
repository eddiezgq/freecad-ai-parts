"""运动学分析过死点：缺省按速度外推越过（曲柄继续转），报经过死点的时刻和运动副。

《多体动力学》书第 5 章线索第 13 条（问渠 CAD 0.3.8 细则）。
- 曲柄摇杆（40 / 120 / 100 / 110 mm）改成摇杆驱动：从摆动中点起 φ₄ = 27.34°·sin(2πt)，正好摆到两端（曲柄与连杆共线的死点），2 s；
- 曲柄滑块（曲柄 40 mm、连杆 140 mm）改成滑块驱动：从行程中点起 x = −40·sin(2πt) mm，过上下止点，2 s。
原来牛顿初值取上一时刻的解，两例曲柄都来回摆、转 0 圈（202.1°、179.1° 范围内），无提示。
"""
import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

MM = 1000.0
INERT = {"ixx": 1e-4, "iyy": 1e-4, "izz": 1e-4}
A4, B4, C4, D4 = 0.04, 0.12, 0.10, 0.11
TH0, P4, AMP = math.radians(126.06762649189288), 1.8882492117196983, 27.34284378447514


def _body(bid, c):
    return {"id": bid, "mass_kg": 0.2, "cm_mm": [c[0] * MM, c[1] * MM, 0.0], "inertia_kg_m2": INERT}


def _rev(jid, i, j, p):
    return {"id": jid, "type": "revolute", "body_i": i, "body_j": j, "point_mm": [p[0] * MM, p[1] * MM, 0.0], "axis": [0, 0, 1]}


def _fourbar(steps, branch=None):
    A = A4 * np.array([math.cos(TH0), math.sin(TH0)])
    O4 = np.array([D4, 0.0])
    B = O4 + C4 * np.array([math.cos(P4), math.sin(P4)])
    an = {"type": "kinematic", "end_time_s": 2.0, "output_steps": steps}
    return {"format": "mbd-model/1", "name": "四杆", "gravity_mm_s2": [0, 0, 0],
            "bodies": [_body("crank", A / 2), _body("coupler", (A + B) / 2), _body("rocker", (B + O4) / 2)],
            "joints": [_rev("R1", "ground", "crank", (0, 0)), _rev("R2", "crank", "coupler", A),
                       _rev("R3", "coupler", "rocker", B), _rev("R4", "ground", "rocker", O4)],
            "motions": [{"id": "m1", "joint": "R4", "dof": "rotation", "function": f"{AMP:.12f}*sin(2*PI*time)"}], "analysis": an}


def _slider_crank():
    R, L = 0.04, 0.14
    th = math.radians(81.78678929826178)
    A = np.array([R * math.cos(th), R * math.sin(th)])
    B = np.array([R * math.cos(th) + math.sqrt(L * L - (R * math.sin(th)) ** 2), 0.0])
    return {"format": "mbd-model/1", "name": "曲柄滑块", "gravity_mm_s2": [0, 0, 0],
            "bodies": [_body("crank", A / 2), _body("rod", (A + B) / 2), _body("slider", B)],
            "joints": [_rev("R1", "ground", "crank", (0, 0)), _rev("R2", "crank", "rod", A),
                       {"id": "S3", "type": "spherical", "body_i": "rod", "body_j": "slider", "point_mm": [B[0] * MM, 0, 0]},
                       {"id": "P4", "type": "translational", "body_i": "ground", "body_j": "slider", "point_mm": [B[0] * MM, 0, 0],
                        "axis": [1, 0, 0]}],
            "motions": [{"id": "m1", "joint": "P4", "dof": "translation", "function": f"{-40.0:.12f}*sin(2*PI*time)"}],
            "analysis": {"type": "kinematic", "end_time_s": 2.0, "output_steps": 406}}


def _turns(d):
    c = np.array(d["bodies"]["crank"]["cm_mm"])[:, :2]
    th = np.unwrap(np.arctan2(c[:, 1], c[:, 0]))
    return (th[-1] - th[0]) / (2 * math.pi)


def _dead_msg(msgs):
    return next((m for m in msgs if m.startswith("经过死点")), "")


@pytest.mark.parametrize("steps", [406, 400])          # 400 步时采样点正好落在死点上
def test_rocker_driven_crank_keeps_turning(steps):
    d, msgs = run_model(_fourbar(steps))
    assert abs(_turns(d)) == pytest.approx(2.0, abs=1e-6)     # 原来 0 圈
    assert _dead_msg(msgs).startswith("经过死点 4 次")
    res = next(v for v in d["verification"] if v["key"] == "constraint_residual")
    assert res["status"] == "pass"


def test_slider_driven_crank_keeps_turning():
    d, msgs = run_model(_slider_crank())
    assert abs(_turns(d)) == pytest.approx(2.0, abs=1e-6)
    assert _dead_msg(msgs).startswith("经过死点 4 次")


def test_crank_driven_has_no_dead_point():
    m = _fourbar(360)
    m["motions"] = [{"id": "m1", "joint": "R1", "dof": "rotation", "speed": 60.0}]
    _, msgs = run_model(m)
    assert not _dead_msg(msgs)
