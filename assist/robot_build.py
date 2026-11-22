"""整机：构型 → 载荷 → 选件（ADR-0115 第 44.3 步之一）。不调用 AI，全部是确定性计算与引擎选型。

输入：构型循环采用的整机方案（robot-concept/1，assist/robot_design.py 的结果）与需求里的末端负载。
做什么：
  1 质量：杆件质量按截面 × 长度 × 密度（analysis/robot/mjcf.py），关节模组质量取所选零件的样本质量（第一轮为 0）。
  2 检验动作（需求没给速度时的设计取值，写进报告的“假设”）：从“水平伸直”姿态（第一个水平轴关节的高度上末端伸得最远）出发，
    各转动关节同时转 90°（行程内往能转的一侧），用时 1.0 s、加减速各占 25%（最高 120°/s）；末端带满载。
  3 多体动力学（analysis.mbd，MuJoCo）→ 每个关节的连续（均方根）/ 峰值力矩、最高转速、最大负载惯量。
  4 选件：同一模组组（module_group）的关节取组内各项的最大值作为一个需求，由引擎选型（engine.compose）；
    在没有“不通过”、电机与减速器都有样本质量的组合里，取电机 + 减速器最轻的；同样轻时优先方案里写的减速比。
  5 模组质量回代到第 1 步，重复到选型不再变（最多 MAX_ROUNDS 轮）。
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
ASSUMPTIONS = [
    (f"检验动作（需求没给速度，设计取值）：从水平伸直姿态出发，各转动关节同时转 {MOVE_DEG:g}°，用时 {MOVE_S:g} s，"
     f"加减速各占 {ACCEL:.0%}（最高 {MOVE_DEG / MOVE_S / (1 - ACCEL):.0f}°/s）；末端带满载"),
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


def duty(concept: Mapping) -> dict:
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
        drives.append({"joint": j.id, "kind": "move", "to": round(to, 4), "t0_s": T0, "t1_s": T0 + MOVE_S,
                       "accel_ratio": ACCEL})
    return {"initial": {k: round(v, 4) for k, v in q0.items()}, "drives": drives, "pose_mm": p}


def dynamics(concept: Mapping, payload_kg: float, mods: Mapping[str, float], dt: Mapping) -> dict:
    import analysis
    from analysis.robot import mjcf

    xml = mjcf.mjcf(concept, module_masses_kg=mods, payload_kg=payload_kg)
    r = analysis.run("mbd", {"model": {"kind": "mjcf", "xml": xml}, "duration_s": T0 + MOVE_S + 0.2, "sample_hz": 200,
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


def build(concept: Mapping, payload_kg: float, *, base: Mapping | None = None) -> dict:
    lib = _library()
    base = dict(base or BASE_REQ)
    dt = duty(concept)
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
            best, n = pick(lib, req, ratio[g])
            picks[g] = {"joints": js, "requirement": req, "system": best.system if best else None,
                        "report": best.report if best else None, "candidates": n,
                        "module_mass_kg": module_mass(lib, best.system) if best else None}
        rounds.append({"module_masses_kg": dict(mods), "drives": res["data"]["drives"],
                       "static": res["data"].get("static"),
                       "picks": {g: [c["component"] for c in p["system"]["components"]] if p["system"] else None
                                 for g, p in picks.items()}})
        if any(p["system"] is None for p in picks.values()):
            return {"status": "fail", "rounds": rounds, "picks": picks, "duty": dt,
                    "note": "有模组组选不出带质量数据的组合：" + "、".join(g for g, p in picks.items() if p["system"] is None)}
        new = {j: picks[g]["module_mass_kg"] for g, js in gs.items() for j in js}
        if new == mods:
            break
        mods = new
    else:
        return {"status": "fail", "rounds": rounds, "picks": picks, "duty": dt,
                "note": f"{MAX_ROUNDS} 轮后选型仍在变"}
    return {"status": "pass", "rounds": rounds, "picks": picks, "duty": dt, "result": res,
            "module_masses_kg": mods, "link_masses_kg": _link_masses(concept), "assumptions": ASSUMPTIONS,
            "bom": bom(lib, concept, picks), "cost": {"status": "unknown",
                                                    "note": "零件库没有价格数据；“外购件成本尽量低”要等登记了有价格的公开目录才判得了"}}


def _link_masses(concept: Mapping) -> dict:
    from analysis.robot import mjcf

    return {k: round(v, 4) for k, v in mjcf.link_masses(concept)[0].items()}


def bom(lib, concept: Mapping, picks: Mapping) -> dict:
    """外购件（每个关节一套电机、减速器、驱动器）与自制杆件"""
    rows, total = [], 0.0
    for p in picks.values():
        for c in p["system"]["components"]:
            comp = lib.get(c["component"])
            m = _pv(comp, "mass_kg")
            rows.append({"component": c["component"], "role": c["instance"], "name": comp.get("name"),
                         "qty": len(p["joints"]), "joints": p["joints"], "mass_kg_each": m})
            total = None if total is None or m is None else total + m * len(p["joints"])
    lm = _link_masses(concept)
    made = [{"link": lk["id"], "shape": lk["shape"], "section": lk.get("section"), "length_mm": lk["length_mm"],
             "material": lk.get("material"), "mass_kg": lm.get(lk["id"])} for lk in concept["links"]]
    return {"purchased": rows, "purchased_mass_kg": None if total is None else round(total, 3), "made": made,
            "made_mass_kg": round(sum(lm.values()), 3)}


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
        lines.append(f"外购件 {b['purchased_mass_kg']} kg（含驱动器，驱动器不在臂上）；自制杆件 {b['made_mass_kg']} kg")
        lines.append(f"成本：{out['cost']['note']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.robot_build", description="整机：构型 → 载荷 → 选件（ADR-0115 44.3）")
    ap.add_argument("concept_result", type=Path, help="assist.robot_design 的结果（JSON）")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    if cr.get("status") != "pass":
        print("构型循环没有通过，没有可用的方案", file=sys.stderr)
        return 1
    payload = (cr.get("conditions") or {}).get("payload")          # 构型循环核对过的条件，已统一为 kg
    if isinstance(payload, bool) or not isinstance(payload, (int, float)) or not math.isfinite(payload):
        print("需求里没有末端负载：载荷算不了", file=sys.stderr)
        return 1
    out = build(copy.deepcopy(cr["chosen"]), float(payload))
    print(summary(out), file=sys.stderr)
    if a.out:
        keep = {k: v for k, v in out.items() if k != "result"}
        for p in keep.get("picks", {}).values():
            sysj = p.pop("system", None)
            p["components"] = [c["component"] for c in sysj["components"]] if sysj else None
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if out["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
