# -*- coding: utf-8 -*-
"""关节伺服驱动板 DRV-JOINT 的设计描述（第 88 轮，电子 E4）：器件、数值、封装、每个引脚接哪个网络。
原理图、PCB、BOM 都从这一份生成（build.py）。示例设计，未经硬件验证，不能直接投产。

数值怎么来（与数字工厂电路分析 cae/circuit.py 的例题同一组数，测试核对）：
  - 母线 48 V；额定相电流 ≈ 8.5 A（400 W 伺服电机额定力矩 1.27 N·m ÷ 力矩常数 0.15 N·m/A，示例）
  - 相电流采样：采样电阻 2 mΩ × 放大 20 倍（INA240A1 的固定增益）= 40 mV/A，零点 1.65 V，量程 ±41 A
  - 栅极：驱动 12 V，栅极电阻 10 Ω（例题 2）；死区由 MCU 定时器给（约 200 ns，示例）
  - 母线电容 470 μF / 63 V（例题 3）；每个半桥旁 2.2 μF / 100 V 陶瓷电容就近吸收开关电流
  - 编码器 A/B/Z 进 MCU 前 RC 滤波 1 kΩ / 220 pF（例题 4，截止 ≈ 723 kHz）
  - 12 V：LMR16006Y 降压，L = (Vin−Vo)·Vo/(Vin·f·ΔI)，f = 2.1 MHz、ΔI = 0.3 × 0.6 A → 23.8 μH，取 22 μH；
    反馈 Vo = Vref·(1 + Rt/Rb)，Vref 0.765 V（按器件手册，选型时核对）、Rb 10 kΩ → Rt = 147 kΩ
  - 母线电压检测：(51 k + 51 k) / 6.8 k 分压，48 V → 3.0 V，满量程 52.8 V
示例选型（KiCad 官方库里有的器件，引脚取自库，未经硬件验证）：MCU STM32G431CBT6、半桥驱动 IR2101S × 3、
MOSFET BSC040N08NS5 × 6、电流采样放大 INA240A1D × 3、CAN 收发 MCP2562-E/SN、RS-485 收发 MAX3485 × 2、
降压 LMR16006YQ、线性稳压 AMS1117-5.0 / -3.3。
"""
from __future__ import annotations

# 第 98 轮：B 版（设计对照，不投产）在 A 版上打补丁——编码器经 WQ-ENCIF 计数，MCU 用 SPI1 读。
# drv_joint_b.py 以 REV = "B" 执行本文件；直接 import 本模块就是 A 版（A 版一字不动）。
REV = globals().get("REV", "A")

RS_MOHM = 2.0            # 采样电阻 mΩ
GAIN = 20.0              # INA240A1 增益
RG_OHM = 10.0            # 栅极电阻 Ω
VDRV = 12.0              # 栅极驱动电压 V
C_BUS_UF = 470.0         # 母线电容 μF
ENC_R_OHM = 1000.0       # 编码器滤波电阻 Ω
ENC_C_PF = 220.0         # 编码器滤波电容 pF
BOARD_MM = (100.0, 70.0)  # 板子外形（示例）
LAYERS = 4

SHEETS = [
    ("power", "48 V 输入与母线", "48 V input and DC bus"),
    ("aux", "辅助电源 12 / 5 / 3.3 V", "Auxiliary supplies"),
    ("bridge", "三相桥", "Three-phase bridge"),
    ("gate", "栅极驱动", "Gate drivers"),
    ("sense", "相电流采样与电机输出", "Phase current sensing"),
    ("mcu", "MCU 与烧录口", "MCU and programming"),
    ("io", "编码器接口与 CAN", "Encoder and CAN"),
]

FP_R = "Resistor_SMD:R_0402_1005Metric"
FP_C = "Capacitor_SMD:C_0402_1005Metric"
FP_C1206 = "Capacitor_SMD:C_1206_3216Metric"
FP_SOIC8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
FP_TP = "TestPoint:TestPoint_Pad_D1.0mm"

