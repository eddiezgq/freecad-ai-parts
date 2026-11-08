# -*- coding: utf-8 -*-
"""贴片厂关心的三项（第 112 轮 P5）：只读板子模型和工艺能力表，纯计算。

    P1 板子尺寸在本厂能贴的范围里      P2 最小引脚间距（细间距器件列出来）      P3 最小焊盘

焊盘归哪个器件：KiCad 板子文件里焊盘带位号；光绘里没有，按坐标文件就近归属（同一面、离器件中心最近，
不超过 SEARCH_MM；焊盘对器件中心的对称位置上也有焊盘的器件优先）。和钻孔重合的焊盘（通孔焊盘、过孔）不算贴片焊盘。"""

from __future__ import annotations

import math

from ..schema.capability import value as cap_value
from .basic import EPS, FAIL, PASS, UNKNOWN, _r, _unknown_cap
from .basic import WHY as _WHY

_WHY.update(
    {
        "size": "板子要放进贴片机的轨道和印刷机的夹具；太大放不进，太小夹不住（要拼板）",
        "pitch": "引脚间距越小，钢网开口越窄、锡膏越难印匀，越容易连锡；本厂设备和工艺做得到的最小间距以下就不能接",
        "pad": "焊盘太小，钢网开口出不了足够的锡，贴片吸嘴和光学检测也看不准",
    }
)
SEARCH_MM = 15.0
SAME_MM = 0.01
MIRROR_MM = 0.25  # 对称位置找焊盘的容差


def smd_pads(board):
    """{位号: [(面, 多边形)]}：贴片焊盘按器件分组"""
    holes = [(h.x, h.y) for h in board.holes if h.plated]
    out, cand = {}, []
    have_ref = any(f.ref for f in board.features if f.kind == "pad")
    comps = [c for c in board.components if c.side in ("F", "B")]
    for f in board.features:
        if f.kind != "pad" or f.layer not in ("F", "B"):
            continue
        c = f.geom.centroid
        if any(abs(c.x - hx) < SAME_MM and abs(c.y - hy) < SAME_MM for hx, hy in holes):
            continue  # 通孔焊盘、过孔
        if have_ref:
            if f.ref:
                out.setdefault(f.ref, []).append((f.layer, f.geom))
            continue
        cand.append((f, c))
    if have_ref:
        return out
    pts = {}
    for f, c in cand:
        pts.setdefault(f.layer, []).append((c.x, c.y))

    def has_pad(side, x, y):
        return any(abs(px - x) < MIRROR_MM and abs(py - y) < MIRROR_MM for px, py in pts.get(side, []))

    for f, c in cand:
        near = sorted((math.hypot(k.x - c.x, k.y - c.y), k.ref, k) for k in comps if k.side == f.layer)
        near = [n for n in near if n[0] <= SEARCH_MM]
        if not near:
            continue
        # 大多数封装的焊盘对器件中心是中心对称的：对称位置上也有焊盘的器件优先（去耦电容挨着芯片时不会归错）
        sym = [n for n in near if has_pad(f.layer, 2 * n[2].x - c.x, 2 * n[2].y - c.y)]
        ref = (sym or near)[0][1]
        out.setdefault(ref, []).append((f.layer, f.geom))
    return out


def pitch_of(pads):
    """器件焊盘中心之间的最小距离；连在一起的焊盘（例如网络连接点压在电阻焊盘上）不算。只有一个焊盘返回 None"""
    gs = [g for _, g in pads]
    best = None
    for i, a in enumerate(gs):
        ca = a.centroid
        for b in gs[i + 1 :]:
            if a.intersects(b):
                continue
            cb = b.centroid
            d = math.hypot(ca.x - cb.x, ca.y - cb.y)
            if d > 1e-6 and (best is None or d < best):
                best = d
    return best


def pad_min_of(pads):
    """器件最小的焊盘的短边（最小外接矩形的短边）"""
    best = None
    for _, g in pads:
        r = g.minimum_rotated_rectangle
        xs = list(r.exterior.coords)
        sides = [math.hypot(xs[k + 1][0] - xs[k][0], xs[k + 1][1] - xs[k][1]) for k in range(2)]
        s = min(sides)
        best = s if best is None else min(best, s)
    return best


