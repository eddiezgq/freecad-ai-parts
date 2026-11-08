# -*- coding: utf-8 -*-
"""工艺检查补齐（第 111 轮 P4）：把第 88 轮驱动板脚本 dfm.py 的其余规则搬进统一检查引擎，只读板子模型，纯计算。

    F2 最小线距（铜到铜）      F4 最小阻焊桥          F6 器件外框不重叠      F7 极性元件方向统一
    F8 器件到板边              T1 ICT 测试点覆盖率    C1 大电流走线宽度（IPC-2221）

门槛分两种来源：工厂做得到什么（工艺能力表：F2、F4、F8），设计自己要什么（设计描述板子层的 rules、stackup：T1、C1）。
板子模型里没有的信息（光绘里没有器件外框、没有网络），这一项判“未知”，不判通过。"""

from __future__ import annotations

from .. import geom as G
from ..schema.capability import value as cap_value
from .basic import EPS, FAIL, PASS, UNKNOWN, _r, _unknown_cap
from .basic import WHY as _WHY

_WHY.update(
    {
        "space": "板厂蚀刻能做到的最小线距；两块不相连的铜靠得比这还近，蚀刻不开就短路",
        "mask": "相邻焊盘之间要留一条阻焊（阻焊桥），否则回流焊时锡会连成桥",
        "spacing": "贴片机吸嘴、AOI 视角、返修烙铁都要空间；器件外框（courtyard）不能重叠",
        "polarity": "极性元件（二极管、电解电容）方向统一，贴片编程和 AOI 判反向都简单，人工目检也不容易看错",
        "edge_part": "板边要铣外形、过轨道夹持；元件离边太近会被铣到或卡轨道",
        "ict": "在线测试（ICT）用针床扎测试点；网络上没有能扎的点，这个网络就测不到",
        "current": "按 IPC-2221 由电流算线宽：线太窄会过热",
    }
)
SEARCH_MM = 1.0  # 量间距时看多远以内的邻居（只影响“最小值”报到多少，不影响判定）
POLAR_LIBS = ("Device:D", "Device:C_Polarized", "Device:LED")
TP_LIBS = ("Connector:TestPoint",)
COPPER = ("F", "In1", "In2", "In3", "In4", "B")


def _xy(g):
    c = g.representative_point()
    return [round(c.x, 2), round(c.y, 2)]


def _gaps(features, layers, limit):
    """每层把形状并成连通块，量不同块之间的最小距离；返回 (最小距离, [违规位置])"""
    dmin, bad = None, []
    for lay in layers:
        isl = G.islands([f.geom for f in features if f.layer == lay])
        for d, i, j in G.close_pairs(isl, max(SEARCH_MM, limit)):
            dmin = d if dmin is None else min(dmin, d)
            if d < limit - EPS:
                a, b = isl[i], isl[j]
                p = a.boundary.interpolate(a.boundary.project(b.centroid))
                bad.append([round(p.x, 2), round(p.y, 2), lay, round(d, 3)])
    return dmin, bad


def f2_space(board, cap):
    lim = cap_value(cap, "space_min_mm")
    if lim is None:
        return _unknown_cap("F2", "最小线距（铜到铜）", "space", "最小线距")
    if not board.features:
        return _r("F2", "最小线距（铜到铜）", UNKNOWN, "space", limit=lim, unit="mm", detail="板子模型里没有铜的形状")
    dmin, bad = _gaps(board.features, COPPER, lim)
    detail = "" if dmin is not None else "{:g} mm 以内没有两块不相连的铜".format(SEARCH_MM)
    return _r(
        "F2",
        "最小线距（铜到铜）",
        FAIL if bad else PASS,
        "space",
        None if dmin is None else round(dmin, 3),
        lim,
        "mm",
        bad,
        detail,
    )


def f4_mask(board, cap):
    lim = cap_value(cap, "mask_bridge_min_mm")
    if lim is None:
        return _unknown_cap("F4", "最小阻焊桥", "mask", "最小阻焊桥")
    if not any(f.kind == "opening" for f in board.features):
        return _r("F4", "最小阻焊桥", UNKNOWN, "mask", limit=lim, unit="mm", detail="没有阻焊层")
    dmin, bad = _gaps(board.features, ("F.Mask", "B.Mask"), lim)
    return _r(
        "F4",
        "最小阻焊桥",
        FAIL if bad else PASS,
        "mask",
        None if dmin is None else round(dmin, 3),
        lim,
        "mm",
        bad,
        "相邻开窗之间的阻焊宽度；开窗连在一起的地方不算桥",
    )


