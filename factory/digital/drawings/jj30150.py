# -*- coding: utf-8 -*-
"""键槽铣夹具 JJ-301-50 的总图（A3，1:2）：主视图、俯视图、A–A 剖视（过 V 形块中部），零件序号、明细栏、技术要求和主要尺寸。
由三维模型 models3d/jj30150.py 投影；书中图 52.1.5 与数字工厂 PLM 里的总图出自这里。"""
from __future__ import annotations

import math

from models3d import jj30150 as J
from .sheet import Sheet


def sheet() -> Sheet:
    fx = J.data()
    g = J.geometry()
    a = J.assembly("op40")
    work = [p.shape for p in a.parts if p.name.startswith("工件")]
    shapes = [(p.shape, p.number) for p in a.parts if not p.name.startswith("工件")]
    s = 0.5
    sh = Sheet("A3", title="键槽铣夹具", code=fx["id"], material="", scale_text="1:2", qty="1", mass="",
               designer=fx.get("designer", ""), date=str(fx.get("date", "")))
    # 主视图：x 方向 −89…184、z −38…约 100；放在图纸左上
    fv = sh.view(shapes, "front", s, ref3=(0, 0, 0), at=(105, 82), hidden=False, phantom=work)
    tv = sh.view(shapes, "top", s, ref3=(0, 0, 0), at=(105, 185), hidden=False, phantom=work)
    lv = sh.view(shapes, "left", s, ref3=(30, 0, 0), at=(262, 82), hidden=False, section=((30, 0, 0), (-1, 0, 0)), nocut=(5, 6, 7, 8, 9, 13),
                 phantom=work, name="A–A")
    zc = g["zc"]
    zl, zr = zc + 15.0, zc + 35.3 / 2
    h = fx["clamping"]["strap"]["h"]
    for v, p1, p2 in ((fv, (-62, 0, zc), (125, 0, zc)), (tv, (-62, 0, 0), (125, 0, 0))):
        sh.centerline(v, p1, p2)
    sh.centerline(lv, (30, 0, -45), (30, 0, zc + 30))
    sh.centerline(lv, (30, -30, zc), (30, 30, zc))
    sh.section_label(tv, (30, -70, 0), (30, 108, 0), "A")
    # 尺寸
    xl, xr = J.BODY["x0"] - J.EAR, J.BODY["x1"] + J.EAR
    sh.dim(fv, (xl, 0, -30), (xr, 0, -30), f"{xr - xl:g}", offset=-16)
    sh.dim(fv, (-40, 0, -38), (160, 0, -38), f"{fx['keys']['spacing']:g}", offset=-8)
    sh.dim(tv, (0, J.BODY["y0"], 0), (0, J.BODY["y1"], 0), f"{J.BODY['y1'] - J.BODY['y0']:g}", orient="v", offset=60)
    side, top = g["setting_side"], g["setting_top"]
    sb = fx["setting"]
    sh.dim(lv, (30, 0, top + 14), (30, side, top + 14), f"{sb['side_from_v_plane']:g}±{sb['side_tol']:g}", offset=22, text_shift=-9)
    sh.dim(lv, (30, -12, J.APEX), (30, -12, top), f"{sb['top_from_v_apex']:.2f}±{sb['top_tol']:g}", orient="v", offset=-31)
    k = fx["keys"]["key"]
    sh.dim(lv, (30, -9, -38), (30, 9, -38), f"18 h8（{k[1]:g}/{k[2]:+g}）".replace("+", "−") if k[2] < 0 else "18 h8", offset=-7)
    sh.note(lv.at((30, -24, 47)), "90°", 3.5, anchor="middle")
    sh.dim(lv, (30, 0, -30), (30, 0, zc), f"{zc + 30:.2f}", orient="v", offset=58)
    ztop = zr + h + 16
    sh.dim(fv, (xl, 0, -38), (xl, 0, ztop), f"{ztop + 38:.0f}", orient="v", offset=8)
    # 零件序号（主视图上方一行、俯视图右侧一列）
    sh.balloon_row(fv, [(1, (-70, 0, -15)), (4, (-3, 0, 40)), (3, (45, 0, 30)), (5, (-20, 0, zl + 7)), (8, (80, 0, zr + h + 6)),
                        (7, (80, 0, zr + h + 15)), (10, (148, 0, 40)), (13, (177, 0, -5))], along="x", at=16, gap=11)
    # 主视图下方一行：定位键（底面）、弹簧、可调支承（俯视图里被压板挡住）
    sh.balloon_row(fv, [(2, (-40, 0, -34)), (9, (-20, 0, zl - 12)), (6, (80, 0, 20))], along="x", at=123, gap=14)
    sh.balloon_row(tv, [(11, (40, 30, 0)), (12, (144, 0, 0))], along="y", at=213, gap=10)
    # 明细栏、技术要求
    sh.bom([(r[0], r[4], r[1], r[2], r[3], r[5]) for r in fx["parts"]])
    sh.requirements(fx["requirements"], (32, 233))
    return sh


def svg() -> str:
    return sheet().svg()
