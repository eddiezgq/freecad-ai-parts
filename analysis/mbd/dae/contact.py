"""接触几何、几何配对与接触力、直齿啮合（ADR-0097 D3，补充五）。

几何存在构件坐标系里（原点在质心；t = 0 构件系与地面同向），单位 SI。
配对函数在地面系里算，返回接触列表 [(P_a, P_b, n, δ)]：P_a、P_b 是两表面上的最近点，
n 是单位公法线，方向为“作用在 b 上的法向力”的方向，δ > 0 为穿透深度。
"""

from __future__ import annotations

import math

import numpy as np
from scipy.interpolate import CubicSpline

from analysis.mbd.dae.system import A_of

NEWTON_TOL = 1e-15            # m（曲线最近点牛顿迭代）


class ContactError(ValueError):
    pass


# ---------------------------------------------------------------- 几何
class Geometry:
    kind = ""

    def __init__(self, gid, body):
        self.id, self.body = gid, body

    def placed(self, r, A):
        raise NotImplementedError


class Sphere(Geometry):
    kind = "sphere"

    def __init__(self, gid, body, c, R):
        super().__init__(gid, body)
        self.c, self.R = np.asarray(c, float), float(R)

    def placed(self, r, A):
        return {"c": r + A @ self.c, "R": self.R}


class Plane(Geometry):
    kind = "plane"

    def __init__(self, gid, body, p, n, x=None, half=None):
        super().__init__(gid, body)
        self.p, self.n = np.asarray(p, float), _unit(n)
        if x is None:
            x = np.array([1.0, 0, 0]) if abs(self.n[0]) < 0.9 else np.array([0, 1.0, 0])
        x = np.asarray(x, float) - (np.asarray(x, float) @ self.n) * self.n
        if np.linalg.norm(x) < 1e-9:
            raise ContactError(f"平面 {gid} 的 x_axis 不能与法向平行")
        self.x = x / np.linalg.norm(x)
        self.half = None if half is None else np.asarray(half, float)

    def placed(self, r, A):
        return {"p": r + A @ self.p, "n": A @ self.n, "x": A @ self.x, "half": self.half}


class Cylinder(Geometry):
    kind = "cylinder"

    def __init__(self, gid, body, c, a, R, L):
        super().__init__(gid, body)
        self.c, self.a, self.R, self.L = np.asarray(c, float), _unit(a), float(R), float(L)

    def placed(self, r, A):
        return {"c": r + A @ self.c, "a": A @ self.a, "R": self.R, "L": self.L}


