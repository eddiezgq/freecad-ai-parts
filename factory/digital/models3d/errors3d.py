# -*- coding: utf-8 -*-
"""误差放大的工件形状（第 13 轮 9.4（2）；《机械制造技术》第 54 章）：锥形、鼓形、鞍形、弯曲、椭圆、棱圆。

形状由轮廓数据生成：沿轴向的半径 r(x)（回转体）、截面的半径 r(θ)（拉伸）、轴线的挠度 y(x)（放样）。
数据可以取自 hub/accuracy.py 的计算结果（让刀量、锥度、谐波），误差按 scale 放大画出，图注要写明放大倍数。
工件轴线沿 x，左端面 x = 0。"""
from __future__ import annotations

import math

from . import shapes as S


def profile_shaft(xs, rs):
    """回转体：xs 处的半径 rs（已放大）。锥形、鼓形、鞍形都用它。"""
    pts = [(xs[0], 0.0)] + list(zip(xs, rs)) + [(xs[-1], 0.0)]
    return S.revolve(pts, "x", (0, 0))


def shape_shaft(kind: str, L: float = 167.0, r: float = 20.0, amount: float = 3.0, n: int = 25):
    """标准形状：kind = cylinder、taper（右端大 amount）、drum（中间大 amount）、saddle（中间小 amount）。amount 是半径上的量（已放大）。"""
    xs = [L * i / (n - 1) for i in range(n)]
    if kind == "taper":
        rs = [r - amount / 2 + amount * x / L for x in xs]
    elif kind == "drum":
        rs = [r + amount * (1 - (2 * x / L - 1) ** 2) - amount / 2 for x in xs]
    elif kind == "saddle":
        rs = [r - amount * (1 - (2 * x / L - 1) ** 2) + amount / 2 for x in xs]
    else:
        rs = [r] * n
    return profile_shaft(xs, rs)


def section_shaft(r_of_theta, L: float = 120.0, x0: float = 0.0, m: int = 144):
    """截面形状沿 x 拉伸：r_of_theta(θ) 给出截面的半径（已放大）。椭圆、三棱形、多棱形用它。"""
    pts = [(r_of_theta(2 * math.pi * i / m) * math.cos(2 * math.pi * i / m), r_of_theta(2 * math.pi * i / m) * math.sin(2 * math.pi * i / m))
           for i in range(m)]
    return S.prism("yz", pts, x0, x0 + L)


def lobed(r: float = 20.0, k: int = 2, amp: float = 2.0, phase: float = 0.0):
    """k 阶谐波的截面：r(θ) = r + amp·cos(k(θ − phase))。k = 2 椭圆，3 三棱形。"""
    return lambda t: r + amp * math.cos(k * (t - phase))


def bent_shaft(L: float = 167.0, r: float = 20.0, bow: float = 4.0, n: int = 13, ys=None):
    """弯曲的轴：轴线在 y 方向的挠度 y(x)（默认正弦形，中间最大 bow；或给 ys，与等分的 n 个截面对应），用圆截面放样。"""
    b = S.bd()
    xs = [L * i / (n - 1) for i in range(n)]
    ys = ys if ys is not None else [bow * math.sin(math.pi * x / L) for x in xs]
    secs = [b.Plane(origin=(x, y, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0)) for x, y in zip(xs, ys)]
    faces = [b.Face(b.Wire.make_circle(r, pl)) for pl in secs]
    return b.Solid.make_loft([f.outer_wire() for f in faces])


def lathe_between_centers(L: float = 167.0, r_work: float = 20.15, tool_x: float = 120.0, tool_y: float = None,
                          bed_from: float = -360.0, bed_to: float = None, tail_offset: float = 0.0, cut_side: int = -1):
    """车床两顶尖车外圆（简化整机）：床身与两条导轨、主轴箱、拨盘与前顶尖、尾座与后顶尖、床鞍、中滑板、刀架与车刀。
    工件轴线沿 x、过原点；车刀从 −y 一侧（cut_side = −1，靠操作者一侧）沿 y 切入，刀尖在 (tool_x, tool_y, 0)；
    误差敏感方向是 y（水平面），z 是切向（垂直面）。tail_offset：尾座顶尖沿 y 的偏移（放大画）。返回 Assembly。"""
    from .core import Assembly, Part
    from . import elements as E
    a = Assembly("两顶尖车外圆")
    bed_to = bed_to if bed_to is not None else L + 330
    ty = tool_y if tool_y is not None else cut_side * r_work
    a.add(Part("床身", S.box(bed_from, bed_to, -230, 230, -420, -300), "cast", 1))
    for yg in (-150, 150):
        a.add(Part("导轨" if yg < 0 else "导轨（后）", S.box(bed_from, bed_to, yg - 35, yg + 35, -300, -270), "steel", 2))
    a.add(Part("主轴箱", S.box(bed_from, -150, -200, 200, -270, 140), "cast", 3))
    a.add(Part("拨盘", S.cyl("x", (0, 0), 85, -150, -62) + S.box(-62, -48, 40, 56, -8, 8), "steel_dark", 4))
    a.add(Part("前顶尖", E.center(at=(0, 0, 0), toward=1), "hardened", 5))
    t = tail_offset
    ts = S.box(L + 75, L + 260, -150 + t, 150 + t, -270, -140) + S.box(L + 75, L + 260, -110 + t, 110 + t, -140, 45) \
        + S.cyl("x", (t, 0), 28, L + 22, L + 75)
    a.add(Part("尾座", ts, "cast", 6))
    a.add(Part("后顶尖", E.center(at=(L, t, 0), toward=-1), "hardened", 7))
    # 床鞍、中滑板、刀架、车刀
    x = tool_x
    yp = ty + cut_side * 60                  # 刀架中心
    a.add(Part("床鞍", S.box(x - 110, x + 110, -230, 230, -270, -215), "steel", 8))
    a.add(Part("中滑板", S.box(x - 70, x + 70, min(yp, 0) - 150 if cut_side < 0 else -60, max(yp, 0) + 150 if cut_side > 0 else 60,
                              -215, -170), "steel", 9))
    a.add(Part("刀架", S.box(x - 40, x + 40, yp - 40, yp + 40, -170, -12), "steel_dark", 10))
    tip_y = ty
    y_a, y_b = tip_y + cut_side * 12, yp
    shank = S.box(x - 10, x + 10, min(y_a, y_b), max(y_a, y_b), -12, 8)
    head = S.prism("xy", [(x - 10, tip_y + cut_side * 12), (x + 10, tip_y + cut_side * 12), (x + 2, tip_y), (x - 2, tip_y)], -12, 8)
    a.add(Part("车刀", shank + head, "tool", 11))
    a.anchors.update({"tip": (x, tip_y, 0.0), "center_head": (0.0, 0.0, 0.0), "center_tail": (L, t, 0.0)})
    return a
