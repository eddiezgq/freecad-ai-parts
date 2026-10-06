# -*- coding: utf-8 -*-
"""零件库 C 部分机构的动力学模型（第 12 轮 D3）：按参数生成 MJCF。

坐标与零件库一致：平面机构在竖直 XZ 平面内，转角绕 −Y（从前方看逆时针为正），重力 −Z；齿轮轴沿 Y。
构件按钢（7850 kg/m³）算质量和惯量（杆 = 长方体，齿轮 / 带轮 = 分度圆圆柱）。
运动副的闭合方式：
  四杆、曲柄滑块 —— 连接约束（connect）闭环；
  齿轮系、WQR-105、蜗杆蜗轮、带传动、丝杠 —— 关节比例约束（joint equality，传动比）；
  凸轮、槽轮、棘轮 —— 函数耦合（从动件位置 = f(主动件转角)，由 cae/mbd.py 按虚功原理把从动件受力反作用到主动件）。
参数默认值与零件库条目一致（测试核对）。
"""
import math

RHO = 7850.0

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


def params(mid, given=None):
    if mid not in DEFAULTS:
        raise ValueError("零件库里没有可做动力学的机构“{}”".format(mid))
    p = dict(DEFAULTS[mid])
    for k, v in (given or {}).items():
        if k in p and v not in (None, ""):
            p[k] = float(v)
    return p


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
    raise ValueError("不认识的耦合“{}”".format(name))


def couplings(mid, p):
    if mid == "C-CAM-DISC":
        return [{"driver": "cam", "follower": "follower", "fn": "cam", "params": p}]
    if mid == "C-GNV-GENEVA":
        return [{"driver": "crank", "follower": "wheel", "fn": "geneva", "params": p}]
    if mid == "C-RAT-RATCHET":
        return [{"driver": "crank", "follower": "rocker", "fn": "ratchet_rocker", "params": p},
                {"driver": "crank", "follower": "wheel", "fn": "ratchet_wheel", "params": p}]
    return []


# ---------------------------------------------------------------- MJCF
HINGE_Y = 'type="hinge" axis="0 -1 0"'


def _bar(name, L, w, t, rgba, extra=""):
    """沿本构件 +X 的杆（长 L），两端销孔处画小圆柱"""
    return ('<geom name="{n}" type="box" pos="{h} 0 0" size="{h} {t2} {w2}" density="{rho}" rgba="{c}"/>'
            '<geom type="cylinder" pos="{L} 0 0" euler="90 0 0" size="{r} {t}" mass="0" rgba="0.3 0.3 0.3 1" group="2"/>{x}').format(
        n=name, h=L / 2, t2=t / 2, w2=w / 2, rho=RHO, c=rgba, L=L, r=w * 0.45, t=t * 0.8, x=extra)


def _disc(r, b, rgba, axis="y"):
    eu = "90 0 0" if axis == "y" else "0 90 0"
    return '<geom type="cylinder" euler="{}" size="{} {}" density="{}" rgba="{}"/>'.format(eu, r, b / 2, RHO, rgba)


BLUE, GREY, YEL = "0.24 0.47 0.67 1", "0.8 0.82 0.84 1", "0.95 0.72 0.02 1"
EQ = 'solref="0.002 1" solimp="0.95 0.99 0.001"'


