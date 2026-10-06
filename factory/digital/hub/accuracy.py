# -*- coding: utf-8 -*-
"""机械加工精度（第 13 轮 N4/N6；《机械制造技术》第 54 章）：原始误差的计算、误差形态的判别与精度预算。

书和数字工厂共用：
- 误差敏感方向、原理误差（刀尖圆弧未补偿、直线插补弦差）、调整误差；
- 机床误差：主轴回转误差（车削与镗削的区别）、导轨误差、尾座偏移与锥度、传动链误差；
- 工艺系统受力变形：两顶尖车削的刚度与形状误差（鼓形、鞍形、锥度）、误差复映、生产法测刚度；
- 热变形：机床热伸长的指数模型与拟合、工件热胀、测量温度误差；
- 刀具尺寸磨损与补偿间隔、残余应力引起的弯曲；
- 误差形态的判别（diagnose）：沿轴向的形状、圆度的谐波、逐件序列（漂移、锯齿、预热、跳变、分散变大）；
- 精度预算（budget）：系统误差直接相加，随机误差平方和开方。

单位：长度 mm，力 N，刚度 N/mm，应力 MPa，温度 °C。
"""
from __future__ import annotations

import math
import statistics as st

E_STEEL = 210000.0
ALPHA_STEEL = 11.5e-6


# ---------------------------------------------------------------- 误差敏感方向
def diameter_error(R: float, dy: float = 0.0, dz: float = 0.0) -> float:
    """刀尖相对工件轴线在法向（误差敏感方向）偏移 dy、在切向偏移 dz 时，车出的直径变化（精确式）。
    dy > 0 表示刀尖离开轴线。Δd = 2(√((R + dy)² + dz²) − R) ≈ 2dy + dz²/R。"""
    return 2 * (math.hypot(R + dy, dz) - R)


# ---------------------------------------------------------------- 原理误差
def nose_radius_error(r: float, phi_deg: float) -> float:
    """车刀按假想刀尖对刀（X、Z 两个方向都对到刀尖圆弧的切点）、编程时不用刀尖圆弧半径补偿，
    车一条与轴线成 φ 角的直线（倒角、锥面）时，在该直线法向多留下的材料厚度 r(cos φ + sin φ − 1)。
    φ = 0（外圆）、90°（端面）时为零，45° 时最大，为 (√2 − 1)r。"""
    p = math.radians(phi_deg)
    return r * (math.cos(p) + math.sin(p) - 1)


def chord_error(R: float, s: float) -> float:
    """用长度为 s 的直线段逼近半径为 R 的圆弧时的弦高误差 R − √(R² − s²/4) ≈ s²/(8R)。"""
    return R - math.sqrt(R * R - s * s / 4)


def chord_length(R: float, tol: float) -> float:
    """弦高误差不超过 tol 时允许的最大直线段长度。"""
    return 2 * math.sqrt(R * R - (R - tol) ** 2)


# ---------------------------------------------------------------- 调整误差
def adjustment_error(sigma: float, n_trial: int = 1, meas_range: float = 0.0, step: float = 0.0) -> dict:
    """调整法按试切件的平均值调刀时，调整后的尺寸中心偏离目标的范围（±3σ/√n、测量误差范围、补偿的最小步距，平方和开方）。
    sigma：机床加工一件的随机误差标准差；meas_range：测量误差的范围（如 ±0.001 记 0.002）；step：刀补的最小增量。
    返回各项与合计（都是“范围”，即上下极限之差）。"""
    a = 6 * sigma / math.sqrt(n_trial)
    total = math.sqrt(a * a + meas_range ** 2 + step ** 2)
    return {"trial": a, "meas": meas_range, "step": step, "total": total}


# ---------------------------------------------------------------- 机床误差
def _harm(h, ang):
    return sum(a * math.cos(k * ang - math.radians(ph)) for k, a, ph in h)


