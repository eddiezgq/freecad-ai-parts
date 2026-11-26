"""隐式积分器 HHT-I3（ADR-0098 E1）：在全部坐标上直接解指标 3 的 DAE，硬系统（梁链、硬接触、柔性体高阶模态）用。

第 n+1 步未知量是加速度 a 和乘子 λ（Negrut、Rampalli、Ottarsson、Sajdak 2007，ADAMS 的 HHT）：
    q  = qₙ + h q̇ₙ + h²[(½ − β) aₙ + β a]，q̇ = q̇ₙ + h[(1 − γ) aₙ + γ a]
    M(q) a /(1+α) + f(q, q̇, λ) − α/(1+α) fₙ = 0，f = Φqᵀλ − Q
    Φ(q, t)/(β h²) = 0
α ∈ [−⅓, 0]，γ = ½ − α，β = (1 − α)²/4。α = 0 是梯形法（不耗散）；α < 0 时高频被阻尼掉。

牛顿迭代矩阵 [[M/(1+α) + β h² g_q + γ h g_q̇, Φqᵀ], [Φq, 0]]，g = M a/(1+α) + Φqᵀλ − Q。g 的导数用差分（E1），
只在收敛变慢时重算；步长变了只重新组合、分解。步长按局部截断误差估计 h²|β − ⅙||a − aₙ| 调。
每步之后把 q̇ 投影到速度约束上。记录点的加速度和反力用 solve.accel 重新算（和显式积分的输出同一口径）。
"""

from __future__ import annotations

import math

import numpy as np

from analysis.mbd.dae import solve as S

NEWTON_MAX = 8
NEWTON_TOL = 0.05          # 牛顿收敛：剩余修正量 ≤ 0.05 个容差单位
NEWTON_FLOOR = 0.33        # 迭代过之后修正量 ≤ ⅓ 个容差单位也算收敛（同 SUNDIALS 的牛顿判据）
DQ_ROUNDOFF = 1e-13        # 修正量到舍入误差这一级就算收敛（容差给得很紧时）
PHI_TOL = 1e-9             # 约束残差上限（m 或无量纲），比核查限值 1e-8 严一个量级；实际取 min(它, 0.01·atol)：
#                            留下的残差下一步会被当成加速度修掉（a ≈ Φ/(βh²)），残差大了误差估计会被它带偏、步长越缩越小
H_MIN = 1e-12


