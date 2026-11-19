"""问渠CAM 在 FreeCAD 文档里的事（ADR-0104 产品化第 2 步）：从回转体读车削轮廓、画刀路、画仿真后的形状。

- 车削件约定轴线沿 Z，右端是 Z 最大处（程序 Z0），左端夹在卡盘里。
- 读轮廓只认圆柱面、圆锥面（倒角）：外圆柱面给各段直径与长度；比两边都小、宽度不超过 8 mm 的一段当成槽；
  内圆柱面从右端往里给内孔各段。螺纹在实体上通常不画，要手填。
- 刀路与仿真结果放在一个组 “WenQuestCAM” 里，再算一次会先清掉旧的。
"""

from __future__ import annotations

import itertools
import math

GROUP = "WenQuestCAM"
GROOVE_MAX_W = 8.0


class CamDocError(ValueError):
    pass


def turn_features(shape) -> dict:
    """回转体 → {"segments": [[d, L], …]（从左到右）, "chamfer_mm", "grooves": [...], "bore": [[d, 深], …] 或 []}"""
    bb = shape.BoundBox
    z0, z1 = bb.ZMin, bb.ZMax
    outer, inner, cones, inner_cones, curved = [], [], [], [], []
    face_grooves, fg_faces = _face_grooves(shape, z1)
    for f in shape.Faces:
        s = f.Surface
        name = type(s).__name__
        if name in ("Toroid", "Sphere", "BSplineSurface", "SurfaceOfRevolution") and not _is_inner(f):
            curved.append(f)                                # 外圆上的圆弧过渡等：按截面轮廓车
        if name not in ("Cylinder", "Cone") or any(f.isSame(g) for g in fg_faces):
            continue
        ax = s.Axis
        if abs(abs(ax.z) - 1) > 1e-6 or math.hypot(s.Center.x if name == "Cylinder" else s.Apex.x,
                                                      s.Center.y if name == "Cylinder" else s.Apex.y) > 1e-6:
            raise CamDocError("回转面的轴线不在 Z 轴上：车削件要让轴线沿 Z、过原点")
        fb = f.BoundBox
        if name == "Cone":
            if _is_inner(f):
                inner_cones.append((fb.ZMin, fb.ZMax))
            else:
                cones.append((fb.ZMin, fb.ZMax))
            continue
        r = s.Radius
        # 法向朝外（离开轴线）是外圆，朝里是内孔
        u, v = f.ParameterRange[0], (f.ParameterRange[2] + f.ParameterRange[3]) / 2
        p, n = f.valueAt(u, v), f.normalAt(u, v)
        (outer if (p.x * n.x + p.y * n.y) > 0 else inner).append((fb.ZMin, fb.ZMax, r))
    if not outer:
        raise CamDocError("没有找到外圆柱面：选中的不是回转体零件")
    outer.sort()
    segs = [[2 * r, za, zb] for za, zb, r in outer]
    # 倒角：两端的圆锥面，长度相同时当成 45° 倒角
    ch = 0.0
    ends = [c for c in cones if abs(c[0] - z0) < 1e-6 or abs(c[1] - z1) < 1e-6]      # 外圆两端的锥面（内孔口的倒角不算）
    if ends:
        ch = round(max(c[1] - c[0] for c in ends), 6)
        segs[0][1] = z0
        segs[-1][2] = z1
    grooves, keep = [], []
    for i, (d, za, zb) in enumerate(segs):
        w = zb - za
        if 0 < i < len(segs) - 1 and w <= GROOVE_MAX_W and d < segs[i - 1][0] and d < segs[i + 1][0]:
            grooves.append({"z": round(zb - z1, 6), "width": round(w, 6), "d": round(d, 6)})
            # 槽并进两边直径小的那一段（退刀槽开在小直径一侧的轴肩根部）；成品轮廓按没槽算，槽单独切
            if segs[i + 1][0] <= segs[i - 1][0]:
                segs[i + 1][1] = za
            else:
                keep[-1][2] = zb
            continue
        keep.append([d, za, zb])
    segments = [[round(d, 6), round(zb - za, 6)] for d, za, zb in keep]
    bore = []
    opens = any(abs(zb - z1) < 1e-6 for _za, zb, _r in inner) or any(abs(zb - z1) < 1e-6 for _za, zb in inner_cones)
    out = {"segments": segments, "chamfer_mm": ch, "grooves": grooves, "bore": bore, "length_mm": round(z1 - z0, 6),
           "z_right": z1}
    if face_grooves:
        out["face_grooves"] = face_grooves
    mid_cones = [c for c in cones if not (abs(c[0] - z0) < 1e-6 or abs(c[1] - z1) < 1e-6)]
    end_unequal = len({round(c[1] - c[0], 6) for c in ends}) > 1
    if mid_cones or curved or end_unequal:               # 外圆有锥面、圆弧或两端倒角不一样：按截面轮廓车（ADR-0106 Q3a）
        out["profile"] = outer_profile(shape, grooves)
    if not opens:
        return out                                          # 内孔要从右端开口
    if not inner_cones:
        for za, zb, r in sorted(inner, key=lambda x: -x[1]):
            if not bore and abs(zb - z1) > 1e-6:
                break
            bore.append([round(2 * r, 6), round(zb - za, 6)])
        return out
    # 内孔有锥面、倒角：按截面轮廓仿形镗（ADR-0106 Q3a）；segments 按轮廓每一段的较大直径给（选刀、工艺卡用）
    prof = bore_profile(shape)
    out["bore_profile"] = prof
    for (za, da), (zb, db) in itertools.pairwise(prof):
        if za - zb > 1e-9:
            bore.append([round(max(da, db), 6), round(za - zb, 6)])
    return out


