# -*- coding: utf-8 -*-
"""工程图（第 13 轮 8.3 R3）：由 build123d 三维模型投影出视图，加国标图框、标题栏、明细栏、尺寸与公差、形位公差、
表面粗糙度、零件序号和技术要求，输出 SVG（单位 mm）。书中的零件图、夹具总图与数字工厂 PLM 里的图出自这里。

按第一角画法（GB/T 14692）：主视图从前方（−y 一侧）看，俯视图在主视图下方，左视图在主视图右方。
线型（GB/T 4457.4）：粗实线 0.5、细实线与细虚线 0.25、细点画线 0.25。字体高 3.5（尺寸）、5（标题栏图名 7）。
视图的投影：二维横坐标 = (视向 × 上方向)·p，纵坐标 = 上方向·p（与 build123d project_to_viewport 一致，程序核对）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

SIZES = {"A4": (297, 210), "A3": (420, 297), "A2": (594, 420), "A4V": (210, 297)}
THICK, THIN = 0.5, 0.25
FONT = "Noto Sans CJK SC, Noto Sans SC, sans-serif"
VIEWS = {   # 视向（从相机指向物体）与上方向
    "front": ((0, 1, 0), (0, 0, 1)), "top": ((0, 0, -1), (0, 1, 0)), "left": ((1, 0, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 0, 1)), "back": ((0, -1, 0), (0, 0, 1)), "bottom": ((0, 0, 1), (0, -1, 0)),
}


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _f(v):
    return f"{v:.3f}".rstrip("0").rstrip(".")


@dataclass
class View:
    """一个视图：视向、上方向、比例、视图上某个三维点在图纸上的位置。"""
    sheet: "Sheet"
    d: tuple
    up: tuple
    scale: float
    ref3: tuple          # 这个三维点
    ref2: tuple          # 放在图纸上这里（mm，左上角为原点，y 向下）
    name: str = ""
    vis: list = field(default_factory=list)      # [[(x, y), ...]]（图纸坐标）
    hid: list = field(default_factory=list)
    hatch: list = field(default_factory=list)    # [(折线组, 角度, 间距)]
    phantom: list = field(default_factory=list)  # 双点画线（装配图上的工件、相邻件、运动件的极限位置）

    @property
    def right(self):
        return _cross(self.d, self.up)

    def uv(self, p):
        return (_dot(self.right, p), _dot(self.up, p))

    def at(self, p):
        """三维点 → 图纸坐标。"""
        u, v = self.uv(p)
        u0, v0 = self.uv(self.ref3)
        return (self.ref2[0] + (u - u0) * self.scale, self.ref2[1] - (v - v0) * self.scale)

    def at2(self, uv):
        u0, v0 = self.uv(self.ref3)
        return (self.ref2[0] + (uv[0] - u0) * self.scale, self.ref2[1] - (uv[1] - v0) * self.scale)


def _dedupe(hid, vis, tol=0.05):
    """虚线去重：前后两条重合的不可见边投影到同一位置，两条虚线相位不同会叠成实线；
    与可见边重合的不可见边也不画。直线段按端点比较，统一从左上端开始画（相位一致）。"""
    def key(pl):
        a, b = (round(pl[0][0] / tol), round(pl[0][1] / tol)), (round(pl[-1][0] / tol), round(pl[-1][1] / tol))
        return (min(a, b), max(a, b), len(pl))
    seen = {key(pl) for pl in vis}
    out = []
    for pl in hid:
        k = key(pl)
        if k in seen:
            continue
        seen.add(k)
        if len(pl) == 2 and (pl[1][0], pl[1][1]) < (pl[0][0], pl[0][1]):
            pl = [pl[1], pl[0]]
        out.append(pl)
    return out


def _edges_to_polylines(edges, view: View, tol=0.2):
    out = []
    for e in edges:
        L = e.length
        if L < 1e-6:
            continue
        gt = str(e.geom_type)
        n = 1 if gt.endswith("LINE") else max(4, min(120, int(L * view.scale / tol) // 4 + 4))
        pts = [e @ (i / n) for i in range(n + 1)]
        out.append([view.at2((q.X, q.Y)) for q in pts])
    return out


class Sheet:
    def __init__(self, size="A3", title="", code="", material="", scale_text="1:1", mass="", qty="", company="问渠数字工厂",
                 designer="", checker="", date="", sheet_no="共 1 张 第 1 张", landscape=True):
        self.W, self.H = SIZES[size]
        self.size = size
        self.title, self.code, self.material, self.scale_text = title, code, material, scale_text
        self.mass, self.qty, self.company, self.designer, self.checker, self.date = mass, qty, company, designer, checker, date
        self.sheet_no = sheet_no
        self.items: list[str] = []
        self.views: list[View] = []
        self.bom_rows: list = []
        self.req: list[str] = []
        self.req_at = None

    # ------------------------------------------------------------ 视图
    def view(self, shapes, kind="front", scale=1.0, ref3=(0, 0, 0), at=(150, 120), hidden=True, section=None, nocut=(),
             hatch_parts=None, name="", d=None, up=None, phantom=()) -> View:
        """投影一组形体。section = (点, 法向)：剖视图——沿平面剖开，去掉法向一侧，剖面画剖面线；
        nocut：按不剖处理的零件序号（实心轴、标准件纵向剖切时不剖，GB/T 4458.6）。shapes：[(形体, 零件编号或 None)]。"""
        import build123d as bd
        from models3d.core import cut_half
        if d is None:
            d, up = VIEWS[kind]
        v = View(self, d, up, scale, ref3, at, name)
        solids, hatch_faces = [], []
        for k, (shp, num) in enumerate(shapes):
            if section is not None and num not in nocut:
                c = cut_half(shp, *section)
                if c is None or not c.faces():
                    continue
                solids.append(c)
                (px, py, pz), (nx, ny, nz) = section
                for f in c.faces():
                    vs = [q for q in f.vertices()]
                    if vs and all(abs((q.X - px) * nx + (q.Y - py) * ny + (q.Z - pz) * nz) < 1e-3 for q in vs):
                        hatch_faces.append((f, num if num is not None else k))
            else:
                if section is not None:       # 按不剖处理的零件：整个落在被移去的一侧（剖切面前面）的不画
                    (px, py, pz), (nx, ny, nz) = section
                    bb = shp.bounding_box()
                    corners = [(x, y, z) for x in (bb.min.X, bb.max.X) for y in (bb.min.Y, bb.max.Y) for z in (bb.min.Z, bb.max.Z)]
                    if all((x - px) * nx + (y - py) * ny + (z - pz) * nz > 1e-6 for x, y, z in corners):
                        continue
                solids.append(shp)
        comp = bd.Compound(children=solids)
        far = 5000
        org = (-d[0] * far, -d[1] * far, -d[2] * far)
        vis, hid = comp.project_to_viewport(org, viewport_up=up, look_at=(0, 0, 0))
        v.vis = _edges_to_polylines(vis, v)
        v.hid = _edges_to_polylines(hid, v) if hidden else []
        if phantom:                       # 工件等用双点画线画出（只画可见轮廓，不剖）
            pc = bd.Compound(children=[shp if section is None else (cut_half(shp, *section) or shp) for shp in phantom])
            pv, _ = pc.project_to_viewport(org, viewport_up=up, look_at=(0, 0, 0))
            v.phantom = _edges_to_polylines(pv, v)
        # 剖面线：同一零件同一方向，相邻零件换方向或间距
        styles = [(45, 3.0), (135, 3.0), (45, 1.8), (135, 1.8), (60, 2.5), (120, 2.5)]
        nums = []
        for f, num in hatch_faces:
            if num not in nums:
                nums.append(num)
            ang, gap = styles[nums.index(num) % len(styles)]
            loops = []
            for w in f.wires():
                pts = []
                for e in w.edges():
                    n = max(2, int(e.length / 1.0))
                    pts += [v.at((q.X, q.Y, q.Z)) for q in (e @ (i / n) for i in range(n + 1))]
                loops.append(pts)
            v.hatch.append((loops, ang, gap))
        self.views.append(v)
        return v

    # ------------------------------------------------------------ 标注
    def line(self, a, b, w=THIN, dash=None, color="#000"):
        da = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<line x1="{_f(a[0])}" y1="{_f(a[1])}" x2="{_f(b[0])}" y2="{_f(b[1])}" stroke="{color}" stroke-width="{w}"{da}/>')

    def text(self, p, s, size=3.5, anchor="middle", rot=0, color="#000", bold=False, baseline="auto"):
        tr = f' transform="rotate({_f(rot)} {_f(p[0])} {_f(p[1])})"' if rot else ""
        fw = ' font-weight="700"' if bold else ""
        self.items.append(f'<text x="{_f(p[0])}" y="{_f(p[1])}" font-size="{size}" font-family="{FONT}" text-anchor="{anchor}"'
                          f' fill="{color}"{fw}{tr} dominant-baseline="{baseline}">{escape(s)}</text>')

    def arrow(self, tip, ang, size=3.0, color="#000"):
        a1, a2 = ang + math.pi - 0.17, ang + math.pi + 0.17
        p1 = (tip[0] + size * math.cos(a1), tip[1] + size * math.sin(a1))
        p2 = (tip[0] + size * math.cos(a2), tip[1] + size * math.sin(a2))
        self.items.append(f'<path d="M{_f(tip[0])},{_f(tip[1])} L{_f(p1[0])},{_f(p1[1])} L{_f(p2[0])},{_f(p2[1])} Z" fill="{color}"/>')

    def dim(self, view: View, p1, p2, text, offset=10.0, orient="h", size=3.5, color="#000", ext=True, text_shift=0.0, dev=None):
        """线性尺寸：三维点 p1、p2 在视图上的水平（h）、竖直（v）或沿两点（a）方向的距离；offset 是尺寸线离 p1（h：向上为正；v：向左为正）的距离（图纸 mm）。"""
        a, b = view.at(p1), view.at(p2)
        if orient == "h":
            y = min(a[1], b[1]) - offset if offset >= 0 else max(a[1], b[1]) - offset
            A, B = (a[0], y), (b[0], y)
        elif orient == "v":
            x = min(a[0], b[0]) - offset if offset >= 0 else max(a[0], b[0]) - offset
            A, B = (x, a[1]), (x, b[1])
        else:
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy) or 1
            nx, ny = dy / L, -dx / L
            A, B = (a[0] + nx * offset, a[1] + ny * offset), (b[0] + nx * offset, b[1] + ny * offset)
        if ext:
            for P, Q in ((a, A), (b, B)):
                dx, dy = Q[0] - P[0], Q[1] - P[1]
                L = math.hypot(dx, dy)
                if L > 0.5:
                    ux, uy = dx / L, dy / L
                    self.line((P[0] + ux * 1.0, P[1] + uy * 1.0), (Q[0] + ux * 2.0, Q[1] + uy * 2.0), color=color)
        self.line(A, B, color=color)
        ang = math.atan2(B[1] - A[1], B[0] - A[0])
        L = math.hypot(B[0] - A[0], B[1] - A[1])
        tw = len(text) * size * 0.62
        if L < 9:          # 太短：箭头放到外面
            self.arrow(A, ang, color=color); self.arrow(B, ang + math.pi, color=color)
            self.line(A, (A[0] - 5 * math.cos(ang), A[1] - 5 * math.sin(ang)), color=color)
            self.line(B, (B[0] + 5 * math.cos(ang), B[1] + 5 * math.sin(ang)), color=color)
        else:
            self.arrow(B, ang, color=color); self.arrow(A, ang + math.pi, color=color)
        mx, my = (A[0] + B[0]) / 2 + text_shift * math.cos(ang), (A[1] + B[1]) / 2 + text_shift * math.sin(ang)
        deg = math.degrees(ang)
        if deg > 90.01 or deg < -90.01:
            deg = deg - 180 if deg > 0 else deg + 180
        # 文字在尺寸线上方（竖直尺寸在左侧，字头朝左）
        off = 1.0
        tx, ty = mx + off * math.sin(math.radians(deg)), my - off * math.cos(math.radians(deg))
        if dev is None:
            self.text((tx, ty), text, size, rot=deg, color=color)
        else:                              # 上、下偏差叠写在基本尺寸之后（字高小一号，GB/T 4458.5）
            es, ei = dev
            fmt = lambda v: "0" if abs(v) < 1e-12 else f"{v:+g}".replace("-", "−")  # noqa: E731
            sz = size * 0.72
            wm = len(text) * size * 0.6
            wd = max(len(fmt(es)), len(fmt(ei))) * sz * 0.6
            x0 = tx - (wm + wd + 0.8) / 2
            g = [f'<g transform="rotate({_f(deg)} {_f(tx)} {_f(ty)})" font-family="{FONT}" fill="{color}">',
                 f'<text x="{_f(x0)}" y="{_f(ty)}" font-size="{size}">{escape(text)}</text>',
                 f'<text x="{_f(x0 + wm + 0.8)}" y="{_f(ty - size * 0.55)}" font-size="{_f(sz)}">{escape(fmt(es))}</text>',
                 f'<text x="{_f(x0 + wm + 0.8)}" y="{_f(ty + size * 0.1)}" font-size="{_f(sz)}">{escape(fmt(ei))}</text>', "</g>"]
            self.items.append("".join(g))
        return tw

    def dia_dim(self, view: View, p_axis, d, text, along=(1, 0, 0), offset=0.0, size=3.5):
        """回转面的直径尺寸：在轴线上 p_axis 处，沿视图竖直方向标两条素线之间的距离。"""
        ux, uy = view.up[0], view.up[1]
        up = view.up
        p1 = tuple(p_axis[i] - up[i] * d / 2 for i in range(3))
        p2 = tuple(p_axis[i] + up[i] * d / 2 for i in range(3))
        a, b = view.at(p1), view.at(p2)
        x = a[0] + offset
        self.line((x, a[1]), (x, b[1]))
        self.arrow((x, a[1]), math.pi / 2); self.arrow((x, b[1]), -math.pi / 2)
        self.text((x - 1.0, (a[1] + b[1]) / 2), text, size, rot=-90)

    def angle_dim(self, view: View, apex, d1, d2, r, text, size=3.5):
        """角度尺寸：顶点 apex（三维），两条边的方向 d1、d2（三维），尺寸线是半径 r（图纸 mm）的圆弧，两端箭头，文字在弧中间外侧。"""
        c = view.at(apex)
        def ang(d):
            q = view.at(tuple(apex[i] + d[i] for i in range(3)))
            return math.atan2(q[1] - c[1], q[0] - c[0])
        a1, a2 = ang(d1), ang(d2)
        if (a2 - a1) % (2 * math.pi) > math.pi:
            a1, a2 = a2, a1
        span = (a2 - a1) % (2 * math.pi)
        n = 24
        pts = [(c[0] + r * math.cos(a1 + span * i / n), c[1] + r * math.sin(a1 + span * i / n)) for i in range(n + 1)]
        self.items.append('<polyline points="' + " ".join(f"{_f(x)},{_f(y)}" for x, y in pts) + f'" fill="none" stroke="#000" stroke-width="{THIN}"/>')
        self.arrow(pts[0], a1 - math.pi / 2)
        self.arrow(pts[-1], a2 + math.pi / 2)
        am = a1 + span / 2
        self.text((c[0] + (r + 4) * math.cos(am), c[1] + (r + 4) * math.sin(am) + size * 0.36), text, size)

    def balloon(self, p, q, text, r=3.5, size=3.5):
        """零件序号：引线从零件上的点 p（图纸坐标）到序号圆 q；圆圈、编号。"""
        dx, dy = p[0] - q[0], p[1] - q[1]
        L = math.hypot(dx, dy) or 1
        self.line((q[0] + dx / L * r, q[1] + dy / L * r), p)
        self.items.append(f'<circle cx="{_f(p[0])}" cy="{_f(p[1])}" r="0.6" fill="#000"/>')
        self.items.append(f'<circle cx="{_f(q[0])}" cy="{_f(q[1])}" r="{r}" fill="#fff" stroke="#000" stroke-width="{THIN}"/>')
        self.text((q[0], q[1] + size * 0.36), text, size)

    def balloon_row(self, view: View, items, along="x", at=None, gap=10.0, r=3.5):
        """一排零件序号：items = [(序号, 三维点)]；along = "x" 时序号排成水平一行（at 为行的 y），"y" 时排成竖直一列（at 为列的 x）。
        按指示点的位置排序，间距不小于 gap。"""
        pts = sorted(((str(n), view.at(p)) for n, p in items), key=lambda t: t[1][0] if along == "x" else t[1][1])
        last = -1e9
        for n, p in pts:
            c = p[0] if along == "x" else p[1]
            c = max(c, last + gap)
            last = c
            q = (c, at) if along == "x" else (at, c)
            self.balloon(p, q, n, r)

    def leader_note(self, p, q, text, size=3.5):
        """引出说明：从 p 引到 q，水平线上写字。"""
        self.line(p, q)
        tw = len(text) * size * 0.9
        right = q[0] >= p[0]
        q2 = (q[0] + (tw if right else -tw), q[1])
        self.line(q, q2)
        self.arrow(p, math.atan2(p[1] - q[1], p[0] - q[0]), 2.5)
        self.text(((q[0] + q2[0]) / 2, q[1] - 1.0), text, size)

    def gdt(self, p, q, symbol, value, datum="", size=3.5, via=None):
        """形位公差框格：引线从被测要素 p 指向框格左端 q（箭头在 p）。via：引线的折点（箭头沿 p→via 方向，
        便于让箭头垂直于被测表面或与尺寸线对齐，GB/T 1182）。"""
        cells = [symbol, value] + ([datum] if datum else [])
        h = size * 2
        ws = [h] + [max(h, len(c) * size * 0.65 + 2) for c in cells[1:]]
        x = q[0]
        for c, w in zip(cells, ws):
            self.items.append(f'<rect x="{_f(x)}" y="{_f(q[1] - h / 2)}" width="{_f(w)}" height="{_f(h)}" fill="#fff" stroke="#000" stroke-width="{THIN}"/>')
            if c == "⌯":                 # 对称度符号：三条横线，中间长（字体里多半没有这个字符，画出来）
                cx, cy = x + w / 2, q[1]
                for dy, hw in ((-1.4, 1.6), (0, 2.6), (1.4, 1.6)):
                    self.line((cx - hw, cy + dy), (cx + hw, cy + dy))
            else:
                self.text((x + w / 2, q[1] + size * 0.36), c, size)
            x += w
        if via is not None:
            self.line(p, via)
            self.line(via, (q[0], q[1]))
            self.arrow(p, math.atan2(p[1] - via[1], p[0] - via[0]), 2.5)
        else:
            self.line(p, (q[0], q[1]))
            self.arrow(p, math.atan2(p[1] - q[1], p[0] - q[0]), 2.5)

    def datum(self, p, letter, direction=(0, 1), size=3.5):
        """基准符号（GB/T 1182）：涂黑三角形贴在要素上，连线到方框和字母。direction：从要素指向方框（图纸坐标）。"""
        dx, dy = direction
        L = math.hypot(dx, dy) or 1
        dx, dy = dx / L, dy / L
        nx, ny = -dy, dx
        t1 = (p[0] + nx * 1.8, p[1] + ny * 1.8)
        t2 = (p[0] - nx * 1.8, p[1] - ny * 1.8)
        t3 = (p[0] + dx * 2.2, p[1] + dy * 2.2)
        self.items.append(f'<path d="M{_f(t1[0])},{_f(t1[1])} L{_f(t2[0])},{_f(t2[1])} L{_f(t3[0])},{_f(t3[1])} Z" fill="#000"/>')
        q = (p[0] + dx * 8, p[1] + dy * 8)
        self.line(t3, q)
        s = size * 2
        self.items.append(f'<rect x="{_f(q[0] - s / 2)}" y="{_f(q[1] - s / 2 + dy * s / 2)}" width="{_f(s)}" height="{_f(s)}" fill="#fff" stroke="#000" stroke-width="{THIN}"/>')
        self.text((q[0], q[1] + dy * s / 2 + size * 0.36), letter, size)

    def roughness(self, p, ra, ang=0, size=3.5, removal=True):
        """表面粗糙度符号（GB/T 131）：尖端在 p，符号朝上（ang 为整体转角，度）。"""
        h1 = size * 1.4
        pts = [(-h1 * 0.58, -h1), (0, 0), (h1 * 1.2, -h1 * 2.1)]
        g = [f'<g transform="translate({_f(p[0])},{_f(p[1])}) rotate({_f(ang)})">']
        g.append(f'<polyline points="{" ".join(f"{_f(a)},{_f(b)}" for a, b in pts)}" fill="none" stroke="#000" stroke-width="{THIN}"/>')
        if removal:
            g.append(f'<line x1="{_f(-h1 * 0.58)}" y1="{_f(-h1)}" x2="{_f(h1 * 0.58)}" y2="{_f(-h1)}" stroke="#000" stroke-width="{THIN}"/>')
        g.append(f'<line x1="{_f(h1 * 1.2)}" y1="{_f(-h1 * 2.1)}" x2="{_f(h1 * 1.2 + len(ra) * size * 0.62 + 2)}" y2="{_f(-h1 * 2.1)}" stroke="#000" stroke-width="{THIN}"/>')
        # GB/T 131-2006：参数写在长横线的下方（位置 a）
        g.append(f'<text x="{_f(h1 * 1.2 + 0.8)}" y="{_f(-h1 * 2.1 + size * 1.05)}" font-size="{size}" font-family="{FONT}">{escape(ra)}</text>')
        g.append("</g>")
        self.items.append("".join(g))

    def roughness_rest(self, at, ra, size=3.5):
        """其余表面的粗糙度（GB/T 131-2006）：标题栏附近写“符号 + 参数”，后面括号里画一个基本符号，表示图上另有标注。"""
        x, y = at
        self.roughness((x, y), ra, size=size)
        h1 = size * 1.4
        xb = x + h1 * 1.2 + len(ra) * size * 0.62 + 6
        self.text((xb, y - 1), "（", size, anchor="middle")
        self.roughness((xb + 4.5, y), "", size=size * 0.8)
        self.text((xb + 11, y - 1), "）", size, anchor="middle")

    def centerline(self, view: View, p1, p2, extend=3.0):
        a, b = view.at(p1), view.at(p2)
        dx, dy = b[0] - a[0], b[1] - a[1]
        L = math.hypot(dx, dy) or 1
        ux, uy = dx / L, dy / L
        self.line((a[0] - ux * extend, a[1] - uy * extend), (b[0] + ux * extend, b[1] + uy * extend), dash="8 1.5 1 1.5")

    def center_mark(self, view: View, p, r):
        c = view.at(p)
        e = r * view.scale + 3
        self.line((c[0] - e, c[1]), (c[0] + e, c[1]), dash="8 1.5 1 1.5")
        self.line((c[0], c[1] - e), (c[0], c[1] + e), dash="8 1.5 1 1.5")

    def section_label(self, view: View, p1, p2, letter, look_dir=(0, -1), size=5):
        """剖切位置符号：两端粗短画、箭头表示投射方向、字母。"""
        a, b = view.at(p1), view.at(p2)
        for P in (a, b):
            self.line((P[0], P[1] - 3), (P[0], P[1] + 3), w=0.7)
        for P in (a, b):
            q = (P[0], P[1] + (-5 if P[1] <= min(a[1], b[1]) else 5))
            self.text((P[0] + 2.5, q[1]), letter, size, anchor="start")

    def note(self, p, s, size=3.5, anchor="start", bold=False):
        self.text(p, s, size, anchor=anchor, bold=bold)

    def requirements(self, items, at):
        self.req, self.req_at = list(items), at

    def bom(self, rows):
        """明细栏（GB/T 10609.2）：rows = [(序号, 代号, 名称, 数量, 材料, 备注)]，从下往上画在标题栏上方。"""
        self.bom_rows = list(rows)

    # ------------------------------------------------------------ 输出
    def _frame(self):
        W, H = self.W, self.H
        x0, y0, x1, y1 = 25, 5, W - 5, H - 5          # 装订边 25，其余 5（A3/A4 不留装订边时也可以，书中统一留）
        s = [f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff" stroke="#000" stroke-width="{THIN}"/>',
             f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="none" stroke="#000" stroke-width="0.7"/>']
        # 标题栏 180 × 56（简化的 GB/T 10609.1 格式）
        tx, ty = x1 - 180, y1 - 56
        R = lambda x, y, w, h, wt=THIN: s.append(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="none" stroke="#000" stroke-width="{wt}"/>')  # noqa: E731
        R(tx, ty, 180, 56, 0.7)
        T = lambda x, y, t, sz=3.5, a="middle", b=False: s.append(  # noqa: E731
            f'<text x="{_f(x)}" y="{_f(y)}" font-size="{sz}" font-family="{FONT}" text-anchor="{a}"{" font-weight=\"700\"" if b else ""}>{escape(str(t))}</text>')
        # 左半：签署区 4 行 × (职务, 姓名, 日期)
        for i, (role, who) in enumerate((("设计", self.designer), ("审核", self.checker), ("工艺", ""), ("批准", ""))):
            y = ty + 24 + i * 8
            R(tx, y, 12, 8); R(tx + 12, y, 24, 8); R(tx + 36, y, 22, 8)
            T(tx + 6, y + 5.5, role); T(tx + 24, y + 5.5, who, 3); T(tx + 47, y + 5.5, self.date if i == 0 else "", 3)
        R(tx, ty, 58, 24)
        T(tx + 29, ty + 9, self.company, 4.5, b=True)
        T(tx + 29, ty + 17, self.sheet_no, 3)
        # 中：材料、比例、数量、质量
        R(tx + 58, ty, 72, 18); T(tx + 94, ty + 12, self.material, 5)
        for i, (k, val) in enumerate((("比例", self.scale_text), ("数量", self.qty), ("质量", self.mass))):
            x = tx + 58 + i * 24
            R(x, ty + 18, 24, 8); R(x, ty + 26, 24, 8)
            T(x + 12, ty + 23.5, k); T(x + 12, ty + 31.5, val)
        R(tx + 58, ty + 34, 72, 22)
        # 第一角画法的投影符号（GB/T 14692）：截锥的主视图（梯形，小端在右），左视图（两个同心圆）放在它的右边
        cx, cy = tx + 86, ty + 46
        s.append(f'<path d="M{_f(cx - 9)},{_f(cy - 4)} L{_f(cx - 1)},{_f(cy - 2)} L{_f(cx - 1)},{_f(cy + 2)} L{_f(cx - 9)},{_f(cy + 4)} Z" fill="none" stroke="#000" stroke-width="{THIN}"/>')
        s.append(f'<line x1="{_f(cx - 11)}" y1="{_f(cy)}" x2="{_f(cx + 1)}" y2="{_f(cy)}" stroke="#000" stroke-width="0.18" stroke-dasharray="3 0.8 0.6 0.8"/>')
        s.append(f'<circle cx="{_f(cx + 8)}" cy="{_f(cy)}" r="4" fill="none" stroke="#000" stroke-width="{THIN}"/>')
        s.append(f'<circle cx="{_f(cx + 8)}" cy="{_f(cy)}" r="2" fill="none" stroke="#000" stroke-width="{THIN}"/>')
        # 右：图名、图号
        R(tx + 130, ty, 50, 28); T(tx + 155, ty + 17, self.title, 6 if len(self.title) <= 7 else 4.5, b=True)
        R(tx + 130, ty + 28, 50, 28); T(tx + 155, ty + 45, self.code, 5)
        # 明细栏：在标题栏上方，自下而上
        if self.bom_rows:
            cols = [("序号", 10), ("代号", 40), ("名称", 44), ("数量", 10), ("材料", 22), ("备注", 54)]
            rh = 7
            yb = ty
            R(tx, yb - rh, 180, rh)
            x = tx
            for name, w in cols:
                R(x, yb - rh, w, rh); T(x + w / 2, yb - 2.2, name, 3.2)
                x += w
            for k, row in enumerate(self.bom_rows):
                y = yb - rh * (k + 2)
                x = tx
                for (name, w), val in zip(cols, row):
                    R(x, y, w, rh)
                    val = str(val)
                    fs = 3.2 if len(val) * 3.2 * 0.95 < w - 1 else max(1.9, (w - 1.5) / (len(val) * 0.95))
                    T(x + w / 2, y + 4.8, val, fs)
                    x += w
        return s

    def svg(self) -> str:
        W, H = self.W, self.H
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}" '
               f'stroke-linecap="round" stroke-linejoin="round">']
        out += self._frame()
        for v in self.views:
            for loops, ang, gap in v.hatch:
                out.append(_hatch_svg(loops, ang, gap))
            for pl in _dedupe(v.hid, v.vis):
                out.append(_poly(pl, THIN, "3 1.2"))
            for pl in v.vis:
                out.append(_poly(pl, THICK))
            for pl in v.phantom:
                out.append(_poly(pl, THIN, "6 1.2 0.8 1.2 0.8 1.2"))
            if v.name:
                xs = [p[0] for pl in v.vis for p in pl]
                ys = [p[1] for pl in v.vis for p in pl]
                if xs:
                    out.append(f'<text x="{_f((min(xs) + max(xs)) / 2)}" y="{_f(min(ys) - 6)}" font-size="5" font-family="{FONT}" '
                               f'text-anchor="middle">{escape(v.name)}</text>')
        out += self.items
        if self.req:
            x, y = self.req_at
            out.append(f'<text x="{_f(x)}" y="{_f(y)}" font-size="5" font-family="{FONT}">技术要求</text>')
            for i, r in enumerate(self.req, 1):
                for j, line in enumerate(_wrap(f"{i}. {r}", 46)):
                    out.append(f'<text x="{_f(x + (0 if j == 0 else 4))}" y="{_f(y + 7 + (i - 1) * 0 + self._req_line(i, j))}" '
                               f'font-size="3.5" font-family="{FONT}">{escape(line)}</text>')
        out.append("</svg>")
        return "\n".join(out)

    def _req_line(self, i, j):
        n = sum(len(_wrap(f"{k}. {r}", 46)) for k, r in enumerate(self.req[:i - 1], 1))
        return (n + j) * 5.2

    def bbox_free(self):
        """图框内可用区域（去掉标题栏与明细栏）：(x0, y0, x1, y1)。"""
        return 25, 5, self.W - 5, self.H - 5 - 56 - 7 * (len(self.bom_rows) + 1 if self.bom_rows else 0)


def _wrap(s, n):
    out, cur = [], ""
    for ch in s:
        cur += ch
        if len(cur) >= n:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def _poly(pl, w, dash=None):
    da = f' stroke-dasharray="{dash}"' if dash else ""
    pts = " ".join(f"{_f(x)},{_f(y)}" for x, y in pl)
    return f'<polyline points="{pts}" fill="none" stroke="#000" stroke-width="{w}"{da}/>'


def _hatch_svg(loops, ang_deg, gap):
    """剖面线：与水平成 ang 的等距细实线，按奇偶规则裁剪在多边形（含孔）以内。"""
    a = math.radians(ang_deg)
    ux, uy = math.cos(a), -math.sin(a)          # 图纸 y 向下：45° 线向右上
    nx, ny = -uy, ux
    pts = [p for l in loops for p in l]
    if not pts:
        return ""
    ds = [p[0] * nx + p[1] * ny for p in pts]
    segs = []
    k0, k1 = math.floor(min(ds) / gap), math.ceil(max(ds) / gap)
    edges = [(l[i], l[(i + 1) % len(l)]) for l in loops for i in range(len(l))]
    for k in range(k0, k1 + 1):
        c = k * gap
        ts = []
        for p, q in edges:
            dp, dq = p[0] * nx + p[1] * ny - c, q[0] * nx + q[1] * ny - c
            if (dp > 0) != (dq > 0):
                t = dp / (dp - dq)
                x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
                ts.append(x * ux + y * uy)
        ts.sort()
        for i in range(0, len(ts) - 1, 2):
            s0, s1 = ts[i], ts[i + 1]
            segs.append(((c * nx + s0 * ux, c * ny + s0 * uy), (c * nx + s1 * ux, c * ny + s1 * uy)))
    return "".join(f'<line x1="{_f(p[0])}" y1="{_f(p[1])}" x2="{_f(q[0])}" y2="{_f(q[1])}" stroke="#000" stroke-width="{THIN}"/>'
                   for p, q in segs)
