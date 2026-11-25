"""模型 → 分析 → 结果（对外单位）与核查（ADR-0097 D1、D2）。"""

from __future__ import annotations

import math

import numpy as np

from analysis.mbd.dae import model as M
from analysis.mbd.dae import solve as S
from analysis.mbd.dae.system import A_of, B_of, E_of, G_of

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
RESID_LIMIT_M = 1e-8        # 约束残差判据（m 或无量纲）
ENERGY_LIMIT = 1e-6         # 保守系统能量相对漂移判据


def _series(rec, sysm):
    s = sysm
    out_b = {}
    for k, b in enumerate(s.bodies):
        out_b[b.name] = {
            "cm_mm": [(q[7 * k:7 * k + 3] * 1000).tolist() for q in rec.q],
            "v_mm_s": [(qd[7 * k:7 * k + 3] * 1000).tolist() for qd in rec.qd],
            "euler_parameters": [q[7 * k + 3:7 * k + 7].tolist() for q in rec.q],
            "w_deg_s": [np.degrees(2 * E_of(q[7 * k + 3:7 * k + 7]) @ qd[7 * k + 3:7 * k + 7]).tolist()
                        for q, qd in zip(rec.q, rec.qd, strict=True)],
        }
    joints = {}
    for jid in s.joints:
        joints[jid] = {"on": rec.react[0][jid]["on"] if rec.react else "", "complete": rec.react[0][jid]["complete"],
                       "force_n": [r[jid]["force"].tolist() for r in rec.react],
                       "torque_n_m": [r[jid]["torque"].tolist() for r in rec.react]}
    motions = {}
    for mid, mo in s.motions.items():
        vals = [m.get(mid, float("nan")) for m in rec.motion]
        arr = np.array([v for v in vals if math.isfinite(v)])
        motions[mid] = {"joint": mo["joint"], "unit": "N·m" if mo["dof"] == "rotation" else "N", "effort": vals,
                        "peak": float(np.max(np.abs(arr))) if arr.size else None,
                        "rms": float(np.sqrt(np.mean(arr ** 2))) if arr.size else None}
    reqs = {}
    for r in getattr(s, "requests", []):
        b, sv = r["body"], r["s"]
        pos, vel, acc = [], [], []
        for q, qd, qdd in zip(rec.q, rec.qd, rec.qdd, strict=True):
            rr, p = q[7 * b:7 * b + 3], q[7 * b + 3:7 * b + 7]
            pd, pdd = qd[7 * b + 3:7 * b + 7], qdd[7 * b + 3:7 * b + 7]
            pos.append(((rr + A_of(p) @ sv) * 1000).tolist())
            vel.append(((qd[7 * b:7 * b + 3] + B_of(p, sv) @ pd) * 1000).tolist())
            acc.append(((qdd[7 * b:7 * b + 3] + B_of(p, sv) @ pdd + B_of(pd, sv) @ pd) * 1000).tolist())
        if r.get("node") is not None:                   # D6：柔性构件界面节点，加上弹性变形
            fx, o = s.bodies[b].flex, s.foff[b]
            Pt = fx.Phit[r["node"]]
            pos, vel, acc = [], [], []
            for q, qd, qdd in zip(rec.q, rec.qd, rec.qdd, strict=True):
                A = A_of(q[7 * b + 3:7 * b + 7])
                eta, etad, etadd = q[o:o + fx.nm], qd[o:o + fx.nm], qdd[o:o + fx.nm]
                x = fx.x0[r["node"]] + Pt @ eta
                w = s.omega(q, qd, b)
                wb = A.T @ w
                wdb = 2 * G_of(q[7 * b + 3:7 * b + 7]) @ qdd[7 * b + 3:7 * b + 7]
                u, ud = Pt @ etad, Pt @ etadd
                pos.append(((q[7 * b:7 * b + 3] + A @ x) * 1000).tolist())
                vel.append(((qd[7 * b:7 * b + 3] + A @ (np.cross(wb, x) + u)) * 1000).tolist())
                acc.append(((qdd[7 * b:7 * b + 3] + A @ (np.cross(wdb, x) + np.cross(wb, np.cross(wb, x))
                                                           + 2 * np.cross(wb, u) + ud)) * 1000).tolist())
        reqs[r["id"]] = {"pos_mm": pos, "vel_mm_s": vel, "acc_mm_s2": acc}
    energy = {"kinetic_j": [e[0] for e in rec.energy], "potential_j": [e[1] for e in rec.energy]}
    meas = {}
    units = {"joint_angle": "deg", "joint_speed": "deg/s", "joint_displacement": "mm", "joint_velocity": "mm/s",
             "point_distance": "mm", "point_distance_rate": "mm/s"}
    if getattr(s, "measure_defs", None):
        vals = [s.measures(q, qd) for q, qd in zip(rec.q, rec.qd, strict=True)]
        for m in s.measure_defs:
            meas[m["id"]] = {"type": m["type"], "unit": units[m["type"]], "values": [v[m["id"]] for v in vals]}
    cont = {}
    for kind, f in s.forces:
        if kind not in ("contact", "gear"):
            continue
        from analysis.mbd.dae.contact import contact_wrenches, gear_wrenches
        normal, fric, npts = [], [], []
        for q, qd in zip(rec.q, rec.qd, strict=True):
            F, N = np.zeros((s.nb, 3)), np.zeros((s.nb, 3))
            if kind == "gear":
                normal.append(gear_wrenches(s, q, qd, f, F, N))
                continue
            pts = contact_wrenches(s, q, qd, f, F, N)
            normal.append(sum(p[1] for p in pts))
            fric.append(sum(p[2] for p in pts))
            npts.append(len(pts))
        cont[f["id"]] = {"type": "gear_mesh" if kind == "gear" else "contact", "normal_force_n": normal,
                         "peak_n": max(normal) if normal else None}
        if kind == "contact":
            cont[f["id"]] |= {"friction_force_n": fric, "points": npts}
    flex = {}
    for k, bd in enumerate(s.bodies):
        if bd.flex is None:
            continue
        fx, o = bd.flex, s.foff[k]
        nodes = {}
        for n in fx.interface:
            nodes[str(n)] = [((q[7 * k:7 * k + 3] + A_of(q[7 * k + 3:7 * k + 7]) @ (fx.x0[n] + fx.Phit[n] @ q[o:o + fx.nm]))
                              * 1000).tolist() for q in rec.q]
        stress = None
        if getattr(fx, "stress_shapes", None) is not None:      # D6b：应力回放 σ(t) = Σ ηₖ σₖ
            from analysis.mbd.flexsolid import von_mises

            vmax, where = [], []
            for q in rec.q:
                vm = von_mises(np.einsum("k,kni->ni", q[o:o + fx.nm], fx.stress_shapes))
                j = int(np.argmax(vm))
                vmax.append(float(vm[j]))
                where.append(int(fx.stress_nodes[j]))
            kmax = int(np.argmax(vmax))
            stress = {"max_von_mises_mpa": vmax, "max_node": where, "peak_mpa": vmax[kmax], "peak_time_s": rec.t[kmax],
                      "peak_node": where[kmax],
                      "peak_node_mm": (fx.nodes_world0[where[kmax]] * 1000).tolist() if fx.nodes_world0 is not None else None}
        flex[bd.name] = {"modes": fx.nm, "stress": stress, "frequencies_hz": (fx.freqs / (2 * math.pi)).tolist(),
                         "eta": [q[o:o + fx.nm].tolist() for q in rec.q],
                         "elastic_energy_j": [0.5 * float(q[o:o + fx.nm] @ fx.K @ q[o:o + fx.nm]) for q in rec.q],
                         "interface_nodes_mm": nodes}
    flex.update(_nlbeam_out(s, rec))
    out_b["_flex"] = flex
    if getattr(rec, "ctrl", None):
        acts = sorted({a for d in rec.ctrl for a in d} | {f["id"] for kind, f in s.forces if kind == "actuator"})
        out_b["_act"] = {a: [float(d.get(a, 0.0)) for d in rec.ctrl] for a in acts}
    return out_b, joints, motions, reqs, energy, meas, cont


