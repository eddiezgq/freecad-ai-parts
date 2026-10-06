# -*- coding: utf-8 -*-
"""数控编程刀路（第 13 轮 C1、C2）：数控车（端面、分层粗车、精车轮廓、切槽）与 2.5 轴铣（槽 / 键槽、型腔、外轮廓、钻孔）。

刀路先表示成“动作表”，再由 cam_post.py 写成 G 代码。每个函数都尽量直白，便于学生对照 G 代码读懂。

车削坐标（FANUC 习惯）：X 是直径（mm），Z 沿轴线，Z0 在本次装夹的右端面（精加工后的端面），向左（卡盘方向）为负。
  轮廓 profile：[(z, d), …]，z 从 0 递减，d 为该处直径；轴肩是同一 z 上的两个点。
铣削坐标：工件坐标系 G54，XY 在工件上表面，Z0 为上表面，向下为负。

动作 move：{"t": "rapid" | "feed" | "drill" | "tool" | "spindle" | "comment", …}
  rapid / feed：x, y（铣）, z；feed 带 f（车削 mm/r，铣削 mm/min）
  drill：x, y, z（孔底）, r（R 平面）, q（啄钻每次深度，0 = 一次钻到底）, f
  tool：n（刀号）、name；spindle：css（恒线速 m/min）或 rpm、max_rpm
"""
import math

import numpy as np

CLEAR = 2.0            # 车削：离开工件端面 / 外圆的安全距离（mm）


# ---------------------------------------------------------------- 车削轮廓
def design_profile(segments, chamfer=0.0):
    """阶梯轴 [(直径, 长度), …]（从左到右）→ 设计轮廓 [(t, d), …]，t 从左端 0 起向右；两端倒角 chamfer"""
    pts, t = [], 0.0
    n = len(segments)
    for k, (d, l) in enumerate(segments):
        if k == 0 and chamfer > 0:
            pts += [(0.0, d - 2 * chamfer), (chamfer, d)]
        else:
            pts.append((t, d))
        t += l
        if k == n - 1 and chamfer > 0:
            pts += [(t - chamfer, d), (t, d - 2 * chamfer)]
        else:
            pts.append((t, d))
    return simplify(pts)


def plateau(prof):
    """最大直径那一段的 [t 起, t 止]"""
    dmax = max(d for _, d in prof)
    ts = [t for t, d in prof if abs(d - dmax) < 1e-9]
    return min(ts), max(ts), dmax


def setup_profile(prof, side="right"):
    """设计轮廓 → 一次装夹要车的轮廓 [(z, d), …]（Z0 在本次装夹的右端面，向左为负）。
    外圆车刀只能从右往左车到最大直径段：side="right" 车右端到最大直径段（含）；
    "left" 是调头后车原来的左边，车到最大直径的轴肩为止。返回 (轮廓, 本次车到的长度)"""
    L = prof[-1][0]
    tA, tB, dmax = plateau(prof)
    if side == "right":
        pts = [(t - L, d) for t, d in reversed(prof) if t > tA + 1e-9 or (t >= tA - 1e-9 and abs(d - dmax) < 1e-9)]
        return simplify(pts), L - tA
    pts = [(-t + 0.0, d) for t, d in prof if t < tA - 1e-9 or (t <= tA + 1e-9 and d < dmax - 1e-9)]
    if not pts or tA < 1e-9:
        return [], 0.0
    if abs(pts[-1][1] - dmax) > 1e-9:
        pts.append((-tA, dmax))
    return simplify(pts), tA


def shaft_profile(segments, chamfer=0.0, side="right"):
    """阶梯轴一次装夹的轮廓（只在右端倒角时与旧接口一致）：返回 (轮廓, 本次车到的长度, 总长)"""
    prof = design_profile(segments, chamfer)
    pts, Lreg = setup_profile(prof, side)
    return pts, Lreg, prof[-1][0]


def d_at(profile, z):
    """轮廓在 z 处的直径（轴肩处取较大的一边，偏安全）"""
    best = None
    for (z0, d0), (z1, d1) in zip(profile, profile[1:]):
        if min(z0, z1) - 1e-9 <= z <= max(z0, z1) + 1e-9:
            d = d0 if abs(z1 - z0) < 1e-12 else d0 + (d1 - d0) * (z - z0) / (z1 - z0)
            if abs(z1 - z0) < 1e-12:
                d = max(d0, d1)
            best = d if best is None else max(best, d)
    if best is None:                                   # 超出轮廓两端：取最近一端的直径
        lo = min(profile, key=lambda p: p[0])
        hi = max(profile, key=lambda p: p[0])
        return lo[1] if z < lo[0] else hi[1]
    return best