PARTS = []


def part(ref, lib, value, fp, sheet, pins, item=None, note=""):
    PARTS.append({"ref": ref, "lib": lib, "value": value, "fp": fp, "sheet": sheet, "pins": dict(pins), "item": item, "note": note})


def R(ref, value, a, b, sheet, note=""):
    part(ref, "Device:R", value, FP_R, sheet, {"1": a, "2": b}, "RES-0402", note)


def C(ref, value, a, b, sheet, fp=FP_C, item="CAP-0402", note=""):
    part(ref, "Device:C", value, fp, sheet, {"1": a, "2": b}, item, note)


def TIE(ref, a, b, sheet, note=""):
    """网络连接点（net tie）：大电流网络上单独引出的细信号线（开尔文采样、驱动参考点），不进 BOM"""
    part(ref, "Device:NetTie_2", "NetTie", "NetTie:NetTie-2_SMD_Pad0.5mm", sheet, {"1": a, "2": b}, None, note)


def TP(ref, net, sheet, note=""):
    part(ref, "Connector:TestPoint", net, FP_TP, sheet, {"1": net}, None, note or "测试点（ICT 针床 / 烧录夹具）")


# ------------------------------------------------------------------ 1 输入与母线
part("J1", "Connector:Screw_Terminal_01x02", "48V IN", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal",
     "power", {"1": "VBUS", "2": "GND"}, "CONN-PWR")
TIE("NT10", "VBUS", "VBUS_AUX", "power", "辅助电源从母线单独引出")
part("C1", "Device:C_Polarized", "470u/63V", "Capacitor_SMD:CP_Elec_16x17.5", "power", {"1": "VBUS", "2": "GND"}, "CAP-BULK", "母线电容（例题 3）")
R("R1", "51k", "VBUS_AUX", "VB_MID", "power", "母线电压分压")
R("R2", "51k", "VB_MID", "VBUS_SNS", "power")
R("R3", "6.8k", "VBUS_SNS", "GND", "power")
C("C2", "10n", "VBUS_SNS", "GND", "power")

# ------------------------------------------------------------------ 2 辅助电源
part("U1", "Regulator_Switching:LMR16006YQ", "LMR16006YQ", "Package_TO_SOT_SMD:SOT-23-6", "aux",
     {"1": "SW_CB", "2": "GND", "3": "FB12", "4": "EN12", "5": "VBUS_AUX", "6": "SW12"}, "IC-BUCK", "48 V → 12 V 降压（示例选型）")
C("C3", "2.2u/100V", "VBUS_AUX", "GND", "aux", FP_C1206, "CAP-1206")
R("R4", "100k", "VBUS_AUX", "EN12", "aux", "使能上拉")
C("C4", "100n", "SW_CB", "SW12", "aux", note="自举电容")
part("D1", "Device:D_Schottky", "60V 1A", "Diode_SMD:D_SMA", "aux", {"1": "SW12", "2": "GND"}, "DIO-SMD", "续流二极管")
part("L1", "Device:L", "22u", "Inductor_SMD:L_Bourns_SRN6045TA", "aux", {"1": "SW12", "2": "+12V"}, "IND-PWR")
R("R5", "147k", "+12V", "FB12", "aux", "反馈上电阻")
R("R6", "10k", "FB12", "GND", "aux", "反馈下电阻")
C("C5", "22u/25V", "+12V", "GND", "aux", FP_C1206, "CAP-1206")
part("U2", "Regulator_Linear:AMS1117-5.0", "AMS1117-5.0", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "aux",
     {"1": "GND", "2": "+5V", "3": "+12V"}, "IC-LDO")
C("C6", "10u/25V", "+5V", "GND", "aux", FP_C1206, "CAP-1206")
part("U3", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2", "aux",
     {"1": "GND", "2": "+3V3", "3": "+5V"}, "IC-LDO")
