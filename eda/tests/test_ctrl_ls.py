# -*- coding: utf-8 -*-
"""第 159 轮 159b：平缝机控制器 CTRL-LS 的新功能块计算器，逐项与手算对照。
手算只用规格（design.yaml 的 spec）和规格书上的数（eda/parts），一步一步写在这里，不调被测函数。"""

import math
import os
import shutil

import pytest

from wqeda import blocks, calcbook, parts, sim_ctrl
from wqeda.blocks import common as c
from wqeda.schema import design

HERE = os.path.dirname(os.path.abspath(__file__))
DESIGN = os.path.join(HERE, "..", "..", "factory", "designs", "ctrl-ls", "design.yaml")
pytestmark = pytest.mark.skipif(not os.path.exists(DESIGN), reason="没有 CTRL-LS 设计描述")


@pytest.fixture(scope="module")
def book():
    return calcbook.build(DESIGN, sim=False)


def unit(book, t):
    return next(u for u in book["units"] if u["type"] == t)


def item(book, t, key):
    return next(i for i in unit(book, t)["items"] if i["key"] == key)["value"]


def check(book, t, key):
    return next(x for x in unit(book, t)["checks"] if x["key"] == key)


def test_power_budget_by_hand(book):
    p_bus = 550 / 0.90 / 0.97 + 40  # 电机额定 ÷ η电机 ÷ η逆变 + 辅助
    p_in = p_bus / 0.95
    i_in = p_in / (90 * 0.99)
    assert item(book, "ac_input", "p_bus") == pytest.approx(p_bus, rel=1e-9)
    assert item(book, "ac_input", "i_in") == pytest.approx(i_in, rel=1e-9)
    assert i_in == pytest.approx(7.92, abs=0.01)
    # 浪涌：√2·250·1.1 / 2.5 Ω（热敏电阻 R25，规格书 p.4 Table 1）
    assert item(book, "ac_input", "i_inrush") == pytest.approx(math.sqrt(2) * 250 * 1.1 / 2.5, rel=1e-9)
    assert check(book, "ac_input", "cmc_i")["status"] == c.UNKNOWN  # 共模电感规格书读不出：未知，不是通过


def test_bridge_loss_by_hand(book):
    i_in = (550 / 0.90 / 0.97 + 40) / 0.95 / (90 * 0.99)
    i_avg = 2 * math.sqrt(2) / math.pi * i_in
    assert item(book, "bridge", "p_loss") == pytest.approx(2 * 1.1 * i_avg, rel=1e-9)  # V_F 1.1 V @ 10 A


def test_pfc_inductor_and_currents_by_hand(book):
    po = 550 / 0.90 / 0.97 + 40
    iin = po / 0.95 / 90
    ipk = math.sqrt(2) * iin
    di = 0.3 * ipk
    L = 195 * (1 - 195 / 390) / (65000 * di)  # V_x = V_o/2 = 195 V 在输入范围内
    assert item(book, "pfc_boost", "L") == pytest.approx(L, rel=1e-9)
    assert L == pytest.approx(451e-6, rel=0.01)
    iq = iin * math.sqrt(1 - 8 * math.sqrt(2) * 90 / (3 * math.pi * 390))
    assert item(book, "pfc_boost", "i_q_rms") == pytest.approx(iq, rel=1e-9)
    # 导通电阻：150 ℃ 典型 0.115 × 25 ℃ 最大/典型 0.060/0.049（IPW60R060P7 p.5 Table 4）
    assert item(book, "pfc_boost", "p_q_cond") == pytest.approx(iq**2 * 0.115 * 0.060 / 0.049, rel=1e-9)
    # 采样电阻上限 = 0.18 V / (1.2 × (I_峰 + ΔI/2))；选 10 mΩ 不超过
    assert item(book, "pfc_boost", "r_shunt_max") == pytest.approx(0.18 / (1.2 * (ipk + di / 2)), rel=1e-9)
    # 二倍工频纹波（峰峰）：电容电流 I_o·cos(2ωt)，幅值 I_o/(2ω·C)，峰峰 = P_o / (2π·50 Hz·3×330 µF·390 V)
    io = po / 390
    assert item(book, "pfc_boost", "dv_bus") == pytest.approx(2 * io / (2 * 2 * math.pi * 50 * 990e-6), rel=1e-9)
    # 分压上臂：20 k × (390/2.5 − 1)
    assert item(book, "pfc_boost", "r_vs_top") == pytest.approx(20e3 * (390 / 2.5 - 1), rel=1e-9)


def test_ipm_motor_and_losses_by_hand(book):
    w = 5000 * 2 * math.pi / 60
    kt = 1.5 * (300 / w) / math.sqrt(3)
    assert item(book, "ipm_inverter", "kt") == pytest.approx(kt, rel=1e-9)
    assert item(book, "ipm_inverter", "i_pk") == pytest.approx(3.0 / kt, rel=1e-9)
    ipk = max(0.58 / kt, 550 / w / kt)
    pc = 2.5 * ipk * (1 / (2 * math.pi) + 0.9 * 0.9 / 8)
    ps = (150e-6 + 110e-6) * 16000 * (390 / 300) * (ipk / 7) / math.pi
    assert item(book, "ipm_inverter", "p_igbt") == pytest.approx(pc + ps, rel=1e-9)
    # 量程 = 1.65 V / (8 × 25 mΩ) = 8.25 A
    assert item(book, "low_side_sense", "i_fs") == pytest.approx(8.25, rel=1e-9)
    assert check(book, "low_side_sense", "pga_gain")["status"] == c.UNKNOWN


