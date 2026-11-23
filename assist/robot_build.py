"""整机：构型 → 载荷 → 选件（ADR-0115 第 44.3 步之一）。不调用 AI，全部是确定性计算与引擎选型。

输入：构型循环采用的整机方案（robot-concept/1，assist/robot_design.py 的结果）与需求里的末端负载。
做什么：
  1 质量：杆件质量按截面 × 长度 × 密度（analysis/robot/mjcf.py），关节模组质量取所选零件的样本质量（第一轮为 0）。
  2 检验动作（需求没给速度时的设计取值，写进报告的“假设”）：从“水平伸直”姿态（第一个水平轴关节的高度上末端伸得最远）出发，
    各转动关节同时转 90°（行程内往能转的一侧），默认用时 1.0 s（最高 120°/s，--move-s 可改）、加减速各占 25%；末端带满载。
  3 多体动力学（analysis.mbd，MuJoCo）→ 每个关节的连续（均方根）/ 峰值力矩、最高转速、最大负载惯量。
  4 选件：同一模组组（module_group）的关节取组内各项的最大值作为一个需求，在两条链里各选一个（ADR-0117）：
    工业伺服三件套——引擎选型（engine.compose），在没有“不通过”、电机与减速器都有样本质量的组合里取电机 + 减速器最轻的，
    同样轻时优先方案里写的减速比；一体化关节模组——engine.smart_actuator 逐个校验，取没有“不通过”里最轻的。
    两条链取装在臂上的质量轻的（伺服链的驱动器不在臂上，不计），另一条并列在报告里。
  5 模组质量回代到第 1 步，重复到选型不再变（最多 MAX_ROUNDS 轮）。
  6 重复定位精度：位置测量分辨率一项，在水平伸直姿态上逐关节最坏相加，与需求比（repeatability()）。
  8 装不装得下：关节转角与 U 形支架、共线轴转、关节距（analysis/robot/fit.py）。
  7 杆件：强度（对屈服与弯曲疲劳的安全系数，安全系数要求同选件）与末端下垂（只计杆件），analysis/robot/links.py。
成本：零件库没有价格数据，“外购件成本尽量低”判不了，结论记待确认并写明缺什么。
"""

from __future__ import annotations

import copy
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MAX_ROUNDS = 5
MOVE_DEG, MOVE_S, ACCEL, T0 = 90.0, 1.0, 0.25, 0.2
BASE_REQ = {"safety_factor": 1.2, "supply": {"current_type": "ac", "voltage_v": 200, "phases": 3},
            "fieldbus_protocol": "ethercat", "ambient_temp_c": 25}
def move_s_for(speed_rpm: float) -> float:
    """关节最高角速度（rpm）→ 检验动作转 MOVE_DEG 的用时：梯形速度（加减速各占 ACCEL），最高速度 = MOVE_DEG / (用时 × (1 − ACCEL))"""
    return MOVE_DEG / (speed_rpm * 6.0 * (1 - ACCEL))


def duty_text(move_s: float) -> str:
    return (f"检验动作（需求没给速度，设计取值）：从水平伸直姿态出发，各转动关节同时转 {MOVE_DEG:g}°，用时 {move_s:g} s，"
            f"加减速各占 {ACCEL:.0%}（最高 {MOVE_DEG / move_s / (1 - ACCEL):.0f}°/s）；末端带满载")


ASSUMPTIONS = [
    "供电按 200 V 三相交流、EtherCAT（零件库里的伺服与驱动器是这一类）；安全系数 1.2；环境 25 ℃",
    "关节模组（电机 + 减速器）按样本质量集中在关节处；电缆、壳体、轴承座、夹爪本身的质量不计（夹爪质量方案里没有）",
    "杆件质量按方案的截面、长度与材料密度，均布在本关节到下一关节之间",
]


class BuildError(ValueError):
    pass


def _library():
    from kb.library import JsonLibrary

    return JsonLibrary(ROOT / "data" / "library")


def _pv(comp: Mapping | None, k: str):
    v = ((comp or {}).get("params") or {}).get(k)
    return v.get("value") if isinstance(v, dict) else None