def _nlbeam_out(s, rec):
    """大变形梁（ADR-0101）：每帧每个单元的截面内力（轴力、两个剪力 N，扭矩、两个弯矩 N·m）、节点位置、最大正应力"""
    from analysis.mbd.dae.nlbeam import element

    out = {}
    for name, info in (getattr(s, "nlbeams", None) or {}).items():
        els = [f for kind, f in s.forces if kind == "nlbeam" and f["beam"] == name]
        nodes = [next(k for k, b in enumerate(s.bodies) if b.name == nid) for nid in info["nodes"]]
        A, (Iy, Iz) = info["area_m2"], info["I"]
        fy, fz = info["fiber"]
        frames = {"axial_n": [], "shear_y_n": [], "shear_z_n": [], "torque_n_m": [], "moment_y_n_m": [], "moment_z_n_m": [],
                  "max_stress_mpa": [], "nodes_mm": []}
        for q, qd in zip(rec.q, rec.qd, strict=True):
            nm = np.array([element(s, q, qd, f)[:2] for f in els])            # 单元 × (n, m) × 3
            n, m = nm[:, 0, :], nm[:, 1, :]
            for key, col in (("axial_n", n[:, 0]), ("shear_y_n", n[:, 1]), ("shear_z_n", n[:, 2]), ("torque_n_m", m[:, 0]),
                             ("moment_y_n_m", m[:, 1]), ("moment_z_n_m", m[:, 2])):
                frames[key].append(col.tolist())
            if fy and fz:
                sig = np.abs(n[:, 0]) / A + np.abs(m[:, 1]) * fz * 1e-3 / Iy + np.abs(m[:, 2]) * fy * 1e-3 / Iz
                frames["max_stress_mpa"].append(float(sig.max() / 1e6))
            frames["nodes_mm"].append([(q[7 * k:7 * k + 3] * 1000).tolist() for k in nodes])
        if not (fy and fz):
            frames["max_stress_mpa"] = None
        out[name] = {"type": "nonlinear_beam", "nodes": info["nodes"], "elements": len(els), **frames}
    return out


