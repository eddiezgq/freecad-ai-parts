"""龙门（直角坐标）取放机器人的整机：节拍 → 多体动力学 → 直线模组与抓手选件（ADR-0115 44.5.5 第一步）。不调用 AI。

输入：构型循环采用的方案（robot-concept/1，全部是移动关节、轴线沿坐标轴的龙门）与核对过的取放条件（单片质量、节拍、精度）。
做什么：
  1 节拍：方案 tasks 里的直线动作（cartesian_move）首尾相连成一圈；每段的起点、终点按龙门的线性运动学解出各轴位置，
    各轴在同一时间段里走梯形速度曲线（加速、减速各占 ACCEL，与初筛 assist/robot_cell.py 同一算法），段后停留 dwell_s。
    直角坐标龙门里末端走直线 ⇔ 各轴同步走梯形曲线，没有近似。
  2 多体动力学（analysis.mbd，MuJoCo，多段路径驱动）跑一整个节拍：各轴推力（稳定峰值，去掉理想梯形曲线加速度突变处的软约束过冲）、
    速度、加速度，以及每个滑台面中心受的力与力矩（反力，对滑台随动的参考点取矩）。
  3 选件：每个轴按 engine.linear_module（行程、速度、加速度、推力 × 安全系数、滑台载荷比较系数）在方案写的驱动方式里取最轻的；
    抓手按 engine.gripper（保持力 ≥ 单片 ×（g + 节拍里末端最大加速度）× 2），取方案写的类型里保持力判通过的最轻（没有质量的取保持力最小）。
    选中的模组质量回代到第 2 步重算，到选型不再变（最多 MAX_ROUNDS 轮）。
  4 重复定位精度：各轴重复定位精度最坏相加（直角坐标：各轴误差直接叠到末端），与需求比；横梁变形、振动另算（有限元那一步）。
质量的放法（三维装配之前，照案例 A 的约定，三维装配后按真实质量与位置复核）：
  每个轴的滑台面中心（费斯托目录第 15 页：力与力矩的参考点是导轨中心与滑台纵向中心的交点）取在方案里该关节的原点；
  滑台的运动质量、下一轴模组的固定部分（本体质量 − 滑台质量）集中在该点；杆件按截面 × 长度 × 密度、质心在杆件两端中点；
  抓手（厂商给了质量的）与工件集中在工具点。
滑台的坐标（换算载荷用）：运动方向 = 关节轴线；水平轴的滑台面朝上（法向 +z），竖直轴的滑台面朝 +y；侧向 = 法向 × 运动方向。
  力：侧向 Fy、法向 Fz；力矩：绕运动方向 Mx（滚转）、绕侧向 My（俯仰）、绕法向 Mz（偏摆）。各项取节拍里绝对值的最大，
  不同时刻的最大值放在一起算载荷比较系数，偏保守。
成本：零件库没有价格数据，判不了。
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
FORMAT = "gantry-build/1"
MAX_ROUNDS = 5
ACCEL = 0.25                    # 同 assist.robot_cell.ACCEL
SAFETY = 1.2                    # 直线模组的安全系数（同案例 A 的 BASE_REQ）
GRIPPER_SF = 2.0                # ADR-0115 44.5.4
SAMPLE_HZ = 1000
TOL_MM = 1.0
DRIVE_TYPES = {"belt_linear": {"belt"}, "ballscrew": {"ballscrew"}}
EE_TYPES = {"vacuum": "suction_cup", "suction": "suction_cup", "needle": "needle", "gripper": "finger"}
G = 9.80665
ASSUMPTIONS = [
    f"直线模组安全系数 {SAFETY:g}（推力与滑台载荷都乘），抓手保持力安全系数 {GRIPPER_SF:g}（ADR-0115 44.5.4）",
    ("各轴的滑台面中心取在方案里该关节的原点；滑台运动质量、下一轴模组的固定部分集中在该点；杆件质量按截面、长度与材料密度，"
     "质心在两端中点；抓手与工件集中在工具点——三维装配后按真实质量与偏置复核"),
    "水平轴滑台面朝上、竖直轴滑台面朝 +y；各项载荷取节拍里绝对值的最大，放在一起算载荷比较系数（偏保守）",
    ("推力取多体动力学的稳定峰值：理想梯形速度曲线的加加速度无限大，软约束在加速度突变处有约 13% 的数值过冲，"
     "突变后 8 个约束时间常数内的点不计（原始峰值并列在结果里）；电机、联轴器的转动惯量没有计入（库里没有电机）"),
    "节拍只算动作与停留时间；停稳（振动衰减）的时间要看横梁的一阶频率（有限元那一步）",
]


class BuildError(ValueError):
    pass


def _library():
    from kb.library import JsonLibrary

    return JsonLibrary(ROOT / "data" / "library")


def _pv(comp: Mapping | None, k: str):
    v = ((comp or {}).get("params") or {}).get(k)
    return v.get("value") if isinstance(v, dict) else None


# ---------------------------------------------------------------- 运动学与节拍
def axes(concept: Mapping) -> list[dict]:
    """龙门的各轴（基座到末端的顺序）：{"joint", "axis"（世界坐标单位向量）, "dir"（0/1/2）, "lo", "hi", "transmission"}。
    不是全部移动关节、或轴线不沿坐标轴（零位时）时报错——这一步只做直角坐标龙门"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    T = K.fk(m)
    out = []
    for j in K.chain(m):
        if j.type != "prismatic":
            raise BuildError(f"关节 {j.id} 是{j.type}关节：这一步只做全部是移动关节的龙门（转动关节走 assist.robot_build）")
        a = T[j.parent][:3, :3] @ j.axis
        k = int(np.argmax(np.abs(a)))
        if abs(abs(a[k]) - 1.0) > 1e-9:
            raise BuildError(f"关节 {j.id} 的轴线 {a.round(4).tolist()} 不沿坐标轴：不是直角坐标龙门")
        out.append({"joint": j.id, "axis": np.sign(a[k]) * np.eye(3)[k], "dir": k, "lo": j.lo, "hi": j.hi,
                    "transmission": j.raw.get("transmission")})
    if len({a["dir"] for a in out}) != len(out):
        raise BuildError("有两个轴沿同一方向：这一步只做每个方向一个轴的龙门")
    return out


