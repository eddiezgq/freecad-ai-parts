"""有限元 F3（ADR-0093 补充四）：多个实体、绑定、接触、螺栓预紧。不联网、不调用 LLM。

参考值与出处：
- 绑定的两块拉杆：网格不一致的两块绑在一起，与一整根杆相同：σ = F/A、伸长 = σL/E（材料力学）。
- 过盈配合（同材料两环，平面应力，Lamé）：接触压力 p = E·δ/b · (b² − a²)(c² − b²) / (2b²(c² − a²))，
  内环内壁 σθ = −2pb²/(b² − a²)、外环外壁 σθ = 2pb²/(c² − b²)（δ 为半径过盈量；Timoshenko & Goodier《弹性理论》厚壁圆筒一节）。
- 摩擦滑动：滑动时切向力 = μN（库仑摩擦）。
- 螺栓预紧（两端固定的杆）：截面拉力 = 预紧力、σ = F/A。
- 螺栓连接受外载（连接件受力图，VDI 2230 的基本关系）：螺栓力 = F₀ + Φ·P，Φ = k_b / (k_b + k_c)，k = EA/L（被连接件与螺栓并联、
  两端刚性连接时成立；顶板做成 30 mm 厚近似刚性，容差 5 %）。
"""

from __future__ import annotations

import math

import pytest

import analysis
from tests.test_fea_bench import _faces, _need_fea, _plane, _write

STEEL = "45-QT"


def _mat():
    from analysis.common import materials
    return materials.get(STEEL)


def _study(bodies, supports, loads, connections, size, **kw):
    st = {"format": "fea-study/1", "name": "f3",
          "bodies": [{"id": i, "step_path": p, "material": STEEL} for i, p in bodies],
          "supports": supports, "loads": loads, "connections": connections,
          "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": size}, "checks": {"convergence": False}}
    st.update(kw)
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["steps"][0]
    bal = next(x for x in s["trust"]["items"] if x["name"] == "反力平衡")
    assert bal["verdict"] == "pass", bal                  # 力和力矩都平衡（有接触时力矩按变形后的位置算）
    return s


def _probe(s, pid):
    return next(p for p in s["probes"] if p["id"] == pid)


def _sym(body, f, axis, value=0.0):
    return {"type": "symmetry", "body": body, "faces": [_plane(f, axis, value)]}


def test_bonded_bars_with_mismatched_meshes(tmp_path):
    _need_fea()
    a = _write(tmp_path / "a.step", lambda o: o.addBox(0, 0, 0, 50, 20, 20))
    b = _write(tmp_path / "b.step", lambda o: o.addBox(50, 0, 0, 50, 20, 20))
    fa, fb = _faces(a), _faces(b)
    sig = 50.0
    s = _study([("A", a), ("B", b)],
               [_sym("A", fa, 0), _sym("A", fa, 1), _sym("A", fa, 2), _sym("B", fb, 1), _sym("B", fb, 2)],
               [{"type": "force", "body": "B", "faces": [_plane(fb, 0, 100)], "vector_n": [sig * 400, 0, 0]}],
               [{"type": "bonded", "a": {"body": "B", "faces": [_plane(fb, 0, 50)]}, "b": {"body": "A", "faces": [_plane(fa, 0, 50)]}}],
               7.0, probes=[{"id": "pa", "point_mm": [25, 10, 10]}, {"id": "pb", "point_mm": [75, 10, 10]},
                            {"id": "tip", "point_mm": [100, 10, 10]}])
    assert _probe(s, "pa")["stress_mpa"]["xx"] == pytest.approx(sig, rel=0.005)
    assert _probe(s, "pb")["stress_mpa"]["xx"] == pytest.approx(sig, rel=0.005)
    assert _probe(s, "tip")["u_mm"][0] == pytest.approx(sig * 100 / _mat()["elastic_modulus_mpa"], rel=0.005)
    assert {x["id"] for x in s["bodies"]} == {"A", "B"} and all(x["safety_factor"] > 0 for x in s["bodies"])
    assert s["safety_factor"] is None                     # 没做网格收敛核查：可信度“未知”，不给总的安全系数


def _quarter_ring(o, r1, r2, length):
    c = o.addCylinder(0, 0, 0, 0, 0, length, r2)
    o.cut([(3, c)], [(3, o.addCylinder(0, 0, -1, 0, 0, length + 2, r1))])
    o.intersect([(3, c)], [(3, o.addBox(0, 0, -1, r2 + 1, r2 + 1, length + 2))])


def test_press_fit_contact_pressure(tmp_path):
    _need_fea()
    a, b, c, delta, th = 10.0, 20.0, 40.0, 0.02, 0.7
    inner = _write(tmp_path / "in.step", lambda o: _quarter_ring(o, a, b + delta, 10))
    outer = _write(tmp_path / "out.step", lambda o: _quarter_ring(o, b, c, 10))
    fi, fo = _faces(inner), _faces(outer)
    cyl_i = max((x for x in fi if x["kind"] == "cylinder"), key=lambda x: x["radius_mm"])["id"]
    cyl_o = min((x for x in fo if x["kind"] == "cylinder"), key=lambda x: x["radius_mm"])["id"]
    sup = [_sym(n, f, ax) for n, f in (("I", fi), ("O", fo)) for ax in (0, 1, 2)]
    s = _study([("I", inner), ("O", outer)], sup, [],
               [{"type": "contact", "a": {"body": "I", "faces": [cyl_i]}, "b": {"body": "O", "faces": [cyl_o]}}], 2.0,
               probes=[{"id": "in", "point_mm": [a * math.cos(th), a * math.sin(th), 5]},
                       {"id": "out", "point_mm": [c * math.cos(th), c * math.sin(th), 5]}])
    E = _mat()["elastic_modulus_mpa"]
    p = E * delta / b * (b * b - a * a) * (c * c - b * b) / (2 * b * b * (c * c - a * a))

    def hoop(pid):
        pr = _probe(s, pid)["stress_mpa"]
        return pr["xx"] * math.sin(th) ** 2 + pr["yy"] * math.cos(th) ** 2 - 2 * pr["xy"] * math.sin(th) * math.cos(th)
    # 内环内壁 σθ = −2pb²/(b² − a²)，外环外壁 σθ = 2pb²/(c² − b²)：两处都在自由表面上，探针不会取到另一个零件的节点
    assert hoop("in") == pytest.approx(-2 * p * b * b / (b * b - a * a), rel=0.03)
    assert hoop("out") == pytest.approx(2 * p * b * b / (c * c - b * b), rel=0.03)
    assert s["contact"]["max_pressure_mpa"] == pytest.approx(p, rel=0.05)


