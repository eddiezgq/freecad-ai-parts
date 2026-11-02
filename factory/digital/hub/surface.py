# -*- coding: utf-8 -*-
"""机械加工表面质量与表面完整性（第 13 轮十一；《机械制造技术》第 55 章）。书和数字工厂共用：

- 表面轮廓与粗糙度参数：车削表面的合成轮廓（刀尖圆弧残留 + 积屑瘤与鳞刺 + 振动波纹）、高斯滤波（ISO 16610-21）、
  Ra、Rq、Rz、Rt、轮廓支承长度率 Rmr(c)；
- 车削的理论残留高度（圆弧刀尖 h = r − √(r² − f²/4) ≈ f²/(8r)，尖刀 f/(cot κr + cot κr′)），积屑瘤区；
- 磨削：当量直径、接触弧长、当量磨削厚度 heq = vw·ap/vs、比磨削能、粗糙度与光磨次数；
- 磨削温度（Jaeger 移动热源，Malkin 的写法）与烧伤判别：回火软化用 Hollomon–Jaffe 回火参数换算到磨削的
  毫秒级受热，二次淬火烧伤看是否超过 Ac1；烧伤边界（工件速度–切深图上允许的最大切深）；
- 加工硬化、残余应力沿深度的典型分布（示意）；
- 表面完整性与疲劳：FKM 粗糙度系数 K_R、残余应力按平均应力处理（FKM 平均应力敏感系数 M）、Basquin 寿命。

单位：长度 mm（粗糙度 µm），速度 m/s（另注明的除外），应力 MPa，温度 °C，比磨削能 J/mm³。
标“经验式”“示意”的参数是教学用的典型值，实际要按砂轮、材料、机床实测标定。
"""
from __future__ import annotations

import math

import numpy as np

# ---------------------------------------------------------------- 材料（与 cae/materials.py 的热物性、强度一致）
STEELS = {
    # Ac1 取《机械工程材料》常用值；回火工艺取本书工艺规程（SH-301：560 ℃ 回火）与渗碳件常用的 180 ℃ × 2 h 低温回火
    "45-QT": {"name": "45 钢（调质）", "k": 49.8, "c": 486, "rho": 7850, "Ac1": 724, "temper_c": 560, "temper_h": 2.0,
              "Rm": 640, "sigma_1": 275, "HV": 240},
    "20CrMnTi-CQ": {"name": "20CrMnTi（渗碳淬火、低温回火）", "k": 46.6, "c": 477, "rho": 7850, "Ac1": 740, "temper_c": 180,
                    "temper_h": 2.0, "Rm": 1080, "sigma_1": 525, "HV": 700},
}
EPS_WET = 0.7          # 白刚玉砂轮湿磨时磨削热进入工件的份额（Malkin：普通磨料 0.6–0.85），本书取 0.7
HJ_C = 20.0            # Hollomon–Jaffe 回火参数的常数（碳钢、低合金钢常用 20）
THETA0 = 20.0          # 工件初始温度


def diffusivity(mat: dict) -> float:
    """热扩散率 α = k/(ρc)，m²/s。"""
    return mat["k"] / (mat["rho"] * mat["c"])


# ---------------------------------------------------------------- 车削的理论残留高度
def residual_height(f: float, r: float) -> float:
    """圆弧刀尖（半径 r）、进给量 f 时的理论残留高度（精确式），mm。f ≤ 2r。"""
    return r - math.sqrt(r * r - f * f / 4)


def residual_height_sharp(f: float, kr_deg: float, kr2_deg: float) -> float:
    """尖刀（无刀尖圆弧）：主偏角 κr、副偏角 κr′ 时 h = f/(cot κr + cot κr′)，mm。"""
    return f / (1 / math.tan(math.radians(kr_deg)) + 1 / math.tan(math.radians(kr2_deg)))


def ra_theory(f: float, r: float) -> float:
    """只有刀尖圆弧残留（抛物线近似）时的 Ra = [4/(9√3)]·f²/(8r) ≈ 0.0321 f²/r，µm（f、r 用 mm）。"""
    return 4 / (9 * math.sqrt(3)) * f * f / (8 * r) * 1000