def _face_grooves(shape, z1):
    """右端面上的端面槽：一个朝 +Z 的环形平面（槽底），内外各一圈圆柱面一直通到右端面。返回 ([{d_in, d_out, depth}], 这些面)"""
    out, faces = [], []
    cyls = [f for f in shape.Faces if type(f.Surface).__name__ == "Cylinder"]
    for f in shape.Faces:
        if type(f.Surface).__name__ != "Plane":
            continue
        n = f.normalAt(0, 0)
        zp = f.BoundBox.ZMin
        if abs(abs(n.z) - 1) > 1e-6 or n.z < 0 or zp >= z1 - 1e-6 or abs(f.BoundBox.ZMax - zp) > 1e-6:
            continue
        radii = sorted({round(e.Curve.Radius, 6) for e in f.Edges if type(e.Curve).__name__ == "Circle"})
        if len(radii) != 2:
            continue
        r1, r2 = radii
        walls = []
        for c in cyls:
            cb = c.BoundBox
            if abs(cb.ZMin - zp) < 1e-6 and abs(cb.ZMax - z1) < 1e-6:
                inner_side = _is_inner(c)
                if abs(c.Surface.Radius - r1) < 1e-6 and not inner_side or abs(c.Surface.Radius - r2) < 1e-6 and inner_side:
                    walls.append(c)
        if len(walls) == 2:
            out.append({"d_in": round(2 * r1, 6), "d_out": round(2 * r2, 6), "depth": round(z1 - zp, 6)})
            faces += walls + [f]
    return out, faces


def _section_segments(shape):
    import FreeCAD

    segs = []
    for w in shape.slice(FreeCAD.Vector(0, 1, 0), 0.0):
        pts = w.discretize(Deflection=0.002)
        for a, b in itertools.pairwise(pts):
            if a.x >= -1e-9 and b.x >= -1e-9:
                segs.append((a.x, a.z, b.x, b.z))
    return segs


def _crossings(segs, z):
    xs = sorted(ax + (bx - ax) * (z - az) / (bz - az) for ax, az, bx, bz in segs
                if min(az, bz) <= z < max(az, bz) and abs(bz - az) > 1e-12)
    return [x for x in xs if x > 1e-6]


def outer_profile(shape, grooves=(), step: float = 0.05) -> list[list[float]]:
    """外圆轮廓 [[t, d], …]（t 从左端 0 起向右，d 直径）：截面边界在每条水平线上最外的交点。
    退刀槽（单独切）按槽两边较小的那个直径填平，与 segments 的做法一致。"""
    bb = shape.BoundBox
    z0, z1 = bb.ZMin, bb.ZMax
    segs = _section_segments(shape)
    n = math.ceil((z1 - z0) / step)
    zs = [z0 + min(k * step, z1 - z0) for k in range(n + 1)]
    zs[0], zs[-1] = z0 + 1e-6, z1 - 1e-6
    pts = []
    for z in zs:
        xs = _crossings(segs, z)
        pts.append([z, 2 * xs[-1] if xs else 0.0])
    for g in grooves:
        zr = z1 + g["z"]
        za, zb = zr - g["width"], zr
        dl = next((d for z, d in reversed(pts) if z < za - 1e-6), None)
        dr = next((d for z, d in pts if z > zb + 1e-6), None)
        fill = min(x for x in (dl, dr) if x is not None)
        for q in pts:
            if za - 1e-6 <= q[0] <= zb + 1e-6:
                q[1] = fill
    from analysis.cam import paths as P

    return [[round(z - z0, 4), round(d, 4)] for z, d in P.simplify([(z, d) for z, d in pts], tol=2e-3)]


