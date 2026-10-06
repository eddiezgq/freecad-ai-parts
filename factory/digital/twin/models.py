# -*- coding: utf-8 -*-
"""数字孪生的物理模型（第 15 轮 T3）：全部可以手算核对，数据来源写在常量旁边。

① 输出轴疲劳：键槽处热点应力 = 每 N·m 的应力 × 转矩（第 11 轮有限元：SH-301 示范题 350 N·m 时 259.8 MPa，中网格）；
   转矩循环（雨流计数结果：幅值、平均值、次数）→ Goodman 修正 → S-N 曲线（材料库 45 钢调质，磨削 β 0.92、尺寸 ε 0.85，
   Haibach）→ Miner 累积损伤。与“仿真与分析”页的疲劳计算同一套公式（cae/fatigue.py）。
② 轴承：ISO 281 基本额定寿命 L10 = (C/P)³ × 10⁶ 转（球轴承）。直齿轮没有轴向力，P = 径向力 Fr。
   变工况：损伤 = Σ 转数ᵢ / L10ᵢ（与当量载荷 P_m = (Σ Pᵢ³·nᵢ·tᵢ / Σ nᵢ·tᵢ)^(1/3) 等价）。
③ 油温：减速器热平衡（濮良贵《机械设计》）t_油 = t₀ + P_in(1 − η)/(K_s·A)，与第 14 轮“WQR-105 简化箱体”同一组数。
④ 润滑油：按运行小时累计，油温高于 70 ℃ 时每高 10 ℃ 按 2 倍计（温度每升 10 ℃ 油的氧化速度约加倍——Arrhenius 经验规则），
   磨合后首次换油 500 h，之后每 5000 h（教学取值，实际以减速器说明书为准）。
⑤ 振动：ISO 10816-1 小型机器（≤ 15 kW，第 I 类）振动烈度分区：A/B 0.71、B/C 1.8、C/D 4.5 mm/s。
"""
import math

# ---------------------------------------------------------------- WQR-105 传动链（工厂主数据 factory/data.py）
RATED_T_NM = 350.0                    # 额定输出转矩
N_IN_RPM = 1450.0                     # 电机转速
GEARS = {"z1": 24, "m1": 2.0, "z2": 72, "z3": 20, "m2": 3.0, "z4": 70}
RATIO = (72 / 24) * (70 / 20)         # 10.5
ETA_GEAR, ETA_BRG = 0.97, 0.99        # 闭式圆柱齿轮 8 级 / 级，滚动轴承 / 对（濮良贵《机械设计》常用机械传动效率概略值）
ETA = ETA_GEAR ** 2 * ETA_BRG ** 3    # 0.913
ALPHA = math.radians(20)              # 压力角

# 热平衡：第 14 轮 WQR-105 简化箱体（外形 410×150×300，不计底面）、通风良好
K_S = 17.45                           # W/(m²·℃)
AREA_M2 = (2 * 410 * 300 + 2 * 150 * 300 + 410 * 150) * 1e-6   # 0.3975 m²

# 输出轴疲劳：第 11 轮有限元 + 材料库 45 钢调质
STRESS_REF_MPA, STRESS_REF_NM, D_GEAR_REF = 259.8, 350.0, 40.0   # 键槽处热点应力（中网格）；齿轮位 Ø40 时
SHAFT_MAT = {"sigma_1": 275.0, "N_D": 1.0e7, "k": 9.0, "ultimate_mpa": 640.0}
BETA_SURFACE, SIZE_FACTOR = 0.92, 0.85