C("C7", "10u/25V", "+3V3", "GND", "aux", FP_C1206, "CAP-1206")

# ------------------------------------------------------------------ 3 三相桥 + 4 栅极驱动 + 5 采样
PH = ["A", "B", "C"]
for i, ph in enumerate(PH):
    n = i + 1
    part("Q{}".format(2 * i + 1), "Transistor_FET:BSC040N08NS5", "BSC040N08NS5", "Package_TO_SOT_SMD:TDSON-8-1", "bridge",
         {"1": "SW_" + ph, "2": "SW_" + ph, "3": "SW_" + ph, "4": "GH_" + ph, "5": "VBUS"}, "MOS-80V", "{} 相上管（示例选型）".format(ph))
    part("Q{}".format(2 * i + 2), "Transistor_FET:BSC040N08NS5", "BSC040N08NS5", "Package_TO_SOT_SMD:TDSON-8-1", "bridge",
         {"1": "GND", "2": "GND", "3": "GND", "4": "GL_" + ph, "5": "SW_" + ph}, "MOS-80V", "{} 相下管".format(ph))
    C("C{}".format(10 + n), "2.2u/100V", "VBUS", "GND", "bridge", FP_C1206, "CAP-1206", note="{} 相半桥就近吸收".format(ph))
    # 栅极驱动
    part("U{}".format(3 + n), "Driver_FET:IR2101", "IR2101S", FP_SOIC8, "gate",
         {"1": "+12V", "2": "PWM_{}H".format(ph), "3": "PWM_{}L".format(ph), "4": "GND", "5": "LO_" + ph, "6": "VS_" + ph,
          "7": "HO_" + ph, "8": "VB_" + ph}, "IC-GDRV", "{} 相半桥驱动（示例选型）".format(ph))
    R("R{}".format(10 + 2 * i), "10", "HO_" + ph, "GH_" + ph, "gate", "栅极电阻（例题 2）")
    R("R{}".format(11 + 2 * i), "10", "LO_" + ph, "GL_" + ph, "gate")
    part("D{}".format(1 + n), "Device:D_Schottky", "100V 1A", "Diode_SMD:D_SOD-123", "gate", {"1": "VB_" + ph, "2": "+12V"}, "DIO-SMD", "自举二极管")
    C("C{}".format(20 + n), "1u/25V", "VB_" + ph, "VS_" + ph, "gate", note="自举电容")
    TIE("NT{}".format(6 + n), "SW_" + ph, "VS_" + ph, "gate", "{} 相驱动参考点 VS 从采样电阻焊盘单独引出".format(ph))
    C("C{}".format(23 + n), "1u/25V", "+12V", "GND", "gate")
    # 采样（相线串联采样电阻，INA240 双向，REF1 接 3.3 V、REF2 接地 → 零点 1.65 V）
    part("R{}".format(20 + n), "Device:R", "2m 1%", "Resistor_SMD:R_2512_6332Metric", "sense",
         {"1": "SW_" + ph, "2": "MOT_" + ph}, "RES-SHUNT", "{} 相采样电阻（例题 1），两端开尔文引线到 INA240".format(ph))
    TIE("NT{}".format(2 * i + 1), "SW_" + ph, "SNSP_" + ph, "sense", "开尔文引线（采样电阻电源端）")
    TIE("NT{}".format(2 * i + 2), "MOT_" + ph, "SNSN_" + ph, "sense", "开尔文引线（采样电阻电机端）")
    part("U{}".format(6 + n), "Amplifier_Current:INA240A1D", "INA240A1D", FP_SOIC8, "sense",
         {"1": "SNSN_" + ph, "2": "GND", "3": "GND", "4": "GND", "5": "ISNS_" + ph, "6": "+3V3", "7": "+3V3", "8": "SNSP_" + ph},
         "IC-AMP", "{} 相电流采样放大 20 倍（示例选型）".format(ph))
    C("C{}".format(26 + n), "100n", "+3V3", "GND", "sense")
    C("C{}".format(29 + n), "1n", "ISNS_" + ph, "GND", "sense", note="ADC 抗混叠")
