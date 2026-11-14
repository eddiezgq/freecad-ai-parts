"""有限元 F1（ADR-0093）：算例模型、可信度核查、标准题。不联网、不调用 LLM。

标准题与参考值：
- 悬臂梁：反力与外载平衡（静力平衡，误差 ≤ 0.1 %）。
- Lamé 厚壁圆筒（两端自由、内压 p）：内壁 σθ = p(b² + a²)/(b² − a²)、σr = −p、σz = 0（Timoshenko & Goodier《Theory of Elasticity》，
  厚壁圆筒一节；两端自由时该解对任意长度都精确），Von Mises 与此比较，容差 2 %。
- Kirsch 圆孔板（单向拉伸）：无限大板孔边最大应力 3σ（Kirsch 1898）；本题板宽 / 孔径 = 20，有限宽使峰值约高 0.2 %
  （Heywood 近似式 Kt_net = 2 + (1 − d/W)³），容差 3 %。
- L 形板内直角（凹角）：线弹性理论上应力无穷大（奇异点），网格越密峰值越大——核查必须判“不收敛”、不给安全系数。
- Richardson / GCI：用已知阶数的人工数列核对公式（Roache 1998；非等比加密按 Celik 等 2008）。
"""

from __future__ import annotations

import math
import os

import pytest

import analysis
from analysis.fea import study as S
from analysis.fea import trust as T

# ---------------------------------------------------------------- 纯函数（不要求求解器）


def test_richardson_recovers_known_order_uniform_and_nonuniform():
    for hs in ([1.0, 0.5, 0.25], [1.0, 0.7, 0.3]):
        f = [10 - 3 * h ** 2 for h in hs]                       # 精确值 10、阶数 2
        rr = T.richardson(f, 2.0, hs)
        assert rr["order_p"] == pytest.approx(2.0, abs=1e-6)
        assert rr["extrapolated"] == pytest.approx(10.0, abs=1e-6)
    rr = T.richardson([10 - 3 * h ** 2 for h in (1.0, 0.5, 0.25)], 2.0)     # 不给尺寸：按等比 r
    assert rr["order_p"] == pytest.approx(2.0) and rr["gci_ratio"] == pytest.approx(1.25 * (3 * 0.1875) / 9.8125 / 3)


def test_convergence_verdicts():
    hs = [1.0, 0.6, 0.36]
    ok = T.convergence([100 - 20 * h ** 2 for h in hs], 1 / 0.6, 0.05, hs=hs)
    assert ok["verdict"] == T.PASS
    sing = T.convergence([100 * h ** -0.5 for h in hs], 1 / 0.6, 0.05, hs=hs)      # 奇异：∝ h^(−1/2)
    assert sing["verdict"] == T.FAIL and "奇异点" in sing["text"]
    osc = T.convergence([100.0, 104.0, 102.0], 1.6, 0.05)
    assert osc["verdict"] == T.PASS and osc["oscillation_ratio"] == pytest.approx(2.0 / 102.0)
    big = T.convergence([100.0, 130.0, 110.0], 1.6, 0.05)
    assert big["verdict"] == T.UNKNOWN
    same = T.convergence([0.2, 0.2001, 0.2002], 1.6, 0.05, "最大位移")
    assert same["verdict"] == T.PASS
    assert T.convergence([1.0, 2.0], 1.6)["verdict"] == T.UNKNOWN


def test_balance_and_quality_and_overall_verdict():
    assert T.balance({"available": True, "force_error_ratio": 1e-6, "moment_error_ratio": 2e-6})["verdict"] == T.PASS
    assert T.balance({"available": True, "force_error_ratio": 0.02, "moment_error_ratio": 0.0})["verdict"] == T.FAIL
    assert T.balance({"available": False})["verdict"] == T.UNKNOWN
    q = {"elements": 1000, "min_sj_min": -0.1, "inverted": 1, "gamma_min": 0.0, "gamma_p01": 0.2, "gamma_below_0_1": 1}
    assert T.mesh_quality(q)["verdict"] == T.FAIL
    q.update(inverted=0, min_sj_min=0.5, gamma_below_0_1=5)
    assert T.mesh_quality(q)["verdict"] == T.UNKNOWN
    q.update(gamma_below_0_1=0)
    assert T.mesh_quality(q)["verdict"] == T.PASS
    assert T.verdict([{"verdict": T.PASS}, {"verdict": T.UNKNOWN}]) == T.UNKNOWN
    assert T.verdict([{"verdict": T.PASS}, {"verdict": T.FAIL}, {"verdict": T.UNKNOWN}]) == T.FAIL
    assert T.verdict([{"verdict": T.PASS}]) == T.PASS


