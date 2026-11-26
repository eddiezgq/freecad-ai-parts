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


MOBILITY_STEP = 1e-2     # 有限可动检验：沿可动方向走特征长度的这个比例


def finite_mobility(sysm: System, q, t):
    """动力学开算前的有限可动检验（《多体动力学》书第 44 章线索第 79 条，问渠 CAD 0.3.9 细则）。
    三铰共线的两杆结构：雅可比在这个位形掉秩，数出 1 个自由度，但它只能瞬时可动，离开一点就装不上——原来照算，
    被当成冗余删掉的约束在运动中拉开，或者求根抛“f(a) and f(b) must have different signs”。
    现在对全部约束（含被当成冗余的行）的零空间逐个方向：沿它走特征长度的 1 %，固定变化最大的那个坐标，其余坐标
    投影回约束面。真能动的方向残差收到机器精度；只能瞬时可动的方向残差停在步长平方 / 长度的量级，报错并指出运动副。"""
    rows = list(sysm.rows)
    if not rows or sysm.nb == 0:
        return
    J = sysm.jac(q, t, rows)
    _, sv, Vt = np.linalg.svd(J)
    if sv.size == 0 or sv[0] == 0.0:
        return
    tol = max(J.shape) * np.finfo(float).eps * max(sv[0], 1.0) * 1e3
    N = Vt[int(np.sum(sv > tol)):]
    if not len(N):
        return
    pos = [7 * k + i for k in range(sysm.nb) for i in range(3)]
    rot = [7 * k + 3 + i for k in range(sysm.nb) for i in range(4)]
    cms = [np.asarray(sysm.rp(q, k)[0], float) for k in range(sysm.nb)]
    L = max([np.linalg.norm(a - b) for a in cms for b in cms] + [np.linalg.norm(a) for a in cms] + [1e-2])
    stuck, worst, joints = 0, 0.0, set()
    for v in N:
        scale = max(np.max(np.abs(v[pos])), L * np.max(np.abs(v[rot])), 1e-30) if pos else np.max(np.abs(v))
        h = MOBILITY_STEP * L / scale
        k = int(np.argmax(np.abs(v)))
        free = [i for i in range(sysm.n) if i != k]
        x = q + h * v
        for _ in range(30):
            ph = sysm.phi(x, t, rows)
            if np.max(np.abs(ph)) < 1e-14:
                break
            x[free] += np.linalg.lstsq(sysm.jac(x, t, rows)[:, free], -ph, rcond=None)[0]
        ph = np.abs(sysm.phi(x, t, rows))
        disp = MOBILITY_STEP * L
        if np.max(ph) > 1e-3 * disp * disp / L:
            bad = np.nonzero(ph > 0.1 * np.max(ph))[0]
            joints |= {rows[i].joint for i in bad if rows[i].joint} or {rows[i].label for i in bad}
            stuck, worst = stuck + 1, max(worst, float(np.max(ph)))
    if stuck:
        jtxt = "、".join(f"“{j}”" for j in sorted(joints))
        raise SolveError(
            f"机构锁死或开始时在奇异位形：结构在开始位形只能瞬时可动、不能有限运动（例如三个铰点共线）——"
            f"沿可动方向走 {MOBILITY_STEP * L * 1000:.3g} mm 后约束收不回去（残差 {worst:.2g}），离开这个位形，"
            f"只看运动副的结构自由度是 {max(len(N) - stuck, 0)}；受横向力时内力趋于无穷，动力学算不下去。"
            f"涉及运动副{jtxt}。请检查这些铰点是否共线；它本来就该是不动的结构的话用静力学分析")


def _rows(sysm, idx):
    return [sysm.rows[k] for k in idx]


