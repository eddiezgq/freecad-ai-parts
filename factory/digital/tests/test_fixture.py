"""第 52 章夹具计算库。"""
import math
import os

import pytest

from hub import fixture as F


def test_slot_forces_power_matches_kienzle_volume_estimate():
    r = F.slot_forces(12, 2, 0.03, 1.03)
    P = F.slot_power(r, 12, 25)
    # 体积法：P = ap·ae·vf·kc(hm)/60e6，满槽 hm ≈ 2fz/π
    n = 1000 * 25 / (math.pi * 12)
    vf = 0.03 * 2 * n
    kc = r["kc11"] * (2 * 0.03 / math.pi) ** (-r["mc"])
    assert P == pytest.approx(1.03 * 12 * vf * kc / 60e6, rel=0.08)
    assert r["Fz_mean"] > 0 and r["Fy_peak"] > abs(r["Fy_mean"])


def test_vblock_clamp_conditions():
    need = F.vblock_clamp_required(100, 100, 30, 2.0, 0.15, 0.15, 90, G=0, axial_stop_takes_Fx=False)
    fr = 0.15 + 0.15 / math.sin(math.pi / 4)
    assert need["req"]["rotate"] == pytest.approx(200 / fr) and need["req"]["slide_out"] == pytest.approx(200)
    N1, N2 = F.vblock_normal_forces(1000, 100)
    assert N1 * math.sin(math.pi / 4) * 2 == pytest.approx(1000) or N1 > 0
    assert (N1 + N2) * math.sin(math.pi / 4) == pytest.approx(1000)


def test_mechanisms():
    w = F.wedge(100, 6, 5.71, 5.71)
    assert w["self_lock"] and w["W"] == pytest.approx(100 / (math.tan(math.radians(5.71)) + math.tan(math.radians(11.71))))
    assert not F.wedge(100, 15, 5.71, 5.71)["self_lock"]
    e = F.eccentric(80, 100, 40, 2, 0.1, 0.1)
    assert e["self_lock_safe"] and not F.eccentric(80, 100, 40, 3, 0.1, 0.1)["self_lock_safe"]
    s = F.screw_clamp(50, 100, 10, 1.5, r_end=3)
    assert s["self_lock"] and 3000 < s["W"] < 5000
    assert F.cylinder(50, 0.5, 1.0) == pytest.approx(math.pi / 4 * 2500 * 0.5)


def test_guides_and_fixture_file():
    b = F.bushing_drill_error((6.8, 0.028, 0.013), (6.8, 0, -0.022), 12, 6)
    assert b["zone"] == pytest.approx(0.05 * 2)
    assert F.key_alignment((18, 0.027, 0), (18, 0, -0.027), 200, 45, one_side=True)["skew"] == 0
    r = F.analyse(F.load_fixture("JJ-301-50"))
    assert r["ok_clamp"] and all(b["ok"] for b in r["budgets"].values())
    assert F.review("JJ-301-50") == []


def test_review_uses_student_fixture_data_in_the_operation():
    """TS-52-1：学生把自己的夹具数据写在工序 50 的 fixture 里；把拧紧扭矩改为 1 N·m（hand_force 10、wrench 100），评审员指出夹紧力不够"""
    import copy
    from hub import fixture as FX, process
    from hub.cards import load
    base = FX.load_fixture("JJ-301-50")
    assert FX.review("JJ-301-50") == [] or all(lv != "error" for lv, _ in FX.review("JJ-301-50"))
    weak = copy.deepcopy(base)
    weak["clamping"]["hand_force"] = 10
    msgs = FX.review("JJ-301-50", weak)
    assert any(lv == "error" and "夹紧力" in t for lv, t in msgs)
    plan = load(os.path.join(os.path.dirname(__file__), "..", "std", "SH-301_process.yaml"))
    op50 = next(o for o in plan["operations"] if o["seq"] == 50)
    op50["fixture"] = weak
    f = process.review(plan)
    assert any(x["rule"] == "夹具" and x["level"] == "error" for x in f)