def with_allowance(profile, radial=0.0, axial=0.0):
    """留余量的轮廓：直径加 2×径向余量；朝右的轴肩（向左直径变大）向右让出轴向余量"""
    pts = [list(p) for p in profile]
    for i in range(len(pts) - 1):
        (za, da), (zb, db) = pts[i], pts[i + 1]
        if abs(za - zb) < 1e-12 and db > da and za < -1e-9:
            nz = min(za + axial, 0.0)
            pts[i][0] = pts[i + 1][0] = nz
    return simplify([(z, d + 2 * radial) for z, d in pts])


def simplify(pts, tol=1e-6):
    """去掉重复点和共线的中间点"""
    out = [tuple(pts[0])]
    for p in pts[1:]:
        p = tuple(p)
        if abs(p[0] - out[-1][0]) < 1e-12 and abs(p[1] - out[-1][1]) < 1e-12:
            continue
        if len(out) >= 2:
            (z0, d0), (z1, d1) = out[-2], out[-1]
            if abs((z1 - z0) * (p[1] - d0) - (d1 - d0) * (p[0] - z0)) < tol:
                out[-1] = p
                continue
        out.append(p)
    return out


def z_reach(prof, d):
    """从右往左沿轮廓走，第一次碰到直径 ≥ d 的位置（粗车每层车到这里为止）；整段都比 d 小则返回轮廓左端"""
    if prof[0][1] >= d - 1e-9:
        return prof[0][0]
    for (z0, d0), (z1, d1) in zip(prof, prof[1:]):
        if d1 >= d - 1e-9:
            if abs(d1 - d0) < 1e-12:
                return z1
            return z0 + (z1 - z0) * (d - d0) / (d1 - d0)
    return prof[-1][0]


# ---------------------------------------------------------------- 车削刀路
def turn_face(stock_d, face_allow, ap, f):
    """车端面：毛坯右端比成品多 face_allow，分层车到 Z0；每层从外圆外进刀车过中心，再退回"""
    mv = [{"t": "comment", "text": "车端面 Facing（余量 {:g}）".format(face_allow)}]
    n = max(1, math.ceil(face_allow / ap - 1e-9)) if face_allow > 0 else 1
    xo = stock_d + 2 * CLEAR
    for k in range(n):
        z = max(0.0, face_allow - (k + 1) * ap)
        mv += [{"t": "rapid", "x": xo, "z": z + CLEAR},
               {"t": "rapid", "x": xo, "z": z},
               {"t": "feed", "x": -1.0, "z": z, "f": f},
               {"t": "rapid", "x": -1.0, "z": z + CLEAR},
               {"t": "rapid", "x": xo, "z": z + CLEAR}]
    return mv


def turn_rough(profile, stock_d, ap, f, allow_r=0.3, allow_z=0.1, profile_pass=True):
    """分层粗车（相当于 FANUC G71，展开成直线段便于读懂）：
    每层直径减 2×ap，从端面外向左车到碰到“留余量的轮廓”为止，45° 退刀、快移回右边；
    最后沿留余量的轮廓走一刀，去掉分层留下的小台阶"""
    tgt = with_allowance(profile, allow_r, allow_z)
    dmin = min(d for _, d in tgt)
    mv = [{"t": "comment", "text": "分层粗车 Rough turning（每层 ap={:g}，留余量 径向 {:g} 轴向 {:g}）".format(ap, allow_r, allow_z)}]
    d = stock_d
    while d > dmin + 1e-6:
        d_new = max(d - 2 * ap, dmin)
        zstop = z_reach(tgt, d_new + 1e-6)
        if zstop < -1e-6:
            mv += [{"t": "rapid", "x": d_new, "z": CLEAR},
                   {"t": "feed", "x": d_new, "z": zstop, "f": f},
                   {"t": "feed", "x": d_new + 1.0, "z": zstop + 0.5, "f": f},
                   {"t": "rapid", "x": d_new + 1.0, "z": CLEAR}]
        d = d_new
    if profile_pass:
        mv.append({"t": "comment", "text": "沿留余量的轮廓走一刀，去掉分层留下的台阶"})
        mv += _follow(tgt, f, stock_d)
    return mv


