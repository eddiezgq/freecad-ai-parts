"""多体系统内核（ADR-0097 D1）：绝对坐标 + 欧拉参数，运动副与驱动是代数约束（Haug《Computer-Aided Kinematics and
Dynamics of Mechanical Systems》的写法）。内部只用 SI：m、kg、s、rad、N、N·m。

每个构件 7 个坐标 q_i = [r(3), p(4)]，p = [e0, e1, e2, e3] 是欧拉参数；地面不占坐标。
    A(p) = (e0² − eᵀe)I + 2(e eᵀ + e0 ẽ)（齐次二次式）
    G(p) = [−e, −ẽ + e0 I]，E(p) = [−e, ẽ + e0 I]；ω′ = 2Gṗ（构件系），ω = 2Eṗ（地面系）
    B(p, a′) = ∂(A a′)/∂p = 2[(e0 I + ẽ)a′, e a′ᵀ − (e0 I + ẽ)ã′]
运动方程：M q̈ + Φ_qᵀ λ = Q，Φ_q q̈ = γ；M_i = diag(m I, 4GᵀJ′G)，Q_i = [F, 2Gᵀn′ + 8ĠᵀJ′Ġp]。

约束值、速度右端 ν = −Φ_t、加速度右端 γ 用“射流”算（坐标按 q + εq̇、时间按 t + ε 展开到二阶，二阶系数就是 −γ），
雅可比 Φ_q 用 B 矩阵解析写出；测试里拿射流的方向导数核对雅可比。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from analysis.mbd.dae.expr import Jet, compile_expr

I3 = np.eye(3)


def skew(a):
    return np.array([[0.0, -a[2], a[1]], [a[2], 0.0, -a[0]], [-a[1], a[0], 0.0]])


def A_of(p):
    """齐次二次式（不依赖 |p| = 1，B 矩阵就是它的精确导数）"""
    e0, e = p[0], p[1:]
    return (e0 * e0 - e @ e) * I3 + 2 * (np.outer(e, e) + e0 * skew(e))


def G_of(p):
    e0, e = p[0], p[1:]
    return np.column_stack([-e, -skew(e) + e0 * I3])


def E_of(p):
    e0, e = p[0], p[1:]
    return np.column_stack([-e, skew(e) + e0 * I3])


def B_of(p, a):
    e0, e = p[0], p[1:]
    m = e0 * I3 + skew(e)
    return 2 * np.column_stack([m @ a, np.outer(e, a) - m @ skew(a)])


# ---------------------------------------------------------------- 向量射流（值、一阶、二阶系数）
class V:
    __slots__ = ("d", "dd", "v")

    def __init__(self, v, d=None, dd=None):
        self.v = np.asarray(v, float)
        self.d = np.zeros_like(self.v) if d is None else np.asarray(d, float)
        self.dd = np.zeros_like(self.v) if dd is None else np.asarray(dd, float)

    def __add__(self, o):
        return V(self.v + o.v, self.d + o.d, self.dd + o.dd)

    def __sub__(self, o):
        return V(self.v - o.v, self.d - o.d, self.dd - o.dd)

    def scale(self, s: Jet):
        return V(self.v * s.v, self.d * s.v + self.v * s.d, self.dd * s.v + 2 * self.d * s.d + self.v * s.dd)

    def dot(self, o) -> Jet:
        return Jet(self.v @ o.v, self.d @ o.v + self.v @ o.d, self.dd @ o.v + 2 * self.d @ o.d + self.v @ o.dd)

    def cross(self, o):
        c = _cross
        return V(c(self.v, o.v), c(self.d, o.v) + c(self.v, o.d), c(self.dd, o.v) + 2 * c(self.d, o.d) + c(self.v, o.dd))


def _cross(a, b):
    return np.array([a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]])


def rot_jet(p: V, a):
    """A(p)·a′ 的射流（a′ 是构件上的常向量）：A a′ = (e0² − e·e)a′ + 2(e (e·a′) + e0 (e × a′))"""
    a = np.asarray(a, float)
    e0 = Jet(p.v[0], p.d[0], p.dd[0])
    e = V(p.v[1:], p.d[1:], p.dd[1:])
    ac = V(a)
    out = ac.scale(e0 * e0 - e.dot(e))
    return out + e.scale(e.dot(ac) * 2) + e.cross(ac).scale(e0 * 2)


# ---------------------------------------------------------------- 模型（内部 SI）
@dataclass
class Body:
    name: str
    mass: float
    J: np.ndarray                  # 构件系惯量（t = 0 时构件系与地面同向）
    r0: np.ndarray
    p0: np.ndarray = field(default_factory=lambda: np.array([1.0, 0, 0, 0]))
    v0: np.ndarray = field(default_factory=lambda: np.zeros(3))
    w0: np.ndarray = field(default_factory=lambda: np.zeros(3))


@dataclass
class Row:
    """一条约束方程。kind：sph（取第 k 个分量）、dot1、dot2、norm、rdrive、tdrive。"""
    kind: str
    i: int                         # 构件下标；−1 是地面
    j: int
    a_i: np.ndarray | None = None  # 构件 i 上的向量（构件系）
    a_j: np.ndarray | None = None
    s_i: np.ndarray | None = None  # 点（构件系，相对质心）
    s_j: np.ndarray | None = None
    k: int = 0
    b_i: np.ndarray | None = None  # 转动驱动用的第二个向量（g_i）
    fn: object = None              # 驱动函数（射流，SI）
    c: float = 0.0                 # 常数项（移动驱动的初始距离）
    joint: str = ""
    label: str = ""


class System:
    def __init__(self, bodies: list[Body], gravity):
        self.bodies = bodies
        self.nb = len(bodies)
        self.n = 7 * self.nb
        self.g = np.asarray(gravity, float)
        self.rows: list[Row] = []
        self.forces = []           # (kind, data)
        self.joints = {}           # id → dict(type, i, j, rows[], point s_i s_j, frame)
        self.motions = {}          # id → dict(row index, joint, dof)
        self.names = {b.name: k for k, b in enumerate(bodies)}
        self.Jbody = [b.J for b in bodies]
        self.masses = np.array([b.mass for b in bodies])

    # ------------------------------------------------ 坐标
    def q0(self):
        q = np.zeros(self.n)
        for k, b in enumerate(self.bodies):
            q[7 * k:7 * k + 3] = b.r0
            q[7 * k + 3:7 * k + 7] = b.p0
        return q

    @staticmethod
    def rp(q, k):
        return q[7 * k:7 * k + 3], q[7 * k + 3:7 * k + 7]

    # ------------------------------------------------ 约束值（射流）
    def _jets(self, q, qd, t, td):
        """每个构件：r 的射流，和转换矩阵三件套 (A(p), A 沿 ṗ 的一阶系数, 二阶系数 2A(ṗ))——A 是 p 的齐次二次式，三件套精确"""
        rs, ps = [], []
        for k in range(self.nb):
            sl_r, sl_p = slice(7 * k, 7 * k + 3), slice(7 * k + 3, 7 * k + 7)
            rs.append(V(q[sl_r], qd[sl_r]))
            p, pd = q[sl_p], qd[sl_p]
            if np.any(pd):
                ps.append((A_of(p), 0.5 * (A_of(p + pd) - A_of(p - pd)), 2 * A_of(pd)))
            else:
                ps.append((A_of(p), None, None))
        return rs, ps, Jet(t, td, 0.0)

    @staticmethod
    def _rot(trip, a):
        A0, A1, A2 = trip
        if A1 is None:
            return V(A0 @ a)
        return V(A0 @ a, A1 @ a, A2 @ a)

    def _vec(self, ps, b, a):
        return V(a) if b < 0 else self._rot(ps[b], a)

    def _pt(self, rs, ps, b, s):
        return V(s) if b < 0 else rs[b] + self._rot(ps[b], s)

    def _row_jet(self, row: Row, rs, ps, tj) -> Jet:
        k = row.kind
        if k == "norm":
            return self._pnorm[row.i]
        if k == "dot1":
            return self._vec(ps, row.i, row.a_i).dot(self._vec(ps, row.j, row.a_j))
        if k in ("sph", "dot2", "tdrive"):
            d = self._pt(rs, ps, row.j, row.s_j) - self._pt(rs, ps, row.i, row.s_i)
            if k == "sph":
                return Jet(d.v[row.k], d.d[row.k], d.dd[row.k])
            val = self._vec(ps, row.i, row.a_i).dot(d)
            if k == "dot2":
                return val
            s = row.fn(tj)
            return val - (s + row.c)
        if k == "rdrive":
            fj = self._vec(ps, row.j, row.a_j)
            fi = self._vec(ps, row.i, row.a_i)
            gi = self._vec(ps, row.i, row.b_i)
            th = row.fn(tj)
            c, s = _jcos(th), _jsin(th)
            return fj.dot(gi) * c - fj.dot(fi) * s
        raise ValueError(k)

    def phi_jets(self, q, qd, t, td, rows=None):
        rs, ps, tj = self._jets(q, qd, t, td)
        self._pnorm = []
        for k in range(self.nb):
            pv = V(q[7 * k + 3:7 * k + 7], qd[7 * k + 3:7 * k + 7])
            self._pnorm.append(pv.dot(pv) - 1.0)
        return [self._row_jet(r, rs, ps, tj) for r in (self.rows if rows is None else rows)]

    def phi(self, q, t, rows=None):
        return np.array([j.v for j in self.phi_jets(q, np.zeros(self.n), t, 0.0, rows)])

    def nu(self, q, t, rows=None):
        """速度方程右端 ν = −Φ_t"""
        return -np.array([j.d for j in self.phi_jets(q, np.zeros(self.n), t, 1.0, rows)])

    def gamma(self, q, qd, t, rows=None):
        """加速度方程右端 γ：Φ̈ = Φ_q q̈ − γ，射流二阶系数（q̈ = 0 时）就是 Φ̈ 的其余部分 = −γ；射流存的是 f″/2·2 = f″"""
        return -np.array([j.dd for j in self.phi_jets(q, qd, t, 1.0, rows)])

    # ------------------------------------------------ 雅可比（解析）
    def jac(self, q, t, rows=None):
        rows = self.rows if rows is None else rows
        Jm = np.zeros((len(rows), self.n))
        Ap = {}

        def A(b):
            if b not in Ap:
                Ap[b] = A_of(self.rp(q, b)[1])
            return Ap[b]

        def vec(b, a):
            return np.asarray(a, float) if b < 0 else A(b) @ a

        def B(b, a):
            return B_of(self.rp(q, b)[1], a)

        def add(row_i, b, cr, cp):
            if b < 0:
                return
            if cr is not None:
                Jm[row_i, 7 * b:7 * b + 3] += cr
            if cp is not None:
                Jm[row_i, 7 * b + 3:7 * b + 7] += cp

        for n_, row in enumerate(rows):
            k = row.kind
            if k == "norm":
                add(n_, row.i, None, 2 * self.rp(q, row.i)[1])
            elif k == "dot1":
                ai, aj = vec(row.i, row.a_i), vec(row.j, row.a_j)
                if row.i >= 0:
                    add(n_, row.i, None, aj @ B(row.i, row.a_i))
                if row.j >= 0:
                    add(n_, row.j, None, ai @ B(row.j, row.a_j))
            elif k in ("sph", "dot2", "tdrive"):
                d = self._point(q, row.j, row.s_j) - self._point(q, row.i, row.s_i)
                if k == "sph":
                    e = I3[row.k]
                    add(n_, row.i, -e, -e @ B(row.i, row.s_i) if row.i >= 0 else None)
                    add(n_, row.j, e, e @ B(row.j, row.s_j) if row.j >= 0 else None)
                else:
                    ai = vec(row.i, row.a_i)
                    if row.i >= 0:
                        add(n_, row.i, -ai, d @ B(row.i, row.a_i) - ai @ B(row.i, row.s_i))
                    if row.j >= 0:
                        add(n_, row.j, ai, ai @ B(row.j, row.s_j))
            elif k == "rdrive":
                th = row.fn(Jet(t, 0.0, 0.0)).v
                c, s = math.cos(th), math.sin(th)
                fj, fi, gi = vec(row.j, row.a_j), vec(row.i, row.a_i), vec(row.i, row.b_i)
                # Φ = c (fj·gi) − s (fj·fi)
                if row.j >= 0:
                    add(n_, row.j, None, (c * gi - s * fi) @ B(row.j, row.a_j))
                if row.i >= 0:
                    add(n_, row.i, None, c * (fj @ B(row.i, row.b_i)) - s * (fj @ B(row.i, row.a_i)))
        return Jm

    def _point(self, q, b, s):
        if b < 0:
            return np.asarray(s, float)
        r, p = self.rp(q, b)
        return r + A_of(p) @ s

    # ------------------------------------------------ 质量与力
    def mass(self, q):
        M = np.zeros((self.n, self.n))
        for k, b in enumerate(self.bodies):
            p = self.rp(q, k)[1]
            G = G_of(p)
            M[7 * k:7 * k + 3, 7 * k:7 * k + 3] = b.mass * I3
            M[7 * k + 3:7 * k + 7, 7 * k + 3:7 * k + 7] = 4 * G.T @ b.J @ G
        return M

    def body_wrenches(self, q, qd, t):
        """每个构件受的外力（地面系）与对质心的力矩（地面系）——不含约束力"""
        F = np.zeros((self.nb, 3))
        N = np.zeros((self.nb, 3))
        F += self.masses[:, None] * self.g[None, :]
        for kind, f in self.forces:
            if kind == "force":
                vec = np.array([fn(t) for fn in f["fn"]])
                b = f["body"]
                if b < 0:
                    continue
                A = A_of(self.rp(q, b)[1])
                Fw = A @ vec if f["frame"] == "body" else vec
                F[b] += Fw
                N[b] += np.cross(A @ f["s"], Fw)
            elif kind == "torque":
                vec = np.array([fn(t) for fn in f["fn"]])
                b = f["body"]
                if b < 0:
                    continue
                N[b] += A_of(self.rp(q, b)[1]) @ vec if f["frame"] == "body" else vec
            elif kind == "spring":
                pi_, vi_ = self._pv(q, qd, f["i"], f["s_i"])
                pj_, vj_ = self._pv(q, qd, f["j"], f["s_j"])
                dvec = pj_ - pi_
                L = float(np.linalg.norm(dvec))
                if L < 1e-12:
                    continue
                u = dvec / L
                Ld = float(u @ (vj_ - vi_))
                T = f["k"] * (L - f["L0"]) + f["c"] * Ld + f["pre"]
                for b, s, sign in ((f["i"], f["s_i"], 1.0), (f["j"], f["s_j"], -1.0)):
                    if b < 0:
                        continue
                    Fw = sign * T * u
                    F[b] += Fw
                    N[b] += np.cross(A_of(self.rp(q, b)[1]) @ s, Fw)
        return F, N

    def _pv(self, q, qd, b, s):
        if b < 0:
            return np.asarray(s, float), np.zeros(3)
        r, p = self.rp(q, b)
        rd, pdot = qd[7 * b:7 * b + 3], qd[7 * b + 3:7 * b + 7]
        return r + A_of(p) @ s, rd + B_of(p, s) @ pdot

    def Q(self, q, qd, t):
        F, N = self.body_wrenches(q, qd, t)
        out = np.zeros(self.n)
        for k, b in enumerate(self.bodies):
            p = self.rp(q, k)[1]
            pdot = qd[7 * k + 3:7 * k + 7]
            G, Gd = G_of(p), G_of(pdot)
            nb = A_of(p).T @ N[k]
            out[7 * k:7 * k + 3] = F[k]
            out[7 * k + 3:7 * k + 7] = 2 * G.T @ nb + 8 * Gd.T @ b.J @ Gd @ p
        return out

    # ------------------------------------------------ 能量
    def energy(self, q, qd):
        ke = 0.5 * qd @ self.mass(q) @ qd
        pe = 0.0
        for k in range(self.nb):
            pe -= self.masses[k] * self.g @ self.rp(q, k)[0]
        for kind, f in self.forces:
            if kind == "spring":
                L = float(np.linalg.norm(self._pv(q, qd, f["j"], f["s_j"])[0] - self._pv(q, qd, f["i"], f["s_i"])[0]))
                x = L - f["L0"]
                pe += 0.5 * f["k"] * x * x + f["pre"] * x
        return ke, pe

    def omega(self, q, qd, k):
        p = self.rp(q, k)[1]
        return 2 * E_of(p) @ qd[7 * k + 3:7 * k + 7]


def _jsin(x: Jet):
    return Jet(math.sin(x.v), math.cos(x.v) * x.d, -math.sin(x.v) * x.d ** 2 + math.cos(x.v) * x.dd)


def _jcos(x: Jet):
    return Jet(math.cos(x.v), -math.sin(x.v) * x.d, -math.cos(x.v) * x.d ** 2 - math.sin(x.v) * x.dd)


def frame_from_axis(h):
    """给定轴 h，造正交标架 (f, g, h)"""
    h = np.asarray(h, float)
    h = h / np.linalg.norm(h)
    t = I3[int(np.argmin(np.abs(h)))]
    f = np.cross(h, t)
    f /= np.linalg.norm(f)
    g = np.cross(h, f)
    return f, g, h


def fn_of(src, scale):
    """表达式（对外单位）→ 射流函数（SI）：fn(Jet t) → Jet"""
    e = compile_expr(src)

    def f(tj):
        if isinstance(tj, Jet):
            v, d, dd = e.jet(tj.v)
            # 复合：位移 s(t)，t 是射流 (t, td, tdd)
            return Jet(scale * v, scale * d * tj.d, scale * (dd * tj.d ** 2 + d * tj.dd))
        return scale * e(tj)

    f.expr = e
    return f
