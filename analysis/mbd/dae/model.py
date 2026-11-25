"""模型（schema/mbd-model.schema.json，format = mbd-model/1）→ 内核 System（SI）。单位换算只在这里（ADR-0097 补充一）。"""

from __future__ import annotations

import math

import numpy as np

from analysis.mbd.dae.expr import ExprError, Spline
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


def build(model: dict, base_dir=None) -> System:
    """base_dir：模型文件所在目录（FMU 等相对路径按它找）"""
    from kb.validation import errors

    errs = errors("mbd-model.schema.json", model)
    if errs:
        raise ModelError("模型不符合 schema：" + "；".join(errs[:5]))
    from analysis.mbd.dae import nlbeam

    try:
        model, nl_elems, nl_info = nlbeam.expand(model)          # 大变形梁展开成节点构件（ADR-0101）
    except nlbeam.NlBeamError as exc:
        raise ModelError(str(exc)) from exc
    g = _v(model.get("gravity_mm_s2", [0, 0, 0]), "gravity_mm_s2") * MM
    bodies = []
    seen = set()
    for b in model["bodies"]:
        if b["id"] in seen:
            raise ModelError(f"构件 id 重复：{b['id']}")
        seen.add(b["id"])
        if "flex" in b:
            bodies.append(_flex_body(b))
            continue
        it = b["inertia_kg_m2"]
        J = np.array([[it["ixx"], it.get("ixy", 0.0), it.get("ixz", 0.0)],
                      [it.get("ixy", 0.0), it["iyy"], it.get("iyz", 0.0)],
                      [it.get("ixz", 0.0), it.get("iyz", 0.0), it["izz"]]], float)
        ev = np.linalg.eigvalsh(J)
        if ev.min() <= 0:
            raise ModelError(f"构件 {b['id']} 的惯性张量不是正定的（主惯量 {ev.round(9).tolist()}）")
        bodies.append(Body(b["id"], float(b["mass_kg"]), J, _v(b["cm_mm"], "cm_mm") * MM,
                           v0=_v(b.get("v0_mm_s", [0, 0, 0]), "v0_mm_s") * MM,
                           w0=_v(b.get("w0_deg_s", [0, 0, 0]), "w0_deg_s") * DEG,
                           v0_given="v0_mm_s" in b, w0_given="w0_deg_s" in b))
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

    splines = {}
    for sp in model.get("splines") or []:
        try:
            splines[sp["id"]] = Spline(sp["x"], sp["y"], sp.get("method", "cubic"))
        except ExprError as exc:
            raise ModelError(f"样条 {sp['id']}：{exc}") from exc
    mnames = [m["id"] for m in model.get("measures") or []]

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
        ni, nj = _node(bodies, i, P, jid), _node(bodies, j, P, jid)
        si, sj = local(i, P), local(j, P)
        if ni is not None:
            si = bodies[i].flex.x0[ni].copy()
        if nj is not None:
            sj = bodies[j].flex.x0[nj].copy()
        typ = jt["type"]
        start = len(sysm.rows)
        info = {"type": typ, "i": i, "j": j, "si": si, "sj": sj, "P": P, "node_i": ni, "node_j": nj}
        if (ni is not None or nj is not None) and (jt.get("clearance") or jt.get("friction")):
            raise ModelError(f"运动副 {jid}：挂在柔性构件上的运动副暂不支持间隙、摩擦（ADR-0097 补充十三）")

        def add(kind, label, i=i, j=j, jid=jid, ni=ni, nj=nj, **kw):
            sysm.rows.append(Row(kind, i, j, joint=jid, label=f"{jid} {label}", node_i=ni, node_j=nj, **kw))

        clear = jt.get("clearance")
        if clear is not None and typ != "revolute":
            raise ModelError(f"运动副 {jid}：间隙只能加在转动副上")
        if jt.get("friction") is not None and typ not in ("revolute", "translational"):
            raise ModelError(f"运动副 {jid}：摩擦只能加在转动副、移动副上")
        if clear is not None and jt.get("friction") is not None:
            raise ModelError(f"运动副 {jid}：间隙和摩擦不能同时加（间隙副的摩擦放在 D3 接触里）")
        if typ in ("spherical", "universal", "fixed") or (typ == "revolute" and clear is None):
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
            if typ == "revolute" and clear is not None:
                add("dot2", "h_i·d（间隙副只约束轴向）", a_i=h, s_i=si, s_j=sj)
                e = float(clear.get("exponent", 1.0))
                sysm.forces.append(("clearance", {"id": jid, "i": i, "j": j, "s_i": si, "s_j": sj, "h": h,
                                                  "c": clear["radial_mm"] * MM, "k": clear["stiffness_n_per_mm"] * (1 / MM) ** e,
                                                  "e": e, "cd": clear.get("damping_n_s_per_mm", 0.0) / MM,
                                                  "dpen": clear.get("penetration_mm", 0.01) * MM}))
                info["clearance"] = True
        if typ == "universal":
            ai, aj = _unit(jt["axis_i"], f"{jid}.axis_i"), _unit(jt["axis_j"], f"{jid}.axis_j")
            if abs(ai @ aj) > 1e-6:
                raise ModelError(f"万向副 {jid} 的两个十字轴要垂直")
            add("dot1", "a_i·a_j", a_i=ai, a_j=aj)
        info["rows"] = list(range(start, len(sysm.rows)))
        fr = jt.get("friction")
        if fr is not None:
            if fr["transition_speed"] <= fr["stiction_speed"]:
                raise ModelError(f"运动副 {jid}：摩擦的 transition_speed 要大于 stiction_speed")
            sc = DEG if typ == "revolute" else MM
            if typ == "revolute" and "pin_radius_mm" not in fr:
                raise ModelError(f"转动副 {jid} 的摩擦要写销半径 pin_radius_mm")
            info["friction"] = {"ms": fr["mu_static"], "md": fr["mu_dynamic"], "vs": fr["stiction_speed"] * sc,
                                "vt": fr["transition_speed"] * sc, "R": fr.get("pin_radius_mm", 0.0) * MM,
                                "pre": float(fr.get("preload_n", 0.0))}
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
                fn = fn_of(mo["function"], scale, (), splines)
                if abs(fn(0.0)) > 1e-9:
                    raise ModelError(f"驱动 {mid}：t = 0 时位移要是 0（相对装配位置），现在是 {fn.expr(0.0)}")
        except ExprError as exc:
            raise ModelError(f"驱动 {mid} 的函数：{exc}") from exc
        i, j = jinfo["i"], jinfo["j"]
        if dof == "rotation":
            row = Row("rdrive", i, j, a_i=jinfo["f"], a_j=jinfo["f"], b_i=jinfo["g"], fn=fn, joint=mo["joint"],
                      label=f"{mid} 转动驱动", node_i=jinfo["node_i"], node_j=jinfo["node_j"])
        else:
            row = Row("tdrive", i, j, a_i=jinfo["h"], s_i=jinfo["si"], s_j=jinfo["sj"], fn=fn, c=0.0, joint=mo["joint"],
                      label=f"{mid} 移动驱动", node_i=jinfo["node_i"], node_j=jinfo["node_j"])
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
                                              "fn": [fn_of(f.get(k, 0.0), 1.0, mnames, splines) for k in ("fx_n", "fy_n", "fz_n")]}))
            elif f["type"] == "torque":
                b = body(f["body"], fid)
                sysm.forces.append(("torque", {"id": fid, "body": b, "frame": f.get("frame", "ground"),
                                               "fn": [fn_of(f.get(k, 0.0), 1.0, mnames, splines) for k in ("tx_n_m", "ty_n_m", "tz_n_m")]}))
            elif f["type"] == "rotational_spring_damper":
                i, j = body(f["body_i"], fid), body(f["body_j"], fid)
                ff, gg, hh = frame_from_axis(_unit(f["axis"], fid))
                sysm.forces.append(("rspring", {"id": fid, "i": i, "j": j, "f": ff, "g": gg, "h": hh,
                                                "k": f["stiffness_n_m_per_deg"] / DEG, "c": f.get("damping_n_m_s_per_deg", 0.0) / DEG,
                                                "a0": f.get("free_angle_deg", 0.0) * DEG, "pre": float(f.get("preload_n_m", 0.0))}))
            elif f["type"] == "bushing":
                i, j = body(f["body_i"], fid), body(f["body_j"], fid)
                P = _v(f["point_mm"], fid) * MM

                def arr(key, scale, f=f):
                    return np.asarray(f.get(key, [0, 0, 0]), float) * scale

                sysm.forces.append(("bushing", {"id": fid, "i": i, "j": j, "s_i": local(i, P), "s_j": local(j, P),
                                                "d0": np.zeros(3), "K": arr("stiffness_n_per_mm", 1 / MM),
                                                "C": arr("damping_n_s_per_mm", 1 / MM), "Kr": arr("rot_stiffness_n_m_per_deg", 1 / DEG),
                                                "Cr": arr("rot_damping_n_m_s_per_deg", 1 / DEG), "F0": arr("preload_n", 1.0),
                                                "T0": arr("preload_n_m", 1.0)}))
            elif f["type"] == "actuator":
                if f["joint"] not in sysm.joints:
                    raise ModelError(f"执行器 {fid}：没有运动副 {f['joint']}")
                jt = sysm.joints[f["joint"]]["type"]
                dof = f.get("dof") or {"revolute": "rotation", "translational": "translation"}.get(jt)
                if jt not in ("revolute", "translational", "cylindrical") or dof is None:
                    raise ModelError(f"执行器 {fid}：{jt} 副上不能加执行器（圆柱副要写 dof）")
                if (jt == "revolute" and dof != "rotation") or (jt == "translational" and dof != "translation"):
                    raise ModelError(f"执行器 {fid}：{jt} 副只能是 {'rotation' if jt == 'revolute' else 'translation'}")
                sysm.forces.append(("actuator", {"id": fid, "joint": f["joint"], "dof": dof}))
            elif f["type"] == "gear_mesh":
                sysm.forces.append(("gear", _gear(f, sysm)))
            elif f["type"] == "beam":
                sysm.forces.append(("beam", _beam(f, body(f["body_i"], fid), body(f["body_j"], fid), local)))
            else:
                i, j = body(f["body_i"], fid), body(f["body_j"], fid)
                Pi, Pj = _v(f["point_i_mm"], fid) * MM, _v(f["point_j_mm"], fid) * MM
                L0 = f["free_length_mm"] * MM if "free_length_mm" in f else float(np.linalg.norm(Pj - Pi))
                sysm.forces.append(("spring", {"id": fid, "i": i, "j": j, "s_i": local(i, Pi), "s_j": local(j, Pj), "L0": L0,
                                               "k": f["stiffness_n_per_mm"] / MM, "c": f.get("damping_n_s_per_mm", 0.0) / MM,
                                               "pre": float(f.get("preload_n", 0.0))}))
        except ExprError as exc:
            raise ModelError(f"力元 {fid} 的函数：{exc}") from exc
    _contacts(model, sysm, body, local)
    sysm.measure_defs = []
    for mdef in model.get("measures") or []:
        if mdef["type"].startswith("joint_"):
            if mdef["joint"] not in sysm.joints:
                raise ModelError(f"测量量 {mdef['id']}：没有运动副 {mdef['joint']}")
            jt = sysm.joints[mdef["joint"]]["type"]
            if jt not in ("revolute", "translational", "cylindrical"):
                raise ModelError(f"测量量 {mdef['id']}：{jt} 副没有转角 / 位移")
            sysm.measure_defs.append(dict(mdef))
        else:
            i, j = body(mdef["body_i"], mdef["id"]), body(mdef["body_j"], mdef["id"])
            sysm.measure_defs.append({"id": mdef["id"], "type": mdef["type"], "i": i, "j": j,
                                      "s_i": local(i, _v(mdef["point_i_mm"], mdef["id"]) * MM),
                                      "s_j": local(j, _v(mdef["point_j_mm"], mdef["id"]) * MM)})
    sysm.needs_env = any(fn.expr.uses_vars for kind, f in sysm.forces if kind in ("force", "torque") for fn in f["fn"])
    sysm.requests = []
    for r in model.get("requests") or []:
        b = body(r["body"], r["id"])
        P = _v(r["point_mm"], r["id"]) * MM
        node = None
        if b >= 0 and bodies[b].flex is not None:       # 柔性构件上的点：落在节点上就带弹性变形输出
            d = np.linalg.norm(bodies[b].flex.nodes_world0 - P, axis=1)
            node = int(np.argmin(d)) if d.min() <= FLEX_SNAP_MM * MM else None
            if node is None:
                raise ModelError(f"输出点 {r['id']} 不在柔性构件 {bodies[b].name} 的节点上")
        sysm.requests.append({"id": r["id"], "body": b, "s": local(b, P) if node is None else bodies[b].flex.x0[node],
                              "node": node})
    _check_flex_use(sysm)
    from analysis.mbd.dae.control import ControlError, Controllers
    try:
        sysm.ctrl = Controllers(model.get("controllers") or [], {m["id"] for m in sysm.measure_defs},
                                {f["id"] for kind, f in sysm.forces if kind == "actuator"}, base_dir)
    except ControlError as exc:
        raise ModelError(str(exc)) from exc
    sysm.act = {}
    sysm.model = model
    for e in nl_elems:
        sysm.forces.append(("nlbeam", {**e, "id": f"{e['beam']}.e{e['k']}", "i": idx[e["i_name"]], "j": idx[e["j_name"]]}))
    sysm.nlbeams = nl_info
    return sysm


