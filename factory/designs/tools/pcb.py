# -*- coding: utf-8 -*-
"""由设计描述生成 KiCad 7 的 PCB：摆放（按功能区写好的坐标）→ 网络 → 导出 Specctra DSN（加大电流网络的线宽规则）→
Freerouting 自动布线 → 读回布线结果（SES）→ 地平面、铺铜 → 保存。要 KiCad 7 的 pcbnew Python 模块和 Java。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import pcbnew

FPDIR = os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
MM = pcbnew.FromMM
ORIGIN = (100.0, 100.0)          # 板子左上角在 KiCad 坐标里的位置 mm


def P(x, y):
    return pcbnew.VECTOR2I(MM(ORIGIN[0] + x), MM(ORIGIN[1] + y))


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    fp = pcbnew.FootprintLoad(os.path.join(FPDIR, lib + ".pretty"), name)
    if fp is None:
        raise KeyError(fpid)
    return fp


def outline(board, w, h, r=2.0):
    """板框：圆角矩形（Edge.Cuts）"""
    def seg(a, b):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(P(*a))
        s.SetEnd(P(*b))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)

    def arc(c, start, mid, end):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetArcGeometry(P(*start), P(*mid), P(*end))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)
    k = r * (1 - 0.70710678)
    seg((r, 0), (w - r, 0))
    seg((w, r), (w, h - r))
    seg((w - r, h), (r, h))
    seg((0, h - r), (0, r))
    arc(None, (w - r, 0), (w - k, k), (w, r))
    arc(None, (w, h - r), (w - k, h - k), (w - r, h))
    arc(None, (r, h), (k, h - k), (0, h - r))
    arc(None, (0, r), (k, k), (r, 0))


def build(design, placement, path, holes=(), hole_net="GND"):
    """摆好器件、接好网络的板子（未布线）"""
    board = pcbnew.NewBoard(path)
    board.SetCopperLayerCount(design.LAYERS)
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(design.LAYERS)
    ds.m_TrackMinWidth = MM(0.127)
    ds.m_MinClearance = MM(0.127)
    ds.m_ViasMinSize = MM(0.5)
    ds.m_MinThroughDrill = MM(0.3)
    ds.m_HoleToHoleMin = MM(0.25)
    ds.m_CopperEdgeClearance = MM(0.3)
    nc = ds.m_NetSettings.m_DefaultNetClass
    nc.SetTrackWidth(MM(0.25))
    nc.SetClearance(MM(0.15))
    nc.SetViaDiameter(MM(0.6))
    nc.SetViaDrill(MM(0.3))
    tb = board.GetTitleBlock()
    tb.SetTitle("关节伺服驱动板 DRV-JOINT（示例设计，未经硬件验证）")
    tb.SetCompany("问渠数字工业园 · 电路板厂")
    tb.SetRevision("示例 A")
    tb.SetDate("2026-11-05")
    w, h = design.BOARD_MM
    outline(board, w, h)
    nets = {}
    for n in sorted(design.nets()):
        if n in design.NC_NETS:
            continue
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni
    for p in design.PARTS:
        fp = load_fp(p["fp"])
        fp.SetReference(p["ref"])
        fp.SetValue(p["value"])
        x, y, rot, side = placement[p["ref"]]
        board.Add(fp)
        fp.SetPosition(P(x, y))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(fp.GetPosition(), False)
        if not p["item"]:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
        for pad in fp.Pads():
            num = pad.GetNumber()
            net = p["pins"].get(num)
            if net and net in nets:
                pad.SetNet(nets[net])
    for i, (x, y) in enumerate(holes):
        fp = load_fp("MountingHole:MountingHole_3.2mm_M3_Pad")
        fp.SetReference("H{}".format(i + 1))
        fp.SetValue("M3")
        board.Add(fp)
        fp.SetPosition(P(x, y))
        for pad in fp.Pads():
            if hole_net in nets:
                pad.SetNet(nets[hole_net])
        fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
    return board, nets


def add_zone(board, net, layer, w, h, inset=0.5, prio=0, clearance=0.3, min_w=0.25):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    if net is not None:
        z.SetNet(net)
    z.SetAssignedPriority(prio)
    z.SetLocalClearance(MM(clearance))
    z.SetMinThickness(MM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(MM(0.3))
    z.SetThermalReliefSpokeWidth(MM(0.5))
    ol = z.Outline()
    ol.NewOutline()
    for x, y in ((inset, inset), (w - inset, inset), (w - inset, h - inset), (inset, h - inset)):
        ol.Append(MM(ORIGIN[0] + x), MM(ORIGIN[1] + y))
    board.Add(z)
    return z


def _dsn_rules(dsn_text, classes):
    """改 DSN 的线宽 / 间距类别：classes = {类名: (线宽 mm, 间距 mm, [网络])}；这些网络从缺省类别里拿出来"""
    i = dsn_text.index("(class kicad_default")
    j = dsn_text.index("(circuit", i)
    head = dsn_text[i:j]
    names = re.findall(r'"[^"]*"|[^\s()]+', head[len("(class kicad_default"):])
    moved = {n for spec in classes.values() for n in spec[2]}
    keep = [n for n in names if n.strip('"') not in moved]
    new_head = "(class kicad_default " + " ".join(keep) + "\n      "
    add = ""
    for name, spec in classes.items():
        w, c, nets = spec[:3]
        lay = " (use_layer {})".format(" ".join(spec[3])) if len(spec) > 3 else ""
        if nets:
            add += "    (class {} {}\n      (circuit (use_via Via[0-3]_600:300_um){})\n      (rule (width {:.0f}) (clearance {:.0f}))\n    )\n".format(
                name, " ".join('"{}"'.format(n) for n in nets), lay, w * 1000, c * 1000)
    out = dsn_text[:i] + new_head + dsn_text[j:]
    k = out.index("(class kicad_default")
    return out[:k] + add.lstrip() + "    " + out[k:]


def _keepouts(txt, keepouts, inset=0.45):
    """铺铜区域（向里缩一点）在 DSN 里设为禁布区：别的网络不从铺铜里穿（Freerouting 不把信号层上的铺铜当障碍）；
    铺铜自己的网络在边上一圈还能接进来"""
    from shapely.geometry import Polygon
    add = ""
    for k in keepouts:
        layer, pts = k[0], k[1]
        pg = Polygon(pts).buffer(-(k[2] if len(k) > 2 else inset), join_style=2)
        if pg.is_empty:
            continue
        geoms = list(pg.geoms) if hasattr(pg, "geoms") else [pg]
        for g in geoms:
            coords = list(g.exterior.coords)[:-1]
            add += "    (keepout \"\" (polygon {} 0 {}))\n".format(layer, " ".join(
                "{:.0f} {:.0f}".format((ORIGIN[0] + x) * 1000, -(ORIGIN[1] + y) * 1000) for x, y in coords))
    i = txt.index("    (plane ")             # 结构段里层定义之后、铺铜平面之前
    return txt[:i] + add + txt[i:]


def autoroute(board, workdir, jar, classes, passes=40, timeout=1800, plane_layers=("In1.Cu",), keepouts=()):
    """导出 DSN（去掉电源平面网络）→ Freerouting → 读回 SES"""
    dsn = os.path.join(workdir, "route.dsn")
    ses = os.path.join(workdir, "route.ses")
    pcbnew.ExportSpecctraDSN(board, dsn)
    with open(dsn, encoding="utf-8") as f:
        txt = f.read()
    txt = _dsn_rules(txt, classes)
    if keepouts:
        txt = _keepouts(txt, keepouts)
    if plane_layers:                  # 平面层只给地平面：缺省类别的信号线不走平面层
        sig = [ln for ln in re.findall(r"\(layer (\S+)\s*\n\s*\(type signal\)", txt) if ln not in plane_layers]
        i = txt.index("(class kicad_default")
        j = txt.index("(use_via", i)
        k = txt.index(")", j)
        txt = txt[:k + 1] + " (use_layer {})".format(" ".join(sig)) + txt[k + 1:]
    with open(dsn, "w", encoding="utf-8") as f:
        f.write(txt)
    if os.path.exists(ses):
        os.remove(ses)
    cmd = ["java", "-jar", jar, "-de", dsn, "-do", ses, "-mp", str(passes), "-mt", "0", "-dct", "0"]
    if os.environ.get("DISPLAY") is None and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a"] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=workdir)
    if not os.path.exists(ses):
        raise RuntimeError("Freerouting 没有产出：" + (r.stdout[-2000:] + r.stderr[-2000:]))
    return import_ses(board, ses)


def import_ses(board, ses):
    """读 Specctra SES 的布线结果加到板子上（KiCad 7 的 ImportSpecctraSES 只能在图形界面里用）"""
    with open(ses, encoding="utf-8") as f:
        txt = f.read()
    res = re.search(r"\(resolution\s+(\w+)\s+(\d+)\)", txt)
    unit, div = res.group(1), float(res.group(2))
    scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4}[unit] / div
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu}
    netmap = {board.GetNetInfo().GetNetItem(i).GetNetname(): board.GetNetInfo().GetNetItem(i) for i in range(board.GetNetCount())}
    ntr = nvia = 0

    def pt(x, y):
        return pcbnew.VECTOR2I(int(round(float(x) * scale * 1e6)), int(round(-float(y) * scale * 1e6)))
    body = txt[txt.find("(network_out"):]
    for blk in _net_blocks(body):
        name, content = blk
        net = netmap.get(name)
        if net is None:
            continue
        for w in re.finditer(r"\(path\s+(\S+)\s+([\d.]+)\s+([-\d.\s]+)\)", content):
            layer = layers.get(w.group(1).strip('"'))
            width = float(w.group(2)) * scale
            nums = w.group(3).split()
            pts = [pt(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            for a, b in zip(pts, pts[1:]):
                t = pcbnew.PCB_TRACK(board)
                t.SetStart(a)
                t.SetEnd(b)
                t.SetWidth(MM(width))
                t.SetLayer(layer)
                t.SetNet(net)
                board.Add(t)
                ntr += 1
        for v in re.finditer(r'\(via\s+"?([^"\s]+)"?\s+([-\d.]+)\s+([-\d.]+)', content):
            m = re.search(r"(\d+):(\d+)_um", v.group(1))
            dia, drill = (int(m.group(1)) / 1000, int(m.group(2)) / 1000) if m else (0.6, 0.3)
            via = pcbnew.PCB_VIA(board)
            via.SetPosition(pt(v.group(2), v.group(3)))
            via.SetWidth(MM(dia))
            via.SetDrill(MM(drill))
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            via.SetNet(net)
            board.Add(via)
            nvia += 1
    return ntr, nvia


def _net_blocks(text):
    """(net 名字 ...) 块：按括号配对切出来"""
    out = []
    i = 0
    while True:
        i = text.find("(net ", i)
        if i < 0:
            return out
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        blk = text[i:j + 1]
        m = re.match(r'\(net\s+(?:"([^"]*)"|(\S+))', blk)
        out.append((m.group(1) if m.group(1) is not None else m.group(2), blk))
        i = j + 1


def add_pour(board, net, layer_name, pts, clearance=0.3, min_w=0.3):
    """功率铺铜：多边形，焊盘整块连上（不做散热焊盘），优先级高于地平面"""
    z = pcbnew.ZONE(board)
    z.SetLayer(board.GetLayerID(layer_name))
    z.SetNet(net)
    z.SetAssignedPriority(2)
    z.SetLocalClearance(MM(clearance))
    z.SetMinThickness(MM(min_w))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(MM(ORIGIN[0] + x), MM(ORIGIN[1] + y))
    board.Add(z)
    return z


def fill_zones(board):
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