def test_solenoid_release_by_hand(book):
    tau = 0.02 / 8
    vz = 29.50 + 0.95  # SMBJ24A V_BR,max + ES3D V_F,max
    assert item(book, "solenoid_drive", "t_off") == pytest.approx(tau * math.log(1 + 3.0 * 8 / vz), rel=1e-9)
    assert item(book, "solenoid_drive", "t_off_diode") == pytest.approx(tau * math.log(1 + 24 / 0.95), rel=1e-9)
    assert item(book, "solenoid_drive", "v_ds") == pytest.approx(24 * 1.1 + vz, rel=1e-9)


def test_flyback_by_hand(book):
    vmin = math.sqrt(2) * 90 * 0.9
    pin = (24 * 0.8 + 15 * 0.15 + 5 * 0.3) / 0.80
    dmax = 100 / (100 + vmin)
    ip = 2 * pin / (vmin * dmax)
    assert item(book, "flyback_aux", "i_pk") == pytest.approx(ip, rel=1e-9)
    assert item(book, "flyback_aux", "lp") == pytest.approx(vmin * dmax / (ip * 66000), rel=1e-9)
    assert item(book, "flyback_aux", "v_ds") == pytest.approx(390 * 1.08 + 150, rel=1e-9)


def test_heatsink_takes_the_tightest_device(book):
    hs = unit(book, "heatsink")
    total = item(book, "heatsink", "p_total")
    lim = min(i["value"] for i in hs["items"] if i["key"].startswith("ts"))
    assert item(book, "heatsink", "r_sa") == pytest.approx((lim - 50) / total, rel=1e-9)
    # 最紧的是功率模块的推荐壳温 100 ℃：T_s ≤ 100 − P_模块 × 0.5 K/W
    p_ipm = item(book, "ipm_inverter", "p_total")
    assert lim == pytest.approx(100 - p_ipm * 0.5, rel=1e-9)


def test_unchecked_data_never_passes_and_missing_data_is_unknown(book):
    """录了没核对的 → 待核对；没录的 → 未知；都不算通过（细则第二节第 2 条）"""
    st = [x["status"] for u in book["units"] for x in u["checks"]]
    assert c.FAIL not in st
    assert book["count"][c.UNKNOWN] >= 4
    dev = parts.Devices.load()
    dev.entries.pop("GBU1006")
    b2 = calcbook.build(DESIGN, sim=False, devices=dev)
    br = next(u for u in b2["units"] if u["type"] == "bridge")
    assert {x["status"] for x in br["checks"]} == {c.UNKNOWN}


def test_all_new_unit_types_registered():
    for t in (
        "ac_input",
        "bridge",
        "pfc_boost",
        "flyback_aux",
        "ipm_inverter",
        "low_side_sense",
        "solenoid_drive",
        "stepper",
        "panel_iso",
        "heatsink",
    ):
        assert t in blocks.CALCULATORS and t in blocks.NAMES


@pytest.mark.skipif(shutil.which("ngspice") is None, reason="没有 ngspice")
def test_spice_matches_formulas():
    """159c：校正级开关纹波、母线二倍工频纹波、掉电保持、电磁铁释放——仿真与公式相差都在容差里"""
    b = calcbook.build(DESIGN, sim=True)
    sims = {u["type"]: u["sim"] for u in b["units"] if u.get("sim")}
    assert set(sims) == {"pfc_boost", "solenoid_drive"}
    rows = [r for s in sims.values() for r in s["rows"]]
    assert len(rows) == 5 and all(r["status"] == c.PASS for r in rows)


def test_spice_formula_by_hand():
    """网表对照用的公式值也逐项手算（不调 ngspice）"""
    dev = parts.Devices.load()
    d = design.read_yaml(DESIGN)
    doc, spec = blocks.by_type(d), d["spec"]
    case = sim_ctrl.pfc_cases(spec, doc["pfc_boost"]["params"], dev)
    po = 550 / 0.90 / 0.97 + 40
    assert case["formulas"]["vripple"] == pytest.approx(po / (2 * math.pi * 50 * 990e-6 * 390), rel=1e-9)
    assert case["formulas"]["t_hold"] == pytest.approx(990e-6 * (390**2 - 300**2) / (2 * po), rel=1e-9)
    sol = sim_ctrl.solenoid_cases(spec, doc["solenoid_drive"]["params"], dev)
    vz = 29.50 + 0.95
    assert sol["formulas"]["t_off"] == pytest.approx(0.0025 * math.log((3 + vz / 8) / (0.03 + vz / 8)), rel=1e-9)
    assert sol["formulas"]["v_ds"] == pytest.approx(24 + vz, rel=1e-9)