def _conservative(sysm) -> bool:
    if sysm.motions:
        return False
    if any(b.flex is not None and b.flex.zeta > 0 for b in sysm.bodies):
        return False
    if any(info.get("friction") for info in sysm.joints.values()):
        return False
    for kind, f in sysm.forces:
        if kind in ("bushing", "beam", "clearance", "contact", "gear", "actuator", "nlbeam"):
            return False          # 衬套、梁的阻尼和间隙碰撞耗能；势能也没单独算
        if kind == "rspring" and (f["c"] > 0 or f["pre"]):
            return False
        if kind == "spring" and f["c"] > 0:
            return False
        if kind in ("force", "torque"):
            if any(not fn.expr.constant for fn in f["fn"]):
                return False
            if kind == "force" and any(fn(0.0) for fn in f["fn"]):
                return False          # 恒力也做功，但不进势能：不按能量守恒判
            if kind == "torque" and any(fn(0.0) for fn in f["fn"]):
                return False
    return True


def run_model(model: dict, base_dir=None):
    sysm = M.build(model, base_dir)
    an = model["analysis"]
    typ = an["type"]
    steps = int(an.get("output_steps", 100))
    t_end = float(an.get("end_time_s", 1.0))
    method = an.get("integrator", "DOP853")
    rtol, atol = float(an.get("rtol", 1e-8)), float(an.get("atol", 1e-10))
    if method == "HHT":                     # ADR-0098：二阶隐式，缺省容差放宽到它的精度档
        from analysis.mbd.dae import hht

        rtol, atol = float(an.get("rtol", 1e-6)), float(an.get("atol", 1e-9))

        def dyn(sysm_, t_end_, steps_, **kw):
            kw.pop("method")
            return hht.dynamic(sysm_, t_end_, steps_, alpha=float(an.get("hht_alpha", -0.1)), **kw)
    else:
        dyn = S.dynamic
    S.check_structure(sysm, sysm.q0(), 0.0)          # 问渠 CAD 0.3.6 细则 C3：锁死在分析入口报出来
    messages = []
    stab = None
    if typ == "kinematic":
        rec, info = S.kinematic(sysm, t_end, steps)
    elif typ == "static":
        rec, info = S.static(sysm, load_steps=int(an.get("load_steps", 1)))
        stab = _stability(sysm, rec.q[-1], rec.t[-1])
    elif typ == "dynamic":
        rec, info = dyn(sysm, t_end, steps, method=method, rtol=rtol, atol=atol)
    elif typ in ("linear", "static_then_linear"):
        return _run_linear(model, sysm, typ)
    else:  # static_then_dynamic
        st, info0 = S.static(sysm, load_steps=int(an.get("load_steps", 1)))
        messages.append("先做静平衡（残差 {:.2g}），从平衡位置开始动力学".format(info0["residual"]))
        stab = _stability(sysm, st.q[0], 0.0)
        if stab["status"] == FAIL:
            messages.append("注意：静平衡找到的是不稳定平衡，动力学从这里出发会长时间“静止”（舍入误差要很久才放大），"
                            "看起来像稳定，其实一碰就倒。给一点初始扰动或改用稳定的平衡位置")
        rec, info = dyn(sysm, t_end, steps, method=method, rtol=rtol, atol=atol, q=st.q[0], qd=np.zeros(sysm.n))
    if info.get("redundant"):
        messages.append("删掉了 {} 条冗余约束（反力里这些方向的分量不唯一，标为不完整）：{}".format(
            len(info["redundant"]), "、".join(info["redundant"])))
    nr = getattr(sysm, "near_redundant", None)
    if nr:
        messages.append("运动副近冗余：{} 这组约束的奇异值只有最大值的 {:.2g}（制造误差级），按冗余处理；"
                        "被删约束在运动中实际拉开多少，见“约束残差（全部约束）”核查".format("、".join(nr["joints"]), nr["sigma_rel"]))
    bodies, joints, motions, reqs, energy, meas, cont = _series(rec, sysm)
    flex = bodies.pop("_flex")
    act = bodies.pop("_act", {})
    resid = max(rec.resid) if rec.resid else 0.0
    verification = [{"key": "constraint_residual", "name": "约束残差（全部约束，含删掉的冗余约束）", "value": resid,
                     "limit": RESID_LIMIT_M, "status": PASS if resid <= RESID_LIMIT_M else FAIL}]
    if typ in ("dynamic", "static_then_dynamic"):
        if _conservative(sysm):
            tot = [k + p for k, p in zip(energy["kinetic_j"], energy["potential_j"], strict=True)]
            scale = max(max(abs(x) for x in energy["kinetic_j"]), abs(tot[0]), 1e-12)
            drift = max(abs(x - tot[0]) for x in tot) / scale
            verification.append({"key": "energy_drift", "name": "能量守恒（无驱动、无阻尼、无外力时的相对漂移）", "value": drift,
                                 "limit": ENERGY_LIMIT, "status": PASS if drift <= ENERGY_LIMIT else FAIL})
        else:
            verification.append({"key": "energy_drift", "name": "能量守恒", "value": None, "limit": ENERGY_LIMIT,
                                 "status": UNKNOWN, "note": "有驱动、阻尼或外力，系统不守恒，不判"})
    fl = _friction_check(sysm, messages)
    if fl is not None:
        verification.append(fl)
    dof_g = M.grubler(sysm)
    # 问渠 CAD 0.3.6 细则 C3：原来比的是“秩算自由度”和“Grübler + 冗余数”，冗余数 = 约束数 − 秩，两边按定义恒等，永远通过。
    # 改成比两个独立算出的数：起始位形和结束位形上只看运动副的结构自由度——相同说明冗余是结构上的；不同说明碰上了奇异位形
    s0 = S.structural(sysm, sysm.q0(), 0.0)
    s1 = S.structural(sysm, np.asarray(rec.q[-1]), float(rec.t[-1])) if len(rec.t) > 1 else s0
    verification.append({"key": "dof", "name": "结构自由度（只看运动副的秩，起始与结束位形各算一次）", "value": s0["dof"],
                         "end_value": s1["dof"], "grubler": dof_g + len(sysm.motions), "drives": len(sysm.motions),
                         "redundant": len(info.get("redundant", [])),
                         "status": PASS if s0["dof"] == s1["dof"] else UNKNOWN,
                         "note": "两个位形的结构自由度相同时通过（冗余是结构上的）；不同说明运动中经过奇异位形，请检查模型。"
                                 "Grübler 数只作参考（有冗余约束时它偏小）"})
    data = {"model": model["name"], "analysis": typ, "dof": info["dof"], "redundant_constraints": info.get("redundant", []),
            "times_s": rec.t, "bodies": bodies, "joints": joints, "motions": motions, "requests": reqs, "measures": meas,
            "contacts": cont, "flex": flex, "actuators": act, "energy": energy,
            "verification": verification,
            "solver": {k: info[k] for k in ("rhs", "segments", "repartitions", "steps", "rejected", "jacobians", "newton",
                                                       "newton_fail", "error_fail", "h_min", "h_max")
                       if k in info} | {"integrator": method, "rtol": rtol,
                                                                                               "atol": atol}}
    if stab is not None:
        verification.append(stab)
        if stab["status"] == FAIL:
            messages.append("静平衡不稳定：平衡位置有 {} 个特征值实部为正（最大 {:.3g} 1/s），一碰就会离开；"
                            "这是结论，不是计算错误。要找稳定平衡可换初始位置，或用 static_then_dynamic 加扰动和阻尼".format(
                                stab["value"], stab["max_real"]))
    return data, messages


