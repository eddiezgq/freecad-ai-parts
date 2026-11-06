# -*- coding: utf-8 -*-
"""功能块：三相半桥（half_bridge）、栅极驱动与自举（gate_drive）、相电流采样（current_sense）。

三块按相交错展开（每一相：上下管、吸收电容 → 驱动、栅极电阻、自举 → 采样电阻、开尔文引线、放大器），所以共用一个
生成器 phase_legs；计算器各算各的。示例设计，数值为示例值。"""

from __future__ import annotations

from . import common as c

FP_R = "Resistor_SMD:R_0402_1005Metric"
FP_C = "Capacitor_SMD:C_0402_1005Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"


def _tie(ref, a, b, block, note):
    return c.part(ref, "Device:NetTie_2", "NetTie", "NetTie:NetTie-2_SMD_Pad0.5mm", block, {"1": a, "2": b}, None, note)


def gen_phase_legs(blocks, spec, d):
    """blocks：{"half_bridge": 块, "gate_drive": 块, "current_sense": 块}"""
    hb, gd, cs = blocks["half_bridge"], blocks["gate_drive"], blocks["current_sense"]
    ph_, pg, ps = hb["params"], gd["params"], cs["params"]
    kb, kg, ks = hb["key"], gd["key"], cs["key"]
    rg = c.fmt(pg["RG_OHM"])
    shunt = "{} {}".format(c.fmt(ps["RS_MOHM"] * 1e-3), ps["shunt_tol"])
    out = []
    for i, ph in enumerate(ph_["phases"]):
        n = i + 1
        sw, gh, gl = "SW_" + ph, "GH_" + ph, "GL_" + ph
        out += [
            c.part(
                "Q{}".format(2 * i + 1),
                ph_["fet_lib"],
                ph_["fet"],
                ph_["fet_fp"],
                kb,
                {"1": sw, "2": sw, "3": sw, "4": gh, "5": "VBUS"},
                ph_["fet_item"],
                "{} 相上管（示例选型）".format(ph),
            ),
            c.part(
                "Q{}".format(2 * i + 2),
                ph_["fet_lib"],
                ph_["fet"],
                ph_["fet_fp"],
                kb,
                {"1": "GND", "2": "GND", "3": "GND", "4": gl, "5": sw},
                ph_["fet_item"],
                "{} 相下管".format(ph),
            ),
            c.two(
                "C{}".format(10 + n),
                "Device:C",
                ph_["c_snub"],
                "VBUS",
                "GND",
                kb,
                FP_C1206,
                "CAP-1206",
                "{} 相半桥就近吸收".format(ph),
            ),
            c.part(
                "U{}".format(3 + n),
                "Driver_FET:IR2101",
                pg["driver"],
                FP_SOIC8,
                kg,
                {
                    "1": "+12V",
                    "2": "PWM_{}H".format(ph),
                    "3": "PWM_{}L".format(ph),
                    "4": "GND",
                    "5": "LO_" + ph,
                    "6": "VS_" + ph,
                    "7": "HO_" + ph,
                    "8": "VB_" + ph,
                },
                "IC-GDRV",
                "{} 相半桥驱动（示例选型）".format(ph),
            ),
            c.two("R{}".format(10 + 2 * i), "Device:R", rg, "HO_" + ph, gh, kg, FP_R, "RES-0402", "栅极电阻（例题 2）"),
            c.two("R{}".format(11 + 2 * i), "Device:R", rg, "LO_" + ph, gl, kg, FP_R, "RES-0402"),
            c.part(
                "D{}".format(1 + n),
                "Device:D_Schottky",
                pg["d_boot"],
                "Diode_SMD:D_SOD-123",
                kg,
                {"1": "VB_" + ph, "2": "+12V"},
                "DIO-SMD",
                "自举二极管",
            ),
            c.two(
                "C{}".format(20 + n), "Device:C", pg["c_boot"], "VB_" + ph, "VS_" + ph, kg, FP_C, "CAP-0402", "自举电容"
            ),
            _tie("NT{}".format(6 + n), sw, "VS_" + ph, kg, "{} 相驱动参考点 VS 从采样电阻焊盘单独引出".format(ph)),
            c.two("C{}".format(23 + n), "Device:C", pg["c_vcc"], "+12V", "GND", kg, FP_C, "CAP-0402"),
            c.part(
                "R{}".format(20 + n),
                "Device:R",
                shunt,
                "Resistor_SMD:R_2512_6332Metric",
                ks,
                {"1": sw, "2": "MOT_" + ph},
                "RES-SHUNT",
                "{} 相采样电阻（例题 1），两端开尔文引线到 INA240".format(ph),
            ),
            _tie("NT{}".format(2 * i + 1), sw, "SNSP_" + ph, ks, "开尔文引线（采样电阻电源端）"),
            _tie("NT{}".format(2 * i + 2), "MOT_" + ph, "SNSN_" + ph, ks, "开尔文引线（采样电阻电机端）"),
            c.part(
                "U{}".format(6 + n),
                "Amplifier_Current:INA240A1D",
                ps["amp"],
                FP_SOIC8,
                ks,
                {
                    "1": "SNSN_" + ph,
                    "2": "GND",
                    "3": "GND",
                    "4": "GND",
                    "5": "ISNS_" + ph,
                    "6": "+3V3",
                    "7": "+3V3",
                    "8": "SNSP_" + ph,
                },
                "IC-AMP",
                "{} 相电流采样放大 {:g} 倍（示例选型）".format(ph, ps["GAIN"]),
            ),
            c.two("C{}".format(26 + n), "Device:C", "100n", "+3V3", "GND", ks, FP_C, "CAP-0402"),
            c.two(
                "C{}".format(29 + n), "Device:C", ps["c_aa"], "ISNS_" + ph, "GND", ks, FP_C, "CAP-0402", "ADC 抗混叠"
            ),
        ]
    out.append(
        c.part(
            "J2",
            "Connector:Screw_Terminal_01x03",
            "MOTOR UVW",
            "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3_1x03_P5.00mm_Horizontal",
            ks,
            {str(j + 1): "MOT_" + ph for j, ph in enumerate(ph_["phases"])},
            "CONN-PWR",
        )
    )
    return out


