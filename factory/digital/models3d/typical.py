# -*- coding: utf-8 -*-
"""典型夹具的三维模型（第 52 章 52.4–52.8 节）：车床、铣床、钻床、镗床、加工中心夹具，组合夹具与零点定位。

每个函数返回 Assembly：零件名、颜色、序号（图中的标注用）和爆炸方向。工件用暖色（"work"）。
结构是教材里讲的典型形式，尺寸示意；用到的元件见 elements.py。坐标：z 向上（车床夹具的回转轴沿 x）。
"""
from __future__ import annotations

import math

from .core import Assembly, Part
from . import elements as E
from . import shapes as S


# ---------------------------------------------------------------- 教学用工件
def lever_part(at=(0, 0, 0), t=20.0):
    """杠杆：大头孔 Ø20、小头孔 Ø10，中心距 100，厚 t（钻模的工件）。底面在 at 的 z，大头孔中心在 at。"""
    x, y, z = at
    s = S.cyl("z", (x, y), 22, z, z + t) + S.cyl("z", (x + 100, y), 14, z, z + t * 0.8) + S.box(x, x + 100, y - 9, y + 9, z, z + t * 0.6)
    return s - S.cyl("z", (x, y), 10, z - 1, z + t + 1)


def bracket_part(at=(0, 0, 0)):
    """支架：底板 120 × 80 × 16（两个 Ø10 工艺孔，一面两孔定位），立板上有待镗的孔 Ø40，孔轴线平行于底面、高 70。
    底面在 at 的 z，底板中心在 at。"""
    x, y, z = at
    s = S.box(x - 60, x + 60, y - 40, y + 40, z, z + 16) + S.box(x - 35, x + 35, y + 20, y + 40, z + 16, z + 100)
    s = s + S.cyl("y", (x, z + 70), 34, y + 18, y + 42)
    s = s - S.cyl("y", (x, z + 70), 20, y + 10, y + 50)
    for hx in (-45, 45):
        s = s - S.cyl("z", (x + hx, y - 22), 5, z - 1, z + 17)
    return s


def sleeve_part(D=50.0, d=30.0, L=60.0, at=(0, 0, 0), axis="x"):
    """套筒（心轴、回转钻模的工件）：轴线沿 axis，左端面在 at。"""
    x, y, z = at
    if axis == "x":
        return S.tube("x", (y, z), D / 2, d / 2, x, x + L)
    return S.tube("z", (x, y), D / 2, d / 2, z, z + L)


def box_part(L=200.0, B=140.0, H=120.0, bore=(62.0, 80.0), at=(0, 0, 0)):
    """箱体（镗模的工件，简化）：壁厚 12 的空箱，前后壁上一对同轴孔 bore（两个直径），孔轴线沿 y、高 H/2。底面中心在 at。"""
    x, y, z = at
    s = S.box(x - L / 2, x + L / 2, y - B / 2, y + B / 2, z, z + H) - S.box(x - L / 2 + 12, x + L / 2 - 12, y - B / 2 + 12, y + B / 2 - 12, z + 12, z + H + 1)
    for k, dd in enumerate(bore):
        bx = x - L / 4 + k * L / 2
        s = s + S.cyl("y", (bx, z + H / 2), dd / 2 + 12, y - B / 2 - 6, y - B / 2 + 12) + S.cyl("y", (bx, z + H / 2), dd / 2 + 12, y + B / 2 - 12, y + B / 2 + 6)
        s = s - S.cyl("y", (bx, z + H / 2), dd / 2, y - B, y + B)
    return s


def small_shaft(d=20.0, L=60.0, at=(0, 0, 0)):
    """小轴（多件铣夹具的工件）：轴线沿 x，左端在 at。"""
    x, y, z = at
    return S.cyl("x", (y, z), d / 2, x, x + L)


