"""常用机构的动力学模型：按参数生成 MJCF（搬自问渠数字工厂第 12 轮，ADR-0056）。

参数为示例几何（按你的设计改），长度单位米（MuJoCo 内部单位）；构件密度取材料库 45 钢。

坐标与零件库一致：平面机构在竖直 XZ 平面内，转角绕 −Y（从前方看逆时针为正），重力 −Z；齿轮轴沿 Y。
构件按钢（7850 kg/m³）算质量和惯量（杆 = 长方体，齿轮 / 带轮 = 分度圆圆柱）。
运动副的闭合方式：
  四杆、曲柄滑块 —— 连接约束（connect）闭环；
  齿轮系、WQR-105、蜗杆蜗轮、带传动、丝杠 —— 关节比例约束（joint equality，传动比）；
  凸轮、槽轮、棘轮 —— 函数耦合（从动件位置 = f(主动件转角)，由 cae/mbd.py 按虚功原理把从动件受力反作用到主动件）。
"""
import math

from analysis.common import materials

RHO = materials.get("45-QT")["density_kg_m3"]

DEFAULTS = {
    "C-LNK-4BAR": {"crank_m": 0.04, "coupler_m": 0.12, "rocker_m": 0.08, "ground_m": 0.1, "link_width_m": 0.012, "link_thickness_m": 0.006},
    "C-LNK-SLIDER": {"crank_m": 0.04, "rod_m": 0.14, "offset_m": 0.0, "link_width_m": 0.012, "link_thickness_m": 0.006},
    "C-CAM-DISC": {"base_radius_m": 0.04, "roller_radius_m": 0.008, "lift_m": 0.02, "rise_deg": 120, "far_dwell_deg": 60,
                   "return_deg": 120, "thickness_m": 0.01},
    "C-GER-TRAIN": {"module1_mm": 2, "z1": 20, "z2": 40, "face1_mm": 12, "module2_mm": 2.5, "z3": 18, "z4": 54, "face2_mm": 16},
    "C-RED-WQR105": {"module1_mm": 2, "z1": 24, "z2": 72, "face1_mm": 30, "module2_mm": 3, "z3": 20, "z4": 70, "face2_mm": 40},
    "C-GNV-GENEVA": {"slots": 4, "crank_m": 0.05, "thickness_m": 0.008},
    "C-RAT-RATCHET": {"teeth": 12, "wheel_radius_m": 0.05, "swing_deg": 40, "thickness_m": 0.008},
    "C-WRM-WORM": {"module_mm": 2, "worm_starts": 1, "wheel_teeth": 30, "diameter_factor": 10, "wheel_face_mm": 14},
    "C-BLT-BELT": {"d1_m": 0.06, "d2_m": 0.12, "center_m": 0.25, "width_m": 0.02},
    "C-SCN-LEAD": {"diameter_mm": 16, "lead_mm": 4, "screw_length_m": 0.3, "nut_length_m": 0.04},
}
NAMES = {
    "C-LNK-4BAR": "曲柄摇杆机构（铰链四杆）", "C-LNK-SLIDER": "曲柄滑块机构", "C-CAM-DISC": "盘形凸轮 + 直动滚子从动件",
    "C-GER-TRAIN": "两级齿轮系", "C-RED-WQR105": "WQR-105 减速器传动链", "C-GNV-GENEVA": "外槽轮机构", "C-RAT-RATCHET": "棘轮机构",
    "C-WRM-WORM": "蜗杆蜗轮", "C-BLT-BELT": "开口带传动", "C-SCN-LEAD": "丝杠螺母",
}
# 主动件关节（驱动加在这里）与各构件、关节的中文名
DRIVER = {"C-LNK-4BAR": "crank", "C-LNK-SLIDER": "crank", "C-CAM-DISC": "cam", "C-GER-TRAIN": "shaft1", "C-RED-WQR105": "shaft1",
          "C-GNV-GENEVA": "crank", "C-RAT-RATCHET": "crank", "C-WRM-WORM": "worm", "C-BLT-BELT": "pulley1", "C-SCN-LEAD": "screw"}
