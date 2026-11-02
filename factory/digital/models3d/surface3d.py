# -*- coding: utf-8 -*-
"""表面质量与表面强化的三维模型（第 13 轮 11.4（4）；《机械制造技术》第 55 章）。

- rolling_fillet：两顶尖装夹的 SH-301，滚压工具压在轴肩圆角上（滚压强化）；
- shot_peening：喷嘴、弹丸流与转动的工件（喷丸强化）；
- gear_shaft：齿轮轴 SH-101 的简化模型（齿轮段用齿形截面拉伸），可在轴承位标出烧伤带与裂纹（第 55.0 节）。
工件轴线沿 x，左端面 x = 0。尺寸是示意的，图注要写明。"""
from __future__ import annotations

import math

from . import shapes as S
from .core import Assembly, Part


def _gear_section(r_tip: float, r_root: float, z: int, m: int = 8):
    """简化齿形截面（梯形齿）：z 个齿，齿顶宽约为齿距的 0.3、齿根宽 0.5。返回 yz 平面上的多边形顶点。"""
    pts = []
    for i in range(z):
        a0 = 2 * math.pi * i / z
        p = 2 * math.pi / z
        for frac, r in ((0.0, r_root), (0.22, r_root), (0.35, r_tip), (0.65, r_tip), (0.78, r_root)):
            a = a0 + frac * p
            pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def gear_shaft(burn: bool = False, crack: bool = False):
    """SH-101 齿轮轴（示意）：左轴颈 Ø25 × 22、齿轮段（齿顶 Ø48、18 齿）× 30、轴身 Ø30 × 40、右轴颈 Ø25 × 22、轴伸 Ø20 × 36。
    burn=True：左轴颈表面画出一条回火烧伤带（深色环）；crack=True：烧伤带上一条沿周向的细裂纹。返回 Assembly。"""
    a = Assembly("SH-101 齿轮轴")
    segs = [(25, 22), (30, 6), (None, 30), (30, 40), (25, 22), (20, 36)]
    x = 0.0
    body = None
    marks = {}
    for d, L in segs:
        if d is None:
            sec = _gear_section(24.0, 19.5, 18)
            part = S.prism("yz", sec, x, x + L)
            marks["gear"] = (x, x + L)
        else:
            part = S.cyl("x", (0, 0), d / 2, x, x + L)
        body = part if body is None else body + part
        if d == 25 and "journal" not in marks:
            marks["journal"] = (x, x + L)
        x += L
    a.add(Part("SH-101", body, "work", 1))
    if burn:
        x0, x1 = marks["journal"]
        a.add(Part("烧伤带", S.tube("x", (0, 0), 12.62, 12.45, x0 + 5, x1 - 5), "#6b4a2e", 2))
    if crack:
        x0, x1 = marks["journal"]
        xm = (x0 + x1) / 2
        a.add(Part("磨削裂纹", S.tube("x", (0, 0), 12.66, 12.3, xm - 0.25, xm + 0.25) & S.box(xm - 1, xm + 1, -13, 13, 3, 13), "red", 3))
    a.anchors.update({"journal": ((marks["journal"][0] + marks["journal"][1]) / 2, 0.0, 12.5), "gear": (sum(marks["gear"]) / 2, 0.0, 24.0)})
    return a


def rolling_fillet(x_fillet: float = 52.0, r_shaft: float = 17.5, d_roller: float = 30.0, r_edge: float = 2.0, tilt_deg: float = 45.0):
    """滚压轴肩圆角：SH-301（成品）支在两顶尖上，默认在左轴承位与齿轮位之间的轴肩（x = 52，Ø35 一侧），滚压头上的滚轮（直径 d_roller、刃口圆弧 r_edge）以 tilt_deg 倾斜压在圆角上。
    滚压力沿滚轮轴线的法向。返回 Assembly，anchors 有滚压点 roll 与滚压力方向的起点 push。"""
    from . import elements as E
    from .workpiece import sh301
    a = Assembly("滚压轴肩圆角")
    a.add(Part("SH-301", sh301("op60").shape, "work", 1))
    a.add(Part("前顶尖", E.center(at=(0, 0, 0), toward=1), "hardened", 2))
    a.add(Part("后顶尖", E.center(at=(167, 0, 0), toward=-1), "hardened", 3))
    t = math.radians(tilt_deg)
    # 滚轮：轴线在 xy 平面内与 x 轴成 tilt，接触点在 (x_fillet, -r_shaft, 0)
    cx, cy = x_fillet - (d_roller / 2) * math.sin(t), -r_shaft - (d_roller / 2) * math.cos(t)
    roller = S.cyl("z", (0, 0), d_roller / 2, -6, 6)
    roller = S.rot(roller, ax=90)                    # 轴线转到 y
    roller = S.rot(roller, az=-tilt_deg)
    roller = S.move(roller, cx, cy, 0)
    a.add(Part("滚轮", roller, "hardened", 4))
    # 滚压头：支架与杆
    ax_dir = (math.sin(t), math.cos(t))
    far = (cx - ax_dir[0] * 0 - math.sin(t) * 25, cy - math.cos(t) * 25)
    fork = S.box(-9, 9, -10, 10, -14, 14)
    fork = S.rot(fork, az=-tilt_deg)
    fork = S.move(fork, far[0], far[1], 0)
    a.add(Part("滚压头", fork + S.move(S.rot(S.cyl("y", (0, 0), 7, -90, -10), az=-tilt_deg), far[0], far[1], 0), "steel_dark", 5))
    a.anchors.update({"roll": (x_fillet, -r_shaft, 0.0), "push": (far[0], far[1], 0.0)})
    return a


def shot_peening(r_work: float = 30.0, L: float = 60.0, n_shot: int = 60, seed: int = 55):
    """喷丸：工件（圆环，代表谐波减速器柔轮）绕 x 轴转动，喷嘴从 −y 方向喷出弹丸（球，直径放大画）。返回 Assembly。"""
    import random
    rng = random.Random(seed)
    a = Assembly("喷丸")
    a.add(Part("工件（柔轮示意）", S.tube("x", (0, 0), r_work, r_work - 2.5, 0, L), "work", 1))
    a.add(Part("喷嘴", S.cyl("y", (L / 2, 0), 6, -r_work - 90, -r_work - 40), "steel_dark", 2))
    b = S.bd()
    shots = None
    for _ in range(n_shot):
        y = -r_work - 40 + rng.random() * 38
        spread = (y + r_work + 40) / 38 * 8 + 3
        x = L / 2 + rng.uniform(-spread, spread)
        z = rng.uniform(-spread, spread)
        s = b.Pos(x, y, z) * b.Sphere(0.9)
        shots = s if shots is None else shots + s
    a.add(Part("弹丸", shots, "steel", 3))
    a.anchors.update({"nozzle": (L / 2, -r_work - 40, 0.0), "hit": (L / 2, -r_work, 0.0)})
    return a
