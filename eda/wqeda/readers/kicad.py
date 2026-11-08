# -*- coding: utf-8 -*-
"""入口一：KiCad 板子文件 → 板子模型。用 KiCad 自带的 pcbnew 模块（KiCad 7；只作工具调用，不改它）。"""

from __future__ import annotations

from .. import geom as G
from ..model import Board, BomRow, Component, Copper, Feature, Hole, Pad, Track

MAX_ERR_MM = 0.005  # 圆弧变多边形的误差


def _layer_name(board, lay):
    n = board.GetLayerName(lay)  # F.Cu、B.Cu、In1.Cu……
    return n[:-3] if n.endswith(".Cu") else n


def read(path, board=None):
    import pcbnew

    if board is None:
        board = pcbnew.LoadBoard(path)
    mm = pcbnew.ToMM

    def pt(p):
        return round(mm(p.x), 4), round(-mm(p.y), 4)

    def box(bb, layer):
        x0, y0, x1, y1 = mm(bb.GetLeft()), -mm(bb.GetBottom()), mm(bb.GetRight()), -mm(bb.GetTop())
        return Copper(layer, round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4))

    xs, ys = [], []
    for d in board.GetDrawings():
        if d.GetLayer() == pcbnew.Edge_Cuts:
            for p in (d.GetStart(), d.GetEnd()):
                x, y = pt(p)
                xs.append(x)
                ys.append(y)
    outline = (min(xs), min(ys), max(xs), max(ys)) if xs else None
    out = Board("kicad", outline, board.GetCopperLayerCount())

    for t in board.GetTracks():
        cls = t.GetClass()
        if cls in ("PCB_TRACK", "PCB_ARC"):
            (x1, y1), (x2, y2) = pt(t.GetStart()), pt(t.GetEnd())
            lay = _layer_name(board, t.GetLayer())
            out.tracks.append(Track(lay, round(mm(t.GetWidth()), 4), x1, y1, x2, y2))
            out.copper.append(box(t.GetBoundingBox(), lay))
        elif cls == "PCB_VIA":
            x, y = pt(t.GetPosition())
            d, w = mm(t.GetDrillValue()), mm(t.GetWidth())
            out.holes.append(Hole(x, y, round(d, 4), True, round((w - d) / 2, 4), "via"))
            for lay in ("F", "B"):
                out.copper.append(box(t.GetBoundingBox(), lay))

    for fp in board.GetFootprints():
        side = "B" if fp.GetLayer() == pcbnew.B_Cu else "F"
        attrs = fp.GetAttributes()
        for pad in fp.Pads():
            x, y = pt(pad.GetPosition())
            a = pad.GetAttribute()
            if a in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH):
                d = mm(min(pad.GetDrillSize().x, pad.GetDrillSize().y))
                plated = a == pcbnew.PAD_ATTRIB_PTH
                ring = round((mm(min(pad.GetSize().x, pad.GetSize().y)) - d) / 2, 4) if plated else None
                out.holes.append(Hole(x, y, round(d, 4), plated, ring, "pad", fp.GetReference()))
                if plated:
                    out.pads.append(Pad("FB", x, y))
                    for lay in ("F", "B"):
                        out.copper.append(box(pad.GetBoundingBox(), lay))
            elif a in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                pside = "B" if pad.IsOnLayer(pcbnew.B_Cu) else "F"
                out.pads.append(Pad(pside, x, y))
                out.copper.append(box(pad.GetBoundingBox(), pside))
        if not attrs & pcbnew.FP_EXCLUDE_FROM_POS_FILES and not attrs & pcbnew.FP_EXCLUDE_FROM_BOM:
            x, y = pt(fp.GetPosition())
            out.components.append(Component(fp.GetReference(), x, y, round(fp.GetOrientationDegrees(), 3), side))

    for z in board.Zones():
        for lay in z.GetLayerSet().Seq():
            if not pcbnew.IsCopperLayer(lay):
                continue
            polys = z.GetFilledPolysList(lay)
            if polys.OutlineCount():
                out.copper.append(box(polys.BBox(), _layer_name(board, lay)))

    _features(board, out)

    groups = {}
    for fp in board.GetFootprints():
        if fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        key = (fp.GetValue(), str(fp.GetFPID().GetLibItemName()))
        groups.setdefault(key, []).append(fp.GetReference())
    for (value, package), refs in sorted(groups.items()):
        out.bom.append(BomRow(tuple(sorted(refs)), len(refs), value, package))
    return out


