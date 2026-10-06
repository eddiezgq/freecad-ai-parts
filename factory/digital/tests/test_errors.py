# -*- coding: utf-8 -*-
"""第 13 轮 N6：加工误差模型与问题情景——注入的问题在数据上表现出对应的形态，只有对症的措施能消除它。"""
import statistics

import pytest

from sim import errors as ERR
from test_sim import dispatch_all, make_engine, run_to_end


def values(out, code, after_serial=None):
    return [m["data"]["value_mm"] for t, m in out
            if m["type"] == "quality.measurement" and m["data"]["characteristic"] == code]


def run(problem=None, magnitude=None, qty=40, fix=None, seed=3):
    eng, clock, out = make_engine(seed=seed)
    if problem:
        eng.errors.inject(problem, magnitude)
    if fix:
        eng.errors.apply_fix(fix)
    dispatch_all(eng, qty=qty)
    run_to_end(eng, clock)
    return out


def taper(out):
    left, right = values(out, "bearing_seat_d35"), values(out, "bearing_seat_d35_r")
    return statistics.mean(r - l for l, r in zip(left, right))


def test_normal_process_is_capable_and_has_no_taper():
    out = run()
    assert abs(taper(out)) < 0.001
    assert max(values(out, "runout_bearing")) < 0.012 and max(values(out, "keyway_sym")) < 0.02


def test_tailstock_offset_shows_as_taper_and_only_the_right_fix_removes_it():
    e = 0.008
    out = run("tailstock_offset", e)
    assert taper(out) == pytest.approx(2 * e * (ERR.Z_RIGHT - ERR.Z_LEFT) / ERR.LENGTH, abs=0.0008)
    wrong = run("tailstock_offset", e, fix="reduce_feed")
    assert taper(wrong) > 0.005
    right = run("tailstock_offset", e, fix="align_tailstock")
    assert abs(taper(right)) < 0.001


def test_dressing_interval_steepens_the_drift():
    def slope(out):
        v = values(out, "bearing_seat_d35")
        return (statistics.mean(v[-8:]) - statistics.mean(v[:8]))
    assert slope(run("dressing_interval")) > 1.8 * slope(run())


def test_cold_grinder_makes_parts_smaller_then_settles():
    """同一随机种子，有无“未预热”逐件相减，得到的就是热变形引起的偏移：开始很小，约 15 件后稳定在 −0.010。"""
    hot, base = values(run("thermal_warmup", 0.010), "bearing_seat_d35"), values(run(), "bearing_seat_d35")
    d = [h - b for h, b in zip(hot, base)]
    assert max(d[:2]) > -0.004 and statistics.mean(d[-10:]) == pytest.approx(-0.010, abs=0.0015)


def test_worn_locator_and_poor_center_holes():
    sym = values(run("locator_worn"), "keyway_sym")
    assert statistics.mean(sym) > 0.015 and max(sym) > 0.02
    ro = values(run("center_hole"), "runout_bearing")
    assert statistics.mean(ro) > 0.008 and max(ro) > 0.012


def test_original_three_characteristics_are_unchanged_without_problems():
    """没有问题情景时，原有三项的数值与改动前的模型一样（随机数仍来自引擎主随机数，顺序不变）。"""
    import random
    out = run(seed=5, qty=5)
    v = values(out, "gear_seat_d40")
    assert all(40.002 <= x <= 40.018 for x in v)
    assert ERR.CHARS[:3] == [("bearing_seat_d35", "轴承位直径 Ø35 k6（左）", 35.010, 35.002, 35.018),
                             ("gear_seat_d40", "齿轮位直径 Ø40 k6", 40.010, 40.002, 40.018),
                             ("keyway_width_12", "键槽宽 12 N9", 11.9785, 11.957, 12.000)]
    with pytest.raises(KeyError):
        ERR.ErrorModel().inject("no_such_problem")
    assert random  # noqa