def _placed(board):
    """贴片厂要贴的器件：在坐标里的（安装孔、网络连接点不贴，不算）"""
    refs = {c.ref for c in board.components}
    return {r: v for r, v in board.courtyards.items() if r in refs}


def f6_overlap(board):
    cy = _placed(board)
    if not cy:
        return _r("F6", "器件外框不重叠", UNKNOWN, "spacing", detail="板子模型里没有器件外框（光绘里没有这一层）")
    refs = sorted(cy)
    bad = []
    for i, a in enumerate(refs):
        sa, ga = cy[a]
        for b in refs[i + 1 :]:
            sb, gb = cy[b]
            if sa == sb and ga.intersects(gb) and ga.intersection(gb).area > 1e-4:
                bad.append(_xy(ga.intersection(gb)) + ["{} / {}".format(a, b)])
    return _r(
        "F6", "器件外框不重叠", FAIL if bad else PASS, "spacing", len(bad), 0, "处", bad, "{} 个器件".format(len(refs))
    )


def f8_part_edge(board, cap):
    lim = cap_value(cap, "component_edge_min_mm")
    if lim is None:
        return _unknown_cap("F8", "器件到板边", "edge_part", "元件到板边最小距离")
    cy = _placed(board)
    if not cy or board.outline_geom is None:
        what = "器件外框" if not cy else "板框"
        return _r("F8", "器件到板边", UNKNOWN, "edge_part", limit=lim, unit="mm", detail="板子模型里没有" + what)
    edge = board.outline_geom.boundary
    dist = {r: g.distance(edge) if board.outline_geom.contains(g) else 0.0 for r, (_, g) in cy.items()}
    bad = [_xy(cy[r][1]) + [r, round(d, 2)] for r, d in sorted(dist.items()) if d < lim - EPS]
    return _r("F8", "器件到板边", FAIL if bad else PASS, "edge_part", round(min(dist.values()), 2), lim, "mm", bad)


def f7_polarity(board, design):
    """二极管、电解电容只用 0° 一族和 90° 一族（不能有转 180°、270° 的）：同一个方向贴，AOI 一套程序"""
    if design is None:
        return _r("F7", "极性元件方向统一", UNKNOWN, "polarity", detail="没有设计描述，不知道哪些是极性元件")
    if not board.components:
        return _r("F7", "极性元件方向统一", UNKNOWN, "polarity", detail="没有坐标")
    pol = [q["ref"] for q in design["parts"] if q["lib"].startswith(POLAR_LIBS) and q.get("item")]
    rot = {c.ref: c for c in board.components}
    lost = [r for r in pol if r not in rot]
    bad = []
    for r in pol:
        c = rot.get(r)
        if c is not None and int(round(c.rot)) % 360 in (180, 270):
            bad.append([round(c.x, 2), round(c.y, 2), "{} 转 {}°".format(r, int(round(c.rot)) % 360)])
    status = FAIL if bad else (UNKNOWN if lost else PASS)
    return _r(
        "F7",
        "极性元件方向统一",
        status,
        "polarity",
        len(pol) - len(bad) - len(lost),
        len(pol),
        "个",
        bad,
        "二极管、电解电容 {} 个".format(len(pol)) + ("；坐标里没有 {}".format("、".join(lost)) if lost else ""),
    )


def t1_ict(board, design):
    lim = ((design or {}).get("rules") or {}).get("ict_coverage_min")
    if lim is None:
        return _r(
            "T1",
            "ICT 测试点覆盖率",
            UNKNOWN,
            "ict",
            detail="设计描述没写 ICT 覆盖率要求（board.rules.ict_coverage_min）",
        )
    if not board.has_nets:
        return _r("T1", "ICT 测试点覆盖率", UNKNOWN, "ict", limit=lim, detail="板子模型里没有网络（光绘不带网表）")
    tps = {q["ref"] for q in design["parts"] if q["lib"].startswith(TP_LIBS)}
    access = {}
    for f in board.features:
        if not f.net or f.net.startswith("unconnected") or f.kind in ("zone", "opening"):
            continue
        ok = f.kind in ("pth", "via") or (f.kind == "pad" and f.layer == "B" and f.ref in tps)
        access[f.net] = access.get(f.net, False) or ok
    miss = sorted(n for n, ok in access.items() if not ok)
    cov = (len(access) - len(miss)) / max(1, len(access))
    return _r(
        "T1",
        "ICT 测试点覆盖率",
        PASS if cov >= lim - 1e-9 else FAIL,
        "ict",
        round(cov, 3),
        lim,
        "",
        [],
        "扎不到的网络：" + "、".join(miss) if miss else "每个网络都扎得到（通孔焊盘、底面测试点或过孔）",
    )


