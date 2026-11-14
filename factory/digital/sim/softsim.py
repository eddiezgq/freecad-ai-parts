# -*- coding: utf-8 -*-
"""软件公司的两个模型（第 167 轮）。示例模型，量级按常见的嵌入式实时系统、Linux 发行版、云服务取，不对应任何真实产品。

一、构建流水线（每个版本构建一次）：
  单元测试 + 集成测试一共 N 个用例，正常偶发失败按泊松分布（平均 base_fail 个）；构建服务器时钟漂移时，和时间有关的用例
  （超时、证书有效期、定时器）在那台服务器上随机失败，多出平均 flaky 个——“重跑一下就过了”的典型。测试通过率 = 通过数 / N。
  硬件在环（实时 OS、机器人软件）：2 万次中断，延迟 = 基础 + 对数正态尾巴（缓存未命中、总线争用）；测试台缓存配置错时每次都多一截。
      最坏中断延迟 = 2 万次里的最大值。
  长稳压测（OS、云平台、数字工厂）：每 10 分钟记一次内存占用，带垃圾回收的锯齿；内存泄漏时多一条直线斜率。
      内存增长速率 = 每次垃圾回收后的内存底线的最小二乘斜率（MB/h）。
二、24 小时服务曲线（每份订阅开通后验收一天）：
  每分钟延迟 p99 = 基础 × 日周期 × 噪声；同一宿主机上“吵闹的邻居”占满时，随机三成的分钟多出几十毫秒；
  错误率 = 基础 + 错误配置推到那个可用区时的额外错误。可用性 = 延迟 < 200 ms 且错误率 < 1 % 的分钟占比。
  服务延迟 p99 = 24 小时平均，错误率 = 24 小时平均，可用性 = 好的分钟占比。
测量值都由曲线算出，只存生成参数（种子、产品、注入的额外量），网关按参数用本模块还原整条曲线。
"""
from __future__ import annotations

import math
import random
import zlib

# 版本：测试用例数、偶发失败、覆盖率、硬件在环（基础延迟 μs、尾巴）、长稳压测（小时、基础内存 MB、正常斜率 MB/h）
BUILD = {
    "REL-RTOS": dict(tests=3200, base_fail=0.8, hil=(3.0, 0.18), soak=None),
    "REL-ROBOT": dict(tests=2600, base_fail=0.8, hil=(4.8, 0.22), soak=None),
    "REL-OS": dict(tests=5200, base_fail=1.0, hil=None, soak=(12, 900.0, 0.3)),
    "REL-CLOUD": dict(tests=6400, base_fail=1.2, hil=None, soak=(12, 2400.0, 0.3)),
    "REL-MES": dict(tests=4000, base_fail=1.0, hil=None, soak=(4, 1200.0, 0.3)),
}
SERVICE = {"SUB-CLOUD": dict(base=18.0), "SUB-MES": dict(base=19.0)}
IRQ_N = 20000
STAGES = ("合并与评审", "编译与单元测试", "集成测试", "硬件在环测试 / 长稳压测", "安全扫描", "发布门禁", "签名发布")


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    k, p, L = 0, 1.0, math.exp(-lam)
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def build_params(rng: random.Random, serial: str, item: str, flaky=0.0, irq_extra=0.0, leak=0.0, runner="", bench="") -> dict:
    """一个版本构建的生成参数。flaky：时钟漂移带来的额外偶发失败（平均个数）；irq_extra：测试台缓存配置错多出的延迟 μs；leak：内存泄漏 MB/h"""
    return {"seed": zlib.crc32(serial.encode()) ^ rng.getrandbits(16), "item": item, "flaky": round(flaky, 3), "irq_extra": round(irq_extra, 3),
            "leak": round(leak, 3), "runner": runner, "bench": bench, "cov": round(rng.gauss(0, 1), 3)}