class Curve(Geometry):
    """平面闭合轮廓：C(u)（u 为弧长参数，周期 Lc），材料在曲线围成的一侧"""
    kind = "curve"

    def __init__(self, gid, body, origin, n, x, pts2, closed=True, method="cubic"):
        super().__init__(gid, body)
        if not closed:
            raise ContactError(f"曲线 {gid}：D3 只支持闭合轮廓")
        self.o, self.n = np.asarray(origin, float), _unit(n)
        x = np.asarray(x, float) - (np.asarray(x, float) @ self.n) * self.n
        if np.linalg.norm(x) < 1e-9:
            raise ContactError(f"曲线 {gid} 的 x_axis 不能与法向平行")
        self.ex = x / np.linalg.norm(x)
        self.ey = np.cross(self.n, self.ex)
        P = np.asarray(pts2, float)
        if np.allclose(P[0], P[-1]):
            P = P[:-1]
        if len(P) < 3:
            raise ContactError(f"曲线 {gid} 至少要 3 个不同的点")
        area = 0.5 * np.sum(P[:, 0] * np.roll(P[:, 1], -1) - np.roll(P[:, 0], -1) * P[:, 1])
        if abs(area) < 1e-18:
            raise ContactError(f"曲线 {gid} 围成的面积为 0")
        if area < 0:                     # 统一成逆时针，外法向 = (y', −x')
            P = P[::-1]
        Pc = np.vstack([P, P[:1]])
        seg = np.linalg.norm(np.diff(Pc, axis=0), axis=1)
        if np.any(seg < 1e-12):
            raise ContactError(f"曲线 {gid} 有重合点")
        u = np.concatenate([[0.0], np.cumsum(seg)])
        self.Lc = float(u[-1])
        self.linear = method == "linear"
        if self.linear:
            self.u, self.P = u, Pc
        else:
            self.sp = CubicSpline(u, Pc, bc_type="periodic")
        ns = max(400, 8 * len(P))
        self.us = np.linspace(0, self.Lc, ns, endpoint=False)
        self.samp = np.array([self.eval(s)[0] for s in self.us])

    def eval(self, s):
        """2D 平面坐标：C、C'、C''"""
        s = s % self.Lc
        if not self.linear:
            return self.sp(s), self.sp(s, 1), self.sp(s, 2)
        k = int(np.searchsorted(self.u, s, side="right") - 1)
        k = min(max(k, 0), len(self.u) - 2)
        d = (self.P[k + 1] - self.P[k]) / (self.u[k + 1] - self.u[k])
        return self.P[k] + d * (s - self.u[k]), d, np.zeros(2)

    def placed(self, r, A):
        return {"o": r + A @ self.o, "ex": A @ self.ex, "ey": A @ self.ey, "n": A @ self.n, "curve": self}


class Mesh(Geometry):
    kind = "mesh"

    def __init__(self, gid, body, verts, faces):
        super().__init__(gid, body)
        self.v = np.asarray(verts, float)
        self.f = np.asarray(faces, int)
        if self.f.max() >= len(self.v):
            raise ContactError(f"网格 {gid} 的面引用了不存在的顶点")
        c = self.v.mean(axis=0)
        for tri in self.f:
            a, b, d = self.v[tri]
            nrm = np.cross(b - a, d - a)
            if np.linalg.norm(nrm) < 1e-20:
                raise ContactError(f"网格 {gid} 有退化三角形")
            if nrm @ (a - c) < 0:
                raise ContactError(f"网格 {gid} 的面法向要朝外（逆时针），或网格不是凸体")

    def placed(self, r, A):
        return {"v": r + self.v @ A.T, "f": self.f}


def _unit(x):
    a = np.asarray(x, float)
    n = np.linalg.norm(a)
    if n < 1e-12:
        raise ContactError("方向不能是零向量")
    return a / n


# ---------------------------------------------------------------- 配对
def _flip(cs):
    return [(Pb, Pa, -n, d) for Pa, Pb, n, d in cs]


def sphere_sphere(a, b):
    d = b["c"] - a["c"]
    L = float(np.linalg.norm(d))
    dep = a["R"] + b["R"] - L
    if dep <= 0 or L < 1e-15:
        return []
    n = d / L
    return [(a["c"] + a["R"] * n, b["c"] - b["R"] * n, n, dep)]


def _in_plane(pl, P):
    if pl["half"] is None:
        return True
    w = P - pl["p"]
    y = np.cross(pl["n"], pl["x"])
    return abs(w @ pl["x"]) <= pl["half"][0] and abs(w @ y) <= pl["half"][1]


def plane_point(pl, P, R=0.0):
    """点（或半径 R 的球心）对平面：返回 (平面上的点, 物体上的点, n, δ) 或 None；n 为平面外法向（作用在物体上的方向）"""
    s = float((P - pl["p"]) @ pl["n"])
    dep = R - s
    if dep <= 0:
        return None
    foot = P - s * pl["n"]
    if not _in_plane(pl, foot):
        return None
    return (foot, P - R * pl["n"], pl["n"], dep)


def plane_sphere(pl, sp):
    c = plane_point(pl, sp["c"], sp["R"])
    return [c] if c else []


