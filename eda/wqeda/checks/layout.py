# -*- coding: utf-8 -*-
"""布局约束（第 111 轮 P4）：设计描述板子层 constraints 里写的五种约束，按板子上的焊盘和器件外框量，纯计算。

    loop    功率回路：回路上的焊盘围成的面积（凸包）不超过限值——面积越大，寄生电感越大，开关尖峰越高
    kelvin  开尔文采样：采样线经网络连接点（net tie）从采样电阻焊盘上单独引出，不和功率电流共用一段铜
    near    靠近：去耦电容的焊盘到芯片电源脚的距离不超过限值
    apart   远离：发热件和怕热件的器件外框之间不小于限值
    edge    接插件在板边：器件外框到板边不超过限值

限值是设计规则，出处写在约束的 source 里（没有出处的写“示例值”）。需要网络和焊盘编号，光绘那条路判“未知”。"""

from __future__ import annotations

from shapely.geometry import MultiPoint

from .basic import EPS, FAIL, PASS, UNKNOWN

WHY = {
    "loop": "开关电流走的回路面积越大，寄生电感越大，开关时的电压尖峰和电磁干扰越大",
    "kelvin": "采样电阻只有毫欧级，功率电流在共用的那段铜上的压降会混进采样信号；采样线要从电阻焊盘上单独引出",
    "near": "去耦电容离芯片电源脚越远，中间走线的电感越大，高频电流就供不上",
    "apart": "电解电容、晶振、采样运放怕热；靠近发热件，寿命变短、参数漂移",
    "edge": "接插件要从板边插拔线缆；放在板子中间，线缆会压到别的器件",
}
NAMES = {"loop": "功率回路面积", "kelvin": "开尔文采样", "near": "靠近", "apart": "远离", "edge": "接插件在板边"}


def _pads(board, ref, num=None):
    return [f for f in board.features if f.kind in ("pad", "pth") and f.ref == ref and (num is None or f.pad == num)]


def _res(c, status, value=None, limit=None, unit="", detail="", at=None):
    return {
        "key": "L-" + c["key"],
        "name": "{}：{}".format(NAMES[c["kind"]], c.get("name") or c["key"]),
        "status": status,
        "why": WHY[c["kind"]],
        "value": value,
        "limit": limit,
        "unit": unit,
        "at": at or [],
        "count": len(at or []),
        "detail": detail,
        "source": c.get("source", ""),
    }


def loop(board, c):
    pts = [f.geom.centroid for r in c["refs"] for f in _pads(board, r) if f.net in c["nets"]]
    if len(pts) < 3:
        return _res(c, UNKNOWN, detail="回路上的焊盘不到三个（位号或网络对不上）")
    area = MultiPoint(pts).convex_hull.area
    lim = c["max_area_mm2"]
    ok = area <= lim + EPS
    p = MultiPoint(pts).convex_hull.centroid
    return _res(
        c,
        PASS if ok else FAIL,
        round(area, 1),
        lim,
        "mm²",
        "{} 的 {} 焊盘中心围成的凸包".format("、".join(c["refs"]), "、".join(c["nets"])),
        None if ok else [[round(p.x, 2), round(p.y, 2), "回路面积 {:.0f} mm²".format(area)]],
    )


def kelvin(board, c):
    res = _pads(board, c["ref"])
    if not res:
        return _res(c, UNKNOWN, detail="板子上没有 {}".format(c["ref"]))
    bad, ok = [], []
    for tie in c["ties"]:
        tp = _pads(board, tie)
        hit = [(t, r) for t in tp for r in res if t.net == r.net and t.layer == r.layer and t.geom.intersects(r.geom)]
        if hit:
            ok.append("{} 在 {} 第 {} 脚上".format(tie, c["ref"], hit[0][1].pad))
        else:
            where = tp[0].geom.centroid if tp else None
            bad.append(
                ([round(where.x, 2), round(where.y, 2)] if where else [])
                + ["{} 没有落在 {} 的焊盘上".format(tie, c["ref"])]
            )
    return _res(c, FAIL if bad else PASS, len(ok), len(c["ties"]), "个", "；".join(ok), bad)


def near(board, c):
    target = _pads(board, c["to"], str(c["pin"]))
    if not target:
        return _res(c, UNKNOWN, detail="板子上没有 {} 第 {} 脚".format(c["to"], c["pin"]))
    net = target[0].net
    mine = [f for f in _pads(board, c["ref"]) if f.net == net]
    if not mine:
        return _res(c, UNKNOWN, detail="{} 没有焊盘接在 {} 上".format(c["ref"], net))
    d, a = min((a.geom.distance(b.geom), a) for a in mine for b in target)
    lim = c["max_mm"]
    ok = d <= lim + EPS
    p = a.geom.centroid
    return _res(
        c,
        PASS if ok else FAIL,
        round(d, 2),
        lim,
        "mm",
        "{} 的 {} 焊盘到 {} 第 {} 脚（焊盘边到边）".format(c["ref"], net, c["to"], c["pin"]),
        None
        if ok
        else [[round(p.x, 2), round(p.y, 2), "{} 离 {} 第 {} 脚 {:.1f} mm".format(c["ref"], c["to"], c["pin"], d)]],
    )


def apart(board, c):
    cy = board.courtyards
    miss = [r for r in c["hot"] + c["cold"] if r not in cy]
    if miss:
        return _res(c, UNKNOWN, detail="没有器件外框：" + "、".join(miss))
    best, pair = None, None
    for h in c["hot"]:
        for k in c["cold"]:
            d = cy[h][1].distance(cy[k][1])
            if best is None or d < best:
                best, pair = d, (h, k)
    lim = c["min_mm"]
    ok = best >= lim - EPS
    p = cy[pair[1]][1].centroid
    return _res(
        c,
        PASS if ok else FAIL,
        round(best, 2),
        lim,
        "mm",
        "最近的一对：{} 和 {}（器件外框边到边）".format(*pair),
        None if ok else [[round(p.x, 2), round(p.y, 2), "{} 离 {} {:.1f} mm".format(pair[1], pair[0], best)]],
    )


def edge(board, c):
    cy = board.courtyards
    if board.outline_geom is None:
        return _res(c, UNKNOWN, detail="没有板框")
    rim = board.outline_geom.boundary
    bad, worst = [], 0.0
    for r in c["refs"]:
        if r not in cy:
            bad.append([r, "没有器件外框"])
            continue
        d = cy[r][1].distance(rim)
        worst = max(worst, d)
        if d > c["max_mm"] + EPS:
            p = cy[r][1].centroid
            bad.append([round(p.x, 2), round(p.y, 2), "{} 离板边 {:.1f} mm".format(r, d)])
    return _res(c, FAIL if bad else PASS, round(worst, 2), c["max_mm"], "mm", "器件外框到板边，最远的一个", bad)


RULES = {"loop": loop, "kelvin": kelvin, "near": near, "apart": apart, "edge": edge}


def run(board, design):
    """design = expand() 的结果；没有约束返回空表"""
    out = []
    for c in (design or {}).get("constraints") or []:
        if not board.has_nets:
            out.append(_res(c, UNKNOWN, detail="板子模型里没有网络和焊盘编号（光绘那条路查不了布局约束）"))
        else:
            out.append(RULES[c["kind"]](board, c))
    return out
