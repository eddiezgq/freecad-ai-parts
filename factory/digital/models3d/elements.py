# -*- coding: utf-8 -*-
"""夹具元件的三维模型（第 51、52 章）：定位元件、夹紧元件、对刀导向元件、连接元件、动力元件。

结构按机床夹具零件及部件标准（JB/T 8004–8045 系列）的典型形式；尺寸取常用规格的比例，示意用，
具体尺寸以所用标准为准。每个函数返回 build123d 形体（或 Assembly），工作面的位置在说明里写明。
"""
from __future__ import annotations

import math

from .core import Assembly, Part
from . import shapes as S


# ---------------------------------------------------------------- 定位元件
def support_pin(kind="A", d=12.0, H=8.0, at=(0, 0, 0)):
    """支承钉：A 平头（精基准面）、B 球头（粗基准面）、C 网纹顶面（侧面粗基准）。头部顶面在 at 的 z（球头为顶点）。"""
    x, y, z = at
    shank = S.cyl("z", (x, y), d * 0.5 * 0.6, z - H - 12, z - H)
    if kind == "B":
        import build123d as bd
        R = d * 0.75
        sph = bd.Pos(x, y, z - R) * bd.Sphere(R)
        cylh = S.cyl("z", (x, y), d / 2, z - H, z - 0.4 * d)
        head = cylh + (sph & S.cyl("z", (x, y), d / 2, z - 0.4 * d, z))
    else:
        head = S.cyl("z", (x, y), d / 2, z - H, z)
        if kind == "C":
            for k in range(-2, 3):
                head = head - S.cbox(x + k * d / 5, y, z, 0.8, d + 1, 1.0) - S.cbox(x, y + k * d / 5, z, d + 1, 0.8, 1.0)
    return head + shank


