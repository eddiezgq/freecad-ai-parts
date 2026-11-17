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
    out_b["_flex"] = flex
    return out_b, joints, motions, reqs, energy, meas, cont


def _conservative(sysm) -> bool:
    if sysm.motions:
        return False
    if any(b.flex is not None and b.flex.zeta > 0 for b in sysm.bodies):
        return False
    if any(info.get("friction") for info in sysm.joints.values()):
        return False
    for kind, f in sysm.forces:
        if kind in ("bushing", "beam", "clearance", "contact", "gear"):
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


def run_model(model: dict):
    sysm = M.build(model)
    an = model["analysis"]
    typ = an["type"]
    steps = int(an.get("output_steps", 100))
    t_end = float(an.get("end_time_s", 1.0))
    method = an.get("integrator", "DOP853")
    rtol, atol = float(an.get("rtol", 1e-8)), float(an.get("atol", 1e-10))
    messages = []
    if typ == "kinematic":
        rec, info = S.kinematic(sysm, t_end, steps)
    elif typ == "static":
        rec, info = S.static(sysm)
    elif typ == "dynamic":
        rec, info = S.dynamic(sysm, t_end, steps, method=method, rtol=rtol, atol=atol)
    elif typ in ("linear", "static_then_linear"):
        return _run_linear(model, sysm, typ)
    else:  # static_then_dynamic
        st, info0 = S.static(sysm)
        messages.append("先做静平衡（残差 {:.2g}），从平衡位置开始动力学".format(info0["residual"]))
        rec, info = S.dynamic(sysm, t_end, steps, method=method, rtol=rtol, atol=atol, q=st.q[0], qd=np.zeros(sysm.n))
    if info.get("redundant"):
        messages.append("删掉了 {} 条冗余约束（反力里这些方向的分量不唯一，标为不完整）：{}".format(
            len(info["redundant"]), "、".join(info["redundant"])))
    bodies, joints, motions, reqs, energy, meas, cont = _series(rec, sysm)
    flex = bodies.pop("_flex")
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
    dof_g = M.grubler(sysm)
    verification.append({"key": "dof", "name": "自由度（雅可比秩算）与 Grübler 公式", "value": info["dof"], "grubler": dof_g,
                         "redundant": len(info.get("redundant", [])),
                         "status": PASS if info["dof"] == dof_g + len(info.get("redundant", [])) else UNKNOWN,
                         "note": "雅可比秩算出的自由度 = Grübler 自由度 + 冗余约束数时通过；不等说明有奇异位形，请检查模型"})
    data = {"model": model["name"], "analysis": typ, "dof": info["dof"], "redundant_constraints": info.get("redundant", []),
            "times_s": rec.t, "bodies": bodies, "joints": joints, "motions": motions, "requests": reqs, "measures": meas,
            "contacts": cont, "flex": flex, "energy": energy,
            "verification": verification,
            "solver": {k: info[k] for k in ("rhs", "segments", "repartitions") if k in info} | {"integrator": method, "rtol": rtol,
                                                                                               "atol": atol}}
    return data, messages


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
    if typ == "static_then_linear":
        st, info0 = S.static(sysm)
        messages.append("先做静平衡（残差 {:.2g}），在平衡位置线性化".format(info0["residual"]))
        q, qd = st.q[0], np.zeros(sysm.n)
    else:
        q = sysm.q0()
        keep, _ = S.independent_rows(sysm, q, 0.0)
        rows = S._rows(sysm, keep)
        q = S.assemble(sysm, q, 0.0, rows)
        qd = S.initial_velocity(sysm, q, 0.0, rows)
    if L.nonsmooth(sysm):
        messages.append("模型里有摩擦、接触、间隙或齿轮侧隙：这些力不光滑，线性化结果只在工作点附近、接触状态不变时成立")
    lin, q, qd = L.linearize(sysm, q, qd, 0.0, inputs, outputs, an.get("modes"))
    rec = S.Recorder(sysm)
    keep, _ = S.independent_rows(sysm, q, 0.0)
    rows = S._rows(sysm, keep)
    qdd, lam = S.accel(sysm, q, qd, 0.0, rows)
    rec.add(0.0, q, qd, qdd, keep, lam)
    bodies, joints, motions, reqs, energy, meas, cont = _series(rec, sysm)
    flex = bodies.pop("_flex")
    resid = max(rec.resid) if rec.resid else 0.0
    unstable = [m for m in lin["modes"] if m["eigenvalue"][0] > 1e-6 * max(1.0, abs(complex(*m["eigenvalue"])))]
    verification = [{"key": "constraint_residual", "name": "约束残差（工作点）", "value": resid, "limit": RESID_LIMIT_M,
                     "status": PASS if resid <= RESID_LIMIT_M else FAIL},
                    {"key": "stability", "name": "工作点稳定性（特征值实部都不大于 0）", "value": len(unstable),
                     "status": PASS if not unstable else FAIL,
                     "note": "有实部为正的特征值说明工作点不稳定（例如倒立摆顶点），这是结论不是计算错误"}]
    if lin["redundant"]:
        messages.append("删掉了 {} 条冗余约束：{}".format(len(lin["redundant"]), "、".join(lin["redundant"])))
    data = {"model": model["name"], "analysis": typ, "dof": lin["dof"], "redundant_constraints": lin["redundant"],
            "times_s": rec.t, "bodies": bodies, "joints": joints, "motions": motions, "requests": reqs, "measures": meas,
            "contacts": cont, "flex": flex, "energy": energy, "linear": {k: v for k, v in lin.items() if k != "redundant"},
            "verification": verification, "solver": {"linearization": "中心差分（相对步长 1e-6），B 精确"}}
    return data, messages