def spindle_roundness(journal=(), hole=(), mode="turning", m=360) -> dict:
    """滑动轴承主轴的回转误差对工件圆度的影响（简化模型：切削力方向上，主轴颈在接触点的半径误差 j 与轴承孔在接触点的半径误差 h
    使主轴中心沿力的方向移动）。journal、hole：半径误差的谐波 [(阶次 k, 幅值, 相位°)]。
    车削：力的方向固定，主轴颈随主轴转动，接触点在轴颈上逐点变化，在轴承孔上固定——工件的圆度误差反映轴颈的形状；
    镗削：力随镗刀转动，接触点在轴颈上固定，在轴承孔上逐点变化——孔的圆度误差反映轴承孔的形状。
    返回工件（孔）的半径误差 r(ψ) 与圆度误差（去掉一阶分量即偏心后的最大 − 最小）。"""
    th = [2 * math.pi * i / m for i in range(m)]
    r = []
    for t in th:
        if mode == "turning":
            # 刀具在空间 0°，切削力把主轴推向 180° 一侧：轴承孔的接触点固定在 180°；轴颈随主轴转过 t，接触点在轴颈上的角度为 180° − t。
            # 被车削的点在工件（与轴颈一起转）上的角度为 −t
            r.append(-_harm(journal, math.pi - t) + _harm(hole, math.pi))
        else:
            # 镗刀在空间 t 处；轴颈接触点固定，轴承孔接触点在 t + π
            r.append(-_harm(journal, math.pi) + _harm(hole, t + math.pi))
    # 去掉一阶分量（偏心），得到圆度误差
    a1 = 2 / m * sum(v * math.cos(t) for v, t in zip(r, th))
    b1 = 2 / m * sum(v * math.sin(t) for v, t in zip(r, th))
    rr = [v - a1 * math.cos(t) - b1 * math.sin(t) for v, t in zip(r, th)]
    # 工件转角 ψ = −t（车削）或 t（镗削）
    psi = [(-t) % (2 * math.pi) if mode == "turning" else t for t in th]
    return {"psi": psi, "r": rr, "roundness": max(rr) - min(rr)}


def guide_errors(R: float, dy_h: float = 0.0, dz_v: float = 0.0, twist: float = 0.0, H: float = 0.0, B: float = 1.0) -> dict:
    """车床导轨误差引起的直径误差：水平面直线度 dy_h（误差敏感方向，Δd ≈ 2dy）、垂直面直线度 dz_v（非敏感方向，Δd ≈ dz²/R）、
    前后导轨的扭曲（平行度）twist：在宽度 B 上一条导轨比另一条高 twist，刀架倾斜，中心高 H 处的刀尖水平移动 H·twist/B。"""
    dy_t = H * twist / B
    return {"horizontal": 2 * dy_h, "vertical": diameter_error(R, 0, dz_v), "twist": 2 * dy_t, "twist_dy": dy_t}


def taper_from_offset(e: float, L: float, z1: float, z2: float) -> float:
    """两顶尖装夹（磨削、车削），尾座端的回转中心相对导轨（工作台运动方向）在误差敏感方向偏移 e（头架端为零）：
    车（磨）出的直径沿轴向线性变化，z2 处比 z1 处大 2e(z2 − z1)/L。e > 0 表示尾座顶尖离开砂轮（刀具）。"""
    return 2 * e * (z2 - z1) / L


def chain_error(elements) -> dict:
    """传动链误差：elements = [(名称, 该元件的转角误差或位移误差, 该元件到末端的传动比)]。
    末端误差 = Σ 误差·传动比（极值），以及平方和开方（各元件误差相位随机时）。"""
    terms = [(n, e * i) for n, e, i in elements]
    return {"terms": terms, "extreme": sum(abs(v) for _, v in terms), "rss": math.sqrt(sum(v * v for _, v in terms))}


