# -*- coding: utf-8 -*-
"""SH-301 输出轴零件图（A3，1:1）与毛坯图（A4，1:1）：由三维模型 models3d/workpiece.py 投影；尺寸、公差、形位公差、粗糙度和技术要求
取自工艺规程 std/SH-301_process.yaml 的 part、characteristics。书中图 50.1.1、50.1.2 与数字工厂 PLM 里的图出自这里。"""
from __future__ import annotations

import math

from models3d import workpiece as W
from models3d import shapes as S
from .sheet import Sheet


def _chars():
    p = W.plan()
    return p, {c["id"]: c for c in p["characteristics"]}


def part_sheet() -> Sheet:
    p, ch = _chars()
    segs = p["part"]["segments"]
    k = p["part"]["keyway"]
    xs = [0.0]
    for _, L, _n in segs:
        xs.append(xs[-1] + L)
    Ltot = xs[-1]
    xk0 = xs[2] + float(k["offset_mm"])
    xk1 = xk0 + float(k["L"])
    xkm = (xk0 + xk1) / 2
    bw = float(k["b"])
    z_bot = 20.0 - float(k["t"])
    # 键槽转到朝向观察者（−y 一侧），主视图上画出键槽的形状（轴类零件图的习惯画法）
    shaft = S.rot(W.sh301("op60").shape, 90, 0, 0)
    sh = Sheet("A3", title="输出轴", code="SH-301", material="45", scale_text="1:1", mass=f"{p['part']['mass_kg']:g} kg", qty="1",
               designer="", date="")
    fv = sh.view([(shaft, 1)], "front", 1.0, ref3=(0, 0, 0), at=(70, 125), hidden=False)
    # 移出断面 A–A：沿 +x 看，上方向取 −y，键槽在上
    sv = sh.view([(shaft, 1)], d=(1, 0, 0), up=(0, -1, 0), scale=1.0, ref3=(xkm, 0, 0), at=(320, 125), hidden=False,
                 section=((xkm, 0, 0), (-1, 0, 0)))
    sh.centerline(fv, (0, 0, 0), (Ltot, 0, 0), extend=5)
    sh.center_mark(sv, (xkm, 0, 0), 20)
    sh.section_label(fv, (xkm, 0, -27), (xkm, 0, 27), "A")
    # 直径：标公差带代号（偏差查 GB/T 1800）
    dia = {0: ("Ø30 h8", 15), 1: ("Ø35 k6", 17.5), 2: ("Ø40 k6", 20), 3: ("Ø35 k6", 17.5), 4: ("Ø30 h8", 15)}
    dx = {0: 0, 1: 0, 2: 26.5, 3: 0, 4: 0}
    for i, (txt, r) in dia.items():
        sh.dia_dim(fv, ((xs[i] + xs[i + 1]) / 2 + dx[i], 0, 0), 2 * r, txt, offset=0)
    # 长度：40、12、60、25 和总长 167；右轴端长 30 不注（开口环，与工艺规程 tolerance_chart.drawing 一致）
    y1 = 38.0
    for i in range(4):
        sh.dim(fv, (xs[i], 0, -dia[i][1]), (xs[i + 1], 0, -dia[i][1]), f"{segs[i][1]:g}", offset=-(y1 - dia[i][1]))
    sh.dim(fv, (0, 0, -15), (Ltot, 0, -15), f"{Ltot:g}", offset=-(y1 + 14 - 15))
    # 键槽：在主视图的槽形上标位置 7.5 和长 45
    sh.dim(fv, (xs[2], 0, 6), (xk0, 0, 6), f"{k['offset_mm']:g}", offset=34)
    sh.dim(fv, (xk0, 0, 6), (xk1, 0, 6), f"{k['L']:g}", offset=34)
    # 断面图：键槽宽（代号）、d − t₁（叠写偏差）
    c5 = ch["C5"]
    sh.dim(sv, (xkm, -z_bot, bw / 2), (xkm, -z_bot, -bw / 2), "12 N9", offset=14)
    sh.dim(sv, (xkm, 20, -24), (xkm, -z_bot, -24), f"{c5['nominal']:g}", orient="v", offset=-16, dev=(c5["es"], c5["ei"]))
    sh.note(sv.at((xkm, -40, 0)), "A–A", 5, anchor="middle")
    # 基准：A、B 对齐两轴承位的尺寸线，C 对齐齿轮位 Ø40 的尺寸线
    for i, letter in ((1, "A"), (3, "B"), (2, "C")):
        xm = (xs[i] + xs[i + 1]) / 2 + dx[i]
        sh.datum(fv.at((xm, 0, -dia[i][1])), letter, direction=(0, 1))
    # 径向圆跳动：箭头垂直于外圆（竖直向下指向上母线），框格在正上方
    for i, val, h in ((1, "0.012", 30), (2, "0.015", 44), (3, "0.012", 30)):
        x = (xs[i] + xs[i + 1]) / 2 + (-10 if i == 2 else 0)
        t = fv.at((x, 0, dia[i][1]))
        sh.gdt(t, (t[0], t[1] - h), "↗", val, "A–B", via=(t[0], t[1] - h))
    # 端面圆跳动：箭头平行于轴线，指在齿轮位左端面（左轴承的定位轴肩）上
    f = fv.at((xs[2], 0, 18.8))
    sh.gdt(f, (f[0] - 14, f[1] - 52), "↗", "0.02", "A–B", via=(f[0] - 10, f[1]))
    sh.line((f[0] - 10, f[1]), (f[0] - 14, f[1] - 52 + 0.0))
    # 对称度：被测要素是键槽中心平面，箭头与 12 N9 的尺寸线对齐
    dl = sv.at((xkm, -z_bot, -bw / 2))
    y_dim = sv.at((xkm, -z_bot, 0))[1] - 14
    sh.gdt((dl[0], y_dim), (dl[0] + 18, y_dim - 14), "⌯", "0.02", "C", via=(dl[0] + 8, y_dim))
    # 粗糙度：轴承位、齿轮位 Ra 0.8 标在下母线上（引出），键槽两侧 Ra 3.2
    for i, xr, dxl in ((1, xs[1] + 3, -16), (2, xs[3] - 4, 14), (3, xs[4] - 3, 16)):
        q = fv.at((xr, 0, dia[i][1]))
        top = (q[0] + dxl, q[1] - 10)
        sh.line(q, top)
        sh.arrow(q, math.atan2(q[1] - top[1], q[0] - top[0]), 2.5)
        x0, x1 = (top[0] - 16, top[0]) if dxl < 0 else (top[0], top[0] + 16)
        sh.line((x0, top[1]), (x1, top[1]))
        sh.roughness(((x0 + x1) / 2 - 3, top[1]), "Ra 0.8")
    q32 = sv.at((xkm, -z_bot - 3, bw / 2))
    sh.leader_note(q32, (q32[0] - 18, q32[1] - 18), "两侧 Ra 3.2")
    for xe in (0.0, Ltot):                        # 轴端面 Ra 3.2
        q = fv.at((xe, 0, 9))
        sh.roughness(q, "Ra 3.2", ang=-90 if xe == 0 else 90)
    sh.roughness_rest((322, 30), "Ra 6.3")
    # 中心孔（GB/T 4459.5：要求保留的中心孔，标记写在引出线上）
    q = fv.at((0, 0, 0))
    sh.leader_note(q, (q[0] + 8, q[1] + 62), "2×GB/T 4459.5-A3.15/6.7")
    req = ["调质 217–255 HB", "未注倒角 C1.5", "未注尺寸公差按 GB/T 1804-m", "两端中心孔保留"]
    sh.requirements(req, (32, 230))
    return sh


