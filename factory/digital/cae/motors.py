# -*- coding: utf-8 -*-
"""电机选型助手（第 12 轮 D7）：关节力矩、转速曲线 → 交流伺服电机 + 谐波减速器组合，是否够用、裕量多少。

参数表是通用的“典型值”，按 Eddie 确认（2026-10-02）不绑定厂家；选型前以所选厂家目录为准。
  电机：60 / 80 法兰小功率交流伺服，额定 3000 r/min、最高 6000 r/min；峰值力矩约为额定的 3–3.5 倍
        （量级参照 Yaskawa Σ-7 SGM7J、Inovance SV660、Panasonic MINAS A6 等目录）。
  减速器：杯型谐波减速器，效率取 0.75；额定力矩 = 平均负载力矩上限，峰值 = 起停时允许的重复峰值力矩
        （量级参照 Harmonic Drive CSF-2UH、国产同类产品目录，传动比 50–160 时近似取同一值）。
校核（每个时刻）：
  电机侧力矩 T_m = τ/(i·η) + J_m·α·i（τ 关节力矩、α 关节角加速度、i 传动比、J_m 转子惯量）
  电机：峰值 |T_m| ≤ 电机峰值力矩；均方根 T_m ≤ 额定力矩；最高转速 ω·i ≤ 电机最高转速
  减速器：峰值 |τ| ≤ 重复峰值力矩；均方根 τ ≤ 额定力矩；输入转速 ≤ 减速器允许输入转速
"""
import math

import numpy as np

SOURCE = "通用典型值（量级参照 Yaskawa Σ-7 SGM7J、Inovance SV660、Panasonic MINAS A6 伺服电机目录；Harmonic Drive CSF-2UH 谐波减速器目录）；选型前以厂家目录为准"

# 名称, 额定功率 W, 额定力矩 N·m, 峰值力矩 N·m, 最高转速 r/min, 转子惯量 kg·m²
MOTORS = [
    ("伺服 100 W", 100, 0.318, 1.11, 6000, 0.04e-4),
    ("伺服 200 W", 200, 0.637, 2.23, 6000, 0.26e-4),
    ("伺服 400 W", 400, 1.27, 4.46, 6000, 0.42e-4),
    ("伺服 750 W", 750, 2.39, 8.36, 6000, 1.6e-4),
    ("伺服 1 kW", 1000, 3.18, 9.55, 5000, 2.0e-4),
    ("伺服 1.5 kW", 1500, 4.77, 14.3, 5000, 2.9e-4),
    ("伺服 2 kW", 2000, 6.37, 19.1, 5000, 3.8e-4),
]
# 名称, 额定力矩 N·m, 重复峰值力矩 N·m, 允许输入转速 r/min
HARMONIC = [
    ("谐波 14 号", 7.8, 28, 8500),
    ("谐波 17 号", 24, 54, 7300),
    ("谐波 20 号", 34, 82, 6500),
    ("谐波 25 号", 67, 178, 5600),
    ("谐波 32 号", 137, 333, 4800),
    ("谐波 40 号", 265, 647, 4000),
]
RATIOS = (50, 80, 100, 120, 160)
ETA = 0.75
RPM = 60 / (2 * math.pi)


def check(tau, w, a, motor, gear, i, eta=ETA):
    """一种组合的校核结果"""
    name_m, P, Tr, Tp, nmax, Jm = motor
    name_g, Gr, Gp, gin = gear
    tm = tau / (i * eta) + Jm * a * i
    res = {
        "motor": name_m, "power_W": P, "gear": name_g, "ratio": i,
        "motor_peak": float(np.max(np.abs(tm))), "motor_rms": float(np.sqrt(np.mean(tm ** 2))),
        "motor_speed_rpm": float(np.max(np.abs(w)) * i * RPM),
        "gear_peak": float(np.max(np.abs(tau))), "gear_rms": float(np.sqrt(np.mean(tau ** 2))),
        "limits": {"motor_peak": Tp, "motor_rated": Tr, "motor_speed": nmax, "gear_peak": Gp, "gear_rated": Gr, "gear_input": gin},
    }
    ratios = {"motor_peak": res["motor_peak"] / Tp, "motor_rms": res["motor_rms"] / Tr,
              "motor_speed": res["motor_speed_rpm"] / min(nmax, gin),
              "gear_peak": res["gear_peak"] / Gp, "gear_rms": res["gear_rms"] / Gr}
    worst = max(ratios, key=ratios.get)
    res["utilization"] = {k: round(v, 3) for k, v in ratios.items()}
    res["worst"] = worst
    res["ok"] = ratios[worst] <= 1.0
    m = (1 / ratios[worst] - 1) * 100 if ratios[worst] > 0 else math.inf
    res["margin_pct"] = round(m, 1) if m <= 1000 else None          # None = 裕量很大（> 1000%）
    return res


WORST_NAME = {"motor_peak": "电机峰值力矩", "motor_rms": "电机连续（均方根）力矩", "motor_speed": "转速",
              "gear_peak": "减速器峰值力矩", "gear_rms": "减速器额定（均方根）力矩"}


def select(tau, w, a, safety=1.2):
    """给一个关节选组合：在所有组合里找满足（含安全系数 safety）的，按电机功率、减速器大小、传动比接近 100 排序。
    返回 {需求, 推荐, 备选（最多 3 个）}；都不满足时给出最接近的一个并说明卡在哪里"""
    tau, w, a = (np.asarray(x, float) for x in (tau, w, a))
    need = {"peak_Nm": float(np.max(np.abs(tau))), "rms_Nm": float(np.sqrt(np.mean(tau ** 2))),
            "speed_rpm": float(np.max(np.abs(w)) * RPM), "accel_max": float(np.max(np.abs(a)))}
    cands = []
    for g in HARMONIC:
        for i in RATIOS:
            for m in MOTORS:
                r = check(tau * safety, w, a * safety, m, g, i)
                cands.append(r)
    ok = [r for r in cands if r["ok"]]
    key = lambda r: (r["power_W"], [x[0] for x in HARMONIC].index(r["gear"]), abs(r["ratio"] - 100))  # noqa: E731
    if ok:
        ok.sort(key=key)
        best = ok[0]
        alts, seen = [], {(best["motor"], best["gear"])}
        for r in ok[1:]:
            if (r["motor"], r["gear"]) not in seen:
                seen.add((r["motor"], r["gear"]))
                alts.append(r)
            if len(alts) >= 3:
                break
        note = "按 {:.1f} 倍安全系数选；最紧的是{}（利用率 {:.0%}）".format(safety, WORST_NAME[best["worst"]], best["utilization"][best["worst"]])
        return {"need": need, "best": best, "alternatives": alts, "ok": True, "safety": safety, "note": note}
    near = min(cands, key=lambda r: max(r["utilization"].values()))
    return {"need": need, "best": near, "alternatives": [], "ok": False, "safety": safety,
            "note": "表里没有够用的组合：最接近的是 {} + {}（i = {}），卡在{}（需要 {:.0%}）。请换更大规格、改轨迹（降低加速度）或减小负载".format(
                near["motor"], near["gear"], near["ratio"], WORST_NAME[near["worst"]], near["utilization"][near["worst"]])}


def table():
    return {"source": SOURCE, "eta": ETA, "ratios": list(RATIOS),
            "motors": [dict(zip(("name", "power_W", "rated_Nm", "peak_Nm", "max_rpm", "rotor_inertia"), m)) for m in MOTORS],
            "harmonic": [dict(zip(("name", "rated_Nm", "peak_Nm", "max_input_rpm"), g)) for g in HARMONIC]}
