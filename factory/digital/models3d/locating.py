# -*- coding: utf-8 -*-
"""第 51 章（定位原理与定位误差）用到的三维模型：找正用的工具、更多的定位元件、测量与上下料设备。

结构是典型形式的简化，尺寸取常用规格的比例，示意用；与工件配合的尺寸（直径、孔距）由调用者给出，和书中算例一致。
坐标约定同 elements.py：回转体轴线沿 x 时，端面在给定的 x；平面元件的工作面在给定的 z。"""
from __future__ import annotations

import math

from . import shapes as S
from .core import Assembly, Part


# ---------------------------------------------------------------- 找正装夹
def chuck4(D=250.0, grips=(60.0, 60.0, 60.0, 60.0), face_x=0.0, jaw_len=30.0):
    """四爪单动卡盘：卡盘体轴线沿 x、端面在 face_x（卡盘体在 −x 一侧）；四个卡爪各自径向调整，grips 为四个爪的夹持面
    到卡盘轴线的距离（依次在 +z、+y、−z、−y 方向）。每个爪单独动，所以能夹偏心件、方件，也能按划线或千分表找正。"""
    a = Assembly("四爪单动卡盘")
    body = S.cyl("x", (0, 0), D / 2, face_x - 70, face_x) - S.cyl("x", (0, 0), 30, face_x - 71, face_x + 1)
    for k in range(4):                                   # 卡爪导槽
        body = body - S.rot(S.box(face_x - 8, face_x + 1, -14, 14, 40, D / 2 + 1), 90 * k, 0, 0)
    a.add(Part("卡盘体", body, "steel"))
    for k, r in enumerate(grips):
        jaw = S.box(face_x, face_x + jaw_len, -12, 12, r, r + 22) + S.box(face_x - 8, face_x, -12, 12, r, r + 40)
        screw = S.cyl("z", (face_x - 30, 0), 7, D / 2 - 20, D / 2 + 4)          # 调整丝杠（每爪一根）
        a.add(Part(f"卡爪{k + 1}", S.rot(jaw, 90 * k, 0, 0), "hardened"))
        a.add(Part(f"丝杠{k + 1}", S.rot(screw, 90 * k, 0, 0), "steel_dark"))
    return a


def surface_gauge(base_at=(0, 0, 0), tip=(0, 0, 100)):
    """划针盘：底座在 base_at（底面），立柱竖直，划针从立柱上的夹头伸向 tip。"""
    bx, by, bz = base_at
    a = Assembly("划针盘")
    a.add(Part("底座", S.box(bx - 40, bx + 40, by - 28, by + 28, bz, bz + 18), "cast"))
    a.add(Part("立柱", S.cyl("z", (bx, by), 6, bz + 18, tip[2] + 60), "steel"))
    a.add(Part("夹头", S.cbox(bx, by, tip[2], 18, 18, 14), "steel_dark"))
    import build123d as bd
    L = math.dist((bx, by, tip[2]), tip)
    mid = ((bx + tip[0]) / 2, (by + tip[1]) / 2, tip[2])
    ang = math.degrees(math.atan2(tip[1] - by, tip[0] - bx))
    needle = bd.Pos(*mid) * (bd.Rot(0, 0, ang) * (bd.Rot(0, 90, 0) * bd.Cone(1.6, 0.3, L)))
    a.add(Part("划针", needle, "hardened"))
    return a


def touch_probe(x, y, z_tip, ball=3.0, L=40.0):
    """机床测头（触发式）：测针红宝石球心在 (x, y, z_tip + ball)，测针竖直，测头体和刀柄在上面。"""
    import build123d as bd
    a = Assembly("测头")
    a.add(Part("测球", bd.Pos(x, y, z_tip + ball) * bd.Sphere(ball), "red"))
    a.add(Part("测针", S.cyl("z", (x, y), 1.2, z_tip + ball, z_tip + L), "steel_dark"))
    a.add(Part("测头体", S.cyl("z", (x, y), 13, z_tip + L, z_tip + L + 45), "steel"))
    a.add(Part("刀柄", S.cyl("z", (x, y), 22, z_tip + L + 45, z_tip + L + 80), "steel_dark"))
    return a


# ---------------------------------------------------------------- 定位元件（补充 elements.py）
def self_aligning_support(at=(0, 0, 0), span=30.0, d=10.0):
    """自位支承（浮动支承）：摆块绕中间的销摆动，两端两个接触点同时贴住工件，只起一个支承点的作用。
    接触点顶面在 at 的 z，两点沿 x 相距 span。"""
    x, y, z = at
    rocker = S.box(x - span / 2 - 6, x + span / 2 + 6, y - 8, y + 8, z - 16, z - 6)
    for sx in (-1, 1):
        rocker = rocker + S.cyl("z", (x + sx * span / 2, y), d / 2, z - 6, z)
    seat = S.box(x - 12, x + 12, y - 14, y + 14, z - 36, z - 16) - S.box(x - 13, x + 13, y - 8.5, y + 8.5, z - 22, z - 15)
    pin = S.cyl("y", (x, z - 16), 3, y - 15, y + 15)
    return {"摆块": rocker, "支座": seat, "销": pin}