def _comp(lib, system: Mapping, kind: str):
    for c in system["components"]:
        if c["instance"] == kind:
            return lib.get(c["component"])
    return None


def module_mass(lib, system: Mapping) -> float | None:
    """电机 + 减速器的样本质量（kg）；缺任何一项返回 None（不估）"""
    m = [_pv(_comp(lib, system, i), "mass_kg") for i in ("motor", "reducer")]
    return None if any(x is None for x in m) else float(sum(m))


def stretched_pose(concept: Mapping) -> tuple[dict, list[float]]:
    """水平伸直姿态：第一个轴线水平的转动关节的高度上，末端沿 +x 伸得最远的逆解（二分，精度 1 mm）"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    T = K.fk(m)
    z = None
    for j in K.chain(m):
        a = T[j.parent][:3, :3] @ j.axis
        if j.type != "prismatic" and abs(a[2]) < 1e-6:
            z = float((T[j.parent] @ np.append(j.origin, 1.0))[2])
            break
    if z is None:
        raise BuildError("构型里没有水平轴的转动关节：水平伸直姿态不适用，检验动作要另定")
    lo, hi, best = 0.0, 5000.0, None
    while hi - lo > 1.0:
        x = (lo + hi) / 2
        q, _ = K.ik(m, [x, 0.0, z])
        if q is None:
            hi = x
        else:
            lo, best = x, (q, [x, 0.0, z])
    if best is None:
        raise BuildError("找不到水平伸直姿态")
    return best


def duty(concept: Mapping, move_s: float = MOVE_S) -> dict:
    """检验动作：{"initial", "drives", "pose_mm"}（analysis.mbd 的设置写法）"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    q0, p = stretched_pose(concept)
    drives = []
    for j in K.chain(m):
        if j.type == "prismatic":
            drives.append({"joint": j.id, "kind": "hold"})
            continue
        v = q0[j.id]
        to = v + MOVE_DEG if j.hi is None or v + MOVE_DEG <= j.hi else v - MOVE_DEG
        if j.lo is not None:
            to = max(to, j.lo)
        drives.append({"joint": j.id, "kind": "move", "to": round(to, 4), "t0_s": T0, "t1_s": T0 + move_s,
                       "accel_ratio": ACCEL})
    return {"initial": {k: round(v, 4) for k, v in q0.items()}, "drives": drives, "pose_mm": p, "move_s": move_s}


def dynamics(concept: Mapping, payload_kg: float, mods: Mapping[str, float], dt: Mapping) -> dict:
    import analysis
    from analysis.robot import mjcf

    xml = mjcf.mjcf(concept, module_masses_kg=mods, payload_kg=payload_kg)
    r = analysis.run("mbd", {"model": {"kind": "mjcf", "xml": xml}, "duration_s": T0 + dt["move_s"] + 0.2, "sample_hz": 200,
                             "initial": dt["initial"], "drives": dt["drives"]})
    if r.get("status") != "ok":
        raise BuildError(f"多体动力学没算成：{r.get('error')}")
    return r


def groups(concept: Mapping) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for j in concept["joints"]:
        out.setdefault(j.get("module_group") or j["id"], []).append(j["id"])
    return out


def group_requirement(res: Mapping, joints: list[str], base: Mapping) -> dict:
    """组内各关节需求逐项取最大"""
    from analysis import mbd

    reqs = [mbd.requirement(res, j, base=base) for j in joints]
    out = dict(reqs[0])
    for k in ("output_torque_cont_nm", "output_torque_peak_nm", "output_speed_rpm", "load_inertia_kgm2"):
        out[k] = max(r[k] for r in reqs)
    by = {k: max(joints, key=lambda j, k=k: reqs[joints.index(j)][k]) for k in
          ("output_torque_cont_nm", "output_torque_peak_nm", "output_speed_rpm")}
    out["statement"] = (f"关节 {'、'.join(joints)} 共用一种模组：连续 {out['output_torque_cont_nm']:.2f} N·m（{by['output_torque_cont_nm']}）、"
                        f"峰值 {out['output_torque_peak_nm']:.2f} N·m（{by['output_torque_peak_nm']}）、"
                        f"{out['output_speed_rpm']:.1f} rpm（{by['output_speed_rpm']}）")
    return out


