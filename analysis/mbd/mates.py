"""从零件的几何面找运动副候选（ADR-0097 D5b，补充十一）。确定性、纯 Python，不碰 FreeCAD、不调 LLM。

输入每个零件的面摘要（freecad_addon/fc/mbd_mates.py 从实体里取）：

    {"id", "label", "volume_mm3",
     "faces": [{"kind": "cylinder", "point": [3], "axis": [3], "radius", "t": [t0, t1], "convex": bool},
               {"kind": "plane", "point": [3], "normal": [3]（朝实体外）, "area"},
               {"kind": "sphere", "center": [3], "radius", "convex": bool}]}

规则（都是几何事实，不猜意图）：
- 一个零件的外圆柱面（轴、销）与另一个零件的内圆柱面（孔）同轴、半径差在配合间隙内、轴向有重叠 → 转动副候选（备选圆柱副）；
  同时有法向垂直于轴线的贴合平面（键、花键侧面）→ 转不动：再有轴向止推面为固定，否则为移动副（沿轴线）；
- 外球面与内球面同心、半径差在间隙内 → 球副候选；
- 两零件之间没有同轴配合，但有两组以上法向不平行的贴合平面（法向相反、共面）→ 移动副候选，方向为两法向的叉积；
- 同一对零件有两条以上不同轴线的轴孔配合 → 固定候选（两个销钉定位，转不动）。
- 轴孔半径差 ≤ 孔径 1 % 才算配合；更大的是过孔，不当运动副。同一根外圆柱穿过两件的过孔、两件端面贴合 → 螺栓连接：两件固定，
  螺栓与其中一件固定。最后按候选算一次整体自由度，只靠一个转动副挂着的零件提示“局部自由度”。
"""

from __future__ import annotations

import itertools

import numpy as np

LIN_TOL_MM = 1e-3            # 同轴、共面、同心的位置容差
ANG_TOL = 1e-6               # 平行的方向容差（|sin|）
GAP_MAX_MM = 0.5             # 球窝半径差上限
GAP_REL = 0.05
FIT_REL = 0.01               # 轴孔半径差 ≤ 孔径的 1 % 算配合（线索第 66 条）；更大的是过孔，不当运动副
CLEAR_MAX_REL = 0.15         # 半径差 ≤ 孔径的 15 % 算过孔（螺栓、轴穿过），用来找“螺栓连接”


def _u(v):
    a = np.asarray(v, float)
    return a / np.linalg.norm(a)


def _parallel(a, b):
    return np.linalg.norm(np.cross(a, b)) < ANG_TOL


def _gap_ok(r_shaft, r_hole):
    """球窝：半径差在间隙内"""
    g = r_hole - r_shaft
    return -LIN_TOL_MM <= g <= max(GAP_MAX_MM, GAP_REL * r_hole)


def _fit(r_shaft, r_hole):
    """轴孔：'fit'（配合，半径差 ≤ 孔径 1 %）、'clearance'（过孔）或 None。
    《多体动力学》书第 39 章线索第 66 条（问渠 CAD 0.3.9 细则）：原来半径差上限 Ø20 以下恒为 0.5 mm（Ø4 时是半径的 25 %），
    M8 螺栓在 Ø9 过孔里、轴穿过 Ø20.6 过孔都被当成转动副，螺栓连接的两块板之间反而没有候选"""
    g = r_hole - r_shaft
    if g < -LIN_TOL_MM:
        return None
    if g <= max(FIT_REL * 2 * r_hole, LIN_TOL_MM):
        return "fit"
    if g <= CLEAR_MAX_REL * 2 * r_hole:
        return "clearance"
    return None


