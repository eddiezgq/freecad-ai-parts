# -*- coding: utf-8 -*-
"""第 159 轮 159f：平缝机控制器 CTRL-LS 的固件在 Renode 里四个场景全过；固件用的引脚与原理图 U10 一致（按 KiCad 官方符号库的脚名）；
寄存器与 ST 官方头文件核对过的数一致；控制器的标称参数与仿真对象一致；一转负载表与第 138 轮 G2 一致；参数来源标明。
（重新编译、重跑仿真在 CI“电路板设计（KiCad）”任务里，这里只读产物。）"""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(os.path.dirname(HERE), "ctrl-ls", "fw")
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SYM = "/usr/share/kicad/symbols/MCU_ST_STM32G4.kicad_sym"
# 159c 的复算结果、第 138 轮的机构模型只在问渠仓库里（freecad-ai-parts 同步了 factory/，没有 docs/ 和 tools/wqls/）
REF159C = os.path.join(ROOT, "docs", "设计", "WQ-LS", "GC", "控制器仿真", "仿真结果.json")
WQLS = os.path.join(ROOT, "tools", "wqls")


def _t(p):
    return open(os.path.join(FW, p), encoding="utf-8").read()


def _sim():
    return json.load(open(os.path.join(FW, "out", "sim_sew.json"), encoding="utf-8"))


def test_four_scenarios_pass():
    s = _sim()
    assert s["all_pass"] and [x["id"] for x in s["scenarios"]] == ["cycle", "seam", "jam", "stall"]
    for sc in s["scenarios"]:
        assert sc["checks"] and all(c["ok"] for c in sc["checks"]), sc["id"]
        n = len(sc["series"]["t"])
        assert all(len(v) == n for v in sc["series"].values()), sc["id"]
    assert 0 < s["firmware"]["flash"] <= 128 * 1024 and s["firmware"]["ram"] <= 22 * 1024
    src = {p["source"] for p in s["params"]}
    assert any("159c" in x for x in src) and any(x.startswith("示例") for x in src) and any("设计描述" in x for x in src)
    assert "示例" in s["disclaimer"] and "未选型" in s["disclaimer"]


@pytest.mark.skipif(not os.path.exists(REF159C), reason="159c 的复算结果只在问渠仓库里")
def test_cycle_compared_with_159c():
    """场景 ① 每一项和 159c 对照的都写了 159c 的数"""
    s = _sim()
    cyc = s["scenarios"][0]
    vs = [c for c in cyc["checks"] if c["vs"]]
    assert len(vs) >= 6 and all("159c" in c["vs"] for c in vs)
    ref = json.load(open(REF159C, encoding="utf-8"))["servo"]
    assert any("{:.4f}".format(ref["t_reach_5000_s"]) in c["vs"] for c in vs)
    assert any("{:.4f}".format(ref["t_from_release_s"]) in c["vs"] for c in vs)


def test_seam_sequence():
    """场景 ② 电磁铁顺序：倒缝 → 剪线 → 拨线 → 抬压脚；剪线电磁铁吸合时主轴在 200°–330°"""
    sc = _sim()["scenarios"][1]
    seq = [(x["name"], x["on"]) for x in sc["solenoids"]]
    assert seq == [("倒缝", 1), ("倒缝", 0), ("剪线", 1), ("剪线", 0), ("拨线", 1), ("拨线", 0), ("抬压脚", 1), ("抬压脚", 0)]
    tr = [x for x in sc["solenoids"] if x["name"] == "剪线"]
    assert 200 <= tr[0]["ang"] <= 202 and 330 <= tr[1]["ang"] <= 332