part("J2", "Connector:Screw_Terminal_01x03", "MOTOR UVW", "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-3_1x03_P5.00mm_Horizontal",
     "sense", {"1": "MOT_A", "2": "MOT_B", "3": "MOT_C"}, "CONN-PWR")

# ------------------------------------------------------------------ 6 MCU
MCU = {"1": "+3V3", "5": "OSC_IN", "6": "OSC_OUT", "7": "NRST", "8": "ISNS_A", "9": "ISNS_B", "10": "ISNS_C", "11": "VBUS_SNS",
       "14": "ENC_A_F", "15": "ENC_B_F", "16": "ENC_Z_F", "19": "GND", "20": "+3V3", "21": "+3V3", "23": "GND", "24": "+3V3",
       "27": "PWM_AL", "28": "PWM_BL", "29": "PWM_CL", "30": "PWM_AH", "31": "PWM_BH", "32": "PWM_CH", "33": "CAN_RXD", "34": "CAN_TXD",
       "35": "GND", "36": "+3V3", "37": "SWDIO", "38": "SWCLK", "40": "SSI_CLK", "41": "SSI_DATA", "45": "BOOT0", "47": "GND", "48": "+3V3"}
part("U10", "MCU_ST_STM32G4:STM32G431CBTx", "STM32G431CBT6", "Package_QFP:LQFP-48_7x7mm_P0.5mm", "mcu",
     MCU, "IC-MCU-MC", "电机控制 MCU（示例选型）：TIM1 三相互补 PWM、ADC 采三相电流与母线、TIM3 编码器、SPI1 读 SSI、FDCAN1")
for k, ref in enumerate(["C40", "C41", "C42", "C43"]):
    C(ref, "100n", "+3V3", "GND", "mcu")
C("C44", "4.7u", "+3V3", "GND", "mcu")
C("C45", "1u", "+3V3", "GND", "mcu", note="VDDA")
C("C46", "100n", "NRST", "GND", "mcu")
R("R30", "10k", "BOOT0", "GND", "mcu", "BOOT0 下拉")
part("Y1", "Device:Crystal_GND24", "8MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", "mcu",
     {"1": "OSC_IN", "2": "GND", "3": "OSC_OUT", "4": "GND"}, "XTAL")
C("C47", "10p", "OSC_IN", "GND", "mcu")
C("C48", "10p", "OSC_OUT", "GND", "mcu")
TP("TP1", "SWDIO", "mcu", "烧录口（烧录工位 PG-1 的弹簧针夹具）")
TP("TP2", "SWCLK", "mcu", "烧录口")
TP("TP3", "NRST", "mcu", "烧录口")
TP("TP4", "+3V3", "mcu", "烧录口供电")
TP("TP5", "GND", "mcu", "烧录口地")

# ------------------------------------------------------------------ 7 编码器与 CAN
part("J3", "Connector_Generic:Conn_01x05", "ENC ABZ", "Connector_JST:JST_XH_B5B-XH-A_1x05_P2.50mm_Vertical", "io",
     {"1": "+5V", "2": "GND", "3": "ENC_A", "4": "ENC_B", "5": "ENC_Z"}, "CONN-SIG", "A/B/Z（2500 线，示例）")
for k, s in enumerate(["A", "B", "Z"]):
    R("R{}".format(31 + k), "1k", "ENC_" + s, "ENC_{}_F".format(s), "io", "编码器滤波（例题 4）")
    C("C{}".format(50 + k), "220p", "ENC_{}_F".format(s), "GND", "io")
