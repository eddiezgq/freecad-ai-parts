"""回放（ADR-0106 Q2 第 5 步）：把一个程序的仿真整理成按时间走的帧，供界面的回放条、程序窗口用。

- 帧：每段走刀一帧——程序行号、起止时间（按 sim.move_time，与程序时间一致）、刀尖起止点、刀号、快移 / 切削；
- 事件：检查清单里带行号的条目（碰撞、快移切削、超程……）挂到那一行的第一帧上，时间轴上标出来；
- 在制毛坯：铣削用 dexel（每隔若干段存一份，拖到任意一帧时从最近一份往后补切），车削用半径网格（每段存一份，数据小）。
  铣削画面用 Z 向 dexel 的顶面画（毛坯从上往下看到的样子，倒扣的部分不画）；车削画成回转面。
纯计算，不调用 FreeCAD。
"""

from __future__ import annotations

import bisect
import math

import numpy as np

from analysis.cam import dexel as DX
from analysis.cam import sim as S

MAX_CKPT = 60


class Replay:
    def __init__(self, gcode: str | None, machine: dict, replay_in: dict, checks=None, h=None, keep_every=20):
        """gcode 为 None（整机仿真不通过、没出程序）时用 replay_in 里留下的仿真程序"""
        gcode = gcode or replay_in.get("gcode") or ""
        self.gcode = gcode
        self.lines = gcode.splitlines()
        self.machine = machine
        self.kind = replay_in["kind"]
        self.parsed = S.parse(gcode, machine)
        self.lathe = self.parsed["lathe"]
        self.tools = {int(k): v for k, v in (replay_in.get("tools") or {}).items()}
        self.frames = []
        t = 0.0
        tc = float(machine.get("tool_change_s") or 0.0)
        changes = sorted(self.parsed["tool_changes"])
        k = 0
        for i, mv in enumerate(self.parsed["moves"]):
            while k < len(changes) and changes[k] <= mv["line"]:   # 换刀时间放在换刀后第一段前面（与程序时间一致）
                t += tc
                k += 1
            dt = S.move_time(mv, machine, self.lathe)
            self.frames.append({"i": i, "line": mv["line"], "t0": t, "t1": t + dt, "a": tuple(mv["a"]), "b": tuple(mv["b"]),
                                "tool": mv["tool"], "rapid": mv["t"] == "rapid", "home": bool(mv.get("home"))})
            t += dt
        self.duration = t + tc * (len(changes) - k)
        self._t0 = [f["t0"] for f in self.frames]
        self.events = []
        by_line = {}
        for f in self.frames:
            by_line.setdefault(f["line"], f["i"])
        for c in checks or []:
            if c.get("line") is not None and c["line"] in by_line:
                self.events.append({"i": by_line[c["line"]], "line": c["line"], "level": c["level"], "text": c["text"]})
        self.events.sort(key=lambda e: e["i"])
        self.keep_every = keep_every
        self._stock_in = replay_in.get("stock") or {}
        self._target = replay_in.get("target") or {}
        self._h = h
        self._built = False

    # ---- 时间与位置
    def frame_at(self, t: float) -> int:
        """时间 t（秒）所在的帧号"""
        if not self.frames:
            return 0
        return max(0, min(len(self.frames) - 1, bisect.bisect_right(self._t0, t) - 1))

    def frames_of_line(self, line: int) -> list[int]:
        return [f["i"] for f in self.frames if f["line"] == line]

    def tip(self, i: int, s: float = 1.0) -> tuple[float, float, float]:
        """第 i 帧走到 s（0–1）时刀尖在工件坐标里的位置；车床返回 (半径, 0, z)"""
        f = self.frames[i]
        a, b = np.asarray(f["a"], float), np.asarray(f["b"], float)
        p = a + (b - a) * s
        if self.lathe:
            return (float(p[0] / 2), 0.0, float(p[2]))
        return tuple(float(v) for v in p)

    def at(self, t: float) -> tuple[int, float]:
        """时间 t → (帧号, 帧内比例)"""
        i = self.frame_at(t)
        f = self.frames[i]
        dt = f["t1"] - f["t0"]
        return i, (0.0 if dt <= 0 else min(1.0, max(0.0, (t - f["t0"]) / dt)))

    def nearest_frame(self, p, max_dist=None) -> int | None:
        """离点 p（工件坐标）最近的那段走刀（点视图里的刀路跳到那一行用）"""
        p = np.asarray(p, float)
        best, bi = math.inf, None
        for f in self.frames:
            if f["home"]:
                continue
            a, b = np.asarray(self.tip(f["i"], 0.0)), np.asarray(self.tip(f["i"], 1.0))
            ab = b - a
            L2 = float(ab @ ab)
            s = 0.0 if L2 < 1e-12 else min(1.0, max(0.0, float((p - a) @ ab) / L2))
            d = float(np.linalg.norm(a + ab * s - p))
            if d < best:
                best, bi = d, f["i"]
        return bi if max_dist is None or best <= max_dist else None

    # ---- 在制毛坯
    def _build(self):
        if self._built:
            return
        if self.lathe:
            st = self._stock_in
            stock = {k: float(v) for k, v in st.items() if k in ("d", "z_right", "z_left", "bore_d")}
            self._hist = []
            S.simulate_turn(self.parsed, stock, self.tools, h=self._h or 0.05, history=self._hist)
        else:
            st = self._stock_in
            x0, y0, x1, y1 = (float(v) for v in st["box"])
            top = float(st.get("top", 0.0))
            depth = max([top - min(f["b"][2] for f in self.frames)] + [1.0])
            height = float(st.get("height") or depth + 5.0)
            h = self._h or max(0.2, max(x1 - x0, y1 - y0) / 250.0)
            pad = max([v.get("d", 10.0) for v in self.tools.values()] + [10.0])
            self._stock0 = DX.Dexel.box([x0, y0, top - height], [x1, y1, top], h, pad=pad)
            self._specs = {k: {**v, "L": v.get("L") or 3 * v.get("d", 10.0)} for k, v in self.tools.items()}
            self._ckpt = {0: self._stock0.copy()}
            dx = self._stock0.copy()
            built = {k: DX.Tool.from_spec(v) for k, v in self._specs.items()}
            self._volume = [0.0]
            every = max(self.keep_every, math.ceil(len(self.frames) / MAX_CKPT))   # 检查点最多 MAX_CKPT 份（曲面程序十几万段，每 20 段存一份会耗尽内存）
            for f in self.frames:
                tl = built.get(f["tool"])
                if tl is not None and not f["home"]:
                    r = dx.cut(tl, f["a"], f["b"])
                    self._volume.append(self._volume[-1] + r["volume"])
                else:
                    self._volume.append(self._volume[-1])
                if (f["i"] + 1) % every == 0:
                    self._ckpt[f["i"] + 1] = dx.copy()
            self._final = dx
        self._built = True

    def stock_after(self, n: int):
        """前 n 段走完以后的在制毛坯：铣 → Dexel；车 → (z, r, ri)"""
        self._build()
        n = max(0, min(n, len(self.frames)))
        if self.lathe:
            if n == 0:
                return self._hist[0][0], self._hist[0][1], self._hist[0][2]
            return self._hist[n]
        if n == len(self.frames):
            return self._final
        k = max(c for c in self._ckpt if c <= n)
        dx = self._ckpt[k].copy()
        built = {t: DX.Tool.from_spec(v) for t, v in self._specs.items()}
        for f in self.frames[k:n]:
            tl = built.get(f["tool"])
            if tl is not None and not f["home"]:
                dx.cut(tl, f["a"], f["b"])
        return dx

    def removed_volume(self, n: int) -> float:
        """铣：前 n 段一共切掉的体积（mm³）"""
        self._build()
        return self._volume[n] if not self.lathe else float("nan")