def dynamic(sysm, t_end, steps, *, alpha=-0.1, rtol=None, atol=None, q=None, qd=None, t0=0.0):
    if not -1 / 3 - 1e-12 <= alpha <= 0:
        raise S.SolveError("HHT 的 α 要在 −⅓ 到 0 之间")
    rtol = 1e-6 if rtol is None else rtol
    atol = 1e-9 if atol is None else atol
    al = alpha
    gam = 0.5 - al
    beta = (1 - al) ** 2 / 4
    c_a = 1.0 / (1 + al)
    c_f = al / (1 + al)
    est_c = abs(beta - 1 / 6)

    q = sysm.q0() if q is None else q.copy()
    keep, drop = S.independent_rows(sysm, q, t0)
    rows = S._rows(sysm, keep)
    q = S.assemble(sysm, q, t0, rows)
    dof = sysm.n - len(keep)
    if dof <= 0:
        raise S.SolveError("没有自由度（全被驱动定死了），请用运动学分析")
    if qd is None:
        qd = S.initial_velocity(sysm, q, t0, rows)
    n, m = sysm.n, len(rows)
    ctrl = getattr(sysm, "ctrl", None)
    ctrl = ctrl if ctrl is not None and ctrl.any else None
    jids = S._friction_joints(sysm)
    rec = S.Recorder(sysm)
    rec.ctrl = []
    last_fail = {}
    stats = {"steps": 0, "rejected": 0, "jacobians": 0, "factorizations": 0, "newton": 0}

    # 容差的权：位置按 atol + rtol·|q|；欧拉参数量级是 1，按 atol + rtol（不然转角接近 0 时要求修正到 1e-9 以下，牛顿永远收不住）
    phi_tol = min(PHI_TOL, 0.01 * atol)
    floor = np.zeros(n)
    for k_ in range(sysm.nb):
        floor[7 * k_ + 3:7 * k_ + 7] = 1.0

    def weights(q_):
        return atol + rtol * np.maximum(np.abs(q_), floor)

    def set_act(t, q_, qd_, xc):
        if ctrl is not None:
            sysm.act = ctrl.outputs(t, sysm.measures(q_, qd_), xc)

    def Qtot(q_, qd_, t, lam, J):
        Qv = sysm.Q(q_, qd_, t)
        if jids:
            react = S._joint_forces(sysm, q_, J, lam, rows, jids)
            Fx, Nx = sysm.friction_wrenches(q_, qd_, react)
            Qv = Qv + sysm.Q_extra(q_, qd_, Fx, Nx)
        return Qv

    xstate = {"x": None}                           # 当前牛顿迭代用的控制器状态（差分时执行器输出随 q 变）

    def g(q_, qd_, t, a, lam):
        if ctrl is not None and xstate["x"] is not None:
            set_act(t, q_, qd_, xstate["x"])
        J = sysm.jac(q_, t, rows)
        return c_a * (sysm.mass(q_) @ a) + J.T @ lam - Qtot(q_, qd_, t, lam, J)

    groups = color_groups(sysm, ctrl)

    def pieces(q_, qd_, t, a, lam):
        """g 对 q、q̇ 的差分导数：按构件耦合分组（E2），同组构件一起扰动，各行按耦合关系认领"""
        stats["jacobians"] += 1
        return (sysm.mass(q_),) + grouped_fd(lambda qq, vv: g(qq, vv, t, a, lam), q_, qd_, groups)

    def kkt_factor(Mm, gq, gqd, J, h):
        stats["factorizations"] += 1
        A = c_a * Mm + beta * h * h * gq + gam * h * gqd
        K = np.block([[A, J.T], [J, np.zeros((m, m))]])
        return S.factor(K)

    def project_velocity(q_, qd_, t):
        J = sysm.jac(q_, t, rows)
        r = sysm.nu(q_, t, rows) - J @ qd_
        if np.max(np.abs(r), initial=0.0) < 1e-14:
            return qd_
        K = np.block([[sysm.mass(q_), J.T], [J, np.zeros((m, m))]])
        try:
            x = S.factor(K)(np.concatenate([np.zeros(n), r]))
        except (np.linalg.LinAlgError, ValueError, RuntimeError):
            x = np.linalg.lstsq(K, np.concatenate([np.zeros(n), r]), rcond=None)[0]
        return qd_ + x[:n]

    # 初始状态
    xc = ctrl.x0.copy() if ctrl else np.zeros(0)
    times = np.linspace(t0, t0 + t_end, steps + 1)
    h_s = ctrl.sample if ctrl and ctrl.sample else None
    if h_s:
        ctrl.start(t0, sysm.measures(q, qd))
    next_s = t0 + h_s if h_s else math.inf
    set_act(t0, q, qd, xc)
    a, lam = S.accel(sysm, q, qd, t0, rows)
    rec.add(float(t0), q, qd, a, keep, lam)
    rec.ctrl.append(dict(getattr(sysm, "act", {})))
    f_n = -(sysm.mass(q) @ a)                     # t0 上 M a + f = 0
    t = t0
    k = 1
    h_free = min(times[1] - times[0], 1e-3) if steps else t_end     # 不受输出点截短的步长
    cache = None                                   # (M, g_q, g_q̇, J)
    lu, lu_h = None, None
    fresh = False                                  # 当前 cache 是不是在这一步算的

    # 线索第 24 条：时间函数的过渡点是必经时刻，过渡区间里步长不超过过渡宽度（同 solve.dynamic）
    breaks = [b for b in S.time_breaks(sysm) if b[1] > t0 and b[0] < t0 + t_end]
    must = sorted({x for b in breaks for x in b if t0 < x < t0 + t_end})
    stats["time_breaks"] = must
    while k <= steps:
        next_b = next((x for x in must if x > t + 1e-12 * max(1.0, abs(t))), math.inf)
        t_target = min(float(times[k]), next_s, next_b)
        rem = t_target - t
        inside = [b[1] - b[0] for b in breaks if b[0] - 1e-12 <= t < b[1] - 1e-12]
        hf = min([h_free, *inside])
        # 不留碎步：剩下不到 1.25 步就一步走到；不到 2 步就两步平分
        h = rem if rem <= 1.25 * hf else (0.5 * rem if rem < 2 * hf else hf)
        landing = abs(t + h - t_target) < 1e-12 * max(1.0, abs(t_target))
        t1 = t_target if landing else t + h
        nxc = len(xc)
        xc_dot = ctrl.deriv(t, sysm.measures(q, qd), xc) if nxc else np.zeros(0)
        xc_pred = xc + h * xc_dot
        if nxc:                                       # 控制器状态对自身的导数（PID、状态空间都是线性的）：差分一次
            f0 = ctrl.deriv(t1, sysm.measures(q, qd), xc)
            Jx = np.empty((nxc, nxc))
            for j in range(nxc):
                xx = xc.copy()
                xx[j] += 1e-6 * (1 + abs(xc[j]))
                Jx[:, j] = (ctrl.deriv(t1, sysm.measures(q, qd), xx) - f0) / (xx[j] - xc[j])
            Ix = np.linalg.inv(np.eye(nxc) - 0.5 * h * Jx)

        def xc_trap(q1_, qd1_, guess, Ix=Ix if nxc else None, xc=xc, h=h, xc_dot=xc_dot, t1=t1):
            """控制器状态用梯形法隐式推进（导数滤波这类快状态显式推不稳），两次修正"""
            meas = sysm.measures(q1_, qd1_)
            x = guess.copy()
            for _ in range(2):
                x = x - Ix @ (x - xc - 0.5 * h * (xc_dot + ctrl.deriv(t1, meas, x)))
            return x
        a1, lam1 = a.copy(), lam.copy()
        ok, slow = False, False
        tries = 0
        while True:
            tries += 1
            if cache is None:
                xstate["x"] = xc_pred
                set_act(t1, q, qd, xc_pred)
                cache = pieces(q, qd, t1, a, lam)[:3] + (sysm.jac(q, t1, rows),)
                lu, fresh = None, True
            if lu is None or lu_h != h:
                try:
                    lu = kkt_factor(*cache, h)
                except (np.linalg.LinAlgError, ValueError, RuntimeError):
                    lu = None
                lu_h = h
            if lu is None:
                break
            prev, conv = math.inf, False
            for it in range(NEWTON_MAX):
                stats["newton"] += 1
                q1 = q + h * qd + h * h * ((0.5 - beta) * a + beta * a1)
                qd1 = qd + h * ((1 - gam) * a + gam * a1)
                if nxc:
                    xc_pred = xc_trap(q1, qd1, xc_pred)
                set_act(t1, q1, qd1, xc_pred)
                J1 = sysm.jac(q1, t1, rows)
                r1 = c_a * (sysm.mass(q1) @ a1) + J1.T @ lam1 - Qtot(q1, qd1, t1, lam1, J1) - c_f * f_n
                r2 = sysm.phi(q1, t1, rows) / (beta * h * h)
                if not (np.all(np.isfinite(r1)) and np.all(np.isfinite(r2))):
                    last_fail.update(why="力或约束算出 NaN", it=it)
                    break
                dx = lu(-np.concatenate([r1, r2]))
                a1 += dx[:n]
                lam1 += dx[n:]
                dq = beta * h * h * dx[:n]
                size = np.max(np.abs(dq) / weights(q1))
                rate = size / prev if it >= 2 else 0.0     # 第一次修正多在硬方向、第二次在软方向，两者比不出收敛速率
                last_fail.update(why=f"牛顿第 {it + 1} 次修正 {size:.3g} 个容差单位（速率 {rate:.2f}），最大在坐标 "
                                     f"{int(np.argmax(np.abs(dq) / weights(q1)))}", it=it)
                if it >= 2 and rate > 0.9 and size > NEWTON_FLOOR:
                    break                                  # 收敛太慢或发散
                prev = size
                # 收敛判据（与误差判据同一套权）：修正量已远小于一个容差单位（剩余量估计 size·rate/(1 − rate) 很小），
                # 或者已迭代过、修正量落到容差的零头（硬系统的修正量到这一级就是舍入噪声，速率估计不再可信）
                r_ = min(rate, 0.5)
                if ((size * r_ / (1 - r_) if it >= 2 else size) <= NEWTON_TOL or (it >= 2 and size <= NEWTON_FLOOR)
                        or np.max(np.abs(dq)) <= DQ_ROUNDOFF * (1 + np.max(np.abs(q1)))):
                    q1 = q + h * qd + h * h * ((0.5 - beta) * a + beta * a1)
                    ph1 = sysm.phi(q1, t1, rows)
                    if np.max(np.abs(ph1), initial=0.0) <= phi_tol:
                        conv = True
                        break
                    kb = int(np.argmax(np.abs(ph1)))
                    last_fail.update(why=f"修正量已收敛，约束“{rows[kb].label}”残差 {ph1[kb]:.3g} 仍超 {phi_tol:.0e}")
            if conv:
                ok = True
                slow = it >= 3                             # 用了 4 次以上：雅可比旧了，下一步开头换新的
                break
            if not fresh:                                  # 先换新雅可比再试一次
                cache = None
                a1, lam1 = a.copy(), lam.copy()
                continue
            break
        err = math.inf
        if ok:
            ev = h * h * est_c * np.abs(a1 - a) / weights(q1)
            err = float(np.max(ev))
            if err > 1.0:
                kk = int(np.argmax(ev))
                last_fail.update(why=f"误差估计 {err:.3g} 超限（坐标 {kk}，步长 {h:.3g} s）")
        if not ok or err > 1.0:
            stats["rejected"] += 1
            stats["newton_fail" if not ok else "error_fail"] = stats.get("newton_fail" if not ok else "error_fail", 0) + 1
            h_free = h * (0.25 if not ok else max(0.2, 0.8 * err ** (-1 / 3)))
            if h_free < H_MIN:
                raise S.SolveError(f"HHT 步长缩到 {h_free:.2g} s 仍不收敛（t = {t:.6g} s；最后一次：{last_fail.get('why', '误差超限')}）")
            fresh = False
            continue
        # 接受这一步
        stats["steps"] += 1
        stats["h_min"] = min(stats.get("h_min", math.inf), h)
        stats["h_max"] = max(stats.get("h_max", 0.0), h)
        qd1 = qd + h * ((1 - gam) * a + gam * a1)
        if nxc:
            xc = xc_trap(q1, qd1, xc_pred)
        qd1 = project_velocity(q1, qd1, t1)
        f_n = c_f * f_n - c_a * (sysm.mass(q1) @ a1)
        q, qd, a, lam, t = q1, qd1, a1, lam1, t1
        if slow and not fresh:
            cache = None
        fresh = False
        if landing and h_s and abs(t - next_s) < 1e-12 * max(1.0, abs(next_s)):
            ctrl.sample_at(t, sysm.measures(q, qd))
            next_s = t0 + h_s * (round((next_s - t0) / h_s) + 1)
        if landing and abs(t - times[k]) < 1e-12 * max(1.0, abs(times[k])):
            set_act(t, q, qd, xc)
            qdd_o, lam_o = S.accel(sysm, q, qd, t, rows)
            rec.add(float(t), q, qd, qdd_o, keep, lam_o)
            rec.ctrl.append(dict(getattr(sysm, "act", {})))
            k += 1
        grow = min(2.0, 0.8 * err ** (-1 / 3)) if err > 0 else 2.0
        h_free = max((max(h, h_free) if landing else h) * min(grow, 1.0 if landing else grow), H_MIN)
    if ctrl:
        ctrl.close()
    return rec, {"dof": dof, "redundant": [sysm.rows[j].label for j in drop], **stats}


