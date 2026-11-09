# -*- coding: utf-8 -*-
"""编码器整圈误差曲线（第 125 轮，传感器厂）。

终检时把编码器和基准编码器同轴连起来转一圈，每隔 360°/4096 记一次“被测读数 − 基准读数”，就是整圈误差曲线。
曲线由几种成分叠加（都是示例模型，量级按光电编码器的常见情况取）：
  一次谐波（每圈一个起伏）：码盘偏心 e，幅值 ≈ e / R（弧度）。R 是码道半径（示例 13 mm），e = 1 µm → 约 16″
  二次谐波：码盘倾斜、轴承椭圆，幅值几角秒
  高次谐波：码盘刻划误差，3–16 次逐渐减小
  脏污：码盘上某处有污点 → 那个角度信号幅值掉坑，细分出错 → 曲线上一处尖峰
  细分误差：读头正余弦信号幅值不等、有偏置时，每个信号周期（360°/2048）内起伏；周期太短，在整圈曲线上看不出，单独放大两个信号周期看
信号幅值（额定 = 100 %）主要由读头间隙决定：间隙偏大幅值下降，细分误差随之变大（近似与幅值的平方成反比）。

只存生成参数（种子、偏心、间隙幅值、污点……），网关按参数用本模块还原整条曲线——和仿真算测量值用的是同一个函数，所以曲线和测量值一定对得上。
"""
from __future__ import annotations

import math
import random

R_MM = 13.0          # 码道半径（示例）
LINES = 2048         # 增量码道线数（示例）：一个信号周期 360°/2048 ≈ 633″
N = 4096             # 整圈采样点数
ARCSEC = 206264.806


def h1_of(ecc_um):
    """偏心 e（µm）引起的一次谐波幅值（角秒）"""
    return ecc_um * 1e-3 / R_MM * ARCSEC


def _dft(y, k):
    n = len(y)
    re = sum(v * math.cos(2 * math.pi * k * i / n) for i, v in enumerate(y))
    im = sum(v * math.sin(2 * math.pi * k * i / n) for i, v in enumerate(y))
    return 2 * math.hypot(re, im) / n


def generate(p: dict) -> dict:
    """p：seed、ecc_um（偏心）、h2（二次谐波角秒）、grad（刻划误差系数）、amp（平均信号幅值 %）、interp_base（额定幅值下的细分误差峰峰值）、
    spots [[角度°, 宽度°, 深度 0–1], …]。返回测量值与画图用的数据。"""
    rng = random.Random(p["seed"])
    ph = [rng.uniform(0, 2 * math.pi) for _ in range(17)]
    amp_k = [0.0, h1_of(p["ecc_um"]), p["h2"]] + [p["grad"] / math.sqrt(k) * rng.uniform(0.4, 1.0) for k in range(3, 17)]
    spots = p.get("spots") or []
    amp0 = p["amp"]
    interp = p["interp_base"] * (100.0 / max(amp0, 20.0)) ** 2
    err, ampc = [], []
    for i in range(N):
        th = 2 * math.pi * i / N
        deg = 360.0 * i / N
        e = sum(amp_k[k] * math.sin(k * th + ph[k]) for k in range(1, 17)) + rng.gauss(0, 0.6)
        a = amp0 * (1 + 0.004 * p["ecc_um"] * math.sin(th + ph[1]))     # 偏心让读头看到的码道半径一圈变化，幅值跟着轻微起伏
        for (sa, sw, sd) in spots:
            dd = (deg - sa + 180.0) % 360.0 - 180.0
            g = math.exp(-(dd / sw) ** 2)
            a *= 1 - sd * g
            e += 60.0 * sd * g * (1 if dd >= 0 else -1)               # 幅值掉坑处细分出错：一正一负的尖峰
        err.append(e)
        ampc.append(a)
    mean = sum(err) / N
    err = [v - mean for v in err]
    harm = [round(_dft(err, k), 2) for k in range(1, 17)]
    pp = max(err) - min(err)
    # 两个信号周期内的细分误差：幅值不等给每周期两个起伏，偏置给一个（示例比例）
    ip = [(interp / 2) * (0.75 * math.sin(4 * math.pi * j / 100 + ph[0]) + 0.25 * math.sin(2 * math.pi * j / 100 + ph[2])) / 0.92
          for j in range(201)]
    return {
        "acc": round(pp + interp, 2),
        "h1": harm[0],
        "interp": round(interp, 2),
        "amp": round(sum(ampc) / N, 2),
        "amp_min": round(min(ampc), 2),
        "err": err, "amp_curve": ampc, "harmonics": harm, "interp_curve": ip,
    }


def params(rng: random.Random, serial: str, ecc_extra=0.0, amp_drop=0.0, spots_lam=0.0) -> dict:
    """一台编码器的生成参数：正常的散布 + 隐藏问题带来的偏差（偏心增加 µm、幅值下降 %、污点个数的期望）"""
    import zlib
    n_sp = 0
    if spots_lam > 0:
        L, k, q = math.exp(-spots_lam), 0, 1.0
        while True:
            q *= rng.random()
            if q <= L:
                break
            k += 1
        n_sp = k
    if rng.random() < 0.03:
        n_sp += 1                                      # 偶尔一个小污点（正常也会有）
    spots = [[round(rng.uniform(0, 360), 1), round(rng.uniform(1.0, 3.0), 2),
              round(rng.uniform(0.3, 0.5) if spots_lam > 0 else rng.uniform(0.05, 0.15), 3)] for _ in range(n_sp)]
    return {"seed": zlib.crc32(serial.encode()) ^ rng.getrandbits(16),
            "ecc_um": round(0.75 * rng.lognormvariate(0, 0.3) + ecc_extra, 3),
            "h2": round(abs(rng.gauss(3.0, 1.0)), 2), "grad": round(abs(rng.gauss(3.0, 0.5)), 2),
            "amp": round(rng.gauss(100.0, 3.0) - amp_drop, 2), "interp_base": round(abs(rng.gauss(7.5, 0.8)), 2), "spots": spots}


def render(p: dict, points=720) -> dict:
    """页面用：整圈曲线、幅值曲线抽稀到 points 点"""
    g = generate(p)
    step = N // points
    return {"deg": [round(360.0 * i / N, 3) for i in range(0, N, step)],
            "err": [round(g["err"][i], 2) for i in range(0, N, step)],
            "amp_curve": [round(g["amp_curve"][i], 2) for i in range(0, N, step)],
            "interp_curve": [round(v, 2) for v in g["interp_curve"]],
            "harmonics": g["harmonics"], "acc": g["acc"], "h1": g["h1"], "interp": g["interp"], "amp": g["amp"], "amp_min": g["amp_min"],
            "ecc_um": p["ecc_um"], "spots": p.get("spots") or [], "r_mm": R_MM, "lines": LINES, "n": N}
