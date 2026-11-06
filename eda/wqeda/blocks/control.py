# -*- coding: utf-8 -*-
"""功能块：MCU 最小系统与烧录口（mcu_core）、编码器接口（encoder）、SSI 的 RS-485 收发（ssi_rs485）、CAN（can）。
示例设计，数值为示例值。"""

from __future__ import annotations

import math

from . import common as c

FP_R = "Resistor_SMD:R_0402_1005Metric"
FP_C = "Capacitor_SMD:C_0402_1005Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"


def _tp(ref, net, block, note):
    return c.part(ref, "Connector:TestPoint", net, FP_TP, block, {"1": net}, None, note)


def gen_mcu_core(block, spec, d):
    p, k = block["params"], block["key"]
    out = [
        c.part(
            "U10",
            "MCU_ST_STM32G4:STM32G431CBTx",
            p["mcu"],
            "Package_QFP:LQFP-48_7x7mm_P0.5mm",
            k,
            p["pin_map"],
            "IC-MCU-MC",
            p["mcu_note"],
        )
    ]
    out += [c.two(ref, "Device:C", "100n", "+3V3", "GND", k, FP_C, "CAP-0402") for ref in ("C40", "C41", "C42", "C43")]
    out += [
        c.two("C44", "Device:C", "4.7u", "+3V3", "GND", k, FP_C, "CAP-0402"),
        c.two("C45", "Device:C", "1u", "+3V3", "GND", k, FP_C, "CAP-0402", "VDDA"),
        c.two("C46", "Device:C", "100n", "NRST", "GND", k, FP_C, "CAP-0402"),
        c.two("R30", "Device:R", "10k", "BOOT0", "GND", k, FP_R, "RES-0402", "BOOT0 下拉"),
        c.part(
            "Y1",
            "Device:Crystal_GND24",
            p["xtal"],
            "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
            k,
            {"1": "OSC_IN", "2": "GND", "3": "OSC_OUT", "4": "GND"},
            "XTAL",
        ),
        c.two("C47", "Device:C", p["c_load"], "OSC_IN", "GND", k, FP_C, "CAP-0402"),
        c.two("C48", "Device:C", p["c_load"], "OSC_OUT", "GND", k, FP_C, "CAP-0402"),
        _tp("TP1", "SWDIO", k, "烧录口（烧录工位 PG-1 的弹簧针夹具）"),
        _tp("TP2", "SWCLK", k, "烧录口"),
        _tp("TP3", "NRST", k, "烧录口"),
        _tp("TP4", "+3V3", k, "烧录口供电"),
        _tp("TP5", "GND", k, "烧录口地"),
    ]
    return out


def calc_mcu_core(block, spec, d, parts):
    p, dev = block["params"], d["devices"]
    nets = set(p["pin_map"].values())
    need = {"ISNS_A", "ISNS_B", "ISNS_C", "VBUS_SNS", "SWDIO", "SWCLK", "NRST"}
    items = [c.item("pins", "已分配的 MCU 引脚", len(p["pin_map"]), "只")]
    checks = [
        c.judge(
            "pins",
            "电流、母线、烧录信号都接到 MCU",
            len(need),
            len(need & nets),
            "个",
            "缺：" + "、".join(sorted(need - nets)) if need - nets else "全部接上",
        ),
        dev.in_range(p["mcu"], "vdd_range", "MCU 供电 3.3 V 在工作范围内", 3.3, "V"),
        c.judge(
            "c_load",
            "晶振负载电容",
            None,
            None,
            "",
            "要晶振的负载电容 C_L 数据才能算（C = 2·(C_L − C_杂散)）",
            note="晶振型号与数据未录，判未知",
        ),
    ]
    return items, checks


# ------------------------------------------------------------------------------------------------- 编码器


def gen_encoder(block, spec, d):
    p, k = block["params"], block["key"]
    out = [
        c.part(
            "J3",
            "Connector_Generic:Conn_01x05",
            "ENC ABZ",
            "Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical",
            k,
            {"1": "+5V", "2": "GND", "3": "ENC_A", "4": "ENC_B", "5": "ENC_Z"},
            "CONN-SIG",
            "A/B/Z（{} 线，示例）".format(p["lines"]),
        )
    ]
    for i, s in enumerate(["A", "B", "Z"]):
        out.append(
            c.two(
                "R{}".format(31 + i),
                "Device:R",
                c.fmt(p["ENC_R_OHM"]),
                "ENC_" + s,
                "ENC_{}_F".format(s),
                k,
                FP_R,
                "RES-0402",
                "编码器滤波（例题 4）",
            )
        )
        out.append(
            c.two(
                "C{}".format(50 + i),
                "Device:C",
                c.fmt(p["ENC_C_PF"] * 1e-12),
                "ENC_{}_F".format(s),
                "GND",
                k,
                FP_C,
                "CAP-0402",
            )
        )
    return out


def encoder(p):
    tau = p["ENC_R_OHM"] * p["ENC_C_PF"] * 1e-12
    fe = p["rpm_max"] / 60 * p["lines"]
    return {"fc": 1 / (2 * math.pi * tau), "f_pulse": fe, "tau": tau}