def _follow(prof, f, stock_d):
    """沿轮廓从右往左走一刀：在端面外对准起点直径，进给切入，走完沿径向退出到外圆外"""
    z0, d0 = prof[0]
    xo = max(stock_d, max(d for _, d in prof)) + 2 * CLEAR
    mv = [{"t": "rapid", "x": d0, "z": CLEAR},
          {"t": "feed", "x": d0, "z": z0, "f": f}]
    mv += [{"t": "feed", "x": d, "z": z, "f": f} for z, d in prof[1:]]
    zl = prof[-1][0]
    mv += [{"t": "feed", "x": xo, "z": zl, "f": f},
           {"t": "rapid", "x": xo, "z": CLEAR}]
    return mv


def turn_finish(profile, stock_d, f):
    """精车轮廓：沿本工序尺寸的轮廓一刀走完（含倒角、轴肩）"""
    return [{"t": "comment", "text": "精车轮廓 Finish profile"}] + _follow(simplify(profile), f, stock_d)


def turn_groove(z, d_bottom, width, d_from, f, tool_width):
    """切槽：z 是槽右侧位置，刀宽 tool_width（刀位点在刀的右刀尖）；槽宽于刀时多刀并排，每刀重叠 20%"""
    if width < tool_width - 1e-9:
        raise ValueError("槽宽 {:g} 小于刀宽 {:g}".format(width, tool_width))
    mv = [{"t": "comment", "text": "切槽 Grooving：Z{:g} 槽宽 {:g} 槽底 Ø{:g}，刀宽 {:g}".format(z, width, d_bottom, tool_width)}]
    span = width - tool_width
    n = 1 if span < 1e-9 else math.ceil(span / (0.8 * tool_width) - 1e-9) + 1
    for k in range(n):
        zk = z - (span * k / (n - 1) if n > 1 else 0.0)
        mv += [{"t": "rapid", "x": d_from + 2 * CLEAR, "z": zk},
               {"t": "feed", "x": d_bottom, "z": zk, "f": f},
               {"t": "rapid", "x": d_from + 2 * CLEAR, "z": zk}]
    return mv


# ---------------------------------------------------------------- 2.5 轴铣削
def mill_slot(a, b, width, depth, tool_d, step_down, f, f_plunge, safe=5.0):
    """直槽 / 键槽（a、b 为两端圆心）：每层从 a 斜线下刀到 b，再回 a 把中线铣到底；
    槽宽大于刀径时，再沿槽边（刀心偏置）绕一圈"""
    from shapely.geometry import LineString
    if width < tool_d - 1e-9:
        raise ValueError("槽宽 {:g} 小于刀具直径 {:g}".format(width, tool_d))
    off = (width - tool_d) / 2
    ring = None
    if off > 1e-6:
        ring = list(LineString([tuple(a), tuple(b)]).buffer(off, quad_segs=16).exterior.coords)
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣槽 Slot：宽 {:g} 深 {:g}，刀具 Ø{:g}，分 {} 层".format(width, depth, tool_d, layers)},
          {"t": "rapid", "x": a[0], "y": a[1], "z": safe}, {"t": "rapid", "x": a[0], "y": a[1], "z": 0.5}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv.append({"t": "feed", "x": b[0], "y": b[1], "z": z1, "f": f_plunge})      # 斜线下刀
        mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
        if ring:
            mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in ring]
            mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
    mv.append({"t": "rapid", "x": a[0], "y": a[1], "z": safe})
    return mv


def _ring_coords(geom):
    from shapely.geometry import MultiPolygon, Polygon
    polys = [geom] if isinstance(geom, Polygon) else list(geom.geoms) if isinstance(geom, MultiPolygon) else []
    out = []
    for p in polys:
        if p.is_empty:
            continue
        out.append(list(p.exterior.coords))
        out += [list(i.coords) for i in p.interiors]
    return out


def _ramp(ring, z_from, z_to, length, f):
    """沿环的前一段路一边走一边下刀（斜线下刀，刀具不垂直扎进材料）"""
    mv, acc = [], 0.0
    for (xa, ya), (xb, yb) in zip(ring, ring[1:]):
        acc += math.hypot(xb - xa, yb - ya)
        t = min(acc / length, 1.0) if length > 1e-9 else 1.0
        mv.append({"t": "feed", "x": xb, "y": yb, "z": z_from + (z_to - z_from) * t, "f": f})
        if t >= 1.0:
            break
    return mv


