"""Joint reaction reported on the right body regardless of the order (body_i, body_j) — DAE kernel.

Source of the finding: the multibody dynamics book (mbd-ai-textbook), chapter 8, clue 17: with the revolute joint written as
(body_i = pendulum, body_j = ground) the report said "on = pendulum" but gave the force acting on the ground (sign flipped).
WenQuest CAD 0.3.6 plan, item C1.

Reference: point-mass pendulum, m = 1 kg, L = 0.5 m, released from horizontal; rod tension T = 3 m g sin(alpha)
(alpha below horizontal), pulling the mass toward the pivot. No network, no LLM.
"""

from __future__ import annotations

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

G = 9.81


def _pendulum(bi, bj):
    m = {"format": "mbd-model/1", "name": "point-mass pendulum", "gravity_mm_s2": [0, -9810, 0],
         "bodies": [{"id": "b", "mass_kg": 1.0, "cm_mm": [500, 0, 0], "inertia_kg_m2": {"ixx": 1e-6, "iyy": 1e-6, "izz": 1e-6}}],
         "joints": [{"id": "R1", "type": "revolute", "body_i": bi, "body_j": bj, "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
         "analysis": {"type": "dynamic", "end_time_s": 0.5, "output_steps": 100}}
    d, _ = run_model(m)
    jr = d["joints"]["R1"]
    F = np.array(jr["force_n"])[:, :2]
    c = np.array(d["bodies"]["b"]["cm_mm"])[:, :2] / 1000
    return jr["on"], F, c


@pytest.mark.parametrize("bi,bj", [("ground", "b"), ("b", "ground")])
def test_force_on_pendulum_points_to_pivot(bi, bj):
    on, F, c = _pendulum(bi, bj)
    assert on == "b"
    toward = np.einsum("ij,ij->i", F, -c) / np.linalg.norm(c, axis=1)     # component toward the pivot
    alpha = np.arctan2(-c[:, 1], c[:, 0])
    tension = 3 * G * np.abs(np.sin(alpha))
    assert np.all(toward[5:] > 0)
    assert np.max(np.abs(np.linalg.norm(F, axis=1) - tension)) < 0.05


def test_both_orders_report_the_same_force():
    _, Fa, _ = _pendulum("ground", "b")
    _, Fb, _ = _pendulum("b", "ground")
    assert np.max(np.abs(Fa - Fb)) < 1e-6 * (1 + np.max(np.abs(Fa)))