def calc_encoder(block, spec, d, parts):
    p = block["params"]
    e = encoder(p)
    items = [
        c.item("fc", "RC 截止频率", e["fc"], "Hz", "f_c = 1 / (2π·R·C)"),
        c.item(
            "f_pulse",
            "最高转速时每路脉冲频率",
            e["f_pulse"],
            "Hz",
            "n_max / 60 × 线数",
            note="{:g} r/min，{} 线".format(p["rpm_max"], p["lines"]),
        ),
        c.item("delay", "RC 时间常数", e["tau"], "s", "τ = R·C"),
    ]
    checks = [
        c.judge(
            "fc",
            "截止频率高于脉冲频率（留余量）",
            p["fc_margin"] * e["f_pulse"],
            e["fc"],
            "Hz",
            "f_c ≥ {:g} × f_脉冲".format(p["fc_margin"]),
        )
    ]
    return items, checks


# ------------------------------------------------------------------------------------------------- SSI（RS-485）、CAN


def gen_ssi_rs485(block, spec, d):
    k = block["key"]
    p = block["params"]
    return [
        c.part(
            "U11",
            "Interface_UART:MAX3485",
            p["xcvr"],
            FP_SOIC8,
            k,
            {
                "1": "NC_U11",
                "2": "+3V3",
                "3": "+3V3",
                "4": "SSI_CLK",
                "5": "GND",
                "6": "SSIC_P",
                "7": "SSIC_N",
                "8": "+3V3",
            },
            "IC-RS485",
            "SSI 时钟发送（示例选型）",
        ),
        c.part(
            "U12",
            "Interface_UART:MAX3485",
            p["xcvr"],
            FP_SOIC8,
            k,
            {
                "1": "SSI_DATA",
                "2": "GND",
                "3": "GND",
                "4": "GND",
                "5": "GND",
                "6": "SSID_P",
                "7": "SSID_N",
                "8": "+3V3",
            },
            "IC-RS485",
            "SSI 数据接收",
        ),
        c.two("C53", "Device:C", "100n", "+3V3", "GND", k, FP_C, "CAP-0402"),
        c.two("C54", "Device:C", "100n", "+3V3", "GND", k, FP_C, "CAP-0402"),
        c.two("R34", "Device:R", c.fmt(p["r_term"]), "SSID_P", "SSID_N", k, FP_R, "RES-0402", "终端电阻"),
        c.part(
            "J4",
            "Connector_Generic:Conn_01x06",
            "ENC SSI",
            "Connector_JST:JST_XH_B6B-XH-A_1x06_P2.50mm_Vertical",
            k,
            {"1": "+5V", "2": "GND", "3": "SSIC_P", "4": "SSIC_N", "5": "SSID_P", "6": "SSID_N"},
            "CONN-SIG",
            "输出端绝对值编码器",
        ),
    ]


def gen_can(block, spec, d):
    k = block["key"]
    p = block["params"]
    return [
        c.part(
            "U13",
            "Interface_CAN_LIN:MCP2562-E-SN",
            p["xcvr"],
            FP_SOIC8,
            k,
            {"1": "CAN_TXD", "2": "GND", "3": "+5V", "4": "CAN_RXD", "5": "+3V3", "6": "CANL", "7": "CANH", "8": "GND"},
            "IC-CAN",
            "CAN 收发（示例选型）",
        ),
        c.two("C55", "Device:C", "100n", "+5V", "GND", k, FP_C, "CAP-0402"),
        c.two("C56", "Device:C", "100n", "+3V3", "GND", k, FP_C, "CAP-0402"),
        c.two("R35", "Device:R", c.fmt(p["r_term"]), "CANH", "CANL", k, FP_R, "RES-0402", "CAN 终端电阻"),
        c.part(
            "J5",
            "Connector_Generic:Conn_01x04",
            "CAN",
            "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical",
            k,
            {"1": "CANH", "2": "CANL", "3": "GND", "4": "+5V"},
            "CONN-SIG",
        ),
    ]


def _match(p):
    ok = abs(p["r_term"] - p["z_cable"]) < 1e-9
    return c.judge(
        "r_term",
        "终端电阻与电缆阻抗一致",
        p["z_cable"],
        p["r_term"],
        "Ω",
        "R_终端 = Z_电缆",
        status=c.PASS if ok else c.FAIL,
    )


def calc_ssi_rs485(block, spec, d, parts):
    p, dev = block["params"], d["devices"]
    items = [
        c.item("r_term", "终端电阻", p["r_term"], "Ω", note="等于电缆特性阻抗（块参数 {:g} Ω）".format(p["z_cable"]))
    ]
    checks = [_match(p), dev.in_range(p["xcvr"], "vcc_range", "收发器供电 3.3 V 在工作范围内", 3.3, "V")]
    return items, checks


def calc_can(block, spec, d, parts):
    p, dev = block["params"], d["devices"]
    items = [c.item("r_term", "终端电阻", p["r_term"], "Ω", note="总线两端各一只")]
    checks = [
        _match(p),
        dev.in_range(p["xcvr"], "vdd_range", "CAN 收发器 VDD 5 V 在工作范围内", 5.0, "V"),
        dev.in_range(p["xcvr"], "vio_range", "CAN 收发器 VIO 3.3 V 在工作范围内", 3.3, "V"),
    ]
    return items, checks