# ---------------------------------------------------------------- 工艺系统的受力变形
def kienzle_turning(ap: float, f: float, kc11: float = 2220.0, mc: float = 0.14, kr_deg: float = 93.0, ratio_p: float = 0.4) -> dict:
    """车削的主切削力 Fc = kc1.1·b·h^(1−mc)（b = ap/sin κr，h = f·sin κr），背向力 Fp ≈ ratio_p·Fc（按刀具和用量估计，以实测为准）。
    返回 Fc、Fp 和误差复映要用的 C = Fp/ap（N/mm，背向力随切深的变化率）。"""
    s = math.sin(math.radians(kr_deg))
    b, h = ap / s, f * s
    Fc = kc11 * b * h ** (1 - mc)
    Fp = ratio_p * Fc
    return {"Fc": Fc, "Fp": Fp, "C": Fp / ap}


def compliance_between_centers(x: float, L: float, d: float, k_head: float, k_tail: float, k_tool: float,
                               E: float = E_STEEL, rest: bool = False) -> dict:
    """两顶尖装夹车（磨）削，刀具在距头架 x 处，单位背向力引起的刀具–工件相对位移（mm/N），各部分分开给出：
    头架 ((L − x)/L)²/k_head，尾座 (x/L)²/k_tail，刀架 1/k_tool，工件（简支梁）x²(L − x)²/(3EIL)。
    rest=True 表示用跟刀架（支承随刀具移动，近似认为工件本身不再弯曲）。"""
    I = math.pi * d ** 4 / 64
    head = ((L - x) / L) ** 2 / k_head
    tail = (x / L) ** 2 / k_tail
    tool = 1 / k_tool
    work = 0.0 if rest else x * x * (L - x) ** 2 / (3 * E * I * L)
    return {"head": head, "tail": tail, "tool": tool, "work": work, "total": head + tail + tool + work}


def profile_between_centers(Fp: float, L: float, d: float, k_head: float, k_tail: float, k_tool: float,
                            E: float = E_STEEL, rest: bool = False, n: int = 41) -> dict:
    """沿轴向各点的让刀量 y(x) = Fp·柔度，车出的直径比调刀尺寸大 2y。返回位置、直径误差、形状判别（shape_along）。"""
    xs = [L * i / (n - 1) for i in range(n)]
    dd = [2 * Fp * compliance_between_centers(x, L, d, k_head, k_tail, k_tool, E, rest)["total"] for x in xs]
    return {"x": xs, "dd": dd, **shape_along(xs, dd)}


def system_stiffness(*k) -> float:
    """串联的各部分刚度合成：1/k = Σ 1/kᵢ。"""
    return 1 / sum(1 / v for v in k)


def reflection(C: float, k: float, passes: int = 1) -> float:
    """误差复映系数 ε = C/k（C：背向力随切深的变化率，k：工艺系统刚度）；走刀 n 次时 ε 连乘。"""
    return (C / k) ** passes


def passes_needed(blank_err: float, allowed: float, eps_each) -> int:
    """毛坯误差 blank_err 要经几次走刀才降到 allowed 以下；eps_each 为每次走刀的复映系数（一个数或一列）。"""
    eps = list(eps_each) if hasattr(eps_each, "__iter__") else None
    e, n = blank_err, 0
    while e > allowed and n < 20:
        e *= eps[n] if eps and n < len(eps) else (eps[-1] if eps else eps_each)
        n += 1
    return n


def stiffness_from_steps(C: float, d_ap: float, d_work: float) -> float:
    """生产法（误差复映法）测刚度：毛坯上做出切深差 d_ap 的台阶，一次走刀后测出工件上的台阶差 d_work（半径），
    k = C·d_ap/d_work。"""
    return C * d_ap / d_work


# ---------------------------------------------------------------- 热变形
def warmup(delta_inf: float, tau: float, t: float) -> float:
    """机床热变形随时间的变化（一阶系统）：δ(t) = δ∞(1 − e^(−t/τ))。"""
    return delta_inf * (1 - math.exp(-t / tau))


