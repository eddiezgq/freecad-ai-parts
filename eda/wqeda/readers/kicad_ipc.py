# -*- coding: utf-8 -*-
"""入口三（第 113 轮 P6）：正在 KiCad 9 起的编辑器里打开的板子 → 板子模型。走 KiCad 的进程间接口（IPC API），
用官方 Python 库 kicad-python（kipy，MIT）。给 KiCad 插件用：设计师不用保存、不用导出，直接查编辑器里的板子。

和入口一（readers/kicad.py，KiCad 7 的 pcbnew 模块）出同样的板子模型；CI 里用 KiCad 9 打开驱动板 A，
两条入口的检查结论要一致。坐标：KiCad 内部纳米、y 向下 → 模型毫米、y 向上（和入口一相同）。"""

from __future__ import annotations

from .. import geom as G
from ..model import Board, BomRow, Component, Copper, Feature, Hole, Pad, Track

NM = 1e-6


def _layer_names():
    from kipy.proto.board.board_types_pb2 import BoardLayer as BL

    names = {BL.BL_F_Cu: "F", BL.BL_B_Cu: "B"}
    for i in range(1, 31):
        v = getattr(BL, "BL_In{}_Cu".format(i), None)
        if v is not None:
            names[v] = "In{}".format(i)
    return BL, names


def _xy(v):
    return v.x * NM, -v.y * NM


def _ring(line):
    pts = []
    for n in line.nodes:
        if n.has_point:
            pts.append(_xy(n.point))
        elif n.has_arc:  # 圆弧：起点、中点、终点（足够画出形状；焊盘、铺铜的圆弧 KiCad 一般已经拆成点）
            a = n.arc
            pts += [_xy(a.start), _xy(a.mid), _xy(a.end)]
    return pts


def _poly(p):
    """kipy 的 PolygonWithHoles → shapely"""
    from shapely.geometry import Polygon

    if p is None:
        return None
    shell = _ring(p.outline)
    if len(shell) < 3:
        return None
    g = Polygon(shell, [h for h in (_ring(x) for x in p.holes) if len(h) >= 3])
    return g if g.is_valid else g.buffer(0)


def _shape_geom(s):
    """器件外框、板框上的图形 → 线或多边形（shapely）"""
    from shapely.geometry import LineString, Polygon, box

    kind = type(s).__name__
    if kind == "BoardRectangle":
        (x0, y0), (x1, y1) = _xy(s.top_left), _xy(s.bottom_right)
        return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
    if kind == "BoardPolygon":
        gs = [_poly(p) for p in s.polygons]
        gs = [g for g in gs if g is not None]
        return gs[0] if len(gs) == 1 else (None if not gs else gs[0].union(gs[1]))
    if kind == "BoardCircle":
        cx, cy = _xy(s.center)
        rx, ry = _xy(s.radius_point)
        return G.circle(cx, cy, 2 * ((cx - rx) ** 2 + (cy - ry) ** 2) ** 0.5)
    if kind == "BoardArc":
        return LineString([_xy(s.start), _xy(s.mid), _xy(s.end)])
    if kind == "BoardSegment":
        return LineString([_xy(s.start), _xy(s.end)])
    return Polygon()


def _outline(lines):
    from shapely.ops import polygonize, unary_union

    polys = [g for g in lines if g is not None and g.geom_type == "Polygon" and not g.is_empty]
    segs = [g for g in lines if g is not None and g.geom_type == "LineString"]
    if segs:
        polys += list(polygonize(unary_union(segs)))
    return max(polys, key=lambda g: g.area) if polys else None


