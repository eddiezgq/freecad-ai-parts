"""有限元 F2（ADR-0093 补充二）：边界与载荷补齐，NAFEMS 线弹性标准题。不联网、不调用 LLM。

参考值与出处：
- NAFEMS LE1 椭圆膜（平面应力）：内椭圆 (x/2)² + y² = 1、外椭圆 (x/3.25)² + (y/2.75)² = 1（m），厚 0.1 m，E = 210 GPa、ν = 0.3，
  外边向外拉 10 MPa，AB（x = 0）ux = 0、CD（y = 0）uy = 0；D (2, 0) 处 σyy = 92.7 MPa。
  出处：NAFEMS《The Standard NAFEMS Benchmarks》TNSB Rev. 3（1990）LE1；几何与边界按 Ansys 验证手册 VMFEBSTALE1、
  COMSOL “Elliptic Membrane” 模型说明（后者给出解析参考 92.65817 MPa，出自 Davies、Fenner、Lewis《Background to Benchmarks》NAFEMS 1993）。
- NAFEMS LE10 厚板受压：同样的椭圆环，厚 0.6 m，上表面 1 MPa 压力；DCD′C′ uy = 0、ABA′B′ ux = 0、外椭圆面 BCB′C′ ux = uy = 0、
  外椭圆面中面线 EE′ uz = 0；D (2, 0, 0.3) 处 σyy = −5.38 MPa。出处：NAFEMS TNSB Rev. 3 LE10；几何与边界按 Abaqus 基准手册 LE10、
  COMSOL “Thick Plate” 模型说明（引 Background to Benchmarks 第 77 页）、seamplex Fino 案例 012。
- 自重悬臂：δ = qL⁴ / (8EI)，q = ρgA（材料力学）。
- 强制位移拉杆：σ = Eδ/L，反力 = σA。
- 自由热膨胀：u = αΔT·L，应力为 0。
- 旋转实心薄圆盘中心：σr = σθ = (3 + ν)/8 · ρω²R²（Timoshenko & Goodier，旋转圆盘）。
- 弹性地基上的块：沉降 = p/k + pH/E。
- 远端载荷：悬臂端部力 F 加力矩 M = (Q − C) × F：δ = FL³/(3EI) + ML²/(2EI)。
- 轴承载荷：合力正好是给定的力，且只加在受压的半圈。
"""

from __future__ import annotations

import math

import pytest

import analysis
from analysis.fea import trust as T
from tests.test_fea_bench import _faces, _need_fea, _plane, _write

STEEL = "45-QT"          # E = 210 GPa、ν = 0.3、ρ = 7850、α = 1.12e-5（材料库）


def _run(step, supports, loads, size, **kw):
    st = {"format": "fea-study/1", "name": "f2", "bodies": [{"id": "b1", "step_path": step, "material": STEEL}],
          "supports": supports, "loads": loads, "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": size},
          "checks": {"convergence": False}}
    st.update(kw)
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["steps"][0]
    assert s["balance"]["force_error_ratio"] < 1e-3 and s["balance"]["moment_error_ratio"] < 1e-3, s["balance"]
    return s


def _probe(s, pid):
    return next(p for p in s["probes"] if p["id"] == pid)


def _sym(f, axis, value=0.0):
    return {"type": "symmetry", "body": "b1", "faces": [_plane(f, axis, value)]}


def _mat():
    from analysis.common import materials
    return materials.get(STEEL)


def test_faces_lists_edges(tmp_path):
    _need_fea()
    step = _write(tmp_path / "b.step", lambda o: o.addBox(0, 0, 0, 10, 20, 30))
    d = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]
    assert len(d["edges"]) == 12 and {e["kind"] for e in d["edges"]} == {"line"}
    assert sorted(round(e["length_mm"]) for e in d["edges"]) == [10] * 4 + [20] * 4 + [30] * 4


