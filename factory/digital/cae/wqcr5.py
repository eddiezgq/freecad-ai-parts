# -*- coding: utf-8 -*-
"""问渠机器人厂 WQ-CR5 六轴协作机器人的动力学模型（第 58 轮 D-1）。**原件**；零件库、教材用的是它的副本或生成物：

    python3 factory/digital/cae/wqcr5.py --sync      # 复制到 library/generators/wqcr5.py，生成 textbook/robotics/models/mjcf/wqcr5.xml

测试 factory/digital/tests/test_wqcr5.py 核对：副本一字不差、教材的 MJCF 与重新生成的一致、DH 与整机标定（sim/calib.py）一致、
关节模组的电机与谐波减速器参数与电机选型助手（cae/motors.py）一致。

模型怎么来的（全部是 **示例值**：量级与常见 5 kg 协作臂相同，不照抄任何厂商的数）：
- 几何：第 55 轮整机标定的名义 DH（标准 DH，T_i = Rz(θ_i)·Tz(d_i)·Tx(a_i)·Rx(α_i)）。
- MJCF 的构件 i 跟着关节 i 转：它的坐标系 = DH 坐标系 i−1 绕 z 转 θ_i；子构件放在 (a_i, 0, d_i)，再绕 x 转 α_i。
- 每个构件由几块“零件”组成：关节模组（实心圆柱，沿它驱动的关节轴）、臂管（铝合金薄壁圆管）、壳体与法兰。
  构件 i 带着下一个关节（i+1）的模组——模组的外壳固定在前一节上，这是协作臂的常见做法。
  质量、质心、惯量由这些零件按平行轴定理逐项相加（手算可核对，见教材 29.2 节），写成 MJCF 的 <inertial>。
- 关节模组（机器人厂清单）：WQJ-L 大关节（谐波 32 号 + 400 W，J1、J2）、WQJ-M 中关节（25 号 + 200 W，J3）、WQJ-S 小关节（17 号 + 100 W，J4–J6），
  减速比都取 100。电机转子惯量折算到关节侧 J_m·i² 写成 armature；力矩上限 = min(电机峰值 × i × η，减速器重复峰值)。
- 关节摩擦（粘性 damping、库仑 frictionloss）是名义值；每台机器人的实际摩擦由仿真车间按出厂编号在名义值附近散布（实验 28）。
纯计算（只用 numpy），不联网。
"""
from __future__ import annotations

import math

import numpy as np

NAME = "WQ-CR5"
LIB_ID = "B-ARM-WQCR5"
JOINTS = ("J1", "J2", "J3", "J4", "J5", "J6")
# 名义 DH（与 sim/calib.py 的 NOMINAL 相同，测试核对）：a、α、d 单位 m、rad
DH = [
    {"a": 0.0, "alpha": math.pi / 2, "d": 0.150},
    {"a": -0.400, "alpha": 0.0, "d": 0.0},
    {"a": -0.360, "alpha": 0.0, "d": 0.0},
    {"a": 0.0, "alpha": math.pi / 2, "d": 0.120},
    {"a": 0.0, "alpha": -math.pi / 2, "d": 0.100},
    {"a": 0.0, "alpha": 0.0, "d": 0.090},
]
HOME_DEG = (0, -90, 90, -90, -90, 0)            # 与整机标定的初始位姿相同
PAYLOAD_KG = 5.0
GEAR_RATIO = 100
ETA = 0.75                                      # 谐波减速器效率（与电机选型助手相同）
LIMIT_DEG = 175.0                               # 各关节的软限位（示例）
# 出厂的位置环（关节 PD，示例值）：τ = kp(θ_d − θ) − kv θ̇（教材 29.2～29.4 节的“控制器 A”）
SERVO_KP = (2000.0, 2000.0, 1000.0, 300.0, 300.0, 300.0)
SERVO_KV = (400.0, 400.0, 200.0, 40.0, 40.0, 40.0)
BASE_TOP = 0.095                                # 底座上 J1 模组的顶面（J2 模组在 0.15 m 处横着，半径 0.055）

