"""模拟规格书用的虚构组件目录（issue #27，ADR-0015）。

全部型号与数值均为虚构，只用于开发和评估抽取流程，不代表任何真实产品，永不进入正式库。
数值一律为标准单位（实施细则第四节）。某个字段不出现，表示这份规格书上就没有这一项：
用来检验抽取时“缺数据就不写”，不是遗漏。

条件文字（condition）按语言给出，规格书用哪种语言，答案里就记哪种原文。
"""

from __future__ import annotations

COND_RATED_HARMONIC = {"en": "at input speed 2000 rpm", "zh": "输入转速 2000 r/min 时"}
COND_RATED_PLANETARY = {"en": "at input speed 3000 rpm, S1 duty", "zh": "输入转速 3000 r/min、S1 工作制"}
COND_EFF = {"en": "at rated torque, 25 °C", "zh": "额定扭矩、25 °C 时"}

SERVO_MOTORS: list[dict] = [
    {
        "model": "SM100", "rated_power_w": 100, "rated_torque_nm": 0.318, "peak_torque_nm": 0.955,
        "rated_speed_rpm": 3000, "max_speed_rpm": 6000, "rotor_inertia_kgm2": 5.1e-6,
        "torque_constant_nm_per_a": 0.30, "mass_kg": 0.45, "rated_current_a": 1.1, "peak_current_a": 3.3,
        "voltage_class_v": 200, "encoder_protocol": "biss_c", "encoder_kind": "absolute",
        "resolution_bits": 23, "ip_rating": "IP65", "brake": False,
        "shaft_diameter_mm": 8, "shaft_fit": "h6", "shaft_feature": "plain", "shaft_usable_length_mm": 25,
        "flange_pcd_mm": 46, "flange_hole_count": 4, "flange_hole_kind": "through",
        "flange_hole_diameter_mm": 4.5, "flange_pilot_diameter_mm": 30, "flange_square_mm": 40,
        "body_length_mm": 75,
    },
    {
        "model": "SM200", "rated_power_w": 200, "rated_torque_nm": 0.637, "peak_torque_nm": 1.91,
        "rated_speed_rpm": 3000, "max_speed_rpm": 6000, "rotor_inertia_kgm2": 1.4e-5,
        "torque_constant_nm_per_a": 0.36, "mass_kg": 0.82, "rated_current_a": 1.6, "peak_current_a": 5.8,
        "voltage_class_v": 200, "encoder_protocol": "biss_c", "encoder_kind": "absolute",
        "resolution_bits": 23, "ip_rating": "IP65", "brake": False,
        "shaft_diameter_mm": 11, "shaft_fit": "h6", "shaft_feature": "keyed", "shaft_key_width_mm": 4,
        "shaft_usable_length_mm": 25,
        "flange_pcd_mm": 70, "flange_hole_count": 4, "flange_hole_kind": "through",
        "flange_hole_diameter_mm": 5.5, "flange_pilot_diameter_mm": 50, "flange_square_mm": 60,
        "body_length_mm": 80,
    },
    {
        "model": "SM400B", "rated_power_w": 400, "rated_torque_nm": 1.27, "peak_torque_nm": 3.82,
        "rated_speed_rpm": 3000, "max_speed_rpm": 6000, "rotor_inertia_kgm2": 2.6e-5,
        "torque_constant_nm_per_a": 0.45, "mass_kg": 1.6, "rated_current_a": 2.8, "peak_current_a": 8.5,
        "voltage_class_v": 200, "encoder_protocol": "endat_2_2", "encoder_kind": "absolute",
        "resolution_bits": 25, "ip_rating": "IP67", "brake": True,
        "shaft_diameter_mm": 14, "shaft_fit": "h6", "shaft_feature": "keyed", "shaft_key_width_mm": 5,
        "shaft_usable_length_mm": 30,
        "flange_pcd_mm": 70, "flange_hole_count": 4, "flange_hole_kind": "through",
        "flange_hole_diameter_mm": 5.5, "flange_pilot_diameter_mm": 50, "flange_square_mm": 60,
        "body_length_mm": 140,
    },
    {
        "model": "SM750", "rated_power_w": 750, "rated_torque_nm": 2.39, "peak_torque_nm": 7.16,
        "rated_speed_rpm": 3000, "max_speed_rpm": 5000, "rotor_inertia_kgm2": 1.1e-4,
        "torque_constant_nm_per_a": 0.55, "mass_kg": 2.3, "rated_current_a": 4.4, "peak_current_a": 13.4,
        "voltage_class_v": 200, "encoder_protocol": "biss_c", "encoder_kind": "absolute",
        "resolution_bits": 23, "ip_rating": "IP65", "brake": False,
        "shaft_diameter_mm": 19, "shaft_fit": "h6", "shaft_feature": "keyed", "shaft_key_width_mm": 6,
        "shaft_usable_length_mm": 35,
        "flange_pcd_mm": 90, "flange_hole_count": 4, "flange_hole_kind": "through",
        "flange_hole_diameter_mm": 6.6, "flange_pilot_diameter_mm": 70, "flange_square_mm": 80,
        "body_length_mm": 125,
    },
    {
        # 低压机器人关节电机：无分辨率、无制动器、无防护等级行，检验缺项
        "model": "SM48-150", "rated_power_w": 150, "rated_torque_nm": 0.48, "peak_torque_nm": 1.44,
        "rated_speed_rpm": 3000, "max_speed_rpm": 4000, "rotor_inertia_kgm2": 9.0e-6,
        "torque_constant_nm_per_a": 0.08, "mass_kg": 0.6, "rated_current_a": 6.0, "peak_current_a": 18.0,
        "voltage_class_v": 48, "encoder_protocol": "incremental_abz", "encoder_kind": "incremental",
        "shaft_diameter_mm": 8, "shaft_fit": "h7", "shaft_feature": "d_cut", "shaft_usable_length_mm": 20,
        "flange_pcd_mm": 50, "flange_hole_count": 4, "flange_hole_kind": "threaded", "flange_thread": "M3",
        "flange_pilot_diameter_mm": 22, "flange_square_mm": 42, "body_length_mm": 70,
    },
]

