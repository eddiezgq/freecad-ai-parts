"""机器人关节输出空心轴的结构与校核（ADR-0100 42.5）：对照《机械设计》33.10 的 RJ-201。不联网；kt 用假函数（有限元另有标准题）。"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from analysis.shaft import joint as J

BOOK = yaml.safe_load((Path(__file__).with_name("data") / "book_33_10.yaml").read_text(encoding="utf-8"))
# 测试用的轴承（尺寸按 6010 的 50×80×16；额定动载荷是测试用的数，不是哪家目录的值）
B6010 = {"id": "bearing.test.6010", "category": "bearing", "model": "6010",
         "ports": [{"id": "inner", "spec": {"diameter_mm": {"value": 50}}}, {"id": "outer", "spec": {"diameter_mm": {"value": 80}}}],
         "params": {"width_mm": {"value": 16}, "dynamic_load_rating_n": {"value": 20000}}}
B6009 = {**B6010, "id": "bearing.test.6009", "model": "6009",
         "ports": [{"id": "inner", "spec": {"diameter_mm": {"value": 45}}}, {"id": "outer", "spec": {"diameter_mm": {"value": 75}}}]}
LIB = {b["id"]: b for b in (B6010, B6009)}
COND = {"T_peak_nm": BOOK["T_peak_nm"], "T_min_nm": BOOK["T_min_nm"], "F_peak_n": BOOK["F_peak_n"], "T_stop_nm": BOOK["T_stop_nm"],
        "reach_mm": BOOK["reach_mm"], "budget_mm": BOOK["budget_mm"], "required_safety": 1.5, "bearing_life_h": 20000,
        "speed_avg_rpm": 3.0, "material": "40Cr-QT", "surface": "machined"}


def fake_kt(d, big, r, bore=0.0):
    return {"kt_bending": 2.5, "kt_torsion": 1.8, "method": "测试用"}


def test_rules_match_book_33_10():
    assert J.spline(50)["D_ie_mm"] == 42.75 and J.spline(45)["D_ie_mm"] == 38.25
    assert J.thread(50) == 42
    segs = J.layout(50, 16)
    assert [(s["d"], s["L"]) for s in segs[:5]] == [(70, 10), (50, 16), (50, 24), (50, 16), (42.75, 20)]
    assert segs[4]["z1"] - (segs[3]["z0"] + 8) == BOOK["arm_offset_mm"]          # 外侧轴承中心到大臂连接面 28 mm


def test_book_scheme_passes_with_book_numbers():
    rep = J.evaluate({"bearing": "bearing.test.6010", "bore_mm": 30, "fillet_mm": 1.0}, COND, LIB.get, kt=fake_kt)
    by = {i["item"]: i for i in rep["items"]}
    assert rep["theta_rad"] == pytest.approx(BOOK["schemes"][2]["theta_rad"], rel=1e-6)
    assert rep["delta_mm"] == pytest.approx(BOOK["schemes"][2]["delta_mm"], rel=1e-6)
    assert rep["mass_model_kg"] == pytest.approx(BOOK["schemes"][2]["mass_kg"], rel=1e-6)
    assert by["静强度：轴承位"]["value"] == pytest.approx(BOOK["S_static_seat"], abs=0.01)
    assert by["静强度：花键段（按小径）"]["value"] == pytest.approx(BOOK["S_static_hub"], abs=0.01)
    assert by["急停：花键段不屈服"]["value"] == pytest.approx(BOOK["S_stop"], abs=0.01)
    assert by["花键齿面挤压（峰值力矩）"]["value"] == pytest.approx(BOOK["sigma_p_mpa"], abs=0.01)
    assert by["花键齿面挤压（急停）"]["value"] == pytest.approx(BOOK["sigma_p_stop_mpa"], abs=0.01)
    assert rep["overall"] == "pass", [i for i in rep["items"] if i["status"] != "pass"]


@pytest.mark.parametrize("bearing,bore,ok", [("bearing.test.6009", 25, False), ("bearing.test.6009", 30, False),
                                             ("bearing.test.6010", 34, False), ("bearing.test.6010", 38, False)])
def test_other_book_schemes_fail_stiffness(bearing, bore, ok):
    rep = J.evaluate({"bearing": bearing, "bore_mm": bore, "fillet_mm": 1.0}, COND, LIB.get, kt=fake_kt)
    stiff = next(i for i in rep["items"] if i["item"].startswith("刚度"))
    assert (stiff["status"] == "pass") is ok


def test_missing_requirement_is_unknown_not_pass():
    c = {k: v for k, v in COND.items() if k not in ("budget_mm", "required_safety")}
    rep = J.evaluate({"bearing": "bearing.test.6010", "bore_mm": 30, "fillet_mm": 1.0}, c, LIB.get, kt=fake_kt)
    assert rep["overall"] == "unknown"


def test_bad_proposals():
    with pytest.raises(J.JointProposalInvalid):
        J.evaluate({"bearing": "nope", "bore_mm": 30, "fillet_mm": 1}, COND, LIB.get, kt=fake_kt)
    rep = J.evaluate({"bearing": "bearing.test.6010", "bore_mm": 43, "fillet_mm": 1}, COND, LIB.get, kt=fake_kt)
    assert rep["overall"] == "fail"                                             # 内孔比花键小径还大
    rep = J.evaluate({"bearing": "bearing.test.6010", "bore_mm": 30, "fillet_mm": 10}, COND, LIB.get, kt=fake_kt)
    assert any(i["item"] == "法兰台阶圆角" and i["status"] == "fail" for i in rep["items"])
