"""从零件的几何面找运动副候选（ADR-0097 D5b，补充十一）。确定性、纯 Python，不碰 FreeCAD、不调 LLM。

输入每个零件的面摘要（freecad_addon/fc/mbd_mates.py 从实体里取）：

    {"id", "label", "volume_mm3",
     "faces": [{"kind": "cylinder", "point": [3], "axis": [3], "radius", "t": [t0, t1], "convex": bool},
               {"kind": "plane", "point": [3], "normal": [3]（朝实体外）, "area"},
               {"kind": "sphere", "center": [3], "radius", "convex": bool}]}

规则（都是几何事实，不猜意图）：
- 一个零件的外圆柱面（轴、销）与另一个零件的内圆柱面（孔）同轴、半径差在配合间隙内、轴向有重叠 → 转动副候选（备选圆柱副）；
- 外球面与内球面同心、半径差在间隙内 → 球副候选；
- 两零件之间没有同轴配合，但有两组以上法向不平行的贴合平面（法向相反、共面）→ 移动副候选，方向为两法向的叉积；
- 同一对零件有两条以上不同轴线的轴孔配合 → 固定候选（两个销钉定位，转不动）。
"""

from __future__ import annotations

import itertools

import numpy as np

LIN_TOL_MM = 1e-3            # 同轴、共面、同心的位置容差
ANG_TOL = 1e-6               # 平行的方向容差（|sin|）
GAP_MAX_MM = 0.5             # 轴孔、球窝半径差上限（配合间隙）
GAP_REL = 0.05


def _u(v):
    a = np.asarray(v, float)
    return a / np.linalg.norm(a)


def _parallel(a, b):
    return np.linalg.norm(np.cross(a, b)) < ANG_TOL


def _gap_ok(r_shaft, r_hole):
    g = r_hole - r_shaft
    return -LIN_TOL_MM <= g <= max(GAP_MAX_MM, GAP_REL * r_hole)


def _coaxial(fa, fb):
    """外圆柱 fa、内圆柱 fb 同轴且轴向有重叠：返回 (轴线上一点, 轴向, 重叠段中点) 或 None"""
    a, b = _u(fa["axis"]), _u(fb["axis"])
    if not _parallel(a, b):
        return None
    pa, pb = np.asarray(fa["point"], float), np.asarray(fb["point"], float)
    d = pb - pa
    if np.linalg.norm(d - (d @ a) * a) > LIN_TOL_MM:
        return None
    if not _gap_ok(fa["radius"], fb["radius"]):
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


def find_candidates(parts: list[dict]) -> dict:
    """全部零件 → {"candidates": [...], "ground": 建议的机架, "unconnected": [...]}"""
    cands = []
    for A, B in itertools.combinations(parts, 2):
        cands += pair_candidates(A, B)
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
