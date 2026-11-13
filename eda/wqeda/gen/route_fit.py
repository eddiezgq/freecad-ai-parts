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
    return len(made)


def drop_dangling(board):
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
        if t.GetClass() == "PCB_VIA" or not t.IsLocked():
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


def widen(board, targets, clearance):
    """targets = {网络名: 目标线宽 mm}；clearance(网络 A, 网络 B) → 要求间距 mm。
    每段线按“离别的网络的铜还有多远”加宽，最多到目标线宽；别的网络若也要加宽，按它加宽后的宽度算（偏保守）。
    返回 (加宽到目标的段数, 只加宽一部分的段数, 没动的段数)"""
    from shapely import STRtree
    from shapely.geometry import LineString, Point

    layers = {}

    def add(layer, net, geom, grow=0.0):
        layers.setdefault(layer, []).append((net, geom.buffer(grow) if grow else geom))

    for fp in board.GetFootprints():
        for p in fp.Pads():
            g = _poly(p.GetEffectivePolygon())
            for lid in p.GetLayerSet().CuStack():
                add(lid, p.GetNetname(), g)
    segs = []
    for t in board.GetTracks():
        lid, net = t.GetLayer(), t.GetNetname()
        if t.GetClass() == "PCB_VIA":
            g = Point(pcbnew.ToMM(t.GetPosition().x), pcbnew.ToMM(t.GetPosition().y)).buffer(
                pcbnew.ToMM(t.GetWidth()) / 2
            )
            for l2 in t.GetLayerSet().CuStack():
                add(l2, net, g)
            continue
        line = LineString(
            [
                (pcbnew.ToMM(t.GetStart().x), pcbnew.ToMM(t.GetStart().y)),
                (pcbnew.ToMM(t.GetEnd().x), pcbnew.ToMM(t.GetEnd().y)),
            ]
        )
        w = pcbnew.ToMM(t.GetWidth())
        add(lid, net, line.buffer(max(w, targets.get(net, w)) / 2))
        if net in targets and targets[net] > w + 1e-6:
            segs.append((t, line, w))
    for z in board.Zones():
        if z.GetIsRuleArea() or not z.GetNetname():
            continue
        for lid in z.GetLayerSet().CuStack():
            fill = z.GetFilledPolysList(lid)
            for i in range(fill.OutlineCount()):
                o = fill.Outline(i)
                from shapely.geometry import Polygon

                pg = Polygon([(pcbnew.ToMM(o.CPoint(k).x), pcbnew.ToMM(o.CPoint(k).y)) for k in range(o.PointCount())])
                if pg.is_valid and not pg.is_empty:
                    add(lid, z.GetNetname(), pg)
    trees = {lid: (STRtree([g for _, g in v]), v) for lid, v in layers.items()}
    full = part = none = 0
    for t, line, w in segs:
        net, goal = t.GetNetname(), targets[t.GetNetname()]
        tree, items = trees[t.GetLayer()]
        half = goal / 2
        for i in tree.query(line.buffer(goal / 2 + 6.0)):
            onet, g = items[int(i)]
            if onet == net:
                continue
            half = min(half, line.distance(g) - clearance(net, onet))
        nw = max(w, min(goal, int(2 * half / STEP + 1e-9) * STEP))
        if nw >= goal - 1e-6:
            full += 1
        elif nw > w + 1e-6:
            part += 1
        else:
            none += 1
        t.SetWidth(pcbnew.FromMM(round(nw, 2)))
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
                        for onet, olay, og, oref, _c in its if ok else ():
                            if onet == net or lid[ln] not in olay:
                                continue
                            need = 0.15 if (oref in refs) else clearance(net, onet)
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
