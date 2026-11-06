# -*- coding: utf-8 -*-
"""入口一：KiCad 板子文件 → 板子模型。用 KiCad 自带的 pcbnew 模块（KiCad 7；只作工具调用，不改它）。"""

from __future__ import annotations

from ..model import Board, BomRow, Component, Copper, Hole, Pad, Track


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

    groups = {}
    for fp in board.GetFootprints():
        if fp.GetAttributes() & pcbnew.FP_EXCLUDE_FROM_BOM:
            continue
        key = (fp.GetValue(), str(fp.GetFPID().GetLibItemName()))
        groups.setdefault(key, []).append(fp.GetReference())
    for (value, package), refs in sorted(groups.items()):
        out.bom.append(BomRow(tuple(sorted(refs)), len(refs), value, package))
    return out
