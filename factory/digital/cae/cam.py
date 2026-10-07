# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：数控车刀路（端面、分层粗车、精车、切槽）、钻孔与切削参数只留一份，在 analysis/cam/paths.py。
这里另有工厂才用的：按任意多边形（含岛，shapely）偏置的 2.5 轴铣削刀路——从 STEP 识别出的型腔、外轮廓（第 13 轮 C2）。

车削坐标（FANUC 习惯）：X 是直径（mm），Z 沿轴线，Z0 在本次装夹的右端面，向左为负。
铣削坐标：工件坐标系 G54，XY 在工件上表面，Z0 为上表面，向下为负。
"""
import math

import numpy as np

from analysis.cam.paths import (  # noqa: F401
    CLEAR, _follow, d_at, design_profile, drill, mill_feed, plateau, setup_profile, simplify, spindle_rpm, turn_face, turn_finish,
    turn_groove, turn_rough, with_allowance, z_reach,
)


def shaft_profile(segments, chamfer=0.0, side="right"):
    """阶梯轴一次装夹的轮廓（只在右端倒角时与旧接口一致）：返回 (轮廓, 本次车到的长度, 总长)"""
    prof = design_profile(segments, chamfer)
    pts, Lreg = setup_profile(prof, side)
    return pts, Lreg, prof[-1][0]


def mill_slot(a, b, width, depth, tool_d, step_down, f, f_plunge, safe=5.0):
    """直槽 / 键槽（a、b 为两端圆心）：每层从 a 斜线下刀到 b，再回 a 把中线铣到底；
    槽宽大于刀径时，再沿槽边（刀心偏置）绕一圈"""
    from shapely.geometry import LineString
    if width < tool_d - 1e-9:
        raise ValueError("槽宽 {:g} 小于刀具直径 {:g}".format(width, tool_d))
    off = (width - tool_d) / 2
    ring = None
    if off > 1e-6:
        ring = list(LineString([tuple(a), tuple(b)]).buffer(off, quad_segs=16).exterior.coords)
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣槽 Slot：宽 {:g} 深 {:g}，刀具 Ø{:g}，分 {} 层".format(width, depth, tool_d, layers)},
          {"t": "rapid", "x": a[0], "y": a[1], "z": safe}, {"t": "rapid", "x": a[0], "y": a[1], "z": 0.5}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv.append({"t": "feed", "x": b[0], "y": b[1], "z": z1, "f": f_plunge})      # 斜线下刀
        mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
        if ring:
            mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in ring]
            mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
    mv.append({"t": "rapid", "x": a[0], "y": a[1], "z": safe})
    return mv


def _ring_coords(geom):
    from shapely.geometry import MultiPolygon, Polygon
    polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms) if isinstance(geom, MultiPolygon) else []
    out = []
    for p in polys:
        if p.is_empty:
            continue
        out.append(list(p.exterior.coords))
        out += [list(i.coords) for i in p.interiors]
    return out


def _ramp(ring, z_from, z_to, length, f):
    """沿环的前一段路一边走一边下刀（斜线下刀，刀具不垂直扎进材料）"""
    mv, acc = [], 0.0
    for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
        acc += math.hypot(xb - xa, yb - ya)
        t = min(acc / length, 1.0) if length > 1e-9 else 1.0
        mv.append({"t": "feed", "x": xb, "y": yb, "z": z_from + (z_to - z_from) * t, "f": f})
        if t >= 1.0:
            break
    return mv


def mill_pocket(polygon, depth, tool_d, stepover, step_down, f, f_plunge, safe=5.0):
    """型腔（可带岛）：每层从里往外按刀心偏置环一圈圈铣，最外一圈贴着型腔壁；
    每层在最里面一环斜线下刀；两环之间如果直线连过去会碰到岛或型腔壁，就抬刀再下"""
    from shapely.geometry import LineString, Polygon
    poly = polygon if isinstance(polygon, Polygon) else Polygon(polygon)
    room = poly.buffer(-tool_d / 2, join_style=1)
    if room.is_empty:
        raise ValueError("型腔太窄，Ø{:g} 的刀放不进去".format(tool_d))
    levels, g = [], room
    while not g.is_empty:
        levels.append(_ring_coords(g))
        g = g.buffer(-stepover * tool_d, join_style=1)
    rings = [r for lv in levels[::-1] for r in lv]                  # 从里往外
    ok = room.buffer(1e-3)
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣型腔 Pocket：深 {:g}，刀具 Ø{:g}，行距 {:g} 倍刀径，分 {} 层".format(depth, tool_d, stepover, layers)}]
    for k in range(layers):
        z0, z1 = -depth * k / layers, -depth * (k + 1) / layers
        first = rings[0]
        x0, y0 = first[0]
        mv += [{"t": "rapid", "x": x0, "y": y0, "z": safe}, {"t": "rapid", "x": x0, "y": y0, "z": z0 + 0.5}]
        mv += _ramp(first, z0 + 0.5, z1, max(3 * tool_d, 1.0), f_plunge)
        mv.append({"t": "feed", "x": x0, "y": y0, "z": z1, "f": f})
        for ring in rings:
            px, py = mv[-1]["x"], mv[-1]["y"]
            x, y = ring[0]
            if math.hypot(x - px, y - py) > 1e-9:
                if LineString([(px, py), (x, y)]).within(ok):
                    mv.append({"t": "feed", "x": x, "y": y, "z": z1, "f": f})
                else:
                    # 抬到工件上表面以上再平移（不能贴着上一层平移：中间可能有岛），快移落到上一层深度上方，再进给下刀
                    mv += [{"t": "rapid", "x": px, "y": py, "z": 1.0}, {"t": "rapid", "x": x, "y": y, "z": 1.0},
                           {"t": "rapid", "x": x, "y": y, "z": z0 + 0.5}, {"t": "feed", "x": x, "y": y, "z": z1, "f": f_plunge}]
            mv += [{"t": "feed", "x": xx, "y": yy, "z": z1, "f": f} for xx, yy in ring[1:]]
        mv.append({"t": "rapid", "x": mv[-1]["x"], "y": mv[-1]["y"], "z": safe})
    return mv


def mill_contour(polygon, depth, tool_d, step_down, f, safe=5.0):
    """外轮廓：刀心在轮廓外偏一个刀具半径，顺铣（主轴正转、沿顺时针绕工件），分层；
    从第一条边中点的外法线方向直线切入、切出"""
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    poly = polygon if isinstance(polygon, Polygon) else Polygon(polygon)
    path = orient(poly.buffer(tool_d / 2, join_style=1, quad_segs=16), sign=-1.0)       # 顺时针
    ring = list(path.exterior.coords)[:-1]
    # 从最长的一段中点开始
    i = max(range(len(ring)), key=lambda k: math.dist(ring[k], ring[(k + 1) % len(ring)]))
    pa, pb = ring[i], ring[(i + 1) % len(ring)]
    start = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    seq = [start] + ring[i + 1:] + ring[:i + 1] + [start]
    t = np.array(pb) - np.array(pa)
    t = t / max(np.linalg.norm(t), 1e-12)
    nrm = np.array([-t[1], t[0]])                 # 顺时针环：左侧是外面
    lead = np.array(start) + nrm * tool_d
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣外轮廓 Contour：深 {:g}，刀具 Ø{:g}，顺铣，分 {} 层".format(depth, tool_d, layers)}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv += [{"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": 0.5},
               {"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f / 2}]
        mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in seq]
        mv += [{"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}]
    return mv
