# -*- coding: utf-8 -*-
"""可制造性检查（DFM，第 88 轮）：按一份“示例板厂工艺能力”查 PCB。读 KiCad 7 的 .kicad_pcb（pcbnew Python 模块）。

前四项看板厂做不做得出来（线宽线距、孔与孔环、阻焊桥、元件到板边、元件间距），后四项是贴片、检测、测试好不好做
（极性元件方向、ICT 测试点覆盖率、大电流走线宽度）。工艺能力都是示例值。"""
from __future__ import annotations

import math

CAP = {"track_min": 0.127, "space_min": 0.127, "drill_min": 0.3, "annular_min": 0.15, "mask_bridge_min": 0.1,
       "edge_min": 0.5, "courtyard_gap": 0.0, "ict_coverage_min": 0.9, "dt_c": 20.0, "outer_oz": 2.0, "inner_oz": 1.0}
WHY = {
    "track": "板厂蚀刻能做到的最细线宽、最小线距；再细就会断线或短路",
    "drill": "钻头越细越容易断、孔壁镀铜越难；孔环太窄，钻偏一点就破环",
    "mask": "相邻焊盘之间要留一条阻焊（阻焊桥），否则回流焊时锡会连成桥",
    "edge": "板边要铣外形、过轨道夹持；元件离边太近会被铣到或卡轨道",
    "spacing": "贴片机吸嘴、AOI 视角、返修烙铁都要空间；器件外框（courtyard）不能重叠",
    "polarity": "极性元件（二极管、电解电容、芯片第 1 脚）方向统一，贴片编程和 AOI 判反向都简单，人工目检也不容易看错",
    "ict": "在线测试（ICT）用针床扎测试点；网络上没有能扎的点，这个网络就测不到",
    "current": "按 IPC-2221 由电流算线宽：线太窄会过热；外层 2 oz、内层 1 oz 铜，温升 20 ℃（示例）",
}


def _mm(v):
    import pcbnew
    return pcbnew.ToMM(v)


def ipc2221_width_mm(i_a, dt_c=20.0, oz=2.0, outer=True):
    """IPC-2221：I = k·ΔT^0.44·A^0.725（A 单位 mil²；外层 k = 0.048、内层 0.024）→ 线宽 mm"""
    k = 0.048 if outer else 0.024
    area = (i_a / (k * dt_c ** 0.44)) ** (1 / 0.725)
    thick_mil = 1.378 * oz
    return area / thick_mil * 0.0254


