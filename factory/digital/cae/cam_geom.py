# -*- coding: utf-8 -*-
"""数控编程的几何识别（第 13 轮 C3）：从 STEP 认出
  - 回转零件的外轮廓（车削用）：同轴的圆柱、圆锥、圆角面在“轴向位置—半径”平面上的外包络；
  - 2.5 轴铣削特征（铣削用）：外轮廓、各层平底型腔（含岛）、竖直孔；以及高度图目标（仿真比对用）。
不用 FreeCAD：Gmsh 读 STEP 划表面网格（曲面细分到 4° 以内，R5 圆角的弦高约 0.003 mm），trimesh 截面、shapely 求多边形。
零件要摆正：车削件轴线沿 X / Y / Z 之一；铣削件加工面朝 +Z（顶面在最高处）。"""
import math
import tempfile

import numpy as np

from cae import geometry as G

AXES = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0])}


def _mesh(step_bytes):
    """→ (面清单 [{info, pts, tris}], 包围盒, trimesh 整体网格)"""
    import trimesh
    with G._LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = G._gmsh()
        G.load_step(gmsh, step_bytes, tmp)
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = math.dist(bb[:3], bb[3:])
        gmsh.option.setNumber("Mesh.MeshSizeMin", 0)
        gmsh.option.setNumber("Mesh.MeshSizeMax", diag / 30)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 90)
        gmsh.model.mesh.generate(2)
        faces, allv, allt = [], [], []
        off = 0
        for _, tag in gmsh.model.getEntities(2):
            info = G._face_info(gmsh, tag)
            ntags, xyz, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)
            etypes, _, enodes = gmsh.model.mesh.getElements(2, tag)
            if not len(ntags) or not etypes:
                continue
            idx = {int(t): i for i, t in enumerate(ntags)}
            pts = np.asarray(xyz, float).reshape(-1, 3)
            tri = np.array([idx[int(n)] for n in enodes[0]], int).reshape(-1, 3)
            faces.append({"info": info, "pts": pts, "tris": tri})
            allv.append(pts)
            allt.append(tri + off)
            off += len(pts)
    mesh = trimesh.Trimesh(np.vstack(allv), np.vstack(allt), process=True)
    mesh.merge_vertices(digits_vertex=5)
    return faces, list(bb), mesh


