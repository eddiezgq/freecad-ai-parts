# -*- coding: utf-8 -*-
"""入口二：光绘文件（Gerber RS-274X / X2，Excellon 钻孔）+ 物料清单 + 坐标文件 → 板子模型。
工厂收到的客户资料包是这三样；不需要原设计软件。读光绘用 gerbonara（Apache-2.0）。

物料清单和坐标的列名各家不一样，用“列映射”对一次；默认映射是 KiCad 导出和问渠物料清单的列名。"""

from __future__ import annotations

import csv
import os
import re
import warnings

from .. import geom as G
from ..model import Board, BomRow, Component, Copper, Feature, Hole, Pad, Track

BOM_MAP = {"refs": "位号", "qty": "数量", "value": "数值", "package": "封装", "item": "物料编号"}
CPL_MAP = {"ref": "Ref", "x": "PosX", "y": "PosY", "rot": "Rot", "side": "Side"}
SIDES = {"top": "F", "bottom": "B", "t": "F", "b": "B", "f": "F", "front": "F", "back": "B"}
SAME = 0.005  # 钻孔与焊盘“同一位置”的容差 mm
# 第 112 轮：各家物料清单、坐标的列名不一样，先按这些常见写法猜一次（不分大小写、去掉空格和标点），人可以改
SYNONYMS = {
    "bom": {
        "refs": ["位号", "designator", "designators", "reference", "references", "ref", "refdes", "partreference"],
        "qty": ["数量", "qty", "quantity", "count"],
        "value": ["数值", "value", "val", "comment"],
        "package": ["封装", "footprint", "package", "pcbfootprint"],
        "item": ["物料编号", "料号", "partnumber", "mpn", "item", "pn", "manufacturerpartnumber", "internalpn"],
    },
    "cpl": {
        "ref": ["ref", "designator", "位号", "refdes", "reference"],
        "x": ["posx", "midx", "centerx", "centerxmm", "x", "refx", "locationx", "x坐标"],
        "y": ["posy", "midy", "centery", "centerymm", "y", "refy", "locationy", "y坐标"],
        "rot": ["rot", "rotation", "angle", "角度", "旋转"],
        "side": ["side", "layer", "面", "tb", "topbottom"],
    },
}
LAYER_NAMES = [
    "top copper",
    "top mask",
    "top silk",
    "top paste",
    "bottom copper",
    "bottom mask",
    "bottom silk",
    "bottom paste",
    "inner_01 copper",
    "inner_02 copper",
    "inner_03 copper",
    "inner_04 copper",
    "mechanical outline",
    "drill pth",
    "drill npth",
    "ignore",
]


def _layer_names(stack):
    """光绘层 → 铜层名（F、In1、In2……、B）。内层按文件编号排序后依次编号。"""
    names = {}
    inner = sorted(k for k in stack.graphic_layers if k[1] == "copper" and k[0].startswith("inner"))
    for i, k in enumerate(inner):
        names[k] = "In{}".format(i + 1)
    for k in stack.graphic_layers:
        if k == ("top", "copper"):
            names[k] = "F"
        elif k == ("bottom", "copper"):
            names[k] = "B"
    return names


def _bbox(o):
    (x0, y0), (x1, y1) = o.bounding_box()
    return x0, y0, x1, y1