# 轴承：SKF 深沟球轴承样本的基本额定动载荷 C（6205 14.8 kN、6206 20.3 kN、6207 27.0 kN）
# 受力布置（简化，按装配图取整）：三根轴都是两支点简支；输出轴的支点、齿轮位置取网页设计台 SH-301 现行尺寸
#   输入轴：小齿轮 z24 离 A 端 35 mm，跨距 120 mm；
#   中间轴：大齿轮 z72 离 A 端 35 mm、小齿轮 z20 离 A 端 85 mm，跨距 120 mm（三根轴在同一平面：圆周力同向、径向力反向）；
#   输出轴：轴承 A 在第 2 段中点（46 mm）、齿轮在第 3 段中点（82 mm）、轴承 B 在第 4 段中点（124.5 mm）。
BEARINGS = [
    # (编号, 名称, 型号, C 牛, 所在轴)
    ("in-A", "输入轴轴承 A（靠小齿轮）", "6205-2RS", 14800.0, "in"),
    ("in-B", "输入轴轴承 B", "6205-2RS", 14800.0, "in"),
    ("mid-A", "中间轴轴承 A（靠大齿轮）", "6206-2RS", 20300.0, "mid"),
    ("mid-B", "中间轴轴承 B（靠小齿轮）", "6206-2RS", 20300.0, "mid"),
    ("out-A", "输出轴轴承 A（轴伸端）", "6207-2RS", 27000.0, "out"),
    ("out-B", "输出轴轴承 B", "6207-2RS", 27000.0, "out"),
]
BRG = {b[0]: b for b in BEARINGS}

# 润滑油（CKC 220 矿物油）
OIL_FIRST_H, OIL_INTERVAL_H, OIL_REF_C = 500.0, 5000.0, 70.0
# 振动分区
VIB_ZONES = [(0.71, "A"), (1.8, "B"), (4.5, "C"), (math.inf, "D")]


def speeds(n_in=N_IN_RPM):
    """三根轴的转速 r/min"""
    n_mid = n_in * 24 / 72
    return {"in": n_in, "mid": n_mid, "out": n_mid * 20 / 70}


def torques(t_out):
    """由输出转矩反推各轴转矩（N·m），计入每级齿轮和轴承效率"""
    t_mid = t_out / (70 / 20) / (ETA_GEAR * ETA_BRG)
    t_in = t_mid / (72 / 24) / (ETA_GEAR * ETA_BRG)
    return {"in": t_in, "mid": t_mid, "out": t_out}


def _support(F, a, L):
    """简支梁：距 A 端 a 处受力 F，返回 (R_A, R_B)"""
    return F * (L - a) / L, F * a / L


def bearing_loads(t_out, design=None):
    """输出转矩 t_out 时 6 个轴承的径向力（N）。直齿轮：Ft = 2T/d，Fr = Ft·tanα，合力 F = Ft / cosα"""
    T = torques(t_out)
    d1, d2 = GEARS["m1"] * GEARS["z1"], GEARS["m1"] * GEARS["z2"]          # 48、144 mm
    d3, d4 = GEARS["m2"] * GEARS["z3"], GEARS["m2"] * GEARS["z4"]          # 60、210 mm
    Ft12, Ft34 = 2 * T["in"] * 1000 / d1, 2 * T["mid"] * 1000 / d3          # 圆周力
    Fr12, Fr34 = Ft12 * math.tan(ALPHA), Ft34 * math.tan(ALPHA)            # 径向力
    F12, F34 = math.hypot(Ft12, Fr12), math.hypot(Ft34, Fr34)
    out = {}
    out["in-A"], out["in-B"] = _support(F12, 35.0, 120.0)
    # 中间轴（三轴在同一平面）：两处啮合点在轴的两侧，圆周力同向相加，径向力反向相减
    ax1, bx1 = _support(Fr12, 35.0, 120.0)
    ay1, by1 = _support(Ft12, 35.0, 120.0)
    ax2, bx2 = _support(-Fr34, 85.0, 120.0)
    ay2, by2 = _support(Ft34, 85.0, 120.0)
    out["mid-A"], out["mid-B"] = math.hypot(ax1 + ax2, ay1 + ay2), math.hypot(bx1 + bx2, by1 + by2)
    seg = (design or {}).get("segments") or [(30, 40), (35, 12), (40, 60), (35, 25), (30, 30)]
    x = [0.0]
    for _, l in seg:
        x.append(x[-1] + l)
    xa, xg, xb = (x[1] + x[2]) / 2, (x[2] + x[3]) / 2, (x[3] + x[4]) / 2
    out["out-A"], out["out-B"] = _support(F34 * 1.0, xg - xa, xb - xa)
    return out


