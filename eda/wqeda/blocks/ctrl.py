# -*- coding: utf-8 -*-
"""平缝机控制器 CTRL-LS 各功能块的生成器（第 159 轮 159d1）：把功能块展开成原理图器件和网络。

和关节驱动板（power.py、drive.py、control.py）一样，每个生成器返回 common.part() 的清单，纯函数。
符号和封装都取 KiCad 7 官方库（库里有功率模块 STGIPS14K60T、ICE3PCS01、TOP266KG、TMC2226、ADuM1201、STM32G431）；
没有官方库的只有两种定制磁性元件（升压电感、反激变压器），用工程自带的 wq 库，磁芯和封装 159d2 定。

整块板以母线负端为地（GND）：主控、功率模块输入、电流采样都不隔离（方案第一节），
人能碰到的面板口经 ADuM1201 隔离（GND_ISO）。
位号按功能块分段：交流输入 1xx、校正 2xx、辅助电源 3xx、逆变 4xx、电磁铁与步进 5xx、面板口 6xx、传感器输入 7xx；
主控沿用 control.gen_mcu_core（U10、C40–C48、R30、Y1、TP1–TP5）。

阻容的取值：规格书给了参考值的照规格书（注里写页码）；其余是设计取值，注里写算法或理由；
要规格书核对的写“待核对”。示例设计，未经硬件验证。"""

from __future__ import annotations

import math

from . import common as c

FP_R = "Resistor_SMD:R_0603_1608Metric"
FP_R1206 = "Resistor_SMD:R_1206_3216Metric"
FP_R2512 = "Resistor_SMD:R_2512_6332Metric"
FP_C = "Capacitor_SMD:C_0603_1608Metric"
FP_C0805 = "Capacitor_SMD:C_0805_2012Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_C1812 = "Capacitor_SMD:C_1812_4532Metric"
FP_SOT23 = "Package_TO_SOT_SMD:SOT-23"
FP_SOD123 = "Diode_SMD:D_SOD-123"
FP_SMB = "Diode_SMD:D_SMB"
FP_SMC = "Diode_SMD:D_SMC"
FP_TDSON = "Package_TO_SOT_SMD:TDSON-8-1"
FP_TERM3 = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3-5.08_1x03_P5.08mm_Horizontal"
FP_MAG = "wq:Magnetics_TBD"  # 定制磁性元件：磁芯与骨架 159d2 定，封装随之


def _r(ref, val, a, b, k, note="", fp=FP_R, item="RES-0603"):
    return c.two(ref, "Device:R", val, a, b, k, fp, item, note)


def _c(ref, val, a, b, k, note="", fp=FP_C, item="CAP-0603"):
    return c.two(ref, "Device:C", val, a, b, k, fp, item, note)


def _d(ref, val, anode, cathode, k, fp, item, note=""):
    return c.part(ref, "Device:D", val, fp, k, {"1": cathode, "2": anode}, item, note)


def _nfet(ref, g, d_, s, k, note=""):
    """小信号 N 沟道管 2N7002（SOT-23：1 G、2 S、3 D）"""
    return c.part(ref, "Transistor_FET:2N7002", "2N7002", FP_SOT23, k, {"1": g, "2": s, "3": d_}, "MOS-2N7002", note)


def _divider_top(refs, a, b, val, k, note):
    """高压分压的上臂拆成几只 1206 串联（每只承受的电压低于它的额定）"""
    out, nets = [], [a] + ["{}_{}".format(b, i) for i in range(1, len(refs))] + [b]
    for i, ref in enumerate(refs):
        out.append(_r(ref, val, nets[i], nets[i + 1], k, note if i == 0 else "", FP_R1206, "RES-1206"))
    return out


# ------------------------------------------------------------------------------------------------- 交流输入与整流


