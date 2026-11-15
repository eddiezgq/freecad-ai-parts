"""有限元 F4（ADR-0093 补充六）：弹塑性、大变形、线性屈曲；另补 F3 的 Hertz 接触题。不联网、不调用 LLM。

参考值与出处：
- 欧拉压杆（一端固定一端自由）：P = π²EI / (4L²)（Timoshenko & Gere《Theory of Elastic Stability》第 2 章）。
- 四边简支方板单向受压：σ = kπ²E / (12(1 − ν²)) · (t/b)²，k = 4（同书第 9 章）。板厚 t/b = 1/20，计入剪切变形的厚板值
  比薄板公式低 1–2 %，实体单元通过厚度只有两三层时又偏刚，容差 3 %。
- 理想弹塑性拉杆：屈服后反力 = σy·A，等效塑性应变 = ε − σy/E（定义）。
- 硬化曲线拉杆：σ = σ₀ + H·εp 且 εp = ε − σ/E，两式联立（输入的曲线就是参考，不是材料数据）。
- 厚壁筒内压的极限压力（理想弹塑性、Mises、平面应变）：p = (2/√3)·σy·ln(b/a)（Hill《The Mathematical Theory of Plasticity》1950，第 5 章）。
- 大挠度悬臂（端部集中力方向不变，PL²/EI = 1）：端部竖向位移 / L = 0.30172、水平缩进 / L = 0.05643
  （Bisshopp & Drucker 1945，Quart. Appl. Math. 3；Mattiasson 1981 的数值表）。
- Hertz 接触（球—平面，同材料）：a = (3FR / (4E*))^(1/3)，E* = E / (2(1 − ν²))，最大压力 p₀ = 3F / (2πa²)
  （Johnson《Contact Mechanics》1985，第 4 章）。
"""

from __future__ import annotations

import math

import pytest

import analysis
from analysis.fea import study as S
from tests.test_fea_bench import _faces, _need_fea, _plane, _write

STEEL = "45-QT"
E, NU, SY = 210000.0, 0.30, 355.0           # 45-QT（材料库）


def _run(bodies, supports, loads, steps, size, connections=(), **kw):
    st = {"format": "fea-study/1", "name": "f4", "bodies": bodies, "supports": supports, "loads": loads,
          "connections": list(connections), "steps": steps, "mesh": {"size_mm": size}, "checks": {"convergence": False}}
    st.update(kw)
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["steps"][0]


def _verdicts(s):
    return {x["name"]: x["verdict"] for x in s["trust"]["items"]}


def _edges(step):
    return analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["edges"]


def _edge_at(edges, c):
    return next(e["id"] for e in edges if all(abs(x - y) < 1e-6 for x, y in zip(e["center"], c)))


def _body(i, step, **kw):
    return {"id": i, "step_path": step, "material": STEEL, **kw}


# ------------------------------------------------------------------ 线性屈曲


def test_euler_column_buckling(tmp_path):
    _need_fea()
    step = _write(tmp_path / "col.step", lambda o: o.addBox(0, 0, 0, 10, 10, 200))
    f = _faces(step)
    s = _run([_body("c", step)], [{"type": "fixed", "body": "c", "faces": [_plane(f, 2, 0)]}],
             [{"type": "force", "body": "c", "faces": [_plane(f, 2, 200)], "vector_n": [0, 0, -1000]}],
             [{"id": "b", "type": "buckling", "n_modes": 2}], 5.0)
    pcr = math.pi ** 2 * E * (10 ** 4 / 12) / (4 * 200 ** 2)
    assert s["type"] == "buckling" and len(s["load_factors"]) == 2
    assert s["load_factors"][0] * 1000 == pytest.approx(pcr, rel=0.01)
    assert s["load_factors"][1] == pytest.approx(s["load_factors"][0], rel=0.01)      # 方截面：两个方向同一个值
    assert s["buckles_under_reference_load"] is False


def test_simply_supported_plate_buckling(tmp_path):
    _need_fea()
    a, t = 100.0, 5.0
    step = _write(tmp_path / "plate.step", lambda o: o.addBox(0, 0, 0, a, a, t))
    f, ed = _faces(step), _edges(step)
    sig = 100.0

    def side(ax, v):                       # 侧面只限制面外位移：可以绕棱边转动（简支）
        return {"type": "displacement", "body": "p", "faces": [_plane(f, ax, v)], "uz_mm": 0}
    # 面内的刚体运动只用两条底棱限制（两端受等值反向的力，这两条棱上没有反力），不约束面内伸缩
    sup = [side(0, 0), side(0, a), side(1, 0), side(1, a),
           {"type": "displacement", "body": "p", "edges": [_edge_at(ed, [0, a / 2, 0])], "ux_mm": 0},
           {"type": "displacement", "body": "p", "edges": [_edge_at(ed, [a / 2, 0, 0])], "uy_mm": 0}]
    loads = [{"type": "force", "body": "p", "faces": [_plane(f, 0, a)], "vector_n": [-sig * a * t, 0, 0]},
             {"type": "force", "body": "p", "faces": [_plane(f, 0, 0)], "vector_n": [sig * a * t, 0, 0]}]
    s = _run([_body("p", step)], sup, loads, [{"id": "b", "type": "buckling", "n_modes": 1}], 2.5)
    scr = 4 * math.pi ** 2 * E / (12 * (1 - NU ** 2)) * (t / a) ** 2
    assert s["load_factors"][0] * sig == pytest.approx(scr, rel=0.03)


