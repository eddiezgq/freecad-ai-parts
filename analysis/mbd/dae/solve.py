"""分析（ADR-0097 D1）：运动学、动力学（坐标分块 + 误差控制积分）、静平衡；冗余约束识别；核查。内部 SI。"""

from __future__ import annotations

import math

import numpy as np
import scipy.linalg as sla
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from scipy.integrate import solve_ivp
from scipy.optimize import root

from analysis.mbd.dae.system import A_of, B_of, E_of, G_of, System

TOL_PHI = 1e-10      # 约束残差（m 或无量纲）
NEWTON_MAX = 30


class SolveError(RuntimeError):
    pass


# ---------------------------------------------------------------- 冗余约束与装配
DRIVE_KINDS = ("rdrive", "tdrive")
NEAR_REDUNDANT = 1e-6    # 运动副约束的奇异值 / 最大奇异值低于它：工程上按冗余处理（制造误差级的偏差），并报出来


def _qr_rows(J, tol=None):
    _, R, piv = sla.qr(J.T, pivoting=True, mode="economic")
    d = np.abs(np.diag(R))
    if tol is None:
        tol = max(J.shape) * np.finfo(float).eps * max(d[0], 1.0) * 1e3
    rank = int(np.sum(d > tol))
    return sorted(int(x) for x in piv[:rank]), sorted(int(x) for x in piv[rank:])


def structural(sysm: System, q, t):
    """只看运动副约束（不含驱动）的秩：精确秩、工程秩（近奇异按冗余）和最接近冗余的那组约束。
    问渠 CAD 0.3.6 细则 C3（《多体动力学》书第 4 章线索第 11 条）：原来连同驱动一起判秩，“运动副缺 1 个秩 + 驱动补上”
    和“运动副满秩（锁死）+ 驱动多余”删的行数一样，锁死的机构被当成有冗余约束照算，被删的真约束在运动中拉开。"""
    srows = [k for k, r in enumerate(sysm.rows) if r.kind not in DRIVE_KINDS]
    if not srows:
        return {"rows": srows, "dof_exact": sysm.n, "dof": sysm.n, "sigma_rel": None, "joints": []}
    J = sysm.jac(q, t, [sysm.rows[k] for k in srows])
    U, sv, _ = np.linalg.svd(J, full_matrices=False)
    tol = max(J.shape) * np.finfo(float).eps * max(sv[0], 1.0) * 1e3
    r_exact = int(np.sum(sv > tol))
    r_eng = int(np.sum(sv > max(tol, NEAR_REDUNDANT * sv[0])))
    # 最小的“精确非零”奇异值：最接近冗余的约束方向；左奇异向量里分量大的行就是参与的运动副
    sig, joints = None, []
    if r_exact:
        k = r_exact - 1
        sig = float(sv[k] / sv[0])
        u = np.abs(U[:, k])
        joints = sorted({sysm.rows[srows[i]].joint or sysm.rows[srows[i]].label for i in np.nonzero(u > 0.2 * u.max())[0]})
    return {"rows": srows, "J": J, "tol": tol, "dof_exact": sysm.n - r_exact, "dof": sysm.n - r_eng, "sigma_rel": sig,
            "joints": joints, "sigma_max": float(sv[0])}


def check_structure(sysm: System, q, t):
    """分析开始前：只看运动副的结构自由度少于驱动数 → 锁死或驱动多余，报错（不删真约束照算）"""
    drives = [r for r in sysm.rows if r.kind in DRIVE_KINDS]
    if not drives:
        return
    st = structural(sysm, q, t)
    if len(drives) > st["dof"]:
        where = "、".join(st["joints"]) or "—"
        sig = f"{st['sigma_rel']:.2g}" if st["sigma_rel"] is not None else "—"
        raise SolveError(
            f"机构锁死或驱动多余：只看运动副，机构的自由度是 {st['dof']}，却加了 {len(drives)} 个驱动。"
            f"最可能卡住的是 {where}（这组约束的奇异值是最大值的 {sig}，高于按冗余处理的界限 {NEAR_REDUNDANT:g}，偏差已超出制造误差的量级）。"
            "检查这几个运动副的位置、方向是否和设计一致；确实要按冗余（靠间隙）处理时，去掉其中一个或改成约束更少的运动副")