def gen_ac_input(block, spec, d):
    p, k = block["params"], block["key"]
    return [
        c.part(
            "J101",
            "Connector:Screw_Terminal_01x03",
            "AC IN L/N/PE",
            FP_TERM3,
            k,
            {"1": "L_IN", "2": "N_IN", "3": "PE"},
            "CONN-AC",
            "交流输入：1 相线、2 零线、3 保护地",
        ),
        c.part(
            "F101",
            "Device:Fuse",
            "10A T",
            "Fuse:Fuseholder_Clip-5x20mm_Bel_FC-203-22_Lateral_P17.80x5.00mm_D1.17mm_Horizontal",
            k,
            {"1": "L_IN", "2": "L_F"},
            "FUSE-T10A",
            p["fuse"] + "（5×20 mm 慢断，夹座安装；夹座封装待核对）",
        ),
        c.part(
            "RV101",
            "Device:Varistor",
            "S14K275",
            "Varistor:RV_Disc_D15.5mm_W4.9mm_P7.5mm",
            k,
            {"1": "L_F", "2": "N_IN"},
            "MOV-275",
            p["mov"] + "（封装按 14 mm 盘片选，待核对）",
        ),
        c.part(
            "C101",
            "Device:C",
            "470n X2",
            "Capacitor_THT:C_Rect_L26.5mm_W10.5mm_P22.50mm_MKS4",
            k,
            {"1": "L_F", "2": "N_IN"},
            "CAP-X2-470N",
            p["x_cap"] + "（封装待核对）",
        ),
        _r(
            "R101",
            "1M",
            "L_F",
            "XDIS",
            k,
            "X 电容放电：2 MΩ × 0.47 µF = 0.94 s（拔插头后 1 s 内放到安全）",
            FP_R1206,
            "RES-1206",
        ),
        _r("R102", "1M", "XDIS", "N_IN", k, fp=FP_R1206, item="RES-1206"),
        c.part(
            "L101",
            "Device:Filter_EMI_CommonMode",
            "15mH 10A",
            "Inductor_THT:L_CommonMode_Toroid_Vertical_L34.3mm_W20.3mm_Px15.24mm_Py22.86mm_Bourns_8100",
            k,
            {"1": "L_F", "2": "L_C", "3": "N_IN", "4": "N_C"},
            "CMC-15MH",
            p["cmc"] + "（规格书是图片读不出、KiCad 库没有它的封装：159d2 换一个库里有封装的型号，这里先占位）",
        ),
        c.part(
            "C102",
            "Device:C",
            "2n2 Y1",
            "Capacitor_THT:C_Disc_D8.0mm_W5.0mm_P7.50mm",
            k,
            {"1": "L_C", "2": "PE"},
            "CAP-Y-2N2",
            "Y 电容（封装待核对）",
        ),
        c.part(
            "C103",
            "Device:C",
            "2n2 Y1",
            "Capacitor_THT:C_Disc_D8.0mm_W5.0mm_P7.50mm",
            k,
            {"1": "N_C", "2": "PE"},
            "CAP-Y-2N2",
        ),
        c.part(
            "TH101",
            "Device:Thermistor_NTC",
            "2.5R",
            "Varistor:RV_Disc_D15.5mm_W4.9mm_P7.5mm",
            k,
            {"1": "L_C", "2": "L_R"},
            "NTC-2R5",
            p["ntc"] + "（上电浪涌限流，母线充好后由 K101 短接；封装按盘片选，待核对）",
        ),
        c.part(
            "K101",
            "Relay:G5LE-1",
            "G5LE-1 DC12",
            "Relay_THT:Relay_SPDT_Omron-G5LE-1",
            k,
            {"1": "L_C", "3": "L_R", "2": "+15V", "5": "RLY_K"},
            "RLY-G5LE",
            p["relay"]
            + "：1 公共端、3 常开（短接热敏电阻）、2/5 线圈。线圈 12 V 用在 15 V 上——线圈最高允许电压待核对规格书",
        ),
        _d("D101", "1N4148W", "RLY_K", "+15V", k, FP_SOD123, "DIO-1N4148W", "继电器线圈续流"),
        _nfet("Q101", "RLY_G", "RLY_K", "GND", k, "母线充好（校正控制器 VB_OK = 5 V）后吸合"),
        _r("R103", "1k", "VB_OK", "RLY_G", k, "VB_OK 最多出 1 mA（ICE3PCS01G 规格书 p.19），只推管子栅极"),
        _r("R104", "100k", "RLY_G", "GND", k),
    ]


def gen_bridge(block, spec, d):
    p, k = block["params"], block["key"]
    return [
        c.part(
            "BR101",
            "Device:D_Bridge_+AA-",
            p["bridge"],
            "Diode_THT:Diode_Bridge_Vishay_GBU",
            k,
            {"1": "VRECT", "2": "L_R", "3": "N_C", "4": "RECT_N"},
            "BRG-GBU1006",
            "整流桥（引脚 + ~ ~ −，与 KiCad 的 GBU 封装对照规格书待核对；装在散热器上）",
        ),
        c.part(
            "C104",
            "Device:C",
            "1u/450V",
            "Capacitor_THT:C_Rect_L18.0mm_W8.0mm_P15.00mm_FKS3_FKP3",
            k,
            {"1": "VRECT", "2": "RECT_N"},
            "CAP-FILM-1U-450V",
            "整流后高频旁路（吸收升压管开关电流，薄膜电容）",
        ),
    ]


# ------------------------------------------------------------------------------------------------- 功率因数校正


