# -*- coding: utf-8 -*-
"""主轴伺服与执行器的功能块（第 159 轮 159b，平缝机控制器 CTRL-LS）：
智能功率模块逆变、下桥采样与片内运放、电磁铁驱动、步进驱动、面板口隔离。

计算器都是纯函数（不联网、不调 AI）；器件参数从 eda/parts/ 读，判定规矩同 mains.py。"""

from __future__ import annotations

import math

from . import common as c
from .mains import _losses, le, src, stat

SQ2 = math.sqrt(2.0)


def motor(spec):
    """由“5000 r/min 时线反电势峰值 ≤ 上限”推出力矩常数和相电流（磁场定向控制、幅值不变变换）"""
    w = spec["speed_max_rpm"] * 2 * math.pi / 60
    ke_ll = spec["bemf_ll_peak_max_v"] / w
    kt = 1.5 * ke_ll / math.sqrt(3)
    return {
        "w": w,
        "ke_ll": ke_ll,
        "kt": kt,
        "i_pk": spec["torque_peak_nm"] / kt,
        "i_rms_torque_pk": spec["torque_rms_nm"] / kt,
        "i_rated_pk": spec["motor_power_w"] / w / kt,
    }


def ipm_losses(dev, ipm, vdc, ipk, f, m_idx, cosphi):
    """一相（一只 IGBT + 一只二极管）的损耗，正弦调制的平均式：
    P_cond,IGBT = V_CE · I_pk · (1/(2π) + m·cosφ/8)，P_cond,D = V_F · I_pk · (1/(2π) − m·cosφ/8)，
    P_sw = (E_on + E_off) · f · (V_dc/300 V) · (I_pk/7 A) / π（规格书测试点 300 V、7 A，按电压、电流线性折算）"""
    vce, vf, eon, eoff = (dev.value(ipm, k) for k in ("vce_sat_max", "vf_diode_max", "eon_7a", "eoff_7a"))
    if None in (vce, vf, eon, eoff):
        return None
    pc = vce * ipk * (1 / (2 * math.pi) + m_idx * cosphi / 8)
    pd = vf * ipk * (1 / (2 * math.pi) - m_idx * cosphi / 8)
    ps = (eon + eoff) * f * (vdc / 300.0) * (ipk / 7.0) / math.pi
    return {"igbt": pc + ps, "diode": pd, "cond": pc, "sw": ps}


