"""刀路（ADR-0059，M11 第二步）：数控车（端面、分层粗车、精车轮廓、切槽）与 2.5 轴铣（键槽 / 直槽、矩形型腔、矩形外轮廓、钻孔）。
搬自问渠数字工厂第 13 轮 cae/cam.py；铣削的偏置改为直接按矩形、长圆计算，不依赖 shapely。

刀路先表示成“动作表”，再由 post.py 写成 G 代码。
车削坐标（FANUC 习惯）：X 是直径（mm），Z 沿轴线，Z0 在本次装夹的右端面，向左（卡盘方向）为负。
  轮廓 profile：[(z, d), …]，z 从 0 递减，d 为该处直径；轴肩是同一 z 上的两个点。
铣削坐标：工件坐标系 G54，XY 在工件上表面，Z0 为上表面，向下为负。
动作 move：{"t": "rapid" | "feed" | "drill" | "comment", …}
  rapid / feed：x, y（铣）, z；feed 带 f（车削 mm/r，铣削 mm/min）
  drill：x, y, z（孔底）, r（R 平面）, q（啄钻每次深度，0 = 一次钻到底）, f
"""

from __future__ import annotations

import itertools
import math

CLEAR = 2.0  # 车削：离开工件端面 / 外圆的安全距离（mm）


class CamError(ValueError):
    pass


# ---------------------------------------------------------------- 车削轮廓
def simplify(pts, tol=1e-6):
    """去掉重复点和共线的中间点。"""
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


def design_profile(segments, chamfer=0.0):
    """阶梯轴 [(直径, 长度), …]（从左到右）→ 设计轮廓 [(t, d), …]，t 从左端 0 起向右；两端倒角 chamfer。"""
    if not segments:
        raise CamError("阶梯轴至少一段")
    if any(d <= 0 or seg_len <= 0 for d, seg_len in segments):
        raise CamError("每段直径、长度都要大于 0")
    if chamfer and chamfer * 2 >= min(segments[0][0], segments[-1][0]):
        raise CamError("倒角太大")
    pts, t = [], 0.0
    n = len(segments)
    for k, (d, seg_len) in enumerate(segments):
        if k == 0 and chamfer > 0:
            pts += [(0.0, d - 2 * chamfer), (chamfer, d)]
        else:
            pts.append((t, d))
        t += seg_len
        if k == n - 1 and chamfer > 0:
            pts += [(t - chamfer, d), (t, d - 2 * chamfer)]
        else:
            pts.append((t, d))
    return simplify(pts)


def plateau(prof):
    """最大直径那一段的 (t 起, t 止, 直径)。"""
    dmax = max(d for _, d in prof)
    ts = [t for t, d in prof if abs(d - dmax) < 1e-9]
    return min(ts), max(ts), dmax


def setup_profile(prof, side="right"):
    """设计轮廓 → 一次装夹要车的轮廓 [(z, d), …]（Z0 在本次装夹的右端面，向左为负）。外圆车刀只能从右往左车到最大直径段：
    side="right" 车右端到最大直径段（含）；"left" 是调头后车原来的左边，车到最大直径的轴肩为止。返回 (轮廓, 本次车到的长度)。"""
    length = prof[-1][0]
    ta, _, dmax = plateau(prof)
    if side == "right":
        pts = [(t - length, d) for t, d in reversed(prof) if t > ta + 1e-9 or (t >= ta - 1e-9 and abs(d - dmax) < 1e-9)]
        return simplify(pts), length - ta
    pts = [(-t + 0.0, d) for t, d in prof if t < ta - 1e-9 or (t <= ta + 1e-9 and d < dmax - 1e-9)]
    if not pts or ta < 1e-9:
        return [], 0.0
    if abs(pts[-1][1] - dmax) > 1e-9:
        pts.append((-ta, dmax))
    return simplify(pts), ta


def d_at(profile, z):
    """轮廓在 z 处的直径（轴肩处取较大的一边，偏安全）。"""
    best = None
    for (z0, d0), (z1, d1) in itertools.pairwise(profile):
        if min(z0, z1) - 1e-9 <= z <= max(z0, z1) + 1e-9:
            d = max(d0, d1) if abs(z1 - z0) < 1e-12 else d0 + (d1 - d0) * (z - z0) / (z1 - z0)
            best = d if best is None else max(best, d)
    if best is None:
        lo = min(profile, key=lambda p: p[0])
        hi = max(profile, key=lambda p: p[0])
        return lo[1] if z < lo[0] else hi[1]
    return best


