# -*- coding: utf-8 -*-
"""布线器（Freerouting）的两个限制和对应的做法（第 159 轮 159d2b，平缝机控制器 CTRL-LS 试出来的）：

1. 一个焊盘离同一器件上另一网络的焊盘比“两类网络之间的布线间距”还近时，布线器接不上这个焊盘
   （例：1206 分压电阻两脚 1.8 mm、要求 2.2 mm；整流桥两个交流脚 1.9 mm、相线↔零线要求 2.6 mm）。
   引脚间距是器件自己的事（由它的额定管）：布线前给这种焊盘各引一小段锁定的线，朝最空的方向、长到离开相邻焊盘的
   间距范围，布线器从线头接；全板的布线间距不放宽（第十一次试过整体放宽，别处的线也跟着挤近了）。 → stubs
   设计规则检查和安全距离检查对这几段同样按“器件自己引脚间距”处理（只限这个器件外框里、这两个网络之间）。
2. 布线器不会在引脚旁边把粗线收细：大电流线（交流 7.9 A 用 2.5 mm）进不了 5 mm 脚距的端子。
   分类可以写 route_mm（布线时的线宽，比 track_mm 细），布完再把每段线在有空的地方加宽到 track_mm，
   旁边没空的那几段保持细（只在引脚附近）。 → widen

纯几何计算，不联网、不调 AI。"""

from __future__ import annotations

import itertools

import pcbnew

STEP = 0.05
SAME_NET_GAP = 0.2  # 同网络、不相连的两块铜加宽后至少隔这么多（比工艺能力表最小线距 0.127 mm 宽）
SLACK = 0.01  # 焊盘圆弧在这里按多边形算，比 KiCad 精确算的近一点点：加宽时多留 0.01 mm（159d2c：2.595 对 2.6）


def _poly(ps):
    from shapely.geometry import Polygon

    o = ps.Outline(0)
    return Polygon([(pcbnew.ToMM(o.CPoint(i).x), pcbnew.ToMM(o.CPoint(i).y)) for i in range(o.PointCount())])


def pad_gaps(board, class_of):
    """{frozenset((类 A, 类 B)): 同一器件上两类焊盘之间的最小间距 mm, ...}；class_of(网络名) → 类名"""
    out = {}
    for fp in board.GetFootprints():
        pads = [(p, class_of(p.GetNetname())) for p in fp.Pads() if p.GetNetname()]
        for (p, a), (q, b) in itertools.combinations(pads, 2):
            if a == b or p.GetNetname() == q.GetNetname():
                continue
            g = _poly(p.GetEffectivePolygon()).distance(_poly(q.GetEffectivePolygon()))
            k = frozenset((a, b))
            if k not in out or g < out[k][0]:
                out[k] = (g, fp.GetReference())
    return out


def conflicts(board, class_of, clearance):
    """同一器件上、比布线间距还近的两类焊盘：[(器件, 焊盘 A, 焊盘 B, 间距 mm, 要求 mm)]"""
    out = []
    for fp in board.GetFootprints():
        pads = [p for p in fp.Pads() if p.GetNetname()]
        for p, q in itertools.combinations(pads, 2):
            na, nb = p.GetNetname(), q.GetNetname()
            if na == nb or class_of(na) == class_of(nb):
                continue
            need = clearance(na, nb)
            g = _poly(p.GetEffectivePolygon()).distance(_poly(q.GetEffectivePolygon()))
            if g < need - 1e-6:
                out.append((fp.GetReference(), p, q, g, need))
    return out