def blank_sheet() -> Sheet:
    p, _ = _chars()
    segs, x0 = W.segments("blank")
    D, L = segs[0]
    shaft = W.sh301("op60").shape
    blank = W.sh301("blank").shape
    mass = math.pi * (D / 2) ** 2 * L * 7.85e-6
    sh = Sheet("A4", title="输出轴毛坯", code="SH-301-M", material="45 热轧圆钢", scale_text="1:1", qty="1", mass=f"{mass:.2f} kg")
    fv = sh.view([(blank, 1)], "front", 1.0, ref3=(0, 0, 0), at=(60, 90), hidden=False, phantom=[shaft])
    sh.centerline(fv, (x0, 0, 0), (x0 + L, 0, 0), extend=5)
    sh.dia_dim(fv, (x0 + L - 12, 0, 0), D, f"Ø{D:g}", offset=0)
    sh.dim(fv, (x0, 0, -D / 2), (x0 + L, 0, -D / 2), f"{L:g}±1", offset=-12)
    sh.note((60, 140), "双点画线为成品轮廓；两端各留端面余量，外圆按热轧圆钢规格", 3.5)
    sh.requirements([f"材料 45 热轧圆钢 Ø{D:g}（GB/T 702）", f"物料编码 {p['blank']['material_item']}", "锯床下料，端面垂直度 1 mm", "下料后打钢号与炉批号"], (32, 150))
    return sh