def _closest_on_cyl_surface(cy, P):
    """圆柱侧面 + 两端圆边上离 P 最近的点（P 在圆柱外）"""
    a = cy["a"]
    w = P - cy["c"]
    t = float(w @ a)
    radial = w - t * a
    rho = float(np.linalg.norm(radial))
    e = radial / rho if rho > 1e-15 else _perp(a)
    h = cy["L"] / 2
    if abs(t) <= h:
        return cy["c"] + t * a + cy["R"] * e
    return cy["c"] + math.copysign(h, t) * a + cy["R"] * e


def _perp(a):
    v = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    v = v - (v @ a) * a
    return v / np.linalg.norm(v)


def cylinder_sphere(cy, sp):
    Q = _closest_on_cyl_surface(cy, sp["c"])
    d = sp["c"] - Q
    L = float(np.linalg.norm(d))
    dep = sp["R"] - L
    if dep <= 0 or L < 1e-15:
        return []
    n = d / L
    return [(Q, sp["c"] - sp["R"] * n, n, dep)]


def plane_cylinder(pl, cy):
    """圆柱两端圆边上离平面最深的点各算一个接触（躺着时两点，立着时端面圆边四点）"""
    a, n = cy["a"], pl["n"]
    w = -n + (n @ a) * a
    h = cy["L"] / 2
    out = []
    if np.linalg.norm(w) > 1e-9:
        dirs = [w / np.linalg.norm(w)]
    else:
        e1 = _perp(a)
        e2 = np.cross(a, e1)
        dirs = [e1, -e1, e2, -e2]
    for sgn in (-1, 1):
        for e in dirs:
            c = plane_point(pl, cy["c"] + sgn * h * a + cy["R"] * e)
            if c:
                out.append(c)
    return out


def _curve_world(cv, s):
    C, d1, d2 = cv["curve"].eval(s)
    return (cv["o"] + C[0] * cv["ex"] + C[1] * cv["ey"], d1[0] * cv["ex"] + d1[1] * cv["ey"],
            d2[0] * cv["ex"] + d2[1] * cv["ey"])


def _outward(cv, d1):
    t = d1 / np.linalg.norm(d1)
    return np.cross(t, cv["n"])          # 逆时针曲线：t × n 朝外


def curve_plane(cv, pl):
    """曲线上对平面最深的点（凸轮对平底从动件）"""
    crv = cv["curve"]
    n = pl["n"]
    n2 = np.array([n @ cv["ex"], n @ cv["ey"]])
    if np.linalg.norm(n2) < 1e-9:
        raise ContactError("曲线与平面接触时，平面法向要在曲线平面内")
    base = cv["o"] - pl["p"]
    vals = (base @ n) + crv.samp @ n2
    s = float(crv.us[int(np.argmin(vals))])
    if not crv.linear:
        for _ in range(50):
            _, d1, d2 = crv.eval(s)
            g, gp = float(d1 @ n2), float(d2 @ n2)
            if gp <= 0:
                break
            ds = -g / gp
            s += ds
            if abs(ds) < NEWTON_TOL:
                break
    P = _curve_world(cv, s)[0]
    c = plane_point(pl, P)
    return _flip([c]) if c else []


def _curve_closest(cv, P):
    crv = cv["curve"]
    w = P - cv["o"]
    p2 = np.array([w @ cv["ex"], w @ cv["ey"]])
    k = int(np.argmin(np.sum((crv.samp - p2) ** 2, axis=1)))
    s = float(crv.us[k])
    if crv.linear:
        best = None
        for j in (k - 1, k):
            a, b = crv.eval(crv.us[j % len(crv.us)])[0], crv.eval(crv.us[(j + 1) % len(crv.us)])[0]
            ab = b - a
            tt = min(1.0, max(0.0, float((p2 - a) @ ab / (ab @ ab))))
            q = a + tt * ab
            dq = float(np.linalg.norm(p2 - q))
            if best is None or dq < best[0]:
                best = (dq, crv.us[j % len(crv.us)] + tt * (crv.us[1] - crv.us[0]))
        s = best[1]
    else:
        for _ in range(50):
            C, d1, d2 = crv.eval(s)
            g = float((C - p2) @ d1)
            gp = float(d1 @ d1 + (C - p2) @ d2)
            if gp <= 0:
                break
            ds = -g / gp
            s += ds
            if abs(ds) < NEWTON_TOL:
                break
    return _curve_world(cv, s)