def read_gerbers(path, layers=None):
    """path：光绘文件所在的文件夹或 zip。layers = {文件名: 层名（LAYER_NAMES 之一）}：自动认不出时由人指定"""
    from gerbonara import LayerStack
    from gerbonara.apertures import CircleAperture
    from gerbonara.graphic_objects import Arc, Flash, Line

    with warnings.catch_warnings():  # 钻孔文件“表头之后又出现 G90”之类的格式提示，不影响读数
        warnings.simplefilter("ignore", SyntaxWarning)
        if layers:
            import re as _re

            over = {_re.escape(os.path.basename(fn)): lay for fn, lay in layers.items()}
            stack = LayerStack.open(path, overrides=over, autoguess=False)
        else:
            stack = LayerStack.open(path)
    xs, ys = [], []
    for o in stack.outline.objects if stack.outline else []:
        if isinstance(o, (Line, Arc)):
            xs += [o.x1, o.x2]
            ys += [o.y1, o.y2]
    outline = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    names = _layer_names(stack)
    out = Board("gerber", outline, len(names))
    out.stack = stack  # 第 112 轮：工厂端出板图、报告每个文件认成了哪一层（不是数据字段）
    flashes = {"F": [], "B": []}
    for key, lay in names.items():
        for o in stack.graphic_layers[key].objects:
            x0, y0, x1, y1 = _bbox(o)
            out.copper.append(Copper(lay, round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)))
            if isinstance(o, (Line, Arc)) and isinstance(o.aperture, CircleAperture):
                out.tracks.append(Track(lay, round(o.aperture.diameter, 4), o.x1, o.y1, o.x2, o.y2))
            elif isinstance(o, Flash) and lay in flashes:
                flashes[lay].append((o.x, o.y, min(x1 - x0, y1 - y0)))
                out.pads.append(Pad(lay, o.x, o.y))

    def pad_at(x, y):
        for lay in ("F", "B"):
            for fx, fy, size in flashes[lay]:
                if abs(fx - x) < SAME and abs(fy - y) < SAME:
                    return size
        return None

    for layer, plated in ((stack.drill_pth, True), (stack.drill_npth, False)):
        for o in layer.objects if layer else []:
            d = o.aperture.diameter
            x, y = (o.x, o.y) if isinstance(o, Flash) else (o.x1, o.y1)
            size = pad_at(x, y) if plated else None
            ring = round((size - d) / 2, 4) if size is not None else None
            out.holes.append(Hole(x, y, round(d, 4), plated, ring))
    if not out.holes and not (stack.drill_pth or stack.drill_npth):
        out.notes.append("没有钻孔文件")
    _features(stack, names, out)
    return out


def _prim(p):
    """gerbonara 图元 → shapely；不认识的返回 None"""
    from gerbonara import graphic_primitives as gp
    from shapely.geometry import Polygon

    if isinstance(p, gp.Circle):
        return G.circle(p.x, p.y, 2 * p.r)
    if isinstance(p, gp.Rectangle):
        return G.rect(p.x, p.y, p.w, p.h, p.rotation)
    if isinstance(p, gp.Line):
        return G.segment(p.x1, p.y1, p.x2, p.y2, p.width)
    if isinstance(p, gp.Arc):
        return G.arc(p.x1, p.y1, p.x2, p.y2, p.cx, p.cy, p.clockwise, p.width)
    if isinstance(p, gp.ArcPoly):
        pts = list(p.outline)
        return Polygon(pts).buffer(0) if len(pts) >= 3 else None
    return None


def _shape(o):
    """一个光绘对象（走线、焊盘、铺铜区）的形状：亮图元并起来，减去暗图元"""
    from shapely.ops import unary_union

    dark, clear = [], []
    for p in o.to_primitives(unit="mm"):
        g = _prim(p)
        if g is not None and not g.is_empty:
            (dark if p.polarity_dark else clear).append(g)
    if not dark:
        return None
    g = unary_union(dark)
    return g.difference(unary_union(clear)) if clear else g


def _features(stack, names, out):
    """第 111 轮：铜和阻焊开窗的形状（光绘里没有网络，net 留空）；板框多边形"""
    from gerbonara.graphic_objects import Arc, Flash, Line
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    kinds = {Flash: "pad", Line: "track", Arc: "track"}
    for key, lay in names.items():
        for o in stack.graphic_layers[key].objects:
            g = _shape(o)
            if g is not None:
                w = (
                    round(o.aperture.diameter, 4)
                    if kinds.get(type(o)) == "track" and hasattr(o.aperture, "diameter")
                    else 0.0
                )
                out.features.append(Feature(lay, g, kinds.get(type(o), "zone"), width=w))
    for side, name in (("top", "F.Mask"), ("bottom", "B.Mask")):
        layer = stack.graphic_layers.get((side, "mask"))
        for o in layer.objects if layer else []:
            g = _shape(o)
            if g is not None:
                out.features.append(Feature(name, g, "opening"))
    if stack.outline:
        lines = []
        for o in stack.outline.objects:
            if isinstance(o, Line):
                lines.append(LineString([(o.x1, o.y1), (o.x2, o.y2)]))
            elif isinstance(o, Arc):
                lines.append(_arc_line(o))
        polys = list(polygonize(unary_union(lines)))
        if polys:
            out.outline_geom = max(polys, key=lambda g: g.area)