def check(pcb_path, design, cap=None, board=None):
    import pcbnew
    cap = dict(CAP, **(cap or {}))
    if board is None:
        board = pcbnew.LoadBoard(pcb_path)
    ox, oy = 100.0, 100.0
    W, H = design.BOARD_MM
    checks = []

    def add(key, name, why, ok, value, limit, unit, at=None, detail=""):
        checks.append({"key": key, "name": name, "why": WHY[why], "pass": bool(ok), "value": value, "limit": limit, "unit": unit,
                       "at": at or [], "detail": detail})

    tracks = [t for t in board.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]

    def xy(p):
        return [round(_mm(p.x) - ox, 2), round(_mm(p.y) - oy, 2)]
    # 1 线宽、线距
    thin = sorted(tracks, key=lambda t: t.GetWidth())[:1]
    wmin = round(_mm(thin[0].GetWidth()), 3) if thin else None
    add("track_width", "最细线宽", "track", wmin is None or wmin >= cap["track_min"] - 1e-6, wmin, cap["track_min"], "mm",
        [xy(thin[0].GetStart()) + [thin[0].GetNetname()]] if thin else [])
    clr = _clearance_violations(board, cap["space_min"])
    add("track_space", "最小线距（铜到铜）", "track", not clr, round(min((c[0] for c in clr), default=cap["space_min"]), 3), cap["space_min"], "mm",
        [c[1] for c in clr[:20]], "{} 处小于工艺能力".format(len(clr)) if clr else "")
    # 2 孔与孔环
    bad_d, bad_r, dmin, rmin = [], [], 99.0, 99.0
    for v in vias:
        d, dia = _mm(v.GetDrillValue()), _mm(v.GetWidth())
        dmin, rmin = min(dmin, d), min(rmin, (dia - d) / 2)
        if d < cap["drill_min"] - 1e-6:
            bad_d.append(xy(v.GetPosition()) + ["过孔"])
        if (dia - d) / 2 < cap["annular_min"] - 1e-6:
            bad_r.append(xy(v.GetPosition()) + ["过孔"])
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH:
                d = _mm(min(pad.GetDrillSize().x, pad.GetDrillSize().y))
                ring = (_mm(min(pad.GetSize().x, pad.GetSize().y)) - d) / 2
                dmin, rmin = min(dmin, d), min(rmin, ring)
                if d < cap["drill_min"] - 1e-6:
                    bad_d.append(xy(pad.GetPosition()) + [fp.GetReference()])
                if ring < cap["annular_min"] - 1e-6:
                    bad_r.append(xy(pad.GetPosition()) + [fp.GetReference()])
    add("drill", "最小孔径", "drill", not bad_d, round(dmin, 3), cap["drill_min"], "mm", bad_d[:20])
    add("annular", "最小孔环", "drill", not bad_r, round(rmin, 3), cap["annular_min"], "mm", bad_r[:20])
    # 3 阻焊桥：同一器件相邻焊盘的阻焊开窗间距
    margin = _mm(board.GetDesignSettings().m_SolderMaskExpansion)
    bmin, bad_b = 99.0, []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD and p.GetNumber() != ""]
        for i, a in enumerate(pads):
            ba = a.GetBoundingBox()
            for b in pads[i + 1:]:
                if a.GetNetCode() == b.GetNetCode() and a.GetNetCode() > 0:
                    continue
                bb = b.GetBoundingBox()
                gx = max(_mm(bb.GetLeft()) - _mm(ba.GetRight()), _mm(ba.GetLeft()) - _mm(bb.GetRight()))
                gy = max(_mm(bb.GetTop()) - _mm(ba.GetBottom()), _mm(ba.GetTop()) - _mm(bb.GetBottom()))
                g = max(gx, gy) - 2 * margin
                if g < 0.6:
                    bmin = min(bmin, g)
                    if g < cap["mask_bridge_min"] - 1e-6:
                        bad_b.append(xy(a.GetPosition()) + [fp.GetReference()])
    add("mask_bridge", "最小阻焊桥", "mask", not bad_b, round(bmin, 3), cap["mask_bridge_min"], "mm", bad_b[:20])
    # 4 元件到板边、元件间距
    boxes, bad_e, emin = [], [], 99.0
    for fp in board.GetFootprints():
        if fp.GetReference().startswith(("H", "NT")):      # 安装孔、网络连接点（铜皮的一部分）不算元件
            continue
        lay = pcbnew.F_CrtYd if fp.GetLayer() == pcbnew.F_Cu else pcbnew.B_CrtYd
        c = fp.GetCourtyard(lay)
        bb = c.BBox() if c.OutlineCount() else fp.GetBoundingBox(False, False)
        x0, y0 = _mm(bb.GetX()) - ox, _mm(bb.GetY()) - oy
        x1, y1 = x0 + _mm(bb.GetWidth()), y0 + _mm(bb.GetHeight())
        boxes.append((fp.GetReference(), fp.GetLayer(), x0, y0, x1, y1))
        e = min(x0, y0, W - x1, H - y1)
        emin = min(emin, e)
        if e < cap["edge_min"] - 1e-6:
            bad_e.append([round((x0 + x1) / 2, 2), round((y0 + y1) / 2, 2), fp.GetReference()])
    add("edge", "元件到板边", "edge", not bad_e, round(emin, 2), cap["edge_min"], "mm", bad_e)
    ovl = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] != b[1]:
                continue
            if a[2] < b[4] and b[2] < a[4] and a[3] < b[5] and b[3] < a[5]:
                ovl.append([round((max(a[2], b[2]) + min(a[4], b[4])) / 2, 2), round((max(a[3], b[3]) + min(a[5], b[5])) / 2, 2), a[0] + " / " + b[0]])
    add("spacing", "元件外框不重叠", "spacing", not ovl, len(ovl), 0, "处", ovl[:20])
    # 5 极性元件方向：二极管、电解电容不能有转 180°、270° 的（只用 0° 一族和 90° 一族）
    pol = [p for p in design.PARTS if p["lib"] in ("Device:D_Schottky", "Device:C_Polarized", "Device:D")]
    bad_p = []
    for p in pol:
        fp = board.FindFootprintByReference(p["ref"])
        r = int(round(fp.GetOrientationDegrees())) % 360
        if r in (180, 270):
            bad_p.append(xy(fp.GetPosition()) + ["{} 转 {}°".format(p["ref"], r)])
    add("polarity", "极性元件方向统一", "polarity", not bad_p, len(pol) - len(bad_p), len(pol), "个", bad_p,
        "二极管、电解电容 {} 个".format(len(pol)))
    # 6 ICT 测试点覆盖率：网络上有通孔焊盘、底面测试点或不盖阻焊的过孔，针床就扎得到
    access = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            n = pad.GetNetname()
            if not n:
                continue
            access.setdefault(n, False)
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH or (fp.GetLayer() == pcbnew.B_Cu and fp.GetReference().startswith("TP")):
                access[n] = True
    for v in vias:
        if v.GetNetname() in access:
            access[v.GetNetname()] = True
    nets = [n for n in access if not n.startswith("unconnected")]
    miss = sorted(n for n in nets if not access[n])
    cov = (len(nets) - len(miss)) / max(1, len(nets))
    add("ict", "ICT 测试点覆盖率", "ict", cov >= cap["ict_coverage_min"] - 1e-9, round(cov, 3), cap["ict_coverage_min"], "",
        [], "扎不到的网络：" + "、".join(miss) if miss else "每个网络都扎得到")
    # 7 大电流走线宽度：功率路径上的焊盘（MOSFET、采样电阻、端子、母线电容）之间，只用够宽的走线也连得通
    #   （驱动、采样放大器引出的细线是信号支路，不走大电流，不查；地走内层平面，不查）
    bad_i, rows = [], []
    for net, amps in design.HIGH_CURRENT.items():
        pads = getattr(design, "POWER_PADS", {}).get(net)
        if net == "GND" or not pads:
            continue
        need_o = ipc2221_width_mm(amps, cap["dt_c"], cap["outer_oz"], True)
        need_i = ipc2221_width_mm(amps, cap["dt_c"], cap["inner_oz"], False)
        ok, widest = _wide_path(board, net, pads, need_o, need_i)
        rows.append("{} {:g} A：外层要 ≥ {:.2f} mm（内层 {:.2f} mm），功率路径{}".format(net, amps, need_o, need_i, "连通" if ok else "有一段不够宽"))
        if not ok:
            fp = board.FindFootprintByReference(pads[0][0])
            bad_i.append(xy(fp.GetPosition()) + [net])
    add("current", "大电流走线宽度", "current", not bad_i, len(rows) - len(bad_i), len(rows), "条网络", bad_i, "；".join(rows))
    return {"capability": cap, "checks": checks, "pass": all(c["pass"] for c in checks)}