LABELS = {"crank": "曲柄", "coupler": "连杆", "rocker": "摇杆", "rod": "连杆", "slider": "滑块", "cam": "凸轮", "follower": "从动件",
          "shaft1": "输入轴", "shaft2": "中间轴", "shaft3": "输出轴", "wheel": "从动轮", "worm": "蜗杆", "pulley1": "主动带轮",
          "pulley2": "从动带轮", "screw": "丝杠", "nut": "螺母（滑台）"}


# 没有缺省值的可选参数（不给就不核查、判 unknown——不编造参数）
OPTIONAL = {"C-BLT-BELT": ("initial_tension_n", "mu", "ea_n")}


def params(mid, given=None):
    if mid not in DEFAULTS:
        raise ValueError(f"零件库里没有可做动力学的机构“{mid}”")
    p = dict(DEFAULTS[mid])
    opt = OPTIONAL.get(mid, ())
    for k, v in (given or {}).items():
        if (k in p or k in opt) and v not in (None, ""):
            p[k] = float(v)
    return p


def belt_check(given, torque_driver_nm):
    """带传动的打滑、蠕滑与轴上拉力（《多体动力学》书第 24 章线索第 38 条，问渠 CAD 0.3.8 细则）。
    原来库里的带只按传动比 1:2 刚性传动：30 N·m 照样传，而 μ 0.3、初拉力 150 N 时欧拉极限只有其 1/4；带轮轴上没有带的拉力。
    给了初拉力 F0、摩擦系数 μ（ea_n 可选）就核：小带轮包角 α，打滑时 F1/F2 = e^{μα}，有效拉力极限 ΔF = 2F0(e^{μα} − 1)/(e^{μα} + 1)；
    工作时 F1 = F0 + F/2、F2 = F0 − F/2（F = 主动轮力矩 / r1）；速比计蠕滑 (1 + ε₁)/(1 + ε₂)·D2/D1（ε = F/EA）；
    轴上拉力 = 紧边、松边拉力的合力。没给就判 unknown"""
    p = params("C-BLT-BELT", given)
    D1, D2, a = p["d1_m"], p["d2_m"], p["center_m"]
    beta = math.asin((D2 - D1) / (2 * a))
    alpha = math.pi - 2 * beta                       # 小带轮包角
    out = {"wrap_small_deg": math.degrees(alpha)}
    if "initial_tension_n" not in p or "mu" not in p:
        return out | {"status": "unknown", "note": "没给初拉力 initial_tension_n 和摩擦系数 mu，打滑、轴上拉力未核查"}
    F0, mu = p["initial_tension_n"], p["mu"]
    k = math.exp(mu * alpha)
    dF_max = 2 * F0 * (k - 1) / (k + 1)
    F = abs(torque_driver_nm) / (D1 / 2)
    F1, F2 = F0 + F / 2, F0 - F / 2
    # 两边直线段与中心线夹 β：紧边、松边拉力的合力（作用在两个带轮轴上，大小相同、方向相反）
    shaft = math.sqrt(F1 * F1 + F2 * F2 + 2 * F1 * F2 * math.cos(2 * beta))
    out |= {"slip_ratio_e_mu_alpha": k, "effective_pull_limit_n": dF_max, "torque_limit_driver_nm": dF_max * D1 / 2,
            "torque_limit_driven_nm": dF_max * D2 / 2, "effective_pull_n": F, "tight_side_n": F1, "slack_side_n": F2,
            "shaft_load_n": shaft, "safety_factor": dF_max / F if F > 0 else math.inf,
            "status": "pass" if F <= dF_max else "fail"}
    if "ea_n" in p:
        e1, e2 = F1 / p["ea_n"], F2 / p["ea_n"]
        out["transmission_ratio_with_creep"] = (1 + e1) / (1 + e2) * D2 / D1
    return out


# ---------------------------------------------------------------- 运动学（与零件库 generators/c_mech.py 相同的公式，测试互核）
def four_bar_solve(p, th2, branch=1):
    a, b, c, d = p["crank_m"], p["coupler_m"], p["rocker_m"], p["ground_m"]
    Ax, Az = a * math.cos(th2), a * math.sin(th2)
    vx, vz = d - Ax, -Az
    L = math.hypot(vx, vz)
    if L > b + c or L < abs(b - c):
        return None
    x = (b * b - c * c + L * L) / (2 * L)
    h = math.sqrt(max(0.0, b * b - x * x))
    ux, uz = vx / L, vz / L
    Bx, Bz = Ax + x * ux - branch * h * uz, Az + x * uz + branch * h * ux
    return (Ax, Az), (Bx, Bz), math.atan2(Bz - Az, Bx - Ax), math.atan2(Bz, Bx - d)