def gen_pfc_boost(block, spec, d):
    """ICE3PCS01G 典型接法（规格书 V3.0 2017-04-03，p.7 物料表、第 1.2 节引脚说明）；母线分压按 390 V 重算"""
    p, k = block["params"], block["key"]
    vo = spec["bus_voltage_v"]
    rb = c.parse(p["r_vs_bottom"])
    out = [
        c.part(
            "U201",
            "Regulator_Controller:ICE3PCS01",
            p["controller"],
            "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
            k,
            {
                "1": "BOFO",
                "2": "ISENSE",
                "3": "GND",
                "4": "ICOMP",
                "5": "FREQ",
                "6": "VB_OK",
                "7": "VBTHL_EN",
                "8": "VREF",
                "9": "BOP",
                "10": "OVP",
                "11": "VSENSE",
                "12": "+15V",
                "13": "GATE_IC",
                "14": "GND",
            },
            "IC-PFC-ICE3PCS01G",
            "连续导通功率因数校正控制器",
        ),
        _c("C201", "1u/25V", "+15V", "GND", k, "VCC 去耦（规格书没给值，设计取值）", FP_C0805, "CAP-0805"),
        _c("C202", "100n", "+15V", "GND", k),
        c.part(
            "L201",
            "wq:L_PFC",
            "{:.0f}uH".format(_pfc_l(spec, p, d)),
            FP_MAG,
            k,
            {"1": "VRECT", "2": "SW_PFC"},
            "IND-PFC-CUSTOM",
            "升压电感（定制：电感量、峰值电流见计算书；磁芯与封装 159d2 定）",
        ),
        c.part(
            "Q201",
            "Device:Q_NMOS_GDS",
            p["fet"],
            "Package_TO_SOT_THT:TO-247-3_Vertical",
            k,
            {"1": "GATE_PFC", "2": "SW_PFC", "3": "GND"},
            "MOS-IPW60R060P7",
            "升压开关管（TO-247：1 G、2 D、3 S；装在散热器上）",
        ),
        _r("R201", "3.3", "GATE_IC", "GATE_PFC", k, "栅极电阻 3.3 Ω（规格书 p.7 物料表 RGATE）"),
        _r("R202", "10k", "GATE_PFC", "GND", k, "栅源下拉（设计取值）"),
        c.part(
            "D201",
            "Device:D",
            p["diode"],
            "Package_TO_SOT_THT:TO-220-2_Vertical",
            k,
            {"1": "VBUS", "2": "SW_PFC"},
            "DIO-C3D06060A",
            "升压二极管（碳化硅，TO-220-2：1 阴极、2 阳极，待核对规格书；装在散热器上）",
        ),
        _d(
            "D202",
            "1N5408",
            "VRECT",
            "VBUS",
            k,
            "Diode_THT:D_DO-201AD_P15.24mm_Horizontal",
            "DIO-1N5408",
            "旁路二极管：上电时浪涌电流绕过电感直接给母线电容充电（规格书 p.7 物料表 DBYP 的作用，型号是设计取值）",
        ),
    ]
    for i in range(p["n_caps"]):
        out.append(
            c.part(
                "C{}".format(221 + i),
                "Device:C_Polarized",
                "330u/500V",
                "Capacitor_THT:CP_Radial_D30.0mm_P10.00mm_SnapIn",
                k,
                {"1": "VBUS", "2": "GND"},
                "CAP-BULK-330U-500V",
                p["cap"] + "（母线电容，计算书：3 只并联）" if i == 0 else "",
            )
        )
    out += [
        c.part(
            "R203",
            "Device:R",
            p["r_shunt"],
            FP_R2512,
            k,
            {"1": "RECT_N", "2": "GND"},
            "RES-SHUNT-10M",
            "电流采样电阻（整流桥负端到地，ISENSE 取负压；型号与额定功率 159d2 定）",
        ),
        _r("R204", "51", "RECT_N", "ISENSE", k, "ISENSE 串联电阻约 50 Ω，限浪涌（规格书 p.4、p.7 物料表 RCS）"),
        _c("C205", "1n", "ISENSE", "GND", k, "规格书 p.7 物料表 CISENSE 1 nF"),
        _c("C206", "4.7n", "ICOMP", "GND", k, "电流环补偿（规格书 p.7 物料表 CICOMP 4.7 nF）"),
        _r("R205", "66.5k", "FREQ", "GND", k, "开关频率：规格书 67 kΩ → 65 kHz（p.7–8），取 E96 最近的 66.5 kΩ"),
        _c("C207", "100n", "VREF", "GND", k, "5 V 基准去耦（规格书 p.7、p.8）"),
        _r(
            "R206",
            "200k",
            "VREF",
            "BOFO",
            k,
            "BOFO 拉到 0.5 V 以上 = 不用升压跟随（规格书 p.13）；200 k / 200 k 照 p.7 物料表",
        ),
        _r("R207", "200k", "BOFO", "GND", k),
        _r(
            "R208",
            "330k",
            "VREF",
            "VBTHL_EN",
            k,
            "VB_OK 断开门限 = 5 V × 200/530 = 1.89 V（母线约 294 V）；"
            "330 k / 200 k 照 p.7 物料表 RVB1、RVB2，接法是按框图读的，待核对",
        ),
        _r("R209", "200k", "VBTHL_EN", "GND", k),
        _nfet("Q202", "PFC_OFF", "VBTHL_EN", "GND", k, "主控拉高 PFC_OFF → VBTHL_EN < 0.5 V → 校正关断（规格书 p.14）"),
        _r("R210", "100k", "PFC_OFF", "GND", k, "主控没输出时校正照常工作"),
        # 欠压（BOP）：两只 1N4007 从交流两线全波取样，3.9 M + 3.9 M / 130 k，3 µF（规格书 p.7 物料表、图 12）
        _d(
            "D203",
            "1N4007",
            "L_R",
            "BRO_A",
            k,
            "Diode_SMD:D_SMA",
            "DIO-1N4007",
            "欠压取样（规格书 p.7 DBRO1、DBRO2；贴片 M7 等效）",
        ),
        _d("D204", "1N4007", "N_C", "BRO_A", k, "Diode_SMD:D_SMA", "DIO-1N4007"),
        _r("R211", "3.9M", "BRO_A", "BRO_B", k, "规格书 p.7 RBRO1、RBRO2 3.9 MΩ", FP_R1206, "RES-1206"),
        _r("R212", "3.9M", "BRO_B", "BOP", k, fp=FP_R1206, item="RES-1206"),
        _r("R213", "130k", "BOP", "GND", k, "规格书 p.7 RBRO3 130 kΩ"),
        _c("C208", "3.3u/25V", "BOP", "GND", k, "规格书 p.7 CBRO 3 µF，取 3.3 µF", FP_C0805, "CAP-0805"),
    ]
    # 母线分压：VSENSE（稳压）与 OVP（第二级过压，2.5 V 动作，规格书 p.12、p.18）各一路
    rt = rb * (vo / 2.5 - 1)
    each = c.nearest(rt / 3, "E96")
    out += _divider_top(
        ["R214", "R215", "R216"],
        "VBUS",
        "VSENSE",
        c.fmt(each),
        k,
        "VSENSE 上臂 3 × {}（理想 {:.3g} MΩ）：母线 = 2.5 V × (1 + 上/下)".format(c.fmt(each), rt / 1e6),
    )
    out.append(_r("R217", p["r_vs_bottom"], "VSENSE", "GND", k, "VSENSE 下臂"))
    v_ovp2 = 1.10 * vo
    rt2 = rb * (v_ovp2 / 2.5 - 1)
    each2 = c.nearest(rt2 / 3, "E96")
    out += _divider_top(
        ["R218", "R219", "R220"],
        "VBUS",
        "OVP",
        c.fmt(each2),
        k,
        "OVP 上臂 3 × {}：第二级过压约 110 % 额定（{:.0f} V，设计取值）".format(c.fmt(each2), v_ovp2),
    )
    out.append(_r("R221", p["r_vs_bottom"], "OVP", "GND", k, "OVP 下臂"))
    return out