def initial_velocity(sysm: System, q, t, rows):
    """初速度：构件给的 v0、ω0 与运动副初速度，投影到速度约束上。

    《多体动力学》书第 13 章线索第 22 条（问渠 CAD 0.3.8 细则）：原来在（质心速度, 欧拉参数变化率）空间里不加权地
    最小二乘修正，没写的 ω0 当成 0 去凑——刚体摆只给质心速度 1 m/s、质心距铰点 0.1 m 时，开始的质心速度变成 0.038 m/s，
    无提示；结果还随长度单位变。现在：
    1. 模型里写了的分量（v0_mm_s、w0_deg_s）当硬条件，没写的由运动副补全；相容就原样保留用户给的速度；
    2. 不相容时只对给了的分量按动能加权投影（与坐标、单位无关），没给的由运动副补全，并在
       sysm.init_velocity_notes 里记下哪个构件被改了多少，由 run_model 报出。
    """
    qd0 = np.zeros(sysm.n)
    given = []
    for k, b in enumerate(sysm.bodies):
        p = sysm.rp(q, k)[1]
        qd0[7 * k:7 * k + 3] = b.v0
        qd0[7 * k + 3:7 * k + 7] = 0.5 * E_of(p).T @ b.w0
        if b.v0_given:
            for c in range(3):
                row = np.zeros(sysm.n)
                row[7 * k + c] = 1.0
                given.append((row, b.v0[c]))
        if b.w0_given:
            Ew = 2 * E_of(p)                       # ω（地面系）= 2 E(p) ṗ
            for c in range(3):
                row = np.zeros(sysm.n)
                row[7 * k + 3:7 * k + 7] = Ew[c]
                given.append((row, b.w0[c]))
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
    W = sysm.mass(q)
    sysm.init_velocity_notes = []
    if given:
        Jg = np.vstack([J, np.array([g[0] for g in given])])
        ng = np.concatenate([nu, [g[1] for g in given]])
        qd = _weighted_projection(W, Jg, ng, qd0)
        if np.max(np.abs(Jg @ qd - ng), initial=0) <= 1e-8:
            return qd                              # 用户给的全部保留
    # 不相容：只对用户给了的分量按动能加权（质心速度权 m，角速度权地面系惯量），没给的由运动副补全；
    # 再加一个很小的整体动能权保证唯一
    Wg = np.zeros_like(W)
    for k, b in enumerate(sysm.bodies):
        p = sysm.rp(q, k)[1]
        if b.v0_given:
            Wg[7 * k:7 * k + 3, 7 * k:7 * k + 3] += b.mass * np.eye(3)
        if b.w0_given:
            A, Ew = A_of(p), 2 * E_of(p)
            Wg[7 * k + 3:7 * k + 7, 7 * k + 3:7 * k + 7] += Ew.T @ (A @ b.J @ A.T) @ Ew
    if not given:
        Wg = W
    qd = _weighted_projection(Wg + INIT_W_REG * W, J, nu, qd0)
    if np.max(np.abs(J @ qd - nu), initial=0) > 1e-8:
        raise SolveError("初速度和运动副、驱动不相容（运动副初速度与驱动冲突，或给了被约束住的速度）")
    for k, b in enumerate(sysm.bodies):
        p = sysm.rp(q, k)[1]
        v, w = qd[7 * k:7 * k + 3], 2 * E_of(p) @ qd[7 * k + 3:7 * k + 7]
        dv = float(np.linalg.norm(v - b.v0)) if b.v0_given else 0.0
        dw = float(np.linalg.norm(w - b.w0)) if b.w0_given else 0.0
        if dv > INIT_V_TOL * max(1.0, float(np.linalg.norm(b.v0))) or dw > INIT_W_TOL * max(1.0, float(np.linalg.norm(b.w0))):
            sysm.init_velocity_notes.append(
                "构件“{}”给的初速度与运动副不相容，按动能加权投影改成：质心速度 {} mm/s（给的 {}），"
                "角速度 {} °/s（给的 {}）".format(b.name, _fmt3(v * 1e3), _fmt3(b.v0 * 1e3) if b.v0_given else "未给",
                                                  _fmt3(np.degrees(w)), _fmt3(np.degrees(b.w0)) if b.w0_given else "未给"))
    return qd


INIT_V_TOL = 1e-6        # 相对（m/s 下限 1）：给的初速度被改动超过它就报
INIT_W_TOL = 1e-6
INIT_W_REG = 1e-9      # 没给的分量上的动能权（相对），只为解唯一


def _fmt3(x):
    return "(" + ", ".join(f"{float(c):.4g}" for c in x) + ")"


