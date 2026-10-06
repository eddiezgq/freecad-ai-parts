# -*- coding: utf-8 -*-
"""机械臂关节孪生（第 15 轮 T8，选做）：一个搬运循环的关节力矩、转速（第 12 轮运动与动力分析）→ 每个关节的谐波减速器寿命。

谐波减速器寿命（Harmonic Drive CSF 系列样本的寿命公式，波发生器轴承决定寿命）：
  L10 = 7000 h × (T_r / T_av)³ × (n_r / n_av)
  T_r：额定力矩（输入 2000 r/min 时，见 cae/motors.py 的谐波减速器表）；n_r = 2000 r/min；
  T_av：平均负载力矩 = (Σ nᵢ·tᵢ·|Tᵢ|³ / Σ nᵢ·tᵢ)^(1/3)（按输入转速加权的立方平均）；
  n_av：平均输入转速 = Σ nᵢ·tᵢ / Σ tᵢ（含停顿时间）。
减速器规格和传动比按第 12 轮的电机选型助手自动选（安全系数 1.2）。"""
import math

import numpy as np

L_RATED_H, N_RATED_RPM = 7000.0, 2000.0
RPM = 60 / (2 * math.pi)


def joint_life(t, tau, w, rated_nm, ratio):
    t, tau, w = (np.asarray(x, float) for x in (t, tau, w))
    dt = np.gradient(t) if len(t) > 1 else np.ones(1)
    n_in = np.abs(w) * RPM * ratio
    wsum = float(np.sum(n_in * dt))
    if wsum <= 0:
        return {"T_av": 0.0, "n_av_in": 0.0, "L10_h": None}
    T_av = (float(np.sum(n_in * dt * np.abs(tau) ** 3)) / wsum) ** (1 / 3)
    n_av = wsum / float(np.sum(dt))
    L = L_RATED_H * (rated_nm / max(T_av, 1e-9)) ** 3 * (N_RATED_RPM / n_av)
    return {"T_av": T_av, "n_av_in": n_av, "L10_h": L}


def reducer_life(ser, joints):
    """ser：第 12 轮的时间序列（t、drive.<关节>、qd.<关节>、qdd.<关节>）；joints：要算的转动关节名"""
    from cae import motors as MT
    out = []
    for jn in joints:
        sel = MT.select(ser["drive." + jn], ser["qd." + jn], ser["qdd." + jn], 1.2)
        b = sel["best"]
        rated = b["limits"]["gear_rated"]
        r = joint_life(ser["t"], ser["drive." + jn], ser["qd." + jn], rated, b["ratio"])
        out.append(dict(r, joint=jn, gear=b["gear"], ratio=b["ratio"], rated_Nm=rated, ok=sel["ok"],
                        peak_Nm=sel["need"]["peak_Nm"]))
    return {"cycle_s": float(ser["t"][-1] - ser["t"][0]), "joints": out,
            "formula": "L10 = 7000 h ×（额定力矩 / 平均负载力矩）³ ×（2000 r/min / 平均输入转速）"}
