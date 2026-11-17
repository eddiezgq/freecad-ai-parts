"""分析（ADR-0097 D1）：运动学、动力学（坐标分块 + 误差控制积分）、静平衡；冗余约束识别；核查。内部 SI。"""

from __future__ import annotations

import math

import numpy as np
import scipy.linalg as sla
from scipy.integrate import solve_ivp
from scipy.optimize import root

from analysis.mbd.dae.system import A_of, B_of, E_of, G_of, System

TOL_PHI = 1e-10      # 约束残差（m 或无量纲）
NEWTON_MAX = 30


class SolveError(RuntimeError):
    pass


# ---------------------------------------------------------------- 冗余约束与装配
def independent_rows(sysm: System, q, t):
    """雅可比按行做带主元的 QR，挑出线性无关的约束行（ADAMS 同样会删掉冗余约束，并报出来）"""
    J = sysm.jac(q, t)
    if J.shape[0] == 0:
        return [], []
    _, R, piv = sla.qr(J.T, pivoting=True, mode="economic")
    d = np.abs(np.diag(R))
    tol = max(J.shape) * np.finfo(float).eps * max(d[0], 1.0) * 1e3
    rank = int(np.sum(d > tol))
    keep = sorted(int(x) for x in piv[:rank])
    drop = sorted(int(x) for x in piv[rank:])
    return keep, drop


def assemble(sysm: System, q, t, rows, free=None):
    """牛顿迭代把 q 拉回约束面（最小改动：伪逆）；free 给出只许动的坐标下标"""
    q = q.copy()
    for _ in range(NEWTON_MAX):
        ph = sysm.phi(q, t, rows)
        if np.max(np.abs(ph), initial=0.0) < TOL_PHI:
            return q
        J = sysm.jac(q, t, rows)
        if free is not None:
            dx = np.linalg.lstsq(J[:, free], -ph, rcond=None)[0]
            q[free] += dx
        else:
            q += np.linalg.lstsq(J, -ph, rcond=None)[0]
    ph = sysm.phi(q, t, rows)
    if np.max(np.abs(ph), initial=0.0) > 1e-7:
        bad = int(np.argmax(np.abs(ph)))
        raise SolveError(f"装配不上：约束“{rows[bad] if isinstance(rows[bad], str) else rows[bad].label}”残差 {ph[bad]:.3g}")
    return q


def _rows(sysm, idx):
    return [sysm.rows[k] for k in idx]


def initial_velocity(sysm: System, q, t, rows):
    """初速度：构件给的 v0、ω0 与运动副初速度，按最小改动投影到速度约束上"""
    qd0 = np.zeros(sysm.n)
    for k, b in enumerate(sysm.bodies):
        p = sysm.rp(q, k)[1]
        qd0[7 * k:7 * k + 3] = b.v0
        qd0[7 * k + 3:7 * k + 7] = 0.5 * E_of(p).T @ b.w0
    J, nu = sysm.jac(q, t, rows), sysm.nu(q, t, rows)
    extra_J, extra_v = [], []
    for info in sysm.joints.values():
        if "initial_speed" not in info:
            continue
        i, j = info["i"], info["j"]
        row = np.zeros(sysm.n)
        if info["type"] == "translational":
            h = info["h"] if i < 0 else A_of(sysm.rp(q, i)[1]) @ info["h"]
            if j >= 0:
                row[7 * j:7 * j + 3] += h
                row[7 * j + 3:7 * j + 7] += h @ B_of(sysm.rp(q, j)[1], info["sj"])
            if i >= 0:
                row[7 * i:7 * i + 3] -= h
                row[7 * i + 3:7 * i + 7] -= h @ B_of(sysm.rp(q, i)[1], info["si"])
            val = info["initial_speed"] * 1e-3
        else:
            h = info["h"] if i < 0 else A_of(sysm.rp(q, i)[1]) @ info["h"]
            if j >= 0:
                row[7 * j + 3:7 * j + 7] += 2 * h @ E_of(sysm.rp(q, j)[1])
            if i >= 0:
                row[7 * i + 3:7 * i + 7] -= 2 * h @ E_of(sysm.rp(q, i)[1])
            val = math.radians(info["initial_speed"])
        extra_J.append(row)
        extra_v.append(val)
    if extra_J:
        J = np.vstack([J, np.array(extra_J)])
        nu = np.concatenate([nu, extra_v])
    r = nu - J @ qd0
    corr = np.linalg.lstsq(J, r, rcond=None)[0]
    qd = qd0 + corr
    if np.max(np.abs(J @ qd - nu), initial=0) > 1e-8:
        raise SolveError("初速度和运动副、驱动不相容（运动副初速度与驱动冲突，或给了被约束住的速度）")
    return qd