def independent_rows(sysm: System, q, t):
    """雅可比按行做带主元的 QR，挑出线性无关的约束行（ADAMS 同样会删掉冗余约束，并报出来）。
    运动副近奇异（制造误差级）→ 按冗余处理并记下；锁死（驱动数多于结构自由度）由分析入口的 check_structure 报错。"""
    J = sysm.jac(q, t)
    if J.shape[0] == 0:
        return [], []
    sysm.near_redundant = None
    keep, drop = _qr_rows(J)
    drives = [k for k, r in enumerate(sysm.rows) if r.kind in DRIVE_KINDS]
    if not drives:
        return keep, drop
    st = structural(sysm, q, t)
    nd = len(drives)
    if nd > st["dof"]:            # 锁死或驱动多余：分析入口（run_model 调 check_structure）会先报错；底层照原来的办法挑行
        return keep, drop
    if nd > st["dof_exact"]:
        # 运动副近奇异：工程上按冗余处理——运动副行用工程阈值挑，驱动全留
        ks, _ = _qr_rows(st["J"], tol=max(st["tol"], NEAR_REDUNDANT * st["sigma_max"]))
        keep = sorted([st["rows"][i] for i in ks] + drives)
        drop = sorted(set(range(len(sysm.rows))) - set(keep))
        sysm.near_redundant = {"sigma_rel": st["sigma_rel"], "joints": st["joints"], "rows": [sysm.rows[k].label for k in drop]}
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
SPARSE_N = 120              # D8：坐标数到这个数以上，线性方程用稀疏 LU（雅可比、KKT 阵都很稀）


def factor(A):
    """方阵分解：大而稀用 splu，小用稠密 LU；返回 solve(rhs)"""
    if A.shape[0] >= SPARSE_N:
        lu = spla.splu(sp.csc_matrix(A))
        return lu.solve
    lu = sla.lu_factor(A)
    return lambda r: sla.lu_solve(lu, r)
FLEX_PIVOT_WEIGHT = 1e-6


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


def accel(sysm: System, q, qd, t, rows, J=None):
    M = sysm.mass(q)
    J = sysm.jac(q, t, rows) if J is None else J
    gam = sysm.gamma(q, qd, t, rows)
    m = J.shape[0]
    K = np.block([[M, J.T], [J, np.zeros((m, m))]])
    try:
        solve = factor(K)
    except (np.linalg.LinAlgError, ValueError, RuntimeError):
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
        if j < 0:  # body_j 是地面：报在 body_i 上。-Jᵀλ 取 body_i 的分量就是作用在 body_i 上的力，不取反
            # （原来取反，报的是作用在地面上的力——《多体动力学》书第 8 章线索第 17 条，问渠 CAD 0.3.6 细则 C1）
            j_eff, sgn, s = info["i"], 1.0, info["si"]
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


def static(sysm: System, t=0.0, q=None, load_steps=1):
    """静平衡。load_steps > 1 时外力和重力分步加（ADR-0101：大变形一步解不出来），每步从上一步的解起步。"""
    if load_steps <= 1:
        return _static_once(sysm, t, q)
    try:
        for k in range(1, load_steps + 1):
            sysm.load_scale = k / load_steps
            try:
                rec, info = _static_once(sysm, t, q)
            except SolveError as exc:
                raise SolveError(f"分步加载第 {k}/{load_steps} 步：{exc}；加大 load_steps 试试") from exc
            q = rec.q[-1]
    finally:
        sysm.load_scale = 1.0
    info["load_steps"] = load_steps
    return rec, info


