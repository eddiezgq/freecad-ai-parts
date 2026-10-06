# -*- coding: utf-8 -*-
"""第 13 轮 N4：尺寸链（极值法、概率法、蒙特卡罗、反计算）、工艺尺寸跟踪图、定位误差。数字都按教材公式另行手算核对。"""
import math

import pytest

from hub import tolerance as T
from hub.tolerance import Cut, Link


def test_extreme_method_closing_ring():
    # 封闭环 A0 = A1 − A2：A1 = 50（0/−0.17），A2 = 40（+0.19/0）→ A0 = 10（0/−0.36）
    r = T.extreme([Link("A1", 50, 0, -0.17, +1), Link("A2", 40, 0.19, 0, -1)])
    assert r.nominal == 10 and r.es == pytest.approx(0) and r.ei == pytest.approx(-0.36)
    assert r.T == pytest.approx(0.36)


def test_solve_link_for_a_process_dimension_when_datums_differ():
    # 设计尺寸 10（0/−0.36）以左端面为基准，加工时从右端面测：求工序尺寸 A2 → 40（+0.19/0）
    a2 = T.solve_link([Link("A1", 50, 0, -0.17, +1)], (10, 0, -0.36), "A2", sense=-1)
    assert a2.nominal == pytest.approx(40) and a2.es == pytest.approx(0.19) and a2.ei == pytest.approx(0)
    with pytest.raises(ValueError):
        T.solve_link([Link("A1", 50, 0, -0.40, +1)], (10, 0, -0.36), "A2", sense=-1)   # 封闭环公差比 A1 还小


def test_statistical_and_monte_carlo_agree():
    links = [Link(f"A{i}", 10, 0.05, -0.05, +1) for i in range(4)]
    s = T.statistical(links)
    assert s.T == pytest.approx(math.sqrt(4) * 0.1)                     # √ΣT² = 0.2，极值法是 0.4
    assert T.extreme(links).T == pytest.approx(0.4)
    mc = T.monte_carlo(links, n=40_000)
    assert mc.T == pytest.approx(s.T, rel=0.05)


def test_tolerance_chart_resultant_and_allowance():
    ch = T.ToleranceChart([("L", "R", 105, 1.0, -1.0)])
    ch.cut(Cut(10, "R", "L", -102, 0.2, -0.2))       # 以右端面为基准车左端面
    ch.cut(Cut(20, "L", "S", 40, 0.1, -0.1))         # 以左端面为基准车台阶面
    ch.cut(Cut(30, "L", "R", 100, 0.1, -0.1))        # 调头，以左端面为基准车右端面
    r = ch.resultant("S", "R")                        # 图纸尺寸 S–R = 60：链 = −40 + 100
    assert r.nominal == pytest.approx(60) and r.T == pytest.approx(0.2 + 0.2)
    z = {a["surface"]: a for a in ch.allowances()}
    assert z["R"]["nominal"] == pytest.approx(2)                       # 右端面第二次车掉 2 ±(0.2 + 0.1)：链 = 工序 10 的 −102（±0.2）+ 工序 30 的 100（±0.1）
    assert (z["R"]["min"], z["R"]["max"]) == (pytest.approx(1.7), pytest.approx(2.3))


def test_v_block_formula_and_simulation():
    Td = 0.039
    assert T.v_block(Td, 90) == pytest.approx(Td / (2 * math.sin(math.pi / 4)))
    assert T.v_block(Td, 90, "top") == pytest.approx(Td / (2 * math.sin(math.pi / 4)) + Td / 2)
    assert T.v_block(Td, 90, "bottom") == pytest.approx(Td / (2 * math.sin(math.pi / 4)) - Td / 2)
    for m in ("center", "top", "bottom"):
        assert T.v_block_mc(40.3, 0, -Td, 90, m, n=20_000) == pytest.approx(T.v_block(Td, 90, m), rel=0.01)


def test_pin_and_two_pin_errors():
    hole, pin = (20, 0.021, 0), (20, -0.007, -0.020)                  # Ø20 H7 / g6
    assert T.pin_clearance(hole, pin) == pytest.approx(0.041)
    assert T.pin_clearance(hole, pin, "one") == pytest.approx((0.021 + 0.013) / 2)
    r = T.two_pins(100, hole, pin, (12, 0.018, 0), 0.03)
    assert r["rot_deg"] == pytest.approx(math.degrees(math.atan((0.041 + 0.03) / 200)))


def test_center_hole_and_judgement():
    assert T.center_hole_axial(0.2) == pytest.approx(0.2 / (2 * math.tan(math.radians(30))))
    assert T.ok_against(0.1, 0.03) and not T.ok_against(0.1, 0.04)
    assert T.locate_error(0.02, 0.01) == pytest.approx(0.03) and T.locate_error(0.02, 0.01, False) == pytest.approx(0.01)