def curve_circle(cv, c, R):
    Q, d1, _ = _curve_closest(cv, c)
    out = _outward(cv, d1)
    d = c - Q
    d = d - (d @ cv["n"]) * cv["n"]
    L = float(np.linalg.norm(d))
    sgn = 1.0 if d @ out >= 0 else -1.0
    dep = R - sgn * L
    if dep <= 0:
        return []
    n = out if L < 1e-15 else sgn * d / L
    return [(Q, c - R * n, n, dep)]


def curve_sphere(cv, sp):
    return curve_circle(cv, sp["c"], sp["R"])


def curve_cylinder(cv, cy):
    if abs(cy["a"] @ cv["n"]) < 0.999:
        raise ContactError("曲线与圆柱（滚子）接触时，圆柱轴线要垂直于曲线平面")
    c = cy["c"] - ((cy["c"] - cv["o"]) @ cv["n"]) * cv["n"]
    return curve_circle(cv, c, cy["R"])


def mesh_plane(me, pl):
    out = []
    for v in me["v"]:
        c = plane_point(pl, v)
        if c:
            out.append(c)
    return _flip(out)


def _closest_on_triangle(p, a, b, c):
    """Ericson《Real-Time Collision Detection》5.1.5"""
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = ab @ ap, ac @ ap
    if d1 <= 0 and d2 <= 0:
        return a
    bp = p - b
    d3, d4 = ab @ bp, ac @ bp
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return a + d1 / (d1 - d3) * ab
    cp = p - c
    d5, d6 = ab @ cp, ac @ cp
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return a + d2 / (d2 - d6) * ac
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        return b + (d4 - d3) / ((d4 - d3) + (d5 - d6)) * (c - b)
    den = 1.0 / (va + vb + vc)
    return a + ab * vb * den + ac * vc * den


def mesh_sphere(me, sp):
    c = sp["c"]
    best = None
    for tri in me["f"]:
        a, b, d = me["v"][tri]
        Q = _closest_on_triangle(c, a, b, d)
        L = float(np.linalg.norm(c - Q))
        if best is None or L < best[0]:
            best = (L, Q)
    L, Q = best
    dep = sp["R"] - L
    if dep <= 0 or L < 1e-15:
        return []
    n = (c - Q) / L
    return [(Q, c - sp["R"] * n, n, dep)]


PAIRS = {("sphere", "sphere"): sphere_sphere, ("plane", "sphere"): plane_sphere, ("cylinder", "sphere"): cylinder_sphere,
         ("plane", "cylinder"): plane_cylinder, ("curve", "plane"): curve_plane, ("curve", "sphere"): curve_sphere,
         ("curve", "cylinder"): curve_cylinder, ("mesh", "plane"): mesh_plane, ("mesh", "sphere"): mesh_sphere}


def pair_function(ka, kb):
    """(函数, 是否交换) 或抛错"""
    if (ka, kb) in PAIRS:
        return PAIRS[(ka, kb)], False
    if (kb, ka) in PAIRS:
        return PAIRS[(kb, ka)], True
    raise ContactError(f"暂不支持 {ka} 与 {kb} 的接触（支持的配对见 ADR-0097 补充五）")