def _friction_check(sysm, messages):
    """运动副摩擦的不动点迭代有没有收敛（《多体动力学》书线索第 29 条，问渠 CAD 0.3.8 细则）"""
    if not any(info.get("friction") for info in sysm.joints.values()):
        return None
    log = sysm.__dict__.get("friction_log") or {}
    fail = log.get("fail", 0)          # 自锁（增益 ≥ 1）在求解时就停下报错，到不了这里
    item = {"key": "friction_iteration", "name": "运动副摩擦迭代收敛（摩擦力与约束反力一致）", "value": fail,
            "limit": 0, "status": PASS if fail == 0 else FAIL}
    if log.get("gain_max", 0.0) >= S.FRICTION_LOCK_GAIN:
        messages.append("接近自锁：t = {:.6g} s 运动副摩擦的迭代增益到 {:.3g}（1 就卡死），摩擦最大的是运动副“{}”；"
                        "这附近的驱动力矩、反力对摩擦系数非常敏感".format(log["gain_t"], log["gain_max"], log["gain_joint"]))
    if fail:
        messages.append("摩擦迭代不收敛：t = {:.6g} s 起共 {} 次，摩擦最大的是运动副“{}”，这些时刻的结果不可信".format(
            log["t_first"], fail, log["joint"]))
    return item