def stubs(board, class_of, clearance, width_of, layers_of, outline, keepouts=()):
    """给“比布线间距还近”的焊盘各引一小段固定线（锁定）：从焊盘中心朝最空的方向引出，长到离开相邻焊盘的间距范围，
    布线器从线头接（它接不上这种焊盘本身，见上面第 1 条）。返回加的段数。
    width_of(网络) → 布线线宽；layers_of(网络) → 允许的铜层名；outline = 板框（shapely 多边形，mm，KiCad 坐标）；
    keepouts = 禁布区 [(shapely 多边形, 铜层号集合)]：焊盘压着禁布区边的（隔离带收窄处的隔离电源脚），布线器同样接不上，
    也引一段出来，引出线本身不进禁布区"""
    import math

    from shapely.geometry import LineString

    cons = conflicts(board, class_of, clearance)
    need = {}
    for _, p, q, _, c in cons:
        for a in (p, q):
            k = (a.GetParent().GetReference(), a.GetNumber())
            need[k] = (a, max(c, need.get(k, (a, 0))[1]))
    pads = [(p, _poly(p.GetEffectivePolygon())) for fp in board.GetFootprints() for p in fp.Pads() if p.GetNetname()]
    for p, g in pads:
        if any(g.intersects(kp) and lays & set(p.GetLayerSet().CuStack()) for kp, lays in keepouts):
            k = (p.GetParent().GetReference(), p.GetNumber())
            need.setdefault(k, (p, 0.6))
    lid = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In2.Cu": pcbnew.In2_Cu}
    made = []  # 已经引出的线也算障碍：(网络, 层, 形状)
    n_made = 0
    # 板上已有的线（先布的交流线）也算障碍；已经有线接着的焊盘不用再引
    # （159d2c：相线的引出线贴着先布的零线，只隔 0.68 mm）
    mm = pcbnew.ToMM
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            continue
        g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(
            mm(t.GetWidth()) / 2)
        made.append((t.GetNetname(), {v: k for k, v in lid.items()}.get(t.GetLayer()), g))
        for key in list(need):
            pa = need[key][0]
            if pa.GetNetname() == t.GetNetname() and pa.IsOnLayer(t.GetLayer()) and \
                    _poly(pa.GetEffectivePolygon()).distance(g) < 1e-3:
                del need[key]
    for (_ref, _num), (p, c) in sorted(need.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        net = p.GetNetname()
        w = width_of(net)
        x0, y0 = pcbnew.ToMM(p.GetPosition().x), pcbnew.ToMM(p.GetPosition().y)
        sx, sy = pcbnew.ToMM(p.GetSize().x), pcbnew.ToMM(p.GetSize().y)
        length = max(sx, sy) / 2 + c + w / 2 + 0.3
        on = [ln for ln in layers_of(net) if ln in lid and p.IsOnLayer(lid[ln])]
        best = None
        for ln in on:
            for k in range(16):
                a = k * math.pi / 8
                end = (x0 + length * math.cos(a), y0 + length * math.sin(a))
                seg = LineString([(x0, y0), end])
                if not outline.buffer(-(w / 2 + 0.5)).contains(LineString([seg.interpolate(0.5), end])):
                    continue
                if any(lid[ln] in lays and seg.buffer(w / 2).intersects(kp) for kp, lays in keepouts):
                    continue
                tip = LineString([seg.interpolate(max(sx, sy) / 2 + c), end]).buffer(w / 2)
                score = 99.0
                for q, g in pads:
                    if q.GetNetname() == net or not q.IsOnLayer(lid[ln]):
                        continue
                    d = g.distance(tip) - clearance(net, q.GetNetname())
                    other = q.GetParent().GetReference() != p.GetParent().GetReference()
                    if other and g.distance(seg.buffer(w / 2)) < clearance(net, q.GetNetname()):
                        d = min(d, -1.0)
                    score = min(score, d)
                for onet, olay, og in made:
                    if onet != net and olay == ln:
                        score = min(score, og.distance(seg.buffer(w / 2)) - clearance(net, onet))
                if best is None or score > best[0]:
                    best = (score, ln, end)
        if not best or best[0] < 0:
            continue
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(p.GetPosition())
        t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(best[2][0]), pcbnew.FromMM(best[2][1])))
        t.SetWidth(pcbnew.FromMM(w))
        t.SetLayer(lid[best[1]])
        t.SetNet(p.GetNet())
        t.SetLocked(True)
        board.Add(t)
        made.append((net, best[1], LineString([(x0, y0), best[2]]).buffer(w / 2)))
        n_made += 1
    return n_made


def drop_dangling(board, keep=()):
    """布完以后，没有别的线、过孔接到（焊盘以外那一截）的引出线删掉：布线器从别处接通了这个焊盘，引出线用不上。返回删的段数"""
    from shapely.geometry import LineString, Point

    def geom(t):
        mm = pcbnew.ToMM
        if t.GetClass() == "PCB_VIA":
            return Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
        return LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(
            mm(t.GetWidth()) / 2)

    tracks = list(board.GetTracks())
    drop = []
    for t in tracks:
        if t.GetClass() == "PCB_VIA" or not t.IsLocked() or t.m_Uuid.AsString() in keep:
            continue
        mm = pcbnew.ToMM
        a, b = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
        # 整段都算（第十四次：布线器的过孔打在引出线中段，只看外面一截时误删了）；
        # 宁可留下一段用不上的（只是提示），不能删掉接着的
        outer = LineString([a, b])
        pad = [_poly(p.GetEffectivePolygon()) for p in board.GetPads() if p.GetNetname() == t.GetNetname()
               and p.GetPosition() == t.GetStart()]
        used = any(o is not t and o.GetNetname() == t.GetNetname() and not o.IsLocked() and
                   not (pad and pad[0].buffer(0.05).contains(geom(o))) and
                   (o.GetClass() == "PCB_VIA" or o.GetLayer() == t.GetLayer()) and geom(o).distance(outer) < 0.01
                   for o in tracks)
        if not used:
            drop.append(t)
    for t in drop:
        board.Remove(t)
    return len(drop)


