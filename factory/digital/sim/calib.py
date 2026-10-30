# -*- coding: utf-8 -*-
"""整机运动学标定（第 55 轮）：协作机器人 WQ-CR5 的几何误差模型、激光跟踪仪测量、最小二乘辨识、补偿与验证。

教材对照：《机器人学》第 13 章（DH 参数；13.5 节讲相邻平行轴时 DH 参数的病态）、26.3 节（最小二乘辨识）。

- 名义几何：标准 DH，T_i = Rz(θ_i + Δθ_i) · Tz(d_i + Δd_i) · Tx(a_i + Δa_i) · Rx(α_i + Δα_i)。名义参数是 **示例值**
  （量级与常见 5 kg 协作臂相同，不照抄任何厂商的数）；工具点离法兰轴线 50 mm，第 6 关节的零位也看得见。
- 一台机器人的“真实”偏差：6 个关节各 4 个参数的偏差。关节零位偏差 = 这台机器人装的关节在关节测试台上测得的零位残差
  + 装配时的零位偏差（示例 σ 0.01°）；连杆长度、偏距偏差（示例 σ 0.3 mm）、扭角偏差（示例 σ 0.05°）按出厂编号定（可复现）。
  标定前绝对定位误差约 0.8–1.5 mm，标定后约 0.1–0.15 mm（示例量级）。
- 测量：激光跟踪仪测工具点位置，噪声示例 σ 0.02 mm；另有几何模型以外的误差（关节柔度、齿隙，示例 σ 0.06 mm）——
  标定补不了它，所以标定后的误差降不到零，这是真实的样子。
- 辨识：残差对 24 个参数偏差求雅可比（数值差分），列归一化后用奇异值分解求最小范数解，迭代几次（高斯-牛顿 / LM）。
  相邻平行轴（2、3、4）沿轴向的偏距只辨识得出它们的和，这类“结构上分不开”的组合由奇异值分解自动放掉（秩 r）。
  条件数 = σ₁ / σ_r：位姿太少、太集中时变大，辨识出的参数被噪声放大。
纯计算，不联网、不读数据库；仿真车间和枢纽都用它，同一台机器人算出的结果一样。"""
from __future__ import annotations

import math
import zlib

import numpy as np

# 名义 DH（示例值）：a、α、d 单位 m、rad
NOMINAL = [
    {"a": 0.0, "alpha": math.pi / 2, "d": 0.150},
    {"a": -0.400, "alpha": 0.0, "d": 0.0},
    {"a": -0.360, "alpha": 0.0, "d": 0.0},
    {"a": 0.0, "alpha": math.pi / 2, "d": 0.120},
    {"a": 0.0, "alpha": -math.pi / 2, "d": 0.100},
    {"a": 0.0, "alpha": 0.0, "d": 0.090},
]
TOOL = np.array([0.050, 0.0, 0.100])          # 工具点在法兰坐标系里的位置（m）
JOINTS = ("J1", "J2", "J3", "J4", "J5", "J6")
JOINT_SIZE = ("L", "L", "M", "S", "S", "S")   # 装哪种关节模组（清单：大关节 J1、J2，中关节 J3，小关节 J4–J6）
PARAMS = ("dtheta", "dd", "da", "dalpha")      # 每个关节 4 个偏差，顺序固定
PARAM_NAME = {"dtheta": "零位 Δθ", "dd": "偏距 Δd", "da": "连杆长度 Δa", "dalpha": "扭角 Δα"}
NP = 6 * len(PARAMS)

# 误差与测量的量级（示例值）
SIG_ZERO_ASM = math.radians(0.01)
SIG_LEN = 0.30e-3
SIG_TWIST = math.radians(0.05)
SIG_TRACKER = 0.02e-3
SIG_UNMODELED = 0.06e-3
LIMIT_MM = 0.5                                 # 标定后绝对定位误差的上限（清单 cr_abs 的上限）

# 关节范围（度）：铺满工作空间；集中：在一个常用姿态附近 ±10°
RANGES = [(-170, 170), (-170, -10), (-150, 150), (-170, 170), (-170, 170), (-170, 170)]
HOME = (0, -90, 90, -90, -90, 0)
N_DEFAULT = 30
N_VERIFY = 20


def _seed(*parts):
    return zlib.crc32("|".join(str(x) for x in parts).encode())


def _link(theta, d, a, alpha):
    ct, st, ca, sa = math.cos(theta), math.sin(theta), math.cos(alpha), math.sin(alpha)
    return np.array([[ct, -st * ca, st * sa, a * ct],
                     [st, ct * ca, -ct * sa, a * st],
                     [0.0, sa, ca, d],
                     [0.0, 0.0, 0.0, 1.0]])


def fk(q, p=None):
    """工具点位置（m）。q：6 个关节角（rad）；p：24 个偏差（按 关节 × PARAMS 排），None = 名义"""
    p = np.zeros(NP) if p is None else np.asarray(p, dtype=float)
    T = np.eye(4)
    for i, n in enumerate(NOMINAL):
        dth, dd, da, dal = p[4 * i:4 * i + 4]
        T = T @ _link(q[i] + dth, n["d"] + dd, n["a"] + da, n["alpha"] + dal)
    return (T @ np.append(TOOL, 1.0))[:3]


