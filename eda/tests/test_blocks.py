# -*- coding: utf-8 -*-
"""功能块（第 104 轮）：E 系列与标注、各计算器的手算标准题、器件数据的“未知 / 待核对”、
48 V 生成一字不差、24 V 跟着变。"""

import json
import math
import os
import shutil

import pytest
from conftest import DESIGNS, EDA

from wqeda import blocks, calcbook, parts
from wqeda.blocks import common as c
from wqeda.blocks import control, drive, power
from wqeda.schema import design

A_PATH = os.path.join(DESIGNS, "drv-joint", "design.yaml")
V24 = os.path.join(EDA, "examples", "drv-joint-24v", "variant.yaml")


def unit(doc, t):
    return blocks.by_type(doc)[t]


@pytest.fixture(scope="module")
def doc():
    return design.load_design(A_PATH)


def test_series_and_labels():
    assert c.nearest(23.8e-6, "E6") == pytest.approx(22e-6)
    assert c.nearest(15.87e-6, "E6") == pytest.approx(15e-6)
    assert c.nearest(146862.7, "E96") == pytest.approx(147000)
    assert c.nearest(23800, "E24") == pytest.approx(24000) and c.nearest(51000, "E24") == pytest.approx(51000)
    assert [c.fmt(x) for x in (51000, 6800, 147000, 10.0, 1000.0, 2.2e-10, 4.7e-6, 0.002)] == [
        "51k",
        "6.8k",
        "147k",
        "10",
        "1k",
        "220p",
        "4.7u",
        "2m",
    ]
    assert c.parse("470u/63V") == pytest.approx(470e-6) and c.parse("2m 1%") == pytest.approx(0.002)
    assert c.rating("470u/63V") == 63 and c.rating("60V 1A") == 60 and c.rating("60V 1A", "A") == 1
    assert c.rating("100n") is None


def test_generation_is_identical_to_round_102(doc):
    """48 V：功能块展开的电路 = 第 102 轮迁移时的器件清单（tests/data 里的快照，和当时的 YAML 展开逐字相等）"""
    with open(os.path.join(EDA, "tests", "data", "drv-joint-a-parts.json"), encoding="utf-8") as f:
        snap = json.load(f)
    got = design.expand(doc)["parts"]
    assert json.dumps(got, ensure_ascii=False) == json.dumps(snap, ensure_ascii=False)


def test_hand_calc_bus_and_aux(doc):
    spec = doc["spec"]
    dv = power.bus_divider(unit(doc, "bus_input")["params"], spec)
    assert dv["r_top_need"] == pytest.approx(6800 * (48 / 3.0 - 1))  # 102 kΩ
    assert dv["r_each"] == pytest.approx(51000) and dv["v_fs"] == pytest.approx(3.3 * 108800 / 6800)  # 52.8 V
    b = power.buck(unit(doc, "aux_supply")["params"], spec)
    assert b["l_need"] == pytest.approx((48 - 12) * 12 / (48 * 2.1e6 * 0.18))  # 23.81 µH
    assert b["l"] == pytest.approx(22e-6)
    assert b["rt_need"] == pytest.approx(10e3 * (12 / 0.765 - 1)) and b["rt"] == pytest.approx(147e3)


def test_hand_calc_sense_encoder_gate(doc):
    s = drive.sense(unit(doc, "current_sense")["params"], doc["spec"])
    assert s["range"] == pytest.approx(1.65 / (20 * 0.002))  # ±41.25 A
    assert s["swing_pk"] == pytest.approx(20 * 0.002 * 29.73)  # 1.189 V
    assert s["p_shunt"] == pytest.approx(8.5**2 * 0.002)
    e = control.encoder(unit(doc, "encoder")["params"])
    assert e["fc"] == pytest.approx(1 / (2 * math.pi * 1000 * 220e-12))  # 723 kHz
    assert e["f_pulse"] == pytest.approx(6000 / 60 * 2500)  # 250 kHz
    items, _ = drive.calc_gate_drive(
        unit(doc, "gate_drive"), doc["spec"], {"derating": doc["spec"]["derating"], "devices": parts.Devices({})}, []
    )
    assert items[0]["value"] == pytest.approx(12 / 10)