def _check_flex_use(sysm):
    """D6a：力元、接触、测量量不能挂在柔性构件上（会按刚体算错，所以报错而不是悄悄近似）"""
    flex = {k for k, b in enumerate(sysm.bodies) if b.flex is not None}
    if not flex:
        return
    name = {k: sysm.bodies[k].name for k in flex}
    for kind, f in sysm.forces:
        used = {f.get(x) for x in ("body", "i", "j")}
        if kind == "contact":
            used |= {f["ga"].body, f["gb"].body}
        if kind == "gear":
            used |= {sysm.joints[f["joint_i"]]["j"], sysm.joints[f["joint_j"]]["j"]}
        bad = used & flex
        if bad:
            raise ModelError(f"{kind} {f.get('id', '')} 挂在柔性构件 {name[bad.pop()]} 上：D6a 还不支持，"
                             "请挂在与它相连的刚体上（ADR-0097 补充十三）")
    for m in getattr(sysm, "measure_defs", []):
        js = sysm.joints.get(m.get("joint"), {})
        if {m.get("i"), m.get("j"), js.get("i"), js.get("j")} & flex:
            raise ModelError(f"测量量 {m['id']} 涉及柔性构件：D6a 还不支持（ADR-0097 补充十三）")


def _beam(f, i, j, local):
    """直梁的 6×6 刚度（梁坐标系：x 沿梁，y、z 截面主轴；j 端相对 i 端），欧拉–伯努利 + 可选剪切变形（Timoshenko 修正）"""
    Pi, Pj = _v(f["point_i_mm"], f["id"]) * MM, _v(f["point_j_mm"], f["id"]) * MM
    ax = Pj - Pi
    L = float(np.linalg.norm(ax))
    if L <= 0:
        raise ModelError(f"梁 {f['id']} 两端重合")
    x = ax / L
    y = _v(f["y_axis"], f["id"])
    y = y - (y @ x) * x
    if np.linalg.norm(y) < 1e-9:
        raise ModelError(f"梁 {f['id']} 的 y_axis 不能与梁轴平行")
    y /= np.linalg.norm(y)
    z = np.cross(x, y)
    E, G = f["youngs_modulus_mpa"] * 1e6, f["shear_modulus_mpa"] * 1e6
    A, Iy, Iz, J = f["area_mm2"] * 1e-6, f["iyy_mm4"] * 1e-12, f["izz_mm4"] * 1e-12, f["ixx_mm4"] * 1e-12
    py = 12 * E * Iz / (G * A * f["shear_area_ratio_y"] * L * L) if "shear_area_ratio_y" in f else 0.0
    pz = 12 * E * Iy / (G * A * f["shear_area_ratio_z"] * L * L) if "shear_area_ratio_z" in f else 0.0
    K = np.zeros((6, 6))
    K[0, 0] = E * A / L
    K[3, 3] = G * J / L
    K[1, 1] = 12 * E * Iz / (L ** 3 * (1 + py))
    K[1, 5] = K[5, 1] = -6 * E * Iz / (L ** 2 * (1 + py))
    K[5, 5] = (4 + py) * E * Iz / (L * (1 + py))
    K[2, 2] = 12 * E * Iy / (L ** 3 * (1 + pz))
    K[2, 4] = K[4, 2] = 6 * E * Iy / (L ** 2 * (1 + pz))
    K[4, 4] = (4 + pz) * E * Iy / (L * (1 + pz))
    return {"id": f["id"], "i": i, "j": j, "s_i": local(i, Pi), "s_j": local(j, Pj), "d0": Pj - Pi,
            "Bm": np.column_stack([x, y, z]), "K6": K, "cr": float(f.get("damping_ratio", 0.0))}