def joint_values(concept: Mapping, p_mm) -> dict[str, float]:
    """末端到 p_mm 时各轴的位置（mm）。龙门是线性的：工具点 = 零位工具点 + Σ q × 轴线；够不着（另两个方向差 > 1 mm）或超行程报错"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    ax = axes(concept)
    d = np.asarray(p_mm, float) - K.tool_point(m)
    q = {a["joint"]: float(d @ a["axis"]) for a in ax}
    rest = d - sum(q[a["joint"]] * a["axis"] for a in ax)
    if np.linalg.norm(rest) > TOL_MM:
        raise BuildError(f"末端到不了 {list(p_mm)}：没有轴的方向差 {np.round(rest, 1).tolist()} mm")
    for a in ax:
        v = q[a["joint"]]
        if (a["lo"] is not None and v < a["lo"] - 1e-6) or (a["hi"] is not None and v > a["hi"] + 1e-6):
            raise BuildError(f"末端到 {list(p_mm)} 时 {a['joint']} = {v:g} mm，超出行程 [{a['lo']:g}, {a['hi']:g}]")
    return q


def trapezoid(length: float, move_s: float, accel: float = ACCEL) -> tuple[float, float]:
    """同 assist.robot_cell.trapezoid：(最高速度, 加速度)，单位随 length（mm → mm/s、mm/s²）"""
    ta = accel * move_s
    v = length / (move_s - ta)
    return v, v / ta


def cycle(concept: Mapping) -> dict:
    """一个节拍：{"initial", "drives"（analysis.mbd 的多段路径）, "segments", "total_s", "axes": {关节: 最高速度、加速度、走过的范围},
    "tool": {最高速度、最大加速度}}"""
    moves = [t for t in concept.get("tasks") or [] if t.get("type") == "cartesian_move"]
    if not moves or len(moves) != len(concept.get("tasks") or []):
        raise BuildError("节拍要全部用直线动作（cartesian_move）写")
    for k, mv in enumerate(moves):
        nxt = moves[(k + 1) % len(moves)]
        if math.dist(mv["to_mm"], nxt["from_mm"]) > TOL_MM:
            raise BuildError(f"直线动作没有首尾相连：第 {k + 1} 段的终点不是下一段的起点")
    ax = axes(concept)
    q0 = joint_values(concept, moves[0]["from_mm"])
    t, cur = 0.0, dict(q0)
    segs, paths = [], {a["joint"]: [] for a in ax}
    vmax = {a["joint"]: 0.0 for a in ax}
    amax = dict(vmax)
    seen = {a["joint"]: [cur[a["joint"]]] for a in ax}
    tool_v = tool_a = 0.0
    for mv in moves:
        T = float(mv["move_s"])
        if T <= 0:
            raise BuildError(f"动作 {mv['name']} 的用时要大于 0")
        q1 = joint_values(concept, mv["to_mm"])
        L = math.dist(mv["from_mm"], mv["to_mm"])
        v, a = trapezoid(L, T)
        tool_v, tool_a = max(tool_v, v), max(tool_a, a)
        for jid, segs_j in paths.items():
            dq = q1[jid] - cur[jid]
            if abs(dq) > 1e-9:
                segs_j.append({"to": round(q1[jid], 6), "t0_s": round(t, 6), "t1_s": round(t + T, 6), "accel_ratio": ACCEL})
                vj, aj = trapezoid(abs(dq), T)
                vmax[jid], amax[jid] = max(vmax[jid], vj), max(amax[jid], aj)
            seen[jid].append(q1[jid])
        dw = float(mv.get("dwell_s") or 0.0)
        segs.append({"name": mv["name"], "t0_s": round(t, 6), "t1_s": round(t + T, 6), "dwell_s": dw,
                     "from_mm": list(mv["from_mm"]), "to_mm": list(mv["to_mm"]), "length_mm": round(L, 3),
                     "speed_m_s": round(v / 1000, 4), "accel_m_s2": round(a / 1000, 4),
                     "joints_to_mm": {k: round(x, 3) for k, x in q1.items()}})
        t += T + dw
        cur = q1
    drives = [{"joint": jid, "kind": "path", "segments": sg} if sg else {"joint": jid, "kind": "hold"} for jid, sg in paths.items()]
    return {"initial": {k: round(v, 6) for k, v in q0.items()}, "drives": drives, "segments": segs, "total_s": round(t, 6),
            "axes": {jid: {"speed_m_s": round(vmax[jid] / 1000, 4), "accel_m_s2": round(amax[jid] / 1000, 4),
                           "travel_mm": [round(min(seen[jid]), 3), round(max(seen[jid]), 3)]} for jid in paths},
            "tool": {"speed_m_s": round(tool_v / 1000, 4), "accel_m_s2": round(tool_a / 1000, 4)}}


# ---------------------------------------------------------------- 多体动力学模型
def frame(a: Mapping) -> dict[str, np.ndarray]:
    """滑台的坐标（世界坐标单位向量）：运动方向、法向（水平轴朝上，竖直轴朝 +y）、侧向 = 法向 × 运动方向"""
    e1 = np.asarray(a["axis"], float)
    n = np.array([0.0, 0.0, 1.0]) if a["dir"] != 2 else np.array([0.0, 1.0, 0.0])
    return {"motion": e1, "normal": n, "lateral": np.cross(n, e1)}


def masses(concept: Mapping, picks: Mapping[str, Mapping], gripper_kg: float | None, part_kg: float) -> dict:
    """各轴运动部分上的集中质量 {关节: [(名称, kg, 位置 mm（该轴构件坐标）)]}——模块说明里的放法；缺的质量不计、写进 missing"""
    from analysis.robot import kinematics as K
    from analysis.robot import mjcf as RM

    m = K.build(concept)
    ax = axes(concept)
    lm, probs = RM.link_masses(concept)
    out, missing = {}, list(probs)
    for i, a in enumerate(ax):
        j = next(x for x in m.joints if x.id == a["joint"])
        rows = []
        pk = picks.get(a["joint"]) or {}
        if pk.get("carriage_kg") is not None:
            rows.append((f"{pk['model']} 滑台", pk["carriage_kg"], [0.0, 0.0, 0.0]))
        elif pk:
            missing.append(f"{pk['model']} 的滑台质量厂商没给")
        if i + 1 < len(ax):
            nk = picks.get(ax[i + 1]["joint"]) or {}
            if nk.get("body_kg") is not None:
                nj = next(x for x in m.joints if x.id == ax[i + 1]["joint"])
                rows.append((f"{nk['model']} 本体（不含滑台）", nk["body_kg"], nj.origin.tolist()))
        if j.child in lm:
            mid = (np.zeros(3) + RM._segment(m, j.child)) / 2
            rows.append((f"杆件 {j.child}", lm[j.child], mid.tolist()))
        if j.child == m.tool_link:
            rows.append(("工件（单片）", part_kg, m.tool_offset.tolist()))
            if gripper_kg is not None:
                rows.append(("抓手", gripper_kg, m.tool_offset.tolist()))
        out[a["joint"]] = rows
    if gripper_kg is None:
        missing.append("抓手质量厂商没给（未计入运动质量）")
    return {"bodies": out, "missing": missing}


def mjcf(concept: Mapping, bodies: Mapping[str, list], origins: Mapping[str, list] | None = None) -> str:
    """MJCF（米、千克）：每个轴一个构件，原点在该关节（= 滑台面中心），沿轴线滑动；质量为集中质量（小球几何）。
    origins：{关节: 构件原点在上一构件坐标系里的位置 mm}，三维装配后按真实的滑台面中心给（assist.gantry_cad）；不给时用方案的关节原点"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    ax = axes(concept)
    if (concept.get("base") or {}).get("mount") not in (None, "table", "floor"):
        raise BuildError("龙门只做装在台面或地面上的（基座坐标系 = 世界坐标系）")

    def f(v):
        return " ".join(f"{float(x):.6g}" for x in v)

    def geoms(jid, rows):
        out = []
        for k, (_name, kg, pos) in enumerate(rows):
            if kg and kg > 0:
                out.append(f'<geom name="{jid}_m{k}" type="sphere" size="0.005" pos="{f(np.asarray(pos) / 1000)}" mass="{kg:.6g}" '
                           'contype="0" conaffinity="0"/>')
        if not out:
            out.append('<geom type="sphere" size="0.001" mass="1e-6" contype="0" conaffinity="0"/>')
        return "".join(out)

    xml = ""
    for a in reversed(ax):
        j = next(x for x in m.joints if x.id == a["joint"])
        o = np.asarray((origins or {}).get(a["joint"], j.origin), float)
        xml = (f'<body name="{j.child}" pos="{f(o / 1000)}"><joint name="{j.id}" type="slide" axis="{f(j.axis)}"/>'
               f'{geoms(a["joint"], bodies[a["joint"]])}{xml}</body>')
    return f'<mujoco model="{concept.get("name", "gantry")}"><worldbody>{xml}</worldbody></mujoco>'


