"""三向 dexel 材料去除（ADR-0106 Q2 第 1 步）。

毛坯用三组平行射线表示：沿 X、沿 Y、沿 Z 各一组，射线穿过网格中心（间距 h），每根射线存它在材料里的区间。
刀具扫过时，从每根射线上减去刀具扫过的区间。三组射线一起用：
- 体积：三组各自算（区间长度 × 格面积），取平均；
- 表面：每个区间端点就是材料表面上的一点（带法向所在的轴），画在制毛坯、比色差都用它。

刀具是回转体：从刀尖沿刀轴往上，一串截圆锥（平底、钻头）加可选的一个球（球头）；牛鼻刀的圆角用 8 段截圆锥内接逼近，
少切不超过圆角半径的 0.5%（1 − cos(π/32)）。刀轴方向任意（3+2、五轴）。
刀具是凸的、一段走刀里刀轴不变时扫过的体积也是凸的，一根射线和它的交是一段区间：按走刀方向取若干刀位（间距不超过 h），
每个刀位求射线与刀具的交，取最小进入、最大离开。刀位之间漏切的深度不超过 step²/(8R)（R 刀具半径），h = 0.2、R = 5 时约 0.0003 mm。
刀轴在一段走刀里变（五轴联动）时，把这段按刀轴转角不超过 2° 拆开，每一小段按刀轴不变算。

纯 numpy，不调用 FreeCAD；长度 mm。
"""

from __future__ import annotations

import math

import numpy as np

AIR = np.nan
_EPS = 1e-9


# ---------------------------------------------------------------- 刀具
class Tool:
    """回转体刀具：frusta = [(z0, z1, r0, r1), …]（离刀尖的距离 z，半径 r），sphere = (球心离刀尖的距离, 半径) 或 None。
    所有部分合起来是凸的（平底、球头、牛鼻、钻头都是）。"""

    def __init__(self, frusta, sphere=None):
        self.frusta = [tuple(float(v) for v in f) for f in frusta]
        self.sphere = None if sphere is None else (float(sphere[0]), float(sphere[1]))
        self.length = max([f[1] for f in self.frusta] + ([sum(self.sphere)] if self.sphere else []))
        self.radius = max([max(f[2], f[3]) for f in self.frusta] + ([self.sphere[1]] if self.sphere else []))

    @classmethod
    def from_spec(cls, spec: dict) -> Tool:
        """spec：{"kind": endmill | ballend | bullnose | drill, "d": 直径, "L": 刃长或伸出长（缺省 3d）,
        "corner_r": 牛鼻圆角, "tip_angle": 钻头顶角（缺省 118°）}"""
        d = float(spec["d"])
        R = d / 2
        L = float(spec.get("L") or 3 * d)
        kind = spec.get("kind", "endmill")
        if kind == "ballend":
            return cls([(R, max(L, R + _EPS), R, R)], sphere=(R, R))
        if kind == "bullnose":
            rc = float(spec["corner_r"])
            if not 0 < rc <= R:
                raise ValueError(f"牛鼻刀圆角 {rc} 要在 0 和半径 {R} 之间")
            fr = []
            for i in range(8):                   # 圆角：圆心在 (R − rc, rc)，从刀底 (R − rc, 0) 转到侧面 (R, rc)
                a0, a1 = -math.pi / 2 + i * math.pi / 16, -math.pi / 2 + (i + 1) * math.pi / 16
                z0, z1 = rc + rc * math.sin(a0), rc + rc * math.sin(a1)
                r0, r1 = R - rc + rc * math.cos(a0), R - rc + rc * math.cos(a1)
                fr.append((z0, z1, r0, r1))
            fr.append((0.0, _EPS, 0.0, R - rc))  # 刀底平面
            fr.append((rc, max(L, rc + _EPS), R, R))
            return cls(fr)
        if kind == "drill":
            ang = math.radians(float(spec.get("tip_angle") or 118.0))
            hc = R / math.tan(ang / 2)
            return cls([(0.0, hc, 0.0, R), (hc, max(L, hc + _EPS), R, R)])
        return cls([(0.0, L, R, R)])

    def bbox(self, tip, w):
        """刀尖在 tip、刀轴 w（单位向量，刀尖指向主轴）时的包围盒"""
        tip = np.asarray(tip, float)
        w = np.asarray(w, float)
        ext = np.sqrt(np.clip(1.0 - w * w, 0.0, None))
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        rings = [(f[0], f[2]) for f in self.frusta] + [(f[1], f[3]) for f in self.frusta]
        if self.sphere:
            c, r = self.sphere
            lo = np.minimum(lo, tip + c * w - r)
            hi = np.maximum(hi, tip + c * w + r)
        for z, r in rings:
            p = tip + z * w
            lo = np.minimum(lo, p - r * ext)
            hi = np.maximum(hi, p + r * ext)
        return lo, hi