def _weighted_projection(W, A, b, x0):
    """min (x − x0)ᵀ W (x − x0)，A x = b：W 是质量阵（动能加权）。W 在欧拉参数的径向上是奇异的，
    但 A 里有欧拉参数归一的速度约束，KKT 阵一般可逆；冗余行用最小二乘"""
    n, m = W.shape[0], A.shape[0]
    K = np.block([[W, A.T], [A, np.zeros((m, m))]])
    rhs = np.concatenate([np.zeros(n), b - A @ x0])
    sol = np.linalg.lstsq(K, rhs, rcond=None)[0]
    return x0 + sol[:n]


# ---------------------------------------------------------------- 加速度与反力
FRICTION_ITER = 30           # 普通不动点迭代次数；不收敛再按增益分情况（线索第 29 条）
FRICTION_ITER_MAX = 400
FRICTION_LOCK_GAIN = 0.9        # 增益到这里算“接近自锁”：积分失败时报自锁，算完时提示
FRICTION_ITER_EARLY = 10        # 普通迭代到第 10 次时增益 > 0.5 就提前改用加速
FRICTION_AA_DEPTH = 5
FRICTION_TOL = 1e-12
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
        x = _friction_fixed_point(sysm, q, qd, t, J, rows, jids, Q0, gam, solve, x)
    return x[:sysm.n], x[sysm.n:]


def _friction_fixed_point(sysm, q, qd, t, J, rows, jids, Q0, gam, solve, x):
    """摩擦力随约束反力变：不动点 x = g(x)（反力 → 摩擦 → 反力）。

    一般 3~6 次收敛。《多体动力学》书第 20 章线索第 29 条（问渠 CAD 0.3.8 细则）：原来最多 30 次、不收敛不报，
    μ 大时收敛很慢（μ = 1.5 要 355 次，30 次时差 11 %），增益 ≥ 1（自锁）时根本没有解，照样给出 30 次后的数。
    现在：从上一次的解出发普通迭代（最多 FRICTION_ITER 次，慢就提前停）；没收敛改 Anderson 加速；
    加速后仍不收敛时看普通迭代估出的增益——≥ 1 是没有解（自锁），报“可能自锁”；< 1 记进 sysm.friction_log，
    由 run_model 报“摩擦迭代不收敛”。
    """
    def g(x_):
        react = _joint_forces(sysm, q, J, x_[sysm.n:], rows, jids)
        Fx, Nx = sysm.friction_wrenches(q, qd, react)
        return solve(np.concatenate([Q0 + sysm.Q_extra(q, qd, Fx, Nx), gam])), react

    return _fp_iterate(sysm, t, g, x, "_friction_x")