def dedupe(board):
    """布线器的结果里会带回固定线（与板上已有的一样）：同网络、同层、同起止点的重复段删掉。返回删的段数"""
    seen, drop = set(), []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            k = ("v", t.GetNetname(), t.GetPosition().x, t.GetPosition().y)
        else:
            a, b = (t.GetStart().x, t.GetStart().y), (t.GetEnd().x, t.GetEnd().y)
            k = ("t", t.GetNetname(), t.GetLayer(), min(a, b), max(a, b))
        if k in seen:
            drop.append(t)
        seen.add(k)
    for t in drop:
        board.Remove(t)
    return len(drop)


def widen(board, targets, clearance, passes=2, outline=None, edge_mm=0.5, keepouts=()):
    """targets = {网络名: 目标线宽 mm}；clearance(网络 A, 网络 B) → 要求间距 mm。
    每段线按“离别的网络的铜还有多远”加宽，最多到目标线宽。一段一段来，已加宽的按加宽后的宽度给后面的段让路；走两遍
    （第一遍让路让多了的，第二遍再补）。线头接着的焊盘所在器件，它别的焊盘按“器件自己引脚间距”算
    （与 stubs、设计规则检查里的引脚规则同一口径：线贴着自己的焊盘，离邻脚不比两个焊盘之间更近）。
    outline = 板框（shapely 多边形）：线离板边至少 edge_mm（159d2c：端子旁的线加宽后压到板边）；
    keepouts = 禁布区 [(多边形, 铜层号集合)]：加宽不进去（159d2c：一段内层线加宽后压进了隔离带）。
    返回 (加宽到目标的段数, 只加宽一部分的段数, 没动的段数)"""
    from shapely import STRtree
    from shapely.geometry import LineString, Point

    mm = pcbnew.ToMM
    edge = outline.exterior if outline is not None else None
    static = {}  # 层 → [(网络, 形状, 器件, 焊盘形状)]
    pads = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            g = _poly(p.GetEffectivePolygon())
            pads.append((p.GetNetname(), g, fp.GetReference()))
            for lid in p.GetLayerSet().CuStack():
                static.setdefault(lid, []).append((p.GetNetname(), g, fp.GetReference()))
    segs = []
    for t in board.GetTracks():
        net = t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
            for l2 in t.GetLayerSet().CuStack():
                static.setdefault(l2, []).append((net, g, None))
            continue
        line = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
        w = mm(t.GetWidth())
        if net in targets and targets[net] > w + 1e-6:
            segs.append([t, line, w, t.GetLayer()])
        else:
            static.setdefault(t.GetLayer(), []).append((net, line.buffer(w / 2), None))
    # 铺铜不算：它在线之后填，会给线让路（板上已填好的铺铜正好贴着现在的线宽，算进来就加不宽了）
    trees = {lid: (STRtree([g for _, g, _ in v]), v) for lid, v in static.items()}
    # 每段线头接着哪些焊盘：{段号: [(器件, 焊盘形状)]}
    own = {}
    for k, (t, line, _w, _l) in enumerate(segs):
        ends = [Point(line.coords[0]), Point(line.coords[-1])]
        own[k] = [(ref, g) for n, g, ref in pads
                  if n == t.GetNetname() and any(g.buffer(0.01).contains(e) for e in ends)]
    width = [sg[2] for sg in segs]
    for npass in range(passes):
        for k, (t, line, w0, lid) in enumerate(segs):
            net, goal = t.GetNetname(), targets[t.GetNetname()]
            half = goal / 2
            if edge is not None:
                half = min(half, line.distance(edge) - edge_mm)
            for kp, lays in keepouts:
                if lid in lays:
                    half = min(half, line.distance(kp) - 0.05)
            win = line.buffer(goal / 2 + 6.0)
            tree, items = trees.get(lid, (None, []))
            near = [items[int(i)] for i in tree.query(win)] if tree is not None else []
            for onet, g, ref in near:
                if onet == net:
                    # 同一网络、原来没碰上的铜：要么碰上、要么隔开，不能加宽到只剩一条细缝
                    # （159d2c：工艺检查 F2 量到 0.12 mm 的缝）
                    if g.distance(line.buffer(w0 / 2)) > 1e-3:
                        half = min(half, line.distance(g) - SAME_NET_GAP)
                    continue
                c = clearance(net, onet)
                if ref is not None:
                    for oref, pg in own[k]:
                        if oref == ref:
                            c = min(c, pg.distance(g))
                half = min(half, line.distance(g) - c - SLACK)
            for m, (t2, line2, _w, lid2) in enumerate(segs):
                if m == k or lid2 != lid or t2.GetNetname() == net or line2.distance(line) > goal + 6.0:
                    continue
                half = min(half, line.distance(line2) - width[m] / 2 - clearance(net, t2.GetNetname()) - SLACK)
            width[k] = max(w0, min(goal, int(2 * half / STEP + 1e-9) * STEP), width[k] if npass else w0)
    full = part = none = 0
    for k, (t, _line, w0, _l) in enumerate(segs):
        goal = targets[t.GetNetname()]
        if width[k] >= goal - 1e-6:
            full += 1
        elif width[k] > w0 + 1e-6:
            part += 1
        else:
            none += 1
        t.SetWidth(pcbnew.FromMM(round(width[k], 2)))
    return full, part, none