def test_friction_sliding_force_is_mu_n(tmp_path):
    _need_fea()
    base = _write(tmp_path / "base.step", lambda o: o.addBox(0, 0, 0, 60, 40, 10))
    blk = _write(tmp_path / "blk.step", lambda o: o.addBox(10, 10, 10, 40, 20, 10))
    fb, fk = _faces(base), _faces(blk)
    mu, p = 0.3, 10.0
    s = _study([("base", base), ("blk", blk)],
               [{"type": "fixed", "body": "base", "faces": [_plane(fb, 2, 0)]},
                {"type": "displacement", "body": "blk", "faces": [_plane(fk, 2, 20)], "ux_mm": 0.2, "uy_mm": 0}],
               [{"type": "pressure", "body": "blk", "faces": [_plane(fk, 2, 20)], "value_mpa": p}],
               [{"type": "contact", "a": {"body": "blk", "faces": [_plane(fk, 2, 10)]}, "b": {"body": "base", "faces": [_plane(fb, 2, 10)]},
                 "friction_coefficient": mu}], 4.0)
    pull = next(r for r in s["support_reactions"] if r["type"] == "displacement")
    assert abs(pull["force_n"][0]) == pytest.approx(mu * p * 40 * 20, rel=0.02)


def test_bolt_preload_in_fixed_bar(tmp_path):
    _need_fea()
    step = _write(tmp_path / "bolt.step", lambda o: o.addCylinder(0, 0, 0, 0, 0, 40, 5))
    f = _faces(step)
    F = 10000.0
    s = _study([("bolt", step)], [{"type": "fixed", "body": "bolt", "faces": [_plane(f, 2, 0), _plane(f, 2, 40)]}], [],
               [{"type": "bolt_preload", "body": "bolt", "point_mm": [0, 0, 20], "axis_dir": [0, 0, 1], "force_n": F}], 2.0,
               probes=[{"id": "m", "point_mm": [0, 0, 10]}])
    bolt = s["bolts"][0]
    assert bolt["force_n"] == pytest.approx(F, rel=1e-3)
    assert bolt["section_area_mm2"] == pytest.approx(math.pi * 25, rel=0.02)
    assert _probe(s, "m")["stress_mpa"]["zz"] == pytest.approx(F / (math.pi * 25), rel=0.02)


def test_bolted_joint_load_factor(tmp_path):
    _need_fea()
    L, rb, ri, ro = 40.0, 5.0, 6.0, 10.0
    bolt = _write(tmp_path / "b.step", lambda o: o.addCylinder(0, 0, 0, 0, 0, L, rb))

    def sleeve(o):
        o.cut([(3, o.addCylinder(0, 0, 0, 0, 0, L, ro))], [(3, o.addCylinder(0, 0, -1, 0, 0, L + 2, ri))])
    slv = _write(tmp_path / "s.step", sleeve)
    T = 30.0                                                          # 顶板做厚，近似刚性（公式假定两端刚性连接）
    plate = _write(tmp_path / "p.step", lambda o: o.addBox(-15, -15, L, 30, 30, T))
    fb, fs, fp = _faces(bolt), _faces(slv), _faces(plate)
    F0, Pext = 10000.0, 5000.0
    s = _study([("bolt", bolt), ("sleeve", slv), ("plate", plate)],
               [{"type": "fixed", "body": "bolt", "faces": [_plane(fb, 2, 0)]},
                {"type": "fixed", "body": "sleeve", "faces": [_plane(fs, 2, 0)]}],
               [{"type": "force", "body": "plate", "faces": [_plane(fp, 2, L + T)], "vector_n": [0, 0, Pext]}],
               [{"type": "bonded", "a": {"body": "bolt", "faces": [_plane(fb, 2, L)]}, "b": {"body": "plate", "faces": [_plane(fp, 2, L)]}},
                {"type": "bonded", "a": {"body": "sleeve", "faces": [_plane(fs, 2, L)]}, "b": {"body": "plate", "faces": [_plane(fp, 2, L)]}},
                {"type": "bolt_preload", "id": "M10", "body": "bolt", "point_mm": [0, 0, 20], "axis_dir": [0, 0, 1], "force_n": F0}],
               2.5)
    kb, kc = math.pi * rb ** 2, math.pi * (ro ** 2 - ri ** 2)          # 同材料、同长度：刚度比 = 面积比
    phi = kb / (kb + kc)
    got = s["bolts"][0]["force_n"]
    assert got - F0 == pytest.approx(phi * Pext, rel=0.05), (got, phi)