def fit_warmup(t, y) -> dict:
    """由逐件（或逐时）测量值拟合 y = y0 + δ∞(1 − e^(−t/τ))：对 τ 网格搜索，每个 τ 下线性最小二乘求 y0、δ∞。"""
    t, y = list(t), list(y)
    best = None
    span = max(t) - min(t) or 1.0
    for i in range(1, 400):
        tau = span * i / 200
        g = [1 - math.exp(-v / tau) for v in t]
        gm, ym = st.fmean(g), st.fmean(y)
        sgg = sum((a - gm) ** 2 for a in g)
        if sgg < 1e-15:
            continue
        dinf = sum((a - gm) * (b - ym) for a, b in zip(g, y)) / sgg
        y0 = ym - dinf * gm
        sse = sum((b - y0 - dinf * a) ** 2 for a, b in zip(g, y))
        if best is None or sse < best["sse"]:
            best = {"tau": tau, "delta_inf": dinf, "y0": y0, "sse": sse}
    return best


def thermal_size(d: float, dT: float, alpha: float = ALPHA_STEEL) -> float:
    """工件温度比测量基准温度高 dT 时直径（长度）的胀大量 d·α·ΔT。"""
    return d * alpha * dT


def measure_temp_error(d: float, T_part: float, T_gauge: float, alpha_part: float = ALPHA_STEEL,
                       alpha_gauge: float = ALPHA_STEEL, T_ref: float = 20.0) -> float:
    """测量温度误差：读数比 20 °C 时的真实尺寸大 d[α_件(T_件 − 20) − α_量(T_量 − 20)]。"""
    return d * (alpha_part * (T_part - T_ref) - alpha_gauge * (T_gauge - T_ref))


def abbe_error(offset: float, tilt: float) -> float:
    """阿贝误差：被测线与量具的刻线不在一条直线上，偏开 offset，测量时量爪相对倾斜 tilt（rad），误差 ≈ offset·tilt。"""
    return offset * math.tan(tilt)


# ---------------------------------------------------------------- 刀具磨损
def cutting_length_m(d: float, length: float, f: float) -> float:
    """车一段长 length、直径 d 的外圆，切削路程（m）= π·d·length/f/1000。"""
    return math.pi * d * length / f / 1000


def radial_wear(length_m: float, K0_um_per_km: float, NB0_um: float = 0.0) -> float:
    """刀具的尺寸磨损（径向，mm）：初期磨损 NB0 加正常磨损 K0（μm/1000 m）× 切削路程。"""
    return (NB0_um + K0_um_per_km * length_m / 1000) / 1000


def compensation_interval(T: float, sigma: float, drift: float, k: float = 3.0, other: float = 0.0) -> dict:
    """尺寸随件数线性漂移（每件 drift，mm/件），每隔 n 件补偿（换刀、修整、调刀补）一次，补偿后回到下限一侧。
    尺寸中心在 n 件内移动 n·drift；要让每件都满足 ±kσ 在公差内：n·drift + 2kσ + other ≤ T。
    返回允许的最大间隔 n 和此时补偿后的起始中心（距下限 kσ + other/2）。"""
    room = T - 2 * k * sigma - other
    n = math.floor(room / drift) if drift > 0 and room > 0 else 0
    return {"n_max": n, "room": room, "start_above_lsl": k * sigma + other / 2}


# ---------------------------------------------------------------- 残余应力
def bow_from_moment(M: float, L: float, x1: float, x2: float, E: float, I: float, n: int = 2001) -> dict:
    """简支（两顶尖）的轴，在 [x1, x2] 段内作用均匀的弯矩 M（如去掉一侧有残余应力的材料后应力重新平衡产生的弯矩），
    求挠度曲线的最大值。曲率 κ = M/(EI) 只在该段内；两端挠度为零，积分两次。返回最大挠度与它的位置、径向圆跳动（≈ 2 倍最大挠度）。"""
    xs = [L * i / (n - 1) for i in range(n)]
    kappa = [M / (E * I) if x1 <= x <= x2 else 0.0 for x in xs]
    h = xs[1] - xs[0]
    th, y = [0.0], [0.0]
    for i in range(1, n):
        th.append(th[-1] + 0.5 * (kappa[i] + kappa[i - 1]) * h)
        y.append(y[-1] + 0.5 * (th[i] + th[i - 1]) * h)
    corr = [y[i] - y[-1] * xs[i] / L for i in range(n)]       # 满足两端挠度为零
    j = max(range(n), key=lambda i: abs(corr[i]))
    return {"max": abs(corr[j]), "x": xs[j], "runout": 2 * abs(corr[j]), "x_list": xs, "y": corr}


