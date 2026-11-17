"""Andrews 挤压机构（ADR-0097 D1 标准题）：平面 7 构件闭环机构，Test Set for IVP Solvers（Bari 大学，release 2.4）
第 II.13 题“Andrews' squeezing mechanism”（https://archimede.uniba.it/~testset/report/andrews.pdf）。

原题用 7 个相对角 q1…q7 写成指标 3 的 DAE；这里按原题的约束方程 g1…g6、质量矩阵、弹簧力把机构还原成 7 个刚体
（绝对坐标、转动副），在 t = 0 的相容初值 q0 处装配，用本模块的通用求解器算，和原题 t = 0.03 s 的参考解比较。
无重力；驱动力矩 mom 加在曲柄上；弹簧 F = −c0(L − l0)/L · (D − C)。

还原时各点（由约束方程读出）：
  O = (0, 0) 曲柄 K1 绕 O 转，F = rr(cos q1, sin q1)，质心距 O 为 ra
  K2 从 F 到 E：E = F − d(cos(q1+q2), sin(q1+q2))，质心 F − da(…)
  K3 绕 B 转：E = B + ss(sin q3, −cos q3)，弹簧点 D = B + (sd cos q3 + sc sin q3, sd sin q3 − sc cos q3)；质心距 B 为 √(sa²+sb²)
  K5 绕 A 转：G = A + zt(cos q5, sin q5)；K4 从 G 到 E：E = G + e(−sin(q4+q5), cos(q4+q5))，质心 G − (e−ea)(−sin, cos)
  K7 绕 A 转：H = A + u(sin q7, −cos q7)；K6 从 H 到 E：E = H + zf(cos(q6+q7), sin(q6+q7))，质心 H + (zf−fa)(cos, sin)
  K5、K7 的质心只影响它们对 A 的转动惯量（m(ta²+tb²)、m(ua²+ub²)），放在 A 正右方。
平面运动：构件出平面的两个惯量取与 izz 相同（不影响平面运动）。
"""

import math

P = {"m1": 0.04325, "m2": 0.00365, "m3": 0.02373, "m4": 0.00706, "m5": 0.07050, "m6": 0.00706, "m7": 0.05498, "I1":
     2.194e-6, "I2": 4.410e-7, "I3": 5.255e-6, "I4": 5.667e-7, "I5": 1.169e-5, "I6": 5.667e-7, "I7": 1.912e-5, "xa":
     -0.06934, "ya": -0.00227, "xb": -0.03635, "yb": 0.03273, "xc": 0.014, "yc": 0.072, "c0": 4530, "l0": 0.07785,
     "mom": 0.033, "d": 0.028, "da": 0.0115, "e": 0.02, "ea": 0.01421, "rr": 0.007, "ra": 0.00092, "ss": 0.035, "sa":
     0.01874, "sb": 0.01043, "sc": 0.018, "sd": 0.02, "ta": 0.02308, "tb": 0.00916, "u": 0.04, "ua": 0.01228, "ub":
     0.00449, "zf": 0.02, "zt": 0.04, "fa": 0.01421}
Q0 = [-0.0617138900142764496358948458001, 0.0, 0.455279819163070380255912382449, 0.222668390165885884674473185609,
      0.487364979543842550225598953530, -0.222668390165885884674473185609, 1.23054744454982119249735015568]
REF_T = 0.03
REF = [0.1581077119629904e2, -0.1575637105984298e2, 0.4082224013073101e-1, -0.5347301163226948, 0.5244099658805304,
       0.5347301163226948, 0.1048080741042263e1]


