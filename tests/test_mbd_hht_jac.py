"""HHT 的分组差分雅可比（ADR-0098 E2）：与逐列差分一致；梁链只要几组。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from analysis.mbd.dae import hht as H
from analysis.mbd.dae import model as MD
from analysis.mbd.dae import solve as S

pytest.importorskip("scipy")
FIX = Path(__file__).parent / "fixtures" / "mbd-model" / "valid"


def beam_chain(n, seg=20.0, end=0.05, steps=50):
    """钢棒（φ10）分成 n 段刚体，相邻段用梁元件连，第一段铰在地上，重力下摆"""
    d = 10.0
    area, i2 = np.pi * d * d / 4, np.pi * d ** 4 / 64
    m = 7850 * area * seg * 1e-9
    ixx = 0.5 * m * (d / 2000) ** 2
    iyy = m * ((seg / 1000) ** 2 / 12 + (d / 2000) ** 2 / 4)
    bodies, forces = [], []
    for k in range(n):
        bodies.append({"id": f"s{k}", "mass_kg": m, "cm_mm": [seg * (k + 0.5), 0, 0],
                       "inertia_kg_m2": {"ixx": ixx, "iyy": iyy, "izz": iyy}})
        if k:
            forces.append({"id": f"b{k}", "type": "beam", "body_i": f"s{k - 1}", "point_i_mm": [seg * (k - 0.5), 0, 0],
                           "body_j": f"s{k}", "point_j_mm": [seg * (k + 0.5), 0, 0], "y_axis": [0, 1, 0],
                           "youngs_modulus_mpa": 206000, "shear_modulus_mpa": 79000, "area_mm2": area,
                           "iyy_mm4": i2, "izz_mm4": i2, "ixx_mm4": 2 * i2, "damping_ratio": 0.001})
    return {"format": "mbd-model/1", "name": "梁元件链", "gravity_mm_s2": [0, -9810, 0], "bodies": bodies, "forces": forces,
            "joints": [{"id": "pin", "type": "revolute", "body_i": "ground", "body_j": "s0", "point_mm": [0, 0, 0],
                        "axis": [0, 0, 1]}],
            "analysis": {"type": "dynamic", "end_time_s": end, "output_steps": steps, "integrator": "HHT"}}


def _state(sysm):
    q = sysm.q0()
    keep, _ = S.independent_rows(sysm, q, 0.0)
    rows = S._rows(sysm, keep)
    q = S.assemble(sysm, q, 0.0, rows)
    rng = np.random.default_rng(1)
    qd = S.initial_velocity(sysm, q, 0.0, rows) + 1e-2 * rng.standard_normal(sysm.n)   # 速度随便给，测导数
    a, lam = S.accel(sysm, q, qd, 0.0, rows)
    return q, qd, a, lam, rows


def _g(sysm, rows, a, lam):
    def g(q, qd):
        J = sysm.jac(q, 0.0, rows)
        return sysm.mass(q) @ a + J.T @ lam - sysm.Q(q, qd, 0.0)
    return g


@pytest.mark.parametrize("name", ["pendulum.json", "slider_crank_all_d1.json", "d2_force_elements.json", "d3_contacts.json",
                                  "d6_flex_pendulum.json", "universal_static_then_dynamic.json", "d7_pid_turntable.json"])
def test_grouped_equals_column_by_column(name):
    doc = json.loads((FIX / name).read_text(encoding="utf-8"))
    sysm = MD.build(doc.get("instance", doc), FIX)
    q, qd, a, lam, rows = _state(sysm)
    ctrl = sysm.ctrl if getattr(sysm, "ctrl", None) is not None and sysm.ctrl.any else None
    if ctrl is not None:
        sysm.act = ctrl.outputs(0.0, sysm.measures(q, qd), ctrl.x0)
    groups = H.color_groups(sysm, ctrl)
    assert groups is not None
    g = _g(sysm, rows, a, lam)
    gq0, gqd0 = H.grouped_fd(g, q, qd, None)
    gq1, gqd1 = H.grouped_fd(g, q, qd, groups)
    sc = max(np.abs(gq0).max(), 1.0)
    assert np.abs(gq1 - gq0).max() <= 1e-12 * sc
    assert np.abs(gqd1 - gqd0).max() <= 1e-12 * max(np.abs(gqd0).max(), 1.0)


def test_chain_needs_three_groups():
    sysm = MD.build(beam_chain(50))
    groups = H.color_groups(sysm)
    assert len(groups) == 3                                  # 链：隔两个才不相邻
    q, qd, a, lam, rows = _state(sysm)
    g = _g(sysm, rows, a, lam)
    calls = {"n": 0}

    def counted(qq, vv):
        calls["n"] += 1
        return g(qq, vv)

    gq, _ = H.grouped_fd(counted, q, qd, groups)
    assert calls["n"] == 1 + 2 * 3 * 7                       # 逐列要 1 + 2 × 350
    gq0, _ = H.grouped_fd(g, q, qd, None)
    assert np.abs(gq - gq0).max() <= 1e-12 * np.abs(gq0).max()


def test_unknown_force_falls_back():
    sysm = MD.build(beam_chain(3))
    sysm.forces.append(("mystery", {}))
    assert H.color_groups(sysm) is None