def slider_crank_x(p, th):
    r, l, e = p["crank_m"], p["rod_m"], p["offset_m"]
    s = r * math.sin(th) - e
    if abs(s) > l:
        return None
    return r * math.cos(th) + math.sqrt(l * l - s * s)


def cam_lift(p, phi_deg):
    h, r1, d1, r2 = p["lift_m"], p["rise_deg"], p["far_dwell_deg"], p["return_deg"]
    f = phi_deg % 360
    if f < r1:
        return h / 2 * (1 - math.cos(math.pi * f / r1))
    if f < r1 + d1:
        return h
    if f < r1 + d1 + r2:
        return h / 2 * (1 + math.cos(math.pi * (f - r1 - d1) / r2))
    return 0.0


def geneva_wheel_angle(p, deg):
    n, R = int(p["slots"]), p["crank_m"]
    C = R / math.sin(math.pi / n)
    lim = math.pi / 2 - math.pi / n
    turns = math.floor(deg / 360)
    alpha = math.radians(deg - 360 * turns) - math.pi
    if alpha < -lim:
        beta = -math.pi / n
    elif alpha > lim:
        beta = math.pi / n
    else:
        beta = math.atan2(R * math.sin(alpha), C - R * math.cos(alpha))
    return -turns * 2 * math.pi / n - beta


def ratchet_state(p, deg):
    z, sw = int(p["teeth"]), math.radians(p["swing_deg"])
    pitch = 2 * math.pi / z
    th = math.radians(deg)
    n, f = divmod(th, 2 * math.pi)
    psi = sw * (1 - math.cos(f)) / 2
    idle = sw - pitch
    adv = max(0.0, psi - idle) if f <= math.pi else pitch
    return psi, n * pitch + adv


# ---------------------------------------------------------------- 函数耦合（凸轮、槽轮、棘轮）
def coupling_fn(name, p):
    """返回 f(q_主动, 弧度) → 从动件位置（米或弧度）"""
    if name == "cam":
        return lambda q: cam_lift(p, math.degrees(q))
    if name == "geneva":
        return lambda q: geneva_wheel_angle(p, math.degrees(q))
    if name == "ratchet_rocker":
        return lambda q: ratchet_state(p, math.degrees(q))[0]
    if name == "ratchet_wheel":
        return lambda q: ratchet_state(p, math.degrees(q))[1]
    raise ValueError(f"不认识的耦合“{name}”")


def couplings(mid, p):
    if mid == "C-CAM-DISC":
        return [{"driver": "cam", "follower": "follower", "fn": "cam", "params": p}]
    if mid == "C-GNV-GENEVA":
        return [{"driver": "crank", "follower": "wheel", "fn": "geneva", "params": p}]
    if mid == "C-RAT-RATCHET":
        return [{"driver": "crank", "follower": "rocker", "fn": "ratchet_rocker", "params": p},
                {"driver": "crank", "follower": "wheel", "fn": "ratchet_wheel", "params": p}]
    return []


def ratio_couplings(mid, p):
    """传动比耦合：[(从动关节, 主动关节, k)]，从动 = k × 主动（关节零位都是 0）。齿轮系、减速器、蜗杆、带、丝杠用。"""
    if mid in ("C-GER-TRAIN", "C-RED-WQR105"):
        return [("shaft2", "shaft1", -p["z1"] / p["z2"]), ("shaft3", "shaft2", -p["z3"] / p["z4"])]
    if mid == "C-WRM-WORM":
        return [("wheel", "worm", p["worm_starts"] / p["wheel_teeth"])]
    if mid == "C-BLT-BELT":
        return [("pulley2", "pulley1", p["d1_m"] / p["d2_m"])]
    if mid == "C-SCN-LEAD":
        return [("nut", "screw", p["lead_mm"] / 1000 / (2 * math.pi))]
    return []