def _pfc_l(spec, p, d):
    from .mains import pfc

    return pfc(spec, p, None)["L"] * 1e6


# ------------------------------------------------------------------------------------------------- 反激辅助电源


def gen_flyback_aux(block, spec, d):
    """TOP266KG（TOPSwitch-JX 规格书 Rev. E 08/12）：V 脚 4 MΩ 接母线（p.6）、X 脚接 S 用片内默认限流（p.3）、
    F 脚接 C 选 66 kHz（p.5）、C 脚 47 µF（p.8 的例子）。整块板共地，三路输出都以 GND 为参考（不隔离），
    稳压取 24 V 与 15 V 加权（TL431 + 光耦）。"""
    p, k = block["params"], block["key"]
    return [
        c.part(
            "U301",
            "Regulator_Switching:TOP266KG",
            p["ic"],
            "Package_SO:PowerIntegrations_eSOP-12B",
            k,
            {
                "1": "TOP_V",
                "2": "GND",
                "3": "TOP_C",
                "4": "TOP_C",
                "6": "FLY_D",
                "7": "GND",
                "8": "GND",
                "9": "GND",
                "10": "GND",
                "11": "GND",
                "12": "GND",
            },
            "IC-TOP266KG",
            "反激控制器（集成 725 V 开关管）；X 接 S、F 接 C",
        ),
        _r(
            "R301",
            "2M",
            "VBUS",
            "TOP_V1",
            k,
            "V 脚线路检测 4 MΩ（规格书 p.6），两只 1206 串联分压；离 V 脚 10 mm 内（p.21）",
            FP_R1206,
            "RES-1206",
        ),
        _r("R302", "2M", "TOP_V1", "TOP_V", k, fp=FP_R1206, item="RES-1206"),
        c.part(
            "C301",
            "Device:C_Polarized",
            "47u/16V",
            "Capacitor_SMD:CP_Elec_6.3x5.4",
            k,
            {"1": "TOP_C", "2": "GND"},
            "CAP-EL-47U-16V",
            "C 脚旁路 47 µF（规格书 p.8：起动 / 重启时间按 47 µF 给出）",
        ),
        _c("C302", "100n", "TOP_C", "GND", k, "C 脚高频旁路（规格书 p.20–21 建议）"),
        c.part(
            "T301",
            "wq:Transformer_FLY3",
            "FLY-24/15/5",
            FP_MAG,
            k,
            {"1": "VBUS", "2": "FLY_D", "3": "FLY_24", "4": "GND", "5": "FLY_15", "6": "GND", "7": "FLY_5", "8": "GND"},
            "XFMR-FLY-CUSTOM",
            "反激变压器（定制：初级电感、匝比见计算书；三路次级共地，不要求加强绝缘；磁芯与封装 159d2 定）",
        ),
        # 初级钳位（RCD）：漏感未知，R、C 按样机调（第一版取常见值）
        _d("D301", "US1M", "FLY_D", "CLAMP", k, "Diode_SMD:D_SMA", "DIO-US1M", "钳位二极管（快恢复 1000 V）"),
        _r(
            "R303",
            "100k",
            "VBUS",
            "CLAMP",
            k,
            "RCD 钳位电阻：要变压器漏感才能算，第一版取常见值、按样机调（待定）",
            FP_R2512,
            "RES-2512",
        ),
        c.part(
            "C303",
            "Device:C",
            "1n/1kV",
            FP_C1206,
            k,
            {"1": "VBUS", "2": "CLAMP"},
            "CAP-1206-1KV",
            "RCD 钳位电容（待定，同上）",
        ),
        _d("D302", p["out_diode"], "FLY_24", "+24V", k, FP_SMC, "DIO-ES3D", "24 V 整流"),
        c.part(
            "C304",
            "Device:C_Polarized",
            "470u/35V",
            "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
            k,
            {"1": "+24V", "2": "GND"},
            "CAP-EL-470U-35V",
            "24 V 输出（电磁铁吸合的脉冲电流从这里出）",
        ),
        _c("C305", "1u/50V", "+24V", "GND", k, fp=FP_C1206, item="CAP-1206"),
        _d("D303", p["out_diode"], "FLY_15", "+15V", k, FP_SMC, "DIO-ES3D", "15 V 整流"),
        c.part(
            "C306",
            "Device:C_Polarized",
            "220u/25V",
            "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
            k,
            {"1": "+15V", "2": "GND"},
            "CAP-EL-220U-25V",
            "15 V 输出（功率模块、校正控制器、继电器）",
        ),
        _d("D304", p["out_diode"], "FLY_5", "+5V", k, FP_SMC, "DIO-ES3D", "5 V 整流"),
        c.part(
            "C307",
            "Device:C_Polarized",
            "1000u/10V",
            "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm",
            k,
            {"1": "+5V", "2": "GND"},
            "CAP-EL-1000U-10V",
            "5 V 输出",
        ),
        # 稳压：TL431 取 24 V 与 15 V 的加权（各一半），光耦把误差送到 C 脚（光耦集电极接 15 V）
        _r("R304", "82k", "+24V", "FB_REF", k, "加权取样：24 V 与 15 V 各占一半（设计取值），下臂 10 k"),
        _r("R305", "47k", "+15V", "FB_REF", k),
        _r("R306", "10k", "FB_REF", "GND", k),
        c.part(
            "U302",
            "Reference_Voltage:TL431DBZ",
            "TL431AIDBZR",
            FP_SOT23,
            k,
            {"1": "FB_K", "2": "FB_REF", "3": "GND"},
            "IC-TL431",
            "反馈基准",
        ),
        _r("R307", "10k", "FB_K", "FB_RC", k, "补偿（设计取值，按样机调）"),
        _c("C308", "100n", "FB_RC", "FB_REF", k),
        c.part(
            "U303",
            "Isolator:PC817",
            "PC817X2NSZ9F",
            "Package_DIP:SMDIP-4_W9.53mm",
            k,
            {"1": "FB_LED", "2": "FB_K", "3": "TOP_C", "4": "+15V"},
            "OPTO-PC817",
            "反馈光耦（这里不为隔离，只为把误差电流送进 C 脚）",
        ),
        _r("R308", "1k", "+24V", "FB_LED", k, "光耦发光管限流"),
        _r("R309", "1k", "FB_LED", "FB_K", k, "发光管旁路（TL431 最小工作电流从这里走）"),
        # 3.3 V：5 V 线性降压（主控、片内运放、施密特整形）
        c.part(
            "U304",
            "Regulator_Linear:AMS1117-3.3",
            "AMS1117-3.3",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            k,
            {"1": "GND", "2": "+3V3", "3": "+5V"},
            "IC-LDO-3V3",
            "3.3 V（沿用关节驱动板）",
        ),
        _c("C309", "10u/25V", "+5V", "GND", k, fp=FP_C1206, item="CAP-1206"),
        _c("C310", "10u/25V", "+3V3", "GND", k, fp=FP_C1206, item="CAP-1206"),
    ]