def _plant_inputs(model, sysm):
    names = {b.name: k for k, b in enumerate(sysm.bodies)}
    out = []
    for u in (model["analysis"].get("plant") or {}).get("inputs", []):
        if u["body"] not in names:
            raise M.ModelError(f"状态空间输入 {u['id']}：没有构件 {u['body']}（地面上加力没有意义）")
        k = names[u["body"]]
        d = np.asarray(u["direction"], float)
        if np.linalg.norm(d) < 1e-12:
            raise M.ModelError(f"状态空间输入 {u['id']}：方向不能是零向量")
        P = np.asarray(u.get("point_mm", (sysm.bodies[k].r0 * 1000).tolist()), float) * 1e-3
        out.append({"id": u["id"], "type": u["type"], "body": k, "dir": d / np.linalg.norm(d), "s": P - sysm.bodies[k].r0})
    return out


def _stability(sysm, q, t):
    """静平衡位置的稳定性：在平衡位置线性化，特征值实部有正的就不稳定（问渠 CAD 0.3.6 细则 C4，
    《多体动力学》书第 21 章线索第 21 条：原来静平衡不判稳定，倒立杆、四杆机构可能落在不稳定平衡上，核查全部通过）"""
    from analysis.mbd.dae import linear as L
    item = {"key": "stability", "name": "静平衡的稳定性（平衡位置线性化，特征值实部都不大于 0）"}
    try:
        lin, _, _ = L.linearize(sysm, np.asarray(q), np.zeros(sysm.n), float(t), xc=getattr(sysm, "static_xc", None))
    except Exception as exc:  # noqa: BLE001 — 线性化做不了时如实标“未知”，不影响静平衡结果
        return item | {"value": None, "status": UNKNOWN, "note": f"线性化没做成，稳定性未判：{str(exc)[:120]}"}
    reals = [m["eigenvalue"][0] for m in lin["modes"]]
    unstable = [m for m in lin["modes"] if not m.get("rigid_body")
                and m["eigenvalue"][0] > 1e-6 * max(1.0, abs(complex(*m["eigenvalue"])))]
    note = "有实部为正的特征值说明平衡不稳定（例如倒立摆顶点），这是结论不是计算错误"
    if L.nonsmooth(sysm):
        note += "；模型里有摩擦、接触、间隙或齿轮侧隙，线性化只在平衡点附近、接触状态不变时成立"
    return item | {"value": len(unstable), "max_real": max(reals) if reals else 0.0,
                   "status": PASS if not unstable else FAIL, "note": note}