# ---------------------------------------------------------------- 加速度与反力
FRICTION_ITER = 30


def _friction_joints(sysm):
    return [jid for jid, info in sysm.joints.items() if info.get("friction")]


def _joint_forces(sysm, q, J, lam, rows, jids):
    """摩擦要用的运动副约束力（作用在 body_j 上，地面系；只用到大小和方向，不分正负）"""
    pos = {id(r): n for n, r in enumerate(rows)}
    out = {}
    for jid in jids:
        info = sysm.joints[jid]
        ks = [pos[id(sysm.rows[r])] for r in info["rows"] if id(sysm.rows[r]) in pos]
        b = info["j"] if info["j"] >= 0 else info["i"]
        gen = -J[ks].T @ lam[ks] if ks else np.zeros(sysm.n)
        F, _ = _gen_to_wrench(sysm, q, b, gen)
        out[jid] = (F, None)
    return out


def accel(sysm: System, q, qd, t, rows):
    M = sysm.mass(q)
    J = sysm.jac(q, t, rows)
    gam = sysm.gamma(q, qd, t, rows)
    m = J.shape[0]
    K = np.block([[M, J.T], [J, np.zeros((m, m))]])
    try:
        lu = sla.lu_factor(K)

        def solve(r):
            return sla.lu_solve(lu, r)
    except (np.linalg.LinAlgError, ValueError):
        def solve(r):
            return np.linalg.lstsq(K, r, rcond=None)[0]
    Q0 = sysm.Q(q, qd, t)
    if getattr(sysm, "relax_alpha", 0.0):
        Q0 = Q0 - sysm.relax_alpha * (M @ qd)
    x = solve(np.concatenate([Q0, gam]))
    jids = _friction_joints(sysm)
    if jids:
        # 摩擦力随约束反力变：不动点迭代（反力 → 摩擦 → 反力），一般 3~6 次收敛
        for _ in range(FRICTION_ITER):
            react = _joint_forces(sysm, q, J, x[sysm.n:], rows, jids)
            Fx, Nx = sysm.friction_wrenches(q, qd, react)
            Qf = Q0 + sysm.Q_extra(q, qd, Fx, Nx)
            x1 = solve(np.concatenate([Qf, gam]))
            done = np.max(np.abs(x1 - x)) <= 1e-12 * (1 + np.max(np.abs(x1)))
            x = x1
            if done:
                break
    return x[:sysm.n], x[sysm.n:]