REDUCERS: list[dict] = [
    {
        "model": "HR14-50", "reducer_kind": "harmonic", "ratio": 50,
        "rated_torque_nm": 5.4, "rated_torque_condition": COND_RATED_HARMONIC,
        "repeated_peak_torque_nm": 18, "momentary_max_torque_nm": 35,
        "max_input_speed_rpm": 8500, "avg_input_speed_limit_rpm": 3500,
        "efficiency_ratio": 0.65, "efficiency_condition": COND_EFF,
        "lost_motion_arcmin": 1.0, "torsional_stiffness_nm_per_arcmin": 1.3,
        "input_inertia_kgm2": 3.3e-6, "mass_kg": 0.36,
        "bore_diameter_mm": 6, "bore_fit": "H7", "bore_feature": "d_cut", "bore_clamping": "set_screw",
        "motor_pcd_mm": 46, "motor_hole_count": 4, "motor_thread": "M3", "motor_pilot_diameter_mm": 30,
        "output_pcd_mm": 23, "output_hole_count": 6, "output_thread": "M3",
        "housing_pcd_mm": 65, "housing_hole_count": 8, "housing_hole_diameter_mm": 3.4,
        "outer_diameter_mm": 70, "length_mm": 37,
    },
    {
        "model": "HR17-100", "reducer_kind": "harmonic", "ratio": 100,
        "rated_torque_nm": 16, "rated_torque_condition": COND_RATED_HARMONIC,
        "repeated_peak_torque_nm": 34, "momentary_max_torque_nm": 70,
        "max_input_speed_rpm": 7300, "avg_input_speed_limit_rpm": 3500,
        "efficiency_ratio": 0.68, "efficiency_condition": COND_EFF,
        "lost_motion_arcmin": 1.0, "torsional_stiffness_nm_per_arcmin": 3.0,
        "input_inertia_kgm2": 8.0e-6, "mass_kg": 0.55, "output_bearing_moment_load_rating_nm": 74,
        "bore_diameter_mm": 8, "bore_fit": "H7", "bore_feature": "keyed", "bore_clamping": "key",
        "bore_key_width_mm": 3,
        "motor_pcd_mm": 46, "motor_hole_count": 4, "motor_thread": "M4", "motor_pilot_diameter_mm": 30,
        "output_pcd_mm": 30, "output_hole_count": 8, "output_thread": "M4",
        "housing_pcd_mm": 75, "housing_hole_count": 12, "housing_hole_diameter_mm": 3.4,
        "outer_diameter_mm": 80, "length_mm": 42,
    },
    {
        "model": "HR20-120", "reducer_kind": "harmonic", "ratio": 120,
        "rated_torque_nm": 34, "rated_torque_condition": COND_RATED_HARMONIC,
        "repeated_peak_torque_nm": 64, "momentary_max_torque_nm": 113,
        "max_input_speed_rpm": 6500, "avg_input_speed_limit_rpm": 3500,
        "efficiency_ratio": 0.66, "efficiency_condition": COND_EFF,
        "lost_motion_arcmin": 1.0, "torsional_stiffness_nm_per_arcmin": 5.7,
        "input_inertia_kgm2": 1.9e-5, "mass_kg": 0.9, "output_bearing_moment_load_rating_nm": 187,
        "output_bearing_dynamic_load_rating_n": 14600,
        "bore_diameter_mm": 11, "bore_fit": "H7", "bore_feature": "keyed", "bore_clamping": "key",
        "bore_key_width_mm": 4,
        "motor_pcd_mm": 70, "motor_hole_count": 4, "motor_thread": "M5", "motor_pilot_diameter_mm": 50,
        "output_pcd_mm": 35, "output_hole_count": 8, "output_thread": "M4",
        "housing_pcd_mm": 82, "housing_hole_count": 12, "housing_hole_diameter_mm": 3.4,
        "outer_diameter_mm": 90, "length_mm": 46,
    },
    {
        "model": "PG60-10", "reducer_kind": "planetary", "ratio": 10,
        "rated_torque_nm": 20, "rated_torque_condition": COND_RATED_PLANETARY,
        "repeated_peak_torque_nm": 40, "momentary_max_torque_nm": 60,
        "max_input_speed_rpm": 6000, "avg_input_speed_limit_rpm": 3000,
        "efficiency_ratio": 0.95, "efficiency_condition": COND_EFF,
        "backlash_arcmin": 3, "torsional_stiffness_nm_per_arcmin": 3.5,
        "input_inertia_kgm2": 3.2e-5, "mass_kg": 1.1,
        "bore_diameter_mm": 14, "bore_fit": "H7", "bore_feature": "plain", "bore_clamping": "clamp_ring",
        "motor_pcd_mm": 70, "motor_hole_count": 4, "motor_thread": "M5", "motor_pilot_diameter_mm": 50,
        "output_pcd_mm": 31.5, "output_hole_count": 7, "output_thread": "M5",
        "housing_pcd_mm": 70, "housing_hole_count": 4, "housing_hole_diameter_mm": 5.5,
        "outer_diameter_mm": 62, "length_mm": 105,
    },
    {
        # 无平均输入转速、无输入惯量行，检验缺项
        "model": "PG90-5", "reducer_kind": "planetary", "ratio": 5,
        "rated_torque_nm": 50, "rated_torque_condition": COND_RATED_PLANETARY,
        "repeated_peak_torque_nm": 100, "momentary_max_torque_nm": 150,
        "max_input_speed_rpm": 5000,
        "efficiency_ratio": 0.96, "efficiency_condition": COND_EFF,
        "backlash_arcmin": 3, "torsional_stiffness_nm_per_arcmin": 10, "mass_kg": 3.0,
        "bore_diameter_mm": 19, "bore_fit": "H7", "bore_feature": "plain", "bore_clamping": "clamp_ring",
        "motor_pcd_mm": 90, "motor_hole_count": 4, "motor_thread": "M6", "motor_pilot_diameter_mm": 70,
        "output_pcd_mm": 50, "output_hole_count": 7, "output_thread": "M6",
        "housing_pcd_mm": 100, "housing_hole_count": 4, "housing_hole_diameter_mm": 6.6,
        "outer_diameter_mm": 92, "length_mm": 120,
    },
]