def mill_pocket(polygon, depth, tool_d, stepover, step_down, f, f_plunge, safe=5.0):
    """型腔（可带岛）：每层从里往外按刀心偏置环一圈圈铣，最外一圈贴着型腔壁；
    每层在最里面一环斜线下刀；两环之间如果直线连过去会碰到岛或型腔壁，就抬刀再下"""
    from shapely.geometry import LineString, Polygon
    poly = polygon if isinstance(polygon, Polygon) else Polygon(polygon)
    room = poly.buffer(-tool_d / 2, join_style=1)
    if room.is_empty:
        raise ValueError("型腔太窄，Ø{:g} 的刀放不进去".format(tool_d))
    levels, g = [], room
    while not g.is_empty:
        levels.append(_ring_coords(g))
        g = g.buffer(-stepover * tool_d, join_style=1)
    rings = [r for lv in levels[::-1] for r in lv]                  # 从里往外
    ok = room.buffer(1e-3)
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣型腔 Pocket：深 {:g}，刀具 Ø{:g}，行距 {:g} 倍刀径，分 {} 层".format(depth, tool_d, stepover, layers)}]
    for k in range(layers):
        z0, z1 = -depth * k / layers, -depth * (k + 1) / layers
        first = rings[0]
        x0, y0 = first[0]
        mv += [{"t": "rapid", "x": x0, "y": y0, "z": safe}, {"t": "rapid", "x": x0, "y": y0, "z": z0 + 0.5}]
        mv += _ramp(first, z0 + 0.5, z1, max(3 * tool_d, 1.0), f_plunge)
        mv.append({"t": "feed", "x": x0, "y": y0, "z": z1, "f": f})
        for ring in rings:
            px, py = mv[-1]["x"], mv[-1]["y"]
            x, y = ring[0]
            if math.hypot(x - px, y - py) > 1e-9:
                if LineString([(px, py), (x, y)]).within(ok):
                    mv.append({"t": "feed", "x": x, "y": y, "z": z1, "f": f})
                else:
                    # 抬到工件上表面以上再平移（不能贴着上一层平移：中间可能有岛），快移落到上一层深度上方，再进给下刀
                    mv += [{"t": "rapid", "x": px, "y": py, "z": 1.0}, {"t": "rapid", "x": x, "y": y, "z": 1.0},
                           {"t": "rapid", "x": x, "y": y, "z": z0 + 0.5}, {"t": "feed", "x": x, "y": y, "z": z1, "f": f_plunge}]
            mv += [{"t": "feed", "x": xx, "y": yy, "z": z1, "f": f} for xx, yy in ring[1:]]
        mv.append({"t": "rapid", "x": mv[-1]["x"], "y": mv[-1]["y"], "z": safe})
    return mv


def mill_contour(polygon, depth, tool_d, step_down, f, safe=5.0):
    """外轮廓：刀心在轮廓外偏一个刀具半径，顺铣（主轴正转、沿顺时针绕工件），分层；
    从第一条边中点的外法线方向直线切入、切出"""
    from shapely.geometry import Polygon
    from shapely.geometry.polygon import orient
    poly = polygon if isinstance(polygon, Polygon) else Polygon(polygon)
    path = orient(poly.buffer(tool_d / 2, join_style=1, quad_segs=16), sign=-1.0)       # 顺时针
    ring = list(path.exterior.coords)[:-1]
    # 从最长的一段中点开始
    i = max(range(len(ring)), key=lambda k: math.dist(ring[k], ring[(k + 1) % len(ring)]))
    pa, pb = ring[i], ring[(i + 1) % len(ring)]
    start = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    seq = [start] + ring[i + 1:] + ring[:i + 1] + [start]
    t = np.array(pb) - np.array(pa)
    t = t / max(np.linalg.norm(t), 1e-12)
    nrm = np.array([-t[1], t[0]])                 # 顺时针环：左侧是外面
    lead = np.array(start) + nrm * tool_d
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": "铣外轮廓 Contour：深 {:g}，刀具 Ø{:g}，顺铣，分 {} 层".format(depth, tool_d, layers)}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv += [{"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": 0.5},
               {"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f / 2}]
        mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in seq]
        mv += [{"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}]
    return mv


def drill(points, depth, peck, f, r_plane=2.0, safe=5.0):
    mv = [{"t": "comment", "text": "钻孔 Drilling：{} 个孔，深 {:g}{}".format(len(points), depth, "，啄钻每次 {:g}".format(peck) if peck else "")}]
    for x, y in points:
        mv.append({"t": "drill", "x": x, "y": y, "z": -depth, "r": r_plane, "q": peck, "f": f, "safe": safe})
    return mv


# ---------------------------------------------------------------- 切削参数
def spindle_rpm(vc_m_min, d_mm, max_rpm):
    """n = 1000·vc / (π·D)，不超过机床最高转速"""
    return min(1000 * vc_m_min / (math.pi * max(d_mm, 1e-6)), max_rpm)


def mill_feed(fz, z_teeth, rpm):
    """铣削进给速度 F = fz·z·n（mm/min）"""
    return fz * z_teeth * rpm