def with_allowance(profile, radial=0.0, axial=0.0):
    """留余量的轮廓：直径加 2×径向余量；朝右的轴肩（向左直径变大）向右让出轴向余量。"""
    pts = [list(p) for p in profile]
    for i in range(len(pts) - 1):
        (za, da), (zb, db) = pts[i], pts[i + 1]
        if abs(za - zb) < 1e-12 and db > da and za < -1e-9:
            nz = min(za + axial, 0.0)
            pts[i][0] = pts[i + 1][0] = nz
    return simplify([(z, d + 2 * radial) for z, d in pts])


def z_reach(prof, d):
    """从右往左沿轮廓走，第一次碰到直径 ≥ d 的位置（粗车每层车到这里为止）。"""
    if prof[0][1] >= d - 1e-9:
        return prof[0][0]
    for (z0, d0), (z1, d1) in itertools.pairwise(prof):
        if d1 >= d - 1e-9:
            if abs(d1 - d0) < 1e-12:
                return z1
            return z0 + (z1 - z0) * (d - d0) / (d1 - d0)
    return prof[-1][0]


# ---------------------------------------------------------------- 车削刀路
def turn_face(stock_d, face_allow, ap, f):
    """车端面：毛坯右端比成品多 face_allow，分层车到 Z0。"""
    mv = [{"t": "comment", "text": f"车端面（余量 {face_allow:g}）"}]
    n = max(1, math.ceil(face_allow / ap - 1e-9)) if face_allow > 0 else 1
    xo = stock_d + 2 * CLEAR
    for k in range(n):
        z = max(0.0, face_allow - (k + 1) * ap)
        mv += [{"t": "rapid", "x": xo, "z": z + CLEAR}, {"t": "rapid", "x": xo, "z": z},
               {"t": "feed", "x": -1.0, "z": z, "f": f}, {"t": "rapid", "x": -1.0, "z": z + CLEAR},
               {"t": "rapid", "x": xo, "z": z + CLEAR}]
    return mv


def _follow(prof, f, stock_d):
    z0, d0 = prof[0]
    xo = max(stock_d, max(d for _, d in prof)) + 2 * CLEAR
    mv = [{"t": "rapid", "x": d0, "z": CLEAR}, {"t": "feed", "x": d0, "z": z0, "f": f}]
    mv += [{"t": "feed", "x": d, "z": z, "f": f} for z, d in prof[1:]]
    zl = prof[-1][0]
    mv += [{"t": "feed", "x": xo, "z": zl, "f": f}, {"t": "rapid", "x": xo, "z": CLEAR}]
    return mv


def turn_rough(profile, stock_d, ap, f, allow_r=0.3, allow_z=0.1):
    """分层粗车（相当于 FANUC G71，展开成直线段）：每层直径减 2×ap，车到碰到留余量的轮廓为止；最后沿留余量的轮廓走一刀。"""
    tgt = with_allowance(profile, allow_r, allow_z)
    dmin = min(d for _, d in tgt)
    mv = [{"t": "comment", "text": f"分层粗车（每层 ap={ap:g}，留余量 径向 {allow_r:g} 轴向 {allow_z:g}）"}]
    d = stock_d
    while d > dmin + 1e-6:
        d_new = max(d - 2 * ap, dmin)
        zstop = z_reach(tgt, d_new + 1e-6)
        if zstop < -1e-6:
            mv += [{"t": "rapid", "x": d_new, "z": CLEAR}, {"t": "feed", "x": d_new, "z": zstop, "f": f},
                   {"t": "feed", "x": d_new + 1.0, "z": zstop + 0.5, "f": f}, {"t": "rapid", "x": d_new + 1.0, "z": CLEAR}]
        d = d_new
    mv.append({"t": "comment", "text": "沿留余量的轮廓走一刀"})
    return mv + _follow(tgt, f, stock_d)


def turn_finish(profile, stock_d, f):
    return [{"t": "comment", "text": "精车轮廓"}, *_follow(simplify(profile), f, stock_d)]