def _fp_iterate(sysm, t, g, x, key):
    """摩擦不动点 x = g(x) 的通用迭代（g 返回 (新 x, 各运动副反力)）：热启动（上一次的解存在 sysm.<key>）、普通迭代、
    慢就改 Anderson 加速、增益 ≥ 1 判自锁。加速度（accel）与运动学的反力（kinematic）共用"""
    def small(d, ref):
        return np.max(np.abs(d)) <= FRICTION_TOL * (1 + np.max(np.abs(ref)))

    prev = sysm.__dict__.get(key)
    if prev is not None and prev.shape == x.shape:
        x = prev.copy()                  # 从上一次的解出发：积分相邻两步的反力差得很少
    steps = []
    for k in range(FRICTION_ITER):
        x1, react = g(x)
        d = x1 - x
        steps.append(float(np.max(np.abs(d))))
        x = x1
        if small(d, x1):
            setattr(sysm, key, x)
            sysm._friction_lock = None
            return x
        if k >= FRICTION_ITER_EARLY and _gain(steps) > 0.5:
            break                        # 收敛慢：不再空耗普通迭代，下面按增益分情况
    rate = _gain(steps)
    log = sysm.__dict__.setdefault("friction_log", {"slow": 0, "fail": 0, "t_first": None, "joint": None, "rate": 0.0,
                                                        "gain_max": 0.0, "gain_t": None, "gain_joint": None})
    log["slow"] += 1
    if rate > log["gain_max"]:
        # 增益趋近 1 时不动点的摩擦力趋于无穷（τ ≈ a / (1 − 增益)），机构接近卡死；记下最接近的时刻
        log["gain_max"], log["gain_t"], log["gain_joint"] = rate, float(t), _max_friction_joint(sysm, react)
    # Anderson 加速（深度 FRICTION_AA_DEPTH），对线性收缩的不动点几步就到；增益 ≥ 1 也先试，真有解就会收敛，没解才判自锁
    X, G = [], []
    for _ in range(FRICTION_ITER_MAX - FRICTION_ITER):
        gx, react = g(x)
        f = gx - x
        if small(f, gx):
            setattr(sysm, key, gx)
            sysm._friction_lock = None
            return gx
        X.append(x.copy())
        G.append(gx.copy())
        X, G = X[-FRICTION_AA_DEPTH - 1:], G[-FRICTION_AA_DEPTH - 1:]
        if len(X) == 1:
            x = gx
            continue
        F = np.array([gg - xx for gg, xx in zip(G, X, strict=True)]).T
        dF = F[:, 1:] - F[:, :-1]
        dG = np.array(G).T[:, 1:] - np.array(G).T[:, :-1]
        gam_, *_ = np.linalg.lstsq(dF, F[:, -1], rcond=None)
        x = G[-1] - dG @ gam_
    if rate >= 1.0:
        # 增益 ≥ 1：摩擦力越算越大，没有解——机构在这里卡死。照样往下积分只会得到越来越大的假数（原来 μ = 2.0 给 35203 N·m）。
        # 积分器试步时碰上会把它当“步太大”缩步；真走到这里积分就会失败，dynamic 再用 friction_lock 报出原因
        msg = (f"可能自锁：t = {float(t):.6g} s 运动副摩擦的迭代增益约 {rate:.3g}（≥ 1，摩擦力越算越大，没有解），"
               f"摩擦最大的是运动副“{_max_friction_joint(sysm, react)}”。机构在这个位置会卡死；请检查摩擦系数、销半径，"
               "或确认这就是要找的自锁位置")
        sysm._friction_lock = msg
        raise SolveError(msg)
    log["fail"] += 1
    log["rate"] = max(log["rate"], rate)
    if log["t_first"] is None:
        log["t_first"] = float(t)
        log["joint"] = _max_friction_joint(sysm, react)
    return x


def _gain(steps):
    """普通迭代最后几步修正量的几何平均缩小率：线性收缩时就是不动点映射的增益。
    用几何平均而不是相邻比的中位数——迭代常常一大一小交替（相邻比 2.0、0.27 交替，实际每步缩到 0.73）"""
    w = [x for x in steps[-6:] if x > 0]
    if len(w) < 2:
        return 0.0
    return float((w[-1] / w[0]) ** (1.0 / (len(w) - 1)))


def _max_friction_joint(sysm, react):
    best, val = None, -1.0
    for jid, (F, _) in react.items():
        fr = sysm.joints[jid]["friction"]
        v = max(fr["ms"], fr["md"]) * float(np.linalg.norm(F))
        if v > val:
            best, val = jid, v
    return best


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
        ph = s.phi(q, t)
        self.resid.append(float(np.max(np.abs(ph), initial=0.0)))
        _check_dropped(s, q, t, ph, rows_idx)


DROPPED_STOP = 1e-5        # m（角度类约束是 rad）：删掉的“冗余”约束拉开到这个数就停（近冗余的制造误差级远小于它）


def _check_dropped(sysm, q, t, ph, rows_idx):
    """《多体动力学》书第 35 章线索第 52 条（问渠 CAD 0.3.8 细则）：初始位形奇异（例如三点共线）时，独立约束看起来像冗余，
    被删掉照算——双摆加一个本应锁死的接地转动副，删掉 4 条约束、积分完成、约束残差 2.0。
    真冗余的约束在运动中自动满足；被删的约束拉开了，说明它不是冗余：停下，报奇异位形 / 锁死和运动副"""
    keep = set(rows_idx)
    dropped = [k for k in range(len(sysm.rows)) if k not in keep]
    if not dropped:
        return
    k = max(dropped, key=lambda i: abs(ph[i]))
    if abs(ph[k]) <= DROPPED_STOP:
        return
    row = sysm.rows[k]
    dof = structural(sysm, q, t)["dof"]
    gap = f"{abs(ph[k]):.3g}（方向约束，无量纲）" if row.kind in ("dot1", "dot2", "norm") else f"{abs(ph[k]) * 1000:.4g} mm"
    raise SolveError(
        f"机构锁死或开始时在奇异位形：开始时按冗余删掉的约束“{row.label}”到 t = {t:.6g} s 拉开了 {gap}"
        f"——真冗余的约束会自动满足，它不是冗余。现在只看运动副的结构自由度是 {dof}。"
        f"开始位形多半是奇异位形（例如三个铰点共线），离开它机构就动不了。请检查运动副“{row.joint or row.label}”的位置，"
        "或换一个不奇异的初始位形")