def dynamics(concept: Mapping, bodies: Mapping, cyc: Mapping, origins: Mapping | None = None) -> dict:
    import analysis
    from analysis.robot import kinematics as K

    m = K.build(concept)
    links = [next(x for x in m.joints if x.id == a["joint"]).child for a in axes(concept)]
    r = analysis.run("mbd", {"force_solver": "soft", "model": {"kind": "mjcf", "xml": mjcf(concept, bodies, origins)}, "duration_s": cyc["total_s"] + 0.1,
                             "sample_hz": SAMPLE_HZ, "initial": cyc["initial"], "drives": cyc["drives"], "reactions": links})
    if r.get("status") != "ok":
        raise BuildError("多体动力学没算成：" + "；".join(r.get("messages") or []))
    return r


def axis_loads(concept: Mapping, res: Mapping) -> dict[str, dict]:
    """每个轴：推力（稳定峰值与原始峰值）、速度、滑台载荷（换到滑台坐标，绝对值最大）"""
    from analysis.robot import kinematics as K

    m = K.build(concept)
    d = res["data"]
    dr = {x["joint"]: x for x in d["drives"]}
    out = {}
    for a in axes(concept):
        jid = a["joint"]
        child = next(x for x in m.joints if x.id == jid).child
        mx = d["reactions"][child]["max_abs_settled"]
        fr = frame(a)
        F = np.array([mx["fx"], mx["fy"], mx["fz"]])
        M = np.array([mx["mx"], mx["my"], mx["mz"]])

        def comp(v, e):
            return float(abs(np.asarray(e)) @ v)                # 轴线沿坐标轴：取对应分量

        x = dr.get(jid) or {}
        out[jid] = {"thrust_n": round(x.get("peak_settled") or 0.0, 4), "thrust_peak_raw_n": round(x.get("peak") or 0.0, 4),
                    "thrust_rms_n": round(x.get("rms") or 0.0, 4), "speed_mm_s": round(x.get("speed_max") or 0.0, 3),
                    "force_lateral_n": round(comp(F, fr["lateral"]), 4), "force_normal_n": round(comp(F, fr["normal"]), 4),
                    "moment_roll_nm": round(comp(M, fr["motion"]), 4), "moment_pitch_nm": round(comp(M, fr["lateral"]), 4),
                    "moment_yaw_nm": round(comp(M, fr["normal"]), 4)}
    return out