# 关节模组（示例）：质量 kg、外形（实心圆柱）半径、长 m；电机（名称、峰值力矩 N·m、转子惯量 kg·m²，取自 motors.MOTORS）；
# 谐波减速器（名称、额定、重复峰值 N·m，取自 motors.HARMONIC）；名义摩擦：粘性 N·m·s/rad（示例）、库仑 N·m（关节侧，
# = 机器人厂关节测试台“空载摩擦力矩”的名义值，plants/wenquest-robot.yaml 的 joint_friction）
MODULES = {
    "L": {"code": "WQJ-L", "mass": 3.0, "r": 0.055, "h": 0.110, "motor": ("伺服 400 W", 4.46, 0.42e-4),
          "gear": ("谐波 32 号", 137.0, 333.0), "damping": 2.0, "frictionloss": 1.2},
    "M": {"code": "WQJ-M", "mass": 2.0, "r": 0.045, "h": 0.095, "motor": ("伺服 200 W", 2.23, 0.26e-4),
          "gear": ("谐波 25 号", 67.0, 178.0), "damping": 1.0, "frictionloss": 0.8},
    "S": {"code": "WQJ-S", "mass": 1.2, "r": 0.035, "h": 0.080, "motor": ("伺服 100 W", 1.11, 0.04e-4),
          "gear": ("谐波 17 号", 24.0, 54.0), "damping": 0.3, "frictionloss": 0.4},
}
JOINT_MODULE = ("L", "L", "M", "S", "S", "S")    # 与清单、sim/calib.py 的 JOINT_SIZE 相同
RHO_AL = 2700.0                                  # 臂管：铝合金
TUBES = {"upper": (0.045, 0.003), "fore": (0.0375, 0.003)}   # 外半径、壁厚 m

GREY, BLUE, DARK, ORANGE = "0.80 0.82 0.84 1", "0.20 0.45 0.70 1", "0.27 0.29 0.32 1", "0.95 0.55 0.15 1"


# ---------------------------------------------------------------- 零件的质量与惯量
def _Rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def _axis_frame(axis):
    """把局部 z 轴转到 axis 方向的旋转矩阵（圆柱的轴）"""
    z = np.asarray(axis, float) / np.linalg.norm(axis)
    x = np.array([1.0, 0, 0]) if abs(z[0]) < 0.9 else np.array([0, 1.0, 0])
    x = x - z * (x @ z)
    x /= np.linalg.norm(x)
    return np.column_stack([x, np.cross(z, x), z])


def solid_cylinder(m, r, h, center, axis):
    """实心圆柱：轴向 m r²/2，横向 m(3r² + h²)/12"""
    Il = np.diag([m * (3 * r * r + h * h) / 12, m * (3 * r * r + h * h) / 12, m * r * r / 2])
    R = _axis_frame(axis)
    return {"mass": m, "com": np.asarray(center, float), "I": R @ Il @ R.T}


def tube(r_out, t, start, end):
    """铝合金薄壁圆管（两端开口）：轴向 m(r₁² + r₂²)/2，横向 m(3(r₁² + r₂²) + L²)/12"""
    start, end = np.asarray(start, float), np.asarray(end, float)
    L = float(np.linalg.norm(end - start))
    r_in = r_out - t
    m = RHO_AL * math.pi * (r_out ** 2 - r_in ** 2) * L
    s = r_out ** 2 + r_in ** 2
    Il = np.diag([m * (3 * s + L * L) / 12, m * (3 * s + L * L) / 12, m * s / 2])
    R = _axis_frame(end - start)
    return {"mass": m, "com": (start + end) / 2, "I": R @ Il @ R.T}


def point_box(m, size, center):
    """长方体（壳体、法兰盘的近似）"""
    a, b, c = size
    return {"mass": m, "com": np.asarray(center, float), "I": np.diag([m * (b * b + c * c) / 12, m * (a * a + c * c) / 12, m * (a * a + b * b) / 12])}