def finish(board, class_of, clearance, width_of, layers_of, skip=("GND", "GND_ISO"), keepouts=()):
    """布线器两遍都没接上的几根：同一网络还分成几块时，在两块最近的两点之间试一段直线或一个拐角（两段），
    哪一层、哪条路上离别的网络的铜都够远就加上。器件自己引脚之间的间距照旧不算（与 stubs 同一口径）。
    skip = 平面网络（由内层平面连通，不在这里补）；keepouts = 禁布区 [(多边形, 铜层号集合)]，补的线不进去。
    返回 [(网络, 层, 段数)]"""
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union

    mm = pcbnew.ToMM
    lid = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In2.Cu": pcbnew.In2_Cu}

    def items():
        out = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname():
                    out.append((p.GetNetname(), set(p.GetLayerSet().CuStack()), _poly(p.GetEffectivePolygon()),
                                fp.GetReference(), [(mm(p.GetPosition().x), mm(p.GetPosition().y))]))
        for t in board.GetTracks():
            if t.GetClass() == "PCB_VIA":
                c = (mm(t.GetPosition().x), mm(t.GetPosition().y))
                g = Point(c).buffer(mm(t.GetWidth()) / 2)
                out.append((t.GetNetname(), set(t.GetLayerSet().CuStack()), g, None, [c]))
            else:
                a, b = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
                g = LineString([a, b]).buffer(mm(t.GetWidth()) / 2)
                out.append((t.GetNetname(), {t.GetLayer()}, g, None, [a, b]))
        return out

    added = []
    for _ in range(3):
        its = items()
        nets = {}
        for k, it in enumerate(its):
            nets.setdefault(it[0], []).append(k)
        done = False
        for net, ks in sorted(nets.items()):
            if net in skip or len(ks) < 2:
                continue
            parent = {k: k for k in ks}
            for i, a in enumerate(ks):
                for b in ks[i + 1:]:
                    ia, ib = its[a], its[b]
                    if ia[1] & ib[1] and ia[2].distance(ib[2]) < 1e-3:
                        parent[_root(parent, a)] = _root(parent, b)
            groups = {}
            for k in ks:
                groups.setdefault(_root(parent, k), []).append(k)
            if len(groups) < 2:
                continue
            g = list(groups.values())
            w = width_of(net)
            # 候选：第一块和其余各块之间，端点两两配对，近的先试（第十七次：只试最近一对时，那一对的路正好被挡）
            cands = sorted(
                (Point(pa).distance(Point(pb)), x, y, pa, pb)
                for x in g[0] for y in [k for gg in g[1:] for k in gg]
                for pa in its[x][4] for pb in its[y][4])[:40]
            for _d, x, y, pa, pb in cands:
                refs = {its[x][3], its[y][3]} - {None}
                for ln in layers_of(net):
                    if ln not in lid or not (lid[ln] in its[x][1] and lid[ln] in its[y][1]):
                        continue
                    for path in ([pa, pb], [pa, (pb[0], pa[1]), pb], [pa, (pa[0], pb[1]), pb]):
                        legs = zip(path, path[1:], strict=False)
                        shape = unary_union([LineString([u, v]).buffer(w / 2) for u, v in legs])
                        ok = not any(lid[ln] in lays and shape.intersects(k) for k, lays in keepouts)
                        ends = [g for g in (its[x][2], its[y][2])]
                        for onet, olay, og, oref, _c in its if ok else ():
                            if onet == net or lid[ln] not in olay:
                                continue
                            need = clearance(net, onet)
                            if oref in refs:  # 两头焊盘所在器件的邻脚：不比两个焊盘之间更近（与 widen 同一口径）
                                need = min(need, min(e.distance(og) for e in ends))
                            if og.distance(shape) < need:
                                ok = False
                                break
                        if not ok:
                            continue
                        for u, v in zip(path, path[1:], strict=False):
                            if u == v:
                                continue
                            t = pcbnew.PCB_TRACK(board)
                            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(u[0]), pcbnew.FromMM(u[1])))
                            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(v[0]), pcbnew.FromMM(v[1])))
                            t.SetWidth(pcbnew.FromMM(w))
                            t.SetLayer(lid[ln])
                            t.SetNet(board.FindNet(net))
                            board.Add(t)
                        added.append((net, ln, len(path) - 1))
                        done = True
                        break
                    if done:
                        break
                if done:
                    break
            if done:
                break
        if not done:
            break
    return added


def _root(parent, k):
    while parent[k] != k:
        parent[k] = parent[parent[k]]
        k = parent[k]
    return k


