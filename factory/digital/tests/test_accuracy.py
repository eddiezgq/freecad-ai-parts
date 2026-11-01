# -*- coding: utf-8 -*-
"""第 13 轮 9.4（1）：hub/accuracy.py（《机械制造技术》第 54 章与数字工厂共用）的单元测试——每个公式用手算或独立方法核对，
误差形态的判别用仿真车间的误差模型（sim/errors.py simulate）造数据核对，工艺规程工序 60 的精度预算由评审员复核。"""
import math
import random

import pytest

from hub import accuracy as A


def test_sensitive_direction():
    R = 20.0
    assert A.diameter_error(R, dy=0.01) == pytest.approx(0.02, rel=1e-6)          # 法向：Δd = 2Δy
    dz = A.diameter_error(R, dz=0.01)                                              # 切向：Δd ≈ Δz²/R，小三个数量级
    assert dz == pytest.approx(0.01 ** 2 / R, rel=1e-3) and dz < 1e-5


def test_principle_errors():
    assert A.nose_radius_error(0.8, 0) == pytest.approx(0) and A.nose_radius_error(0.8, 90) == pytest.approx(0, abs=1e-12)
    assert A.nose_radius_error(0.8, 45) == pytest.approx((math.sqrt(2) - 1) * 0.8)
    s = A.chord_length(30.0, 0.002)
    assert A.chord_error(30.0, s) == pytest.approx(0.002, rel=1e-9)
    assert A.chord_error(30.0, 1.0) == pytest.approx(1.0 ** 2 / (8 * 30.0), rel=1e-3)


def test_adjustment_error():
    r = A.adjustment_error(0.002, n_trial=4, meas_range=0.002)
    assert r["trial"] == pytest.approx(6 * 0.002 / 2) and r["total"] == pytest.approx(math.hypot(0.006, 0.002))


def test_spindle_turning_vs_boring():
    """车削时工件圆度反映主轴颈的形状（椭圆），与轴承孔形状无关；镗削时反过来"""
    journal, hole = [(2, 0.003, 0)], [(3, 0.004, 0)]
    t = A.spindle_roundness(journal, hole, "turning")
    b = A.spindle_roundness(journal, hole, "boring")
    assert t["roundness"] == pytest.approx(2 * 0.003, rel=1e-6)
    assert b["roundness"] == pytest.approx(2 * 0.004, rel=1e-6)
    assert A.harmonics(t["r"])["dominant"] == 2 and A.harmonics(b["r"])["dominant"] == 3


def test_guides_taper_chain():
    g = A.guide_errors(20.0, dy_h=0.01, dz_v=0.01, twist=0.02, H=200.0, B=400.0)
    assert g["horizontal"] == pytest.approx(0.02) and g["vertical"] < 1e-5 and g["twist"] == pytest.approx(0.02)
    assert A.taper_from_offset(0.008, 167.0, 46.0, 124.5) == pytest.approx(2 * 0.008 * 78.5 / 167)
    c = A.chain_error([("丝杠", 0.01, 1.0), ("交换齿轮", 0.02, 0.5)])
    assert c["extreme"] == pytest.approx(0.02) and c["rss"] == pytest.approx(math.hypot(0.01, 0.01))


def test_stiffness_shapes():
    """两顶尖车削：工件很刚、头尾架软 → 鞍形；工件细长、头尾架很刚 → 鼓形；尾座比头架软 → 锥度（尾座端大）"""
    kw = dict(Fp=300.0, L=500.0, k_tool=1e9)
    saddle = A.profile_between_centers(d=80.0, k_head=2e4, k_tail=2e4, **kw)
    drum = A.profile_between_centers(d=20.0, k_head=1e8, k_tail=1e8, **kw)
    taper = A.profile_between_centers(d=80.0, k_head=1e6, k_tail=1e4, **kw)
    assert saddle["label"] == "saddle" and drum["label"] == "drum" and taper["label"] == "taper"
    assert taper["dd"][-1] > taper["dd"][0]
    # 中点的工件挠度与简支梁公式 FL³/(48EI) 一致
    c = A.compliance_between_centers(250.0, 500.0, 20.0, 1e12, 1e12, 1e12)
    I = math.pi * 20 ** 4 / 64
    assert c["work"] == pytest.approx(500.0 ** 3 / (48 * A.E_STEEL * I), rel=1e-9)
    assert A.system_stiffness(2e4, 2e4) == pytest.approx(1e4)


def test_reflection_and_stiffness_measurement():
    eps = A.reflection(C=400.0, k=20000.0)
    assert eps == pytest.approx(0.02) and A.reflection(400.0, 20000.0, 2) == pytest.approx(0.0004)
    assert A.passes_needed(0.5, 0.01, 0.05) == 2                   # 0.5 → 0.025 → 0.00125
    k = A.stiffness_from_steps(C=400.0, d_ap=1.0, d_work=0.02)
    assert k == pytest.approx(20000.0)
    f = A.kienzle_turning(1.0, 0.2)
    assert f["Fp"] == pytest.approx(0.4 * f["Fc"]) and f["C"] == pytest.approx(f["Fp"])


def test_thermal():
    t = [i * 2.0 for i in range(40)]
    y = [35.010 - A.warmup(0.010, 12.0, v) for v in t]
    r = A.fit_warmup(t, y)
    assert r["tau"] == pytest.approx(12.0, rel=0.05) and r["delta_inf"] == pytest.approx(-0.010, rel=0.02)
    assert A.thermal_size(40.0, 10.0) == pytest.approx(40 * 11.5e-6 * 10)
    assert A.measure_temp_error(40.0, 30.0, 20.0) == pytest.approx(A.thermal_size(40.0, 10.0))
    assert A.measure_temp_error(40.0, 25.0, 25.0) == pytest.approx(0.0, abs=1e-12)     # 同温同材料不差
    assert A.abbe_error(20.0, 1e-4) == pytest.approx(0.002, rel=1e-6)