EQ_ALPHA_LIMIT = 1e-3     # rad/s²：静止工作点上构件角加速度超过它，就不算平衡点（线索第 48 条）
EQ_ACC_LIMIT = 1.0        # mm/s²（约 1e-4 g）


def _working_point(sysm, q, qd, qdd):
    """工作点各刚体的加速度：最大线加速度、最大角加速度和所在构件；静止（速度近零）时据此判是不是平衡点"""
    a_max, al_max, who = 0.0, 0.0, None
    v_max, w_max = 0.0, 0.0
    for k in range(sysm.nb):
        p = q[7 * k + 3:7 * k + 7]
        a = float(np.linalg.norm(qdd[7 * k:7 * k + 3]))
        al = float(np.linalg.norm(2 * G_of(p) @ qdd[7 * k + 3:7 * k + 7]))
        v_max = max(v_max, float(np.linalg.norm(qd[7 * k:7 * k + 3])))
        w_max = max(w_max, float(np.linalg.norm(2 * G_of(p) @ qd[7 * k + 3:7 * k + 7])))
        if al / EQ_ALPHA_LIMIT + a / EQ_ACC_LIMIT > al_max / EQ_ALPHA_LIMIT + a_max / EQ_ACC_LIMIT:
            a_max, al_max, who = a, al, sysm.bodies[k].name
    static = v_max <= 1e-6 and w_max <= 1e-9
    return {"static": static, "equilibrium": a_max <= EQ_ACC_LIMIT and al_max <= EQ_ALPHA_LIMIT,
            "a_mm_s2": a_max, "alpha_rad_s2": al_max, "body": who}


