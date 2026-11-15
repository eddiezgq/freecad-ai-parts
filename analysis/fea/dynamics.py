"""动力学（ADR-0093 F5）：在模态结果上做模态叠加——谐响应、随机振动、瞬态。纯计算：不联网、不调用 LLM、不启动求解器。

模态结果来自 solve.solve_bodies(frequency=n)：振型 φ 按质量归一化（φᵀMφ = 1），单位 mm、N、t、s。
每阶的模态方程：q̈ + 2ζω q̇ + ω² q = φᵀF·a(t)（外载），或 = −Γ·ü_b（基础加速度，Γ = φᵀM r 为参与系数）。
"""

from __future__ import annotations

import math

import numpy as np

# Von Mises 二次型：σ_vm² = σᵀ A σ，σ = (xx, yy, zz, xy, yz, zx)
MISES = np.array([[1, -0.5, -0.5, 0, 0, 0], [-0.5, 1, -0.5, 0, 0, 0], [-0.5, -0.5, 1, 0, 0, 0],
                  [0, 0, 0, 3, 0, 0], [0, 0, 0, 0, 3, 0], [0, 0, 0, 0, 0, 3]], float)


def _omega(m):
    return 2 * math.pi * np.asarray(m["freqs_hz"], float)


def modal_loads(m):
    """各阶的模态力 φᵢᵀF（N·√t 量纲，配合质量归一化振型）"""
    return np.einsum("nkm,nk->m", m["phi"], m["load"])


def static_from_modes(m):
    """0 Hz 时模态叠加得到的位移 Σ φᵢ (φᵢᵀF) / ωᵢ²，与真正的静力解比较判断模态截断"""
    return np.einsum("nkm,m->nk", m["phi"], modal_loads(m) / _omega(m) ** 2)


def trapz_weights(x):
    """梯形积分的权：∫ y dx ≈ Σ wᵢ yᵢ（非均匀网格）"""
    x = np.asarray(x, float)
    w = np.zeros_like(x)
    dx = np.diff(x)
    w[:-1] += dx / 2
    w[1:] += dx / 2
    return w


def frequency_grid(f1, f2, n, modes_hz, zeta):
    """对数等分 n 个点，另在 [f1, f2] 内每阶固有频率附近（±10ζ 带宽内）加 41 个点，共振峰不会落在点与点之间"""
    g = list(np.geomspace(f1, f2, n))
    for fn in modes_hz:
        band = fn * (1 + zeta * np.linspace(-10, 10, 41))
        g += [x for x in band if f1 <= x <= f2]
    return np.unique(np.round(np.array(g), 12))


def _h(omega_n, zeta, w):
    """模态坐标对单位模态力的复频响应 1 / (ωₙ² − ω² + 2jζωₙω)：形状 (阶数, 频率数)"""
    return 1.0 / (omega_n[:, None] ** 2 - w[None, :] ** 2 + 2j * zeta * omega_n[:, None] * w[None, :])


def nearest(m, point):
    return int(np.argmin(np.linalg.norm(m["xyz"] - np.asarray(point, float), axis=1)))


def _vm(s):
    """s：(..., 6) 的应力 → Von Mises"""
    return np.sqrt(np.maximum(np.einsum("...i,ij,...j->...", s, MISES, s), 0.0))


def harmonic(m, f1, f2, n_points, zeta, probes=()):
    """谐响应：载荷幅值 F、同相位。返回各频率下探针的位移幅值与相位、全模型最大位移幅值、峰值频率处的最大 Von Mises 幅值"""
    om = _omega(m)
    f = frequency_grid(f1, f2, n_points, m["freqs_hz"], zeta)
    w = 2 * math.pi * f
    Q = modal_loads(m)[:, None] * _h(om, zeta, w)                      # (阶数, 频率数)
    phi = m["phi"]
    amp = np.empty(len(f))
    where = np.empty(len(f), np.int64)
    for k in range(0, len(f), 64):                                     # 分批，免得 节点 × 3 × 频率 的复数组太大
        U = np.einsum("nkm,mf->nkf", phi, Q[:, k:k + 64])
        mag = np.sqrt((np.abs(U) ** 2).sum(axis=1))                    # 各分量幅值的平方和开方
        amp[k:k + 64] = mag.max(axis=0)
        where[k:k + 64] = mag.argmax(axis=0)
    ip = int(np.argmax(amp))
    S = np.einsum("nkm,m->nk", m["sig"], Q[:, ip])                     # 峰值频率处各节点的应力相量
    phases = np.linspace(0, 2 * math.pi, 36, endpoint=False)
    vm = np.max([_vm(np.real(S * np.exp(1j * t))) for t in phases], axis=0)
    jv = int(np.argmax(vm))
    out = {"frequencies_hz": [round(float(x), 6) for x in f], "u_amp_max_mm": [round(float(x), 9) for x in amp],
           "peak": {"frequency_hz": round(float(f[ip]), 6), "u_amp_mm": round(float(amp[ip]), 9),
                    "u_at_mm": [round(float(x), 3) for x in m["xyz"][where[ip]]],
                    "vm_amp_max_mpa": round(float(vm[jv]), 6), "vm_at_mm": [round(float(x), 3) for x in m["xyz"][jv]]},
           "probes": []}
    for p in probes:
        j = nearest(m, p["point_mm"])
        U = np.einsum("km,mf->kf", phi[j], Q)
        out["probes"].append({"id": p["id"], "node_at_mm": [round(float(x), 4) for x in m["xyz"][j]],
                              "u_amp_mm": [[round(float(x), 9) for x in np.abs(U[k])] for k in range(3)],
                              "u_phase_deg": [[round(float(x), 3) for x in np.degrees(np.angle(U[k]))] for k in range(3)]})
    return out