def layer_moment(sigma: float, area: float, e: float) -> float:
    """去掉一块承受残余应力 sigma（MPa）、面积 area（mm²）、形心离中性轴 e（mm）的材料，相当于在剩余截面上加了弯矩 σ·A·e。"""
    return sigma * area * e


# ---------------------------------------------------------------- 误差形态的判别
SHAPES = {
    "taper": {"name": "锥度", "causes": ["两顶尖连线与导轨（工作台运动方向）不平行：尾座偏移、工作台转角没调好",
                                       "导轨在水平面内与主轴轴线不平行", "长走刀中刀具磨损（车削）", "头架、尾座刚度相差较大"]},
    "drum": {"name": "鼓形（中间大、两头小）", "causes": ["工件刚度低（细长轴）：中间让刀多", "切削中工件热伸长被两顶尖顶住而弯曲"]},
    "saddle": {"name": "鞍形（中间小、两头大）", "causes": ["头架、尾座（顶尖）刚度低于工件：两头让刀多",
                                                         "导轨在垂直面或水平面内中凸（磨损后中间低常表现为相反形状）"]},
    "ellipse": {"name": "椭圆（二阶）", "causes": ["车削时主轴颈不圆（滑动轴承）", "中心孔不圆或两中心孔不同轴", "两点或对置夹紧变形",
                                                 "镗削时轴承孔不圆"]},
    "lobe3": {"name": "三棱形（三阶）", "causes": ["三爪卡盘夹紧薄壁件后松开回弹", "无心磨削的棱圆", "三点支承的夹具夹紧变形"]},
    "lobes": {"name": "多棱形（高阶）", "causes": ["振动（颤振）留下的波纹", "砂轮不平衡或修整不良", "主轴轴承滚动体误差"]},
    "drift_linear": {"name": "尺寸逐件线性漂移", "causes": ["刀具（砂轮）尺寸磨损", "冷却液温度逐渐升高"]},
    "drift_saw": {"name": "锯齿形（漂移后回落）", "causes": ["刀具磨损 + 定期换刀、修整砂轮或补偿：回落点就是补偿时刻"]},
    "warmup": {"name": "开机后逐件变化、渐趋稳定", "causes": ["机床未达到热平衡（主轴、砂轮架热伸长）", "刀具热伸长"]},
    "jump": {"name": "某一件起整体跳变", "causes": ["换刀、修整、调刀补后的调整误差", "换了一批毛坯（硬度、余量不同）", "换了操作工或量具",
                                               "夹具、定位元件松动或更换"]},
    "shift": {"name": "整体偏移（与正常时比）", "causes": ["定位元件、夹具磨损或松动", "调整误差（对刀、刀补）", "换了一批毛坯或材料",
                                                    "量具零位变了"]},
    "spread": {"name": "分散变大", "causes": ["中心孔质量差、顶尖磨损（回转中心跳动）", "机床零件松动、间隙变大", "振动",
                                            "测量系统变差（量具、方法）"]},
}