# ---------------------------------------------------------------- 选件
def requirement(a: Mapping, cyc: Mapping, ld: Mapping) -> dict:
    lo, hi = a["lo"], a["hi"]
    req = {"stroke_mm": None if lo is None or hi is None else float(hi - lo), "speed_m_s": cyc["axes"][a["joint"]]["speed_m_s"],
           "accel_m_s2": cyc["axes"][a["joint"]]["accel_m_s2"], "safety_factor": SAFETY,
           **{k: ld[k] for k in ("thrust_n", "force_lateral_n", "force_normal_n", "moment_roll_nm", "moment_pitch_nm",
                                 "moment_yaw_nm")}}
    return req


def pick_axis(lib, a: Mapping, req: Mapping) -> dict:
    """一个轴：方案写的驱动方式里没有“不通过”的最轻的；返回 {"component", "model", "check", "mass_kg", "carriage_kg", "body_kg",
    "candidates", "rejected"}，选不出时 component 为 None"""
    from engine import linear_module as LM

    comps = list(lib.all())
    types = DRIVE_TYPES.get(a["transmission"] or "")
    cands = LM.candidates(req, comps, top=40, drive_types=types)
    rej = [r for r in LM.rejected(req, comps)
           if not types or _pv(lib.get(r["component"]), "drive_type") in types]
    ok = [c for c in cands if c["mass_kg"] is not None]
    out = {"drive_types": sorted(types) if types else None, "candidates": [{"component": c["component"], "overall": c["overall"],
                                                                           "mass_kg": c["mass_kg"]} for c in cands],
           "rejected": [{"component": r["component"], "why": [f"{x['check']} {x.get('message', '')}" for x in r["checks"]
                                                              if x["status"] == "fail"]} for r in rej]}
    if not ok:
        return dict(out, component=None, model=None, check=None, mass_kg=None, carriage_kg=None, body_kg=None)
    best = ok[0]
    comp = lib.get(best["component"])
    car = _pv(comp, "carriage_mass_kg")
    return dict(out, component=best["component"], model=comp.get("model"), check=best, mass_kg=round(best["mass_kg"], 4),
                carriage_kg=car, body_kg=None if car is None else round(best["mass_kg"] - car, 4))