def _clearance_violations(board, space):
    """铜到铜间距：不同网络的走线之间（线段到线段）；焊盘、铺铜的间距由 KiCad 设计规则检查管"""
    items = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_TRACK":
            items.append(("t", t.GetLayer(), t.GetNetCode(), _mm(t.GetStart().x), _mm(t.GetStart().y), _mm(t.GetEnd().x), _mm(t.GetEnd().y),
                          _mm(t.GetWidth()) / 2))
    out = []
    by_layer = {}
    for it in items:
        by_layer.setdefault(it[1], []).append(it)
    for lay, its in by_layer.items():
        its.sort(key=lambda a: min(a[3], a[5]))
        for i, a in enumerate(its):
            ax1 = max(a[3], a[5]) + a[7] + space + 3
            for b in its[i + 1:]:
                if min(b[3], b[5]) > ax1:
                    break
                if a[2] == b[2]:
                    continue
                d = _seg_dist(a[3:7], b[3:7]) - a[7] - b[7]
                if d < space - 1e-4:
                    out.append((d, [round((a[3] + a[5]) / 2 - 100, 2), round((a[4] + a[6]) / 2 - 100, 2), board.GetLayerName(lay)]))
    return out


def _seg_dist(a, b):
    def pt_seg(px, py, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        L = dx * dx + dy * dy
        t = 0 if L == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L))
        return math.hypot(px - x1 - t * dx, py - y1 - t * dy)
    x1, y1, x2, y2 = a
    x3, y3, x4, y4 = b

    def ccw(ax, ay, bx, by, cx, cy):
        return (cy - ay) * (bx - ax) - (by - ay) * (cx - ax)
    d1, d2 = ccw(x1, y1, x2, y2, x3, y3), ccw(x1, y1, x2, y2, x4, y4)
    d3, d4 = ccw(x3, y3, x4, y4, x1, y1), ccw(x3, y3, x4, y4, x2, y2)
    if d1 * d2 < 0 and d3 * d4 < 0:
        return 0.0
    return min(pt_seg(x1, y1, x3, y3, x4, y4), pt_seg(x2, y2, x3, y3, x4, y4), pt_seg(x3, y3, x1, y1, x2, y2), pt_seg(x4, y4, x1, y1, x2, y2))