def support_plate(L=80.0, B=20.0, H=12.0, kind="A", at=(0, 0, 0), n=2):
    """支承板：A 型光面、B 型带斜槽（容屑）；长 L 沿 x，顶面在 at 的 z，沉头螺钉孔 n 个。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z - H, z)
    for k in range(n):
        cx = x - L / 2 + L * (k + 0.5) / n
        s = s - S.cyl("z", (cx, y), 3.4, z - H - 1, z + 1) - S.cyl("z", (cx, y), 5.5, z - 3.5, z + 1)
        if kind == "B" and k < n - 1:
            s = s - S.rot(S.cbox(x - L / 2 + L * (k + 1) / n, y, z, 3, B * 2, 3), 0, 0, 45, about=(x - L / 2 + L * (k + 1) / n, y, z))
    return s


def adjustable_support(d=12.0, at=(0, 0, 0), H=30.0):
    """可调支承：六角头螺钉 + 锁紧螺母，顶面在 at 的 z。"""
    x, y, z = at
    return S.hexagon("z", (x, y), d * 1.5, z - 0.6 * d, z) + S.cyl("z", (x, y), d / 2, z - H, z - 0.6 * d) + \
        S.nut((x, y), d * 1.6, z - 0.6 * d - 4 - 0.8 * d, 0.8 * d)


def auxiliary_support(d=16.0, at=(0, 0, 0)):
    """弹簧自位式辅助支承（简化）：柱塞在弹簧作用下顶住工件，再用侧面的顶紧螺钉锁住。"""
    x, y, z = at
    body = S.box(x - 20, x + 20, y - 18, y + 18, z - 60, z - 22) - S.cyl("z", (x, y), d / 2 + 0.5, z - 61, z - 21)
    plunger = S.cyl("z", (x, y), d / 2, z - 50, z)
    body = body - S.cyl("y", (x, z - 40), 4, y - 19, y)          # 顶紧螺钉的螺孔
    lock = S.cyl("y", (x, z - 40), 4, y - 30, y - d / 2) + S.cyl("y", (x, z - 40), 7, y - 36, y - 30)     # 顶紧螺钉拧到柱塞上
    return {"body": body, "plunger": plunger, "lock": lock}


def vblock(alpha=90.0, B=72.0, L=40.0, H=40.0, apex=14.0, at=(0, 0, 0), axis="x", relief=0.0):
    """V 形块：V 槽沿 axis（"x" 或 "y"），宽 B（横向）、长 L（沿槽）、高 H，V 槽顶点（两工作面交线）离底面 apex。
    底面中心在 at。relief > 0 时中间退刀，只留两端工作面。"""
    x, y, z = at
    a = math.radians(alpha) / 2
    w = (H - apex) * math.tan(a)
    if axis == "x":
        s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z, z + H)
        g = S.prism("yz", [(y - w - 3 * math.tan(a), z + H + 3), (y, z + apex), (y + w + 3 * math.tan(a), z + H + 3)], x - L / 2 - 1, x + L / 2 + 1)
        s = s - g - S.box(x - L / 2 - 1, x + L / 2 + 1, y - 1.2, y + 1.2, z + apex - 2.5, z + apex + 1)
        for sx in (-1, 1):   # 两个螺钉沉孔、两个销孔
            s = s - S.cyl("z", (x + sx * L * 0.28, y + (B / 2 - 7) * (1 if sx > 0 else -1)), 3.4, z - 1, z + H + 1)
    else:
        s = S.box(x - B / 2, x + B / 2, y - L / 2, y + L / 2, z, z + H)
        g = S.prism("xz", [(x - w - 3 * math.tan(a), z + H + 3), (x, z + apex), (x + w + 3 * math.tan(a), z + H + 3)], y - L / 2 - 1, y + L / 2 + 1)
        s = s - g - S.box(x - 1.2, x + 1.2, y - L / 2 - 1, y + L / 2 + 1, z + apex - 2.5, z + apex + 1)
    return s


def v_axis_height(d, alpha=90.0, apex=14.0):
    """直径 d 的工件放在 V 形块上，轴心离 V 形块底面的高度。"""
    return apex + d / 2 / math.sin(math.radians(alpha) / 2)


def locating_pin(d=16.0, h=12.0, kind="cyl", at=(0, 0, 0), b=None, flat_dir="y"):
    """定位销：cyl 圆柱销、dia 菱形销（削边销，沿 flat_dir 方向削去两边，只留宽 b 的圆柱部分）；
    工作部分在 at 的 z 以上 h，头部倒锥便于导入；下部是台肩和压入部分。"""
    x, y, z = at
    s = S.revolve([(z - 18, 0), (z - 18, d * 0.4), (z - 3, d * 0.4), (z - 3, d * 0.75), (z, d * 0.75), (z, d / 2),
                   (z + h - 2, d / 2), (z + h, d / 2 - 1.5), (z + h, 0)], "z", (x, y))
    if kind == "dia":
        b = b or max(3.0, d * 0.25)
        cut = 50.0
        if flat_dir == "y":
            s = s - S.box(x - cut, x + cut, y + b / 2, y + cut, z + 0.01, z + h + 1) - S.box(x - cut, x + cut, y - cut, y - b / 2, z + 0.01, z + h + 1)
        else:
            s = s - S.box(x + b / 2, x + cut, y - cut, y + cut, z + 0.01, z + h + 1) - S.box(x - cut, x - b / 2, y - cut, y + cut, z + 0.01, z + h + 1)
    return s


def center(at=(0, 0, 0), toward=1, live=False, half=False):
    """60° 顶尖：尖端在 at，朝 x 方向 toward 指向工件；half=True 为半缺顶尖（让开车端面的车刀）。"""
    x, y, z = at
    prof = [(x, 0), (x - toward * 12, 6.93), (x - toward * 12, 9), (x - toward * 70, 12), (x - toward * 70, 0)]
    s = S.revolve(prof, "x", (y, z))
    if half:
        s = s - S.box(min(x, x - toward * 13) - 0.01, max(x, x - toward * 13) + 0.01, y, y + 20, z, z + 20)
    return s


def mandrel(d=30.0, L=60.0, collar_d=50.0, at=(0, 0, 0)):
    """圆柱心轴（带台肩和压紧螺母）：轴线沿 x，台肩端面在 at 的 x，工作部分向 +x 伸出 L。"""
    x, y, z = at
    s = S.cyl("x", (y, z), collar_d / 2, x - 12, x) + S.cyl("x", (y, z), d / 2, x, x + L) + S.cyl("x", (y, z), d * 0.35, x + L, x + L + 25) + \
        S.cyl("x", (y, z), d * 0.4, x - 60, x - 12)
    nut = S.hexagon("x", (y, z), d * 0.95, x + L + 5, x + L + 15)
    return s, nut


# ---------------------------------------------------------------- 导向元件
def drill_bushing(kind="fixed", d=10.0, D=None, H=20.0, at=(0, 0, 0), plate_t=None):
    """钻套：fixed 固定钻套（带肩，压入钻模板）；renew 可换钻套（衬套 + 钻套，螺钉压住）；quick 快换钻套（台肩上有缺口，转一下就取出）。
    钻模板顶面在 at 的 z，钻套轴线竖直过 at。返回 {部件名: 形体}。"""
    x, y, z = at
    D = D or d * 1.6 + 4
    parts = {}
    if kind == "fixed":
        parts["钻套"] = S.tube("z", (x, y), D / 2, d / 2, z - H, z) + S.tube("z", (x, y), D / 2 + 3, d / 2, z, z + 4)
    else:
        Dl = D + 6
        parts["衬套"] = S.tube("z", (x, y), Dl / 2, D / 2, z - H, z)
        b = S.tube("z", (x, y), D / 2, d / 2, z - H, z) + S.tube("z", (x, y), D / 2 + 6, d / 2, z, z + 8)
        if kind == "quick":
            b = b - S.box(x + D / 2 - 1, x + D / 2 + 8, y - 4, y + 4, z - 0.5, z + 9) - S.box(x - D / 2 - 8, x - D / 2 + 3, y + 1, y + 10, z + 3, z + 9)
        else:
            b = b - S.box(x + D / 2 + 1, x + D / 2 + 8, y - 8, y + 8, z + 3, z + 9)
        parts["钻套"] = b
        sx = x + D / 2 + 9
        parts["钻套螺钉"] = S.cyl("z", (sx, y), 3, z - 12, z) + S.cyl("z", (sx, y), 6, z, z + 3) + S.cyl("z", (sx, y), 4.5, z + 3, z + 9)
    return parts


def bushing_plate(L, B, t, holes, at=(0, 0, 0), D_holes=None):
    """钻模板：L × B × t，顶面在 at 的 z；holes 为钻套中心 [(x, y)]。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z - t, z)
    for hx, hy in holes:
        s = s - S.cyl("z", (hx, hy), (D_holes or 10) / 2, z - t - 1, z + 1)
    return s


