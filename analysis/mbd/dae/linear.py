"""工作点线性化：状态空间矩阵、特征值、模态（ADR-0097 D4，补充七、八）。

状态 x = [z, u]：z 是工作点上用 QR 选主元从扰动坐标 (δr, δπ) 里挑出的独立坐标，u 是对应的速度 (ṙ, ω)；
f(x) 由精确的约束动力学给出，
A 用中心差分，B 由加速度方程对输入广义力的线性关系直接解出，C 对测量量中心差分。
"""

from __future__ import annotations

import math

import numpy as np
import scipy.linalg as sla

from analysis.mbd.dae import solve as S
from analysis.mbd.dae.system import A_of, E_of

REL_STEP = 1e-6
NONSMOOTH = ("contact", "gear", "clearance")
MM, DEG = 1e-3, math.pi / 180


def _qmul(a, b):
    a0, av, b0, bv = a[0], a[1:], b[0], b[1:]
    return np.concatenate([[a0 * b0 - av @ bv], a0 * bv + b0 * av + np.cross(av, bv)])


def _qexp(phi):
    th = float(np.linalg.norm(phi))
    if th < 1e-12:
        return np.concatenate([[1.0], 0.5 * phi])
    return np.concatenate([[math.cos(th / 2)], math.sin(th / 2) * phi / th])


def _skew(a):
    return np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])


