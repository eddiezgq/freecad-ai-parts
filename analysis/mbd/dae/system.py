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


def _skew_b(a):
    """N×3 → N×3×3"""
    out = np.zeros((len(a), 3, 3))
    out[:, 0, 1], out[:, 0, 2] = -a[:, 2], a[:, 1]
    out[:, 1, 0], out[:, 1, 2] = a[:, 2], -a[:, 0]
    out[:, 2, 0], out[:, 2, 1] = -a[:, 1], a[:, 0]
    return out


def A_batch(P):
    """N×4 欧拉参数 → N×3×3（与 A_of 同一公式）"""
    e0, e = P[:, 0], P[:, 1:]
    return ((e0 * e0 - np.einsum("ni,ni->n", e, e))[:, None, None] * I3
            + 2 * (np.einsum("ni,nj->nij", e, e) + e0[:, None, None] * _skew_b(e)))


def B_batch(P, a):
    """N×4、N×3 → N×3×4（与 B_of 同一公式）"""
    e0, e = P[:, 0], P[:, 1:]
    m = e0[:, None, None] * I3 + _skew_b(e)
    col0 = np.einsum("nij,nj->ni", m, a)
    rest = np.einsum("ni,nj->nij", e, a) - np.einsum("nij,njk->nik", m, _skew_b(a))
    return 2 * np.concatenate([col0[:, :, None], rest], axis=2)


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
    flex: object = None            # D6：柔性构件的 FlexData（analysis/mbd/dae/flex.py）


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
    node_i: int | None = None      # D6：挂在柔性构件的哪个界面节点上（点、方向随节点变形）
    node_j: int | None = None