def _is_inner(face) -> bool:
    """回转面法向朝轴线 → 内孔一侧"""
    u = (face.ParameterRange[0] + face.ParameterRange[1]) / 2
    v = (face.ParameterRange[2] + face.ParameterRange[3]) / 2
    p, n = face.valueAt(u, v), face.normalAt(u, v)
    return (p.x * n.x + p.y * n.y) < 0


def bore_profile(shape, step: float = 0.05) -> list[list[float]]:
    """回转体在 XZ 半平面上的截面 → 内孔轮廓 [[z, d], …]（z 从右端孔口 0 往里为负，到孔底为止）。
    截面边界离散成折线，每隔 step 取一条水平线求交：交点两个以上时最小的那个是内孔半径。共线的点并掉，锥面、倒角是直线段，圆弧按折线。"""
    bb = shape.BoundBox
    z1 = bb.ZMax
    segs = _section_segments(shape)

    def inner_at(z):
        xs = _crossings(segs, z)                            # 半开区间：正好过顶点只算一次
        return xs[0] if len(xs) >= 2 else None

    n = math.ceil((z1 - bb.ZMin) / step)
    prof, last = [], None
    for k in range(n + 1):
        z = z1 - max(min(k * step, z1 - bb.ZMin - 1e-6), 1e-6)
        x = inner_at(z)
        if x is None:
            if last is not None:                            # 孔底：在最后一个有孔的位置和这里之间二分找准
                lo, hi = z, last
                for _ in range(40):
                    mid = (lo + hi) / 2
                    lo, hi = (mid, hi) if inner_at(mid) is None else (lo, mid)
                prof.append((round(hi - z1, 4), round(2 * inner_at(hi), 4)))
            break
        prof.append((round(z - z1, 4), round(2 * x, 4)))
        last = z
    from analysis.cam import paths as P

    return [list(p) for p in P.simplify(prof, tol=2e-3)]


def _group(doc):
    g = doc.getObject(GROUP)
    if g is None:
        g = doc.addObject("App::DocumentObjectGroup", GROUP)
        g.Label = "问渠CAM"
    return g


def clear(doc) -> None:
    g = doc.getObject(GROUP)
    if g is None:
        return
    for o in list(g.Group):
        doc.removeObject(o.Name)


def draw_toolpath(doc, parsed: dict, *, lathe: bool, offset=(0.0, 0.0, 0.0), label: str = "刀路"):
    """快移、切削各一个线框对象（车床的 X 是直径，画在 XZ 平面里）"""
    import FreeCAD
    import Part

    g = _group(doc)
    out = []
    for kind, color in (("rapid", (1.0, 0.55, 0.0)), ("cut", (0.1, 0.45, 0.95))):
        edges = []
        for m in parsed["moves"]:
            if (m["t"] == "rapid") != (kind == "rapid"):
                continue
            a, b = m["a"], m["b"]
            if lathe:
                a, b = (a[0] / 2, 0.0, a[2]), (b[0] / 2, 0.0, b[2])
            pa = FreeCAD.Vector(a[0] + offset[0], a[1] + offset[1], a[2] + offset[2])
            pb = FreeCAD.Vector(b[0] + offset[0], b[1] + offset[1], b[2] + offset[2])
            if (pa - pb).Length > 1e-9:
                edges.append(Part.LineSegment(pa, pb).toShape())
        if not edges:
            continue
        o = doc.addObject("Part::Feature", f"CamPath_{kind}")
        o.Label = f"{label}（{'快移' if kind == 'rapid' else '切削'}）"
        o.Shape = Part.Compound(edges)
        g.addObject(o)
        vo = getattr(o, "ViewObject", None)
        if vo is not None:
            vo.LineColor = color
            vo.LineWidth = 1.0 if kind == "rapid" else 2.0
            if kind == "rapid":
                vo.DrawStyle = "Dashed"
        out.append(o)
    doc.recompute()
    return out


