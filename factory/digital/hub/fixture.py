"""夹具设计计算库（第 13 轮，配教材《机械制造技术》第 52 章）：切削力、夹紧力、夹紧机构、动力装置、对刀导向误差、夹具精度。

教材的程序、实验、数字工厂的 AI 工艺评审员都调用这里的函数。所有公式都是教学用的工程估算：
摩擦系数、安全系数、机构效率按夹具设计手册一类资料的常见取值，写在参数默认值里，使用时应按实际情况核对。
单位：力 N，长度 mm，角度 °（函数参数），应力 MPa。
"""
from __future__ import annotations

import math
import os
import sys

import yaml

# ---------------------------------------------------------------- 安全系数
# K = K0·K1·K2·K3·K4·K5·K6（国内夹具设计手册常用的分项写法；数值为常见取值，以所用手册为准）
K_ITEMS = {
    "K0": ("基本安全系数", {"一般": 1.5}),
    "K1": ("加工性质", {"粗加工": 1.2, "精加工": 1.0}),
    "K2": ("刀具钝化", {"车削": 1.0, "铣削": 1.2, "钻削": 1.15, "磨削": 1.0}),
    "K3": ("断续切削", {"连续": 1.0, "断续": 1.2}),
    "K4": ("夹紧力的稳定性", {"机动": 1.0, "手动": 1.3}),
    "K5": ("手动夹紧的方便程度", {"方便": 1.0, "不便": 1.2}),
    "K6": ("仅有力矩使工件回转时的支承情况", {"支承点接触": 1.0, "接触面积大": 1.5}),
}


def safety_factor(**choice) -> dict:
    """按分项选择算总安全系数：safety_factor(K1="粗加工", K2="铣削", K3="断续", K4="手动")。没选的取第一项。
    K6 只在“仅有力矩使工件回转”时考虑：支承为点（线）接触取 1.0，接触面积大（摩擦力矩的作用半径不确定）取 1.5。"""
    items, K = [], 1.0
    for key, (name, opts) in K_ITEMS.items():
        label = choice.get(key, next(iter(opts)))
        v = opts[label]
        K *= v
        items.append((key, name, label, v))
    return {"K": K, "items": items}


# ---------------------------------------------------------------- 切削力
def _kienzle(material="45"):
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from cae.cam_power import _row
    row, _ = _row(material)
    return float(row["kc11_MPa"]), float(row["mc"])


def slot_forces(D: float, z: int, fz: float, ap: float, material="45", Kr=0.35, Ka=0.25, n=1440, ae=None) -> dict:
    """立铣刀铣槽（满槽 ae = D，或侧铣 ae < D）时作用在工件上的切削力，按每齿切削刃逐角积分（机理模型）。

    每个参与切削的刀齿：切屑厚度 h = fz·sinφ，切向力 Ft = kc1.1·ap·h^(1−mc)（Kienzle），径向力 Fr = Kr·Ft，
    轴向力 Fa = Ka·Ft（右旋刀刃把工件往上拔）。φ 从刀齿切入处算起，满槽 φ ∈ [0, π]。
    坐标（作用在工件上）：x 沿进给方向，y 垂直于进给的水平方向，z 竖直向上。返回一转内的平均值与峰值。"""
    kc11, mc = _kienzle(material)
    ae = D if ae is None else ae
    phi_ex = math.pi if ae >= D else math.acos(1 - 2 * ae / D)   # 逆铣侧铣：从 0 切入、到 phi_ex 切出
    fx, fy, fzs, tq = [], [], [], []
    for k in range(n):
        th = 2 * math.pi * k / n
        Fx = Fy = Fz = T = 0.0
        for j in range(z):
            phi = (th + 2 * math.pi * j / z) % (2 * math.pi)
            if 0 < phi < phi_ex:
                h = fz * math.sin(phi)
                Ft = kc11 * ap * h ** (1 - mc)
                Fr = Kr * Ft
                # 作用在刀具上的力（Altintas 的写法），工件上的力与之相反
                tx = -Ft * math.cos(phi) - Fr * math.sin(phi)
                ty = Ft * math.sin(phi) - Fr * math.cos(phi)
                Fx -= tx
                Fy -= ty
                Fz += Ka * Ft
                T += Ft * D / 2
        fx.append(Fx); fy.append(Fy); fzs.append(Fz); tq.append(T)
    mean = lambda a: sum(a) / len(a)  # noqa: E731
    peak = lambda a: max(abs(v) for v in a)  # noqa: E731
    Tm = mean(tq)                                   # N·mm
    return {"kc11": kc11, "mc": mc, "Fx_mean": mean(fx), "Fy_mean": mean(fy), "Fz_mean": mean(fzs),
            "Fx_peak": peak(fx), "Fy_peak": peak(fy), "Fz_peak": peak(fzs), "torque_Nmm": Tm,
            "Fx_max": max(fx), "Fx_min": min(fx),
            "Fc_mean": Tm / (D / 2)}


