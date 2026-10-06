# -*- coding: utf-8 -*-
"""JJ-301-50 的两张非标准零件图（A4，1:1）：3 V 形块 JJ-301-50-03、10 对刀块 JJ-301-50-10。
由三维模型 models3d/jj30150.py 投影；尺寸、公差取自夹具数据 std/JJ-301-50_fixture.yaml 与模型常数，书中图 52.9.7、52.9.8 出自这里。

视图按第一角画法：主视图取最能表达形状的方向——V 形块和对刀块都是沿 x 拉伸的棱柱，主视图沿 +x 看（图上水平向左为 +y），
俯视图在主视图下方（从上往下看，图上向上为 +x），左视图在主视图右方（沿 −y 看，图上向右为 −x）。"""
from __future__ import annotations

import math

from models3d import jj30150 as J
from models3d import shapes as S
from .sheet import Sheet

MAIN = dict(d=(1, 0, 0), up=(0, 0, 1))
TOP = dict(d=(0, 0, -1), up=(1, 0, 0))
LEFT = dict(d=(0, -1, 0), up=(0, 0, 1))


def vblock_sheet() -> Sheet:
    fx = J.data()
    g = J.geometry()
    vb = J.vblock()
    L, land, apex, H, half = J.V_LEN, fx["locating"]["v_land"], J.APEX, 50.0, 40.0
    zc = g["zc"]
    k = 2.0
    bar = S.cyl("x", (0, zc), g["d_g"] / 2, 0, L)
    sh = Sheet("A3", title="V 形块", code="JJ-301-50-03", material="20Cr", scale_text="2:1", qty="1",
               designer=fx.get("designer", ""), date=str(fx.get("date", "")))
    mv = sh.view([(vb, 3)], scale=k, ref3=(0, 0, 0), at=(140, 180), hidden=True, phantom=[bar], **MAIN)
    lv = sh.view([(vb, 3)], scale=k, ref3=(0, 0, 0), at=(370, 180), hidden=True, **LEFT)
    # 中心线：V 形块对称面、检验棒轴线、孔
    sh.centerline(mv, (0, 0, 0), (0, 0, H))
    sh.centerline(mv, (0, -26, zc), (0, 26, zc))
    sh.centerline(lv, (0, 0, zc), (L, 0, zc))
    for x, y, d, dep in J.VB_HOLES:
        sh.centerline(mv, (0, y, 0), (0, y, dep), extend=2)
    for x in sorted({h[0] for h in J.VB_HOLES}):
        sh.centerline(lv, (x, 0, 0), (x, 0, 20), extend=2)
    # 主视图尺寸
    sh.dim(mv, (0, half, 0), (0, -half, 0), "80", offset=-24)
    ys = sorted({h[1] for h in J.VB_HOLES})
    sh.dim(mv, (0, ys[1], 0), (0, ys[0], 0), f"{ys[1] - ys[0]:g}", offset=-12)
    w_top = 2 * (H - apex)
    sh.dim(mv, (0, w_top / 2, H), (0, -w_top / 2, H), f"{w_top:g}", offset=8)
    sh.dim(mv, (0, half, 0), (0, half, H), "50", orient="v", offset=10)
    sh.dim(mv, (0, -half, 0), (0, -half, apex), f"{apex:g}", orient="v", offset=-10)
    sh.dim(mv, (0, -half, 0), (0, -half, zc), f"{zc:.2f}±0.01", orient="v", offset=-24)
    sh.dim(mv, (0, -1.5, apex - 3), (0, 1.5, apex - 3), "3", offset=-12)
    # 两工作面延长到理论顶点（细实线），角度尺寸 90°±2′
    for sy in (1, -1):
        sh.line(mv.at((0, sy * 12, apex + 12)), mv.at((0, 0, apex)))
    sh.angle_dim(mv, (0, 0, apex), (0, 1, 1), (0, -1, 1), 24, "90°±2′")
    sh.note(mv.at((0, 25, zc + 25)), f"检验棒 Ø{g['d_g']:g}（双点画线）", 3.5, anchor="middle")
    # 基准、形位公差、粗糙度
    pA = mv.at((0, 20, 0))
    sh.datum(pA, "A", direction=(0, 1))
    # 基准 B：宽度 80 的中心平面（基准符号与尺寸 80 的尺寸线对齐）；被测要素：V 形的中心平面（框格引线与尺寸 60 的尺寸线对齐）
    d80 = mv.at((0, 0, 0))
    sh.datum((d80[0] + 18, d80[1] + 24), "B", direction=(0, 1))
    c = mv.at((0, -14, zc))
    sh.gdt(c, (c[0] + 60, c[1] - 52), "∥", "0.005", "A")
    t60 = mv.at((0, 0, H))
    sh.gdt((t60[0], t60[1] - 8), (t60[0] - 70, t60[1] - 24), "⌯", "0.01", "B")
    face = mv.at((0, -14.0, apex + 14.0))
    sh.roughness(face, "Ra 0.4", ang=-45)
    sh.roughness(mv.at((0, 22.0, apex + 22.0)), "Ra 0.4", ang=45)
    bl = mv.at((0, half, 0))
    sh.line(bl, (bl[0] - 40, bl[1]))
    sh.roughness((bl[0] - 36, bl[1]), "Ra 0.8")
    sh.roughness_rest((322, 30), "Ra 3.2")
    # 左视图：长度、工作面长度、孔的位置
    sh.dim(lv, (L, 0, H), (0, 0, H), f"{L:g}", offset=8)
    sh.dim(lv, (L, 0, 0), (L - land, 0, 0), f"{land:g}", offset=-10)
    sh.dim(lv, (land, 0, 0), (0, 0, 0), f"{land:g}", offset=-10)
    xs = sorted({h[0] for h in J.VB_HOLES})
    sh.dim(lv, (xs[1], 0, 0), (xs[0], 0, 0), f"{xs[1] - xs[0]:g}", offset=-22)
    sh.dim(lv, (xs[0], 0, 0), (0, 0, 0), f"{xs[0]:g}", offset=-22)
    p1 = mv.at((0, ys[0], 20))
    sh.leader_note(p1, (p1[0] + 5, p1[1] + 75), "2×M8–6H 深 16，底孔深 20（底面）")
    p2 = mv.at((0, ys[1], 12))
    sh.leader_note(p2, (p2[0] + 5, p2[1] + 64), "2×Ø8 H7 深 12，与夹具体配作")
    q = lv.at((L / 2, 0, H - 4))
    sh.leader_note(q, (q[0] + 30, q[1] - 30), "中段退刀 1.5，不与工件接触")
    sh.requirements(["渗碳深度 0.8–1.2 mm，淬火 58–62 HRC；螺孔、销孔处防渗",
                     f"尺寸 {zc:.2f}±0.01（V 形块定位高度 T）用 Ø{g['d_g']:g} 检验棒测量",
                     "两段工作面一次磨出；对底面 A 的平行度、对宽度中心平面 B 的对称度见图",
                     "工作面磨损超过 0.005 mm 更换（维护规程，52.10 节）",
                     "未注倒角 C0.5，锐边倒钝",
                     "螺孔、销孔在底面对角布置：y 向位置见主视图，x 向位置见左视图"], (32, 238))
    return sh


