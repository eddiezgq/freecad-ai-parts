"""整机三维装配（assist/robot_cad.py，ADR-0115 44.3 之二）。

标准题：直管质量 = [π/4·(D² − d²)·L − 两头倒圆（帕普斯定理）]·ρ；装配校核通过的整机生成后没有干涉；把 U 底板硬挪进壳体里能查出干涉；
螺钉头（ISO 4762 M2.5）沉在套管底下的沉头孔里放得下，去掉沉头孔就查得出放不下；管子细了螺钉从管孔里装不进去，
查得出并给出最小管径 2 ×（孔离管轴 √(10² + 8²) + 沉头孔半径 2.75 + 孔底圆角 1）= 33.1 → 34 mm。
"""

from __future__ import annotations

import copy
import math
import os

import pytest

if os.environ.get("CI"):
    import gmsh  # noqa: F401 — CI 中必须装（ADR-0056）
else:
    pytest.importorskip("gmsh")

from analysis.robot import fit
from assist import robot_cad as RC
from tests.test_robot_fit import _arm, _comp


def _ok_arm():
    c = _arm(wrist=[24.5, 0, 150])                               # 横置滚转，壳体中心在腕杆轴线上
    c["joints"][0]["origin_mm"] = [0, 0, 55]
    c["joints"][1]["origin_mm"] = [0, 0, 120]
    c["joints"][2]["origin_mm"] = [0, 0, 230]
    c["joints"][3]["origin_mm"] = [0, 0, 200]
    c["joints"][4]["axis"] = [1, 0, 0]
    c["end_effector"]["offset_mm"] = [60, 0, 0]
    c["links"][4]["length_mm"] = 60
    c["links"][3]["section"] = {"od_mm": 34, "id_mm": 28}          # 接 j5 壳体底座：螺钉从管孔里装要 ≥ 34 mm
    return c


def test_fit_passing_arm_assembles_without_interference(tmp_path):
    c, comp = _ok_arm(), _comp()
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]}, min_spare_mm=RC.min_spare_mm())
    assert fr["overall"] == "pass"
    r = RC.build(c, fr, comp, tmp_path)
    assert r["status"] == "pass" and not r["interferences"] and not r["problems"]
    assert (tmp_path / "assembly.step").stat().st_size > 10_000
    kinds = [p["kind"] for p in r["parts"]]
    assert kinds.count("actuator") == 5 and kinds.count("link") == 5 and kinds.count("bracket") == 10
    up = next(p for p in r["parts"] if p.get("link") == "upper")
    # 两头外棱倒圆 r：每头去掉的截面 (1 − π/4)r²，形心离外表面 r(10 − 3π)/(3(4 − π))，绕管轴一圈（帕普斯定理）
    rr = RC.DESIGN["tube_end_round_mm"]
    a_cut, xc = (1 - math.pi / 4) * rr ** 2, rr * (10 - 3 * math.pi) / (3 * (4 - math.pi))
    vol = math.pi / 4 * (40 ** 2 - 34 ** 2) * up["length_mm"] - 2 * a_cut * 2 * math.pi * (20 - xc)
    assert up["volume_mm3"] == pytest.approx(vol, rel=2e-4)
    assert up["mass_kg"] == pytest.approx(vol * 2.70e-6, abs=1e-4)
    assert r["mass_kg"] == pytest.approx(sum(p["mass_kg"] for p in r["parts"]), rel=1e-6)


def test_u_bracket_moved_into_the_housing_is_caught():
    c, comp = _ok_arm(), _comp()
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]}, min_spare_mm=RC.min_spare_mm())
    bad = copy.deepcopy(fr)
    for r in bad["joints"]:
        if r["joint"] == "j3":
            r["d_min_mm"] = 20.0                                 # 底板放到壳体里面
    res = RC.build(c, bad, comp)
    assert res["status"] == "fail"
    assert any("j3 U 形支架" in (h["a"] + h["b"]) and "j3 模组" in (h["a"] + h["b"]) for h in res["interferences"])


def test_fit_failure_is_not_built():
    c, comp = _arm(), _comp()                                    # 腕部共线滚转：装配校核不通过
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]})
    with pytest.raises(RC.CadError):
        RC.build(c, fr, comp)


def test_bolt_heads_under_sockets_need_counterbores(monkeypatch):
    c, comp = _ok_arm(), _comp()
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]}, min_spare_mm=RC.min_spare_mm())
    good = RC.build(c, fr, comp)
    assert good["status"] == "pass" and not any("螺钉头" in p for p in good["problems"])
    hb = next(p for p in good["parts"] if p["name"] == "j3 壳体底座")
    holes = hb["interfaces"]["load"]
    assert holes["counterbore_mm"] == RC.DESIGN["cb_depth_mm"] and len(holes["heads"]) == 4
    monkeypatch.setitem(RC.DESIGN, "plate_cb_mm", RC.DESIGN["plate_mm"])      # 不做沉头孔：头部压在套管底的板面上
    monkeypatch.setitem(RC.DESIGN, "cb_depth_mm", 0.0)
    bad = RC.build(c, fr, comp)
    # 孔在 20 × 16 上，离套管轴线 12.8 mm，头部外缘到 12.8 + 2.25 = 15.05 mm：前臂管 Ø34/28（内半径 14）顶到管壁；
    # 上臂管 Ø40/34（内半径 17）头部全落在管子里面，放得下
    assert bad["status"] == "fail" and any("j4 壳体底座 的螺钉头放不下：与 杆件 fore" in p for p in bad["problems"])
    assert not any(p.startswith("j3 壳体底座") for p in bad["problems"])


def test_thin_tube_blocks_the_screwdriver_and_says_how_thick():
    c, comp = _ok_arm(), _comp()
    c["links"][3]["section"] = {"od_mm": 32, "id_mm": 28}
    fr = fit.check(c, {j["id"]: comp for j in c["joints"]}, min_spare_mm=RC.min_spare_mm())
    r = RC.build(c, fr, comp)
    assert r["status"] == "fail"
    msg = next(p for p in r["problems"] if p.startswith("j5 壳体底座 的螺钉装不进去"))
    assert "外径加大到至少 34 mm" in msg
    assert RC.min_tube_od_mm() == {"housing": 34, "flange": 30}