# ---------------------------------------------------------------- 分析
def kinematic(sysm: System, t_end, steps, branch="continue"):
    q = sysm.q0()
    keep, drop = independent_rows(sysm, q, 0.0)
    rows = _rows(sysm, keep)
    dof = sysm.n - len(keep)
    if dof != 0:
        raise SolveError(f"运动学分析要自由度为 0（加了驱动以后还剩 {dof} 个自由度）；有自由度的用动力学分析")
    rec = Recorder(sysm)
    # 《多体动力学》书第 5 章线索第 13 条（问渠 CAD 0.3.8 细则）：原来牛顿初值取上一时刻的解，过死点（雅可比奇异）时走“倒回”
    # 那一支——摇杆驱动的曲柄摇杆 2 s 曲柄来回摆、转 0 圈，无提示。现在初值按速度外推（原动件推着越过死点，脚踏缝纫机、
    # 内燃机要的是这一支），branch="reverse" 保留原来的走法；雅可比行列式变号就记一次经过死点，报时刻和运动副
    ts = np.linspace(0.0, t_end, steps + 1)
    jids = _friction_joints(sysm)
    q_prev, qd, det_prev, dead = None, None, None, []
    for n, t in enumerate(ts):
        if branch == "continue" and n >= 2:
            guess = q + (q - q_prev)                         # 割线外推（= 速度外推，采样点落在死点上也有定义）
        elif branch == "continue" and n == 1 and qd is not None:
            guess = q + qd * (t - ts[0])
        else:
            guess = q
        try:
            q_new = assemble(sysm, guess, t, rows)
        except SolveError:
            q_new = assemble(sysm, q, t, rows)               # 外推越界装不上：退回上一时刻的解起步
        q_prev, q = q, q_new
        J = sysm.jac(q, t, rows)
        sv = np.linalg.svd(J, compute_uv=False)
        sign, logdet = np.linalg.slogdet(J)
        det = sign * math.exp(logdet) if sign else 0.0
        if det_prev is not None and det_prev * det < 0:
            tc = float(ts[n - 1] + (t - ts[n - 1]) * det_prev / (det_prev - det))
            dead.append({"t_s": tc, "joints": _singular_joints(sysm, q, t, rows), "collinear": _collinear(sysm, q)})
        if det != 0.0:
            det_prev = det
        if sv[-1] < KIN_SINGULAR * sv[0] and q_prev is not None:
            qd = (q - q_prev) / (t - ts[n - 1])              # 正好落在死点上：速度由运动副定不了，用相邻两点差分
            qdd = np.linalg.lstsq(J, sysm.gamma(q, qd, t, rows), rcond=None)[0]
            lam = np.linalg.lstsq(J.T, sysm.Q(q, qd, t) - sysm.mass(q) @ qdd, rcond=None)[0]
        else:
            qd = np.linalg.solve(J, sysm.nu(q, t, rows))
            qdd = np.linalg.solve(J, sysm.gamma(q, qd, t, rows))
            Q = sysm.Q(q, qd, t)
            rhs0 = Q - sysm.mass(q) @ qdd
            lam = np.linalg.solve(J.T, rhs0)
            if jids:
                lam = _kinematic_friction(sysm, q, qd, t, J, rows, jids, rhs0, lam)
        rec.add(float(t), q, qd, qdd, keep, lam)
    return rec, {"dof": 0, "redundant": [sysm.rows[k].label for k in drop], "dead_points": dead, "branch": branch}


KIN_SINGULAR = 1e-10     # 运动学雅可比最小 / 最大奇异值低于它：采样点正好落在死点上