def _shapely(ps):
    """KiCad 的 SHAPE_POLY_SET → shapely（y 取反）"""
    import pcbnew
    from shapely.geometry import MultiPolygon, Polygon

    mm = pcbnew.ToMM
    polys = []
    for i in range(ps.OutlineCount()):

        def ring(chain):
            return [(mm(chain.CPoint(k).x), -mm(chain.CPoint(k).y)) for k in range(chain.PointCount())]

        shell = ring(ps.Outline(i))
        holes = [ring(ps.Hole(i, h)) for h in range(ps.HoleCount(i))]
        if len(shell) >= 3:
            g = Polygon(shell, [h for h in holes if len(h) >= 3])
            polys.append(g if g.is_valid else g.buffer(0))
    if not polys:
        return None
    return polys[0] if len(polys) == 1 else MultiPolygon(polys).buffer(0)


def _features(board, out):
    """第 111 轮：铜（走线、过孔、焊盘、铺铜）和阻焊开窗的真实形状、网络；器件外框；板框多边形"""
    import pcbnew

    mm = pcbnew.ToMM
    err = pcbnew.FromMM(MAX_ERR_MM)
    out.has_nets = True
    cu = {lay: _layer_name(board, lay) for lay in board.GetEnabledLayers().CuStack()}
    for t in board.GetTracks():
        cls = t.GetClass()
        if cls == "PCB_TRACK":
            x1, y1, x2, y2 = mm(t.GetStart().x), -mm(t.GetStart().y), mm(t.GetEnd().x), -mm(t.GetEnd().y)
            out.features.append(
                Feature(
                    cu[t.GetLayer()],
                    G.segment(x1, y1, x2, y2, mm(t.GetWidth())),
                    "track",
                    t.GetNetname(),
                    width=round(mm(t.GetWidth()), 4),
                )
            )
        elif cls == "PCB_VIA":
            x, y = mm(t.GetPosition().x), -mm(t.GetPosition().y)
            g = G.circle(x, y, mm(t.GetWidth()))
            vid = "via@{:.3f},{:.3f}".format(x, y)
            for lay in cu.values():  # 通孔过孔：每层都有铜（KiCad 7 不去掉内层没连线的焊环）
                out.features.append(Feature(lay, g, "via", t.GetNetname(), vid))
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        for pad in fp.Pads():
            a = pad.GetAttribute()
            if a == pcbnew.PAD_ATTRIB_NPTH:
                continue
            kind = "pth" if a == pcbnew.PAD_ATTRIB_PTH else "pad"
            for lay, name in cu.items():
                if not pad.IsOnLayer(lay):
                    continue
                ps = pcbnew.SHAPE_POLY_SET()
                pad.TransformShapeToPolygon(ps, lay, 0, err)
                g = _shapely(ps)
                if g is not None:
                    out.features.append(Feature(name, g, kind, pad.GetNetname(), ref, pad.GetNumber()))
            for lay, name in ((pcbnew.F_Mask, "F.Mask"), (pcbnew.B_Mask, "B.Mask")):
                if pad.IsOnLayer(lay):
                    ps = pcbnew.SHAPE_POLY_SET()
                    pad.TransformShapeToPolygon(ps, lay, pad.GetSolderMaskExpansion(), err)
                    g = _shapely(ps)
                    if g is not None:
                        out.features.append(Feature(name, g, "opening", pad.GetNetname(), ref, pad.GetNumber()))
        side = "B" if fp.GetLayer() == pcbnew.B_Cu else "F"
        c = fp.GetCourtyard(pcbnew.B_CrtYd if side == "B" else pcbnew.F_CrtYd)
        if c.OutlineCount():
            g = _shapely(c)
            if g is not None:
                out.courtyards[ref] = (side, g)
    for z in board.Zones():
        for lay in z.GetLayerSet().Seq():
            if lay not in cu or not z.IsFilled():
                continue
            g = _shapely(z.GetFilledPolysList(lay))
            if g is not None:
                out.features.append(Feature(cu[lay], g, "zone", z.GetNetname(), "zone:" + z.m_Uuid.AsString()))
    ps = pcbnew.SHAPE_POLY_SET()
    if board.GetBoardPolygonOutlines(ps):
        out.outline_geom = _shapely(ps)