def feed_for_ra(ra_um: float, r: float) -> float:
    """要求的 Ra（µm）下允许的最大进给量（只按几何残留，实际还要留给积屑瘤、振动的余量），mm/r。"""
    return math.sqrt(ra_um / 1000 * 8 * r * 9 * math.sqrt(3) / 4)


def bue_amplitude(vc_m_min: float, peak_um: float = 2.0) -> float:
    """积屑瘤与鳞刺在加工中碳钢时附加的不平度幅值（经验式，示意）：vc ≈ 20–30 m/min 最严重，
    70 m/min 以上基本消失，很低速（< 5 m/min）也不产生。返回 µm。"""
    if vc_m_min <= 0:
        return 0.0
    return peak_um * math.exp(-(math.log(vc_m_min / 25.0) / 0.55) ** 2)


# ---------------------------------------------------------------- 轮廓与粗糙度参数（与《机械设计》4.7 节同一做法）
DX = 0.0005            # 采样间隔 mm
LC = 0.8               # 截止波长 λc（Ra 0.1–2 µm 的表面）


def turned_profile(f: float, r: float, vc_m_min: float = 120.0, wave_um: float = 0.0, wave_mm: float = 2.5,
                   noise_um: float = 0.12, seed: int = 7, lc: float = LC, n_samp: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """车削表面的轮廓 z(x)，mm。刀尖圆弧残留 + 随机微观不平（相关长度约 10 µm）+ 积屑瘤（按 vc）+ 振动波纹。
    长度为 n_samp 个取样长度再加两端各一个 λc（给滤波器“热身”）。"""
    L = (n_samp + 2) * lc
    x = np.arange(0, L, DX)
    rng = np.random.default_rng(seed)
    xc = (x + rng.uniform(0, f)) % f - f / 2
    z = r - np.sqrt(np.maximum(r * r - xc ** 2, 0))
    k = np.exp(-0.5 * (np.arange(-40, 41) * DX / 0.005) ** 2)
    n = np.convolve(rng.normal(0, 1, x.size), k / np.sqrt((k ** 2).sum()), mode="same")
    z = z + n * noise_um / 1000
    b = bue_amplitude(vc_m_min) / 1000
    if b > 0:                       # 积屑瘤时生时灭：碎片嵌在表面、撕下的地方留下凹坑——相关长度约 20 µm 的随机起伏
        k2 = np.exp(-0.5 * (np.arange(-120, 121) * DX / 0.02) ** 2)
        g = np.convolve(rng.normal(0, 1, x.size), k2 / np.sqrt((k2 ** 2).sum()), mode="same")
        z = z + b * g
    if wave_um:
        z = z + wave_um / 1000 * np.sin(2 * math.pi * x / wave_mm + 0.7)
    return x, z


def gauss_mean(z: np.ndarray, lc: float = LC) -> np.ndarray:
    """高斯滤波得到中线（ISO 16610-21）：权函数 exp(−π(x/(αλc))²)，α = √(ln2/π)。"""
    a = math.sqrt(math.log(2) / math.pi)
    u = np.arange(-lc, lc + DX / 2, DX)
    s = np.exp(-math.pi * (u / (a * lc)) ** 2)
    return np.convolve(z, s / s.sum(), mode="same")


def roughness(x: np.ndarray, z: np.ndarray, lc: float = LC, n_samp: int = 5) -> dict:
    """粗糙度参数（µm）：Ra、Rq、Rz（各取样长度内最大峰谷高的平均）、Rt（评定长度内最大峰谷高），
    以及粗糙度轮廓 r(x)（评定长度内，µm）。"""
    m = gauss_mean(z, lc)
    keep = (x >= lc) & (x < lc * (n_samp + 1))
    rr = (z - m)[keep] * 1000
    n = int(round(lc / DX))
    seg = [rr[i * n:(i + 1) * n] for i in range(n_samp)]
    return {"Ra": float(np.mean(np.abs(rr))), "Rq": float(np.sqrt(np.mean(rr ** 2))),
            "Rz": float(np.mean([s.max() - s.min() for s in seg])), "Rt": float(rr.max() - rr.min()),
            "x": x[keep], "r": rr}


def material_ratio(r_um: np.ndarray, c_um: float) -> float:
    """轮廓支承长度率 Rmr(c)：在最高峰以下 c 处截取，轮廓实体所占的长度比例（0–1）。"""
    level = r_um.max() - c_um
    return float(np.mean(r_um >= level))


def surface_map(f: float, r: float, vc_m_min: float = 120.0, wave_um: float = 0.0, wave_mm: float = 2.5,
                width: float = 2.0, length: float = 1.2, n: int = 160, seed: int = 7) -> np.ndarray:
    """车削表面的高度场（µm），沿进给方向 length、沿切削速度方向 width，n × n 点；三维实验与插图用。
    进给方向是刀尖圆弧残留（同一转内各处一样，只有微观不平不同），切削方向叠加振动波纹。"""
    rng = np.random.default_rng(seed)
    xs = np.linspace(0, length, n)
    ys = np.linspace(0, width, n)
    xc = (xs[:, None] + 0 * ys[None, :]) % f - f / 2
    z = (r - np.sqrt(np.maximum(r * r - xc ** 2, 0))) * 1000
    z = z + rng.normal(0, 0.12, z.shape)
    b = bue_amplitude(vc_m_min)
    if b:                           # 与 turned_profile 相同：相关长度约 20 µm 的随机起伏（µm）
        from scipy.ndimage import gaussian_filter
        g = gaussian_filter(rng.normal(0, 1, z.shape), 0.02 / (length / n))
        z = z + b * g / max(g.std(), 1e-12)
    if wave_um:
        z = z + wave_um * np.sin(2 * math.pi * ys[None, :] / wave_mm)
    return z - z.mean()


# ---------------------------------------------------------------- 磨削：几何、比磨削能、粗糙度
def equivalent_diameter(dw: float, ds: float, internal: bool = False) -> float:
    """外圆磨削 de = dw·ds/(dw + ds)；内圆磨削 de = dw·ds/(dw − ds)；平面磨削 de = ds。mm。"""
    if dw == math.inf:
        return ds
    return dw * ds / ((dw - ds) if internal else (dw + ds))


def contact_length(ap: float, de: float) -> float:
    """几何接触弧长 lc = √(ap·de)，mm。"""
    return math.sqrt(ap * de)


def heq(vw: float, ap: float, vs: float) -> float:
    """当量磨削厚度 heq = vw·ap/vs，µm（vw、vs 同一单位，ap 用 mm）。"""
    return vw * ap / vs * 1000


def specific_energy(h_eq_um: float, wear_flat_pct: float = 0.5) -> float:
    """比磨削能 u（J/mm³），经验式（示意，量级与 Malkin《Grinding Technology》中钢的数据相符）：
    u = 14·heq^−0.35（heq 用 µm）——切得越薄，单位体积耗能越大（尺寸效应）；
    砂轮变钝，磨粒磨平面积 A（占砂轮表面的百分数，刚修整约 0.5%）增大，摩擦耗能随之增加：× [1 + 0.3(A − 0.5)]。"""
    return 14.0 * h_eq_um ** -0.35 * (1 + 0.3 * (wear_flat_pct - 0.5))


def grinding_ra(h_eq_um: float, sparkout: int = 0, mesh: int = 60, wear_flat_pct: float = 0.5) -> float:
    """磨削表面的 Ra（µm），经验式（示意，按 60# 白刚玉砂轮精细修整标定）：
    进给磨削时 Ra₀ = 2.6·heq^0.4；无进给光磨每次把残留的让刀量切掉约一半，Ra 向砂轮形貌决定的下限
    Ra∞ = 0.4·(60/粒度号) 逼近；砂轮钝化、堵塞后 Ra 变大：× [1 + 0.1(A − 0.5)]。"""
    floor = 0.4 * 60 / mesh
    ra0 = max(2.6 * h_eq_um ** 0.4, floor)
    return (floor + (ra0 - floor) * 0.5 ** sparkout) * (1 + 0.1 * (wear_flat_pct - 0.5))


# ---------------------------------------------------------------- 磨削温度与烧伤
def grinding_temperature(mat: dict, vs: float, vw: float, ap: float, de: float, wear_flat_pct: float = 0.5,
                         eps: float = EPS_WET) -> dict:
    """磨削区工件表面的最高温度（Jaeger 移动带状热源，数值精确解；Peclet 数 L 大于约 5 时就是
    θmax − θ0 ≈ 1.13·q·√(α·lc/vw)/k），热流密度 q = ε·u·vw·ap/lc。
    vs、vw：m/s；ap、de：mm。返回 θmax（°C）与中间量：lc（mm）、heq（µm）、u（J/mm³）、q（W/mm²）、接触时间 t（ms）、Peclet 数。"""
    lc = contact_length(ap, de)
    h = heq(vw, ap, vs)
    u = specific_energy(h, wear_flat_pct)
    a = diffusivity(mat)
    q = eps * (u * 1e9) * vw * (ap * 1e-3) / (lc * 1e-3)                 # W/m²
    L = vw * lc * 1e-3 / (4 * a)                                          # Peclet 数（以半接触长计）
    rise = 2 * q * a / (math.pi * mat["k"] * vw) * jaeger_peak(L)        # 精确解；L 大时 → 1.13·q·√(α·lc/vw)/k
    return {"theta": THETA0 + rise, "rise": rise, "rise_approx": 1.13 * q * math.sqrt(a * lc * 1e-3 / vw) / mat["k"],
            "lc": lc, "heq": h, "u": u, "q": q / 1e6, "t_ms": lc / (vw * 1000) * 1000, "peclet": L}


_JP: dict = {}


def jaeger_peak(L: float) -> float:
    """Jaeger 移动带状热源（半宽 l、速度 v，绝热表面以外散热不计）表面温度的无量纲峰值
    max_X ∫_{X−L}^{X+L} e^(−u)·K₀(|u|) du，L = v·l/(2α)；θ = 2qα/(πkv) × 它。"""
    key = round(L, 4)
    if key in _JP:
        return _JP[key]
    from scipy.integrate import quad
    from scipy.optimize import minimize_scalar
    from scipy.special import k0

    def F(X):
        lo, hi = X - L, X + L
        pts = [0.0] if lo < 0 < hi else None
        return quad(lambda u: math.exp(-u) * k0(abs(u)) if u else 0.0, lo, hi, points=pts, limit=200)[0]
    r = minimize_scalar(lambda X: -F(X), bounds=(-L, 1.5 * L + 1), method="bounded", options={"xatol": 1e-4})
    _JP[key] = -r.fun
    return _JP[key]


def temper_onset(mat: dict, t_s: float) -> float:
    """受热时间 t（s）时开始回火软化的温度（°C）：Hollomon–Jaffe 回火参数 P = T(C + lg t) 与原回火工艺
    （temper_c、temper_h）相等时的温度。加热越短，要越高的温度才产生同样的回火效果。"""
    P = (mat["temper_c"] + 273.15) * (HJ_C + math.log10(mat["temper_h"] * 3600))
    return P / (HJ_C + math.log10(t_s)) - 273.15


def burn_state(mat: dict, theta: float, t_ms: float, coolant: bool = True) -> dict:
    """烧伤判别。θ ≥ Ac1：表层奥氏体化——有冷却液急冷成二次淬火马氏体（白层，下面是回火软带），叫二次淬火烧伤；
    干磨缓冷则得退火组织，叫退火烧伤。回火软化温度 ≤ θ < Ac1：回火烧伤（硬度下降）。否则不烧伤。"""
    onset = temper_onset(mat, t_ms / 1000)
    if theta >= mat["Ac1"]:
        kind = "rehardening" if coolant else "annealing"
    elif theta >= onset:
        kind = "tempering"
    else:
        kind = "none"
    name = {"none": "不烧伤", "tempering": "回火烧伤", "rehardening": "二次淬火烧伤", "annealing": "退火烧伤"}[kind]
    return {"kind": kind, "name": name, "onset": onset, "Ac1": mat["Ac1"], "margin": min(onset, mat["Ac1"]) - theta}


def max_infeed(mat: dict, vs: float, vw: float, de: float, wear_flat_pct: float = 0.5, eps: float = EPS_WET,
               lo: float = 1e-4, hi: float = 0.2) -> float:
    """不烧伤（不超过回火软化温度，也不超过 Ac1）时允许的最大切深 ap（mm），二分法。"""
    def ok(ap):
        g = grinding_temperature(mat, vs, vw, ap, de, wear_flat_pct, eps)
        return burn_state(mat, g["theta"], g["t_ms"])["kind"] == "none"
    if not ok(lo):
        return 0.0
    if ok(hi):
        return hi
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


def burn_boundary(mat: dict, vs: float, de: float, vws: list[float], wear_flat_pct: float = 0.5) -> list[tuple[float, float]]:
    """烧伤边界：每个工件速度 vw（m/s）下的最大切深 ap（mm）。"""
    return [(vw, max_infeed(mat, vs, vw, de, wear_flat_pct)) for vw in vws]


# ---------------------------------------------------------------- 加工硬化与残余应力（典型分布，示意）
def hardness_profile(hv_core: float, degree: float, depth: float, z: np.ndarray) -> np.ndarray:
    """加工硬化的显微硬度分布 HV(z) = HV₀[1 + N·e^(−3z/h)]：硬化程度 N = (HV表 − HV₀)/HV₀，
    硬化层深度 h（硬度增量降到约 5% 处）。"""
    return hv_core * (1 + degree * np.exp(-3 * z / depth))


RESIDUAL = {   # 沿深度的残余应力典型分布（深度 mm，应力 MPa；示意，量值在文献常见范围内），三次 Hermite 插值
    "turned": [(0, 250), (0.02, 150), (0.05, 20), (0.08, -40), (0.15, -10), (0.3, 0)],
    "ground": [(0, -150), (0.01, -180), (0.03, -60), (0.06, -10), (0.15, 0), (0.3, 0)],
    "ground_burn": [(0, 550), (0.02, 450), (0.05, 180), (0.08, 20), (0.12, -60), (0.2, -20), (0.3, 0)],
    "shot_peened": [(0, -450), (0.04, -650), (0.1, -500), (0.2, -150), (0.3, 50), (0.5, 20), (0.8, 0)],
    "rolled": [(0, -550), (0.15, -800), (0.4, -600), (0.8, -150), (1.1, 60), (1.6, 0)],
}
RESIDUAL_NAME = {"turned": "精车", "ground": "正常磨削", "ground_burn": "磨削烧伤", "shot_peened": "喷丸", "rolled": "滚压"}


def residual_stress(kind: str, z: np.ndarray) -> np.ndarray:
    """某种加工后表层轴向残余应力的典型分布（MPa，拉为正）。"""
    pts = np.array(RESIDUAL[kind], float)
    from scipy.interpolate import PchipInterpolator
    return PchipInterpolator(pts[:, 0], pts[:, 1], extrapolate=False)(np.clip(z, 0, pts[-1, 0]))


# ---------------------------------------------------------------- 表面完整性与疲劳（FKM 指南的做法）
def roughness_factor(rz_um: float, rm: float, a_r: float = 0.22, rm_min: float = 400.0) -> float:
    """粗糙度系数 K_R = 1 − a_R·lg(Rz)·lg(2Rm/Rm,min)（FKM 指南，钢 a_R = 0.22、Rm,min = 400 MPa；Rz ≤ 1 µm 取 1）。"""
    if rz_um <= 1:
        return 1.0
    return 1 - a_r * math.log10(rz_um) * math.log10(2 * rm / rm_min)


def mean_stress_sensitivity(rm: float) -> float:
    """平均应力敏感系数 M = 0.35×10⁻³·Rm − 0.1（FKM，钢，正应力）。"""
    return 0.35e-3 * rm - 0.1


def fatigue_limit(mat: dict, rz_um: float, sigma_res: float = 0.0, size: float = 1.0) -> dict:
    """考虑表面粗糙度和表层残余应力的弯曲疲劳极限（MPa）：σD = σ₋₁·K_R·size − M·σ_res
    （残余应力按平均应力处理：拉应力降低、压应力提高疲劳极限；按 FKM 在 σm 不太大的范围内线性修正）。"""
    kr = roughness_factor(rz_um, mat["Rm"])
    m = mean_stress_sensitivity(mat["Rm"])
    sd = mat["sigma_1"] * kr * size - m * sigma_res
    return {"KR": kr, "M": m, "sigma_D": max(sd, 0.0)}


def life(sigma_a: float, sigma_d: float, n_d: float = 1e7, k: float = 9.0) -> float:
    """Basquin：σa ≤ σD 时为无限寿命（返回 inf），否则 N = N_D·(σa/σD)^−k。"""
    if sigma_a <= sigma_d:
        return math.inf
    return n_d * (sigma_a / sigma_d) ** -k