def _arc_line(o):
    import math

    from shapely.geometry import LineString

    cx, cy = o.center  # 光绘里圆心是相对起点的偏移，center 是绝对坐标
    r = math.hypot(o.x1 - cx, o.y1 - cy)
    a1, a2 = math.atan2(o.y1 - cy, o.x1 - cx), math.atan2(o.y2 - cy, o.x2 - cx)
    if o.clockwise:
        while a2 > a1:
            a2 -= 2 * math.pi
    else:
        while a2 < a1:
            a2 += 2 * math.pi
    n = 16
    return LineString(
        [(cx + r * math.cos(a1 + (a2 - a1) * i / n), cy + r * math.sin(a1 + (a2 - a1) * i / n)) for i in range(n + 1)]
    )


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _norm(h):
    return re.sub(r"[\s_\-\.:()（）\[\]/]+", "", (h or "").strip().lower())


def guess_map(headers, kind):
    """按常见列名猜列映射 → (映射, 没猜到的键)"""
    norm = {_norm(h): h for h in headers}
    out, miss = {}, []
    for key, names in SYNONYMS[kind].items():
        hit = next((norm[n] for n in names if n in norm), None)
        if hit is None:
            miss.append(key)
        else:
            out[key] = hit
    return out, miss


def headers(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f), [])


def _num(v):
    """坐标、角度：去掉单位（mm、°）再转数"""
    return float(re.sub(r"[^0-9eE+\-.]", "", str(v)) or "nan")


def read_bom(path, mapping=None):
    m = dict(BOM_MAP, **(mapping or {})) if mapping else _auto(path, "bom", BOM_MAP)
    out = []
    for r in _rows(path):
        refs = tuple(x for x in re.split(r"[\s,;]+", r.get(m["refs"], "") or "") if x)
        if not refs:
            continue
        q = (r.get(m.get("qty", ""), "") or "").strip()
        out.append(
            BomRow(
                refs,
                int(float(q)) if re.fullmatch(r"\d+(\.0+)?", q) else None,
                r.get(m.get("value", ""), "") or "",
                r.get(m.get("package", ""), "") or "",
                r.get(m.get("item", ""), "") or "",
            )
        )
    return out


def read_cpl(path, mapping=None, sides=None):
    m = dict(CPL_MAP, **(mapping or {})) if mapping else _auto(path, "cpl", CPL_MAP)
    sd = dict(SIDES, **(sides or {}))
    out = []
    for r in _rows(path):
        if not (r.get(m["ref"]) or "").strip():
            continue
        side = sd.get((r.get(m.get("side", "")) or "").strip().lower(), "")
        out.append(
            Component(r[m["ref"]].strip(), _num(r[m["x"]]), _num(r[m["y"]]), _num(r.get(m.get("rot", "")) or 0), side)
        )
    return out


def _auto(path, kind, default):
    """没给映射：先看是不是缺省列名，不是就猜"""
    hs = headers(path)
    if all(v in hs for k, v in default.items() if k not in ("qty", "value", "package", "item", "rot")):
        return dict(default)
    m, _ = guess_map(hs, kind)
    return m


def read(gerbers, bom=None, cpl=None, bom_map=None, cpl_map=None, sides=None, layers=None):
    out = read_gerbers(gerbers, layers)
    if bom:
        out.bom = read_bom(bom, bom_map)
    else:
        out.notes.append("没有物料清单")
    if cpl:
        out.components = read_cpl(cpl, cpl_map, sides)
    else:
        out.notes.append("没有坐标文件")
    return out


def layer_map(stack):
    """每个文件认成了哪一层：{文件名: 层名}"""
    out = {}
    for (side, use), layer in stack.graphic_layers.items():
        name = (
            "inner_{:02d} copper".format(int(side.split("_")[1]))
            if side.startswith("inner")
            else "{} {}".format(side, use)
        )
        if getattr(layer, "original_path", None):
            out[os.path.basename(str(layer.original_path))] = name
    for layer, name in ((stack.drill_pth, "drill pth"), (stack.drill_npth, "drill npth")):
        if layer is not None and getattr(layer, "original_path", None):
            out[os.path.basename(str(layer.original_path))] = name
    return dict(sorted(out.items()))