def asd_at(asd, f):
    """加速度功率谱：两点之间对数—对数线性插值，范围之外为 0"""
    fx = np.array([p[0] for p in asd], float)
    sx = np.array([p[1] for p in asd], float)
    out = np.zeros_like(f, dtype=float)
    inside = (f >= fx[0]) & (f <= fx[-1])
    out[inside] = np.exp(np.interp(np.log(f[inside]), np.log(fx), np.log(sx)))
    return out


def random_vibration(m, direction, asd, zeta, probes=()):
    """随机振动（基础加速度，平稳、零均值）。asd：[(Hz, (mm/s²)²/Hz)]（求解器内部单位；算例里是 (m/s²)²/Hz，入口乘 10⁶）。
    模态坐标的协方差 C_ij = ∫ Γᵢ Γⱼ Hᵢ Hⱼ* S df，任一线性量 x = Σ aᵢ qᵢ 的均方 = aᵀ Re(C) a；
    Von Mises 的均方 = Σ Re(C_ij) sᵢᵀ A sⱼ（Segalman, Fulcher, Reese, Field 2000, J. Sound Vib. 230(2)）"""
    d = np.asarray(direction, float)
    d = d / np.linalg.norm(d)
    if m.get("gamma") is None:
        raise RuntimeError("没有读到参与系数，不能算基础激励")
    g = m["gamma"] @ d                                                 # 各阶对激励方向的参与系数 φᵀM r
    om = _omega(m)
    f1, f2 = asd[0][0], asd[-1][0]
    f = frequency_grid(f1, f2, 2000, m["freqs_hz"], zeta)
    S = asd_at(asd, f)
    G = g[:, None] * _h(om, zeta, 2 * math.pi * f)                      # 相对位移的模态响应 / 基础加速度（差一个负号，不影响均方）
    C = np.real(np.einsum("if,jf,f->ij", G, np.conj(G), S * trapz_weights(f)))
    phi, sig = m["phi"], m["sig"]
    u_ms = np.einsum("nkm,mp,nkp->nk", phi, C, phi)                    # 各节点各分量的均方
    u_rms = np.sqrt(np.maximum(u_ms.sum(axis=1), 0))                   # 位移向量的均方根
    vm_ms = np.einsum("nim,ij,njp,mp->n", sig, MISES, sig, C)
    vm_rms = np.sqrt(np.maximum(vm_ms, 0))
    ju, jv = int(np.argmax(u_rms)), int(np.argmax(vm_rms))
    tm = m.get("total_mass")
    em = m.get("eff_mass")
    mass_frac = None
    if tm is not None and em is not None:
        tot = float(np.dot(d ** 2, tm))
        mass_frac = float(np.sum(em @ (d ** 2)) / tot) if tot > 0 else None
    a_rms = math.sqrt(float(np.sum(S * trapz_weights(f))))
    out = {"input_a_rms_m_s2": round(a_rms / 1000, 6), "u_rms_max_mm": round(float(u_rms[ju]), 9),
           "u_rms_at_mm": [round(float(x), 3) for x in m["xyz"][ju]],
           "vm_rms_max_mpa": round(float(vm_rms[jv]), 6), "vm_3sigma_mpa": round(3 * float(vm_rms[jv]), 6),
           "vm_rms_at_mm": [round(float(x), 3) for x in m["xyz"][jv]],
           "effective_mass_fraction": None if mass_frac is None else round(mass_frac, 6), "probes": []}
    for p in probes:
        j = nearest(m, p["point_mm"])
        out["probes"].append({"id": p["id"], "node_at_mm": [round(float(x), 4) for x in m["xyz"][j]],
                              "u_rms_mm": [round(float(math.sqrt(max(x, 0))), 9) for x in u_ms[j]],
                              "vm_rms_mpa": round(float(vm_rms[j]), 6)})
    return out


