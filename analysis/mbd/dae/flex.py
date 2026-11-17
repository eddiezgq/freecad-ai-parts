"""柔性构件（ADR-0097 D6，补充十三）：集中质量节点 + 模态坐标的浮动参考系模型，梁柔性体的有限元与 Craig-Bampton 缩减。

内部 SI。构件参考系原点在未变形时的质心，t = 0 与地面同向。节点 i：位置 xᵢ(η) = x₀ᵢ + Φtᵢ η（构件系），小转角 Φrᵢ η。
"""

from __future__ import annotations

import numpy as np
import scipy.linalg as sla

RIGID_TOL = 1e-6           # 去刚体模态：特征值 < 这个数 × 最大特征值时算刚体


class FlexError(ValueError):
    pass


def skew_batch(x):
    """N×3 → N×3×3 反对称阵"""
    z = np.zeros(len(x))
    return np.stack([np.stack([z, -x[:, 2], x[:, 1]], -1), np.stack([x[:, 2], z, -x[:, 0]], -1),
                     np.stack([-x[:, 1], x[:, 0], z], -1)], 1)


class FlexData:
    """x0: N×3（相对未变形质心）；m: N；Jn: N×3×3（节点转动惯量，构件系）；Phit、Phir: N×3×nm；K、D: nm×nm"""

    def __init__(self, x0, m, Jn, Phit, Phir, freqs_rad, zeta=0.0, interface=(), nodes_world0=None):
        self.x0 = np.asarray(x0, float)
        self.m = np.asarray(m, float)
        self.Jn = np.asarray(Jn, float)
        self.Phit = np.asarray(Phit, float)
        self.Phir = np.asarray(Phir, float)
        self.nm = self.Phit.shape[2]
        w = np.asarray(freqs_rad, float)
        self.freqs = w
        self.K = np.diag(w * w)
        self.D = np.diag(2 * zeta * w)
        self.zeta = zeta
        self.interface = list(interface)
        self.mass = float(self.m.sum())
        self.nodes_world0 = nodes_world0
        # 与 η 无关的不变量
        self.Psi = np.einsum("i,iab->ab", self.m, self.Phit)                       # Σ mᵢ Φtᵢ
        self.Mff = (np.einsum("i,iak,ial->kl", self.m, self.Phit, self.Phit)
                    + np.einsum("iak,iab,ibl->kl", self.Phir, self.Jn, self.Phir))

    # ---------------------------------------------------- 随 η 变的量
    def x(self, eta):
        return self.x0 + self.Phit @ eta

    def mass_v(self, eta):
        """(S, J, M_ωf)：S = Σmᵢxᵢ，J = Σmᵢ x̃ᵢᵀx̃ᵢ + ΣJᵢ，M_ωf = Σ(mᵢ x̃ᵢΦtᵢ + JᵢΦrᵢ)"""
        x = self.x(eta)
        S = self.m @ x
        xx = np.einsum("i,ia,ia->i", self.m, x, x)
        J = np.eye(3) * xx.sum() - np.einsum("i,ia,ib->ab", self.m, x, x) + self.Jn.sum(0)
        Mwf = np.einsum("i,iab,ibk->ak", self.m, skew_batch(x), self.Phit) + np.einsum("iab,ibk->ak", self.Jn, self.Phir)
        return S, J, Mwf

    def quad(self, w, eta, etad):
        """二次速度力（构件系的 r 部分未乘 A）：(c_r, Q_ω, Q_f)，Q_r = −A·c_r"""
        x = self.x(eta)
        u = self.Phit @ etad                                      # N×3 节点弹性速度
        c = np.cross(w, np.cross(w, x)) + 2 * np.cross(w, u)       # N×3
        mc = self.m[:, None] * c
        cr = mc.sum(0)
        Om = w + self.Phir @ etad                                  # N×3
        h = np.einsum("iab,ib->ia", self.Jn, Om)
        wr = np.cross(w, h)
        Qw = -np.cross(x, mc).sum(0) - wr.sum(0)
        Qf = -np.einsum("iak,ia->k", self.Phit, mc) - np.einsum("iak,ia->k", self.Phir, wr)
        return cr, Qw, Qf

    def gravity(self, gb, eta):
        """构件系重力 gb：(Q_ω, Q_f)；Q_r = m g 由刚体部分给"""
        S = self.m @ self.x(eta)
        return np.cross(S, gb), self.Psi.T @ gb