def pick(lib, req: Mapping, ratio: float | None):
    """引擎选型；在不“不通过”且有样本质量的组合里取电机 + 减速器最轻的，同样轻时优先方案的减速比。返回 (组合, 候选数)"""
    from engine.compose import compose_chain

    cands = compose_chain(dict(req), list(lib.all()), top_n=40, include_unknown=True)
    ok = [c for c in cands if c.report["overall"] != "fail" and module_mass(lib, c.system) is not None]
    if not ok:
        return None, len(cands)

    def key(c):
        r = _pv(_comp(lib, c.system, "reducer"), "ratio")
        return (round(module_mass(lib, c.system), 6), 0 if ratio and r == ratio else 1)

    return min(ok, key=key), len(cands)


def operating_points(res: Mapping, joints: list[str]) -> list[tuple[float, float]]:
    """组内各关节动作过程中同一时刻的 (驱动力矩 N·m, 转速 rpm)"""
    s = res["data"].get("series") or {}
    return [(abs(t), abs(w)) for j in joints if j in s for t, w in zip(s[j]["drive"], s[j]["speed"], strict=True)]


def pick_smart(lib, req: Mapping, points=None):
    """一体化关节模组：没有“不通过”、且有机械接口数据（舵盘孔位、安装孔、外形）的里面最轻的——
    没有接口数据的装不装得下判不了，不选（ADR-0115 44.3 之二）。返回 (校验结果或 None, 候选数)"""
    from analysis.robot import fit
    from engine import smart_actuator

    with_iface = [c for c in lib.all() if c.get("category") == "smart_actuator" and fit.housing_geometry(c) is not None]
    cands = smart_actuator.candidates(req, with_iface, top=40, points=points)
    ok = [c for c in cands if c["mass_kg"] is not None]
    return (ok[0] if ok else None), len(cands)


def smart_shortfall(lib, req: Mapping, points=None) -> str:
    """一体化模组一个都不行时，说清楚卡在哪：堵转力矩最大的那个没通过的项"""
    from analysis.robot import fit
    from engine import smart_actuator
    from engine.values import nominal

    comps = [c for c in lib.all() if c.get("category") == "smart_actuator" and fit.housing_geometry(c) is not None]
    if not comps:
        return "库里没有带机械接口数据的一体化关节模组"
    top = max(comps, key=lambda c: nominal((c.get("params") or {}).get("stall_torque_nm")) or 0.0)
    r = smart_actuator.check(req, top, points)
    bad = [f"{x['check']} {x.get('message', '')}" for x in r["checks"] if x["status"] == "fail"]
    return f"库里有接口数据的 {len(comps)} 个一体化模组都不通过；力矩最大的 {top['model']}：" + "；".join(bad)


def choose(lib, req: Mapping, ratio: float | None, points=None) -> dict:
    """一个模组组在两条链里的结果，与选中的那条"""
    best, n = pick(lib, req, ratio)
    smart, ns = pick_smart(lib, req, points)
    options = {}
    if best:
        options["servo"] = {"chain": "servo", "components": [c["component"] for c in best.system["components"]],
                            "roles": {c["component"]: c["instance"] for c in best.system["components"]},
                            "report": best.report, "overall": best.report["overall"],
                            "module_mass_kg": module_mass(lib, best.system), "candidates": n}
    if smart:
        options["smart"] = {"chain": "smart", "components": [smart["component"]],
                            "roles": {smart["component"]: "actuator"}, "report": smart, "overall": smart["overall"],
                            "module_mass_kg": smart["mass_kg"], "candidates": ns}
    shortfall = None if smart else smart_shortfall(lib, req, points)
    if not options:
        return {"chain": None, "components": None, "module_mass_kg": None, "options": {}, "smart_shortfall": shortfall}
    k = min(options, key=lambda c: (options[c]["module_mass_kg"], c))
    return dict(options[k], options={c: {x: v for x, v in o.items() if x != "report"} for c, o in options.items()},
                smart_shortfall=shortfall)


