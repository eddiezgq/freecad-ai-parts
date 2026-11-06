# -*- coding: utf-8 -*-
"""AI 起草（第 105 轮）：不调真模型，用录好的回答当替身。正常草稿能展开并通过；编造、越界、来源不合格的被挡下；
需求没给电压时留空提问、不出设计；不通过时让模型再改一轮。"""

import os

import pytest
from conftest import DESIGNS

from wqeda import blocks
from wqeda.ai import catalog as cat
from wqeda.ai import draft
from wqeda.ai.check import check
from wqeda.blocks import common as c
from wqeda.schema import design

A_PATH = os.path.join(DESIGNS, "drv-joint", "design.yaml")
REQ = "给 400 W、48 V 的机器人关节伺服电机做一块驱动板，额定相电流 8.5 A，峰值 30 A，带 2500 线增量编码器和 CAN。"


def S(key, value, source="requirement", quote="", why=""):
    return {"key": key, "value": value, "source": source, "quote": quote, "why": why}


GOOD = {
    "spec": [
        S("bus_voltage_v", 48, quote="48 V"),
        S("phase_current_a", 8.5, quote="额定相电流 8.5 A"),
        S("phase_current_peak_a", 30, quote="峰值 30 A"),
        S("motor_power_w", 400, quote="400 W"),
    ],
    "units": [{"type": "encoder", "params": [S("lines", 2500, quote="2500 线")]}, {"type": "can", "params": []}],
    "questions": ["最高转速是多少？"],
    "unsupported": [],
}


@pytest.fixture(scope="module")
def template():
    return design.load_design(A_PATH)


@pytest.fixture(scope="module")
def catalog(template):
    return cat.build(template)


def fake(*answers):
    seen = []

    def model(requirement, catalog, lang, feedback):
        seen.append(feedback)
        return answers[min(len(seen) - 1, len(answers) - 1)], 100 + len(seen)

    model.seen = seen
    return model


def test_catalog_lists_only_what_blocks_support(catalog, template):
    assert {u["type"] for u in catalog["units"]} | {u["type"] for u in catalog["fixed_units"]} == set(
        blocks.CALCULATORS
    )
    assert all("default" not in s for s in draft.for_model(catalog)["spec"])  # 规格不给模型默认值，免得照抄
    rg = next(p for u in catalog["units"] if u["type"] == "gate_drive" for p in u["params"] if p["key"] == "RG_OHM")
    assert rg["default"] == 10.0 and rg["allowed"] == [2.2, 47]


def test_good_draft_expands_and_matches_drive_board(template):
    res = draft.run(REQ, fake(GOOD), template)
    f = res["final"]
    assert f["report"]["rejected"] == [] and f["report"]["missing"] == []
    assert f["result"]["fails"] == [] and f["passed"] and len(res["rounds"]) == 1
    doc = design.read_yaml_text(f["result"]["yaml"])
    assert [u["type"] for u in blocks.units(doc)] == [u["type"] for u in blocks.units(template)]
    assert doc["spec"]["bus_voltage_v"] == 48 and doc["spec"]["phase_current_peak_a"] == 30
    assert doc["draft"]["provenance"]["spec"]["bus_voltage_v"] == {"source": "requirement", "quote": "48 V"}
    assert len(design.all_parts(doc)) == len(design.all_parts(template))  # 同一套电路


@pytest.mark.parametrize(
    "bad, reason",
    [
        ({"type": "ethercat", "params": []}, "目录里没有这种单元"),
        ({"type": "gate_drive", "params": [S("RG_OHM", 100, "rule", why="随便")]}, "超出本版支持的范围"),
        ({"type": "bus_input", "params": [S("c_bus_v", 70, "rule", why="48×1.25=60，取 70")]}, "不在可选项里"),
        ({"type": "gate_drive", "params": [S("RG_OHM", 4.7, "rule")]}, "没写用了哪些数"),
        ({"type": "gate_drive", "params": [S("RG_OHM", 4.7, "assumption")]}, "要写成一个要人回答的问题"),
        ({"type": "encoder", "params": [S("rpm_max", 3000, quote="3000 r/min")]}, "引用的话不在需求里"),
        ({"type": "encoder", "params": [S("lines", 1000, quote="2500 线")]}, "引用的话里没有这个数"),
        ({"type": "mcu_core", "params": [S("mcu", "STM32F4", "assumption", why="?")]}, "没有可以改的参数"),
        ({"type": "encoder", "params": [S("pin_map", {}, "rule", why="x")]}, "不能改或不存在"),
    ],
)
def test_bad_values_are_rejected(catalog, bad, reason):
    ans = dict(GOOD, units=[bad])
    rep = check(ans, REQ, catalog)
    assert any(reason in r["reason"] for r in rep["rejected"]), rep["rejected"]


