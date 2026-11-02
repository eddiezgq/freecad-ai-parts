# -*- coding: utf-8 -*-
"""工艺路线的三维模型（第 13 轮十二（4）；《机械制造技术》第 56 章）。

- sh101(state)：SH-101 输入齿轮轴（std/SH-101_part.yaml 的尺寸，std/SH-101_route.yaml 的各道工序尺寸）的各工序状态：
  blank（棒料 Ø60×142）、op20（粗车）、op30（半精车、精车）、op40（滚齿）、op50（铣键槽）、op60（渗碳淬火）、op70（磨，成品）；
  齿形是渐开线（m2 z24，按分度圆压力角 20° 近似画出），工件轴线沿 x，左端面 x = 0（成品）。
- flange()：协作机器人关节的空心输出法兰（示意，精基准选择的例子）。
- sleeve(good)：铸件套筒的粗基准（以不加工的外圆为粗基准，壁厚均匀；以内孔毛面为粗基准，壁厚不均）。
- craft_pairs()：结构工艺性正误对照的小模型（退刀槽、越程槽、键槽方向、齿轮与轴肩的距离……）。
尺寸是示意的（法兰、套筒、正误对照），图注要写明。"""
from __future__ import annotations

import math
import os

import yaml

from . import shapes as S
from .core import Assembly, Part

STD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std")