def _coaxial(fa, fb, kind="fit"):
    """外圆柱 fa、内圆柱 fb 同轴、半径差属于 kind（配合 / 过孔）且轴向有重叠：返回 (轴线上一点, 轴向, 重叠段中点) 或 None"""
    a, b = _u(fa["axis"]), _u(fb["axis"])
    if not _parallel(a, b):
        return None
    pa, pb = np.asarray(fa["point"], float), np.asarray(fb["point"], float)
    d = pb - pa
    if np.linalg.norm(d - (d @ a) * a) > LIN_TOL_MM:
        return None
    if _fit(fa["radius"], fb["radius"]) != kind:
        return None
    ta = sorted(fa["t"])
    sb = float(d @ a)                              # fb 的参数原点在 fa 轴上的位置
    tb = sorted(t * float(b @ a) + sb for t in fb["t"])
    lo, hi = max(ta[0], tb[0]), min(ta[1], tb[1])
    if hi - lo <= LIN_TOL_MM:
        return None
    return pa, a, pa + a * (lo + hi) / 2


def _same_line(p1, a1, p2, a2):
    if not _parallel(a1, a2):
        return False
    d = p2 - p1
    return np.linalg.norm(d - (d @ a1) * a1) < LIN_TOL_MM


def _plane_contacts(A, B):
    """两零件之间贴合的平面对（法向相反、共面）的法向（A 侧，去重平行的）"""
    normals = []
    for fa, fb in itertools.product(A["faces"], B["faces"]):
        if fa["kind"] != "plane" or fb["kind"] != "plane":
            continue
        na, nb = _u(fa["normal"]), _u(fb["normal"])
        if na @ nb > -1 + ANG_TOL:
            continue
        if abs((np.asarray(fb["point"], float) - np.asarray(fa["point"], float)) @ na) > LIN_TOL_MM:
            continue
        if not any(_parallel(na, n) for n in normals):
            normals.append(na)
    return normals


def _flat_contacts(A, B, axis):
    """轴孔配合的两零件之间：法向垂直于轴线的贴合平面有几组、有没有法向平行于轴线的（止推面）"""
    ns = _plane_contacts(A, B)
    side = sum(1 for n in ns if abs(n @ axis) < 1e-6)
    thrust = any(_parallel(n, axis) for n in ns)
    return side, thrust