def _ratio_tendons(mid, p):
    """传动比耦合写成固定肌腱 + 肌腱等式（肌腱长 = 从动 − k × 主动，保持为 0）。
    原来用关节等式 <joint polycoef>：MuJoCo 估它的正则项时按两个关节各自的逆权重相加、不乘传动比的平方，
    丝杠（k ≈ 6e-4 m/rad）受 200 N 时螺母偏离 954 mm、蜗轮受 30 N·m 落后 15°，结果仍报正常——
    《多体动力学》书第 24 章线索第 37 条（问渠 CAD 0.3.6 细则 C2）。肌腱等式的正则项按肌腱的有效逆惯量算，偏差回到亚毫米。"""
    ten, eq = [], []
    for n, (out, inp, k) in enumerate(ratio_couplings(mid, p)):
        ten.append(f'<fixed name="ratio{n}"><joint joint="{out}" coef="1"/><joint joint="{inp}" coef="{-k!r}"/></fixed>')
        eq.append(f'<tendon tendon1="ratio{n}" {EQ}/>')
    return ten, eq


# ---------------------------------------------------------------- MJCF
HINGE_Y = 'type="hinge" axis="0 -1 0"'


def _bar(name, L, w, t, rgba, extra=""):
    """沿本构件 +X 的杆（长 L），两端销孔处画小圆柱"""
    return ('<geom name="{n}" type="box" pos="{h} 0 0" size="{h} {t2} {w2}" density="{rho}" rgba="{c}"/>'
            '<geom type="cylinder" pos="{L} 0 0" euler="90 0 0" size="{r} {t}" mass="0" rgba="0.3 0.3 0.3 1" group="2"/>{x}').format(
        n=name, h=L / 2, t2=t / 2, w2=w / 2, rho=RHO, c=rgba, L=L, r=w * 0.45, t=t * 0.8, x=extra)


def _disc(r, b, rgba, axis="y"):
    eu = "90 0 0" if axis == "y" else "0 90 0"
    return f'<geom type="cylinder" euler="{eu}" size="{r} {b / 2}" density="{RHO}" rgba="{rgba}"/>'


BLUE, GREY, YEL = "0.24 0.47 0.67 1", "0.8 0.82 0.84 1", "0.95 0.72 0.02 1"
EQ = 'solref="0.002 1" solimp="0.95 0.99 0.001"'


LOOP_MIDS = ("C-LNK-4BAR", "C-LNK-SLIDER")      # 用 connect 软约束闭环的机构
LOOP_GAP_REL = 1e-3                              # 闭环允许拉开：最短构件的 0.1 %
LOOP_TAU_MAX = 0.002                             # 缺省（MuJoCo solref 的时间常数）
DT_MAX = 0.0002


def _links(mid, p):
    if mid == "C-LNK-4BAR":
        return [p["crank_m"], p["coupler_m"], p["rocker_m"]]
    return [p["crank_m"], p["rod_m"]]


def loop_tau(mid, given, w_max):
    """闭环软约束的时间常数 τ 与步长 h。《多体动力学》书第 17 章线索第 23 条（问渠 CAD 0.3.8 细则）：MuJoCo 的参考加速度不含 J̇q̇，
    闭合点的向心加速度只能靠约束拉开来补，穿透 ≈ τ²·|J̇q̇|（实测是这个估计的 0.79–0.92 倍）；缺省 τ = 2 ms 时
    600 rpm 拉开 1.1 mm、驱动力矩逐点误差 12 %。按 τ²·a_c ≤ 最短构件的 0.1 % 选 τ，a_c 取 ω²·（运动构件长度之和，偏大的估计），
    步长 h ≤ τ/2。返回 (τ, h)"""
    if mid not in LOOP_MIDS or not w_max:
        return LOOP_TAU_MAX, DT_MAX
    p = params(mid, given)
    links = _links(mid, p)
    a_c = w_max ** 2 * sum(links)
    tau = min(LOOP_TAU_MAX, math.sqrt(LOOP_GAP_REL * min(links) / a_c))
    return tau, min(DT_MAX, tau / 2)


