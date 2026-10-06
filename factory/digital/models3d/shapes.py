# -*- coding: utf-8 -*-
"""造型的小工具：长方体、圆柱、回转体、拉伸多边形、孔、倒角等（build123d），各模型共用。单位 mm。"""
from __future__ import annotations

import math


def bd():
    import build123d
    return build123d


def box(x0, x1, y0, y1, z0, z1):
    b = bd()
    return b.Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * b.Box(x1 - x0, y1 - y0, z1 - z0)


def cbox(cx, cy, cz, dx, dy, dz):
    b = bd()
    return b.Pos(cx, cy, cz) * b.Box(dx, dy, dz)


def cyl(axis, c, r, h0, h1):
    """沿坐标轴 axis（"x"/"y"/"z"）的圆柱：中心线过 c（另外两个坐标），从 h0 到 h1。"""
    b = bd()
    L = h1 - h0
    s = b.Cylinder(r, L, align=(b.Align.CENTER, b.Align.CENTER, b.Align.MIN))
    if axis == "z":
        return b.Pos(c[0], c[1], h0) * s
    if axis == "x":
        return b.Pos(h0, c[0], c[1]) * (b.Rot(0, 90, 0) * s)
    return b.Pos(c[0], h0, c[1]) * (b.Rot(-90, 0, 0) * s)


def tube(axis, c, r_out, r_in, h0, h1):
    return cyl(axis, c, r_out, h0, h1) - cyl(axis, c, r_in, h0 - 1, h1 + 1)


def revolve(profile, axis="x", c=(0, 0)):
    """（沿轴坐标, 半径）轮廓绕轴 axis 回转；c 为轴线在另外两个坐标上的位置。"""
    b = bd()
    with b.BuildPart() as bp:
        with b.BuildSketch(b.Plane.XY):
            with b.BuildLine():
                b.Polyline(*profile, close=True)
            b.make_face()
        b.revolve(axis=b.Axis.X)
    s = bp.part
    if axis == "x":
        return b.Pos(0, c[0], c[1]) * s
    if axis == "z":
        return b.Pos(c[0], c[1], 0) * (b.Rot(0, -90, 0) * s)
    return b.Pos(c[0], 0, c[1]) * (b.Rot(0, 0, 90) * s)


def prism(plane, pts, a0, a1):
    """平面 plane（"xy"/"yz"/"xz"）上的多边形，沿法向从 a0 拉伸到 a1。点为平面内的两个坐标（xy: (x,y)；yz: (y,z)；xz: (x,z)）。"""
    b = bd()
    if plane == "xy":
        pl = b.Plane.XY.offset(a0)
    elif plane == "yz":
        pl = b.Plane.YZ.offset(a0)
    else:
        pl = b.Plane.XZ.offset(-a0)
    with b.BuildPart() as bp:
        with b.BuildSketch(pl):
            with b.BuildLine():
                b.Polyline(*pts, close=True)
            b.make_face()
        b.extrude(amount=(a1 - a0) if plane != "xz" else -(a1 - a0))
    return bp.part


def hexagon(axis, c, s_flats, h0, h1):
    """六角（对边 s_flats），沿 z 轴。"""
    b = bd()
    r = s_flats / 2 / math.cos(math.pi / 6)
    p = b.extrude(b.RegularPolygon(r, 6), amount=h1 - h0)
    if axis == "z":
        return b.Pos(c[0], c[1], h0) * p
    if axis == "x":
        return b.Pos(h0, c[0], c[1]) * (b.Rot(0, 90, 0) * p)
    return b.Pos(c[0], h0, c[1]) * (b.Rot(-90, 0, 0) * p)


def screw(axis, c, d, h0, h1, head=True, head_dir=1):
    """内六角圆柱头螺钉（简化）：螺杆 d，头部 1.5d × d；head_dir = +1 头在 h1 一端。"""
    s = cyl(axis, c, d / 2, h0, h1)
    if head:
        if head_dir > 0:
            s = s + cyl(axis, c, 0.75 * d, h1, h1 + d) - cyl(axis, c, 0.3 * d, h1 + 0.4 * d, h1 + d + 1)
        else:
            s = s + cyl(axis, c, 0.75 * d, h0 - d, h0) - cyl(axis, c, 0.3 * d, h0 - d - 1, h0 - 0.4 * d)
    return s


def nut(c, s_flats, z0, h):
    return hexagon("z", c, s_flats, z0, z0 + h) - cyl("z", c, s_flats * 0.29, z0 - 1, z0 + h + 1)


def move(shape, dx=0.0, dy=0.0, dz=0.0):
    return bd().Pos(dx, dy, dz) * shape


def rot(shape, ax=0.0, ay=0.0, az=0.0, about=(0, 0, 0)):
    b = bd()
    return b.Pos(*about) * (b.Rot(ax, ay, az) * (b.Pos(-about[0], -about[1], -about[2]) * shape))


def union(*shapes):
    out = None
    for s in shapes:
        if s is None:
            continue
        out = s if out is None else out + s
    return out