def build(p: dict) -> dict:
    k = BUILD[p["item"]]
    rng = random.Random(p["seed"])
    n = k["tests"]
    fail_base = _poisson(rng, k["base_fail"])
    fail_flaky = _poisson(rng, p["flaky"] * n / 3000)          # 时钟有关的用例大致和用例总数成比例
    fails = min(n, fail_base + fail_flaky)
    out = {"item": p["item"], "tests": n, "fails": fails, "fail_flaky": fail_flaky, "pass": round((n - fails) / n * 100, 3),
           "runner": p.get("runner", ""), "bench": p.get("bench", "")}
    if k["hil"]:
        base, sig = k["hil"]
        lat = [base + p["irq_extra"] + rng.lognormvariate(-0.9, 0.45) + (rng.uniform(0, 1.5) if rng.random() < 0.02 else 0.0) for _ in range(IRQ_N)]
        lat.sort()
        edges = [round(base + p["irq_extra"] * 0 + i * 0.25, 2) for i in range(41)]
        hist = [0] * 40
        for v in lat:
            j = int((v - edges[0]) / 0.25)
            hist[min(39, max(0, j))] += 1
        out.update(irq_max=round(lat[-1], 3), irq_p999=round(lat[int(0.999 * IRQ_N)], 3), irq_mean=round(sum(lat) / IRQ_N, 3),
                   hist_edges=edges, hist=hist)
    if k["soak"]:
        hours, m0, slope = k["soak"]
        ts, mem, ft, fm = [], [], [], []
        for i in range(hours * 6 + 1):
            t = i / 6
            saw = 60.0 * ((i % 6) / 6)                       # 垃圾回收锯齿：每小时回收一次，回收后回到底线
            v = round(m0 + (slope + p["leak"]) * t + saw + rng.gauss(0, 2), 1)
            mem.append(v)
            ts.append(round(t, 3))
            if i % 6 == 0:                                   # 每次回收后的底线：泄漏看的是底线在不在涨
                ft.append(t)
                fm.append(v)
        tm = sum(ft) / len(ft)
        mm = sum(fm) / len(fm)
        b = sum((a - tm) * (c - mm) for a, c in zip(ft, fm)) / sum((a - tm) ** 2 for a in ft)
        out.update(leak=round(b, 3), soak_h=ts, soak_mb=mem, floor_h=ft, floor_mb=fm)
    return out


def service_params(rng: random.Random, serial: str, item: str, host="", noisy=0.0, cfg=0.0) -> dict:
    """一份订阅 24 小时验收的生成参数。noisy：同宿主机“吵闹的邻居”强度；cfg：错误配置带来的额外错误率 %"""
    return {"seed": zlib.crc32(serial.encode()) ^ rng.getrandbits(16), "item": item, "host": host, "noisy": round(noisy, 3), "cfg": round(cfg, 4)}


def service(p: dict) -> dict:
    k = SERVICE[p["item"]]
    rng = random.Random(p["seed"])
    lat, err, good = [], [], 0
    for m in range(1440):
        day = 1 + 0.18 * math.sin(2 * math.pi * (m / 60 - 9) / 24)
        v = k["base"] * day * rng.lognormvariate(0, 0.06)
        if p["noisy"] > 0 and rng.random() < 0.3:
            v += p["noisy"] * rng.uniform(30, 90)
        e = max(0.0, rng.gauss(0.02, 0.006) + (p["cfg"] * rng.uniform(0.6, 1.4) if p["cfg"] > 0 else 0.0))
        lat.append(round(v, 2))
        err.append(round(e, 4))
        good += 1 if (v < 200 and e < 1.0) else 0
    return {"item": p["item"], "host": p.get("host", ""), "p99": round(sum(lat) / 1440, 3), "err": round(sum(err) / 1440, 4),
            "avail": round(good / 1440 * 100, 3), "lat": lat, "errs": err}


def render_service(p: dict, points=288) -> dict:
    """页面用：抽稀到每 5 分钟一点"""
    g = service(p)
    step = 1440 // points
    idx = list(range(0, 1440, step))
    return {"minute": idx, "lat": [max(g["lat"][i:i + step]) for i in idx], "err": [max(g["errs"][i:i + step]) for i in idx],
            "p99": g["p99"], "err_avg": g["err"], "avail": g["avail"], "host": g["host"], "item": g["item"], "noisy": p["noisy"], "cfg": p["cfg"]}