part("U11", "Interface_UART:MAX3485", "MAX3485", FP_SOIC8, "io",
     {"1": "NC_U11", "2": "+3V3", "3": "+3V3", "4": "SSI_CLK", "5": "GND", "6": "SSIC_P", "7": "SSIC_N", "8": "+3V3"}, "IC-RS485",
     "SSI 时钟发送（示例选型）")
part("U12", "Interface_UART:MAX3485", "MAX3485", FP_SOIC8, "io",
     {"1": "SSI_DATA", "2": "GND", "3": "GND", "4": "GND", "5": "GND", "6": "SSID_P", "7": "SSID_N", "8": "+3V3"}, "IC-RS485",
     "SSI 数据接收")
C("C53", "100n", "+3V3", "GND", "io")
C("C54", "100n", "+3V3", "GND", "io")
R("R34", "120", "SSID_P", "SSID_N", "io", "终端电阻")
part("J4", "Connector_Generic:Conn_01x06", "ENC SSI", "Connector_JST:JST_XH_B6B-XH-A_1x06_P2.50mm_Vertical", "io",
     {"1": "+5V", "2": "GND", "3": "SSIC_P", "4": "SSIC_N", "5": "SSID_P", "6": "SSID_N"}, "CONN-SIG", "输出端绝对值编码器")
part("U13", "Interface_CAN_LIN:MCP2562-E-SN", "MCP2562-E/SN", FP_SOIC8, "io",
     {"1": "CAN_TXD", "2": "GND", "3": "+5V", "4": "CAN_RXD", "5": "+3V3", "6": "CANL", "7": "CANH", "8": "GND"}, "IC-CAN",
     "CAN 收发（示例选型）")
C("C55", "100n", "+5V", "GND", "io")
C("C56", "100n", "+3V3", "GND", "io")
R("R35", "120", "CANH", "CANL", "io", "CAN 终端电阻")
part("J5", "Connector_Generic:Conn_01x04", "CAN", "Connector_JST:JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical", "io",
     {"1": "CANH", "2": "CANL", "3": "GND", "4": "+5V"}, "CONN-SIG")

# ------------------------------------------------------------------ B 版补丁（第 98 轮）
B_CHANGES = []          # (位号, 改了什么) —— 页面“A→B 改了什么”用
if REV == "B":
    TITLE = "关节伺服驱动板 DRV-JOINT B 版（放上编码器接口芯片 WQ-ENCIF；设计对照，不投产）"
    _mcu = next(p for p in PARTS if p["ref"] == "U10")
    # PA4–PA7 = SPI1（NSS / SCK / MISO / MOSI，AF5）接芯片；PB1 接芯片复位；PB0 空出。SSI 仍在 PB3 / PB4（改用 SPI3，AF6，引脚不变）
    for pin, (old, new) in {"12": (None, "ENC_CS_N"), "13": (None, "ENC_SCK"), "14": ("ENC_A_F", "ENC_MISO"),
                            "15": ("ENC_B_F", "ENC_MOSI"), "16": ("ENC_Z_F", None), "17": (None, "ENC_RST_N")}.items():
        if new is None:
            _mcu["pins"].pop(pin, None)
        else:
            _mcu["pins"][pin] = new
        B_CHANGES.append(("U10", "引脚 {}：{} → {}".format(pin, old or "未用", new or "未用")))
    _mcu["note"] = "电机控制 MCU（示例选型）：TIM1 三相互补 PWM、ADC 采三相电流与母线、SPI1 读编码器接口芯片 U14、SPI3 读 SSI、FDCAN1"
    part("U14", "wq:WQ-ENCIF", "WQ-ENCIF", "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm", "io",
         {"1": "ENC_A_F", "2": "ENC_B_F", "3": "ENC_Z_F", "4": "GND", "5": "ENC_CLK", "6": "ENC_RST_N", "7": "+1V8", "8": "GND",
          "9": "ENC_CS_N", "10": "ENC_SCK", "11": "ENC_MOSI", "12": "ENC_MISO", "13": "+3V3", "14": "GND", "17": "GND"},
         "IC-ENCIF", "编码器接口芯片 WQ-ENCIF（第 92 轮设计，未流片）：滤波、4 倍频计数、SPI 从机")
    part("Y2", "Oscillator:ASE-xxxMHz", "50MHz", "Oscillator:Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm", "io",
         {"1": "+3V3", "2": "GND", "3": "ENC_CLK", "4": "+3V3"}, "OSC-50M", "芯片时钟 50 MHz 有源晶振（示例选型）")
    part("U15", "Regulator_Linear:AP2112K-1.8", "AP2112K-1.8", "Package_TO_SOT_SMD:SOT-23-5", "io",
         {"1": "+3V3", "2": "GND", "3": "+3V3", "5": "+1V8"}, "IC-LDO18", "芯片核心电源 1.8 V（示例选型）")
    C("C57", "100n", "+3V3", "GND", "io", note="U14 VDDIO 去耦")
    C("C58", "100n", "+1V8", "GND", "io", note="U14 VCCD 去耦")
    C("C59", "1u", "+3V3", "GND", "io", note="U15 输入")
    C("C60", "1u", "+1V8", "GND", "io", note="U15 输出")
    C("C61", "100n", "+3V3", "GND", "io", note="Y2 去耦")
    for _r in ("U14", "Y2", "U15", "C57", "C58", "C59", "C60", "C61"):
        B_CHANGES.append((_r, "新增：" + next(p["note"] for p in PARTS if p["ref"] == _r)))

