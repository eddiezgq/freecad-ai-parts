# -*- coding: utf-8 -*-
"""第一批六项检查（第 102 轮 P1）：只看板子模型和工厂工艺能力表，纯计算——不联网、不调 AI、不读数据库。
结果三种：pass 通过、fail 不通过、unknown 未知（缺数据或工厂没填能力，不判通过）。规则和“为什么”沿用第 88 轮 dfm.py。

    D1 物料清单与坐标的位号一一对上    D2 物料清单的数量 = 位号个数    D4 坐标的正反面与焊盘所在面一致
    F1 最小线宽                        F3 最小孔径、最小孔环           F5 铜到板边"""
from __future__ import annotations

import math

from ..schema.capability import value as cap_value

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
EPS = 1e-6
PAD_SEARCH_MM = 8.0     # D4：坐标点周围多大范围内找焊盘（检查程序的搜索范围，不是工艺能力）
MAX_AT = 20             # 每项最多列出的位置

WHY = {
    "refs": "物料清单和坐标文件是两份文件，位号对不上，贴片机就会漏贴、多贴或贴错料",
    "qty": "数量和位号个数不一致，备料、报价都会错",
    "side": "坐标写在顶面，焊盘却在底面（或反过来），贴片编程会放错面",
    "track": "板厂蚀刻能做到的最细线宽；再细就会断线",
    "drill": "钻头越细越容易断、孔壁镀铜越难；孔环太窄，钻偏一点就破环",
    "edge": "板边要铣外形、过轨道夹持；铜离边太近会被铣到、露铜",
}


def _r(key, name, status, why, value=None, limit=None, unit="", at=None, detail=""):
    return {"key": key, "name": name, "status": status, "why": WHY[why], "value": value, "limit": limit, "unit": unit,
            "at": (at or [])[:MAX_AT], "count": len(at or []), "detail": detail}


def _unknown_cap(key, name, why, cap_key, unit="mm"):
    return _r(key, name, UNKNOWN, why, unit=unit, detail="工艺能力表没填“{}”".format(cap_key))


def d1_refs(board):
    if not board.bom or not board.components:
        miss = "物料清单" if not board.bom else "坐标"
        return _r("D1", "物料清单与坐标位号对上", UNKNOWN, "refs", detail="没有{}，没法对".format(miss))
    bom = [r for row in board.bom for r in row.refs]
    cpl = [c.ref for c in board.components]
    dup_b = sorted({r for r in bom if bom.count(r) > 1})
    dup_c = sorted({r for r in cpl if cpl.count(r) > 1})
    only_b = sorted(set(bom) - set(cpl))
    only_c = sorted(set(cpl) - set(bom))
    at = [[r, "只在物料清单里"] for r in only_b] + [[r, "只在坐标里"] for r in only_c]
    at += [[r, "物料清单里重复"] for r in dup_b] + [[r, "坐标里重复"] for r in dup_c]
    ok = not at
    return _r("D1", "物料清单与坐标位号对上", PASS if ok else FAIL, "refs", len(set(bom) & set(cpl)),
              len(set(bom) | set(cpl)), "个位号", at, "" if ok else "{} 处对不上".format(len(at)))


def d2_qty(board):
    if not board.bom:
        return _r("D2", "数量等于位号个数", UNKNOWN, "qty", detail="没有物料清单")
    bad = [[" ".join(row.refs[:3]) + (" …" if len(row.refs) > 3 else ""),
            "写 {}，位号 {} 个".format(row.qty, len(row.refs))]
           for row in board.bom if row.qty is not None and row.qty != len(row.refs)]
    none = sum(1 for row in board.bom if row.qty is None)
    status = FAIL if bad else (UNKNOWN if none else PASS)
    return _r("D2", "数量等于位号个数", status, "qty", len(board.bom) - len(bad) - none, len(board.bom), "行", bad,
              "{} 行没写数量".format(none) if none else "")