def l10_hours(C, P, n_rpm):
    """ISO 281 基本额定寿命（小时）"""
    if P <= 0 or n_rpm <= 0:
        return math.inf
    return (C / P) ** 3 * 1e6 / (60 * n_rpm)


def bearing_damage(load_hist, n_in=N_IN_RPM, design=None):
    """一段时间的轴承损伤：load_hist = [[输出转矩 N·m, 运行小时], ...]。返回 {轴承: 损伤（L10 的分数）}"""
    n = speeds(n_in)
    D = {b[0]: 0.0 for b in BEARINGS}
    for t, h in load_hist:
        if h <= 0 or t <= 0:
            continue
        P = bearing_loads(t, design)
        for bid, _, _, C, shaft in BEARINGS:
            D[bid] += h / l10_hours(C, P[bid], n[shaft])
    return D


def equivalent_load(load_hist, bid, n_in=N_IN_RPM, design=None):
    """变工况当量载荷 P_m = (Σ Pᵢ³·tᵢ / Σ tᵢ)^(1/3)（同一转速），手算核对用"""
    num = den = 0.0
    for t, h in load_hist:
        if h > 0 and t > 0:
            num += bearing_loads(t, design)[bid] ** 3 * h
            den += h
    return (num / den) ** (1 / 3) if den else 0.0


# ---------------------------------------------------------------- 输出轴疲劳
def stress_per_nm(design=None):
    """键槽处热点应力（MPa / N·m）。齿轮位直径改了按扭转应力 ∝ 1/d³ 换算"""
    d = D_GEAR_REF
    seg = (design or {}).get("segments")
    if seg:
        d = float(seg[2][0])
    return STRESS_REF_MPA / STRESS_REF_NM * (D_GEAR_REF / d) ** 3


def sn_cycles(sa_eq, mat=SHAFT_MAT, haibach=True):
    """修正后的 S-N 曲线：S_D = σ₋₁·β·ε；高于 S_D 斜率 k，低于 S_D 按 Haibach 斜率 2k − 1"""
    SD = mat["sigma_1"] * BETA_SURFACE * SIZE_FACTOR
    if sa_eq <= 0:
        return math.inf
    if sa_eq >= SD:
        return mat["N_D"] * (SD / sa_eq) ** mat["k"]
    if not haibach:
        return math.inf
    return mat["N_D"] * (SD / sa_eq) ** (2 * mat["k"] - 1)


def shaft_damage(cycles, design=None, mat=SHAFT_MAT, haibach=True):
    """cycles = [[转矩幅值 N·m, 转矩平均值 N·m, 次数], ...] → Miner 损伤"""
    s = stress_per_nm(design)
    D = 0.0
    for a, m, n in cycles:
        if a <= 0 or n <= 0:
            continue
        sa, sm = s * a, s * abs(m)
        sa_eq = sa / (1 - min(sm / mat["ultimate_mpa"], 0.999))
        N = sn_cycles(sa_eq, mat, haibach)
        if math.isfinite(N):
            D += n / N
    return D


# ---------------------------------------------------------------- 热平衡、润滑油、振动
def heat_w(t_out_nm, n_in=N_IN_RPM):
    """箱体内发热 Φ = P_in(1 − η)，P_out = T·ω_out"""
    p_out = t_out_nm * speeds(n_in)["out"] * 2 * math.pi / 60
    return p_out / ETA * (1 - ETA)


def oil_temp_model(t_out_nm, t_amb_c, n_in=N_IN_RPM, k_s=K_S, area=AREA_M2):
    """稳态油温 ℃"""
    return t_amb_c + heat_w(t_out_nm, n_in) / (k_s * area)


def oil_equiv_hours(run_h, oil_t_c):
    """润滑油的“当量运行小时”：油温高于 70 ℃ 每高 10 ℃ 按 2 倍计"""
    return run_h * (2 ** max(0.0, (oil_t_c - OIL_REF_C) / 10))


def vib_zone(v):
    for lim, z in VIB_ZONES:
        if v < lim:
            return z
    return "D"
