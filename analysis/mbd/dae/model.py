"""模型（schema/mbd-model.schema.json，format = mbd-model/1）→ 内核 System（SI）。单位换算只在这里（ADR-0097 补充一）。"""

from __future__ import annotations

import math

import numpy as np

from analysis.mbd.dae.expr import ExprError
from analysis.mbd.dae.system import Body, Row, System, fn_of, frame_from_axis

MM = 1e-3
DEG = math.pi / 180
RPM = 2 * math.pi / 60

N_ROWS = {"spherical": 3, "revolute": 5, "cylindrical": 4, "translational": 5, "universal": 4, "fixed": 6}


class ModelError(ValueError):
    pass


def _v(x, name):
    a = np.asarray(x, float)
    if a.shape != (3,) or not np.all(np.isfinite(a)):
        raise ModelError(f"{name} 要 3 个数")
    return a


def _unit(x, name):
    a = _v(x, name)
    n = np.linalg.norm(a)
    if n < 1e-12:
        raise ModelError(f"{name} 不能是零向量")
    return a / n


def build(model: dict) -> System:
    from kb.validation import errors

    errs = errors("mbd-model.schema.json", model)
    if errs:
        raise ModelError("模型不符合 schema：" + "；".join(errs[:5]))
    g = _v(model.get("gravity_mm_s2", [0, 0, 0]), "gravity_mm_s2") * MM
    bodies = []
    seen = set()
    for b in model["bodies"]:
        if b["id"] in seen:
            raise ModelError(f"构件 id 重复：{b['id']}")
        seen.add(b["id"])
        it = b["inertia_kg_m2"]
        J = np.array([[it["ixx"], it.get("ixy", 0.0), it.get("ixz", 0.0)],
                      [it.get("ixy", 0.0), it["iyy"], it.get("iyz", 0.0)],
                      [it.get("ixz", 0.0), it.get("iyz", 0.0), it["izz"]]], float)
        ev = np.linalg.eigvalsh(J)
        if ev.min() <= 0:
            raise ModelError(f"构件 {b['id']} 的惯性张量不是正定的（主惯量 {ev.round(9).tolist()}）")
        bodies.append(Body(b["id"], float(b["mass_kg"]), J, _v(b["cm_mm"], "cm_mm") * MM,
                           v0=_v(b.get("v0_mm_s", [0, 0, 0]), "v0_mm_s") * MM,
                           w0=_v(b.get("w0_deg_s", [0, 0, 0]), "w0_deg_s") * DEG))
    sysm = System(bodies, g)
    idx = {b.name: k for k, b in enumerate(bodies)}
    idx["ground"] = -1

    def body(name, where):
        if name not in idx:
            raise ModelError(f"{where}：没有构件 {name}")
        return idx[name]

    def local(b, P):
        """地面系的点 → 构件系（t = 0 构件系与地面同向，原点在质心）"""
        return P if b < 0 else P - bodies[b].r0

    for k in range(len(bodies)):
        sysm.rows.append(Row("norm", k, k, joint="", label=f"{bodies[k].name} 欧拉参数归一"))

    ids = set()
    for jt in model.get("joints") or []:
        jid = jt["id"]
        if jid in ids:
            raise ModelError(f"运动副 id 重复：{jid}")
        ids.add(jid)
        i, j = body(jt["body_i"], jid), body(jt["body_j"], jid)
        if i == j:
            raise ModelError(f"运动副 {jid} 两边是同一个构件")
        P = _v(jt["point_mm"], f"{jid}.point_mm") * MM
        si, sj = local(i, P), local(j, P)
        typ = jt["type"]
        start = len(sysm.rows)
        info = {"type": typ, "i": i, "j": j, "si": si, "sj": sj, "P": P}

        def add(kind, label, i=i, j=j, jid=jid, **kw):
            sysm.rows.append(Row(kind, i, j, joint=jid, label=f"{jid} {label}", **kw))

        if typ in ("spherical", "revolute", "universal", "fixed"):
            for c in range(3):
                add("sph", "xyz"[c], s_i=si, s_j=sj, k=c)
        if typ in ("revolute", "cylindrical", "translational", "fixed"):
            f, gg, h = frame_from_axis(jt["axis"]) if typ != "fixed" else frame_from_axis([0, 0, 1])
            info.update(f=f, g=gg, h=h)
            add("dot1", "f_i·h_j", a_i=f, a_j=h) if typ != "fixed" else add("dot1", "f_i·g_j", a_i=f, a_j=gg)
            add("dot1", "g_i·h_j", a_i=gg, a_j=h)
            if typ == "fixed":
                add("dot1", "h_i·f_j", a_i=h, a_j=f)
            if typ in ("cylindrical", "translational"):
                add("dot2", "f_i·d", a_i=f, s_i=si, s_j=sj)
                add("dot2", "g_i·d", a_i=gg, s_i=si, s_j=sj)
            if typ == "translational":
                add("dot1", "f_i·g_j", a_i=f, a_j=gg)
        if typ == "universal":
            ai, aj = _unit(jt["axis_i"], f"{jid}.axis_i"), _unit(jt["axis_j"], f"{jid}.axis_j")
            if abs(ai @ aj) > 1e-6:
                raise ModelError(f"万向副 {jid} 的两个十字轴要垂直")
            add("dot1", "a_i·a_j", a_i=ai, a_j=aj)
        info["rows"] = list(range(start, len(sysm.rows)))
        if "initial_speed" in jt:
            if typ not in ("revolute", "translational", "cylindrical"):
                raise ModelError(f"运动副 {jid}：只有转动、移动、圆柱副能给初速度")
            info["initial_speed"] = float(jt["initial_speed"])
        sysm.joints[jid] = info

    mids = set()
    for mo in model.get("motions") or []:
        mid = mo["id"]
        if mid in mids or mid in ids:
            raise ModelError(f"驱动 id 重复：{mid}")
        mids.add(mid)
        if mo["joint"] not in sysm.joints:
            raise ModelError(f"驱动 {mid}：没有运动副 {mo['joint']}")
        jinfo = sysm.joints[mo["joint"]]
        dof, typ = mo["dof"], jinfo["type"]
        ok = {"revolute": {"rotation"}, "translational": {"translation"}, "cylindrical": {"rotation", "translation"}}
        if dof not in ok.get(typ, set()):
            raise ModelError(f"驱动 {mid}：{typ} 副不能加 {dof} 驱动")
        scale = DEG if dof == "rotation" else MM
        try:
            if "speed" in mo:
                v = float(mo["speed"]) * (RPM / DEG if dof == "rotation" else 1.0)   # 换成 °/s 或 mm/s
                fn = fn_of(f"{v!r}*time", scale)
            else:
                fn = fn_of(mo["function"], scale)
                if abs(fn(0.0)) > 1e-9:
                    raise ModelError(f"驱动 {mid}：t = 0 时位移要是 0（相对装配位置），现在是 {fn.expr(0.0)}")
        except ExprError as exc:
            raise ModelError(f"驱动 {mid} 的函数：{exc}") from exc
        i, j = jinfo["i"], jinfo["j"]
        if dof == "rotation":
            row = Row("rdrive", i, j, a_i=jinfo["f"], a_j=jinfo["f"], b_i=jinfo["g"], fn=fn, joint=mo["joint"],
                      label=f"{mid} 转动驱动")
        else:
            row = Row("tdrive", i, j, a_i=jinfo["h"], s_i=jinfo["si"], s_j=jinfo["sj"], fn=fn, c=0.0, joint=mo["joint"],
                      label=f"{mid} 移动驱动")
        sysm.motions[mid] = {"row": len(sysm.rows), "joint": mo["joint"], "dof": dof}
        sysm.rows.append(row)

    fids = set()
    for f in model.get("forces") or []:
        fid = f["id"]
        if fid in fids:
            raise ModelError(f"力元 id 重复：{fid}")
        fids.add(fid)
        try:
            if f["type"] == "force":
                b = body(f["body"], fid)
                sysm.forces.append(("force", {"id": fid, "body": b, "s": local(b, _v(f["point_mm"], fid) * MM),
                                              "frame": f.get("frame", "ground"),
                                              "fn": [fn_of(f.get(k, 0.0), 1.0) for k in ("fx_n", "fy_n", "fz_n")]}))
            elif f["type"] == "torque":
                b = body(f["body"], fid)
                sysm.forces.append(("torque", {"id": fid, "body": b, "frame": f.get("frame", "ground"),
                                               "fn": [fn_of(f.get(k, 0.0), 1.0) for k in ("tx_n_m", "ty_n_m", "tz_n_m")]}))
            else:
                i, j = body(f["body_i"], fid), body(f["body_j"], fid)
                Pi, Pj = _v(f["point_i_mm"], fid) * MM, _v(f["point_j_mm"], fid) * MM
                L0 = f["free_length_mm"] * MM if "free_length_mm" in f else float(np.linalg.norm(Pj - Pi))
                sysm.forces.append(("spring", {"id": fid, "i": i, "j": j, "s_i": local(i, Pi), "s_j": local(j, Pj), "L0": L0,
                                               "k": f["stiffness_n_per_mm"] / MM, "c": f.get("damping_n_s_per_mm", 0.0) / MM,
                                               "pre": float(f.get("preload_n", 0.0))}))
        except ExprError as exc:
            raise ModelError(f"力元 {fid} 的函数：{exc}") from exc
    sysm.requests = []
    for r in model.get("requests") or []:
        b = body(r["body"], r["id"])
        sysm.requests.append({"id": r["id"], "body": b, "s": local(b, _v(r["point_mm"], r["id"]) * MM)})
    sysm.model = model
    return sysm


def grubler(sysm: System) -> int:
    """空间自由度粗算（Grübler–Kutzbach）：6 × 构件数 − Σ 运动副约束数 − 驱动数"""
    return 6 * sysm.nb - sum(N_ROWS[j["type"]] for j in sysm.joints.values()) - len(sysm.motions)