@pytest.mark.skipif(not os.path.exists(SYM), reason="没有 KiCad 官方符号库")
def test_pins_match_schematic():
    """固件注释和代码里用的引脚，与原理图上 U10 各脚接的网络一致（脚名取 KiCad 官方符号库 STM32G431C_6-8-B_Tx）"""
    t = open(SYM, encoding="utf-8").read()
    i = t.index('(symbol "STM32G431C_6-8-B_Tx"')
    blk = t[i:t.index('\n  (symbol "', i + 10)]
    name = {int(m.group(2)): m.group(1) for m in re.finditer(r'\(pin \w+ \w+.*?\(name "([^"]+)".*?\(number "(\d+)"', blk, re.S)}
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import ctrl_ls as D

    u = next(p for p in D.PARTS if p["ref"] == "U10")
    net = {name[int(k)]: v for k, v in u["pins"].items()}
    want = {"PA5": "SOL_TRIM", "PA11": "SOL_WIPE", "PA12": "SOL_REV", "PA15": "SOL_FOOT", "PB12": "IPM_SD",
            "PA8": "PWM_UH", "PA9": "PWM_VH", "PA10": "PWM_WH", "PB13": "PWM_UL", "PB14": "PWM_VL", "PB15": "PWM_WL",
            "PA1": "ISNS_U", "PA7": "ISNS_V", "PB0": "ISNS_W", "PA0": "VBUS_SNS", "PB1": "PEDAL",
            "PB6": "ENC_A_F", "PB7": "ENC_B_F", "PA6": "ENC_Z_F"}
    for pin, n in want.items():
        assert net[pin] == n, pin
    sew = _t("src/sew.c")
    assert "static const uint32_t SOL_PIN[4] = {5, 11, 12, 15};" in sew          # 剪线 PA5、拨线 PA11、倒缝 PA12、抬压脚 PA15
    mot = _t("src/motor.c")
    assert "GPIO_BSRR(GPIOB_BASE) = 1u << 12;" in mot                           # IPM_SD = PB12
    assert "(GPIO_IDR(GPIOA_BASE) >> 6) & 1u" in mot                            # Z 相 = PA6


# 对照 ST 官方 CMSIS 头文件 stm32g431xx.h（cmsis_device_g4）与 LL 驱动 stm32g4xx_ll_adc.h 核对过的数（2026-11-13）
CMSIS = {"TIM1_BASE": 0x40012C00, "TIM4_BASE": 0x40000800, "ADC1_BASE": 0x50000000, "ADC2_BASE": 0x50000100, "OPAMP_BASE": 0x40010300,
         "RCC_BASE": 0x40021000, "GPIOA_BASE": 0x48000000, "GPIOB_BASE": 0x48000400, "GPIOC_BASE": 0x48000800, "IRQ_ADC1_2": 18,
         "ADC_CH_VOPAMP1": 13, "ADC_CH_VOPAMP2": 16, "ADC_CH_VOPAMP3": 18}
BITS = {"RCC_TIM4EN": 2, "RCC_SYSCFGEN": 0, "RCC_GPIOCEN": 2, "RCC_TIM1EN": 11, "RCC_ADC12EN": 13,
        "OPAMP_CSR_EN": 0, "OPAMP_CSR_HIGHSPEED": 7, "OPAMP_CSR_INTEN": 8}
OFFS = {"TIM4_SMCR": 0x08, "TIM4_CCMR1": 0x18, "TIM4_CCER": 0x20, "TIM4_CNT": 0x24, "TIM4_ARR": 0x2C,
        "TIM1_BDTR": 0x44, "TIM1_CCR3": 0x3C, "RCC_APB1ENR1": 0x58, "RCC_APB2ENR": 0x60, "RCC_AHB2ENR": 0x4C}


def test_registers_match_cmsis():
    regs = _t("src/regs.h")
    for k, v in CMSIS.items():
        m = re.search(r"#define {} (0x[0-9A-Fa-f]+|\d+)u?\b".format(k), regs)
        assert m and int(m.group(1), 0) == v, k
    for k, b in BITS.items():
        m = re.search(r"#define {} \(1u << (\d+)\)".format(k), regs)
        assert m and int(m.group(1)) == b, k
    for k, off in OFFS.items():
        m = re.search(r"#define {} REG\(\w+ \+ (0x[0-9A-Fa-f]+)\)".format(k), regs)
        assert m and int(m.group(1), 16) == off, k
    assert "#define OPAMP_CSR_VMSEL_PGA (2u << 5)" in regs and "#define OPAMP_CSR_GAIN8 (2u << 14)" in regs


