# -*- coding: utf-8 -*-
"""功能块库（第 104 轮 P2）：每种功能块 = 端口与参数 + 计算器 + 生成器 + 仿真标准题。

设计描述里，一个功能块（= 原理图一页）下面有若干“单元”（units），每个单元一种类型、一组参数；电路由
circuit.generate 列出的生成器按顺序展开。计算器、生成器都是纯函数：不联网、不调 AI。"""

from __future__ import annotations

from . import common, control, drive, mains, power, servo

CALCULATORS = {
    "bus_input": power.calc_bus_input,
    "aux_supply": power.calc_aux_supply,
    "half_bridge": drive.calc_half_bridge,
    "gate_drive": drive.calc_gate_drive,
    "current_sense": drive.calc_current_sense,
    "mcu_core": control.calc_mcu_core,
    "encoder": control.calc_encoder,
    "ssi_rs485": control.calc_ssi_rs485,
    "can": control.calc_can,
    # 第 159 轮：平缝机控制器 CTRL-LS（交流输入、校正、逆变、执行器）
    "ac_input": mains.calc_ac_input,
    "bridge": mains.calc_bridge,
    "pfc_boost": mains.calc_pfc_boost,
    "flyback_aux": mains.calc_flyback_aux,
    "ipm_inverter": servo.calc_ipm_inverter,
    "low_side_sense": servo.calc_low_side_sense,
    "solenoid_drive": servo.calc_solenoid_drive,
    "stepper": servo.calc_stepper,
    "panel_iso": servo.calc_panel_iso,
    "heatsink": mains.calc_heatsink,
}
NAMES = {
    "bus_input": ("母线输入与电压检测", "DC bus input and voltage sensing"),
    "aux_supply": ("辅助电源", "Auxiliary supplies"),
    "half_bridge": ("三相半桥", "Three-phase half bridge"),
    "gate_drive": ("栅极驱动与自举", "Gate drive and bootstrap"),
    "current_sense": ("相电流采样", "Phase current sensing"),
    "mcu_core": ("MCU 最小系统与烧录口", "MCU core and programming port"),
    "encoder": ("编码器接口", "Encoder interface"),
    "ssi_rs485": ("绝对值编码器 SSI（RS-485）", "SSI encoder (RS-485)"),
    "can": ("CAN 总线", "CAN bus"),
    "ac_input": ("交流输入、电磁兼容与浪涌", "AC input, EMI and inrush"),
    "bridge": ("整流桥", "Bridge rectifier"),
    "pfc_boost": ("功率因数校正（连续导通升压）", "PFC boost (CCM)"),
    "flyback_aux": ("反激辅助电源", "Flyback auxiliary supply"),
    "ipm_inverter": ("智能功率模块逆变", "IPM inverter"),
    "low_side_sense": ("下桥电流采样与片内运放", "Low-side current sensing"),
    "solenoid_drive": ("电磁铁驱动", "Solenoid drivers"),
    "stepper": ("针距步进驱动", "Stitch-length stepper driver"),
    "panel_iso": ("面板口隔离", "Isolated panel port"),
    "heatsink": ("散热器", "Heatsink"),
}
# 单个单元的生成器；phase_legs 一次用三个单元（半桥、驱动、采样）
GENERATORS = {
    "bus_input": power.gen_bus_input,
    "aux_supply": power.gen_aux_supply,
    "mcu_core": control.gen_mcu_core,
    "encoder": control.gen_encoder,
    "ssi_rs485": control.gen_ssi_rs485,
    "can": control.gen_can,
}
MULTI = {"phase_legs": (drive.gen_phase_legs, ("half_bridge", "gate_drive", "current_sense"))}
SIM = {"current_sense": "sense", "gate_drive": "gate", "bus_input": "bus", "encoder": "encoder"}


class BlockError(ValueError):
    pass


def units(doc):
    """[(块 key, 单元)]：单元带上所属块的 key，生成器和计算器都按块 key 标器件所在的原理图页"""
    out = []
    for b in doc["blocks"]:
        for u in b.get("units") or []:
            if u.get("type") not in CALCULATORS:
                raise BlockError("功能块 {} 里有不认识的单元类型 {}".format(b["key"], u.get("type")))
            out.append({"key": b["key"], "type": u["type"], "params": u.get("params") or {}})
    return out


def by_type(doc):
    out = {}
    for u in units(doc):
        if u["type"] in out:
            raise BlockError("单元类型 {} 出现两次（本版每种只允许一个）".format(u["type"]))
        out[u["type"]] = u
    return out


def generate(doc, d=None):
    """按 circuit.generate 的顺序展开电路，返回器件清单"""
    spec = doc["spec"]
    bt = by_type(doc)
    out = []
    for g in doc["circuit"].get("generate") or []:
        if g in GENERATORS:
            if g not in bt:
                raise BlockError("要展开 {}，但功能块里没有这种单元".format(g))
            out += GENERATORS[g](bt[g], spec, d or {})
        elif g in MULTI:
            fn, need = MULTI[g]
            miss = [t for t in need if t not in bt]
            if miss:
                raise BlockError("要展开 {}，缺单元 {}".format(g, "、".join(miss)))
            out += fn({t: bt[t] for t in need}, spec, d or {})
        else:
            raise BlockError("不认识的生成器 {}".format(g))
    return out


def exported_params(doc):
    """大写名字的单元参数（RS_MOHM、GAIN……）原样交给生成程序用（第 102 轮起的名字）"""
    out = {}
    for u in units(doc):
        out.update({k: v for k, v in u["params"].items() if k.isupper()})
    return out


def calculate(doc, devices, parts):
    """每个单元跑计算器 → [{块、单元类型、名称、items、checks}]"""
    d = {"derating": doc["spec"]["derating"], "devices": devices}
    out = []
    for u in units(doc):
        items, checks = CALCULATORS[u["type"]](u, doc["spec"], d, parts)
        out.append(
            {
                "block": u["key"],
                "type": u["type"],
                "name": NAMES[u["type"]][0],
                "name_en": NAMES[u["type"]][1],
                "items": items,
                "checks": checks,
            }
        )
    return out


__all__ = ["common", "generate", "calculate", "units", "exported_params", "SIM", "BlockError"]