def combine(parts):
    """平行轴定理：几个零件合成一个构件的质量、质心、对质心的惯量"""
    m = sum(p["mass"] for p in parts)
    c = sum(p["mass"] * p["com"] for p in parts) / m
    I = np.zeros((3, 3))
    for p in parts:
        d = p["com"] - c
        I += p["I"] + p["mass"] * ((d @ d) * np.eye(3) - np.outer(d, d))
    return {"mass": m, "com": c, "I": I}


def _child_axis(i):
    """构件 i 坐标系里，关节 i+1 的轴（= DH 坐标系 i 的 z 轴）"""
    return _Rx(DH[i]["alpha"])[:, 2]


def _child_pos(i):
    return np.array([DH[i]["a"], 0.0, DH[i]["d"]])


def link_parts(i):
    """构件 i（0 起，跟着关节 J(i+1) 转）的零件表：[(名称, 零件, 可视几何)]"""
    p_end = _child_pos(i)
    out = []
    if i < 5:                                    # 带着下一个关节的模组
        mod = MODULES[JOINT_MODULE[i + 1]]
        out.append(("{} 模组（J{}）".format(mod["code"], i + 2), solid_cylinder(mod["mass"], mod["r"], mod["h"], p_end, _child_axis(i)),
                    ("cylinder", mod["r"], mod["h"], p_end, _child_axis(i), BLUE)))
    if i == 0:                                   # 肩座壳体（立在 J1 上）
        out.append(("肩座壳体", point_box(0.5, (0.10, 0.10, 0.12), (0, 0, 0.07)), ("box", (0.05, 0.05, 0.06), (0, 0, 0.07), GREY)))
    elif i in (1, 2):                            # 大臂、小臂：铝管 + 两端的罩壳
        r, t = TUBES["upper" if i == 1 else "fore"]
        tb = tube(r, t, (0, 0, 0), p_end)
        out.append(("{}铝管 Ø{:.0f}×{:.0f}".format("大臂" if i == 1 else "小臂", 2000 * r, 1000 * t), tb,
                    ("capsule", r, None, (0, 0, 0), p_end, GREY)))
        out.append(("罩壳与线缆", point_box(0.3 if i == 1 else 0.2, (0.08, 0.08, 0.08), p_end / 2), None))
    elif i in (3, 4):                            # 腕部连接件
        out.append(("腕部连接件", point_box(0.2, (0.07, 0.07, 0.07), p_end / 2), ("box", (0.03, 0.03, max(abs(p_end[2]) / 2, 0.02)), p_end / 2, GREY)))
    else:                                        # 末端法兰
        out.append(("末端法兰", solid_cylinder(0.35, 0.035, 0.03, (0, 0, DH[5]["d"] - 0.015), (0, 0, 1)),
                    ("cylinder", 0.035, 0.03, (0, 0, DH[5]["d"] - 0.015), (0, 0, 1), DARK)))
    return out


def links():
    """6 个构件的质量、质心（构件坐标系）、对质心的惯量"""
    return [combine([p for _, p, _ in link_parts(i)]) for i in range(6)]


def base_mass():
    """不动的部分：底座 + J1 的模组（不进动力学，只算整机质量）"""
    return 2.5 + MODULES["L"]["mass"]


def total_mass():
    return base_mass() + sum(l["mass"] for l in links())


def armature():
    """电机转子惯量折算到关节侧：J_m · i²"""
    return [MODULES[s]["motor"][2] * GEAR_RATIO ** 2 for s in JOINT_MODULE]


def torque_limit():
    """关节力矩上限 = min(电机峰值 × i × η，减速器重复峰值)"""
    out = []
    for s in JOINT_MODULE:
        mod = MODULES[s]
        out.append(min(mod["motor"][1] * GEAR_RATIO * ETA, mod["gear"][2]))
    return out


