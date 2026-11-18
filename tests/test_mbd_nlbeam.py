"""大变形梁（ADR-0101 F1 验收）：对解析解和经典标准题。

钢圆杆 φ20 × 1000 mm（EI = 1617.9 N·m²），根部固定：
- 小挠度：端部 1 N → PL³/3EI + PL/κGA，误差 < 1%
- 端部力矩 M = πEI/L：卷成半圆，端点 (0, 2L/π)，误差 < 1%（分步加载）
- 弹性线 PL²/EI = 1（端部恒向力）：w/L = 0.30172、u/L = 0.05643（Mattiasson 1981），误差 < 1%
- 整体刚体转动、平移：没有内力
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis.mbd.dae.run import run_model

pytest.importorskip("scipy")
L, D = 1000.0, 20.0
E, G = 206000.0, 79000.0
A, I = math.pi * D ** 2 / 4, math.pi * D ** 4 / 64
EI = E * 1e6 * I * 1e-12


def cantilever(loads, *, elements=20, steps=1, **beam):
    return {"format": "mbd-model/1", "name": "大变形悬臂", "gravity_mm_s2": [0, 0, 0],
            "bodies": [{"id": "rod", "flex": {"type": "nonlinear_beam", "from_mm": [0, 0, 0], "to_mm": [L, 0, 0], "y_axis": [0, 1, 0],
                                              "youngs_modulus_mpa": E, "shear_modulus_mpa": G, "density_kg_m3": 7850,
                                              "area_mm2": A, "iyy_mm4": I, "izz_mm4": I, "ixx_mm4": 2 * I, "elements": elements,
                                              "fiber_y_mm": D / 2, "fiber_z_mm": D / 2, **beam}}],
            "joints": [{"id": "root", "type": "fixed", "body_i": "ground", "body_j": "rod", "point_mm": [0, 0, 0]}],
            "forces": loads, "analysis": {"type": "static", "load_steps": steps}}


def tip(data, k=-1):
    return np.array(data["flex"]["rod"]["nodes_mm"][k][-1])


def test_small_deflection_matches_beam_theory():
    P = 1.0
    data, _ = run_model(cantilever([{"id": "p", "type": "force", "body": "rod", "point_mm": [L, 0, 0], "fy_n": -P}]))
    ref = (P * (L * 1e-3) ** 3 / (3 * EI) + P * L * 1e-3 / (5 / 6 * G * 1e6 * A * 1e-6)) * 1e3
    assert -tip(data)[1] == pytest.approx(ref, rel=1e-2)
    fl = data["flex"]["rod"]
    assert fl["moment_z_n_m"][-1][0] == pytest.approx(-P * L * 1e-3 * (1 - 0.5 / 20), rel=1e-6) or \
        abs(fl["moment_z_n_m"][-1][0]) == pytest.approx(P * L * 1e-3 * (1 - 0.5 / 20), rel=1e-3)
    sig = P * L * 1e-3 * (1 - 0.5 / 20) * D / 2 * 1e-3 / (I * 1e-12) / 1e6
    assert fl["max_stress_mpa"][-1] == pytest.approx(sig, rel=1e-3)


def test_end_moment_rolls_into_half_circle():
    M = math.pi * EI / (L * 1e-3)
    data, _ = run_model(cantilever([{"id": "m", "type": "torque", "body": "rod__n40", "tz_n_m": M}],
                                      elements=40, steps=10))
    x, y, _ = tip(data)
    assert abs(x) < 1e-2 * L and y == pytest.approx(2 * L / math.pi, rel=1e-2)
    mz = np.array(data["flex"]["rod"]["moment_z_n_m"][-1])
    assert np.allclose(np.abs(mz), M, rtol=1e-6)                       # 纯弯：每个单元弯矩都是 M


def test_elastica_matches_mattiasson():
    P = EI / (L * 1e-3) ** 2                                             # PL²/EI = 1
    data, _ = run_model(cantilever([{"id": "p", "type": "force", "body": "rod", "point_mm": [L, 0, 0], "fy_n": -P}],
                                   elements=40, steps=5))
    x, y, _ = tip(data)
    assert -y / L == pytest.approx(0.30172, rel=1e-2)
    assert (L - x) / L == pytest.approx(0.05643, rel=1e-2)


def test_rigid_motion_has_no_internal_force():
    from analysis.mbd.dae import model as MD
    from analysis.mbd.dae.nlbeam import element
    from analysis.mbd.dae.system import E_of

    m = cantilever([])
    m["joints"] = []
    sysm = MD.build(m)
    q = sysm.q0()
    ax = np.array([0.3, -0.5, 0.8]) / np.linalg.norm([0.3, -0.5, 0.8])
    ang = 1.3
    p = np.r_[math.cos(ang / 2), math.sin(ang / 2) * ax]
    R = np.eye(3) + math.sin(ang) * np.cross(np.eye(3), ax) + (1 - math.cos(ang)) * np.outer(ax, ax) - (1 - math.cos(ang)) * np.eye(3)
    qd = np.zeros(sysm.n)
    w = np.array([1.0, 2.0, -3.0])
    for k in range(sysm.nb):
        r0 = q[7 * k:7 * k + 3].copy()
        q[7 * k:7 * k + 3] = R @ r0 + [0.1, 0.2, 0.3]
        q[7 * k + 3:7 * k + 7] = p
    for k in range(sysm.nb):
        qd[7 * k:7 * k + 3] = np.cross(w, q[7 * k:7 * k + 3])
        qd[7 * k + 3:7 * k + 7] = 0.5 * E_of(p).T @ w
    for kind, f in sysm.forces:
        if kind == "nlbeam":
            f = {**f, "c": 1e-3}
            n, mm, *_ = element(sysm, q, qd, f)
            assert np.abs(n).max() < 1e-6 and np.abs(mm).max() < 1e-6


def test_joint_off_node_is_reported():
    from analysis.mbd.dae import model as MD
    from analysis.mbd.dae.model import ModelError

    m = cantilever([{"id": "p", "type": "force", "body": "rod", "point_mm": [L / 2 + 10, 0, 0], "fy_n": -1}])
    with pytest.raises(ModelError, match="节点"):
        MD.build(m)