# ICT 测试点：没有通孔焊盘可扎的网络，每个在底面放一个测试点（针床从底面扎；间距 ≥ 2.5 mm）
_THT_NETS = {n for p in PARTS if p["ref"].startswith("J") for n in p["pins"].values()}
_HAS_TP = {p["pins"]["1"] for p in PARTS if p["ref"].startswith("TP")}
ICT_NETS = sorted({n for p in PARTS for n in p["pins"].values()} - _THT_NETS - _HAS_TP - {"NC_U11", "SW_A", "SW_B", "SW_C"})
for _k, _n in enumerate(ICT_NETS):
    TP("TP{}".format(10 + _k), _n, "mcu" if _n not in ("VBUS", "SW12", "EN12", "FB12", "SW_CB", "VB_MID", "VBUS_SNS") else "power",
       "ICT 测试点")

# 没用到的 MCU 引脚、器件引脚：原理图上画不连接标记
NC_NETS = {"NC_U11"}
POWER_NETS = {"VBUS", "GND", "+12V", "+5V", "+3V3"}
HIGH_CURRENT = {"VBUS": 9.0, "GND": 9.0, "SW_A": 8.5, "SW_B": 8.5, "SW_C": 8.5, "MOT_A": 8.5, "MOT_B": 8.5, "MOT_C": 8.5}   # 连续电流 A（示例）

# 电路板厂清单里 SMT 段（贴片板 SMT-DRV）与后段（成品板 DRV-JOINT）各用哪些
BACK_END_ITEMS = {"CONN-PWR", "CONN-SIG"}


def nets():
    out = {}
    for p in PARTS:
        for pin, n in p["pins"].items():
            out.setdefault(n, []).append((p["ref"], pin))
    return out


def bom_by_item():
    out = {}
    for p in PARTS:
        if p["item"]:
            out[p["item"]] = out.get(p["item"], 0) + 1
    return out


