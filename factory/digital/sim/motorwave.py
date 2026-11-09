# -*- coding: utf-8 -*-
"""电机终检波形（第 131 轮，电机厂）。

终检台（测功台）上做两件事：
  拖动电机匀速转一圈，录三相线电压 = 反电势波形；
  不通电、慢慢转一圈，录转矩 = 齿槽转矩曲线。
示例电机：10 极 12 槽（极对数 P = 5、槽数 Q = 12），转一圈反电势走 5 个电周期；齿槽转矩的基本周期数是 LCM(2P, Q) = 60 次/圈。
（都是示例模型，量级按小功率永磁伺服电机的常见情况取。）

模型：转子 10 块磁钢，每块有自己的强度系数 a_i 和贴装位置误差 d_i（机械角度）。
  反电势：每相 = 反电势常数 × 当前对着那相线圈的磁钢强度 × 波形（基波 + 3、5、7 次）；三相在空间上互差 120° 电角度。
  齿槽转矩：每块磁钢和 12 个槽相互作用，产生每圈 12k 次的分量；10 块磁钢一样且贴得准时，前几次互相抵消，只剩每圈 60 次；
           磁钢贴歪、强弱不一时抵消不掉，出现每圈 12、24 次的低次成分，峰峰值变大。
测量值：反电势常数（相对额定 %）、三相不平衡（%）、谐波畸变 THD（%，线电压里基波以外的全部成分，含磁钢不齐造成的次谐波）、
        齿槽转矩峰峰值（相对额定转矩 %）——都由曲线算出来。

只存生成参数（种子、磁钢强度与位置误差、充磁系数、三相系数），网关按参数用本模块还原整条曲线——和仿真算测量值用的是同一个函数。
"""
from __future__ import annotations

import math
import random

P = 5               # 极对数（示例：10 极）
Q = 12              # 槽数（示例）
N = 1440            # 一圈采样点数（每点 0.25°）
B3, B5, B7 = 0.05, 0.02, 0.008       # 反电势波形 3、5、7 次谐波（相对基波，示例）
COG_K = (0.0, 3.0, 1.2, 0.4, 0.2, 0.125, 0.05)  # 单块磁钢与槽作用的每圈 12k 次分量（相对值，示例；k=5 即每圈 60 次，10 块磁钢同相叠加）
COG_SCALE = 0.40    # 换算到“% 额定转矩”的系数（示例：正常电机峰峰值约 1 %）


def _dft(y, m):
    n = len(y)
    re = sum(v * math.cos(2 * math.pi * m * i / n) for i, v in enumerate(y))
    im = sum(v * math.sin(2 * math.pi * m * i / n) for i, v in enumerate(y))
    return 2 * math.hypot(re, im) / n


def _smooth(vals, th):
    """磁钢 i 覆盖 [i, i+1)·(2π/2P)；在磁钢之间用余弦平滑过渡，得到“此刻对着的磁钢”的值"""
    n = len(vals)
    x = th / (2 * math.pi) * n - 0.5
    i0 = math.floor(x)
    f = x - i0
    w = 0.5 - 0.5 * math.cos(math.pi * f)
    return vals[i0 % n] * (1 - w) + vals[(i0 + 1) % n] * w


def generate(p: dict) -> dict:
    """p：seed、ke（充磁系数，1 = 额定）、mag_a [10 块磁钢强度]、mag_d [10 块位置误差，机械角度 °]、ph [三相系数]。
    返回测量值与画图用的数据。"""
    rng = random.Random(p["seed"])
    a, d = p["mag_a"], [math.radians(x) for x in p["mag_d"]]
    ke, ph = p["ke"], p["ph"]
    psi = [rng.uniform(0, 2 * math.pi) for _ in COG_K]
    emf = [[], [], []]
    cog = []
    for i in range(N):
        th = 2 * math.pi * i / N
        for x in range(3):
            t = th - x * 2 * math.pi / (3 * P)
            amp = _smooth(a, t)
            u = P * (t - _smooth(d, t))
            f = math.sin(u) + B3 * math.sin(3 * u) + B5 * math.sin(5 * u) + B7 * math.sin(7 * u)
            emf[x].append(100.0 * ke * ph[x] * amp * f + rng.gauss(0, 0.05))
        c = 0.0
        for j in range(2 * P):
            tj = th - j * 2 * math.pi / (2 * P) - d[j]
            c += a[j] ** 2 * sum(COG_K[k] * math.sin(k * Q * tj + psi[k]) for k in range(1, len(COG_K)))
        cog.append(COG_SCALE * c + rng.gauss(0, 0.01))
    fund = [_dft(e, P) for e in emf]
    line = [emf[0][i] - emf[1][i] for i in range(N)]
    lh = [_dft(line, m) for m in range(1, 8 * P + 1)]
    l1 = lh[P - 1]
    thd = 100.0 * math.sqrt(sum(v * v for m, v in enumerate(lh, 1) if m != P)) / l1
    ch = [round(_dft(cog, Q * k), 4) for k in range(1, 7)]
    mean = sum(fund) / 3
    return {
        "ke": round(mean, 3),                       # 相反电势基波幅值（额定 = 100）
        "unbal": round(100.0 * (max(fund) - min(fund)) / mean, 3),
        "thd": round(thd, 3),
        "cog": round(max(cog) - min(cog), 4),
        "emf": emf, "cog_curve": cog, "line_harm": [round(100.0 * v / l1, 3) for v in lh], "cog_harm": ch,
    }


def params(rng: random.Random, serial: str, mag_extra=0.0, ke_drop=0.0, ph_drop=0.0) -> dict:
    """一台电机的生成参数：正常散布 + 隐藏问题带来的偏差（磁钢位置误差加大 °、充磁不足 %、某一相匝间问题 %）"""
    import zlib
    sd = 0.12 + mag_extra                         # 磁钢位置误差（机械角度 °，示例）
    sa = 0.008 + 0.01 * mag_extra                 # 磁钢强度散布
    ph = [1 + rng.gauss(0, 0.002) for _ in range(3)]
    if ph_drop:
        ph[rng.randrange(3)] *= 1 - ph_drop / 100.0
    return {"seed": zlib.crc32(serial.encode()) ^ rng.getrandbits(16),
            "ke": round(1 + rng.gauss(0, 0.008) - ke_drop / 100.0, 4),
            "mag_a": [round(1 + rng.gauss(0, sa), 4) for _ in range(2 * P)],
            "mag_d": [round(rng.gauss(0, sd), 3) for _ in range(2 * P)],
            "ph": [round(v, 4) for v in ph]}


def render(p: dict, points=720) -> dict:
    """页面用：三相反电势、齿槽转矩抽稀到 points 点"""
    g = generate(p)
    step = N // points
    return {"deg": [round(360.0 * i / N, 3) for i in range(0, N, step)],
            "emf": [[round(e[i], 2) for i in range(0, N, step)] for e in g["emf"]],
            "cog_curve": [round(g["cog_curve"][i], 4) for i in range(0, N, step)],
            "line_harm": g["line_harm"], "cog_harm": g["cog_harm"],
            "ke": g["ke"], "unbal": g["unbal"], "thd": g["thd"], "cog": g["cog"],
            "mag_a": p["mag_a"], "mag_d": p["mag_d"], "poles": 2 * P, "slots": Q, "n": N}