# ------------------------------------------------------------------------------------------------- 逆变与电流采样


def gen_ipm_inverter(block, spec, d):
    """STGIPS14K60T（规格书：HIN、LIN 高有效，SD 低有效、外接上拉到 3.3 V，T1 是片内热敏电阻一端）"""
    p, k = block["params"], block["key"]
    pins = {
        "1": "OUT_U",
        "2": "VB_U",
        "3": "IN_UL",
        "4": "IN_UH",
        "5": "+15V",
        "6": "OUT_V",
        "7": "VB_V",
        "8": "GND",
        "9": "IN_VL",
        "10": "IN_VH",
        "11": "OUT_W",
        "12": "VB_W",
        "13": "IN_WL",
        "14": "IN_WH",
        "15": "IPM_SD",
        "16": "IPM_T",
        "17": "N_W",
        "18": "MOT_W",
        "19": "VBUS",
        "20": "N_V",
        "21": "MOT_V",
        "22": "VBUS",
        "23": "N_U",
        "24": "MOT_U",
        "25": "VBUS",
    }
    out = [
        c.part(
            "U401",
            "Transistor_Power_Module:STGIPS14K60T",
            p["ipm"],
            "Transistor_Power_Module:ST_SDIP-25L",
            k,
            pins,
            "IPM-STGIPS14K60T",
            "三相智能功率模块（装在散热器上）。OUT_x 是上桥浮地参考，自举电容接在 VB_x 与 OUT_x 之间",
        ),
        c.part(
            "J401",
            "Connector:Screw_Terminal_01x03",
            "MOTOR U/V/W",
            FP_TERM3,
            k,
            {"1": "MOT_U", "2": "MOT_V", "3": "MOT_W"},
            "CONN-MOT",
            "电机三相",
        ),
        _c(
            "C401",
            "4.7u/25V",
            "VB_U",
            "OUT_U",
            k,
            "自举电容：静态电流 300 µA（规格书）× 每个 PWM 周期 62.5 µs ≪ 4.7 µF × 1 V",
            FP_C1206,
            "CAP-1206",
        ),
        _c("C402", "4.7u/25V", "VB_V", "OUT_V", k, fp=FP_C1206, item="CAP-1206"),
        _c("C403", "4.7u/25V", "VB_W", "OUT_W", k, fp=FP_C1206, item="CAP-1206"),
        _c("C404", "10u/25V", "+15V", "GND", k, "VCC 去耦，紧靠模块引脚（规格书 4.1 节）", FP_C1206, "CAP-1206"),
        _c("C405", "100n", "+15V", "GND", k),
        c.part(
            "C406",
            "Device:C",
            "100n/630V",
            FP_C1812,
            k,
            {"1": "VBUS", "2": "GND"},
            "CAP-1812-630V",
            "母线高频旁路，紧靠 P、N 引脚（规格书 4.1 节）",
        ),
        _r("R401", "10k", "+3V3", "IPM_SD", k, "SD 外接上拉到 3.3 V（规格书 4.1 节）；主控拉低关断"),
        _c("C407", "1n", "IPM_SD", "GND", k),
        _r(
            "R402",
            "1k",
            "+3V3",
            "IPM_T",
            k,
            "热敏电阻上拉：25 ℃ 4.7 kΩ → 2.71 V，100 ℃ 约 330 Ω → 0.82 V（R25、B 值见规格书）",
        ),
        _c("C408", "10n", "IPM_T", "GND", k),
    ]
    for i, (ph, hl) in enumerate((("U", "H"), ("U", "L"), ("V", "H"), ("V", "L"), ("W", "H"), ("W", "L"))):
        out.append(
            _r(
                "R{}".format(403 + i),
                "100",
                "PWM_{}{}".format(ph, hl),
                "IN_{}{}".format(ph, hl),
                k,
                "输入 RC 滤波 100 Ω / 1 nF（0.1 µs ≪ 死区 1 µs，设计取值）" if i == 0 else "",
            )
        )
        out.append(_c("C{}".format(409 + i), "1n", "IN_{}{}".format(ph, hl), "GND", k))
    return out