def _ray_tool(o, d, tip, w, tool: Tool):
    """射线 o + t·d（d 是坐标轴方向）与刀具的交，逐对算。o、tip、w:(P,3) → t_in, t_out:(P,)，不相交为 nan。"""
    rel = o - tip
    wd = w @ d                                                   # 射线方向在刀轴上的分量 (P,)
    pz = np.einsum("pk,pk->p", rel, w)                           # 刀轴方向坐标
    perp0 = rel - pz[:, None] * w                                # 垂直刀轴的分量
    dperp = d[None, :] - wd[:, None] * w
    a = np.einsum("pk,pk->p", dperp, dperp)
    b = 2 * np.einsum("pk,pk->p", perp0, dperp)
    c = np.einsum("pk,pk->p", perp0, perp0)
    P = len(pz)
    t_in = np.full(P, np.inf)
    t_out = np.full(P, -np.inf)
    big = np.full(P, 1e9)
    with np.errstate(divide="ignore", invalid="ignore"):
        for z0, z1, r0, r1 in tool.frusta:
            k = (r1 - r0) / max(z1 - z0, _EPS)
            g0 = r0 - k * z0                                     # 半径 g(z) = g0 + k z
            # 条件：|perp(t)|² ≤ g(z(t))²，g ≥ 0，z0 ≤ z(t) ≤ z1；z(t) = pz + t·wd
            gp = g0 + k * pz
            A = a - (k * wd) ** 2
            B = b - 2 * k * wd * gp
            C = c - gp * gp
            disc = B * B - 4 * A * C
            sq = np.sqrt(np.where(disc >= 0, disc, np.nan))
            lin = np.abs(A) < 1e-12
            cand = [-big, big, np.where(lin, -C / B, (-B - sq) / (2 * A)), np.where(lin, np.nan, (-B + sq) / (2 * A)),
                    (z0 - pz) / wd, (z1 - pz) / wd]
            if abs(k) > 1e-12:
                cand.append((-g0 / k - pz) / wd)
            T = np.stack(cand, -1)
            T = np.where(np.isfinite(T), T, np.nan)
            T = np.sort(T, -1)                                   # nan 排在最后
            mid = 0.5 * (T[:, :-1] + T[:, 1:])
            zm = pz[:, None] + mid * wd[:, None]
            rr = a[:, None] * mid * mid + b[:, None] * mid + c[:, None]
            gm = g0 + k * zm
            ok = (zm >= z0 - 1e-9) & (zm <= z1 + 1e-9) & (gm >= -1e-12) & (rr <= gm * gm + 1e-9) & np.isfinite(mid)
            t_in = np.minimum(t_in, np.where(ok, T[:, :-1], np.inf).min(-1))
            t_out = np.maximum(t_out, np.where(ok, T[:, 1:], -np.inf).max(-1))
    if tool.sphere:
        cz, R = tool.sphere
        q = rel - cz * w
        qb = q @ d
        qc = np.einsum("pk,pk->p", q, q) - R * R
        disc = qb * qb - qc
        sq = np.sqrt(np.where(disc >= 0, disc, np.nan))
        hit = disc >= 0
        t_in = np.where(hit, np.minimum(t_in, -qb - sq), t_in)
        t_out = np.where(hit, np.maximum(t_out, -qb + sq), t_out)
    miss = ~(t_out > t_in)
    t_in[miss] = np.nan
    t_out[miss] = np.nan
    return t_in, t_out


