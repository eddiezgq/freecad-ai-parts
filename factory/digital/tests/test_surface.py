# -*- coding: utf-8 -*-
"""第 13 轮 11.4（1）：hub/surface.py（《机械制造技术》第 55 章与数字工厂共用）的单元测试——公式用手算或独立方法核对。"""
import math

import numpy as np
import pytest

from hub import surface as S

M45, M20 = S.STEELS["45-QT"], S.STEELS["20CrMnTi-CQ"]


def test_residual_height_and_theoretical_ra():
    assert S.residual_height(0.2, 0.8) == pytest.approx(0.8 - math.sqrt(0.64 - 0.01))
    assert S.residual_height(0.1, 0.8) == pytest.approx(0.1 ** 2 / (8 * 0.8), rel=2e-3)         # f²/(8r)
    assert S.residual_height_sharp(0.2, 45, 45) == pytest.approx(0.1)                           # 两个 45°：h = f/2
    assert S.feed_for_ra(S.ra_theory(0.15, 0.4), 0.4) == pytest.approx(0.15)
    # 只有几何残留的轮廓（不加噪声、不加波纹、高速无积屑瘤），数值的 Ra 与 0.0321 f²/r 相差不到 3%
    x, z = S.turned_profile(0.1, 0.8, vc_m_min=200, noise_um=0)
    assert S.roughness(x, z)["Ra"] == pytest.approx(S.ra_theory(0.1, 0.8), rel=0.03)
    assert S.ra_theory(0.1, 0.8) == pytest.approx(0.0321 * 0.1 ** 2 / 0.8 * 1000, rel=1e-3)


def test_roughness_parameters_of_a_sine():
    """正弦轮廓（波长远小于 λc）：Ra = 2A/π，Rq = A/√2，Rz = Rt = 2A。"""
    x = np.arange(0, 7 * S.LC, S.DX)
    A = 0.001
    r = S.roughness(x, A * np.sin(2 * math.pi * x / 0.05))
    assert r["Ra"] == pytest.approx(2 * A * 1000 / math.pi, rel=0.01)
    assert r["Rq"] == pytest.approx(A * 1000 / math.sqrt(2), rel=0.01)
    assert r["Rz"] == pytest.approx(2 * A * 1000, rel=0.01)
    assert S.material_ratio(r["r"], 2 * A * 1000) == pytest.approx(1.0, abs=0.02)
    assert S.material_ratio(r["r"], A * 1000) == pytest.approx(0.5, abs=0.02)


def test_built_up_edge_makes_it_rougher():
    assert S.bue_amplitude(25) == pytest.approx(2.0) and S.bue_amplitude(120) < 0.05 and S.bue_amplitude(3) < 0.05
    ra = lambda vc: np.mean([S.roughness(*S.turned_profile(0.1, 0.8, vc_m_min=vc, seed=s))["Ra"] for s in range(3)])
    assert ra(25) > 2.5 * ra(120)


def test_grinding_geometry_and_temperature_by_hand():
    de = S.equivalent_diameter(35, 400)
    assert de == pytest.approx(35 * 400 / 435)
    assert S.equivalent_diameter(math.inf, 400) == 400 and S.equivalent_diameter(60, 40, internal=True) == pytest.approx(120)
    vs, vw, ap = 35.0, 20 / 60, 0.01
    g = S.grinding_temperature(M45, vs, vw, ap, de)
    lc = math.sqrt(ap * de)
    h = vw * ap / vs * 1000
    u = 14 * h ** -0.35
    alpha = 49.8 / (7850 * 486)
    q = 0.7 * u * 1e9 * vw * ap * 1e-3 / (lc * 1e-3)
    assert g["lc"] == pytest.approx(lc) and g["heq"] == pytest.approx(h) and g["u"] == pytest.approx(u)
    assert g["rise_approx"] == pytest.approx(1.13 * q * math.sqrt(alpha * lc * 1e-3 / vw) / 49.8)
    assert g["peclet"] == pytest.approx(vw * lc * 1e-3 / (4 * alpha))
    # 精确解（Jaeger 积分）在 Peclet 数约 3.6 时比 1.13 的近似式低 5% 左右；Peclet 数大时两者趋于一致
    assert 0.9 < g["rise"] / g["rise_approx"] < 1.0
    assert S.jaeger_peak(80) == pytest.approx(1.13 * math.pi * math.sqrt(80), rel=0.01)   # 2qα/(πkv)·峰值 → 1.13·q·√(α·lc/v)/k
    # 同一 heq 下 θ ∝ ap^(3/4)·vw^(1/2)（近似式）：vw 加倍、ap 减半，温度变为 2^(1/2)·2^(−3/4) 倍
    g2 = S.grinding_temperature(M45, vs, 2 * vw, ap / 2, de)
    assert g2["rise_approx"] / g["rise_approx"] == pytest.approx(2 ** 0.5 * 2 ** -0.75, rel=1e-9)
    # 砂轮钝化：比磨削能、温度都上升
    assert S.grinding_temperature(M45, vs, vw, ap, de, wear_flat_pct=4)["theta"] > g["theta"] + 150


