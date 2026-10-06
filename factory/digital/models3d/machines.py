# -*- coding: utf-8 -*-
"""机床附件与通用夹具的简化三维模型（第 51、52、54 章的插图用）：平口钳、三爪卡盘、分度头、回转工作台、
千分表与磁力表座、车床两顶尖（主轴端、尾座）、外圆磨床头架尾座与砂轮、立铣主轴头。
外形按常见规格的比例画，尺寸示意（以产品样本为准），不用于设计计算。"""
from __future__ import annotations

import math

from .core import Assembly, Part
from . import shapes as S


def vise(jaw_w=125.0, opening=60.0):
    """平口钳（机用虎钳）：底座、固定钳身、活动钳身、钳口板、丝杠与手柄。钳口在 x 方向夹紧，钳口顶面 z = 0。"""
    a = Assembly("平口钳")
    h = 42.0                      # 钳口高
    L = 300.0
    base = S.box(-L / 2 + 20, L / 2 - 30, -jaw_w / 2 - 20, jaw_w / 2 + 20, -h - 40, -h - 20)
    base = base + S.cyl("z", (0, 0), 95, -h - 60, -h - 40) - S.cyl("z", (0, 0), 90, -h - 61, -h - 59)
    body = S.box(-L / 2 + 20, L / 2 - 30, -jaw_w / 2 + 10, jaw_w / 2 - 10, -h - 20, -h)
    fixed = S.box(-opening / 2 - 45, -opening / 2, -jaw_w / 2, jaw_w / 2, -h - 20, 0)
    a.add(Part("钳座", base + body + fixed, "cast"))
    a.add(Part("固定钳口板", S.box(-opening / 2 - 6, -opening / 2, -jaw_w / 2, jaw_w / 2, -h + 4, 0), "hardened"))
    mov = S.box(opening / 2, opening / 2 + 55, -jaw_w / 2, jaw_w / 2, -h - 14, 0) + S.box(opening / 2 + 55, opening / 2 + 75, -30, 30, -h - 14, -h + 10)
    a.add(Part("活动钳身", mov, "cast"))
    a.add(Part("活动钳口板", S.box(opening / 2, opening / 2 + 6, -jaw_w / 2, jaw_w / 2, -h + 4, 0), "hardened"))
    xs = opening / 2 + 75
    a.add(Part("丝杠与手柄", S.cyl("x", (0, -h - 2), 9, xs, xs + 70) + S.box(xs + 62, xs + 70, -9, 9, -h - 60, -h + 50)
               + S.cyl("z", (xs + 66, 0), 6, -h + 50, -h + 80), "steel_dark"))
    return a


def chuck3(D=160.0, grip=40.0, jaws="outer", face_x=0.0):
    """三爪自定心卡盘：卡盘体（轴线沿 x，端面在 face_x，卡盘体在负方向），三个阶梯卡爪按 grip 直径收拢。"""
    a = Assembly("三爪卡盘")
    body = S.cyl("x", (0, 0), D / 2, face_x - 62, face_x) - S.cyl("x", (0, 0), 22, face_x - 63, face_x + 1)
    for k in range(3):     # 扳手方孔
        ang = math.radians(60 + 120 * k)
        body = body - S.cbox(face_x - 30, (D / 2 - 6) * math.cos(ang), (D / 2 - 6) * math.sin(ang), 14, 14, 14)
    a.add(Part("卡盘体", body, "steel"))
    for k in range(3):
        ang = 120 * k + 90
        r0 = grip / 2
        # 阶梯爪：三级台阶，夹持面在 r0
        jaw = S.union(S.box(face_x, face_x + 22, -11, 11, r0, r0 + 18), S.box(face_x, face_x + 14, -11, 11, r0 + 18, r0 + 32),
                      S.box(face_x, face_x + 7, -11, 11, r0 + 32, r0 + 46))
        jaw = S.rot(jaw, ang - 90, 0, 0)
        a.add(Part(f"卡爪{k + 1}", jaw, "hardened"))
    return a