# ---------------------------------------------------------------- MJCF
def principal(I):
    """主惯量（升序）与主轴坐标系的四元数（w, x, y, z）：I = R diag Rᵀ，R 的列是主轴（右手系）"""
    ev, R = np.linalg.eigh(I)
    if np.linalg.det(R) < 0:
        R[:, 2] = -R[:, 2]
    w = math.sqrt(max(0.0, 1 + R[0, 0] + R[1, 1] + R[2, 2])) / 2
    if w > 1e-6:
        q = np.array([w, (R[2, 1] - R[1, 2]) / (4 * w), (R[0, 2] - R[2, 0]) / (4 * w), (R[1, 0] - R[0, 1]) / (4 * w)])
    else:                                        # 转角接近 180°：从最大的对角元求
        k = int(np.argmax(np.diag(R)))
        i, j = (k + 1) % 3, (k + 2) % 3
        v = np.zeros(3)
        v[k] = math.sqrt(max(0.0, 1 + R[k, k] - R[i, i] - R[j, j])) / 2
        v[i] = (R[i, k] + R[k, i]) / (4 * v[k])
        v[j] = (R[j, k] + R[k, j]) / (4 * v[k])
        q = np.array([(R[j, i] - R[i, j]) / (4 * v[k]), *v])
    return ev, q / np.linalg.norm(q)


def _f(v):
    return " ".join("%.6g" % x for x in v)


def _quat_x(a):
    return (math.cos(a / 2), math.sin(a / 2), 0.0, 0.0)


def _geom_xml(g, ind):
    kind = g[0]
    if kind == "cylinder":
        _, r, h, c, axis, rgba = g
        a = np.asarray(axis, float) / np.linalg.norm(axis)
        p0, p1 = np.asarray(c) - a * h / 2, np.asarray(c) + a * h / 2
        return '{}<geom type="cylinder" fromto="{}" size="{:.4g}" rgba="{}"/>'.format(ind, _f(list(p0) + list(p1)), r, rgba)
    if kind == "capsule":
        _, r, _, p0, p1, rgba = g
        return '{}<geom type="capsule" fromto="{}" size="{:.4g}" rgba="{}"/>'.format(ind, _f(list(p0) + list(p1)), r, rgba)
    _, half, c, rgba = g
    return '{}<geom type="box" size="{}" pos="{}" rgba="{}"/>'.format(ind, _f(half), _f(c), rgba)