def test_controller_matches_model():
    """控制器“知道”的标称值与仿真对象一致；功率模块的频率、死区、过流阈值与设计描述一致"""
    import yaml

    h, cs = _t("src/motor.h"), _t("renode/WqSew.cs")

    def c(name):
        return float(re.search(r"#define {} ([\d.e-]+)f?".format(name), h).group(1))

    def m(name):  # C# 常量（可能写成 a + b）
        expr = re.search(r"public const (?:double|int) {} = ([^;]+);".format(name), cs).group(1)
        return sum(float(x) for x in expr.split(" + "))

    assert c("KT") == m("Kt") and c("POLE_PAIRS") == m("P") and c("R_PHASE") == m("Rs") and c("L_PHASE") == m("Ls")
    assert abs(c("J_TOTAL") - m("J")) < 1e-9 and c("CNT_PER_REV") == m("Cpr") and c("PWM_HZ") == m("Fpwm")
    doc = yaml.safe_load(open(os.path.join(os.path.dirname(HERE), "ctrl-ls", "design.yaml"), encoding="utf-8"))
    un = {u["type"]: u["params"] for b in doc["blocks"] for u in b["units"]}
    assert un["ipm_inverter"]["f_pwm"] == c("PWM_HZ") and un["ipm_inverter"]["t_dead"] == m("Dead")
    assert un["low_side_sense"]["i_trip"] == c("I_TRIP") and un["low_side_sense"]["gain"] == 8
    assert un["sensor_inputs"]["encoder_lines"] * 4 == c("CNT_PER_REV")
    # 死区 DTG：(64 + 21) × 2 / 170 MHz = 1.0 µs
    assert abs((64 + (0x95 & 0x3F)) * 2 / 170e6 - un["ipm_inverter"]["t_dead"]) < 1e-9 and "#define DTG_1US 0x95u" in h


@pytest.mark.skipif(not os.path.isdir(WQLS), reason="第 138 轮的机构模型只在问渠仓库里")
def test_load_table_matches_g2():
    """一转负载表是第 138 轮 G2 的（dyn.py 重算一致）；要 numpy，没有就跳过"""
    pytest.importorskip("numpy")
    sys.path.insert(0, FW)
    import gen_load

    w5, rows = gen_load.table()
    lines = [x for x in _t("renode/load_table.txt").splitlines() if not x.startswith("#")]
    assert lines[0] == "w5000 {:.6f}".format(w5) and len(lines) == 1 + 720
    for ln, r in zip(lines[1:], rows):
        assert ln == "{:.1f} {:.6f} {:.6f}".format(*r)


@pytest.mark.skipif(not os.path.isdir(WQLS), reason="第 138 轮的机构模型只在问渠仓库里")
def test_ref_159c_matches_model():
    """out/ref_159c.json 是 159c 同一个模型算的（要 numpy、matplotlib，没有就跳过）"""
    pytest.importorskip("numpy")
    pytest.importorskip("matplotlib")
    sys.path.insert(0, WQLS)
    import gc_sim

    old = gc_sim.T_PEAK
    try:
        gc_sim.T_PEAK = 3.0
        t_trim = 0.62 + 0.2
        lg = gc_sim.simulate(gc_sim.cycle(), f_s=40.0, ff=0.0, stop_at=(t_trim, 70.0), t_end=t_trim + 0.25, trim_window=(0.62, t_trim))
    finally:
        gc_sim.T_PEAK = old
    t, rpm, ang = lg[:, 0], lg[:, 1], lg[:, 3]
    m = (t >= 0.62) & (t <= t_trim) & (ang >= 200) & (ang <= 330)
    r = json.load(open(os.path.join(FW, "out", "ref_159c.json"), encoding="utf-8"))
    assert r["trim_rpm_mean"] == round(float(rpm[m].mean()), 2)
    assert r["t_decel_300_s"] == round(float(t[(t > 0.5) & (rpm <= 315)][0] - 0.5), 4)


def test_fw_json_and_zip():
    import zipfile

    d = json.load(open(os.path.join(FW, "out", "fw.json"), encoding="utf-8"))
    assert {f["path"] for f in d["files"]} >= {"src/sew.c", "src/motor.c", "renode/WqSew.cs", "run_sew.py"}
    for f in d["files"]:
        assert f["text"] == _t(f["path"]), f["path"]
    names = zipfile.ZipFile(os.path.join(FW, "out", "ctrl-ls-fw.zip")).namelist()
    assert "ctrl-ls-fw/build/fw.elf" in names and "ctrl-ls-fw/out/sim_sew.json" in names
