"""工序简图（第 13 轮 7.3（4）N3）：由工艺规程数据画回转体零件的工序简图，输出 SVG。

画法按工艺文件的惯例：
- 零件在本工序结束时的形状用细实线画出，本工序加工的表面用粗实线；
- 标出本工序的工序尺寸及偏差、几何公差、表面粗糙度；
- 用定位、夹紧符号标出定位面、限制的自由度数和夹紧位置（GB/T 24740 的含义：定位符号旁的数字是限制的自由度数，
  夹紧符号为指向夹紧面的箭头，动力夹紧在箭头旁注字母，如 Y 液压、Q 气动；字母以标准原文为准）。

只用标准库：工厂镜像不装绘图库，书里和数字工厂网页用的是同一个函数。
"""
from __future__ import annotations

from html import escape

INK = "#1d2327"
THIN = 0.9
THICK = 2.4
DIM = "#1d2327"
SYM = "#b5443b"      # 定位、夹紧符号
FONT = "'Noto Sans CJK SC','Noto Sans SC','Microsoft YaHei',sans-serif"


class _Svg:
    def __init__(self, w, h):
        self.w, self.h, self.items = w, h, []

    def line(self, x1, y1, x2, y2, w=THIN, color=INK, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{w}"{d}/>')

    def poly(self, pts, w=THIN, color=INK, fill="none", close=False):
        tag = "polygon" if close else "polyline"
        p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.items.append(f'<{tag} points="{p}" stroke="{color}" stroke-width="{w}" fill="{fill}" stroke-linejoin="round"/>')

    def circle(self, x, y, r, w=THIN, color=INK, fill="none"):
        self.items.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" stroke="{color}" stroke-width="{w}" fill="{fill}"/>')

    def text(self, x, y, s, size=10, anchor="middle", color=INK, rotate=None, weight="normal"):
        r = f' transform="rotate({rotate} {x:.1f} {y:.1f})"' if rotate is not None else ""
        size = size * 1.45
        self.items.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size:.1f}" text-anchor="{anchor}" fill="{color}" '
                          f'font-family="{FONT}" font-weight="{weight}"{r}>{escape(str(s))}</text>')

    def arrow(self, x, y, ang_dx, ang_dy, color=DIM, size=5):
        """Arrowhead at (x, y) pointing along (dx, dy)."""
        import math
        L = math.hypot(ang_dx, ang_dy) or 1
        ux, uy = ang_dx / L, ang_dy / L
        px, py = -uy, ux
        self.poly([(x, y), (x - ux * size + px * size * 0.4, y - uy * size + py * size * 0.4),
                   (x - ux * size - px * size * 0.4, y - uy * size - py * size * 0.4)], w=0.6, color=color, fill=color, close=True)

    def svg(self):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">'
                + "".join(self.items) + "</svg>")


def _hdim(s, x1, x2, y, text, ext_from=None):
    """Horizontal (length) dimension with extension lines from ext_from (y of the part edge)."""
    if ext_from is not None:
        s.line(x1, ext_from + 3, x1, y + 4, w=0.6, color=DIM)
        s.line(x2, ext_from + 3, x2, y + 4, w=0.6, color=DIM)
    s.line(x1, y, x2, y, w=0.6, color=DIM)
    s.arrow(x1, y, -1, 0); s.arrow(x2, y, 1, 0)
    s.text((x1 + x2) / 2, y - 3, text, size=9)


def _vdim(s, x, y1, y2, text):
    """Diameter dimension drawn across the section, text rotated along the line."""
    s.line(x, y1, x, y2, w=0.6, color=DIM)
    s.arrow(x, y1, 0, -1); s.arrow(x, y2, 0, 1)
    s.text(x - 3, (y1 + y2) / 2, text, size=9, rotate=-90)