def dividing_head():
    """万能分度头（简化）：底座、回转体、主轴（前端带三爪卡盘）、分度盘与手柄、侧面的蜗杆箱。主轴轴线沿 x，中心高 125。"""
    a = Assembly("分度头")
    H = 125.0
    a.add(Part("底座", S.box(-120, 60, -90, 90, 0, 40) - S.box(-121, 61, -9, 9, -1, 8), "cast"))
    body = S.cyl("y", (-20, H), 72, -62, 62) + S.box(-90, 50, -62, 62, 40, H)
    a.add(Part("回转体", body, "cast"))
    a.add(Part("主轴", S.cyl("x", (0, H), 30, 40, 90), "steel"))
    c = chuck3(150, 30, face_x=150.0)
    for p in c.parts:
        p.shape = S.move(p.shape, 0, 0, H)
        a.add(p)
    a.add(Part("分度盘", S.cyl("y", (-20, H), 60, -88, -70) - S.cyl("y", (-20, H), 12, -89, -69), "steel"))
    a.add(Part("手柄", S.box(-24, -16, -105, -88, H, H + 52) + S.cyl("y", (-20, H + 50), 6, -120, -88), "steel_dark"))
    return a


def rotary_table(D=250.0):
    a = Assembly("回转工作台")
    a.add(Part("底座", S.cyl("z", (0, 0), D / 2 + 10, 0, 45) + S.box(-D / 2 - 40, -D / 2 + 10, -40, 40, 0, 60), "cast"))
    t = S.cyl("z", (0, 0), D / 2, 45, 75)
    for k in range(4):
        t = t - S.rot(S.box(20, D / 2 + 1, -7, 7, 63, 76), 0, 0, 90 * k)
    t = t - S.cyl("z", (0, 0), 15, 60, 76)
    a.add(Part("工作台面", t, "steel"))
    a.add(Part("手轮", S.cyl("x", (0, 30), 40, -D / 2 - 75, -D / 2 - 62) + S.cyl("x", (0, 30), 8, -D / 2 - 62, -D / 2 - 40), "steel_dark"))
    return a


def dial_indicator(tip=(0, 0, 0), stem_dir=(0, 0, 1), base_at=(120, 0, -60)):
    """千分表与磁力表座（简化）：表头测杆末端在 tip，测杆沿 stem_dir（指向表）。"""
    a = Assembly("千分表")
    tx, ty, tz = tip
    if tuple(stem_dir) != (0, 0, 1):
        return _dial_side(a, tip, stem_dir, base_at)
    a.add(Part("表座", S.box(base_at[0] - 30, base_at[0] + 30, base_at[1] - 25, base_at[1] + 25, base_at[2] - 55, base_at[2]), "rubber"))
    # 立杆、横杆
    post = S.cyl("z", (base_at[0], base_at[1]), 6, base_at[2], tz + 70)
    # 横杆：先沿 y 从立杆伸到表头所在的 y，再沿 x 伸到表头上方（表座不在表头正侧方时是 L 形）
    bx, by = base_at[0], base_at[1]
    arm = post
    if abs(by - ty) > 0.5:
        arm = arm + S.cyl("y", (bx, tz + 64), 5, min(by, ty) - 5, max(by, ty))
    if abs(bx - tx) > 0.5:
        arm = arm + S.cyl("x", (ty, tz + 64), 5, min(tx, bx) - 5, max(tx, bx) + 5)
    a.add(Part("表杆", arm, "steel_dark"))
    stem = S.cyl("z", (tx, ty), 2.5, tz, tz + 22)
    dial = S.cyl("y", (tx, tz + 42), 28, ty - 8, ty + 8)
    a.add(Part("表头", stem + dial, "steel"))
    a.add(Part("表盘", S.cyl("y", (tx, tz + 42), 24, ty - 8.6, ty - 7.9), "#ffffff"))
    return a


