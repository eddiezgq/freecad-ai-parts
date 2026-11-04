# -*- coding: utf-8 -*-
"""问渠机器人厂 WQ-H1 轮式人形的动力学模型（第 75 轮）。**原件**；零件库用的是它的副本：

    python3 factory/digital/cae/wqh1.py --sync      # 复制到 library/generators/wqh1.py

测试 factory/digital/tests/test_wqh1.py 核对：副本一字不差、16 个关节与机器人厂物料清单对应、总质量 = 各零件之和、
MuJoCo 能加载、位置伺服下静止 1 秒不发散、重力下各关节力矩在关节模组的力矩上限以内。

模型怎么来的（全部是 **示例值**，不照抄任何厂商的数）：
- 结构：底盘（一台 WQ-AGV300，按一个刚体，固定在地上，两个驱动轮不建关节）→ 腰 2 个关节（转 W1、俯仰 W2，大关节 WQJ-L）→ 躯干
  → 头 2 个（转 H1、俯仰 H2，小关节 WQJ-S）+ 左右臂各 6 个（肩俯仰 A1、肩侧摆 A2 用中关节 WQJ-M；上臂转 A3、肘 A4、小臂转 A5、腕 A6 用小关节 WQJ-S）。
  与第 71 轮物料清单一一对应：WQJ-L × 2、WQJ-M × 4、WQJ-S × 10。
- 坐标：基座坐标系在底盘底面中心，X 向前、Z 向上；零位时所有构件坐标系与基座平行（双臂自然下垂、头朝前），关节轴写在构件坐标系里。
- 关节模组的质量、外形、电机、谐波减速器、减速比、效率、名义摩擦都取 WQ-CR5 那一份（cae/wqcr5.py 的 MODULES），只有一份数据源。
  模组的外壳固定在前一个构件上（与 WQ-CR5 相同），所以关节 k 的模组质量算在它的父构件里。
- 构件的质量、质心、惯量由零件按平行轴定理逐项相加（与 WQ-CR5 用同一组函数），写成 MJCF 的 <inertial>。
纯计算（只用 numpy），不联网。
"""
from __future__ import annotations

import math

if __name__ == "__main__":                      # 直接运行原件（--sync）：把 factory/digital 放进路径
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:                                            # 原件在 factory/digital/cae/；零件库的副本在 library/generators/
    from cae import wqcr5 as W
except ImportError:                             # pragma: no cover - 零件库里
    from generators import wqcr5 as W

NAME = "WQ-H1"
LIB_ID = "B-HUM-WQH1"
GEAR_RATIO, ETA, MODULES = W.GEAR_RATIO, W.ETA, W.MODULES
GREY, BLUE, DARK, ORANGE = W.GREY, W.BLUE, W.DARK, W.ORANGE
WHITE = "0.93 0.94 0.95 1"

# 外购件与自制件的示例质量 kg（型号待确认的外购件按同类常见量级取，都是示例值）
MASS = {"WQ-AGV300": 110.0, "WAIST-H1": 2.5, "TORSO-H1": 6.0, "SHOULDER-H1": 2.0, "CTRL-H1": 2.0, "CAM-STEREO": 0.4,
        "GRIP-2F": 0.9, "CABLE-ARM": 0.3}
CHASSIS = (0.70, 0.50, 0.32)                    # 底盘外形 m（示例）
ARM_FO = W.TUBES["fore"]                        # 每只手臂一根臂管：和 WQ-CR5 的小臂同一种（物料 ARM-FO）
UPPER_ARM = 0.26                                # 肩到肘 m
FOREARM = 0.24                                  # 肘到腕 m
SHOULDER_Y = 0.25                               # 两肩到中线 m
PAYLOAD_KG = 2.5                                # 每只手（示例；双手抱箱 5 kg）


def _cyl(module, center, axis):
    mod = MODULES[module]
    return W.solid_cylinder(mod["mass"], mod["r"], mod["h"], center, axis), ("cylinder", mod["r"], mod["h"], center, axis, BLUE)


def _box(m, size, center, rgba=GREY):
    half = tuple(s / 2 for s in size)
    return W.point_box(m, size, center), ("box", half, center, rgba)


AX = {"x": (1.0, 0, 0), "y": (0, 1.0, 0), "z": (0, 0, 1.0)}