def _ra(s, x, y, value):
    """Surface texture symbol (√ with Ra value) standing on the surface at (x, y)."""
    s.poly([(x - 4, y - 5), (x, y), (x + 9, y - 16), (x + 22, y - 16)], w=0.8, color=INK)
    s.text(x + 15, y - 18, f"Ra {value:g}", size=8)


def _locate(s, x, y, dof, up=False, label=None):
    """Locating symbol: a small support (inverted V) touching the surface at (x, y), with the number of DOF."""
    k = -1 if up else 1
    s.poly([(x - 6, y + k * 9), (x, y), (x + 6, y + k * 9)], w=1.4, color=SYM)
    s.text(x + 10, y + k * 9 + (4 if not up else 0), str(dof), size=9, anchor="start", color=SYM, weight="bold")
    if label:
        s.text(x, y + k * 22 + (4 if not up else 0), label, size=8, color=SYM)


def _clamp(s, x, y, kind="manual", up=True, label=None):
    """Clamping symbol: an arrow pointing at the clamped surface (letter Y/Q for hydraulic/pneumatic; check the standard)."""
    k = -1 if up else 1
    s.line(x, y + k * 22, x, y + k * 3, w=1.4, color=SYM)
    s.arrow(x, y + k * 1, 0, -k, color=SYM, size=6)
    letter = {"hydraulic": "Y", "pneumatic": "Q"}.get(kind)
    if letter:
        s.text(x + 6, y + k * 16, letter, size=9, anchor="start", color=SYM, weight="bold")
    if label:
        s.text(x, y + k * 27 + (0 if up else 6), label, size=8, color=SYM)