def turn_groove(z, d_bottom, width, d_from, f, tool_width):
    """切槽：z 是槽右侧位置，刀位点在刀的右刀尖；槽宽于刀时多刀并排，每刀重叠 20%。"""
    if width < tool_width - 1e-9:
        raise CamError(f"槽宽 {width:g} 小于刀宽 {tool_width:g}")
    mv = [{"t": "comment", "text": f"切槽：Z{z:g} 槽宽 {width:g} 槽底 Ø{d_bottom:g}，刀宽 {tool_width:g}"}]
    span = width - tool_width
    n = 1 if span < 1e-9 else math.ceil(span / (0.8 * tool_width) - 1e-9) + 1
    for k in range(n):
        zk = z - (span * k / (n - 1) if n > 1 else 0.0)
        mv += [{"t": "rapid", "x": d_from + 2 * CLEAR, "z": zk}, {"t": "feed", "x": d_bottom, "z": zk, "f": f},
               {"t": "rapid", "x": d_from + 2 * CLEAR, "z": zk}]
    return mv


# ---------------------------------------------------------------- 2.5 轴铣削（矩形、长圆）
def rounded_rect(x0, y0, x1, y1, r, ccw=True, seg_deg=10.0):
    """圆角矩形的顶点（r = 0 为尖角矩形），逆时针或顺时针；首尾不重复。"""
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        raise CamError("矩形尺寸要大于 0")
    r = max(0.0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    if r < 1e-9:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        pts = []
        n = max(1, math.ceil(90 / seg_deg))
        for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
            pts += [(cx + r * math.cos(math.radians(a0 + 90 * k / n)), cy + r * math.sin(math.radians(a0 + 90 * k / n)))
                    for k in range(n + 1)]
    return pts if ccw else pts[::-1]


def stadium(a, b, r, seg_deg=10.0):
    """长圆（两端半圆、中线 a→b、半径 r）的顶点，逆时针。"""
    ax, ay = a
    bx, by = b
    ang = math.atan2(by - ay, bx - ax)
    n = max(2, math.ceil(180 / seg_deg))
    pts = [(bx + r * math.cos(ang - math.pi / 2 + math.pi * k / n), by + r * math.sin(ang - math.pi / 2 + math.pi * k / n))
           for k in range(n + 1)]
    pts += [(ax + r * math.cos(ang + math.pi / 2 + math.pi * k / n), ay + r * math.sin(ang + math.pi / 2 + math.pi * k / n))
            for k in range(n + 1)]
    return pts


def mill_slot(a, b, width, depth, tool_d, step_down, f, f_plunge, safe=5.0):
    """直槽 / 键槽（a、b 为两端圆心）：每层从 a 斜线下刀到 b，再回 a；槽宽大于刀径时再沿槽边（刀心偏置）绕一圈。"""
    if width < tool_d - 1e-9:
        raise CamError(f"槽宽 {width:g} 小于刀具直径 {tool_d:g}")
    off = (width - tool_d) / 2
    ring = stadium(a, b, off) if off > 1e-6 else None
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": f"铣槽：宽 {width:g} 深 {depth:g}，刀具 Ø{tool_d:g}，分 {layers} 层"},
          {"t": "rapid", "x": a[0], "y": a[1], "z": safe}, {"t": "rapid", "x": a[0], "y": a[1], "z": 0.5}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv.append({"t": "feed", "x": b[0], "y": b[1], "z": z1, "f": f_plunge})
        mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
        if ring:
            mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in [*ring, ring[0]]]
            mv.append({"t": "feed", "x": a[0], "y": a[1], "z": z1, "f": f})
    mv.append({"t": "rapid", "x": a[0], "y": a[1], "z": safe})
    return mv


