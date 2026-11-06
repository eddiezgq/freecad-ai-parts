# -*- coding: utf-8 -*-
"""入口二：光绘文件（Gerber RS-274X / X2，Excellon 钻孔）+ 物料清单 + 坐标文件 → 板子模型。
工厂收到的客户资料包是这三样；不需要原设计软件。读光绘用 gerbonara（Apache-2.0）。

物料清单和坐标的列名各家不一样，用“列映射”对一次；默认映射是 KiCad 导出和问渠物料清单的列名。"""
from __future__ import annotations

import csv
import re
import warnings

from ..model import Board, BomRow, Component, Copper, Hole, Pad, Track

BOM_MAP = {"refs": "位号", "qty": "数量", "value": "数值", "package": "封装", "item": "物料编号"}
CPL_MAP = {"ref": "Ref", "x": "PosX", "y": "PosY", "rot": "Rot", "side": "Side"}
SIDES = {"top": "F", "bottom": "B", "t": "F", "b": "B", "f": "F", "front": "F", "back": "B"}
SAME = 0.005            # 钻孔与焊盘“同一位置”的容差 mm


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


def read_gerbers(path):
    """path：光绘文件所在的文件夹或 zip"""
    from gerbonara import LayerStack
    from gerbonara.apertures import CircleAperture
    from gerbonara.graphic_objects import Arc, Flash, Line

    with warnings.catch_warnings():          # 钻孔文件“表头之后又出现 G90”之类的格式提示，不影响读数
        warnings.simplefilter("ignore", SyntaxWarning)
        stack = LayerStack.open(path)
    xs, ys = [], []
    for o in stack.outline.objects if stack.outline else []:
        if isinstance(o, (Line, Arc)):
            xs += [o.x1, o.x2]
            ys += [o.y1, o.y2]
    outline = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    names = _layer_names(stack)
    out = Board("gerber", outline, len(names))
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
    return out


def _rows(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_bom(path, mapping=None):
    m = dict(BOM_MAP, **(mapping or {}))
    out = []
    for r in _rows(path):
        refs = tuple(x for x in re.split(r"[\s,;]+", r.get(m["refs"], "") or "") if x)
        q = (r.get(m["qty"]) or "").strip()
        out.append(BomRow(refs, int(q) if q.isdigit() else None, r.get(m["value"], "") or "",
                          r.get(m["package"], "") or "", r.get(m["item"], "") or ""))
    return out


def read_cpl(path, mapping=None, sides=None):
    m = dict(CPL_MAP, **(mapping or {}))
    sd = dict(SIDES, **(sides or {}))
    out = []
    for r in _rows(path):
        side = sd.get((r.get(m["side"]) or "").strip().lower(), "")
        out.append(Component(r[m["ref"]].strip(), float(r[m["x"]]), float(r[m["y"]]),
                             float(r.get(m["rot"]) or 0), side))
    return out


def read(gerbers, bom=None, cpl=None, bom_map=None, cpl_map=None, sides=None):
    out = read_gerbers(gerbers)
    if bom:
        out.bom = read_bom(bom, bom_map)
    else:
        out.notes.append("没有物料清单")
    if cpl:
        out.components = read_cpl(cpl, cpl_map, sides)
    else:
        out.notes.append("没有坐标文件")
    return out
