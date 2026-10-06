# -*- coding: utf-8 -*-
"""键槽铣夹具 JJ-301-50 的三维模型（第 52 章；尺寸取自 std/JJ-301-50_fixture.yaml 与工艺规程）。

坐标：x 沿工件轴线（齿轮位左端即左轴肩在 x = 0，工作台进给方向），y 横向，z 向上，夹具体顶面 z = 0。
V 形块顶点（两工作面交线）离夹具体顶面 20 mm；工件放在 V 形块上，齿轮位 Ø40.3，轴心高 zc = 20 + 20.15/sin45°。
压板按设计数据：螺柱离压工件点 l_work = 40，后支点再往外 l_heel = 50（夹紧力计算用的就是这两个尺寸）。
序号与明细栏（parts）一致。
"""
from __future__ import annotations

import functools
import math
import os

import yaml

from .core import Assembly, Part
from . import workpiece as W

STD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std"))
APEX = 20.0                  # V 形块顶点高度
V_LEN = 60.0                 # V 形块长（= 齿轮位长度）
VB_HOLES = [(12, -28, 6.8, 20), (48, 28, 6.8, 20), (48, -28, 8, 12), (12, 28, 8, 12)]   # V 形块底面的孔：x, y, 直径, 深（M8 底孔 6.8）
SB_HOLES = [(144, -4, 5.0, 14), (144, 21, 5.0, 14), (139, 8.5, 6, 10), (149, 8.5, 6, 10)]   # 对刀块底面：2×M6 螺孔（底孔 5）、2×Ø6 销孔
BODY = dict(x0=-75.0, x1=170.0, y0=-62.0, y1=100.0, t=30.0)
STRAP_X = (-20.0, 80.0)      # 两个压板的位置：离 V 形块两端各 20 mm
EAR = 14.0                   # U 形耳座伸出长度