def draw_turned(doc, sim_res: dict, *, z_offset: float = 0.0, label: str = "仿真后的形状"):
    """车削仿真结果（半径网格 r、内径 ri）→ 回转体"""
    import FreeCAD
    import Part

    z, r = sim_res["z"], sim_res["r"]
    ri = sim_res.get("ri")
    pts_out = [(float(zz), float(rr)) for zz, rr in zip(z, r, strict=True)]
    pts_in = [(float(zz), float(rr)) for zz, rr in zip(z, ri, strict=True)] if ri is not None else [(float(zz), 0.0) for zz in z]
    poly = [FreeCAD.Vector(rr, 0, zz + z_offset) for zz, rr in pts_out] + \
        [FreeCAD.Vector(rr, 0, zz + z_offset) for zz, rr in reversed(pts_in)]
    poly.append(poly[0])
    face = Part.Face(Part.makePolygon(poly))
    solid = face.revolve(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 360)
    o = doc.addObject("Part::Feature", "CamResult")
    o.Label = label
    o.Shape = solid
    _group(doc).addObject(o)
    doc.recompute()
    return o


def draw_milled(doc, sim_res: dict, *, offset=(0.0, 0.0, 0.0), label: str = "仿真后的形状", step: int = 2):
    """铣削仿真高度图 → 网格（只画毛坯范围内的顶面），step 隔几格取一格"""
    import Mesh

    x, y, H, inside = sim_res["x"][::step], sim_res["y"][::step], sim_res["H"][::step, ::step], sim_res["inside"][::step, ::step]
    tris = []
    for i in range(len(x) - 1):
        for j in range(len(y) - 1):
            if not (inside[i, j] and inside[i + 1, j] and inside[i, j + 1] and inside[i + 1, j + 1]):
                continue

            def p(a, b):
                return (float(x[a] + offset[0]), float(y[b] + offset[1]), float(H[a, b] + offset[2]))
            tris += [[p(i, j), p(i + 1, j), p(i + 1, j + 1)], [p(i, j), p(i + 1, j + 1), p(i, j + 1)]]
    m = Mesh.Mesh(tris)
    o = doc.addObject("Mesh::Feature", "CamResult")
    o.Label = label
    o.Mesh = m
    _group(doc).addObject(o)
    doc.recompute()
    return o


# ISO 261 粗牙螺纹的攻丝底孔直径（ISO 2306 / DIN 336 常用值）：底孔 → (公称直径, 螺距)
TAP_DRILL = {2.5: (3, 0.5), 3.3: (4, 0.7), 4.2: (5, 0.8), 5.0: (6, 1.0), 6.8: (8, 1.25), 8.5: (10, 1.5),
             10.2: (12, 1.75), 12.0: (14, 2.0), 14.0: (16, 2.0), 17.5: (20, 2.5)}