# ---------------------------------------------------------------- E2：按耦合分组的差分雅可比
def body_coords(sysm, k):
    """构件 k 的坐标下标：7 个刚体坐标 + 柔性模态坐标"""
    idx = list(range(7 * k, 7 * k + 7))
    if sysm.bodies[k].flex is not None:
        o = sysm.foff[k]
        idx += list(range(o, o + sysm.bodies[k].flex.nm))
    return idx


def coupling(sysm, ctrl=None):
    """构件之间谁的坐标会影响谁的力（含约束力 Φqᵀλ）：返回每个构件的闭邻域集合；遇到不认识的力元返回 None，退回逐列差分。
    函数力用了测量量、执行器由控制器驱动时，这些力所在的构件与测量量涉及的全部构件算耦合"""
    nb = sysm.nb
    adj = [{k} for k in range(nb)]
    env_bodies = []
    for m in getattr(sysm, "measure_defs", []):
        jt = sysm.joints[m["joint"]] if m["type"].startswith("joint_") else m
        env_bodies += [jt["i"], jt["j"]]
    uses_env = getattr(sysm, "needs_env", False)
    ctrl_on = ctrl is not None

    def link(*bs):
        bs = [b for b in bs if b is not None and b >= 0]
        for x in bs:
            adj[x].update(bs)

    for r in sysm.rows:
        link(r.i, r.j)
    for kind, f in sysm.forces:
        if kind in ("spring", "rspring", "bushing", "beam", "clearance", "nlbeam"):
            link(f["i"], f["j"])
        elif kind == "actuator":
            jt = sysm.joints[f["joint"]]
            link(jt["i"], jt["j"], *(env_bodies if ctrl_on else ()))
        elif kind == "gear":
            j1, j2 = sysm.joints[f["joint_i"]], sysm.joints[f["joint_j"]]
            link(j1["i"], j1["j"], j2["i"], j2["j"])
        elif kind == "contact":
            link(f["ga"].body, f["gb"].body)
        elif kind in ("force", "torque"):
            if uses_env and any(fn.expr.uses_vars for fn in f["fn"]):
                link(f["body"], *env_bodies)
        else:
            return None                                   # 不认识的力元：保守起见逐列
    return adj


