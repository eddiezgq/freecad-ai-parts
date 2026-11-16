"""零件特征识别（ADR-0093 补充十一第 3 步）：从 STEP 认出工业零件上常见的结构，给 AI 起草算例当依据。

确定性代码，不调用 LLM：
- 每个面：类型、面积、法向（指向零件外）、圆柱半径与轴线、凹（孔、座）还是凸（轴段、外圆）；
- 归纳：轴段（同轴的凸圆柱）、孔与座（凹圆柱，按同轴合并）、孔组（同径平行孔，轴心落在一个圆上 → 分布圆直径）、
  配合座（直径与零件库里外购件的配合尺寸或包络外径对上）、疑似螺纹底孔（直径 ≈ 粗牙螺纹的 D − P，只标“疑似”，由人确认）、
  安装面与端面（零件包围盒两端的大平面）、圆角与倒角（环面、小锥面、小半径的局部圆柱面）、键槽或平台（在轴段半径以内、平行于轴线的平面）。

只报看得出来的：认不出的不猜（例如 STEP 里没有螺纹，就只说“疑似”）。
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Iterable

import numpy as np

# 粗牙普通螺纹的螺距（GB/T 193、ISO 261 粗牙系列）：底孔约为 D − P（只用来标“疑似螺纹底孔”，须人确认）
COARSE_PITCH = {3: 0.5, 4: 0.7, 5: 0.8, 6: 1.0, 8: 1.25, 10: 1.5, 12: 1.75, 14: 2.0, 16: 2.0, 20: 2.5, 24: 3.0}
TAP_TOL_MM = 0.15
FIT_TOL_MM = 0.05


def _surface_point(gmsh, tag):
    """面上一点与该点的单位法向（参数域中点）"""
    lo, hi = gmsh.model.getParametrizationBounds(2, tag)
    uv = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2]
    p = np.array(gmsh.model.getValue(2, tag, uv), float)
    n = np.array(gmsh.model.getNormal(tag, uv), float)[:3]
    return p, n / (np.linalg.norm(n) or 1.0)


def _outward(gmsh, vols, p, n, eps):
    """法向是否指向零件外：沿法向挪一小步，不在任何实体里就是朝外"""
    q = p + eps * n
    inside = any(gmsh.model.isInside(3, t, list(q)) for _d, t in vols)
    return not inside


def _faces(step_path):
    from analysis.fea.geometry import _LOCK, _axis_fit, _gmsh, load_step

    out = []
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        vols = load_step(gmsh, step_path, tmp)
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = math.dist(bb[:3], bb[3:])
        gmsh.option.setNumber("Mesh.MeshSizeMax", diag / 40)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.model.mesh.generate(2)
        eps = diag * 1e-4
        for _d, tag in gmsh.model.getEntities(2):
            typ = gmsh.model.getType(2, tag)
            kind = {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere", "Torus": "torus"}.get(typ, "other")
            f = {"id": int(tag), "kind": kind, "area_mm2": float(gmsh.model.occ.getMass(2, tag)),
                 "center": list(gmsh.model.occ.getCenterOfMass(2, tag)), "bbox": list(gmsh.model.getBoundingBox(2, tag))}
            try:
                p, n = _surface_point(gmsh, tag)
                if not _outward(gmsh, vols, p, n, eps):
                    n = -n
                f["point"], f["normal"] = p.tolist(), n.tolist()
            except Exception:  # noqa: BLE001, S110 — 个别面取不到法向，其余信息照给
                pass
            if kind == "cylinder":
                _axis_fit(gmsh, tag, f)
                if "axis" in f and "point" in f:
                    d = np.array(f["axis"])
                    rv = np.array(f["point"]) - np.array(f["axis_origin"])
                    rv -= d * np.dot(rv, d)
                    f["concave"] = bool(np.dot(rv, f["normal"]) < 0)      # 法向朝轴线：孔、座
                    ext = [np.dot(np.array(c), d) for c in _corners(f["bbox"])]
                    f["length_mm"] = float(max(ext) - min(ext))
                    full = 2 * math.pi * f["radius_mm"] * max(f["length_mm"], 1e-9)
                    f["coverage"] = min(1.0, f["area_mm2"] / full)
            out.append(f)
        info = {"bbox_mm": list(bb), "diag_mm": diag, "volume_mm3": sum(gmsh.model.occ.getMass(3, t) for _d, t in vols)}
    return out, info


def _corners(bb):
    x0, y0, z0, x1, y1, z1 = bb
    return [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]


def _coaxial(a, b, tol=None):
    tol = tol if tol is not None else max(0.05, 0.002 * a.get("radius_mm", 0))   # 局部圆柱面的轴线拟合有误差
    da, db = np.array(a["axis"]), np.array(b["axis"])
    if abs(abs(np.dot(da, db)) - 1) > 1e-3:
        return False
    v = np.array(b["axis_origin"]) - np.array(a["axis_origin"])
    return float(np.linalg.norm(v - da * np.dot(v, da))) < tol


def library_fits(components: Iterable[dict]) -> list[tuple[float, bool, str]]:
    """零件库里外购件的配合尺寸与包络外径：[(直径 mm, 是否“凸”的一方, 说明)]。凸的（轴、凸止口、外形）配我们零件上的孔 / 座，
    凹的（孔、凹止口）配我们零件上的轴段"""
    out = []

    def val(v):
        d = v.get("value", v.get("nominal")) if isinstance(v, dict) else None
        return float(d) if isinstance(d, (int, float)) and not isinstance(d, bool) else None
    for c in components:
        name = f"{c.get('model', c.get('id'))}"
        for p in c.get("ports") or []:
            spec = p.get("spec") or {}
            d = val(spec.get("diameter_mm"))
            if d and p.get("type") in ("mechanical.cyl_male", "mechanical.cyl_female"):
                male = p["type"] == "mechanical.cyl_male"
                out.append((d, male, f"{name} 的{'轴' if male else '孔'}（{p['id']}）Ø{d:g}"))
            d = val(spec.get("pilot_diameter_mm"))
            kind = (spec.get("pilot_kind") or {}).get("value")
            if d and kind in ("male", "female"):
                out.append((d, kind == "male", f"{name} 的{'凸' if kind == 'male' else '凹'}止口（{p['id']}）Ø{d:g}"))
        for part in (c.get("envelope") or {}).get("parts") or []:
            d = val(part.get("diameter_mm"))
            if d:
                out.append((d, True, f"{name} 外形 Ø{d:g}"))
    return out


def recognize(step_path, library: Iterable[dict] = ()) -> dict:
    """认出零件特征。返回 {"faces": [...], "features": [...], "text": 给人和给 AI 看的清单, "bbox_mm", "volume_mm3"}"""
    faces, info = _faces(step_path)
    diag = info["diag_mm"]
    fits = library_fits(library)
    feats = []

    cyl = [f for f in faces if f["kind"] == "cylinder" and "axis" in f and "concave" in f]
    small = [f for f in cyl if f["radius_mm"] < 0.03 * diag and f.get("coverage", 1) < 0.3]
    rounds = [f for f in faces if f["kind"] == "torus"] + small
    chamf = [f for f in faces if f["kind"] == "cone" and f["area_mm2"] < 0.01 * diag ** 2]
    if rounds:
        feats.append({"type": "fillet", "faces": [f["id"] for f in rounds], "text": f"圆角 {len(rounds)} 处"})
    if chamf:
        feats.append({"type": "chamfer", "faces": [f["id"] for f in chamf], "text": f"倒角 {len(chamf)} 处"})
    skip = {f["id"] for f in small}
    main = [f for f in cyl if f["id"] not in skip]

    # 同轴、同凹凸的圆柱面合并成一个“段”（轴段、孔）
    def span(f):
        d = np.array(f["axis"])
        e = [float(np.dot(np.array(c), d)) for c in _corners(f["bbox"])]
        return min(e), max(e)
    groups = []
    for f in main:                                   # 同轴、同径、同凹凸、轴向连着的面才合成一段（两个分开的轴承位不合并）
        lo, hi = span(f)
        for g in groups:
            h = g[0]
            glo, ghi = min(span(x)[0] for x in g), max(span(x)[1] for x in g)
            if h["concave"] == f["concave"] and abs(h["radius_mm"] - f["radius_mm"]) < 1e-3 and _coaxial(h, f) \
                    and lo <= ghi + 1e-3 and hi >= glo - 1e-3:
                g.append(f)
                break
        else:
            groups.append([f])
    holes = []
    for g in groups:
        f0 = g[0]
        dia = 2 * f0["radius_mm"]
        length = sum(f["length_mm"] for f in g)
        ids = [f["id"] for f in g]
        item = {"faces": ids, "diameter_mm": round(dia, 3), "length_mm": round(length, 2),
                "axis": [round(x, 4) for x in f0["axis"]], "axis_origin": [round(x, 3) for x in f0["axis_origin"]]}
        match = [lab for d, male, lab in fits if abs(d - dia) <= FIT_TOL_MM and male == f0["concave"]]
        if f0["concave"]:
            item["type"] = "bore"
            tap = [f"M{D}" for D, P in COARSE_PITCH.items() if abs(dia - (D - P)) <= TAP_TOL_MM]
            text = f"孔 / 座 Ø{dia:g}，深 {length:.1f}，面 {ids}"
            if tap and dia < 25:
                item["thread_suspect"] = tap
                text += f"（直径与 {'/'.join(tap)} 粗牙螺纹底孔相符：疑似螺纹孔，须人确认）"
            holes.append(item)
        else:
            item["type"] = "shaft_segment"
            text = f"外圆 / 轴段 Ø{dia:g}，长 {length:.1f}，面 {ids}"
        if match:
            item["fits"] = match
            text += "；直径与零件库 " + "、".join(match[:3]) + " 相符（可能的配合面）"
        item["text"] = text
        feats.append(item)

    # 孔组：同径、轴线平行的孔 ≥ 3 个，轴心在一个圆上
    by_d = {}
    for h in holes:
        by_d.setdefault((round(h["diameter_mm"], 2), tuple(np.round(np.abs(h["axis"]), 3))), []).append(h)
    for (d, ax), hs in by_d.items():
        if len(hs) < 3:
            continue
        a = np.array(hs[0]["axis"])
        e1 = np.cross(a, [1, 0, 0] if abs(a[0]) < 0.9 else [0, 1, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(a, e1)
        pts = np.array([[np.dot(h["axis_origin"], e1), np.dot(h["axis_origin"], e2)] for h in hs])
        A = np.c_[2 * pts, np.ones(len(pts))]
        (cx, cy, k), *_ = np.linalg.lstsq(A, (pts ** 2).sum(1), rcond=None)
        r = math.sqrt(max(k + cx * cx + cy * cy, 0))
        resid = float(np.max(np.abs(np.linalg.norm(pts - [cx, cy], axis=1) - r)))
        if resid < 0.05 and r > 0:
            center = (cx * e1 + cy * e2).tolist()
            feats.append({"type": "hole_pattern", "faces": [i for h in hs for i in h["faces"]], "count": len(hs),
                          "diameter_mm": d, "pcd_mm": round(2 * r, 3), "center": [round(x, 3) for x in center],
                          "text": f"孔组：{len(hs)} × Ø{d:g}，分布圆 Ø{2 * r:.2f}"
                          + (f"（疑似 {'/'.join(hs[0]['thread_suspect'])} 螺纹孔，须人确认）" if hs[0].get("thread_suspect") else "")})

    # 安装面、端面：包围盒两端的平面
    bb = np.array(info["bbox_mm"])
    for f in faces:
        if f["kind"] != "plane" or "normal" not in f:
            continue
        n = np.array(f["normal"])
        ax = int(np.argmax(np.abs(n)))
        if abs(n[ax]) < 0.999:
            continue
        side = 1 if n[ax] > 0 else 0
        at_end = abs(f["center"][ax] - bb[ax + 3 * side]) < 1e-3 * diag
        if at_end:
            feats.append({"type": "end_face", "faces": [f["id"]], "axis": "xyz"[ax], "side": "+" if side else "-",
                          "area_mm2": round(f["area_mm2"], 1),
                          "text": f"端面 / 安装面：面 {f['id']}，朝 {'+' if side else '-'}{'xyz'[ax]}，面积 {f['area_mm2']:.0f} mm²"})

    # 台阶面：法向与某段轴线平行、又不在零件两端的平面（轴肩、孔底、法兰面）
    ends = {i for x in feats if x["type"] == "end_face" for i in x["faces"]}
    axes = [np.array(x["axis"]) for x in feats if x.get("type") in ("shaft_segment", "bore")]
    for f in faces:
        if f["kind"] == "plane" and "normal" in f and f["id"] not in ends and \
                any(abs(abs(np.dot(a, f["normal"])) - 1) < 1e-3 for a in axes):
            feats.append({"type": "shoulder", "faces": [f["id"]], "area_mm2": round(f["area_mm2"], 1),
                          "text": f"台阶面（轴肩 / 孔底 / 法兰面）：面 {f['id']}，面积 {f['area_mm2']:.0f} mm²"})

    # 键槽或平台：平面法向垂直于某轴段的轴线，且平面在轴段半径以内
    shafts = [g for g in feats if g.get("type") == "shaft_segment"]
    for f in faces:
        if f["kind"] != "plane" or "normal" not in f:
            continue
        for s in shafts:
            a = np.array(s["axis"])
            if abs(np.dot(a, f["normal"])) > 1e-3:
                continue
            v = np.array(f["center"]) - np.array(s["axis_origin"])
            dist = float(np.linalg.norm(v - a * np.dot(v, a)))
            lo = min(np.dot(np.array(c), a) for c in _corners(f["bbox"]))
            hi = max(np.dot(np.array(c), a) for c in _corners(f["bbox"]))
            o = float(np.dot(np.array(s["axis_origin"]), a))
            radial = [float(np.linalg.norm((np.array(c) - s["axis_origin"]) - a * np.dot(np.array(c) - s["axis_origin"], a)))
                      for c in _corners(f["bbox"])]
            inside = max(radial) <= s["diameter_mm"] / 2 * 1.05      # 整个平面都在轴段的外圆以内（包围盒角点允许 5 % 余量）
            if dist < s["diameter_mm"] / 2 - 1e-3 and inside and lo >= o - s["length_mm"] and hi <= o + s["length_mm"]:
                feats.append({"type": "keyway_or_flat", "faces": [f["id"]], "shaft_diameter_mm": s["diameter_mm"],
                              "text": f"键槽或平台：面 {f['id']}，在 Ø{s['diameter_mm']:g} 轴段上"})
                break

    lines = [f"零件包围盒 {[round(x, 1) for x in info['bbox_mm']]} mm，体积 {info['volume_mm3']:.0f} mm³，{len(faces)} 个面"]
    lines += [f"- {x['text']}" for x in feats]
    return {"faces": faces, "features": feats, "text": "\n".join(lines), "bbox_mm": info["bbox_mm"],
            "volume_mm3": info["volume_mm3"]}