def _study(step="x.step", **kw):
    st = {"format": "fea-study/1", "name": "t", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
          "supports": [{"type": "fixed", "body": "b1", "faces": [1]}],
          "loads": [{"type": "force", "body": "b1", "faces": [2], "vector_n": [0, 0, -100]}],
          "steps": [{"id": "s1", "type": "static"}]}
    st.update(kw)
    return st


def test_study_validation_rules():
    S.validate(_study())
    with pytest.raises(S.StudyInvalid, match="AI 起草"):
        S.validate(_study(provenance={"drafted_by": "ai", "confirmed_by_human": False}))
    S.validate(_study(provenance={"drafted_by": "ai", "confirmed_by_human": True}))
    with pytest.raises(S.StudyInvalid, match="没有实体"):
        S.validate(_study(supports=[{"type": "fixed", "body": "b9", "faces": [1]}]))
    with pytest.raises(S.StudyInvalid, match="载荷"):
        S.validate(_study(loads=[]))
    with pytest.raises(S.StudyInvalid, match="格式"):
        S.validate(_study(steps=[{"id": "s1", "type": "buckling"}]))
    out = analysis.run("fea", _study(provenance={"drafted_by": "ai", "confirmed_by_human": False}))
    assert out["status"] == "failed" and "AI 起草" in out["messages"][0]