def slot_power(res: dict, D: float, vc: float) -> float:
    """铣槽的切削功率（kW）：平均扭矩 × 角速度。"""
    n = 1000 * vc / (math.pi * D)
    return res["torque_Nmm"] / 1000 * 2 * math.pi * n / 60 / 1000


# ---------------------------------------------------------------- 夹紧力：V 形块上的轴
def vblock_clamp_required(Fx: float, Fy: float, Fz_lift: float, K: float, mu1=0.16, mu2=0.16, alpha=90.0,
                          G=0.0, axial_stop_takes_Fx=True, r_f: float = 1.0, r_c: float = 1.0, r_v: float = 1.0) -> dict:
    """轴放在 V 形块上、从上方夹紧（夹紧力 W，向下），切削力：沿轴线 Fx、水平横向 Fy（作用在轴的上母线附近）、向上 Fz。
    mu1：压板与工件的摩擦系数；mu2：V 形块工作面与工件的摩擦系数；G：工件重力。各条件都乘安全系数 K。

    1. 不被抬起：W + G ≥ K·Fz；
    2. 横向不滑出 V 形块（任一工作面的法向力不变成负）：W + G ≥ K·Fy·tan(α/2)；
    3. 不绕轴线转动：横向力对轴心的力矩 Fy·r_f 由压板处（半径 r_c）和 V 形块两面（半径 r_v）的摩擦力矩平衡，
       W ≥ K·Fy·r_f/(μ1·r_c + μ2·r_v/sin(α/2)) − 重力项；r_f、r_c、r_v 缺省都取 1（同一半径）；
    4. 轴向不滑动（没有挡板承受轴向力时）：W ≥ K·Fx/(μ1 + μ2/sin(α/2)) − 重力项。
    返回每个条件需要的 W 和起控制作用的条件。"""
    s = math.sin(math.radians(alpha) / 2)
    t = math.tan(math.radians(alpha) / 2)
    fr = mu1 + mu2 / s                               # 单位夹紧力产生的摩擦力（压板一处 + V 形块两面）
    frm = mu1 * r_c + mu2 * r_v / s                  # 单位夹紧力产生的摩擦力矩
    req = {
        "lift": K * Fz_lift - G,
        "slide_out": K * Fy * t - G,
        "rotate": (K * Fy * r_f - mu2 * G * r_v / s) / frm,
        "axial": 0.0 if axial_stop_takes_Fx else (K * Fx - mu2 * G / s) / fr,
    }
    req = {k: max(0.0, v) for k, v in req.items()}
    gov = max(req, key=req.get)
    return {"req": req, "W": req[gov], "governing": gov, "fr": fr, "frm": frm}


def axial_to_resist(f: dict, stop_takes_toward=True) -> float:
    """要靠摩擦抵抗的轴向力：有挡板承受朝向挡板的分力时，只剩一转中背离挡板的那一部分（−Fx_min）；没有挡板时取峰值。"""
    return max(0.0, -f["Fx_min"]) if stop_takes_toward else f["Fx_peak"]