def test_sh301_keyway_depth_chain_holds():
    """SH-301 的工艺：精车 Ø40.3（0/−0.039）后铣键槽控制 H = 35.15（−0.03/−0.20），再磨到 Ø40 k6；
    图纸要求 d − t = 35（0/−0.2）。磨削使下母线上移 (d精车 − d磨)/2：d − t = H − d精车/2 + d磨/2。"""
    import yaml
    from pathlib import Path
    p = yaml.safe_load((Path(__file__).resolve().parents[1] / "std" / "SH-301_process.yaml").read_text(encoding="utf-8"))
    fin = next(f for o in p["operations"] if o["seq"] == 40 for f in o["features"] if f["name"] == "齿轮位")
    grd = next(f for o in p["operations"] if o["seq"] == 60 for f in o["features"] if f["name"] == "齿轮位")
    r = T.extreme([Link("H", 35.15, -0.03, -0.20, +1),
                   Link("精车半径", fin["size_mm"] / 2, fin["es_mm"] / 2, fin["ei_mm"] / 2, -1),
                   Link("磨削半径", grd["size_mm"] / 2, grd["es_mm"] / 2, grd["ei_mm"] / 2, +1)])
    c5 = next(c for c in p["characteristics"] if c["id"] == "C5")
    assert r.nominal == pytest.approx(c5["nominal"])
    assert r.es <= c5["es"] + 1e-9 and r.ei >= c5["ei"] - 1e-9


def test_dof_analysis():
    plane = {"z", "rx", "ry"}
    side = {"y", "rz"}
    end = {"x"}
    assert T.dof_analysis([("底面", plane), ("侧面", side), ("端面", end)], set(T.DOF))["verdict"] == "完全定位"
    # 铣通槽：沿槽长方向 x 不必限制
    assert T.dof_analysis([("底面", plane), ("侧面", side)], {"z", "rx", "ry", "y", "rz"})["verdict"] == "不完全定位"
    assert T.dof_analysis([("底面", plane)], {"z", "rx", "ry", "y"})["missing"] == ["y"]
    # 长 V 形块（4 个）+ 两个端面挡销都限制 x：过定位
    r = T.dof_analysis([("长 V 形块", {"y", "z", "ry", "rz"}), ("左挡销", {"x"}), ("右挡销", {"x"})], {"x", "y", "z", "ry", "rz"})
    assert r["verdict"] == "过定位" and r["repeated"] == ["x"]


def test_v_block_contact_geometry_and_roundness():
    import math as m
    cx, cy = T.v_block_contact(T.circle_points(40, 720), 90)
    assert abs(cx) < 1e-9 and cy == pytest.approx(20 / m.sin(m.pi / 4), rel=1e-4)
    # 工作面不对称磨损：轴心偏离对称面
    cx2, _ = T.v_block_contact(T.circle_points(40, 720), 90, wear_left=0.01)
    assert abs(cx2) > 0.005
    # 三棱圆的圆度误差在 V 形块上被放大或缩小，公式不能反映
    base = T.v_block_mc(40.3, 0, -0.039, 90, "bottom", n=2000)
    assert base == pytest.approx(T.v_block(0.039, 90, "bottom"), rel=0.01)
    lob = T.v_block_mc(40.3, 0, -0.039, 90, "bottom", n=300, lobes=3, roundness=0.01)
    assert lob > base


def test_two_pins_point_and_diamond_pin():
    r = T.two_pins_point(150, 220, 0.029, 0.03)
    assert r["perp"] == pytest.approx(0.029 * (1 - 150 / 220) + 0.03 * 150 / 220)
    dp = T.diamond_pin((8, 0.015, 0), 3, 0.05, 0.01, 0.009)
    assert dp["X2min"] == pytest.approx(2 * 3 * 0.06 / 8) and dp["X2max"] == pytest.approx(8.015 - (8 - 0.045 - 0.009))


def test_statistical_general_and_allocate():
    links = [Link("A", 50, 0.1, -0.1, 1), Link("B", 30, 0.05, -0.05, -1)]
    g = T.statistical_general(links)
    s = T.statistical(links)
    assert g.T == pytest.approx(s.T) and g.es == pytest.approx(s.es)
    u = T.statistical_general(links, ["uniform", "uniform"])
    assert u.T == pytest.approx(1.73 * s.T)
    sk = T.statistical_general(links, ["skew_out", "normal"])
    assert sk.detail["mid"] == pytest.approx(0.26 * 0.2 / 2)
    a = T.allocate(0.3, [10, 100])
    assert sum(a) == pytest.approx(0.3) and a[1] > a[0]


def test_sh301_tolerance_chart_and_review():
    import copy
    import yaml
    from pathlib import Path
    from hub import process as P
    p = yaml.safe_load((Path(__file__).resolve().parents[1] / "std" / "SH-301_process.yaml").read_text(encoding="utf-8"))
    r = T.chart_from_plan(p["tolerance_chart"])
    assert all(d["ok"] for d in r["drawing"]) and all(a["ok"] for a in r["allowances"])
    bad = copy.deepcopy(p)
    for c in bad["tolerance_chart"]["cuts"]:
        if c["seq"] == 40.3:
            c["es"], c["ei"] = 0.3, -0.3
    rb = T.chart_from_plan(bad["tolerance_chart"])
    assert not next(d for d in rb["drawing"] if d["nominal"] == 60)["ok"]
    found = [x for x in P.review(bad) if "跟踪图" in str(x)]
    assert found, "评审员应当指出齿轮位长度 60 保证不了"
    assert not [x for x in P.review(p) if "cut_dir" in str(x)]
    nodir = copy.deepcopy(p)
    del nodir["tolerance_chart"]["cut_dir"]
    assert [x for x in P.review(nodir) if "cut_dir" in str(x)], "缺加工方向时应给出警告"