def _coeffs(w, z, dt):
    """单位质量、刚度 ω² 的单自由度在一个时间步内、载荷线性变化时的精确递推系数（Chopra《Dynamics of Structures》表 5.2.1）"""
    k = w * w
    wd = w * math.sqrt(1 - z * z)
    e = math.exp(-z * w * dt)
    s, c = math.sin(wd * dt), math.cos(wd * dt)
    r = z / math.sqrt(1 - z * z)
    A = e * (r * s + c)
    B = e * s / wd
    C = (2 * z / (w * dt) + e * (((1 - 2 * z * z) / (wd * dt) - r) * s - (1 + 2 * z / (w * dt)) * c)) / k
    D = (1 - 2 * z / (w * dt) + e * ((2 * z * z - 1) / (wd * dt) * s + 2 * z / (w * dt) * c)) / k
    A1 = -e * (w / math.sqrt(1 - z * z)) * s
    B1 = e * (c - r * s)
    C1 = (-1 / dt + e * ((w / math.sqrt(1 - z * z) + z / (dt * math.sqrt(1 - z * z))) * s + c / dt)) / k
    D1 = (1 - e * (r * s + c)) / (k * dt)
    return A, B, C, D, A1, B1, C1, D1


def sdof_piecewise_linear(w, z, times, p):
    """单自由度 q̈ + 2ζω q̇ + ω² q = p(t)，p 在相邻时刻之间线性变化，初始静止；返回各时刻的 q"""
    q, v = 0.0, 0.0
    out = [0.0]
    cache = {}
    for i in range(len(times) - 1):
        dt = float(times[i + 1] - times[i])
        key = round(dt, 15)
        if key not in cache:
            cache[key] = _coeffs(w, z, dt)
        A, B, C, D, A1, B1, C1, D1 = cache[key]
        q, v = A * q + B * v + C * p[i] + D * p[i + 1], A1 * q + B1 * v + C1 * p[i] + D1 * p[i + 1]
        out.append(q)
    return np.array(out)


def amplitude_at(amp, t):
    ts = np.array([a[0] for a in amp], float)
    fs = np.array([a[1] for a in amp], float)
    return np.interp(t, ts, fs, left=fs[0], right=fs[-1])


def transient(m, amp, t_end, dt, zeta, probes=()):
    """瞬态：载荷 F × a(t)，a 分段线性。积分网格 = 输出时刻 ∪ 载荷折点，故按分段线性载荷精确积分"""
    t_out = np.arange(0, t_end + dt * 0.5, dt)
    breaks = np.array([a[0] for a in amp], float)
    t_all = np.unique(np.concatenate([t_out, breaks[(breaks > 0) & (breaks < t_end)]]))
    a = amplitude_at(amp, t_all)
    om = _omega(m)
    pl = modal_loads(m)
    Qall = np.array([sdof_piecewise_linear(float(om[i]), zeta, t_all, pl[i] * a) for i in range(len(om))])
    idx = np.searchsorted(t_all, t_out)
    idx = np.minimum(idx, len(t_all) - 1)
    Q = Qall[:, idx]                                                   # (阶数, 输出时刻)
    phi, sig = m["phi"], m["sig"]
    umax, uat, ut = 0.0, 0, 0.0
    vmax, vat, vt = 0.0, 0, 0.0
    for k in range(0, len(t_out), 100):
        U = np.einsum("nkm,mt->ntk", phi, Q[:, k:k + 100])
        mag = np.linalg.norm(U, axis=2)
        j = np.unravel_index(int(np.argmax(mag)), mag.shape)
        if mag[j] > umax:
            umax, uat, ut = float(mag[j]), int(j[0]), float(t_out[k + j[1]])
        V = _vm(np.einsum("nim,mt->nti", sig, Q[:, k:k + 100]))
        j = np.unravel_index(int(np.argmax(V)), V.shape)
        if V[j] > vmax:
            vmax, vat, vt = float(V[j]), int(j[0]), float(t_out[k + j[1]])
    out = {"times_s": [round(float(x), 9) for x in t_out], "u_max_mm": round(umax, 9), "u_max_time_s": round(ut, 9),
           "u_max_at_mm": [round(float(x), 3) for x in m["xyz"][uat]],
           "vm_max_mpa": round(vmax, 6), "vm_max_time_s": round(vt, 9), "vm_max_at_mm": [round(float(x), 3) for x in m["xyz"][vat]],
           "probes": []}
    for p in probes:
        j = nearest(m, p["point_mm"])
        U = phi[j] @ Q
        out["probes"].append({"id": p["id"], "node_at_mm": [round(float(x), 4) for x in m["xyz"][j]],
                              "u_mm": [[round(float(x), 9) for x in U[k]] for k in range(3)]})
    return out