def _collinear(sysm, q):
    """死点处共线的两根杆：在连接两个运动构件的铰上，两根杆各自“另一个铰 → 这个铰”的方向最接近共线的那一处。
    返回 (杆 1, 杆 2, 铰) 或 None"""
    pts = {}                                      # 构件下标 → [(铰名, 地面系位置)]
    for jid, info in sysm.joints.items():
        for b, s_ in ((info["i"], info.get("si")), (info["j"], info.get("sj"))):
            if b >= 0 and s_ is not None:
                r, p = sysm.rp(q, b)
                pts.setdefault(b, []).append((jid, r + A_of(p) @ np.asarray(s_, float)))
    best, out = 0.05, None
    for jid, info in sysm.joints.items():
        bi, bj = info["i"], info["j"]
        if bi < 0 or bj < 0:
            continue
        dirs = []
        for b in (bi, bj):
            here = next(x for n_, x in pts[b] if n_ == jid)
            others = [x for n_, x in pts[b] if n_ != jid and np.linalg.norm(x - here) > 1e-9]
            if not others:
                break
            v = here - others[0]
            dirs.append(v / np.linalg.norm(v))
        if len(dirs) < 2:
            continue
        sine = float(np.linalg.norm(np.cross(dirs[0], dirs[1])))
        if sine < best:
            best, out = sine, (sysm.bodies[bi].name, sysm.bodies[bj].name, jid)
    return out


def _singular_joints(sysm, q, t, rows):
    """雅可比最接近奇异的方向上分量大的约束行 → 所在运动副（死点处共线的那几根杆连着的铰）"""
    J = sysm.jac(q, t, rows)
    U, _, _ = np.linalg.svd(J)
    u = np.abs(U[:, -1])
    return sorted({rows[i].joint or rows[i].label for i in np.nonzero(u > 0.2 * u.max())[0]})


def _kinematic_friction(sysm, q, qd, t, J, rows, jids, rhs0, lam):
    """运动学分析的反力（含驱动力矩）计入运动副摩擦。《多体动力学》书第 20 章线索第 27 条（问渠 CAD 0.3.8 细则）：
    原来解乘子不走摩擦迭代，曲柄滑块 μ = 0.2 与无摩擦的驱动力矩完全相同、无提示（书里一周最大多 4.12 N·m）；
    全驱动的模型又不能做动力学分析。现在与加速度一样走摩擦不动点（反力 → 摩擦 → 反力）"""
    lu = sla.lu_factor(J.T)

    def g(lam_):
        react = _joint_forces(sysm, q, J, lam_, rows, jids)
        Fx, Nx = sysm.friction_wrenches(q, qd, react)
        return sla.lu_solve(lu, rhs0 + sysm.Q_extra(q, qd, Fx, Nx)), react

    return _fp_iterate(sysm, t, g, lam, "_friction_lam")


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


def ctrl_states(sysm):
    """静平衡、线性化里要随系统一起求的控制器状态下标（《多体动力学》书第 32 章线索第 47 条）：
    PID 的积分状态只有 ki ≠ 0 时才影响输出（ki = 0 时它的“导数 = 误差”不是平衡条件）；微分滤波、状态空间的状态都算"""
    ctrl = getattr(sysm, "ctrl", None)
    if ctrl is None or not ctrl.items:
        return []
    idx = []
    for it in ctrl.items:
        if "sp" in it:
            if it["c"].get("ki", 0.0):
                idx.append(it["o"])
            if it["filt"]:
                idx.append(it["o"] + 1)
        else:
            idx += list(range(it["o"], it["o"] + it["n"]))
    return idx


def apply_ctrl(sysm, q, qd, t, xc):
    """控制器输出 → 执行器（静平衡、线性化里与动力学同样计入控制器）"""
    ctrl = getattr(sysm, "ctrl", None)
    if ctrl is not None and ctrl.any:
        sysm.act = ctrl.outputs(t, sysm.measures(q, qd), xc)