def ipc2221_width_mm(i_a, dt_c, oz, outer=True):
    """IPC-2221：I = k·ΔT^0.44·A^0.725（A 单位 mil²；外层 k = 0.048、内层 0.024）→ 线宽 mm（1 oz = 1.378 mil）"""
    k = 0.048 if outer else 0.024
    area = (i_a / (k * dt_c**0.44)) ** (1 / 0.725)
    return area / (1.378 * oz) * 0.0254


def _wide_path(board, net, pads, need):
    """只用够宽的走线、过孔、焊盘、铺铜，net 上这些功率焊盘是否连成一片。need = {层: 最小线宽}"""
    items = []
    for i, f in enumerate(board.features):
        if f.net != net or f.kind == "opening":
            continue
        if f.kind == "track" and f.width + EPS < need.get(f.layer, 0):
            continue
        items.append(((f.layer, i), f))
    group = G.connected([(k, f.geom) for k, f in items])
    parent = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            a = parent[a]
        return a

    def union(a, b):
        parent[find(a)] = find(b)

    for (lay, i), f in items:
        union(("g", lay, group[(lay, i)]), ("f", i))
        if f.kind in ("via", "pth", "pad"):  # 过孔、通孔焊盘把各层连起来；同一器件同一网络的焊盘器件内部相连
            union(("f", i), ("id", f.ref))
    want = []
    for ref, num in pads:
        hit = [("f", i) for (_, i), f in items if f.ref == ref and f.pad == num]
        if not hit:
            return False, "{} 第 {} 脚不在 {} 上".format(ref, num, net)
        want.append(hit[0])
    roots = {find(k) for k in want}
    return len(roots) == 1, ""


def c1_current(board, design):
    name = "大电流走线宽度"
    if design is None or not design.get("high_current"):
        return _r("C1", name, UNKNOWN, "current", detail="设计描述没写大电流网络")
    st, ru = design.get("stackup") or {}, design.get("rules") or {}
    miss = [
        k
        for k, v in (
            ("外层铜厚", st.get("outer_oz")),
            ("内层铜厚", st.get("inner_oz")),
            ("允许温升", ru.get("trace_dt_c")),
        )
        if v is None
    ]
    if miss:
        return _r("C1", name, UNKNOWN, "current", detail="设计描述没写：" + "、".join(miss))
    if not board.has_nets:
        return _r("C1", name, UNKNOWN, "current", detail="板子模型里没有网络（光绘不带网表）")
    dt, rows, bad = ru["trace_dt_c"], [], []
    for net, amps in design["high_current"].items():
        pads = design.get("power_pads", {}).get(net)
        if not pads:
            continue  # 地走内层平面、没列功率焊盘的网络不查
        need_o = ipc2221_width_mm(amps, dt, st["outer_oz"], True)
        need_i = ipc2221_width_mm(amps, dt, st["inner_oz"], False)
        need = {lay: (need_o if lay in ("F", "B") else need_i) for lay in COPPER}
        ok, why = _wide_path(board, net, pads, need)
        src = (design.get("high_current_src") or {}).get(net)
        rows.append(
            (
                ok,
                "{} {:g} A{}：外层 ≥ {:.2f} mm、内层 ≥ {:.2f} mm，功率路径{}".format(
                    net,
                    amps,
                    "（跟着规格 {}）".format(src[5:]) if isinstance(src, str) else "",
                    need_o,
                    need_i,
                    "连通" if ok else "有一段不够宽" + ("：" + why if why else ""),
                ),
            )
        )
        if not ok:
            bad.append([net, round(need_o, 2)])
    if not rows:
        return _r("C1", name, UNKNOWN, "current", detail="大电流网络都没列功率焊盘（board.power_pads）")
    return _r(
        "C1",
        name,
        FAIL if bad else PASS,
        "current",
        len(rows) - len(bad),
        len(rows),
        "条网络",
        bad,
        # 有不通过的只列不通过的网络，其余一句带过（起草台上看得清）
        "；".join(t for ok, t in rows if not ok or not bad)
        + ("；其余 {} 条网络连通".format(len(rows) - len(bad)) if bad and len(rows) > len(bad) else "")
        + "。IPC-2221，外层 {:g} oz、内层 {:g} oz，温升 {:g} ℃".format(st["outer_oz"], st["inner_oz"], dt),
    )


def run(board, cap, design=None):
    """七项工艺检查。design = expand() 的结果（极性、测试点、大电流要用；没有就判未知）"""
    return [
        f2_space(board, cap),
        f4_mask(board, cap),
        f6_overlap(board),
        f7_polarity(board, design),
        f8_part_edge(board, cap),
        t1_ict(board, design),
        c1_current(board, design),
    ]