def test_wear_and_compensation():
    Lm = A.cutting_length_m(40.0, 60.0, 0.2)
    assert Lm == pytest.approx(math.pi * 40 * 60 / 0.2 / 1000)
    assert A.radial_wear(1000.0, 8.0, 3.0) == pytest.approx(0.011)
    r = A.compensation_interval(T=0.016, sigma=0.0012, drift=0.0125 / 30)
    assert r["n_max"] == math.floor((0.016 - 6 * 0.0012) / (0.0125 / 30))
    assert r["n_max"] >= 10                  # 工艺规程“每 10 件修整一次”在允许的间隔之内


def test_residual_stress_bow():
    E, d, L = A.E_STEEL, 40.0, 167.0
    I = math.pi * d ** 4 / 64
    M = A.layer_moment(200.0, 12 * 5, 17.5)
    r = A.bow_from_moment(M, L, 0.0, L, E, I)
    assert r["max"] == pytest.approx(M * L ** 2 / (8 * E * I), rel=1e-3)          # 全长均匀弯矩：ML²/(8EI)
    assert r["x"] == pytest.approx(L / 2, abs=0.2)


def test_shape_and_harmonics():
    x = [0, 25, 50, 75, 100]
    assert A.shape_along(x, [0.000, 0.002, 0.004, 0.006, 0.008])["label"] == "taper"
    assert A.shape_along(x, [0.0, 0.003, 0.004, 0.003, 0.0])["label"] == "drum"
    assert A.shape_along(x, [0.004, 0.001, 0.0, 0.001, 0.004])["label"] == "saddle"
    m = 120
    r3 = [0.003 * math.cos(3 * 2 * math.pi * i / m) + 0.001 * math.cos(2 * math.pi * i / m) for i in range(m)]
    h = A.harmonics(r3)
    assert h["label"] == "lobe3" and h["amp"][3] == pytest.approx(0.003, rel=1e-6)


def _sim(problem=None, n=60, **k):
    from sim import errors
    return errors.simulate(n, problem, seed=54, **k)


def test_sequences_from_the_simulated_shop():
    """仿真车间的数据：正常（磨损锯齿）、未预热（指数段）、尾座偏移（锥度）、中心孔差（分散变大），判别都对"""
    s = _sim(dress_every=10)
    resets = [i + 1 for i in s["dress_after"]]
    q = A.sequence(s["values"]["bearing_seat_d35"], resets=resets, sigma=0.0012)
    assert q["label"] == "drift_saw" and q["saw_slope"] == pytest.approx(0.0125 / 30, rel=0.35)
    w = _sim("thermal_warmup", dress_every=10)
    qw = A.sequence(w["values"]["bearing_seat_d35"], resets=[i + 1 for i in w["dress_after"]], sigma=0.0012)
    assert "warmup" in qw["labels"]
    t = _sim("tailstock_offset", n=20)
    left = sum(t["values"]["bearing_seat_d35"]) / 20
    right = sum(t["values"]["bearing_seat_d35_r"]) / 20
    from sim.errors import Z_LEFT, Z_RIGHT
    assert right - left == pytest.approx(A.taper_from_offset(0.008, 167.0, Z_LEFT, Z_RIGHT), abs=0.0012)
    d = A.diagnose(along=([Z_LEFT, Z_RIGHT], [left, right]), tol=0.016)
    assert d and d[0]["label"] == "taper" and any("尾座" in c for c in d[0]["causes"])
    c = _sim("center_hole", n=60, dress_every=10)
    base = _sim(n=60, dress_every=10)
    sd = lambda v: (sum((a - sum(v) / len(v)) ** 2 for a in v) / (len(v) - 1)) ** 0.5      # noqa: E731
    assert sd(c["values"]["runout_bearing"]) > 1.5 * sd(base["values"]["runout_bearing"])


def test_jump_detected():
    rng = random.Random(1)
    v = [35.008 + rng.gauss(0, 0.0012) for _ in range(20)] + [35.012 + rng.gauss(0, 0.0012) for _ in range(20)]
    q = A.sequence(v, sigma=0.0012)
    assert "jump" in q["labels"] and q["jump"]["at"] == pytest.approx(20, abs=2)


def test_budget_and_process_review():
    r = A.budget([{"name": "a", "range": 0.004, "kind": "sys"}, {"name": "b", "range": 0.003, "kind": "rand"},
                  {"name": "c", "range": 0.004, "kind": "rand"}], 0.016)
    assert r["total"] == pytest.approx(0.004 + 0.005) and r["ok"] and not r["tight"]
    from hub import process
    from hub.cards import load
    import os
    plan = load(os.path.join(os.path.dirname(__file__), "..", "std", "SH-301_process.yaml"))
    op60 = next(o for o in plan["operations"] if o["seq"] == 60)
    assert {a["char"] for a in op60["accuracy"]} == {"C1", "C7"}
    f = [x for x in process.review(plan) if x["rule"] == "精度"]
    assert f and all(x["level"] == "warning" for x in f)          # 磨 k6：预算在公差之内，但裕量不足（第 54 章的讨论）
    op60["accuracy"][0]["items"][1]["range"] = 0.0125          # 改为不修整、一个砂轮寿命内的磨损：超差
    f2 = [x for x in process.review(plan) if x["rule"] == "精度"]
    assert any(x["level"] == "error" for x in f2)