def _static(sysm: System, t=0.0, q=None):
    """静平衡：Q(q) − Φ_qᵀλ = 0、Φ(q) = 0（速度为 0）。有控制器时执行器力按控制器输出算，
    要随系统求的控制器状态（PID 积分等）加进未知量，方程是它们的导数为 0（线索第 47 条：原来不计控制器，
    伺服臂的静平衡“没找到（残差 10.6）”）"""
    q = sysm.q0() if q is None else q
    keep, drop = independent_rows(sysm, q, t)
    rows = _rows(sysm, keep)
    q = assemble(sysm, q, t, rows)
    m = len(rows)
    zero = np.zeros(sysm.n)
    ctrl = getattr(sysm, "ctrl", None)
    xc_base = ctrl.x0.copy() if ctrl is not None and ctrl.any else np.zeros(0)
    ci = ctrl_states(sysm)
    nc = len(ci)

    def split(x):
        xc = xc_base.copy()
        if nc:
            xc[ci] = x[sysm.n + m:]
        return x[:sysm.n], x[sysm.n:sysm.n + m], xc

    def F(x):
        qq, lam, xc = split(x)
        apply_ctrl(sysm, qq, zero, t, xc)
        out = [sysm.Q(qq, zero, t) - sysm.jac(qq, t, rows).T @ lam, sysm.phi(qq, t, rows)]
        if nc:
            out.append(ctrl.deriv(t, sysm.measures(qq, zero), xc)[ci])
        return np.concatenate(out)

    J0 = sysm.jac(q, t, rows)
    apply_ctrl(sysm, q, zero, t, xc_base)
    lam0 = np.linalg.lstsq(J0.T, sysm.Q(q, zero, t), rcond=None)[0]
    x0 = np.concatenate([q, lam0, xc_base[ci]])
    x = _static_newton(sysm, t, rows, x0) if getattr(sysm, "nlbeams", None) and not nc else None
    if x is None:
        sol = root(F, x0, method="hybr", options={"xtol": 1e-13, "maxfev": 20000})
        x = sol.x
    res = F(x)
    sysm.static_xc = split(x)[2]
    if nc and np.max(np.abs(res[sysm.n + m:])) > 1e-8:
        raise SolveError(f"静平衡没找到：控制器状态没有到稳态（导数残差 {np.max(np.abs(res[sysm.n + m:])):.3g}）")
    res = res[:sysm.n + m]
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


def time_breaks(sysm):
    """模型里所有时间表达式（力、驱动、控制器设定值……）中 STEP / STEP5 / HAVSIN 的过渡区间"""
    from analysis.mbd.dae.expr import Expr

    out, seen = [], set()

    def walk(o, depth):
        if depth > 6 or id(o) in seen:
            return
        seen.add(id(o))
        if isinstance(o, Expr):
            out.extend(o.time_breaks())
        elif isinstance(o, dict):
            for x in o.values():
                walk(x, depth + 1)
        elif isinstance(o, (list, tuple)):
            for x in o:
                walk(x, depth + 1)
        elif callable(o) and getattr(o, "__closure__", None):        # 力元把表达式包在闭包里
            for c in o.__closure__:
                try:
                    walk(c.cell_contents, depth + 1)
                except ValueError:                                  # 空的闭包格
                    pass
        elif type(o).__module__.startswith("analysis.mbd") and hasattr(o, "__dict__"):
            for x in vars(o).values():
                walk(x, depth + 1)

    for name in ("forces", "motions", "rows", "ctrl"):
        walk(getattr(sysm, name, None), 0)
    return sorted(set(out))


SEG_ROT_RAD = 0.5          # 积分每段里构件最多转过的角度（rad）


def _max_angular_speed(sysm, q, qd):
    w = 0.0
    for k in range(sysm.nb):
        p = sysm.rp(q, k)[1]
        w = max(w, float(np.linalg.norm(2 * E_of(p) @ qd[7 * k + 3:7 * k + 7])))
    return w


STALL_RHS = 200_000        # 一个输出间隔的 1 % 都没推进、却已求值这么多次：积分卡住了


class _Stall(RuntimeError):
    """积分步长持续过小（不让 rhs 里的“缩步重试”吞掉）"""


