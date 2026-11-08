# -*- coding: utf-8 -*-
"""数量统计（第 112 轮 P5）：报价和备料的依据。只算量，不算钱（单价是企业自己的配置）。纯计算。

    贴片元件数（正面、反面）、贴片焊点数、通孔元件数和通孔焊点数、物料种类（物料清单行数）、元件总数、细间距器件数。

光绘里分不清过孔和通孔焊盘：带阻焊开窗的孔算通孔焊盘（过孔一般盖阻焊）；孔按坐标就近归到器件。"""

from __future__ import annotations

import math

from .checks import assembly
from .schema.capability import value as cap_value

NEAR_MM = 15.0


def _tht_holes(board, smd):
    """通孔焊盘的孔 → [(孔, 位号)]。KiCad 里孔带位号；光绘里看孔上有没有阻焊开窗（过孔一般盖阻焊），
    再归到通孔器件：坐标原点落在孔上的（KiCad 等软件通孔件原点在第 1 脚），或者没有贴片焊盘、附近有孔的器件。
    归不到器件的孔（安装孔等）位号留空"""
    plated = [h for h in board.holes if h.plated]
    placed = {c.ref for c in board.components}
    if any(h.ref for h in plated):
        return [(h, h.ref if h.ref in placed else "") for h in plated if h.kind == "pad"]
    from shapely.geometry import Point

    opens = [f.geom for f in board.features if f.kind == "opening"]
    pads = [h for h in plated if any(g.contains(Point(h.x, h.y)) for g in opens)]
    tht = []
    for c in board.components:
        on_hole = any(math.hypot(c.x - h.x, c.y - h.y) < 0.05 for h in pads)
        bare = c.ref not in smd and any(math.hypot(c.x - h.x, c.y - h.y) <= NEAR_MM for h in pads)
        if on_hole or bare:
            tht.append(c)
    out = []
    for h in pads:
        near = sorted((math.hypot(c.x - h.x, c.y - h.y), c.ref) for c in tht)
        out.append((h, near[0][1] if near and near[0][0] <= NEAR_MM else ""))
    return out


def count(board, cap=None):
    placed = {c.ref: c for c in board.components}
    bom_refs = {r for row in board.bom for r in row.refs}
    smd = assembly.smd_pads(board)
    tht = _tht_holes(board, smd)
    tht_refs = {ref for _, ref in tht if ref}
    smd_refs = {r for r in smd if r in placed and r not in tht_refs}
    top = sum(1 for r in smd_refs if placed[r].side == "F")
    bottom = sum(1 for r in smd_refs if placed[r].side == "B")
    fine = cap_value(cap, "fine_pitch_mm") if cap else None
    fine_refs = sorted(
        r for r in smd_refs if fine is not None and (p := assembly.pitch_of(smd[r])) is not None and p < fine - 1e-6
    )
    rows = [
        ("贴片元件", len(smd_refs), "正面 {}、反面 {}".format(top, bottom)),
        ("贴片焊点", sum(len(smd[r]) for r in smd_refs), "贴片元件的焊盘数"),
        ("通孔元件", len(tht_refs), "、".join(sorted(tht_refs))),
        (
            "通孔焊点",
            sum(1 for _, r in tht if r),
            "通孔器件的焊盘数；另有 {} 个孔不属于器件（安装孔等）".format(sum(1 for _, r in tht if not r)),
        ),
        ("物料种类", len(board.bom), "物料清单行数"),
        ("元件总数", sum(row.qty if row.qty is not None else len(row.refs) for row in board.bom), "物料清单数量合计"),
        (
            "细间距器件",
            len(fine_refs) if fine is not None else None,
            ("间距 < {:g} mm：".format(fine) + "、".join(fine_refs))
            if fine is not None
            else "工艺能力表没填细间距门槛",
        ),
        ("贴片面", (1 if top else 0) + (1 if bottom else 0), "两面都有贴片要过两次炉" if top and bottom else ""),
    ]
    notes = []
    if not board.bom:
        notes.append("没有物料清单：物料种类、元件总数没算")
    if not board.components:
        notes.append("没有坐标：贴片元件没法按面统计")
    missing = sorted(r for r in placed if bom_refs and r not in bom_refs)
    if missing:
        notes.append("坐标里有、物料清单里没有：" + "、".join(missing))
    return {"rows": [{"name": n, "value": v, "note": t} for n, v, t in rows], "notes": notes}