DRIVES: list[dict] = [
    {
        "model": "SD100", "rated_output_power_w": 100, "mass_kg": 0.6, "safety_functions": ["STO"],
        "supply_current_type": "ac", "supply_voltage_v": {"min": 200, "max": 240}, "supply_phases": 1,
        "supply_frequency_hz": {"min": 50, "max": 60}, "supply_rated_current_a": 1.2,
        "out_voltage_class_v": 200, "out_rated_current_a": 1.1, "out_peak_current_a": 3.3,
        "encoder_protocols": ["biss_c"], "bus_protocol": "ethercat", "bus_profile": "cia402",
        "mount_pitch_x_mm": 30, "mount_pitch_y_mm": 150, "mount_hole_count": 2,
        "mount_hole_diameter_mm": 5.5, "width_mm": 40, "height_mm": 160, "depth_mm": 130,
    },
    {
        "model": "SD200", "rated_output_power_w": 200, "mass_kg": 0.7, "safety_functions": ["STO"],
        "supply_current_type": "ac", "supply_voltage_v": {"min": 200, "max": 240}, "supply_phases": 1,
        "supply_frequency_hz": {"min": 50, "max": 60}, "supply_rated_current_a": 2.0,
        "out_voltage_class_v": 200, "out_rated_current_a": 1.6, "out_peak_current_a": 5.8,
        "encoder_protocols": ["biss_c", "endat_2_2"], "bus_protocol": "ethercat", "bus_profile": "cia402",
        "mount_pitch_x_mm": 30, "mount_pitch_y_mm": 150, "mount_hole_count": 2,
        "mount_hole_diameter_mm": 5.5, "width_mm": 40, "height_mm": 160, "depth_mm": 130,
    },
    {
        "model": "SD400", "rated_output_power_w": 400, "mass_kg": 0.9, "safety_functions": ["STO", "SS1"],
        "supply_current_type": "ac", "supply_voltage_v": {"min": 200, "max": 240}, "supply_phases": 1,
        "supply_frequency_hz": {"min": 50, "max": 60}, "supply_rated_current_a": 3.5,
        "out_voltage_class_v": 200, "out_rated_current_a": 2.8, "out_peak_current_a": 10,
        "encoder_protocols": ["biss_c", "endat_2_2"], "bus_protocol": "ethercat", "bus_profile": "cia402",
        "mount_pitch_x_mm": 40, "mount_pitch_y_mm": 150, "mount_hole_count": 2,
        "mount_hole_diameter_mm": 5.5, "width_mm": 50, "height_mm": 160, "depth_mm": 150,
    },
    {
        # 无总线行规（profile）行
        "model": "SD750", "rated_output_power_w": 750, "mass_kg": 1.4, "safety_functions": ["STO", "SS1"],
        "supply_current_type": "ac", "supply_voltage_v": {"min": 200, "max": 240}, "supply_phases": 3,
        "supply_frequency_hz": {"min": 50, "max": 60}, "supply_rated_current_a": 4.1,
        "out_voltage_class_v": 200, "out_rated_current_a": 5.0, "out_peak_current_a": 15,
        "encoder_protocols": ["biss_c", "endat_2_2", "ssi"], "bus_protocol": "profinet",
        "mount_pitch_x_mm": 60, "mount_pitch_y_mm": 150, "mount_hole_count": 2,
        "mount_hole_diameter_mm": 5.5, "width_mm": 70, "height_mm": 160, "depth_mm": 170,
    },
    {
        # 直流供电：相数不印在规格书上，由“直流”推出为 0（隐含字段）
        "model": "SD48-20", "rated_output_power_w": 300, "mass_kg": 0.25, "safety_functions": ["STO"],
        "supply_current_type": "dc", "supply_voltage_v": {"min": 24, "max": 60},
        "supply_rated_current_a": 8.0,
        "out_voltage_class_v": 48, "out_rated_current_a": 6.5, "out_peak_current_a": 20,
        "encoder_protocols": ["incremental_abz", "biss_c"], "bus_protocol": "canopen", "bus_profile": "cia402",
        "mount_pitch_x_mm": 70, "mount_pitch_y_mm": 90, "mount_hole_count": 4,
        "mount_hole_diameter_mm": 4.5, "width_mm": 80, "height_mm": 100, "depth_mm": 30,
    },
]