def test_buckling_rejects_plasticity_and_contact():
    st = {"format": "fea-study/1", "name": "x", "bodies": [_body("b", "x.step", plasticity={"model": "perfectly_plastic"})],
          "supports": [{"type": "fixed", "body": "b", "faces": [1]}],
          "loads": [{"type": "force", "body": "b", "faces": [2], "vector_n": [0, 0, -1]}],
          "steps": [{"id": "b", "type": "buckling"}]}
    with pytest.raises(S.StudyInvalid, match="弹塑性"):
        S.validate(st)
    st["bodies"] = [_body("b", "x.step"), _body("c", "y.step")]
    st["connections"] = [{"type": "contact", "a": {"body": "c", "faces": [1]}, "b": {"body": "b", "faces": [3]}}]
    with pytest.raises(S.StudyInvalid, match="接触"):
        S.validate(st)


def test_plastic_curve_must_increase():
    st = {"format": "fea-study/1", "name": "x", "supports": [{"type": "fixed", "body": "b", "faces": [1]}],
          "loads": [{"type": "force", "body": "b", "faces": [2], "vector_n": [0, 0, -1]}], "steps": [{"id": "s", "type": "static"}],
          "bodies": [_body("b", "x.step", plasticity={"model": "curve", "source": "测试用", "points": [
              {"true_stress_mpa": 355, "plastic_strain": 0.01}, {"true_stress_mpa": 400, "plastic_strain": 0.02}]})]}
    with pytest.raises(S.StudyInvalid, match="塑性曲线"):
        S.validate(st)
    st["bodies"][0]["plasticity"]["points"][0]["plastic_strain"] = 0.0
    S.validate(st)
    st["bodies"][0]["plasticity"]["points"][1]["plastic_strain"] = 0.0
    with pytest.raises(S.StudyInvalid, match="塑性曲线"):
        S.validate(st)


# ------------------------------------------------------------------ 弹塑性


