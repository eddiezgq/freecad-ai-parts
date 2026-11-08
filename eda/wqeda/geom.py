# -*- coding: utf-8 -*-
"""几何小工具（第 111 轮 P4）：把走线、焊盘、铺铜、光绘图元变成平面多边形（shapely），检查里量间距、看连通用。
纯计算：不联网、不调 AI、不读数据库。单位 mm。"""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

RES = 8  # 圆弧近似：每四分之一圆的段数（与 0.005 mm 量级的误差相比足够）


def segment(x1, y1, x2, y2, width):
    """圆头走线 → 多边形"""
    r = width / 2
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        return Point(x1, y1).buffer(r, RES)
    return LineString([(x1, y1), (x2, y2)]).buffer(r, RES)


def circle(x, y, d):
    return Point(x, y).buffer(d / 2, RES)


def rect(x, y, w, h, rot_rad=0.0):
    """中心 (x, y)、宽 w、高 h、逆时针转 rot（弧度）"""
    hw, hh = w / 2, h / 2
    c, s = math.cos(rot_rad), math.sin(rot_rad)
    pts = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    return Polygon([(x + c * px - s * py, y + s * px + c * py) for px, py in pts])


def arc(x1, y1, x2, y2, cx, cy, clockwise, width):
    """圆弧走线：按段近似"""
    r = math.hypot(x1 - cx, y1 - cy)
    a1, a2 = math.atan2(y1 - cy, x1 - cx), math.atan2(y2 - cy, x2 - cx)
    if clockwise:
        while a2 > a1:
            a2 -= 2 * math.pi
    else:
        while a2 < a1:
            a2 += 2 * math.pi
    n = max(2, int(abs(a2 - a1) / (math.pi / 2) * RES) + 1)
    pts = [(cx + r * math.cos(a1 + (a2 - a1) * i / n), cy + r * math.sin(a1 + (a2 - a1) * i / n)) for i in range(n + 1)]
    return LineString(pts).buffer(width / 2, RES)


def islands(geoms):
    """一组多边形合并后的连通块（不同的块之间有空隙）"""
    u = unary_union([g for g in geoms if g is not None and not g.is_empty])
    if u.is_empty:
        return []
    return list(u.geoms) if hasattr(u, "geoms") else [u]


def close_pairs(polys, limit):
    """polys 里两两之间距离小于 limit 的对：[(距离, i, j)]，按距离从小到大。距离 0（碰上）不算——碰上就是同一块"""
    if len(polys) < 2:
        return []
    tree = STRtree(polys)
    out = []
    for i, g in enumerate(polys):
        for j in tree.query(g.buffer(limit, 2)):
            j = int(j)
            if j <= i:
                continue
            d = g.distance(polys[j])
            if 0 < d < limit:
                out.append((d, i, j))
    out.sort()
    return out


def connected(groups):
    """groups：[(键, 几何)]。几何相交的键并成一组；返回 {键: 组号}"""
    keys = [k for k, _ in groups]
    geoms = [g for _, g in groups]
    parent = list(range(len(keys)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    if geoms:
        tree = STRtree(geoms)
        for i, g in enumerate(geoms):
            for j in tree.query(g):
                j = int(j)
                if j > i and g.intersects(geoms[j]):
                    parent[find(i)] = find(j)
    return {k: find(i) for i, k in enumerate(keys)}


def bbox(g):
    return box(*g.bounds)