def linearize(sysm, q, qd, t=0.0, inputs=(), outputs=(), n_modes=None):
    """扰动坐标：每个构件 (δr, δπ)，δπ 是地面系小转动向量（p = exp(δπ)⊗p₀）；速度 (ṙ, ω)。
    用这套坐标而不是欧拉参数，旋转中的构件（转子）线性化后的涡动频率才对：欧拉参数本身随自转变化，直接对它线性化会差 Ω/2。"""
    keep, drop = S.independent_rows(sysm, q, t)
    rows = S._rows(sysm, keep)
    q = S.assemble(sysm, q, t, rows)
    crow = [r for r in rows if r.kind != "norm"]
    nb, n = sysm.nb, sysm.n
    nf = n - 7 * nb                       # D6：模态坐标（接在刚体坐标后面），扰动就是 δη
    N6 = 6 * nb + nf

    def T_of(qq):
        T = np.zeros((n, N6))
        for k in range(nb):
            p = qq[7 * k + 3:7 * k + 7]
            T[7 * k:7 * k + 3, 6 * k:6 * k + 3] = np.eye(3)
            T[7 * k + 3:7 * k + 7, 6 * k + 3:6 * k + 6] = 0.5 * E_of(p).T
        if nf:
            T[7 * nb:, 6 * nb:] = np.eye(nf)
        return T

    def Jr(qq):
        return sysm.jac(qq, t, crow) @ T_of(qq) if crow else np.zeros((0, N6))

    J0 = Jr(q)
    m = J0.shape[0]
    dof = N6 - m
    if dof <= 0:
        raise S.SolveError("没有自由度，不能线性化")
    if m:
        Jw = J0.copy()
        Jw[:, 6 * nb:] *= S.FLEX_PIVOT_WEIGHT     # 与动力学一样：模态坐标留作独立坐标
        _, _, piv = sla.qr(Jw, pivoting=True, mode="economic")
        dep = np.sort(piv[:m])
    else:
        dep = np.array([], int)
    ind = np.array(sorted(set(range(N6)) - set(dep.tolist())))

    def q_of(dy):
        qq = q.copy()
        for k in range(nb):
            qq[7 * k:7 * k + 3] = q[7 * k:7 * k + 3] + dy[6 * k:6 * k + 3]
            qq[7 * k + 3:7 * k + 7] = _qmul(_qexp(dy[6 * k + 3:6 * k + 6]), q[7 * k + 3:7 * k + 7])
        if nf:
            qq[7 * nb:] = q[7 * nb:] + dy[6 * nb:]
        return qq

    def complete(z, u):
        dy = np.zeros(N6)
        dy[ind] = z
        qq = q_of(dy)
        for _ in range(S.NEWTON_MAX):
            if not m:
                break
            ph = sysm.phi(qq, t, crow)
            if np.max(np.abs(ph)) < 1e-15:
                break
            dx = np.linalg.solve(Jr(qq)[:, dep], -ph)
            dy[dep] += dx
            qq = q_of(dy)
            if np.max(np.abs(dx)) < 1e-16:
                break
        v = np.zeros(N6)
        v[ind] = u
        if m:
            Jq = Jr(qq)
            v[dep] = np.linalg.solve(Jq[:, dep], sysm.nu(qq, t, crow) - Jq[:, ind] @ u)
        return dy, qq, v, T_of(qq) @ v

    def vdot(qq, qdd):
        out = np.zeros(N6)
        for k in range(nb):
            out[6 * k:6 * k + 3] = qdd[7 * k:7 * k + 3]
            out[6 * k + 3:6 * k + 6] = 2 * E_of(qq[7 * k + 3:7 * k + 7]) @ qdd[7 * k + 3:7 * k + 7]
        if nf:
            out[6 * nb:] = qdd[7 * nb:]
        return out

    ref = {"v": np.zeros(N6)}

    def f(x):
        # 扰动是相对“随工作点速度运动的参考”量的：r = r_ref(t) + δr，R = exp(δπ)·R_ref(t)，R_ref 以工作点角速度 ω_ref 转。
        # 于是 δṙ = ṙ − v_ref，δπ̇ = J_l⁻¹(δπ)(ω − exp(δπ)ω_ref)。对静止工作点就是普通的扰动；对转子这一项给出正确的陀螺耦合。
        dy, qq, v, vv = complete(x[:dof], x[dof:])
        acc, _ = S.accel(sysm, qq, vv, t, rows)
        dyd = v - ref["v"]
        for k in range(nb):
            ph = dy[6 * k + 3:6 * k + 6]
            S_ = _skew(ph)
            w_ref = sla.expm(S_) @ ref["v"][6 * k + 3:6 * k + 6]
            dyd[6 * k + 3:6 * k + 6] = (np.eye(3) - 0.5 * S_ + S_ @ S_ / 12) @ (v[6 * k + 3:6 * k + 6] - w_ref)
        return np.concatenate([dyd[ind], vdot(qq, acc)[ind]])

    # 工作点速度（满足速度约束）
    v0 = np.zeros(N6)
    for k in range(nb):
        v0[6 * k:6 * k + 3] = qd[7 * k:7 * k + 3]
        v0[6 * k + 3:6 * k + 6] = 2 * E_of(q[7 * k + 3:7 * k + 7]) @ qd[7 * k + 3:7 * k + 7]
    if nf:
        v0[6 * nb:] = qd[7 * nb:]
    _, _, v0, qd = complete(np.zeros(dof), v0[ind])
    ref["v"] = v0.copy()
    x0 = np.concatenate([np.zeros(dof), v0[ind]])
    A = _jac(f, x0)
    M = sysm.mass(q)
    Jf = sysm.jac(q, t, rows)
    K = np.block([[M, Jf.T], [Jf, np.zeros((len(rows), len(rows)))]])
    B = np.zeros((2 * dof, len(inputs)))
    for k, u in enumerate(inputs):
        F, N = np.zeros((nb, 3)), np.zeros((nb, 3))
        b = u["body"]
        r, p = sysm.rp(q, b)
        if u["type"] == "force":
            sysm._add(F, N, q, b, u["dir"], r + A_of(p) @ u["s"])
        else:
            N[b] += u["dir"]
        sol = np.linalg.lstsq(K, np.concatenate([sysm.Q_extra(q, qd, F, N), np.zeros(len(rows))]), rcond=None)[0]
        B[dof:, k] = vdot(q, sol[:n])[ind]
    C = np.zeros((len(outputs), 2 * dof))
    if outputs:
        def g(x):
            _, qq, _, vv = complete(x[:dof], x[dof:])
            mm = sysm.measures(qq, vv)
            return np.array([mm[o] for o in outputs])
        C = _jac(g, x0)
    D = np.zeros((len(outputs), len(inputs)))

    lam, V = np.linalg.eig(A)
    modes = []
    big = max(1.0, float(np.abs(lam).max()))
    zeros = [k for k in range(len(lam)) if abs(lam[k]) < 1e-8 * big]
    skip = set(zeros[: len(zeros) // 2])          # 刚体模态的零特征值成对出现（位置、速度）：每对只报一个
    for k in np.argsort(np.abs(lam)):
        if k in skip:
            continue
        lk = lam[k]
        if lk.imag < -1e-9 * max(1.0, abs(lk)):
            continue                                 # 共轭对只留虚部为正的那个（重根各自保留）
        w = abs(lk)
        modes.append({"eigenvalue": [float(lk.real), float(lk.imag)], "frequency_hz": w / (2 * math.pi),
                      "damped_frequency_hz": abs(lk.imag) / (2 * math.pi),
                      "damping_ratio": (-lk.real / w) if w > 0 else None,
                      "shape": _shape(sysm, J0, dep, ind, V[:dof, k])})
    if n_modes:
        modes = modes[:n_modes]
    fnames = [f"{b.name}.eta{m + 1}" for b in sysm.bodies if b.flex is not None for m in range(b.flex.nm)]
    names = [f"{sysm.bodies[i // 6].name}.{['dx', 'dy', 'dz', 'rx', 'ry', 'rz'][i % 6]}" if i < 6 * nb
             else fnames[i - 6 * nb] for i in ind]
    return {"dof": dof, "states": names + [s_ + "_dot" for s_ in names], "independent_coordinates": names,
            "A": A.tolist(), "B": B.tolist(), "C": C.tolist(), "D": D.tolist(),
            "inputs": [u["id"] for u in inputs], "outputs": list(outputs), "modes": modes,
            "redundant": [sysm.rows[k].label for k in drop]}, q, qd


def _jac(f, x0):
    f0 = f(x0)
    out = np.zeros((len(f0), len(x0)))
    for k in range(len(x0)):
        h = REL_STEP * max(1.0, abs(x0[k]))
        xp, xm = x0.copy(), x0.copy()
        xp[k] += h
        xm[k] -= h
        out[:, k] = (f(xp) - f(xm)) / (2 * h)
    return out


def _shape(sysm, J, dep, ind, vz):
    """振型：各构件质心位移（mm）与转角（deg），最大分量归一为 1（相位转到最大分量为实数）"""
    vz = np.asarray(vz, complex)
    dy = np.zeros(J.shape[1], complex)
    dy[ind] = vz
    if len(dep):
        dy[dep] = -np.linalg.solve(J[:, dep], J[:, ind] @ vz)
    parts = {b.name: (dy[6 * k:6 * k + 3] / MM, dy[6 * k + 3:6 * k + 6] / DEG) for k, b in enumerate(sysm.bodies)}
    allv = np.concatenate([np.concatenate(v) for v in parts.values()])
    big = allv[np.argmax(np.abs(allv))]
    if abs(big) == 0:
        return {name: {"translation_mm": [0.0] * 3, "rotation_deg": [0.0] * 3} for name in parts}
    rot = abs(big) / big
    return {name: {"translation_mm": np.real(dr * rot / abs(big)).tolist(), "rotation_deg": np.real(dth * rot / abs(big)).tolist()}
            for name, (dr, dth) in parts.items()}


def nonsmooth(sysm):
    return any(kind in NONSMOOTH for kind, _ in sysm.forces) or any(i.get("friction") for i in sysm.joints.values())