def reactions(sysm: System, q, t, rows_idx, lam):
    """每个运动副作用在 body_j 上的约束力（地面系，N）和对运动副中心的力矩（N·m）；驱动的力矩 / 力"""
    rows = _rows(sysm, rows_idx)
    J = sysm.jac(q, t, rows)
    out, motions = {}, {}
    pos = {r: n for n, r in enumerate(rows_idx)}
    for jid, info in sysm.joints.items():
        j = info["j"]
        ks = [pos[r] for r in info["rows"] if r in pos]
        if j < 0:  # 反力报在 body_i 上，取反
            j_eff, sgn, s = info["i"], -1.0, info["si"]
        else:
            j_eff, sgn, s = j, 1.0, info["sj"]
        gen = -J[ks].T @ lam[ks] if ks else np.zeros(sysm.n)
        F, Nn = _gen_to_wrench(sysm, q, j_eff, gen)
        sw = A_of(sysm.rp(q, j_eff)[1]) @ s
        out[jid] = {"force": sgn * F, "torque": sgn * (Nn - np.cross(sw, F)), "on": sysm.bodies[j_eff].name,
                    "complete": len(ks) == len(info["rows"])}
    for mid, mo in sysm.motions.items():
        r = mo["row"]
        if r not in pos:
            continue
        info = sysm.joints[mo["joint"]]
        k = pos[r]
        gen = -J[[k]].T @ lam[[k]]
        j = info["j"] if info["j"] >= 0 else info["i"]
        sgn = 1.0 if info["j"] >= 0 else -1.0
        F, Nn = _gen_to_wrench(sysm, q, j, gen)
        i = info["i"]
        h = info["h"] if i < 0 else A_of(sysm.rp(q, i)[1]) @ info["h"]
        if mo["dof"] == "rotation":
            motions[mid] = sgn * float(h @ (Nn - np.cross(A_of(sysm.rp(q, j)[1]) @ (info["sj"] if sgn > 0 else info["si"]), F)))
        else:
            motions[mid] = sgn * float(h @ F)
    return out, motions


def _gen_to_wrench(sysm, q, b, gen):
    F = gen[7 * b:7 * b + 3]
    Qp = gen[7 * b + 3:7 * b + 7]
    p = sysm.rp(q, b)[1]
    n_body = 0.5 * G_of(p) @ Qp
    return F, A_of(p) @ n_body


# ---------------------------------------------------------------- 记录
class Recorder:
    def __init__(self, sysm: System):
        self.s = sysm
        self.t, self.q, self.qd, self.qdd = [], [], [], []
        self.react, self.motion, self.energy, self.resid = [], [], [], []

    def add(self, t, q, qd, qdd, rows_idx, lam):
        s = self.s
        self.t.append(t)
        self.q.append(q.copy())
        self.qd.append(qd.copy())
        self.qdd.append(qdd.copy())
        r, m = reactions(s, q, t, rows_idx, lam)
        self.react.append(r)
        self.motion.append(m)
        self.energy.append(s.energy(q, qd))
        self.resid.append(float(np.max(np.abs(s.phi(q, t)), initial=0.0)))


# ---------------------------------------------------------------- 分析
def kinematic(sysm: System, t_end, steps):
    q = sysm.q0()
    keep, drop = independent_rows(sysm, q, 0.0)
    rows = _rows(sysm, keep)
    dof = sysm.n - len(keep)
    if dof != 0:
        raise SolveError(f"运动学分析要自由度为 0（加了驱动以后还剩 {dof} 个自由度）；有自由度的用动力学分析")
    rec = Recorder(sysm)
    for t in np.linspace(0.0, t_end, steps + 1):
        q = assemble(sysm, q, t, rows)
        J = sysm.jac(q, t, rows)
        qd = np.linalg.solve(J, sysm.nu(q, t, rows))
        qdd = np.linalg.solve(J, sysm.gamma(q, qd, t, rows))
        Q = sysm.Q(q, qd, t)
        lam = np.linalg.solve(J.T, Q - sysm.mass(q) @ qdd)
        rec.add(float(t), q, qd, qdd, keep, lam)
    return rec, {"dof": 0, "redundant": [sysm.rows[k].label for k in drop]}


RELAX_ALPHA = 1000.0     # 1/s，静平衡找不到时“过阻尼动力学放松”的质量比例阻尼
RELAX_TIME = 0.05        # s


def _nonsmooth(sysm):
    return any(kind in ("contact", "gear", "clearance") for kind, _ in sysm.forces)


