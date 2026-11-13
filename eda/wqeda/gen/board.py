# -*- coding: utf-8 -*-
"""板子生成（第 111 轮 P4，由 factory/designs/tools/pcb.py 迁来并做成通用的）：设计描述的 L4 → KiCad 7 板子。

    摆放（L4 placement）→ 网络 → 地平面、功率铺铜 → 导出 Specctra DSN（加网络分类的线宽、禁布区）→
    Freerouting 自动布线 → 读回布线结果（SES）→ 填充铺铜 → 保存

输入是 wqeda.schema.design.expand() 的结果（平铺的器件、摆放、网络分类、铺铜）。要 KiCad 7 的 pcbnew Python 模块；
自动布线还要 Java 和 Freerouting 的 jar。Freerouting 是 GPL 工具，只作为外部程序调用。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess

import pcbnew

FPDIR = os.environ.get("KICAD7_FOOTPRINT_DIR", "/usr/share/kicad/footprints")
MM = pcbnew.FromMM
ORIGIN = (100.0, 100.0)  # 板子左上角在 KiCad 坐标里的位置 mm
HOLE_FP = "MountingHole:MountingHole_3.2mm_M3_Pad"


def P(x, y):
    return pcbnew.VECTOR2I(MM(ORIGIN[0] + x), MM(ORIGIN[1] + y))


# 工程自带封装库：库名 → 目录（第 159 轮：平缝机控制器的 wq.pretty；调用方按需登记，不登记就只用 KiCad 官方库）
LOCAL_FPDIRS = {}


def load_fp(fpid):
    lib, name = fpid.split(":", 1)
    fp = pcbnew.FootprintLoad(os.path.join(LOCAL_FPDIRS.get(lib, FPDIR), lib + ".pretty"), name)
    if fp is None:
        raise KeyError(fpid)
    return fp


def nets_of(parts):
    out = {}
    for p in parts:
        for pin, n in p["pins"].items():
            out.setdefault(n, []).append((p["ref"], pin))
    return out


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

    def arc(start, mid, end):
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
    arc((w - r, 0), (w - k, k), (w, r))
    arc((w, h - r), (w - k, h - k), (w - r, h))
    arc((r, h), (k, h - k), (0, h - r))
    arc((0, r), (k, k), (r, 0))


def build(x, path, title=None, hole_net="GND"):
    """摆好器件、接好网络的板子（未布线）。x = expand() 的结果；title = {title, company, rev, date}（可省）"""
    board = pcbnew.NewBoard(path)
    board.SetCopperLayerCount(x["layers"])
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(x["layers"])
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
    if title:
        tb = board.GetTitleBlock()
        tb.SetTitle(title["title"])
        tb.SetCompany(title["company"])
        tb.SetRevision(title["rev"])
        tb.SetDate(title["date"])
    w, h = x["board_mm"]
    outline(board, w, h)
    nets = {}
    for n in sorted(nets_of(x["parts"])):
        if n in x["nc_nets"]:
            continue
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni
    for p in x["parts"]:
        fp = load_fp(p["fp"])
        fp.SetReference(p["ref"])
        fp.SetValue(p["value"])
        px, py, rot, side = x["placement"][p["ref"]]
        board.Add(fp)
        fp.SetPosition(P(px, py))
        fp.SetOrientationDegrees(rot)
        if side == "B":
            fp.Flip(fp.GetPosition(), False)
        if not p["item"]:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
        for pad in fp.Pads():
            net = p["pins"].get(pad.GetNumber())
            if net and net in nets:
                pad.SetNet(nets[net])
    for i, (hx, hy) in enumerate(x["holes"]):
        fp = load_fp(HOLE_FP)
        fp.SetReference("H{}".format(i + 1))
        fp.SetValue("M3")
        board.Add(fp)
        fp.SetPosition(P(hx, hy))
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
    for zx, zy in ((inset, inset), (w - inset, inset), (w - inset, h - inset), (inset, h - inset)):
        ol.Append(MM(ORIGIN[0] + zx), MM(ORIGIN[1] + zy))
    board.Add(z)
    return z


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
    for px, py in pts:
        ol.Append(MM(ORIGIN[0] + px), MM(ORIGIN[1] + py))
    board.Add(z)
    return z


def tie_keepouts(board):
    """网络连接点（NT 开头）两个焊盘之间那段铜不属于任何网络：布线器不知道它，走线别压上去——在 DSN 里设成小禁布区"""
    out = []
    for fp in board.GetFootprints():
        if not fp.GetReference().startswith("NT"):
            continue
        a, b = [p.GetPosition() for p in sorted(fp.Pads(), key=lambda p: p.GetNumber())]
        ax, ay, bx, by = (pcbnew.ToMM(v) - 100 for v in (a.x, a.y, b.x, b.y))
        L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        ux, uy = (bx - ax) / L, (by - ay) / L
        sx, sy = ax + ux * 0.3, ay + uy * 0.3  # 两端各让出 0.3 mm 给焊盘接线
        ex, ey = bx - ux * 0.3, by - uy * 0.3
        nx, ny = -uy * 0.4, ux * 0.4  # 宽 0.8 mm，不往里缩
        out.append(("F.Cu", [(sx + nx, sy + ny), (ex + nx, ey + ny), (ex - nx, ey - ny), (sx - nx, sy - ny)], 0.0))
    return out


def _drop_classes(txt):
    """去掉 KiCad 自己导出的网络分类（工程文件 .kicad_pro 里有分类时它也写一份，间距、层是上次的旧值，
    排在我们的分类后面会把它们盖掉——159d2b 第八、九次布线就是这样没按新间距布）；只留 kicad_default，
    去掉的分类里的网络放回 kicad_default（再由 dsn_rules 按新分类拿出去）"""
    out, k, back = [], 0, []
    for m in re.finditer(r"\(class (?!kicad_default\b|_class)", txt):
        if m.start() < k:
            continue
        depth, j = 0, m.start()
        while True:
            ch = txt[j]
            depth += ch == "("
            depth -= ch == ")"
            j += 1
            if depth == 0:
                break
        blk = txt[m.start():j]
        back += re.findall(r'"[^"]*"|[^\s()]+', blk[: blk.index("(", 1)])[2:]
        out.append(txt[k:m.start()])
        k = j
        while k < len(txt) and txt[k] in " \t\n":
            k += 1
    out.append(txt[k:])
    txt = "".join(out)
    if back:
        i = txt.index("(class kicad_default") + len("(class kicad_default")
        txt = txt[:i] + " " + " ".join(back) + txt[i:]
    return txt


def dsn_rules(dsn_text, classes, pairs=()):
    """改 DSN 的线宽 / 间距类别：classes = {类名: (线宽 mm, 间距 mm, [网络], [层]?)}；这些网络从缺省类别里拿出来。
    pairs = [(类名 A, 类名 B, 间距 mm)]：两个分类之间另定的间距
    （Specctra class_class；Default 即缺省类别 kicad_default）"""
    dsn_text = _drop_classes(dsn_text)
    i = dsn_text.index("(class kicad_default")
    j = dsn_text.index("(circuit", i)
    head = dsn_text[i:j]
    names = re.findall(r'"[^"]*"|[^\s()]+', head[len("(class kicad_default") :])
    moved = {n for spec in classes.values() for n in spec[2]}
    keep = [n for n in names if n.strip('"') not in moved]
    new_head = "(class kicad_default " + " ".join(keep) + "\n      "
    add = ""
    for name, spec in classes.items():
        w, c, nets = spec[:3]
        lay = " (use_layer {})".format(" ".join(spec[3])) if len(spec) > 3 else ""
        if nets:
            add += (
                "    (class {} {}\n      (circuit (use_via Via[0-3]_600:300_um){})\n"
                "      (rule (width {:.0f}) (clearance {:.0f}))\n    )\n"
            ).format(name, " ".join('"{}"'.format(n) for n in nets), lay, w * 1000, c * 1000)
    have = {n for n, spec in classes.items() if spec[2]} | {"Default"}
    for a, b, c in pairs:
        if a in have and b in have:
            add += "    (class_class (classes {} {}) (rule (clearance {:.0f})))\n".format(
                *("kicad_default" if n == "Default" else n for n in (a, b)), c * 1000)
    out = dsn_text[:i] + new_head + dsn_text[j:]
    k = out.index("(class kicad_default")
    return out[:k] + add.lstrip() + "    " + out[k:]


def dsn_keepouts(txt, keepouts, inset=0.45):
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
            add += '    (keepout "" (polygon {} 0 {}))\n'.format(
                layer,
                " ".join(
                    "{:.0f} {:.0f}".format((ORIGIN[0] + px) * 1000, -(ORIGIN[1] + py) * 1000) for px, py in coords
                ),
            )
    i = txt.index("    (plane ")  # 结构段里层定义之后、铺铜平面之前
    return txt[:i] + add + txt[i:]


def autoroute(board, workdir, jar, classes, passes=40, timeout=1800, plane_layers=("In1.Cu",), keepouts=(), pairs=(),
              replace=False):
    """导出 DSN（去掉电源平面网络）→ Freerouting → 读回 SES；返回 (走线段数, 过孔数)。
    replace=True：第二遍（板上已有上一遍的线，布线器接着补没连上的），读回前把没锁定的线删掉"""
    dsn = os.path.join(workdir, "route.dsn")
    ses = os.path.join(workdir, "route.ses")
    pcbnew.ExportSpecctraDSN(board, dsn)
    with open(dsn, encoding="utf-8") as f:
        txt = f.read()
    txt = dsn_rules(txt, classes, pairs)
    if keepouts:
        txt = dsn_keepouts(txt, keepouts)
    if plane_layers:  # 平面层只给地平面：缺省类别的信号线不走平面层
        sig = [ln for ln in re.findall(r"\(layer (\S+)\s*\n\s*\(type signal\)", txt) if ln not in plane_layers]
        i = txt.index("(class kicad_default")
        j = txt.index("(use_via", i)
        k = txt.index(")", j)
        txt = txt[: k + 1] + " (use_layer {})".format(" ".join(sig)) + txt[k + 1 :]
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
    if replace:  # 板上已有的线（上一遍的结果）导出时一起给了布线器，它可能改过：没锁定的先删掉，按它的结果整个换
        for t in [t for t in board.GetTracks() if not t.IsLocked()]:
            board.Remove(t)
    return import_ses(board, ses)


def import_ses(board, ses):
    """读 Specctra SES 的布线结果加到板子上（KiCad 7 的 ImportSpecctraSES 只能在图形界面里用）"""
    with open(ses, encoding="utf-8") as f:
        txt = f.read()
    res = re.search(r"\(resolution\s+(\w+)\s+(\d+)\)", txt)
    unit, div = res.group(1), float(res.group(2))
    scale = {"um": 1e-3, "mm": 1.0, "mil": 0.0254, "inch": 25.4}[unit] / div
    layers = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In1.Cu": pcbnew.In1_Cu, "In2.Cu": pcbnew.In2_Cu}
    ni = board.GetNetInfo()
    netmap = {ni.GetNetItem(i).GetNetname(): ni.GetNetItem(i) for i in range(board.GetNetCount())}
    ntr = nvia = 0

    def pt(px, py):
        return pcbnew.VECTOR2I(int(round(float(px) * scale * 1e6)), int(round(-float(py) * scale * 1e6)))

    body = txt[txt.find("(network_out") :]
    for name, content in _net_blocks(body):
        net = netmap.get(name)
        if net is None:
            continue
        for w in re.finditer(r"\(path\s+(\S+)\s+([\d.]+)\s+([-\d.\s]+)\)", content):
            layer = layers.get(w.group(1).strip('"'))
            width = float(w.group(2)) * scale
            nums = w.group(3).split()
            pts = [pt(nums[k], nums[k + 1]) for k in range(0, len(nums) - 1, 2)]
            for a, b in zip(pts, pts[1:], strict=False):
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
        blk = text[i : j + 1]
        m = re.match(r'\(net\s+(?:"([^"]*)"|(\S+))', blk)
        out.append((m.group(1) if m.group(1) is not None else m.group(2), blk))
        i = j + 1


def fill_zones(board):
    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())


def classes_of(x):
    """L4 网络分类 → 布线器要的 {类名: (线宽, 间距, [网络], [层]?)}；
    分类写了 route_mm 时布线按它（布完再加宽，见 route_fit）"""
    out = {}
    for c in x.get("net_classes") or []:
        spec = (c.get("route_mm") or c["track_mm"], c["clearance_mm"], list(c["nets"]))
        out[c["name"]] = spec + (list(c["layers"]),) if c.get("layers") else spec
    return out


def pairs_of(x):
    """L4 分类之间的间距 → [(类名 A, 类名 B, 间距 mm)]（每一对只列一次）"""
    out, seen = [], set()
    for q in x.get("class_pairs") or []:
        for a in q["a"]:
            for b in q["b"]:
                k = frozenset((a, b))
                if a != b and k not in seen:
                    seen.add(k)
                    out.append((a, b, q["clearance_mm"]))
    return out


def prepare(x, path, title=None, plane_net="GND", plane_layer="In1.Cu"):
    """未布线的板子：器件、网络、地平面、功率铺铜；返回 (board, nets, 禁布区)"""
    board, nets = build(x, path, title)
    w, h = x["board_mm"]
    if plane_net in nets:
        z = add_zone(board, nets[plane_net], board.GetLayerID(plane_layer), w, h)
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
    for net, layer, pts in x["pours"]:
        add_pour(board, nets[net], layer, pts)
    keep = [(lay, pts) for _, lay, pts in x["pours"]] + tie_keepouts(board)
    return board, nets, keep


def generate(x, path, workdir, jar, title=None, passes=50):
    """L4 → 布好线、填好铺铜的 KiCad 板子，存到 path；返回 (走线段数, 过孔数)"""
    board, _, keep = prepare(x, path, title)
    os.makedirs(workdir, exist_ok=True)
    ntr, nvia = autoroute(board, workdir, jar, classes_of(x), passes=passes, keepouts=keep)
    board.BuildConnectivity()
    fill_zones(board)
    pcbnew.SaveBoard(path, board)
    return ntr, nvia