def _arm(side):
    """一只手臂的 6 个构件。side = "l"（+Y）或 "r"（−Y）"""
    s = 1.0 if side == "l" else -1.0
    P = side.upper()
    tube = W.tube(ARM_FO[0], ARM_FO[1], (0, 0, -0.04), (0, 0, -UPPER_ARM))
    return [
        {"name": side + "_shoulder", "parent": "torso", "pos": (0, s * SHOULDER_Y, 0.42),
         "joint": (P + "A1", "y", "M", (-180, 60)),
         "parts": [("{} 模组（{}A2）".format(MODULES["M"]["code"], P), *_cyl("M", (0, s * 0.07, 0), AX["x"]))]},
        {"name": side + "_upper", "parent": side + "_shoulder", "pos": (0, s * 0.07, 0),
         "joint": (P + "A2", "x", "M", (-100, 100) if s > 0 else (-100, 100)),
         "parts": [("{} 模组（{}A3）".format(MODULES["S"]["code"], P), *_cyl("S", (0, 0, -0.07), AX["z"]))]},
        {"name": side + "_arm", "parent": side + "_upper", "pos": (0, 0, -0.07),
         "joint": (P + "A3", "z", "S", (-170, 170)),
         "parts": [("臂管 ARM-FO Ø{:.0f}×{:.0f}".format(2000 * ARM_FO[0], 1000 * ARM_FO[1]), tube,
                    ("capsule", ARM_FO[0], None, (0, 0, -0.04), (0, 0, -UPPER_ARM), GREY)),
                   ("{} 模组（{}A4）".format(MODULES["S"]["code"], P), *_cyl("S", (0, 0, -UPPER_ARM), AX["y"])),
                   ("线束 CABLE-ARM", W.point_box(MASS["CABLE-ARM"], (0.04, 0.04, 0.2), (0, 0, -0.15)), None)]},
        {"name": side + "_elbow", "parent": side + "_arm", "pos": (0, 0, -UPPER_ARM),
         "joint": (P + "A4", "y", "S", (-150, 10)),
         "parts": [("{} 模组（{}A5）".format(MODULES["S"]["code"], P), *_cyl("S", (0, 0, -0.10), AX["z"])),
                   ("肘部连接件", *_box(0.2, (0.06, 0.06, 0.06), (0, 0, -0.05)))]},
        {"name": side + "_fore", "parent": side + "_elbow", "pos": (0, 0, -0.10),
         "joint": (P + "A5", "z", "S", (-170, 170)),
         "parts": [("{} 模组（{}A6）".format(MODULES["S"]["code"], P), *_cyl("S", (0, 0, -(FOREARM - 0.10)), AX["y"])),
                   ("小臂罩壳", *_box(0.2, (0.06, 0.06, FOREARM - 0.16), (0, 0, -(FOREARM - 0.10) / 2)))]},
        {"name": side + "_wrist", "parent": side + "_fore", "pos": (0, 0, -(FOREARM - 0.10)),
         "joint": (P + "A6", "y", "S", (-120, 120)),
         "parts": [("二指电动夹爪 GRIP-2F", *_box(MASS["GRIP-2F"], (0.06, 0.09, 0.12), (0, 0, -0.08), DARK))],
         "sites": {side + "_tcp": (0, 0, -0.15)}},
    ]