def _wide_path(board, net, pads, need_outer, need_inner):
    """只用够宽的走线、过孔和焊盘，net 上这些功率焊盘是否连成一片"""
    import pcbnew
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)
    outer = (pcbnew.F_Cu, pcbnew.B_Cu)
    pad_items = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetname() == net:
                key = ("pad", fp.GetReference(), pad.GetNumber(), pad.GetPosition().x, pad.GetPosition().y)
                pad_items.append((key, pad))
    pts = []
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            k = ("via", t.GetPosition().x, t.GetPosition().y)
            for lay in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
                pts.append(((lay, t.GetPosition().x, t.GetPosition().y), k))
            continue
        need = need_outer if t.GetLayer() in outer else need_inner
        if pcbnew.ToMM(t.GetWidth()) + 1e-6 < need:
            continue
        a = (t.GetLayer(), t.GetStart().x, t.GetStart().y)
        b = (t.GetLayer(), t.GetEnd().x, t.GetEnd().y)
        union(a, b)
        pts += [(a, a), (b, b)]
    for p, k in pts:
        union(p, k)
    # 铺铜：同一块铺铜（填充后的一个岛）碰到的焊盘、走线端点、过孔都连在一起
    for z in board.Zones():
        if z.GetNetname() != net or not z.IsFilled():
            continue
        for lay in z.GetLayerSet().Seq():
            fills = z.GetFilledPolysList(lay)
            for oi in range(fills.OutlineCount()):
                chain = fills.Outline(oi)
                isle = ("zone", z.m_Uuid.AsString(), lay, oi)
                find(isle)
                for key, pad in pad_items:
                    if pad.IsOnLayer(lay) and any(chain.PointInside(q) for q in _pad_points(pad)):
                        union(key, isle)
                for p, _ in pts:
                    if p[0] == lay and chain.PointInside(pcbnew.VECTOR2I(p[1], p[2])):
                        union(p, isle)
    # 焊盘：落在焊盘铜上的点都并到焊盘
    for key, pad in pad_items:
        find(key)
        for p, _ in pts:
            lay, x, y = p
            if pad.IsOnLayer(lay) and pad.HitTest(pcbnew.VECTOR2I(x, y)):
                union(p, key)
    # 同一器件同一编号的多个焊盘（TDSON 的源极 1–3）算一个
    by_num = {}
    for key, pad in pad_items:
        by_num.setdefault((key[1], key[2]), []).append(key)
    groups = {}
    for key, pad in pad_items:
        groups.setdefault((key[1], key[2]), key)
    for (ref, num), keys in by_num.items():
        for k in keys[1:]:
            union(k, keys[0])
    want = []
    for ref, num in pads:
        k = groups.get((ref, num))
        if k is None:
            return False, None
        want.append(k)
    # MOSFET 源极 1–3 脚同一网络：一起算
    for (ref, num), keys in by_num.items():
        if ref.startswith("Q") and num in ("1", "2", "3"):
            for n2 in ("1", "2", "3"):
                if (ref, n2) in groups:
                    union(groups[(ref, n2)], keys[0])
    roots = {find(k) for k in want}
    return len(roots) == 1, None


def _pad_points(pad):
    """焊盘中心和四边往里 20% 的点（铺铜只盖住焊盘一部分也算连上）"""
    import pcbnew
    bb = pad.GetBoundingBox()
    cx, cy = bb.GetCenter().x, bb.GetCenter().y
    hw, hh = int(bb.GetWidth() * 0.4), int(bb.GetHeight() * 0.4)
    return [pcbnew.VECTOR2I(cx, cy), pcbnew.VECTOR2I(cx - hw, cy), pcbnew.VECTOR2I(cx + hw, cy),
            pcbnew.VECTOR2I(cx, cy - hh), pcbnew.VECTOR2I(cx, cy + hh)]