@functools.lru_cache(maxsize=1)
def data() -> dict:
    with open(os.path.join(STD, "JJ-301-50_fixture.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def geometry() -> dict:
    """主要尺寸（程序和书中核对用）。"""
    fx = data()
    a = math.radians(fx["locating"]["alpha"]) / 2
    d_g = 40.3
    zc = APEX + d_g / 2 / math.sin(a)
    cl = fx["clamping"]
    return {"zc": zc, "apex": APEX, "half_angle": a, "d_g": d_g, "l_work": cl["l_work"], "l_heel": cl["l_heel"],
            "stud_y": cl["l_work"], "heel_y": cl["l_work"] + cl["l_heel"], "key_spacing": fx["keys"]["spacing"],
            "setting_top": APEX + fx["setting"]["top_from_v_apex"], "setting_side": fx["setting"]["side_from_v_plane"],
            "work_x0": -52.0}


def _box(x0, x1, y0, y1, z0, z1):
    import build123d as bd
    return bd.Pos((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2) * bd.Box(x1 - x0, y1 - y0, z1 - z0)


def _cyl_z(x, y, z0, z1, r):
    import build123d as bd
    return bd.Pos(x, y, z0) * bd.Cylinder(r, z1 - z0, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))


def _prism_yz(pts, x0, x1):
    """yz 平面上的多边形沿 x 拉伸（x0 → x1）。"""
    import build123d as bd
    with bd.BuildPart() as bp:
        with bd.BuildSketch(bd.Plane.YZ.offset(x0)):
            with bd.BuildLine():
                bd.Polyline(*pts, close=True)
            bd.make_face()
        bd.extrude(amount=x1 - x0)
    return bp.part


def _prism_xz(pts, y0, y1):
    import build123d as bd
    with bd.BuildPart() as bp:
        with bd.BuildSketch(bd.Plane.XZ.offset(-y0)):
            with bd.BuildLine():
                bd.Polyline(*pts, close=True)
            bd.make_face()
        bd.extrude(amount=-(y1 - y0))
    return bp.part


def body():
    """1 夹具体（HT200）：底板、两端 U 形耳座、底面两条定位键槽、压板后支点的凸台。"""
    b = BODY
    s = _box(b["x0"], b["x1"], b["y0"], b["y1"], -b["t"], 0)
    for ex0, ex1 in ((b["x0"] - EAR, b["x0"]), (b["x1"], b["x1"] + EAR)):
        ear = _box(ex0, ex1, -20, 20, -b["t"], -12)
        # U 形缺口（宽 18，开口朝外）
        cx = ex0 if ex0 < b["x0"] else ex1
        u = _box(min(cx, cx + (8 if ex0 < b["x0"] else -8)) - 0.1, max(cx, cx + (8 if ex0 < b["x0"] else -8)) + 0.1, -9, 9, -b["t"] - 1, -11)
        u = u + _cyl_z(cx + (8 if ex0 < b["x0"] else -8), 0, -b["t"] - 1, -11, 9)
        s = s + ear - u
    g = geometry()
    for kx in (-40.0, -40.0 + g["key_spacing"]):
        s = s - _box(kx - 12.5, kx + 12.5, -9, 9, -b["t"] - 1, -b["t"] + 6)       # 定位键槽
    for sx in STRAP_X:                                                            # 后支点凸台
        s = s + _box(sx - 16, sx + 16, g["heel_y"] - 10, g["heel_y"] + 10, 0, 34)
    return s


def vblock():
    """3 V 形块（20Cr 渗碳淬火）：90° V 形槽，顶点高 20；中间退刀，只留两端各 18 mm 的工作面；顶点处开空刀槽。"""
    fx = data()
    a = math.radians(fx["locating"]["alpha"]) / 2
    land = fx["locating"]["v_land"]
    H, half = 50.0, 40.0
    s = _box(0, V_LEN, -half, half, 0, H)
    w = (H - APEX) * math.tan(a)
    groove = _prism_yz([(-w - 5 * math.tan(a), H + 5), (0, APEX), (w + 5 * math.tan(a), H + 5)], -1, V_LEN + 1)
    s = s - groove
    # 中间退刀 1.5 mm：两工作面之间的 V 面整体后退
    r = 1.5 / math.sin(a)
    relief = _prism_yz([(-w - 6, H + 5), (0, APEX - r), (w + 6, H + 5)], land, V_LEN - land)
    s = s - relief
    s = s - _box(-1, V_LEN + 1, -1.5, 1.5, APEX - 3, APEX + 1)        # 顶点空刀槽
    for x, y, d, depth in VB_HOLES:                                       # 底面：2×M8 螺孔（螺钉从夹具体下面拧入）、2×Ø8 销孔（与夹具体配作）
        s = s - _cyl_z(x, y, -1, depth, d / 2)
    return s


def stop_plate():
    """4 轴向挡板（T8 淬火）：U 形缺口宽 37，让开左轴承位 Ø35.3，只碰左轴肩的环形端面。"""
    import build123d as bd
    g = geometry()
    s = _box(-6, 0, -30, 30, 0, 60)
    notch = bd.Pos(-3, 0, g["zc"]) * bd.Cylinder(18.5, 8, rotation=(0, 90, 0)) + _box(-7, 1, -18.5, 18.5, g["zc"], 70)
    return s - notch


def strap(sx: float, z_work: float):
    """5 移动压板（45 调质）：沿 y 放置，前端压工件顶部（y = 0），中间长孔穿螺柱，后端支在可调支承上。"""
    fx = data()
    st = fx["clamping"]["strap"]
    g = geometry()
    b, h = st["b"], st["h"]
    y0, y1 = -10.0, g["heel_y"] + 10
    s = _box(sx - b / 2, sx + b / 2, y0, y1, z_work, z_work + h)
    # 长孔（宽 slot_w）：可以后退让开工件
    import build123d as bd
    sl = bd.Pos(sx, g["stud_y"] + 5, z_work + h / 2) * bd.extrude(bd.SlotOverall(30, st["slot_w"], rotation=90), amount=h, both=True)
    s = s - sl
    # 前端压头倒成弧面（线接触），简化为倒斜角
    s = s - _prism_yz([(y0 - 1, z_work - 1), (y0 + 6, z_work - 1), (y0 - 1, z_work + 5)], sx - b / 2 - 1, sx + b / 2 + 1)
    return s


def stud_nut(sx: float, z_top: float):
    """7 双头螺柱 M10、8 球面垫圈与锥面垫圈、螺母。"""
    import build123d as bd
    g = geometry()
    y = g["stud_y"]
    stud = _cyl_z(sx, y, -15, z_top + 16, 5)
    washer = _cyl_z(sx, y, z_top, z_top + 4, 10)
    nut = bd.Pos(sx, y, z_top + 4) * bd.extrude(bd.RegularPolygon(8.66, 6), amount=8)
    return stud, washer + nut


def spring(sx: float, z_top: float):
    """9 弹簧：套在螺柱上，松开时把压板顶起（简化为一圈圈的环）。"""
    import build123d as bd
    g = geometry()
    s = None
    n = 7
    for k in range(n):
        z = 2 + k * (z_top - 4) / n
        ring = bd.Pos(sx, g["stud_y"], z) * bd.Torus(8, 1.2)
        s = ring if s is None else s + ring
    return s


def heel_support(sx: float, z_top: float):
    """6 可调支承（压板后支点）：凸台上的螺钉，头部顶在压板下面。"""
    g = geometry()
    return _cyl_z(sx, g["heel_y"], 34, z_top - 3, 5) + _cyl_z(sx, g["heel_y"], z_top - 3, z_top, 7)


def setting_block():
    """10 直角对刀块（20 渗碳淬火）：内直角——底面（对刀面）在铣刀正下方，离 V 形块顶点 40.38，对槽底深度；
    侧面在 y = 9（铣刀半径 6 + 塞尺 3），对键槽中心。铣刀端面与底面、刀齿外缘与侧面之间各塞 3 mm 塞尺。"""
    g = geometry()
    side, top = g["setting_side"], g["setting_top"]
    prof = [(-12, 0), (side + 16, 0), (side + 16, top + 14), (side, top + 14), (side, top), (-12, top)]
    s = _prism_yz(prof, 135, 153) + _box(130, 158, -16, side + 20, 0, 6)
    for x, y, d, depth in SB_HOLES:
        s = s - _cyl_z(x, y, -1, depth, d / 2)
    return s


def key(kx: float):
    """2 定位键（18 h8）：嵌在夹具体底面，伸出 8 mm 进入机床 T 形槽。"""
    return _box(kx - 12, kx + 12, -9, 9, -BODY["t"] - 8, -BODY["t"] + 5.5)


def tslot_bolt(x: float):
    """13 T 形槽用螺栓 M16 与螺母、垫圈（压紧 U 形耳座）。"""
    import build123d as bd
    z0 = -BODY["t"] - 20
    bolt = _cyl_z(x, 0, z0, -6, 8) + _box(x - 14, x + 14, -7, 7, z0 - 8, z0)
    nut = _cyl_z(x, 0, -12, -9, 15) + bd.Pos(x, 0, -9) * bd.extrude(bd.RegularPolygon(13.85, 6), amount=13)
    return bolt, nut


def cutter(x: float, z_tip: float, d: float = 12.0):
    """键槽铣刀 Ø12（两刃，示意）。"""
    import build123d as bd
    body_ = _cyl_z(x, 0, z_tip, z_tip + 26, d / 2)
    shank = _cyl_z(x, 0, z_tip + 26, z_tip + 70, d / 2)
    flute = bd.Pos(x, 0, z_tip + 13) * bd.Box(d + 2, 2.2, 22)
    return body_ - flute + shank


def table(x0=-160.0, x1=260.0):
    """机床工作台（局部，带 18 mm 的 T 形槽）：只在需要表示安装时显示。"""
    z1 = -BODY["t"]
    s = _box(x0, x1, -150, 190, z1 - 50, z1)
    for y in (-90.0, 0.0, 90.0):
        s = s - _box(x0 - 1, x1 + 1, y - 9, y + 9, z1 - 20, z1 + 1) - _box(x0 - 1, x1 + 1, y - 16, y + 16, z1 - 38, z1 - 20)
    return s


def assembly(work_state="op40", with_work=True, with_cutter=False, with_table=False, explode_scale=1.0) -> Assembly:
    """JJ-301-50 总成。work_state：工件处于哪个工序状态（op40 铣键槽前，op50 铣键槽后）。"""
    import build123d as bd
    g = geometry()
    e = explode_scale
    a = Assembly("JJ-301-50")
    if with_table:
        a.add(Part("工作台", table(), "steel_dark", tags=("nocut",)))
    a.add(Part("夹具体", body(), "cast", 1, (0, 0, -60 * e)))
    for k, kx in enumerate((-40.0, -40.0 + g["key_spacing"])):
        a.add(Part(f"定位键{k + 1}", key(kx), "steel", 2, (0, 0, -110 * e)))
    a.add(Part("V 形块", vblock(), "hardened", 3, (0, 0, 40 * e)))
    a.add(Part("轴向挡板", stop_plate(), "hardened", 4, (-60 * e, 0, 40 * e)))
    z_left = g["zc"] + 15.0           # 左轴端 Ø30 顶部
    z_right = g["zc"] + 35.3 / 2      # 右轴承位 Ø35.3 顶部
    for k, (sx, zw) in enumerate(zip(STRAP_X, (z_left, z_right))):
        h = data()["clamping"]["strap"]["h"]
        a.add(Part(f"压板{k + 1}", strap(sx, zw), "steel", 5, (0, 0, 130 * e)))
        a.add(Part(f"可调支承{k + 1}", heel_support(sx, zw), "steel_dark", 6, (0, 0, 60 * e)))
        stud, nutw = stud_nut(sx, zw + h)
        a.add(Part(f"螺柱{k + 1}", stud, "steel_dark", 7, (0, 0, 85 * e)))
        a.add(Part(f"垫圈螺母{k + 1}", nutw, "steel_dark", 8, (0, 0, 175 * e)))
        a.add(Part(f"弹簧{k + 1}", spring(sx, zw), "rubber", 9, (0, 0, 100 * e)))
    a.add(Part("对刀块", setting_block(), "hardened", 10, (60 * e, 0, 30 * e)))
    for k, x in enumerate((BODY["x0"] - EAR + 8, BODY["x1"] + EAR - 8)):
        bolt, nut = tslot_bolt(x)
        a.add(Part(f"T形槽螺栓{k + 1}", bolt, "steel_dark", 13, (0, 0, -110 * e)))
        a.add(Part(f"螺母{k + 1}", nut, "steel_dark", 13, (0, 0, 60 * e)))
    if with_work:
        w = W.sh301(work_state)
        w.shape = bd.Pos(g["work_x0"], 0, g["zc"]) * w.shape
        w.name = "工件 SH-301"
        w.explode = (0, 0, 95 * e)
        a.add(w)
    if with_cutter:
        k = W.plan()["part"]["keyway"]
        xk = 52.0 + float(k["offset_mm"]) + float(k["L"]) - 6 + g["work_x0"]
        a.add(Part("键槽铣刀", cutter(xk, g["zc"] + 15.0), "tool", tags=("nocut",)))
    a.anchors.update({"work_axis": (0, 0, g["zc"]), "v_apex": (30, 0, APEX), "stop_face": (0, 19.3, g["zc"]),
                      "setting_side": (144, g["setting_side"], g["setting_top"] + 7), "setting_top": (144, 0, g["setting_top"])})
    return a