def _run_linear(model, sysm, typ):
    from analysis.mbd.dae import linear as L
    an = model["analysis"]
    messages = []
    outputs = (an.get("plant") or {}).get("outputs", [])
    known = {m["id"] for m in getattr(sysm, "measure_defs", [])}
    for o in outputs:
        if o not in known:
            raise M.ModelError(f"状态空间输出 {o} 不在 measures 里")
    inputs = _plant_inputs(model, sysm)
    xc = None
    if typ == "static_then_linear":
        st, info0 = S.static(sysm, load_steps=int(an.get("load_steps", 1)))
        messages.append("先做静平衡（残差 {:.2g}），在平衡位置线性化".format(info0["residual"]))
        q, qd = st.q[0], np.zeros(sysm.n)
        xc = getattr(sysm, "static_xc", None)
    else:
        q = sysm.q0()
        keep, _ = S.independent_rows(sysm, q, 0.0)
        rows = S._rows(sysm, keep)
        q = S.assemble(sysm, q, 0.0, rows)
        qd = S.initial_velocity(sysm, q, 0.0, rows)
    if L.nonsmooth(sysm):
        messages.append("模型里有摩擦、接触、间隙或齿轮侧隙：这些力不光滑，线性化结果只在工作点附近、接触状态不变时成立")
    ctrl = getattr(sysm, "ctrl", None)
    if ctrl is not None and ctrl.fmus:
        messages.append("模型里有 FMU 控制器：它是采样（离散）控制器，线性化不含它，模态和稳定性按没有这个控制器算")
    lin, q, qd = L.linearize(sysm, q, qd, 0.0, inputs, outputs, an.get("modes"), xc=xc)
    rec = S.Recorder(sysm)
    keep, _ = S.independent_rows(sysm, q, 0.0)
    rows = S._rows(sysm, keep)
    qdd, lam = S.accel(sysm, q, qd, 0.0, rows)
    rec.add(0.0, q, qd, qdd, keep, lam)
    bodies, joints, motions, reqs, energy, meas, cont = _series(rec, sysm)
    flex = bodies.pop("_flex")
    act = bodies.pop("_act", {})
    resid = max(rec.resid) if rec.resid else 0.0
    unstable = [m for m in lin["modes"] if not m.get("rigid_body")
                and m["eigenvalue"][0] > 1e-6 * max(1.0, abs(complex(*m["eigenvalue"])))]
    wp = _working_point(sysm, q, qd, qdd)
    stab_item = {"key": "stability", "name": "工作点稳定性（特征值实部都不大于 0）", "value": len(unstable),
                 "status": PASS if not unstable else FAIL,
                 "note": "有实部为正的特征值说明工作点不稳定（例如倒立摆顶点），这是结论不是计算错误"}
    if wp["static"] and not wp["equilibrium"]:
        # 《多体动力学》书第 32 章线索第 48 条（问渠 CAD 0.3.8 细则）：原来不查工作点是不是平衡点，
        # 软关节柔性臂零位（弹簧不受力、角加速度 24.5 rad/s²）照样线性化、稳定性判通过，第一阶频率差 18 %
        stab_item |= {"status": UNKNOWN, "note": "工作点不是平衡点（静止但有加速度），在这里线性化没有意义，稳定性不判"}
        messages.append("工作点不是平衡点：静止时构件“{}”的加速度 {:.3g} mm/s²、角加速度 {:.3g} rad/s²，"
                        "模态和稳定性只在平衡点上才有意义。请改用 static_then_linear（先找静平衡再线性化），"
                        "或确认这就是想要的工作点".format(wp["body"], wp["a_mm_s2"], wp["alpha_rad_s2"]))
    verification = [{"key": "constraint_residual", "name": "约束残差（工作点）", "value": resid, "limit": RESID_LIMIT_M,
                     "status": PASS if resid <= RESID_LIMIT_M else FAIL},
                    {"key": "equilibrium", "name": "工作点是平衡点（静止时各构件加速度近零）",
                     "value": wp["alpha_rad_s2"], "a_mm_s2": wp["a_mm_s2"], "body": wp["body"],
                     "limit": EQ_ALPHA_LIMIT, "limit_a_mm_s2": EQ_ACC_LIMIT,
                     "status": (PASS if wp["equilibrium"] else FAIL) if wp["static"] else UNKNOWN,
                     **({} if wp["static"] else {"note": "工作点有速度（稳态运动），不要求是平衡点，不判"})},
                    stab_item]
    if lin["redundant"]:
        messages.append("删掉了 {} 条冗余约束：{}".format(len(lin["redundant"]), "、".join(lin["redundant"])))
    data = {"model": model["name"], "analysis": typ, "dof": lin["dof"], "redundant_constraints": lin["redundant"],
            "times_s": rec.t, "bodies": bodies, "joints": joints, "motions": motions, "requests": reqs, "measures": meas,
            "contacts": cont, "flex": flex, "actuators": act, "energy": energy, "linear": {k: v for k, v in lin.items() if k != "redundant"},
            "verification": verification, "solver": {"linearization": "中心差分（相对步长 1e-6），B 精确"}}
    return data, messages