def mill_holes(shape) -> list[dict]:
    """铣削件上沿 Z 的孔（ADR-0106 Q3b 孔特征识别）：按孔轴（x, y）把内圆柱面、圆锥面归成一个孔，
    → [{"x", "y", "d", "z_top", "z_bottom", "through", "cbore": {"d", "depth"} | None, "csink": {"d", "angle"} | None,
        "tip": 钻尖锥（盲孔底）, "thread": {"d", "pitch", "guess": True} | None}]（Z 是模型坐标）。
    - 主孔：最小直径的圆柱面；孔口 z_top 是这个孔最上面一个面的顶；通孔：主孔底到零件最低处；
    - 沉孔：比主孔大、底在主孔顶的圆柱面；锪孔口：开口朝上的圆锥面（孔口直径、锥角）；
    - 螺纹孔：主孔直径正好是粗牙螺纹的攻丝底孔（TAP_DRILL）时**推测**为螺纹孔，标 guess，要人确认（模型上一般不画螺纹）。"""
    zmin = shape.BoundBox.ZMin
    groups: dict = {}
    for f in shape.Faces:
        sf = f.Surface
        kind = type(sf).__name__
        if kind not in ("Cylinder", "Cone") or abs(abs(sf.Axis.z) - 1) > 1e-6:
            continue
        c = sf.Center if kind == "Cylinder" else sf.Apex
        u = (f.ParameterRange[0] + f.ParameterRange[1]) / 2
        v = (f.ParameterRange[2] + f.ParameterRange[3]) / 2
        p, n = f.valueAt(u, v), f.normalAt(u, v)
        if (p.x - c.x) * n.x + (p.y - c.y) * n.y >= 0:          # 法向背着轴线：外圆柱面（凸台），不是孔
            continue
        key = (round(c.x, 3), round(c.y, 3))
        bb = f.BoundBox
        if kind == "Cylinder":
            groups.setdefault(key, {"cyl": [], "cone": []})["cyl"].append((2 * sf.Radius, bb.ZMin, bb.ZMax))
        else:
            r_lo = math.hypot(f.valueAt(u, f.ParameterRange[2]).x - c.x, f.valueAt(u, f.ParameterRange[2]).y - c.y)
            r_hi = math.hypot(f.valueAt(u, f.ParameterRange[3]).x - c.x, f.valueAt(u, f.ParameterRange[3]).y - c.y)
            z_lo, z_hi = f.valueAt(u, f.ParameterRange[2]).z, f.valueAt(u, f.ParameterRange[3]).z
            (ra, za), (rb, zb) = sorted([(r_lo, z_lo), (r_hi, z_hi)], key=lambda t: t[1])   # a 在下、b 在上
            groups.setdefault(key, {"cyl": [], "cone": []})["cone"].append({"r_bot": ra, "z_bot": za, "r_top": rb, "z_top": zb})
    out = []
    for (x, y), g in sorted(groups.items()):
        if not g["cyl"]:
            continue
        d, zb, zt = min(g["cyl"])
        h = {"x": x, "y": y, "d": round(d, 4), "z_bottom": zb, "z_top": max(t for _, _, t in g["cyl"]),
             "through": zb <= zmin + 1e-6, "cbore": None, "csink": None, "tip": None, "thread": None}
        big = [c for c in g["cyl"] if c[0] > d + 1e-6 and abs(c[1] - zt) < 1e-6]
        if big:
            cb = min(big)
            h["cbore"] = {"d": round(cb[0], 4), "depth": round(cb[2] - cb[1], 4)}
        for cn in g["cone"]:
            if cn["r_top"] > cn["r_bot"] + 1e-6 and cn["z_bot"] >= zt - 1e-6:       # 开口朝上、在主孔（或沉孔）上面：锪孔口
                ang = 2 * math.degrees(math.atan2(cn["r_top"] - cn["r_bot"], cn["z_top"] - cn["z_bot"]))
                h["csink"] = {"d": round(2 * cn["r_top"], 4), "angle": round(ang, 2)}
                h["z_top"] = max(h["z_top"], cn["z_top"])
            elif cn["z_top"] <= zb + 1e-6:                                       # 盲孔底的钻尖锥（尖朝下）
                h["tip"] = {"angle": round(2 * math.degrees(math.atan2(cn["r_top"] - cn["r_bot"], cn["z_top"] - cn["z_bot"])), 2)}
        if h["cbore"]:
            h["z_top"] = max(h["z_top"], zt + h["cbore"]["depth"])
        m = next((v for k, v in TAP_DRILL.items() if abs(k - d) < 1e-3), None)
        if m:
            h["thread"] = {"d": float(m[0]), "pitch": m[1], "guess": True}
        out.append(h)
    return out


TAP_RUNOUT_P = 3.0     # 攻丝：盲孔攻到孔深 − 3P（丝锥前端倒锥留空）；通孔攻出底面 2P（规则值，人确认）