# ---------------------------------------------------------------- 车床夹具
def lathe_angle_plate():
    """角铁式车床夹具：花盘（回转轴沿 x）上装角铁，支架以底面和两个工艺孔（一面两销）定位在角铁上，两个压板压紧，
    对面装平衡块。待镗孔的轴线与主轴轴线重合。"""
    a = Assembly("角铁式车床夹具")
    fp = S.cyl("x", (0, 0), 160, -40, 0) - S.cyl("x", (0, 0), 30, -41, 1)
    for k in range(6):
        fp = fp - S.rot(S.box(-41, 1, 60, 140, -6, 6), 60 * k, 0, 0)
    a.add(Part("花盘", fp, "steel", 1, (-60, 0, 0)))
    # 角铁：竖直安装面贴花盘（x = 0..30），水平定位面 z = −70（工件底面），支架的待镗孔中心在主轴轴线上
    ang = S.box(0, 30, -80, 80, -150, 40) + S.box(0, 150, -80, 80, -100, -70)
    ang = ang + S.prism("xz", [(30, -100), (30, -10), (120, -100)], -60, -48) + S.prism("xz", [(30, -100), (30, -10), (120, -100)], 48, 60)
    a.add(Part("角铁", ang, "cast", 2, (40, 0, -120)))
    # 支架工件：底面贴角铁水平面，立板孔轴线沿 x（把 bracket_part 绕 z 转 −90°，孔轴线从 y 变 x）
    w = S.rot(bracket_part(at=(0, 0, 0)), 0, 0, -90)
    w = S.move(w, 90, 0, -70)                    # 孔中心：bracket 的孔在 (x, y+30, z+70) → 转后在 (30, 0, 70)
    a.add(Part("工件（支架）", w, "work", None, (90, 0, 140)))
    for k, (px, py) in enumerate(((68, -45), (68, 45))):
        a.add(Part(f"定位销{k + 1}", E.locating_pin(10, 10, "cyl" if k == 0 else "dia", at=(px, py, -70), flat_dir="x"), "hardened", 3, (90, 0, 160)))
    for k, py in enumerate((-60, 60)):
        a.add(Part(f"压板{k + 1}", S.box(105, 135, py - 12, py + 12, -54, -42), "steel", 4, (60, 0, 230)))
        a.add(Part(f"压板螺栓{k + 1}", S.cyl("z", (125, py), 5, -100, -30) + S.hexagon("z", (125, py), 16, -42, -32), "steel_dark", 5, (60, 0, 280)))
    a.add(Part("平衡块", S.box(0, 90, -70, 70, 60, 130), "steel_dark", 6, (40, 0, 120)))
    a.anchors.update({"spindle_axis": (0, 0, 0), "bore": (120, 0, 0)})
    return a


def lathe_mandrel():
    """圆柱心轴装夹套筒（两顶尖或锥柄装在主轴上）：工件以内孔和端面定位，螺母压紧。"""
    a = Assembly("心轴")
    m, nut = E.mandrel(30, 60, 50, at=(0, 0, 0))
    a.add(Part("心轴", m, "hardened", 1))
    a.add(Part("工件（套筒）", sleeve_part(50, 30, 55, at=(0, 0, 0)), "work", None, (0, 0, 70)))
    a.add(Part("开口垫圈", S.tube("x", (0, 0), 24, 15.2, 55, 61) - S.box(54, 62, -16, 16, 0, 30), "steel", 2, (25, 0, 70)))
    a.add(Part("螺母", S.move(nut, 1, 0, 0), "steel_dark", 3, (60, 0, 0)))
    return a


