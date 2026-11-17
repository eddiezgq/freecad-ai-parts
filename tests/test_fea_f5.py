"""有限元 F5（ADR-0093 补充八）：模态（预应力、多个实体）、谐响应、随机振动、瞬态。不联网、不调用 LLM。

参考值与出处：
- 单自由度：刚块（20 mm 立方体，自身频率远高于地基频率）放在弹性地基上，竖向一阶就是单自由度，ωₙ = √(kA/m)。
  - 谐响应：位移幅值 = (F/k) / √((1 − r²)² + (2ζr)²)，r = f/fₙ。
  - 白噪声基础加速度（单边谱 G）：相对位移的均方 = G / (8ζωₙ³)（Miles 1954；Crandall & Mark《Random Vibration in Mechanical Systems》）。
  - 阶跃载荷：u(t) = (F/k)·[1 − e^(−ζωₙt)(cos ω_d t + ζ/√(1 − ζ²) sin ω_d t)]，峰值约 2F/k（Chopra《Dynamics of Structures》第 4 章）。
- 悬臂梁端部受简谐力：端部位移 / 力 = (L³/EI)·(sin λ cosh λ − cos λ sinh λ) / (λ³(1 + cos λ cosh λ))，λ⁴ = ρAω²L⁴/EI
  （Euler–Bernoulli 梁的精确解；Bishop & Johnson《The Mechanics of Vibration》）。
- 两端铰支梁受轴力 T：fₙ = fₙ⁰·√(1 + TL²/(n²π²EI))（受压时 T 为负；Blevins《Formulas for Natural Frequency and Mode Shape》）。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

import analysis
from analysis.fea import dynamics as D
from analysis.fea import study as S
from tests.test_fea_bench import _faces, _need_fea, _plane, _write
from tests.verification import record

STEEL = "45-QT"
E, RHO = 210000.0, 7850e-12                 # 45-QT：MPa、t/mm³


def _run(bodies, supports, loads, steps, size, connections=(), **kw):
    st = {"format": "fea-study/1", "name": "f5", "bodies": bodies, "supports": supports, "loads": loads,
          "connections": list(connections), "steps": steps, "mesh": {"size_mm": size}, "checks": {"convergence": False}}
    st.update(kw)
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["steps"]


def _body(i, step):
    return {"id": i, "step_path": step, "material": STEEL}


def _verdicts(s):
    return {x["name"]: x["verdict"] for x in s["trust"]["items"]}


def _at(freqs, values, f):
    i = min(range(len(freqs)), key=lambda k: abs(freqs[k] - f))
    return freqs[i], values[i]


# ------------------------------------------------------------------ 单自由度：弹性地基上的刚块

KS, ZETA, F0 = 0.062, 0.02, 100.0          # 地基刚度 N/mm³（面积 400 mm²），阻尼比，力幅 N


@pytest.fixture(scope="module")
def sdof(tmp_path_factory):
    _need_fea()
    step = _write(tmp_path_factory.mktemp("sdof") / "cube.step", lambda o: o.addBox(0, 0, 0, 20, 20, 20))
    f = _faces(step)
    steps = [{"id": "m", "type": "modal", "n_modes": 6},
             {"id": "h", "type": "harmonic", "f_min_hz": 20, "f_max_hz": 300, "n_points": 50, "damping_ratio": ZETA},
             {"id": "r", "type": "random", "direction": [0, 0, 1], "damping_ratio": ZETA,
              "asd": [{"frequency_hz": 5, "asd_m2_s4_per_hz": 1.0}, {"frequency_hz": 5000, "asd_m2_s4_per_hz": 1.0}]},
             {"id": "t", "type": "transient", "end_time_s": 0.05, "time_step_s": 5e-5, "damping_ratio": 0.001,
              "amplitude": [{"time_s": 0, "factor": 1}, {"time_s": 1, "factor": 1}]}]
    out = _run([_body("b", step)], [{"type": "elastic_support", "body": "b", "faces": [_plane(f, 2, 0)], "stiffness_n_per_mm3": KS}],
               [{"type": "force", "body": "b", "faces": [_plane(f, 2, 20)], "vector_n": [0, 0, -F0]}], steps, 5.0,
               probes=[{"id": "top", "point_mm": [10, 10, 20]}])
    k, m = KS * 400, RHO * 8000
    return {r["id"]: r for r in out}, k, m, math.sqrt(k / m)


def test_sdof_frequency_and_effective_mass(sdof):
    r, _k, _m, wn = sdof
    mo = r["m"]
    vertical = min(mo["freqs"], key=lambda x: abs(x["hz"] - wn / (2 * math.pi)))
    record(("竖向固有频率", "vertical natural frequency"), vertical["hz"], wn / (2 * math.pi), tol=1e-3, unit="Hz",
           formula="ωn = √(kA/m)")
    assert vertical["hz"] == pytest.approx(wn / (2 * math.pi), rel=1e-3)
    assert mo["effective_mass_fraction"]["z"] == pytest.approx(1.0, abs=1e-3)       # 地基上的刚块：全部质量都参与
    assert mo["surface"]["u"] and mo["prestress"] is False


def test_sdof_harmonic_amplification(sdof):
    r, k, _m, wn = sdof
    h = r["h"]
    fn = wn / (2 * math.pi)
    amp = h["probes"][0]["u_amp_mm"][2]
    for target in (50.0, fn, 200.0):
        f, a = _at(h["frequencies_hz"], amp, target)
        rr = f / fn
        record((f"位移幅值（f/fn = {rr:.2f}）", f"displacement amplitude (f/fn = {rr:.2f})"), a,
               (F0 / k) / math.sqrt((1 - rr * rr) ** 2 + (2 * ZETA * rr) ** 2), tol=0.005, unit="mm",
               formula="(F/k)/√((1 − r²)² + (2ζr)²)")
        assert a == pytest.approx((F0 / k) / math.sqrt((1 - rr * rr) ** 2 + (2 * ZETA * rr) ** 2), rel=0.005)
    assert h["peak"]["frequency_hz"] == pytest.approx(fn, rel=0.002)                  # 共振峰没有落在频率点之间
    v = _verdicts(h)
    assert v["模态截断"] == "pass" and v["频率范围"] == "pass" and h["trust"]["verdict"] == "pass"


def test_sdof_random_miles(sdof):
    r, _k, _m, wn = sdof
    rv = r["r"]
    g = 1.0e6                                                                         # 1 (m/s²)²/Hz = 10⁶ (mm/s²)²/Hz
    record(("相对位移均方根", "RMS relative displacement"), rv["probes"][0]["u_rms_mm"][2], math.sqrt(g / (8 * ZETA * wn ** 3)),
           tol=0.01, unit="mm", formula="√(G/(8ζωn³)) (Miles)")
    assert rv["probes"][0]["u_rms_mm"][2] == pytest.approx(math.sqrt(g / (8 * ZETA * wn ** 3)), rel=0.01)
    assert rv["input_a_rms_m_s2"] == pytest.approx(math.sqrt(5000 - 5), rel=1e-3)     # 平直谱：RMS = √(G·Δf)
    assert rv["vm_3sigma_mpa"] == pytest.approx(3 * rv["vm_rms_max_mpa"], rel=1e-4)
    assert _verdicts(rv)["模态截断"] == "pass" and rv["effective_mass_fraction"] >= 0.99


def test_sdof_step_load(sdof):
    r, k, _m, wn = sdof
    t = r["t"]
    z = 0.001
    wd = wn * math.sqrt(1 - z * z)
    ust = F0 / k
    uz = t["probes"][0]["u_mm"][2]
    for i in (17, 63, 100, 400, 999):
        tt = t["times_s"][i]
        exact = -ust * (1 - math.exp(-z * wn * tt) * (math.cos(wd * tt) + z / math.sqrt(1 - z * z) * math.sin(wd * tt)))
        assert uz[i] == pytest.approx(exact, rel=0.005, abs=ust * 1e-3)
    record(("阶跃载荷峰值位移", "peak displacement under step load"), t["u_max_mm"], 2 * ust, tol=0.01, unit="mm",
           formula="u_max ≈ 2F/k (Chopra)")
    assert t["u_max_mm"] == pytest.approx(2 * ust, rel=0.01)
    assert t["u_max_time_s"] == pytest.approx(math.pi / wd, rel=0.02)
    assert _verdicts(t)["模态截断"] == "pass"


def test_piecewise_linear_integrator_is_exact():
    """模态坐标的积分（Chopra 表 5.2.1）：恒力与斜坡力都和闭式解一致，与步长无关"""
    w, z = 2 * math.pi * 50, 0.05
    wd = w * math.sqrt(1 - z * z)
    t = np.linspace(0, 0.2, 41)                                                       # 每步 5 ms，约四分之一周期
    q = D.sdof_piecewise_linear(w, z, t, np.ones_like(t))
    exact = (1 - np.exp(-z * w * t) * (np.cos(wd * t) + z / math.sqrt(1 - z * z) * np.sin(wd * t))) / w ** 2
    assert np.allclose(q * w ** 2, exact * w ** 2, rtol=0, atol=1e-9)
    ramp = D.sdof_piecewise_linear(w, 0.0001, t, t.copy())                            # 斜坡 p = t（几乎无阻尼）：q = (t − sin ωt / ω) / ω²
    assert np.allclose(ramp, (t - np.sin(w * t) / w) / w ** 2, rtol=1e-3, atol=1e-9)


# ------------------------------------------------------------------ 悬臂梁谐响应（连续梁精确解）


def test_cantilever_harmonic_exact(tmp_path):
    _need_fea()
    L, b = 200.0, 10.0
    step = _write(tmp_path / "cant.step", lambda o: o.addBox(0, 0, 0, L, b, b))
    f = _faces(step)
    EI, rA = E * b ** 4 / 12, RHO * b * b
    f1 = 1.875104 ** 2 / (2 * math.pi) * math.sqrt(EI / (rA * L ** 4))
    _m, h = _run([_body("b", step)], [{"type": "fixed", "body": "b", "faces": [_plane(f, 0, 0)]}],
                 [{"type": "force", "body": "b", "faces": [_plane(f, 0, L)], "vector_n": [0, 0, 1.0]}],
                 [{"id": "m", "type": "modal", "n_modes": 2},
                  {"id": "h", "type": "harmonic", "f_min_hz": 0.2 * f1, "f_max_hz": 3.2 * f1, "n_points": 60, "damping_ratio": 0.001,
                   "n_modes": 20}], 5.0, probes=[{"id": "tip", "point_mm": [L, b / 2, b / 2]}])
    record(("一阶固有频率", "first natural frequency"), _m["freqs"][0]["hz"], f1, tol=0.005, unit="Hz",
           formula="(1.875104²/2π)·√(EI/(ρAL⁴))")
    assert _m["freqs"][0]["hz"] == pytest.approx(f1, rel=0.005)

    def receptance(w):
        lam = (rA * w * w * L ** 4 / EI) ** 0.25
        return L ** 3 / EI * (math.sin(lam) * math.cosh(lam) - math.cos(lam) * math.sinh(lam)) / (lam ** 3 * (1 + math.cos(lam) * math.cosh(lam)))
    amp = h["probes"][0]["u_amp_mm"][2]
    for r in (0.2, 0.5, 2.0, 3.0):                                                    # 一阶以下、一阶与二阶之间
        fq, a = _at(h["frequencies_hz"], amp, r * f1)
        record((f"端部位移 / 力（f = {r:g}·f1）", f"tip receptance (f = {r:g}·f1)"), a, abs(receptance(2 * math.pi * fq)), tol=0.01,
               unit="mm/N", formula="Euler–Bernoulli beam exact receptance")
        assert a == pytest.approx(abs(receptance(2 * math.pi * fq)), rel=0.01)


# ------------------------------------------------------------------ 预应力模态、多个实体的模态


def test_prestressed_pinned_beam(tmp_path):
    _need_fea()
    L, b = 200.0, 10.0
    step = _write(tmp_path / "pp.step", lambda o: o.addBox(0, 0, 0, L, b, b))
    f = _faces(step)
    ed = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["edges"]
    edge = next(e["id"] for e in ed if all(abs(x - y) < 1e-6 for x, y in zip(e["center"], [0, b / 2, 0])))
    pcr = math.pi ** 2 * E * (b ** 4 / 12) / L ** 2
    # 两端面只限制 y、z（绕 y 轴可转：z 向弯曲两端铰支）；轴向只用一条底棱限制（两端受等值反向的力，这条棱上没有轴向反力）
    sup = [{"type": "displacement", "body": "b", "faces": [_plane(f, 0, x)], "uy_mm": 0, "uz_mm": 0} for x in (0, L)]
    sup.append({"type": "displacement", "body": "b", "edges": [edge], "ux_mm": 0})

    def f1(tension, pre):
        loads = [{"type": "force", "body": "b", "faces": [_plane(f, 0, L)], "vector_n": [tension, 0, 0]},
                 {"type": "force", "body": "b", "faces": [_plane(f, 0, 0)], "vector_n": [-tension, 0, 0]}]
        s = _run([_body("b", step)], sup, loads, [{"id": "m", "type": "modal", "n_modes": 2, "prestress": pre}], 5.0)[0]
        assert s["prestress"] is pre
        return s["freqs"][0]["hz"]                                                    # 一阶是 z 向（两端铰支）弯曲
    f0 = f1(1.0, False)
    ten = f1(pcr, True) / f0
    record(("受拉（T = Pcr）频率比", "frequency ratio in tension (T = Pcr)"), ten, math.sqrt(2.0), tol=0.015,
           formula="fn/fn0 = √(1 + TL²/(π²EI))")
    assert ten == pytest.approx(math.sqrt(2.0), rel=0.015)                            # 拉力 = 欧拉临界力：频率 × √2
    assert f1(-0.5 * pcr, True) / f0 == pytest.approx(math.sqrt(0.5), rel=0.015)      # 压力 = 一半临界力：频率 × √0.5


def test_bonded_bodies_modal_equals_single_bar(tmp_path):
    _need_fea()
    whole = _write(tmp_path / "w.step", lambda o: o.addBox(0, 0, 0, 200, 10, 10))
    a = _write(tmp_path / "a.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    b = _write(tmp_path / "b.step", lambda o: o.addBox(100, 0, 0, 100, 10, 10))
    fw, fa, fb = _faces(whole), _faces(a), _faces(b)
    step = [{"id": "m", "type": "modal", "n_modes": 2}]
    one = _run([_body("w", whole)], [{"type": "fixed", "body": "w", "faces": [_plane(fw, 0, 0)]}], [], step, 5.0)[0]
    two = _run([_body("A", a), _body("B", b)], [{"type": "fixed", "body": "A", "faces": [_plane(fa, 0, 0)]}], [], step, 5.0,
               connections=[{"type": "bonded", "a": {"body": "B", "faces": [_plane(fb, 0, 100)]},
                             "b": {"body": "A", "faces": [_plane(fa, 0, 100)]}}], mesh={"size_mm": 4.0})[0]
    record(("两段绑定与整根杆的一阶频率", "first frequency, two bonded parts vs one bar"), two["freqs"][0]["hz"],
           one["freqs"][0]["hz"], tol=0.005, unit="Hz", formula="same structure")
    assert two["freqs"][0]["hz"] == pytest.approx(one["freqs"][0]["hz"], rel=0.005)


# ------------------------------------------------------------------ 校验


def _st(steps, **kw):
    st = {"format": "fea-study/1", "name": "x", "bodies": [_body("b", "x.step")],
          "supports": [{"type": "fixed", "body": "b", "faces": [1]}],
          "loads": [{"type": "force", "body": "b", "faces": [2], "vector_n": [0, 0, -1]}], "steps": steps}
    st.update(kw)
    return st


H = {"id": "h", "type": "harmonic", "f_min_hz": 10, "f_max_hz": 100, "damping_ratio": 0.02}


def test_dynamics_validation():
    S.validate(_st([H]))
    with pytest.raises(S.StudyInvalid, match="上限频率"):
        S.validate(_st([dict(H, f_min_hz=200)]))
    with pytest.raises(S.StudyInvalid, match="弹塑性"):
        S.validate(_st([H], bodies=[{**_body("b", "x.step"), "plasticity": {"model": "perfectly_plastic"}}]))
    with pytest.raises(S.StudyInvalid, match="温度"):
        S.validate(_st([H], loads=[{"type": "temperature", "body": "b", "delta_t_k": 10}]))
    with pytest.raises(S.StudyInvalid, match="强制位移"):
        S.validate(_st([H], supports=[{"type": "displacement", "body": "b", "faces": [1], "ux_mm": 0.1}]))
    with pytest.raises(S.StudyInvalid, match="要有载荷"):
        S.validate(_st([H], loads=[]))
    rnd = {"id": "r", "type": "random", "direction": [0, 0, 0], "damping_ratio": 0.02,
           "asd": [{"frequency_hz": 10, "asd_m2_s4_per_hz": 1}, {"frequency_hz": 100, "asd_m2_s4_per_hz": 1}]}
    with pytest.raises(S.StudyInvalid, match="零向量"):
        S.validate(_st([rnd], loads=[]))
    S.validate(_st([dict(rnd, direction=[0, 0, 1])], loads=[]))                       # 随机振动不用载荷
    with pytest.raises(S.StudyInvalid, match="递增"):
        S.validate(_st([dict(rnd, direction=[1, 0, 0], asd=rnd["asd"][::-1])], loads=[]))
    tr = {"id": "t", "type": "transient", "end_time_s": 1, "time_step_s": 1e-5, "damping_ratio": 0.02,
          "amplitude": [{"time_s": 0, "factor": 0}, {"time_s": 0.1, "factor": 1}]}
    with pytest.raises(S.StudyInvalid, match="20000"):
        S.validate(_st([tr]))
    with pytest.raises(S.StudyInvalid, match="时间要递增"):
        S.validate(_st([dict(tr, time_step_s=1e-3, amplitude=tr["amplitude"][::-1])]))
    st = _st([H], bodies=[_body("b", "x.step"), _body("c", "y.step")],
             connections=[{"type": "contact", "a": {"body": "c", "faces": [1]}, "b": {"body": "b", "faces": [3]}}])
    with pytest.raises(S.StudyInvalid, match="绑定"):
        S.validate(st)