def shape_along(x, d) -> dict:
    """沿轴向的直径误差 d(x) 分解为平均值、线性（锥度）和二次（中凸或中凹）分量：
    在 ξ = 2(x − x̄)/(x_max − x_min) ∈ [−1, 1] 上按正交多项式 1、ξ、(3ξ² − 1)/2 做最小二乘。
    taper = 右端减左端的直径差（由线性项），crown = 中间减两端平均的直径差（由二次项；> 0 鼓形，< 0 鞍形）。"""
    x, d = list(x), list(d)
    lo, hi = min(x), max(x)
    xi = [2 * (v - lo) / (hi - lo) - 1 for v in x]
    if len(set(x)) < 3:                   # 只有两个截面：只能看锥度
        dl = st.fmean([b for a, b in zip(xi, d) if a < 0])
        dr = st.fmean([b for a, b in zip(xi, d) if a > 0])
        return {"mean": (dl + dr) / 2, "taper": dr - dl, "crown": 0.0, "range": max(d) - min(d), "resid": 0.0,
                "label": "taper" if dr != dl else None}
    P = [[1.0] * len(xi), xi, [(3 * v * v - 1) / 2 for v in xi]]
    # 正规方程（点数少、分布不均时也可用）
    A = [[sum(a * b for a, b in zip(P[i], P[j])) for j in range(3)] for i in range(3)]
    bvec = [sum(a * b for a, b in zip(P[i], d)) for i in range(3)]
    c = _solve3(A, bvec)
    fit = [c[0] + c[1] * u + c[2] * (3 * u * u - 1) / 2 for u in xi]
    resid = [a - b for a, b in zip(d, fit)]
    taper = 2 * c[1]                      # ξ 从 −1 到 1
    crown = c[2] * (-0.5 - 1.0)           # 中间（ξ = 0）减两端平均（ξ = ±1）
    rng = max(d) - min(d)
    label = None
    if rng > 0:
        if abs(taper) >= max(abs(crown), 1e-12) * 1.5:
            label = "taper"
        elif abs(crown) >= abs(taper) / 1.5:
            label = "drum" if crown > 0 else "saddle"
    return {"mean": c[0], "taper": taper, "crown": crown, "range": rng, "resid": max(map(abs, resid)) if resid else 0.0,
            "label": label}