def gen_low_side_sense(block, spec, d):
    """三相下桥 25 mΩ 采样；进主控片内运放前加偏置：V+ = V_采样 · 15/16 + 3.3 V/16，放大 8 倍后零点 1.65 V"""
    p, k = block["params"], block["key"]
    out = []
    for i, ph in enumerate("UVW"):
        out.append(
            c.part(
                "R{}".format(411 + i),
                "Device:R",
                "25m",
                FP_R2512,
                k,
                {"1": "N_" + ph, "2": "GND"},
                "RES-SHUNT-25M",
                p["shunt"] + "（下桥采样电阻）" if i == 0 else "",
            )
        )
        out.append(
            _r(
                "R{}".format(414 + i),
                c.fmt(p["r_in"]),
                "N_" + ph,
                "ISNS_" + ph,
                k,
                "偏置网络：输入 {} / 偏置 {}（见计算书）".format(c.fmt(p["r_in"]), c.fmt(p["r_bias"]))
                if i == 0
                else "",
            )
        )
        out.append(_r("R{}".format(417 + i), c.fmt(p["r_bias"]), "+3V3", "ISNS_" + ph, k))
        out.append(_c("C{}".format(415 + i), "1n", "ISNS_" + ph, "GND", k, "抗混叠" if i == 0 else ""))
    # 母线电压检测
    out += _divider_top(
        ["R420", "R421", "R422"], "VBUS", "VBUS_SNS", "1M", k, "母线电压检测：3 MΩ / 22 kΩ，390 V → 2.84 V"
    )
    out += [_r("R423", "22k", "VBUS_SNS", "GND", k), _c("C418", "10n", "VBUS_SNS", "GND", k)]
    return out


# ------------------------------------------------------------------------------------------------- 电磁铁与步进


def gen_solenoid_drive(block, spec, d):
    """每路：80 V 管低边开关线圈；关断经“二极管 + 稳压管”钳位到 24 V + V_BR（计算书）。
    栅极要 10 V 级驱动（主控 3.3 V 推不动）：小管 2N7002 反相，15 V 经 4.7 kΩ 上拉；主控引脚上拉到 3.3 V，
    复位时（引脚悬空）小管导通、电磁铁不动作。"""
    p, k = block["params"], block["key"]
    out = [
        c.part(
            "J501",
            "Connector_Generic:Conn_01x08",
            "SOLENOIDS",
            "Connector_JST:JST_VH_B8P-VH_1x08_P3.96mm_Vertical",
            k,
            {str(2 * i + 1): "+24V" for i in range(4)} | {str(2 * i + 2): "SOL{}_D".format(i + 1) for i in range(4)},
            "CONN-VH8",
            "电磁铁 4 路（每路 +24 V 与漏极）：" + "、".join(n for n, _ in p["channels"]),
        )
    ]
    for i, (name, net) in enumerate(p["channels"]):
        n = i + 1
        dn, g, gi = "SOL{}_D".format(n), "SOL{}_G".format(n), net
        out += [
            c.part(
                "Q{}".format(500 + n),
                "Transistor_FET:BSC040N08NS5",
                p["fet"],
                FP_TDSON,
                k,
                {"1": "GND", "2": "GND", "3": "GND", "4": g, "5": dn},
                "MOS-80V",
                "{}电磁铁".format(name),
            ),
            _r("R{}".format(500 + n), "4.7k", "+15V", g, k, "栅极上拉到 15 V" if n == 1 else ""),
            _nfet("Q{}".format(504 + n), gi, g, "GND", k, "主控输出低 = 吸合" if n == 1 else ""),
            _r("R{}".format(504 + n), "10k", "+3V3", gi, k, "复位时保持不吸合" if n == 1 else ""),
            _d(
                "D{}".format(500 + n),
                p["diode"],
                dn,
                "SOL{}_K".format(n),
                k,
                FP_SMC,
                "DIO-ES3D",
                "钳位支路二极管" if n == 1 else "",
            ),
            c.part(
                "D{}".format(504 + n),
                "Device:D_Zener",
                p["tvs"],
                FP_SMB,
                k,
                {"1": "SOL{}_K".format(n), "2": "+24V"},
                "TVS-SMBJ24A",
                "钳位稳压管（反接，击穿电压 + 二极管压降 + 24 V = 关断时漏极电压）" if n == 1 else "",
            ),
        ]
    return out