def vblock_normal_forces(W: float, Fy: float = 0.0, alpha=90.0) -> tuple:
    """V 形块两个工作面上的法向力（竖直合力 W 向下、横向力 Fy 向 +y）。"""
    h = math.radians(alpha) / 2
    N1 = W / (2 * math.sin(h)) - Fy / (2 * math.cos(h))
    return N1, N1 + Fy / math.cos(h)


def friction_clamp_required(F: float, K: float, mu1=0.16, mu2=0.16) -> float:
    """最简单的情况：平面定位、夹紧力垂直于定位面，切削力平行于定位面，只靠两个接触面的摩擦力抵抗：W ≥ K·F/(μ1 + μ2)。"""
    return K * F / (mu1 + mu2)


# ---------------------------------------------------------------- 基本夹紧机构
def wedge(Q: float, alpha: float, phi1: float, phi2: float) -> dict:
    """斜楔夹紧：原始作用力 Q 推斜楔（楔角 α），φ1 斜楔与工件、φ2 斜楔与夹具体斜面的摩擦角（°）。
    W = Q / (tan φ1 + tan(α + φ2))；理想无摩擦时 W = Q/tan α；自锁条件 α ≤ φ1 + φ2。"""
    a, p1, p2 = (math.radians(v) for v in (alpha, phi1, phi2))
    W = Q / (math.tan(p1) + math.tan(a + p2))
    ideal = Q / math.tan(a)
    return {"W": W, "i": W / Q, "ideal": ideal, "eta": W / ideal, "self_lock": alpha <= phi1 + phi2 + 1e-12,
            "stroke_ratio": math.tan(a)}


def thread(d: float, P: float, d2: float | None = None) -> dict:
    """普通螺纹（60°）的几何：中径、升角。d2 缺省按 GB/T 196 的近似 d − 0.6495P。"""
    d2 = d - 0.6495 * P if d2 is None else d2
    return {"d": d, "P": P, "d2": d2, "lead_deg": math.degrees(math.atan(P / (math.pi * d2)))}


def screw_clamp(Q: float, L: float, d: float, P: float, mu_thread=0.15, mu_end=0.15, r_end: float | None = None) -> dict:
    """螺旋夹紧：扳手（手柄）长 L，作用力 Q，力矩 M = Q·L。
    M = W·[r2·tan(α + φ') + r'·tan φ1]：r2 中径的一半，α 螺纹升角，φ' 当量摩擦角（tan φ' = μ/cos 30°），
    r' 螺杆（或螺母）端面的当量摩擦半径（球面垫圈或点接触取很小，平端面取 1/3 外径左右），φ1 端面摩擦角。"""
    t = thread(d, P)
    a = math.radians(t["lead_deg"])
    phi_e = math.atan(mu_thread / math.cos(math.radians(30)))
    r_end = d / 3 if r_end is None else r_end
    M = Q * L
    W = M / (t["d2"] / 2 * math.tan(a + phi_e) + r_end * mu_end)
    return {"M_Nmm": M, "W": W, "i": W / Q, "lead_deg": t["lead_deg"], "phi_e_deg": math.degrees(phi_e),
            "self_lock": t["lead_deg"] < math.degrees(phi_e)}


def strap_clamp(W_screw: float, l_work: float, l_heel: float, eta=0.95) -> dict:
    """移动压板（杠杆）：螺栓在压板中间，一端压工件、一端支在垫块（后支点）上。
    l_work：螺栓到压工件一端的距离，l_heel：螺栓到后支点的距离。工件上的夹紧力 W = W_screw·l_heel/(l_work + l_heel)·η。
    螺栓越靠近工件，W 越大。"""
    W = W_screw * l_heel / (l_work + l_heel) * eta
    return {"W": W, "ratio": l_heel / (l_work + l_heel), "heel": W_screw - W / eta}