def _static_once(sysm: System, t=0.0, q=None):
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
    x0 = np.concatenate([q, lam0])
    x = _static_newton(sysm, t, rows, x0) if getattr(sysm, "nlbeams", None) else None
    if x is None:
        sol = root(F, x0, method="hybr", options={"xtol": 1e-13, "maxfev": 20000})
        x = sol.x
    res = F(x)
    # 力的残差按力的量级判（大变形梁内力上万牛，舍入噪声就有 1e-6 N 级）；约束残差按长度判
    fscale = max(1.0, float(np.max(np.abs(sysm.Q(x[:sysm.n], zero, t)))))
    if not np.all(np.isfinite(res)) or np.max(np.abs(res[:sysm.n])) > max(1e-6, 1e-8 * fscale) \
            or np.max(np.abs(res[sysm.n:]), initial=0.0) > 1e-9:
        raise SolveError(f"静平衡没找到（残差 {np.max(np.abs(res)):.3g}）；可能是机构没有稳定的平衡位置")
    q, lam = x[:sysm.n], x[sysm.n:m + sysm.n]
    rec = Recorder(sysm)
    rec.add(t, q, zero, np.zeros(sysm.n), keep, lam)
    return rec, {"dof": sysm.n - m, "redundant": [sysm.rows[k].label for k in drop], "residual": float(np.max(np.abs(res)))}