def mjcf(actuator="motor", kp=None, kv=None, payload_kg=0.0, timestep=0.002, integrator="implicitfast", friction=True):
    """WQ-CR5 的 MJCF。actuator："motor"（给力矩）或 "position"（位置伺服 = PD：kp、kv 每个关节一个，N·m/rad、N·m·s/rad）。
    payload_kg：法兰上挂的负载（质点，在工具点上）。friction=False 去掉关节摩擦（核对教材算例用）。
    不带地面和灯（要的话由使用者在 <!--WORLD--> 处加）；四个占位注释与教材网页实验的模型约定相同（textbook/tools/mjcf_web.py）。"""
    L = links()
    arm, lim = armature(), torque_limit()
    out = ['<mujoco model="wq_cr5">',
           '  <!-- 问渠机器人厂 WQ-CR5 六轴协作机器人（示例值，第 58 轮）。由 factory/digital/cae/wqcr5.py 生成，不要手改 -->',
           '  <compiler angle="radian" inertiafromgeom="false" autolimits="true"/>',
           '  <!--OPTION-->',
           ('  <option integrator="{}" />'.format(integrator) if timestep == 0.002 else
            '  <option timestep="{:g}" integrator="{}" />'.format(timestep, integrator)),
           '  <default><geom contype="0" conaffinity="0" group="1"/></default>',
           '  <worldbody>',
           '    <body name="base" pos="0 0 0">',
           '      <inertial pos="0 0 0.06" mass="{:.4g}" diaginertia="0.03 0.03 0.02"/>'.format(base_mass()),
           '      <geom type="cylinder" fromto="0 0 0 0 0 0.04" size="0.075" rgba="{}"/>'.format(DARK),
           '      <geom type="cylinder" fromto="0 0 0.04 0 0 {:.4g}" size="{:.4g}" rgba="{}"/>'.format(BASE_TOP, MODULES["L"]["r"], BLUE)]
    def body(i, ind):
        l, jn, mod = L[i], JOINTS[i], MODULES[JOINT_MODULE[i]]
        diag, quat = principal(l["I"])
        place = "" if i == 0 else ' pos="{}" quat="{}"'.format(_f(_child_pos(i - 1)), _f(_quat_x(DH[i - 1]["alpha"])))
        lines = ['{}<body name="link{}"{}>'.format(ind, i + 1, place),
                 '{}  <inertial pos="{}" quat="{}" mass="{:.6g}" diaginertia="{}"/>'.format(ind, _f(l["com"]), _f(quat), l["mass"], _f(diag))]
        fr = ' damping="{:.4g}" frictionloss="{:.4g}"'.format(mod["damping"], mod["frictionloss"]) if friction else ""
        lines.append('{}  <joint name="{}" axis="0 0 1" range="{:.6g} {:.6g}" armature="{:.6g}"{} actuatorfrcrange="{:.6g} {:.6g}"/>'.format(
            ind, jn, -math.radians(LIMIT_DEG), math.radians(LIMIT_DEG), arm[i], fr, -lim[i], lim[i]))
        lines += [_geom_xml(g, ind + "  ") for _, _, g in link_parts(i) if g]
        if i < 5:                                # 下一个构件放在 (a_i, 0, d_i)，绕 x 转 α_i
            lines += body(i + 1, ind + "  ")
        else:
            lines.append('{}  <site name="flange" pos="0 0 {:.6g}"/>'.format(ind, DH[5]["d"]))
            lines.append('{}  <site name="tcp" pos="0.05 0 {:.6g}"/>'.format(ind, DH[5]["d"] + 0.10))
            lines.append('{}  <!--TOOL-->'.format(ind))
            if payload_kg > 0:
                lines.append('{}  <body name="payload" pos="0.05 0 {:.6g}"><inertial pos="0 0 0" mass="{:.6g}" diaginertia="1e-4 1e-4 1e-4"/>'
                             '<geom type="sphere" size="0.03" rgba="{}"/></body>'.format(ind, DH[5]["d"] + 0.10, payload_kg, ORANGE))
        lines.append('{}</body>'.format(ind))
        return lines

    out += body(0, "      ")
    out += ['    </body>', '    <!--WORLD-->', '  </worldbody>']
    out.append('  <actuator>')
    for i, jn in enumerate(JOINTS):
        if actuator == "position":
            out.append('    <position name="{0}" joint="{0}" kp="{1:.6g}" kv="{2:.6g}" forcerange="{3:.6g} {4:.6g}"/>'.format(
                jn, kp[i], kv[i], -torque_limit()[i], torque_limit()[i]))
        else:
            out.append('    <motor name="{0}" joint="{0}" ctrlrange="{1:.6g} {2:.6g}"/>'.format(jn, -torque_limit()[i], torque_limit()[i]))
    out.append('    <!--ACTUATOR-->')
    out.append('  </actuator>')
    out.append('  <keyframe><key name="home" qpos="{}"/></keyframe>'.format(_f([math.radians(d) for d in HOME_DEG])))
    out.append('</mujoco>')
    return "\n".join(out) + "\n"


def summary():
    """零件库条目、教材用的数据表"""
    L = links()
    return {"name": NAME, "dof": 6, "payload_kg": PAYLOAD_KG, "reach_mm": round(1000 * (abs(DH[1]["a"]) + abs(DH[2]["a"]) + DH[4]["d"])),
            "mass_kg": round(total_mass(), 2), "moving_mass_kg": round(sum(l["mass"] for l in L), 3),
            "links": [{"name": "link{}".format(i + 1), "mass_kg": round(l["mass"], 4), "com_m": [round(x, 5) for x in l["com"]],
                       "inertia_kg_m2": [round(l["I"][a, b], 6) for a, b in ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))]}
                      for i, l in enumerate(L)],
            "joints": [{"name": JOINTS[i], "module": MODULES[s]["code"], "ratio": GEAR_RATIO, "armature_kg_m2": round(armature()[i], 6),
                        "torque_limit_Nm": round(torque_limit()[i], 2), "damping_Nms_rad": MODULES[s]["damping"],
                        "frictionloss_Nm": MODULES[s]["frictionloss"]} for i, s in enumerate(JOINT_MODULE)],
            "dh": DH, "note": "示例值：量级与常见 5 kg 协作臂相同，不照抄任何厂商的数"}