def model(steps=300, rtol=1e-10, atol=1e-12, integrator="DOP853"):
    p = P
    q1, q2, q3, q4, q5, q6, q7 = Q0
    c, s = math.cos, math.sin
    O = (0.0, 0.0)
    A = (p["xa"], p["ya"])
    B = (p["xb"], p["yb"])
    C = (p["xc"], p["yc"])
    F = (p["rr"] * c(q1), p["rr"] * s(q1))
    a12 = q1 + q2
    E = (F[0] - p["d"] * c(a12), F[1] - p["d"] * s(a12))
    cm1 = (p["ra"] * c(q1), p["ra"] * s(q1))
    cm2 = (F[0] - p["da"] * c(a12), F[1] - p["da"] * s(a12))
    D = (B[0] + p["sd"] * c(q3) + p["sc"] * s(q3), B[1] + p["sd"] * s(q3) - p["sc"] * c(q3))
    r3 = math.hypot(p["sa"], p["sb"])
    cm3 = (B[0] + r3, B[1])
    G = (A[0] + p["zt"] * c(q5), A[1] + p["zt"] * s(q5))
    b45 = q4 + q5
    cm4 = (G[0] + (p["e"] - p["ea"]) * s(b45), G[1] - (p["e"] - p["ea"]) * c(b45))
    cm5 = (A[0] + math.hypot(p["ta"], p["tb"]), A[1])
    H = (A[0] + p["u"] * s(q7), A[1] - p["u"] * c(q7))
    b67 = q6 + q7
    cm6 = (H[0] + (p["zf"] - p["fa"]) * c(b67), H[1] + (p["zf"] - p["fa"]) * s(b67))
    cm7 = (A[0] + math.hypot(p["ua"], p["ub"]), A[1])

    def mm(pt):
        return [pt[0] * 1000, pt[1] * 1000, 0.0]

    def body(n, cm):
        Iz = p[f"I{n}"]
        return {"id": f"K{n}", "mass_kg": p[f"m{n}"], "cm_mm": mm(cm), "inertia_kg_m2": {"ixx": Iz, "iyy": Iz, "izz": Iz}}

    z = [0, 0, 1]

    def rev(jid, bi, bj, pt):
        return {"id": jid, "type": "revolute", "body_i": bi, "body_j": bj, "point_mm": mm(pt), "axis": z}

    return {
        "format": "mbd-model/1", "name": "Andrews 挤压机构",
        "bodies": [body(n, cm) for n, cm in zip(range(1, 8), (cm1, cm2, cm3, cm4, cm5, cm6, cm7), strict=True)],
        "joints": [rev("O", "ground", "K1", O), rev("F", "K1", "K2", F), rev("B", "ground", "K3", B),
                   rev("E3", "K2", "K3", E), rev("A5", "ground", "K5", A), rev("G", "K5", "K4", G),
                   rev("E4", "K2", "K4", E), rev("A7", "ground", "K7", A), rev("H", "K7", "K6", H),
                   rev("E6", "K2", "K6", E)],
        "forces": [{"id": "mom", "type": "torque", "body": "K1", "tz_n_m": p["mom"]},
                   {"id": "spring", "type": "spring_damper", "body_i": "ground", "point_i_mm": mm(C), "body_j": "K3",
                    "point_j_mm": mm(D), "stiffness_n_per_mm": p["c0"] / 1000, "free_length_mm": p["l0"] * 1000}],
        "analysis": {"type": "dynamic", "end_time_s": REF_T, "output_steps": steps, "integrator": integrator,
                     "rtol": rtol, "atol": atol},
        "source": "Test Set for IVP Solvers II.13（见本文件说明）",
    }


def angles(q_series):
    """各构件绕 z 的转角（展开），换回原题的 q1…q7"""
    import numpy as np

    th = []
    for k in range(7):
        a = np.unwrap([2 * math.atan2(q[7 * k + 6], q[7 * k + 3]) for q in q_series])
        th.append(a)
    t1, t2, t3, t4, t5, t6, t7 = [a[-1] for a in th]
    a1, a12, a3, a45, a5, a67, a7 = (Q0[0] + t1, Q0[0] + Q0[1] + t2, Q0[2] + t3, Q0[3] + Q0[4] + t4, Q0[4] + t5,
                                     Q0[5] + Q0[6] + t6, Q0[6] + t7)
    return [a1, a12 - a1, a3, a45 - a5, a5, a67 - a7, a7]