# ------------------------------------------------------------------ 摆放（板子左上角为原点，x 向右、y 向下，mm；角度逆时针；面 F 顶 / B 底）
COLS = {"A": 44.0, "B": 60.0, "C": 76.0}
PLACEMENT = {
    "J1": (6, 6, 270, "F"), "NT10": (17.75, 16.45, 270, "F"), "C1": (24, 11, 0, "F"),
    "R1": (21, 24, 0, "F"), "R2": (24, 24, 0, "F"), "R3": (27, 24, 0, "F"), "C2": (27, 26, 0, "F"),
    "U1": (9, 30, 0, "F"), "C3": (4, 30, 90, "F"), "R4": (9, 26, 0, "F"), "C4": (12.5, 27, 90, "F"), "D1": (9, 36, 0, "F"),
    "L1": (18, 31, 0, "F"), "R5": (14, 37, 90, "F"), "R6": (16, 37, 90, "F"), "C5": (23.5, 32, 90, "F"),
    "U2": (9, 46, 0, "F"), "C6": (16, 46, 90, "F"), "U3": (9, 57, 0, "F"), "C7": (16, 57, 90, "F"),
    "J2": (93.5, 7, 270, "F"),
    "U10": (40, 58, 0, "F"), "Y1": (31, 63, 0, "F"), "C47": (28, 60, 90, "F"), "C48": (28, 66, 90, "F"),
    "C40": (33.3, 54, 90, "F"), "C41": (46.7, 54, 90, "F"), "C42": (46.7, 62, 90, "F"), "C43": (33.3, 58, 90, "F"),
    "C44": (40, 65.5, 0, "F"), "C45": (40, 50.5, 0, "F"), "C46": (36, 66, 0, "F"), "R30": (44, 66, 0, "F"),
    "TP1": (30, 46, 0, "B"), "TP2": (33, 46, 0, "B"), "TP3": (36, 46, 0, "B"), "TP4": (39, 46, 0, "B"), "TP5": (42, 46, 0, "B"),
    "R31": (50, 53, 0, "F"), "R32": (50, 55, 0, "F"), "R33": (50, 57, 0, "F"),
    "C50": (53, 53, 0, "F"), "C51": (53, 55, 0, "F"), "C52": (53, 57, 0, "F"),
    "J3": (52, 64.5, 0, "F"), "J4": (70, 64.5, 0, "F"), "J5": (95, 40, 270, "F"),
    "U11": (62, 54, 0, "F"), "U12": (73, 54, 0, "F"), "C53": (66.5, 50.5, 0, "F"), "C54": (77.5, 50.5, 0, "F"), "R34": (77.5, 57.5, 0, "F"),
    "U13": (85, 54, 0, "F"), "C55": (89, 50.5, 0, "F"), "C56": (89, 57.5, 0, "F"), "R35": (85, 58.5, 0, "F"),
}
for _i, _ph in enumerate(PH):          # 开尔文连接点 NT：一端压在采样电阻焊盘上
    _x = COLS[_ph]
    PLACEMENT.update({
        "Q{}".format(2 * _i + 1): (_x, 7, 180, "F"), "Q{}".format(2 * _i + 2): (_x, 15.5, 0, "F"), "C{}".format(11 + _i): (_x - 6.3, 9.5, 180, "F"),
        "R{}".format(21 + _i): (_x, 23.5, 0, "F"),
        "U{}".format(4 + _i): (_x, 31, 0, "F"), "C{}".format(24 + _i): (_x - 5.5, 31, 90, "F"),
        "R{}".format(10 + 2 * _i): (_x - 3, 36.5, 90, "F"), "R{}".format(11 + 2 * _i): (_x - 1.5, 36.5, 90, "F"),
        "D{}".format(2 + _i): (_x + 2, 37, 90, "F"), "C{}".format(21 + _i): (_x + 4.5, 37, 90, "F"),
        "U{}".format(7 + _i): (_x, 44, 0, "F"), "NT{}".format(1 + 2 * _i): (_x - 2.96, 25.85, 270, "F"), "NT{}".format(7 + _i): (_x - 4.12, 24.95, 180, "F"), "NT{}".format(2 + 2 * _i): (_x + 2.96, 25.85, 270, "F"), "C{}".format(27 + _i): (_x - 5.5, 44, 90, "F"), "C{}".format(30 + _i): (_x + 5.5, 44, 90, "F"),
    })