def truth(serial, zero_arcsec=None):
    """一台机器人的真实偏差（24 个）。zero_arcsec：6 台关节在测试台上的零位残差（角秒），缺的按随机补"""
    rng = np.random.default_rng(_seed("truth", serial))
    p = np.zeros(NP)
    for i in range(6):
        z = (zero_arcsec or [None] * 6)[i] if zero_arcsec is not None and i < len(zero_arcsec) else None
        bench = math.radians(float(z) / 3600.0) if z is not None else rng.normal(0, math.radians(20 / 3600.0))
        p[4 * i + 0] = bench + rng.normal(0, SIG_ZERO_ASM)
        p[4 * i + 1] = float(np.clip(rng.normal(0, SIG_LEN), -2 * SIG_LEN, 2 * SIG_LEN))
        p[4 * i + 2] = float(np.clip(rng.normal(0, SIG_LEN), -2 * SIG_LEN, 2 * SIG_LEN))
        p[4 * i + 3] = float(np.clip(rng.normal(0, SIG_TWIST), -2 * SIG_TWIST, 2 * SIG_TWIST))
    return p


def poses(seed, n=N_DEFAULT, spread="full"):
    """n 个测量位姿（rad）。spread：full 铺满工作空间 / cluster 集中在常用姿态附近 ±10°"""
    rng = np.random.default_rng(_seed("poses", seed, n, spread))
    out = []
    for _ in range(int(n)):
        if spread == "cluster":
            q = [math.radians(h + rng.uniform(-10, 10)) for h in HOME]
        else:
            q = [math.radians(rng.uniform(lo, hi)) for lo, hi in RANGES]
        out.append(q)
    return np.array(out)


def measure(p_true, Q, seed):
    """激光跟踪仪测得的工具点位置：真实几何 + 几何以外的误差 + 测量噪声"""
    rng = np.random.default_rng(_seed("measure", seed, len(Q)))
    return np.array([fk(q, p_true) + rng.normal(0, SIG_UNMODELED, 3) + rng.normal(0, SIG_TRACKER, 3) for q in Q])


def jacobian(Q, p, h=1e-7):
    base = np.concatenate([fk(q, p) for q in Q])
    J = np.zeros((base.size, NP))
    for k in range(NP):
        dp = np.array(p, dtype=float)
        dp[k] += h
        J[:, k] = (np.concatenate([fk(q, dp) for q in Q]) - base) / h
    return J


_RANK = []


def structural_rank():
    """铺满工作空间、位姿很多时的秩：结构上分得开的参数组合有几个（与位姿怎么选无关）"""
    if not _RANK:
        J = jacobian(poses("rank", 120, "full"), np.zeros(NP))
        s = np.linalg.svd(J / np.linalg.norm(J, axis=0), compute_uv=False)
        _RANK.append(int(np.sum(s > s[0] * 1e-6)))
    return _RANK[0]


def identify(Q, M, iters=6):
    """由测量位姿 Q、测得位置 M 辨识 24 个偏差。返回 (p, 条件数, 秩)"""
    r_struct = structural_rank()
    p = np.zeros(NP)
    cond = None
    for _ in range(iters):
        res = (M - np.array([fk(q, p) for q in Q])).ravel()
        J = jacobian(Q, p)
        scale = np.linalg.norm(J, axis=0)
        scale[scale == 0] = 1.0
        U, s, Vt = np.linalg.svd(J / scale, full_matrices=False)
        r = min(r_struct, int(np.sum(s > s[0] * 1e-12)), len(res))
        cond = float(s[0] / s[r - 1])
        dp = Vt[:r].T @ ((U[:, :r].T @ res) / s[:r])
        p = p + dp / scale
        if np.max(np.abs(dp)) < 1e-12:
            break
    return p, cond, r_struct


def errors_mm(Q, M, p):
    """每个位姿的位置误差（mm）：测得位置与模型（参数 p）算出的位置之差"""
    return [float(np.linalg.norm(m - fk(q, p)) * 1000) for q, m in zip(Q, M)]


def table(p):
    """参数偏差表：每个关节 Δθ（°）、Δd（mm）、Δa（mm）、Δα（°）"""
    out = []
    for i, j in enumerate(JOINTS):
        dth, dd, da, dal = p[4 * i:4 * i + 4]
        out.append({"joint": j, "dtheta_deg": round(math.degrees(dth), 4), "dd_mm": round(dd * 1000, 3), "da_mm": round(da * 1000, 3),
                    "dalpha_deg": round(math.degrees(dal), 4)})
    return out


def case(serial, zero_arcsec=None, n=N_DEFAULT, spread="full", detail=False):
    """一台机器人的标定：n 个位姿测量 → 辨识 → 另取 20 个位姿验证（标定前用名义参数，标定后用辨识出的参数）"""
    p_true = truth(serial, zero_arcsec)
    Q = poses(serial, n, spread)
    M = measure(p_true, Q, (serial, "cal", n, spread))
    p_hat, cond, rank = identify(Q, M)
    V = poses((serial, "verify"), N_VERIFY, "full")
    MV = measure(p_true, V, (serial, "verify"))
    before = errors_mm(V, MV, None)
    after = errors_mm(V, MV, p_hat)
    out = {"serial": serial, "n": int(n), "spread": spread, "cond": round(cond, 1), "rank": rank, "params": NP,
           "before_mean_mm": round(float(np.mean(before)), 4), "before_max_mm": round(float(np.max(before)), 4),
           "after_mean_mm": round(float(np.mean(after)), 4), "after_max_mm": round(float(np.max(after)), 4),
           "pass": bool(np.mean(after) <= LIMIT_MM), "limit_mm": LIMIT_MM}
    if detail:
        out.update({
            "poses_deg": [[round(math.degrees(x), 2) for x in q] for q in Q],
            "points_mm": [[round(v * 1000, 2) for v in m] for m in M],
            "fit_before_mm": [round(x, 4) for x in errors_mm(Q, M, None)], "fit_after_mm": [round(x, 4) for x in errors_mm(Q, M, p_hat)],
            "verify_before_mm": [round(x, 4) for x in before], "verify_after_mm": [round(x, 4) for x in after],
            "identified": table(p_hat), "_truth": table(p_true)})
    return out