# ------------------------------------------------------------------------------------------------- 计算器


def calc_half_bridge(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    vbus, irat, ipk = spec["bus_voltage_v"], spec["phase_current_a"], spec["phase_current_peak_a"]
    rds = dev.value(p["fet"], "rds_on_max")
    items = [
        c.item("i_rated", "额定相电流", irat, "A", source=spec.get("current_source", "")),
        c.item("i_peak", "峰值相电流", ipk, "A", source=spec.get("current_source", "")),
    ]
    if rds is not None:
        items.append(
            c.item(
                "p_cond",
                "每管导通损耗（额定电流，最坏按全周期导通估）",
                irat**2 * rds,
                "W",
                "P = I² · R_DS(on),max",
                source=dev.source(p["fet"], "rds_on_max"),
                note=dev.note(p["fet"], "rds_on_max"),
            )
        )
    checks = [
        dev.judge(p["fet"], "vds", "功率管耐压", vbus * m["mosfet"], "V", "V_DS ≥ {:g} × V_母线".format(m["mosfet"])),
        dev.judge(p["fet"], "id_25c", "功率管电流（25 ℃ 壳温额定）", ipk, "A", "I_D ≥ 峰值相电流"),
        c.judge(
            "c_snub_v",
            "吸收电容耐压",
            vbus * m["capacitor"],
            c.rating(p["c_snub"]),
            "V",
            "耐压 ≥ {:g} × V_母线".format(m["capacitor"]),
        ),
    ]
    return items, checks


def calc_gate_drive(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    vbus, vdrv, rg = spec["bus_voltage_v"], p["VDRV"], p["RG_OHM"]
    items = [
        c.item("ig_pk", "栅极峰值电流（不计驱动器和管子内阻）", vdrv / rg, "A", "I = V_驱动 / R_g", note="上限估计"),
    ]
    checks = [
        c.judge(
            "d_boot_v",
            "自举二极管反向耐压",
            vbus * m["diode"],
            c.rating(p["d_boot"]),
            "V",
            "耐压 ≥ {:g} × V_母线".format(m["diode"]),
        ),
        c.judge(
            "c_boot_v",
            "自举电容耐压",
            vdrv * m["capacitor"],
            c.rating(p["c_boot"]),
            "V",
            "耐压 ≥ {:g} × V_驱动".format(m["capacitor"]),
        ),
        dev.judge(p["driver"], "vs_max", "驱动器高边浮动电压", vbus, "V", "V_S,max ≥ V_母线"),
        dev.in_range(p["driver"], "vcc_range", "驱动器供电在推荐范围内", vdrv, "V"),
    ]
    return items, checks


def sense(p, spec):
    rs, g, vfs = p["RS_MOHM"] * 1e-3, p["GAIN"], p["v_adc_fs"]
    vz = vfs / 2
    return {
        "rs": rs,
        "g": g,
        "vz": vz,
        "range": vz / (g * rs),
        "swing_pk": g * rs * spec["phase_current_peak_a"],
        "p_shunt": spec["phase_current_a"] ** 2 * rs,
    }


def calc_current_sense(block, spec, d, parts):
    p, dev = block["params"], d["devices"]
    s = sense(p, spec)
    items = [
        c.item("k", "灵敏度", s["g"] * s["rs"], "V/A", "G · R_s"),
        c.item("range", "量程（±）", s["range"], "A", "(V_ADC满量程 / 2) / (G · R_s)", note="零点在 ADC 满量程的一半"),
        c.item("swing", "峰值电流时输出摆幅", s["swing_pk"], "V", "G · R_s · I_峰值"),
        c.item("p_shunt", "采样电阻功耗（额定电流）", s["p_shunt"], "W", "I² · R_s"),
        c.item(
            "f3db",
            "放大器带宽（例题 1 的运放模型）",
            p["gbw_mhz"] * 1e6 / (1 + s["g"]),
            "Hz",
            "GBW / (1 + G)",
            note="例题用的通用运放模型，不是 INA240 的实测带宽",
        ),
    ]
    checks = [
        c.judge("range", "量程覆盖峰值电流", spec["phase_current_peak_a"], s["range"], "A", "量程 ≥ I_峰值"),
        dev.judge(p["amp"], "vcm_max", "采样放大器共模电压上限", spec["bus_voltage_v"], "V", "V_CM,max ≥ V_母线"),
        dev.equals(p["amp"], "gain", "放大器固定增益与设计一致", s["g"]),
    ]
    return items, checks


SIM_KEYS = {"current_sense": "sense", "gate_drive": "gate"}


def sim_params(btype, block, spec):
    """仿真标准题（数字工厂 cae/circuit.py 的例题）用的参数"""
    p = block["params"]
    if btype == "current_sense":
        return {"rs_mohm": p["RS_MOHM"], "gain": p["GAIN"], "gbw_mhz": p["gbw_mhz"]}
    if btype == "gate_drive":
        return {"rg_ohm": p["RG_OHM"], "vdrv": p["VDRV"]}
    return {}