def build(concept: Mapping, payload_kg: float, *, base: Mapping | None = None, move_s: float = MOVE_S,
          repeatability_mm: float | None = None, points_mm=None) -> dict:
    lib = _library()
    base = dict(base or BASE_REQ)
    dt = duty(concept, move_s)
    gs = groups(concept)
    ratio = {g: next((j.get("ratio") for j in concept["joints"] if j["id"] == js[0]), None) for g, js in gs.items()}
    mods: dict[str, float] = {}
    rounds = []
    for k in range(1, MAX_ROUNDS + 1):
        res = dynamics(concept, payload_kg, mods, dt)
        picks = {}
        for g, js in gs.items():
            req = group_requirement(res, js, base)
            req["id"] = f"group-{g}"
            picks[g] = dict(choose(lib, req, ratio[g], operating_points(res, js)), joints=js, requirement=req)
        rounds.append({"module_masses_kg": dict(mods), "drives": res["data"]["drives"],
                       "static": res["data"].get("static"),
                       "picks": {g: p["components"] for g, p in picks.items()}})
        if any(p["components"] is None for p in picks.values()):
            return {"status": "fail", "rounds": rounds, "picks": picks, "duty": dt,
                    "note": "有模组组两条链都选不出带质量数据的零件：" + "、".join(g for g, p in picks.items() if p["components"] is None)}
        new = {j: picks[g]["module_mass_kg"] for g, js in gs.items() for j in js}
        if new == mods:
            break
        mods = new
    else:
        return {"status": "fail", "rounds": rounds, "picks": picks, "duty": dt,
                "note": f"{MAX_ROUNDS} 轮后选型仍在变"}
    open_items = [f"模组组 {g}（{p['chain']}）：{c['check']} {c.get('message', '')}" for g, p in picks.items()
                  for c in p["report"]["checks"] if c["status"] == "unknown"]
    return {"status": "pass", "rounds": rounds, "picks": picks, "duty": dt, "result": res,
            "module_masses_kg": mods, "link_masses_kg": _link_masses(concept), "assumptions": [duty_text(move_s), *ASSUMPTIONS],
            "open_items": open_items, "bom": bom(lib, concept, picks),
            "repeatability": repeatability(lib, concept, dt, picks, repeatability_mm, points_mm),
            "links": link_check(concept, dt, res, mods, payload_kg, float(base.get("safety_factor") or 1.0)),
            "fit": fit_check(lib, concept, picks),
            "cost": {"status": "unknown", "note": "零件库没有价格数据；“外购件成本尽量低”要等登记了有价格的公开目录才判得了"}}


def repeatability(lib, concept: Mapping, dt: Mapping, picks: Mapping, target_mm: float | None,
                  points_mm=None) -> dict:
    """末端重复定位精度（只算位置测量的分辨率这一项，最坏情况线性相加）：
    每个转动关节的角度不确定 ±½ 个计数 = ±π / 每转计数（rad），乘以该关节轴线到工具点的距离，逐关节相加。
    在哪里算：需求要够得着的点（臂展点与方案的工作空间点，取逆解得到的姿态）里最坏的；没有这些点时用水平伸直姿态（力臂最大，偏保守）。
    一体化模组：规格表的分辨率是输出端每转计数（位置控制 0–360°），直接用；回差另报（同方向趋近时不计，反向时最坏会多出这么多）。
    伺服链：编码器在电机端，每转计数 = 2^位数 × 减速比；库里没有编码器位数 → 待确认；减速器的空回也不在这里算。
    """
    from analysis.robot import kinematics as K

    m = K.build(concept)
    poses = []
    for p in points_mm or []:
        q, _ = K.ik(m, p)
        if q is not None:
            poses.append((f"需求点 {tuple(round(float(x), 1) for x in p)}", q))
    if not poses:
        poses = [("水平伸直（力臂最大）", dt["initial"])]
    out = max((dict(_resolution_error(lib, m, q, picks), pose=name) for name, q in poses), key=lambda r: r["worst_mm"])
    missing = out.pop("missing")
    out["target_mm"] = target_mm
    if missing or target_mm is None:
        out["status"] = "unknown"
        out["note"] = "缺数据：" + "、".join(missing) if missing else "需求没给重复定位精度"
    else:
        total, lost = out["worst_mm"], out["backlash_lost_motion_mm"]
        out["status"] = "pass" if total <= target_mm + 1e-9 else "fail"
        out["note"] = (f"{out['pose']}：分辨率一项最坏 ±{total:.2f} mm，要求 ±{target_mm:g} mm"
                       + (f"；反向趋近时回差最坏再多 {lost:.1f} mm" if lost else ""))
    return out


