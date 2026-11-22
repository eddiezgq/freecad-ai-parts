"""整机构型初筛（ADR-0115 第 44.1 步，ADR-0056 的分析模块）：AI 提的整机方案（robot-concept/1，ADR-0116）能不能用的第一道检查。

查什么：
  结构：schema 之外的结构问题（kinematics.structure_problems）
  工作空间：需求要求够得着的点，在关节行程内有没有逆解
  动作：关节动作在行程内；直线动作沿途（等分 20 段）每点都有逆解、相邻两点关节变化连续，沿途不奇异
  奇异：位置雅可比的最小 / 最大奇异值之比；数值上秩亏（< SINGULAR_RATIO）才判奇异，其余只报数
  粗载荷（下限）：只计末端负载的重力，对每个转动关节轴的静力矩，在各动作姿态与工作空间点上取最大；
                  自重、惯性在选件、设计自制件之后由多体动力学算（这里不估质量）
移动底盘：工作空间与载荷在选件后按整车质量算，这一步只查结构与升降等关节行程。

设置：{"concept": robot-concept/1, "payload_kg": 末端负载（可不给，不给则不算粗载荷）}
不联网、不调用 AI；结果不写入零件参数。
"""

from __future__ import annotations

import math
import time

import numpy as np

from analysis.common import result
from analysis.robot import kinematics as K

MODULE = {"id": "robot", "name": "整机构型初筛", "version": "1",
          "description": "AI 提的整机方案：结构、工作空间、动作可达与连续、奇异、末端负载的静力矩（下限）",
          "python": ["numpy"], "solvers": [], "install": ""}
LIMITS = ["逆解只求末端位置（不管姿态）；用阻尼最小二乘从固定的若干起点出发，找不到解判为够不着（可能漏掉很窄的可达区）",
          "奇异只看位置雅可比的秩；接近奇异只报最小 / 最大奇异值之比，不判",
          "粗载荷只计末端负载的重力，是下限；自重、惯性力矩在选件之后由多体动力学算"]
G = 9.80665
CART_STEPS = 20


def _item(name: str, status: str, value=None, limit=None, note: str = "") -> dict:
    d = {"item": name, "status": status}
    if value is not None:
        d["value"] = value
    if limit is not None:
        d["limit"] = limit
    if note:
        d["note"] = note
    return d


def _payload_torques(m: K.Model, q: dict, payload: float) -> dict[str, float]:
    """末端负载重力对各转动关节轴的静力矩（N·m，取绝对值）"""
    T = K.fk(m, q)
    p = K.tool_point(m, q)
    F = np.array([0.0, 0.0, -payload * G])
    out = {}
    for j in K.chain(m):
        if j.type == "prismatic":
            continue
        Tp = T[j.parent]
        o = (Tp @ np.append(j.origin, 1.0))[:3]
        a = Tp[:3, :3] @ j.axis
        out[j.id] = abs(float(a @ np.cross((p - o) / 1000.0, F)))
    return out