BEARINGS: list[dict] = [
    {
        "model": "SB6004-2RS", "bearing_kind": "deep_groove", "bore_mm": 20, "outer_diameter_mm": 42,
        "width_mm": 12, "dynamic_load_rating_n": 9400, "static_load_rating_n": 5000,
        "limiting_speed_rpm": 13000, "seal": "2RS", "mass_kg": 0.069, "precision": "P0",
    },
    {
        "model": "SB6205-ZZ", "bearing_kind": "deep_groove", "bore_mm": 25, "outer_diameter_mm": 52,
        "width_mm": 15, "dynamic_load_rating_n": 14000, "static_load_rating_n": 7900,
        "limiting_speed_rpm": 12000, "seal": "ZZ", "mass_kg": 0.128, "precision": "P6",
    },
    {
        # 开式轴承：无密封行
        "model": "SB7006C", "bearing_kind": "angular_contact", "bore_mm": 30, "outer_diameter_mm": 55,
        "width_mm": 13, "dynamic_load_rating_n": 15500, "static_load_rating_n": 10000,
        "limiting_speed_rpm": 15000, "mass_kg": 0.12, "precision": "P5",
    },
    {
        "model": "SBX4010", "bearing_kind": "cross_roller", "bore_mm": 40, "outer_diameter_mm": 65,
        "width_mm": 10, "dynamic_load_rating_n": 7350, "static_load_rating_n": 8350,
        "limiting_speed_rpm": 3000, "moment_load_rating_nm": 160, "mass_kg": 0.12, "precision": "P5",
    },
    {
        "model": "SBT30205", "bearing_kind": "tapered_roller", "bore_mm": 25, "outer_diameter_mm": 52,
        "width_mm": 16.25, "dynamic_load_rating_n": 32000, "static_load_rating_n": 37000,
        "limiting_speed_rpm": 8000, "mass_kg": 0.15, "precision": "P0",
    },
]

VENDORS = {
    "servo_motor": "Synth Motion",
    "drive": "Synth Motion",
    "reducer": "Synth Gear",
    "bearing": "Synth Bearing",
}

CATALOG: dict[str, list[dict]] = {
    "servo_motor": SERVO_MOTORS,
    "reducer": REDUCERS,
    "drive": DRIVES,
    "bearing": BEARINGS,
}
