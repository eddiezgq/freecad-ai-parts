"""模拟规格书生成器（issue #27，ADR-0015 的替代数据路线）。

用 ingest/synthetic_catalog.py 中的虚构组件生成 PDF 规格书，并给出逐项答案，供 PDF 抽取（#28）、
LLM 结构化抽取（#29）和准确率评估（#31）使用。

每份规格书由（组件，变体号）唯一确定，生成结果可复现：
- 语言：英文或中文，两种语言在每个品类中交替出现
- 单位：每份规格书为每类量随机选一种写法（kgf·cm、×10⁻⁴ kg·m²、r/min、A(0-p) 等），
  全部是 ingest/units.py 能换算回标准单位的写法
- 叫法：参数名、枚举值各有几种同义写法
- 版式：三列（项目 / 数值 / 单位）或两列（单位写在项目名里）

答案（answer key）是一个 JSON 对象：
- component：完整组件（标准单位，符合 component.schema.json），id 以 test. 开头
- fields：规格书上印出的每一行，含页码、印出的文字、单位，以及换算到标准单位后的期望值
- implicit：组件中有、但规格书上没有直接印出的字段路径（由品类或其他字段推出，评估时不计）

规格书上印有“虚构产品”声明；这些数据永不进入正式库。
生成 PDF 需要 reportlab（开发依赖）；只用答案不需要。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import zlib
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from xml.sax.saxutils import escape

from ingest.synthetic_catalog import CATALOG, VENDORS
from ingest.units import standard_unit, to_standard

TEST_DOC = "src-test-fixture"  # 与 kb.sources.TEST_DOC 一致：测试专用来源，正式库拒收
ANSWER_FORMAT = "synthetic-answer/1"
SPEC, IFACE = "spec", "interface"

# ---------------------------------------------------------------- 字段定义


@dataclass(frozen=True)
class Field:
    key: str  # 目录中的键
    paths: tuple[str, ...]  # 在组件中的位置，如 params/rated_torque_nm、ports/shaft/diameter_mm
    en: tuple[str, ...]  # 英文叫法
    zh: tuple[str, ...]  # 中文叫法
    section: str = SPEC
    vocab: str | None = None  # 枚举值的同义写法表
    units: tuple[str, ...] | None = None  # 覆盖该类量的默认单位写法
    condition_key: str | None = None  # 目录中对应工况文字的键

    @property
    def unit_field(self) -> str:
        """用于判断标准单位的字段名（路径最后一段）。"""
        return self.paths[0].rsplit("/", 1)[-1]


def F(key, paths, en, zh, **kw) -> Field:  # 字段表写得紧凑一些
    if isinstance(paths, str):
        paths = (paths,)
    if isinstance(en, str):
        en = (en,)
    if isinstance(zh, str):
        zh = (zh,)
    return Field(key, tuple(paths), tuple(en), tuple(zh), **kw)


PEAK_A = ("A", "Arms", "A(0-p)")

FIELDS: dict[str, list[Field]] = {
    "servo_motor": [
        F("rated_power_w", "params/rated_power_w", ("Rated output", "Rated power"), ("额定功率", "额定输出")),
        F("rated_torque_nm", "params/rated_torque_nm", ("Rated torque", "Continuous rated torque"),
          ("额定转矩", "额定扭矩")),
        F("peak_torque_nm", "params/peak_torque_nm", ("Peak torque", "Instantaneous max. torque"),
          ("瞬时最大转矩", "峰值扭矩")),
        F("rated_speed_rpm", "params/rated_speed_rpm", "Rated speed", "额定转速"),
        F("max_speed_rpm", "params/max_speed_rpm", ("Max. speed", "Maximum speed"), ("最高转速", "最大转速")),
        F("rotor_inertia_kgm2", "params/rotor_inertia_kgm2", ("Rotor moment of inertia", "Rotor inertia"),
          ("转子转动惯量", "转子惯量")),
        F("torque_constant_nm_per_a", "params/torque_constant_nm_per_a", "Torque constant", "转矩常数"),
        F("rated_current_a", "ports/power_in/rated_current_a", "Rated current", "额定电流"),
        F("peak_current_a", "ports/power_in/peak_current_a", ("Peak current", "Max. current"),
          ("瞬时最大电流", "峰值电流"), units=PEAK_A),
        F("voltage_class_v", "ports/power_in/voltage_class_v", ("Voltage class", "Supply voltage class"),
          "电压等级"),
        F("mass_kg", "params/mass_kg", ("Mass", "Weight"), ("质量", "重量")),
        F("encoder_protocol", "ports/encoder/protocol", ("Encoder interface", "Encoder protocol"),
          ("编码器接口", "编码器协议"), vocab="encoder_protocol"),
        F("encoder_kind", "ports/encoder/kind", "Encoder type", "编码器类型", vocab="encoder_kind"),
        F("resolution_bits", "ports/encoder/resolution_bits", "Encoder resolution (bits)",
          "编码器分辨率（位）"),
        F("ip_rating", "params/ip_rating", ("Protection class", "Enclosure rating"), "防护等级"),
        F("brake", "params/brake", ("Holding brake", "Brake"), ("保持制动器", "制动器"), vocab="brake"),
        F("shaft_diameter_mm", ("ports/shaft/diameter_mm", "envelope/1/diameter_mm"), "Shaft diameter",
          ("轴径", "输出轴直径"), section=IFACE),
        F("shaft_fit", "ports/shaft/fit", "Shaft tolerance", "轴公差", section=IFACE),
        F("shaft_feature", "ports/shaft/feature", "Shaft end", "轴端形式", section=IFACE,
          vocab="shaft_feature"),
        F("shaft_key_width_mm", "ports/shaft/key_width_mm", "Key width", "键宽", section=IFACE),
        F("shaft_usable_length_mm", ("ports/shaft/usable_length_mm", "envelope/1/length_mm"),
          ("Shaft length", "Usable shaft length"), "轴伸长度", section=IFACE),
        F("flange_pcd_mm", "ports/mount_flange/pcd_mm", ("Mounting hole PCD", "Bolt circle diameter"),
          ("安装孔分布圆直径", "安装孔节圆直径"), section=IFACE),
        F("flange_hole_count", "ports/mount_flange/hole_count", "Number of mounting holes", "安装孔数量",
          section=IFACE),
        F("flange_hole_kind", "ports/mount_flange/hole_kind", "Mounting hole type", "安装孔类型",
          section=IFACE, vocab="hole_kind"),
        F("flange_hole_diameter_mm", "ports/mount_flange/hole_diameter_mm", "Mounting hole diameter",
          "安装孔直径", section=IFACE),
        F("flange_thread", "ports/mount_flange/thread", "Mounting thread", "安装螺纹", section=IFACE),
        F("flange_pilot_diameter_mm", "ports/mount_flange/pilot_diameter_mm",
          ("Spigot diameter", "Pilot diameter"), "止口直径", section=IFACE),
        F("flange_square_mm",
          ("ports/mount_flange/square_size_mm", "envelope/0/width_mm", "envelope/0/height_mm"),
          "Flange size (square)", "法兰尺寸（方）", section=IFACE),
        F("body_length_mm", "envelope/0/length_mm", "Body length (excl. shaft)", "机身长度（不含轴）",
          section=IFACE),
    ],
    "reducer": [
        F("reducer_kind", "params/reducer_kind", "Type", "类型", vocab="reducer_kind"),
        F("ratio", "params/ratio", ("Reduction ratio", "Gear ratio"), "减速比", vocab="ratio"),
        F("rated_torque_nm", "params/rated_torque_nm", "Rated torque", ("额定扭矩", "额定转矩"),
          condition_key="rated_torque_condition"),
        F("repeated_peak_torque_nm", "params/repeated_peak_torque_nm",
          ("Allowable peak torque (start/stop)", "Max. acceleration torque"), ("启停允许峰值扭矩", "重复峰值扭矩")),
        F("momentary_max_torque_nm", "params/momentary_max_torque_nm",
          ("Allowable momentary torque", "Emergency stop torque"), ("瞬间允许最大扭矩", "瞬时最大扭矩")),
        F("max_input_speed_rpm", "params/max_input_speed_rpm", "Max. input speed", "最高输入转速"),
        F("avg_input_speed_limit_rpm", "params/avg_input_speed_limit_rpm", "Allowable average input speed",
          "平均输入转速限制"),
        F("efficiency_ratio", "params/efficiency_ratio", "Efficiency", "效率", condition_key="efficiency_condition"),
        F("lost_motion_arcmin", "params/lost_motion_arcmin", "Lost motion", "空程"),
        F("backlash_arcmin", "params/backlash_arcmin", "Backlash", ("背隙", "回程间隙")),
        F("torsional_stiffness_nm_per_arcmin", "params/torsional_stiffness_nm_per_arcmin",
          "Torsional stiffness", "扭转刚度"),
        F("input_inertia_kgm2", "params/input_inertia_kgm2", "Moment of inertia (input side)", "输入侧转动惯量"),
        F("mass_kg", "params/mass_kg", ("Mass", "Weight"), ("质量", "重量")),
        F("output_bearing_dynamic_load_rating_n", "params/output_bearing_dynamic_load_rating_n",
          "Output bearing dynamic load rating", "输出轴承额定动载荷"),
        F("output_bearing_moment_load_rating_nm", "params/output_bearing_moment_load_rating_nm",
          ("Output bearing moment load rating", "Max. tilting moment"), "输出轴承许用倾覆力矩"),
        F("bore_diameter_mm", "ports/input_bore/diameter_mm", "Input bore diameter", "输入孔径", section=IFACE),
        F("bore_fit", "ports/input_bore/fit", "Input bore tolerance", "输入孔公差", section=IFACE),
        F("bore_feature", "ports/input_bore/feature", "Input bore type", "输入孔形式", section=IFACE,
          vocab="bore_feature"),
        F("bore_clamping", "ports/input_bore/clamping", "Input shaft fastening", "输入轴紧固方式",
          section=IFACE, vocab="clamping"),
        F("bore_key_width_mm", "ports/input_bore/key_width_mm", "Keyway width", "键槽宽", section=IFACE),
        F("motor_pcd_mm", "ports/motor_flange/pcd_mm", "Motor flange PCD", "电机法兰分布圆直径", section=IFACE),
        F("motor_hole_count", "ports/motor_flange/hole_count", "Motor flange holes", "电机法兰孔数",
          section=IFACE),
        F("motor_thread", "ports/motor_flange/thread", "Motor flange thread", "电机法兰螺纹", section=IFACE),
        F("motor_pilot_diameter_mm", "ports/motor_flange/pilot_diameter_mm", "Motor flange spigot diameter",
          "电机法兰止口直径", section=IFACE),
        F("output_pcd_mm", "ports/output_flange/pcd_mm", "Output flange PCD", "输出法兰分布圆直径",
          section=IFACE),
        F("output_hole_count", "ports/output_flange/hole_count", "Output flange holes", "输出法兰孔数",
          section=IFACE),
        F("output_thread", "ports/output_flange/thread", "Output flange thread", "输出法兰螺纹", section=IFACE),
        F("housing_pcd_mm", "ports/housing_mount/pcd_mm", "Housing mounting PCD", "壳体安装孔分布圆直径",
          section=IFACE),
        F("housing_hole_count", "ports/housing_mount/hole_count", "Housing mounting holes", "壳体安装孔数",
          section=IFACE),
        F("housing_hole_diameter_mm", "ports/housing_mount/hole_diameter_mm", "Housing mounting hole diameter",
          "壳体安装孔直径", section=IFACE),
        F("outer_diameter_mm", "envelope/0/diameter_mm", "Outer diameter", "外径", section=IFACE),
        F("square_mm", ("envelope/0/width_mm", "envelope/0/height_mm"), "Housing size (square)", "壳体尺寸（方）",
          section=IFACE),
        F("length_mm", "envelope/0/length_mm", "Overall length", "总长", section=IFACE),
    ],
    "drive": [
        F("rated_output_power_w", "params/rated_output_power_w", ("Rated output power", "Applicable motor power"),
          ("额定输出功率", "适配电机功率")),
        F("mass_kg", "params/mass_kg", ("Mass", "Weight"), ("质量", "重量")),
        F("safety_functions", "params/safety_functions", "Safety functions", "安全功能"),
        F("supply_current_type", "ports/power_in/current_type", "Power supply", "电源类型", vocab="current_type"),
        F("supply_voltage_v", "ports/power_in/voltage_v", "Input voltage", "输入电压"),
        F("supply_phases", "ports/power_in/phases", "Input phases", "输入相数", vocab="phases"),
        F("supply_frequency_hz", "ports/power_in/frequency_hz", "Input frequency", "输入频率"),
        F("supply_rated_current_a", "ports/power_in/rated_current_a", "Rated input current", "额定输入电流"),
        F("out_voltage_class_v", "ports/motor_out/voltage_class_v", "Motor voltage class", "适配电机电压等级"),
        F("out_rated_current_a", "ports/motor_out/rated_current_a",
          ("Rated output current", "Continuous output current"), "额定输出电流"),
        F("out_peak_current_a", "ports/motor_out/peak_current_a", ("Max. output current", "Peak output current"),
          ("最大输出电流", "峰值输出电流"), units=PEAK_A),
        F("encoder_protocols", "ports/encoder_in/protocol", "Supported encoders", "支持的编码器",
          vocab="encoder_protocol"),
        F("bus_protocol", "ports/bus/protocol", ("Fieldbus", "Communication"), ("通信总线", "总线"), vocab="bus"),
        F("bus_profile", "ports/bus/profile", "Device profile", "设备行规", vocab="profile"),
        F("mount_pitch_x_mm", "ports/mount/pitch_x_mm", "Mounting hole pitch (horizontal)", "安装孔水平间距",
          section=IFACE),
        F("mount_pitch_y_mm", "ports/mount/pitch_y_mm", "Mounting hole pitch (vertical)", "安装孔垂直间距",
          section=IFACE),
        F("mount_hole_count", "ports/mount/hole_count", "Number of mounting holes", "安装孔数量", section=IFACE),
        F("mount_hole_diameter_mm", "ports/mount/hole_diameter_mm", "Mounting hole diameter", "安装孔直径",
          section=IFACE),
        F("width_mm", "envelope/0/width_mm", "Width", "宽度", section=IFACE),
        F("height_mm", "envelope/0/height_mm", "Height", "高度", section=IFACE),
        F("depth_mm", "envelope/0/length_mm", "Depth", "深度", section=IFACE),
    ],
    "bearing": [
        F("bearing_kind", "params/bearing_kind", "Bearing type", "轴承类型", vocab="bearing_kind"),
        F("bore_mm", "ports/inner/diameter_mm", "Bore diameter d", "内径 d"),
        F("outer_diameter_mm", ("ports/outer/diameter_mm", "envelope/0/diameter_mm"), "Outside diameter D",
          "外径 D"),
        F("width_mm", ("params/width_mm", "envelope/0/length_mm"), "Width B", "宽度 B"),
        F("dynamic_load_rating_n", "params/dynamic_load_rating_n",
          ("Basic dynamic load rating Cr", "Dynamic load rating"), ("基本额定动载荷 Cr", "额定动载荷")),
        F("static_load_rating_n", "params/static_load_rating_n", "Basic static load rating C0r",
          "基本额定静载荷 C0r"),
        F("limiting_speed_rpm", "params/limiting_speed_rpm", "Limiting speed", "极限转速"),
        F("moment_load_rating_nm", "params/moment_load_rating_nm", "Allowable moment load", "许用倾覆力矩"),
        F("seal", "params/seal", "Seal / shield", "密封形式"),
        F("mass_kg", "params/mass_kg", ("Mass", "Weight"), ("质量", "重量")),
        F("precision", ("ports/inner/fit", "ports/outer/fit"), ("Precision class", "Tolerance class"), "精度等级",
          vocab="precision"),
    ],
}

# 每类量的单位写法；第一个为标准写法。全部须能被 ingest.units 换算。
UNIT_OPTIONS: dict[str, tuple[str, ...]] = {
    "_nm_per_arcmin": ("N·m/arcmin", "kN·m/rad"),
    "_nm_per_a": ("N·m/A", "Nm/A"),
    "_kgm2": ("kg·m²", "×10⁻⁴ kg·m²", "kg·cm²"),
    "_arcmin": ("arcmin", "'", "arcsec"),
    "_ratio": ("", "%"),
    "_rpm": ("rpm", "r/min", "min⁻¹"),
    "_hz": ("Hz",),
    "_mm": ("mm",),
    "_nm": ("N·m", "Nm", "kgf·cm"),
    "_kg": ("kg", "g"),
    "_w": ("W", "kW"),
    "_v": ("V",),
    "_a": ("A", "Arms"),
    "_n": ("N", "kN", "kgf"),
}

# 枚举值的同义写法：canonical → {语言: 写法}
VOCAB: dict[str, dict] = {
    "encoder_protocol": {
        "biss_c": {"en": ("BiSS-C", "BiSS C"), "zh": ("BiSS-C", "BiSS C")},
        "endat_2_2": {"en": ("EnDat 2.2",), "zh": ("EnDat 2.2",)},
        "ssi": {"en": ("SSI",), "zh": ("SSI",)},
        "incremental_abz": {"en": ("Incremental ABZ", "A/B/Z incremental"), "zh": ("增量式 ABZ", "ABZ 增量")},
    },
    "encoder_kind": {
        "absolute": {"en": ("Absolute",), "zh": ("绝对式", "绝对值")},
        "incremental": {"en": ("Incremental",), "zh": ("增量式",)},
    },
    "brake": {
        True: {"en": ("Yes", "Included"), "zh": ("有", "带")},
        False: {"en": ("No", "None"), "zh": ("无", "不带")},
    },
    "shaft_feature": {
        "plain": {"en": ("Plain", "Smooth"), "zh": ("光轴",)},
        "keyed": {"en": ("Keyed", "With key"), "zh": ("带键", "有键槽")},
        "d_cut": {"en": ("D-cut", "Flat"), "zh": ("D 形切边", "D 形轴")},
    },
    "bore_feature": {
        "plain": {"en": ("Plain bore",), "zh": ("光孔",)},
        "keyed": {"en": ("With keyway", "Keyway"), "zh": ("带键槽",)},
        "d_cut": {"en": ("D-bore",), "zh": ("D 形孔",)},
    },
    "clamping": {
        "key": {"en": ("Key",), "zh": ("平键",)},
        "clamp_ring": {"en": ("Clamping ring", "Clamp collar"), "zh": ("锁紧环", "抱紧环")},
        "set_screw": {"en": ("Set screw",), "zh": ("紧定螺钉", "顶丝")},
    },
    "hole_kind": {
        "through": {"en": ("Through hole",), "zh": ("通孔",)},
        "threaded": {"en": ("Tapped", "Threaded"), "zh": ("螺纹孔",)},
    },
    "reducer_kind": {
        "harmonic": {"en": ("Strain wave gear", "Harmonic"), "zh": ("谐波减速器", "谐波")},
        "planetary": {"en": ("Planetary gearbox", "Planetary"), "zh": ("行星减速器", "行星")},
    },
    "current_type": {
        "ac": {"en": ("AC",), "zh": ("交流",)},
        "dc": {"en": ("DC",), "zh": ("直流",)},
    },
    "phases": {
        1: {"en": ("Single-phase", "1-phase"), "zh": ("单相",)},
        3: {"en": ("Three-phase", "3-phase"), "zh": ("三相",)},
    },
    "bus": {
        "ethercat": {"en": ("EtherCAT",), "zh": ("EtherCAT",)},
        "canopen": {"en": ("CANopen",), "zh": ("CANopen",)},
        "profinet": {"en": ("PROFINET",), "zh": ("PROFINET",)},
    },
    "profile": {
        "cia402": {"en": ("CiA 402", "CiA402", "DS402"), "zh": ("CiA 402", "CiA402")},
    },
    "bearing_kind": {
        "deep_groove": {"en": ("Deep groove ball bearing",), "zh": ("深沟球轴承",)},
        "angular_contact": {"en": ("Angular contact ball bearing",), "zh": ("角接触球轴承",)},
        "cross_roller": {"en": ("Crossed roller bearing",), "zh": ("交叉滚子轴承",)},
        "tapered_roller": {"en": ("Tapered roller bearing",), "zh": ("圆锥滚子轴承",)},
    },
    "precision": {
        "P0": {"en": ("P0", "Normal (P0)"), "zh": ("P0", "P0 级", "普通级（P0）")},
        "P6": {"en": ("P6", "Class 6 (P6)"), "zh": ("P6", "P6 级")},
        "P5": {"en": ("P5", "Class 5 (P5)"), "zh": ("P5", "P5 级")},
    },
}

TITLES = {
    "servo_motor": {"en": "AC Servo Motor", "zh": "交流伺服电机"},
    "reducer": {"en": "Precision Gear Reducer", "zh": "精密减速器"},
    "drive": {"en": "Servo Drive", "zh": "伺服驱动器"},
    "bearing": {"en": "Rolling Bearing", "zh": "滚动轴承"},
}
SECTION_TITLES = {
    SPEC: {"en": ("Specifications", "Ratings and specifications"), "zh": ("规格参数", "额定值与规格")},
    IFACE: {"en": ("Mechanical interface and dimensions",), "zh": ("机械接口与尺寸",)},
}
HEADERS = {
    "en": (("Item", "Value", "Unit"), ("Parameter", "Value", "Unit")),
    "zh": (("项目", "数值", "单位"), ("参数", "数值", "单位")),
}
DISCLAIMER = {
    "en": "Fictional product for software testing only. Not a real product; values are invented.",
    "zh": "虚构产品，仅用于软件测试，并非真实产品，数值均为虚构。",
}
COMPONENT_NOTE = "模拟规格书用虚构组件（ADR-0015），数值不代表任何真实产品"

# ---------------------------------------------------------------- 组件构建（答案）


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def component_id(category: str, model: str) -> str:
    return f"test.{category}.{_slug(VENDORS[category])}.{_slug(model).replace('-', '')}"


def _pv(raw, page: int, condition: str | None = None) -> dict:
    pv: dict = {"min": raw["min"], "max": raw["max"]} if isinstance(raw, dict) else {"value": raw}
    if condition:
        pv["condition"] = condition
    pv.update({"source": {"doc": TEST_DOC, "page": page}, "method": "manual", "confidence": 1, "reviewed": True})
    return pv


def _frame(z: float) -> dict:
    return {"origin_mm": [0, 0, z], "axis": [0, 0, 1]}


def _skeleton(category: str, row: dict) -> tuple[list[dict], list[dict]]:
    """返回（端口列表，包络各部分）；spec 与尺寸由字段填入。frame、z_start 是隐含布置，不在规格书上。"""
    def port(pid, ptype, pdir, motion=None, z=None):
        p = {"id": pid, "type": ptype, "dir": pdir}
        if motion:
            p["motion"] = motion
            p["frame"] = _frame(z or 0)
        p["spec"] = {}
        return p

    if category == "servo_motor":
        ports = [
            port("shaft", "mechanical.cyl_male", "out", "rotating", row["shaft_usable_length_mm"]),
            port("mount_flange", "mechanical.flange", "bidir", "stationary", 0),
            port("power_in", "electrical.motor_power", "in"),
            port("encoder", "signal.encoder", "out"),
        ]
        env = [
            {"shape": "box", "z_start_mm": -row["body_length_mm"], "label": "body"},
            {"shape": "cylinder", "z_start_mm": 0, "label": "shaft"},
        ]
    elif category == "reducer":
        length = row["length_mm"]
        ports = [
            port("input_bore", "mechanical.cyl_female", "in", "rotating", 0),
            port("motor_flange", "mechanical.flange", "bidir", "stationary", 0),
            port("output_flange", "mechanical.flange", "out", "rotating", length),
            port("housing_mount", "mechanical.flange", "bidir", "stationary", length),
        ]
        env = [{"shape": "box" if "square_mm" in row else "cylinder", "z_start_mm": 0, "label": "body"}]
    elif category == "drive":
        ports = [
            port("power_in", "electrical.power_supply", "in"),
            port("motor_out", "electrical.motor_power", "out"),
            port("encoder_in", "signal.encoder", "in"),
            port("bus", "signal.fieldbus", "bidir"),
            port("mount", "mechanical.mount_face", "bidir", "stationary", 0),
        ]
        env = [{"shape": "box", "z_start_mm": 0, "label": "body"}]
    elif category == "bearing":
        ports = [
            port("inner", "mechanical.cyl_female", "bidir", "rotating", 0),
            port("outer", "mechanical.cyl_male", "bidir", "stationary", 0),
        ]
        env = [{"shape": "cylinder", "z_start_mm": 0, "label": "body"}]
    else:
        raise ValueError(f"不支持的品类 {category}")
    return ports, env


def _implicit(category: str, row: dict) -> dict[str, tuple[object, str]]:
    """规格书上不直接印出、由品类或其他字段推出的值：路径 → (值, 推导依据)。"""
    out: dict[str, tuple[object, str]] = {}
    if category == "reducer":
        out["ports/motor_flange/hole_kind"] = ("threaded", "印有螺纹规格，故为螺纹孔")
        out["ports/output_flange/hole_kind"] = ("threaded", "印有螺纹规格，故为螺纹孔")
        out["ports/housing_mount/hole_kind"] = ("through", "印有孔径，故为通孔")
    elif category == "drive":
        out["ports/mount/pattern"] = ("rect", "安装孔按水平、垂直间距排列")
        if row["supply_current_type"] == "dc":
            out["ports/power_in/phases"] = (0, "直流供电，相数按约定记 0")
        kinds = sorted({"incremental" if p == "incremental_abz" else "absolute" for p in row["encoder_protocols"]})
        out["ports/encoder_in/kind"] = (kinds, "由支持的编码器协议推出")
    elif category == "bearing":
        out["ports/inner/fit_system"] = ("bearing", "滚动轴承内圈按 ISO 492 精度等级")
        out["ports/inner/feature"] = ("plain", "轴承内圈为光孔")
        out["ports/inner/clamping"] = ("press_fit", "轴承内圈按过盈配合安装")
        out["ports/outer/fit_system"] = ("bearing", "滚动轴承外圈按 ISO 492 精度等级")
        out["ports/outer/feature"] = ("plain", "轴承外圈为光面")
    return out


def _derived_pv(value, why: str) -> dict:
    """隐含字段：不是从规格书读出的，按推导值记录（method=computed，来源写推导依据）。"""
    return {"value": value, "source": {"formula": why}, "method": "computed", "confidence": 1, "reviewed": True}


def _set(comp: dict, path: str, pv: dict) -> None:
    head, *rest = path.split("/")
    if head == "params":
        comp["params"][rest[0]] = pv
    elif head == "ports":
        port = next(p for p in comp["ports"] if p["id"] == rest[0])
        port["spec"][rest[1]] = pv
    elif head == "envelope":
        comp["envelope"]["parts"][int(rest[0])][rest[1]] = pv
    else:
        raise ValueError(f"无法识别的路径 {path}")


# ---------------------------------------------------------------- 渲染计划


def _fmt(x: float) -> str:
    """4 位有效数字，不用科学计数法。"""
    if x == 0:
        return "0"
    s = format(Decimal(f"{x:.4g}"), "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def _seed(*parts) -> int:
    return zlib.crc32(":".join(map(str, parts)).encode("utf-8"))


def _render_value(field: Field, raw, unit: str, lang: str, rng: random.Random) -> str:
    if field.vocab == "ratio":
        pattern = rng.choice(("{v}", "1:{v}", "i = {v}") if lang == "en" else ("{v}", "1:{v}"))
        return pattern.format(v=_fmt(raw))
    if isinstance(raw, list):
        sep = rng.choice((", ", " / "))
        return sep.join(_render_value(field, item, unit, lang, rng) for item in raw)
    if field.vocab:
        return rng.choice(VOCAB[field.vocab][raw][lang])
    if isinstance(raw, dict):
        sep = rng.choice(("–", " ~ "))
        return sep.join(_render_value(field, raw[k], unit, lang, rng) for k in ("min", "max"))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        if field.units is None and not _has_unit_suffix(field):
            return str(raw)
        return _fmt(raw / to_standard(1, unit, field.unit_field))
    return str(raw)


def _has_unit_suffix(field: Field) -> bool:
    try:
        standard_unit(field.unit_field)
    except ValueError:
        return False
    return True


def _expected(raw) -> dict:
    if isinstance(raw, dict):
        return {"min": raw["min"], "max": raw["max"]}
    return {"value": raw}


@dataclass
class Datasheet:
    id: str
    answer: dict

    def render(self, path: Path) -> Path:
        """把规格书写成 PDF，返回路径。"""
        return render_pdf(self.answer, Path(path))


def build_datasheet(category: str, row: dict, variant: int = 0) -> Datasheet:
    """由目录中的一行生成一份规格书的答案（含渲染所需的全部文字）。"""
    cid = component_id(category, row["model"])
    rng = random.Random(_seed(cid, variant))
    lang = ("en", "zh")[(_seed(cid, "lang") + variant) % 2]  # 只由组件与变体号决定，与目录顺序无关
    layout = rng.choice(("three_col", "two_col"))
    sections = [s for s in (SPEC, IFACE) if any(f.section == s and f.key in row for f in FIELDS[category])]
    pages = {s: i + 1 for i, s in enumerate(sections)}
    unit_choice: dict[str, str] = {}

    comp: dict = {
        "id": cid, "category": category, "vendor": VENDORS[category], "model": row["model"],
        "status": "active", "license": "params-only", "params": {},
    }
    comp["ports"], parts = _skeleton(category, row)
    comp["envelope"] = {"parts": parts}

    fields_out = []
    for field in FIELDS[category]:
        if field.key not in row:
            continue
        raw = row[field.key]
        unit = ""
        if field.vocab is None and not isinstance(raw, (str, bool, list)) and _has_unit_suffix(field):
            suffix, _ = standard_unit(field.unit_field)
            if field.units is not None:
                unit = rng.choice(field.units)
            elif suffix == "_a" and row.get("supply_current_type") == "dc" and "power_in" in field.paths[0]:
                unit = "A"  # 直流电流不写 Arms
            else:
                unit = unit_choice.setdefault(suffix, rng.choice(UNIT_OPTIONS[suffix]))
        condition = row[field.condition_key][lang] if field.condition_key else None
        page = pages[field.section]
        for path in field.paths:
            _set(comp, path, _pv(raw, page, condition))
        name = rng.choice(field.en if lang == "en" else field.zh)
        entry = {
            "key": field.key, "paths": list(field.paths), "page": page, "section": field.section,
            "name": name, "unit": unit, "text": _render_value(field, raw, unit, lang, rng),
            "expected": _expected(raw),
        }
        if condition:
            entry["condition"] = condition
        fields_out.append(entry)

    implicit = _implicit(category, row)
    for path, (value, why) in implicit.items():
        _set(comp, path, _derived_pv(value, why))
    comp["note"] = COMPONENT_NOTE
    # 端口 spec 按 schema 中字段顺序无要求；排序让答案稳定
    for p in comp["ports"]:
        p["spec"] = dict(sorted(p["spec"].items()))

    rng.shuffle(fields_out)  # 先打乱再按页分组：同一节内顺序随变体变化
    fields_out.sort(key=lambda e: e["page"])
    answer = {
        "format": ANSWER_FORMAT,
        "datasheet_id": f"{cid}.v{variant}",
        "component_id": cid,
        "category": category,
        "variant": variant,
        "lang": lang,
        "layout": layout,
        "title": f"{VENDORS[category]} {row['model']} {TITLES[category][lang]}",
        "headers": list(rng.choice(HEADERS[lang])),
        "sections": [{"page": pages[s], "title": rng.choice(SECTION_TITLES[s][lang])} for s in sections],
        "disclaimer": DISCLAIMER[lang],
        "fields": fields_out,
        "implicit": sorted(implicit),
        "component": comp,
    }
    return Datasheet(answer["datasheet_id"], answer)


def datasheets(variant: int = 0, categories: list[str] | None = None) -> list[Datasheet]:
    """目录中全部组件的规格书（同一变体号）。"""
    out = []
    for category, rows in CATALOG.items():
        if categories and category not in categories:
            continue
        out += [build_datasheet(category, row, variant) for row in rows]
    return out


def row_label(entry: dict, lang: str, layout: str) -> str:
    """表格第一列的文字：叫法，加上工况；两列版式时再加单位。"""
    label = entry["name"]
    if entry.get("condition"):
        label += f" ({entry['condition']})" if lang == "en" else f"（{entry['condition']}）"
    if layout == "two_col" and entry["unit"]:
        label += f" [{entry['unit']}]" if lang == "en" else f"（{entry['unit']}）"
    return label


# ---------------------------------------------------------------- PDF 渲染

# 拉丁字母与单位符号（·²⁻ 等）用 DejaVu Sans；中文用文泉驿正黑。两者都是可嵌入的 TrueType 字体，
# 生成的 PDF 自带字形，在任何阅读器里都能显示，抽取时也不丢字。
_FONTS = {
    "latin": ("FAP_LATIN_FONT", "fonts-dejavu-core", (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    )),
    "cjk": ("FAP_CJK_FONT", "fonts-wqy-zenhei", (
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/wenquanyi/wqy-zenhei/wqy-zenhei.ttc",
        "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
    )),
}
_CJK = re.compile("[\u3000-\u303f\u3400-\u9fff\uff00-\uffef]+")


class FontMissing(RuntimeError):
    """找不到生成 PDF 所需的字体。"""


def find_font(kind: str) -> str:
    """字体路径（kind 为 latin 或 cjk）：优先环境变量 FAP_LATIN_FONT / FAP_CJK_FONT。"""
    env_name, package, candidates = _FONTS[kind]
    env = os.environ.get(env_name)
    for path in ((env,) if env else ()) + candidates:
        if path and Path(path).is_file():
            return path
    raise FontMissing(f"找不到 {kind} 字体；请安装 {package}，或用环境变量 {env_name} 指定路径")


@cache
def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("FapLatin", find_font("latin")))
    cjk = find_font("cjk")
    pdfmetrics.registerFont(TTFont("FapCJK", cjk, subfontIndex=0) if cjk.endswith(".ttc") else TTFont("FapCJK", cjk))
    return "FapLatin", "FapCJK"


def _markup(text: str) -> str:
    """中文用中文字体，其余（数字、单位符号、英文）用拉丁字体。"""
    _, cjk = _fonts()
    out, pos = [], 0
    for m in _CJK.finditer(text):
        if m.start() > pos:
            out.append(escape(text[pos:m.start()]))
        out.append(f'<font name="{cjk}">{escape(m.group())}</font>')
        pos = m.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def render_pdf(answer: dict, path: Path) -> Path:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    latin, _ = _fonts()
    body = ParagraphStyle("body", fontName=latin, fontSize=9, leading=12)
    title = ParagraphStyle("title", parent=body, fontSize=15, leading=20, spaceAfter=4)
    head = ParagraphStyle("head", parent=body, fontSize=11, leading=15, spaceBefore=8, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=colors.grey)

    lang, layout = answer["lang"], answer["layout"]
    h_item, h_value, h_unit = answer["headers"]
    story: list = []
    for n, section in enumerate(answer["sections"]):
        if n:
            story.append(PageBreak())
        story.append(Paragraph(_markup(answer["title"]), title))
        story.append(Paragraph(_markup(answer["disclaimer"]), small))
        story.append(Paragraph(_markup(section["title"]), head))
        if layout == "three_col":
            rows = [[h_item, h_value, h_unit]]
            widths = [250, 150, 95]
        else:
            rows = [[h_item, h_value]]
            widths = [320, 175]
        for e in answer["fields"]:
            if e["page"] != section["page"]:
                continue
            row = [row_label(e, lang, layout), e["text"]]
            if layout == "three_col":
                row.append(e["unit"] or "—")
            rows.append(row)
        cells = [[Paragraph(_markup(c), body) for c in r] for r in rows]
        table = Table(cells, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8e8e8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(Spacer(1, 4))
        story.append(table)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50,
        title=answer["title"], author="freecad-ai-parts synthetic generator", invariant=True,
    )
    doc.build(story)
    return path


# ---------------------------------------------------------------- 命令行


def write_all(out_dir: Path, variants: int = 1) -> list[Path]:
    """为每个组件、每个变体写出 <datasheet_id>.pdf 与 <datasheet_id>.answer.json。"""
    written = []
    for v in range(variants):
        for sheet in datasheets(v):
            pdf = sheet.render(out_dir / f"{sheet.id}.pdf")
            ans = out_dir / f"{sheet.id}.answer.json"
            ans.write_text(json.dumps(sheet.answer, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written += [pdf, ans]
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成模拟规格书（虚构组件）及答案")
    parser.add_argument("--out", type=Path, default=Path("data/synthetic"), help="输出目录（不入 git）")
    parser.add_argument("--variants", type=int, default=1, help="每个组件生成几种变体")
    args = parser.parse_args(argv)
    files = write_all(args.out, args.variants)
    print(f"已生成 {len(files) // 2} 份规格书 → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ANSWER_FORMAT", "FIELDS", "UNIT_OPTIONS", "VOCAB", "Datasheet", "Field", "FontMissing",
    "build_datasheet", "component_id", "datasheets", "find_font", "main", "render_pdf", "row_label",
    "write_all",
]