def _resolution_error(lib, m, q: Mapping, picks: Mapping) -> dict:
    """一个姿态下各关节分辨率误差（mm）与回差空回"""
    from analysis.robot import kinematics as K

    T = K.fk(m, q)
    tip = K.tool_point(m, q)
    group_of = {j: g for g, pk in picks.items() for j in pk["joints"]}
    rows, total, lost, missing = [], 0.0, 0.0, []
    for j in K.chain(m):
        if j.type == "prismatic":
            missing.append(f"{j.id}（移动关节）")
            continue
        o = (T[j.parent] @ np.append(j.origin, 1.0))[:3]
        a = T[j.parent][:3, :3] @ j.axis
        lever = float(np.linalg.norm(np.cross(a, tip - o)))
        pk = picks[group_of[j.id]]
        counts = backlash = None
        if pk["chain"] == "smart":
            comp = lib.get(pk["components"][0])
            counts = _pv(comp, "resolution_counts_per_rev")
            backlash = _pv(comp, "backlash_arcmin")
        if not counts:
            missing.append(f"{j.id}（{'伺服链：库里没有编码器位数' if pk['chain'] == 'servo' else '模组没给分辨率'}）")
            continue
        e = math.pi / counts * lever
        total += e
        if backlash:
            lost += math.radians(backlash / 60) * lever
        rows.append({"joint": j.id, "lever_mm": round(lever, 1), "counts_per_rev": counts, "error_mm": round(e, 3)})
    return {"rows": rows, "worst_mm": round(total, 3), "missing": missing,
            "backlash_lost_motion_mm": round(lost, 2) if lost else None}


def build_check(concept: Mapping, cond: Mapping) -> dict:
    """构型循环用（assist/robot_design.design 的 after_screen）：按条件选件并校核装配、杆件、精度。
    返回 {"ok", "items"（没通过的项，给 AI 看）, "summary"（选中的模组与外形，给 AI 改构型用）, "result"}"""
    payload = cond.get("payload")
    if not isinstance(payload, (int, float)) or isinstance(payload, bool):
        return {"ok": True, "items": [], "summary": "需求里没有末端负载：选件不做"}
    sp = cond.get("joint_speed")
    move_s = move_s_for(sp) if isinstance(sp, (int, float)) and not isinstance(sp, bool) and sp > 0 else MOVE_S
    pts = [[cond["reach"], 0.0, 0.0]] if isinstance(cond.get("reach"), (int, float)) else []
    pts += list(((concept.get("workspace") or {}).get("points_mm")) or [])
    rep = cond.get("repeatability")
    try:
        out = build(copy.deepcopy(dict(concept)), float(payload), move_s=move_s, points_mm=pts,
                    repeatability_mm=float(rep) if isinstance(rep, (int, float)) and not isinstance(rep, bool) else None)
    except (BuildError, ValueError) as ex:
        return {"ok": False, "items": [f"选件算不了：{ex}"], "summary": ""}
    items = []
    if out["status"] != "pass":
        items.append(f"选件：{out.get('note', '')}")
    for key, name in (("fit", "装配"), ("links", "杆件强度")):
        part = out.get(key) or {}
        rows = (part.get("joints") or []) + (part.get("links") or []) if key == "fit" else part.get("items") or []
        items += [f"{name}：{r.get('joint') or r.get('link') or r.get('item')} {r.get('note', '')}" for r in rows
                  if r.get("status") == "fail"]
    r = out.get("repeatability") or {}
    if r.get("status") == "fail":
        items.append(f"重复定位精度：{r.get('note', '')}")
    lib = _library()
    summ = []
    for g, p in (out.get("picks") or {}).items():
        if not p.get("components"):
            continue
        comp = lib.get(p["components"][0])
        txt = f"模组组 {g}（关节 {'、'.join(p['joints'])}）选 {comp.get('model')}"
        if p.get("chain") == "smart":
            from analysis.robot import fit

            gm = fit.housing_geometry(comp)
            if gm:
                txt += (f"：壳体宽 {2 * gm['half_width']:g} mm，输出轴离壳体底面 {gm['axis_to_bottom']:g} mm（这一面最远）；"
                        "只有输出舵盘（与背面惰轮舵盘同轴）会转，能固定的面（底面、两侧面）都与输出轴平行")
        summ.append(txt)
    return {"ok": not items, "items": items, "summary": "；".join(summ), "result": out}


