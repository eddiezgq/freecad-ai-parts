# -*- coding: utf-8 -*-
"""整机老化曲线（第 166 轮，计算机厂）。

老化房里每台整机跑满载压力测试：每小时满载 50 分钟、空闲 10 分钟，老化软件每分钟记一次 CPU 温度、风扇转速、整机功耗。
（示例模型，量级按常见台式机、笔记本、2U 双路服务器取，不对应任何真实产品。）

模型（每分钟一步）：
  CPU 功耗 P_cpu：满载 / 空闲两档，带一点随机起伏；整机功耗 = CPU + 其余部件 + 风扇。
  散热：结温 T = 进风温度 + P_cpu ×（R_tim + R_hs / f^0.6），一阶滞后（时间常数 tau 分钟）；
        R_tim 是导热硅脂那一层（点胶量少 → 变大），R_hs 是散热器到空气（风扇转速 f 越高越小）。
  风扇：按温度调速，f = 0.3 … 1（相对最高转速）。
测量值：CPU 满载温度 = 老化全程 CPU 温度最高值；老化平均功耗 = 整机功耗平均值——都由曲线算出来。
只存生成参数（种子、产品类型、各热阻与功耗系数），网关按参数用本模块还原整条曲线——和仿真算测量值用的是同一个函数。
"""
from __future__ import annotations

import math
import random

# 产品类型：时长 min、进风 ℃、CPU 满载 / 空闲 W、CPU 颗数、其余部件 W、R_tim、R_hs（℃/W，满转速）、时间常数 min、
# 风扇最高转速 r/min、风扇总功率 W（满转速）、温控起点 ℃、调速区间 ℃（示例值）
KINDS = {
    "dt": dict(minutes=240, amb=25.0, p_load=125.0, p_idle=15.0, cpus=1, p_rest=40.0, r_tim=0.08, r_hs=0.32, tau=2.5, rpm=1800, p_fan=6.0, t_set=45.0, span=25.0),
    "nb": dict(minutes=240, amb=28.0, p_load=45.0, p_idle=5.0, cpus=1, p_rest=8.0, r_tim=0.22, r_hs=1.05, tau=1.5, rpm=5200, p_fan=2.0, t_set=55.0, span=25.0),
    "sv": dict(minutes=720, amb=25.0, p_load=270.0, p_idle=60.0, cpus=2, p_rest=105.0, r_tim=0.025, r_hs=0.145, tau=3.0, rpm=16000, p_fan=60.0, t_set=40.0,
               span=25.0),
}
ITEM_KIND = {"WQ-PC1": "dt", "WQ-IPC": "dt", "WQ-NB14": "nb", "WQ-SV2U": "sv"}
LOAD_MIN, CYCLE_MIN = 50, 60


def params(rng: random.Random, serial: str, kind: str, tim_extra=0.0) -> dict:
    """一台整机的生成参数：正常散布 + 点胶量不足（tim_extra：硅脂层热阻增加的倍数，0 = 正常）"""
    import zlib
    k = KINDS[kind]
    n = k["cpus"]
    return {"seed": zlib.crc32(serial.encode()) ^ rng.getrandbits(16), "kind": kind,
            "amb": round(k["amb"] + rng.gauss(0, 0.5), 2),
            "tim": [round(k["r_tim"] * max(0.6, rng.gauss(1, 0.06)) * (1 + tim_extra), 5) for _ in range(n)],
            "hs": [round(k["r_hs"] * rng.gauss(1, 0.03), 5) for _ in range(n)],
            "pl": [round(k["p_load"] * rng.gauss(1, 0.02), 2) for _ in range(n)],
            "rest": round(k["p_rest"] * rng.gauss(1, 0.03), 2)}


def generate(p: dict) -> dict:
    k = KINDS[p["kind"]]
    rng = random.Random(p["seed"])
    n = k["cpus"]
    temp = [[] for _ in range(n)]
    tj = [p["amb"] + 8.0] * n
    fan, power, load = [], [], []
    f = 0.3
    for m in range(k["minutes"]):
        on = (m % CYCLE_MIN) < LOAD_MIN
        load.append(1 if on else 0)
        pc = [(p["pl"][i] if on else k["p_idle"]) * (1 + rng.gauss(0, 0.01)) for i in range(n)]
        for i in range(n):
            target = p["amb"] + pc[i] * (p["tim"][i] + p["hs"][i] / f ** 0.6)
            tj[i] += (target - tj[i]) * (1 - math.exp(-1.0 / k["tau"]))
            temp[i].append(round(tj[i] + rng.gauss(0, 0.25), 2))
        hot = max(tj)
        f = min(1.0, max(0.3, 0.3 + 0.7 * (hot - k["t_set"]) / k["span"]))
        fan.append(round(k["rpm"] * f * (1 + rng.gauss(0, 0.01))))
        power.append(round((sum(pc) + p["rest"] + k["p_fan"] * f ** 3) * (1 + rng.gauss(0, 0.005)), 2))
    tmax = max(max(t) for t in temp)
    return {"tmax": round(tmax, 2), "pavg": round(sum(power) / len(power), 2), "temp": temp, "fan": fan, "power": power, "load": load,
            "minutes": k["minutes"], "kind": p["kind"]}


def render(p: dict, points=360) -> dict:
    """页面用：抽稀到大约 points 点"""
    g = generate(p)
    step = max(1, g["minutes"] // points)
    idx = list(range(0, g["minutes"], step))
    return {"minute": idx, "temp": [[t[i] for i in idx] for t in g["temp"]], "fan": [g["fan"][i] for i in idx],
            "power": [g["power"][i] for i in idx], "load": [g["load"][i] for i in idx],
            "tmax": g["tmax"], "pavg": g["pavg"], "kind": g["kind"], "minutes": g["minutes"],
            "r_tim": p["tim"], "r_hs": p["hs"], "amb": p["amb"], "cpus": len(p["tim"])}
