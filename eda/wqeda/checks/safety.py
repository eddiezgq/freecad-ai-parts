# -*- coding: utf-8 -*-
"""安全距离（第 159 轮 159d2b，平缝机控制器 CTRL-LS）：网络分组之间的最小铜间距，和规则文件里的电气间隙、爬电距离比。

规则是设计数据（细则第 159 轮第二节第 3 条）：哪些网络算一组、两组之间要多少 mm，写在设计旁边的 safety.yaml 里，
数是示例值时规则上标 example: true，结果里如实写“示例值”；企业按自己的安规表填。纯计算：只读板子模型（readers.kicad），
不联网、不调 AI。

量法：同一铜层上两组铜（焊盘、走线、过孔、铺铜）之间的直线最短距离；通孔焊盘和过孔各层都算。
- 电气间隙：就是这个直线距离（铜面上方没有遮挡时的空气距离）。
- 爬电距离：沿板面的路径不会比直线短，直线够了爬电一定够（偏保守）；开槽能加长爬电，本版不算开槽。
- 内层之间隔着板材（固体绝缘），实际要求通常更低；本版内层也按同一规则查（偏保守）。
- 同一个器件自己的焊盘之间不算（引脚间距是器件自己的事，按它规格书的额定；例如功率模块的自举脚和输入脚）。
- 跨在两组之间的器件（两组网络都有它的焊盘，例如隔离电源、数字隔离器、功率模块），最近点落在它的器件外框里面时也不算：
  那一段是器件引脚自己的间距，由器件的隔离额定管（隔离额定另在计算书里核对）。"""

from __future__ import annotations

from .basic import EPS, FAIL, PASS, UNKNOWN

COPPER = ("pad", "pth", "track", "via", "zone")


def groups_of(rules, nets):
    """规则里的分组 → {组名: 网络集合}；"rest" 表示“不在其他任何组里的网络”"""
    out, named = {}, set()
    for name, members in rules["groups"].items():
        if members != "rest":
            out[name] = set(members) & set(nets)
            named |= out[name]
    for name, members in rules["groups"].items():
        if members == "rest":
            out[name] = set(nets) - named
    return out


def _feats(board, nets):
    return [f for f in board.features if f.kind in COPPER and f.net in nets]


def _bridges(board):
    """{位号: 它焊盘上的网络集合}"""
    out = {}
    for f in board.features:
        if f.kind in ("pad", "pth") and f.ref and f.net:
            out.setdefault(f.ref, set()).add(f.net)
    return out


def _inside_bridge(board, bridges, pt, na, nb):
    from shapely.geometry import Point

    for ref, nets in bridges.items():
        if na in nets and nb in nets and ref in board.courtyards and board.courtyards[ref][1].contains(Point(pt)):
            return True
    return False


def _nearest(fa, fb, window, board=None, bridges=None):
    """两组铜之间的最短距离（同层；同一器件自己的焊盘之间不算）：(距离, 位置)"""
    from shapely import STRtree
    from shapely.ops import nearest_points

    best, where = None, None
    by_layer = {}
    for f in fb:
        by_layer.setdefault(f.layer, []).append(f)
    trees = {k: (STRtree([f.geom for f in v]), v) for k, v in by_layer.items()}
    for f in fa:
        if f.layer not in trees:
            continue
        tree, items = trees[f.layer]
        for i in tree.query(f.geom.buffer(window)):
            g = items[int(i)]
            if f.ref and f.ref == g.ref and f.kind in ("pad", "pth") and g.kind in ("pad", "pth"):
                continue
            d = f.geom.distance(g.geom)
            if best is None or d < best:
                p, q = nearest_points(f.geom, g.geom)
                if bridges and _inside_bridge(board, bridges, ((p.x + q.x) / 2, (p.y + q.y) / 2), f.net, g.net):
                    continue
                best, where = (
                    d,
                    [
                        round((p.x + q.x) / 2, 2),
                        round(-(p.y + q.y) / 2, 2),
                        f.layer,
                        "{} {}{} ↔ {} {}{}".format(
                            f.kind, f.net, " " + f.ref if f.ref else "", g.kind, g.net, " " + g.ref if g.ref else ""
                        ),
                    ],
                )
    return best, where


def run(board, rules):
    if not board.has_nets:
        return [{"key": "S-nets", "name": "安全距离", "status": UNKNOWN, "detail": "板子没有网络信息（光绘），量不了"}]
    nets = {f.net for f in board.features if f.net}
    g = groups_of(rules, nets)
    out = []
    for r in rules["rules"]:
        a = set().union(*(g[x] for x in r["a"]))
        b = set().union(*(g[x] for x in r["b"]))
        need = max(r["clearance_mm"], r["creepage_mm"])
        best, where = _nearest(_feats(board, a), _feats(board, b), need + 1.0, board, _bridges(board))
        if best is None:
            st, best_txt = PASS, None
            detail = "两组铜在同一层上都隔着 {:g} mm 以上".format(need + 1.0)
        else:
            st = PASS if best >= need - EPS else FAIL
            detail = "最近 {:.2f} mm（{} 层，{}）".format(best, where[2], where[3])
            best_txt = round(best, 3)
        out.append(
            {
                "key": "S-" + r["key"],
                "name": "安全距离：" + r["name"],
                "status": st,
                "value": best_txt,
                "limit": need,
                "unit": "mm",
                "at": [where] if where else [],
                "detail": detail,
                "rule": "电气间隙 ≥ {:g} mm、爬电距离 ≥ {:g} mm（直线距离量，偏保守）".format(
                    r["clearance_mm"], r["creepage_mm"]
                ),
                "insulation": r.get("insulation", ""),
                "example": bool(r.get("example")),
                "source": r.get("source", ""),
                "groups": [sorted(a), sorted(b)],
            }
        )
    return out