# ---------------------------------------------------------------- 梁
def _beam_element(L, E, G, A, Iy, Iz, J):
    """12×12 欧拉梁单元刚度（局部系：x 沿梁，节点 DOF ux uy uz rx ry rz）"""
    k = np.zeros((12, 12))
    ea, gj = E * A / L, G * J / L
    for a, b, v in ((0, 0, ea), (0, 6, -ea), (6, 6, ea), (3, 3, gj), (3, 9, -gj), (9, 9, gj)):
        k[a, b] = v
    # xy 平面弯曲：uy、rz，用 Iz
    c = E * Iz / L ** 3
    idx = [1, 5, 7, 11]
    kb = c * np.array([[12, 6 * L, -12, 6 * L], [6 * L, 4 * L * L, -6 * L, 2 * L * L], [-12, -6 * L, 12, -6 * L],
                       [6 * L, 2 * L * L, -6 * L, 4 * L * L]])
    for r_, a in enumerate(idx):
        for s_, b in enumerate(idx):
            k[a, b] += kb[r_, s_]
    # xz 平面弯曲：uz、ry，用 Iy（ry 与 uz 的符号相反）
    c = E * Iy / L ** 3
    idx = [2, 4, 8, 10]
    kb = c * np.array([[12, -6 * L, -12, -6 * L], [-6 * L, 4 * L * L, 6 * L, 2 * L * L], [-12, 6 * L, 12, 6 * L],
                       [-6 * L, 2 * L * L, 6 * L, 4 * L * L]])
    for r_, a in enumerate(idx):
        for s_, b in enumerate(idx):
            k[a, b] += kb[r_, s_]
    for a in range(12):
        for b in range(a):
            k[a, b] = k[b, a] = max(k[a, b], k[b, a], key=abs)
    return k


def beam_fe(P0, P1, yax, E, G, rho, A, Iy, Iz, J, n_el):
    """直梁有限元（地面系，SI）：节点坐标 N×3、K、M（HRZ 集中质量，6N×6N 对角）、节点平动质量、节点转动惯量 N×3×3"""
    P0, P1 = np.asarray(P0, float), np.asarray(P1, float)
    ax = P1 - P0
    Lt = float(np.linalg.norm(ax))
    if Lt <= 0:
        raise FlexError("梁两端重合")
    ex = ax / Lt
    ey = np.asarray(yax, float) - (np.asarray(yax, float) @ ex) * ex
    if np.linalg.norm(ey) < 1e-9:
        raise FlexError("梁的 y_axis 不能与梁轴平行")
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    R = np.column_stack([ex, ey, ez])               # 局部 → 地面
    N = n_el + 1
    X = P0 + np.outer(np.linspace(0, 1, N), ax)
    L = Lt / n_el
    ke = _beam_element(L, E, G, A, Iy, Iz, J)
    T = sla.block_diag(R, R, R, R)
    kg = T @ ke @ T.T
    K = np.zeros((6 * N, 6 * N))
    for e in range(n_el):
        s = slice(6 * e, 6 * e + 12)
        K[s, s] += kg
    me = rho * A * L
    m = np.full(N, me)
    m[0] = m[-1] = me / 2
    jl = np.diag([rho * (Iy + Iz) * L / 2, me * L * L / 78, me * L * L / 78])  # 每个单元给每个端节点的量（HRZ）
    Jn = np.array([R @ (jl * (1.0 if k in (0, N - 1) else 2.0)) @ R.T for k in range(N)])
    Md = np.zeros(6 * N)
    for k in range(N):
        Md[6 * k:6 * k + 3] = m[k]
        Md[6 * k + 3:6 * k + 6] = np.diag(Jn[k])
    # 转动惯量阵在地面轴下可能不是对角（梁斜放时）：用完整 3×3 块
    M = np.diag(Md)
    for k in range(N):
        M[6 * k + 3:6 * k + 6, 6 * k + 3:6 * k + 6] = Jn[k]
    return X, K, M, m, Jn


def craig_bampton(K, M, boundary, n_fixed, keep=None):
    """Craig-Bampton 缩减后再正交化、去掉 6 个刚体模态：返回 (全 DOF 振型 n×nm（质量归一）, 角频率 rad/s)"""
    n = K.shape[0]
    b = np.asarray(sorted(boundary))
    i = np.array(sorted(set(range(n)) - set(b.tolist())))
    Kii, Kib = K[np.ix_(i, i)], K[np.ix_(i, b)]
    Psi = -np.linalg.solve(Kii, Kib)
    cols = [np.zeros((n, len(b)))]
    cols[0][b, np.arange(len(b))] = 1.0
    cols[0][i, :] = Psi
    if n_fixed > 0 and len(i):
        lam, V = sla.eigh(Kii, M[np.ix_(i, i)])
        nf = min(n_fixed, len(i))
        Phi = np.zeros((n, nf))
        Phi[i, :] = V[:, :nf]
        cols.append(Phi)
    Tcb = np.hstack(cols)
    Kr, Mr = Tcb.T @ K @ Tcb, Tcb.T @ M @ Tcb
    Kr, Mr = (Kr + Kr.T) / 2, (Mr + Mr.T) / 2
    lam, V = sla.eigh(Kr, Mr)
    top = max(abs(lam).max(), 1e-30)
    rigid = lam < RIGID_TOL * top
    if int(rigid.sum()) != 6:
        raise FlexError(f"缩减后刚体模态是 {int(rigid.sum())} 个（应为 6）：构件可能没连成一体")
    lam, V = lam[~rigid], V[:, ~rigid]
    if keep:
        lam, V = lam[:keep], V[:, :keep]
    return Tcb @ V, np.sqrt(lam)


def from_full(X, m, Jn, shapes, freqs, cm, zeta, interface):
    """全 DOF 振型（n×nm）→ FlexData（构件系原点在质心 cm）"""
    N = len(X)
    nm = shapes.shape[1]
    S = shapes.reshape(N, 6, nm)
    return FlexData(X - cm, m, Jn, S[:, :3, :], S[:, 3:, :], freqs, zeta, interface, nodes_world0=X)