def color_groups(sysm, ctrl=None):
    """距离为 2 的着色：同组构件的闭邻域互不相交，扰动它们的坐标时各行只来自一个构件。
    返回 [(组内构件, 各构件的坐标下标, 各构件认领的行下标)]；None 表示逐列"""
    adj = coupling(sysm, ctrl)
    if adj is None:
        return None
    colors = []
    for k in sorted(range(sysm.nb), key=lambda b: -len(adj[b])):
        for c in colors:
            if all(not (adj[k] & adj[o]) for o in c):
                c.append(k)
                break
        else:
            colors.append([k])
    out = []
    for c in colors:
        coords = {k: body_coords(sysm, k) for k in c}
        rows = {k: [i for r in sorted(adj[k]) for i in body_coords(sysm, r)] for k in c}
        out.append((c, coords, rows))
    return out


def grouped_fd(gfun, q, qd, groups):
    """∂g/∂q、∂g/∂q̇ 的差分；groups 为 None 时逐列"""
    n = len(q)
    g0 = gfun(q, qd)
    gq, gqd = np.zeros((n, n)), np.zeros((n, n))
    if groups is None:
        for j in range(n):
            d = 1e-7 * (1 + abs(q[j]))
            qq = q.copy()
            qq[j] += d
            gq[:, j] = (gfun(qq, qd) - g0) / d
            d = 1e-6 * (1 + abs(qd[j]))
            vv = qd.copy()
            vv[j] += d
            gqd[:, j] = (gfun(q, vv) - g0) / d
        return gq, gqd
    for members, coords, rows in groups:
        width = max(len(c) for c in coords.values())
        for slot in range(width):
            for x, out, rel in ((q, gq, 1e-7), (qd, gqd, 1e-6)):
                xx = x.copy()
                cols = {}
                for k in members:
                    if slot < len(coords[k]):
                        j = coords[k][slot]
                        d = rel * (1 + abs(x[j]))
                        xx[j] += d
                        cols[k] = (j, d)
                diff = (gfun(xx, qd) if out is gq else gfun(q, xx)) - g0
                for k, (j, d) in cols.items():
                    out[rows[k], j] = diff[rows[k]] / d
    return gq, gqd