def eccentric(Q: float, L: float, D: float, e: float, mu1=0.15, mu2=0.15, gamma: float = 90.0) -> dict:
    """圆偏心夹紧：偏心轮直径 D、偏心距 e，手柄长 L，作用力 Q；γ 为偏心轮从起始位置转过的角度（°，90° 左右时升角最大）。
    把偏心轮看成绕在基圆上的斜楔：升角 α_γ = atan(e·sin γ/(D/2 − e·cos γ))；转动中心到夹紧点的距离 ρ ≈ (D/2 − e cos γ)/cos α_γ。最大升角 sin α_max = e/(D/2)（在 cos γ = e/(D/2) 处）。
    W ≈ Q·L / (ρ·tan(α_γ + φ2) + r·tan φ1)（φ2 夹紧点的摩擦角，φ1 转轴处的摩擦角，转轴半径 r 取 D/8）。
    自锁条件（最不利的 γ = 90°）：e/(D/2) ≤ tan φ，即 2e/D ≤ μ，常写成 D/e ≥ 2/μ（μ = 0.1 时 D/e ≥ 20，0.15 时约 14）。"""
    g = math.radians(gamma)
    R = D / 2
    a = math.atan(e * math.sin(g) / (R - e * math.cos(g)))
    rho = (R - e * math.cos(g)) / math.cos(a)
    p1, p2 = math.atan(mu1), math.atan(mu2)
    W = Q * L / (rho * math.tan(a + p2) + (D / 8) * math.tan(p1))
    a_max = math.asin(e / R)                         # 升角最大出现在 cos γ = e/R 处，sin α_max = e/R
    # 自锁：最不利位置的升角不超过两处摩擦角之和（工件处 + 转轴处）；只按工件处一个摩擦角判断更安全
    return {"W": W, "i": W / Q, "lift_deg": math.degrees(a), "lift_max_deg": math.degrees(a_max), "rho": rho,
            "self_lock": a_max <= p1 + p2, "self_lock_safe": 2 * e / D <= mu2, "D_over_e_min": 2 / mu2, "stroke": 2 * e}


def lever(Q: float, l_in: float, l_out: float, eta=0.95) -> float:
    """杠杆（铰链压板）：W = Q·l_in/l_out·η。"""
    return Q * l_in / l_out * eta


def hinge(Q: float, alpha: float, beta: float = 1.0) -> dict:
    """单臂铰链增力机构：连杆与夹紧方向的夹角 α（°），β 为铰链摩擦引起的附加角（°，常取 1–3°，教学取值）。
    W = Q / tan(α + β)；α 越小增力越大，但行程越小，α → 0 时增力很大且对尺寸变化敏感。"""
    W = Q / math.tan(math.radians(alpha + beta))
    return {"W": W, "i": W / Q}


# ---------------------------------------------------------------- 动力装置
def cylinder(D: float, p: float, eta=0.85, d_rod: float = 0.0, push=True) -> float:
    """气缸、液压缸的输出力（N）：推力 Q = π/4·D²·p·η；拉力用有杆腔面积 π/4·(D² − d²)。p 单位 MPa。"""
    A = math.pi / 4 * (D ** 2 - (0 if push else d_rod ** 2))
    return A * p * eta


ROD = {12: 6, 16: 6, 20: 8, 25: 10, 32: 12, 40: 16, 50: 20, 63: 20, 80: 25, 100: 25, 125: 32, 160: 40, 200: 40}   # 常见的缸径与活塞杆直径（以产品样本为准）


def cylinder_bore(Q: float, p: float, eta=0.85, series=(25, 32, 40, 50, 63, 80, 100, 125, 160, 200), pull=False) -> dict:
    """按需要的力 Q 和最低压力 p 选标准缸径（缸径系列参照 ISO 3320 一类优先数，以产品样本为准）。
    pull=True：靠活塞杆拉回夹紧（转角缸、拉杆式压板），有效面积要扣除活塞杆。"""
    for D in series:
        q = cylinder(D, p, eta, ROD.get(D, 0.4 * D), push=not pull)
        if q >= Q:
            break
    else:
        D, q = None, None
    Dmin = math.sqrt(4 * Q / (math.pi * p * eta))
    return {"D_min": Dmin, "D": D, "Q": q, "rod": ROD.get(D) if D else None}