def _bar(tmp_path, plasticity, ux):
    step = _write(tmp_path / "bar.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    f = _faces(step)
    sym = [{"type": "symmetry", "body": "b", "faces": [_plane(f, ax, 0)]} for ax in (0, 1, 2)]
    pull = {"type": "displacement", "body": "b", "faces": [_plane(f, 0, 100)], "ux_mm": ux}
    s = _run([_body("b", step, plasticity=plasticity)], [*sym, pull], [], [{"id": "s", "type": "static"}], 5.0,
             probes=[{"id": "m", "point_mm": [50, 5, 5]}])
    hist = [h["supports"][3]["force_n"][0] for h in s["nonlinear"]["history"]]
    return s, hist


def test_perfectly_plastic_bar_plateau(tmp_path):
    _need_fea()
    s, hist = _bar(tmp_path, {"model": "perfectly_plastic"}, 0.5)           # 应变 0.5 %，约为屈服应变的 3 倍
    nl = s["nonlinear"]
    assert nl["completed"] and nl["plasticity"] and nl["increments"] >= 10
    assert hist[-1] == pytest.approx(SY * 100, rel=0.005)                     # 屈服后反力平台 = σy·A
    assert max(hist) <= SY * 100 * 1.005
    assert hist[0] == pytest.approx(E * nl["history"][0]["load_fraction"] * 0.5 / 100 * 100, rel=0.01)   # 第一个增量还在弹性段
    assert s["peeq_max"] == pytest.approx(0.005 - SY / E, rel=0.01)
    assert "safety_factor" not in s and "弹塑性" in s["safety_factor_withheld"]
    assert _verdicts(s)["载荷加完"] == "pass" and _verdicts(s)["反力平衡"] == "pass"


def test_hardening_curve_bar(tmp_path):
    _need_fea()
    s0, h = 355.0, 10000.0                                                    # 测试用的人为曲线：σ = 355 + 10000·εp
    curve = {"model": "curve", "source": "测试用的人为曲线，不是材料数据",
             "points": [{"true_stress_mpa": s0, "plastic_strain": 0}, {"true_stress_mpa": s0 + h * 0.01, "plastic_strain": 0.01}]}
    s, hist = _bar(tmp_path, curve, 0.5)
    sig = (s0 + h * 0.005) / (1 + h / E)
    assert hist[-1] / 100 == pytest.approx(sig, rel=0.005)
    assert s["probes"][0]["stress_mpa"]["xx"] == pytest.approx(sig, rel=0.005)
    assert s["peeq_max"] == pytest.approx(0.005 - sig / E, rel=0.01)


def test_thick_cylinder_limit_pressure(tmp_path):
    _need_fea()
    a, b, L = 10.0, 20.0, 5.0

    def ring(o):
        c = o.addCylinder(0, 0, 0, 0, 0, L, b)
        o.cut([(3, c)], [(3, o.addCylinder(0, 0, -1, 0, 0, L + 2, a))])
        o.intersect([(3, c)], [(3, o.addBox(0, 0, -1, b + 1, b + 1, L + 2))])
    step = _write(tmp_path / "ring.step", ring)
    f = _faces(step)
    bore = min((x for x in f if x["kind"] == "cylinder"), key=lambda x: x["radius_mm"])["id"]
    sup = [{"type": "symmetry", "body": "r", "faces": [_plane(f, ax, v)]} for ax, v in ((0, 0), (1, 0), (2, 0), (2, L))]  # 两端面都对称：平面应变
    plim = 2 / math.sqrt(3) * SY * math.log(b / a)
    p = 1.1 * plim                                                            # 比极限压力大 10 %：算不完全部载荷
    s = _run([_body("r", step, plasticity={"model": "perfectly_plastic"})], sup,
             [{"type": "pressure", "body": "r", "faces": [bore], "value_mpa": p}], [{"id": "s", "type": "static"}], 2.5)
    nl = s["nonlinear"]
    assert nl["completed"] is False
    assert nl["load_fraction_reached"] * p == pytest.approx(plim, rel=0.02)
    v = _verdicts(s)
    assert v["载荷加完"] == "fail" and v["反力平衡"] == "pass"               # 平衡按已加到的那一成载荷核对
    assert s["trust"]["verdict"] == "fail" and "safety_factor" not in s


# ------------------------------------------------------------------ 大变形


def test_large_deflection_cantilever(tmp_path):
    _need_fea()
    L, b = 200.0, 5.0
    step = _write(tmp_path / "can.step", lambda o: o.addBox(0, 0, 0, L, b, b))
    f = _faces(step)
    P = E * (b ** 4 / 12) / L ** 2                                             # PL²/EI = 1

    def tip(large):
        s = _run([_body("b", step)], [{"type": "fixed", "body": "b", "faces": [_plane(f, 0, 0)]}],
                 [{"type": "force", "body": "b", "faces": [_plane(f, 0, L)], "vector_n": [0, 0, -P]}],
                 [{"id": "s", "type": "static", "large_deformation": large}], 2.5,
                 probes=[{"id": "tip", "point_mm": [L, b / 2, b / 2]}])
        return s, s["probes"][0]["u_mm"]
    s, u = tip(True)
    assert -u[2] / L == pytest.approx(0.30172, rel=0.01)
    assert -u[0] / L == pytest.approx(0.05643, rel=0.03)
    assert s["nonlinear"]["large_deformation"] and s["nonlinear"]["completed"]
    assert _verdicts(s)["反力平衡"] == "pass"                                   # 力矩按变形后的位置核对
    _s, u0 = tip(False)
    assert -u0[2] / L == pytest.approx(1 / 3, rel=0.01)                         # 小变形：PL³/(3EI) = L/3


# ------------------------------------------------------------------ Hertz 接触（F3 验收表里的题）


def test_hertz_sphere_on_flat(tmp_path):
    _need_fea()
    R, W, d = 5.0, 4.0, 0.05

    def ball(o):
        o.intersect([(3, o.addSphere(0, 0, R, R))], [(3, o.addBox(0, 0, 0, R + 1, R + 1, R))])
    blk = _write(tmp_path / "blk.step", lambda o: o.addBox(0, 0, -W, W, W, W))
    bal = _write(tmp_path / "ball.step", ball)
    fb, fs = _faces(blk), _faces(bal)
    sph = next(x["id"] for x in fs if x["kind"] == "sphere")
    sup = [{"type": "symmetry", "body": n, "faces": [_plane(f, ax, 0)]} for n, f in (("blk", fb), ("ball", fs)) for ax in (0, 1)]
    sup += [{"type": "fixed", "body": "blk", "faces": [_plane(fb, 2, -W)]},
            {"type": "displacement", "body": "ball", "faces": [_plane(fs, 2, R)], "uz_mm": -d}]
    s = _run([_body("blk", blk), _body("ball", bal)], sup, [], [{"id": "s", "type": "static"}], 0.5,
             connections=[{"type": "contact", "a": {"body": "ball", "faces": [sph]}, "b": {"body": "blk", "faces": [_plane(fb, 2, 0)]}}])
    F = 4 * abs(next(r for r in s["support_reactions"] if r["type"] == "displacement")["force_n"][2])    # 四分之一模型
    es = E / (2 * (1 - NU ** 2))
    a = (3 * F * R / (4 * es)) ** (1 / 3)
    assert s["contact"]["max_pressure_mpa"] == pytest.approx(3 * F / (2 * math.pi * a * a), rel=0.05)
    assert _verdicts(s)["反力平衡"] == "pass"