def fit_check(lib, concept: Mapping, picks: Mapping) -> dict:
    """装不装得下（analysis/robot/fit.py）：一体化模组按它的机械接口算；伺服链没有整体外形与接口，判不了"""
    from analysis.robot import fit

    acts = {}
    for p in picks.values():
        if p.get("chain") == "smart":
            comp = lib.get(p["components"][0])
            acts.update({j: comp for j in p["joints"]})
    return fit.check(concept, acts)


def dynamic_factor(res: Mapping) -> float:
    """动载系数：各关节多体动力学峰值力矩 / 同一关节在检验动作起点的静重力矩，取最大（静重力矩小于最大值 5% 的关节不算）；至少 1"""
    st = {k: abs(v) for k, v in ((res["data"].get("static") or {}).get("gravity_torque_nm") or {}).items()}
    if not st or max(st.values()) <= 0:
        return 1.0
    big = max(st.values())
    ks = [d["peak"] / st[d["joint"]] for d in res["data"]["drives"] if st.get(d["joint"], 0) > 0.05 * big]
    return max([1.0, *ks])


def link_check(concept: Mapping, dt: Mapping, res: Mapping, mods: Mapping, payload_kg: float, safety: float) -> dict:
    """杆件强度与末端下垂（analysis/robot/links.py），在检验动作起点（水平伸直）算，静载乘动载系数"""
    from analysis.robot import links

    return links.check(concept, dt["initial"], module_masses_kg=mods, payload_kg=payload_kg,
                       dynamic_factor=dynamic_factor(res), required_safety=safety)


def _link_masses(concept: Mapping) -> dict:
    from analysis.robot import mjcf

    return {k: round(v, 4) for k, v in mjcf.link_masses(concept)[0].items()}


def bom(lib, concept: Mapping, picks: Mapping) -> dict:
    """外购件（伺服链每个关节一套电机、减速器、驱动器；一体化链每个关节一个模组）与自制杆件"""
    rows, total, notes = [], 0.0, []
    for p in picks.values():
        for cid in p["components"]:
            comp = lib.get(cid)
            m = _pv(comp, "mass_kg")
            rows.append({"component": cid, "role": p["roles"][cid], "model": comp.get("model"), "vendor": comp.get("vendor"),
                         "qty": len(p["joints"]), "joints": p["joints"], "mass_kg_each": m})
            total = None if total is None or m is None else total + m * len(p["joints"])
        if p["chain"] == "smart":
            notes.append("一体化关节模组还要一个总线控制器（如 U2D2 一类的总线转接）与直流电源；库里没有这两类，未列入")
    lm = _link_masses(concept)
    made = [{"link": lk["id"], "shape": lk["shape"], "section": lk.get("section"), "length_mm": lk["length_mm"],
             "material": lk.get("material"), "mass_kg": lm.get(lk["id"])} for lk in concept["links"]]
    return {"purchased": rows, "purchased_mass_kg": None if total is None else round(total, 3), "made": made,
            "made_mass_kg": round(sum(lm.values()), 3), "notes": sorted(set(notes))}