def diaphragm(D: float, d: float, p: float) -> float:
    """平膜片气室的有效推力（近似）：有效直径取 (D + d)/2 时，Q ≈ π/16·(D + d)²·p（行程起始位置；行程越大推力越小）。"""
    return math.pi / 16 * (D + d) ** 2 * p


# ---------------------------------------------------------------- 对刀、导向、安装误差
def bushing_drill_error(bush_id: tuple, drill: tuple, H: float, s: float, B: float = 0.0, liner_X: float = 0.0) -> dict:
    """钻套引导钻头的位置误差。bush_id = (基本尺寸, ES, EI)，drill = (基本尺寸, es, ei)；H 钻套导向长度，s 钻套下端到工件表面的距离，
    B 孔深（取孔深中点处的偏移，国内教材的写法），liner_X 可换、快换钻套与衬套之间的最大间隙。
    最不利时钻头上端靠一侧、下端靠另一侧，钻头轴线过钻套中点、歪斜 X/H，离钻套中点 z 处偏离钻套轴线 z·X/H：
    工件表面处 X/2 + s·X/H，孔深中点处 (H/2 + s + B/2)·X/H。再加上钻套在衬套里的偏移 liner_X/2。占用的位置度公差带为 2 倍。"""
    X = (bush_id[0] + bush_id[1]) - (drill[0] + drill[2])
    off_surface = X / 2 + s * X / H
    off = (H / 2 + s + B / 2) * X / H + liner_X / 2
    return {"X": X, "offset": off, "zone": 2 * off, "offset_surface": off_surface, "tilt": X / H}


def key_alignment(slot_W: tuple, key_w: tuple, spacing: float, length: float, one_side=False) -> dict:
    """定位键在机床 T 形槽里的间隙引起的夹具偏转：两键之间的距离 spacing，转角最大 X_max/spacing。
    在工件上一段长 length 的加工面（如键槽）上，造成的歪斜量 length·X_max/spacing。
    安装时把两个键都靠向 T 形槽的同一侧（one_side=True），这项误差只剩槽侧面的直线度，按 0 计。"""
    X = (slot_W[0] + slot_W[1]) - (key_w[0] + key_w[2])
    th = 0.0 if one_side else X / spacing
    return {"X": X, "theta": th, "skew": length * th}


def parallelism_skew(t_per_100: float, length: float) -> float:
    """夹具上两个要素的平行度 t（每 100 mm），在长 length 的加工面上造成的歪斜量。"""
    return t_per_100 * length / 100


def budget(items: dict, T: float, method="extreme") -> dict:
    """夹具精度：ΔD + ΔJ + ΔA + ΔT + ΔG ≤ T。items：{名称: 变动范围}；method="extreme" 直接相加，"rss" 平方和开方。
    返回合计、余量、是否满足，以及按 1/3 判据检查定位误差（"ΔD" 项）。"""
    vals = list(items.values())
    tot = sum(vals) if method == "extreme" else math.sqrt(sum(v * v for v in vals))
    return {"total": tot, "margin": T - tot, "ok": tot <= T + 1e-12, "items": items}


# ---------------------------------------------------------------- 薄壁件的夹紧变形
def ring_clamp(n_jaws: int, W_total: float, R: float, E: float, b: float, t: float, arc_deg: float = 0.0, m=400, n_terms=60) -> dict:
    """薄壁圆环用 n 个卡爪径向夹紧（总夹紧力 W_total 平均分给各爪；arc_deg > 0 时每爪的力均匀分布在这么大的圆弧上，
    相当于软爪、扇形爪）。按不可伸长薄圆环的傅里叶级数解：径向线载荷的 n 阶分量 q_k，
    径向位移 w_k = q_k·R⁴/(EI·(k² − 1)²)（k ≥ 2；k = 0、1 阶是均匀压缩和刚体移动，不产生圆度误差）。
    R 中径半径，b 宽度，t 壁厚，I = b·t³/12。返回各角度的径向位移和圆度误差（最大 − 最小，松开后就是车出的孔的圆度误差）。
    两点夹紧时沿载荷方向直径的减小量 = 0.1488·W·R³/(EI)，与 Roark 手册的经典结果一致（程序核对）。"""
    I = b * t ** 3 / 12
    EI = E * I
    Wj = W_total / n_jaws
    sub = max(1, int(arc_deg / 2)) if arc_deg > 0 else 1   # 圆弧分布的载荷用若干点力近似
    loads = []
    for j in range(n_jaws):
        c = 2 * math.pi * j / n_jaws
        for s in range(sub):
            off = 0.0 if sub == 1 else math.radians(arc_deg) * (s / (sub - 1) - 0.5)
            loads.append((c + off, Wj / sub))
    th = [2 * math.pi * i / m for i in range(m)]
    w = []
    for a in th:
        tot = 0.0
        for k in range(2, n_terms + 1):
            qk = sum(P * math.cos(k * (a - ak)) for ak, P in loads) / (math.pi * R)
            tot += qk * R ** 4 / (EI * (k * k - 1) ** 2)
        w.append(tot)                                       # 向内为正
    return {"w": w, "theta": th, "roundness": max(w) - min(w), "EI": EI}