def boring_bushing(D_bar=40.0, at=(0, 0, 0), L=50.0, axis="x", rotating=False):
    """镗套：固定式（镗杆在套内转动）或回转式（套随镗杆转，装在滚动轴承里）；轴线沿 axis，中心在 at，长 L。"""
    x, y, z = at
    if axis == "x":
        inner = S.tube("x", (y, z), D_bar / 2 + 6, D_bar / 2, x - L / 2, x + L / 2) + S.tube("x", (y, z), D_bar / 2 + 10, D_bar / 2, x + L / 2, x + L / 2 + 6)
        if rotating:
            inner = inner + S.tube("x", (y, z), D_bar / 2 + 20, D_bar / 2 + 12, x - L / 2, x + L / 2)
    else:
        inner = S.tube("z", (x, y), D_bar / 2 + 6, D_bar / 2, z - L / 2, z + L / 2) + S.tube("z", (x, y), D_bar / 2 + 10, D_bar / 2, z + L / 2, z + L / 2 + 6)
    return inner


# ---------------------------------------------------------------- 对刀与连接
def setting_block(kind="angle", at=(0, 0, 0), size=20.0):
    """对刀块：round 圆形（顶面对刀）、square 方形（顶面和一个侧面）、angle 直角（内直角：底面和侧面，铣刀放进内角一次对好两个方向，常用于铣槽）、side 侧装（侧面）。
    对刀面：顶面（直角对刀块为内角底面）在 at 的 z，侧面在 at 的 y（朝 −y）。底座在下面。"""
    x, y, z = at
    if kind == "round":
        return S.cyl("z", (x, y + size / 2), size / 2, z - 12, z) - S.cyl("z", (x, y + size / 2), 3.4, z - 13, z + 1)
    if kind == "square":
        return S.box(x - size / 2, x + size / 2, y, y + size, z - 15, z) - S.cyl("z", (x, y + size / 2), 3.4, z - 16, z + 1)
    if kind == "side":
        return S.box(x - size / 2, x + size / 2, y, y + 12, z - 30, z + 4) - S.cyl("y", (x, z - 13), 3.4, y - 1, y + 13)
    # 内直角：底面（深度对刀面）在 at 的 z、向 −y 伸出到铣刀下面；侧面在 at 的 y，向上高出 0.6 size
    return S.prism("yz", [(y - 1.2 * size, z - 30), (y + size, z - 30), (y + size, z + 0.6 * size), (y, z + 0.6 * size), (y, z), (y - 1.2 * size, z)],
                   x - size / 2, x + size / 2)