# ---------------------------------------------------------------- 钻床夹具（钻模）
def drill_fixed():
    """固定式钻模：夹具体上有定位支承板、圆柱销（大头孔）和挡销（小头侧面），钻模板固定在两根立柱上，
    固定钻套引导钻小头孔；工件是杠杆，螺钉压块压紧。"""
    a = Assembly("固定式钻模")
    a.add(Part("夹具体", S.box(-60, 170, -60, 60, -20, 0), "cast", 1, (0, 0, -60)))
    a.add(Part("支承板", E.support_plate(140, 40, 8, at=(50, 0, 8), n=3), "hardened", 2, (0, 0, -30)))
    a.add(Part("定位销", E.locating_pin(20, 18, at=(0, 0, 8)), "hardened", 3, (0, 0, 40)))
    a.add(Part("挡销", S.cyl("z", (100, 18), 5, 0, 30), "hardened", 4, (0, 40, 30)))
    a.add(Part("工件（杠杆）", lever_part(at=(0, 0, 8)), "work", None, (0, 0, 110)))
    for k, cx in enumerate((-40, 145)):
        a.add(Part(f"立柱{k + 1}", S.cyl("z", (cx, -40), 9, 0, 70), "steel", 5, (0, 0, 60)))
    plate = S.box(-50, 160, -55, 20, 58, 70) - S.cyl("z", (100, 0), 9, 57, 71)
    a.add(Part("钻模板", plate, "steel", 6, (0, 0, 150)))
    for n, s in E.drill_bushing("fixed", 10, 18, 12, at=(100, 0, 70)).items():
        a.add(Part(n, s, "hardened", 7, (0, 0, 190)))
    for n, s in E.swivel_screw_clamp(at=(0, 0, 30), d=10, L=30).items():
        a.add(Part("夹紧" + n, s, "steel_dark", 8, (0, 0, 230)))
    a.anchors["drill"] = (100, 0, 8)
    return a


def drill_cover():
    """盖板式钻模：钻模板直接放在工件上，以工件的一个孔和端面定位（圆柱销 + 削边销），没有夹具体；
    工件是法兰盘，钻 6 个均布孔。"""
    a = Assembly("盖板式钻模")
    flange = S.cyl("z", (0, 0), 70, 0, 18) + S.cyl("z", (0, 0), 40, 18, 40) - S.cyl("z", (0, 0), 25, -1, 41)
    a.add(Part("工件（法兰盘）", flange, "work"))
    plate = S.cyl("z", (0, 0), 72, 40, 52) - S.cyl("z", (0, 0), 30, 39, 53)
    plate = S.cyl("z", (0, 0), 72, 18, 30) - S.cyl("z", (0, 0), 41, 17, 31) + S.cyl("z", (0, 0), 42, 30, 40) - S.cyl("z", (0, 0), 26, 17, 41)
    holes = [(55 * math.cos(math.pi / 3 * k), 55 * math.sin(math.pi / 3 * k)) for k in range(6)]
    for hx, hy in holes:
        plate = plate - S.cyl("z", (hx, hy), 7.5, 17, 41)
    a.add(Part("钻模板", plate, "steel", 1, (0, 0, 80)))
    for k, (hx, hy) in enumerate(holes):
        a.add(Part(f"钻套{k + 1}", S.tube("z", (hx, hy), 7.5, 4.5, 18, 30) + S.tube("z", (hx, hy), 10, 4.5, 30, 33), "hardened", 2, (0, 0, 120)))
    a.add(Part("把手", S.cyl("z", (0, -34), 4, 40, 70) + S.cyl("z", (0, 34), 4, 40, 70) + S.box(-6, 6, -38, 38, 70, 78), "steel_dark", 3, (0, 0, 80)))
    return a


def drill_tumble():
    """翻转式钻模：箱式夹具体四面都有钻套，工件（小方块）装在里面，钻完一面翻转到下一面，夹具体底面四角有支脚。"""
    a = Assembly("翻转式钻模")
    L = 110.0
    body = S.box(-L / 2, L / 2, -L / 2, L / 2, 0, L) - S.box(-L / 2 + 12, L / 2 - 12, -L / 2 - 1, L / 2 - 12, 12, L - 12)   # 前面敞开，装卸工件
    body = body - S.cyl("z", (0, 0), 7, L - 13, L + 1) - S.cyl("y", (0, L / 2), 7, L / 2 - 13, L / 2 + 1) - S.cyl("x", (0, L / 2), 7, -L / 2 - 1, -L / 2 + 13)
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body + S.cyl("z", (sx * (L / 2 - 10), sy * (L / 2 - 10)), 6, -10, 0)
    a.add(Part("夹具体", body, "cast", 1, (0, 0, -60)))
    a.add(Part("工件（方块）", S.box(-36, 36, -36, 36, 12, 84), "work", None, (0, -120, 0)))
    for k, (axis, c, h0, h1) in enumerate((("z", (0, 0), L - 12, L + 4), ("y", (0, L / 2), L / 2 - 12, L / 2 + 4), ("x", (0, L / 2), -L / 2 - 4, -L / 2 + 12))):
        a.add(Part(f"钻套{k + 1}", S.tube(axis, c, 7, 4, h0, h1), "hardened", 2, {"z": (0, 0, 40), "y": (0, 40, 0), "x": (-40, 0, 0)}[axis]))
    for n, s in E.swivel_screw_clamp(at=(30, 0, 48), d=10, L=24).items():     # 从右侧（+x 壁）把工件推向左壁
        a.add(Part("夹紧" + n, S.rot(s, 0, -90, 0, about=(36, 0, 48)), "steel_dark", 3, (80, 0, 0)))
    return a


