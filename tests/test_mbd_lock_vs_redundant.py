"""Locked vs redundant constraints and the DOF check — DAE kernel of analysis.mbd.

Source of the finding: the multibody dynamics book (mbd-ai-textbook), chapter 4, clue 11. A double parallelogram whose
third crank pivot is offset sideways by eps is locked (it can only move through clearance), yet the kernel reported
"7 redundant constraints removed" and finished the kinematics for every eps from 1e-9 to 1 mm; the DOF check compared two
numbers that are equal by definition and always passed. WenQuest CAD 0.3.6 plan, item C3.

Reference: the exact double parallelogram (eps = 0) has one degree of freedom with 7 redundant joint equations. With an
offset the joint constraints alone have full rank; the key singular value is about 0.329 * eps[m] against a largest of 4.15
(book, ex4_2_wq.py), so eps = 1 mm is a real lock, eps = 1e-6 mm is a manufacturing-size mismatch.
No network, no LLM.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model
from analysis.mbd.dae.solve import SolveError

MM = 1000.0
INERT = {"ixx": 1e-4, "iyy": 1e-4, "izz": 1e-4}
L, D, TH0 = 0.10, 0.08, math.radians(60.0)


def _body(bid, c):
    return {"id": bid, "mass_kg": 0.2, "cm_mm": (np.asarray(c) * MM).tolist(), "inertia_kg_m2": INERT}


def _rev(jid, i, j, P):
    return {"id": jid, "type": "revolute", "body_i": i, "body_j": j, "point_mm": (np.asarray(P) * MM).tolist(), "axis": [0, 0, 1]}


def _double_parallelogram(eps_m):
    u = np.array([math.cos(TH0), math.sin(TH0), 0.0])
    n = np.array([-math.sin(TH0), math.cos(TH0), 0.0])
    piv = [np.array([k * D, 0.0, 0.0]) for k in range(3)]
    tips = [p + L * u for p in piv]
    piv[2] = piv[2] + eps_m * n
    bodies = [_body(f"c{k + 1}", (piv[k] + tips[k]) / 2) for k in range(3)] + [_body("cp", (tips[0] + tips[2]) / 2)]
    joints = []
    for k in range(3):
        joints += [_rev(f"R{k + 1}", "ground", f"c{k + 1}", piv[k]), _rev(f"R{k + 1}c", f"c{k + 1}", "cp", tips[k])]
    return {"format": "mbd-model/1", "name": "double parallelogram", "gravity_mm_s2": [0, 0, 0], "bodies": bodies, "joints": joints,
            "motions": [{"id": "m1", "joint": "R1", "dof": "rotation", "speed": 10.0}],
            "analysis": {"type": "kinematic", "end_time_s": 1.0, "output_steps": 20}}


def _dof_check(d):
    return next(v for v in d["verification"] if v["key"] == "dof")


def test_exact_parallelogram_is_redundant_and_passes():
    d, msgs = run_model(_double_parallelogram(0.0))
    assert len(d["redundant_constraints"]) == 7
    v = _dof_check(d)
    assert v["value"] == 1 and v["end_value"] == 1 and v["status"] == "pass"
    assert not any("近冗余" in m for m in msgs)


def test_offset_one_mm_is_locked():
    with pytest.raises(SolveError, match="锁死"):
        run_model(_double_parallelogram(1e-3))


def test_offset_1e6_mm_is_near_redundant():
    d, msgs = run_model(_double_parallelogram(1e-9))
    assert any("近冗余" in m for m in msgs)
    assert _dof_check(d)["status"] == "pass"


def test_plain_four_bar_unchanged():
    O2, O4 = np.array([0.0, 0, 0]), np.array([0.12, 0, 0])
    A = O2 + 0.04 * np.array([math.cos(1.0), math.sin(1.0), 0])
    # solve B: |B - A| = 0.12, |B - O4| = 0.08
    a, b = 0.12, 0.08
    dvec = O4 - A
    dist = np.linalg.norm(dvec)
    x = (dist ** 2 + a ** 2 - b ** 2) / (2 * dist)
    h = math.sqrt(a ** 2 - x ** 2)
    e = dvec / dist
    B = A + x * e + h * np.array([-e[1], e[0], 0])
    bodies = [_body("crank", (O2 + A) / 2), _body("coupler", (A + B) / 2), _body("rocker", (B + O4) / 2)]
    joints = [_rev("R1", "ground", "crank", O2), _rev("R2", "crank", "coupler", A), _rev("R3", "coupler", "rocker", B),
              _rev("R4", "rocker", "ground", O4)]
    m = {"format": "mbd-model/1", "name": "four bar", "gravity_mm_s2": [0, 0, 0], "bodies": bodies, "joints": joints,
         "motions": [{"id": "m1", "joint": "R1", "dof": "rotation", "speed": 1.0}],
         "analysis": {"type": "kinematic", "end_time_s": 1.0, "output_steps": 10}}
    d, msgs = run_model(m)
    assert _dof_check(d)["status"] == "pass" and _dof_check(d)["value"] == 1
    assert not any("近冗余" in x for x in msgs)