def _where(board):
    return "" if any(f.ref for f in board.features if f.kind == "pad") else "（光绘里焊盘不带位号，按坐标就近归属）"


def p1_size(board, cap):
    mx, mn = cap_value(cap, "board_max_mm"), cap_value(cap, "board_min_mm")
    if mx is None and mn is None:
        return _unknown_cap("P1", "板子尺寸", "size", "能贴的最大 / 最小板子")
    if board.outline is None:
        return _r("P1", "板子尺寸", UNKNOWN, "size", detail="没有板框")
    x0, y0, x1, y1 = board.outline
    size = sorted((round(x1 - x0, 2), round(y1 - y0, 2)), reverse=True)
    bad, notes = [], []
    if mx is not None:
        lim = sorted(mx, reverse=True)
        if size[0] > lim[0] + EPS or size[1] > lim[1] + EPS:
            bad.append(["超过能贴的最大 {:g} × {:g} mm".format(*lim)])
    else:
        notes.append("工艺能力表没填最大板子")
    if mn is not None:
        lim = sorted(mn, reverse=True)
        if size[0] < lim[0] - EPS or size[1] < lim[1] - EPS:
            bad.append(["小于能贴的最小 {:g} × {:g} mm，要拼板".format(*lim)])
    else:
        notes.append("工艺能力表没填最小板子")
    status = FAIL if bad else (UNKNOWN if notes else PASS)
    return _r(
        "P1",
        "板子尺寸",
        status,
        "size",
        "{:g} × {:g}".format(*size),
        " ~ ".join("{:g} × {:g}".format(*sorted(v, reverse=True)) for v in (mn, mx) if v),
        "mm",
        bad,
        "；".join(notes),
    )


def p2_pitch(board, cap):
    lim, fine = cap_value(cap, "pitch_min_mm"), cap_value(cap, "fine_pitch_mm")
    groups = smd_pads(board)
    if not groups:
        return _r("P2", "最小引脚间距", UNKNOWN, "pitch", detail="板子模型里没有贴片焊盘或坐标")
    pitch = {r: p for r, pads in groups.items() if (p := pitch_of(pads)) is not None}
    cpl = {c.ref: c for c in board.components}

    def at(r):
        c = cpl.get(r)
        return [round(c.x, 2), round(c.y, 2)] if c else []

    fines = sorted((p, r) for r, p in pitch.items() if fine is not None and p < fine - EPS)
    detail = (
        "细间距器件（间距 < {:g} mm，要注意钢网和检测）：{}".format(
            fine, "、".join("{} {:.2f}".format(r, p) for p, r in fines)
        )
        if fines
        else ""
    ) + _where(board)
    if lim is None:
        return _r(
            "P2",
            "最小引脚间距",
            UNKNOWN,
            "pitch",
            round(min(pitch.values()), 3) if pitch else None,
            None,
            "mm",
            [],
            "工艺能力表没填“能贴的最小引脚间距”。" + detail,
        )
    bad = [at(r) + [r, round(p, 3)] for r, p in sorted(pitch.items()) if p < lim - EPS]
    return _r(
        "P2", "最小引脚间距", FAIL if bad else PASS, "pitch", round(min(pitch.values()), 3), lim, "mm", bad, detail
    )


def p3_pad(board, cap):
    lim = cap_value(cap, "pad_min_mm")
    if lim is None:
        return _unknown_cap("P3", "最小焊盘", "pad", "最小焊盘")
    groups = smd_pads(board)
    if not groups:
        return _r("P3", "最小焊盘", UNKNOWN, "pad", limit=lim, unit="mm", detail="板子模型里没有贴片焊盘或坐标")
    size = {r: pad_min_of(p) for r, p in groups.items()}
    cpl = {c.ref: c for c in board.components}
    bad = [
        ([round(cpl[r].x, 2), round(cpl[r].y, 2)] if r in cpl else []) + [r, round(s, 3)]
        for r, s in sorted(size.items())
        if s < lim - EPS
    ]
    return _r(
        "P3",
        "最小焊盘",
        FAIL if bad else PASS,
        "pad",
        round(min(size.values()), 3),
        lim,
        "mm",
        bad,
        "焊盘短边" + _where(board),
    )


def run(board, cap):
    return [p1_size(board, cap), p2_pitch(board, cap), p3_pad(board, cap)]