def _solve3(A, b):
    M = [row[:] + [v] for row, v in zip(A, b)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        if abs(M[i][i]) < 1e-15:
            return [st.fmean(b) if i == 0 else 0.0 for i in range(3)]
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [a - f * c for a, c in zip(M[r], M[i])]
    return [M[i][3] / M[i][i] for i in range(3)]


def harmonics(r, kmax: int = 12) -> dict:
    """圆度测量值 r（等角度间隔采样的半径偏差）的谐波分析：各阶幅值 A_k（半径上的幅值，峰谷约 2A_k）。
    一阶是偏心（安装），不算圆度误差。label：二阶为主 → ellipse，三阶 → lobe3，四阶以上 → lobes。"""
    m = len(r)
    amp = {}
    for k in range(1, kmax + 1):
        a = 2 / m * sum(v * math.cos(2 * math.pi * k * i / m) for i, v in enumerate(r))
        b = 2 / m * sum(v * math.sin(2 * math.pi * k * i / m) for i, v in enumerate(r))
        amp[k] = math.hypot(a, b)
    k_dom = max(range(2, kmax + 1), key=lambda k: amp[k])
    label = "ellipse" if k_dom == 2 else "lobe3" if k_dom == 3 else "lobes"
    return {"amp": amp, "dominant": k_dom, "label": label}


def _linfit(x, y):
    xm, ym = st.fmean(x), st.fmean(y)
    sxx = sum((a - xm) ** 2 for a in x)
    b = sum((a - xm) * (c - ym) for a, c in zip(x, y)) / sxx if sxx else 0.0
    return ym - b * xm, b


def sequence(values, resets=(), sigma=None, baseline=None) -> dict:
    """逐件序列的形态。步骤：
    1. 锯齿：resets 给出补偿（修整、换刀）后第一件的序号时，求各段内共同的斜率 saw_slope（每件），并从数据中减去，得到“去掉磨损”的序列；
       没有 resets 时求整体的线性斜率 slope，同样减去；
    2. 在去掉磨损的序列上找：开机预热（指数拟合比常数好得多、δ∞ 超过 3σ）、跳变（两段均值差的 t 值最大处）、
       整体偏移（与 baseline = (均值, σ) 比较，均值差超过 3σ/√n 且超过 σ）、分散变大（组内 σ 超过 baseline 或 sigma 的 1.25 倍）。
    sigma：正常状态的组内标准差（判别用；不给时用移动极差估计）。返回各特征和 labels（按显著程度排列）。"""
    v = list(values)
    n = len(v)
    idx = list(range(n))
    mr = [abs(b - a) for a, b in zip(v, v[1:])]
    s_mr = st.fmean(mr) / 1.128 if mr else 0.0
    ref = sigma or (baseline[1] if baseline else None) or s_mr
    res = {"n": n, "mean": st.fmean(v), "sigma_mr": s_mr}
    found = []
    cuts = [0] + sorted(r for r in resets if 0 < r < n) + [n]
    segs = [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1) if cuts[k + 1] - cuts[k] >= 3]
    pos = [0] * n                              # 每件在它那一段里的序号
    for s0, e0 in [(cuts[k], cuts[k + 1]) for k in range(len(cuts) - 1)]:
        for i in range(s0, e0):
            pos[i] = i - s0
    if len(segs) >= 2:
        xs = [i - s0 - (e0 - s0 - 1) / 2 for s0, e0 in segs for i in range(s0, e0)]
        ys = [v[i] - st.fmean(v[s0:e0]) for s0, e0 in segs for i in range(s0, e0)]
        _, b = _linfit(xs, ys)
        res["saw_slope"] = b
        w = [v[i] - b * pos[i] for i in idx]
        if abs(b) * 20 > 3 * ref:
            found.append(("drift_saw", abs(b) * 20 / ref))
    else:
        _, b = _linfit(idx, v)
        res["slope"] = b
        w = [v[i] - b * i for i in idx]
        if abs(b) * min(n, 20) > 3 * ref:
            found.append(("drift_linear", abs(b) * min(n, 20) / ref))
    wm = st.fmean(w)
    sse0 = sum((y - wm) ** 2 for y in w)
    if n >= 8:
        # 磨损斜率与预热一起拟合：y = c0 + b·段内序号 + δ∞(1 − e^(−i/τ))，对 τ 网格搜索
        best_w = None
        for k in range(1, 200):
            tau = n / 2 * k / 200
            g = [1 - math.exp(-i / tau) for i in idx]
            cols = [[1.0] * n, [float(q) for q in pos] if len(segs) >= 2 else [float(i) for i in idx], g]
            A3 = [[sum(a * c for a, c in zip(cols[r], cols[q])) for q in range(3)] for r in range(3)]
            c = _solve3(A3, [sum(a * y for a, y in zip(cols[r], v)) for r in range(3)])
            sse = sum((y - c[0] - c[1] * cols[1][i] - c[2] * g[i]) ** 2 for i, y in enumerate(v))
            if best_w is None or sse < best_w[0]:
                best_w = (sse, tau, c)
        sse_w, tau, c = best_w
        res["warmup"] = {"tau": tau, "delta_inf": c[2], "slope": c[1], "sse": sse_w, "sse_const": sse0}
        if sse0 > 0 and sse_w < 0.7 * sse0 and abs(c[2]) > 3 * ref and tau < n / 3:
            found.append(("warmup", abs(c[2]) / ref))
            if len(segs) >= 2:
                res["saw_slope"] = c[1]
            else:
                res["slope"] = c[1]
            g = [1 - math.exp(-i / tau) for i in idx]
            w = [v[i] - c[1] * (pos[i] if len(segs) >= 2 else i) - c[2] * g[i] for i in idx]
    res["detrended"] = w
    # 组内分散：去掉趋势后的移动极差，跨过补偿点的相邻两件不算
    rs = set(r for r in resets)
    mr2 = [abs(w[i] - w[i - 1]) for i in range(1, n) if i not in rs]
    s_mr = st.fmean(mr2) / 1.128 if mr2 else s_mr
    res["sigma_mr"] = s_mr
    best = None
    for c in range(3, n - 3):
        m1, m2 = st.fmean(w[:c]), st.fmean(w[c:])
        t = abs(m2 - m1) / (ref * math.sqrt(1 / c + 1 / (n - c))) if ref > 0 else 0.0
        if best is None or t > best[0]:
            best = (t, c, m2 - m1)
    if best:
        res["jump"] = {"t": best[0], "at": best[1], "size": best[2]}
        if best[0] > 6 and abs(best[2]) > 2 * ref and not any(f[0] == "warmup" for f in found):
            found.append(("jump", best[0] / 6))
    if baseline:
        d = res["mean"] - baseline[0]
        res["shift"] = d
        if abs(d) > max(3 * baseline[1] / math.sqrt(n), baseline[1]):
            found.append(("shift", abs(d) / baseline[1]))
    res["sigma_ratio"] = s_mr / ref if ref else 1.0
    if (sigma or baseline) and res["sigma_ratio"] > 1.25:
        found.append(("spread", res["sigma_ratio"]))
    found.sort(key=lambda f: -f[1])
    res["labels"] = [f[0] for f in found]
    res["label"] = res["labels"][0] if found else None
    return res