def _pieces(board, net):
    """一个网络的铜分成几块：[[(层号集合, 形状)], ...]（焊盘、过孔跨层，走线单层；同层相碰算连着）"""
    from shapely.geometry import LineString, Point

    mm = pcbnew.ToMM
    its = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname() == net:
                its.append((set(p.GetLayerSet().CuStack()), _poly(p.GetEffectivePolygon())))
    for t in board.GetTracks():
        if t.GetNetname() != net:
            continue
        if t.GetClass() == "PCB_VIA":
            c = (mm(t.GetPosition().x), mm(t.GetPosition().y))
            its.append((set(t.GetLayerSet().CuStack()), Point(c).buffer(mm(t.GetWidth()) / 2)))
        else:
            a, b = (mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))
            its.append(({t.GetLayer()}, LineString([a, b]).buffer(mm(t.GetWidth()) / 2)))
    parent = {k: k for k in range(len(its))}
    for i in range(len(its)):
        for j in range(i + 1, len(its)):
            if its[i][0] & its[j][0] and its[i][1].distance(its[j][1]) < 1e-3:
                parent[_root(parent, i)] = _root(parent, j)
    groups = {}
    for k in range(len(its)):
        groups.setdefault(_root(parent, k), []).append(its[k])
    return list(groups.values())


def maze(board, net, class_of, clearance, width, layers, outline, keepouts=(), step=0.25, edge_mm=0.5, lock=False):
    """补线的最后一招（159d2c：交流零线一根从滤波电感到整流桥，两遍自动布线、直线和拐角都接不上）：
    在一层上按网格找路（A*，八个方向），把网络还分开的两块接起来。障碍 = 这一层别的网络的铜各按要求间距外扩、
    禁布区、板边。找到就按路径（合并同方向的格）加线，返回 (层名, 段数)；找不到返回 None。纯几何计算。"""
    import heapq

    import numpy as np
    import shapely
    from shapely import contains_xy
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union

    mm = pcbnew.ToMM
    lid = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu, "In2.Cu": pcbnew.In2_Cu}
    pieces = _pieces(board, net)
    if len(pieces) < 2:
        return None
    x0, y0, x1, y1 = outline.bounds
    xs = np.arange(x0, x1, step) + step / 2
    ys = np.arange(y0, y1, step) + step / 2
    gx, gy = np.meshgrid(xs, ys)
    inner = outline.buffer(-(width / 2 + edge_mm))
    for ln in layers:
        if ln not in lid:
            continue
        L = lid[ln]
        bufs = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.GetNetname() != net and p.IsOnLayer(L):
                    g = _poly(p.GetEffectivePolygon())
                    bufs.append(g.buffer(clearance(net, p.GetNetname()) + width / 2 + SLACK))
        for t in board.GetTracks():
            if t.GetNetname() == net or not t.IsOnLayer(L):
                continue
            if t.GetClass() == "PCB_VIA":
                g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
            else:
                g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(
                    mm(t.GetWidth()) / 2)
            bufs.append(g.buffer(clearance(net, t.GetNetname()) + width / 2 + SLACK))
        for kp, lays in keepouts:
            if L in lays:
                bufs.append(kp.buffer(width / 2 + SLACK))
        obst = unary_union(bufs)
        blocked = contains_xy(obst, gx, gy) | ~contains_xy(inner, gx, gy)
        on = [unary_union([g for ls, g in pc if L in ls]) for pc in pieces]
        if sum(1 for o in on if not o.is_empty) < 2:
            continue
        src = contains_xy(on[0], gx, gy) if not on[0].is_empty else np.zeros_like(blocked)
        dst = np.zeros_like(blocked)
        for o in on[1:]:
            if not o.is_empty:
                dst |= contains_xy(o, gx, gy)
        if not src.any() or not dst.any():
            continue
        free = ~blocked | src | dst
        ny, nx = free.shape
        tgt = np.argwhere(dst)
        ty, tx = tgt[:, 0].mean(), tgt[:, 1].mean()
        start = [tuple(v) for v in np.argwhere(src)]
        dist = {s: 0.0 for s in start}
        prev = {}
        heap = [(np.hypot(s[0] - ty, s[1] - tx), 0.0, s) for s in start]
        heapq.heapify(heap)
        moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
                 (-1, -1, 1.4142), (-1, 1, 1.4142), (1, -1, 1.4142), (1, 1, 1.4142)]
        end = None
        while heap:
            _f, d, (i, j) = heapq.heappop(heap)
            if d > dist.get((i, j), 1e18):
                continue
            if dst[i, j]:
                end = (i, j)
                break
            for di, dj, c in moves:
                a, b = i + di, j + dj
                if 0 <= a < ny and 0 <= b < nx and free[a, b]:
                    nd = d + c
                    if nd < dist.get((a, b), 1e18):
                        dist[(a, b)] = nd
                        prev[(a, b)] = (i, j)
                        heapq.heappush(heap, (nd + 0.5 * np.hypot(a - ty, b - tx), nd, (a, b)))
        if end is None:
            continue
        path = [end]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        # 合并同方向的格成一段
        pts = [path[0]]
        for k in range(1, len(path) - 1):
            d1 = (path[k][0] - path[k - 1][0], path[k][1] - path[k - 1][1])
            d2 = (path[k + 1][0] - path[k][0], path[k + 1][1] - path[k][1])
            if d1 != d2:
                pts.append(path[k])
        pts.append(path[-1])
        xy = [(float(xs[j]), float(ys[i])) for i, j in pts]
        # 拉直：从当前点往后找最远、直线过去不碰障碍的点（网格路径是锯齿，段数多）
        ok_area = inner.difference(obst).union(unary_union([o for o in on if not o.is_empty]))
        shapely.prepare(ok_area)
        out = [xy[0]]
        k = 0
        while k < len(xy) - 1:
            far = k + 1
            for m in range(len(xy) - 1, k + 1, -1):
                if ok_area.contains(LineString([xy[k], xy[m]])):
                    far = m
                    break
            out.append(xy[far])
            k = far
        xy = out
        made = []
        for u, v in zip(xy, xy[1:], strict=False):
            if u == v:
                continue
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(u[0]), pcbnew.FromMM(u[1])))
            t.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(v[0]), pcbnew.FromMM(v[1])))
            t.SetWidth(pcbnew.FromMM(width))
            t.SetLayer(L)
            t.SetNet(board.FindNet(net))
            board.Add(t)
            made.append(t)
        for t in made:
            t.SetLocked(lock)
        return ln, len(xy) - 1
    return None