# ---------------------------------------------------------------- 夹具体与回转夹具
def unbalance_force(m_kg: float, e_mm: float, n_rpm: float) -> float:
    """车床夹具不平衡引起的离心力（N）：F = m·e·ω²。"""
    w = 2 * math.pi * n_rpm / 60
    return m_kg * e_mm / 1000 * w * w


def counterweight(m_kg: float, e_mm: float, r_cw_mm: float) -> float:
    """平衡块质量：m_cw·r_cw = m·e（静平衡）。"""
    return m_kg * e_mm / r_cw_mm


def strap_stress(W_screw: float, l_work: float, l_heel: float, b: float, h: float, slot_w: float) -> dict:
    """移动压板的强度：最大弯矩在螺栓孔处，M = W_work·l_work（= 后支点力 × l_heel），
    截面去掉长槽后宽 b − slot_w、高 h，抗弯截面系数 (b − slot_w)·h²/6。"""
    Ww = W_screw * l_heel / (l_work + l_heel)
    M = Ww * l_work
    Z = (b - slot_w) * h * h / 6
    return {"M_Nmm": M, "sigma": M / Z}


# ---------------------------------------------------------------- 夹具数据文件与评审
STD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std"))


def load_fixture(fid: str) -> dict | None:
    path = os.path.join(STD, f"{fid}_fixture.yaml")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def analyse(fx: dict) -> dict:
    """按夹具数据（std/<编号>_fixture.yaml）算：切削力、需要的夹紧力、手动（和气动）夹紧能给出的夹紧力、精度预算。"""
    c = fx["cutting"]
    f = slot_forces(c["D"], c["z"], c["fz"], c["ap"], c.get("material", "45"))
    Ks = safety_factor(**fx["safety"])
    cl = fx["clamping"]
    need = vblock_clamp_required(axial_to_resist(f, cl.get("axial_stop_takes_Fx", True)), f["Fy_peak"], f["Fz_peak"], Ks["K"],
                                 cl["mu1"], cl["mu2"], fx["locating"]["alpha"], cl.get("G", 0.0), False,
                                 cl.get("r_f", 1.0), cl.get("r_c", 1.0), cl.get("r_v", 1.0))
    sc = screw_clamp(cl["hand_force"], cl["wrench"], cl["thread_d"], cl["thread_P"], cl["mu_thread"], cl["mu_end"], cl.get("r_end"))
    st = strap_clamp(sc["W"], cl["l_work"], cl["l_heel"])
    W_have = st["W"] * cl["count"]
    res = {"forces": f, "K": Ks, "need": need, "screw": sc, "strap": st, "W_have": W_have, "ok_clamp": W_have >= need["W"]}
    if "pneumatic" in fx:                            # 机动夹紧：K4 取 1.0；气缸代替螺柱在压板中部下拉（拉力），经杠杆比传到工件
        pn = fx["pneumatic"]
        Kp = safety_factor(**(fx["safety"] | {"K4": "机动", "K5": "方便"}))
        need_p = vblock_clamp_required(axial_to_resist(f, cl.get("axial_stop_takes_Fx", True)), f["Fy_peak"], f["Fz_peak"], Kp["K"],
                                       cl["mu1"], cl["mu2"], fx["locating"]["alpha"], cl.get("G", 0.0), False,
                                       cl.get("r_f", 1.0), cl.get("r_c", 1.0), cl.get("r_v", 1.0))
        per = need_p["W"] / cl["count"] / (cl["l_heel"] / (cl["l_work"] + cl["l_heel"]) * 0.95)
        res["need_pneumatic"] = need_p
        res["cyl"] = cylinder_bore(per, pn["p_min"], pn.get("eta", 0.85), pull=True)
    res["budgets"] = {}
    for b in fx.get("budgets", []):
        res["budgets"][b["what"]] = budget(b["items"], b["T"], b.get("method", "extreme")) | {"T": b["T"], "method": b.get("method", "extreme")}
    return res