def hole_ops(shape, lib: dict) -> list[dict]:
    """孔特征 → 孔工序（钻孔以外的）：[{"kind": "cbore" | "csink" | "tap", "title", "tool" | None, "d", "holes": 程序坐标, "note"}]。
    同一种（直径、锥角、螺纹）的孔归一道工序；刀具库里没有合适的刀，tool 为 None、note 写明。"""
    top = shape.BoundBox.ZMax
    hs = mill_holes(shape)
    out = []
    ends = sorted((t for t in lib["tools"] if t["kind"] == "flat_endmill" and "diameter_mm" in t), key=lambda t: -t["diameter_mm"])
    for D in sorted({h["cbore"]["d"] for h in hs if h["cbore"]}):
        grp = [h for h in hs if h["cbore"] and h["cbore"]["d"] == D]
        t = next((t for t in ends if D / 2 - 1e-9 <= t["diameter_mm"] < D - 1e-9), None)
        out.append({"kind": "cbore", "title": f"铣沉孔 Ø{D:g}", "tool": t, "d": D,
                    "holes": [(h["x"], h["y"], h["z_top"] - top, h["cbore"]["depth"]) for h in grp],
                    "note": "" if t else f"沉孔 Ø{D:g}：刀具库里没有刀径在 Ø{D / 2:g} ~ Ø{D:g} 之间的平底立铣刀"})
    for D, ang in sorted({(h["csink"]["d"], h["csink"]["angle"]) for h in hs if h["csink"]}):
        grp = [h for h in hs if h["csink"] and (h["csink"]["d"], h["csink"]["angle"]) == (D, ang)]
        t = next((t for t in lib["tools"] if t["kind"] == "chamfer_mill" and abs(float(t.get("tip_angle_deg", -1)) - ang) < 0.5
                  and t.get("diameter_mm", 0) > D), None)
        out.append({"kind": "csink", "title": f"锪孔口 Ø{D:g}×{ang:g}°", "tool": t, "d": D,
                    "holes": [(h["x"], h["y"], h["z_top"] - top) for h in grp],
                    "note": "" if t else f"锪孔口 Ø{D:g}×{ang:g}°：刀具库里没有锥角 {ang:g}°、直径大于 {D:g} 的倒角刀"})
    for d, pch in sorted({(h["thread"]["d"], h["thread"]["pitch"]) for h in hs if h["thread"]}):
        grp = [h for h in hs if h["thread"] and (h["thread"]["d"], h["thread"]["pitch"]) == (d, pch)]
        t = next((t for t in lib["tools"] if t["kind"] == "tap" and abs(t.get("diameter_mm", -1) - d) < 1e-6
                  and abs(t.get("pitch_mm", -1) - pch) < 1e-6), None)
        holes = []
        for h in grp:
            ze = (h["z_top"] - (h["cbore"]["depth"] if h["cbore"] else 0.0)) - top
            zb = (h["z_bottom"] - top) - 2 * pch if h["through"] else (h["z_bottom"] - top) + TAP_RUNOUT_P * pch
            holes.append((h["x"], h["y"], ze, zb))
        guess = f"Ø{grp[0]['d']:g} 是 M{d:g}×{pch:g} 的攻丝底孔，推测是螺纹孔（模型上没画螺纹），确认后再用"
        rule = f"盲孔攻到孔深 − {TAP_RUNOUT_P:g}P，通孔攻出底面 2P"
        miss = f"刀具库里没有 M{d:g}×{pch:g} 的丝锥"
        out.append({"kind": "tap", "title": f"攻丝 M{d:g}×{pch:g}（推测）", "tool": t, "d": d, "holes": holes, "guess": guess,
                    "note": "；".join([guess, rule] + ([] if t else [miss]))})
    return out