def _static_newton(sysm, t, rows, x0, iters=60):
    """静平衡的牛顿法（ADR-0101）：雅可比 [[∂(Φqᵀλ − Q)/∂q, Φqᵀ], [Φq, 0]]，力的导数按构件耦合分组差分；回溯线搜索。
    大变形梁这类坐标多、强非线性的问题，scipy 的 hybr（逐列差分、信赖域）既慢又常卡住。收不住返回 None。"""
    from analysis.mbd.dae.hht import color_groups, grouped_fd

    n = sysm.n
    zero = np.zeros(n)
    groups = color_groups(sysm)
    x = x0.copy()

    def resid(x_):
        qq, lam = x_[:n], x_[n:]
        return np.concatenate([sysm.jac(qq, t, rows).T @ lam - sysm.Q(qq, zero, t), sysm.phi(qq, t, rows)])

    r = resid(x)
    scale = max(1.0, float(np.max(np.abs(sysm.Q(x[:n], zero, t)))))
    prev = math.inf
    for _ in range(iters):
        rf, rc = np.max(np.abs(r[:n])), np.max(np.abs(r[n:]), initial=0.0)
        scale = max(1.0, float(np.max(np.abs(sysm.Q(x[:n], zero, t)))))     # 内力（梁的弹性力）也在 Q 里
        if rc <= 1e-12 and (rf <= 1e-10 * scale or (rf <= 1e-8 * scale and rf > 0.5 * prev)):   # 到舍入噪声这一级就停
            return x
        prev = rf
        qq, lam = x[:n], x[n:]
        J = sysm.jac(qq, t, rows)
        gq, _ = grouped_fd(lambda q_, v_, lam=lam: sysm.jac(q_, t, rows).T @ lam - sysm.Q(q_, v_, t), qq, zero, groups)
        K = np.block([[gq, J.T], [J, np.zeros((len(rows), len(rows)))]])
        try:
            dx = factor(K)(-r)
        except (np.linalg.LinAlgError, ValueError, RuntimeError):
            return None
        # 不做线搜索：大变形的第一步常把残差先放大（约束先满足、力再回来），完整牛顿步随后二次收敛
        x = x + dx
        r = resid(x)
        if not np.all(np.isfinite(r)):
            return None
    return x if np.max(np.abs(r)) <= 1e-6 else None


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
    ctrl = getattr(sysm, "ctrl", None)
    ctrl = ctrl if ctrl is not None and ctrl.any else None
    nx = ctrl.nx if ctrl else 0
    rec.ctrl = []                                   # D7：每个记录点的执行器值

    def set_actuators(t, q, qd, xc):
        if ctrl is None:
            return
        sysm.act = ctrl.outputs(t, sysm.measures(q, qd), xc)

    def partition(q, t):
        J = sysm.jac(q, t, rows)
        J = J.copy()
        J[:, 7 * sysm.nb:] *= FLEX_PIVOT_WEIGHT   # D6：非独立坐标优先挑刚体坐标，模态坐标留作独立坐标（否则参考系会漂走）
        _, _, piv = sla.qr(J, pivoting=True, mode="economic")
        dep = np.sort(piv[:len(rows)])
        ind = np.array(sorted(set(range(sysm.n)) - set(dep.tolist())))
        return dep, ind

    def full_state(t, y, dep, ind, need_acc=True):
        q = state["q"].copy()
        q[ind] = y[:dof]
        # 积分器看到的右端要“干净”：牛顿迭代解到 1e-14（比积分容差小得多），否则紧容差时步长会被噪声拖小。
        # D8：简化牛顿——起点的雅可比分解一次反复用（起点离解很近，几步就收敛）；收得慢时再重算
        lu, prev = None, math.inf
        for _ in range(NEWTON_MAX):
            ph = sysm.phi(q, t, rows)
            res = np.max(np.abs(ph))
            if res < 1e-14:
                break
            if lu is None or res > 0.05 * prev:          # 收敛变慢（起点远、或柔性构件）就重算雅可比
                lu = None
            prev = res
            if lu is None:
                try:
                    lu = factor(sysm.jac(q, t, rows)[:, dep])
                except (ValueError, np.linalg.LinAlgError, RuntimeError) as exc:
                    raise SolveError("积分中约束雅可比奇异") from exc
            dx = lu(-ph)
            q[dep] += dx
            if np.max(np.abs(dx)) < 1e-15:
                break
        else:
            if np.max(np.abs(sysm.phi(q, t, rows))) > 1e-9:
                raise SolveError("积分中约束解不回来（分块病态）")
        state["q"] = q
        J = sysm.jac(q, t, rows)
        qd = np.zeros(sysm.n)
        qd[ind] = y[dof:2 * dof]
        qd[dep] = factor(J[:, dep])(sysm.nu(q, t, rows) - J[:, ind] @ qd[ind])
        if not need_acc:
            return q, qd, None, None
        set_actuators(t, q, qd, y[2 * dof:])
        qdd, lam = accel(sysm, q, qd, t, rows, J)
        return q, qd, qdd, lam

    t_cur, q_cur, qd_cur = t0, q, qd
    xc_cur = ctrl.x0.copy() if ctrl else np.zeros(0)
    n_s, h_s = 0, (ctrl.sample if ctrl and ctrl.sample else None)
    if h_s:
        ctrl.start(t0, sysm.measures(q_cur, qd_cur))     # FMU：初始化并走第一拍
    next_s = t0 + h_s if h_s else math.inf
    set_actuators(t_cur, q_cur, qd_cur, xc_cur)
    qdd0, lam0 = accel(sysm, q_cur, qd_cur, t_cur, rows)
    rec.add(float(t_cur), q_cur, qd_cur, qdd0, keep, lam0)
    rec.ctrl.append(dict(getattr(sysm, "act", {})))
    k = 0                                   # 已记录到 times[k]
    seg = max(1, steps // 50)               # 每段最多这么多个输出点就重新挑一次分块
    try:
        return _dynamic_loop(locals())
    finally:
        if ctrl:
            ctrl.close()


def _dynamic_loop(v):
    """dynamic 的积分循环（拆出来是为了 FMU 用 try/finally 关掉）"""
    sysm, rec, rows, keep, drop, steps, times, method, rtol, atol, stats, state = (
        v[k] for k in ("sysm", "rec", "rows", "keep", "drop", "steps", "times", "method", "rtol", "atol", "stats", "state"))
    partition, full_state, ctrl, dof, nx = (v[k] for k in ("partition", "full_state", "ctrl", "dof", "nx"))
    t_cur, q_cur, qd_cur, xc_cur, k, seg = (v[k] for k in ("t_cur", "q_cur", "qd_cur", "xc_cur", "k", "seg"))
    t0, h_s, n_s, next_s = v["t0"], v["h_s"], v["n_s"], v["next_s"]
    while k < steps:
        dep, ind = partition(q_cur, t_cur)
        stats["segments"] += 1
        state["q"] = q_cur.copy()
        y0 = np.concatenate([q_cur[ind], qd_cur[ind], xc_cur])
        cond0 = np.linalg.cond(sysm.jac(q_cur, t_cur, rows)[:, dep])
        limit = max(1e3, 10 * cond0)
        k1 = min(steps, k + seg)
        t_stop = min(float(times[k1]), next_s)

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
                return np.full(2 * dof + nx, np.nan)
            if nx:
                xcd = ctrl.deriv(t, sysm.measures(state["q"], qd_), y[2 * dof:])
                return np.concatenate([qd_[ind], qdd_[ind], xcd])
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
        t_eval = [tt for tt in times[k + 1:k1 + 1] if tt <= t_stop + 1e-12]
        sol = solve_ivp(rhs, (t_cur, t_stop), y0, method=method, t_eval=t_eval, rtol=rtol, atol=atol,
                        events=ill, dense_output=True)
        if sol.status < 0:
            raise SolveError(f"积分失败：{sol.message}")
        for n_, tt in enumerate(sol.t):
            state["q"] = rec.q[-1].copy()       # 牛顿迭代从上一个记录点起步（积分器的最后一次求值可能在更后面）
            try:
                qq, qqd, qqdd, lam = full_state(tt, sol.y[:, n_], dep, ind)
            except SolveError:
                # 两个记录点之间动得多（大摆角、柔性构件）时，从上一点直接牛顿可能收不回来：沿积分器的稠密输出分小步走过去
                t_prev = rec.t[-1]
                state["q"] = rec.q[-1].copy()
                for s_ in range(1, 33):
                    ts = t_prev + (tt - t_prev) * s_ / 32
                    full_state(ts, sol.sol(ts), dep, ind, need_acc=False)
                qq, qqd, qqdd, lam = full_state(tt, sol.y[:, n_], dep, ind)
            rec.add(float(tt), qq, qqd, qqdd, keep, lam)
            rec.ctrl.append(dict(getattr(sysm, "act", {})))
            k += 1
        if sol.status == 1:                 # 事件：换分块，从事件点接着积
            stats["repartitions"] += 1
            te = float(sol.t_events[0][0])
            ye = sol.sol(te)
            state["q"] = rec.q[-1].copy()
            try:
                q_cur, qd_cur, _, _ = full_state(te, ye, dep, ind, need_acc=False)
            except SolveError:
                state["q"] = rec.q[-1].copy()
                for s_ in range(1, 33):
                    ts = rec.t[-1] + (te - rec.t[-1]) * s_ / 32
                    q_cur, qd_cur, _, _ = full_state(ts, sol.sol(ts), dep, ind, need_acc=False)
            t_cur = te
            xc_cur = ye[2 * dof:]
        else:
            if len(sol.t) and abs(sol.t[-1] - t_stop) < 1e-12:
                t_cur, q_cur, qd_cur = float(sol.t[-1]), rec.q[-1].copy(), rec.qd[-1].copy()
                xc_cur = sol.y[2 * dof:, -1]
            else:                               # 停在采样时刻（不是输出点）
                ys = sol.sol(t_stop)
                state["q"] = (rec.q[-1] if len(sol.t) else q_cur).copy()
                q_cur, qd_cur, _, _ = full_state(t_stop, ys, dep, ind, need_acc=False)
                t_cur, xc_cur = t_stop, ys[2 * dof:]
            if h_s and abs(t_cur - next_s) < 1e-12:      # FMU 采样：送入测量量、走一拍、保持输出
                ctrl.sample_at(t_cur, sysm.measures(q_cur, qd_cur))
                n_s += 1
                next_s = t0 + h_s * (n_s + 1)
    return rec, {"dof": dof, "redundant": [sysm.rows[k].label for k in drop], **stats}