def gen_stepper(block, spec, d):
    """TMC2226 独立模式（STEP/DIR，不用串口）。外围照 TMC2226-BOB 物料清单（Rev 1.00 2020-04-20）：
    采样电阻 0.12 Ω / 1 W（2010）、电荷泵 22 nF、VCP 100 nF、5VOUT 2.2 µF；VREF 与电流的关系待核对规格书。"""
    p, k = block["params"], block["key"]
    pins = {
        "1": "STP_OB1",
        "2": "STP_BRB",
        "3": "+24V",
        "4": "STP_OB2",
        "5": "STP_EN",
        "6": "GND",
        "7": "STP_CPO",
        "8": "STP_CPI",
        "9": "STP_VCP",
        "10": "GND",
        "11": "STP_5V",
        "12": "GND",
        "14": "GND",
        "15": "STP_DIAG",
        "17": "GND",
        "18": "GND",
        "19": "+3V3",
        "20": "STP_STEP",
        "21": "STP_VREF",
        "22": "GND",
        "23": "STP_DIR",
        "24": "GND",
        "25": "STP_OA2",
        "26": "+24V",
        "27": "STP_BRA",
        "28": "STP_OA1",
        "29": "GND",
    }
    return [
        c.part(
            "U501",
            "Driver_Motor:TMC2226-SA",
            p["driver"],
            "Package_SO:HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.75x6.2mm_ThermalVias",
            k,
            pins,
            "IC-TMC2226",
            "针距步进驱动：MS1、MS2 接地（8 细分）、SPREAD 接地（静音模式）、CLK 接地（片内时钟）、"
            "PDN_UART 接地（停转时电流减半）、STDBY 接地；以上独立模式接法待核对规格书",
        ),
        c.part(
            "J502",
            "Connector_Generic:Conn_01x04",
            "STEPPER",
            "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical",
            k,
            {"1": "STP_OA1", "2": "STP_OA2", "3": "STP_OB1", "4": "STP_OB2"},
            "CONN-XH4",
            "针距步进电机",
        ),
        c.part(
            "R509",
            "Device:R",
            "0.12",
            "Resistor_SMD:R_2010_5025Metric",
            k,
            {"1": "STP_BRA", "2": "GND"},
            "RES-2010-0R12",
            "采样电阻 0.12 Ω / 1 W（BOB 物料清单）",
        ),
        c.part(
            "R510",
            "Device:R",
            "0.12",
            "Resistor_SMD:R_2010_5025Metric",
            k,
            {"1": "STP_BRB", "2": "GND"},
            "RES-2010-0R12",
        ),
        _c("C501", "22n/50V", "STP_CPO", "STP_CPI", k, "电荷泵（BOB 物料清单）"),
        _c("C502", "100n/50V", "STP_VCP", "+24V", k),
        _c("C503", "2.2u", "STP_5V", "GND", k, "片内 5 V 稳压输出", FP_C0805, "CAP-0805"),
        _c("C504", "100n/50V", "+24V", "GND", k),
        c.part(
            "C505",
            "Device:C",
            "10u/50V",
            "Capacitor_SMD:C_1210_3225Metric",
            k,
            {"1": "+24V", "2": "GND"},
            "CAP-1210",
            "VS 去耦",
        ),
        _c("C506", "100n", "+3V3", "GND", k),
        _r("R511", "10k", "STP_5V", "STP_VREF", k, "VREF 分压（电流设定，见计算书；关系式待核对）"),
        _r("R512", "22k", "STP_VREF", "GND", k),
        _r("R513", "10k", "+3V3", "STP_EN", k, "EN 高 = 关断：主控没输出时步进不动"),
    ]


# ------------------------------------------------------------------------------------------------- 面板口隔离


def gen_panel_iso(block, spec, d):
    """面板口：主控 USART2（发送反相，TXINV）→ ADuM1201 → 隔离侧 MAX3485。
    ADuM1201 只有两路，RS-485 方向不单独占一路：发送反相后的信号同时接 DE 和 /RE，DI 接地——发 0 时驱动器把总线拉成 0，
    发 1 时驱动器关、接收开、总线靠偏置电阻回到 1。隔离侧 5 V 经 AMS1117 降到 3.3 V（MAX3485 是 3.3 V 器件）。"""
    p, k = block["params"], block["key"]
    return [
        c.part(
            "U601",
            "Isolator:ADuM1201AR",
            p["isolator"],
            "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            k,
            {
                "1": "+3V3",
                "2": "PNL_RX",
                "3": "PNL_TX",
                "4": "GND",
                "5": "GND_ISO",
                "6": "TXN_ISO",
                "7": "RO_ISO",
                "8": "+3V3_ISO",
            },
            "IC-ADUM1201",
            "数字隔离：B 通道主控 → 面板（发送），A 通道面板 → 主控（接收）",
        ),
        _c("C601", "100n", "+3V3", "GND", k),
        _c("C602", "100n", "+3V3_ISO", "GND_ISO", k),
        c.part(
            "U602",
            "wq:B0505S",
            p["dcdc"],
            "wq:Converter_SIP4_B0505S",
            k,
            {"1": "GND", "2": "+5V", "3": "GND_ISO", "4": "+5V_ISO"},
            "DCDC-B0505S",
            "隔离电源 5 V → 5 V 1 W（引脚 1 GND、2 Vin、3 0V、4 +Vo；引脚与封装待核对规格书）",
        ),
        c.part("C603", "Device:C", "4.7u/25V", FP_C1206, k, {"1": "+5V", "2": "GND"}, "CAP-1206"),
        c.part("C604", "Device:C", "10u/25V", FP_C1206, k, {"1": "+5V_ISO", "2": "GND_ISO"}, "CAP-1206"),
        c.part(
            "U603",
            "Regulator_Linear:AMS1117-3.3",
            "AMS1117-3.3",
            "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            k,
            {"1": "GND_ISO", "2": "+3V3_ISO", "3": "+5V_ISO"},
            "IC-LDO-3V3",
            "隔离侧 3.3 V",
        ),
        c.part("C605", "Device:C", "10u/25V", FP_C1206, k, {"1": "+3V3_ISO", "2": "GND_ISO"}, "CAP-1206"),
        c.part(
            "U604",
            "Interface_UART:MAX3485",
            "MAX3485ESA+T",
            "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            k,
            {
                "1": "RO_ISO",
                "2": "TXN_ISO",
                "3": "TXN_ISO",
                "4": "GND_ISO",
                "5": "GND_ISO",
                "6": "PNL_A",
                "7": "PNL_B",
                "8": "+3V3_ISO",
            },
            "IC-RS485",
            "RS-485 收发（DE、/RE 由发送信号控制，DI 接地）",
        ),
        _c("C606", "100n", "+3V3_ISO", "GND_ISO", k),
        _r("R601", "10k", "+3V3_ISO", "RO_ISO", k, "发送时接收器关、RO 高阻，上拉保持 1"),
        _r("R602", "680", "+3V3_ISO", "PNL_A", k, "总线空闲偏置（A 上拉、B 下拉）"),
        _r("R603", "680", "PNL_B", "GND_ISO", k),
        _r("R604", "120", "PNL_A", "PNL_B", k, "终端电阻（控制器在总线一端）"),
        c.part(
            "J601",
            "Connector_Generic:Conn_01x04",
            "PANEL",
            "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical",
            k,
            {"1": "+5V_ISO", "2": "PNL_A", "3": "PNL_B", "4": "GND_ISO"},
            "CONN-XH4",
            "操作面板（隔离侧，人能碰到的唯一接口）",
        ),
    ]