class System:
    def __init__(self, bodies: list[Body], gravity):
        self.bodies = bodies
        self.nb = len(bodies)
        # D6：柔性构件的模态坐标依次接在全部刚体坐标后面（不动现有下标）
        self.foff = {}
        n = 7 * self.nb
        for k, b in enumerate(bodies):
            if b.flex is not None:
                self.foff[k] = n
                n += b.flex.nm
        self.n = n
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
        es = {k: V(q[o:o + self.bodies[k].flex.nm], qd[o:o + self.bodies[k].flex.nm]) for k, o in self.foff.items()}
        self._es = es
        return rs, ps, Jet(t, td, 0.0)

    def eta(self, q, k):
        o = self.foff[k]
        return q[o:o + self.bodies[k].flex.nm]

    def _local(self, b, s, node, which="s"):
        """柔性构件界面节点上的点 / 方向在构件系里的射流（刚体就是常向量）"""
        if b < 0 or node is None or b not in self.foff:
            return V(np.asarray(s, float))
        fx, e = self.bodies[b].flex, self._es[b]
        if which == "s":
            P = fx.Phit[node]
            return V(np.asarray(s, float)) + V(P @ e.v, P @ e.d, P @ e.dd)
        th = V(fx.Phir[node] @ e.v, fx.Phir[node] @ e.d, fx.Phir[node] @ e.dd)
        a = V(np.asarray(s, float))
        return a + th.cross(a)

    @staticmethod
    def _rot(trip, a):
        A0, A1, A2 = trip
        if isinstance(a, V):                       # D6：a 本身是射流（柔性节点）
            if A1 is None:
                return V(A0 @ a.v, A0 @ a.d, A0 @ a.dd)
            return V(A0 @ a.v, A1 @ a.v + A0 @ a.d, A2 @ a.v + 2 * (A1 @ a.d) + A0 @ a.dd)
        if A1 is None:
            return V(A0 @ a)
        return V(A0 @ a, A1 @ a, A2 @ a)

    def _vec(self, ps, b, a, node=None):
        if b < 0:
            return V(a)
        return self._rot(ps[b], self._local(b, a, node, "a") if node is not None else a)

    def _pt(self, rs, ps, b, s, node=None):
        if b < 0:
            return V(s)
        return rs[b] + self._rot(ps[b], self._local(b, s, node, "s") if node is not None else s)

    def _row_jet(self, row: Row, rs, ps, tj) -> Jet:
        k = row.kind
        if k == "norm":
            return self._pnorm[row.i]
        ni, nj = row.node_i, row.node_j
        if k == "dot1":
            return self._vec(ps, row.i, row.a_i, ni).dot(self._vec(ps, row.j, row.a_j, nj))
        if k in ("sph", "dot2", "tdrive"):
            d = self._pt(rs, ps, row.j, row.s_j, nj) - self._pt(rs, ps, row.i, row.s_i, ni)
            if k == "sph":
                return Jet(d.v[row.k], d.d[row.k], d.dd[row.k])
            val = self._vec(ps, row.i, row.a_i, ni).dot(d)
            if k == "dot2":
                return val
            s = row.fn(tj)
            return val - (s + row.c)
        if k == "rdrive":
            fj = self._vec(ps, row.j, row.a_j, nj)
            fi = self._vec(ps, row.i, row.a_i, ni)
            gi = self._vec(ps, row.i, row.b_i, ni)
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
        return self._phi3(q, None, t, 0.0, rows, need=1)[0]

    def nu(self, q, t, rows=None):
        """速度方程右端 ν = −Φ_t"""
        return -self._phi3(q, None, t, 1.0, rows, need=2)[1]

    def gamma(self, q, qd, t, rows=None):
        """加速度方程右端 γ：Φ̈ = Φ_q q̈ − γ，射流二阶系数（q̈ = 0 时）就是 Φ̈ 的其余部分 = −γ；射流存的是 f″/2·2 = f″"""
        return -self._phi3(q, qd, t, 1.0, rows, need=3)[2]

    # ------------------------------------------------ D8：常见行（球铰三行、两种点积行，不在柔性节点上）成批算
    VEC_KINDS = ("sph", "dot1", "dot2", "norm")

    def _plan(self, rows):
        key = tuple(map(id, rows))
        cache = self.__dict__.setdefault("_plans", {})
        if key in cache:
            return cache[key]
        nb = self.nb
        vec, other = [], []
        for n_, r in enumerate(rows):
            if r.kind in self.VEC_KINDS and r.node_i is None and r.node_j is None:
                vec.append(n_)
            else:
                other.append(n_)
        rv = [rows[n_] for n_ in vec]

        def body(b):
            return nb if b < 0 else b                    # 地面：多放一个“构件”位置，A = I、r = 0

        def arr(attr):
            return np.array([np.zeros(3) if getattr(r, attr) is None else np.asarray(getattr(r, attr), float) for r in rv]
                            ).reshape(len(rv), 3)

        plan = {"vec": np.array(vec, int), "other": other, "kind": np.array([r.kind for r in rv]),
                "i": np.array([body(r.i) for r in rv], int), "j": np.array([body(r.j) for r in rv], int),
                "ri": np.array([r.i for r in rv], int), "rj": np.array([r.j for r in rv], int),
                "si": arr("s_i"), "sj": arr("s_j"), "ai": arr("a_i"), "aj": arr("a_j"),
                "k": np.array([r.k if r.kind == "sph" else 0 for r in rv], int)}
        plan["sph"] = np.flatnonzero(plan["kind"] == "sph")
        plan["dot1"] = np.flatnonzero(plan["kind"] == "dot1")
        plan["dot2"] = np.flatnonzero(plan["kind"] == "dot2")
        plan["norm"] = np.flatnonzero(plan["kind"] == "norm")
        if len(cache) > 64:
            cache.clear()
        cache[key] = plan
        return plan

    def _bodies_b(self, q, qd):
        """全部构件（+ 地面）的 r、ṙ 与 A 三件套，成批"""
        nb = self.nb
        P = q[:7 * nb].reshape(nb, 7)
        R0 = np.vstack([P[:, :3], np.zeros(3)])
        A0 = np.concatenate([A_batch(P[:, 3:]), I3[None]], 0)
        if qd is None or not np.any(qd[:7 * nb]):
            z = np.zeros((nb + 1, 3))
            return R0, z, A0, None, None
        Pd = qd[:7 * nb].reshape(nb, 7)
        R1 = np.vstack([Pd[:, :3], np.zeros(3)])
        p, pd = P[:, 3:], Pd[:, 3:]
        A1 = np.concatenate([0.5 * (A_batch(p + pd) - A_batch(p - pd)), np.zeros((1, 3, 3))], 0)
        A2 = np.concatenate([2 * A_batch(pd), np.zeros((1, 3, 3))], 0)
        return R0, R1, A0, A1, A2

    def _phi3(self, q, qd, t, td, rows, need):
        rows = self.rows if rows is None else rows
        m = len(rows)
        out = np.zeros((3, m))
        plan = self._plan(rows)
        if plan["other"]:
            sub = [rows[n_] for n_ in plan["other"]]
            js = self.phi_jets(q, np.zeros(self.n) if qd is None else qd, t, td, sub)
            out[:, plan["other"]] = np.array([[j.v, j.d, j.dd] for j in js]).T
        if not len(plan["vec"]):
            return out
        R0, R1, A0, A1, A2 = self._bodies_b(q, qd)
        moving = A1 is not None and need >= 2

        def rot(b, a):
            v = np.einsum("nij,nj->ni", A0[b], a)
            if not moving:
                return v, None, None
            return v, np.einsum("nij,nj->ni", A1[b], a), np.einsum("nij,nj->ni", A2[b], a)

        def pt(b, s):
            v, d, dd = rot(b, s)
            if not moving:
                return R0[b] + v, None, None
            return R0[b] + v, R1[b] + d, dd

        def dot(x, y):
            v = np.einsum("ni,ni->n", x[0], y[0])
            if not moving:
                return v, 0.0, 0.0
            d = np.einsum("ni,ni->n", x[1], y[0]) + np.einsum("ni,ni->n", x[0], y[1])
            dd = (np.einsum("ni,ni->n", x[2], y[0]) + 2 * np.einsum("ni,ni->n", x[1], y[1])
                  + np.einsum("ni,ni->n", x[0], y[2]))
            return v, d, dd

        res = np.zeros((3, len(plan["vec"])))
        g = plan["sph"]
        if len(g):
            Pj, Pi = pt(plan["j"][g], plan["sj"][g]), pt(plan["i"][g], plan["si"][g])
            kk = plan["k"][g]
            ar = np.arange(len(g))
            res[0, g] = (Pj[0] - Pi[0])[ar, kk]
            if moving:
                res[1, g] = (Pj[1] - Pi[1])[ar, kk]
                res[2, g] = (Pj[2] - Pi[2])[ar, kk]
        g = plan["dot1"]
        if len(g):
            res[:, g] = np.vstack(np.broadcast_arrays(*dot(rot(plan["i"][g], plan["ai"][g]),
                                                           rot(plan["j"][g], plan["aj"][g]))))
        g = plan["dot2"]
        if len(g):
            Pj, Pi = pt(plan["j"][g], plan["sj"][g]), pt(plan["i"][g], plan["si"][g])
            d = (Pj[0] - Pi[0], None if not moving else Pj[1] - Pi[1], None if not moving else Pj[2] - Pi[2])
            res[:, g] = np.vstack(np.broadcast_arrays(*dot(rot(plan["i"][g], plan["ai"][g]), d)))
        g = plan["norm"]
        if len(g):
            b = plan["ri"][g]
            pp = q[:7 * self.nb].reshape(self.nb, 7)[b, 3:]
            res[0, g] = np.einsum("ni,ni->n", pp, pp) - 1.0
            if qd is not None and need >= 2:
                pdd = qd[:7 * self.nb].reshape(self.nb, 7)[b, 3:]
                res[1, g] = 2 * np.einsum("ni,ni->n", pp, pdd)
                res[2, g] = 2 * np.einsum("ni,ni->n", pdd, pdd)
        out[:, plan["vec"]] = res
        return out

    # ------------------------------------------------ 雅可比（解析）
    def jac(self, q, t, rows=None):
        rows = self.rows if rows is None else rows
        plan = self._plan(rows)
        if not len(plan["vec"]):
            return self._jac_rows(q, t, rows)
        Jm = np.zeros((len(rows), self.n))
        if plan["other"]:
            Jm[plan["other"]] = self._jac_rows(q, t, [rows[n_] for n_ in plan["other"]])
        nb = self.nb
        P = q[:7 * nb].reshape(nb, 7)
        Pp = np.vstack([P[:, 3:], [1.0, 0, 0, 0]])
        R0, _, A0, _, _ = self._bodies_b(q, None)
        vec = plan["vec"]
        bi, bj, ri, rj = plan["i"], plan["j"], plan["ri"], plan["rj"]
        r_cols = np.arange(3)
        p_cols = np.arange(3, 7)

        def add(rows_, b_real, coef, block):
            """Jm[rows_, 7b + cols] += coef_row · block（b_real < 0 的行是地面，跳过）"""
            ok = b_real >= 0
            if not np.any(ok):
                return
            rr, bb = rows_[ok], b_real[ok]
            vals = np.einsum("ni,nij->nj", coef[ok], block[ok])
            ncol = vals.shape[1]
            cols = 7 * bb[:, None] + (r_cols if ncol == 3 else p_cols)[None, :]
            np.add.at(Jm, (np.repeat(rr, ncol), cols.ravel()), vals.ravel())

        I3b = np.broadcast_to(I3, (len(vec), 3, 3))
        g = plan["sph"]
        if len(g):
            c = np.eye(3)[plan["k"][g]]
            rows_ = vec[g]
            add(rows_, rj[g], c, I3b[g])
            add(rows_, rj[g], c, B_batch(Pp[bj[g]], plan["sj"][g]))
            add(rows_, ri[g], -c, I3b[g])
            add(rows_, ri[g], -c, B_batch(Pp[bi[g]], plan["si"][g]))
        g = plan["dot1"]
        if len(g):
            ai = np.einsum("nij,nj->ni", A0[bi[g]], plan["ai"][g])
            aj = np.einsum("nij,nj->ni", A0[bj[g]], plan["aj"][g])
            add(vec[g], ri[g], aj, B_batch(Pp[bi[g]], plan["ai"][g]))
            add(vec[g], rj[g], ai, B_batch(Pp[bj[g]], plan["aj"][g]))
        g = plan["dot2"]
        if len(g):
            ai = np.einsum("nij,nj->ni", A0[bi[g]], plan["ai"][g])
            Pj = R0[bj[g]] + np.einsum("nij,nj->ni", A0[bj[g]], plan["sj"][g])
            Pi = R0[bi[g]] + np.einsum("nij,nj->ni", A0[bi[g]], plan["si"][g])
            d = Pj - Pi
            rows_ = vec[g]
            add(rows_, ri[g], d, B_batch(Pp[bi[g]], plan["ai"][g]))
            add(rows_, rj[g], ai, I3b[g])
            add(rows_, rj[g], ai, B_batch(Pp[bj[g]], plan["sj"][g]))
            add(rows_, ri[g], -ai, I3b[g])
            add(rows_, ri[g], -ai, B_batch(Pp[bi[g]], plan["si"][g]))
        g = plan["norm"]
        if len(g):
            b = ri[g]
            cols = 7 * b[:, None] + p_cols[None, :]
            Jm[np.repeat(vec[g], 4), cols.ravel()] += (2 * P[b, 3:]).ravel()
        return Jm

    def _jac_rows(self, q, t, rows):
        Jm = np.zeros((len(rows), self.n))
        Ap = {}

        def A(b):
            if b not in Ap:
                Ap[b] = A_of(self.rp(q, b)[1])
            return Ap[b]

        def flex(b, node):
            return node is not None and b in self.foff

        def s_eff(b, s, node):
            if not flex(b, node):
                return np.asarray(s, float)
            return np.asarray(s, float) + self.bodies[b].flex.Phit[node] @ self.eta(q, b)

        def a_eff(b, a, node):
            if not flex(b, node):
                return np.asarray(a, float)
            a = np.asarray(a, float)
            return a + np.cross(self.bodies[b].flex.Phir[node] @ self.eta(q, b), a)

        def wvec(b, a, node):
            return np.asarray(a, float) if b < 0 else A(b) @ a_eff(b, a, node)

        def wpt(b, s, node):
            return np.asarray(s, float) if b < 0 else self.rp(q, b)[0] + A(b) @ s_eff(b, s, node)

        def add_pt(n_, b, s, node, c, sign):
            """Φ 里有 sign·c·(r_b + A_b s_b)"""
            if b < 0:
                return
            c = sign * np.asarray(c, float)
            Jm[n_, 7 * b:7 * b + 3] += c
            Jm[n_, 7 * b + 3:7 * b + 7] += c @ B_of(self.rp(q, b)[1], s_eff(b, s, node))
            if flex(b, node):
                o, fx = self.foff[b], self.bodies[b].flex
                Jm[n_, o:o + fx.nm] += c @ A(b) @ fx.Phit[node]

        def add_vec(n_, b, a, node, c):
            """Φ 里有 c·(A_b a_b)"""
            if b < 0:
                return
            Jm[n_, 7 * b + 3:7 * b + 7] += c @ B_of(self.rp(q, b)[1], a_eff(b, a, node))
            if flex(b, node):
                o, fx = self.foff[b], self.bodies[b].flex
                Jm[n_, o:o + fx.nm] += c @ A(b) @ (-skew(np.asarray(a, float)) @ fx.Phir[node])

        for n_, row in enumerate(rows):
            k = row.kind
            ni, nj = row.node_i, row.node_j
            if k == "norm":
                Jm[n_, 7 * row.i + 3:7 * row.i + 7] += 2 * self.rp(q, row.i)[1]
            elif k == "dot1":
                ai, aj = wvec(row.i, row.a_i, ni), wvec(row.j, row.a_j, nj)
                add_vec(n_, row.i, row.a_i, ni, aj)
                add_vec(n_, row.j, row.a_j, nj, ai)
            elif k in ("sph", "dot2", "tdrive"):
                if k == "sph":
                    c = I3[row.k]
                else:
                    c = wvec(row.i, row.a_i, ni)
                    d = wpt(row.j, row.s_j, nj) - wpt(row.i, row.s_i, ni)
                    add_vec(n_, row.i, row.a_i, ni, d)
                add_pt(n_, row.j, row.s_j, nj, c, 1.0)
                add_pt(n_, row.i, row.s_i, ni, c, -1.0)
            elif k == "rdrive":
                th = row.fn(Jet(t, 0.0, 0.0)).v
                c, s_ = math.cos(th), math.sin(th)
                fj, fi, gi = wvec(row.j, row.a_j, nj), wvec(row.i, row.a_i, ni), wvec(row.i, row.b_i, ni)
                # Φ = c (fj·gi) − s (fj·fi)
                add_vec(n_, row.j, row.a_j, nj, c * gi - s_ * fi)
                add_vec(n_, row.i, row.b_i, ni, c * fj)
                add_vec(n_, row.i, row.a_i, ni, -s_ * fj)
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
            if b.flex is None:
                M[7 * k + 3:7 * k + 7, 7 * k + 3:7 * k + 7] = 4 * G.T @ b.J @ G
                continue
            # D6：柔性构件，速度 (ṙ, ω̄ = 2Gṗ, η̇) 下的质量阵换到 (ṙ, ṗ, η̇)
            fx, A = b.flex, A_of(p)
            S, J, Mwf = fx.mass_v(self.eta(q, k))
            G2 = 2 * G
            r_, p_, o = slice(7 * k, 7 * k + 3), slice(7 * k + 3, 7 * k + 7), self.foff[k]
            f_ = slice(o, o + fx.nm)
            Mrp = -A @ skew(S) @ G2
            Mrf = A @ fx.Psi
            Mpf = G2.T @ Mwf
            M[p_, p_] = G2.T @ J @ G2
            M[r_, p_], M[p_, r_] = Mrp, Mrp.T
            M[r_, f_], M[f_, r_] = Mrf, Mrf.T
            M[p_, f_], M[f_, p_] = Mpf, Mpf.T
            M[f_, f_] = fx.Mff
        return M

    # ------------------------------------------------ 测量量（D2，SI：rad、rad/s、m、m/s）
    def joint_frame(self, q, info):
        """运动副在 body_i 上的 f、g、h（地面系）"""
        i = info["i"]
        if i < 0:
            return info["f"], info["g"], info["h"]
        A = A_of(self.rp(q, i)[1])
        return A @ info["f"], A @ info["g"], A @ info["h"]

    def joint_kin(self, q, qd, info):
        """运动副 j 相对 i 的转角（−π…π）、角速度、沿轴位移、沿轴速度"""
        f_i, g_i, h = self.joint_frame(q, info)
        j = info["j"]
        f_j = info["f"] if j < 0 else A_of(self.rp(q, j)[1]) @ info["f"]
        ang = math.atan2(float(f_j @ g_i), float(f_j @ f_i))
        wi = self.omega(q, qd, info["i"]) if info["i"] >= 0 else np.zeros(3)
        wj = self.omega(q, qd, j) if j >= 0 else np.zeros(3)
        Pi, Vi = self._pv(q, qd, info["i"], info["si"])
        Pj, Vj = self._pv(q, qd, j, info["sj"])
        return ang, float(h @ (wj - wi)), float(h @ (Pj - Pi)), float(h @ (Vj - Vi))

    def measures(self, q, qd):
        """对外单位：°、°/s、mm、mm/s"""
        out = {}
        for m in getattr(self, "measure_defs", []):
            if m["type"].startswith("joint_"):
                ang, w, x, v = self.joint_kin(q, qd, self.joints[m["joint"]])
                out[m["id"]] = {"joint_angle": math.degrees(ang), "joint_speed": math.degrees(w),
                                "joint_displacement": x * 1000, "joint_velocity": v * 1000}[m["type"]]
            else:
                Pi, Vi = self._pv(q, qd, m["i"], m["s_i"])
                Pj, Vj = self._pv(q, qd, m["j"], m["s_j"])
                d = Pj - Pi
                L = float(np.linalg.norm(d))
                out[m["id"]] = L * 1000 if m["type"] == "point_distance" else (float(d @ (Vj - Vi)) / L * 1000 if L > 0 else 0.0)
        return out

    def _add(self, F, N, q, b, Fw, P=None, T=None):
        """把作用在构件 b 的力 Fw（作用点 P，地面系）和力矩 T 加进去"""
        if b < 0:
            return
        if Fw is not None:
            F[b] += Fw
            N[b] += np.cross(P - self.rp(q, b)[0], Fw)
        if T is not None:
            N[b] += T

    @staticmethod
    def _qconj(p):
        return np.array([p[0], -p[1], -p[2], -p[3]])

    @staticmethod
    def _qmul(a, b):
        a0, av, b0, bv = a[0], a[1:], b[0], b[1:]
        return np.r_[a0 * b0 - av @ bv, a0 * bv + b0 * av + np.cross(av, bv)]

    def rel_rotvec(self, q, i, j):
        """j 相对 i 的转动向量（body_i 坐标系）"""
        pi = np.array([1.0, 0, 0, 0]) if i < 0 else self.rp(q, i)[1]
        pj = np.array([1.0, 0, 0, 0]) if j < 0 else self.rp(q, j)[1]
        r = self._qmul(self._qconj(pi), pj) / (np.linalg.norm(pi) * np.linalg.norm(pj))
        if r[0] < 0:
            r = -r
        v = r[1:]
        sv = float(np.linalg.norm(v))
        return np.zeros(3) if sv < 1e-15 else 2 * math.atan2(sv, r[0]) * v / sv

    def body_wrenches(self, q, qd, t):
        """每个构件受的外力（地面系）与对质心的力矩（地面系）——不含约束力"""
        F = np.zeros((self.nb, 3))
        N = np.zeros((self.nb, 3))
        ls = getattr(self, "load_scale", 1.0)               # 静平衡分步加载（ADR-0101）：只缩放重力和外加力、力矩
        F += ls * self.masses[:, None] * self.g[None, :]
        env = self.measures(q, qd) if getattr(self, "needs_env", False) else None
        for kind, f in self.forces:
            if kind == "contact":
                from analysis.mbd.dae.contact import contact_wrenches
                contact_wrenches(self, q, qd, f, F, N)
                continue
            if kind == "gear":
                from analysis.mbd.dae.contact import gear_wrenches
                gear_wrenches(self, q, qd, f, F, N)
                continue
            if kind == "force":
                vec = ls * np.array([fn(t, env) for fn in f["fn"]])
                b = f["body"]
                if b < 0:
                    continue
                A = A_of(self.rp(q, b)[1])
                Fw = A @ vec if f["frame"] == "body" else vec
                F[b] += Fw
                N[b] += np.cross(A @ f["s"], Fw)
            elif kind == "torque":
                vec = ls * np.array([fn(t, env) for fn in f["fn"]])
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
            elif kind == "actuator":                   # D7：执行器，沿运动副轴，j 上 +、i 上 −
                u = float(getattr(self, "act", {}).get(f["id"], 0.0))
                if u == 0.0:
                    continue
                jt = self.joints[f["joint"]]
                h = self.joint_frame(q, jt)[2]
                if f["dof"] == "rotation":
                    for b, sign in ((jt["j"], 1.0), (jt["i"], -1.0)):
                        if b >= 0:
                            N[b] += sign * u * h
                else:
                    P = self._pv(q, qd, jt["j"], jt["sj"])[0]
                    self._add(F, N, q, jt["j"], u * h, P)
                    self._add(F, N, q, jt["i"], -u * h, P)
            elif kind == "rspring":
                info = {"i": f["i"], "j": f["j"], "f": f["f"], "g": f["g"], "h": f["h"], "si": np.zeros(3), "sj": np.zeros(3)}
                ang, w, _, _ = self.joint_kin(q, qd, info)
                h = self.joint_frame(q, info)[2]
                Tq = -(f["k"] * math.remainder(ang - f["a0"], 2 * math.pi) + f["c"] * w) + f["pre"]
                self._add(F, N, q, f["j"], None, T=Tq * h)
                self._add(F, N, q, f["i"], None, T=-Tq * h)
            elif kind == "nlbeam":
                continue                                    # 循环后成批算（ADR-0101 F2）
            elif kind in ("bushing", "beam"):
                i, j = f["i"], f["j"]
                Ai = np.eye(3) if i < 0 else A_of(self.rp(q, i)[1])
                Pi, Vi = self._pv(q, qd, i, f["s_i"])
                Pj, Vj = self._pv(q, qd, j, f["s_j"])
                d = Ai.T @ (Pj - Pi) - f["d0"]
                th = self.rel_rotvec(q, i, j)
                wi = self.omega(q, qd, i) if i >= 0 else np.zeros(3)
                # 变形速度是 d 对时间的导数（在 i 构件系里看）：Aᵢᵀ(Vⱼ − Vᵢ − ωᵢ × (Pⱼ − Pᵢ))。
                # ADR-0098 E2 发现：原来少了 −ωᵢ × (Pⱼ − Pᵢ)，整体转动时没有变形也会出阻尼力（i 是地面时不受影响）
                dd = Ai.T @ (Vj - Vi - np.cross(wi, Pj - Pi))
                wj = self.omega(q, qd, j) if j >= 0 else np.zeros(3)
                wr = Ai.T @ (wj - wi)
                if kind == "bushing":
                    fl = -f["K"] * d - f["C"] * dd + f["F0"]
                    tl = -f["Kr"] * th - f["Cr"] * wr + f["T0"]
                else:
                    Bm = f["Bm"]
                    x = np.r_[Bm.T @ d, Bm.T @ th]
                    xd = np.r_[Bm.T @ dd, Bm.T @ wr]
                    g6 = -f["K6"] @ (x + f["cr"] * xd)
                    fl, tl = Bm @ g6[:3], Bm @ g6[3:]
                Fw, Tw = Ai @ fl, Ai @ tl
                self._add(F, N, q, j, Fw, Pj, Tw)
                self._add(F, N, q, i, -Fw, Pj, -Tw)
            elif kind == "clearance":
                i, j = f["i"], f["j"]
                Pi, Vi = self._pv(q, qd, i, f["s_i"])
                Pj, Vj = self._pv(q, qd, j, f["s_j"])
                h = f["h"] if i < 0 else A_of(self.rp(q, i)[1]) @ f["h"]
                d = Pj - Pi
                dr = d - (h @ d) * h
                er = float(np.linalg.norm(dr))
                pen = er - f["c"]
                if pen <= 0 or er < 1e-15:
                    continue
                u = dr / er
                pend = float(u @ (Vj - Vi))
                damp = f["cd"] if pen >= f["dpen"] else f["cd"] * (pen / f["dpen"]) ** 2 * (3 - 2 * pen / f["dpen"])
                Fn = max(0.0, f["k"] * pen ** f["e"] + damp * pend)
                self._add(F, N, q, j, -Fn * u, Pj)
                self._add(F, N, q, i, Fn * u, Pj)
        nlb = self.nlbeam_batch()
        if nlb is not None:
            _, _, fj, Mi, Mj = nlb.eval(q, qd, self.nb)
            np.add.at(F, nlb.j, fj)
            np.add.at(F, nlb.i, -fj)
            np.add.at(N, nlb.j, Mj)
            np.add.at(N, nlb.i, Mi)
        return F, N

    def nlbeam_batch(self):
        """大变形梁单元的成批计算器（ADR-0101 F2），没有就返回 None；力元表变了就重建"""
        fs = [f for kind, f in self.forces if kind == "nlbeam"]
        if not fs:
            return None
        key = tuple(map(id, fs))
        cache = getattr(self, "_nlb_cache", None)
        if cache is None or cache[0] != key:
            from analysis.mbd.dae.nlbeam import Batch

            cache = (key, Batch(fs))
            self._nlb_cache = cache
        return cache[1]

    def friction_wrenches(self, q, qd, react):
        """运动副摩擦（D2）：react = {joint: (F_on_j, T_on_j about joint point)} 来自上一次迭代的约束力"""
        F = np.zeros((self.nb, 3))
        N = np.zeros((self.nb, 3))
        for jid, info in self.joints.items():
            fr = info.get("friction")
            if not fr or jid not in react:
                continue
            Fr = react[jid][0]
            _, w, _, v = self.joint_kin(q, qd, info)
            h = self.joint_frame(q, info)[2]
            Nn = float(np.linalg.norm(Fr - (Fr @ h) * h)) + fr["pre"]
            vel = w if info["type"] == "revolute" else v
            a = abs(vel)
            if a <= fr["vs"]:
                mu = fr["ms"] * _smooth(a / fr["vs"])
            elif a < fr["vt"]:
                mu = fr["ms"] + (fr["md"] - fr["ms"]) * _smooth((a - fr["vs"]) / (fr["vt"] - fr["vs"]))
            else:
                mu = fr["md"]
            mag = -math.copysign(mu * Nn, vel) if vel != 0 else 0.0
            if info["type"] == "revolute":
                Tq = mag * fr["R"] * h
                self._add(F, N, q, info["j"], None, T=Tq)
                self._add(F, N, q, info["i"], None, T=-Tq)
            else:
                Pj = self._pv(q, qd, info["j"], info["sj"])[0]
                self._add(F, N, q, info["j"], mag * h, Pj)
                self._add(F, N, q, info["i"], -mag * h, Pj)
        return F, N

    def _pv(self, q, qd, b, s):
        if b < 0:
            return np.asarray(s, float), np.zeros(3)
        r, p = self.rp(q, b)
        rd, pdot = qd[7 * b:7 * b + 3], qd[7 * b + 3:7 * b + 7]
        return r + A_of(p) @ s, rd + B_of(p, s) @ pdot

    def Q_extra(self, q, qd, F, N):
        """只把附加的力 / 力矩（地面系）换成广义力（不含惯性项）"""
        out = np.zeros(self.n)
        for k in range(self.nb):
            p = self.rp(q, k)[1]
            out[7 * k:7 * k + 3] = F[k]
            out[7 * k + 3:7 * k + 7] = 2 * G_of(p).T @ (A_of(p).T @ N[k])
        return out

    def Q(self, q, qd, t, extra=None):
        F, N = self.body_wrenches(q, qd, t)
        if extra is not None:
            F, N = F + extra[0], N + extra[1]
        out = np.zeros(self.n)
        for k, b in enumerate(self.bodies):
            p = self.rp(q, k)[1]
            pdot = qd[7 * k + 3:7 * k + 7]
            G, Gd = G_of(p), G_of(pdot)
            A = A_of(p)
            nb = A.T @ N[k]
            if b.flex is None:
                out[7 * k:7 * k + 3] = F[k]
                out[7 * k + 3:7 * k + 7] = 2 * G.T @ nb + 8 * Gd.T @ b.J @ Gd @ p
                continue
            # D6：柔性构件——逐节点的二次速度力、分布重力、弹性与模态阻尼
            fx, o = b.flex, self.foff[k]
            eta, etad = q[o:o + fx.nm], qd[o:o + fx.nm]
            w = 2 * G @ pdot
            cr, Qw, Qf = fx.quad(w, eta, etad)
            gw, gf = fx.gravity(A.T @ self.g, eta)
            out[7 * k:7 * k + 3] = F[k] - A @ cr
            out[7 * k + 3:7 * k + 7] = 2 * G.T @ (nb + Qw + gw)
            out[o:o + fx.nm] = Qf + gf - fx.K @ eta - fx.D @ etad
        return out

    # ------------------------------------------------ 能量
    def energy(self, q, qd):
        ke = 0.5 * qd @ self.mass(q) @ qd
        pe = 0.0
        for k in range(self.nb):
            pe -= self.masses[k] * self.g @ self.rp(q, k)[0]
            fx = self.bodies[k].flex
            if fx is not None:
                eta = self.eta(q, k)
                S = fx.m @ fx.x(eta)
                pe += -self.g @ (A_of(self.rp(q, k)[1]) @ S) + 0.5 * eta @ fx.K @ eta
        for kind, f in self.forces:
            if kind == "spring":
                L = float(np.linalg.norm(self._pv(q, qd, f["j"], f["s_j"])[0] - self._pv(q, qd, f["i"], f["s_i"])[0]))
                x = L - f["L0"]
                pe += 0.5 * f["k"] * x * x + f["pre"] * x
            elif kind == "rspring":
                info = {"i": f["i"], "j": f["j"], "f": f["f"], "g": f["g"], "h": f["h"], "si": np.zeros(3), "sj": np.zeros(3)}
                x = math.remainder(self.joint_kin(q, qd, info)[0] - f["a0"], 2 * math.pi)
                pe += 0.5 * f["k"] * x * x - f["pre"] * x
        return ke, pe

    def omega(self, q, qd, k):
        p = self.rp(q, k)[1]
        return 2 * E_of(p) @ qd[7 * k + 3:7 * k + 7]


def _smooth(s):
    """三次过渡 0 → 1（STEP 的形状）"""
    s = min(max(s, 0.0), 1.0)
    return s * s * (3 - 2 * s)


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


def fn_of(src, scale, variables=(), splines=None):
    """表达式（对外单位）→ 射流函数（SI）：fn(Jet t) → Jet；力元的表达式可以用测量量（env）"""
    e = compile_expr(src, variables, splines)

    def f(tj, env=None):
        if isinstance(tj, Jet):
            v, d, dd = e.jet(tj.v, env)
            # 复合：位移 s(t)，t 是射流 (t, td, tdd)
            return Jet(scale * v, scale * d * tj.d, scale * (dd * tj.d ** 2 + d * tj.dd))
        return scale * e(tj, env)

    f.expr = e
    return f
