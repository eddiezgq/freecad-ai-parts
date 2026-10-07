"""疲劳寿命（ADR-0056，M10 第三步）：危险点应力 × 载荷谱 → 雨流计数 → Goodman 平均应力修正 → S-N → Miner 累积损伤。

搬自问渠数字工厂第 11 轮的做法，雨流计数改为本模块自写（ASTM E1049-85 重复载荷历程的三点法），不再依赖 pyLife。

设置：
  material: 材料库 id（需要 σ₋₁、拐点次数 N_D、斜率 k、抗拉强度）
  stress_ref_mpa、load_ref：危险点在参考载荷 load_ref 下的应力（如有限元结果的最大 Von Mises 应力与所加扭矩）；
                           线弹性比例加载：任意时刻应力 = stress_ref_mpa × 载荷 / load_ref
  load_series: 载荷记录（一个重复的块，与 load_ref 同单位）；block_seconds：这一块的时长（算小时数）
  surface_factor、size_factor：表面状态系数 β、尺寸系数 ε（0–1，按教材图表查得后填写，本模块不给缺省值）
  kf：附加缺口系数（缺省 1——有限元已算出形状引起的应力集中）
  miner: "haibach"（缺省，低于疲劳极限按斜率 2k−1 继续损伤）| "original"（低于疲劳极限不损伤）
"""

from __future__ import annotations

import math
import time

from analysis.common import materials, result

MODULE = {
    "id": "fatigue", "name": "疲劳寿命", "version": "1",
    "description": "载荷谱 → 雨流计数 → Goodman → S-N → Miner，算危险点寿命",
    "python": [], "solvers": [], "install": "",
}
LIMITS = ["名义应力法的局部应力版：危险点应力按载荷比例缩放（线弹性、比例加载）",
          "表面、尺寸系数按教材图表取值，结果对它们很敏感，主要用于比较方案",
          "Miner 线性累积，不计加载顺序效应"]


class FatigueError(ValueError):
    pass


def reversals(series) -> list[float]:
    """峰谷点（去掉单调中间点与相等的相邻点）。"""
    out: list[float] = []
    for x in map(float, series):
        if out and x == out[-1]:
            continue
        if len(out) >= 2 and (out[-1] - out[-2]) * (x - out[-1]) > 0:
            out[-1] = x
        else:
            out.append(x)
    return out


def closed_block(series) -> list[float]:
    """把一段载荷当作重复的块：从 |载荷| 最大处切开、首尾相接（ASTM E1049 重复历程的做法）。"""
    s = [float(x) for x in series]
    if len(s) < 2:
        raise FatigueError("载荷记录太短")
    i = max(range(len(s)), key=lambda k: abs(s[k]))
    return reversals(s[i:] + s[: i + 1])


def rainflow(series) -> list[tuple[float, float]]:
    """重复块的雨流计数（ASTM E1049-85 第 5.4.4 节，三点法）：返回每块的全循环 [(幅值, 平均值)]。"""
    stack: list[float] = []
    out = []
    for p in closed_block(series):
        stack.append(p)
        while len(stack) >= 3:
            x = abs(stack[-1] - stack[-2])
            y = abs(stack[-2] - stack[-3])
            if x < y:
                break
            a, b = stack[-3], stack[-2]
            out.append((abs(b - a) / 2, (a + b) / 2))
            del stack[-3:-1]
    return out


def sn_cycles(sa_eq: float, s_d: float, n_d: float, k: float, haibach: bool) -> float:
    """S-N 曲线（Basquin）：σᵏ·N = 常数；低于疲劳极限按 Haibach（斜率 2k−1）或不损伤。"""
    if sa_eq <= 0:
        return math.inf
    if sa_eq >= s_d:
        return n_d * (s_d / sa_eq) ** k
    return n_d * (s_d / sa_eq) ** (2 * k - 1) if haibach else math.inf