def test_device_data_unknown_pending_pass_fail():
    entry = {
        "part": "X1",
        "datasheet": {"title": "X1 ds", "revision": "r1"},
        "params": {"vds": {"value": 80, "where": "p.1", "checked": False}},
    }
    dev = parts.Devices({"X1": entry})
    assert dev.judge("X1", "vds", "耐压", 60)["status"] == c.PENDING  # 录了没核对：待核对，不算通过
    assert dev.judge("X1", "id", "电流", 10)["status"] == c.UNKNOWN  # 没录：未知
    assert dev.judge("Y9", "vds", "耐压", 60)["status"] == c.UNKNOWN
    entry["params"]["vds"]["checked"] = True
    assert dev.judge("X1", "vds", "耐压", 60)["status"] == c.PASS
    assert dev.judge("X1", "vds", "耐压", 90)["status"] == c.FAIL


def test_shipped_device_data_is_sourced_and_unchecked():
    dev = parts.Devices.load()
    assert {"BSC040N08NS5", "INA240A1D", "LMR16006YQ", "MAX3485", "STM32G431CBT6"} <= set(dev.entries)
    for m, e in dev.entries.items():
        assert e["datasheet"]["url"].startswith("https://") and e["datasheet"]["title"]
        for k, p in e["params"].items():
            assert p.get("where") and p.get("checked") is False, (m, k)


def test_calculators_on_drive_board(doc):
    res = blocks.calculate(doc, parts.Devices.load(), design.all_parts(doc))
    st = [ch["status"] for u in res for ch in u["checks"]]
    assert c.FAIL not in st
    assert c.PASS not in [ch["status"] for u in res for ch in u["checks"] if ch.get("note") == "待核对"]
    names = {u["type"] for u in res}
    assert names == set(blocks.CALCULATORS)


def test_24v_follows(doc):
    base, var = design.load_variant(V24)
    new, changes = design.apply_variant(base, var)
    assert changes == [("规格", "母线电压（V）：48 → 24")]
    d = calcbook.diff(base, new, parts.Devices.load())
    got = {(r["ref"], r["field"]): (r["base"], r["new"]) for r in d["parts"]}
    assert got == {
        ("J1", "数值"): ("48V IN", "24V IN"),
        ("R1", "数值"): ("51k", "24k"),
        ("R2", "数值"): ("51k", "24k"),
        ("L1", "数值"): ("22u", "15u"),
        ("U1", "说明"): ("48 V → 12 V 降压（示例选型）", "24 V → 12 V 降压（示例选型）"),
    }
    assert base == doc  # 底稿不动


def test_calcbook_without_sim_is_deterministic():
    b1 = calcbook.build(A_PATH, sim=False)
    b2 = calcbook.build(A_PATH, sim=False)
    assert calcbook.to_markdown(b1) == calcbook.to_markdown(b2)
    assert b1["count"][c.FAIL] == 0 and b1["count"][c.PENDING] > 0
    html = calcbook.to_html(b1)
    assert "<title>计算书 DRV-JOINT A</title>" in html and "待核对" in html


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="没有 ngspice")
def test_simulation_checks():
    b = calcbook.build(A_PATH, sim=True)
    sims = [u["sim"] for u in b["units"] if u.get("sim")]
    assert {s["example"] for s in sims} == {"sense", "gate", "bus", "encoder"}
    assert all(r["status"] == c.PASS for s in sims for r in s["rows"])
    b24 = calcbook.build(V24, sim=True)
    st = {u["type"]: [r["status"] for r in u["sim"]["rows"]] for u in b24["units"] if u.get("sim")}
    assert st["bus_input"] == [c.UNKNOWN] and st["gate_drive"] == [c.UNKNOWN]  # 例题母线写死 48 V，不拿来核对
    assert all(x == c.PASS for x in st["current_sense"] + st["encoder"])
