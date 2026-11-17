"""壳单元与梁单元（ADR-0095）：与解析解对照的标准题，加核查与语义规则。

对照（ADR-0095 第 4 节）：
- 悬臂梁端部集中力：端部挠度 PL³/(3EI)（Euler–Bernoulli）；B32 计入剪切变形，与 Timoshenko 梁 PL³/(3EI) + PL/(κGA) 比
  （矩形 κ = 5/6）；根部弯曲应力 PL·c/I。
- 悬臂梁自重：端部挠度 wL⁴/(8EI)。
- 悬臂梁第一阶固有频率 (1.875104²/L²)·√(EI/(ρA))（Euler–Bernoulli）。
- 四边简支方板受均布压力：中点挠度 α·q·a⁴/D、中点板面应力 6·β·q·a²/t²，α = 0.00406、β = 0.0479（ν = 0.3，
  Timoshenko、Woinowsky-Krieger《Theory of Plates and Shells》第 5 章表）；第一阶频率 (π/2)·(2/a²)·√(D/(ρt))。
"""

from __future__ import annotations

import math

import pytest

from tests.test_fea_bench import _need_fea, _write

MAT = "45-QT"


def _mat():
    from analysis.common import materials

    return materials.get(MAT)


def _beam_step(tmp_path, L=200.0):
    return _write(tmp_path / "beam.step", lambda o: o.addLine(o.addPoint(0, 0, 0), o.addPoint(L, 0, 0)))


def _plate_step(tmp_path, a=200.0):
    return _write(tmp_path / "plate.step", lambda o: o.addRectangle(0, 0, 0, a, a))


def _beam(step, section, loads, steps=None, size=10.0):
    return {"format": "fea-study/1", "name": "beam", "bodies": [{"id": "b", "step_path": step, "material": MAT, "kind": "beam",
                                                                  "section": section}],
            "supports": [{"type": "fixed", "body": "b", "vertices": [1]}], "loads": loads,
            "steps": steps or [{"id": "s1", "type": "static"}], "mesh": {"size_mm": size}}


RECT = {"shape": "rect", "width_mm": 10.0, "height_mm": 20.0, "orientation": [0.0, 1.0, 0.0]}     # 高 20 沿 z
CIRC = {"shape": "circle", "diameter_mm": 20.0}
PIPE = {"shape": "pipe", "outer_diameter_mm": 30.0, "wall_mm": 3.0}


@pytest.mark.parametrize("section", [RECT, CIRC, PIPE], ids=["rect", "circle", "pipe"])
def test_cantilever_tip_load(tmp_path, section):
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.structural import section_props

    m = _mat()
    E, nu = m["elastic_modulus_mpa"], m["poisson_ratio"]
    L, Pn = 200.0, 100.0
    r = run_study(_beam(_beam_step(tmp_path, L), section, [{"type": "force", "body": "b", "vertices": [2], "vector_n": [0, 0, -Pn]}]))
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["steps"][0]
    sp = section_props(section)
    I = sp["i1_mm4"]                                                  # 绕局部 1 轴（y）弯：高度沿 z
    c = (section.get("height_mm") or section.get("diameter_mm") or section.get("outer_diameter_mm")) / 2
    eb = Pn * L ** 3 / (3 * E * I)
    assert s["u_max_mm"] == pytest.approx(eb, rel=0.025)             # Euler–Bernoulli：差的主要是剪切变形（短粗梁）
    if section is RECT:                                               # Timoshenko 梁（矩形截面剪切系数 κ = 5/6）
        shear = Pn * L / (5 / 6 * E / (2 * (1 + nu)) * sp["area_mm2"])
        assert s["u_max_mm"] == pytest.approx(eb + shear, rel=0.005)
    # 求解器展开截面的取点使最大应力比外缘理论值偏低：矩形约 1 %、管约 3 %（写进了局限，不许再变差）
    th = Pn * L * c / I
    assert th * {"rect": 0.98, "circle": 0.99, "pipe": 0.96}[section["shape"]] <= s["vm_max_mpa"] <= th * 1.01
    assert s["vm_max_at"][0] <= 10.0 + 1e-6                          # 最大应力在根部第一个单元（展开节点取在积分点外推处）
    if section is PIPE:            # 管截面三层网格的最大应力有小幅来回（< 1 %），按规则判“未知”，安全系数不给
        assert s["trust"]["verdict"] in ("pass", "unknown")
    else:
        assert s["trust"]["verdict"] == "pass", s["trust"]
    if s["trust"]["verdict"] == "pass":
        assert s["safety_factor"] == pytest.approx(m["yield_strength_mpa"] / s["vm_max_mpa"], rel=1e-3)
    else:
        assert s["safety_factor"] is None and s["safety_factor_withheld"]