def static(sysm: System, t=0.0, q=None):
    """静平衡。直接解不出来、且模型有接触 / 齿轮 / 间隙（力在间隙里为 0，牛顿法没有方向）时，
    先用重阻尼的动力学放松一段，再从放松后的位置解（ADR-0097 补充六）"""
    try:
        return _static(sysm, t, q)
    except SolveError:
        if not _nonsmooth(sysm):
            raise
    sysm.relax_alpha = RELAX_ALPHA
    try:
        rec0, _ = dynamic(sysm, RELAX_TIME, 5, q=q, t0=t, qd=np.zeros(sysm.n))
    finally:
        sysm.relax_alpha = 0.0
    rec, info = _static(sysm, t, rec0.q[-1])
    info["relaxed"] = True
    return rec, info


def _static(sysm: System, t=0.0, q=None):
    """静平衡：Q(q) − Φ_qᵀλ = 0、Φ(q) = 0（速度为 0）"""
    q = sysm.q0() if q is None else q
    keep, drop = independent_rows(sysm, q, t)
    rows = _rows(sysm, keep)
    q = assemble(sysm, q, t, rows)
    m = len(rows)
    zero = np.zeros(sysm.n)

    def F(x):
        qq, lam = x[:sysm.n], x[sysm.n:]
        return np.concatenate([sysm.Q(qq, zero, t) - sysm.jac(qq, t, rows).T @ lam, sysm.phi(qq, t, rows)])

    J0 = sysm.jac(q, t, rows)
    lam0 = np.linalg.lstsq(J0.T, sysm.Q(q, zero, t), rcond=None)[0]
    sol = root(F, np.concatenate([q, lam0]), method="hybr", options={"xtol": 1e-13, "maxfev": 20000})
    x = sol.x
    res = F(x)
    if not np.all(np.isfinite(res)) or np.max(np.abs(res)) > 1e-6:
        raise SolveError(f"静平衡没找到（残差 {np.max(np.abs(res)):.3g}）；可能是机构没有稳定的平衡位置")
    q, lam = x[:sysm.n], x[sysm.n:m + sysm.n]
    rec = Recorder(sysm)
    rec.add(t, q, zero, np.zeros(sysm.n), keep, lam)
    return rec, {"dof": sysm.n - m, "redundant": [sysm.rows[k].label for k in drop], "residual": float(np.max(np.abs(res)))}


