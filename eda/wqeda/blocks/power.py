# -*- coding: utf-8 -*-
"""功能块：母线输入与电压检测（bus_input）、辅助电源（aux_supply）。

生成器只算由公式定的数（分压电阻、降压电感、反馈电阻、端子标注）；器件选型（电容耐压、二极管、芯片）是块参数，
由人或 AI 提议，计算器按规格校核。示例设计，数值为示例值。"""

from __future__ import annotations

from . import common as c

FP_R = "Resistor_SMD:R_0402_1005Metric"
FP_C = "Capacitor_SMD:C_0402_1005Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"


# ------------------------------------------------------------------------------------------------- 母线输入与电压检测


def bus_divider(p, spec):
    """母线电压检测分压：上臂两只相同电阻串联（分担电压），下臂固定；母线额定电压时 ADC 端 = 目标电压"""
    vbus, vt = spec["bus_voltage_v"], p["v_adc_target"]
    rb = c.parse(p["r_div_bottom"])
    r_top = rb * (vbus / vt - 1)
    each = c.nearest(r_top / 2, "E24")
    v_adc = vbus * rb / (2 * each + rb)
    v_fs = p["v_adc_fs"] * (2 * each + rb) / rb
    return {"r_top_need": r_top, "r_each": each, "v_adc": v_adc, "v_fs": v_fs}


def c_bus_value(p):
    """母线电容标注：容量（C_BUS_UF）/ 耐压（c_bus_v），例如 470u/63V"""
    return "{}/{:g}V".format(c.fmt(p["C_BUS_UF"] * 1e-6), p["c_bus_v"])


def gen_bus_input(block, spec, d):
    p, k = block["params"], block["key"]
    dv = bus_divider(p, spec)
    r = c.fmt(dv["r_each"])
    return [
        c.part(
            "J1",
            "Connector:Screw_Terminal_01x02",
            "{:g}V IN".format(spec["bus_voltage_v"]),
            "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
            k,
            {"1": "VBUS", "2": "GND"},
            "CONN-PWR",
        ),
        c.part(
            "NT10",
            "Device:NetTie_2",
            "NetTie",
            "NetTie:NetTie-2_SMD_Pad0.5mm",
            k,
            {"1": "VBUS", "2": "VBUS_AUX"},
            None,
            "辅助电源从母线单独引出",
        ),
        c.part(
            "C1",
            "Device:C_Polarized",
            c_bus_value(p),
            "Capacitor_SMD:CP_Elec_16x17.5",
            k,
            {"1": "VBUS", "2": "GND"},
            "CAP-BULK",
            "母线电容（例题 3）",
        ),
        c.two("R1", "Device:R", r, "VBUS_AUX", "VB_MID", k, FP_R, "RES-0402", "母线电压分压"),
        c.two("R2", "Device:R", r, "VB_MID", "VBUS_SNS", k, FP_R, "RES-0402"),
        c.two("R3", "Device:R", p["r_div_bottom"], "VBUS_SNS", "GND", k, FP_R, "RES-0402"),
        c.two("C2", "Device:C", p["c_filter"], "VBUS_SNS", "GND", k, FP_C, "CAP-0402"),
    ]


def calc_bus_input(block, spec, d, parts):
    p = block["params"]
    vbus, m = spec["bus_voltage_v"], d["derating"]
    dv = bus_divider(p, spec)
    rb = c.parse(p["r_div_bottom"])
    items = [
        c.item(
            "r_top",
            "分压上臂（两只串联）",
            dv["r_top_need"],
            "Ω",
            "R_上 = R_下 · (V_母线 / V_目标 − 1)",
            note="R_下 = {}，V_目标 = {:g} V".format(p["r_div_bottom"], p["v_adc_target"]),
        ),
        c.item("r_each", "上臂每只（E24 最接近）", dv["r_each"], "Ω", "R_上 / 2 取 E24"),
        c.item("v_adc", "额定母线时 ADC 端电压", dv["v_adc"], "V", "V_母线 · R_下 / (2R + R_下)"),
        c.item(
            "v_fs",
            "母线电压满量程",
            dv["v_fs"],
            "V",
            "V_ADC满量程 · (2R + R_下) / R_下",
            note="ADC 满量程 {:g} V".format(p["v_adc_fs"]),
        ),
        c.item(
            "p_div", "分压电阻功耗（每只上臂）", (vbus / (2 * dv["r_each"] + rb)) ** 2 * dv["r_each"], "W", "I² · R"
        ),
    ]
    checks = [
        c.judge(
            "v_fs",
            "满量程高于母线（留余量）",
            vbus * m["sense_headroom"],
            dv["v_fs"],
            "V",
            "V_满量程 ≥ {:g} × V_母线".format(m["sense_headroom"]),
        ),
        c.judge(
            "c_bus_v",
            "母线电容耐压",
            vbus * m["capacitor"],
            p["c_bus_v"],
            "V",
            "耐压 ≥ {:g} × V_母线".format(m["capacitor"]),
        ),
    ]
    return items, checks


# ------------------------------------------------------------------------------------------------- 辅助电源