def sn_cycles_array(sa_eq, s_d: float, n_d: float, k: float, haibach: bool):
    """sn_cycles 的数组版（逐点；工厂网页对每个表面点算寿命用）。"""
    import numpy as np

    sa = np.asarray(sa_eq, float)
    out = np.full(sa.shape, np.inf)
    pos = sa > 0
    hi = pos & (sa >= s_d)
    with np.errstate(divide="ignore"):
        out[hi] = n_d * (s_d / sa[hi]) ** k
        lo = pos & (sa < s_d)
        if haibach:
            out[lo] = n_d * (s_d / sa[lo]) ** (2 * k - 1)
    return out


def hand_check(sigma_a: float, sigma_m: float, mat: dict, surface_factor: float, size_factor: float, kf: float = 1.0,
               haibach: bool = False) -> float:
    """恒幅手算：Goodman + Basquin（测试与报告对照用）。返回循环次数。"""
    s_d = mat["fatigue_limit_bending_mpa"] * surface_factor * size_factor / kf
    sa_eq = sigma_a / (1 - abs(sigma_m) / mat["ultimate_strength_mpa"])
    return sn_cycles(sa_eq, s_d, mat["sn_knee_cycles"], mat["sn_exponent"], haibach)


def _factor(setup: dict, key: str) -> float:
    v = setup.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
        raise FatigueError(f"{key} 须为 0–1 之间的数（按教材图表查得后填写）")
    return float(v)


def run(setup: dict) -> dict:
    t0 = time.time()
    try:
        mat = materials.get(setup.get("material", ""))
        materials.require(mat, ["fatigue_limit_bending_mpa", "sn_knee_cycles", "sn_exponent", "ultimate_strength_mpa"],
                          "疲劳计算")
        beta, eps = _factor(setup, "surface_factor"), _factor(setup, "size_factor")
        kf = float(setup.get("kf", 1.0))
        if kf < 1:
            raise FatigueError("kf 不能小于 1")
        ref, sref = float(setup["load_ref"]), float(setup["stress_ref_mpa"])
        if ref == 0:
            raise FatigueError("参考载荷不能为 0")
        block_s = float(setup.get("block_seconds", 0))
        haibach = setup.get("miner", "haibach") == "haibach"
        cycles = rainflow(setup.get("load_series") or [])
    except (materials.MissingData, FatigueError, KeyError, TypeError, ValueError) as exc:
        return result.failed("fatigue", MODULE["version"], setup, f"没有算出：{exc}")
    scale = sref / abs(ref)
    s_d = mat["fatigue_limit_bending_mpa"] * beta * eps / kf
    n_d, k, rm = mat["sn_knee_cycles"], mat["sn_exponent"], mat["ultimate_strength_mpa"]
    damage, rows = 0.0, []
    for a, m in cycles:
        sa, sm = scale * a, scale * abs(m)
        sa_eq = sa / (1 - min(sm / rm, 0.999))
        n = sn_cycles(sa_eq, s_d, n_d, k, haibach)
        damage += 0.0 if math.isinf(n) else 1.0 / n
        rows.append({"load_amp": a, "load_mean": m, "sigma_a_mpa": sa, "sigma_m_mpa": sm, "sigma_a_eq_mpa": sa_eq,
                     "cycles_to_failure": None if math.isinf(n) else n})
    infinite = damage <= 0
    blocks = None if infinite else 1.0 / damage
    data = {"cycles_per_block": len(cycles), "fatigue_strength_mpa": s_d, "knee_cycles": n_d, "sn_exponent": k,
            "miner": "haibach" if haibach else "original", "damage_per_block": damage, "life_blocks": blocks,
            "life_hours": None if blocks is None or not block_s else blocks * block_s / 3600, "infinite": infinite,
            "worst_cycles": sorted(rows, key=lambda r: -r["sigma_a_eq_mpa"])[:8],
            "max_stress_mpa": scale * max((abs(x) for x in setup["load_series"]), default=0)}
    msgs = []
    if data["max_stress_mpa"] >= materials.strength_mpa(mat)[0]:
        msgs.append("最大应力已达到材料强度，先做强度校核")
    return result.make("fatigue", MODULE["version"], setup, data, limitations=LIMITS, messages=msgs,
                       elapsed_s=time.time() - t0)