def pick_gripper(lib, concept: Mapping, cond: Mapping, tool_accel: float) -> dict:
    """抓手：方案写的类型（真空 → 吸盘）里保持力判通过的；并列每种类型的代表供人比较"""
    from engine import gripper as GR

    req = {"part_mass_kg": cond.get("part_mass"), "accel_m_s2": tool_accel, "safety_factor": GRIPPER_SF, "count": 1,
           "material": "布料"}
    cmp_ = GR.compare(req, list(lib.all()))
    want = EE_TYPES.get(((concept.get("end_effector") or {}).get("type") or "").lower())
    chosen = next((r for r in cmp_ if r["type"] == want and r["checks"][0]["status"] == "pass"), None)
    out = {"requirement": req, "required_force_n": GR.required_force(req), "type_wanted": want,
           "compare": [{"component": r["component"], "model": lib.get(r["component"]).get("model"), "type": r["type"],
                        "type_name": GR.TYPE_NAMES.get(r["type"], r["type"]), "overall": r["overall"],
                        "holding_force_n": r.get("holding_force_n"), "mass_kg": r["mass_kg"],
                        "checks": r["checks"]} for r in cmp_]}
    if chosen is None:
        return dict(out, component=None, model=None, mass_kg=None,
                    note=f"方案要的{GR.TYPE_NAMES.get(want, '抓手')}里没有保持力判通过的")
    return dict(out, component=chosen["component"], model=lib.get(chosen["component"]).get("model"), mass_kg=chosen["mass_kg"],
                checks=chosen["checks"], overall=chosen["overall"])