def test_legacy_setup_converts_to_same_internal_loads():
    setup = {"step_path": "x.step", "material": "45-QT", "mesh": {"size_mm": 3}, "loads": [
        {"type": "fixed", "faces": [1]},
        {"type": "cyl_support", "faces": [3], "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}, "dofs": ["radial", "axial"], "band_mm": 1},
        {"type": "force", "faces": [2], "vector_n": [0, -1, 0]},
        {"type": "pressure", "faces": [4], "value_mpa": 2.0},
        {"type": "torque", "faces": [5], "value_nm": 35, "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}]}
    st = S.from_setup(setup)
    S.validate(st)
    assert st["checks"] == {"convergence": False}
    inner = S.internal_loads(st)
    from analysis.fea import _internal_loads
    legacy = _internal_loads(setup["loads"])
    key = lambda d: (d["type"], d["faces"])
    assert sorted(inner, key=key) == sorted(legacy, key=key)


# ---------------------------------------------------------------- 求解（要 gmsh + CalculiX）


def _need_fea():
    from analysis.common.solvers import find_ccx
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        assert find_ccx(), "CI 中没有 ccx"
        return
    pytest.importorskip("gmsh")
    pytest.importorskip("scipy")
    if find_ccx() is None:
        pytest.skip("本机没有 CalculiX")


def _write(path, build):
    import gmsh
    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("m")
    build(gmsh.model.occ)
    gmsh.model.occ.synchronize()
    gmsh.write(str(path))
    gmsh.finalize()
    return str(path)


def _faces(step):
    return analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]


def _plane(faces, axis, value):
    return next(f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][axis] - value) < 1e-6)


def _static(step, supports, loads, size, **kw):
    st = {"format": "fea-study/1", "name": "bench", "bodies": [{"id": "b1", "step_path": step, "material": "45-QT"}],
          "supports": supports, "loads": loads, "steps": [{"id": "s1", "type": "static"}], "mesh": {"size_mm": size}}
    st.update(kw)
    r = analysis.run("fea", st)
    assert r["status"] == "ok", r["messages"]
    return r["data"]["steps"][0]


def test_cantilever_balance_and_legacy_trust_block(tmp_path):
    _need_fea()
    step = _write(tmp_path / "box.step", lambda o: o.addBox(0, 0, 0, 100, 10, 10))
    f = _faces(step)
    root, tip = _plane(f, 0, 0), _plane(f, 0, 100)
    s = _static(step, [{"type": "fixed", "body": "b1", "faces": [root]}],
                [{"type": "force", "body": "b1", "faces": [tip], "vector_n": [0, 0, -100]}], 2.5,
                checks={"convergence": False})
    assert s["balance"]["force_error_ratio"] < 1e-3 and s["balance"]["moment_error_ratio"] < 1e-3
    assert s["balance"]["reaction_n"][2] == pytest.approx(100, rel=1e-4)
    assert s["trust"]["verdict"] == T.UNKNOWN and s["safety_factor"] is None          # 没做收敛：不给安全系数
    legacy = analysis.run("fea", {"step_path": step, "material": "45-QT", "mesh": {"size_mm": 2.5},
                                  "loads": [{"type": "fixed", "faces": [root]},
                                            {"type": "force", "faces": [tip], "vector_n": [0, 0, -100]}]})
    d = legacy["data"]
    assert d["safety_factor"] > 0 and "未经网格收敛" in d["safety_factor_note"]          # 旧写法照旧给，附说明
    assert [i["name"] for i in d["trust"]["items"]][:2] == ["反力平衡", "网格质量"]


def test_lame_thick_cylinder(tmp_path):
    _need_fea()
    a, b, p = 25.0, 50.0, 100.0

    def build(o):
        c1, c2 = o.addCylinder(0, 0, 0, 0, 0, 40, b), o.addCylinder(0, 0, 0, 0, 0, 40, a)
        o.cut([(3, c1)], [(3, c2)])
    step = _write(tmp_path / "ring.step", build)
    f = _faces(step)
    cyl = [x for x in f if x["kind"] == "cylinder"]
    inner, outer = min(cyl, key=lambda x: x["radius_mm"])["id"], max(cyl, key=lambda x: x["radius_mm"])["id"]
    ax = {"origin_mm": [0, 0, 0], "dir": [0, 0, 1]}
    # 只消除刚体运动、不引入应力：外圆限切向（不让转、不让平移），一个端面限轴向
    s = _static(step, [{"type": "cyl_support", "body": "b1", "faces": [outer], "axis": ax, "dofs": ["tangential"]},
                       {"type": "cyl_support", "body": "b1", "faces": [_plane(f, 2, 0)], "axis": ax, "dofs": ["axial"]}],
                [{"type": "pressure", "body": "b1", "faces": [inner], "value_mpa": p}], 5.0)
    th = p * (b * b + a * a) / (b * b - a * a)
    vm = math.sqrt(th * th + p * p + th * p)
    assert s["vm_max_mpa"] == pytest.approx(vm, rel=0.02)
    assert s["trust"]["verdict"] == T.PASS, s["trust"]["items"]
    assert s["safety_factor"] == pytest.approx(355 / s["vm_max_mpa"], rel=1e-3)


def test_kirsch_plate_with_hole(tmp_path):
    _need_fea()
    d, w, t, sigma = 10.0, 200.0, 2.0, 10.0

    def build(o):
        bx = o.addBox(0, -w / 2, 0, 400, w, t)
        o.cut([(3, bx)], [(3, o.addCylinder(200, 0, 0, 0, 0, t, d / 2))])
    step = _write(tmp_path / "plate.step", build)
    f = _faces(step)
    hole = next(x["id"] for x in f if x["kind"] == "cylinder")
    s = _static(step, [{"type": "fixed", "body": "b1", "faces": [_plane(f, 0, 0)]}],
                [{"type": "force", "body": "b1", "faces": [_plane(f, 0, 400)], "vector_n": [sigma * w * t, 0, 0]}], 8.0,
                mesh={"size_mm": 8.0, "refine_faces": [hole]})
    assert s["vm_max_mpa"] / sigma == pytest.approx(3.0, rel=0.03)
    assert abs(s["vm_max_at"][1]) == pytest.approx(d / 2, abs=0.5)                     # 在孔边、垂直于拉力方向
    assert s["trust"]["verdict"] == T.PASS, s["trust"]["items"]


def test_l_shape_reentrant_corner_is_flagged(tmp_path):
    _need_fea()

    def build(o):
        o.fuse([(3, o.addBox(0, 0, 0, 100, 20, 10))], [(3, o.addBox(0, 0, 0, 20, 100, 10))])
    step = _write(tmp_path / "L.step", build)
    f = _faces(step)
    s = _static(step, [{"type": "fixed", "body": "b1", "faces": [_plane(f, 1, 100)]}],
                [{"type": "force", "body": "b1", "faces": [_plane(f, 0, 100)], "vector_n": [0, -500, 0]}], 5.0)
    conv = next(i for i in s["trust"]["items"] if i["name"] == "网格收敛（最大应力）")
    assert conv["verdict"] == T.FAIL and "奇异点" in conv["text"]
    assert s["vm_max_at"][:2] == pytest.approx([20, 20], abs=1.0)                       # 峰值在凹角
    assert s["trust"]["verdict"] == T.FAIL and s["safety_factor"] is None and "不通过" in s["safety_factor_withheld"]
    disp = next(i for i in s["trust"]["items"] if i["name"] == "网格收敛（最大位移）")
    assert disp["verdict"] == T.PASS                                                     # 位移不受奇异点影响
