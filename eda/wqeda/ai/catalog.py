# -*- coding: utf-8 -*-
"""起草目录（第 105 轮 P3）：AI 只能在这里面挑。由模板设计（驱动板）和下面的元数据生成，纯数据，不联网、不调 AI。

本版只有一套功能块（电机驱动板），拓扑固定（九种单元、七张页都在），AI 起草的是规格和各单元里可以改的参数。
范围、可选项是本版功能块支持的范围（生成器和器件选型能覆盖的），不是标准值。"""

from __future__ import annotations

from .. import blocks
from ..schema import design

# 规格字段：键 → (中文名, 英文名, 类型, 单位, 范围或可选项, 必须有)
SPEC = {
    "bus_voltage_v": ("母线电压", "DC bus voltage", "number", "V", [12, 60], True),
    "phase_current_a": ("额定相电流", "rated phase current", "number", "A", [0.5, 40], True),
    "phase_current_peak_a": ("峰值相电流", "peak phase current", "number", "A", [0.5, 80], True),
    "motor_power_w": ("电机功率", "motor power", "number", "W", [10, 2000], False),
    "current_source": ("电流从哪里来（说明）", "where the currents come from", "text", "", None, False),
    "target_factory": ("目标工厂", "target factory", "text", "", None, False),
    "acceptance_class": ("验收等级（IPC-A-610）", "acceptance class (IPC-A-610)", "choice", "", [1, 2, 3], False),
}

# 各单元里 AI 可以改的参数：单元类型 → {键: (中文名, 英文名, 类型, 单位, 范围或可选项)}
PARAMS = {
    "bus_input": {
        "C_BUS_UF": ("母线电容容量", "bus capacitance", "number", "µF", [47, 4700]),
        "c_bus_v": ("母线电容耐压", "bus capacitor rating", "choice", "V", [35, 50, 63, 80, 100]),
        "v_adc_target": ("额定母线时 ADC 端电压", "ADC voltage at rated bus", "number", "V", [1.0, 3.3]),
    },
    "aux_supply": {
        "c_in": ("降压输入电容", "buck input capacitor", "choice", "", ["2.2u/50V", "2.2u/100V"]),
        "d_freewheel": ("续流二极管", "freewheel diode", "choice", "", ["40V 1A", "60V 1A", "100V 1A"]),
    },
    "half_bridge": {
        "c_snub": ("半桥吸收电容", "half-bridge snubber capacitor", "choice", "", ["2.2u/50V", "2.2u/100V"]),
    },
    "gate_drive": {
        "RG_OHM": ("栅极电阻", "gate resistor", "number", "Ω", [2.2, 47]),
        "VDRV": ("栅极驱动电压", "gate drive voltage", "choice", "V", [10, 12, 15]),
        "d_boot": ("自举二极管", "bootstrap diode", "choice", "", ["60V 1A", "100V 1A"]),
    },
    "current_sense": {
        "RS_MOHM": ("采样电阻", "shunt resistor", "number", "mΩ", [0.5, 10]),
    },
    "encoder": {
        "lines": ("编码器线数", "encoder lines", "number", "", [100, 10000]),
        "rpm_max": ("最高转速", "maximum speed", "number", "r/min", [100, 20000]),
        "ENC_R_OHM": ("编码器滤波电阻", "encoder filter resistor", "number", "Ω", [100, 10000]),
        "ENC_C_PF": ("编码器滤波电容", "encoder filter capacitor", "number", "pF", [10, 2200]),
    },
}
SOURCES = ("requirement", "rule", "assumption")
SOURCE_NAMES = {"requirement": "需求原文", "rule": "规则推出", "assumption": "AI 假设", "template": "模板默认"}
INTERFACES = ["增量编码器 A/B/Z（RC 滤波）", "绝对值编码器 SSI（RS-485）", "CAN 总线", "SWD 烧录口"]


def build(template):
    """模板设计 → 目录（交给模型，也给校验用）"""
    by_type = blocks.by_type(template)
    units = []
    for t, prm in PARAMS.items():
        cur = by_type[t]["params"]
        units.append(
            {
                "type": t,
                "name": blocks.NAMES[t][0],
                "name_en": blocks.NAMES[t][1],
                "params": [
                    {
                        "key": k,
                        "name": m[0],
                        "name_en": m[1],
                        "kind": m[2],
                        "unit": m[3],
                        "allowed": m[4],
                        "default": cur.get(k),
                    }
                    for k, m in prm.items()
                ],
            }
        )
    fixed = [{"type": t, "name": blocks.NAMES[t][0]} for t in blocks.CALCULATORS if t not in PARAMS]
    spec = [
        {
            "key": k,
            "name": m[0],
            "name_en": m[1],
            "kind": m[2],
            "unit": m[3],
            "allowed": m[4],
            "required": m[5],
            "default": template["spec"].get(k),
        }
        for k, m in SPEC.items()
    ]
    devices = sorted(
        {
            str(u["params"][k])
            for u in blocks.units(template)
            for k in ("fet", "driver", "amp", "mcu", "xcvr")
            if k in u["params"]
        }
    )
    return {
        "board": "电机驱动板（三相，带电流采样）",
        "template": template["name"],
        "spec": spec,
        "units": units,
        "fixed_units": fixed,
        "interfaces": INTERFACES,
        "devices": devices,
        "sources": list(SOURCES),
    }


def load_template(path):
    return design.load_design(path)