def repeatability(lib, picks: Mapping, target_mm: float | None) -> dict:
    """各轴重复定位精度最坏相加（直角坐标龙门：各轴误差直接叠到末端）"""
    rows, total, missing = [], 0.0, []
    for jid, p in picks.items():
        r = _pv(lib.get(p["component"]), "repeatability_mm") if p.get("component") else None
        if r is None:
            missing.append(jid)
            continue
        rows.append({"joint": jid, "model": p["model"], "repeatability_mm": r})
        total += abs(r)
    out = {"rows": rows, "worst_mm": round(total, 4), "target_mm": target_mm}
    if missing or target_mm is None:
        out["status"] = "unknown"
        out["note"] = ("厂商没给重复定位精度：" + "、".join(missing)) if missing else "需求没给重复定位精度"
    else:
        out["status"] = "pass" if total <= target_mm + 1e-9 else "fail"
        out["note"] = (f"各轴重复定位精度最坏相加 ±{total:g} mm，要求 ±{target_mm:g} mm（只含直线模组本身；"
                       "横梁变形与振动在有限元那一步，抓手放料偏差没有公开数据）")
    return out


def motor_need(lib, a: Mapping, p: Mapping, ld: Mapping, cyc: Mapping) -> dict:
    """电机要的：力矩 = 推力 × 每转行程 / 2π（不含传动效率，厂商没给）、转速 = 最高速度 / 每转行程。库里没有配这类模组的电机，没选"""
    lead = _pv(lib.get(p["component"]), "lead_mm") if p.get("component") else None
    if not lead:
        return {"status": "unknown", "note": "厂商没给每转行程，电机要的力矩、转速算不了"}
    tq = ld["thrust_n"] * SAFETY * lead / 1000 / (2 * math.pi)
    rpm = cyc["axes"][a["joint"]]["speed_m_s"] * 1000 / lead * 60
    return {"status": "unknown", "lead_mm": lead, "torque_nm": round(tq, 4), "speed_rpm": round(rpm, 1),
            "note": f"电机轴上要 {tq:.3g} N·m（推力 × 安全系数 {SAFETY:g} × 每转行程 {lead:g} mm / 2π，传动效率厂商没给、未计）、"
                    f"{rpm:.0f} rpm；零件库里没有配费斯托模组的电机与电机套件，电机没选"}


