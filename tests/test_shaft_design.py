"""阶梯轴设计方案的确定性校核（ADR-0100 42.2）。轴承用公共库里的 NSK 6201（公开目录，ADR-0040）。"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from assist import shaft_design as SD

ROOT = Path(__file__).resolve().parents[1]
B6201 = "bearing.nsk-ltd.6201"
KT = {(10.0, 12.0): (2.0405327466155305, 1.4933575966450117), (12.0, 16.0): (2.3306613715159963, 1.6070317843068973)}


def get(cid):
    p = ROOT / "data" / "library" / "bearing" / f"{cid}.json"
    return json.loads(p.read_text("utf-8")) if p.is_file() else None


def fake_kt(d, big, r):
    a, b = KT.get((d, big), (2.0, 1.5))
    return {"kt_bending": a, "kt_torsion": b, "method": "《机械设计》33.11 的有限元值（测试用）"}


COND = {
    "speeds_rpm": [5000, 5500], "bearing_centers_mm": [27, 252], "drive_z_mm": 282, "material": "45-QT",
    "surface": "ground", "required_safety": 1.5, "critical_ratio": 1.3, "bearing_life_h": 20000,
    "masses": [{"name": "曲柄与平衡块", "z_mm": 11, "mass_kg": 0.15}, {"name": "挑线凸轮", "z_mm": 45, "mass_kg": 0.05},
               {"name": "送布偏心轮", "z_mm": 150, "mass_kg": 0.08}, {"name": "同步带轮", "z_mm": 262, "mass_kg": 0.06},
               {"name": "手轮与转子", "z_mm": 282, "mass_kg": 0.45}],
    "loads": [{"type": "crank_slider", "z_mm": 11, "crank_radius_mm": 15.5, "rod_length_mm": 55, "reciprocating_mass_kg": 0.12,
               "balance_ratio": 0.45}, {"type": "torque_load", "z_mm": 11, "power_w": 150},
              {"type": "force", "z_mm": 262, "fx_n": 0, "fy_n": -120}],
}
LS101 = {"segments": [{"role": "crank_seat", "diameter_mm": 10, "length_mm": 22, "fillet_mm": 0.5},
                      {"role": "bearing_seat", "bearing": B6201, "fillet_mm": 0.5},
                      {"role": "body", "diameter_mm": 16, "length_mm": 215, "fillet_mm": 0.5},
                      {"role": "bearing_seat", "bearing": B6201, "fillet_mm": 0.5},
                      {"role": "pulley_seat", "diameter_mm": 10, "length_mm": 40}]}


@pytest.fixture(scope="module")
def ls101():
    assert get(B6201), "公共库里要有 NSK 6201"
    return SD.evaluate(LS101, COND, get, kt=fake_kt)


def by(rep, text):
    return [i for i in rep["items"] if text in i["item"]]


def test_bearing_seats_from_library(ls101):
    segs = ls101["segments"]
    assert [(s["d"], s["L"]) for s in segs] == [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]   # 与书中 LS-101 相同
    assert all(i["status"] == "pass" for i in by(ls101, "轴承中心"))
    assert all(i["status"] == "pass" for i in by(ls101, "能套进去")) and all(i["status"] == "pass" for i in by(ls101, "轴肩定位"))
    # NSK 6201 的安装尺寸（da 16–17、ra max 0.6，ADR-0102）：轴身 Ø16、圆角 0.5 合规
    assert [i["status"] for i in by(ls101, "轴肩直径")] == ["pass", "pass"]
    assert [i["status"] for i in by(ls101, "轴肩圆角")] == ["pass", "pass"]
    assert ls101["overall"] == "pass"


def test_shoulder_with_abutment_data():
    """有安装尺寸时按 da min–da max、ra max 判（ADR-0102）；数是测试用的，不是哪家的目录"""
    comp = json.loads(json.dumps(get(B6201)))
    for k, v in (("abutment_shaft_min_mm", 16.0), ("abutment_shaft_max_mm", 17.0), ("fillet_max_mm", 0.6)):
        comp["params"][k] = {"value": v}
    lay = SD.layout(SD.check_proposal(LS101, lambda c: comp)[0])
    items = SD.shoulder_checks(lay, 1, comp)
    assert [i["status"] for i in items] == ["pass", "pass"]                  # 轴身 Ø16 在 16–17 之间，圆角 0.5 ≤ 0.6
    low = json.loads(json.dumps(LS101))
    low["segments"][2]["diameter_mm"] = 14
    lay = SD.layout(SD.check_proposal(low, lambda c: comp)[0])
    assert SD.shoulder_checks(lay, 1, comp)[0]["status"] == "fail"


def test_ls101_strength_matches_book_and_passes(ls101):
    s = {i["item"]: i for i in by(ls101, "安全系数")}
    i5 = next(v for k, v in s.items() if "Ø10→Ø12" in k and "5000" in k)
    assert i5["value"] == pytest.approx(2.7461, rel=0.02) and i5["status"] == "pass"     # 书中截面 I：2.75
    assert all(v["status"] == "pass" for v in s.values())
    crit = by(ls101, "临界转速")[0]
    assert crit["status"] == "pass" and crit["value"] > 4


def test_bearing_life(ls101):
    lives = by(ls101, "寿命")
    assert len(lives) == 4 and all(i["status"] in ("pass", "fail") and i["value"] > 0 for i in lives)
    front = next(i for i in lives if "z 27" in i["item"] and "5000" in i["item"])
    rear = next(i for i in lives if "z 252" in i["item"] and "5000" in i["item"])
    assert front["value"] < rear["value"]                     # 前轴承靠近曲柄，载荷大


def test_life_formula_simple_case():
    cond = {"speeds_rpm": [1000], "bearing_centers_mm": [5, 95], "material": "45-QT",
            "loads": [{"type": "force", "z_mm": 50, "fx_n": 0, "fy_n": -1000}], "bearing_life_h": 1}
    prop = {"segments": [{"role": "bearing_seat", "bearing": B6201, "fillet_mm": 0.5},
                         {"role": "body", "diameter_mm": 16, "length_mm": 80, "fillet_mm": 0.5},
                         {"role": "bearing_seat", "bearing": B6201}]}
    rep = SD.evaluate(prop, cond, get, kt=fake_kt)
    c = get(B6201)["params"]["dynamic_load_rating_n"]["value"]
    want = 1e6 / (60 * 1000) * (c / 500) ** 3
    for i in by(rep, "寿命"):
        assert i["value"] == pytest.approx(want, rel=1e-6)


def test_wrong_positions_and_assembly_fail():
    bad = {"segments": [{"role": "body", "diameter_mm": 16, "length_mm": 30, "fillet_mm": 0.5},
                        {"role": "bearing_seat", "bearing": B6201, "fillet_mm": 0.5},
                        {"role": "body", "diameter_mm": 16, "length_mm": 215, "fillet_mm": 0.5},
                        {"role": "bearing_seat", "bearing": B6201, "fillet_mm": 0.5},
                        {"role": "end", "diameter_mm": 16, "length_mm": 30}]}
    rep = SD.evaluate(bad, COND, get, kt=fake_kt)
    assert rep["overall"] == "fail"
    assert any(i["status"] == "fail" for i in by(rep, "轴承中心"))
    assert any(i["status"] == "fail" for i in by(rep, "能套进去"))           # 两侧都是 Ø16，Ø12 内径的轴承套不进去
    fb = SD.feedback(rep)
    assert "不通过" in fb and "要求" in fb


@pytest.mark.parametrize("prop,msg", [
    ({}, "没有轴段"),
    ({"segments": [{"role": "magic", "diameter_mm": 1, "length_mm": 1}]}, "用途"),
    ({"segments": [{"role": "bearing_seat", "bearing": "bearing.nobody.x"}]}, "不在零件库"),
    ({"segments": [{"role": "body", "diameter_mm": 10}]}, "直径和长度"),
])
def test_bad_proposals_refused(prop, msg):
    with pytest.raises(SD.ProposalInvalid, match=msg):
        SD.evaluate(prop, COND, get, kt=fake_kt)


def test_missing_fillet_is_unknown():
    p = json.loads(json.dumps(LS101))
    del p["segments"][0]["fillet_mm"]
    rep = SD.evaluate(p, COND, get, kt=fake_kt)
    assert any(i["status"] == "unknown" and "没给过渡圆角" in i.get("note", "") for i in rep["items"])
    assert rep["overall"] in ("unknown", "fail") and not math.isnan(rep["mass_kg"])


def test_fillet_larger_than_step_fails():
    p = json.loads(json.dumps(LS101))
    p["segments"][0]["fillet_mm"] = 2.0                      # Ø10→Ø12 台阶高 1 mm
    rep = SD.evaluate(p, COND, get, kt=fake_kt)
    bad = [i for i in rep["items"] if "圆角" in i["item"] and i["status"] == "fail" and "台阶高度" in i.get("note", "")]
    assert bad and rep["overall"] == "fail"