def test_cantilever_self_weight_and_first_frequency(tmp_path):
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.structural import section_props

    m = _mat()
    E, rho = m["elastic_modulus_mpa"], m["density_kg_m3"] * 1e-12
    L = 1000.0                                                        # 细长：剪切影响小
    sp = section_props(RECT)
    st = _beam(_beam_step(tmp_path, L), RECT, [{"type": "gravity", "body": "b", "acceleration_m_s2": [0, 0, -9.80665]}],
               steps=[{"id": "s1", "type": "static"}, {"id": "m1", "type": "modal", "n_modes": 2}], size=25.0)
    r = run_study(st)
    assert r["status"] == "ok", r["messages"]
    w = rho * sp["area_mm2"] * 9806.65                                # N/mm
    assert r["data"]["steps"][0]["u_max_mm"] == pytest.approx(w * L ** 4 / (8 * E * sp["i1_mm4"]), rel=0.01)
    bal = r["data"]["steps"][0]["balance"]
    assert bal["applied_n"][2] == pytest.approx(-w * L, rel=1e-6)
    f_weak = 1.875104 ** 2 / L ** 2 * math.sqrt(E * sp["i2_mm4"] / (rho * sp["area_mm2"])) / (2 * math.pi)
    assert r["data"]["steps"][1]["freqs"][0]["hz"] == pytest.approx(f_weak, rel=0.01)


def _plate(step, t, q, steps=None, size=20.0):
    return {"format": "fea-study/1", "name": "plate",
            "bodies": [{"id": "p", "step_path": step, "material": MAT, "kind": "shell", "thickness_mm": t}],
            "supports": [{"type": "displacement", "body": "p", "edges": [1, 2, 3, 4], "ux_mm": 0, "uy_mm": 0, "uz_mm": 0}],
            "loads": [{"type": "pressure", "body": "p", "faces": [1], "value_mpa": q}],
            "steps": steps or [{"id": "s1", "type": "static"}], "mesh": {"size_mm": size}}


def test_simply_supported_plate(tmp_path):
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.solve import read_frd
    from analysis.fea.structural import _frd_nodes

    m = _mat()
    E, nu, rho = m["elastic_modulus_mpa"], m["poisson_ratio"], m["density_kg_m3"] * 1e-12
    assert nu == pytest.approx(0.3)                                   # 表里的系数是 ν = 0.3 的
    a, t, q = 200.0, 2.0, 0.01
    D = E * t ** 3 / (12 * (1 - nu ** 2))
    keep = tmp_path / "keep"
    r = run_study(_plate(_plate_step(tmp_path, a), t, q, steps=[{"id": "s1", "type": "static"}, {"id": "m1", "type": "modal",
                                                                                                "n_modes": 1}]), keep_dir=str(keep))
    assert r["status"] == "ok", r["messages"]
    s = r["data"]["steps"][0]
    assert s["u_max_mm"] == pytest.approx(0.00406 * q * a ** 4 / D, rel=0.02)
    assert s["u_max_at"][:2] == pytest.approx([100, 100], abs=1.0)
    disp, stress = read_frd(keep / "s1" / "job.frd")
    X = _frd_nodes(keep / "s1" / "job.frd")
    top = [n for n, x in X.items() if abs(x[2] - t / 2) < 1e-6]
    bot = [n for n, x in X.items() if abs(x[2] + t / 2) < 1e-6]
    near = lambda ns: min(ns, key=lambda n: (X[n][0] - 100) ** 2 + (X[n][1] - 100) ** 2)
    center = [near(top), near(bot)]
    assert all(abs(X[n][0] - 100) < 5 and abs(X[n][1] - 100) < 5 for n in center), "中点附近上下表面的展开节点"
    assert disp[center[0]][2] < 0                                     # 正压力沿法向（+z）的反方向压
    for n in center:
        assert abs(stress[n][0]) == pytest.approx(6 * 0.0479 * q * a ** 2 / t ** 2, rel=0.03)
    items = {i["name"]: i["verdict"] for i in s["trust"]["items"]}
    assert items["反力平衡"] == "pass" and items["网格收敛（最大位移）"] == "pass"
    # 四边铰支方板的角点：最大应力随网格加密一直增大——程序判“疑似奇异点”，不给安全系数
    assert items["网格收敛（最大应力）"] == "fail" and s["safety_factor"] is None
    f11 = math.pi / 2 * (2 / a ** 2) * math.sqrt(D / (rho * t))
    assert r["data"]["steps"][1]["freqs"][0]["hz"] == pytest.approx(f11, rel=0.02)