def feeler(at=(0, 0, 0), t=3.0, L=60.0, W=12.0, plane="xz"):
    """塞尺（对刀用的平塞尺），厚 t。plane = "xz"：薄的方向沿 y；"xy"：薄的方向沿 z。"""
    x, y, z = at
    if plane == "xz":
        return S.box(x - W / 2, x + W / 2, y - t, y, z - 4, z - 4 + L)
    return S.box(x - L / 2, x + L / 2, y - W / 2, y + W / 2, z, z + t)


def locating_key(at=(0, 0, 0), b=18.0, L=24.0, h_out=8.0):
    """定位键：嵌在夹具体底面的键槽里，伸出 h_out 进入机床 T 形槽，b 为键宽。顶面（嵌入部分）在 at 的 z。"""
    x, y, z = at
    return S.box(x - L / 2, x + L / 2, y - b / 2, y + b / 2, z - 5.5 - h_out, z) - S.cyl("z", (x, y), 3.4, z - 14, z + 1)


# ---------------------------------------------------------------- 夹紧元件
def moving_strap(at=(0, 0, 0), L=110.0, b=32.0, h=14.0, slot=11.0, toward=-1):
    """移动压板：前端压头在 at（底面），沿 y 方向（toward = −1 表示压头在 −y 端），长 L、宽 b、厚 h，中间长孔。"""
    x, y, z = at
    y0, y1 = (y, y + L) if toward < 0 else (y - L, y)
    s = S.box(x - b / 2, x + b / 2, y0, y1, z, z + h)
    import build123d as bd
    yc = y + 0.42 * L * (1 if toward < 0 else -1)
    s = s - bd.Pos(x, yc, z + h / 2) * bd.extrude(bd.SlotOverall(30, slot, rotation=90), amount=h, both=True)
    return s


def hook_clamp(at=(0, 0, 0), r=18.0, H=60.0, reach=26.0):
    """钩形压板（简化）：立柱绕自身轴线转动，钩头伸出 reach 压在工件上；钩头底面在 at 的 z。"""
    x, y, z = at
    post = S.cyl("z", (x, y), r * 0.55, z - H, z + 20)
    hook = S.box(x - 8, x + reach + 8, y - 10, y + 10, z, z + 14)
    return post + hook


def swivel_screw_clamp(at=(0, 0, 0), d=12.0, L=50.0, axis_dir=(0, 0, -1)):
    """螺钉夹紧（带活动压块）：压块底面在 at，螺钉竖直向上 L，顶部滚花手柄。返回 {压块, 螺钉}。"""
    x, y, z = at
    pad = S.cyl("z", (x, y), d, z, z + 6) - S.cyl("z", (x, y), d * 0.3, z + 2, z + 7)
    screw = S.cyl("z", (x, y), d / 2, z + 5, z + L) + S.cyl("z", (x, y), d * 1.2, z + L, z + L + 10) + S.cyl("x", (y, z + L + 5), 3, x - 35, x + 35)
    return {"压块": pad, "螺钉": screw}


def wedge(at=(0, 0, 0), alpha_deg=8.0, L=80.0, B=24.0, h0=10.0):
    """斜楔：沿 x 推入，上表面斜角 α，前端高 h0；底面在 at 的 z，前端在 at 的 x。"""
    x, y, z = at
    h1 = h0 + L * math.tan(math.radians(alpha_deg))
    return S.prism("xz", [(x, z), (x - L, z), (x - L, z + h1), (x, z + h0)], y - B / 2, y + B / 2)