def _gear(f, sysm):
    fid = f["id"]
    for k in ("joint_i", "joint_j"):
        if f[k] not in sysm.joints or sysm.joints[f[k]]["type"] != "revolute":
            raise ModelError(f"齿轮啮合 {fid}：{f[k]} 要是转动副")
    j1, j2 = sysm.joints[f["joint_i"]], sysm.joints[f["joint_j"]]
    if j1["i"] != j2["i"]:
        raise ModelError(f"齿轮啮合 {fid}：两个转动副要装在同一个支承构件上（body_i 相同）")
    if j1["j"] < 0 or j2["j"] < 0 or j1["j"] == j2["j"]:
        raise ModelError(f"齿轮啮合 {fid}：两个齿轮要是不同的运动构件（body_j）")
    s = float(j1["h"] @ j2["h"])
    if abs(abs(s) - 1) > 1e-6:
        raise ModelError(f"齿轮啮合 {fid}：两轴要平行")
    m, z1, z2 = f["module_mm"] * MM, int(f["teeth_i"]), int(f["teeth_j"])
    alpha = f.get("pressure_angle_deg", 20.0) * DEG
    d = j2["P"] - j1["P"]
    d = d - (d @ j1["h"]) * j1["h"]
    a_geo, a_nom = float(np.linalg.norm(d)), m * (z1 + z2) / 2
    if abs(a_geo - a_nom) > 1e-3 * a_nom:
        raise ModelError(f"齿轮啮合 {fid}：中心距 {a_geo / MM:.4g} mm 与 m(z1+z2)/2 = {a_nom / MM:.4g} mm 不符")
    return {"id": fid, "joint_i": f["joint_i"], "joint_j": f["joint_j"], "s": math.copysign(1.0, s), "alpha": alpha,
            "rp1": m * z1 / 2, "rb1": m * z1 * math.cos(alpha) / 2, "rb2": m * z2 * math.cos(alpha) / 2,
            "pb": math.pi * m * math.cos(alpha), "k": f["mesh_stiffness_n_per_mm"] / MM,
            "c": f.get("damping_n_s_per_mm", 0.0) / MM, "b": f.get("backlash_mm", 0.0) * MM}