HOLES = [(4, 66), (96, 66), (96, 27), (4, 21)]          # M3 安装孔，焊盘接地
if REV == "B":          # B 版新增器件放底面（顶面这一带已满；底面只有测试点）
    PLACEMENT.update({"U14": (58, 54, 0, "B"), "C57": (58, 50.5, 0, "B"), "C58": (61.5, 54, 90, "B"),
                      "Y2": (64.5, 58, 0, "B"), "C61": (64.5, 54.5, 0, "B"),
                      "U15": (70, 53, 0, "B"), "C59": (67, 53, 90, "B"), "C60": (73, 53, 90, "B")})

# 底面测试点的位置：三排，间距 2.8 mm（避开通孔焊盘和安装孔；底面没有别的器件）
_TP_ALL = ["TP{}".format(k) for k in range(1, 6)] + ["TP{}".format(10 + k) for k in range(len(ICT_NETS))]
_TP_SPOTS = [(8 + 2.8 * i, 41.0) for i in range(30)] + [(8 + 2.8 * i, 44.5) for i in range(30)] + [(8 + 2.8 * i, 48.0) for i in range(14)]
for _ref, (_x, _y) in zip(_TP_ALL, _TP_SPOTS):
    PLACEMENT[_ref] = (round(_x, 2), _y, 0, "B")

# 大电流路径上的焊盘（DFM 查这些焊盘之间有一条足够宽的铜路径）
POWER_PADS = {"VBUS": [("J1", "1"), ("C1", "1")], "MOT_A": [], "MOT_B": [], "MOT_C": []}
for _i, _ph in enumerate(PH):
    POWER_PADS["VBUS"] += [("Q{}".format(2 * _i + 1), "5"), ("C{}".format(11 + _i), "1")]
    POWER_PADS["SW_" + _ph] = [("Q{}".format(2 * _i + 1), "1"), ("Q{}".format(2 * _i + 2), "5"), ("R{}".format(21 + _i), "1")]
    POWER_PADS["MOT_" + _ph] = [("R{}".format(21 + _i), "2"), ("J2", str(_i + 1))]


# 功率铺铜（顶层）：母线 VBUS 一条横带 + 每相落到上管漏极和吸收电容；每相半桥中点 SW 从上管源极经下管漏极到采样电阻。
# 宽度都 ≥ 2 mm（IPC-2221：8.5–9 A、2 oz、温升 20 ℃ 要约 1.9–2.0 mm）；多边形顶点 mm，板子左上角为原点。
def _sw_poly(x):
    return [
        (x + 2.0, 5.8), (x + 4.2, 5.8), (x + 4.2, 20.8), (x - 1.6, 20.8), (x - 1.6, 24.3), (x - 3.9, 24.3), (x - 3.9, 18.3),
        (x - 1.9, 18.3), (x - 1.9, 13.0), (x - 3.0, 13.0), (x - 3.0, 9.6), (x + 2.0, 9.6)]


POURS = [("VBUS", "F.Cu", [(3.0, 1.0), (COLS["C"] + 1.6, 1.0), (COLS["C"] + 1.6, 9.2)] + sum(
    [[(COLS[ph] + 1.6, 4.4) if k else (COLS[ph] + 1.6, 9.2), (COLS[ph] + 1.6, 9.2), (COLS[ph] - 3.6, 9.2), (COLS[ph] - 3.6, 10.2),
      (COLS[ph] - 5.8, 10.2), (COLS[ph] - 5.8, 4.4)][1 if not k else 0:] for k, ph in enumerate(["C", "B", "A"])], []) +
    [(20.0, 4.4), (20.0, 9.0), (15.0, 9.0), (15.0, 4.4), (9.0, 4.4), (9.0, 8.0), (3.0, 8.0)])]
POURS += [("SW_" + ph, "F.Cu", _sw_poly(COLS[ph])) for ph in PH]
