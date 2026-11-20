"""问渠CAM 工艺卡的图（ADR-0106 Q6a）：零件图、装夹图、刀具图。matplotlib 画，只吃数据（不依赖 FreeCAD）。

每个函数画一张 PNG，图上的数都从调用方给的 `num(来源, 指针)` 拿（工艺卡传 Ledger.num：印出来的数记进出处账）；
算出来的数（伸出长度等）用 `derived(值, 公式)` 记账。缺的尺寸不画不标，写进返回的 notes（“没写刃长”之类）。

- part_views_png：零件三视图（第一角画法：主视在左上、左视在右、俯视在下），views 由 FreeCAD 投影（freecad_addon.fc.cam_figures_fc）
- turn_part_png：车削零件外形（按轮廓），标各段直径、台阶位置、总长，槽、螺纹
- turn_setup_png / mill_setup_png：每次装夹一张：毛坯、卡爪或夹具、零件、工件零点
- tools_png：刀具清单里每把刀一个小图
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

INK, THIN, STOCK, FIX, PART, ORIG = "#202020", "#606060", "#9e9e9e", "#5b7db1", "#c62828", "#2e7d32"
INSERT_ANGLE = {"C": 80, "D": 55, "V": 35, "W": 80, "T": 60, "S": 90, "R": None}


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _dim(ax, p1, p2, off, text, horizontal=True, color=INK, fs=7):
    """尺寸线：p1、p2 两点，off 是尺寸线离开的距离（水平尺寸往 y 方向、竖直尺寸往 x 方向）"""
    (x1, y1), (x2, y2) = p1, p2
    if horizontal:
        y = max(y1, y2) + off if off > 0 else min(y1, y2) + off
        ax.plot([x1, x1], [y1, y], color=THIN, lw=0.4)
        ax.plot([x2, x2], [y2, y], color=THIN, lw=0.4)
        ax.annotate("", (x1, y), (x2, y), arrowprops={"arrowstyle": "<->", "lw": 0.6, "color": color, "shrinkA": 0, "shrinkB": 0},
                    annotation_clip=False)
        ax.text((x1 + x2) / 2, y, text, ha="center", va="bottom" if off > 0 else "top", fontsize=fs, color=color)
    else:
        x = max(x1, x2) + off if off > 0 else min(x1, x2) + off
        ax.plot([x1, x], [y1, y1], color=THIN, lw=0.4)
        ax.plot([x2, x], [y2, y2], color=THIN, lw=0.4)
        ax.annotate("", (x, y1), (x, y2), arrowprops={"arrowstyle": "<->", "lw": 0.6, "color": color, "shrinkA": 0, "shrinkB": 0},
                    annotation_clip=False)
        ax.text(x, (y1 + y2) / 2, text, ha="left" if off > 0 else "right", va="center", fontsize=fs, color=color, rotation=90)


def _origin(ax, x, y, labels=("X", "Z"), size=8.0, name="G54"):
    ax.plot([x + size * 1.3, x - size * 0.6], [y + size * 1.3, y - size * 0.6], alpha=0)     # 自动范围包住箭头和字
    ax.annotate("", (x + size, y), (x, y), arrowprops={"arrowstyle": "->", "lw": 1.0, "color": ORIG}, annotation_clip=False)
    ax.annotate("", (x, y + size), (x, y), arrowprops={"arrowstyle": "->", "lw": 1.0, "color": ORIG}, annotation_clip=False)
    ax.text(x + size, y, labels[0], color=ORIG, fontsize=7, va="top")
    ax.text(x, y + size, labels[1], color=ORIG, fontsize=7, ha="right")
    ax.plot([x], [y], "o", color=ORIG, ms=3)
    ax.text(x - size * 0.2, y - size * 0.2, name, color=ORIG, fontsize=7, ha="right", va="top")


def _finish(fig, ax_list, out):
    for ax in ax_list:
        ax.set_aspect("equal")
        ax.axis("off")
    fig.tight_layout()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=200)
    _plt().close(fig)
    return out


# ---------------------------------------------------------------- 零件图
def part_views_png(views: dict, out, derived) -> Path:
    """views：{"front": [折线…], "top": […], "left": […], "bbox": [xmin, ymin, zmin, xmax, ymax, zmax]}（程序坐标）；
    总长、总宽、总高 = 包围盒的边长，用 derived(值, 公式) 记账"""
    plt = _plt()
    bb = views["bbox"]
    lx, ly, lz = bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]
    fig = plt.figure(figsize=(7.5, 6.0))
    m = 0.25 * max(lx, ly, lz)
    gs = fig.add_gridspec(2, 2, width_ratios=[lx + 2 * m, ly + 2 * m], height_ratios=[lz + 2 * m, ly + 2 * m])
    axf, axl, axt = fig.add_subplot(gs[0, 0]), fig.add_subplot(gs[0, 1]), fig.add_subplot(gs[1, 0])
    for ax, key in ((axf, "front"), (axl, "left"), (axt, "top")):
        for pl in views.get(key + "_hidden") or []:
            xs, ys = zip(*pl, strict=True)
            ax.plot(xs, ys, color=THIN, lw=0.5, ls=(0, (3, 2)))
        for pl in views.get(key) or []:
            xs, ys = zip(*pl, strict=True)
            ax.plot(xs, ys, color=INK, lw=0.7)
    pad = 0.12 * max(lx, ly, lz)
    _dim(axt, (bb[0], bb[1]), (bb[3], bb[1]), -pad, derived(lx, "总长 = 零件包围盒 X 向边长"))
    _dim(axt, (bb[3], bb[1]), (bb[3], bb[4]), pad, derived(ly, "总宽 = 零件包围盒 Y 向边长"), horizontal=False)
    _dim(axf, (bb[3], bb[2]), (bb[3], bb[5]), pad, derived(lz, "总高 = 零件包围盒 Z 向边长"), horizontal=False)
    # 主视与俯视 X 对齐、主视与左视 Z 对齐（长对正、高平齐）
    axf.set_xlim(bb[0] - m, bb[3] + m)
    axt.set_xlim(bb[0] - m, bb[3] + m)
    axf.set_ylim(bb[2] - m, bb[5] + m)
    axl.set_ylim(bb[2] - m, bb[5] + m)
    axl.set_xlim(-bb[4] - m, -bb[1] + m)
    axt.set_ylim(bb[1] - m, bb[4] + m)
    for ax in (axf, axl, axt):
        ax.set_aspect("equal", adjustable="box")
    axf.set_title("A", fontsize=8, loc="left")
    axl.set_title("B", fontsize=8, loc="left")
    axt.set_title("C", fontsize=8, loc="left")
    return _finish(fig, (axf, axl, axt), out)


def turn_part_png(profile, grooves, threads, out, num) -> Path:
    """profile：[[离右端面距离, 直径], …]（result 的 profile）；grooves：[{z, width, d}]（零件坐标，Z0 在右端面）；
    threads：[{z_start, z_end, d, pitch}]。num(来源指针) → 印的数：profile 用 ("result", "/profile/i/1")，槽、螺纹用 ("draft", …)"""
    plt = _plt()
    pts = [(-float(t), float(d) / 2) for t, d in profile]
    total = max(float(t) for t, _ in profile)
    dmax = max(float(d) for _, d in profile)
    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    xs = [p[0] for p in pts]
    ax.plot(xs, [p[1] for p in pts], color=INK, lw=1.0)
    ax.plot(xs, [-p[1] for p in pts], color=INK, lw=1.0)
    ax.plot([pts[0][0]] * 2, [-pts[0][1], pts[0][1]], color=INK, lw=1.0)
    ax.plot([pts[-1][0]] * 2, [-pts[-1][1], pts[-1][1]], color=INK, lw=1.0)
    ax.plot([-total - 3, 3], [0, 0], color=THIN, lw=0.5, ls=(0, (8, 2, 1, 2)))
    for i in range(1, len(pts) - 1):              # 台阶线
        if abs(pts[i][0] - pts[i + 1][0]) < 1e-9 or abs(pts[i][0] - pts[i - 1][0]) < 1e-9:
            ax.plot([pts[i][0]] * 2, [-pts[i][1], pts[i][1]], color=INK, lw=0.6)
    # 直径：每段等径的中点标 Ø
    done = set()
    for i in range(len(pts) - 1):
        (z0, r0), (z1, r1) = pts[i], pts[i + 1]
        if abs(r0 - r1) < 1e-9 and abs(z1 - z0) > 1e-6 and round(r0, 4) not in done:
            done.add(round(r0, 4))
            zm = (z0 + z1) / 2
            ax.annotate("", (zm, r0), (zm, -r0), arrowprops={"arrowstyle": "<->", "lw": 0.6, "color": INK})
            ax.text(zm + 0.6, 0.15 * r0, "Ø" + num(("result", f"/profile/{i}/1")), fontsize=7, rotation=90, va="bottom")
    # 台阶位置（从右端面量）：只标轴肩（轮廓里同一个位置前后两点，直径变了），倒角起点不标；短的靠近零件
    sh = [i for i in range(1, len(profile)) if abs(float(profile[i][0]) - float(profile[i - 1][0])) < 1e-9
          and 0 < float(profile[i][0]) < total]
    sh = sorted(sh, key=lambda i: float(profile[i][0]))
    for k, i in enumerate(sh[:6]):
        _dim(ax, (0, -pts[0][1]), (-float(profile[i][0]), -max(pts[i][1], pts[i - 1][1])), -(0.16 + 0.2 * k) * dmax,
             num(("result", f"/profile/{i}/0")))
    _dim(ax, (0, dmax / 2), (-total, dmax / 2), 0.25 * dmax, num(("result", "/length_mm")))
    for gi, g in enumerate(grooves or []):
        z, w, d = float(g["z"]), float(g["width"]), float(g["d"])
        ro = _radius_at(pts, z - w / 2)
        ax.fill_between([z - w, z], [d / 2] * 2, [ro + 0.5] * 2, color="white", zorder=3)
        ax.fill_between([z - w, z], [-d / 2] * 2, [-ro - 0.5] * 2, color="white", zorder=3)
        ax.plot([z, z, z - w, z - w], [ro, d / 2, d / 2, ro], color=INK, lw=0.8, zorder=4)
        ax.plot([z, z, z - w, z - w], [-ro, -d / 2, -d / 2, -ro], color=INK, lw=0.8, zorder=4)
        ax.text(z - w / 2, ro + 0.06 * dmax, f"{num(('draft', f'/setup/grooves/{gi}/width'))}×Ø{num(('draft', f'/setup/grooves/{gi}/d'))}",
                fontsize=7, ha="center", color=PART)
    for ti, t in enumerate(threads or []):
        za, zb, d, p = float(t["z_start"]), float(t["z_end"]), float(t["d"]), float(t["pitch"])
        root = d / 2 - 0.6134 * p                     # 画示意的小径线（ISO 68-1 牙高 5/8·H，H = 0.866P）
        ax.plot([za, zb], [root, root], color=INK, lw=0.5, ls="--")
        ax.plot([za, zb], [-root, -root], color=INK, lw=0.5, ls="--")
        ax.text((za + zb) / 2, -d / 2 - 0.08 * dmax,
                f"M{num(('draft', f'/setup/threads/{ti}/d'))}×{num(('draft', f'/setup/threads/{ti}/pitch'))}",
                fontsize=7, ha="center", va="top", color=PART)
    ax.margins(0.06, 0.12)
    return _finish(fig, (ax,), out)


def _radius_at(pts, z):
    """轮廓在 z 处的半径（取该处最大的）"""
    best = 0.0
    for (z0, r0), (z1, r1) in itertools.pairwise(pts):
        lo, hi = min(z0, z1), max(z0, z1)
        if lo - 1e-9 <= z <= hi + 1e-9:
            r = r0 if abs(z1 - z0) < 1e-12 else r0 + (r1 - r0) * (z - z0) / (z1 - z0)
            best = max(best, r, r0 if abs(z1 - z0) < 1e-12 else 0.0)
    return best


# ---------------------------------------------------------------- 装夹图
def turn_setup_png(stock, target, clamp, out, num, derived, pptr) -> Path:
    """一次车削装夹：stock {d, z_right, z_left}；target [[z, d], …]（本次要车成的外形）；clamp {jaw_len, jaw_d, z_left} 或 None；
    pptr：这个程序在计算结果里的指针（/programs/i）"""
    plt = _plt()
    d, zr, zl = float(stock["d"]), float(stock["z_right"]), float(stock["z_left"])
    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.add_patch(_rect(zl, -d / 2, zr - zl, d, STOCK, alpha=0.25))
    zs = [float(z) for z, _ in target]
    rs = [float(x) / 2 for _, x in target]
    ax.plot(zs, rs, color=PART, lw=1.1)
    ax.plot(zs, [-r for r in rs], color=PART, lw=1.1)
    ax.plot([zl - 5, zr + 5], [0, 0], color=THIN, lw=0.5, ls=(0, (8, 2, 1, 2)))
    if clamp:
        jl, jd, zj = float(clamp["jaw_len"]), float(clamp["jaw_d"]), float(clamp["z_left"])
        ax.add_patch(_rect(zj, d / 2, jl, jd / 2 - d / 2, FIX, alpha=0.6))
        ax.add_patch(_rect(zj, -jd / 2, jl, jd / 2 - d / 2, FIX, alpha=0.6))
        ax.add_patch(_rect(zj - 30, -jd / 2, 30, jd, FIX, alpha=0.25))
        _dim(ax, (zj, jd / 2), (zj + jl, jd / 2), 0.08 * d, num(("result", pptr + "/clamp/jaw_len")))
        _dim(ax, (zj + jl, -d / 2), (0.0, -d / 2), -0.3 * d, derived(-(zj + jl), "伸出长度 = 0 − (卡爪起点 + 夹持长度)"))
    _origin(ax, 0.0, 0.0, ("Z", "X"), size=0.25 * d, name="Z0 X0")
    ax.margins(0.08, 0.3)
    return _finish(fig, (ax,), out)


def mill_setup_png(stock, fixtures, views, out, num, derived, sptr) -> Path:
    """一次铣削装夹：俯视、主视。stock {box: [x0, y0, x1, y1], top, height}；fixtures [{box_mm | cylinder_mm}]（程序坐标）；
    views：零件投影（可没有）。工件零点在程序原点"""
    plt = _plt()
    x0, y0, x1, y1 = (float(v) for v in stock["box"])
    top, h = float(stock.get("top", 0.0)), float(stock["height"])
    zb = top - h
    fig, (axt, axf) = plt.subplots(2, 1, figsize=(7.0, 6.4), gridspec_kw={"height_ratios": [max(y1 - y0, 1), max(h, 1) + 10]})
    axt.add_patch(_rect(x0, y0, x1 - x0, y1 - y0, STOCK, alpha=0.25))
    axf.add_patch(_rect(x0, zb, x1 - x0, h, STOCK, alpha=0.25))
    for fx in fixtures or []:
        if "box_mm" in fx:
            a, b, c, dx, dy, dz = (float(v) for v in fx["box_mm"])
            axt.add_patch(_rect(a, b, dx - a, dy - b, FIX, alpha=0.5))
            axf.add_patch(_rect(a, c, dx - a, dz - c, FIX, alpha=0.5))
        elif "cylinder_mm" in fx:
            cy = fx["cylinder_mm"]
            p0, p1, r = cy["p0"], cy["p1"], float(cy["r"])
            axt.add_patch(_circle(p0[0], p0[1], r))
            axf.add_patch(_rect(p0[0] - r, min(p0[2], p1[2]), 2 * r, abs(p1[2] - p0[2]), FIX, alpha=0.5))
    for ax, key in ((axt, "top"), (axf, "front")):
        for pl in (views or {}).get(key) or []:
            xs, ys = zip(*pl, strict=True)
            ax.plot(xs, ys, color=PART, lw=0.7)
    s = 0.12 * max(x1 - x0, y1 - y0)
    _origin(axt, 0.0, 0.0, ("X", "Y"), size=s)
    _origin(axf, 0.0, 0.0, ("X", "Z"), size=s)
    _dim(axt, (x0, y0), (x1, y0), -0.1 * (y1 - y0) - 2, derived(x1 - x0, "毛坯长 = 毛坯 X1 − X0"))
    _dim(axt, (x1, y0), (x1, y1), 0.06 * (x1 - x0) + 2, derived(y1 - y0, "毛坯宽 = 毛坯 Y1 − Y0"), horizontal=False)
    _dim(axf, (x1, zb), (x1, top), 0.06 * (x1 - x0) + 2, num(("result", sptr + "/height")), horizontal=False)
    for ax in (axt, axf):
        ax.margins(0.15)
    lo = min(axt.get_xlim()[0], axf.get_xlim()[0])            # 俯视、主视 X 范围相同
    hi = max(axt.get_xlim()[1], axf.get_xlim()[1])
    axt.set_xlim(lo, hi)
    axf.set_xlim(lo, hi)
    for ax in (axt, axf):
        ax.set_aspect("equal", adjustable="box")
    return _finish(fig, (axt, axf), out)


def _rect(x, y, w, h, color, alpha=0.3):
    from matplotlib.patches import Rectangle

    return Rectangle((x, y), w, h, facecolor=color, edgecolor=INK, lw=0.6, alpha=alpha)


def _circle(x, y, r):
    from matplotlib.patches import Circle

    return Circle((x, y), r, facecolor=FIX, edgecolor=INK, lw=0.6, alpha=0.5)


# ---------------------------------------------------------------- 刀具图
MILL_KINDS = ("flat_endmill", "ball_endmill", "bull_endmill", "drill", "tap", "chamfer_mill", "thread_mill", "face_mill", "endmill")


def tools_png(items, out, num, *, missing_text=None) -> tuple[Path, list[str]]:
    """items：[{"tno", "tool"（库里的刀）, "ti"（库里的序号）, "length"（机床设置里的刀长，可无）, "lptr"}]。
    返回 (png, notes)：缺尺寸的写进 notes"""
    plt = _plt()
    n = len(items)
    cols = min(4, max(n, 1))
    rows = math.ceil(n / cols) if n else 1
    fig, axes = plt.subplots(rows, cols, figsize=(1.9 * cols, 2.6 * rows), squeeze=False)
    notes = []
    miss = missing_text or (lambda tno, what: f"T{tno:02d}：没写{what}")
    for k, it in enumerate(items):
        ax = axes[k // cols][k % cols]
        t, ti, tno = it["tool"], it["ti"], it["tno"]
        base = f"/tools/{ti}"
        ax.set_title(f"T{tno:02d} {t['id']}", fontsize=7)
        if t["kind"] in MILL_KINDS:
            notes += _mill_tool(ax, t, base, it, num, lambda w, tno=tno: miss(tno, w))
        else:
            notes += _turn_tool(ax, t, base, num, lambda w, tno=tno: miss(tno, w))
        ax.margins(0.25)
    for k in range(n, rows * cols):
        axes[k // cols][k % cols].set_visible(False)
    return _finish(fig, [a for row in axes for a in row], out), notes


def _mill_tool(ax, t, base, it, num, miss):
    notes = []
    D = float(t["diameter_mm"])
    r = D / 2
    lf = t.get("flute_length_mm")
    shank = float(t.get("shank_diameter_mm") or D) / 2
    body = float(lf) if lf else 2.0 * D
    kind = t["kind"]
    tip = 0.0
    if kind == "drill":
        tip = r / math.tan(math.radians(float(t.get("tip_angle_deg", 118)) / 2))
    elif kind == "chamfer_mill":
        dt = float(t.get("tip_diameter_mm") or 0.0) / 2
        tip = (r - dt) / math.tan(math.radians(float(t.get("tip_angle_deg", 90)) / 2))
    # 刃部（刃长没写：画两倍直径示意，不标）
    if kind == "ball_endmill":
        th = [math.pi + i * math.pi / 30 for i in range(31)]
        xs = [r * math.cos(a) for a in th]
        ys = [r + r * math.sin(a) for a in th]
        ax.plot(xs, ys, color=INK, lw=0.8)
        ax.plot([-r, -r], [r, body], color=INK, lw=0.8)
        ax.plot([r, r], [r, body], color=INK, lw=0.8)
    elif kind in ("drill", "chamfer_mill"):
        dt = float(t.get("tip_diameter_mm") or 0.0) / 2 if kind == "chamfer_mill" else 0.0
        ax.plot([-r, -dt, dt, r], [tip, 0, 0, tip], color=INK, lw=0.8)
        ax.plot([-r, -r], [tip, max(body, tip)], color=INK, lw=0.8)
        ax.plot([r, r], [tip, max(body, tip)], color=INK, lw=0.8)
    else:
        cr = float(t.get("corner_radius_mm") or 0.0)
        ax.plot([-r, -r, r, r], [body, cr, cr, body], color=INK, lw=0.8)
        ax.plot([-r + cr, r - cr], [0, 0], color=INK, lw=0.8)
        if cr > 0:
            for sx in (-1, 1):
                th = [i * math.pi / 2 / 10 for i in range(11)]
                ax.plot([sx * (r - cr + cr * math.sin(a)) for a in th], [cr - cr * math.cos(a) for a in th], color=INK, lw=0.8)
        if kind in ("tap", "thread_mill"):
            for y in [body * (i + 0.5) / 8 for i in range(8)]:
                ax.plot([-r, r], [y, y + body / 16], color=THIN, lw=0.4)
    top = float(t.get("stickout_mm") or body + 2 * D)
    ax.plot([-shank, -shank, shank, shank], [body, top, top, body], color=INK, lw=0.8)
    ax.plot([-r, r], [body, body], color=THIN, lw=0.4)
    off = r + 0.25 * D
    ax.text(0, -0.15 * D, "Ø" + num(("library", base + "/diameter_mm")), ha="center", va="top", fontsize=7)
    if lf:
        _dim(ax, (-r, 0), (-r, body), -0.25 * D, num(("library", base + "/flute_length_mm")), horizontal=False)
    elif kind not in ("drill",):
        notes.append(miss("刃长"))
    if t.get("stickout_mm"):
        _dim(ax, (r, 0), (shank, top), off, num(("library", base + "/stickout_mm")), horizontal=False)
        ax.plot([-shank - 0.3 * D, shank + 0.3 * D], [top, top], color=FIX, lw=1.2)
    else:
        notes.append(miss("伸出长"))
    if it.get("length") is not None:
        ax.text(0, top + 0.2 * D, "L=" + num(("draft", it["lptr"])), ha="center", va="bottom", fontsize=7, color=ORIG)
    if kind in ("tap", "thread_mill") and (t.get("pitch_mm") or t.get("thread_angle_deg")):
        lab = "P" + num(("library", base + "/pitch_mm")) if t.get("pitch_mm") else num(("library", base + "/thread_angle_deg")) + "°"
        ax.text(r + 0.1 * D, body / 2, lab, fontsize=7, va="center")
    if kind in ("drill", "chamfer_mill") and t.get("tip_angle_deg"):
        ax.text(r + 0.1 * D, tip / 2, num(("library", base + "/tip_angle_deg")) + "°", fontsize=7, va="center")
    return notes


def _turn_tool(ax, t, base, num, miss):
    notes = []
    ins = t.get("insert") or {}
    rn = ins.get("nose_radius_mm")
    kind = t["kind"]
    if kind == "groove":
        w = float(ins.get("width_mm") or 3.0)
        ax.plot([0, 0, w, w], [3 * w, 0, 0, 3 * w], color=INK, lw=0.9)
        if ins.get("width_mm"):
            _dim(ax, (0, 0), (w, 0), -0.4 * w, num(("library", base + "/insert/width_mm")))
        else:
            notes.append(miss("刃宽"))
    elif kind == "thread_turn":
        a = 60.0
        h = 5.0
        ax.plot([-h * math.tan(math.radians(a / 2)), 0, h * math.tan(math.radians(a / 2))], [h, 0, h], color=INK, lw=0.9)
        ax.text(0, h * 1.05, "60°", ha="center", fontsize=7)
        if t.get("pitch_mm"):
            ax.text(0, -0.8, "P" + num(("library", base + "/pitch_mm")), ha="center", va="top", fontsize=7)
    else:
        code = (ins.get("iso") or "")[:1].upper()
        ang = INSERT_ANGLE.get(code, 80) if code != "R" else None
        L = 10.0
        if ang is None:
            from matplotlib.patches import Circle

            ax.add_patch(Circle((0, L / 2), L / 2, fill=False, edgecolor=INK, lw=0.9))
        else:
            half = math.radians(ang) / 2
            p = [(0, 0), (L * math.sin(half), L * math.cos(half)), (0, 2 * L * math.cos(half)), (-L * math.sin(half), L * math.cos(half))]
            if code == "T":
                p = [(0, 0), (L * math.sin(half), L * math.cos(half) * 1.0), (-L * math.sin(half), L * math.cos(half))]
            xs, ys = zip(*(p + [p[0]]), strict=True)
            ax.plot(xs, ys, color=INK, lw=0.9)
            ax.text(0, L * 0.35, f"{ang}°", ha="center", fontsize=7)
        if ins.get("iso"):
            ax.text(0, -1.2, ins["iso"], ha="center", va="top", fontsize=7)
    if rn is not None:
        ax.text(0.8, 0.2, "r" + num(("library", base + "/insert/nose_radius_mm")), fontsize=7, color=PART)
    else:
        notes.append(miss("刀尖圆弧"))
    return notes
