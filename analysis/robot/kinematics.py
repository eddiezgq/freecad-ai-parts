"""整机方案（robot-concept/1，ADR-0116）的运动学：结构检查、正运动学、位置雅可比、位置逆解。

约定（ADR-0116）：每根杆件的坐标系原点在带动它的关节处，零位时与父件同向；关节的 origin_mm、axis 是零位时在父件坐标系里的值。
子件位姿 T_子 = T_父 · 平移(origin) · 关节运动(q)；转动关节与轮子绕 axis 转 q（°），移动关节沿 axis 移 q（mm）。
纯计算：不联网、不调用 AI。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

SINGULAR_RATIO = 1e-6           # 位置雅可比最小奇异值 / 最大奇异值低于它才判“奇异”（数值上的秩亏），其余只报数
IK_TOL_MM = 0.05                # 逆解收敛：末端位置误差（mm）
IK_ITER = 300
IK_DAMP = 1e-3


class ConceptError(ValueError):
    pass


@dataclass
class Joint:
    id: str
    type: str
    parent: str
    child: str
    origin: np.ndarray
    axis: np.ndarray
    lo: float | None = None
    hi: float | None = None
    radius_mm: float | None = None
    raw: dict = field(default_factory=dict)


@dataclass
class Model:
    concept: dict
    joints: list[Joint]                     # 按树的先后（父在前）
    by_child: dict[str, Joint]
    links: dict[str, dict]
    tool_link: str | None
    tool_offset: np.ndarray


def structure_problems(c: Mapping) -> list[str]:
    """schema 表达不了的结构问题：id 重复、引用不存在、不是以 base 为根的树、轴线为零、动作里的关节不存在或超行程、末端杆件不存在"""
    out: list[str] = []
    links = [lk["id"] for lk in c.get("links") or []]
    joints = list(c.get("joints") or [])
    if len(set(links)) != len(links):
        out.append("杆件 id 有重复")
    jids = [j["id"] for j in joints]
    if len(set(jids)) != len(jids):
        out.append("关节 id 有重复")
    if set(links) & set(jids):
        out.append("杆件与关节用了同一个 id：" + "、".join(sorted(set(links) & set(jids))))
    known = set(links)
    children: dict[str, int] = {}
    for j in joints:
        if j["parent"] != "base" and j["parent"] not in known:
            out.append(f"关节 {j['id']} 的父件 {j['parent']} 不存在")
        if j["child"] not in known:
            out.append(f"关节 {j['id']} 的子件 {j['child']} 不存在")
        if j["child"] == j["parent"]:
            out.append(f"关节 {j['id']} 的父件与子件相同")
        children[j["child"]] = children.get(j["child"], 0) + 1
        if float(np.linalg.norm(j["axis"])) < 1e-9:
            out.append(f"关节 {j['id']} 的轴线是零向量")
    for lk in links:
        n = children.get(lk, 0)
        if n == 0:
            out.append(f"杆件 {lk} 没有关节带动（每根杆件都要由一个关节连到父件上）")
        elif n > 1:
            out.append(f"杆件 {lk} 被 {n} 个关节带动（只能有一个，闭链机构不在 robot-concept/1 里）")
    if not out:
        parent_of = {j["child"]: j["parent"] for j in joints}
        for lk in links:
            seen, cur = set(), lk
            while cur != "base":
                if cur in seen:
                    out.append(f"杆件 {lk} 往上找不到 base（有环）")
                    break
                seen.add(cur)
                cur = parent_of[cur]
    ee = c.get("end_effector") or {}
    if ee.get("parent") and ee["parent"] not in known:
        out.append(f"末端装在不存在的杆件 {ee['parent']} 上")
    jtype = {j["id"]: j for j in joints}
    for t in c.get("tasks") or []:
        if t.get("type") != "joint_move":
            continue
        for side in ("from", "to"):
            for jid, v in (t.get(side) or {}).items():
                j = jtype.get(jid)
                if j is None:
                    out.append(f"动作“{t['name']}”里的关节 {jid} 不存在")
                    continue
                rng = j.get("range_deg") or j.get("range_mm")
                if rng and not rng[0] - 1e-9 <= v <= rng[1] + 1e-9:
                    out.append(f"动作“{t['name']}”里关节 {jid} 的 {v:g} 超出行程 [{rng[0]:g}, {rng[1]:g}]")
    kinds = {j["type"] for j in joints}
    if c.get("kind") == "mobile_base" and "wheel" not in kinds:
        out.append("移动底盘没有轮子关节")
    if c.get("kind") in ("serial_arm", "gantry") and "wheel" in kinds:
        out.append(f"{c['kind']} 里有轮子关节（移动的请用 mobile_base）")
    return out


def build(c: Mapping) -> Model:
    from kb.validation import errors

    errs = list(errors("robot-concept.schema.json", dict(c)))
    if errs:
        raise ConceptError("整机方案不符合格式：" + "；".join(errs[:5]))
    probs = structure_problems(c)
    if probs:
        raise ConceptError("整机方案结构有问题：" + "；".join(probs))
    raw = {j["id"]: j for j in c["joints"]}
    order: list[Joint] = []
    placed = {"base"}
    pending = list(c["joints"])
    while pending:
        nxt = [j for j in pending if j["parent"] in placed]
        for j in nxt:
            rng = j.get("range_deg") or j.get("range_mm")
            ax = np.array(j["axis"], float)
            order.append(Joint(j["id"], j["type"], j["parent"], j["child"], np.array(j["origin_mm"], float),
                               ax / np.linalg.norm(ax), rng[0] if rng else None, rng[1] if rng else None,
                               j.get("radius_mm"), raw[j["id"]]))
            placed.add(j["child"])
        pending = [j for j in pending if j not in nxt]
    by_child = {j.child: j for j in order}
    links = {lk["id"]: lk for lk in c["links"]}
    ee = c.get("end_effector") or {}
    tool = ee.get("parent") or _leaf(order, links)
    off = np.array(ee.get("offset_mm") or [0, 0, 0], float)
    return Model(dict(c), order, by_child, links, tool, off)


def _leaf(order: list[Joint], links: Mapping) -> str | None:
    """末端默认装在运动链最末一根杆件上：不经过轮子的叶子杆件只有一根时就是它"""
    has_child = {j.parent for j in order}
    leaves = [lk for lk in links if lk not in has_child]
    wheel_children = {j.child for j in order if j.type == "wheel"}
    leaves = [lk for lk in leaves if lk not in wheel_children]
    return leaves[0] if len(leaves) == 1 else None


def _rot(axis: np.ndarray, ang: float) -> np.ndarray:
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    return np.array([[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                     [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                     [z * x * C - y * s, z * y * C + x * s, c + z * z * C]])


def fk(m: Model, q: Mapping[str, float] | None = None) -> dict[str, np.ndarray]:
    """各杆件坐标系的位姿（4×4，基座坐标系，mm）。q 里没写的关节取 0"""
    q = q or {}
    T = {"base": np.eye(4)}                          # 基座坐标系在安装面上；base.height_mm 只给外形用
    for j in m.joints:
        A = np.eye(4)
        A[:3, 3] = j.origin
        M = np.eye(4)
        v = float(q.get(j.id, 0.0))
        if j.type == "prismatic":
            M[:3, 3] = j.axis * v
        else:
            M[:3, :3] = _rot(j.axis, math.radians(v))
        T[j.child] = T[j.parent] @ A @ M
    return T


def chain(m: Model, link: str | None = None) -> list[Joint]:
    """从基座到某杆件经过的关节（不含轮子）"""
    link = link or m.tool_link
    if link is None:
        raise ConceptError("末端装在哪根杆件上不明确（有多根叶子杆件）：请写 end_effector.parent")
    out, cur = [], link
    while cur != "base":
        j = m.by_child[cur]
        if j.type != "wheel":
            out.append(j)
        cur = j.parent
    return list(reversed(out))


def tool_point(m: Model, q: Mapping[str, float] | None = None) -> np.ndarray:
    T = fk(m, q)[m.tool_link] if m.tool_link else None
    if T is None:
        raise ConceptError("末端装在哪根杆件上不明确：请写 end_effector.parent")
    return (T @ np.append(m.tool_offset, 1.0))[:3]


def jacobian(m: Model, q: Mapping[str, float], joints: list[Joint] | None = None) -> np.ndarray:
    """末端位置对各关节的雅可比（3 × n；转动关节按每弧度 mm、移动关节按每 mm mm）"""
    joints = joints if joints is not None else chain(m)
    T = fk(m, q)
    p = tool_point(m, q)
    cols = []
    for j in joints:
        Tp = T[j.parent]
        o = (Tp @ np.append(j.origin, 1.0))[:3]
        a = Tp[:3, :3] @ j.axis                     # 关节轴线在零件转动前后都不变（绕自身轴转）
        cols.append(a if j.type == "prismatic" else np.cross(a, p - o))
    return np.array(cols).T if cols else np.zeros((3, 0))


def singular_values(m: Model, q: Mapping[str, float]) -> np.ndarray:
    J = jacobian(m, q)
    return np.linalg.svd(J, compute_uv=False) if J.size else np.zeros(0)


def in_range(j: Joint, v: float) -> bool:
    return (j.lo is None or v >= j.lo - 1e-9) and (j.hi is None or v <= j.hi + 1e-9)


def _clamp(j: Joint, v: float) -> float:
    if j.lo is not None:
        v = max(v, j.lo)
    if j.hi is not None:
        v = min(v, j.hi)
    return v


def _seeds(joints: list[Joint], n: int) -> list[dict]:
    rng = np.random.default_rng(20261122)            # 固定种子：结果可复现
    out = [{j.id: _clamp(j, 0.0) for j in joints},
           {j.id: (j.lo + j.hi) / 2 if j.lo is not None and j.hi is not None else 0.0 for j in joints}]
    for _ in range(n):
        out.append({j.id: float(rng.uniform(j.lo, j.hi)) if j.lo is not None and j.hi is not None
                    else float(rng.uniform(-180, 180)) for j in joints})
    return out


def ik(m: Model, target, q0: Mapping[str, float] | None = None, *, restarts: int = 24) -> tuple[dict | None, float]:
    """末端到 target（mm）的一组关节值（在行程内）：阻尼最小二乘，从 q0 与若干固定起点出发；返回 (q 或 None, 最小误差 mm)"""
    joints = chain(m)
    target = np.asarray(target, float)
    starts = ([dict(q0)] if q0 else []) + _seeds(joints, restarts)
    best_err = math.inf
    for s in starts:
        q = {j.id: _clamp(j, float(s.get(j.id, 0.0))) for j in joints}
        for _ in range(IK_ITER):
            e = target - tool_point(m, q)
            err = float(np.linalg.norm(e))
            if err < IK_TOL_MM:
                break
            J = jacobian(m, q, joints)
            scale = np.array([180 / math.pi if j.type != "prismatic" else 1.0 for j in joints])
            JJ = J @ J.T
            lam = IK_DAMP * (np.trace(JJ) / 3 + 1.0)
            dq = J.T @ np.linalg.solve(JJ + lam * np.eye(3), e)
            for j, d, k in zip(joints, dq, scale):
                q[j.id] = _clamp(j, q[j.id] + float(d) * k)
        err = float(np.linalg.norm(target - tool_point(m, q)))
        best_err = min(best_err, err)
        if err < IK_TOL_MM:
            return q, err
    return None, best_err
