"""初速度：用户给了的分量原样保留，没给的由运动副补全；不相容时按动能加权投影并报出来。

《多体动力学》书第 13 章线索第 22 条（问渠 CAD 0.3.8 细则）。刚体摆 1 kg、绕质心 0.0208 kg·m²，铰点在原点、质心在 (r, 0)，
不计重力。原来只给质心速度 (0, 1) m/s 时，没给的 ω0 当成 0 去凑（不加权最小二乘）：r = 0.1 m 时开始的质心速度只剩
0.038 m/s，动能只剩 0.15 %，无提示。
"""
import math

import pytest

from analysis.mbd.dae.run import run_model

M, I = 1.0, 0.0208


def _run(r, **body):
    m = {"format": "mbd-model/1", "name": "刚体摆（初速度）", "gravity_mm_s2": [0, 0, 0],
         "bodies": [{"id": "b", "mass_kg": M, "cm_mm": [r * 1000, 0, 0], "inertia_kg_m2": {"ixx": I, "iyy": I, "izz": I}, **body}],
         "joints": [{"id": "R", "type": "revolute", "body_i": "ground", "body_j": "b", "point_mm": [0, 0, 0], "axis": [0, 0, 1]}],
         "analysis": {"type": "dynamic", "end_time_s": 0.01, "output_steps": 2}}
    d, msgs = run_model(m)
    w = math.radians(d["bodies"]["b"]["w_deg_s"][0][2])
    v = d["bodies"]["b"]["v_mm_s"][0]
    return w, v[0] / 1000, v[1] / 1000, msgs


@pytest.mark.parametrize("r", [0.1, 0.5, 2.0])
def test_given_cm_velocity_kept(r):
    w, vx, vy, msgs = _run(r, v0_mm_s=[0, 1000, 0])
    assert vy == pytest.approx(1.0, abs=1e-9)          # 原来 0.038 / 0.50 / 0.94 m/s
    assert vx == pytest.approx(0.0, abs=1e-9)
    assert w == pytest.approx(1.0 / r, rel=1e-9)
    assert not any("初速度" in m for m in msgs)


def test_inconsistent_velocity_projected_and_reported():
    # 多给一个沿摆杆向外的 1 m/s：与铰不相容。只在给了的分量上按动能加权 → 去掉径向分量，切向 1 m/s 保留
    w, vx, vy, msgs = _run(0.1, v0_mm_s=[1000, 1000, 0])
    assert vy == pytest.approx(1.0, abs=1e-6)
    assert vx == pytest.approx(0.0, abs=1e-9)
    assert w == pytest.approx(10.0, rel=1e-6)
    assert any("不相容" in m and "“b”" in m for m in msgs)


def test_consistent_velocity_and_rate_unchanged():
    w, _, vy, msgs = _run(0.1, v0_mm_s=[0, 1000, 0], w0_deg_s=[0, 0, math.degrees(10.0)])
    assert (w, vy) == (pytest.approx(10.0, rel=1e-12), pytest.approx(1.0, rel=1e-12))
    assert not any("初速度" in m for m in msgs)


def test_unit_independent():
    # 动能加权与长度单位无关：同一个不相容输入，摆长 0.5 m 与 2 m 都只去掉径向分量
    for r in (0.5, 2.0):
        w, _, vy, _ = _run(r, v0_mm_s=[300, 1000, 0])
        assert vy == pytest.approx(1.0, abs=1e-6) and w == pytest.approx(1.0 / r, rel=1e-6)
