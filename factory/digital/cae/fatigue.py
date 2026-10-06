# -*- coding: utf-8 -*-
"""疲劳寿命（第 11 轮 F6）：有限元结果 + 载荷谱 → 每个表面点的寿命。

做法（名义应力法的“局部应力”版，教学常用）：
1. 线弹性：任意时刻应力 = 有限元应力 × 载荷 / 计算工况载荷（比例加载）。
2. 载荷谱当作一个不断重复的“块”：从绝对值最大的点切开、首尾相接，再用 pyLife 的四点法雨流计数，所有循环都闭合。
3. 每个循环：应力幅 σa、平均应力 σm；Goodman 平均应力修正 σa,eq = σa / (1 − |σm| / σb)。
4. 材料 S-N 曲线（材料库：σ₋₁、N_D、斜率 k）按表面状态 β、尺寸 ε、附加缺口系数 Kf 修正：
   S_D = σ₋₁ · β · ε / Kf。有限元已经算出了形状引起的应力集中，所以 Kf 默认 1。
5. Miner 线性累积损伤（pyLife WoehlerCurve）：低于 S_D 不损伤（原始 Miner）或按 Haibach（斜率 2k−1）继续损伤。
寿命 = 1 / 每块损伤 块数 → 循环数、小时。
"""
import math

import numpy as np

SURFACE = {          # 表面状态系数 β（钢，σb ≈ 600–800 MPa 时的常用值，濮良贵《机械设计》附图 3-8 量级）
    "polished": (1.0, "抛光"),
    "ground": (0.92, "磨削"),
    "fine_turned": (0.85, "精车"),
    "rough_turned": (0.75, "粗车"),
    "forged": (0.55, "锻造毛坯 / 未加工"),
}


def closed_block(series):
    """把一段载荷当作重复的块：从 |载荷| 最大处切开、首尾相接，保证雨流计数时所有循环都闭合"""
    s = np.asarray(series, float)
    if len(s) < 2:
        raise ValueError("载荷记录太短")
    i = int(np.argmax(np.abs(s)))
    return np.concatenate([s[i:], s[:i + 1]])


def _cycles(arr):
    import pandas as pd
    from pylife.stress import rainflow as rf
    c = rf.FourPointDetector(recorder=rf.FullRecorder()).process(pd.Series(arr)).recorder.collective
    return [] if not len(c) else list(zip(c["from"].to_numpy(), c["to"].to_numpy()))


def rainflow(series):
    """一个重复块里的全部循环：返回 [(幅值, 平均值)]，单位与载荷相同。
    pyLife 的计数会留下“残余”（没闭合的半循环）；对重复块，把块接两遍计数，减去只接一遍的结果，就是稳态下每块的循环。"""
    one = closed_block(series)
    two = np.concatenate([one, one[1:]])
    c1, c2 = _cycles(one), _cycles(two)
    left = {}
    for fr, to in c1:
        k = (round(float(fr), 9), round(float(to), 9))
        left[k] = left.get(k, 0) + 1
    out = []
    for fr, to in c2:
        k = (round(float(fr), 9), round(float(to), 9))
        if left.get(k):
            left[k] -= 1
            continue
        out.append((abs(to - fr) / 2, (to + fr) / 2))
    return np.array(out, float).reshape(-1, 2)


def compute(vm_ref, ref_load, series, block_seconds, mat, surface="ground", size_factor=0.85, kf=1.0, haibach=True):
    """vm_ref：各点在计算工况（载荷 ref_load）下的 Von Mises 应力（MPa）。
    返回 (各点每块损伤, 汇总 dict)"""
    import pandas as pd
    import pylife.materiallaws  # noqa: F401 —— 注册 .woehler
    if not ref_load:
        raise ValueError("计算工况的载荷是 0")
    beta = SURFACE[surface][0]
    SD = mat["sigma_1"] * beta * size_factor / kf
    ND, k = float(mat["N_D"]), float(mat["k"])
    Rm = float(mat["ultimate_mpa"])
    cyc = rainflow(series)
    vm = np.asarray(vm_ref, float)
    scale = vm / abs(ref_load)                                    # 每单位载荷的应力
    wc = pd.Series({"SD": SD, "ND": ND, "k_1": k, "k_2": (2 * k - 1) if haibach else np.inf}).woehler
    D = np.zeros(len(vm))
    worst = []
    for a, m in cyc:
        if a <= 0:
            continue
        sa = scale * a
        sm = scale * abs(m)
        ratio = np.clip(sm / Rm, 0, 0.999)
        sa_eq = sa / (1 - ratio)
        N = np.asarray(wc.cycles(sa_eq), float)
        with np.errstate(divide="ignore"):
            D += np.where(np.isfinite(N) & (N > 0), 1.0 / N, 0.0)
        worst.append((a, m))
    i = int(np.argmax(D))
    Dmax = float(D[i])
    blocks = math.inf if Dmax <= 0 else 1.0 / Dmax
    # 最危险点的载荷循环统计（报告和页面展示）
    hot = []
    for a, m in sorted(worst, key=lambda x: -x[0])[:8]:
        sa = scale[i] * a
        sm = scale[i] * abs(m)
        sa_eq = sa / (1 - min(sm / Rm, 0.999))
        n = float(np.asarray(wc.cycles(np.array([sa_eq])))[0])
        hot.append({"load_amp": round(a, 3), "load_mean": round(m, 3), "sigma_a": round(sa, 2), "sigma_m": round(sm, 2),
                    "sigma_a_eq": round(sa_eq, 2), "N": None if not math.isfinite(n) else n})
    summary = {
        "cycles_per_block": int(len(cyc)), "block_seconds": block_seconds,
        "S_D": round(SD, 2), "N_D": ND, "k": k, "k2": (2 * k - 1) if haibach else None,
        "beta": beta, "surface": SURFACE[surface][1], "size_factor": size_factor, "kf": kf, "haibach": haibach,
        "damage_per_block": Dmax, "life_blocks": None if not math.isfinite(blocks) else blocks,
        "life_hours": None if not math.isfinite(blocks) else blocks * block_seconds / 3600,
        "infinite": not math.isfinite(blocks), "hot_index": i, "hot_vm_ref": round(float(vm[i]), 2), "hot_cycles": hot,
    }
    return D, summary


def hand_check(sigma_a, sigma_m, mat, surface="ground", size_factor=0.85, kf=1.0):
    """恒幅手算（测试和报告对照用）：Goodman + Basquin"""
    SD = mat["sigma_1"] * SURFACE[surface][0] * size_factor / kf
    sa_eq = sigma_a / (1 - abs(sigma_m) / mat["ultimate_mpa"])
    if sa_eq < SD:
        return math.inf
    return mat["N_D"] * (SD / sa_eq) ** mat["k"]