def preroute(board, nets, class_of, clearance, width_of, layers_of, outline, keepouts=()):
    """先布几根要紧的线（159d2c：交流相线、零线），再交给自动布线器：板上还空的时候按网格找路（maze），
    每根网络把还分开的块一块块接起来，加的线锁定，自动布线器绕着它们走。
    返回 ({网络: 段数}, 没布通的网络, 加的线的编号集合)"""
    done, failed, ids = {}, [], set()
    for net in nets:
        n = 0
        while len(_pieces(board, net)) > 1:
            before = {t.m_Uuid.AsString() for t in board.GetTracks()}
            r = maze(board, net, class_of, clearance, width_of(net), layers_of(net), outline, keepouts,
                     lock=True)
            if r is None:
                failed.append(net)
                break
            ids |= {t.m_Uuid.AsString() for t in board.GetTracks()} - before
            n += r[1]
        done[net] = n
    return done, failed, ids


def shrink_close(board, clearance, min_w=0.15, most=0.06):
    """走线离别的网络的焊盘差一点点（≤ most mm）不够时，把这段线收细一点补上（不细于 min_w）。
    焊盘要求的间距取网络要求和器件、焊盘自己写的间距里大的（159d2c：反激芯片没接网络的散热焊盘，器件要求 0.2 mm，
    布线器给的 0.164）。返回收细的段数"""
    from shapely import STRtree
    from shapely.geometry import LineString

    mm = pcbnew.ToMM
    pads = []
    for fp in board.GetFootprints():
        fc = mm(fp.GetLocalClearance()) if hasattr(fp, "GetLocalClearance") else 0.0
        for p in fp.Pads():
            pc = mm(p.GetLocalClearance()) if hasattr(p, "GetLocalClearance") else 0.0
            pads.append((p.GetNetname(), _poly(p.GetEffectivePolygon()), max(fc, pc), p))
    tree = STRtree([g for _, g, _, _ in pads])
    n = 0
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            continue
        net, w = t.GetNetname(), mm(t.GetWidth())
        line = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
        short = 0.0
        for i in tree.query(line.buffer(w / 2 + 1.0)):
            pn, g, lc, p = pads[int(i)]
            if pn == net or not p.IsOnLayer(t.GetLayer()):
                continue
            need = max(clearance(net, pn) if pn else 0.0, lc)
            d = line.distance(g) - w / 2
            if d < need:
                short = max(short, need - d)
        if 0 < short <= most and w - 2 * (short + 0.005) >= min_w:
            t.SetWidth(pcbnew.FromMM(round(w - 2 * (short + 0.005), 3)))
            n += 1
    return n