def height_mesh(dx: DX.Dexel, stride: int = 1, cells: bool = False):
    """铣削在制毛坯画面：Z 向 dexel 每根射线的最高点当顶面高度，画成“高度场方块”网格（顶面 + 相邻高度差处的侧面 + 外围侧面）。
    返回 (顶点 (n,3), 三角形 (m,3))；cells=True 时再加每个三角形属于哪一格 (m, 2)（色差上色用）。
    没有材料的格不画。stride > 1 时隔格取（大网格时画得快）。"""
    E = dx.E[2][::stride, ::stride]
    S0 = dx.S[2][::stride, ::stride]
    top = np.where(np.isnan(E), np.nan, E)
    top = np.fmax.reduce(np.nan_to_num(top, nan=-np.inf), -1)
    bot = np.fmin.reduce(np.nan_to_num(S0, nan=np.inf), -1)
    has = np.isfinite(top)
    h = dx.h * stride
    xs, ys = dx.c[0][::stride], dx.c[1][::stride]
    nx, ny = top.shape
    V, T, C = [], [], []

    def quads(p0, p1, p2, p3, ci, cj):
        base = sum(len(v) for v in V)
        n = len(p0)
        if not n:
            return
        V.append(np.concatenate([p0, p1, p2, p3]))
        idx = np.arange(n)
        T.append(np.stack([base + idx, base + n + idx, base + 2 * n + idx], 1))
        T.append(np.stack([base + idx, base + 2 * n + idx, base + 3 * n + idx], 1))
        cc = np.stack([ci, cj], 1) * stride
        C.extend([cc, cc])

    I, J = np.nonzero(has)
    x0, x1 = xs[I] - h / 2, xs[I] + h / 2
    y0, y1 = ys[J] - h / 2, ys[J] + h / 2
    z = top[I, J]
    quads(np.stack([x0, y0, z], 1), np.stack([x1, y0, z], 1), np.stack([x1, y1, z], 1), np.stack([x0, y1, z], 1), I, J)
    zb = bot[I, J]
    quads(np.stack([x0, y0, zb], 1), np.stack([x0, y1, zb], 1), np.stack([x1, y1, zb], 1), np.stack([x1, y0, zb], 1), I, J)
    # 侧面：本格比邻格高的那一段
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        ni, nj = I + di, J + dj
        inside = (ni >= 0) & (ni < nx) & (nj >= 0) & (nj < ny)
        nt = np.full(len(I), -np.inf)
        nt[inside] = top[ni[inside], nj[inside]]
        nt = np.where(np.isfinite(nt), np.maximum(nt, zb), zb)
        sel = z > nt + 1e-9
        if not sel.any():
            continue
        if di:
            xx = (x1 if di == 1 else x0)[sel]
            ya, yb = (y0[sel], y1[sel]) if di == 1 else (y1[sel], y0[sel])
            pa, pb = np.stack([xx, ya], 1), np.stack([xx, yb], 1)
        else:
            yy = (y1 if dj == 1 else y0)[sel]
            xa_, xb_ = (x1[sel], x0[sel]) if dj == 1 else (x0[sel], x1[sel])
            pa, pb = np.stack([xa_, yy], 1), np.stack([xb_, yy], 1)
        lo, hi = nt[sel], z[sel]
        quads(np.column_stack([pa, lo]), np.column_stack([pb, lo]), np.column_stack([pb, hi]), np.column_stack([pa, hi]),
              I[sel], J[sel])
    if not V:
        empty = (np.zeros((0, 3)), np.zeros((0, 3), int))
        return (*empty, np.zeros((0, 2), int)) if cells else empty
    if cells:
        return np.concatenate(V), np.concatenate(T), np.concatenate(C)
    return np.concatenate(V), np.concatenate(T)


