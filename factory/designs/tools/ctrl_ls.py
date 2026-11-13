# -*- coding: utf-8 -*-
"""平缝机控制器 CTRL-LS 的设计数据（第 159 轮 159d1）：读设计描述 `factory/designs/ctrl-ls/design.yaml`、由功能块展开，
放成原理图生成程序（sch.py）要的名字。和 drv_joint.py 同一个做法；改设计请改 YAML。示例设计，未经硬件验证，不能直接投产。"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DESIGNS = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_DESIGNS)), "eda"))

from wqeda.schema import design as _wq  # noqa: E402

DESIGN_PATH = os.path.join(_DESIGNS, "ctrl-ls", "design.yaml")
DOC = _wq.load_design(DESIGN_PATH)
X = _wq.expand(DOC)
REV = X["rev"]
TITLE = "平缝机控制器 CTRL-LS Lockstitch sewing machine controller（示例设计，未经硬件验证）"
SCH_TITLE_BLOCK = {"prefix": "CTRL-LS", "date": "2026-11-12", "rev": "示例 A",
                   "company": "问渠数字工业园 · 电路板厂（示例设计，未经硬件验证，不能直接投产）"}
ROOT_TEXT = ("平缝机控制器 CTRL-LS：单相 90–250 V 输入 → 功率因数校正 → 390 V 母线 → 智能功率模块 → 主轴电机；"
             "电磁铁 4 路、针距步进、隔离面板口。整块板以母线负端为地，只有面板口隔离。示例设计，未经硬件验证。")
SCH_AUTO_PAPER = True
# 隔离带（159d2b）：右下角是隔离面板口（GND_ISO 一侧）。竖带中心 x、横带中心 y、宽度 mm；带里不走线、不打过孔、不铺铜。
# 隔离电源 B0505S 的 2、3 脚只隔 2.54 mm（器件自己的引脚，按它的额定），带在那里收窄成 NOTCH 宽
BARRIER = {"x": 212.0, "y": 116.0, "w": 4.0, "notch_y": (130.5, 133.5), "notch_w": 1.4}
SHEETS = X["sheets"]
PARTS = [{"ref": q["ref"], "lib": q["lib"], "value": q["value"], "fp": q["fp"], "sheet": q["block"], "pins": q["pins"],
          "item": q["item"], "note": q["note"]} for q in X["parts"]]
NC_NETS = X["nc_nets"]
POWER_NETS = X["power_nets"]
SHEET_NOTES = {
    "mains": "交流 L/N 从 J101 进（保护地线直接接电控箱的接地螺柱，Y 电容经安装孔 H1 接箱体）：保险丝 F101、压敏 RV101、X 电容 C101（R101/R102 放电）、共模电感 L101、Y 电容 C102/C103；"
             "热敏电阻 TH101 限上电浪涌，母线充好后校正控制器的 VB_OK 让 K101 吸合短接它；整流桥 BR101。",
    "pfc": "ICE3PCS01G 连续导通升压校正：L201 定制电感、Q201 600 V 60 mΩ、D201 碳化硅二极管、C221–C223 母线 3 × 330 µF / 500 V；"
           "R203 10 mΩ 采样（ISENSE 取负压）；外围阻容照规格书 V3.0 p.7 物料表，母线分压按 390 V 重算。主控拉 PFC_OFF 可关断校正。",
    "aux": "TOP266KG 反激：母线 → 24 V（电磁铁、步进）、15 V（功率模块、校正、继电器）、5 V；AMS1117 再出 3.3 V。"
           "整块板共地，三路输出不隔离；TL431 + 光耦按 24 V / 15 V 加权稳压。钳位 R303/C303 要变压器漏感才能算，按样机调。",
    "servo": "STGIPS14K60T 三相智能功率模块：PWM 经 100 Ω / 1 nF 进模块，SD 上拉 3.3 V，模块内热敏电阻经 1 kΩ 上拉进 ADC；"
             "三相下桥 25 mΩ 采样经偏置网络（1 k / 15 k）进主控片内运放（放大 8 倍，零点 1.65 V）；母线电压 3 MΩ / 22 kΩ 分压。",
    "act": "电磁铁 4 路（剪线、拨线、倒缝、抬压脚）：80 V 管低边开关，关断经 ES3D + SMBJ24A 钳位；栅极由 2N7002 反相从 15 V 驱动，"
           "主控复位时不吸合。针距步进 TMC2226 独立模式（STEP/DIR），采样 0.12 Ω。",
    "io": "STM32G431（沿用关节驱动板的最小系统）。编码器 A/B/Z 与霍尔 U/V/W 上拉 5 V、RC 滤波后经 SN74LVC14A 整形；脚踏板霍尔分压进 ADC；"
          "VB_OK 分压给主控看。",
    "comm": "面板口：USART2 发送反相 → ADuM1201 → 隔离侧 MAX3485（3.3 V，由 B0505S 隔离 5 V 再经 AMS1117 降压）；"
            "发送信号同时控制 DE、/RE，DI 接地。J601 是人能碰到的唯一接口。",
    "thermal": "散热器（型号 159d2 定）：整流桥、升压管、升压二极管、功率模块共用一块，热阻 ≤ 1.05 K/W（计算书）。本页没有电气器件。",
}


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