def bodies():
    """构件表（父在子前）：name、parent、pos（在父构件坐标系里，零位时各坐标系平行）、joint（名、轴、模组、范围°）、parts"""
    cx, cy, cz = CHASSIS
    out = [
        {"name": "base", "parent": None, "pos": (0, 0, 0), "joint": None,
         "parts": [("底盘 WQ-AGV300（整台按一个刚体）", *_box(MASS["WQ-AGV300"], CHASSIS, (0, 0, cz / 2), DARK)),
                   ("{} 模组（W1）".format(MODULES["L"]["code"]), *_cyl("L", (0, 0, cz + 0.055), AX["z"]))]},
        {"name": "waist", "parent": "base", "pos": (0, 0, cz + 0.11), "joint": ("W1", "z", "L", (-170, 170)),
         "parts": [("腰座 WAIST-H1", W.solid_cylinder(MASS["WAIST-H1"], 0.07, 0.10, (0, 0, 0.05), AX["z"]),
                    ("cylinder", 0.07, 0.10, (0, 0, 0.05), AX["z"], GREY)),
                   ("{} 模组（W2）".format(MODULES["L"]["code"]), *_cyl("L", (0, 0, 0.15), AX["y"]))]},
        {"name": "torso", "parent": "waist", "pos": (0, 0, 0.15), "joint": ("W2", "y", "L", (-30, 45)),
         "parts": [("躯干壳体 TORSO-H1", *_box(MASS["TORSO-H1"], (0.24, 0.34, 0.40), (0, 0, 0.24), WHITE)),
                   ("人形主控 CTRL-H1", W.point_box(MASS["CTRL-H1"], (0.12, 0.20, 0.06), (-0.04, 0, 0.18)), None),
                   ("肩架 SHOULDER-H1", *_box(MASS["SHOULDER-H1"], (0.10, 0.42, 0.06), (0, 0, 0.42))),
                   ("{} 模组（H1）".format(MODULES["S"]["code"]), *_cyl("S", (0, 0, 0.49), AX["z"])),
                   ("{} 模组（LA1）".format(MODULES["M"]["code"]), *_cyl("M", (0, SHOULDER_Y, 0.42), AX["y"])),
                   ("{} 模组（RA1）".format(MODULES["M"]["code"]), *_cyl("M", (0, -SHOULDER_Y, 0.42), AX["y"]))]},
        {"name": "neck", "parent": "torso", "pos": (0, 0, 0.53), "joint": ("H1", "z", "S", (-120, 120)),
         "parts": [("{} 模组（H2）".format(MODULES["S"]["code"]), *_cyl("S", (0, 0, 0.06), AX["y"]))]},
        {"name": "head", "parent": "neck", "pos": (0, 0, 0.06), "joint": ("H2", "y", "S", (-30, 45)),
         "parts": [("头部双目相机 CAM-STEREO", *_box(MASS["CAM-STEREO"], (0.06, 0.18, 0.05), (0.05, 0, 0.06), DARK)),
                   ("头罩", *_box(0.3, (0.14, 0.16, 0.14), (0.0, 0, 0.08), WHITE))],
         "sites": {"camera": (0.08, 0, 0.06)}},
    ]
    return out + _arm("l") + _arm("r")


JOINTS = tuple(b["joint"][0] for b in bodies() if b["joint"])
JOINT_MODULE = tuple(b["joint"][2] for b in bodies() if b["joint"])
HOME_DEG = {j: 0.0 for j in JOINTS}             # 零位：站直、双臂自然下垂、头朝前
# 双手在胸前抱箱的位姿（示例）：肩前抬 90°、肘弯 −0°、腕下压，手在身前约 0.45 m
CARRY_DEG = dict(HOME_DEG, LA1=-90.0, RA1=-90.0, LA6=0.0, RA6=0.0)
SERVO_KP = {"L": 3000.0, "M": 1500.0, "S": 300.0}    # 出厂位置环（示例）
SERVO_KV = {"L": 300.0, "M": 150.0, "S": 30.0}


def link(b):
    return W.combine([p for _, p, _ in b["parts"]])


def total_mass():
    return sum(link(b)["mass"] for b in bodies())


def torque_limit(module):
    mod = MODULES[module]
    return min(mod["motor"][1] * GEAR_RATIO * ETA, mod["gear"][2])


def armature(module):
    return MODULES[module]["motor"][2] * GEAR_RATIO ** 2


def bom_count():
    """模型里每种关节模组的个数（与物料清单核对）"""
    out = {}
    for s in JOINT_MODULE:
        out[MODULES[s]["code"]] = out.get(MODULES[s]["code"], 0) + 1
    return out