# ---------------------------------------------------------------- 负载跑合台的标准动作与标准负载（实验 28、教材 29.4 节）
# 标准负载：钢块 100 × 100 × 64 mm（约 5 kg），装在法兰上，质心在法兰前 0.06 m（沿工具方向 z）。示例值
RUNIN_LOAD = {"mass": 5.0, "com": (0.0, 0.0, 0.06), "size": (0.10, 0.10, 0.064)}
# 标准动作：从初始位姿出发，经过三个位姿再回来；每段关节空间五次多项式（起止速度、加速度为零），段间停 DWELL 秒
RUNIN_POSES_DEG = [HOME_DEG, (90, -45, 60, -105, -90, 45), (-60, -110, 120, -100, -60, -45), HOME_DEG]
RUNIN_SEG_S = 1.2
RUNIN_DWELL_S = 0.3


def runin_duration():
    n = len(RUNIN_POSES_DEG) - 1
    return n * RUNIN_SEG_S + (n + 1) * RUNIN_DWELL_S


def runin_ref(t):
    """标准动作在时刻 t 的关节角、角速度、角加速度（rad、rad/s、rad/s²）"""
    P = [np.radians(p) for p in RUNIN_POSES_DEG]
    T, Dw = RUNIN_SEG_S, RUNIN_DWELL_S
    t = max(0.0, float(t))
    for k in range(len(P) - 1):
        t0 = Dw + k * (T + Dw)
        if t < t0:
            return P[k].copy(), np.zeros(6), np.zeros(6)
        if t <= t0 + T:
            s = (t - t0) / T
            d = P[k + 1] - P[k]
            return (P[k] + d * (10 * s ** 3 - 15 * s ** 4 + 6 * s ** 5), d * (30 * s ** 2 - 60 * s ** 3 + 30 * s ** 4) / T,
                    d * (60 * s - 180 * s ** 2 + 120 * s ** 3) / T ** 2)
    return P[-1].copy(), np.zeros(6), np.zeros(6)


def runin_load_xml():
    """标准负载写成法兰上的 body（放在 MJCF 的 <!--TOOL--> 处）"""
    L = RUNIN_LOAD
    a, b, c = L["size"]
    m = L["mass"]
    r = lambda v: " ".join(repr(float(x)) for x in v)  # noqa: E731   全精度：与教材按公式算的惯量逐位一致
    return ('<body name="load" pos="0 0 {}"><inertial pos="{}" mass="{}" diaginertia="{}"/>'
            '<geom type="box" size="{}" pos="{}" rgba="{}"/></body>').format(
        repr(float(DH[5]["d"])), r(L["com"]), repr(float(m)), r([m / 12 * (b * b + c * c), m / 12 * (a * a + c * c), m / 12 * (a * a + b * b)]),
        _f([a / 2, b / 2, c / 2]), _f(L["com"]), ORANGE)


def sync():
    """原件 → 零件库副本、教材的 MJCF"""
    import shutil
    from pathlib import Path
    here = Path(__file__).resolve()
    repo = here.parents[3]
    shutil.copyfile(here, repo / "library" / "generators" / "wqcr5.py")
    (repo / "textbook" / "robotics" / "models" / "mjcf" / "wqcr5.xml").write_text(mjcf(), encoding="utf-8")
    return [repo / "library" / "generators" / "wqcr5.py", repo / "textbook" / "robotics" / "models" / "mjcf" / "wqcr5.xml"]


if __name__ == "__main__":
    import sys
    if "--sync" in sys.argv:
        for p in sync():
            print(p)
    else:
        print(mjcf())