def summary(out: Mapping) -> str:
    lines = [f"结论：{out['status']}；{len(out['rounds'])} 轮" + (f"（{out['note']}）" if out.get("note") else "")]
    for k, rd in enumerate(out["rounds"], 1):
        d = {x["joint"]: x for x in rd["drives"]}
        lines.append(f"第 {k} 轮（模组质量 {rd['module_masses_kg'] or '0'}）："
                     + "；".join(f"{j} 峰值 {x['peak']:.2f} / 均方根 {x['rms']:.2f} N·m、{x['speed_max']:.1f} rpm"
                                for j, x in d.items()))
        lines.append("  选件：" + json.dumps(rd["picks"], ensure_ascii=False))
    if out["status"] == "pass":
        b = out["bom"]
        for g, p in out["picks"].items():
            lines.append(f"模组组 {g}：选 {p['chain']}（{'、'.join(p['components'])}，装在臂上 {p['module_mass_kg']:.3f} kg/关节）；并列："
                         + "；".join(f"{c} {o['module_mass_kg']:.3f} kg {o['overall']}（{'、'.join(o['components'])}）"
                                    for c, o in p["options"].items())
                         + (f"；{p['smart_shortfall']}" if p.get("smart_shortfall") else ""))
        lines.append(f"外购件 {b['purchased_mass_kg']} kg；自制杆件 {b['made_mass_kg']} kg")
        r = out.get("repeatability")
        if r:
            lines.append(f"重复定位精度：{r['status']}（{r['note']}）")
        lk = out.get("links")
        if lk:
            lines.append(f"杆件强度：{lk['overall']}（动载系数 {lk['dynamic_factor']}；最小安全系数 "
                         + "、".join(f"{i['item']} {min(i['safety_yield'], i['safety_fatigue']):.1f}" for i in lk["items"]
                                    if i.get("safety_yield") is not None)
                         + f"）；末端下垂（只计杆件）{lk['tool_sag_mm']:.3f} mm")
        ft = out.get("fit")
        if ft:
            lines.append(f"装不装得下：{ft['overall']}")
            lines += [f"  {x.get('joint') or x.get('link')}：{x['status']}（{x['note']}）" for x in ft["joints"] + ft["links"]
                      if x["status"] != "pass" or x.get("d_min_mm")]
        lines += [f"待确认：{x}" for x in out.get("open_items", [])]
        lines.append(f"成本：{out['cost']['note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_build", description="整机：构型 → 载荷 → 选件（ADR-0115 44.3）")
    ap.add_argument("concept_result", type=Path, help="assist.robot_design 的结果（JSON）")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--move-s", type=float, help=f"检验动作每个关节转 {MOVE_DEG:g}° 的用时（s）；不给时按需求的关节最高角速度，"
                    f"需求也没给就用 {MOVE_S:g}")
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    if cr.get("status") != "pass":
        print("构型循环没有通过，没有可用的方案", file=sys.stderr)
        return 1
    payload = (cr.get("conditions") or {}).get("payload")          # 构型循环核对过的条件，已统一为 kg
    if isinstance(payload, bool) or not isinstance(payload, (int, float)) or not math.isfinite(payload):
        print("需求里没有末端负载：载荷算不了", file=sys.stderr)
        return 1
    cond = cr.get("conditions") or {}
    rep = cond.get("repeatability")
    move_s = a.move_s
    sp = cond.get("joint_speed")
    if move_s is None and isinstance(sp, (int, float)) and not isinstance(sp, bool) and sp > 0:
        move_s = move_s_for(sp)                                      # 需求给了关节最高角速度：检验动作按它
    pts = [[cond["reach"], 0.0, 0.0]] if isinstance(cond.get("reach"), (int, float)) else []
    pts += list(((cr["chosen"].get("workspace") or {}).get("points_mm")) or [])
    out = build(copy.deepcopy(cr["chosen"]), float(payload), move_s=move_s or MOVE_S,
                repeatability_mm=float(rep) if isinstance(rep, (int, float)) and not isinstance(rep, bool) else None,
                points_mm=pts)
    print(summary(out), file=sys.stderr)
    if a.out:
        keep = {k: v for k, v in out.items() if k != "result"}
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if out["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