def diagnose(along=None, roundness=None, seq=None, resets=(), sigma=None, baseline=None, tol=None) -> list:
    """把三类数据的形态判别汇总成“可能原因”清单。
    along = (x, d)：同一件沿轴向各截面的直径（或几件的平均）；roundness：一个截面等角度采样的半径偏差；seq：逐件的测量值。
    tol：公差（给出时，只有形态的大小超过公差的 1/10 才列出）。返回 [{kind, label, name, value, causes}]。"""
    out = []
    lim = tol / 10 if tol else 0.0
    if along is not None:
        s = shape_along(*along)
        if s["label"]:
            val = s["taper"] if s["label"] == "taper" else s["crown"]
            if abs(val) > lim:
                out.append({"kind": "along", "label": s["label"], "value": val, **_cat(s["label"])})
    if roundness is not None:
        h = harmonics(roundness)
        val = 2 * h["amp"][h["dominant"]]
        if val > lim:
            out.append({"kind": "roundness", "label": h["label"], "value": val, "order": h["dominant"], **_cat(h["label"])})
    if seq is not None:
        q = sequence(seq, resets, sigma, baseline)
        for lab in q["labels"]:
            val = {"drift_saw": q.get("saw_slope"), "drift_linear": q.get("slope"), "warmup": (q.get("warmup") or {}).get("delta_inf"),
                   "jump": (q.get("jump") or {}).get("size"), "shift": q.get("shift"), "spread": q["sigma_ratio"]}[lab]
            out.append({"kind": "sequence", "label": lab, "value": val, **_cat(lab)})
    return out


def _cat(label):
    s = SHAPES[label]
    return {"name": s["name"], "causes": s["causes"]}


# ---------------------------------------------------------------- 精度预算
def budget(items, T: float) -> dict:
    """加工精度预算。items = [{name, range, kind}]：kind = "sys"（常值或变值系统误差，范围直接相加）或 "rand"（随机误差，
    range 取 ±3σ 即 6σ，平方和开方）。合计 = Σ系统 + √(Σ随机²)，与公差 T 比较。
    返回合计、余量、各项占公差的比例，以及 ok（合计 ≤ T）、tight（合计 > 0.75T，裕量不足）。"""
    sys_ = sum(i["range"] for i in items if i.get("kind", "rand") == "sys")
    rnd = math.sqrt(sum(i["range"] ** 2 for i in items if i.get("kind", "rand") == "rand"))
    tot = sys_ + rnd
    share = [{"name": i["name"], "range": i["range"], "kind": i.get("kind", "rand"), "share": i["range"] / T} for i in items]
    return {"sys": sys_, "rand": rnd, "total": tot, "T": T, "margin": T - tot, "ok": tot <= T + 1e-12,
            "tight": tot > 0.75 * T + 1e-12, "items": share}
