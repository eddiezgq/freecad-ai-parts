"""空心轴扭转刚度与静强度（ADR-0100 42.5）：解析解与《机械设计》33.10 书中结果对照。不联网。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from analysis.shaft import torsion as TS

BOOK = yaml.safe_load((Path(__file__).with_name("data") / "book_33_10.yaml").read_text(encoding="utf-8"))


def segs(seat, hub):
    return [(seat + 20, 10), (seat, 16), (seat, 24), (seat, 16), (hub, 20)]


def test_uniform_hollow_shaft_matches_closed_form():
    """等截面空心圆轴 θ = TL/(GJ)，J = π(D⁴ − d⁴)/32（材料力学）"""
    T, L, G, D, d = 1.0e5, 200.0, 80000.0, 40.0, 25.0
    J = math.pi * (D ** 4 - d ** 4) / 32
    assert TS.twist(T, [(D, L)], G, d) == pytest.approx(T * L / (G * J), rel=1e-12)
    # 两段同径、端段各算一半：等于总长的一半
    assert TS.twist(T, [(D, L), (D, L)], G, d) == pytest.approx(T * L / (G * J), rel=1e-12)


def test_static_safety_closed_form():
    r = TS.static_safety(540, 50, 30, moment_nmm=5000, torque_nmm=96000)
    w = math.pi * (50 ** 4 - 30 ** 4) / (32 * 50)
    assert r["sigma_mpa"] == pytest.approx(5000 / w) and r["tau_mpa"] == pytest.approx(96000 / (2 * w))
    assert TS.static_safety(540, 50, 30)["safety"] is None


@pytest.mark.parametrize("s", BOOK["schemes"], ids=lambda s: f"{s['seat']}-{s['bore']}")
def test_book_33_10_schemes(s):
    """书中五个方案的扭转角、末端偏移、质量（≤ 1 %，实际按同一公式应到 1e-9），以及按 1.2 倍余量的刚度结论"""
    th = TS.twist(BOOK["T_peak_nm"] * 1e3, segs(s["seat"], s["hub"]), BOOK["G_mpa"], s["bore"])
    delta = TS.tip_displacement(th, BOOK["reach_mm"])
    assert th == pytest.approx(s["theta_rad"], rel=1e-6)
    assert delta == pytest.approx(s["delta_mm"], rel=1e-6)
    assert TS.mass(segs(s["seat"], s["hub"]), BOOK["density_g_cm3"], s["bore"]) == pytest.approx(s["mass_kg"], rel=1e-6)
    assert (delta * BOOK["hand_margin"] <= BOOK["budget_mm"]) is s["ok"]


def test_book_33_10_pick_is_lightest_that_passes():
    ok = [s for s in BOOK["schemes"] if s["ok"]]
    pick = min(ok, key=lambda s: s["mass_kg"])
    assert (pick["seat"], pick["bore"]) == (BOOK["picked"]["seat"], BOOK["picked"]["bore"])


def test_book_33_10_static_strength():
    M = BOOK["F_peak_n"] * BOOK["arm_offset_mm"]
    T = BOOK["T_peak_nm"] * 1e3
    seat = TS.static_safety(BOOK["sigma_s_mpa"], 50, 30, M, T)
    hub = TS.static_safety(BOOK["sigma_s_mpa"], 42.75, 30, M, T)
    assert seat["sigma_mpa"] == pytest.approx(BOOK["sigma_seat_mpa"], rel=1e-6)
    assert seat["tau_mpa"] == pytest.approx(BOOK["tau_seat_mpa"], rel=1e-6)
    assert seat["safety"] == pytest.approx(BOOK["S_static_seat"], rel=1e-6)
    assert hub["safety"] == pytest.approx(BOOK["S_static_hub"], rel=1e-6)