def loop_gap(mid, given, q):
    """闭环两点的实际距离（m），q：关节名 → 转角 / 位移序列（MuJoCo 的关节坐标，转角绕 −Y）"""
    import numpy as np

    p = params(mid, given)
    if mid == "C-LNK-4BAR":
        a, b, c, d = p["crank_m"], p["coupler_m"], p["rocker_m"], p["ground_m"]
        t1, t2 = np.asarray(q["crank"]), np.asarray(q["crank"]) + np.asarray(q["coupler"])
        e1 = np.c_[a * np.cos(t1) + b * np.cos(t2), a * np.sin(t1) + b * np.sin(t2)]
        t4 = np.asarray(q["rocker"])
        e2 = np.c_[d + c * np.cos(t4), c * np.sin(t4)]
        return np.linalg.norm(e1 - e2, axis=1)
    if mid == "C-LNK-SLIDER":
        r, L, e = p["crank_m"], p["rod_m"], p["offset_m"]
        t1, t2 = np.asarray(q["crank"]), np.asarray(q["crank"]) + np.asarray(q["rod"])
        e1 = np.c_[r * np.cos(t1) + L * np.cos(t2), r * np.sin(t1) + L * np.sin(t2)]
        e2 = np.c_[np.asarray(q["slider"]), np.full(len(t1), e)]
        return np.linalg.norm(e1 - e2, axis=1)
    return None