def d4_side(board, search=PAD_SEARCH_MM):
    if not board.components:
        return _r("D4", "坐标正反面与焊盘一致", UNKNOWN, "side", detail="没有坐标")
    bad, lost = [], []
    for c in board.components:
        near = {p.side for p in board.pads if math.hypot(p.x - c.x, p.y - c.y) <= search}
        here = c.side in near or "FB" in near
        if here:
            continue
        if near:
            bad.append([round(c.x, 2), round(c.y, 2), "{} 写在{}面，附近的焊盘在{}面".format(
                c.ref, "顶" if c.side == "F" else "底", "顶" if "F" in near else "底")])
        else:
            lost.append([round(c.x, 2), round(c.y, 2), c.ref])
    status = FAIL if bad else (UNKNOWN if lost else PASS)
    detail = "{} 个坐标附近 {:g} mm 内没有焊盘，判不了".format(len(lost), search) if lost else ""
    return _r("D4", "坐标正反面与焊盘一致", status, "side", len(board.components) - len(bad) - len(lost),
              len(board.components), "个", bad + lost, detail)


def f1_track(board, cap):
    lim = cap_value(cap, "track_min_mm")
    if lim is None:
        return _unknown_cap("F1", "最小线宽", "track", "最小线宽")
    if not board.tracks:
        return _r("F1", "最小线宽", PASS, "track", None, lim, "mm", detail="没有走线")
    wmin = min(t.width for t in board.tracks)
    bad = [[round(t.x1, 2), round(t.y1, 2), t.layer, t.width] for t in board.tracks if t.width < lim - EPS]
    return _r("F1", "最小线宽", FAIL if bad else PASS, "track", round(wmin, 3), lim, "mm", bad)


def f3_holes(board, cap):
    out = []
    dlim, rlim = cap_value(cap, "drill_min_mm"), cap_value(cap, "annular_min_mm")
    if dlim is None:
        out.append(_unknown_cap("F3-drill", "最小孔径", "drill", "最小孔径"))
    elif not board.holes:
        out.append(_r("F3-drill", "最小孔径", PASS, "drill", None, dlim, "mm", detail="没有钻孔"))
    else:
        bad = [[round(h.x, 2), round(h.y, 2), h.ref or h.kind or "孔", h.drill]
               for h in board.holes if h.drill < dlim - EPS]
        dmin = round(min(h.drill for h in board.holes), 3)
        out.append(_r("F3-drill", "最小孔径", FAIL if bad else PASS, "drill", dmin, dlim, "mm", bad))
    plated = [h for h in board.holes if h.plated]
    if rlim is None:
        out.append(_unknown_cap("F3-ring", "最小孔环", "drill", "最小孔环"))
    else:
        known = [h for h in plated if h.ring is not None]
        lost = len(plated) - len(known)
        bad = [[round(h.x, 2), round(h.y, 2), h.ref or h.kind or "孔", h.ring] for h in known if h.ring < rlim - EPS]
        status = FAIL if bad else (UNKNOWN if lost else PASS)
        out.append(_r("F3-ring", "最小孔环", status, "drill", round(min(h.ring for h in known), 3) if known else None,
                      rlim, "mm", bad, "{} 个孔在外层找不到焊盘，孔环判不了".format(lost) if lost else ""))
    return out


def f5_copper_edge(board, cap):
    lim = cap_value(cap, "copper_edge_min_mm")
    if lim is None:
        return _unknown_cap("F5", "铜到板边", "edge", "铜到板边最小距离")
    if board.outline is None:
        return _r("F5", "铜到板边", UNKNOWN, "edge", limit=lim, unit="mm", detail="没有板框")
    X0, Y0, X1, Y1 = board.outline
    dist = [(min(c.x0 - X0, X1 - c.x1, c.y0 - Y0, Y1 - c.y1), c) for c in board.copper]
    if not dist:
        return _r("F5", "铜到板边", PASS, "edge", None, lim, "mm", detail="没有铜")
    bad = [[round((c.x0 + c.x1) / 2, 2), round((c.y0 + c.y1) / 2, 2), c.layer, round(d, 3)]
           for d, c in dist if d < lim - EPS]
    return _r("F5", "铜到板边", FAIL if bad else PASS, "edge", round(min(d for d, _ in dist), 3), lim, "mm", bad)


def run(board, cap):
    """跑全部六项，返回 {"checks": [...], "status": 总结论, "notes": 读入时的情况}"""
    checks = [d1_refs(board), d2_qty(board), d4_side(board), f1_track(board, cap)] + f3_holes(board, cap) + [
        f5_copper_edge(board, cap)]
    st = {c["status"] for c in checks}
    return {"source": board.source, "factory": cap.get("factory"), "checks": checks, "notes": list(board.notes),
            "status": FAIL if FAIL in st else (UNKNOWN if UNKNOWN in st else PASS)}