def lathe_mesh(z, r, ri=None, seg=48, stride=5):
    """车削在制毛坯：半径网格旋成回转面（外圆面 + 内孔面 + 两端环面）。返回 (顶点, 三角形)"""
    z, r = np.asarray(z)[::stride], np.asarray(r)[::stride]
    ri = np.zeros_like(r) if ri is None else np.asarray(ri)[::stride]
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    c, s = np.cos(ang), np.sin(ang)
    V, T = [], []

    def surface(rad):
        base = sum(len(v) for v in V)
        n = len(z)
        pts = np.stack([rad[:, None] * c[None, :], rad[:, None] * s[None, :], np.repeat(z[:, None], seg, 1)], -1).reshape(-1, 3)
        V.append(pts)
        tris = []
        for i in range(n - 1):
            if rad[i] <= 1e-9 and rad[i + 1] <= 1e-9:
                continue
            a = base + i * seg + np.arange(seg)
            b = base + i * seg + (np.arange(seg) + 1) % seg
            a2, b2 = a + seg, b + seg
            tris.append(np.stack([a, b, b2], 1))
            tris.append(np.stack([a, b2, a2], 1))
        if tris:
            T.append(np.concatenate(tris))

    solid = r > ri + 1e-9
    surface(np.where(solid, r, 0.0))
    if (ri > 1e-9).any():
        surface(np.where(solid, ri, 0.0))
    if not V:
        return np.zeros((0, 3)), np.zeros((0, 3), int)
    return np.concatenate(V), (np.concatenate(T) if T else np.zeros((0, 3), int))


def lathe_deviation(rp: Replay, tol=0.01, seg=48, stride=5):
    """车削：加工完的半径网格与目标轮廓（replay_in 的 target，外圆与内孔）比，给色差图用。
    返回 {"over_max", "under_max", "tol", "mesh": (顶点, 三角形, 每个三角形的偏差)}；偏差正 = 残留，负 = 过切（半径方向）"""
    from analysis.cam.paths import d_at

    z, r, ri = rp.stock_after(len(rp.frames))
    tg = rp._target if hasattr(rp, "_target") else {}
    outer = tg.get("outer")
    if not outer:
        return None
    zt = min(zz for zz, _ in outer)
    rt = np.array([d_at(outer, zz) / 2 for zz in z])
    dev_o = np.where((z <= 0) & (z >= zt), r - rt, 0.0)
    for zr, w, db in tg.get("grooves") or []:
        g = (z <= zr + 1e-9) & (z >= zr - w - 1e-9)
        dev_o = np.where(g, r - db / 2, dev_o)
    for t in tg.get("threads") or []:
        t = S._thread_entry(t)
        if not t["internal"]:
            dev_o = np.where((z <= t["za"]) & (z >= t["zb"]), 0.0, dev_o)   # 螺纹段按整圈切，不上色
    v, t = lathe_mesh(z, r, ri, seg=seg, stride=stride)
    zs = np.asarray(z)[::stride]
    do = dev_o[::stride]
    outer_tri = t.max(1) < len(zs) * seg                              # 外圆面的顶点在最前面
    dev = np.zeros(len(t))
    dev[outer_tri] = do[np.minimum(t[outer_tri].min(1) // seg, len(do) - 1)]
    return {"over_max": float(max(0.0, -dev_o.min())), "under_max": float(max(0.0, dev_o.max())), "tol": tol,
            "mesh": (v, t, dev)}