def mill_pocket(rect, corner_r, depth, tool_d, stepover, step_down, f, f_plunge, safe=5.0):
    """矩形型腔（圆角 corner_r）：刀心可走的区域是向内偏一个刀具半径的矩形；每层从中心斜线下刀，由里往外一圈圈铣，
    最外一圈贴着型腔壁。刀具半径大于转角圆角时转角会留料（检查里报残留）。"""
    x0, y0, x1, y1 = rect
    rt = tool_d / 2
    ix0, iy0, ix1, iy1 = x0 + rt, y0 + rt, x1 - rt, y1 - rt
    if ix1 < ix0 - 1e-9 or iy1 < iy0 - 1e-9:
        raise CamError(f"型腔太窄，Ø{tool_d:g} 的刀放不进去")
    step = stepover * tool_d
    rings = []
    k = 0
    while True:
        off = k * step
        rx0, ry0, rx1, ry1 = ix0 + off, iy0 + off, ix1 - off, iy1 - off
        if rx1 - rx0 < 1e-6 or ry1 - ry0 < 1e-6:
            cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
            if rx1 - rx0 > -2 * step or ry1 - ry0 > -2 * step:  # 剩一条中线
                hx = max(0.0, (ix1 - ix0) / 2 - off)
                hy = max(0.0, (iy1 - iy0) / 2 - off)
                rings.append([(cx - hx, cy - hy), (cx + hx, cy + hy)])
            break
        r_off = max(0.0, corner_r - rt - off)
        rings.append(rounded_rect(rx0, ry0, rx1, ry1, r_off))
        k += 1
    rings = rings[::-1]  # 由里往外
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": f"铣型腔：深 {depth:g}，刀具 Ø{tool_d:g}，行距 {stepover:g} 倍刀径，分 {layers} 层"}]
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    for k in range(layers):
        z0, z1 = -depth * k / layers, -depth * (k + 1) / layers
        mv += [{"t": "rapid", "x": cx, "y": cy, "z": safe}, {"t": "rapid", "x": cx, "y": cy, "z": z0 + 0.5}]
        # 中心一小段来回斜线下刀
        ramp = min(3 * tool_d, max(ix1 - ix0, iy1 - iy0) / 2)
        if ix1 - ix0 >= iy1 - iy0:
            mv += [{"t": "feed", "x": cx + ramp / 2, "y": cy, "z": (z0 + z1) / 2, "f": f_plunge},
                   {"t": "feed", "x": cx, "y": cy, "z": z1, "f": f_plunge}]
        else:
            mv += [{"t": "feed", "x": cx, "y": cy + ramp / 2, "z": (z0 + z1) / 2, "f": f_plunge},
                   {"t": "feed", "x": cx, "y": cy, "z": z1, "f": f_plunge}]
        for ring in rings:  # 环都是同心的、在刀心可走区域内，直线连过去不会碰壁
            pts = [*ring, ring[0]] if len(ring) > 2 else ring
            mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in pts]
        mv.append({"t": "rapid", "x": mv[-1]["x"], "y": mv[-1]["y"], "z": safe})
    return mv


def mill_contour(rect, corner_r, depth, tool_d, step_down, f, safe=5.0):
    """矩形外轮廓（圆角 corner_r）：刀心在轮廓外偏一个刀具半径，顺铣（沿顺时针绕工件），分层；从下边中点外侧切入、切出。"""
    x0, y0, x1, y1 = rect
    rt = tool_d / 2
    ring = rounded_rect(x0 - rt, y0 - rt, x1 + rt, y1 + rt, corner_r + rt, ccw=False)
    start = ((x0 + x1) / 2, y0 - rt)
    k = min(range(len(ring)), key=lambda i: math.dist(ring[i], start))
    seq = [start, *ring[k:], *ring[:k], start]
    lead = (start[0], start[1] - tool_d)
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    mv = [{"t": "comment", "text": f"铣外轮廓：深 {depth:g}，刀具 Ø{tool_d:g}，顺铣，分 {layers} 层"}]
    for k in range(layers):
        z1 = -depth * (k + 1) / layers
        mv += [{"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": 0.5},
               {"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f / 2}]
        mv += [{"t": "feed", "x": x, "y": y, "z": z1, "f": f} for x, y in seq]
        mv += [{"t": "feed", "x": lead[0], "y": lead[1], "z": z1, "f": f}, {"t": "rapid", "x": lead[0], "y": lead[1], "z": safe}]
    return mv


def drill(points, depth, peck, f, r_plane=2.0, safe=5.0):
    mv = [{"t": "comment", "text": f"钻孔：{len(points)} 个孔，深 {depth:g}" + (f"，啄钻每次 {peck:g}" if peck else "")}]
    for x, y in points:
        mv.append({"t": "drill", "x": x, "y": y, "z": -depth, "r": r_plane, "q": peck, "f": f, "safe": safe})
    return mv


# ---------------------------------------------------------------- 切削参数
def spindle_rpm(vc_m_min, d_mm, max_rpm):
    """n = 1000·v_c / (π·D)，不超过机床最高转速。"""
    return min(1000 * vc_m_min / (math.pi * max(d_mm, 1e-6)), max_rpm)


def mill_feed(fz, z_teeth, rpm):
    """铣削进给速度 F = f_z·z·n（mm/min）。"""
    return fz * z_teeth * rpm


def basic_time_min(length, passes, vc, d, f):
    """车削基本时间 t_b = L·i / (n·f)，n = 1000·v_c / (π·d)（分钟）。"""
    return length * passes / (1000.0 * vc / (math.pi * d) * f)
