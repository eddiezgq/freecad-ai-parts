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
    outer, inner, cones, inner_cones = [], [], [], []
    for f in shape.Faces:
        s = f.Surface
        name = type(s).__name__
        if name not in ("Cylinder", "Cone"):
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


def _is_inner(face) -> bool:
    """回转面法向朝轴线 → 内孔一侧"""
    u = (face.ParameterRange[0] + face.ParameterRange[1]) / 2
    v = (face.ParameterRange[2] + face.ParameterRange[3]) / 2
    p, n = face.valueAt(u, v), face.normalAt(u, v)
    return (p.x * n.x + p.y * n.y) < 0


def bore_profile(shape, step: float = 0.05) -> list[list[float]]:
    """回转体在 XZ 半平面上的截面 → 内孔轮廓 [[z, d], …]（z 从右端孔口 0 往里为负，到孔底为止）。
    截面边界离散成折线，每隔 step 取一条水平线求交：交点两个以上时最小的那个是内孔半径。共线的点并掉，锥面、倒角是直线段，圆弧按折线。"""
    import FreeCAD

    bb = shape.BoundBox
    z1 = bb.ZMax
    wires = shape.slice(FreeCAD.Vector(0, 1, 0), 0.0)
    segs = []
    for w in wires:
        pts = w.discretize(Deflection=0.002)
        for a, b in itertools.pairwise(pts):
            if a.x >= -1e-9 and b.x >= -1e-9:
                segs.append((a.x, a.z, b.x, b.z))

    def inner_at(z):
        xs = sorted(ax + (bx - ax) * (z - az) / (bz - az) for ax, az, bx, bz in segs
                    if min(az, bz) <= z < max(az, bz) and abs(bz - az) > 1e-12)     # 半开区间：正好过顶点只算一次
        xs = [x for x in xs if x > 1e-6]
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


def mill_plan(shape, lib: dict, iso: str, *, pocket: bool = True, profile: bool = True, drill: bool = True,
              max_rpm: float = 1e9) -> dict:
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
        else:
            z = tool.get("flutes")
            if z is None:
                z = CP.TEACH_Z["pocket"]
                notes.append(f"{title}：刀 {tool['id']} 没写刃数，按 {z} 刃算进给，待确认")
            feed = params["fz"] * z * rpm
            spec = {"type": "pocket" if kind == "pocket" else "profile", "tool": tool, "number": n, "rpm": round(rpm),
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
    if not ops:
        raise CamDocError("没有可以加工的：零件上没找到型腔、也没选外轮廓和钻孔")
    return {"ops": ops, "card": card, "notes": notes}


def _cut(tool, iso):
    """刀具样本里这个材料组的参数"""
    from analysis.cam import tools as TL

    return TL.cutting_for(tool, iso)