def calc_ipm_inverter(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    ipm = p["ipm"]
    vdc, f = spec["bus_voltage_v"], p["f_pwm"]
    mo = motor(spec)
    i_cont = max(mo["i_rms_torque_pk"], mo["i_rated_pk"])  # 连续工况：额定功率与仿真力矩均方根取大
    lc = ipm_losses(dev, ipm, vdc, i_cont, f, p["m_index"], p["cos_phi"])
    lp = ipm_losses(dev, ipm, vdc, mo["i_pk"], f, p["m_index"], p["cos_phi"])
    if lc is not None:
        _losses(d)[block["key"] + ":ipm"] = {
            "p": 6 * lc["igbt"] + 6 * lc["diode"],
            "rjc": dev.value(ipm, "rth_jc_igbt"),
            "split": 1,
            "tj_max": dev.value(ipm, "tj_max"),
            "name": "智能功率模块 " + ipm,
            "refs": [(ipm, "rth_jc_igbt"), (ipm, "tj_max"), (ipm, "tc_rec_max")],
            "p_chip": lc["igbt"],
            "tc_max": dev.value(ipm, "tc_rec_max"),
        }
    v_ovp = vdc * 1.08
    items = [
        c.item(
            "ke",
            "电机线反电势常数（要求的上限）",
            mo["ke_ll"],
            "V·s/rad",
            "K_e = V_线峰,max / ω_max",
            note="{:g} r/min 时线反电势峰值 ≤ {:g} V（设计要求）".format(
                spec["speed_max_rpm"], spec["bemf_ll_peak_max_v"]
            ),
        ),
        c.item("kt", "力矩常数", mo["kt"], "N·m/A", "K_t = 1.5 · K_e / √3（相电流峰值）"),
        c.item(
            "i_pk",
            "峰值力矩时的相电流峰值",
            mo["i_pk"],
            "A",
            "T_峰 / K_t",
            note="T_峰 {:g} N·m（第 138 轮 G2）".format(spec["torque_peak_nm"]),
        ),
        c.item(
            "i_cont",
            "连续工况相电流峰值",
            i_cont,
            "A",
            "max(额定功率 / ω_max, 仿真力矩均方根) / K_t",
            note="额定 {:g} W；力矩均方根 {:g} N·m（第 138 轮 gc_sim）".format(
                spec["motor_power_w"], spec["torque_rms_nm"]
            ),
        ),
        c.item(
            "p_igbt",
            "每只 IGBT 损耗（连续）",
            None if lc is None else lc["igbt"],
            "W",
            "导通 + 开关（见函数说明）",
            source=src(dev, [(ipm, "vce_sat_max"), (ipm, "eon_7a")]),
            note="V_CE 取 7 A 时最大值当常数，偏保守；m = {:g}，cosφ = {:g}".format(p["m_index"], p["cos_phi"]),
        ),
        c.item(
            "p_diode",
            "每只二极管损耗（连续）",
            None if lc is None else lc["diode"],
            "W",
            "V_F · I_pk · (1/(2π) − m·cosφ/8)",
        ),
        c.item(
            "p_total",
            "模块总损耗（连续）",
            None if lc is None else 6 * (lc["igbt"] + lc["diode"]),
            "W",
            "6 × (IGBT + 二极管)",
        ),
        c.item("p_igbt_pk", "每只 IGBT 损耗（峰值力矩时）", None if lp is None else lp["igbt"], "W", "同上，I = 峰值"),
    ]
    tj_pk = None
    rjc = dev.value(ipm, "rth_jc_igbt")
    if lp is not None and rjc is not None:
        tj_pk = spec["tc_ipm_max_c"] + lp["igbt"] * rjc
        items.append(
            c.item(
                "tj_pk",
                "峰值力矩时 IGBT 结温（壳温取上限）",
                tj_pk,
                "℃",
                "T_c,max + P_峰 · R_jc",
                note="壳温上限 {:g} ℃（散热器块保证）".format(spec["tc_ipm_max_c"]),
            )
        )
    checks = [
        le(
            dev,
            "vdc_rec",
            "母线不超过推荐工作电压",
            vdc,
            dev.value(ipm, "vpn_rec_max"),
            "V",
            "V_母线 ≤ V_PN,推荐上限",
            [(ipm, "vpn_rec_max")],
        ),
        le(
            dev,
            "vdc_ovp",
            "过压点不超过绝对最大值",
            v_ovp,
            dev.value(ipm, "vpn_abs"),
            "V",
            "1.08 × V_母线 ≤ V_PN,max",
            [(ipm, "vpn_abs")],
        ),
        dev.judge(
            ipm,
            "ic_25c",
            "IGBT 电流（壳温 25 ℃）",
            mo["i_pk"] * m["mosfet"],
            "A",
            "I_C ≥ {:g} × 峰值相电流".format(m["mosfet"]),
        ),
        le(
            dev,
            "f_pwm",
            "开关频率不超过推荐上限",
            f,
            dev.value(ipm, "f_pwm_rec_max"),
            "Hz",
            "f ≤ f_PWM,推荐",
            [(ipm, "f_pwm_rec_max")],
        ),
        dev.in_range(ipm, "vcc_rec", "15 V 供电在推荐范围内", spec["vcc_aux_v"], "V"),
        le(
            dev,
            "tj_pk",
            "峰值力矩时结温",
            tj_pk,
            None if dev.value(ipm, "tj_max") is None else dev.value(ipm, "tj_max") - spec["tj_margin_c"],
            "℃",
            "T_j ≤ T_j,max − {:g}".format(spec["tj_margin_c"]),
            [(ipm, "rth_jc_igbt"), (ipm, "tj_max")],
        ),
        c.judge(
            "dead",
            "死区不小于推荐",
            dev.value(ipm, "t_dead_rec"),
            p["t_dead"],
            "s",
            "t_死区 ≥ 推荐值",
            status=stat(
                dev,
                [(ipm, "t_dead_rec")],
                None if dev.value(ipm, "t_dead_rec") is None else p["t_dead"] >= dev.value(ipm, "t_dead_rec"),
            ),
            source=dev.source(ipm, "t_dead_rec"),
        ),
    ]
    return items, checks


def calc_low_side_sense(block, spec, d, parts):
    """三相下桥采样电阻 + MCU 片内运放（同相放大 G 倍）。
    159d1 起进运放前加偏置网络（输入电阻 R_in、到 V_ref 的偏置电阻 R_b）：
    V+ = V_采样 · k + V_ref · R_in/(R_in + R_b)，k = R_b/(R_in + R_b)；取 R_b = (2G − 1)·R_in 时零点正好是 V_ref/2"""
    p, m, dev = block["params"], d["derating"], d["devices"]
    rs_part = p["shunt"]
    r = dev.value(rs_part, "r")
    mo = motor(spec)
    g, vref = p["gain"], p["v_ref"]
    r_in, r_b = p["r_in"], p["r_bias"]
    gains = dev.value(p["mcu"], "pga_gains") if p.get("mcu") else None
    k = r_b / (r_in + r_b)
    v0 = g * vref * r_in / (r_in + r_b)
    i_fs = None if r is None else min(v0, vref - v0) / (g * k * r)
    p_pk = None if r is None else (mo["i_pk"] / SQ2) ** 2 * r
    i_trip = p["i_trip"]
    items = [
        c.item(
            "i_fs",
            "量程（±）",
            i_fs,
            "A",
            "I_满 = min(V_零, V_ref − V_零) / (G · k · R)",
            source=dev.source(rs_part, "r"),
            note="G = {:g}，V_ref = {:g} V，k = {:.4g}".format(g, vref, k),
        ),
        c.item(
            "v_zero",
            "零电流时运放输出（零点）",
            v0,
            "V",
            "V_零 = G · V_ref · R_in/(R_in + R_b)",
            note="R_in = {}，R_b = {}".format(c.fmt(r_in), c.fmt(r_b)),
        ),
        c.item("p_pk", "采样电阻功耗（峰值力矩持续时）", p_pk, "W", "(I_峰/√2)² · R"),
        c.item(
            "v_trip",
            "过流比较器门限（采样电阻上的电压）",
            None if r is None else i_trip * r,
            "V",
            "I_跳 · R",
            note="I_跳 = {:g} A".format(i_trip),
        ),
    ]
    checks = [
        c.judge(
            "i_fs",
            "量程覆盖峰值电流（留余量）",
            mo["i_pk"] * m["sense_headroom"],
            i_fs,
            "A",
            "I_满 ≥ {:g} × 峰值".format(m["sense_headroom"]),
            status=stat(dev, [(rs_part, "r")], None if i_fs is None else i_fs >= mo["i_pk"] * m["sense_headroom"]),
            source=dev.source(rs_part, "r"),
        ),
        c.judge(
            "i_trip",
            "过流门限高于峰值、在量程内",
            mo["i_pk"],
            i_trip,
            "A",
            "峰值 ≤ I_跳 ≤ I_满",
            status=stat(dev, [(rs_part, "r")], None if i_fs is None else mo["i_pk"] <= i_trip <= i_fs),
        ),
        dev.judge(
            rs_part, "p_70c", "采样电阻额定功率", p_pk if p_pk is not None else 0.0, "W", "P_额定(70 ℃) ≥ 峰值时功耗"
        ),
        c.judge(
            "pga_gain",
            "MCU 片内运放能设成这个增益",
            g,
            None if gains is None else ("有" if g in gains else "没有"),
            "",
            "片内 PGA 可选增益含 G",
            status=stat(dev, [(p["mcu"], "pga_gains")], None if gains is None else g in gains),
            source=dev.source(p["mcu"], "pga_gains"),
            note="" if gains is None else "可选：" + "、".join(str(x) for x in gains),
        ),
        dev.judge(p["ipm"], "ic_25c", "过流门限不超过模块电流", i_trip, "A", "I_C ≥ I_跳"),
    ]
    return items, checks


def calc_solenoid_drive(block, spec, d, parts):
    """电磁铁低边驱动：关断时经“二极管 + 稳压管”钳位，比只用续流二极管释放快"""
    p, m, dev = block["params"], d["derating"], d["devices"]
    fet, tvs, dio = p["fet"], p["tvs"], p["diode"]
    v24 = spec["v24"] * (1 + p["v24_tol"])
    R, L = p["coil_r"], p["coil_l"]
    i0 = spec["v24"] / R
    vbr, vf = dev.value(tvs, "vbr_max"), dev.value(dio, "vf_max")
    vz = None if None in (vbr, vf) else vbr + vf
    tau = L / R
    t_off = None if vz is None else tau * math.log(1 + i0 * R / vz)
    t_off_diode = None if vf is None else tau * math.log(1 + i0 * R / vf)
    v_ds = None if vz is None else v24 + vz
    rds = dev.value(fet, "rds_on_max")
    p_fet = None if rds is None else i0**2 * rds
    vc = dev.value(tvs, "vc")
    items = [
        c.item(
            "i0",
            "线圈电流",
            i0,
            "A",
            "V / R",
            note="线圈 {:g} Ω、{:g} mH 是示例值（机头上的电磁铁，按实物改）".format(R, L * 1000),
        ),
        c.item(
            "t_off",
            "释放时间（二极管 + 稳压管钳位）",
            t_off,
            "s",
            "τ · ln(1 + I₀R / V_z)，τ = L/R",
            source=dev.source(tvs, "vbr_max"),
        ),
        c.item("t_off_diode", "对照：只用续流二极管的释放时间", t_off_diode, "s", "τ · ln(1 + I₀R / V_F)"),
        c.item("v_ds", "关断时开关管漏极电压", v_ds, "V", "V_24,max + V_BR,max + V_F"),
        c.item("p_fet", "开关管导通损耗（吸合时）", p_fet, "W", "I₀² · R_DS(on),max"),
        c.item("e_off", "每次释放的磁能", 0.5 * L * i0**2, "J", "½ L I₀²"),
    ]
    checks = [
        dev.judge(
            fet, "vds", "开关管耐压", (v_ds or 0) * m["mosfet"], "V", "V_DS ≥ {:g} × 关断尖峰".format(m["mosfet"])
        )
        if v_ds
        else c.judge("vds", "开关管耐压", None, None, "V", "", status=c.UNKNOWN),
        dev.judge(fet, "id_25c", "开关管电流", i0 * m["mosfet"], "A", "I_D ≥ {:g} × 线圈电流".format(m["mosfet"])),
        dev.judge(dio, "ifsm", "续流二极管浪涌电流", i0, "A", "I_FSM ≥ 线圈电流（只在释放的几毫秒里导通）"),
        dev.judge(dio, "vrrm", "续流二极管耐压", v24 * m["diode"], "V", "V_RRM ≥ {:g} × V_24".format(m["diode"])),
        dev.judge(tvs, "ppk", "稳压管峰值功率", (vc or 0) * i0, "W", "P_PPM(10/1000 µs) ≥ V_C · I₀")
        if vc
        else c.judge("ppk", "稳压管峰值功率", None, None, "W", "", status=c.UNKNOWN),
        c.judge(
            "t_off",
            "释放时间满足要求",
            t_off,
            p["t_off_max"],
            "s",
            "t ≤ {:g} ms".format(p["t_off_max"] * 1000),
            status=stat(dev, [(tvs, "vbr_max"), (dio, "vf_max")], None if t_off is None else t_off <= p["t_off_max"]),
        ),
    ]
    return items, checks


def calc_stepper(block, spec, d, parts):
    p, dev = block["params"], d["devices"]
    drv = p["driver"]
    v = spec["v24"] * (1 + p["v24_tol"])
    items = [
        c.item("i_coil", "步进电机线圈电流（有效值）", p["i_coil_rms"], "A", note="示例值（针距步进电机按实物改）")
    ]
    checks = [
        dev.in_range(drv, "vs_op", "24 V（含波动）在驱动器工作范围", v, "V"),
        dev.judge(drv, "i_rms_cont", "驱动器连续电流", p["i_coil_rms"], "A", "I_RMS,连续 ≥ 线圈电流"),
    ]
    if "r_sense" in p:  # 159d2：VREF 分压设电流
        vref = p["v_5vout"] * p["r_vref_bot"] / (p["r_vref_top"] + p["r_vref_bot"])
        i_set = 0.325 / (p["r_sense"] + 0.02) / math.sqrt(2) * min(vref, 2.5) / 2.5
        items += [
            c.item("v_vref", "VREF 电压", vref, "V", "V_5VOUT · R_下/(R_上 + R_下)"),
            c.item(
                "i_set",
                "设定的线圈电流（有效值）",
                i_set,
                "A",
                "I = 0.325 V / (R_采样 + 0.02 Ω) / √2 × V_REF / 2.5 V",
                note="TMC22xx 的电流式子（采样 0.11 Ω、V_REF 2.5 V 时 1.77 A，与 FYSETC TMC2226 资料一致）；"
                "待核对 TMC2226 规格书",
            ),
        ]
        ok = abs(i_set - p["i_coil_rms"]) <= 0.1 * p["i_coil_rms"]
        checks.append(
            c.judge(
                "i_set",
                "设定电流与线圈电流相差 ≤ 10 %",
                p["i_coil_rms"],
                i_set,
                "A",
                "|I_设 − I_线圈| ≤ 10 %",
                status=c.PENDING if ok else c.FAIL,
                note="式子待核对规格书，所以只判到“待核对”",
            )
        )
    return items, checks


def calc_panel_iso(block, spec, d, parts):
    """面板口：数字隔离 + 隔离电源 + RS-485。隔离耐压要求 iso_need_v 是示例值（按直流 1 分钟），企业按安规表填。
    159d2 起两颗器件的隔离耐压从规格书读（eda/parts）：数字隔离器给的是交流有效值，按峰值 √2 倍和直流要求比。"""
    p, dev = block["params"], d["devices"]
    need = p["iso_need_v"]
    v_ac = dev.value(p["isolator"], "v_iso_rms")
    items = [
        c.item("baud", "面板串口速率", p["baud"], "bit/s", note="设计给定"),
        c.item(
            "iso_pk",
            "数字隔离器耐压（峰值）",
            None if v_ac is None else v_ac * math.sqrt(2),
            "V",
            "√2 × V_iso,rms",
            source=dev.source(p["isolator"], "v_iso_rms"),
        ),
    ]
    st = stat(dev, [(p["isolator"], "v_iso_rms")], None if v_ac is None else v_ac * math.sqrt(2) >= need)
    checks = [
        c.judge(
            "iso_v",
            "数字隔离器隔离耐压",
            need,
            None if v_ac is None else v_ac * math.sqrt(2),
            "V",
            "√2 × V_iso,rms ≥ 要求（直流 1 分钟，示例值）",
            status=st,
            source=dev.source(p["isolator"], "v_iso_rms"),
        ),
        dev.judge(p["dcdc"], "v_iso_dc", "隔离电源隔离耐压", need, "V", "V_iso（直流 1 分钟）≥ 要求"),
        dev.in_range(p["isolator"], "vdd_range", "数字隔离器两侧供电 3.3 V 在范围内", 3.3, "V"),
    ]
    return items, checks