def _contacts(model, sysm, body, local):
    from analysis.mbd.dae import contact as C
    geos = {}
    for g in model.get("geometries") or []:
        gid = g["id"]
        if gid in geos:
            raise ModelError(f"接触几何 id 重复：{gid}")
        b = body(g["body"], gid)

        def L(key, g=g, b=b, gid=gid):
            return local(b, _v(g[key], f"{gid}.{key}") * MM)

        try:
            t = g["type"]
            if t == "sphere":
                geos[gid] = C.Sphere(gid, b, L("center_mm"), g["radius_mm"] * MM)
            elif t == "plane":
                half = None if "half_size_mm" not in g else np.asarray(g["half_size_mm"], float) * MM
                geos[gid] = C.Plane(gid, b, L("point_mm"), g["normal"], g.get("x_axis"), half)
            elif t == "cylinder":
                geos[gid] = C.Cylinder(gid, b, L("center_mm"), g["axis"], g["radius_mm"] * MM, g["length_mm"] * MM)
            elif t == "curve":
                geos[gid] = C.Curve(gid, b, L("origin_mm"), g["normal"], g["x_axis"], np.asarray(g["points_mm"], float) * MM,
                                    g.get("closed", True), g.get("method", "cubic"))
            else:
                v = np.asarray(g["vertices_mm"], float) * MM
                v = v if b < 0 else v - sysm.bodies[b].r0
                geos[gid] = C.Mesh(gid, b, v, g["faces"])
        except C.ContactError as exc:
            raise ModelError(str(exc)) from exc
    ids = set()
    for c in model.get("contacts") or []:
        cid = c["id"]
        if cid in ids:
            raise ModelError(f"接触对 id 重复：{cid}")
        ids.add(cid)
        for k in ("geometry_i", "geometry_j"):
            if c[k] not in geos:
                raise ModelError(f"接触对 {cid}：没有接触几何 {c[k]}")
        ga, gb = geos[c["geometry_i"]], geos[c["geometry_j"]]
        if ga.body == gb.body:
            raise ModelError(f"接触对 {cid}：两个几何在同一个构件上")
        try:
            fn, swap = C.pair_function(ga.kind, gb.kind)
        except C.ContactError as exc:
            raise ModelError(f"接触对 {cid}：{exc}") from exc
        e = float(c.get("exponent", 1.5))
        f = {"id": cid, "ga": ga, "gb": gb, "fn": fn, "swap": swap, "k": c["stiffness_n_per_mm"] * (1 / MM) ** e, "e": e,
             "c": c.get("damping_n_s_per_mm", 0.0) / MM, "d": c.get("penetration_mm", 0.01) * MM}
        if "restitution" in c:                                  # ADR-0130：按恢复系数算阻尼（线索第 31 条）
            if not 0 < c["restitution"] <= 1:
                raise ModelError(f"接触对 {cid}：restitution 要在 (0, 1] 之间")
            f["rest"] = float(c["restitution"])
            f["vmin"] = float(c.get("min_impact_speed_mm_s", 1.0)) * MM
        fr = c.get("friction")
        if fr:
            if fr["transition_speed_mm_s"] <= fr["stiction_speed_mm_s"]:
                raise ModelError(f"接触对 {cid}：摩擦的 transition_speed 要大于 stiction_speed")
            f["friction"] = {"ms": fr["mu_static"], "md": fr["mu_dynamic"], "vs": fr["stiction_speed_mm_s"] * MM,
                             "vt": fr["transition_speed_mm_s"] * MM}
        sysm.forces.append(("contact", f))


