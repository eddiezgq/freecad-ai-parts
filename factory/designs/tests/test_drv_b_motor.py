# -*- coding: utf-8 -*-
"""第 102 轮：驱动板 B 版固件的电机控制与 CAN 在 Renode 里场景全过（第 107、110 轮各加四个）；寄存器与 ST 官方头文件核对过的数一致；
控制器标称参数与仿真对象一致；参数来源标明。（重新编译、重跑仿真在 CI“电路板设计（KiCad）”任务里，这里只读产物。）"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.join(os.path.dirname(HERE), "drv-joint-b", "fw")


def _t(p):
    return open(os.path.join(FW, p), encoding="utf-8").read()


def test_six_motor_scenarios_pass():
    s = json.load(open(os.path.join(FW, "out", "sim_motor.json"), encoding="utf-8"))
    assert s["all_pass"] and [x["id"] for x in s["scenarios"]] == ["boot", "cur", "spd", "pos", "hold", "prot",
                                                                   "abs", "ssi", "slip", "stop",      # 第 107 轮加四个
                                                                   "brk_boot", "brk_uv", "brk_ssi", "brk_stop",   # 第 110 轮加四个
                                                                   "brk_open", "brk_short", "brk_fet"]            # 第 114 轮加三个
    for sc in s["scenarios"]:
        assert sc["checks"] and all(c["ok"] for c in sc["checks"]), sc["id"]
        assert len(sc["series"]["t"]) == len(sc["series"]["iq"]) == len(sc["series"]["joint"])
    ids = {f["id"] for sc in s["scenarios"] for f in sc["frames"]}
    assert {"0x201", "0x181", "0x701", "0x081"} <= ids
    assert 0 < s["firmware"]["flash"] <= 128 * 1024 and s["firmware"]["ram"] <= 22 * 1024
    src = {p["source"] for p in s["params"]}
    assert any("零件库" in x for x in src) and any(x == "示例" for x in src)
    assert "示例" in s["disclaimer"] and "不投产" in s["disclaimer"]
    # 编码器的六个场景（第 100 轮）在新固件上照旧全过
    assert json.load(open(os.path.join(FW, "out", "sim.json"), encoding="utf-8"))["all_pass"]


# 对照 ST 官方 CMSIS 头文件 stm32g431xx.h（cmsis_device_g4）与 HAL stm32g4xx_hal_fdcan.c 核对过的数（2026-11-06）
CMSIS = {
    "TIM1_BASE": 0x40012C00, "ADC1_BASE": 0x50000000, "FDCAN1_BASE": 0x40006400, "SRAMCAN_BASE": 0x4000A400,
    "SPI1_BASE": 0x40013000, "SPI3_BASE": 0x40003C00, "TIM4_BASE": 0x40000800, "RCC_BASE": 0x40021000, "GPIOA_BASE": 0x48000000, "GPIOB_BASE": 0x48000400,
    "SRAMCAN_RF0SA": 0x0B0, "SRAMCAN_TFQSA": 0x278, "SRAMCAN_ESIZE": 72,
    "IRQ_ADC1_2": 18, "IRQ_FDCAN1_IT0": 21,
}
OFFSETS = {  # 寄存器 → (基址名, 偏移)
    "TIM1_CR1": 0x00, "TIM1_CR2": 0x04, "TIM1_EGR": 0x14, "TIM1_CCMR1": 0x18, "TIM1_CCMR2": 0x1C, "TIM1_CCER": 0x20,
    "TIM1_PSC": 0x28, "TIM1_ARR": 0x2C, "TIM1_RCR": 0x30, "TIM1_CCR1": 0x34, "TIM1_CCR2": 0x38, "TIM1_CCR3": 0x3C, "TIM1_BDTR": 0x44,
    "ADC1_ISR": 0x00, "ADC1_IER": 0x04, "ADC1_CR": 0x08, "ADC1_JSQR": 0x4C,
    "FDCAN1_CCCR": 0x018, "FDCAN1_NBTP": 0x01C, "FDCAN1_IR": 0x050, "FDCAN1_IE": 0x054, "FDCAN1_ILE": 0x05C,
    "FDCAN1_RXGFC": 0x080, "FDCAN1_RXF0S": 0x090, "FDCAN1_RXF0A": 0x094, "FDCAN1_TXFQS": 0x0C4, "FDCAN1_TXBAR": 0x0CC,
    "ADC1_SMPR2": 0x18, "ADC1_SQR1": 0x30, "ADC1_DR": 0x40,   # 第 114 轮
    "TIM4_CR1": 0x00, "TIM4_EGR": 0x14, "TIM4_CCMR1": 0x18, "TIM4_CCER": 0x20, "TIM4_PSC": 0x28, "TIM4_ARR": 0x2C, "TIM4_CCR1": 0x34,   # 第 110 轮
    "RCC_CR": 0x00, "RCC_CFGR": 0x08, "RCC_PLLCFGR": 0x0C, "RCC_AHB2ENR": 0x4C, "RCC_APB1ENR1": 0x58, "RCC_APB2ENR": 0x60, "RCC_CCIPR": 0x88,
}


def test_registers_match_cmsis():
    regs = _t("src/regs.h")
    for name, v in CMSIS.items():
        m = re.search(r"#define {} (0x[0-9A-Fa-f]+|\d+)u?\b".format(name), regs)
        assert m and int(m.group(1), 0) == v, name
    for name, off in OFFSETS.items():
        m = re.search(r"#define {} REG\((\w+) \+ (0x[0-9A-Fa-f]+)\)".format(name), regs)
        assert m and int(m.group(2), 16) == off, name
    # 平台描述里的地址、中断号与固件一致
    repl = _t("renode/stm32g431.repl")
    for frag in ("WqTim1Motor @ sysbus 0x40012C00", "WqAdc1 @ sysbus 0x50000000", "WqFdcan1 @ sysbus 0x40006400",
                 "sramcan: Memory.MappedMemory @ sysbus 0x4000A400", "IRQ -> nvic@18", "IRQ -> nvic@21"):
        assert frag in repl, frag
    assert "spi3: SPI.STM32SPI @ sysbus 0x40003C00" in repl and "#define RCC_SPI3EN (1u << 15)" in regs   # 第 107 轮：SPI3 读 SSI
    assert "WqTim4Brake @ sysbus 0x40000800" in repl and "#define RCC_TIM4EN (1u << 2)" in regs          # 第 110 轮：TIM4 抱闸
    # PB6 = TIM4_CH1 复用功能 AF2（ST 引脚数据，Zephyr hal_stm32 stm32g431c(6-8-b)tx-pinctrl.dtsi：tim4_ch1_pb6）；与 B 版原理图 43 脚一致
    br = _t("src/brake.c")
    assert "(2u << 24)" in br and "(2u << 12)" in br and "(6u << 4) | (1u << 3)" in br
    # 向量表：ADC1_2 在 16 + 18、FDCAN1_IT0 在 16 + 21
    st = _t("src/startup.c")
    assert "ADC1_2_IRQHandler, D, D, FDCAN1_IT0_IRQHandler" in st


def test_controller_matches_plant_and_board():
    h, cs = _t("src/motor.h"), _t("renode/WqDrive.cs")
    pairs = [("POLE_PAIRS 5", "int P = 5"), ("R_PHASE 0.12f", "Rs = 0.12"), ("L_PHASE 0.0002f", "Ls = 0.0002"),
             ("KT 0.15f", "Kt = 0.15"), ("GEAR 100", "N = 100.0")]
    for a, b in pairs:
        assert a in h and b in cs, (a, b)
    # 采样链与第 88 轮设计一致：2 mΩ × 20 = 40 mV/A，零点 1.65 V；母线分压 6.8 / 108.8（R1 + R2 = 102 k，R3 = 6.8 k）
    mc = _t("src/motor.c")
    assert "0.04f" in mc and "108.8f / 6.8f" in mc and "1.65 + 0.04 * ia" in cs and "6.8 / 108.8" in cs
    proto = _t("src/can_proto.h")
    for frag in ("0x201", "0x181", "0x081", "0x701", "过流", "欠压", "编码器", "通信超时", "输出端编码器", "不一致", "受控停车"):
        assert frag in proto