# ---------------------------------------------------------------- 毛坯
class Dexel:
    """三向 dexel。lo、hi：包围盒；h：射线间距。S[k]、E[k]：沿第 k 轴的射线，形状 (n_u, n_v, K)，区间 [S, E)，空位 nan。"""

    def __init__(self, lo, hi, h):
        self.lo = np.asarray(lo, float)
        self.hi = np.asarray(hi, float)
        self.h = float(h)
        self.n = np.maximum(1, np.ceil((self.hi - self.lo) / self.h).astype(int))
        self.c = [self.lo[i] + (np.arange(self.n[i]) + 0.5) * self.h for i in range(3)]
        self.S, self.E = [], []
        for k in range(3):
            u, v = [i for i in range(3) if i != k]
            self.S.append(np.full((self.n[u], self.n[v], 1), np.nan))
            self.E.append(np.full((self.n[u], self.n[v], 1), np.nan))

    # ---- 建毛坯
    @classmethod
    def box(cls, lo, hi, h, pad=0.0):
        """长方体毛坯；网格比毛坯大 pad（刀具在毛坯外面也要有射线可减）"""
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        dx = cls(lo - pad, hi + pad, h)
        dx.fill(lambda k, U, V: _box_interval(k, U, V, lo, hi))
        return dx

    @classmethod
    def from_triangles(cls, tri, h, lo=None, hi=None):
        """封闭三角网格（tri: (n,3,3)）→ dexel：每根射线与三角形求交，交点排序后两两配成区间（奇偶规则）"""
        tri = np.asarray(tri, float)
        lo = tri.reshape(-1, 3).min(0) if lo is None else np.asarray(lo, float)
        hi = tri.reshape(-1, 3).max(0) if hi is None else np.asarray(hi, float)
        dx = cls(lo, hi, h)
        for k in range(3):
            dx._set_from_triangles(k, tri)
        return dx

    def fill(self, interval):
        """interval(k, U, V) → (s, e) 数组：每根射线一个区间（nan 表示没有材料）"""
        for k in range(3):
            u, v = [i for i in range(3) if i != k]
            U, V = np.meshgrid(self.c[u], self.c[v], indexing="ij")
            s, e = interval(k, U, V)
            self.S[k] = np.asarray(s, float)[..., None]
            self.E[k] = np.asarray(e, float)[..., None]

    def _set_from_triangles(self, k, tri):
        u, v = [i for i in range(3) if i != k]
        U, V = np.meshgrid(self.c[u], self.c[v], indexing="ij")
        # 射线挪开一点点（无理数倍的 1e-7·h）：正好穿过三角形公共边、顶点时只算进一个三角形，不重不漏
        U, V = U + 1.234567e-7 * math.pi * self.h, V + 0.987654e-7 * math.e * self.h
        hits = [[[] for _ in range(self.n[v])] for _ in range(self.n[u])]
        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        for i in range(len(tri)):                 # 每个三角形只看它投影包围盒里的射线
            pu = np.array([a[i, u], b[i, u], c[i, u]])
            pv = np.array([a[i, v], b[i, v], c[i, v]])
            i0 = max(0, int(np.ceil((pu.min() - self.lo[u]) / self.h - 0.5)))
            i1 = min(self.n[u] - 1, int(np.floor((pu.max() - self.lo[u]) / self.h - 0.5)))
            j0 = max(0, int(np.ceil((pv.min() - self.lo[v]) / self.h - 0.5)))
            j1 = min(self.n[v] - 1, int(np.floor((pv.max() - self.lo[v]) / self.h - 0.5)))
            if i1 < i0 or j1 < j0:
                continue
            uu, vv = U[i0:i1 + 1, j0:j1 + 1], V[i0:i1 + 1, j0:j1 + 1]
            # 投影到 (u, v) 平面的重心坐标
            x0, y0, x1, y1, x2, y2 = pu[0], pv[0], pu[1], pv[1], pu[2], pv[2]
            den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
            if abs(den) < 1e-14:
                continue
            l0 = ((y1 - y2) * (uu - x2) + (x2 - x1) * (vv - y2)) / den
            l1 = ((y2 - y0) * (uu - x2) + (x0 - x2) * (vv - y2)) / den
            l2 = 1 - l0 - l1
            ok = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
            t = l0 * a[i, k] + l1 * b[i, k] + l2 * c[i, k]
            for ii, jj in zip(*np.nonzero(ok), strict=True):
                hits[i0 + ii][j0 + jj].append(float(t[ii, jj]))
        K = max(1, max((len(h) for row in hits for h in row), default=0) // 2)
        S = np.full((self.n[u], self.n[v], K), np.nan)
        E = np.full((self.n[u], self.n[v], K), np.nan)
        for i in range(self.n[u]):
            for j in range(self.n[v]):
                h = sorted(hits[i][j])
                for q in range(len(h) // 2):
                    S[i, j, q], E[i, j, q] = h[2 * q], h[2 * q + 1]
        self.S[k], self.E[k] = S, E

    def copy(self) -> Dexel:
        dx = Dexel.__new__(Dexel)
        dx.lo, dx.hi, dx.h, dx.n, dx.c = self.lo, self.hi, self.h, self.n, self.c
        dx.S = [s.copy() for s in self.S]
        dx.E = [e.copy() for e in self.E]
        return dx

    # ---- 量
    def lengths(self, k):
        return np.nansum(self.E[k] - self.S[k], -1)

    def volume(self, k=None):
        """体积 mm³；k 给定时只用那一组射线，否则三组平均"""
        if k is not None:
            return float(self.lengths(k).sum() * self.h * self.h)
        return float(np.mean([self.volume(i) for i in range(3)]))

    # ---- 切
    def subtract(self, k, iu, iv, a, b):
        """从第 k 组的射线 (iu, iv) 上减去区间 [a, b]（数组，等长）。返回每根射线被切掉的长度。"""
        S, E = self.S[k][iu, iv], self.E[k][iu, iv]            # (n, K)
        a, b = a[:, None], b[:, None]
        before = np.nansum(E - S, -1)
        ls, le = S, np.minimum(E, a)                             # 左边剩下的
        rs, re = np.maximum(S, b), E                             # 右边剩下的
        lok, rok = le > ls + 1e-12, re > rs + 1e-12
        NS = np.concatenate([np.where(lok, ls, np.nan), np.where(rok, rs, np.nan)], -1)
        NE = np.concatenate([np.where(lok, le, np.nan), np.where(rok, re, np.nan)], -1)
        order = np.argsort(np.where(np.isnan(NS), np.inf, NS), -1)
        NS = np.take_along_axis(NS, order, -1)
        NE = np.take_along_axis(NE, order, -1)
        Kn = max(1, int((~np.isnan(NS)).sum(-1).max()) if NS.size else 1)
        Kold = self.S[k].shape[2]
        if Kn > Kold:                                             # 区间变多：所有射线都加宽
            padw = Kn - Kold
            self.S[k] = np.concatenate([self.S[k], np.full(self.S[k].shape[:2] + (padw,), np.nan)], -1)
            self.E[k] = np.concatenate([self.E[k], np.full(self.E[k].shape[:2] + (padw,), np.nan)], -1)
        Kc = self.S[k].shape[2]
        if NS.shape[1] < Kc:
            fill = np.full((NS.shape[0], Kc - NS.shape[1]), np.nan)
            NS, NE = np.concatenate([NS, fill], -1), np.concatenate([NE, fill], -1)
        self.S[k][iu, iv] = NS[:, :Kc]
        self.E[k][iu, iv] = NE[:, :Kc]
        return before - np.nansum(NE[:, :Kc] - NS[:, :Kc], -1)

    def cut(self, tool: Tool, a, b, w=(0, 0, 1), w_end=None, step=None):
        """刀尖从 a 直线走到 b（刀轴 w，五轴联动时到 b 变成 w_end），从毛坯上减去扫过的体积。
        返回 {"volume": 切掉的体积 mm³（三组平均）, "depth": 沿刀轴方向最深切进多少（Z 组射线上量，竖直刀具时就是切深）}"""
        a, b = np.asarray(a, float), np.asarray(b, float)
        w0 = _unit(w)
        w1 = _unit(w_end) if w_end is not None else w0
        ang = math.degrees(math.acos(float(np.clip(w0 @ w1, -1, 1))))
        if ang > 2.0:                                             # 刀轴转得多：拆成小段
            n = math.ceil(ang / 2.0)
            out = {"volume": 0.0, "depth": 0.0}
            for i in range(n):
                s0, s1 = i / n, (i + 1) / n
                r = self.cut(tool, a + (b - a) * s0, a + (b - a) * s1, _slerp(w0, w1, s0), _slerp(w0, w1, s1), step)
                out["volume"] += r["volume"]
                out["depth"] = max(out["depth"], r["depth"])
            return out
        step = step or self.h
        vol, depth = 0.0, 0.0
        mvec = b - a
        lo0, hi0 = tool.bbox(a, w0)
        for k in range(3):
            u, v = [i for i in range(3) if i != k]
            d = np.zeros(3)
            d[k] = 1.0
            # 沿射线方向的平移只让交点整体挪动：刀位间距只看垂直射线的那部分位移（走刀与射线平行时首尾两个刀位就够）
            m = max(1, math.ceil(math.hypot(mvec[u], mvec[v]) / step))
            sv = np.linspace(0.0, 1.0, m + 1)
            tips = a[None] + mvec[None] * sv[:, None]
            ws = np.array([_slerp(w0, w1, x) for x in sv]) if w_end is not None else np.broadcast_to(w0, tips.shape)
            # 每个刀位只配它包围盒里的射线
            pi, ri, rj = [], [], []
            for q in range(len(sv)):
                if w_end is not None:
                    blo, bhi = tool.bbox(tips[q], ws[q])
                else:
                    blo, bhi = lo0 + tips[q] - a, hi0 + tips[q] - a
                i0, i1 = self._range(u, blo[u], bhi[u])
                j0, j1 = self._range(v, blo[v], bhi[v])
                if i1 < i0 or j1 < j0:
                    continue
                if blo[k] > self.hi[k] or bhi[k] < self.lo[k]:
                    continue
                II, JJ = np.meshgrid(np.arange(i0, i1 + 1), np.arange(j0, j1 + 1), indexing="ij")
                ri.append(II.ravel())
                rj.append(JJ.ravel())
                pi.append(np.full(II.size, q))
            if not ri:
                continue
            ri, rj, pi = np.concatenate(ri), np.concatenate(rj), np.concatenate(pi)
            has = ~np.isnan(self.S[k][ri, rj, 0])                # 没有材料的射线不用算
            ri, rj, pi = ri[has], rj[has], pi[has]
            if not len(ri):
                continue
            o = np.zeros((len(ri), 3))
            o[:, u], o[:, v] = self.c[u][ri], self.c[v][rj]
            ti, to = _ray_tool(o, d, tips[pi], ws[pi], tool)
            ok = ~np.isnan(ti)
            if not ok.any():
                continue
            key = ri[ok] * self.n[v] + rj[ok]
            uk, inv = np.unique(key, return_inverse=True)
            tin = np.full(len(uk), np.inf)
            tout = np.full(len(uk), -np.inf)
            np.minimum.at(tin, inv, ti[ok])
            np.maximum.at(tout, inv, to[ok])
            removed = self.subtract(k, uk // self.n[v], uk % self.n[v], tin, tout)
            vol += float(removed.sum()) * self.h * self.h / 3.0
            if k == 2:
                depth = max(depth, float(removed.max()))
        return {"volume": vol, "depth": depth}

    def _range(self, ax, lo, hi):
        i0 = max(0, math.ceil((lo - self.lo[ax]) / self.h - 0.5))
        i1 = min(self.n[ax] - 1, math.floor((hi - self.lo[ax]) / self.h - 0.5))
        return i0, i1

    # ---- 表面
    def surface_points(self):
        """材料表面上的点（各组射线的区间端点）：{"p": (n,3), "n": (n,3) 法向（朝材料外）}"""
        P, Nn = [], []
        for k in range(3):
            u, v = [i for i in range(3) if i != k]
            S, E = self.S[k], self.E[k]
            for arr, sign in ((S, -1.0), (E, 1.0)):
                ii, jj, qq = np.nonzero(~np.isnan(arr))
                p = np.zeros((len(ii), 3))
                p[:, u], p[:, v], p[:, k] = self.c[u][ii], self.c[v][jj], arr[ii, jj, qq]
                n = np.zeros((len(ii), 3))
                n[:, k] = sign
                P.append(p)
                Nn.append(n)
        return {"p": np.concatenate(P), "n": np.concatenate(Nn)}

    def z_mesh(self):
        """在制毛坯画成网格面：按 Z 组射线，每根射线的每个区间是一根小方柱（h × h），相邻方柱高度一样的面不画。
        返回 (顶点 (n,3), 三角形 (m,3))。"""
        S, E = self.S[2], self.E[2]
        h = self.h
        xs, ys = self.c[0], self.c[1]
        verts, tris = [], []

        def quad(p0, p1, p2, p3):
            i = len(verts)
            verts.extend([p0, p1, p2, p3])
            tris.extend([(i, i + 1, i + 2), (i, i + 2, i + 3)])

        nx, ny, K = S.shape
        for i in range(nx):
            x0, x1 = xs[i] - h / 2, xs[i] + h / 2
            for j in range(ny):
                y0, y1 = ys[j] - h / 2, ys[j] + h / 2
                for q in range(K):
                    s, e = S[i, j, q], E[i, j, q]
                    if np.isnan(s):
                        break
                    quad((x0, y0, e), (x1, y0, e), (x1, y1, e), (x0, y1, e))
                    quad((x0, y0, s), (x0, y1, s), (x1, y1, s), (x1, y0, s))
                    for di, dj, a0, a1 in ((1, 0, (x1, y0), (x1, y1)), (-1, 0, (x0, y1), (x0, y0)),
                                           (0, 1, (x1, y1), (x0, y1)), (0, -1, (x0, y0), (x1, y0))):
                        ni, nj = i + di, j + dj
                        segs = [(s, e)]
                        if 0 <= ni < nx and 0 <= nj < ny:
                            for q2 in range(K):
                                s2, e2 = S[ni, nj, q2], E[ni, nj, q2]
                                if np.isnan(s2):
                                    break
                                segs = _minus(segs, s2, e2)
                        for zs, ze in segs:
                            quad((*a0, zs), (*a1, zs), (*a1, ze), (*a0, ze))
        return np.asarray(verts, float).reshape(-1, 3), np.asarray(tris, int).reshape(-1, 3)


def _minus(segs, a, b):
    out = []
    for s, e in segs:
        if b <= s or a >= e:
            out.append((s, e))
            continue
        if a > s:
            out.append((s, a))
        if b < e:
            out.append((b, e))
    return out


def _box_interval(k, U, V, lo, hi):
    u, v = [i for i in range(3) if i != k]
    inside = (U >= lo[u]) & (U <= hi[u]) & (V >= lo[v]) & (V <= hi[v])
    return np.where(inside, lo[k], np.nan), np.where(inside, hi[k], np.nan)


def _unit(w):
    w = np.asarray(w, float)
    return w / np.linalg.norm(w)


def _slerp(a, b, t):
    cosang = float(np.clip(a @ b, -1, 1))
    ang = math.acos(cosang)
    if ang < 1e-9:
        return a.copy()
    return (math.sin((1 - t) * ang) * a + math.sin(t * ang) * b) / math.sin(ang)


# ---------------------------------------------------------------- 比对
def compare(stock: Dexel, part: Dexel, tol=0.01):
    """加工后的毛坯与零件（同一网格）比：毛坯表面上每一点（射线区间端点）到零件表面的距离，
    点在零件里面为负（过切），在外面为正（残留）。距离按到零件表面采样点（零件的区间端点）的最近距离算，误差不超过半个网格。
    返回 {"over_max": 最深过切 mm, "under_max": 最厚残留 mm, "over": 是否超过 tol, "at": 最深过切的位置, "points": {"p", "dev"}}"""
    if not (np.allclose(stock.lo, part.lo) and stock.h == part.h and (stock.n == part.n).all()):
        raise ValueError("毛坯和零件的 dexel 网格要一样（同 lo、h、大小）")
    pts = surface_deviation(stock, part)
    dev = pts["dev"]
    over = float(max(0.0, -dev.min())) if dev.size else 0.0
    under = float(max(0.0, dev.max())) if dev.size else 0.0
    at = pts["p"][int(dev.argmin())].tolist() if over > 0 else None
    return {"over_max": over, "under_max": under, "over": over > tol, "at": at, "points": pts}


def surface_deviation(stock: Dexel, part: Dexel):
    """毛坯表面点到零件表面的有符号距离：正 = 残留（毛坯比零件多），负 = 过切。
    里外按点所在的那根射线判断（零件在这根射线上的区间盖住它就在里面）。"""
    from scipy.spatial import cKDTree

    ref = part.surface_points()["p"]
    tree = cKDTree(ref) if len(ref) else None
    P, inside_all = [], []
    for k in range(3):
        u, v = [i for i in range(3) if i != k]
        S, E = stock.S[k], stock.E[k]
        PS, PE = part.S[k], part.E[k]
        for arr in (S, E):
            ii, jj, qq = np.nonzero(~np.isnan(arr))
            t = arr[ii, jj, qq]
            ps, pe = PS[ii, jj], PE[ii, jj]
            with np.errstate(invalid="ignore"):
                inside = ((t[:, None] > ps + 1e-9) & (t[:, None] < pe - 1e-9)).any(1)
            p = np.zeros((len(ii), 3))
            p[:, u], p[:, v], p[:, k] = stock.c[u][ii], stock.c[v][jj], t
            P.append(p)
            inside_all.append(inside)
    p = np.concatenate(P)
    inside = np.concatenate(inside_all)
    dist = tree.query(p)[0] if tree is not None else np.full(len(p), np.inf)
    return {"p": p, "dev": np.where(inside, -dist, dist)}


# ---------------------------------------------------------------- 按程序仿真
def simulate(parsed, stock: Dexel, tools: dict, part: Dexel | None = None, tol=0.01, keep_every=0, on_move=None):
    """按 sim.parse 的走刀在 dexel 毛坯上切（会改 stock）。tools：{刀号: Tool.from_spec 的 spec}；
    走刀可带 "axis"（刀轴，缺省 [0, 0, 1]）与 "axis_b"（走到终点时的刀轴，五轴联动）。
    keep_every > 0 时每隔这么多段存一份毛坯（回放拖时间轴用）。
    返回 {"issues", "moves": [{"i", "line", "volume", "depth"}], "removed", "checkpoints": [(段号, Dexel)], "compare"}"""
    built = {t: Tool.from_spec(s) for t, s in tools.items()}
    issues, out, removed = [], [], 0.0
    checkpoints = [(0, stock.copy())] if keep_every else []
    for i, mv in enumerate(parsed["moves"]):
        if on_move is not None:
            on_move(i, mv, stock)
        tl = built.get(mv["tool"])
        if tl is None or mv.get("home"):
            out.append({"i": i, "line": mv["line"], "volume": 0.0, "depth": 0.0})
            continue
        r = stock.cut(tl, mv["a"], mv["b"], w=mv.get("axis", (0, 0, 1)), w_end=mv.get("axis_b"))
        removed += r["volume"]
        out.append({"i": i, "line": mv["line"], **r})
        if r["volume"] > (stock.h ** 3) and mv["t"] == "rapid":
            issues.append({"line": mv["line"], "level": "error",
                           "text": f"快移撞到工件：切掉 {r['volume']:.1f} mm³（快移不能切削）"})
        if keep_every and (i + 1) % keep_every == 0:
            checkpoints.append((i + 1, stock.copy()))
    res = {"issues": issues, "moves": out, "removed": removed, "checkpoints": checkpoints}
    if part is not None:
        c = compare(stock, part, tol)
        res["compare"] = c
        if c["over"]:
            x, y, z = c["at"]
            issues.append({"line": None, "level": "error",
                           "text": f"过切：最多切进零件 {c['over_max']:.3f} mm，在 X{x:.2f} Y{y:.2f} Z{z:.2f} 附近（三维比对，误差半个网格）"})
    return res
