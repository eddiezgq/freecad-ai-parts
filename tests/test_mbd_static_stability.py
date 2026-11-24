"""Static equilibrium reports its stability — DAE kernel of analysis.mbd.

Source of the finding: the multibody dynamics book (mbd-ai-textbook), chapter 21, clue 21: a static analysis of an inverted
rod (1 kg, 500 mm) started 5 deg off vertical converged to the upright position, an unstable equilibrium, and every check
passed. WenQuest CAD 0.3.6 plan, item C4.

Reference: a rod of mass m and length l pivoted at its lower end has, upright, the real eigenvalue
lambda = sqrt(m g (l/2) / J) with J = m l^2 / 3 (here 5.42 1/s); hanging down it is a stable pendulum with
omega = sqrt(m g (l/2) / J). No network, no LLM.
"""

from __future__ import annotations

import math

import pytest

from analysis.mbd.dae.run import run_model

M, LEN, G = 1.0, 0.5, 9.81
J_END = M * LEN ** 2 / 3
J_CM = M * LEN ** 2 / 12


def _rod(angle_deg, typ="static"):
    a = math.radians(angle_deg)                 # measured from the upward vertical
    c = [-(LEN / 2) * math.sin(a) * 1000, (LEN / 2) * math.cos(a) * 1000, 0.0]
    return {"format": "mbd-model/1", "name": "rod", "gravity_mm_s2": [0, -9810, 0],
            "bodies": [{"id": "rod", "mass_kg": M, "cm_mm": c, "inertia_kg_m2": {"ixx": J_CM, "iyy": J_CM, "izz": J_CM}}],
            "joints": [{"id": "R", "type": "revolute", "body_i": "ground", "body_j": "rod", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
            "analysis": {"type": typ, "end_time_s": 0.2, "output_steps": 10}}


def _stab(d):
    return next(v for v in d["verification"] if v["key"] == "stability")


def test_upright_rod_is_reported_unstable():
    d, msgs = run_model(_rod(5.0))
    cm = d["bodies"]["rod"]["cm_mm"][-1]
    if cm[1] < 0:
        pytest.skip("static solve went to the hanging position from this start; nothing to check here")
    s = _stab(d)
    assert s["status"] == "fail" and s["value"] == 1
    assert abs(s["max_real"] - math.sqrt(M * G * LEN / 2 / J_END)) < 0.05
    assert any("静平衡不稳定" in m for m in msgs)


def test_hanging_rod_is_stable():
    d, msgs = run_model(_rod(175.0))
    assert d["bodies"]["rod"]["cm_mm"][-1][1] < 0
    assert _stab(d)["status"] == "pass"
    assert not any("不稳定" in m for m in msgs)


def test_static_then_dynamic_warns_from_unstable_equilibrium():
    d, msgs = run_model(_rod(0.0, "static_then_dynamic"))
    assert _stab(d)["status"] == "fail"
    assert any("不稳定平衡" in m for m in msgs)


def test_linear_marks_real_eigenvalues_not_oscillatory():
    d, _ = run_model(_rod(0.0, "linear"))
    modes = d["linear"]["modes"]
    assert any(m["oscillatory"] is False and m["eigenvalue"][0] > 0 for m in modes)
