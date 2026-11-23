"""整机三维装配（ADR-0115 44.3 之二第 3 步之二、第 4 步）：按整机方案、选定的一体化关节模组和装配校核结果，
生成自制件（U 形支架、舵盘法兰、壳体底座、基座、直管杆件），在零位装起来，查干涉、算质量与重心，写 STEP 与零件表。

自制件的形状由接口与装配校核决定，尺寸按下面的设计值（DESIGN，第一版的起点；之后由 AI 按载荷与工艺改，代码校核）：
  U 形支架：两块侧板分别用 8 个 M2.5 螺钉装在输出舵盘与背面惰轮舵盘上（孔在 Ø22 分度圆上），中心让开舵盘凸台；
            底板离轴线 d = 装配校核的最小值 + 间隙；底板外侧是套管，杆件插在里面。
  舵盘法兰：圆盘，8 个 M2.5 螺钉装在输出舵盘上；外侧是套管（子杆沿轴线时）。
  壳体底座：一块板用 4 个 M2.5 螺钉装在模组底面（孔距 20 × 16）；外侧是套管，接父杆。
  基座：j1 这样装在基座上的模组，壳体底座做成立板，下接一块底板落在安装面上。
  杆件：直管（截面按方案：圆管、方管或板），两端插进套管。
模组外形用零件库的包络（保守），所以干涉检查偏保守。
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

import numpy as np

DESIGN = {
    "plate_mm": 4.0,            # 支架板厚
    "socket_wall_mm": 3.0,      # 套管壁厚
    "socket_len_mm": 20.0,      # 套管长（杆件插入深度）
    "clearance_mm": 1.0,        # U 底板在装配校核最小值之外再留的间隙
    "bolt_hole_mm": 2.9,        # M2.5 通孔（ISO 273 中等级）
    "boss_hole_mm": 11.0,       # 舵盘中心凸台让位孔（凸台 Ø10）
    "foot_mm": 120.0,           # 基座底板边长
    "base_plate_mm": 8.0,       # 基座立板厚：整条臂的倾覆力矩都压在它根部（4 mm 时有限元算出根部 95 MPa，弯曲疲劳不够）
    "base_fillet_mm": 4.0,      # 基座立板与底板的内角
    "fillet_inner_mm": 2.0,     # U 形支架侧板与底板的内角、基座立板与底板的内角（侧板到模组壳体还有 2.5 mm）
    "fillet_socket_mm": 3.0,    # 套管外壁与板面的内角
    "plate_cb_mm": 6.0,         # 螺钉头在套管底下的板（舵盘法兰、壳体底座）：沉头孔深 3 + 压紧 3
    "head_d_mm": 4.5,           # M2.5 内六角圆柱头螺钉头部直径、高度（ISO 4762 的最大值 dk、k）
    "head_k_mm": 2.5,
    "cb_d_mm": 5.5,             # 沉头孔：头部直径 + 1 mm、头高 + 0.5 mm，螺钉头沉到板面以下，管子才能插到底
    "cb_depth_mm": 3.0,
    "bore_fillet_mm": 1.0,      # 套管孔底的内角（铣刀刀尖圆角）
    "tube_end_round_mm": 1.5,   # 管端外棱倒圆（大于孔底圆角，管子才插得到底）
}
DENSITY_KG_MM3 = {"6061-T6": 2.70e-6}
PCD_MM, HORN_HOLES = 22.0, 8
BOTTOM_HOLES = ((-10.0, -8.0), (-10.0, 8.0), (10.0, -8.0), (10.0, 8.0))   # 底面孔：x，z 相对壳体中段


class CadError(ValueError):
    pass


def min_spare_mm() -> dict[str, float]:
    """每根杆在本关节 U 底板（或舵盘法兰）与下一壳体之间至少要留的长度，按本关节的装法：
    间隙 + 起点的板（U 底板 plate_mm；法兰 plate_cb_mm）+ 终点壳体底座的板（plate_cb_mm）+ 两头套管（管子插满两头）"""
    rest = DESIGN["clearance_mm"] + DESIGN["plate_cb_mm"] + 2 * DESIGN["socket_len_mm"]
    return {"clevis": rest + DESIGN["plate_mm"], "flange": rest + DESIGN["plate_cb_mm"]}


def min_tube_od_mm() -> dict[str, float]:
    """螺钉从套管孔里装（头部沉在沉头孔里、扳手从管孔伸进去）要的最小圆管外径：壳体底座（底面 4 孔）、舵盘法兰（舵盘 8 孔）"""
    ra = DESIGN["cb_d_mm"] / 2
    rh = max(math.hypot(x, z) for x, z in BOTTOM_HOLES)
    f = DESIGN["bore_fillet_mm"]                                 # 沉头孔还要让开套管孔底的圆角
    return {"housing": math.ceil(2 * (rh + ra + f) + 0.5), "flange": math.ceil(2 * (PCD_MM / 2 + ra + f) + 0.5)}


def _section(link: Mapping) -> dict:
    """杆件截面：{"shape": "circle"|"rect", "outer": (宽, 高) 或 直径, "inner": ...}"""
    s, shape = link.get("section") or {}, link.get("shape")
    if shape == "tube":
        return {"shape": "circle", "outer": s["od_mm"], "inner": s.get("id_mm") or 0.0}
    if shape == "box":
        w, h, t = s["width_mm"], s["height_mm"], s.get("wall_mm")
        return {"shape": "rect", "outer": (w, h), "inner": (w - 2 * t, h - 2 * t) if t else None}
    if shape == "plate":
        return {"shape": "rect", "outer": (s["width_mm"], s["thickness_mm"]), "inner": None}
    raise CadError(f"杆件 {link['id']} 的截面 {shape} 这一步不生成（型材要看样本）")


def _frame(z: np.ndarray, y: np.ndarray, o: np.ndarray) -> np.ndarray:
    z = z / np.linalg.norm(z)
    y = y - (y @ z) * z
    y = y / np.linalg.norm(y)
    x = np.cross(y, z)
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = x, y, z, o
    return T


def layout(concept: Mapping, fit_result: Mapping, comp: Mapping) -> dict:
    """零位下每个关节的两个坐标系（世界）：H——模组壳体（z 沿输出轴，y 背离父件、底面朝父件，原点在输出舵盘端面中心）；
    U——随输出转的支架（侧摆关节：y 指向下一壳体中心；轴转关节同 H）"""
    from analysis.robot import fit
    from analysis.robot import kinematics as K

    m = K.build(concept)
    T = K.fk(m)
    g = fit.housing_geometry(comp)
    if g is None:
        raise CadError("模组没有机械接口数据，装不了")
    kinds = {r["joint"]: ("clevis" if r.get("type", "").startswith("侧摆") else "flange") for r in fit_result["joints"]}
    dmin = {r["joint"]: r["d_min_mm"] for r in fit_result["joints"] if r.get("d_min_mm")}
    world = {}
    for j in m.joints:
        Tp = T[j.parent]
        world[j.id] = ((Tp @ np.append(j.origin, 1.0))[:3], Tp[:3, :3] @ j.axis)
    centre = {jid: (o if kinds.get(jid) == "clevis" else o - 24.5 * a) for jid, (o, a) in world.items()}
    out = {}
    for j in m.joints:
        o_j, a = world[j.id]
        kind = kinds.get(j.id)
        if kind is None:
            raise CadError(f"关节 {j.id} 的装法没定")
        pj = m.by_child.get(j.parent)
        away = (o_j - world[pj.id][0]) if pj is not None else np.array([0.0, 0.0, 1.0])   # 背离父件
        if kind == "clevis":
            H = _frame(a, away, o_j + 24.5 * a)
            nxt = [c for c in m.joints if c.parent == j.child]
            tgt = (centre[nxt[0].id] - o_j) if nxt else (T[j.child][:3, :3] @ np.array([0.0, 0.0, 1.0]))
            U = _frame(a, tgt, o_j + 24.5 * a)
        else:
            y = away - (away @ a) * a
            if np.linalg.norm(y) < 1e-9:                            # 基座上的竖轴：壳体底面朝 −x
                y = np.array([1.0, 0.0, 0.0]) - a[0] * a
            H = _frame(a, y, o_j)
            U = H
        out[j.id] = {"H": H, "U": U, "kind": kind, "d_mm": dmin.get(j.id), "parent": j.parent, "child": j.child,
                     "origin": o_j, "axis": a}
    return {"joints": out, "geometry": g, "model": m, "T": T}


def _link_xdir(lay: Mapping, jid: str) -> np.ndarray:
    """关节 jid 带动的杆件，矩形截面第一边（宽）的方向（世界）：取本关节轴线；轴线沿杆向（轴转）时取下一关节的轴线。
    两头套管和杆件都按它摆，矩形才对得上"""
    J = lay["joints"][jid]
    u = J["U"][:3, 1] if J["kind"] == "clevis" else J["U"][:3, 2]
    cands = [J["axis"]] + [K_["axis"] for K_ in lay["joints"].values() if K_["parent"] == J["child"]] + [np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])]
    for c in cands:
        v = c - (c @ u) * u
        if np.linalg.norm(v) > 1e-6:
            return v / np.linalg.norm(v)
    raise CadError("找不到矩形截面的摆向")


# ---------------- 几何（gmsh OCC，单位 mm） ----------------

def _occ():
    from analysis.fea.geometry import _gmsh

    return _gmsh().model.occ


def _box(x0, x1, y0, y1, z0, z1) -> int:
    return _occ().addBox(x0, y0, z0, x1 - x0, y1 - y0, z1 - z0)


def _cyl(p, d, r) -> int:
    return _occ().addCylinder(p[0], p[1], p[2], d[0], d[1], d[2], r)


def _cut(obj: int, tools: list[int]) -> int:
    if not tools:
        return obj
    out = _occ().cut([(3, obj)], [(3, t) for t in tools])[0]
    if len(out) != 1:
        raise CadError("布尔运算后不是一个实体")
    return out[0][1]


def _fuse(tags: list[int]) -> int:
    if len(tags) == 1:
        return tags[0]
    out = _occ().fuse([(3, tags[0])], [(3, t) for t in tags[1:]])[0]
    if len(out) != 1:
        raise CadError("合并后不是一个实体")
    return out[0][1]


def _rim() -> float:
    """套管外壁到板边至少留的宽度：倒圆之外再留 1 mm 平面"""
    return DESIGN["fillet_socket_mm"] + 1.0


def _fillet(vol: int, on_edge, r: float) -> int:
    """给实体上满足 on_edge(点阵) 的边倒圆（内角去掉尖角处的应力集中，加工时铣刀本来就留圆角）；找不到边就原样返回"""
    import gmsh

    occ = _occ()
    occ.synchronize()
    faces = gmsh.model.getBoundary([(3, vol)], combined=False, oriented=False)
    curves = sorted({abs(t) for _d, t in gmsh.model.getBoundary(faces, combined=False, oriented=False)})
    pick = []
    for c in curves:
        lo, hi = gmsh.model.getParametrizationBounds(1, c)
        ts = np.linspace(lo[0], hi[0], 7)
        P = np.asarray(gmsh.model.getValue(1, c, list(ts)), float).reshape(-1, 3)
        if on_edge(P):
            pick.append(c)
    if not pick:
        return vol
    out = occ.fillet([vol], pick, [r], removeVolume=True)
    if len(out) != 1:
        raise CadError("倒圆后不是一个实体")
    return out[0][1]


def _bore(body: int, bore: int, sec: Mapping, c: np.ndarray, axis: np.ndarray, xd: np.ndarray) -> int:
    """掏出套管孔，孔底内角倒圆（铣刀刀尖圆角；尖角在管端顶住处是应力奇异点）"""
    body = _cut(body, [bore])
    return _fillet(body, lambda P: _on_socket_rim(P, sec, c, axis, xd, 0.0), DESIGN["bore_fillet_mm"])


def _round_ends(tag: int, sec: Mapping, start: np.ndarray, axis: np.ndarray, length: float | None, xl: np.ndarray) -> int:
    """杆件插进套管的端头外棱倒圆（大于套管孔底的内圆角，管子才插得到底）；薄壁管的圆角不超过壁厚的 0.9。length 为 None 时只倒起点一头"""
    wall = None
    if sec.get("inner"):
        wall = ((sec["outer"] - sec["inner"]) / 2 if sec["shape"] == "circle"
                else min(sec["outer"][0] - sec["inner"][0], sec["outer"][1] - sec["inner"][1]) / 2)
    r = DESIGN["tube_end_round_mm"] if wall is None else min(DESIGN["tube_end_round_mm"], 0.9 * wall)
    ends = [start] + ([start + axis * length] if length is not None else [])
    return _fillet(tag, lambda P: any(_on_socket_rim(P, sec, c, axis, xl, 0.0) for c in ends), r)


def _on_socket_rim(P: np.ndarray, sec: Mapping, c: np.ndarray, axis: np.ndarray, xdir: np.ndarray, grow: float) -> bool:
    """点阵是否都在套管外壁与板面的交线上：在过 c、法向为 axis 的平面上，且在截面外廓（加厚 grow）上"""
    D = P - c
    if np.any(np.abs(D @ axis) > 1e-3):
        return False
    xd = xdir - (xdir @ axis) * axis
    xd = xd / np.linalg.norm(xd)
    x, y = D @ xd, D @ np.cross(axis, xd)
    if sec["shape"] == "circle":
        return bool(np.all(np.abs(np.hypot(x, y) - (sec["outer"] / 2 + grow)) < 1e-3))
    w, h = sec["outer"][0] / 2 + grow, sec["outer"][1] / 2 + grow
    on = ((np.abs(np.abs(x) - w) < 1e-3) & (np.abs(y) <= h + 1e-3)) | ((np.abs(np.abs(y) - h) < 1e-3) & (np.abs(x) <= w + 1e-3))
    return bool(np.all(on))


def _prism(sec: Mapping, p0: np.ndarray, axis: np.ndarray, length: float, xdir: np.ndarray, grow: float = 0.0,
           hollow: bool = True) -> int:
    """沿 axis 的截面柱体（世界坐标）：圆或矩形；grow 向外加厚；hollow 按截面内孔掏空"""
    if sec["shape"] == "circle":
        outer = _cyl(p0, axis * length, sec["outer"] / 2 + grow)
        if hollow and sec["inner"] and not grow:
            return _cut(outer, [_cyl(p0, axis * length, sec["inner"] / 2)])
        return outer
    w, h = sec["outer"]
    T = _frame(axis, np.cross(axis, xdir), p0)
    tag = _box(-w / 2 - grow, w / 2 + grow, -h / 2 - grow, h / 2 + grow, 0.0, length)
    if hollow and sec["inner"] and not grow:
        iw, ih = sec["inner"]
        tag = _cut(tag, [_box(-iw / 2, iw / 2, -ih / 2, ih / 2, -1.0, length + 1.0)])
    _place(tag, T)
    return tag


def _place(tag: int, A: np.ndarray) -> None:
    _occ().affineTransform([(3, tag)], list(A[:3, :].reshape(-1)))


def _horn_holes(z0: float, z1: float, cb_top: bool = False) -> list[int]:
    """舵盘的 8 个螺钉孔与中心让位孔；cb_top：螺钉头在 z1 一侧、沉下去（沉头孔）"""
    pts = [(PCD_MM / 2 * math.cos(2 * math.pi * k / HORN_HOLES), PCD_MM / 2 * math.sin(2 * math.pi * k / HORN_HOLES))
           for k in range(HORN_HOLES)]
    hs = [_cyl((x, y, z0 - 1), (0, 0, z1 - z0 + 2), DESIGN["bolt_hole_mm"] / 2) for x, y in pts]
    if cb_top:
        cb = DESIGN["cb_depth_mm"]
        hs += [_cyl((x, y, z1 - cb), (0, 0, cb + 1), DESIGN["cb_d_mm"] / 2) for x, y in pts]
    return hs + [_cyl((0, 0, z0 - 1), (0, 0, z1 - z0 + 2), DESIGN["boss_hole_mm"] / 2)]


def actuator_solid(comp: Mapping) -> int:
    """模组外形（组件坐标系）：零件库包络的各段（长方体、圆柱）合成"""
    tags = []
    for p in comp["envelope"]["parts"]:
        z0, L = p["z_start_mm"], p["length_mm"]["value"]
        if p["shape"] == "box":
            w, h = p["width_mm"]["value"], p["height_mm"]["value"]
            tags.append(_box(-w / 2, w / 2, -h / 2, h / 2, z0, z0 + L))
        elif p["shape"] == "cylinder":
            tags.append(_cyl((0, 0, z0), (0, 0, L), p["diameter_mm"]["value"] / 2))
    return _fuse(tags)


def clevis(d: float, sec: Mapping, g: Mapping, xdir: np.ndarray | None = None) -> tuple[int, dict]:
    """U 形支架（模组坐标系，随输出转）：返回 (实体, 套管口：离轴线的距离)"""
    xd = np.array([1.0, 0.0, 0.0]) if xdir is None else np.asarray(xdir, float)
    t, wall, Ls = DESIGN["plate_mm"], DESIGN["socket_wall_mm"], DESIGN["socket_len_mm"]
    span = 49.0                                                  # 前后舵盘端面距离（0 与 −49）
    so = (sec["outer"] + 2 * wall) if sec["shape"] == "circle" else max(sec["outer"]) + 2 * wall
    w = max(2 * g["half_width"], so + 2 * _rim())   # 套管四周留出倒圆的地方（相切会生出碎面）
    a = _cut(_box(-w / 2, w / 2, -13.0, d + t, 0.0, t), _horn_holes(0.0, t))
    b = _cut(_box(-w / 2, w / 2, -13.0, d + t, -span - t, -span), _horn_holes(-span - t, -span))
    zc = -span / 2
    zh = max(span / 2 + t, so / 2 + _rim())  # 底板沿轴向要盖住套管
    base = _box(-w / 2, w / 2, d, d + t, zc - zh, zc + zh)
    sock = _prism(sec, np.array([0.0, d + t, zc]), np.array([0.0, 1.0, 0.0]), Ls, xd, grow=wall)
    bore = _prism(sec, np.array([0.0, d + t, zc]), np.array([0.0, 1.0, 0.0]), Ls + 1, xd, hollow=False)
    body = _fuse([a, b, base, sock])
    fi, fo = DESIGN["fillet_inner_mm"], DESIGN["fillet_socket_mm"]
    body = _fillet(body, lambda P: bool(np.all(np.abs(P[:, 1] - d) < 1e-3) and (np.all(np.abs(P[:, 2]) < 1e-3)
                                                                                  or np.all(np.abs(P[:, 2] + span) < 1e-3))), fi)
    body = _fillet(body, lambda P: _on_socket_rim(P, sec, np.array([0.0, d + t, zc]), np.array([0.0, 1.0, 0.0]), xd, wall), fo)
    body = _bore(body, bore, sec, np.array([0.0, d + t, zc]), np.array([0.0, 1.0, 0.0]), xd)
    return body, {"socket_end": d + t + Ls}


def flange_plate_mm(sec: Mapping | None) -> float:
    """舵盘法兰的盘厚：上面接套管时螺钉头要沉在套管底下（沉头孔），用 plate_cb_mm"""
    return DESIGN["plate_mm"] if sec is None else DESIGN["plate_cb_mm"]


def housing_plate_mm(sec: Mapping | None, table: bool = False) -> float:
    """壳体底座的板厚：外侧接套管时螺钉头沉在套管底下，用 plate_cb_mm；基座立板外侧敞开，用 plate_mm"""
    if table:
        return DESIGN["base_plate_mm"]
    return DESIGN["plate_cb_mm"] if sec is not None else DESIGN["plate_mm"]


def flange(sec: Mapping | None, xdir: np.ndarray | None = None) -> tuple[int, dict]:
    """舵盘法兰（模组坐标系）：圆盘 + 沿轴的套管"""
    xd = np.array([1.0, 0.0, 0.0]) if xdir is None else np.asarray(xdir, float)
    wall, Ls = DESIGN["socket_wall_mm"], DESIGN["socket_len_mm"]
    t = flange_plate_mm(sec)
    so = 0.0 if sec is None else ((sec["outer"] if sec["shape"] == "circle" else math.hypot(*sec["outer"])) + 2 * wall)
    r = max(15.0, so / 2 + _rim())
    disk = _cyl((0, 0, 0), (0, 0, t), r)
    if sec is None:
        return _cut(disk, _horn_holes(0.0, t)), {"socket_end": t}
    sock = _prism(sec, np.array([0.0, 0.0, t]), np.array([0.0, 0.0, 1.0]), Ls, xd, grow=wall)
    bore = _prism(sec, np.array([0.0, 0.0, t]), np.array([0.0, 0.0, 1.0]), Ls + 1, xd, hollow=False)
    body = _fuse([disk, sock])
    body = _fillet(body, lambda P: _on_socket_rim(P, sec, np.array([0.0, 0.0, t]), np.array([0.0, 0.0, 1.0]), xd, wall),
                   DESIGN["fillet_socket_mm"])
    body = _bore(body, bore, sec, np.array([0.0, 0.0, t]), np.array([0.0, 0.0, 1.0]), xd)
    return _cut(body, _horn_holes(0.0, t, cb_top=True)), {"socket_end": t + Ls}


def housing_base(sec: Mapping | None, g: Mapping, *, table_z: float | None = None, xdir: np.ndarray | None = None) -> int:
    """壳体底座（模组坐标系）：底面上的板（4 个 M2.5 孔），外侧套管接父杆；table_z 给出时做成落到安装面的立板加底板"""
    xd = np.array([1.0, 0.0, 0.0]) if xdir is None else np.asarray(xdir, float)
    wall, Ls = DESIGN["socket_wall_mm"], DESIGN["socket_len_mm"]
    t = housing_plate_mm(sec, table_z is not None)
    yb, zc = -g["axis_to_bottom"], -24.5
    so = 0.0 if sec is None else ((sec["outer"] if sec["shape"] == "circle" else max(sec["outer"])) + 2 * wall)
    fo = _rim() if sec is not None else 0.0
    hw = max(g["half_width"], so / 2 + fo)                      # 板要盖住套管，四周留出倒圆的地方
    zh = max(22.0, so / 2 + fo)
    z_lo = zc - zh if table_z is None else table_z
    plate = _box(-hw, hw, yb - t, yb, z_lo, zc + zh)
    holes = [_cyl((x, yb - t - 1, zc + z), (0, t + 2, 0), DESIGN["bolt_hole_mm"] / 2) for x, z in BOTTOM_HOLES]
    if t > DESIGN["plate_mm"]:                                   # 螺钉头沉下去（外侧是套管）
        cb = DESIGN["cb_depth_mm"]
        holes += [_cyl((x, yb - t - 1, zc + z), (0, cb + 1, 0), DESIGN["cb_d_mm"] / 2) for x, z in BOTTOM_HOLES]
    parts = [plate]
    if table_z is not None:
        f = DESIGN["foot_mm"]
        parts.append(_box(-f / 2, f / 2, yb - f, yb, table_z, table_z + t))
    elif sec is not None:
        parts.append(_prism(sec, np.array([0.0, yb - t, zc]), np.array([0.0, -1.0, 0.0]), Ls, xd,
                            grow=wall))
    body = _fuse(parts)
    if table_z is not None:
        # 立板根部的内角：正面一条、两侧各一条（只倒正面时两侧剩下尖的内角，有限元算出是奇异点）
        body = _fillet(body, lambda P: bool(np.all(np.abs(P[:, 2] - (table_z + t)) < 1e-3)
                                            and (np.all(np.abs(P[:, 1] - (yb - t)) < 1e-3)
                                                 or (np.all(np.abs(np.abs(P[:, 0]) - hw) < 1e-3)
                                                     and np.all((P[:, 1] >= yb - t - 1e-3) & (P[:, 1] <= yb + 1e-3))))),
                       DESIGN["base_fillet_mm"])
    elif sec is not None:
        body = _fillet(body, lambda P: _on_socket_rim(P, sec, np.array([0.0, yb - t, zc]), np.array([0.0, -1.0, 0.0]), xd, wall),
                       DESIGN["fillet_socket_mm"])
    if table_z is None and sec is not None:
        body = _bore(body, _prism(sec, np.array([0.0, yb - t, zc]), np.array([0.0, -1.0, 0.0]), Ls + 1, xd, hollow=False),
                     sec, np.array([0.0, yb - t, zc]), np.array([0.0, -1.0, 0.0]), xd)
    return _cut(body, holes)


def _hole_set(A: np.ndarray, holes, t: float, cb: float = 0.0, seat=None) -> dict:
    """一组螺钉孔（世界坐标）。holes：[(孔在贴合面上的点, 指向螺钉头一侧的方向), ...]（组件坐标）；t 板厚，cb 沉头孔深。
    记各孔通孔段的中点与长度（强度分析选孔壁）、螺钉头底面的位置与朝向（查螺钉头干涉）；seat：贴着对方零件的面（点、外法向）"""
    R = A[:3, :3]
    cs, heads, dirs = [], [], []
    for p, d in holes:
        p, d = np.asarray(p, float), np.asarray(d, float)
        cs.append(_r((A @ np.append(p + d * (t - cb) / 2, 1.0))[:3]))
        heads.append(_r((A @ np.append(p + d * (t - cb), 1.0))[:3]))
        dirs.append(_r(R @ d))
    out = {"type": "holes", "radius_mm": DESIGN["bolt_hole_mm"] / 2, "length_mm": t - cb, "axis": dirs[0], "centers": cs,
           "heads": heads, "head_dirs": dirs, "counterbore_mm": cb}
    if seat is not None:
        out["seat"] = {"point": _r((A @ np.append(np.asarray(seat[0], float), 1.0))[:3]), "normal": _r(R @ np.asarray(seat[1], float))}
    return out


def _socket(A: np.ndarray, p0, d, sec: Mapping, xdir: np.ndarray) -> dict:
    """套管孔（世界坐标）：起点（孔底）、方向、深度、截面、矩形截面第一边的方向"""
    return {"type": "socket", "start": _r((A @ np.append(np.asarray(p0, float), 1.0))[:3]),
            "dir": _r(A[:3, :3] @ np.asarray(d, float)), "length_mm": DESIGN["socket_len_mm"],
            "section": {"shape": sec["shape"], "outer": sec["outer"]}, "xdir": _r(A[:3, :3] @ xdir),
            "bottom_fillet_mm": DESIGN["bore_fillet_mm"]}


def _r(v) -> list[float]:
    return [round(float(x), 4) for x in v]


def _horn_pts(z: float) -> list:
    return [(PCD_MM / 2 * math.cos(2 * math.pi * k / HORN_HOLES), PCD_MM / 2 * math.sin(2 * math.pi * k / HORN_HOLES), z)
            for k in range(HORN_HOLES)]


def _overlap(a: int, b: int) -> float:
    """两个实体相交的体积（不改动两者）"""
    occ = _occ()
    bb1, bb2 = occ.getBoundingBox(3, a), occ.getBoundingBox(3, b)
    if any(bb1[q] > bb2[q + 3] or bb2[q] > bb1[q + 3] for q in range(3)):
        return 0.0
    res, _ = occ.intersect([(3, a)], [(3, b)], removeObject=False, removeTool=False)
    occ.synchronize()
    vol = sum(occ.getMass(3, t_) for d_, t_ in res if d_ == 3)
    if res:
        occ.remove(res, recursive=True)
        occ.synchronize()
    return vol


ACCESS_MM = 40.0                # 拧螺钉的通道查到螺钉头外这么远（套管长 20 + 余量）


def bolt_heads(parts: list[dict]) -> list[dict]:
    """螺钉头能不能放下：每个螺钉孔按 M2.5 内六角圆柱头（ISO 4762）的头部做一个圆柱，查它与全部零件（含本零件）是否相交。
    螺钉头压在套管底下、伸进管子或套管壁时，管子插不到底、螺钉也拧不上"""
    occ = _occ()
    hd, hk = DESIGN["head_d_mm"], DESIGN["head_k_mm"]
    out = []
    for p in parts:
        for side in ("fixed", "load"):
            h = (p.get("interfaces") or {}).get(side)
            if not h or h.get("type") != "holes":
                continue
            for k, (b, d) in enumerate(zip(h["heads"], h["head_dirs"])):
                d = np.asarray(d, float)
                # 头部底面略抬 0.01 mm：贴着支承面算接触，不算干涉
                tag = _cyl(np.asarray(b, float) + 0.01 * d, d * hk, hd / 2)
                occ.synchronize()
                for q in parts:
                    v = _overlap(tag, q["tag"])
                    if v > 0.05:
                        out.append({"part": p["name"], "hole": k + 1, "with": q["name"], "volume_mm3": round(v, 2)})
                occ.remove([(3, tag)])
                # 拧螺钉的通道：头部（有沉头孔时按沉头孔直径）沿装入方向退出去的路上不能被本零件挡住（套管壁、套管口）
                ra = (DESIGN["cb_d_mm"] if h.get("counterbore_mm") else hd) / 2
                tag = _cyl(np.asarray(b, float) + 0.01 * d, d * ACCESS_MM, ra - 0.01)
                occ.synchronize()
                v = _overlap(tag, p["tag"])
                if v > 0.05 or _too_close_to_bore(p, np.asarray(b, float), ra):
                    out.append({"part": p["name"], "hole": k + 1, "with": p["name"], "volume_mm3": round(v, 2), "access": True,
                                "fix": _access_fix(p, np.asarray(b, float), d, ra)})
                occ.remove([(3, tag)])
                occ.synchronize()
    return out


def _socket_of(p: Mapping) -> Mapping | None:
    return next((x for x in (p.get("interfaces") or {}).values() if x and x.get("type") == "socket"), None)


def _radial(s: Mapping, b: np.ndarray) -> float:
    u = np.asarray(s["dir"], float)
    r = b - np.asarray(s["start"], float)
    return float(np.linalg.norm(r - (r @ u) * u))


def _too_close_to_bore(p: Mapping, b: np.ndarray, ra: float) -> bool:
    """圆形套管：沉头孔在套管底下、却伸进了孔底圆角（剩下一条薄边，扳手也会刮到）"""
    s = _socket_of(p)
    if s is None or s["section"]["shape"] != "circle":
        return False
    rb = s["section"]["outer"] / 2
    rad = _radial(s, b)
    under = rad - ra < rb + DESIGN["socket_wall_mm"] + DESIGN["fillet_socket_mm"]
    return bool(under and rad + ra + DESIGN["bore_fillet_mm"] > rb + 1e-6)


def _access_fix(p: Mapping, b: np.ndarray, d: np.ndarray, ra: float) -> str:
    """螺钉通道被套管挡住时的改法：套管孔（= 杆件外廓）要把螺钉头与沉头孔整个让出来"""
    s = _socket_of(p)
    if s is None:
        return "螺钉头上方要留出拧螺钉的空间"
    rad, f = _radial(s, b), DESIGN["bore_fillet_mm"]
    if s["section"]["shape"] == "circle":
        return (f"把这根杆的外径加大到至少 {math.ceil(2 * (rad + ra + f) + 0.5):g} mm"
                "（螺钉从管孔里装，头部、沉头孔和扳手都要在管孔里面，并让开孔底圆角）")
    return f"把这根杆的截面加大，让离轴线 {rad + ra + f:.1f} mm 以内都在管孔里面（螺钉从管孔里装）"


def build(concept: Mapping, fit_result: Mapping, comp: Mapping, out_dir: str | Path | None = None) -> dict:
    """生成并装配；返回 {"parts": [...], "interferences": [...], "mass_kg", "cog_mm", "status", "step"}"""
    from analysis.fea.geometry import _LOCK, _gmsh

    if fit_result.get("overall") == "fail":
        raise CadError("装配校核没通过，不生成")
    lay = layout(concept, fit_result, comp)
    g, m = lay["geometry"], lay["model"]
    parts: list[dict] = []
    with _LOCK:
        gm = _gmsh()
        gm.clear()
        gm.model.add("robot")
        for jid, J in lay["joints"].items():
            A = J["H"]
            tag = actuator_solid(comp)
            _place(tag, A)
            parts.append({"name": f"{jid} 模组 {comp.get('model')}", "kind": "actuator", "tag": tag, "joint": jid, "body": J["parent"],
                          "mass_kg": (comp["params"].get("mass_kg") or {}).get("value"), "component": comp["id"]})
            child_link = m.links[J["child"]]
            nxt = [c for c in m.joints if c.parent == J["child"]]
            sec = _section(child_link) if (nxt or J["kind"] == "flange") else None
            xw = _link_xdir(lay, jid)
            t = DESIGN["plate_mm"]
            U = J["U"]
            if J["kind"] == "clevis":
                d = J["d_mm"] + DESIGN["clearance_mm"]
                tag, info = clevis(d, sec, g, U[:3, :3].T @ xw)
                name = f"{jid} U 形支架"
                fixed = _hole_set(U, [(p, (0, 0, 1)) for p in _horn_pts(0.0)] + [(p, (0, 0, -1)) for p in _horn_pts(-49.0)], t)
                load = None if sec is None else _socket(U, (0.0, d + t, -24.5), (0, 1, 0), sec, U[:3, :3].T @ xw)
            else:
                tag, info = flange(sec, U[:3, :3].T @ xw)
                name = f"{jid} 舵盘法兰"
                tf = flange_plate_mm(sec)
                fixed = _hole_set(U, [(p, (0, 0, 1)) for p in _horn_pts(0.0)], tf, DESIGN["cb_depth_mm"] if sec is not None else 0.0)
                load = None if sec is None else _socket(U, (0.0, 0.0, tf), (0, 0, 1), sec, U[:3, :3].T @ xw)
            _place(tag, U)
            parts.append({"name": name, "kind": "bracket", "tag": tag, "joint": jid, "material": "6061-T6", "body": J["child"],
                          "role": "output", "interfaces": {"fixed": fixed, "load": load}})
            J["socket_end"] = info["socket_end"]
            if J["parent"] == "base":
                table_z = -float(J["origin"][2])                       # 安装面在模组坐标系里的 z（竖轴）
                tag = housing_base(None, g, table_z=table_z)
                _place(tag, A)
                yb = -g["axis_to_bottom"]
                holes = _hole_set(A, [((x, yb, -24.5 + z), (0, -1, 0)) for x, z in BOTTOM_HOLES], housing_plate_mm(None, True),
                                  seat=((0.0, yb, -24.5), (0, 1, 0)))
                foot = {"type": "plane", "point": _r((A @ np.array([0.0, yb - DESIGN["foot_mm"] / 2, table_z, 1.0]))[:3]),
                        "normal": _r(-A[:3, 2])}
                parts.append({"name": f"{jid} 基座", "kind": "bracket", "tag": tag, "joint": jid, "material": "6061-T6",
                              "body": "base", "role": "housing", "interfaces": {"fixed": foot, "load": holes}})
            else:
                psec = _section(m.links[J["parent"]])
                pj = m.by_child[J["parent"]]
                hx = J["H"][:3, :3].T @ _link_xdir(lay, pj.id)
                tag = housing_base(psec, g, xdir=hx)
                _place(tag, A)
                yb = -g["axis_to_bottom"]
                th = housing_plate_mm(psec)
                holes = _hole_set(A, [((x, yb, -24.5 + z), (0, -1, 0)) for x, z in BOTTOM_HOLES], th,
                                  DESIGN["cb_depth_mm"] if th > DESIGN["plate_mm"] else 0.0, seat=((0.0, yb, -24.5), (0, 1, 0)))
                parts.append({"name": f"{jid} 壳体底座", "kind": "bracket", "tag": tag, "joint": jid, "material": "6061-T6",
                              "body": J["parent"], "role": "housing",
                              "interfaces": {"fixed": _socket(A, (0.0, yb - th, -24.5), (0, -1, 0), psec, hx), "load": holes}})
        # 杆件：本关节的套管口到下一关节壳体底座的套管底
        t, Ls = DESIGN["plate_mm"], DESIGN["socket_len_mm"]
        problems = []
        for jid, J in lay["joints"].items():
            link = m.links[J["child"]]
            nxt = [c for c in m.joints if c.parent == J["child"]]
            A = J["U"]
            axis_dir = A[:3, 1] if J["kind"] == "clevis" else A[:3, 2]
            if J["kind"] == "clevis":                                   # U 坐标系里 z = −24.5 是两舵盘的中面
                start = (A @ np.array([0.0, J["socket_end"] - Ls, -24.5, 1.0]))[:3]
            else:
                start = (A @ np.array([0.0, 0.0, J["socket_end"] - Ls, 1.0]))[:3]
            if nxt:
                K_ = lay["joints"][nxt[0].id]
                yb = -g["axis_to_bottom"]
                end = (K_["H"] @ np.array([0.0, yb - housing_plate_mm(_section(link)), -24.5, 1.0]))[:3]
                length = float((end - start) @ axis_dir)
                if length < 2 * Ls:
                    problems.append(f"杆件 {link['id']}：两端套管之间没有空隙（长 {length:.1f} mm < {2 * Ls:g}）")
                    continue
            else:
                length = float(link["length_mm"])
            sec = _section(link)
            xl = _link_xdir(lay, jid)
            tag = _prism(sec, start, axis_dir, length, xl)
            tag = _round_ends(tag, sec, start, axis_dir, length if nxt else None, xl)
            parts.append({"name": f"杆件 {link['id']}（{link['shape']}，长 {length:.1f} mm）", "kind": "link", "tag": tag,
                          "link": link["id"], "material": link.get("material") or "6061-T6", "length_mm": round(length, 3),
                          "body": link["id"]})
        _occ().synchronize()
        for p in parts:
            if p["kind"] != "actuator":
                vol = _occ().getMass(3, p["tag"])
                p["volume_mm3"] = round(vol, 1)
                p["mass_kg"] = round(vol * DENSITY_KG_MM3.get(p["material"], DENSITY_KG_MM3["6061-T6"]), 4)
            p["cog_mm"] = [round(v, 2) for v in _occ().getCenterOfMass(3, p["tag"])]
        hits = []
        for i in range(len(parts)):
            for k in range(i + 1, len(parts)):
                a, b = parts[i], parts[k]
                bb1, bb2 = _occ().getBoundingBox(3, a["tag"]), _occ().getBoundingBox(3, b["tag"])
                if any(bb1[q] > bb2[q + 3] or bb2[q] > bb1[q + 3] for q in range(3)):
                    continue
                res, _ = _occ().intersect([(3, a["tag"])], [(3, b["tag"])], removeObject=False, removeTool=False)
                _occ().synchronize()
                vol = sum(_occ().getMass(3, t_) for d_, t_ in res if d_ == 3)
                if res:
                    _occ().remove(res, recursive=True)
                    _occ().synchronize()
                if vol > 1.0:
                    hits.append({"a": a["name"], "b": b["name"], "volume_mm3": round(vol, 1)})
        heads = bolt_heads(parts)
        step = None
        if out_dir is not None:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            step = out_dir / "assembly.step"
            gm.write(str(step))
        gm.clear()
    total = sum(p["mass_kg"] for p in parts if p.get("mass_kg") is not None)
    cog = np.sum([np.array(p["cog_mm"]) * p["mass_kg"] for p in parts if p.get("mass_kg")], axis=0) / total
    for p in parts:
        p.pop("tag", None)
    seen = set()
    for h in heads:
        if (h["part"], h["with"], h.get("access")) not in seen:
            seen.add((h["part"], h["with"], h.get("access")))
            problems.append(f"{h['part']} 的螺钉装不进去：螺钉头的通道被 {h['with']} 的套管挡住（第 {h['hole']} 孔等）；改法：{h['fix']}"
                            if h.get("access") else f"{h['part']} 的螺钉头放不下：与 {h['with']} 相交（第 {h['hole']} 孔等）")
    status = "fail" if hits or problems else "pass"
    return {"status": status, "parts": parts, "interferences": hits, "problems": problems,
            "mass_kg": round(total, 4), "cog_mm": [round(float(v), 1) for v in cog], "design": DESIGN,
            "step": None if step is None else step.name,
            "notes": ["模组外形用零件库的保守包络，干涉检查偏保守", "支架、套管尺寸是第一版设计值（DESIGN），之后由 AI 按载荷与工艺改"]}


def main(argv: list[str] | None = None) -> int:
    import argparse

    from analysis.robot import fit
    from kb.library import JsonLibrary

    ap = argparse.ArgumentParser(prog="python -m assist.robot_cad", description="整机三维装配（ADR-0115 44.3）")
    ap.add_argument("concept_result", type=Path)
    ap.add_argument("build_result", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True, help="输出目录（assembly.step、cad-result.json）")
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    br = json.loads(a.build_result.read_text(encoding="utf-8"))
    lib = JsonLibrary(Path(__file__).resolve().parents[1] / "data" / "library")
    picks = br["picks"]
    if len(picks) != 1 or next(iter(picks.values()))["chain"] != "smart":
        raise CadError("这一步只做“全部关节同一种一体化模组”的整机")
    comp = lib.get(next(iter(picks.values()))["components"][0])
    concept = cr["chosen"]
    fr = fit.check(concept, {j["id"]: comp for j in concept["joints"]})
    res = build(concept, fr, comp, a.out)
    (a.out / "cad-result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{res['status']}：{len(res['parts'])} 个零件，整机 {res['mass_kg']} kg，重心 {res['cog_mm']}；"
          f"干涉 {len(res['interferences'])} 处；{'；'.join(res['problems'])}")
    for h in res["interferences"]:
        print(f"  干涉：{h['a']} × {h['b']}：{h['volume_mm3']} mm³")
    return 0 if res["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