def drill_indexing(n=6):
    """回转式钻模：工件（套筒）套在水平心轴上，心轴连同分度盘一起转；对定销插在分度孔里定位，钻模板上的钻套钻径向孔。"""
    a = Assembly("回转式钻模")
    a.add(Part("夹具体", S.box(-80, 120, -60, 60, -20, 0) + S.box(-80, -50, -60, 60, 0, 130), "cast", 1, (0, 0, -60)))
    H = 80.0
    a.add(Part("心轴", S.cyl("x", (0, H), 14.9, -80, 100) + S.cyl("x", (0, H), 24, -50, -40), "hardened", 2, (0, 0, 40)))
    plate, _ = E.index_plate(at=(-80, 0, H), D=120, n=n)
    a.add(Part("分度盘", plate, "steel", 3, (-60, 0, 0)))
    # 对定销装在固定于夹具体顶上的支架里，从外侧（−x）插进分度盘的分度孔；拔出时向 −x 拉
    zr = H + 120 / 2 - 12
    a.add(Part("对定销支架", S.box(-80, -50, -15, 15, 130, 142) + S.box(-132, -50, -15, 15, 142, 154)
               + S.box(-132, -104, -15, 15, zr - 12, 154) - S.cyl("x", (0, zr), 5, -133, -103), "cast", 8, (0, 0, 60)))
    pin = S.cyl("x", (0, zr), 4.9, -140, -84) + S.cyl("x", (0, zr), 9, -152, -140)
    a.add(Part("对定销", pin, "steel_dark", 4, (-100, 0, 40)))
    a.add(Part("工件（套筒）", sleeve_part(50, 30, 60, at=(0, 0, H)), "work", None, (0, 0, 120)))
    a.add(Part("钻模板", S.box(-10, 70, -30, 30, H + 40, H + 52) - S.cyl("z", (30, 0), 8, H + 39, H + 53) + S.box(-50, -10, -30, 30, H + 40, H + 52), "steel", 5, (0, 0, 120)))
    a.add(Part("钻套", S.tube("z", (30, 0), 8, 5, H + 30, H + 52) + S.tube("z", (30, 0), 11, 5, H + 52, H + 56), "hardened", 6, (0, 0, 170)))
    a.add(Part("螺母", S.hexagon("x", (0, H), 26, 60, 70), "steel_dark", 7, (60, 0, 0)))
    return a