def read(board, copper_layers=None):
    """board = kipy 的 Board（kicad.get_board()）。→ 板子模型"""
    from kipy.proto.board.board_types_pb2 import PadType

    BL, names = _layer_names()
    tracks, vias, pads, fps, shapes, zones = (
        board.get_tracks(),
        board.get_vias(),
        board.get_pads(),
        board.get_footprints(),
        board.get_shapes(),
        board.get_zones(),
    )
    if copper_layers is None:
        copper_layers = board.get_copper_layer_count()
    cu = ["F"] + ["In{}".format(i) for i in range(1, copper_layers - 1)] + ["B"]

    edge = [_shape_geom(s) for s in shapes if s.layer == BL.BL_Edge_Cuts]
    outline_geom = _outline(edge)
    outline = tuple(round(v, 4) for v in outline_geom.bounds) if outline_geom is not None else None
    out = Board("kicad-ipc", outline, len(cu))
    out.outline_geom = outline_geom
    out.has_nets = True

    def box(g, layer):
        x0, y0, x1, y1 = g.bounds
        return Copper(layer, round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))

    for t in tracks:
        lay = names.get(t.layer)
        if lay is None:
            continue
        (x1, y1), (x2, y2) = _xy(t.start), _xy(t.end)
        w = round(t.width * NM, 4)
        g = G.segment(x1, y1, x2, y2, w)
        out.tracks.append(Track(lay, w, round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)))
        out.copper.append(box(g, lay))
        out.features.append(Feature(lay, g, "track", t.net.name, width=w))
    for v in vias:
        x, y = _xy(v.position)
        d, w = v.drill_diameter * NM, v.diameter * NM
        out.holes.append(Hole(round(x, 4), round(y, 4), round(d, 4), True, round((w - d) / 2, 4), "via"))
        g = G.circle(x, y, w)
        vid = "via@{:.3f},{:.3f}".format(x, y)
        for lay in ("F", "B"):
            out.copper.append(box(g, lay))
        for lay in cu:
            out.features.append(Feature(lay, g, "via", v.net.name, vid))

    ref_of, side_of = {}, {}
    for fp in fps:
        ref = fp.reference_field.text.value
        side = "B" if fp.layer == BL.BL_B_Cu else "F"
        side_of[ref] = side
        for p in fp.definition.pads:
            ref_of[p.id.value] = ref
        a = fp.attributes
        if not a.exclude_from_position_files and not a.exclude_from_bill_of_materials:
            x, y = _xy(fp.position)
            out.components.append(
                Component(ref, round(x, 4), round(y, 4), round(fp.orientation.degrees % 360, 3), side)
            )
        crt = BL.BL_B_CrtYd if side == "B" else BL.BL_F_CrtYd
        g = _outline([_shape_geom(s) for s in fp.definition.shapes if s.layer == crt])
        if g is not None:
            out.courtyards[ref] = (side, g)

    by_layer = {}
    for lay_id, lay in list(names.items()) + [(BL.BL_F_Mask, "F.Mask"), (BL.BL_B_Mask, "B.Mask")]:
        if lay not in cu and not lay.endswith("Mask"):
            continue
        if lay.endswith("Mask"):  # 阻焊开窗：焊盘在这一面的阻焊层上（贴片焊盘只在一面，通孔焊盘两面都有）
            on = [p for p in pads if lay_id in p.padstack.layers]
        else:
            on = [p for p in pads if lay_id in p.padstack.layers or p.pad_type == PadType.PT_PTH]
        if on:
            by_layer[lay] = (on, board.get_pad_shapes_as_polygons(on, lay_id))
    for lay, (on, polys) in by_layer.items():
        for p, poly in zip(on, polys, strict=False):
            g = _poly(poly)
            if g is None or p.pad_type == PadType.PT_NPTH:
                continue
            ref = ref_of.get(p.id.value, "")
            if lay.endswith("Mask"):
                out.features.append(Feature(lay, g, "opening", p.net.name, ref, p.number))
            else:
                kind = "pth" if p.pad_type == PadType.PT_PTH else "pad"
                out.features.append(Feature(lay, g, kind, p.net.name, ref, p.number))
    for p in pads:
        x, y = _xy(p.position)
        ref = ref_of.get(p.id.value, "")
        if p.pad_type in (PadType.PT_PTH, PadType.PT_NPTH):
            dv = p.padstack.drill.diameter
            d = min(dv.x, dv.y) * NM
            plated = p.pad_type == PadType.PT_PTH
            ring = None
            if plated:
                lay = p.padstack.copper_layer(BL.BL_F_Cu) or (p.padstack.copper_layers or [None])[0]
                size = lay.size if lay is not None else None
                ring = round((min(size.x, size.y) * NM - d) / 2, 4) if size is not None else None
                out.pads.append(Pad("FB", round(x, 4), round(y, 4)))
            out.holes.append(Hole(round(x, 4), round(y, 4), round(d, 4), plated, ring, "pad", ref))
        else:
            side = "B" if BL.BL_B_Cu in p.padstack.layers and BL.BL_F_Cu not in p.padstack.layers else "F"
            out.pads.append(Pad(side, round(x, 4), round(y, 4)))
    for f in out.features:
        if f.kind in ("pad", "pth") and f.layer in ("F", "B"):
            out.copper.append(box(f.geom, f.layer))

    for z in zones:
        if z.is_rule_area():
            continue
        for lay_id, polys in z.filled_polygons.items():
            lay = names.get(lay_id)
            if lay is None:
                continue
            for p in polys:
                g = _poly(p)
                if g is not None:
                    out.features.append(Feature(lay, g, "zone", z.net.name if z.net else "", "zone:" + z.id.value))
                    out.copper.append(box(g, lay))

    groups = {}
    for fp in fps:
        if fp.attributes.exclude_from_bill_of_materials:
            continue
        key = (fp.value_field.text.value, fp.definition.id.name)
        groups.setdefault(key, []).append(fp.reference_field.text.value)
    for (value, package), refs in sorted(groups.items()):
        out.bom.append(BomRow(tuple(sorted(refs)), len(refs), value, package))
    return out