def setting_block_sheet() -> Sheet:
    fx = J.data()
    g = J.geometry()
    sb = J.setting_block()
    side, top = g["setting_side"], g["setting_top"]
    x0, x1 = 135.0, 153.0
    st = fx["setting"]
    k = 2.0
    sh = Sheet("A3", title="对刀块（直角）", code="JJ-301-50-10", material="20", scale_text="2:1", qty="1",
               designer=fx.get("designer", ""), date=str(fx.get("date", "")))
    mv = sh.view([(sb, 10)], scale=k, ref3=(144, 0, 0), at=(130, 203), hidden=True, **MAIN)
    lv = sh.view([(sb, 10)], scale=k, ref3=(144, 0, 0), at=(300, 203), hidden=True, **LEFT)
    y0, y1 = -12.0, side + 16
    hy = sorted({h[1] for h in J.SB_HOLES if h[2] < 5.5})      # 螺孔
    for x, y, d, dep in J.SB_HOLES:
        sh.centerline(mv, (144, y, 0), (144, y, dep), extend=2)
        sh.centerline(lv, (x, 0, 0), (x, 0, dep), extend=2)
    # 主视图：内直角的两个对刀面
    sh.dim(mv, (144, y1, 0), (144, y1, top + 14), f"{top + 14:.2f}", orient="v", offset=36)
    sh.dim(mv, (144, side + 20, 0), (144, side + 20, top), f"({top:.2f})", orient="v", offset=12)
    sh.dim(mv, (144, y0, 0), (144, y0, 6), "6", orient="v", offset=-14)
    sh.dim(mv, (144, y1, top + 14), (144, side, top + 14), f"{y1 - side:g}", offset=8)
    sh.dim(mv, (144, side, top + 14), (144, y0, top + 14), f"({side - y0:g})", offset=8)
    sh.dim(mv, (144, side + 20, 0), (144, -16, 0), f"{side + 36:g}", offset=-26)
    sh.dim(mv, (144, hy[1], 0), (144, hy[0], 0), f"{hy[1] - hy[0]:g}", offset=-12)
    pin = [h for h in J.SB_HOLES if h[2] > 5.5]
    pa = mv.at((144, pin[0][1], 10))
    sh.leader_note(pa, (pa[0] + 60, pa[1] - 30), f"2×Ø6 H7 深 10，装配时与夹具体配作")
    pm = mv.at((144, hy[0], 14))
    sh.leader_note(pm, (pm[0] + 50, pm[1] + 14), "2×M6–6H 深 12，底孔深 14（底面）")
    pA = mv.at((144, -14, 0))
    sh.datum(pA, "A", direction=(0, 1))
    x_right = mv.at((144, -12, 0))[0]
    c1 = mv.at((144, -10, top))                      # 深度对刀面（内角底面）
    sh.gdt(c1, (x_right + 22, c1[1] + 26), "∥", "0.005", "A")
    c2 = mv.at((144, side, top + 11))                # 侧面对刀面（内角侧面）
    sh.gdt(c2, (x_right + 22, c2[1] - 22), "⊥", "0.005", "A")
    sh.roughness(mv.at((144, -4, top)), "Ra 0.4")
    p_s = mv.at((144, side, top + 9))                # 侧面的粗糙度：水平引出到图外，符号站在引出线上
    sh.line(p_s, (x_right + 40, p_s[1]))
    sh.arrow(p_s, math.pi, 2.5)
    sh.roughness((x_right + 26, p_s[1]), "Ra 0.4")
    bl = mv.at((144, side + 20, 0))
    sh.line(bl, (bl[0] - 56, bl[1]))
    sh.roughness((bl[0] - 52, bl[1]), "Ra 0.8")
    sh.roughness_rest((322, 30), "Ra 3.2")
    # 左视图：长度、孔的 x 位置
    sh.dim(lv, (x1, 0, top + 14), (x0, 0, top + 14), f"{x1 - x0:g}", offset=8)
    sh.dim(lv, (158, 0, 0), (130, 0, 0), "28", offset=-26)
    px = sorted({h[0] for h in J.SB_HOLES if h[2] > 5.5})
    sh.dim(lv, (px[1], 0, 0), (px[0], 0, 0), f"{px[1] - px[0]:g}", offset=-12)
    sh.requirements(["渗碳深度 0.8–1.2 mm，淬火 58–64 HRC；螺孔、销孔处防渗",
                     "两对刀面（内角底面为深度对刀面、内角侧面为侧面对刀面）各留磨量 0.1，装上夹具体后按检验棒配磨",
                     f"配磨后侧面到 V 形块对称面 {st['side_from_v_plane']:g}±{st['side_tol']:g}（总图技术要求 4）",
                     f"配磨后底面到 V 形块顶点 {st['top_from_v_apex']:.2f}±{st['top_tol']:g}（总图技术要求 5）",
                     "对刀面不得有磕碰、锈蚀；内角清根 R≤0.2",
                     "未注倒角 C0.5"], (32, 246))
    return sh


def svgs() -> dict:
    return {"vblock": vblock_sheet().svg(), "setting_block": setting_block_sheet().svg()}