def drill_column(lowered=1.0):
    """滑柱式钻模（标准的手动滑柱钻模底座 + 专用钻模板）：两根滑柱带动钻模板升降，压下时钻模板同时压紧工件；齿轮齿条、手柄。
    lowered：1 压下（夹紧），0 升起。"""
    a = Assembly("滑柱式钻模")
    a.add(Part("底座", S.box(-90, 90, -70, 70, -30, 0) + S.box(-90, 90, 40, 70, 0, 60), "cast", 1, (0, 0, -60)))
    lift = (1 - lowered) * 50
    for k, cx in enumerate((-70, 70)):
        a.add(Part(f"滑柱{k + 1}", S.cyl("z", (cx, 55), 10, -20 + lift, 120 + lift), "steel", 2, (0, 0, 40)))
    a.add(Part("钻模板", S.box(-90, 90, -50, 70, 100 + lift, 116 + lift) - S.cyl("z", (0, -10), 9, 99 + lift, 117 + lift), "steel", 3, (0, 0, 110)))
    a.add(Part("钻套", S.tube("z", (0, -10), 9, 5, 98 + lift, 116 + lift) + S.tube("z", (0, -10), 12, 5, 116 + lift, 120 + lift), "hardened", 4, (0, 0, 150)))
    a.add(Part("工件", S.cyl("z", (0, -10), 40, 0, 70) + S.cyl("z", (0, -10), 25, 70, 100) - S.cyl("z", (0, -10), 12, 85, 101), "work", None, (0, -90, 0)))
    a.add(Part("定位套", S.tube("z", (0, -10), 46, 40.2, 0, 14), "hardened", 5, (0, 0, -20)))
    handle = S.cyl("x", (65, 30), 8, 90, 130) + S.cyl("z", (130, 65), 5, 30, 110) + S.cyl("z", (130, 65), 9, 110, 125)
    handle = S.rot(handle, -70 * (1 - lowered), 0, 0, about=(0, 65, 30))      # 齿轮轴转动，手柄跟着转：压下（夹紧）时手柄竖直
    a.add(Part("手柄", handle, "steel_dark", 6, (60, 0, 0)))
    return a