# ---------------------------------------------------------------- MJCF
def mjcf(actuator="position", payload_kg=0.0, timestep=0.002, integrator="implicitfast", friction=True):
    """WQ-H1 的 MJCF（底盘固定）。actuator："position"（出厂位置环，缺省）或 "motor"（给力矩）。
    payload_kg：每只手上挂的负载（质点，在 tcp 上）。带地面和灯，可以直接打开看。"""
    f = W._f
    bl = bodies()
    kids = {}
    for b in bl:
        kids.setdefault(b["parent"], []).append(b)
    out = ['<mujoco model="wq_h1">',
           '  <!-- 问渠机器人厂 WQ-H1 轮式人形（示例值，第 75 轮）。由 factory/digital/cae/wqh1.py 生成，不要手改 -->',
           '  <compiler angle="radian" inertiafromgeom="false" autolimits="true"/>',
           ('  <option integrator="{}" />'.format(integrator) if timestep == 0.002 else
            '  <option timestep="{:g}" integrator="{}" />'.format(timestep, integrator)),
           '  <default><geom contype="0" conaffinity="0" group="1"/></default>',
           '  <worldbody>',
           '    <light pos="1 1 3" dir="-0.3 -0.3 -1"/>',
           '    <geom name="floor" type="plane" size="3 3 0.1" rgba="0.9 0.9 0.9 1"/>']

    def body(b, ind):
        l = link(b)
        diag, quat = W.principal(l["I"])
        lines = ['{}<body name="{}" pos="{}">'.format(ind, b["name"], f(b["pos"])),
                 '{}  <inertial pos="{}" quat="{}" mass="{:.6g}" diaginertia="{}"/>'.format(ind, f(l["com"]), f(quat), l["mass"], f(diag))]
        if b["joint"]:
            jn, ax, mod, (lo, hi) = b["joint"]
            m = MODULES[mod]
            fr = ' damping="{:.4g}" frictionloss="{:.4g}"'.format(m["damping"], m["frictionloss"]) if friction else ""
            lim = torque_limit(mod)
            lines.append('{}  <joint name="{}" axis="{}" range="{:.6g} {:.6g}" armature="{:.6g}"{} actuatorfrcrange="{:.6g} {:.6g}"/>'.format(
                ind, jn, f(AX[ax]), math.radians(lo), math.radians(hi), armature(mod), fr, -lim, lim))
        lines += [W._geom_xml(g, ind + "  ") for _, _, g in b["parts"] if g]
        for sn, sp in (b.get("sites") or {}).items():
            lines.append('{}  <site name="{}" pos="{}"/>'.format(ind, sn, f(sp)))
            if sn.endswith("_tcp") and payload_kg > 0:
                lines.append('{}  <body name="{}_load" pos="{}"><inertial pos="0 0 0" mass="{:.6g}" diaginertia="1e-3 1e-3 1e-3"/>'
                             '<geom type="sphere" size="0.04" rgba="{}"/></body>'.format(ind, sn[0], f(sp), payload_kg, ORANGE))
        for c in kids.get(b["name"], []):
            lines += body(c, ind + "  ")
        lines.append('{}</body>'.format(ind))
        return lines

    out += body(bl[0], "    ")
    out += ['  </worldbody>', '  <actuator>']
    for jn, mod in zip(JOINTS, JOINT_MODULE):
        lim = torque_limit(mod)
        if actuator == "position":
            out.append('    <position name="{0}" joint="{0}" kp="{1:.6g}" kv="{2:.6g}" forcerange="{3:.6g} {4:.6g}"/>'.format(
                jn, SERVO_KP[mod], SERVO_KV[mod], -lim, lim))
        else:
            out.append('    <motor name="{0}" joint="{0}" ctrlrange="{1:.6g} {2:.6g}"/>'.format(jn, -lim, lim))
    out.append('  </actuator>')
    out.append('  <keyframe><key name="home" qpos="{}"/><key name="carry" qpos="{}"/></keyframe>'.format(
        f([math.radians(HOME_DEG[j]) for j in JOINTS]), f([math.radians(CARRY_DEG[j]) for j in JOINTS])))
    out.append('</mujoco>')
    return "\n".join(out) + "\n"


def summary():
    """零件库条目、教材用的数据表"""
    bl = bodies()
    return {"name": NAME, "dof": len(JOINTS), "payload_kg_per_hand": PAYLOAD_KG, "mass_kg": round(total_mass(), 2),
            "upper_body_mass_kg": round(total_mass() - link(bl[0])["mass"], 2), "modules": bom_count(),
            "links": [{"name": b["name"], "mass_kg": round(link(b)["mass"], 4), "com_m": [round(x, 5) for x in link(b)["com"]],
                       "inertia_kg_m2": [round(link(b)["I"][a, c], 6) for a, c in ((0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2))]}
                      for b in bl],
            "joints": [{"name": b["joint"][0], "axis": b["joint"][1], "parent": b["parent"], "child": b["name"],
                        "module": MODULES[b["joint"][2]]["code"], "ratio": GEAR_RATIO, "range_deg": list(b["joint"][3]),
                        "armature_kg_m2": round(armature(b["joint"][2]), 6), "torque_limit_Nm": round(torque_limit(b["joint"][2]), 2),
                        "damping_Nms_rad": MODULES[b["joint"][2]]["damping"], "frictionloss_Nm": MODULES[b["joint"][2]]["frictionloss"]}
                       for b in bl if b["joint"]],
            "note": "示例值：底盘固定在地上（不做行走），关节模组与 WQ-CR5 同一份数据；不照抄任何厂商的数"}


def sync():
    """原件 → 零件库副本"""
    import shutil
    from pathlib import Path
    here = Path(__file__).resolve()
    dst = here.parents[3] / "library" / "generators" / "wqh1.py"
    shutil.copyfile(here, dst)
    return [dst]


if __name__ == "__main__":
    import sys
    if "--sync" in sys.argv:
        for p in sync():
            print("已写", p)
    else:
        import json
        print(json.dumps(summary(), ensure_ascii=False, indent=1))