def _stall_watch(state, stats, t, dt_out):
    """《多体动力学》书第 31 章线索第 46 条（问渠 CAD 0.3.8 细则）：解贴着不连续面来回切换时，变步长积分步长持续过小、
    几乎不前进，原来不提示（书里转台 90 s 算不完）。推进不到输出间隔的 1 % 就已求值 STALL_RHS 次，停下报原因"""
    mark = state.get("stall_t")
    if mark is None or t > mark + 0.01 * dt_out:
        state["stall_t"], state["stall_n"] = t, 0
        return
    state["stall_n"] += 1
    if state["stall_n"] > STALL_RHS:
        raise _Stall(f"积分卡住：t = {t:.6g} s 附近求值 {STALL_RHS} 次仍推进不到 {0.01 * dt_out:.3g} s（步长持续过小）。"
                     "常见原因：控制器输出贴着限幅来回切换、摩擦粘滑、接触太硬或表达式里有不连续（sign、STEP 太陡）。"
                     "请检查这一时刻附近的控制器和力元，或改用 HHT 积分器")


def dynamic(sysm: System, t_end, steps, method="DOP853", rtol=1e-8, atol=1e-10, q=None, qd=None, t0=0.0):
    q = sysm.q0() if q is None else q.copy()
    keep, drop = independent_rows(sysm, q, t0)
    rows = _rows(sysm, keep)
    q = assemble(sysm, q, t0, rows)
    dof = sysm.n - len(keep)
    if dof <= 0:
        raise SolveError("没有自由度（全被驱动定死了），请用运动学分析")
    finite_mobility(sysm, q, t0)
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
    breaks = [b for b in time_breaks(sysm) if b[1] > t0 and b[0] < t0 + t_end]
    stats["time_breaks"] = sorted({x for b in breaks for x in b if t0 < x < t0 + t_end})
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
    breaks, must = v["breaks"], v["stats"]["time_breaks"]
    dt_out = float(times[1] - times[0]) if len(times) > 1 else 1.0
    while k < steps:
        dep, ind = partition(q_cur, t_cur)
        stats["segments"] += 1
        state["q"] = q_cur.copy()
        y0 = np.concatenate([q_cur[ind], qd_cur[ind], xc_cur])
        cond0 = np.linalg.cond(sysm.jac(q_cur, t_cur, rows)[:, dep])
        limit = max(1e3, 10 * cond0)
        k1 = min(steps, k + seg)
        # 《多体动力学》书第 7 章线索第 16 条（问渠 CAD 0.3.8 细则）：原来每段固定 T/50，高速转动的自由刚体一段里转大半圈，
        # 独立坐标（欧拉参数的某个分量）过零变病态，能量悄悄流失或积分报错。每段转角限 SEG_ROT_RAD，段首重选独立坐标
        w_max = _max_angular_speed(sysm, q_cur, qd_cur)
        t_rot = t_cur + SEG_ROT_RAD / w_max if w_max > 0 else math.inf
        # 线索第 24 条：时间函数的过渡点是必经时刻（分段积分，过点重新起步），过渡区间里最大步长不超过过渡宽度
        next_b = next((x for x in must if x > t_cur + 1e-12), math.inf)
        t_stop = min(float(times[k1]), next_s, t_rot, next_b)
        inside = [b[1] - b[0] for b in breaks if b[0] - 1e-12 <= t_cur < b[1] - 1e-12]
        max_step = min(inside) if inside else math.inf

        def rhs(t, y, dep=dep, ind=ind):
            stats["rhs"] += 1
            _stall_watch(state, stats, t, dt_out)
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
        try:
            sol = solve_ivp(rhs, (t_cur, t_stop), y0, method=method, t_eval=t_eval, rtol=rtol, atol=atol,
                            events=ill, dense_output=True, max_step=max_step)
        except _Stall as exc:
            raise SolveError(str(exc)) from None
        if sol.status < 0:
            lock = sysm.__dict__.get("_friction_lock")
            if lock:                        # 线索第 29 条：积分失败是因为摩擦自锁，就报自锁
                raise SolveError(lock)
            fl = sysm.__dict__.get("friction_log") or {}
            if fl.get("gain_max", 0.0) >= FRICTION_LOCK_GAIN:
                raise SolveError(f"可能自锁：t = {fl['gain_t']:.6g} s 起运动副摩擦的迭代增益到 {fl['gain_max']:.3g}"
                                 f"（接近 1，摩擦力趋于无穷），摩擦最大的是运动副“{fl['gain_joint']}”，积分在 "
                                 f"t = {t_cur:.6g} s 后走不下去。机构在这里会卡死；请检查摩擦系数、销半径，"
                                 "或确认这就是要找的自锁位置")
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