def review(fid: str, data: dict | None = None) -> list:
    """AI 工艺评审员调用：夹具的夹紧力是否够、精度预算是否满足。返回 [(级别, 文字)]。
    data：学生自己设计的夹具数据（格式同 std/<编号>_fixture.yaml，写在工序的 fixture 里，任务单 TS-52-1）；没有时读数字工厂的参照数据。"""
    fx = data or load_fixture(fid)
    if not fx:
        return []
    r = analyse(fx)
    out = []
    if not r["ok_clamp"]:
        out.append(("error", "夹具 {} 的夹紧力约 {:.0f} N，小于需要的 {:.0f} N（起控制作用的是“{}”），加工中工件可能移动。"
                    .format(fid, r["W_have"], r["need"]["W"], GOV_ZH[r["need"]["governing"]])))
    for what, b in r["budgets"].items():
        if not b["ok"]:
            out.append(("error", "夹具 {} 的“{}”精度预算合计 {:.4f} mm，超过工序公差 {:g} mm。".format(fid, what, b["total"], b["T"])))
        elif b["margin"] < 0.1 * b["T"]:
            out.append(("warning", "夹具 {} 的“{}”精度预算余量只有 {:.4f} mm，不到公差的 10%，机床和刀具误差没有余地。".format(fid, what, b["margin"])))
    return out


GOV_ZH = {"lift": "不被抬起", "slide_out": "不滑出 V 形块", "rotate": "不绕轴线转动", "axial": "轴向不滑动"}


def hertz_line(F_per_mm: float, R1: float, E1=210000.0, nu1=0.3, E2=210000.0, nu2=0.3, R2: float = float("inf")) -> dict:
    """线接触的 Hertz 公式：单位长度载荷 F'（N/mm），两圆柱半径 R1、R2（平面取无穷大）。
    1/E* = (1 − ν1²)/E1 + (1 − ν2²)/E2，1/R* = 1/R1 + 1/R2；接触半宽 b = √(4F′R*/(πE*))，最大接触压力 p0 = √(F′E*/(πR*))。"""
    Es = 1 / ((1 - nu1 ** 2) / E1 + (1 - nu2 ** 2) / E2)
    Rs = 1 / (1 / R1 + (0 if R2 == float("inf") else 1 / R2))
    return {"b": math.sqrt(4 * F_per_mm * Rs / (math.pi * Es)), "p0": math.sqrt(F_per_mm * Es / (math.pi * Rs)), "E_star": Es}


def indexing_error(R: float, X_pin: float, L_pin: float, hole_pitch: float, X_axis: float) -> dict:
    """分度误差（教学模型）：对定销与分度盘孔的间隙 X_pin，作用在半径 L_pin 处；分度盘孔距（角向）误差 hole_pitch（弧长，mm，在 L_pin 处）；
    分度盘回转轴的间隙 X_axis。工件上半径 R 处的位置变动 ≈ (X_pin + hole_pitch)·R/L_pin + X_axis。"""
    ang = (X_pin + hole_pitch) / L_pin
    return {"angle_rad": ang, "angle_sec": math.degrees(ang) * 3600, "at_R": ang * R + X_axis}