def mjcf(mid, given=None):
    p = params(mid, given)
    body, eq = [], []
    if mid == "C-LNK-4BAR":
        a, b, c, d, w, t = (p[k] for k in ("crank_m", "coupler_m", "rocker_m", "ground_m", "link_width_m", "link_thickness_m"))
        body.append('<body name="crank"><joint name="crank" {h}/>{g}<body name="coupler" pos="{a} 0 0"><joint name="coupler" {h}/>{g2}'
                    '<site name="coupler_mid" pos="{bm} 0 0"/><site name="coupler_end" pos="{b} 0 0"/></body></body>'.format(
                        h=HINGE_Y, g=_bar("crank", a, w, t, BLUE), a=a, g2=_bar("coupler", b, w, t, GREY), bm=b / 2, b=b))
        body.append('<body name="rocker" pos="{d} 0 0"><joint name="rocker" {h}/>{g}<site name="rocker_end" pos="{c} 0 0"/></body>'.format(
            d=d, h=HINGE_Y, g=_bar("rocker", c, w, t, BLUE), c=c))
        # 用两个点（site）定义连接：约束“两点重合”，与模型的零位无关
        eq.append('<connect site1="coupler_end" site2="rocker_end" {}/>'.format(EQ))
    elif mid == "C-LNK-SLIDER":
        r, l, e, w, t = (p[k] for k in ("crank_m", "rod_m", "offset_m", "link_width_m", "link_thickness_m"))
        body.append('<body name="crank"><joint name="crank" {h}/>{g}<body name="rod" pos="{r} 0 0"><joint name="rod" {h}/>{g2}'
                    '<site name="rod_end" pos="{l} 0 0"/></body></body>'.format(h=HINGE_Y, g=_bar("crank", r, w, t, BLUE), r=r,
                                                                         g2=_bar("rod", l, w, t, GREY), l=l))
        body.append('<body name="slider" pos="0 0 {e}"><joint name="slider" type="slide" axis="1 0 0"/>'
                    '<geom type="box" size="{sx} {sy} {sz}" density="{rho}" rgba="{c}"/><site name="pin" pos="0 0 0"/></body>'.format(
                        e=e, sx=1.2 * w, sy=1.5 * t, sz=w, rho=RHO, c=BLUE))
        eq.append('<connect site1="rod_end" site2="pin" {}/>'.format(EQ))
    elif mid == "C-CAM-DISC":
        r0, rr, h, t = (p[k] for k in ("base_radius_m", "roller_radius_m", "lift_m", "thickness_m"))
        body.append('<body name="cam"><joint name="cam" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(r0 + h / 2, t, BLUE)))
        body.append('<body name="follower" pos="0 0 {z}"><joint name="follower" type="slide" axis="0 0 1"/>'
                    '<geom type="cylinder" euler="90 0 0" size="{rr} {t}" density="{rho}" rgba="{y}"/>'
                    '<geom type="box" pos="0 0 {sz}" size="0.006 {t} 0.04" density="{rho}" rgba="{g}"/></body>'.format(
                        z=r0 + rr, rr=rr, t=t * 0.45, rho=RHO, y=YEL, sz=rr + 0.04, g=GREY))
    elif mid in ("C-GER-TRAIN", "C-RED-WQR105"):
        m1, m2, b1, b2 = p["module1_mm"] / 1000, p["module2_mm"] / 1000, p["face1_mm"] / 1000, p["face2_mm"] / 1000
        z1, z2, z3, z4 = (p[k] for k in ("z1", "z2", "z3", "z4"))
        a1, a2 = m1 * (z1 + z2) / 2, m2 * (z3 + z4) / 2
        y2 = b1 / 2 + b2 / 2 + 0.01
        body.append('<body name="shaft1"><joint name="shaft1" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(m1 * z1 / 2, b1, BLUE)))
        body.append('<body name="shaft2" pos="{x} 0 0"><joint name="shaft2" {h}/>{g}<body pos="0 {y} 0">{g3}</body></body>'.format(
            x=a1, h=HINGE_Y, g=_disc(m1 * z2 / 2, b1, GREY), y=y2, g3=_disc(m2 * z3 / 2, b2, BLUE)))
        body.append('<body name="shaft3" pos="{x} {y} 0"><joint name="shaft3" {h}/>{g}</body>'.format(
            x=a1 + a2, y=y2, h=HINGE_Y, g=_disc(m2 * z4 / 2, b2, GREY)))
        eq.append('<joint joint1="shaft2" joint2="shaft1" polycoef="0 {} 0 0 0" {}/>'.format(-z1 / z2, EQ))
        eq.append('<joint joint1="shaft3" joint2="shaft2" polycoef="0 {} 0 0 0" {}/>'.format(-z3 / z4, EQ))
    elif mid == "C-WRM-WORM":
        m, z1, z2, q = p["module_mm"] / 1000, p["worm_starts"], p["wheel_teeth"], p["diameter_factor"]
        d1, d2 = m * q, m * z2
        body.append('<body name="worm" pos="0 0 {a}"><joint name="worm" type="hinge" axis="1 0 0"/>'
                    '<geom type="cylinder" euler="0 90 0" size="{r} {L}" density="{rho}" rgba="{c}"/></body>'.format(
                        a=(d1 + d2) / 2, r=d1 / 2, L=3 * math.pi * m, rho=RHO, c=BLUE))
        body.append('<body name="wheel"><joint name="wheel" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(d2 / 2, p["wheel_face_mm"] / 1000, GREY)))
        eq.append('<joint joint1="wheel" joint2="worm" polycoef="0 {} 0 0 0" {}/>'.format(z1 / z2, EQ))
    elif mid == "C-BLT-BELT":
        D1, D2, a, w = p["d1_m"], p["d2_m"], p["center_m"], p["width_m"]
        body.append('<body name="pulley1"><joint name="pulley1" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(D1 / 2, w, BLUE)))
        body.append('<body name="pulley2" pos="{a} 0 0"><joint name="pulley2" {h}/>{g}</body>'.format(a=a, h=HINGE_Y, g=_disc(D2 / 2, w, GREY)))
        eq.append('<joint joint1="pulley2" joint2="pulley1" polycoef="0 {} 0 0 0" {}/>'.format(D1 / D2, EQ))
    elif mid == "C-SCN-LEAD":
        d, Ph, Ls, Ln = p["diameter_mm"] / 1000, p["lead_mm"] / 1000, p["screw_length_m"], p["nut_length_m"]
        body.append('<body name="screw"><joint name="screw" type="hinge" axis="1 0 0"/>'
                    '<geom type="cylinder" euler="0 90 0" size="{r} {L}" density="{rho}" rgba="{c}"/></body>'.format(
                        r=d / 2, L=Ls / 2, rho=RHO, c=GREY))
        body.append('<body name="nut"><joint name="nut" type="slide" axis="1 0 0"/>'
                    '<geom type="box" size="{x} {y} {z}" density="{rho}" rgba="{c}"/></body>'.format(
                        x=Ln / 2, y=d, z=d, rho=RHO, c=BLUE))
        eq.append('<joint joint1="nut" joint2="screw" polycoef="0 {} 0 0 0" {}/>'.format(Ph / (2 * math.pi), EQ))
    elif mid == "C-GNV-GENEVA":
        n, R, t = int(p["slots"]), p["crank_m"], p["thickness_m"]
        C = R / math.sin(math.pi / n)
        body.append('<body name="crank"><joint name="crank" {h}/>{g}</body>'.format(h=HINGE_Y, g=_bar("crank", R, 0.01, t, GREY)))
        body.append('<body name="wheel" pos="{x} 0 0"><joint name="wheel" {h}/>{g}</body>'.format(
            x=-C, h=HINGE_Y, g=_disc(math.sqrt(C * C - R * R), t, BLUE)))
    elif mid == "C-RAT-RATCHET":
        R, t = p["wheel_radius_m"], p["thickness_m"]
        body.append('<body name="crank" pos="0 0 {z}"><joint name="crank" {h}/>{g}</body>'.format(
            z=-2.2 * R, h=HINGE_Y, g=_bar("crank", 0.3 * R, 0.008, t, GREY)))
        body.append('<body name="rocker" pos="0 {y} 0"><joint name="rocker" {h}/>{g}</body>'.format(
            y=-1.5 * t, h=HINGE_Y, g=_bar("rocker", 1.6 * R, 0.012, 0.8 * t, GREY)))
        body.append('<body name="wheel"><joint name="wheel" {h}/>{g}</body>'.format(h=HINGE_Y, g=_disc(R, t, BLUE)))
    else:
        raise ValueError("零件库里没有可做动力学的机构“{}”".format(mid))
    return ('<mujoco model="{m}"><compiler angle="degree" autolimits="true"/><option timestep="0.0002"/>'
            '<worldbody>{b}</worldbody><equality>{e}</equality></mujoco>').format(m=mid, b="".join(body), e="".join(eq))


def initial(mid, given, q_driver):
    """主动件在 q_driver 时，满足闭环约束的各关节初值"""
    p = params(mid, given)
    th = float(q_driver)
    if mid == "C-LNK-4BAR":
        s = four_bar_solve(p, th)
        if s is None:
            raise ValueError("这组杆长在曲柄 {:.1f}° 时装不上（不满足装配条件）".format(math.degrees(th)))
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


# ---------------------------------------------------------------- 构件 STEP（送去有限元，第 12 轮 D6）
STEP_MEMBERS = {"C-LNK-4BAR": {"crank": "crank_m", "coupler": "coupler_m", "rocker": "rocker_m"},
                "C-LNK-SLIDER": {"crank": "crank_m", "rod": "rod_m"}}


def member_step(mid, member, given=None):
    """连杆类构件：两端半圆头的扁杆，两端销孔（孔径 = 0.5 倍杆宽）。构件坐标：A 销孔在原点、B 销孔在 +X（米 → STEP 用毫米），
    厚度沿 Y——与动力学模型的构件坐标一致，铰点受力可以直接加到孔面上"""
    import os
    import tempfile
    import build123d as bd
    p = params(mid, given)
    if member not in STEP_MEMBERS.get(mid, {}):
        raise ValueError("“{}”的“{}”不是杆件，不能送去有限元".format(NAMES.get(mid, mid), member))
    L = p[STEP_MEMBERS[mid][member]] * 1000
    w, t = p["link_width_m"] * 1000, p["link_thickness_m"] * 1000
    with bd.BuildPart() as part:
        with bd.BuildSketch(bd.Plane.XZ):                 # XZ 平面：草图 x → 世界 X，草图 y → 世界 Z
            with bd.Locations((L / 2, 0)):
                bd.SlotCenterToCenter(L, w)
            with bd.Locations((0, 0), (L, 0)):
                bd.Circle(w * 0.25, mode=bd.Mode.SUBTRACT)
        bd.extrude(amount=t / 2, both=True)
    shape = part.part
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "m.step")
        bd.export_step(shape, f)
        return open(f, "rb").read()


def member_force_channel(mid, member):
    """杆件 B 端（远端销孔）受的力取自哪个反力通道、取正还是取反：
    主动的曲柄 B 端带着下一根杆，受力 = −（下一根杆从曲柄受的力）；其他杆 B 端受力 ≈ −A 端受力（二力杆，略去惯性和自重）"""
    if member not in STEP_MEMBERS.get(mid, {}):
        raise ValueError("“{}”的“{}”不是杆件，不能送去有限元".format(NAMES.get(mid, mid), member))
    if member == "crank":
        return {"C-LNK-4BAR": "coupler", "C-LNK-SLIDER": "rod"}[mid]
    return member
