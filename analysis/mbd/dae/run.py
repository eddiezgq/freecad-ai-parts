"""模型 → 分析 → 结果（对外单位）与核查（ADR-0097 D1）。"""

from __future__ import annotations

import math

import numpy as np

from analysis.mbd.dae import model as M
from analysis.mbd.dae import solve as S
from analysis.mbd.dae.system import B_of, E_of

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
            from analysis.mbd.dae.system import A_of
            pos.append(((rr + A_of(p) @ sv) * 1000).tolist())
            vel.append(((qd[7 * b:7 * b + 3] + B_of(p, sv) @ pd) * 1000).tolist())
            acc.append(((qdd[7 * b:7 * b + 3] + B_of(p, sv) @ pdd + B_of(pd, sv) @ pd) * 1000).tolist())
        reqs[r["id"]] = {"pos_mm": pos, "vel_mm_s": vel, "acc_mm_s2": acc}
    energy = {"kinetic_j": [e[0] for e in rec.energy], "potential_j": [e[1] for e in rec.energy]}
    return out_b, joints, motions, reqs, energy


def _conservative(sysm) -> bool:
    if sysm.motions:
        return False
    for kind, f in sysm.forces:
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
    else:  # static_then_dynamic
        st, info0 = S.static(sysm)
        messages.append("先做静平衡（残差 {:.2g}），从平衡位置开始动力学".format(info0["residual"]))
        rec, info = S.dynamic(sysm, t_end, steps, method=method, rtol=rtol, atol=atol, q=st.q[0], qd=np.zeros(sysm.n))
    if info.get("redundant"):
        messages.append("删掉了 {} 条冗余约束（反力里这些方向的分量不唯一，标为不完整）：{}".format(
            len(info["redundant"]), "、".join(info["redundant"])))
    bodies, joints, motions, reqs, energy = _series(rec, sysm)
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
            "times_s": rec.t, "bodies": bodies, "joints": joints, "motions": motions, "requests": reqs, "energy": energy,
            "verification": verification,
            "solver": {k: info[k] for k in ("rhs", "segments", "repartitions") if k in info} | {"integrator": method, "rtol": rtol,
                                                                                               "atol": atol}}
    return data, messages