def test_required_spec_cannot_be_assumed_or_invented(catalog, template):
    no_v = "给 400 W 的机器人关节伺服电机做一块驱动板，额定相电流 8.5 A，峰值 30 A。"
    guessed = dict(GOOD, spec=[S("bus_voltage_v", 48, "assumption", why="常见 48 V？")] + GOOD["spec"][1:])
    rep = check(guessed, no_v, catalog)
    assert "bus_voltage_v" in rep["missing"] and any("不能由 AI 假设" in r["reason"] for r in rep["rejected"])
    quoted = dict(GOOD, spec=[S("bus_voltage_v", 48, quote="48 V")] + GOOD["spec"][1:])
    rep = check(quoted, no_v, catalog)
    assert "bus_voltage_v" in rep["missing"]  # 需求里没有“48 V”，引用不成立
    honest = dict(GOOD, spec=[S("bus_voltage_v", None, why="")] + GOOD["spec"][1:], questions=["母线电压是多少？"])
    res = draft.run(no_v, fake(honest), template)
    f = res["final"]
    assert (
        f["result"] is None
        and f["report"]["missing"] == ["bus_voltage_v"]
        and "母线电压是多少？" in f["report"]["questions"]
    )
    assert len(res["rounds"]) == 1  # 缺关键数据：等人回答，不让模型再猜


def test_fail_triggers_one_revision(template):
    weak = dict(
        GOOD,
        units=GOOD["units"]
        + [{"type": "bus_input", "params": [S("c_bus_v", 35, "assumption", why="母线电容用 35 V 的可以吗？")]}],
    )
    fixed = dict(
        GOOD,
        units=GOOD["units"]
        + [{"type": "bus_input", "params": [S("c_bus_v", 63, "rule", why="48 V × 1.25 = 60 V，取 63 V")]}],
    )
    m = fake(weak, fixed)
    res = draft.run(REQ, m, template)
    assert len(res["rounds"]) == 2 and m.seen[0] is None
    assert any(x["name"] == "母线电容耐压" for x in m.seen[1]["fails"])  # 第二轮带上了不通过的项
    assert res["rounds"][0]["result"]["fails"] and res["final"]["passed"]


def test_not_json_is_rejected(catalog):
    rep = check("48 V please", REQ, catalog)
    assert rep["rejected"] and set(rep["missing"]) == {"bus_voltage_v", "phase_current_a", "phase_current_peak_a"}


def test_person_edits_keep_or_replace_provenance(template, catalog):
    rep = check(GOOD, REQ, catalog)
    vals = {
        "spec": {k: e["value"] for k, e in rep["spec"].items()},
        "params": {"gate_drive": {"RG_OHM": 10.0}, "encoder": {"lines": 2500}},
    }
    vals["spec"]["bus_voltage_v"] = 36
    new, probs = draft.merge_edits(rep, vals, catalog)
    assert not probs
    assert new["spec"]["bus_voltage_v"]["source"] == "person"
    assert new["spec"]["phase_current_a"]["source"] == "requirement"
    assert new["params"]["encoder"]["lines"]["source"] == "requirement"
    assert "gate_drive" not in new["params"]  # 和模板一样：沿用模板
    doc = draft.apply(template, new, REQ)
    out = draft.evaluate(doc)
    assert out["count"][c.FAIL] == 0 and "36" in out["markdown"]
    _, probs = draft.merge_edits(rep, {"spec": {"bus_voltage_v": 400}}, catalog)
    assert probs and "超出" in probs[0]