def _dial_side(a, tip, stem_dir, base_at):
    """测杆水平（沿 ±x 或 ±y）的千分表：表盘朝上，横杆从表座立杆伸到表头背后。"""
    tx, ty, tz = tip
    dx, dy, _ = stem_dir
    ax = "x" if abs(dx) > 0.5 else "y"
    sgn = dx if ax == "x" else dy
    c = (tx + 42 * dx, ty + 42 * dy, tz)                      # 表盘中心
    if ax == "x":
        stem = S.cyl("x", (ty, tz), 2.5, min(tx, tx + 22 * sgn), max(tx, tx + 22 * sgn))
    else:
        stem = S.cyl("y", (tx, tz), 2.5, min(ty, ty + 22 * sgn), max(ty, ty + 22 * sgn))
    dial = S.cyl("z", (c[0], c[1]), 28, tz - 8, tz + 8)
    a.add(Part("表座", S.box(base_at[0] - 30, base_at[0] + 30, base_at[1] - 25, base_at[1] + 25, base_at[2] - 55, base_at[2]), "rubber"))
    post = S.cyl("z", (base_at[0], base_at[1]), 6, min(base_at[2], tz + 40), max(base_at[2], tz + 40))
    back = (c[0] + 30 * dx, c[1] + 30 * dy)
    arm = S.cyl("z", back, 5, tz - 8, tz + 40)
    if abs(back[0] - base_at[0]) > 1:
        arm = arm + S.cyl("x", (base_at[1], tz + 40), 5, min(back[0], base_at[0]), max(back[0], base_at[0]))
    if abs(back[1] - base_at[1]) > 1:
        arm = arm + S.cyl("y", (back[0], tz + 40), 5, min(back[1], base_at[1]), max(back[1], base_at[1]))
    a.add(Part("表杆", post + arm, "steel_dark"))
    a.add(Part("表头", stem + dial, "steel"))
    a.add(Part("表盘", S.cyl("z", (c[0], c[1]), 24, tz + 8, tz + 8.7), "#ffffff"))
    return a


def lathe_centers(L=167.0, axis_z=0.0, live_tail=True):
    """车床两顶尖装夹：主轴端（拨盘、前顶尖）在 x < 0，尾座（后顶尖、套筒）在 x > L。工件轴线沿 x，左端面 x = 0。"""
    a = Assembly("两顶尖")
    z = axis_z
    a.add(Part("主轴拨盘", S.cyl("x", (0, z), 80, -110, -60) + S.cyl("x", (0, z), 50, -170, -110)
               + S.box(-60, -40, 45, 65, z - 8, z + 8 + 50), "steel"))
    a.add(Part("前顶尖", S.revolve([(-60, 0), (-60, 9), (-12, 9), (-12, 6.5), (0, 0)], "x", (0, z)), "hardened"))
    tail = S.cyl("x", (0, z), 22, L + 25, L + 130) + S.box(L + 60, L + 200, -70, 70, z - 140, z - 30) + S.box(L + 90, L + 200, -55, 55, z - 30, z + 40)
    a.add(Part("尾座", tail, "cast"))
    a.add(Part("后顶尖", S.revolve([(L, 0), (L + 12, 6.5), (L + 12, 9), (L + 25, 12), (L + 25, 0)], "x", (0, z)), "hardened"))
    return a


def grinder_wheel(x_c, z_axis, D=400.0, B=50.0, side=1):
    """外圆磨床砂轮（局部）：轴线沿 x，在工件的 y 方向一侧（side）。"""
    r = D / 2
    return S.tube("x", (side * (r + 0.0), z_axis), r, 60, x_c - B / 2, x_c + B / 2)


def mill_spindle(x, y, z_tip, cutter_d=12.0, cutter_L=26.0):
    """立铣主轴头与铣刀夹头（局部）。"""
    a = Assembly("铣床主轴")
    a.add(Part("铣刀", S.cyl("z", (x, y), cutter_d / 2, z_tip, z_tip + cutter_L) - S.cbox(x, y, z_tip + cutter_L / 2, cutter_d + 2, 2, cutter_L - 4)
               + S.cyl("z", (x, y), cutter_d / 2, z_tip + cutter_L, z_tip + cutter_L + 30), "tool"))
    a.add(Part("夹头", S.cyl("z", (x, y), 20, z_tip + cutter_L + 20, z_tip + cutter_L + 60), "steel"))
    a.add(Part("主轴头", S.cyl("z", (x, y), 45, z_tip + cutter_L + 60, z_tip + cutter_L + 150), "cast"))
    return a