def mill_plan(shape, lib: dict, iso: str, *, pocket: bool = True, profile: bool = True, drill: bool = True,
              holes: bool = True, taps: bool = False, max_rpm: float = 1e9) -> dict:
    """铣削件（零件实体）→ FreeCAD CAM 的工序（cam_fc.program 的 ops）与工艺卡的工序表。
    选刀：型腔取刀径不超过型腔底面窄边一半的最大平底刀；外轮廓取最大的平底刀；每种孔径取直径相同的钻头。
    参数：刀具样本范围的中间值（assist.cam_process 的规则值）；转速 n = 1000·vc/(π·d)（不超过机床最高转速），进给 = fz·刃数·n。"""
    from assist import cam_process as CP
    from freecad_addon.fc import cam_fc

    top = shape.BoundBox.ZMax
    ends = [t for t in lib["tools"] if t["kind"] == "flat_endmill" and "diameter_mm" in t]
    ops, card, notes = [], [], []

    def add(kind, title, tool, extra):
        params, status = CP._rule_params({"kind": kind}, tool, iso)
        d = float(tool["diameter_mm"])
        rpm = min(1000.0 * params["vc"] / (math.pi * d), max_rpm)
        n = len(ops) + 1
        if kind == "holes":
            feed = params["f"] * rpm
            spec = {"type": "drill", "tool": tool, "number": n, "rpm": round(rpm), "feed_mm_min": round(feed, 1)}
        elif kind in ("csink", "tap"):
            spec = {"type": kind, "tool": tool, "number": n, "rpm": round(rpm),
                    "feed_mm_min": round(params["f"] * rpm, 1) if kind == "csink" else 0.0, **extra}
        else:
            z = tool.get("flutes")
            if z is None:
                z = CP.TEACH_Z["pocket"]
                notes.append(f"{title}：刀 {tool['id']} 没写刃数，按 {z} 刃算进给，待确认")
            feed = params["fz"] * z * rpm
            spec = {"type": kind if kind in ("pocket", "cbore") else "profile", "tool": tool, "number": n, "rpm": round(rpm),
                    "feed_mm_min": round(feed, 1), "plunge_mm_min": round(feed / 3, 1), "step_down_mm": params["ap"], **extra}
        if status == "unknown":
            notes.append(f"{title}：刀 {tool['id']} 的样本没有 {iso} 组的参数，用教学示意值，待确认")
        ops.append(spec)
        card.append({"id": f"f{n}", "title": title, "tool": tool["id"], "tool_name": tool.get("name", ""), "params": params,
                     "status": status, "reason": ""})

    if pocket:
        floors = cam_fc.pocket_floors(shape, top)
        if floors:
            lim = min(min(shape.getElement(f).BoundBox.XLength, shape.getElement(f).BoundBox.YLength) for f in floors) / 2
            fit = [t for t in ends if t["diameter_mm"] <= lim + 1e-9]
            if not fit:
                raise CamDocError(f"刀具库里没有刀径 ≤ {lim:g} mm 的平底立铣刀，型腔铣不了")
            t = max(fit, key=lambda t: t["diameter_mm"])
            c = _cut(t, iso)
            so = min(45.0, 100 * c["ae_max_mm"] / t["diameter_mm"]) if c and "ae_max_mm" in c else 45.0
            add("pocket", "铣型腔", t, {"step_over_pct": so})
    if profile:
        if not ends:
            raise CamDocError("刀具库里没有平底立铣刀，外轮廓铣不了")
        add("contour", "铣外轮廓", max(ends, key=lambda t: t["diameter_mm"]), {})
    if drill:
        import FreeCAD
        from Path.Base import Drillable

        doc = FreeCAD.newDocument("WenQuestCamHoles")
        try:
            o = doc.addObject("Part::Feature", "P")
            o.Shape = shape
            doc.recompute()
            dias = sorted({round(2 * o.Shape.getElement(h[1]).Surface.Radius, 4) for h in Drillable.getDrillableTargets(o)})
        finally:
            FreeCAD.closeDocument(doc.Name)
        for dd in dias:
            t = next((t for t in lib["tools"] if t["kind"] == "drill" and abs(t.get("diameter_mm", -1) - dd) < 1e-6), None)
            if t is None:
                notes.append(f"孔 Ø{dd:g}：刀具库里没有这个直径的钻头，没编程")
                continue
            add("holes", f"钻孔 Ø{dd:g}", t, {})
    if holes:                                   # 钻孔以后：铣沉孔 → 锪孔口 → 攻丝（ADR-0106 Q3b）
        for ho in hole_ops(shape, lib):
            if ho["kind"] == "tap" and not taps:     # 螺纹孔是推测的：起草不自动加攻丝，写进说明，人确认后“新建工序 → 攻丝”
                notes.append(ho["guess"] + "；" + "要攻丝就在“新建工序”里加“攻丝”")
                continue
            if ho["tool"] is None:
                notes.append(ho["note"])
                continue
            add(ho["kind"], ho["title"], ho["tool"], {"holes": ho["holes"], "d": ho["d"], "title": ho["title"]})
            if ho["note"]:
                card[-1]["reason"] = ho["note"]
                if ho["kind"] == "tap":
                    card[-1]["status"] = "unknown"          # 推测的螺纹孔：一定要人确认
    if not ops:
        raise CamDocError("没有可以加工的：零件上没找到型腔、也没选外轮廓和钻孔")
    return {"ops": ops, "card": card, "notes": notes}


def _cut(tool, iso):
    """刀具样本里这个材料组的参数"""
    from analysis.cam import tools as TL

    return TL.cutting_for(tool, iso)