def test_prescribed_displacement_bar_and_symmetry(tmp_path):
    _need_fea()
    step = _write(tmp_path / "bar.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    f = _faces(step)
    s = _run(step, [_sym(f, 0), _sym(f, 1), _sym(f, 2),
                    {"type": "displacement", "body": "b1", "faces": [_plane(f, 0, 100)], "ux_mm": 0.1}], [], 5.0,
             probes=[{"id": "mid", "point_mm": [50, 5, 5]}])
    E = _mat()["elastic_modulus_mpa"]
    p = _probe(s, "mid")
    assert p["stress_mpa"]["xx"] == pytest.approx(E * 0.1 / 100, rel=1e-4)
    assert abs(p["stress_mpa"]["yy"]) < 1e-3 and abs(p["stress_mpa"]["zz"]) < 1e-3
    pull = next(r for r in s["support_reactions"] if r["type"] == "displacement")
    assert pull["force_n"][0] == pytest.approx(E * 0.1 / 100 * 100, rel=1e-4)                  # 反力 = σA


def test_free_thermal_expansion(tmp_path):
    _need_fea()
    step = _write(tmp_path / "blk.step", lambda o: o.addBox(0, 0, 0, 100, 40, 20))
    f = _faces(step)
    s = _run(step, [_sym(f, 0), _sym(f, 1), _sym(f, 2)],
             [{"type": "temperature", "body": "b1", "delta_t_k": 100}], 8.0,
             probes=[{"id": "corner", "point_mm": [100, 40, 20]}])
    a = _mat()["thermal_expansion_per_k"]
    assert _probe(s, "corner")["u_mm"] == pytest.approx([a * 100 * 100, a * 100 * 40, a * 100 * 20], rel=1e-6)
    assert s["vm_peak_all_mpa"] < 1e-3


def test_gravity_cantilever(tmp_path):
    _need_fea()
    L, h = 200.0, 20.0
    step = _write(tmp_path / "c.step", lambda o: o.addBox(0, 0, 0, L, h, h))
    f = _faces(step)
    s = _run(step, [{"type": "fixed", "body": "b1", "faces": [_plane(f, 0, 0)]}],
             [{"type": "gravity", "body": "b1", "acceleration_m_s2": [0, 0, -9810]}], 5.0,      # 1000 g，变形大些好读
             probes=[{"id": "tip", "point_mm": [L, h / 2, h / 2]}])
    m = _mat()
    rho = m["density_kg_m3"] * 1e-12
    g = 9810e3
    q = rho * g * h * h
    EI = m["elastic_modulus_mpa"] * h ** 4 / 12
    assert -_probe(s, "tip")["u_mm"][2] == pytest.approx(q * L ** 4 / (8 * EI), rel=0.03)
    assert s["body_force_n"][2] == pytest.approx(-q * L, rel=1e-6)
    assert s["balance"]["reaction_n"][2] == pytest.approx(q * L, rel=1e-6)


def test_rotating_disk_centre_stress(tmp_path):
    _need_fea()
    R, t = 100.0, 2.0
    step = _write(tmp_path / "disk.step", lambda o: o.addCylinder(0, 0, 0, 0, 0, t, R))
    f = _faces(step)
    rim = next(x["id"] for x in f if x["kind"] == "cylinder")
    ax = {"origin_mm": [0, 0, 0], "dir": [0, 0, 1]}
    s = _run(step, [{"type": "cyl_support", "body": "b1", "faces": [rim], "axis": ax, "dofs": ["tangential"]}, _sym(f, 2)],
             [{"type": "centrifugal", "body": "b1", "speed_rpm": 10000, "axis": ax}], 6.0,
             probes=[{"id": "c", "point_mm": [0, 0, 0]}])
    m = _mat()
    w = 10000 * 2 * math.pi / 60
    ref = (3 + m["poisson_ratio"]) / 8 * m["density_kg_m3"] * 1e-12 * w * w * R * R
    p = _probe(s, "c")
    assert p["stress_mpa"]["xx"] == pytest.approx(ref, rel=0.02)
    assert p["stress_mpa"]["yy"] == pytest.approx(ref, rel=0.02)
    assert s["body_force_n"] == pytest.approx([0, 0, 0], abs=1e-6 * ref * R * R)


def test_block_on_elastic_foundation(tmp_path):
    _need_fea()
    step = _write(tmp_path / "f.step", lambda o: o.addBox(0, 0, 0, 50, 50, 20))
    f = _faces(step)
    k, p = 10.0, 1.0
    s = _run(step, [{"type": "elastic_support", "body": "b1", "faces": [_plane(f, 2, 0)], "stiffness_n_per_mm3": k}],
             [{"type": "pressure", "body": "b1", "faces": [_plane(f, 2, 20)], "value_mpa": p}], 5.0,
             probes=[{"id": "top", "point_mm": [25, 25, 20]}])
    ref = p / k + p * 20 / _mat()["elastic_modulus_mpa"]
    assert -_probe(s, "top")["u_mm"][2] == pytest.approx(ref, rel=0.01)
    assert s["balance"]["reaction_n"][2] == pytest.approx(p * 50 * 50, rel=1e-6)


def test_remote_load_equals_tip_force_plus_moment(tmp_path):
    _need_fea()
    L, h = 100.0, 10.0
    step = _write(tmp_path / "r.step", lambda o: o.addBox(0, 0, 0, L, h, h))
    f = _faces(step)
    s = _run(step, [{"type": "fixed", "body": "b1", "faces": [_plane(f, 0, 0)]}],
             [{"type": "remote_load", "body": "b1", "faces": [_plane(f, 0, L)], "point_mm": [3 * L, h / 2, h / 2],
               "force_n": [0, 0, -100]}], 2.5, probes=[{"id": "tip", "point_mm": [L, h / 2, h / 2]}])
    EI = _mat()["elastic_modulus_mpa"] * h ** 4 / 12
    F, M = 100.0, 100.0 * 2 * L
    assert -_probe(s, "tip")["u_mm"][2] == pytest.approx(F * L ** 3 / (3 * EI) + M * L ** 2 / (2 * EI), rel=0.03)
    assert s["applied_force_n"] == pytest.approx([0, 0, -100], abs=1e-6)


def test_bearing_load_resultant_and_half_circle(tmp_path):
    _need_fea()

    def build(o):
        o.cut([(3, o.addBox(-40, -40, 0, 80, 80, 20))], [(3, o.addCylinder(0, 0, 0, 0, 0, 20, 15))])
    step = _write(tmp_path / "h.step", build)
    f = _faces(step)
    bore = next(x["id"] for x in f if x["kind"] == "cylinder")
    s = _run(step, [{"type": "fixed", "body": "b1", "faces": [_plane(f, 1, -40)]}],
             [{"type": "bearing_load", "body": "b1", "faces": [bore], "force_n": [0, 2000, 0],
               "axis": {"origin_mm": [0, 0, 0], "dir": [0, 0, 1]}}], 4.0)
    assert s["applied_force_n"] == pytest.approx([0, 2000, 0], abs=2000 * 1e-6)


def _ellipse_ring(o, thick, z0=0.0):
    """NAFEMS LE1 / LE10 的四分之一椭圆环（mm）"""
    outer = o.addDisk(0, 0, 0, 3250, 2750)
    inner = o.addDisk(0, 0, 0, 2000, 1000)
    ring, _ = o.cut([(2, outer)], [(2, inner)])
    q = o.addRectangle(0, 0, 0, 4000, 4000)
    quarter, _ = o.intersect(ring, [(2, q)])
    o.translate(quarter, 0, 0, z0)
    return o.extrude(quarter, 0, 0, thick)


def test_nafems_le1_elliptic_membrane(tmp_path):
    _need_fea()

    def build(o):
        _ellipse_ring(o, 50.0)                         # 板厚 100 mm，取一半，z = 0 为对称面
    step = _write(tmp_path / "le1.step", build)
    f = _faces(step)
    cyl = [x for x in f if x["kind"] != "plane"]
    outer = max(cyl, key=lambda x: math.hypot(*x["center"][:2]))["id"]
    inner = min(cyl, key=lambda x: math.hypot(*x["center"][:2]))["id"]
    s = _run(step, [_sym(f, 0), _sym(f, 1), _sym(f, 2)],
             [{"type": "pressure", "body": "b1", "faces": [outer], "value_mpa": -10.0}], 60.0,
             mesh={"size_mm": 60.0, "refine_faces": [inner]}, probes=[{"id": "D", "point_mm": [2000, 0, 25]}])
    assert _probe(s, "D")["stress_mpa"]["yy"] == pytest.approx(92.7, rel=0.01)          # 实得 92.76（+0.06 %）
    assert not s["mesh_quality"]["straight_sided"]


def test_nafems_le10_thick_plate(tmp_path):
    _need_fea()

    def build(o):
        lo = _ellipse_ring(o, 300.0, z0=-300.0)
        hi = _ellipse_ring(o, 300.0, z0=0.0)
        o.fragment([v for v in lo if v[0] == 3], [v for v in hi if v[0] == 3])   # 中面分开，外椭圆面上留出中面线 EE′
    step = _write(tmp_path / "le10.step", build)
    f = _faces(step)
    d = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]
    curved = [x for x in f if x["kind"] != "plane"]
    outer = [x["id"] for x in curved if math.hypot(*x["center"][:2]) > 2600]
    top = _plane(f, 2, 300)
    ee = [e["id"] for e in d["edges"] if abs(e["center"][2]) < 1e-6 and e["kind"] != "line"
          and math.hypot(*e["center"][:2]) > 2600]
    assert len(outer) == 2 and ee                                  # 外椭圆面在中面分成上下两块，中面线 EE′ 可能分成几段
    y0 = [x["id"] for x in f if x["kind"] == "plane" and abs(x["center"][1]) < 1e-6]
    x0 = [x["id"] for x in f if x["kind"] == "plane" and abs(x["center"][0]) < 1e-6]
    s = _run(step, [{"type": "symmetry", "body": "b1", "faces": y0}, {"type": "symmetry", "body": "b1", "faces": x0},
                    {"type": "displacement", "body": "b1", "faces": outer, "ux_mm": 0, "uy_mm": 0},
                    {"type": "displacement", "body": "b1", "edges": ee, "uz_mm": 0}],
             [{"type": "pressure", "body": "b1", "faces": [top], "value_mpa": 1.0}], 120.0,
             mesh={"size_mm": 120.0}, probes=[{"id": "D", "point_mm": [2000, 0, 300]}])
    syy = _probe(s, "D")["stress_mpa"]["yy"]
    assert syy == pytest.approx(-5.38, rel=0.02), syy                       # 实得 −5.384（4.1 万个单元）


def test_le1_convergence_check_passes(tmp_path):
    _need_fea()
    step = _write(tmp_path / "le1c.step", lambda o: _ellipse_ring(o, 50.0))
    f = _faces(step)
    cyl = [x for x in f if x["kind"] != "plane"]
    outer = max(cyl, key=lambda x: math.hypot(*x["center"][:2]))["id"]
    st = {"format": "fea-study/1", "name": "le1", "bodies": [{"id": "b1", "step_path": step, "material": STEEL}],
          "supports": [_sym(f, 0), _sym(f, 1), _sym(f, 2)],
          "loads": [{"type": "pressure", "body": "b1", "faces": [outer], "value_mpa": -10.0}],
          "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 80.0}}
    s = analysis.run("fea", st)["data"]["steps"][0]
    assert s["trust"]["verdict"] == T.PASS, s["trust"]["items"]