def close_slivers(board, gap=SAME_NET_GAP, keep_mm=0.3):
    """同一网络、同一层上两块不相连的铜离得比 gap 还近（只剩一条细缝，板厂蚀刻难做，工艺检查 F2 报）：
    在两者最近的两点之间加一小段线把缝补上（159d2c：功率模块 N_W 脚旁的线在底层离自己的焊盘 0.086 mm）。返回补的处数"""
    from shapely.geometry import LineString, Point
    from shapely.ops import nearest_points

    mm = pcbnew.ToMM
    its = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.GetNetname():
                for lid in p.GetLayerSet().CuStack():
                    its.append((p.GetNetname(), lid, _poly(p.GetEffectivePolygon())))
    tracks = []
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            g = Point(mm(t.GetPosition().x), mm(t.GetPosition().y)).buffer(mm(t.GetWidth()) / 2)
            for lid in t.GetLayerSet().CuStack():
                its.append((t.GetNetname(), lid, g))
        else:
            g = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))]).buffer(
                mm(t.GetWidth()) / 2)
            its.append((t.GetNetname(), t.GetLayer(), g))
            tracks.append((t, g))
    # 别的网络（含没接网络的焊盘）的铜：补的那一小段离它们至少 keep_mm（159d2c：补在反激芯片散热焊盘旁，差了 0.005 mm）
    others = {}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            for lid in p.GetLayerSet().CuStack():
                others.setdefault(lid, []).append((p.GetNetname(), _poly(p.GetEffectivePolygon())))
    for net, lid, og in its:
        others.setdefault(lid, []).append((net, og))
    n = 0
    for t, g in tracks:
        for net, lid, og in its:
            if net != t.GetNetname() or lid != t.GetLayer() or og is g:
                continue
            d = g.distance(og)
            if 1e-3 < d < gap:
                a, b = nearest_points(g, og)
                w = min(mm(t.GetWidth()), 0.3)
                bridge = LineString([a, b]).buffer(w / 2 + keep_mm)
                if any(on != net and og2.intersects(bridge) for on, og2 in others.get(lid, [])):
                    continue
                s = pcbnew.PCB_TRACK(board)
                # 两头各往里伸半个线宽，保证和两边都搭上
                dx, dy = b.x - a.x, b.y - a.y
                k = (w / 2) / max(d, 1e-6)
                s.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(a.x - dx * k), pcbnew.FromMM(a.y - dy * k)))
                s.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(b.x + dx * k), pcbnew.FromMM(b.y + dy * k)))
                s.SetWidth(pcbnew.FromMM(w))
                s.SetLayer(lid)
                s.SetNet(t.GetNet())
                board.Add(s)
                n += 1
    return n


def _copper(board, layer):
    """这一层上的铜：[(形状, 网络名, 是不是铺铜)]——焊盘、过孔、走线、铺铜（已填的）"""
    from shapely.geometry import LineString, Point

    mm = pcbnew.ToMM
    out = []
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(layer):
                out.append((_poly(p.GetEffectivePolygon()), p.GetNetname(), False))
    for t in board.GetTracks():
        if not t.IsOnLayer(layer):
            continue
        if t.GetClass() == "PCB_VIA":
            c = Point(mm(t.GetPosition().x), mm(t.GetPosition().y))
            out.append((c.buffer(mm(t.GetWidth()) / 2), t.GetNetname(), False))
        else:
            seg = LineString([(mm(t.GetStart().x), mm(t.GetStart().y)), (mm(t.GetEnd().x), mm(t.GetEnd().y))])
            out.append((seg.buffer(mm(t.GetWidth()) / 2), t.GetNetname(), False))
    for z in board.Zones():
        if z.GetIsRuleArea() or not z.IsOnLayer(layer):
            continue
        fl = z.GetFilledPolysList(layer)
        for k in range(fl.OutlineCount()):
            o = fl.Outline(k)
            from shapely.geometry import Polygon

            pts = [(mm(o.CPoint(i).x), mm(o.CPoint(i).y)) for i in range(o.PointCount())]
            if len(pts) >= 3:
                out.append((Polygon(pts).buffer(0), z.GetNetname(), True))
    return out