def build(concept: Mapping, cond: Mapping, layout=None, start: Mapping | None = None) -> dict:
    """选件循环。layout(picks) 给定时（三维装配后复核，assist.gantry_cad），每轮的集中质量与构件原点由它按当前选件给出：
    返回 {"bodies", "missing", "origins"}；start 是起始选件（第一步的结果），不给时从“只有杆件与工件”开始"""
    lib = _library()
    concept = copy.deepcopy(dict(concept))
    part = cond.get("part_mass")
    if not isinstance(part, (int, float)) or isinstance(part, bool):
        raise BuildError("取放条件里没有单片质量：载荷算不了")
    ax = axes(concept)
    cyc = cycle(concept)
    grip = pick_gripper(lib, concept, cond, cyc["tool"]["accel_m_s2"])
    picks: dict[str, dict] = {j: dict(p) for j, p in (start or {}).items()}
    rounds = []
    for _ in range(MAX_ROUNDS):
        ms = (masses(concept, picks, grip.get("mass_kg"), float(part)) if layout is None
              else layout(picks, grip.get("mass_kg"), float(part)))
        res = dynamics(concept, ms["bodies"], cyc, ms.get("origins"))
        loads = axis_loads(concept, res)
        new = {}
        for a in reversed(ax):                         # 末端那一轴先选（它的质量压在前面的轴上）
            new[a["joint"]] = dict(pick_axis(lib, a, requirement(a, cyc, loads[a["joint"]])),
                                   requirement=requirement(a, cyc, loads[a["joint"]]))
        new = {a["joint"]: new[a["joint"]] for a in ax}
        rounds.append({"moving_masses": {j: [[n, round(k, 4)] for n, k, _ in rows] for j, rows in ms["bodies"].items()},
                       "loads": loads, "picks": {j: p["component"] for j, p in new.items()}})
        stable = rounds[-1]["picks"] == {j: p.get("component") for j, p in picks.items()}
        picks = new
        if any(p["component"] is None for p in picks.values()):
            return {"format": FORMAT, "status": "fail", "rounds": rounds, "cycle": cyc, "picks": picks, "gripper": grip,
                    "note": "有轴选不出直线模组：" + "、".join(j for j, p in picks.items() if p["component"] is None)}
        if stable:
            break
    else:
        return {"format": FORMAT, "status": "fail", "rounds": rounds, "cycle": cyc, "picks": picks, "gripper": grip,
                "note": f"{MAX_ROUNDS} 轮后选型仍在变"}
    d = res["data"]
    target = cond.get("repeatability")
    rep = repeatability(lib, picks, float(target) if isinstance(target, (int, float)) and not isinstance(target, bool) else None)
    lim = cond.get("cycle")
    ct = {"status": "unknown" if lim is None else ("pass" if cyc["total_s"] <= lim + 1e-9 else "fail"),
          "total_s": cyc["total_s"], "limit_s": lim,
          "note": (f"一圈 {len(cyc['segments'])} 段直线动作加停留 {cyc['total_s']:g} s" + (f"，要求 ≤ {lim:g} s" if lim else "")
                   + "；各轴的速度、加速度由所选模组核（L2、L3）；停稳时间另看横梁一阶频率")}
    motors = {a["joint"]: motor_need(lib, a, picks[a["joint"]], loads[a["joint"]], cyc) for a in ax}
    open_items = [f"{j}（{p['model']}）：{c['check']} {c.get('message', '')}" for j, p in picks.items()
                  for c in p["check"]["checks"] if c["status"] == "unknown"]
    open_items += [f"抓手（{grip.get('model') or '未选'}）：{c['check']} {c.get('message', '')}" for c in grip.get("checks") or []
                   if c["status"] == "unknown"]
    open_items += [f"质量没计入：{x}" for x in ms["missing"]]
    open_items += [f"电机（{j}）：{x['note']}" for j, x in motors.items()]
    if any(a["dir"] == 2 for a in ax):
        open_items.append("竖直轴断电会下滑：要带抱闸的电机（库里没有电机，未选）")
    status = "pass" if grip.get("component") and rep["status"] != "fail" and ct["status"] != "fail" else "fail"
    def r3(xs):
        return [round(float(x), 3) for x in xs or []]

    keep = {j: {k: r3(s.get(k)) for k in ("q", "speed", "drive", "accel")} for j, s in d["series"].items() if j != "t_s"}
    return {"format": FORMAT, "status": status, "rounds": rounds, "cycle": cyc, "loads": loads, "picks": picks, "gripper": grip,
            "repeatability": rep, "cycle_time": ct, "motors": motors,
            "mbd": {"drives": d["drives"], "tracking_error_mm": round(d["tracking_error"] * 1000, 6),
                    "settle_window_s": d["settle_window_s"], "timestep_s": d["timestep_s"],
                    "reactions_max_abs": {b: r["max_abs_settled"] for b, r in d["reactions"].items()},
                    "series": {"t_s": r3(d["series"]["t_s"]), **keep}},
            "moving_masses": rounds[-1]["moving_masses"], "assumptions": ASSUMPTIONS, "open_items": open_items,
            "bom": bom(lib, concept, picks, grip),
            "cost": {"status": "unknown", "note": "零件库没有价格数据；成本要等登记了有价格的公开目录才判得了"}}