def eccentric(at=(0, 0, 0), D=40.0, e=2.5, B=16.0, handle=80.0, angle_deg=0.0):
    """圆偏心轮：转轴沿 y 过 at，偏心距 e，几何中心相对转轴在 angle 方向（0° 向下：夹紧位置附近）；带手柄。"""
    x, y, z = at
    a = math.radians(angle_deg)
    cx, cz = x + e * math.sin(a), z - e * math.cos(a)
    disc = S.cyl("y", (cx, cz), D / 2, y - B / 2, y + B / 2) - S.cyl("y", (x, z), 4, y - B, y + B)
    hx, hz = x + (D / 2 + handle) * math.sin(a - math.pi / 2), z - (D / 2 + handle) * math.cos(a - math.pi / 2)   # 夹紧（angle 0）时手柄水平朝 −x
    import build123d as bd
    L = math.hypot(hx - x, hz - z)
    rod = bd.Pos((x + hx) / 2, y, (z + hz) / 2) * (bd.Rot(0, -math.degrees(math.atan2(hz - z, hx - x)) + 90, 0) * bd.Cylinder(4, L))
    knob = bd.Pos(hx, y, hz) * bd.Sphere(8)
    return disc + rod + knob


def toggle_clamp(at=(0, 0, 0), open_deg=0.0):
    """快速夹钳（垂直式，简化）：底座在 at，压杆末端压头向下；open_deg > 0 为打开角度。"""
    x, y, z = at
    base = S.box(x - 30, x + 10, y - 15, y + 15, z, z + 8) + S.box(x - 10, x + 10, y - 9, y + 9, z + 8, z + 40)
    arm = S.box(x, x + 70, y - 5, y + 5, z + 34, z + 44) + S.cyl("z", (x + 62, y), 5, z, z + 34) + S.cyl("z", (x + 62, y), 9, z - 4, z)
    handle = S.box(x - 70, x + 4, y - 6, y + 6, z + 48, z + 58)
    if open_deg:
        arm = S.rot(arm, 0, -open_deg, 0, about=(x, y, z + 40))
        handle = S.rot(handle, 0, -open_deg * 0.6, 0, about=(x, y, z + 40))
    return {"底座": base, "压杆": arm, "手柄": handle}


def collet(d_grip=30.0, L=70.0, at=(0, 0, 0), slots=3):
    """弹簧夹头：轴线沿 x，夹持孔 d_grip，前端锥面；开 slots 条槽。前端在 at 的 x。"""
    x, y, z = at
    D = d_grip + 14
    s = S.revolve([(x - L, d_grip / 2), (x - L, D / 2 - 2), (x - 18, D / 2 - 2), (x - 6, D / 2 + 4), (x, D / 2 + 4), (x, d_grip / 2)], "x", (y, z))
    for k in range(slots):
        ang = 360 / slots * k
        s = s - S.rot(S.box(x - L * 0.75, x + 1, y - 1, y + 1, z, z + D), ang, 0, 0, about=(x, y, z))
    return s


def cylinder_pneu(bore=50.0, stroke=40.0, at=(0, 0, 0), axis="z", ext=0.0):
    """气缸（简化）：缸体、活塞杆（伸出 ext），轴线沿 axis，缸的杆端端面在 at。"""
    x, y, z = at
    if axis == "z":
        body = S.cyl("z", (x, y), bore / 2 + 6, z - stroke - 40, z) + S.box(x - bore / 2 - 8, x + bore / 2 + 8, y - bore / 2 - 8, y + bore / 2 + 8, z - 10, z)
        rod = S.cyl("z", (x, y), bore * 0.18, z - 10, z + 20 + ext)
    else:
        body = S.cyl("x", (y, z), bore / 2 + 6, x - stroke - 40, x)
        rod = S.cyl("x", (y, z), bore * 0.18, x - 10, x + 20 + ext)
    return {"缸体": body, "活塞杆": rod}


