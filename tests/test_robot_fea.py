"""自制支架强度有限元（assist/robot_fea.py，ADR-0115 44.3 之二第 6 步）。不联网、不调用 LLM。

标准题（与独立算法对照）：
- 载荷：输出支架接口上的远端载荷加支架自重，对关节轴的力矩 = 复核多体动力学（MuJoCo）在同一姿态算出的静重力矩 × 动载系数。
- 有限元：舵盘螺钉孔上的反力对关节轴的力矩 = 同一个值（静力平衡），反力合力 = 下游总重 × 动载系数。
用案例 A（教学桌面臂）的结果文件。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from assist import robot_fea as RF

OUT = Path(__file__).resolve().parents[1] / "examples" / "robots" / "teaching-arm" / "out"


def _load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def _plates():
    """案例的板厚（第 9 步减薄后写在案例目录）；重出装配要按它，才和保存的复核结果一致"""
    pp = OUT.parent / "plates.json"
    return json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None


def _case():
    return _load("concept-result.json"), _load("build-result.json"), _load("cad/cad-result.json"), _load("verify-result.json")


def _axis_moment(part, ld):
    """远端载荷 + 自重对关节轴（舵盘孔组的轴线）的力矩，N·m"""
    h = part["interfaces"]["fixed"]
    a = np.asarray(h["axis"], float)
    c = np.mean(np.asarray(h["centers"], float), axis=0)
    M = np.asarray(ld["moment_nm"]) + np.cross((np.asarray(ld["point_mm"]) - c) / 1000, ld["force_n"])
    M += np.cross((np.asarray(part["cog_mm"]) - c) / 1000, part["mass_kg"] * np.asarray(ld["gravity_m_s2"]))
    return float(M @ a)


def test_output_bracket_load_equals_mbd_gravity_torque_times_factor():
    cr, br, cad, vr = _case()
    k = RF.dynamic_factor(vr)
    assert 1.0 < k < 1.2
    st = vr["static"]["gravity_torque_nm"]
    seen = 0
    for p in cad["parts"]:
        if p.get("role") != "output" or abs(st[p["joint"]]) < 0.1:
            continue
        ld = RF.load_on(cr["chosen"], p, cad["parts"], float(cr["conditions"]["payload"]), br["duty"]["initial"], k)
        assert abs(_axis_moment(p, ld)) == pytest.approx(abs(st[p["joint"]]) * k, rel=1e-4), p["name"]
        seen += 1
    assert seen == 3                                              # j2、j3、j4 三个俯仰关节的 U 形支架


def test_downstream_of_housing_base_includes_its_actuator_but_not_the_parent_tube():
    cr, _, cad, _ = _case()
    hb = next(p for p in cad["parts"] if p["name"] == "j3 壳体底座")
    names = {p["name"] for p in RF.downstream(cr["chosen"], hb, cad["parts"])}
    assert "j3 模组 XM540-W270" in names and "j4 模组 XM540-W270" in names
    assert not any(n.startswith("杆件 upper_arm") or n == "j2 U 形支架" or n == "j3 壳体底座" for n in names)
    ub = next(p for p in cad["parts"] if p["name"] == "j3 U 形支架")
    names = {p["name"] for p in RF.downstream(cr["chosen"], ub, cad["parts"])}
    assert "j3 模组 XM540-W270" not in names and "j3 U 形支架" not in names and any(n.startswith("杆件 forearm") for n in names)


def _fake(trust, vm, sf, withheld=None):
    s = {"trust": {"verdict": trust}, "vm_max_mpa": vm, "safety_factor": sf, "u_max_mm": 0.01}
    if withheld:
        s["safety_factor_withheld"] = withheld
    return {"status": "ok", "data": {"steps": [s]}}


def test_judge_needs_trust_and_checks_fatigue():
    assert RF.judge(_fake("unknown", 10.0, None, "网格没收敛"), "6061-T6", 1.2)["status"] == "unknown"
    ok = RF.judge(_fake("pass", 10.0, 27.6), "6061-T6", 1.2)
    assert ok["status"] == "pass" and ok["safety_fatigue"] == pytest.approx(96.5 / 10.0, rel=1e-3)
    bad = RF.judge(_fake("pass", 90.0, 3.07), "6061-T6", 1.2)          # 屈服够，疲劳 96.5 / 90 = 1.07 不够
    assert bad["status"] == "fail"
    assert RF.judge(_fake("pass", 10.0, 27.6), "6061-T6", None)["status"] == "unknown"
    assert RF.judge({"status": "failed", "messages": ["x"]}, "6061-T6", 1.2)["status"] == "unknown"


def _need_fea():
    from analysis.common.solvers import find_ccx
    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        assert find_ccx(), "CI 中没有 ccx"
        return
    pytest.importorskip("gmsh")
    if not find_ccx():
        pytest.skip("本机没有 CalculiX")


def test_j2_u_bracket_faces_and_reactions(tmp_path):
    """装配 → 取出 j2 U 形支架 → 选面（16 个舵盘孔、套管孔）→ 有限元：舵盘孔反力矩 = 关节静重力矩 × 动载系数"""
    _need_fea()
    import analysis
    from analysis.robot import fit
    from assist import robot_cad as RC
    from kb.library import JsonLibrary

    cr, br, _, vr = _case()
    c = cr["chosen"]
    comp = JsonLibrary(Path(__file__).resolve().parents[1] / "data" / "library").get(
        next(iter(br["picks"].values()))["components"][0])
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]})
    cad = RC.build(c, fr, comp, tmp_path, _plates())
    p = next(x for x in cad["parts"] if x["name"] == "j2 U 形支架")
    step = tmp_path / "j2.step"
    RF.extract(tmp_path / "assembly.step", p, step)
    nodes = RF._face_nodes(step)
    holes = RF.select_faces(nodes, p["interfaces"]["fixed"])
    sock = RF.select_faces(nodes, p["interfaces"]["load"])
    assert len(holes) >= 16 and sock and not set(holes) & set(sock)
    k = RF.dynamic_factor(vr)
    ld = RF.load_on(c, p, cad["parts"], float(cr["conditions"]["payload"]), br["duty"]["initial"], k)
    res = analysis.run("fea", RF.study(p, step, ld, mesh_mm=RF.mesh_mm(p), convergence=False))
    assert res["status"] == "ok", res.get("messages")
    s = res["data"]["steps"][0]
    sr = s["support_reactions"][0]
    h = p["interfaces"]["fixed"]
    a, cen = np.asarray(h["axis"]), np.mean(np.asarray(h["centers"]), axis=0)
    m_axis = (np.asarray(sr["moment_nmm"]) - np.cross(cen, sr["force_n"])) @ a / 1000
    assert abs(m_axis) == pytest.approx(abs(vr["static"]["gravity_torque_nm"]["j2"]) * k, rel=0.01)
    total = (ld["mass_kg"] + p["mass_kg"]) * 9.81 * k
    assert np.linalg.norm(sr["force_n"]) == pytest.approx(total, rel=0.01)