# ---------------------------------------------------------------- 力
def _mu(fr, v):
    from analysis.mbd.dae.system import _smooth
    a = abs(v)
    if a <= fr["vs"]:
        return fr["ms"] * _smooth(a / fr["vs"])
    if a < fr["vt"]:
        return fr["ms"] + (fr["md"] - fr["ms"]) * _smooth((a - fr["vs"]) / (fr["vt"] - fr["vs"]))
    return fr["md"]


def contact_wrenches(sysm, q, qd, f, F, N):
    """接触对 f 的力加到 F、N（地面系）；返回本次各接触点 (位置, 法向力, 摩擦力) 供结果输出"""
    ga, gb = f["ga"], f["gb"]
    pa = ga.placed(*_pose(sysm, q, ga.body))
    pb = gb.placed(*_pose(sysm, q, gb.body))
    cs = f["fn"](pb, pa) if f["swap"] else f["fn"](pa, pb)
    if f["swap"]:
        cs = _flip(cs)
    out = []
    for Pa, Pb, n, dep in cs:
        M = 0.5 * (Pa + Pb)
        va, vb = _vel(sysm, q, qd, ga.body, M), _vel(sysm, q, qd, gb.body, M)
        dv = vb - va
        depd = -float(dv @ n)
        damp = f["c"] if dep >= f["d"] else f["c"] * (dep / f["d"]) ** 2 * (3 - 2 * dep / f["d"])
        Fn = max(0.0, f["k"] * dep ** f["e"] + damp * depd)
        Fv = Fn * n
        Ft = np.zeros(3)
        fr = f.get("friction")
        if fr and Fn > 0:
            vt = dv - (dv @ n) * n
            sp = float(np.linalg.norm(vt))
            if sp > 0:
                Ft = -_mu(fr, sp) * Fn * vt / sp
        sysm._add(F, N, q, gb.body, Fv + Ft, M)
        sysm._add(F, N, q, ga.body, -(Fv + Ft), M)
        out.append((M, Fn, float(np.linalg.norm(Ft))))
    return out


def _pose(sysm, q, b):
    if b < 0:
        return np.zeros(3), np.eye(3)
    r, p = sysm.rp(q, b)
    return r, A_of(p)


def _vel(sysm, q, qd, b, P):
    if b < 0:
        return np.zeros(3)
    r = sysm.rp(q, b)[0]
    return qd[7 * b:7 * b + 3] + np.cross(sysm.omega(q, qd, b), P - r)


def gear_wrenches(sysm, q, qd, g, F, N):
    """直齿外啮合：沿啮合线的弹性力，作用在节点"""
    j1, j2 = sysm.joints[g["joint_i"]], sysm.joints[g["joint_j"]]
    a1, w1 = sysm.joint_kin(q, qd, j1)[:2]
    a2, w2 = sysm.joint_kin(q, qd, j2)[:2]
    s = g["s"]
    delta = math.remainder(g["rb1"] * a1 + s * g["rb2"] * a2, g["pb"])
    ddot = g["rb1"] * w1 + s * g["rb2"] * w2
    h = sysm.joint_frame(q, j1)[2]
    c1 = sysm._pv(q, qd, j1["j"], j1["sj"])[0]
    c2 = sysm._pv(q, qd, j2["j"], j2["sj"])[0]
    u = c2 - c1
    u = u - (u @ h) * h
    u /= np.linalg.norm(u)
    t = np.cross(h, u)
    P = c1 + g["rp1"] * u
    half = g["b"] / 2
    ca, sa = math.cos(g["alpha"]), math.sin(g["alpha"])
    if delta > half:
        mag = g["k"] * (delta - half) + g["c"] * ddot
        lv = ca * t + sa * u
    elif delta < -half:
        mag = g["k"] * (-delta - half) - g["c"] * ddot
        lv = -(ca * t - sa * u)
    else:
        return 0.0
    mag = max(0.0, mag)
    sysm._add(F, N, q, j2["j"], mag * lv, P)
    sysm._add(F, N, q, j1["j"], -mag * lv, P)
    return mag
