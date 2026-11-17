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
        gmsh.option.restoreDefaults()                 # 选项是全局的：别处设过的网格尺寸下限、单元阶次会改变面的识别，先复位
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
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
    def span(f, d):                                   # 沿方向 d 的范围（d 取所比那一段的轴线：拟合出的轴线正负号不一定相同）
        e = [float(np.dot(np.array(c), d)) for c in _corners(f["bbox"])]
        return min(e), max(e)
    groups = []
    for f in main:                                   # 同轴、同径、同凹凸、轴向连着的面才合成一段（两个分开的轴承位不合并）
        for g in groups:
            h = g[0]
            d = np.array(h["axis"])
            lo, hi = span(f, d)
            glo, ghi = min(span(x, d)[0] for x in g), max(span(x, d)[1] for x in g)
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
        d0 = np.array(f0["axis"])                    # 段长取各面沿轴线范围的并（面有重叠时不重复计）
        length = max(span(f, d0)[1] for f in g) - min(span(f, d0)[0] for f in g)
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
            text += "；直径与零件库 {} 相符（可能的配合面）".format("、".join(match[:3]))
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


# ---------------------------------------------------------------- 壳（中面）与梁（轴线）（ADR-0096 第 1 步）

def _adjacency(step_path) -> tuple[dict[int, list[int]], dict[int, list[int]], dict[int, list[int]]]:
    """（边 → 相邻的面, 边 → 两端顶点, 顶点 → 相连的边）；编号与 analysis.fea.geometry.faces 一致（同样的读入方式）"""
    from analysis.fea.geometry import _LOCK, _gmsh, load_step

    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_path, tmp, require_solid=False)
        e_faces, e_verts, v_edges = {}, {}, {}
        for _d, e in gmsh.model.getEntities(1):
            up, down = gmsh.model.getAdjacencies(1, e)
            e_faces[int(e)] = [int(x) for x in up]
            e_verts[int(e)] = [int(x) for x in down]
            for v in down:
                v_edges.setdefault(int(v), []).append(int(e))
    return e_faces, e_verts, v_edges


def _xyz(p) -> str:
    return "(" + ", ".join(f"{x:.1f}" for x in p) + ")"


def _dir_text(d) -> str:
    """方向写法：沿坐标轴的写 ±x / ±y / ±z，否则写单位向量"""
    d = np.asarray(d, float)
    k = int(np.argmax(np.abs(d)))
    if abs(abs(d[k]) - 1) < 1e-6:
        return ("+" if d[k] > 0 else "-") + "xyz"[k]
    return "[" + ", ".join(f"{x:.3f}" for x in d) + "]"


def recognize_thin(step_path) -> dict:
    """壳的中面、梁的轴线：认出可以加支承、载荷的地方。
    壳：每个面（中面）、每条边（边界边只属于一个面，折边 / 交线属于两个以上）；
    梁：每根杆件（边：长度、方向、两端坐标）、每个顶点（只连一根杆件的是端点，连几根的是节点）。
    特征写明作用位置的种类：faces / edges / vertices（算例里固定、力、强制位移可作用在边、顶点上，ADR-0095）。"""
    from analysis.fea.geometry import faces as geo_faces

    fs, info = geo_faces(step_path)
    kind = info["geometry_kind"]
    if kind == "solid":
        raise ValueError("这是实体零件：用 recognize")
    e_faces, e_verts, v_edges = _adjacency(step_path)
    edges = {e["id"]: e for e in info["edge_list"]}
    verts = {v["id"]: v for v in info["vertex_list"]}
    feats = []
    if kind == "shell":
        for f in fs:
            shape = {"plane": "平面", "cylinder": "圆柱面"}.get(f["kind"], "曲面")
            extra = f"，法向 {_dir_text(f['normal'])}" if f["kind"] == "plane" and "normal" in f else ""
            if f["kind"] == "cylinder" and "axis" in f:
                extra = f"，半径 {f['radius_mm']:g}，轴线 {_dir_text(f['axis'])}"
            feats.append({"type": "shell_face", "faces": [f["id"]], "bbox": f["bbox"],
                          "text": f"壳面（中面）：面 {f['id']}，{shape}{extra}，面积 {f['area_mm2']:.0f} mm²"})
        for eid, e in sorted(edges.items()):
            n = len(e_faces.get(eid, []))
            what = "壳的边界边" if n <= 1 else f"壳的折边 / 交线（{n} 个面共用）"
            ends = [verts[v]["point"] for v in e_verts.get(eid, []) if v in verts]
            shape = {"line": "直线", "circle": "圆弧"}.get(e["kind"], "曲线")
            feats.append({"type": "shell_edge", "edges": [eid], "bbox": e["bbox"], "boundary": n <= 1,
                          "text": f"{what}：边 {eid}，{shape}，长 {e['length_mm']:.1f}，中点 {_xyz(e['center'])}"
                          + (f"，两端 {_xyz(ends[0])}–{_xyz(ends[1])}" if len(ends) == 2 else "")})
    else:
        for eid, e in sorted(edges.items()):
            ends = [verts[v]["point"] for v in e_verts.get(eid, []) if v in verts]
            item = {"type": "beam_member", "edges": [eid], "bbox": e["bbox"], "length_mm": e["length_mm"]}
            text = f"杆件：边 {eid}，{ {'line': '直线', 'circle': '圆弧'}.get(e['kind'], '曲线') }，长 {e['length_mm']:.1f}"
            if e["kind"] == "line" and len(ends) == 2:
                d = np.array(ends[1]) - np.array(ends[0])
                d = d / (np.linalg.norm(d) or 1.0)
                if d[int(np.argmax(np.abs(d)))] < 0:
                    d = -d
                item["direction"] = [round(float(x), 6) + 0.0 for x in d]
                text += f"，方向 {_dir_text(d)}"
            if len(ends) == 2:
                text += f"，两端 {_xyz(ends[0])}–{_xyz(ends[1])}"
            item["text"] = text
            feats.append(item)
        for vid, v in sorted(verts.items()):
            n = len(v_edges.get(vid, []))
            typ = "beam_end" if n <= 1 else "beam_joint"
            p = v["point"]
            feats.append({"type": typ, "vertices": [vid], "bbox": [*p, *p], "point": p,
                          "text": (f"梁的端点：顶点 {vid}，坐标 {_xyz(p)}" if n <= 1
                                   else f"梁的节点（{n} 根杆件相交）：顶点 {vid}，坐标 {_xyz(p)}")})
    head = (f"{'壳（STEP 是中面）' if kind == 'shell' else '梁（STEP 是轴线）'}；包围盒 {[round(x, 1) for x in info['bbox_mm']]} mm，"
            f"{len(fs)} 个面、{len(edges)} 条边、{len(verts)} 个顶点")
    return {"kind": kind, "faces": fs, "features": feats, "text": "\n".join([head] + [f"- {x['text']}" for x in feats]),
            "bbox_mm": info["bbox_mm"]}


def geometry_kind(step_path) -> str:
    """STEP 里是实体（solid）、只有曲面（shell，中面）还是只有曲线（beam，轴线）；只读入，不划网格"""
    from analysis.fea.geometry import _LOCK, _gmsh, load_step

    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        vols = load_step(gmsh, step_path, tmp, require_solid=False)
        return "solid" if vols else ("shell" if gmsh.model.getEntities(2) else "beam")