# ---------------------------------------------------------------- 车削：回转轮廓
def turn_profile(step_bytes):
    """→ {"axis": "z", "length": 总长, "profile": [(t, d), …] t 从左端 0 到右端（沿轴线正方向），d 直径,
          "segments": [(d, 长度), …] 近似阶梯（锥面按两端各算一段的平均）, "faces_used": n, "ignored": [不同轴的面]}"""
    faces, bb, _ = _mesh(step_bytes)
    cyl = [f for f in faces if f["info"]["kind"] == "cylinder" and f["info"].get("axis")]
    if not cyl:
        raise ValueError("没有找到圆柱面，不像回转零件")
    # 主轴线：面积最大的那组同向圆柱
    score = {}
    for f in cyl:
        a = np.abs(np.array(f["info"]["axis"]))
        k = "xyz"[int(a.argmax())]
        if a.max() > 0.999:
            score[k] = score.get(k, 0) + f["info"]["area_mm2"]
    if not score:
        raise ValueError("圆柱面的轴线不在 X / Y / Z 方向上：请在 CAD 里把零件轴线摆到坐标轴上再导出")
    ax = max(score, key=score.get)
    d = AXES[ax]
    main = [f for f in cyl if abs(abs(np.dot(f["info"]["axis"], d)) - 1) < 1e-3]
    big = max(main, key=lambda f: f["info"]["area_mm2"])
    o = np.array(big["info"]["axis_origin"], float)
    o = o - d * np.dot(o, d)                                  # 轴线上一点（垂直分量）

    def tr(p):
        t = p @ d
        perp = p - np.outer(t, d) - o
        return t, np.linalg.norm(perp, axis=1)

    pieces, ignored = [], []
    for f in faces:
        k = f["info"]["kind"]
        t, r = tr(f["pts"])
        if k == "cylinder":
            ia = f["info"].get("axis")
            io = np.array(f["info"].get("axis_origin") or [0, 0, 0], float)
            if not ia or abs(abs(np.dot(ia, d)) - 1) > 1e-3 or np.linalg.norm((io - d * np.dot(io, d)) - o) > 0.02:
                ignored.append(f["info"]["id"])
                continue
            pieces.append(("line", t.min(), t.max(), float(np.median(r)), float(np.median(r))))
        elif k == "plane":
            n = np.array(f["info"].get("normal") or [0, 0, 0])
            if abs(abs(np.dot(n, d)) - 1) > 1e-3:
                ignored.append(f["info"]["id"])            # 键槽侧面、底面等不是回转面
            continue                                       # 端面、轴肩由相邻圆柱自然形成
        elif k in ("cone", "torus", "other", "sphere"):
            if r.std() < 1e-9 and t.std() < 1e-9:
                continue
            # 只收同轴回转面：同一轴向位置上半径应当一样（看最远的两点）
            order = np.argsort(t)
            tb = np.round(t[order], 2)
            ok = True
            for tv in np.unique(tb)[:: max(1, len(np.unique(tb)) // 20)]:
                rr = r[order][tb == tv]
                if rr.max() - rr.min() > 0.05 and k != "other":
                    ok = False
                    break
            if not ok:
                ignored.append(f["info"]["id"])
                continue
            if k == "cone":
                i0, i1 = int(r.argmin()), int(r.argmax())
                pieces.append(("line", t[i0], t[i1], r[i0], r[i1]) if t[i0] <= t[i1] else ("line", t[i1], t[i0], r[i1], r[i0]))
            else:
                ts = np.unique(np.round(t, 3))
                env = [(tv, r[np.abs(t - tv) < 2e-3].max()) for tv in ts]
                pieces.append(("poly", env))
    if not pieces:
        raise ValueError("没有找到和主轴线同轴的回转面")
    t_all = sorted({round(p[1], 4) for p in pieces if p[0] == "line"} | {round(p[2], 4) for p in pieces if p[0] == "line"}
                   | {round(tv, 4) for p in pieces if p[0] == "poly" for tv, _ in p[1]})

    def r_at(tv, side):
        best = 0.0
        for p in pieces:
            if p[0] == "line":
                _, a, b, ra, rb = p
                if a - 1e-6 <= tv <= b + 1e-6 and b - a > 1e-6:
                    if (side > 0 and tv >= b - 1e-6) or (side < 0 and tv <= a + 1e-6):
                        continue                           # 只看所在区间内侧
                    best = max(best, ra + (rb - ra) * (tv - a) / (b - a))
            else:
                env = p[1]
                ts = [e[0] for e in env]
                if ts[0] - 1e-6 <= tv <= ts[-1] + 1e-6 and ts[-1] - ts[0] > 1e-6:
                    if (side > 0 and tv >= ts[-1] - 1e-6) or (side < 0 and tv <= ts[0] + 1e-6):
                        continue
                    best = max(best, float(np.interp(tv, ts, [e[1] for e in env])))
        return best
    t0, t1 = t_all[0], t_all[-1]
    prof = []
    for a, b in zip(t_all, t_all[1:]):
        if b - a < 1e-4:
            continue
        ra, rb = r_at(a, +1), r_at(b, -1)
        prof += [(a - t0, 2 * ra), (b - t0, 2 * rb)]
    # 回转零件的包围盒在垂直轴线的两个方向上都应当正好是最大直径，并以轴线为中心（平板上的孔也有同向圆柱，但不是回转零件）
    rmax = max(max(p[3], p[4]) if p[0] == "line" else max(e[1] for e in p[1]) for p in pieces)
    lo, hi = np.array(bb[:3]), np.array(bb[3:])
    for k in range(3):
        if abs(d[k]) > 0.5:
            continue
        if abs((hi[k] - lo[k]) / 2 - rmax) > 0.02 * rmax + 0.05 or abs((hi[k] + lo[k]) / 2 - o[k]) > 0.02 * rmax + 0.05:
            raise ValueError("零件不是绕一根轴线的回转体（外形比最大圆柱大），不能车削编程；铣削请选“铣削”")
    from cae.cam import simplify
    prof = simplify([(round(float(t), 4), round(float(dd), 4)) for t, dd in prof])
    return {"axis": ax, "origin": [float(x) for x in o], "t0": float(t0), "length": float(t1 - t0), "profile": prof,
            "ignored_faces": ignored}


# ---------------------------------------------------------------- 铣削：2.5 轴特征
def _section(mesh, z):
    """z 高度处的截面（材料区域，shapely 多边形）"""
    from shapely.geometry import MultiPolygon, Polygon
    from shapely.ops import unary_union
    sec = mesh.section(plane_origin=(0, 0, z), plane_normal=(0, 0, 1))
    if sec is None:
        return Polygon()
    T = np.eye(4)
    T[2, 3] = -z
    p2, _ = sec.to_2D(to_2D=T)
    polys = list(p2.polygons_full)
    g = unary_union([p for p in polys if p.is_valid and p.area > 1e-6])
    return g if isinstance(g, (Polygon, MultiPolygon)) else Polygon()


def mill_features(step_bytes):
    """→ {"top": 顶面 z, "bottom": 底面 z, "outline": 外轮廓多边形坐标, "pockets": [{"z_floor", "depth", "polygon"(含岛)}],
          "holes": [{"x", "y", "d", "depth", "through"}], "target": 高度图函数需要的数据}
    坐标用零件自己的坐标；工件坐标系 G54 设在顶面（Z0），X、Y 原点与 CAD 原点相同。"""
    from shapely.geometry import Point, Polygon, mapping
    faces, bb, mesh = _mesh(step_bytes)
    top, bottom = bb[5], bb[2]
    H = top - bottom
    # 竖直孔：轴线沿 Z 的圆柱，且是“空的”（中心点在材料外）
    mid = _section(mesh, bottom + 0.5 * H)
    holes = []
    for f in faces:
        i = f["info"]
        if i["kind"] != "cylinder" or not i.get("axis") or abs(abs(i["axis"][2]) - 1) > 1e-3:
            continue
        c = i["axis_origin"]
        zlo, zhi = i["bbox"][2], i["bbox"][5]
        zc = (zlo + zhi) / 2
        sec = _section(mesh, zc)
        if sec.contains(Point(c[0], c[1])):
            continue                                       # 实心圆柱（凸台、岛），不是孔
        bxw = i["bbox"][3] - i["bbox"][0]
        if bxw < 2 * i["radius_mm"] - 0.05:
            continue                                       # 只是一段圆弧（型腔圆角），不是整圆孔
        holes.append({"x": round(c[0], 4), "y": round(c[1], 4), "d": round(2 * i["radius_mm"], 4), "z_top": zhi,
                      "depth": round(top - zlo, 4), "through": abs(zlo - bottom) < 1e-3, "face": i["id"]})
    hole_disks = [Point(h["x"], h["y"]).buffer(h["d"] / 2 + 0.05) for h in holes]
    # 外轮廓：中间高度的截面外边（只取最大那块）
    outline = None
    if not mid.is_empty:
        big = max(getattr(mid, "geoms", [mid]), key=lambda p: p.area)
        outline = Polygon(big.exterior)
    # 平底型腔：朝上的平面，低于顶面；每个底面高度做一次截面，截面里“空的地方”（外轮廓内、材料外，去掉孔）就是型腔
    floors = sorted({round(f["info"]["bbox"][2], 4) for f in faces
                     if f["info"]["kind"] == "plane" and (f["info"].get("normal") or [0, 0, 0])[2] > 0.999
                     and f["info"]["bbox"][2] < top - 1e-3 and f["info"]["bbox"][2] > bottom + 1e-3})
    pockets = []
    for zf in floors:
        sec = _section(mesh, zf + 1e-3)
        if outline is None or sec.is_empty:
            continue
        air = outline.difference(sec)
        for hd in hole_disks:
            air = air.difference(hd)
        for g in getattr(air, "geoms", [air]):
            if g.area < 1.0:
                continue
            # 型腔底面在这一层（不是更深一层的型腔开口）：取底面中心落在这一块里的
            def on_floor(f):
                c = f["pts"][f["tris"][0]].mean(axis=0)          # 底面上一个三角形的中心（面的质心可能落在岛上）
                return g.buffer(0.01).contains(Point(c[0], c[1]))
            fl = [f for f in faces if f["info"]["kind"] == "plane" and abs(f["info"]["bbox"][2] - zf) < 1e-3
                  and (f["info"].get("normal") or [0, 0, 0])[2] > 0.999 and on_floor(f)]
            if not fl:
                continue
            pockets.append({"z_floor": zf, "depth": round(top - zf, 4), "polygon": mapping(g.simplify(0.002)),
                            "area_mm2": round(g.area, 2)})
    return {"top": top, "bottom": bottom, "bbox": bb, "outline": mapping(outline) if outline is not None else None,
            "pockets": pockets, "holes": holes}


def target_fn(feat):
    """特征 → 高度图目标函数 T(X, Y)（仿真比对用）：外轮廓外是“该切掉”到底面以下，孔、型腔按深度"""
    from shapely import contains_xy
    from shapely.geometry import shape
    top = feat["top"]
    outline = shape(feat["outline"]) if feat.get("outline") else None
    pockets = [(shape(p["polygon"]), top - p["depth"]) for p in feat["pockets"]]
    holes = feat["holes"]

    def T(X, Y):
        t = np.full(X.shape, top, float)
        if outline is not None:
            t[~contains_xy(outline.buffer(0.05), X, Y)] = np.nan          # 外轮廓外（含边上一格）不比
            t[contains_xy(outline.buffer(0.05), X, Y) & ~contains_xy(outline.buffer(-0.05), X, Y)] = np.nan
        for poly, z in sorted(pockets, key=lambda q: -q[1]):
            inside = contains_xy(poly.buffer(-0.05), X, Y)
            t[inside] = np.where(np.isnan(t[inside]), np.nan, z)
            edge = contains_xy(poly.buffer(0.05), X, Y) & ~inside
            t[edge] = np.nan
        for h in holes:
            r2 = (X - h["x"]) ** 2 + (Y - h["y"]) ** 2
            t[r2 < (h["d"] / 2 - 0.05) ** 2] = -np.inf if h.get("through") else top - h["depth"]     # 通孔钻多深都行
            t[(r2 >= (h["d"] / 2 - 0.05) ** 2) & (r2 < (h["d"] / 2 + 0.05) ** 2)] = np.nan
        return t
    return T


# ---------------------------------------------------------------- 示例零件
EXAMPLES = {"WQ-PLATE": "示例：带型腔和孔的平板 100×80×20（R5 圆角型腔深 8、中间 Ø12 岛、4 个 Ø8.5 通孔）"}


def example_step(key):
    """没有自己的铣削零件时用的示例（build123d 现做）"""
    import os
    import build123d as bd
    if key != "WQ-PLATE":
        raise KeyError(key)
    with bd.BuildPart() as p:
        bd.Box(100, 80, 20, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MAX))
        with bd.BuildSketch(bd.Plane.XY):
            bd.RectangleRounded(60, 40, 5)
            bd.Circle(6, mode=bd.Mode.SUBTRACT)
        bd.extrude(amount=-8, mode=bd.Mode.SUBTRACT)
        with bd.Locations(*[(x, y, 0) for x in (-40, 40) for y in (-30, 30)]):
            bd.Hole(4.25)
    with tempfile.TemporaryDirectory() as tmp:
        f = os.path.join(tmp, "plate.step")
        bd.export_step(p.part, f)
        return open(f, "rb").read()