def mjcf(mid, given=None, loop_tau_s=None, timestep_s=None):
    p = params(mid, given)
    body, eq = [], []
    EQL = EQ if loop_tau_s is None else f'solref="{loop_tau_s!r} 1" solimp="0.95 0.99 0.001"'
    if mid == "C-LNK-4BAR":
        a, b, c, d, w, t = (p[k] for k in ("crank_m", "coupler_m", "rocker_m", "ground_m", "link_width_m", "link_thickness_m"))
        body.append('<body name="crank"><joint name="crank" {h}/>{g}<body name="coupler" pos="{a} 0 0"><joint name="coupler" {h}/>{g2}'
                    '<site name="coupler_mid" pos="{bm} 0 0"/><site name="coupler_end" pos="{b} 0 0"/></body></body>'.format(
                        h=HINGE_Y, g=_bar("crank", a, w, t, BLUE), a=a, g2=_bar("coupler", b, w, t, GREY), bm=b / 2, b=b))
        body.append('<body name="rocker" pos="{d} 0 0"><joint name="rocker" {h}/>{g}<site name="rocker_end" pos="{c} 0 0"/></body>'.format(
            d=d, h=HINGE_Y, g=_bar("rocker", c, w, t, BLUE), c=c))
        # 用两个点（site）定义连接：约束“两点重合”，与模型的零位无关
        eq.append(f'<connect site1="coupler_end" site2="rocker_end" {EQL}/>')
    elif mid == "C-LNK-SLIDER":
        r, l, e, w, t = (p[k] for k in ("crank_m", "rod_m", "offset_m", "link_width_m", "link_thickness_m"))
        body.append('<body name="crank"><joint name="crank" {h}/>{g}<body name="rod" pos="{r} 0 0"><joint name="rod" {h}/>{g2}'
                    '<site name="rod_end" pos="{l} 0 0"/></body></body>'.format(h=HINGE_Y, g=_bar("crank", r, w, t, BLUE), r=r,
                                                                         g2=_bar("rod", l, w, t, GREY), l=l))
        body.append(f'<body name="slider" pos="0 0 {e}"><joint name="slider" type="slide" axis="1 0 0"/>'
                    f'<geom type="box" size="{1.2 * w} {1.5 * t} {w}" density="{RHO}" rgba="{BLUE}"/><site name="pin" pos="0 0 0"/></body>')
        eq.append(f'<connect site1="rod_end" site2="pin" {EQL}/>')
    elif mid == "C-CAM-DISC":
        r0, rr, h, t = (p[k] for k in ("base_radius_m", "roller_radius_m", "lift_m", "thickness_m"))
        body.append(f'<body name="cam"><joint name="cam" {HINGE_Y}/>{_disc(r0 + h / 2, t, BLUE)}</body>')
        body.append(f'<body name="follower" pos="0 0 {r0 + rr}"><joint name="follower" type="slide" axis="0 0 1"/>'
                    f'<geom type="cylinder" euler="90 0 0" size="{rr} {t * 0.45}" density="{RHO}" rgba="{YEL}"/>'
                    f'<geom type="box" pos="0 0 {rr + 0.04}" size="0.006 {t * 0.45} 0.04" density="{RHO}" rgba="{GREY}"/></body>')
    elif mid in ("C-GER-TRAIN", "C-RED-WQR105"):
        m1, m2, b1, b2 = p["module1_mm"] / 1000, p["module2_mm"] / 1000, p["face1_mm"] / 1000, p["face2_mm"] / 1000
        z1, z2, z3, z4 = (p[k] for k in ("z1", "z2", "z3", "z4"))
        a1, a2 = m1 * (z1 + z2) / 2, m2 * (z3 + z4) / 2
        y2 = b1 / 2 + b2 / 2 + 0.01
        body.append(f'<body name="shaft1"><joint name="shaft1" {HINGE_Y}/>{_disc(m1 * z1 / 2, b1, BLUE)}</body>')
        body.append(f'<body name="shaft2" pos="{a1} 0 0"><joint name="shaft2" {HINGE_Y}/>{_disc(m1 * z2 / 2, b1, GREY)}<body pos="0 {y2} 0">{_disc(m2 * z3 / 2, b2, BLUE)}</body></body>')
        body.append(f'<body name="shaft3" pos="{a1 + a2} {y2} 0"><joint name="shaft3" {HINGE_Y}/>{_disc(m2 * z4 / 2, b2, GREY)}</body>')
    elif mid == "C-WRM-WORM":
        m, z1, z2, q = p["module_mm"] / 1000, p["worm_starts"], p["wheel_teeth"], p["diameter_factor"]
        d1, d2 = m * q, m * z2
        body.append(f'<body name="worm" pos="0 0 {(d1 + d2) / 2}"><joint name="worm" type="hinge" axis="1 0 0"/>'
                    f'<geom type="cylinder" euler="0 90 0" size="{d1 / 2} {3 * math.pi * m}" density="{RHO}" rgba="{BLUE}"/></body>')
        body.append('<body name="wheel"><joint name="wheel" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(d2 / 2, p["wheel_face_mm"] / 1000, GREY)))
    elif mid == "C-BLT-BELT":
        D1, D2, a, w = p["d1_m"], p["d2_m"], p["center_m"], p["width_m"]
        body.append(f'<body name="pulley1"><joint name="pulley1" {HINGE_Y}/>{_disc(D1 / 2, w, BLUE)}</body>')
        body.append(f'<body name="pulley2" pos="{a} 0 0"><joint name="pulley2" {HINGE_Y}/>{_disc(D2 / 2, w, GREY)}</body>')
    elif mid == "C-SCN-LEAD":
        d, Ls, Ln = p["diameter_mm"] / 1000, p["screw_length_m"], p["nut_length_m"]
        body.append('<body name="screw"><joint name="screw" type="hinge" axis="1 0 0"/>'
                    f'<geom type="cylinder" euler="0 90 0" size="{d / 2} {Ls / 2}" density="{RHO}" rgba="{GREY}"/></body>')
        body.append('<body name="nut"><joint name="nut" type="slide" axis="1 0 0"/>'
                    f'<geom type="box" size="{Ln / 2} {d} {d}" density="{RHO}" rgba="{BLUE}"/></body>')
    elif mid == "C-GNV-GENEVA":
        n, R, t = int(p["slots"]), p["crank_m"], p["thickness_m"]
        C = R / math.sin(math.pi / n)
        body.append('<body name="crank"><joint name="crank" {h}/>{g}</body>'.format(h=HINGE_Y, g=_bar("crank", R, 0.01, t, GREY)))
        body.append(f'<body name="wheel" pos="{-C} 0 0"><joint name="wheel" {HINGE_Y}/>{_disc(math.sqrt(C * C - R * R), t, BLUE)}</body>')
    elif mid == "C-RAT-RATCHET":
        R, t = p["wheel_radius_m"], p["thickness_m"]
        body.append('<body name="crank" pos="0 0 {z}"><joint name="crank" {h}/>{g}</body>'.format(
            z=-2.2 * R, h=HINGE_Y, g=_bar("crank", 0.3 * R, 0.008, t, GREY)))
        body.append('<body name="rocker" pos="0 {y} 0"><joint name="rocker" {h}/>{g}</body>'.format(
            y=-1.5 * t, h=HINGE_Y, g=_bar("rocker", 1.6 * R, 0.012, 0.8 * t, GREY)))
        body.append(f'<body name="wheel"><joint name="wheel" {HINGE_Y}/>{_disc(R, t, BLUE)}</body>')
    else:
        raise ValueError(f"零件库里没有可做动力学的机构“{mid}”")
    ten, teq = _ratio_tendons(mid, p)
    eq += teq
    return ('<mujoco model="{m}"><compiler angle="degree" autolimits="true"/><option timestep="{h!r}"/>'
            '<worldbody>{b}</worldbody>{t}<equality>{e}</equality></mujoco>').format(
        m=mid, h=timestep_s or DT_MAX, b="".join(body), t=f"<tendon>{''.join(ten)}</tendon>" if ten else "", e="".join(eq))


def initial(mid, given, q_driver):
    """主动件在 q_driver 时，满足闭环约束的各关节初值"""
    p = params(mid, given)
    th = float(q_driver)
    if mid == "C-LNK-4BAR":
        s = four_bar_solve(p, th)
        if s is None:
            raise ValueError(f"这组杆长在曲柄 {math.degrees(th):.1f}° 时装不上（不满足装配条件）")
        _, _, th3, th4 = s
        return {"crank": th, "coupler": th3 - th, "rocker": th4}
    if mid == "C-LNK-SLIDER":
        x = slider_crank_x(p, th)
        if x is None:
            raise ValueError("连杆太短，曲柄转不过去")
        Ax, Az = p["crank_m"] * math.cos(th), p["crank_m"] * math.sin(th)
        phi = math.atan2(p["offset_m"] - Az, x - Ax)
        return {"crank": th, "rod": phi - th, "slider": x}
    if mid in ("C-GER-TRAIN", "C-RED-WQR105"):
        q2 = -th * p["z1"] / p["z2"]
        return {"shaft1": th, "shaft2": q2, "shaft3": -q2 * p["z3"] / p["z4"]}
    if mid == "C-WRM-WORM":
        return {"worm": th, "wheel": th * p["worm_starts"] / p["wheel_teeth"]}
    if mid == "C-BLT-BELT":
        return {"pulley1": th, "pulley2": th * p["d1_m"] / p["d2_m"]}
    if mid == "C-SCN-LEAD":
        return {"screw": th, "nut": th * p["lead_mm"] / 1000 / (2 * math.pi)}
    out = {DRIVER[mid]: th}
    for c in couplings(mid, p):
        out[c["follower"]] = coupling_fn(c["fn"], p)(th)
    return out


def ratio(mid, given=None):
    """总传动比（输入转角 / 输出转角或位移），报告与核对用"""
    p = params(mid, given)
    if mid in ("C-GER-TRAIN", "C-RED-WQR105"):
        return p["z2"] * p["z4"] / (p["z1"] * p["z3"])
    if mid == "C-WRM-WORM":
        return p["wheel_teeth"] / p["worm_starts"]
    if mid == "C-BLT-BELT":
        return p["d2_m"] / p["d1_m"]
    return None


def prepare_setup(mid, given, setup):
    """机构的设置：主动件初值 → 各关节闭环初值；加上函数耦合"""
    s = dict(setup)
    drv = DRIVER[mid]
    q0 = float((setup.get("initial") or {}).get(drv, 0.0))
    s["initial"] = dict(initial(mid, given, q0), **{k: v for k, v in (setup.get("initial") or {}).items() if k == drv})
    s["couplings"] = couplings(mid, params(mid, given))
    # 初速度：主动件的初速度 × 各关节对主动件的速比（数值求导），避免一开始约束猛拉
    w0 = 0.0
    for d in setup.get("drives") or []:
        if d.get("joint") == drv:
            w0 = {"speed": float(d.get("value") or 0), "sine": float(d.get("amp") or 0) * 2 * math.pi * float(d.get("freq") or 1)}.get(d.get("kind"), 0.0)
    if w0:
        a, b = initial(mid, given, q0 + 1e-6), initial(mid, given, q0 - 1e-6)
        s["initial_qd"] = {k: (a[k] - b[k]) / 2e-6 * w0 for k in a}
    return s


# ---------------------------------------------------------------- 闭环机构的精确力矩（线索第 71 条）
DAE_RATIO = 50.0          # 一转（一个周期）时间 / 给定运动约束的时间常数 小于它：力矩改由 DAE 内核算


def dae_model(mid, given, setup):
    """闭环机构（LOOP_MIDS）按 MuJoCo 模型的构件、质量、惯量写成 mbd-model/1：构件的质心、惯量取 MuJoCo 在初始位形算的值
    （不另算一套几何），树上的关节照搬，connect 软约束换成转动副（平面机构，轴同其他铰）。主动件只能是匀速或正弦驱动"""
    import mujoco
    import numpy as np

    from analysis.mbd import core

    p = params(mid, given)
    model = mujoco.MjModel.from_xml_string(mjcf(mid, p))
    data = mujoco.MjData(model)
    for name, v in (setup.get("initial") or {}).items():
        data.qpos[model.jnt_qposadr[core._jid(model, name)]] = float(v)
    mujoco.mj_forward(model, data)

    def bname(b):
        return "ground" if b == 0 else mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b)

    bodies = []
    for b in range(1, model.nbody):
        R = data.ximat[b].reshape(3, 3)
        J = R @ np.diag(model.body_inertia[b]) @ R.T
        bodies.append({"id": bname(b), "mass_kg": float(model.body_mass[b]), "cm_mm": (data.xipos[b] * 1000).tolist(),
                       "inertia_kg_m2": {"ixx": J[0, 0], "iyy": J[1, 1], "izz": J[2, 2], "ixy": J[0, 1], "ixz": J[0, 2], "iyz": J[1, 2]}})
    joints, hinge_axis = [], [0.0, -1.0, 0.0]
    for j in range(model.njnt):
        b = int(model.jnt_bodyid[j])
        typ = {int(mujoco.mjtJoint.mjJNT_HINGE): "revolute", int(mujoco.mjtJoint.mjJNT_SLIDE): "translational"}[int(model.jnt_type[j])]
        ax = data.xaxis[j].tolist()
        if typ == "revolute":
            hinge_axis = ax
        joints.append({"id": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, j), "type": typ,
                       "body_i": bname(int(model.body_parentid[b])), "body_j": bname(b),
                       "point_mm": (data.xanchor[j] * 1000).tolist(), "axis": ax})
    for e in range(model.neq):
        s1, s2 = int(model.eq_obj1id[e]), int(model.eq_obj2id[e])
        joints.append({"id": f"loop{e + 1}", "type": "revolute", "body_i": bname(int(model.site_bodyid[s1])),
                       "body_j": bname(int(model.site_bodyid[s2])), "point_mm": (data.site_xpos[s1] * 1000).tolist(), "axis": hinge_axis})
    drv = DRIVER[mid]
    d = next(x for x in setup["drives"] if x["joint"] == drv)
    if d["kind"] == "speed":
        motion = {"id": "drive", "joint": drv, "dof": "rotation", "speed": d["value"] * 60 / (2 * math.pi)}
    else:
        motion = {"id": "drive", "joint": drv, "dof": "rotation",
                  "function": f"{math.degrees(d['amp'])!r}*sin(2*PI*{d['freq']!r}*time)"}
    g = (np.asarray(model.opt.gravity) * 1000).tolist() if setup.get("gravity", True) else [0.0, 0.0, 0.0]
    n = max(1, round(setup["duration_s"] * setup["sample_hz"]))
    return {"format": "mbd-model/1", "name": f"{mid}（DAE）", "gravity_mm_s2": g, "bodies": bodies, "joints": joints,
            "motions": [motion], "analysis": {"type": "kinematic", "end_time_s": setup["duration_s"], "output_steps": n}}


def dae_route(mid, setup, dt, w_max):
    """该不该改由 DAE 算力矩：闭环机构、只有主动件一个匀速或正弦驱动、没有附加负载 / 外力 / 摩擦，
    且一转时间与给定运动约束的时间常数之比小于 DAE_RATIO。返回 (是否, 比值)"""
    from analysis.mbd import core

    if mid not in LOOP_MIDS or not w_max:
        return False, None
    ratio = 2 * math.pi / w_max / core.tau_of(dt)
    drives = setup.get("drives") or []
    ok = (len(drives) == 1 and drives[0]["joint"] == DRIVER[mid] and drives[0]["kind"] in ("speed", "sine")
          and not setup.get("payloads") and not setup.get("forces") and not setup.get("friction"))
    return ok and ratio < DAE_RATIO, ratio