def pair_candidates(A, B):
    """两个零件之间的候选（可能为空）"""
    out = []
    axes = []                                      # [(点, 轴, 中点, 证据)]
    for fa, fb in itertools.product(A["faces"], B["faces"]):
        if fa["kind"] != "cylinder" or fb["kind"] != "cylinder" or fa["convex"] == fb["convex"]:
            continue
        shaft, hole, who = (fa, fb, (A, B)) if fa["convex"] else (fb, fa, (B, A))
        hit = _coaxial(shaft, hole)
        if hit is None:
            continue
        p, a, mid = hit
        ev = (f"{who[0].get('label') or who[0]['id']} 的 Ø{2 * shaft['radius']:.4g} 外圆柱与 "
              f"{who[1].get('label') or who[1]['id']} 的 Ø{2 * hole['radius']:.4g} 孔同轴")
        for ax in axes:
            if _same_line(ax[0], ax[1], p, a):
                break
        else:
            axes.append((p, a, mid, ev))
    for fa, fb in itertools.product(A["faces"], B["faces"]):
        if fa["kind"] != "sphere" or fb["kind"] != "sphere" or fa["convex"] == fb["convex"]:
            continue
        ball, cup = (fa, fb) if fa["convex"] else (fb, fa)
        c1, c2 = np.asarray(ball["center"], float), np.asarray(cup["center"], float)
        if np.linalg.norm(c1 - c2) < LIN_TOL_MM and _gap_ok(ball["radius"], cup["radius"]):
            out.append({"type": "spherical", "point_mm": c1.tolist(), "alternatives": [],
                        "evidence": f"Ø{2 * ball['radius']:.4g} 球面与球窝同心"})
    if len(axes) == 1:
        p, a, mid, ev = axes[0]
        side, thrust = _flat_contacts(A, B, a)
        if side:
            # 《多体动力学》书第 39 章线索第 63 条（问渠 CAD 0.3.9 细则）：键侧两平面（法向 ⊥ 轴线）贴合时转不动，原来只看轴孔，
            # 滑键被当成转动副、移动副不在选项里。再有轴向止推面就固定，否则沿轴线移动
            if thrust:
                out.append({"type": "fixed", "point_mm": mid.tolist(), "alternatives": [],
                            "evidence": ev + f"；另有 {side} 组法向垂直于轴线的贴合平面（键、花键侧面）和轴向止推面，相对转不动也滑不动"})
            else:
                out.append({"type": "translational", "point_mm": mid.tolist(), "axis": a.tolist(), "alternatives": ["fixed"],
                            "evidence": ev + f"；另有 {side} 组法向垂直于轴线的贴合平面（键、花键侧面），转不动，只能沿轴线滑动"})
        else:
            out.append({"type": "revolute", "point_mm": mid.tolist(), "axis": a.tolist(), "alternatives": ["cylindrical"],
                        "evidence": ev + "；按转动副起草（如果轴向能滑动，改成圆柱副）"})
    elif len(axes) > 1:
        out.append({"type": "fixed", "point_mm": axes[0][2].tolist(), "alternatives": [],
                    "evidence": f"有 {len(axes)} 条不同轴线的轴孔配合，两零件相对转不动：" + "；".join(x[3] for x in axes)})
    if not axes and not out:
        normals, pts = [], []
        for fa, fb in itertools.product(A["faces"], B["faces"]):
            if fa["kind"] != "plane" or fb["kind"] != "plane":
                continue
            na, nb = _u(fa["normal"]), _u(fb["normal"])
            if na @ nb > -1 + ANG_TOL:
                continue
            if abs((np.asarray(fb["point"], float) - np.asarray(fa["point"], float)) @ na) > LIN_TOL_MM:
                continue
            if not any(_parallel(na, n) for n in normals):
                normals.append(na)
                pts.append(np.asarray(fa["point"], float))
        if len(normals) >= 2:
            d = None
            for n1, n2 in itertools.combinations(normals, 2):
                c = np.cross(n1, n2)
                if np.linalg.norm(c) > 1e-6:
                    c = c / np.linalg.norm(c)
                    if d is None:
                        d = c
                    elif not _parallel(c, d):
                        d = None
                        break
            if d is not None:
                out.append({"type": "translational", "point_mm": pts[0].tolist(), "axis": d.tolist(), "alternatives": [],
                            "evidence": f"{len(normals)} 组法向不同的贴合平面，只剩沿 {np.round(d, 6).tolist()} 能滑动"})
            else:
                out.append({"type": "fixed", "point_mm": pts[0].tolist(), "alternatives": [],
                            "evidence": "三个方向都有贴合平面，相对不能动（如果只是接触不是连接，请删掉）"})
    for c in out:
        c["part1"], c["part2"] = A["id"], B["id"]
    return out


def _clearance_axes(bolt, P):
    """bolt 的外圆柱穿过 P 的过孔：[(轴线上一点, 轴向)]"""
    out = []
    for fa, fb in itertools.product(bolt["faces"], P["faces"]):
        if fa["kind"] == "cylinder" and fb["kind"] == "cylinder" and fa["convex"] and not fb["convex"]:
            hit = _coaxial(fa, fb, "clearance")
            if hit is not None:
                out.append((hit[0], hit[1]))
    return out