def test_shell_beam_rules():
    from analysis.fea.study import StudyInvalid, validate

    base = _beam("x.step", RECT, [{"type": "force", "body": "b", "vertices": [2], "vector_n": [0, 0, -1]}])
    validate(base)
    bad = [
        ({"loads": [{"type": "pressure", "body": "b", "faces": [1], "value_mpa": 1}]}, "梁没有面"),
        ({"steps": [{"id": "x", "type": "buckling"}]}, "静力与模态"),
        ({"supports": [{"type": "symmetry", "body": "b", "faces": [1]}]}, "固定"),
        ({"loads": [{"type": "torque", "body": "b", "faces": [1], "value_nm": 1, "axis": {"origin_mm": [0, 0, 0], "dir": [1, 0, 0]}}]},
         "力、压力、重力"),
    ]
    for patch, why in bad:
        with pytest.raises(StudyInvalid, match=why):
            validate({**base, **patch})
    two = {**base, "bodies": base["bodies"] + [{"id": "c", "step_path": "y.step", "material": MAT}]}
    with pytest.raises(StudyInvalid, match="单独一个实体"):
        validate(two)
    shell = _plate("p.step", 2, 0.1)
    validate(shell)
    with pytest.raises(StudyInvalid, match="不认顶点"):
        validate({**shell, "supports": [{"type": "fixed", "body": "p", "vertices": [1]}]})
    solid = {"format": "fea-study/1", "name": "s", "bodies": [{"id": "s", "step_path": "s.step", "material": MAT}],
             "supports": [{"type": "fixed", "body": "s", "edges": [1]}], "loads": [], "steps": [{"id": "s1", "type": "static"}]}
    with pytest.raises(StudyInvalid, match="实体单元"):
        validate(solid)


def test_faces_reports_geometry_kind_and_vertices(tmp_path):
    _need_fea()
    from analysis.fea.geometry import faces

    _f, info = faces(_beam_step(tmp_path))
    assert info["geometry_kind"] == "beam" and [v["point"] for v in info["vertex_list"]] == [[0, 0, 0], [200, 0, 0]]
    _f, info = faces(_plate_step(tmp_path))
    assert info["geometry_kind"] == "shell" and len(info["edge_list"]) == 4


def test_beam_report_numbers_trace(tmp_path):
    """壳、梁的结果也能出报告，报告里的数字照样逐个对回文件"""
    _need_fea()
    import json

    from analysis.common import materials
    from analysis.fea import run_study
    from assist import fea_report as R
    from tests.test_assist_fea_report import _docx_text, _trace

    st = _beam(_beam_step(tmp_path), RECT, [{"type": "force", "body": "b", "vertices": [2], "vector_n": [0, 0, -100]}])
    res = run_study(st)
    sp = tmp_path / "study.json"
    sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    got = R.build(st, res, tmp_path / "rep.docx", number="QR-B-1", study_path=sp)
    ledger = json.loads(got["ledger"].read_text(encoding="utf-8"))
    record = json.loads(got["record"].read_text(encoding="utf-8"))
    env = {"code": R.code_version(), "gmsh": R.gmsh_version(), "solver": f"{res['solver']['name']} {res['solver']['version']}",
           "module": f"fea {res['module_version']}"}
    sources = {"study": st, "result": res, "materials": {"materials": {MAT: materials._table()[MAT]}}, "record": record,
               "files": ledger["files"], "env": env, "library": [], "explain": {}}
    text = _docx_text(got["docx"])
    assert "最大应力（MPa）" in text
    _trace(text, ledger, sources)



def test_frame_segments_are_joined(tmp_path):
    """L 形框架（ADR-0096 第 1 步）：立柱、横梁在 STEP 里是两段各自的线（相接处的点有两份），读入时合并成一个点，框架连成一体。
    立柱底固定、横梁端部受竖向力 P（不计轴向、剪切变形）：
    竖向位移 = Pa³/(3EI) + Pa²h/(EI)（横梁弯曲 + 立柱顶转角带动），水平位移 = Pa·h²/(2EI)（立柱受弯矩 Pa 侧移），合位移相差 < 3 %"""
    _need_fea()
    from analysis.fea import run_study
    from analysis.fea.geometry import faces

    h, a, P = 400.0, 300.0, 500.0

    def build(o):
        o.addLine(o.addPoint(0, 0, 0), o.addPoint(0, 0, h))
        o.addLine(o.addPoint(0, 0, h), o.addPoint(a, 0, h))

    step = _write(tmp_path / "frame.step", build)
    verts = faces(step)[1]["vertex_list"]
    assert len(verts) == 3                                                   # 合并后：柱底、角点、横梁端
    base = next(v["id"] for v in verts if v["point"] == [0.0, 0.0, 0.0])
    tip = next(v["id"] for v in verts if v["point"] == [a, 0.0, h])
    study = {"format": "fea-study/1", "name": "frame",
             "bodies": [{"id": "b", "step_path": step, "material": MAT, "kind": "beam", "section": PIPE}],
             "supports": [{"type": "fixed", "body": "b", "vertices": [base]}],
             "loads": [{"type": "force", "body": "b", "vertices": [tip], "vector_n": [0, 0, -P]}],
             "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": 10.0}, "checks": {"convergence": False}}
    r = run_study(study)
    assert r["status"] == "ok", r["messages"]
    E = _mat()["elastic_modulus_mpa"]
    do, t = PIPE["outer_diameter_mm"], PIPE["wall_mm"]
    EI = E * math.pi * (do ** 4 - (do - 2 * t) ** 4) / 64
    v = P * a ** 3 / (3 * EI) + P * a ** 2 * h / EI
    u = P * a * h ** 2 / (2 * EI)
    assert r["data"]["steps"][0]["u_max_mm"] == pytest.approx(math.hypot(v, u), rel=0.03)