def screen(concept: dict, payload_kg: float | None = None) -> dict:
    """返回 {"items", "overall", "poses", "payload_torque_nm", "sigma_ratio_min"}"""
    items: list[dict] = []
    try:
        m = K.build(concept)
    except K.ConceptError as ex:
        return {"items": [_item("结构", "fail", note=str(ex))], "overall": "fail"}
    items.append(_item("结构", "pass", note=f"{len(m.links)} 根杆件、{len(m.joints)} 个关节"))
    if concept["kind"] == "mobile_base":
        items.append(_item("工作空间与载荷", "unknown", note="移动底盘的载荷在选件后按整车质量算"))
        return {"items": items, "overall": _overall(items), "poses": [], "payload_torque_nm": {}}
    if m.tool_link is None:
        items.append(_item("末端", "fail", note="末端装在哪根杆件上不明确（有多根叶子杆件）：请写 end_effector.parent"))
        return {"items": items, "overall": "fail"}
    poses: list[tuple[str, dict]] = []
    ratios: list[float] = []

    def sing(name: str, q: dict):
        sv = K.singular_values(m, q)
        r = float(sv.min() / sv.max()) if sv.size and sv.max() > 0 else 0.0
        rank = int((sv > K.SINGULAR_RATIO * (sv.max() if sv.size else 1)).sum())
        ratios.append(r)
        if rank < min(3, len(K.chain(m))):
            items.append(_item(f"奇异：{name}", "fail", round(r, 6), f"> {K.SINGULAR_RATIO:g}",
                               "末端位置在这里少了一个方向的运动能力"))

    pts = ((concept.get("workspace") or {}).get("points_mm")) or []
    if not pts:
        items.append(_item("工作空间", "unknown", note="需求没给要够得着的点"))
    for i, p in enumerate(pts, 1):
        q, err = K.ik(m, p)
        name = f"工作空间点 {i} {tuple(round(x, 1) for x in p)}"
        if q is None:
            items.append(_item(name, "fail", round(err, 2), f"≤ {K.IK_TOL_MM:g} mm", "关节行程内够不着"))
        else:
            items.append(_item(name, "pass", round(err, 3), f"≤ {K.IK_TOL_MM:g} mm"))
            poses.append((name, q))
            sing(name, q)
    for t in concept.get("tasks") or []:
        if t["type"] == "joint_move":
            for side in ("from", "to"):
                q = {j.id: float(t[side].get(j.id, 0.0)) for j in K.chain(m)}
                poses.append((f"{t['name']}（{'起点' if side == 'from' else '终点'}）", q))
                sing(f"{t['name']}（{side}）", q)
            items.append(_item(f"动作：{t['name']}", "pass", note="关节值都在行程内"))
        elif t["type"] == "cartesian_move":
            a, b = np.array(t["from_mm"], float), np.array(t["to_mm"], float)
            q, err = K.ik(m, a)
            if q is None:
                items.append(_item(f"动作：{t['name']}", "fail", round(err, 2), note="起点够不着"))
                continue
            jump, ok, prev = 0.0, True, q
            for k in range(1, CART_STEPS + 1):
                p = a + (b - a) * k / CART_STEPS
                qk, e = K.ik(m, p, prev, restarts=6)
                if qk is None:
                    items.append(_item(f"动作：{t['name']}", "fail", round(e, 2),
                                       note=f"沿途第 {k}/{CART_STEPS} 点够不着 {tuple(round(x, 1) for x in p)}"))
                    ok = False
                    break
                jump = max(jump, max(abs(qk[j] - prev[j]) for j in qk))
                sing(f"{t['name']} 第 {k} 点", qk)
                prev = qk
            if ok:
                items.append(_item(f"动作：{t['name']}", "pass", round(jump, 2), None,
                                   f"沿途 {CART_STEPS} 段都有解；相邻两点关节最大变化 {jump:.2f}（° 或 mm）"))
                poses += [(f"{t['name']}（起点）", q), (f"{t['name']}（终点）", prev)]
    torques: dict[str, float] = {}
    if payload_kg:
        for _, q in poses:
            for jid, v in _payload_torques(m, q, payload_kg).items():
                torques[jid] = max(torques.get(jid, 0.0), v)
        if torques:
            items.append(_item("末端负载的静力矩（下限）", "pass", None, None,
                               "；".join(f"{k} {v:.2f} N·m" for k, v in torques.items())
                               + "。只计负载重力，自重与惯性在选件后由多体动力学算"))
    return {"items": items, "overall": _overall(items), "poses": [{"name": n, "q": q} for n, q in poses],
            "payload_torque_nm": {k: round(v, 4) for k, v in torques.items()},
            "sigma_ratio_min": round(min(ratios), 6) if ratios else None}


def _overall(items: list[dict]) -> str:
    st = {i["status"] for i in items}
    return "fail" if "fail" in st else "unknown" if "unknown" in st else "pass"


def run(setup: dict) -> dict:
    t0 = time.time()
    c = setup.get("concept")
    if not isinstance(c, dict):
        return result.failed("robot", MODULE["version"], setup, "设置里要有 concept（robot-concept/1）")
    pl = setup.get("payload_kg")
    if pl is not None and (isinstance(pl, bool) or not isinstance(pl, (int, float)) or pl < 0 or not math.isfinite(pl)):
        return result.failed("robot", MODULE["version"], setup, "payload_kg 须为非负数")
    rep = screen(c, pl)
    return result.make("robot", MODULE["version"], setup, rep, limitations=LIMITS, elapsed_s=time.time() - t0)