def add_test_points(board, tps, load_fp, clearance, outline, keepouts=(), pitch=2.54, edge_mm=1.0, via=(0.6, 0.3),
                width=0.25, reach=15.0, grid=0.5, tries=40, pour_ok=False, avoid=None, avoid_mm=3.0):
    """第 159 轮 159e：给板上没有测试点的网络补底面 ICT 测试点（板子已经布好线，不重新布）。
    tps = [(位号, 网络, 封装)]。每个测试点：在这个网络的铜附近找一处底面空地放焊盘（离别的网络按要求间距、离别的测试点
    至少 pitch、离板边 edge_mm），旁边打一个过孔、底面一小段线连到焊盘，再在顶层按网格（maze）从过孔接到这个网络。
    avoid：不放的地方（形状，板上坐标；离它至少 avoid_mm），例如发热件周围——
    高压网络的过孔穿过地平面要挖一大圈，那里的铜少了板温就高。
    pour_ok：底面焊盘和那段线可以放进别的网络（非高压）的铺铜里（铺铜重填时让开），给周围全是铺铜的网络用。
    找不到地方的列出来，不硬放。返回 ({位号: (板上 x, y)}, [放不下的位号])。纯几何计算。"""
    from shapely.geometry import LineString, Point
    from shapely.strtree import STRtree

    mm = pcbnew.ToMM
    lays = {pcbnew.F_Cu: "F", pcbnew.In2_Cu: "In2", pcbnew.B_Cu: "B"}
    placed, failed = {}, []
    taken = []
    for fp in board.GetFootprints():
        if fp.GetLayer() == pcbnew.B_Cu and fp.GetReference().startswith("TP"):
            taken.append((mm(fp.GetPosition().x), mm(fp.GetPosition().y)))
    inner = outline.buffer(-edge_mm)
    kos_all = [kp for kp, _ls in keepouts]
    for ref, net, fpid in tps:
        cu = {L: _copper(board, L) for L in lays}
        trees = {L: STRtree([g for g, _n, _z in cu[L]]) for L in lays}

        def free(geom, L, need, _cu=cu, _trees=trees, _net=net):
            for k in _trees[L].query(geom.buffer(need + 3.0)):
                g, n, z = _cu[L][k]
                if n == _net or (z and pour_ok and L == pcbnew.B_Cu and clearance(_net, n) <= 0.3):
                    continue
                if g.distance(geom) < clearance(_net, n) + need:
                    return False
            return True

        mine = [g for g, n, _z in cu[pcbnew.F_Cu] if n == net]
        if not mine:
            failed.append(ref)
            continue
        from shapely.ops import unary_union

        home = unary_union(mine)
        x0, y0, x1, y1 = home.buffer(reach).bounds
        cands = []
        x = x0
        while x <= x1:
            y = y0
            while y <= y1:
                p = Point(round(x / grid) * grid, round(y / grid) * grid)
                d = home.distance(p)
                if d <= reach and inner.contains(p):
                    cands.append((d, p.x, p.y))
                y += grid
            x += grid
        cands.sort()
        ok = False
        tried = 0
        for _d, tx, ty in cands:
            t = Point(tx, ty)
            if any((tx - a) ** 2 + (ty - b) ** 2 < pitch**2 for a, b in taken):
                continue
            near = avoid is not None and avoid.distance(t) < avoid_mm
            if near or any(kp.distance(t) < 0.5 + 0.1 for kp in kos_all):
                continue
            if not free(t.buffer(0.5), pcbnew.B_Cu, 0.0):
                continue
            for k in range(8):
                import math

                for r in (1.3, 1.8):
                    vx, vy = tx + r * math.cos(k * math.pi / 4), ty + r * math.sin(k * math.pi / 4)
                    v = Point(vx, vy)
                    if not inner.contains(v) or any(kp.distance(v) < via[0] / 2 + 0.1 for kp in kos_all) or (
                            avoid is not None and avoid.distance(v) < avoid_mm):
                        continue
                    if not all(free(v.buffer(via[0] / 2), L, 0.0) for L in lays):
                        continue
                    leg = LineString([(tx, ty), (vx, vy)]).buffer(width / 2)
                    if not free(leg, pcbnew.B_Cu, 0.0):
                        continue
                    tried += 1
                    # 先只放过孔、按网格从顶层接；接上了再放焊盘和底面那段线（接不上只拿掉过孔：
                    # 从板上拿掉封装在 KiCad 7 的 Python 接口里会弄坏后面的读封装，第一次试跑在第 41 次时报错）
                    vi = _via(board, net, (vx, vy), via)
                    zk = [(g.buffer(clearance(net, n)), {L}) for L in (pcbnew.F_Cu,) for g, n, _z in cu[L]
                          if n != net and g.geom_type in ("Polygon", "MultiPolygon") and g.area > 4.0]
                    r_ = maze(board, net, None, clearance, width, ["F.Cu"], outline, list(keepouts) + zk, lock=True)
                    if r_ is None:
                        board.Remove(vi)
                        continue
                    _drop_tp(board, ref, net, fpid, load_fp, (tx, ty), (vx, vy), width)
                    placed[ref] = (tx, ty)
                    taken.append((tx, ty))
                    ok = True
                    break
                if ok or tried > tries:
                    break
            if ok or tried > tries:
                break
        if not ok:
            failed.append(ref)
    return placed, failed


def _via(board, net, v, via):
    mm = pcbnew.FromMM
    vi = pcbnew.PCB_VIA(board)
    vi.SetPosition(pcbnew.VECTOR2I(mm(v[0]), mm(v[1])))
    vi.SetWidth(mm(via[0]))
    vi.SetDrill(mm(via[1]))
    vi.SetNet(board.FindNet(net))
    vi.SetLocked(True)
    board.Add(vi)
    return vi


def _drop_tp(board, ref, net, fpid, load_fp, t, v, width):
    """放测试点焊盘（底面）和焊盘到过孔的一小段底面线"""
    mm = pcbnew.FromMM
    ni = board.FindNet(net)
    fp = load_fp(fpid)
    fp.SetReference(ref)
    fp.SetValue(net)
    board.Add(fp)
    fp.SetPosition(pcbnew.VECTOR2I(mm(t[0]), mm(t[1])))
    fp.Flip(fp.GetPosition(), False)
    fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_BOM)
    for pad in fp.Pads():
        pad.SetNet(ni)
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(pcbnew.VECTOR2I(mm(t[0]), mm(t[1])))
    tr.SetEnd(pcbnew.VECTOR2I(mm(v[0]), mm(v[1])))
    tr.SetWidth(mm(width))
    tr.SetLayer(pcbnew.B_Cu)
    tr.SetNet(ni)
    tr.SetLocked(True)
    board.Add(tr)