def buck(p, spec):
    """降压电感 L = (Vin − Vo)·Vo / (Vin·f·ΔI)，ΔI = 纹波比 × 输出电流；反馈 Vo = Vref·(1 + Rt/Rb)"""
    vin, vo = spec["bus_voltage_v"], p["v_out"]
    f, di = p["f_sw_mhz"] * 1e6, p["ripple_ratio"] * p["i_out_a"]
    lneed = (vin - vo) * vo / (vin * f * di)
    rb = c.parse(p["r_fb_bottom"])
    rt = rb * (vo / p["v_ref"] - 1)
    return {"l_need": lneed, "l": c.nearest(lneed, "E6"), "rt_need": rt, "rt": c.nearest(rt, "E96"), "di": di}


def gen_aux_supply(block, spec, d):
    p, k = block["params"], block["key"]
    b = buck(p, spec)
    return [
        c.part(
            "U1",
            "Regulator_Switching:LMR16006YQ",
            "LMR16006YQ",
            "Package_TO_SOT_SMD:SOT-23-6",
            k,
            {"1": "SW_CB", "2": "GND", "3": "FB12", "4": "EN12", "5": "VBUS_AUX", "6": "SW12"},
            "IC-BUCK",
            "{:g} V → {:g} V 降压（示例选型）".format(spec["bus_voltage_v"], p["v_out"]),
        ),
        c.two("C3", "Device:C", p["c_in"], "VBUS_AUX", "GND", k, FP_C1206, "CAP-1206"),
        c.two("R4", "Device:R", "100k", "VBUS_AUX", "EN12", k, FP_R, "RES-0402", "使能上拉"),
        c.two("C4", "Device:C", "100n", "SW_CB", "SW12", k, FP_C, "CAP-0402", "自举电容"),
        c.part(
            "D1",
            "Device:D_Schottky",
            p["d_freewheel"],
            "Diode_SMD:D_SMA",
            k,
            {"1": "SW12", "2": "GND"},
            "DIO-SMD",
            "续流二极管",
        ),
        c.part(
            "L1", "Device:L", c.fmt(b["l"]), "Inductor_SMD:L_Bourns_SRN6045TA", k, {"1": "SW12", "2": "+12V"}, "IND-PWR"
        ),
        c.two("R5", "Device:R", c.fmt(b["rt"]), "+12V", "FB12", k, FP_R, "RES-0402", "反馈上电阻"),
        c.two("R6", "Device:R", p["r_fb_bottom"], "FB12", "GND", k, FP_R, "RES-0402", "反馈下电阻"),
        c.two("C5", "Device:C", p["c_out"], "+12V", "GND", k, FP_C1206, "CAP-1206"),
        c.part(
            "U2",
            "Regulator_Linear:AMS1117-5.0",
            "AMS1117-5.0",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            k,
            {"1": "GND", "2": "+5V", "3": "+12V"},
            "IC-LDO",
        ),
        c.two("C6", "Device:C", "10u/25V", "+5V", "GND", k, FP_C1206, "CAP-1206"),
        c.part(
            "U3",
            "Regulator_Linear:AMS1117-3.3",
            "AMS1117-3.3",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            k,
            {"1": "GND", "2": "+3V3", "3": "+5V"},
            "IC-LDO",
        ),
        c.two("C7", "Device:C", "10u/25V", "+3V3", "GND", k, FP_C1206, "CAP-1206"),
    ]


def calc_aux_supply(block, spec, d, parts):
    p = block["params"]
    vbus, m = spec["bus_voltage_v"], d["derating"]
    b = buck(p, spec)
    dev = d["devices"]
    items = [
        c.item(
            "l_need",
            "降压电感（计算）",
            b["l_need"],
            "H",
            "L = (V_in − V_o)·V_o / (V_in · f · ΔI)",
            note="f = {:g} MHz，ΔI = {:g} × {:g} A".format(p["f_sw_mhz"], p["ripple_ratio"], p["i_out_a"]),
        ),
        c.item("l", "降压电感（E6 最接近）", b["l"], "H", "取 E6"),
        c.item(
            "rt_need",
            "反馈上电阻（计算）",
            b["rt_need"],
            "Ω",
            "R_上 = R_下 · (V_o / V_ref − 1)",
            note="V_ref = {:g} V（{}），R_下 = {}".format(
                p["v_ref"], p.get("v_ref_source", "块参数"), p["r_fb_bottom"]
            ),
        ),
        c.item("rt", "反馈上电阻（E96 最接近）", b["rt"], "Ω", "取 E96"),
        c.item(
            "vo_real",
            "实际输出电压",
            p["v_ref"] * (1 + b["rt"] / c.parse(p["r_fb_bottom"])),
            "V",
            "V_ref · (1 + R_上/R_下)",
        ),
    ]
    checks = [
        c.judge(
            "c_in_v",
            "降压输入电容耐压",
            vbus * m["capacitor"],
            c.rating(p["c_in"]),
            "V",
            "耐压 ≥ {:g} × V_母线".format(m["capacitor"]),
        ),
        c.judge(
            "d_v",
            "续流二极管反向耐压",
            vbus * m["diode"],
            c.rating(p["d_freewheel"]),
            "V",
            "耐压 ≥ {:g} × V_母线".format(m["diode"]),
        ),
        dev.judge("LMR16006YQ", "vin_max", "降压芯片最高输入电压", vbus, "V", "V_in,max ≥ V_母线"),
        dev.judge("AMS1117-5.0", "vin_abs_max", "5 V 稳压器最高输入电压", p["v_out"], "V", "≥ 12 V 输入"),
    ]
    return items, checks