def swing_clamp(at=(0, 0, 0), arm=40.0, ang_deg=0.0, H=70.0):
    """转角缸（转角夹紧缸，简化）：法兰面在 at，活塞杆先转 90° 再下拉；压板长 arm，ang 为压板方向（度，绕 z）。"""
    x, y, z = at
    body = S.cyl("z", (x, y), 22, z - H, z) + S.box(x - 32, x + 32, y - 32, y + 32, z - 12, z)
    rod = S.cyl("z", (x, y), 8, z, z + 30)
    a = math.radians(ang_deg)
    armv = S.rot(S.box(x - 10, x + arm, y - 9, y + 9, z + 24, z + 36) + S.cyl("z", (x + arm - 4, y), 5, z + 14, z + 24), 0, 0, ang_deg, about=(x, y, z))
    return {"缸体": body, "活塞杆": rod, "压板": armv}


def index_plate(at=(0, 0, 0), D=120.0, n=6, t=14.0):
    """分度盘与对定销：盘沿 x 轴（盘面法向 x），中心在 at，n 个分度孔；对定销在盘的上方，可插拔。"""
    x, y, z = at
    s = S.cyl("x", (y, z), D / 2, x - t, x)
    R = D / 2 - 12
    for k in range(n):
        a = 2 * math.pi * k / n
        s = s - S.cyl("x", (y + R * math.sin(a), z + R * math.cos(a)), 5, x - t - 1, x + 1)
    s = s - S.cyl("x", (y, z), 12, x - t - 1, x + 1)
    pin = S.cyl("x", (y, z + R), 4.9, x - t - 4, x + 18) + S.cyl("x", (y, z + R), 9, x + 18, x + 34)
    return s, pin


def zero_point_chuck(at=(0, 0, 0), D=138.0, H=40.0):
    """零点定位卡盘（气动快换，简化）：顶面在 at 的 z，中心有定位孔，锁紧钢球（示意）。"""
    x, y, z = at
    s = S.cyl("z", (x, y), D / 2, z - H, z) - S.cyl("z", (x, y), 13, z - H + 8, z + 1) - S.cyl("z", (x, y), 22, z - 6, z + 1)
    for k in range(4):
        a = math.pi / 4 + k * math.pi / 2
        s = s - S.cyl("z", (x + 0.38 * D * math.cos(a), y + 0.38 * D * math.sin(a)), 4.5, z - H - 1, z + 1)
    return s


def pull_stud(at=(0, 0, 0)):
    """零点定位的拉钉：装在托盘底面，尾部被卡盘里的钢球锁住拉紧。顶面（托盘底面）在 at 的 z。"""
    x, y, z = at
    return S.revolve([(z - 32, 0), (z - 32, 9), (z - 26, 12.5), (z - 22, 12.5), (z - 18, 9), (z - 8, 9), (z - 8, 21), (z, 21), (z, 0)], "z", (x, y))


def tslot_plate(L=400.0, B=300.0, t=40.0, at=(0, 0, 0), slots_y=(-100, 0, 100), w=14.0):
    """T 形槽基础板（组合夹具、工作台局部）：顶面在 at 的 z，T 形槽沿 x。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z - t, z)
    for sy in slots_y:
        s = s - S.box(x - L / 2 - 1, x + L / 2 + 1, y + sy - w / 2, y + sy + w / 2, z - 0.45 * t, z + 1) - \
            S.box(x - L / 2 - 1, x + L / 2 + 1, y + sy - w, y + sy + w, z - 0.8 * t, z - 0.45 * t)
    return s


def hole_grid_plate(L=400.0, B=300.0, t=30.0, pitch=50.0, at=(0, 0, 0)):
    """孔系基础板（孔系组合夹具）：定位孔与螺孔交替，节距 pitch。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z - t, z)
    nx, ny = int(L // pitch), int(B // pitch)
    for i in range(nx):
        for j in range(ny):
            px = x - L / 2 + pitch / 2 + i * pitch
            py = y - B / 2 + pitch / 2 + j * pitch
            r = 6 if (i + j) % 2 == 0 else 4.2
            s = s - S.cyl("z", (px, py), r, z - 12, z + 1)
    return s