# ------------------------------------------------------------------------------------------------- 传感器输入（新单元）


def gen_sensor_inputs(block, spec, d):
    """电机编码器 A/B/Z 与霍尔 U/V/W：上拉到 5 V（集电极开路或推挽都能接）→ RC 滤波
    → SN74LVC14A 施密特整形（3.3 V 供电，输入耐 5 V）
    → 主控（反相由固件处理）。脚踏板霍尔 0.5–4.5 V 经 10 k / 20 k 分压进 ADC。"""
    p, k = block["params"], block["key"]
    sig = ["ENC_A", "ENC_B", "ENC_Z", "HALL_U", "HALL_V", "HALL_W"]
    outs = ["ENC_A_F", "ENC_B_F", "ENC_Z_F", "HALL_U_F", "HALL_V_F", "HALL_W_F"]
    gate_pins = [("1", "2"), ("3", "4"), ("5", "6"), ("9", "8"), ("11", "10"), ("13", "12")]
    pins = {"14": "+3V3", "7": "GND"}
    for (pi, po), s, o in zip(gate_pins, sig, outs, strict=True):
        pins[pi] = s + "_RC"
        pins[po] = o
    out = [
        c.part(
            "J701",
            "Connector_Generic:Conn_01x08",
            "ENCODER",
            "Connector_JST:JST_XH_B8B-XH-A_1x08_P2.50mm_Vertical",
            k,
            {
                "1": "+5V",
                "2": "GND",
                "3": "ENC_A",
                "4": "ENC_B",
                "5": "ENC_Z",
                "6": "HALL_U",
                "7": "HALL_V",
                "8": "HALL_W",
            },
            "CONN-XH8",
            "电机编码器与霍尔",
        ),
        c.part(
            "U701",
            "74xx:74HC14",
            "SN74LVC14APWR",
            "Package_SO:TSSOP-14_4.4x5mm_P0.65mm",
            k,
            pins,
            "IC-74LVC14",
            "施密特整形（六路）",
        ),
        _c("C701", "100n", "+3V3", "GND", k),
        c.part(
            "J702",
            "Connector_Generic:Conn_01x03",
            "PEDAL",
            "Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
            k,
            {"1": "+5V", "2": "PEDAL_IN", "3": "GND"},
            "CONN-XH3",
            "脚踏板（霍尔，0.5–4.5 V）",
        ),
        _r("R701", "10k", "PEDAL_IN", "PEDAL", k, "脚踏分压 × 2/3：4.5 V → 3.0 V"),
        _r("R702", "20k", "PEDAL", "GND", k),
        _c("C702", "100n", "PEDAL", "GND", k),
    ]
    for i, s in enumerate(sig):
        out += [
            _r("R{}".format(703 + i), c.fmt(p["r_pullup"]), "+5V", s, k, "上拉到 5 V" if i == 0 else ""),
            _r(
                "R{}".format(709 + i),
                c.fmt(p["r_filter"]),
                s,
                s + "_RC",
                k,
                "RC 滤波（截止频率见计算书）" if i == 0 else "",
            ),
            _c("C{}".format(703 + i), c.fmt(p["c_filter"]), s + "_RC", "GND", k),
        ]
    return out


def calc_sensor_inputs(block, spec, d, parts):
    """RC 滤波的截止频率要高于编码器最高脉冲频率（留余量）；脚踏分压后不超过 ADC 满量程"""
    p = block["params"]
    fc = 1 / (2 * math.pi * p["r_filter"] * p["c_filter"])
    lines = p.get("encoder_lines")
    f_max = None if not lines else lines * spec["speed_max_rpm"] / 60
    v_pedal = p["pedal_v_max"] * 20e3 / (10e3 + 20e3)
    items = [
        c.item("fc", "编码器输入 RC 截止频率", fc, "Hz", "f_c = 1 / (2π·R·C)"),
        c.item(
            "f_max",
            "编码器最高脉冲频率",
            f_max,
            "Hz",
            "线数 × n_max / 60",
            note="电机未选型：线数是示例值" if lines else "电机线数未定",
        ),
        c.item("v_pedal", "脚踏信号分压后最高电压", v_pedal, "V", "V_max × 20 k / 30 k"),
    ]
    checks = [
        c.judge(
            "fc",
            "截止频率 ≥ 余量 × 最高脉冲频率",
            None if f_max is None else p["fc_margin"] * f_max,
            fc,
            "Hz",
            "f_c ≥ {:g} × f_max".format(p["fc_margin"]),
            status=c.UNKNOWN if f_max is None else (c.PASS if fc >= p["fc_margin"] * f_max else c.FAIL),
            note="线数是示例值（电机未选型）",
        ),
        c.judge(
            "v_pedal",
            "脚踏信号不超过 ADC 满量程",
            v_pedal,
            3.3,
            "V",
            "V ≤ 3.3 V",
            status=c.PASS if v_pedal <= 3.3 else c.FAIL,
            note="脚踏输出 {:g} V 是示例值".format(p["pedal_v_max"]),
        ),
    ]
    return items, checks