def shaft_sketch(part: dict, op: dict, width=1000, height=300, keyway_done=None) -> str:
    """工序简图（回转体）。part：工艺数据的 part；op：一道工序（用 sketch、locate、clamp）。"""
    sk = op.get("sketch") or {}
    stock = [tuple(x) for x in sk.get("stock") or [(d, L) for d, L, *_ in part["segments"]]]
    total = sum(L for _, L in stock)
    dmax = max(d for d, _ in stock)
    margin_l, margin_r = 110, 110
    sc = min((width - margin_l - margin_r) / total, 150 / dmax)
    x0 = margin_l + ((width - margin_l - margin_r) - total * sc) / 2
    yc = 140
    s = _Svg(width, height)
    machined = set(sk.get("machined") or [])
    # 中心线
    s.line(x0 - 18, yc, x0 + total * sc + 18, yc, w=0.6, color=INK, dash="12 3 2 3")
    # 轮廓：上下两条母线 + 台阶
    xs, z = [], 0.0
    for d, L in stock:
        xs.append((x0 + z * sc, x0 + (z + L) * sc, d * sc / 2))
        z += L
    for i, (xa, xb, r) in enumerate(xs):
        w = THICK if i in machined else THIN
        for sgn in (-1, 1):
            s.line(xa, yc + sgn * r, xb, yc + sgn * r, w=w)
    for i in range(len(xs) + 1):
        if i == 0:
            x, r = xs[0][0], xs[0][2]
            w = THICK if "end_L" in machined else THIN
        elif i == len(xs):
            x, r = xs[-1][1], xs[-1][2]
            w = THICK if "end_R" in machined else THIN
        else:
            x, r = xs[i][0], max(xs[i - 1][2], xs[i][2])
            rr = min(xs[i - 1][2], xs[i][2])
            w = THICK if (i - 1 in machined or i in machined) else THIN
            for sgn in (-1, 1):
                s.line(x, yc + sgn * rr, x, yc + sgn * r, w=w)
            continue
        s.line(x, yc - r, x, yc + r, w=w)
    # 中心孔（两端的小锥）
    if part.get("center_hole") and len(stock) > 1:
        for x, k in ((xs[0][0], 1), (xs[-1][1], -1)):
            s.poly([(x, yc - 3.5), (x + k * 7, yc), (x, yc + 3.5)], w=0.7)
    # 键槽（画在上母线，深 t）
    kw = part.get("keyway")
    if keyway_done is None:
        keyway_done = "keyway" in machined
    if not keyway_done:
        kw = None
    if kw and len(stock) > kw["segment"]:
        xa, xb, r = xs[kw["segment"]]
        kx0 = xa + kw.get("offset_mm", 0) * sc
        kx1 = kx0 + kw["L"] * sc
        ky = yc - r + kw["t"] * sc
        w = THICK if "keyway" in machined else THIN
        s.poly([(kx0, yc - r), (kx0, ky), (kx1, ky), (kx1, yc - r)], w=w)
    # 尺寸
    ybot = yc + dmax * sc / 2
    nlen = 0
    for dm in sk.get("dims") or []:
        k = dm["kind"]
        if k == "dia":
            xa, xb, r = xs[dm["seg"]]
            _vdim(s, (xa + xb) / 2, yc - r, yc + r, dm["text"])
        elif k == "length":
            nlen += 1
            yy = ybot + 16 + 15 * (nlen - 1) if (dm["from"], dm["to"]) != (0, total) else height - 22
            _hdim(s, x0 + dm["from"] * sc, x0 + dm["to"] * sc, yy, dm["text"], ext_from=ybot if dm["from"] or dm["to"] != total else None)
            if (dm["from"], dm["to"]) == (0, total):
                s.line(x0, ybot + 3, x0, yy + 4, w=0.6); s.line(x0 + total * sc, ybot + 3, x0 + total * sc, yy + 4, w=0.6)
        elif k.startswith("keyway") and kw:
            xa, xb, r = xs[kw["segment"]]
            kx0 = xa + kw.get("offset_mm", 0) * sc
            kx1 = kx0 + kw["L"] * sc
            ky = yc - r + kw["t"] * sc
            if k == "keyway_length":
                _hdim(s, kx0, kx1, yc - r - 22, dm["text"])
                s.line(kx0, yc - r - 2, kx0, yc - r - 26, w=0.6); s.line(kx1, yc - r - 2, kx1, yc - r - 26, w=0.6)
            elif k == "keyway_depth":
                xd = kx1 + 14
                s.line(kx1 + 2, ky, xd + 4, ky, w=0.6)
                s.line(xd, ky, xd, yc + r, w=0.6)
                s.line(xb - 2, yc + r, xd + 4, yc + r, w=0.6)
                s.arrow(xd, ky, 0, -1); s.arrow(xd, yc + r, 0, 1)
                s.text(xd + 16, (ky + yc + r) / 2, dm["text"], size=9, rotate=-90, anchor="middle")
            elif k == "keyway_width":
                s.text((kx0 + kx1) / 2, yc - r - 44, "键槽宽 " + dm["text"], size=9)
            elif k == "keyway_pos":
                _hdim(s, xa, kx0, yc - r - 8, dm["text"])
        elif k == "runout":
            xa, xb, r = xs[dm["seg"]]
            xm = (xa + xb) / 2
            s.line(xm, yc - r, xm + 6, yc - r - 18, w=0.6)
            s.line(xm + 6, yc - r - 18, xm + 18, yc - r - 18, w=0.6)
            s.items.append(f'<rect x="{xm + 18:.1f}" y="{yc - r - 27:.1f}" width="{8 + 6.2 * len(dm["text"]):.1f}" height="14" '
                           f'fill="white" stroke="{INK}" stroke-width="0.7"/>')
            s.text(xm + 22, yc - r - 16.5, dm["text"], size=8.5, anchor="start")
    # 粗糙度
    ra = sk.get("ra") or {}
    if "all" in ra:
        s.text(width - 8, 16, f"本工序加工面 Ra {ra['all']:g}", size=9, anchor="end")
    for seg, v in (ra.get("seg") or {}).items():
        xa, xb, r = xs[int(seg)]
        _ra(s, xa + (xb - xa) * 0.22, yc - r, v)
    if "keyway" in ra and kw:
        xa, xb, r = xs[kw["segment"]]
        s.text(width - 8, 16, f"键槽侧面 Ra {ra['keyway']:g}", size=9, anchor="end")
    # 定位与夹紧
    for loc in op.get("locate") or []:
        sym = loc["symbol"]
        surf = loc["surface"]
        left = surf.startswith("左") or surf.endswith("（左）")
        if sym in ("center_fixed", "center_live"):
            x = xs[0][0] if left else xs[-1][1]
            k = 1 if left else -1
            tip = x + k * 6
            s.poly([(tip - k * 26, yc - 9), (tip, yc), (tip - k * 26, yc + 9)], w=1.4, color=SYM)
            if sym == "center_live":
                s.circle(tip - k * 33, yc, 5, w=1.2, color=SYM)
            s.text(tip - k * 30, yc - 14, str(loc["dof"]), size=9, color=SYM, weight="bold")
            s.text(tip - k * 30, yc + 24, "回转顶尖" if sym == "center_live" else "固定顶尖", size=8, color=SYM)
        elif sym == "chuck":
            xa, xb, r = xs[0]
            for sgn in (-1, 1):
                s.items.append(f'<rect x="{xa - 8:.1f}" y="{(yc + sgn * r) - (0 if sgn > 0 else 9):.1f}" width="26" height="9" '
                               f'fill="none" stroke="{SYM}" stroke-width="1.3"/>')
            s.text(xa - 16, yc + 4, str(loc["dof"]), size=9, color=SYM, weight="bold", anchor="end")
            s.text(xa + 5, yc + r + 22, "三爪卡盘", size=8, color=SYM)
        elif sym == "v":
            i = _seg_of(surf, part, stock)
            xa, xb, r = xs[i]
            for frac in (0.25, 0.75):
                xm = xa + (xb - xa) * frac
                s.poly([(xm - 14, yc + r + 2), (xm, yc + r + 14), (xm + 14, yc + r + 2)], w=1.3, color=SYM)
            s.text(xa + (xb - xa) * 0.5, yc + r + 16, f"V 形块 {loc['dof']}", size=8, color=SYM, weight="bold")
        elif sym == "plane":
            i = _seg_of("齿轮位", part, stock)
            xa, xb, r = xs[i]
            rr = xs[i - 1][2]
            _locate_axial(s, xa, yc + (r + rr) / 2, loc["dof"])
    for cl in op.get("clamp") or []:
        surf = cl["surface"]
        if "鸡心" in surf:
            left = surf.startswith("左")
            xa, xb, r = xs[0] if left else xs[-1]
            xm = (xa + xb) / 2
            _clamp(s, xm, yc - r, cl.get("kind", "manual"), up=True, label="鸡心夹头")
        elif "外圆" in surf:
            i = 0 if surf.startswith("左") else _seg_of(surf, part, stock)
            xa, xb, r = xs[i]
            _clamp(s, (xa + xb) / 2 + (6 if i else 0), yc - r, cl.get("kind", "manual"), up=True)
    s.text(8, height - 6, "定位与夹紧符号（GB/T 24740 的画法示意）：定位符号旁的数字为限制的自由度数；箭头为夹紧，旁注 Y 液压、Q 气动", size=9, anchor="start", color="#7a868d")
    return s.svg()


def _locate_axial(s, x, y, dof):
    """Axial locating symbol against a shoulder face (support pointing in −z)."""
    s.poly([(x - 10, y - 6), (x - 1, y), (x - 10, y + 6)], w=1.4, color=SYM)
    s.text(x - 14, y + 4, str(dof), size=9, anchor="end", color=SYM, weight="bold")


def _seg_of(surface: str, part: dict, stock) -> int:
    names = [seg[2] if len(seg) > 2 else "" for seg in part["segments"]]
    for i, n in enumerate(names):
        if n and n in surface:
            return i
    for i, n in enumerate(names):
        if n and n.lstrip("左右") in surface:
            return i
    return 0
