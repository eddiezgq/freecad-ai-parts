"""空心阶梯轴的扭转刚度与静强度（ADR-0100 42.5：机器人关节输出轴按刚度设计，对照《机械设计》33.10）。

- 空心圆截面：极惯性矩 J = π(D⁴ − d⁴)/32，抗弯截面系数 W = π(D⁴ − d⁴)/(32D)，抗扭 Wt = 2W；
- 扭转角：转矩从第一段进、在最后一段传出，各段串联 θ = Σ T·Lᵢ/(G·Jᵢ)；两端那两段（法兰、花键）只算一半长度——
  转矩在这两段里是沿长度逐渐传进、传出的（与书中式 33.10.2 同）；
- 末端偏移 δ = θ·R（R 取机器人工作半径）；
- 静强度：σ = M/W，τ = T/Wt，第四强度理论 σv = √(σ² + 3τ²)，S = σs/σv。

单位：mm、N、N·mm、MPa、kg、g/cm³。纯函数，不联网。
"""

from __future__ import annotations

import math


def polar_moment(big: float, bore: float = 0.0) -> float:
    """J（mm⁴）"""
    if not 0 <= bore < big:
        raise ValueError(f"要 0 ≤ 内孔 < 外径（{bore} / {big}）")
    return math.pi * (big ** 4 - bore ** 4) / 32


def section_modulus(big: float, bore: float = 0.0) -> float:
    """抗弯截面系数 W（mm³）；抗扭为 2W"""
    return polar_moment(big, bore) / big


def twist(torque_nmm: float, segments: list[tuple[float, float]], shear_modulus_mpa: float, bore: float = 0.0,
          half_ends: bool = True) -> float:
    """扭转角（rad）。segments = [(外径, 长度)]，转矩从第一段进、最后一段出"""
    if not segments:
        raise ValueError("没有轴段")
    total = 0.0
    for i, (big, length) in enumerate(segments):
        k = 0.5 if half_ends and len(segments) > 1 and i in (0, len(segments) - 1) else 1.0
        total += torque_nmm * k * length / (shear_modulus_mpa * polar_moment(big, bore))
    return total


def tip_displacement(theta_rad: float, reach_mm: float) -> float:
    return theta_rad * reach_mm


def mass(segments: list[tuple[float, float]], density_g_cm3: float, bore: float = 0.0) -> float:
    """质量（kg）"""
    return sum(math.pi / 4 * (big ** 2 - bore ** 2) * length for big, length in segments) * density_g_cm3 * 1e-6


def static_safety(sigma_s_mpa: float, big: float, bore: float, moment_nmm: float = 0.0, torque_nmm: float = 0.0) -> dict:
    """静强度（第四强度理论）：{"sigma_mpa", "tau_mpa", "sigma_v_mpa", "safety"}；没有应力时 safety 为 None"""
    w = section_modulus(big, bore)
    sigma, tau = moment_nmm / w, torque_nmm / (2 * w)
    sv = math.sqrt(sigma ** 2 + 3 * tau ** 2)
    return {"sigma_mpa": sigma, "tau_mpa": tau, "sigma_v_mpa": sv, "safety": sigma_s_mpa / sv if sv > 0 else None}


def shear_modulus(e_mpa: float, poisson: float) -> float:
    return e_mpa / (2 * (1 + poisson))