def bom(lib, concept: Mapping, picks: Mapping, grip: Mapping) -> dict:
    from analysis.robot import mjcf as RM

    rows = []
    for jid, p in picks.items():
        comp = lib.get(p["component"])
        rows.append({"component": p["component"], "role": "linear_module", "model": comp.get("model"), "vendor": comp.get("vendor"),
                     "qty": 1, "joints": [jid], "stroke_mm": p["requirement"]["stroke_mm"], "mass_kg_each": p["mass_kg"]})
    if grip.get("component"):
        comp = lib.get(grip["component"])
        rows.append({"component": grip["component"], "role": "gripper", "model": comp.get("model"), "vendor": comp.get("vendor"),
                     "qty": 1, "joints": [], "mass_kg_each": grip.get("mass_kg")})
    ms = [r["mass_kg_each"] for r in rows]
    lm = RM.link_masses(concept)[0]
    made = [{"link": lk["id"], "shape": lk["shape"], "section": lk.get("section"), "length_mm": lk["length_mm"],
             "material": lk.get("material"), "mass_kg": None if lk["id"] not in lm else round(lm[lk["id"]], 4)}
            for lk in concept["links"]]
    return {"purchased": rows, "purchased_mass_kg": None if any(m is None for m in ms) else round(sum(ms), 4), "made": made,
            "made_mass_kg": round(sum(lm.values()), 4),
            "notes": ["直线模组的电机、电机套件（联轴器、法兰）、横梁与立柱、真空发生器与气路、控制器不在零件库里，未列入",
                      "吸盘个数与排布要按裁片大小与平整度定（这里按 1 个吸盘核保持力，偏保守），布料透气漏气要试"]}


def summary(out: Mapping) -> str:
    lines = [f"结论：{out['status']}；{len(out['rounds'])} 轮" + (f"（{out['note']}）" if out.get("note") else "")]
    c = out["cycle"]
    lines.append(f"节拍 {c['total_s']:g} s；" + "；".join(f"{j} 最高 {a['speed_m_s']:g} m/s、{a['accel_m_s2']:g} m/s²"
                                                     for j, a in c["axes"].items()))
    for k, rd in enumerate(out["rounds"], 1):
        lines.append(f"第 {k} 轮：" + "；".join(f"{j} 推力 {x['thrust_n']:.1f} N（原始峰值 {x['thrust_peak_raw_n']:.1f}）、"
                                              f"Fz {x['force_normal_n']:.1f} N、My {x['moment_pitch_nm']:.2f} N·m"
                                              for j, x in rd["loads"].items()) + " → " + json.dumps(rd["picks"], ensure_ascii=False))
    for j, p in out["picks"].items():
        if p.get("component"):
            fv = next(x for x in p["check"]["checks"] if x["check"] == "L5")
            lines.append(f"{j}：选 {p['model']}（{p['mass_kg']:g} kg）；{fv.get('message', '')}")
    g = out["gripper"]
    lines.append(f"抓手：{g.get('model') or g.get('note')}（至少 {g['required_force_n']:.3g} N）")
    if out.get("repeatability"):
        lines.append(f"重复定位精度：{out['repeatability']['status']}（{out['repeatability']['note']}）")
    lines += [f"待确认：{x}" for x in out.get("open_items", [])]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.gantry_build",
                                 description="龙门取放机器人：节拍 → 多体动力学 → 直线模组与抓手（ADR-0115 44.5.5）")
    ap.add_argument("concept_result", type=Path, help="assist.robot_design 的结果（JSON）")
    ap.add_argument("-o", "--out", type=Path)
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    if cr.get("status") != "pass":
        print("构型循环没有通过，没有可用的方案", file=sys.stderr)
        return 1
    try:
        out = build(cr["chosen"], cr.get("conditions") or {})
    except BuildError as ex:
        print(f"算不了：{ex}", file=sys.stderr)
        return 1
    print(summary(out), file=sys.stderr)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if out["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