# ---------------------------------------------------------------- 铣床夹具
def mill_multi(n=4, linked=True):
    """直线进给的多件铣夹具：n 根小轴放在 n 个 V 形块上，一个螺母通过浮动压块和杠杆同时压紧（联动夹紧），对刀块在一端。"""
    a = Assembly("多件铣夹具")
    pitch = 50.0
    Lb = pitch * n + 80
    a.add(Part("夹具体", S.box(-40, Lb - 40, -60, 60, -25, 0), "cast", 1, (0, 0, -60)))
    zc = E.v_axis_height(20, apex=14.0)
    for k in range(n):
        x = k * pitch
        a.add(Part(f"V形块{k + 1}", E.vblock(B=40, L=70, H=30, apex=14.0, at=(x, 0, 0), axis="y"), "hardened", 2, (0, 0, 30)))
        a.add(Part(f"工件{k + 1}", S.cyl("y", (x, zc), 10, -35, 35), "work", None, (0, 0, 80)))
    # 联动：两个一组的浮动压块，压在两根轴上；一根拉杆穿过夹具体，底部一个螺母拉紧全部压块（经平衡杠杆）
    for g in range(n // 2):
        x0, x1 = 2 * g * pitch, (2 * g + 1) * pitch
        xm = (x0 + x1) / 2
        a.add(Part(f"浮动压块{g + 1}", S.box(x0 - 14, x1 + 14, -12, 12, zc + 10, zc + 24), "steel", 3, (0, 0, 120)))
        a.add(Part(f"拉杆{g + 1}", S.cyl("z", (xm, 0), 6, -60, zc + 34) + S.hexagon("z", (xm, 0), 18, zc + 24, zc + 34), "steel_dark", 4, (0, 0, 160)))
    if n >= 4:
        a.add(Part("平衡杠杆", S.box(pitch * 0.5 - 15, pitch * 2.5 + 15, -14, 14, -70, -58), "steel", 5, (0, 0, -60)))
        a.add(Part("夹紧螺母", S.hexagon("z", (pitch * 1.5, 0), 24, -88, -70) + S.cyl("z", (pitch * 1.5, 0), 8, -110, -58), "steel_dark", 6, (0, 0, -100)))
    a.add(Part("对刀块", E.setting_block("angle", at=(Lb - 60, 14, zc + 4), size=16), "hardened", 7, (40, 0, 30)))
    return a


def mill_circular(stations=6):
    """圆周进给铣夹具：回转工作台上均布 stations 个工位，一边加工、一边装卸。"""
    a = Assembly("圆周进给铣夹具")
    rt = S.cyl("z", (0, 0), 200, -40, 0)
    a.add(Part("回转工作台", rt, "steel", 1))
    for k in range(stations):
        ang = 2 * math.pi * k / stations
        cx, cy = 150 * math.cos(ang), 150 * math.sin(ang)
        a.add(Part(f"定位座{k + 1}", S.move(S.rot(E.vblock(B=50, L=40, H=30, apex=10, at=(0, 0, 0)), 0, 0, math.degrees(ang) + 90), cx, cy, 0), "hardened", 2,
                   (40 * math.cos(ang), 40 * math.sin(ang), 30)))
        zc = E.v_axis_height(24, apex=10)
        piece = S.move(S.rot(S.cyl("x", (0, zc), 12, -25, 25), 0, 0, math.degrees(ang) + 90), cx, cy, 0)
        a.add(Part(f"工件{k + 1}", piece, "work" if k != 1 else "machined", None, (80 * math.cos(ang), 80 * math.sin(ang), 90)))
    a.add(Part("铣刀", S.cyl("z", (150, 0), 40, 60, 90) + S.cyl("z", (150, 0), 18, 90, 150), "tool", explode=(0, 0, 120), tags=("nocut",)))
    return a


# ---------------------------------------------------------------- 镗模与加工中心
def boring_jig():
    """双面导向的镗模：底座、前后两块镗模支架（各装镗套），箱体工件以底面和两孔定位，镗杆穿过两个镗套与工件上的孔。"""
    a = Assembly("镗模")
    a.add(Part("底座", S.box(-150, 150, -170, 170, -30, 0), "cast", 1, (0, 0, -60)))
    zc = 60.0
    for k, y0 in enumerate((-130, 108)):
        sup = S.box(-140, 140, y0, y0 + 22, 0, 130)
        for bx, dd in ((-50, 62), (50, 80)):
            sup = sup - S.cyl("y", (bx, zc), dd / 2 + 16, y0 - 1, y0 + 23)
        a.add(Part(f"镗模支架{k + 1}", sup, "cast", 2, (0, -90 if k == 0 else 90, 0)))
        for bx, dd in ((-50, 62), (50, 80)):
            a.add(Part(f"镗套{k + 1}{bx}", S.tube("y", (bx, zc), dd / 2 + 16, dd / 2 - 4, y0, y0 + 22) + S.tube("y", (bx, zc), dd / 2 + 22, dd / 2 - 4, (y0 - 6) if k == 0 else (y0 + 22), (y0) if k == 0 else (y0 + 28)),
                       "hardened", 3, (0, -130 if k == 0 else 130, 0)))
    a.add(Part("工件（箱体）", box_part(200, 140, 120, at=(0, 0, 0)), "work", None, (0, 0, 160)))
    a.add(Part("镗杆", S.cyl("y", (50, zc), 36, -200, 200) + S.cbox(50, 0, zc + 40, 12, 12, 10), "tool", 4, (0, -240, 0)))
    return a


def tombstone(parts_per_face=2):
    """加工中心的立式多面夹具（“塔柱”）：托盘装在零点定位卡盘上，塔柱四面各装 parts_per_face 个工件，液压转角缸夹紧。"""
    a = Assembly("多面夹具")
    a.add(Part("托盘", S.box(-160, 160, -160, 160, 0, 30), "steel", 1, (0, 0, -40)))
    for k, (sx, sy) in enumerate(((-100, -100), (100, -100), (-100, 100), (100, 100))):
        a.add(Part(f"零点卡盘{k + 1}", E.zero_point_chuck(at=(sx, sy, 0), D=90, H=30), "steel_dark", 2, (0, 0, -90)))
        a.add(Part(f"拉钉{k + 1}", E.pull_stud(at=(sx, sy, 0)), "hardened", 3, (0, 0, -60)))
    a.add(Part("塔柱", S.box(-60, 60, -60, 60, 30, 330), "cast", 4, (0, 0, 40)))
    for f in range(4):
        for j in range(parts_per_face):
            z0 = 70 + j * 140
            # 工件（宽 64）两侧带工艺凸台（y = ±32…±52、厚 15），转角缸装在塔柱里，压凸台，不挡住要加工的外表面（x = 100）
            w = S.box(60, 100, -32, 32, z0, z0 + 100) + S.box(60, 75, -52, 52, z0 + 20, z0 + 80)
            w = S.rot(w, 0, 0, 90 * f)
            a.add(Part(f"工件{f}{j}", w, "work", None, tuple(80 * c for c in (math.cos(math.pi / 2 * f), math.sin(math.pi / 2 * f), 0))))
            for side in (-1, 1):
                for n, s in E.swing_clamp(at=(0, 0, 0), arm=30, ang_deg=0, H=50).items():
                    s2 = S.rot(S.move(S.rot(s, 0, 90, 0), 61, side * 44, z0 + 62), 0, 0, 90 * f)
                    a.add(Part(f"转角缸{f}{j}{'左右'[side > 0]}{n}", s2, "steel_dark", 5,
                               tuple(40 * c for c in (math.cos(math.pi / 2 * f), math.sin(math.pi / 2 * f), 0))))
    return a


def modular_fixture():
    """槽系组合夹具：T 形槽基础板上用方支承、V 形块、角铁、压板和螺栓组装，装一根轴铣平面（示意）。"""
    a = Assembly("组合夹具")
    a.add(Part("基础板", E.tslot_plate(360, 240, 40, slots_y=(-60, 0, 60)), "steel", 1, (0, 0, -60)))
    for k, x in enumerate((-90, 90)):
        a.add(Part(f"方支承{k + 1}", S.box(x - 30, x + 30, -30, 30, 0, 40) - S.cyl("z", (x, 0), 7, -1, 41), "steel", 2, (0, 0, 40)))
        a.add(Part(f"V形块{k + 1}", E.vblock(B=60, L=40, H=30, apex=10, at=(x, 0, 40), axis="x"), "hardened", 3, (0, 0, 80)))
    zc = 40 + E.v_axis_height(40, apex=10)
    a.add(Part("工件（轴）", S.cyl("x", (0, zc), 20, -150, 150), "work", None, (0, 0, 140)))
    for k, x in enumerate((-90, 90)):
        # 压板：前端压工件，螺栓在 T 形槽（y = −60）里，后端搭在后支承（方支承）上
        a.add(Part(f"压板{k + 1}", S.box(x - 12, x + 12, -84, 15, zc + 20, zc + 34), "steel", 4, (0, 0, 190)))
        a.add(Part(f"螺栓{k + 1}", S.cyl("z", (x, -60), 6, -20, zc + 44) + S.hexagon("z", (x, -60), 18, zc + 34, zc + 44), "steel_dark", 5, (0, 0, 230)))
        a.add(Part(f"后支承{k + 1}", S.box(x - 12, x + 12, -84, -72, 0, zc + 20), "steel", 7, (0, -40, 0)))
    a.add(Part("角铁（侧向挡块）", S.box(140, 170, -40, 40, 0, 80), "steel", 6, (40, 0, 40)))
    return a


def linked_clamp_two_dir():
    """联动夹紧：一个螺钉推动压块，同时在两个方向（侧向和向下）夹紧一块方料（浮动压块 + 斜面）。"""
    a = Assembly("双向联动夹紧")
    a.add(Part("夹具体", S.box(-80, 80, -50, 50, -20, 0) + S.box(-80, -60, -50, 50, 0, 70) + S.box(-80, 80, 30, 50, 0, 70), "cast", 1))
    a.add(Part("工件", S.box(-60, 30, -40, 30, 0, 50), "work", None, (0, 0, 90)))
    a.add(Part("浮动压块", S.prism("xz", [(30, 10), (52, 10), (52, 70), (10, 70), (10, 50), (30, 50)], -40, 20), "steel", 2, (40, 0, 60)))
    a.add(Part("斜楔", S.box(52, 70, -30, 10, 10, 40), "steel", 3, (90, 0, 0)))
    a.add(Part("螺钉", S.cyl("x", (-10, 25), 6, 70, 130) + S.hexagon("x", (-10, 25), 18, 130, 140), "steel_dark", 4, (150, 0, 0)))
    return a