def test_temper_onset_and_burn_classes():
    assert S.temper_onset(M45, 2 * 3600) == pytest.approx(560)                         # 与原回火工艺相同时间：回火温度本身
    assert S.temper_onset(M45, 1e-3) > S.temper_onset(M45, 1.0) > 560                  # 受热越短，越高才软化
    assert S.temper_onset(M20, 1e-3) == pytest.approx(453.15 * (20 + math.log10(7200)) / 17 - 273.15)
    assert S.burn_state(M20, 300, 1.0)["kind"] == "none"
    assert S.burn_state(M20, 500, 1.0)["kind"] == "tempering"
    assert S.burn_state(M20, 800, 1.0)["kind"] == "rehardening" and S.burn_state(M20, 800, 1.0, coolant=False)["kind"] == "annealing"
    # 调质钢的回火软化温度在 Ac1 以上：烧伤直接是二次淬火
    assert S.temper_onset(M45, 1.2e-3) > M45["Ac1"] and S.burn_state(M45, 750, 1.2)["kind"] == "rehardening"


def test_burn_boundary():
    de = S.equivalent_diameter(25, 400)
    ap = S.max_infeed(M20, 35, 1 / 3, de)
    g = S.grinding_temperature(M20, 35, 1 / 3, ap, de)
    assert g["theta"] == pytest.approx(S.burn_state(M20, g["theta"], g["t_ms"])["onset"], abs=1.0)
    assert 0.002 < ap < 0.005
    b = S.burn_boundary(M20, 35, de, [0.1, 0.2, 0.4])
    assert b[0][1] > b[1][1] > b[2][1]                                                  # 工件越快，允许的切深越小
    assert S.max_infeed(M20, 35, 1 / 3, de, wear_flat_pct=4) < ap                       # 钝砂轮更容易烧
    assert S.max_infeed(M45, 35, 1 / 3, S.equivalent_diameter(35, 400)) > 0.01          # SH-301 粗磨 0.01 不烧伤


def test_grinding_roughness():
    h = S.heq(20 / 60, 0.005, 35)
    assert S.grinding_ra(h) == pytest.approx(2.6 * h ** 0.4)
    assert S.grinding_ra(h) > S.grinding_ra(h, 1) > S.grinding_ra(h, 2) > 0.4           # 光磨逐次变细，趋于 0.4
    assert S.grinding_ra(h, 50) == pytest.approx(0.4, rel=1e-6) and S.grinding_ra(h, 50, mesh=120) == pytest.approx(0.2, rel=1e-6)
    assert S.grinding_ra(h, 2) < 0.8                                                    # SH-301 工艺规程：精磨 0.005、光磨 2 次达到 Ra 0.8
    assert S.grinding_ra(h, 2, wear_flat_pct=6) > S.grinding_ra(h, 2)


def test_hardening_and_residual_profiles():
    z = np.array([0.0, 0.1, 1.0])
    hv = S.hardness_profile(200, 0.4, 0.1, z)
    assert hv[0] == pytest.approx(280) and hv[1] == pytest.approx(200 * (1 + 0.4 * math.exp(-3))) and hv[2] == pytest.approx(200, rel=1e-6)
    for k, pts in S.RESIDUAL.items():
        d = np.array([p[0] for p in pts])
        assert np.allclose(S.residual_stress(k, d), [p[1] for p in pts])
    assert S.residual_stress("ground_burn", np.array([0.0]))[0] > 0 > S.residual_stress("ground", np.array([0.0]))[0]
    assert S.residual_stress("rolled", np.array([0.5]))[0] < S.residual_stress("shot_peened", np.array([0.5]))[0]   # 滚压的压应力层更深


def test_fatigue_with_surface_and_residual_stress():
    assert S.roughness_factor(1.0, 640) == 1.0
    assert S.roughness_factor(10, 640) == pytest.approx(1 - 0.22 * 1 * math.log10(3.2))
    assert S.roughness_factor(10, 1080) < S.roughness_factor(10, 640)                   # 强度高的钢对粗糙度更敏感
    assert S.mean_stress_sensitivity(640) == pytest.approx(0.124)
    base = S.fatigue_limit(M20, 3.0)["sigma_D"]
    assert S.fatigue_limit(M20, 3.0, 500)["sigma_D"] == pytest.approx(base - 0.278 * 500)
    assert S.fatigue_limit(M20, 3.0, -300)["sigma_D"] > base
    assert S.life(300, 350) == math.inf
    assert S.life(400, 350) == pytest.approx(1e7 * (400 / 350) ** -9)