def locating_sleeve(d=40.0, L=40.0, at=(0, 0, 0), D=None):
    """定位套：轴线沿 x，左端面在 at 的 x，孔径 d（与工件外圆间隙配合），带安装法兰。"""
    x, y, z = at
    D = D or d + 24
    s = S.cyl("x", (y, z), D / 2, x, x + L) + S.cyl("x", (y, z), D / 2 + 12, x, x + 10)
    s = s - S.cyl("x", (y, z), d / 2, x - 1, x + L + 1) - S.revolve([(x + L - 3, d / 2 - 0.01), (x + L + 0.01, d / 2 + 2), (x + L + 0.01, d / 2 - 0.01)], "x", (y, z))
    return s


def half_bore_seat(d=60.0, L=50.0, at=(0, 0, 0), H=None):
    """半圆孔定位座：下半圆孔定位（底座），上半圆盖用螺钉压紧；轴线沿 x，孔心在 at。"""
    x, y, z = at
    H = H or d * 0.4
    W = d + 40
    base = S.box(x - L / 2, x + L / 2, y - W / 2, y + W / 2, z - d / 2 - H, z) - S.cyl("x", (y, z), d / 2, x - L / 2 - 1, x + L / 2 + 1)
    cap = S.box(x - L / 2, x + L / 2, y - W / 2, y + W / 2, z + 2, z + d / 2 + 14) - S.cyl("x", (y, z), d / 2, x - L / 2 - 1, x + L / 2 + 1)
    bolts = S.cyl("z", (x, y - W / 2 + 9), 5, z - 20, z + d / 2 + 22) + S.cyl("z", (x, y + W / 2 - 9), 5, z - 20, z + d / 2 + 22)
    return {"下座": base, "上盖": cap, "螺栓": bolts}


def taper_mandrel(d=35.0, L=120.0, taper=1 / 1000, at=(0, 0, 0), exaggerate=1.0):
    """小锥度心轴：轴线沿 x，小端在 at 的 x，直径 d 向大端增大 taper·L（exaggerate 放大锥度便于看清），两端有中心孔。"""
    x, y, z = at
    k = taper * exaggerate
    prof = [(x - 25, 0), (x - 25, d * 0.4), (x, d * 0.4), (x, d / 2), (x + L, d / 2 + k * L / 2), (x + L, d * 0.4), (x + L + 25, d * 0.4), (x + L + 25, 0)]
    return S.revolve(prof, "x", (y, z))


def expanding_mandrel(d=35.0, L=60.0, at=(0, 0, 0), slots=6):
    """胀胎心轴（弹性套筒式）：开缝的弹性套筒套在锥面上，拉杆把锥体拉进去，套筒胀开撑紧工件内孔。轴线沿 x，左端面在 at 的 x。
    返回 {心轴体, 弹性套, 拉杆}。"""
    x, y, z = at
    body = S.cyl("x", (y, z), d * 0.9, x - 30, x) + S.revolve([(x, 0), (x, d * 0.32), (x + L, d * 0.26), (x + L, 0)], "x", (y, z))
    sleeve = S.cyl("x", (y, z), d / 2, x + 2, x + L - 2) - S.revolve([(x + 1, 0), (x + 1, d * 0.33), (x + L - 1, d * 0.27), (x + L - 1, 0)], "x", (y, z))
    for k in range(slots):
        ang = 360 / slots * k
        sleeve = sleeve - S.rot(S.box(x + 8 if k % 2 else x + 1, x + L - 1 if k % 2 else x + L - 8, y - 0.8, y + 0.8, z, z + d), ang, 0, 0, about=(x, y, z))
    rod = S.cyl("x", (y, z), d * 0.12, x - 80, x + L + 6) + S.hexagon("x", (y, z), d * 0.4, x + L, x + L + 8)
    return {"心轴体": body, "弹性套": sleeve, "拉杆": rod}


def cone_pin(d=20.0, at=(0, 0, 0), half_angle=30.0, h=14.0):
    """锥销：顶面在 at 的 z 以上 h，锥面插入孔口，限制三个移动。"""
    x, y, z = at
    r0 = d / 2 + h * math.tan(math.radians(half_angle))
    r1 = max(1.0, d / 2 - 2)
    return S.revolve([(z - 16, 0), (z - 16, d * 0.35), (z, d * 0.35), (z, r0), (z + h, r1), (z + h, 0)], "z", (x, y))