FLEX_SNAP_MM = 1e-6


def _flex_body(b):
    """bodies[].flex → 柔性 Body（质量、质心、惯量由节点算；ADR-0097 补充十三）"""
    from analysis.mbd.dae import flex as FX

    f = b["flex"]
    try:
        if f["type"] == "beam":
            P0, P1 = _v(f["from_mm"], "from_mm") * MM, _v(f["to_mm"], "to_mm") * MM
            X, K, Mm, m, Jn = FX.beam_fe(P0, P1, _v(f["y_axis"], "y_axis"), f["youngs_modulus_mpa"] * 1e6,
                                         f["shear_modulus_mpa"] * 1e6, f["density_kg_m3"], f["area_mm2"] * 1e-6,
                                         f["iyy_mm4"] * 1e-12, f["izz_mm4"] * 1e-12, f["ixx_mm4"] * 1e-12,
                                         int(f.get("elements", 20)))
            N = len(X)
            bnd = list(range(6)) + list(range(6 * (N - 1), 6 * N))
            shapes, w = FX.craig_bampton(K, Mm, bnd, int(f.get("fixed_interface_modes", 4)), f.get("keep_modes"))
            iface = [0, N - 1]
        else:
            X = np.asarray(f["nodes_mm"], float) * MM
            N = len(X)
            m = np.asarray(f["node_mass_kg"], float)
            if len(m) != N:
                raise FX.FlexError("node_mass_kg 的个数与节点数不同")
            Jn = np.zeros((N, 3, 3))
            if "node_inertia_kg_m2" in f:
                Jn = np.array([np.diag(x) for x in f["node_inertia_kg_m2"]], float)
            sh = np.asarray(f["shapes"], float)              # nm × N × 6
            if sh.shape[1] != N:
                raise FX.FlexError("模态振型的节点数与 nodes_mm 不同")
            sh[:, :, :3] *= MM
            shapes = sh.reshape(sh.shape[0], 6 * N).T
            w = np.asarray(f["frequencies_hz"], float) * 2 * math.pi
            if len(w) != sh.shape[0]:
                raise FX.FlexError("frequencies_hz 的个数与模态数不同")
            iface = list(f["interface_nodes"])
        cm = (m @ X) / m.sum()
        fx = FX.from_full(X, m, Jn, shapes, w, cm, float(f.get("damping_ratio", 0.0)), iface)
        if f.get("stress_shapes_mpa"):                       # D6b：应力振型，用于应力回放
            fx.stress_nodes = np.asarray(f["stress_nodes"], int)
            fx.stress_shapes = np.asarray(f["stress_shapes_mpa"], float)
            if fx.stress_shapes.shape != (fx.nm, len(fx.stress_nodes), 6):
                raise FX.FlexError("stress_shapes_mpa 的形状与模态数、stress_nodes 对不上")
    except FX.FlexError as exc:
        raise ModelError(f"柔性构件 {b['id']}：{exc}") from exc
    J = fx.mass_v(np.zeros(fx.nm))[1]
    return Body(b["id"], fx.mass, J, cm, v0=_v(b.get("v0_mm_s", [0, 0, 0]), "v0_mm_s") * MM,
                w0=_v(b.get("w0_deg_s", [0, 0, 0]), "w0_deg_s") * DEG, flex=fx,
                v0_given="v0_mm_s" in b, w0_given="w0_deg_s" in b)


def _node(bodies, b, P, where):
    """柔性构件上与点 P 重合的界面节点；刚体返回 None"""
    if b < 0 or bodies[b].flex is None:
        return None
    fx = bodies[b].flex
    for n in fx.interface:
        if np.linalg.norm(fx.nodes_world0[n] - P) <= FLEX_SNAP_MM * MM:
            return n
    raise ModelError(f"{where}：点 {np.round(P / MM, 6).tolist()} mm 不在柔性构件 {bodies[b].name} 的界面节点上"
                     f"（界面节点：{[np.round(fx.nodes_world0[n] / MM, 6).tolist() for n in fx.interface]}）")


def grubler(sysm: System) -> int:
    """空间自由度粗算（Grübler–Kutzbach）：6 × 构件数 + 模态数 − Σ 运动副约束数 − 驱动数"""
    return 6 * sysm.nb + sum(b.flex.nm for b in sysm.bodies if b.flex is not None) - sum(N_ROWS[j["type"]] for j in sysm.joints.values()) - len(sysm.motions)