def dynamic(sysm: System, t_end, steps, method="DOP853", rtol=1e-8, atol=1e-10, q=None, qd=None, t0=0.0):
    q = sysm.q0() if q is None else q.copy()
    keep, drop = independent_rows(sysm, q, t0)
    rows = _rows(sysm, keep)
    q = assemble(sysm, q, t0, rows)
    dof = sysm.n - len(keep)
    if dof <= 0:
        raise SolveError("没有自由度（全被驱动定死了），请用运动学分析")
    if qd is None:
        qd = initial_velocity(sysm, q, t0, rows)
    rec = Recorder(sysm)
    times = np.linspace(t0, t0 + t_end, steps + 1)
    stats = {"rhs": 0, "repartitions": 0, "segments": 0}
    state = {"q": q.copy()}

    def partition(q, t):
        J = sysm.jac(q, t, rows)
        _, _, piv = sla.qr(J, pivoting=True, mode="economic")
        dep = np.sort(piv[:len(rows)])
        ind = np.array(sorted(set(range(sysm.n)) - set(dep.tolist())))
        return dep, ind

    def full_state(t, y, dep, ind, need_acc=True):
        q = state["q"].copy()
        q[ind] = y[:dof]
        # 积分器看到的右端要“干净”：牛顿迭代解到 1e-14（比积分容差小得多），否则紧容差时步长会被噪声拖小
        for _ in range(NEWTON_MAX):
            ph = sysm.phi(q, t, rows)
            if np.max(np.abs(ph)) < 1e-14:
                break
            J = sysm.jac(q, t, rows)
            dx = np.linalg.solve(J[:, dep], -ph)
            q[dep] += dx
            if np.max(np.abs(dx)) < 1e-15:
                break
        else:
            if np.max(np.abs(sysm.phi(q, t, rows))) > 1e-9:
                raise SolveError("积分中约束解不回来（分块病态）")
        state["q"] = q
        J = sysm.jac(q, t, rows)
        qd = np.zeros(sysm.n)
        qd[ind] = y[dof:]
        qd[dep] = np.linalg.solve(J[:, dep], sysm.nu(q, t, rows) - J[:, ind] @ qd[ind])
        if not need_acc:
            return q, qd, None, None
        qdd, lam = accel(sysm, q, qd, t, rows)
        return q, qd, qdd, lam

    t_cur, q_cur, qd_cur = t0, q, qd
    qdd0, lam0 = accel(sysm, q_cur, qd_cur, t_cur, rows)
    rec.add(float(t_cur), q_cur, qd_cur, qdd0, keep, lam0)
    k = 0                                   # 已记录到 times[k]
    seg = max(1, steps // 50)               # 每段最多这么多个输出点就重新挑一次分块
    while k < steps:
        dep, ind = partition(q_cur, t_cur)
        stats["segments"] += 1
        state["q"] = q_cur.copy()
        y0 = np.concatenate([q_cur[ind], qd_cur[ind]])
        cond0 = np.linalg.cond(sysm.jac(q_cur, t_cur, rows)[:, dep])
        limit = max(1e3, 10 * cond0)
        k1 = min(steps, k + seg)

        def rhs(t, y, dep=dep, ind=ind):
            stats["rhs"] += 1
            keep_q = state["q"].copy()
            try:
                if not np.all(np.isfinite(y)):
                    raise SolveError("NaN")
                _, qd_, qdd_, _ = full_state(t, y, dep, ind)
                if not (np.all(np.isfinite(qd_)) and np.all(np.isfinite(qdd_))):
                    raise SolveError("NaN")
            except (SolveError, np.linalg.LinAlgError):
                # 积分器试的步太大、约束解不回来：退回原点、给 NaN，积分器会拒掉这一步、缩小步长（接触、齿轮这类硬力元会碰到）
                state["q"] = keep_q
                stats["rejected"] = stats.get("rejected", 0) + 1
                return np.full(2 * dof, np.nan)
            return np.concatenate([qd_[ind], qdd_[ind]])

        def ill(t, y, dep=dep, ind=ind, limit=limit):
            # 分块变病态（非独立坐标的雅可比条件数超限）就停下来换分块
            keep_q = state["q"].copy()
            try:
                if not np.all(np.isfinite(y)):
                    raise SolveError("NaN")
                qq, _, _, _ = full_state(t, y, dep, ind, need_acc=False)
            except (SolveError, np.linalg.LinAlgError):
                state["q"] = keep_q
                return 1.0
            return math.log(limit) - math.log(np.linalg.cond(sysm.jac(qq, t, rows)[:, dep]))

        ill.terminal = True
        ill.direction = -1
        t_eval = times[k + 1:k1 + 1]
        sol = solve_ivp(rhs, (t_cur, times[k1]), y0, method=method, t_eval=t_eval, rtol=rtol, atol=atol,
                        events=ill, dense_output=True)
        if sol.status < 0:
            raise SolveError(f"积分失败：{sol.message}")
        for n_, tt in enumerate(sol.t):
            state["q"] = rec.q[-1].copy()       # 牛顿迭代从上一个记录点起步（积分器的最后一次求值可能在更后面）
            qq, qqd, qqdd, lam = full_state(tt, sol.y[:, n_], dep, ind)
            rec.add(float(tt), qq, qqd, qqdd, keep, lam)
            k += 1
        if sol.status == 1:                 # 事件：换分块，从事件点接着积
            stats["repartitions"] += 1
            te = float(sol.t_events[0][0])
            ye = sol.sol(te)
            state["q"] = rec.q[-1].copy()
            q_cur, qd_cur, _, _ = full_state(te, ye, dep, ind, need_acc=False)
            t_cur = te
        else:
            t_cur, q_cur, qd_cur = float(sol.t[-1]), rec.q[-1].copy(), rec.qd[-1].copy()
    return rec, {"dof": dof, "redundant": [sysm.rows[k].label for k in drop], **stats}