def face_driver(at=(0, 0, 0), D=60.0, pins=6):
    """浮动前顶尖与端面驱动器：轴线沿 x，驱动器端面在 at 的 x；中心的顶尖由弹簧顶出（可轴向退让，只定心），
    端面上一圈驱动齿压进工件端面传递扭矩，工件轴向由驱动器端面（经驱动齿）确定。返回 {驱动器体, 驱动齿, 浮动顶尖, 弹簧}。"""
    x, y, z = at
    body = S.cyl("x", (y, z), D / 2, x - 50, x - 3) - S.cyl("x", (y, z), 9.5, x - 51, x - 2)
    teeth = None
    for k in range(pins):
        a = 2 * math.pi * k / pins
        t = S.cyl("x", (y + 0.32 * D * math.cos(a), z + 0.32 * D * math.sin(a)), 3.5, x - 4, x + 1.5)
        teeth = t if teeth is None else teeth + t
    tip = x + 6
    center = S.revolve([(tip, 0), (tip - 12, 6.93), (tip - 12, 9), (x - 45, 9), (x - 45, 0)], "x", (y, z))
    spring = S.tube("x", (y, z), 9, 6.5, x - 50, x - 46)
    return {"驱动器体": body, "驱动齿": teeth, "浮动顶尖": center, "弹簧": spring}


def bearing(d=35.0, D=72.0, B=17.0, at=(0, 0, 0)):
    """深沟球轴承（简化为内外圈和保持架）：轴线沿 x，左端面在 at 的 x。"""
    x, y, z = at
    inner = S.tube("x", (y, z), d / 2 + (D - d) * 0.18, d / 2, x, x + B)
    outer = S.tube("x", (y, z), D / 2, D / 2 - (D - d) * 0.18, x, x + B)
    cage = S.tube("x", (y, z), (D + d) / 4 + 3, (D + d) / 4 - 3, x + B * 0.3, x + B * 0.7)
    return {"内圈": inner, "外圈": outer, "保持架": cage}


# ---------------------------------------------------------------- 测量与上下料
def cmm(table=(-300, 300, -250, 250), z_table=0.0, probe_at=(0, 0, 100), bridge_y=0.0):
    """三坐标测量机（龙门式，简化）：花岗岩工作台顶面在 z_table，龙门沿 y 移动到 bridge_y，测座在 probe_at（测球球心）。"""
    x0, x1, y0, y1 = table
    px, py, pz = probe_at
    a = Assembly("三坐标测量机")
    a.add(Part("花岗岩工作台", S.box(x0, x1, y0, y1, z_table - 120, z_table), "#6f6f73"))
    top = pz + 260
    for sx in (x0 + 20, x1 - 20):
        a.add(Part(f"立柱{sx}", S.box(sx - 20, sx + 20, bridge_y - 30, bridge_y + 30, z_table, top), "#e8e8ea"))
    a.add(Part("横梁", S.box(x0, x1, bridge_y - 30, bridge_y + 30, top, top + 50), "#e8e8ea"))
    a.add(Part("滑架", S.box(px - 45, px + 45, bridge_y - 45, bridge_y + 45, top - 20, top + 70), "steel"))
    a.add(Part("Z 轴", S.box(px - 18, px + 18, py - 18, py + 18, pz + 60, top), "#e8e8ea"))
    import build123d as bd
    a.add(Part("测头", S.cyl("z", (px, py), 12, pz + 30, pz + 60) + S.cyl("z", (px, py), 1.5, pz, pz + 30), "steel_dark"))
    a.add(Part("测球", bd.Pos(px, py, pz) * bd.Sphere(2.0), "red"))
    return a


def gripper(at=(0, 0, 0), opening=60.0, finger_h=40.0):
    """机器人两指气动手爪（简化）：法兰在上，手指张开距离 opening，手指下端在 at 的 z，手爪中心线竖直过 at。"""
    x, y, z = at
    a = Assembly("手爪")
    a.add(Part("手爪体", S.box(x - opening / 2 - 20, x + opening / 2 + 20, y - 20, y + 20, z + finger_h, z + finger_h + 30), "steel"))
    a.add(Part("法兰", S.cyl("z", (x, y), 30, z + finger_h + 30, z + finger_h + 42) + S.cyl("z", (x, y), 22, z + finger_h + 42, z + finger_h + 120), "steel_dark"))
    for sx in (-1, 1):
        a.add(Part(f"手指{sx}", S.box(x + sx * opening / 2 - (8 if sx > 0 else 0), x + sx * opening / 2 + (0 if sx > 0 else 8), y - 14, y + 14, z, z + finger_h), "hardened"))
    return a


def plate_with_holes(L=200.0, B=120.0, t=20.0, holes=((-70, -35), (70, 35)), D=12.0, at=(0, 0, 0)):
    """一面两孔定位的板形工件：底面在 at 的 z，两个定位孔 Ø D（贯通，孔口倒角）。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z, z + t)
    for hx, hy in holes:
        s = s - S.cyl("z", (x + hx, y + hy), D / 2, z - 1, z + t + 1) - S.revolve([(z - 0.01, D / 2 + 1.5), (z + 1.5, D / 2 - 0.01), (z - 0.01, D / 2 - 0.01)], "z", (x + hx, y + hy))
    return s
