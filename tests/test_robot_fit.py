"""装不装得下（analysis/robot/fit.py，ADR-0115 44.3 之二第 3 步之一）。

标准题（平面几何）：
  · U 底板离轴线很远（d ≫ 外形）时，碰到下面父杆的角度由 d·sin φ = (b + w)/2 决定（φ = 180° − 最大转角，b 底板宽、w 父杆宽）
  · d 小于轴线到壳体顶面的距离时，伸直位就碰上
  · 共线轴转装不上；关节距不够时判不通过
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

from analysis.robot import fit
from kb.library import JsonLibrary

ROOT = Path(__file__).parents[1]
H = {"half_width": 16.75, "bottom": -44.75, "top": 13.75, "axis_to_bottom": 44.75, "horn_diameter": 26.0}


def test_separating_axis_overlap():
    a = fit._rect(0, 1, 0, 1)
    assert fit._overlap(a, fit._rect(0.5, 2, 0.5, 2))
    assert not fit._overlap(a, fit._rect(1, 2, 0, 1))                    # 只接触不算
    assert not fit._overlap(a, fit._rot(fit._rect(2, 3, 0, 1), 0))


def test_far_plate_reach_matches_geometry():
    b, w, d = 33.5, 40.0, 250.0
    phi = math.degrees(math.asin((b + w) / (2 * d)))
    assert fit.clevis_reach(d, b, H, w) == pytest.approx(180 - phi, abs=fit.STEP_DEG)


def test_plate_inside_housing_top_collides_at_straight():
    assert fit.clevis_reach(H["top"] - 1, 33.5, H, 33.5) < 0
    assert fit.clevis_reach(H["top"] + 1, 33.5, H, 33.5) >= 0


def test_d_min_is_monotone_and_none_beyond_limit():
    d1, d2 = fit.d_min(90, 33.5, H, 40), fit.d_min(140, 33.5, H, 40)
    assert d1 is not None and d2 is not None and d1 < d2
    assert fit.clevis_reach(d2, 33.5, H, 40) >= 140 > fit.clevis_reach(d2 - 0.5, 33.5, H, 40)
    assert fit.d_min(179, 33.5, H, 40) is None


def _case_a():
    cr = json.loads((ROOT / "examples" / "robots" / "teaching-arm" / "out" / "concept-result.json").read_text(encoding="utf-8"))
    comp = JsonLibrary(ROOT / "data" / "library").get("smart_actuator.robotis.xm540-w270")
    return cr["chosen"], comp


def test_case_a_collinear_wrist_roll_cannot_be_mounted():
    c, comp = _case_a()
    r = fit.check(c, {j["id"]: comp for j in c["joints"]})
    j = {x["joint"]: x for x in r["joints"]}
    assert j["j5"]["status"] == "fail" and "共线" in j["j5"]["note"]
    assert j["j2"]["status"] == "pass" and j["j2"]["d_min_mm"] > H["axis_to_bottom"]
    links = {x["link"]: x for x in r["links"]}
    assert links["upper_arm"]["status"] == "pass"
    assert links["upper_arm"]["min_mm"] == pytest.approx(j["j2"]["d_min_mm"] + 44.75, abs=0.1)
    assert r["overall"] == "fail"


def test_short_link_fails_and_missing_interfaces_unknown():
    c, comp = _case_a()
    c = copy.deepcopy(c)
    up = next(x for x in c["joints"] if x["id"] == "j3")
    up["origin_mm"] = [0, 0, 60]                                             # 上臂只有 60 mm：放不下 U 底板与下一个壳体
    r = fit.check(c, {j["id"]: comp for j in c["joints"]})
    assert {x["link"]: x for x in r["links"]}["upper_arm"]["status"] == "fail"
    small = JsonLibrary(ROOT / "data" / "library").get("smart_actuator.robotis.xm430-w350")   # 430 没有接口数据
    r = fit.check(c, {j["id"]: small for j in c["joints"]})
    assert all(x["status"] == "unknown" for x in r["joints"])