def part101():
    with open(os.path.join(STD, "SH-101_part.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def route101():
    with open(os.path.join(STD, "SH-101_route.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def involute_gear(z=24, m=2.0, alpha=20.0, n_pts=8):
    """渐开线齿轮的端面轮廓（yz 平面上的多边形顶点）：齿顶圆 m(z + 2)、齿根圆 m(z − 2.5)，分度圆上齿厚等于半个齿距；
    基圆以下用径向直线代替过渡曲线（示意）。"""
    a = math.radians(alpha)
    r = m * z / 2
    rb, ra, rf = r * math.cos(a), r + m, r - 1.25 * m
    inv = lambda t: math.tan(t) - t                                # noqa: E731
    half = math.pi / (2 * z) + inv(a)                               # 基圆上半个齿厚对应的圆心角
    r0 = max(rb, rf)
    flank = []
    for k in range(n_pts + 1):
        rr = r0 + (ra - r0) * k / n_pts
        flank.append((rr, half - inv(math.acos(min(1.0, rb / rr)))))
    pts = []
    for i in range(z):
        c = 2 * math.pi * i / z
        pts.append((rf, c - flank[0][1]))
        pts += [(rr, c - th) for rr, th in flank]
        pts += [(rr, c + th) for rr, th in reversed(flank)]
        pts.append((rf, c + flank[0][1]))
    return [(rr * math.cos(th), rr * math.sin(th)) for rr, th in pts]


def _segments(state):
    """各段 (直径, 长度, 名称) 与左端面 x：成品取零件图，其余取路线里那一道之后的直径（未列出的段沿用上一道）。"""
    P = part101()["part"]
    segs = [(float(d), float(L), n) for d, L, n in P["segments"]]
    if state == "blank":
        b = route101()["blank"]
        return [(60.0, float(b["length_mm"]), "棒料")], -3.0
    if state == "op70":
        return segs, 0.0
    feats = {}
    for o in route101()["operations"]:
        for f in o.get("features") or []:
            feats[f["name"]] = f["size_mm"]
        if o["seq"] == int(state[2:]):
            break
    name_map = {"轴伸": "轴伸", "密封轴颈": "密封轴颈", "左轴承位": "轴承位", "右轴承位": "轴承位", "齿轮": "齿顶圆"}
    out = []
    for d, L, n in segs:
        k = name_map.get(n)
        dd = feats.get(k, d) if k else (d + (1.5 if state == "op20" else 0.0))
        out.append((float(dd), L, n))
    if state == "op20":                    # 粗车后总长 137（两端各留 0.5）
        return out, -0.5
    return out, 0.0


def sh101(state="op70", color="work"):
    """SH-101 某一工序状态的实体（Part）。op40 起齿轮段有齿形，op50 起有键槽，op60 起渗碳层（颜色由调用者设）。"""
    import build123d as bd
    from .workpiece import center_hole, revolve_x, stepped_profile
    segs, x0 = _segments(state)
    if state == "blank":
        body = bd.Pos(x0, 0, 0) * bd.Cylinder(30, segs[0][1], rotation=(0, 90, 0), align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
        return Part("SH-101 blank", body, color)
    gear_on = state in ("op40", "op50", "op60", "op70")
    prof_segs = []
    for d, L, n in segs:
        if n == "齿轮" and gear_on:
            d = 43.0                                # 齿根圆，齿形另外拉伸
        prof_segs.append((d, L))
    body = revolve_x(stepped_profile(prof_segs, x0, chamfer=1.0 if state != "op20" else 0.0, inner_chamfer=0.5))
    xs = [x0]
    for _, L, _ in segs:
        xs.append(xs[-1] + L)
    gi = next(i for i, (_, _, n) in enumerate(segs) if n == "齿轮")
    if gear_on:
        g = S.prism("yz", involute_gear(), xs[gi], xs[gi + 1])
        body = body + g
    L_tot = xs[-1] - x0
    body = body - center_hole(x0, +1, d=2.5, D=5.3) - center_hole(x0 + L_tot, -1, d=2.5, D=5.3)
    if state in ("op50", "op60", "op70"):
        k = part101()["part"]["keyway"]
        r_out = segs[0][0] / 2
        r_bottom = r_out - float(k["t"])
        top = 10.0
        slot = bd.Pos(float(k["offset_mm"]) + float(k["L"]) / 2, 0, r_bottom + top / 2) * bd.extrude(
            bd.SlotOverall(float(k["L"]), float(k["b"])), amount=top / 2, both=True)
        body = body - slot
    return Part(f"SH-101 {state}", body, color)


def sh101_assembly(state="op70", color="work"):
    a = Assembly(f"SH-101 {state}")
    a.add(sh101(state, color))
    segs, x0 = _segments(state)
    xs = [x0]
    for _, L, _ in segs:
        xs.append(xs[-1] + L)
    a.anchors.update({n: ((xs[i] + xs[i + 1]) / 2, 0.0, segs[i][0] / 2) for i, (_, _, n) in enumerate(segs)})
    return a


def flange():
    """空心输出法兰（示意）：外圆 Ø90、止口 Ø62 h7、内孔 Ø40 H7、端面 8 个 M5 螺孔，厚 18。返回 Assembly。"""
    a = Assembly("输出法兰")
    body = S.cyl("x", (0, 0), 45, 0, 10) + S.cyl("x", (0, 0), 31, 10, 18)
    body = body - S.cyl("x", (0, 0), 20, -1, 19)
    for i in range(8):
        t = 2 * math.pi * i / 8
        body = body - S.cyl("x", (37 * math.cos(t), 37 * math.sin(t)), 2.1, -1, 11)
    a.add(Part("输出法兰", body, "work"))
    a.anchors.update({"bore": (9.0, 0.0, 20.0), "spigot": (14.0, 0.0, 31.0), "face": (0.0, 0.0, 40.0), "rim": (5.0, 0.0, 45.0)})
    return a


def sleeve(good=True, ecc=3.0):
    """铸件套筒（示意）：毛坯外圆 Ø80 与内孔 Ø46 偏心 ecc（铸造型芯偏）；加工内孔到 Ø52。good=True：以外圆（不加工面）为粗基准，
    孔与外圆同轴、壁厚均匀；False：以毛坯内孔为粗基准，加工后的孔跟着型芯偏，壁厚一边厚一边薄。返回 Assembly（剖开用 section）。"""
    a = Assembly("铸件套筒")
    off = 0.0 if good else ecc
    body = S.cyl("x", (0, 0), 40, 0, 60) - S.cyl("x", (off, 0), 26, -1, 61)
    a.add(Part("套筒", body, "#b9aa98"))
    a.anchors.update({"thin": (30.0, 40 - (26 + off) / 1, 0.0), "thick": (30.0, -(40 + 26 - off) / 2, 0.0)})
    return a


def craft_pairs():
    """结构工艺性正误对照（示意）：每对 (名称, 不好的, 好的) 两个 Assembly。尺寸示意。"""
    pairs = []
    # 1 退刀槽：螺纹或磨削轴颈到轴肩处
    bad = S.cyl("x", (0, 0), 12, 0, 30) + S.cyl("x", (0, 0), 18, 30, 45)
    good = S.cyl("x", (0, 0), 12, 0, 25) + S.cyl("x", (0, 0), 9.5, 25, 30) + S.cyl("x", (0, 0), 18, 30, 45)   # 越程槽放大画出
    pairs.append(("砂轮越程槽", bad, good))
    # 2 键槽方向：两段键槽不在同一母线上
    shaft = S.cyl("x", (0, 0), 12, 0, 80)
    k1 = S.box(8, 28, -3, 3, 9, 13)
    bad = shaft - k1 - S.rot(S.box(48, 68, -3, 3, 9, 13), ax=90)
    good = shaft - k1 - S.box(48, 68, -3, 3, 9, 13)
    pairs.append(("键槽在同一母线上", bad, good))
    # 3 加工面与不加工面分开（凸台）
    bad = S.box(0, 60, -20, 20, 0, 10)
    good = S.box(0, 60, -20, 20, 0, 8) + S.box(5, 20, -12, 12, 8, 10) + S.box(40, 55, -12, 12, 8, 10)
    pairs.append(("加工面与不加工面分开", bad, good))
    # 4 孔的位置：离壁太近，钻头够不着
    wall = S.box(0, 40, 0, 40, 0, 30) + S.box(0, 8, 0, 40, 30, 60)
    bad = wall - S.cyl("z", (12, 20), 3, -1, 31)
    good = wall - S.cyl("z", (24, 20), 3, -1, 31)
    pairs.append(("孔离侧壁留出钻头的位置", bad, good))
    return pairs