def bolted_candidates(parts: list[dict], taken: set) -> list[dict]:
    """线索第 66 条：同一根外圆柱（螺栓、轴）穿过两件的过孔、两件之间有法向平行于它的贴合平面（端面压紧）→ 两件固定，
    螺栓与其中一件固定。taken：已有候选的零件对（不重复给）"""
    out, seen = [], set(taken)
    for bolt in parts:
        hits = [(P, _clearance_axes(bolt, P)) for P in parts if P is not bolt]
        hits = [(P, ax) for P, ax in hits if ax]
        for (P, axp), (Q, axq) in itertools.combinations(hits, 2):
            for p1, a1 in axp:
                if not any(_same_line(p1, a1, p2, a2) for p2, a2 in axq):
                    continue
                if not any(_parallel(n, a1) for n in _plane_contacts(P, Q)):
                    continue
                for X, Y, why in ((P, Q, f"{bolt.get('label') or bolt['id']} 穿过两件的过孔，两件端面贴合，按螺栓连接固定"),
                                  (bolt, P, f"{bolt.get('label') or bolt['id']} 在 {P.get('label') or P['id']} 的过孔里（不是配合），按紧固件固定")):
                    key = frozenset((X["id"], Y["id"]))
                    if key not in seen:
                        seen.add(key)
                        out.append({"type": "fixed", "point_mm": np.asarray(p1, float).tolist(), "alternatives": [], "evidence": why,
                                    "part1": X["id"], "part2": Y["id"]})
                break
    return out


DOF_OF = {"fixed": 0, "revolute": 1, "translational": 1, "cylindrical": 2, "spherical": 3, "universal": 2, "planar": 3}


def mobility(parts: list[dict], found: dict) -> dict:
    """按候选算整体自由度（Grübler：6(n−1) − Σ(6 − f)，只数约束不看几何，冗余要另看），并找“局部自由度”：
    只靠一个转动副连着别的零件、自己再没别的连接（螺栓、销绕自身轴转）"""
    cands, ground = found["candidates"], (found.get("ground") or {}).get("part")
    n = len(parts)
    dof = 6 * (n - 1) - sum(6 - DOF_OF.get(c["type"], 0) for c in cands) if n else 0
    deg = {p["id"]: [c for c in cands if p["id"] in (c["part1"], c["part2"])] for p in parts}
    local = [pid for pid, cs in deg.items() if pid != ground and len(cs) == 1 and cs[0]["type"] in ("revolute", "cylindrical")]
    return {"dof": dof, "local": local}


def find_candidates(parts: list[dict]) -> dict:
    """全部零件 → {"candidates": [...], "ground": 建议的机架, "unconnected": [...]}（整体自由度另用 mobility(parts, found)）"""
    cands = []
    for A, B in itertools.combinations(parts, 2):
        cands += pair_candidates(A, B)
    cands += bolted_candidates(parts, {frozenset((c["part1"], c["part2"])) for c in cands})
    for k, c in enumerate(cands, 1):
        c["id"] = f"c{k}"
    linked = {c["part1"] for c in cands} | {c["part2"] for c in cands}
    ground = None
    if parts:
        deg = {p["id"]: sum(1 for c in cands if p["id"] in (c["part1"], c["part2"])) for p in parts}
        big = max(parts, key=lambda p: (p.get("volume_mm3", 0.0), deg[p["id"]]))
        ground = {"part": big["id"], "reason": "体积最大的零件，按机架起草"}
    return {"candidates": cands, "ground": ground, "unconnected": [p["id"] for p in parts if p["id"] not in linked]}


def to_assembly_joints(found: dict, accepted: list[dict]) -> list[dict]:
    """人确认（或 AI 挑选、再经人确认）过的候选 → 建 Assembly 运动副用的条目。accepted: [{"id", "type"?, "name"?}]"""
    by_id = {c["id"]: c for c in found["candidates"]}
    out = []
    for a in accepted:
        c = by_id.get(a["id"])
        if c is None:
            raise ValueError(f"没有候选 {a['id']}")
        typ = a.get("type") or c["type"]
        if typ != c["type"] and typ not in c["alternatives"]:
            raise ValueError(f"候选 {a['id']} 只能是 {[c['type'], *c['alternatives']]}，不能改成 {typ}")
        out.append({"name": a.get("name") or f"{typ}_{c['part1']}_{c['part2']}", "type": typ, "part1": c["part1"],
                    "part2": c["part2"], "point_mm": c["point_mm"], "axis": c.get("axis", [0.0, 0.0, 1.0])})
    return out
