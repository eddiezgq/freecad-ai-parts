"""龙门取放机器人的三维装配与复核（ADR-0115 44.5.5 第二步）：按方案、第一步选定的直线模组与吸盘，生成自制件（横梁、立柱与地脚板、
Z 轴连接板、管夹、吸盘座、竖管），在零位装起来，查干涉与取放区的避让，算质量与重心；按装配出来的真实质量与偏置重跑节拍多体动力学、
复核选件（assist.gantry_build 的同一套规则）；整个门架（横梁 + 立柱 + 地脚板）做有限元，出最大变形与前几阶固有频率。不调用 AI。

布置（方案坐标系：安装面 z = 0，X 沿横梁，末端点按方案的运动学不变）：
  X 模组倒挂在横梁下面，滑台面朝下，在末端点正上方；Z 模组竖直装在连接板（L 形：上板接 X 滑台，竖板接 Z 模组背面）上，
  滑台面朝 +y；竖管用管夹装在 Z 滑台上，下端是吸盘座和吸盘。X 滑台面的高度由“Z 模组下端高出一叠裁片最高处”定，
  不沿用方案的关节原点高度（方案只定末端点的位置，模组怎么摆是这一步的事）。
  立柱在横梁两端，离取料区、放料区（以取放点为中心、边长取裁片长边的正方形，高到一叠最高处）至少 DESIGN["keepout_clear_mm"]。

自制件尺寸按 DESIGN（第一版设计值，同案例 A 的做法：之后由 AI 按载荷与工艺改，代码校核）。直线模组按零件库的包络
（目录的 L1 + 行程、B1、H1，含滑台）建成长方体，质量用目录值（不用包络体积），本体重心取包络中心；滑台质量放在滑台面中心。
干涉：同一构件上的零件按实体求交；静止件与运动件、两个运动构件之间，把运动件的外接长方体沿各轴行程扫一遍再求交（偏保守）。
"""

from __future__ import annotations

import copy
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from assist import gantry_build as GB

FORMAT = "gantry-cad/1"
G = 9.81
DESIGN = {
    "keepout_clear_mm": 50.0,    # 立柱、地脚板离取放区的距离
    "stack_clear_mm": 20.0,      # Z 模组下端高出一叠最高处
    "beam_w_mm": 80.0,           # 横梁矩形管：宽（y，不超过 X 模组宽 B1，Z 模组才能贴着 X 模组背后上下）、高（z）、壁厚
    "beam_h_mm": 160.0,
    "beam_wall_mm": 6.0,
    "col_w_mm": 100.0,           # 立柱方管边长、壁厚
    "col_wall_mm": 6.0,
    "foot_mm": 160.0,            # 地脚板边长、厚（用螺栓固定在台面上）
    "foot_t_mm": 12.0,
    "plate_mm": 10.0,            # 连接板：上板（接 X 滑台）与竖板（接 Z 模组背面）厚、宽（x）
    "web_mm": 10.0,
    "bracket_w_mm": 100.0,
    "bracket_fillet_mm": 5.0,    # 上板与竖板的内角
    "z_top_gap_mm": 8.0,         # Z 模组上端离上板（让开内角圆角）
    "clamp_back_mm": 20.0,       # 管夹：Z 滑台面到竖管外壁的材料厚、管夹在竖管前面的厚、宽（x）、高（z）
    "clamp_front_mm": 10.0,
    "clamp_w_mm": 70.0,
    "clamp_h_mm": 60.0,
    "seat_h_mm": 20.0,           # 吸盘座：与竖管同径的圆盘、中心通气孔
    "seat_hole_mm": 8.0,
    "pad_mm": [100.0, 60.0, 2.0],  # 有限元用：横梁跨中下面的垫块（运动部分的质量与惯性力加在这里，取最不利的跨中位置）
}
DENSITY_KG_MM3 = {"6061-T6": 2.70e-6}
MATERIAL = "6061-T6"
E_MPA = 68900.0                  # analysis/common/materials.yaml 的 6061-T6
FEA_MESH_MM = 12.0               # 门架 2.4 m 长、壁厚 6 mm：粗网格 12 mm（约 8 万个二阶单元），再按 1/1.5 加密到 8 mm 核对
TIME_LIMIT_S = 3000              # 细网格约 18 万个二阶单元，静力加模态要十几分钟
N_MODES = 4
LIMITS = ["直线模组按目录外形建成长方体（含滑台），型材槽、端盖、电机没建；本体重心取外形中心",
          "螺钉孔、型材连接件（模组装在横梁上的安装件）没建：门架当一个焊接整体算，连接处的柔度没计入，固有频率偏高",
          "门架有限元里 X 模组只计质量、不计刚度（它的铝型材实际会帮横梁承载，变形偏大、偏保守）",
          "运动部分放在跨中（垂直变形最不利）；X 轴最大推力与 Z 轴最大惯性力同时加上（节拍里两轴不同时加速，偏保守）",
          "地脚板底面全固定（台面当刚体）"]


class CadError(ValueError):
    pass


def _occ():
    from analysis.fea.geometry import _gmsh

    return _gmsh().model.occ


def _box(lo, hi) -> int:
    return _occ().addBox(lo[0], lo[1], lo[2], hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])


def _cut(obj: int, tools: list[int]) -> int:
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


def _tube_rect(lo, hi, wall, axis: int) -> int:
    """矩形管：沿 axis 两端开口"""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    ilo, ihi = lo + wall, hi - wall
    ilo[axis], ihi[axis] = lo[axis] - 1, hi[axis] + 1
    return _cut(_box(lo, hi), [_box(ilo, ihi)])


def _cyl_z(x, y, z0, z1, r) -> int:
    return _occ().addCylinder(x, y, z0, 0, 0, z1 - z0, r)


def _env(comp: Mapping) -> dict:
    part = ((comp.get("envelope") or {}).get("parts") or [{}])[0]

    def v(k):
        x = part.get(k)
        return (x or {}).get("value") if isinstance(x, dict) else x
    return {k: v(k) for k in ("length_mm", "width_mm", "height_mm", "diameter_mm")}


# ---------------------------------------------------------------- 布置
def layout(concept: Mapping, cond: Mapping, picks: Mapping, lib) -> dict:
    """各零件的位置（mm，方案坐标系，零位）与两个构件的参考点；只算数，不建实体"""
    from analysis.robot import kinematics as K

    ax = GB.axes(concept)
    if len(ax) != 2 or ax[0]["dir"] != 0 or ax[1]["dir"] != 2:
        raise CadError("三维装配只做 X（水平，沿 x）– Z（竖直）两轴龙门")
    if (concept.get("base") or {}).get("mount") not in (None, "table", "floor"):
        raise CadError("龙门只做装在台面或地面上的")
    m = K.build(concept)
    jx, jz = (next(j for j in m.joints if j.id == a["joint"]) for a in ax)
    tool0 = np.asarray(jx.origin, float) + np.asarray(jz.origin, float) + np.asarray(m.tool_offset, float)
    D = DESIGN
    comps = {}
    for a in ax:
        p = picks.get(a["joint"]) or {}
        c = lib.get(p.get("component")) if p.get("component") else None
        if c is None:
            raise CadError(f"{a['joint']} 还没有选定直线模组")
        e = _env(c)
        if None in (e["length_mm"], e["width_mm"], e["height_mm"]):
            raise CadError(f"{c.get('model')} 的外形尺寸（L1、B1、H1）不全，建不了外壳")
        comps[a["joint"]] = (c, e)
    (cx, ex), (cz, ez) = comps[ax[0]["joint"]], comps[ax[1]["joint"]]
    xlo, xhi = ax[0]["lo"], ax[0]["hi"]
    zlo, zhi = ax[1]["lo"], ax[1]["hi"]
    if D["beam_w_mm"] > ex["width_mm"] + 1e-9:
        raise CadError("横梁比 X 模组宽：Z 模组贴不到 X 模组背后")
    stack = float(cond.get("stack_height") or 0.0)
    side = max(float(cond.get("part_length") or 0.0), float(cond.get("part_width") or 0.0))
    if side <= 0:
        raise CadError("取放条件里没有裁片尺寸：取放区的避让查不了")
    pts = [np.asarray(p, float) for p in (concept.get("workspace") or {}).get("points_mm") or []]
    if len(pts) < 2:
        raise CadError("方案里没有取料点、放料点")
    Lz = ez["length_mm"] + (zhi - zlo)                     # Z 模组本体长 = L1 + 行程
    Lx = ex["length_mm"] + (xhi - xlo)
    Hx, Bx, Hz, Bz = ex["height_mm"], ex["width_mm"], ez["height_mm"], ez["width_mm"]
    zs = stack + D["stack_clear_mm"] + Lz + D["z_top_gap_mm"] + D["plate_mm"]   # X 滑台面（朝下）的高度
    ox, oy = float(tool0[0]), float(tool0[1])          # 末端点在零位的 x、y（X 滑台面中心在它正上方）
    ztop = zs - D["plate_mm"] - D["z_top_gap_mm"]          # Z 模组上端
    zc0 = ztop - zhi - ez["length_mm"] / 2                  # Z 滑台中心在零位的高度
    tube = next((lk for lk in concept["links"] if lk["id"] == jz.child), None)
    sec = (tube or {}).get("section") or {}
    if (tube or {}).get("shape") != "tube" or not sec.get("od_mm"):
        raise CadError("Z 轴杆件不是圆管：管夹按圆管做")
    ro, ri = sec["od_mm"] / 2, sec["id_mm"] / 2
    ys = oy - ro - D["clamp_back_mm"]                       # Z 滑台面（朝 +y）
    yzb = ys - Hz                                           # Z 模组背面
    yw = yzb - D["web_mm"]                                  # 竖板背面
    grip = ((picks.get("_gripper") or {}).get("envelope") or {})
    cup_h, cup_d = grip.get("length_mm"), grip.get("diameter_mm")
    if cup_h is None or cup_d is None:
        raise CadError("吸盘的外形尺寸不全")
    zt = float(tool0[2])                                     # 末端点（吸盘口）零位高度
    tube_lo = zt + cup_h + D["seat_h_mm"]
    tube_hi = zc0 + D["clamp_h_mm"] / 2
    if tube_hi - tube_lo < D["clamp_h_mm"]:
        raise CadError(f"竖管太短（{tube_hi - tube_lo:.1f} mm），夹不住：Z 滑台离末端点太近")
    pick, place = pts[0], pts[-1]
    lo_pts, hi_pts = min(p[0] for p in pts), max(p[0] for p in pts)
    xl = lo_pts - side / 2 - D["keepout_clear_mm"] - D["col_w_mm"] / 2
    xr = hi_pts + side / 2 + D["keepout_clear_mm"] + D["col_w_mm"] / 2
    zb = zs + Hx                                             # 横梁底面
    return {
        "axes": ax, "tool0_mm": tool0.tolist(), "slide_x_mm": zs, "zc0_mm": zc0, "y_slide_z_mm": ys,
        "x_ref_mm": [ox, oy, zs], "z_ref_mm": [ox, ys, zc0],
        "modules": {ax[0]["joint"]: {"component": cx["id"], "model": cx.get("model"), "box": [[ox + xlo - ex["length_mm"] / 2, oy - Bx / 2, zs],
                                                                                           [ox + xhi + ex["length_mm"] / 2, oy + Bx / 2, zs + Hx]],
                                     "length_mm": Lx},
                    ax[1]["joint"]: {"component": cz["id"], "model": cz.get("model"),
                                     "box": [[ox - Bz / 2, yzb, ztop - Lz], [ox + Bz / 2, ys, ztop]],
                                     "length_mm": Lz}},
        "beam": [[xl - D["col_w_mm"] / 2, oy - D["beam_w_mm"] / 2, zb], [xr + D["col_w_mm"] / 2, oy + D["beam_w_mm"] / 2, zb + D["beam_h_mm"]]],
        "columns": [[[x - D["col_w_mm"] / 2, oy - D["col_w_mm"] / 2, D["foot_t_mm"]], [x + D["col_w_mm"] / 2, oy + D["col_w_mm"] / 2, zb]]
                    for x in (xl, xr)],
        "feet": [[[x - D["foot_mm"] / 2, oy - D["foot_mm"] / 2, 0.0], [x + D["foot_mm"] / 2, oy + D["foot_mm"] / 2, D["foot_t_mm"]]]
                 for x in (xl, xr)],
        "bracket": {"top": [[ox - D["bracket_w_mm"] / 2, yw, zs - D["plate_mm"]], [ox + D["bracket_w_mm"] / 2, oy + Bx / 2, zs]],
                    "web": [[ox - D["bracket_w_mm"] / 2, yw, ztop - Lz], [ox + D["bracket_w_mm"] / 2, yzb, zs - D["plate_mm"]]]},
        "clamp": [[ox - D["clamp_w_mm"] / 2, ys, zc0 - D["clamp_h_mm"] / 2], [ox + D["clamp_w_mm"] / 2, oy + ro + D["clamp_front_mm"],
                                                                            zc0 + D["clamp_h_mm"] / 2]],
        "tube": {"x": ox, "y": oy, "z0": tube_lo, "z1": tube_hi, "ro": ro, "ri": ri},
        "seat": {"z0": zt + cup_h, "z1": zt + cup_h + D["seat_h_mm"], "r": ro},
        "cup": {"z0": zt, "z1": zt + cup_h, "r": cup_d / 2},
        "keepouts": [{"name": n, "box": [[p[0] - side / 2, p[1] - side / 2, 0.0], [p[0] + side / 2, p[1] + side / 2, stack]]}
                     for n, p in (("取料区（一叠裁片）", pick), ("放料区", place))],
        "span_mm": xr - xl, "col_x_mm": [xl, xr], "beam_bottom_mm": zb,
        "concept_slide_x_mm": float(jx.origin[2]),
    }


def _solids(L: Mapping) -> list[dict]:
    """在当前 gmsh 模型里建出全部零件，返回 [{name, kind, body, tag, material?, mass_kg?, component?}]"""
    occ, D = _occ(), DESIGN
    jx, jz = (a["joint"] for a in L["axes"])
    parts = []
    beam = _tube_rect(*L["beam"], D["beam_wall_mm"], 0)
    parts.append({"name": "横梁（矩形管）", "kind": "frame", "body": "base", "tag": beam, "material": MATERIAL})
    for k, (c, f) in enumerate(zip(L["columns"], L["feet"], strict=True)):
        col = _fuse([_tube_rect(*c, D["col_wall_mm"], 2), _box(*f)])
        parts.append({"name": f"立柱与地脚板 {'左右'[k]}", "kind": "frame", "body": "base", "tag": col, "material": MATERIAL})
    for jid, body in ((jx, "base"), (jz, "x")):
        mo = L["modules"][jid]
        parts.append({"name": f"{jid} 直线模组 {mo['model']}（外形）", "kind": "module", "body": body, "tag": _box(*mo["box"]),
                      "component": mo["component"], "joint": jid})
    br = _fuse([_box(*L["bracket"]["top"]), _box(*L["bracket"]["web"])])
    occ.synchronize()
    web = L["bracket"]["web"]
    y_in, z_in = web[1][1], web[1][2]                        # 上板与竖板的内角（竖板前面、上板下面）

    def inner(P):
        return bool(np.all(np.abs(P[:, 1] - y_in) < 1e-6) and np.all(np.abs(P[:, 2] - z_in) < 1e-6))
    from assist.robot_cad import _fillet

    br = _fillet(br, inner, D["bracket_fillet_mm"])
    parts.append({"name": "Z 轴连接板（L 形）", "kind": "made", "body": "x", "tag": br, "material": MATERIAL})
    t = L["tube"]
    cl = _cut(_box(*L["clamp"]), [_cyl_z(t["x"], t["y"], L["clamp"][0][2] - 1, L["clamp"][1][2] + 1, t["ro"])])
    parts.append({"name": "管夹", "kind": "made", "body": "z", "tag": cl, "material": MATERIAL})
    tb = _cut(_cyl_z(t["x"], t["y"], t["z0"], t["z1"], t["ro"]), [_cyl_z(t["x"], t["y"], t["z0"] - 1, t["z1"] + 1, t["ri"])])
    parts.append({"name": f"竖管 Ø{2 * t['ro']:g}/Ø{2 * t['ri']:g}（长 {t['z1'] - t['z0']:.1f} mm）", "kind": "made", "body": "z", "tag": tb,
                  "material": MATERIAL, "length_mm": round(t["z1"] - t["z0"], 2)})
    s = L["seat"]
    st = _cut(_cyl_z(t["x"], t["y"], s["z0"], s["z1"], s["r"]),
              [_cyl_z(t["x"], t["y"], s["z0"] - 1, s["z1"] + 1, D["seat_hole_mm"] / 2)])
    parts.append({"name": "吸盘座", "kind": "made", "body": "z", "tag": st, "material": MATERIAL, "tool": True})
    c = L["cup"]
    parts.append({"name": "吸盘（外形）", "kind": "gripper", "body": "z", "tag": _cyl_z(t["x"], t["y"], c["z0"], c["z1"], c["r"]),
                  "tool": True})
    parts[-3]["tool"] = True                                  # 竖管下端伸进取料区是取料本身
    occ.synchronize()
    return parts


def _sweep_box(tag: int, dq: Mapping[int, tuple[float, float]]):
    bb = _occ().getBoundingBox(3, tag)
    lo, hi = list(bb[:3]), list(bb[3:])
    for k, (a, b) in dq.items():
        lo[k] += a
        hi[k] += b
    return lo, hi


def _box_overlap(a, b) -> float:
    v = 1.0
    for k in range(3):
        d = min(a[1][k], b[1][k]) - max(a[0][k], b[0][k])
        if d <= 0:
            return 0.0
        v *= d
    return v


def interferences(parts: list[dict], L: Mapping) -> tuple[list[dict], list[dict]]:
    """返回（零件之间的干涉, 进了取放区的零件）；体积 > 1 mm³ 才算（贴合面相交是零体积）"""
    from assist.robot_cad import _overlap

    occ = _occ()
    (ax_x, ax_z) = L["axes"]
    rng = {"x": {0: (ax_x["lo"], ax_x["hi"])}, "z": {0: (ax_x["lo"], ax_x["hi"]), 2: (ax_z["lo"], ax_z["hi"])}}
    rel = {("base", "x"): rng["x"], ("base", "z"): rng["z"], ("x", "z"): {2: (ax_z["lo"], ax_z["hi"])}}
    hits = []
    for i in range(len(parts)):
        for k in range(i + 1, len(parts)):
            a, b = parts[i], parts[k]
            if a["body"] == b["body"]:
                vol = _overlap(a["tag"], b["tag"])
                how = "零位实体相交"
            else:
                key = (a["body"], b["body"]) if (a["body"], b["body"]) in rel else (b["body"], a["body"])
                mov, fix = (b, a) if key == (a["body"], b["body"]) else (a, b)
                lo, hi = _sweep_box(mov["tag"], rel[key])
                tmp = _box(lo, hi)
                occ.synchronize()
                vol = _overlap(fix["tag"], tmp)
                occ.remove([(3, tmp)], recursive=True)
                occ.synchronize()
                how = f"{mov['name']}的外接长方体沿行程扫过"
            if vol > 1.0:
                hits.append({"a": a["name"], "b": b["name"], "volume_mm3": round(vol, 1), "how": how})
    keep = []
    for p in parts:
        if p.get("tool"):
            continue
        dq = rng.get(p["body"], {})
        lo, hi = _sweep_box(p["tag"], dq)
        for z in L["keepouts"]:
            v = _box_overlap((lo, hi), z["box"])
            if v > 1.0:
                keep.append({"part": p["name"], "zone": z["name"], "volume_mm3": round(v, 1)})
    return hits, keep


def assemble(concept: Mapping, cond: Mapping, picks: Mapping, lib, out_dir: str | Path | None = None) -> dict:
    """建实体、算质量与重心、查干涉；out_dir 给定时写 assembly.step（零位）"""
    from analysis.fea.geometry import _LOCK, _gmsh

    L = layout(concept, cond, picks, lib)
    with _LOCK:
        gm = _gmsh()
        gm.clear()
        gm.model.add("gantry")
        parts = _solids(L)
        occ = _occ()
        for p in parts:
            vol = occ.getMass(3, p["tag"])
            p["volume_mm3"] = round(vol, 1)
            p["cog_mm"] = [round(float(v), 3) for v in occ.getCenterOfMass(3, p["tag"])]
            if p.get("material"):
                p["mass_kg"] = round(vol * DENSITY_KG_MM3[p["material"]], 4)
        hits, keep = interferences(parts, L)
        step = None
        if out_dir is not None:
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            step = out_dir / "assembly.step"
            gm.write(str(step))
        gm.clear()
    for p in parts:
        p.pop("tag", None)
    status = "fail" if hits or keep else "pass"
    return {"status": status, "layout": _round(L), "parts": parts, "interferences": hits, "keepout_hits": keep,
            "step": None if step is None else step.name}


def _round(x):
    if isinstance(x, np.ndarray):
        return _round(x.tolist())
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_round(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return round(float(x), 3)
    return x


# ---------------------------------------------------------------- 复核用的质量与参考点
def bodies(cad: Mapping, picks: Mapping, part_kg: float, gripper_kg: float | None) -> dict:
    """多体动力学的集中质量：{关节: [(名称, kg, 相对该构件参考点的位置 mm)]}；构件原点 = 滑台面中心（三维装配的真实位置）"""
    L = cad["layout"]
    jx, jz = (a["joint"] for a in L["axes"])
    xr, zr = np.asarray(L["x_ref_mm"]), np.asarray(L["z_ref_mm"])
    rows = {jx: [], jz: []}
    missing = []
    ref = {"x": (jx, xr), "z": (jz, zr)}
    for jid in (jx, jz):
        p = picks[jid]
        if p.get("carriage_kg") is not None:
            rows[jid].append((f"{p['model']} 滑台", p["carriage_kg"], [0.0, 0.0, 0.0]))
        else:
            missing.append(f"{p['model']} 的滑台质量厂商没给")
    for q in cad["parts"]:
        if q["body"] not in ref:
            continue
        jid, r = ref[q["body"]]
        if q["kind"] == "module":
            kg = picks[q["joint"]].get("body_kg")
            if kg is None:
                missing.append(f"{q['name']} 的本体质量算不了")
                continue
            rows[jid].append((f"{picks[q['joint']]['model']} 本体（不含滑台）", kg, (np.asarray(q["cog_mm"]) - r).tolist()))
        elif q["kind"] == "gripper":
            if gripper_kg is None:
                missing.append("抓手质量厂商没给（未计入运动质量）")
            else:
                rows[jid].append((q["name"], gripper_kg, (np.asarray(q["cog_mm"]) - r).tolist()))
        else:
            rows[jid].append((q["name"], q["mass_kg"], (np.asarray(q["cog_mm"]) - r).tolist()))
    rows[jz].append(("工件（单片）", part_kg, (np.asarray(L["tool0_mm"]) - zr).tolist()))
    return {"bodies": rows, "missing": missing, "origins": {jx: xr.tolist(), jz: (zr - xr).tolist()}}


def moving(cad: Mapping, b: Mapping) -> dict:
    """两个运动构件的总质量与重心（方案坐标系，零位）"""
    L = cad["layout"]
    jx, jz = (a["joint"] for a in L["axes"])
    xr, zr = np.asarray(L["x_ref_mm"]), np.asarray(L["z_ref_mm"])
    out = {}
    for jid, r in ((jx, xr), (jz, zr)):
        m = sum(k for _n, k, _p in b["bodies"][jid])
        c = sum(k * (np.asarray(p) + r) for _n, k, p in b["bodies"][jid]) / m
        out[jid] = {"mass_kg": m, "cog_mm": c}
    tot = out[jx]["mass_kg"] + out[jz]["mass_kg"]
    out["all"] = {"mass_kg": tot, "cog_mm": (out[jx]["mass_kg"] * out[jx]["cog_mm"] + out[jz]["mass_kg"] * out[jz]["cog_mm"]) / tot}
    return out


# ---------------------------------------------------------------- 门架：公式校核与有限元
def frame_loads(cad: Mapping, picks: Mapping, mv: Mapping, loads: Mapping) -> dict:
    L = cad["layout"]
    jx, jz = (a["joint"] for a in L["axes"])
    x_static = (picks[jx].get("body_kg") or 0.0)
    fx = loads[jx]["thrust_n"]
    fz = max(loads[jz]["thrust_n"] - mv[jz]["mass_kg"] * G, 0.0)    # Z 轴推力减去运动部分的重量 = 惯性力
    return {"x_module_static_kg": x_static, "moving_kg": mv["all"]["mass_kg"], "thrust_x_n": fx, "inertia_z_n": fz}


def frame_formula(cad: Mapping, fl: Mapping) -> dict:
    """偏保守的公式（材料力学）：横梁按两端简支（跨度 = 立柱中心距），X 模组与横梁自重当均布、运动部分在跨中；
    X 推力让门架侧移，按两根立柱各自是悬臂（横梁不约束柱顶转动）算；第一阶频率按瑞利法（简支梁 + 跨中集中质量，梁的等效质量 17/35）"""
    L, D = cad["layout"], DESIGN
    span = L["span_mm"]
    b, h, t = D["beam_w_mm"], D["beam_h_mm"], D["beam_wall_mm"]
    Ib = (b * h ** 3 - (b - 2 * t) * (h - 2 * t) ** 3) / 12
    w = D["col_w_mm"]
    Ic = (w ** 4 - (w - 2 * D["col_wall_mm"]) ** 4) / 12
    hc = L["beam_bottom_mm"]
    beam_kg = next(p["mass_kg"] for p in cad["parts"] if p["name"].startswith("横梁"))
    q = (beam_kg + fl["x_module_static_kg"]) * G / span                     # N/mm
    P = fl["moving_kg"] * G + fl["inertia_z_n"]
    sag = 5 * q * span ** 4 / (384 * E_MPA * Ib) + P * span ** 3 / (48 * E_MPA * Ib)
    sway = fl["thrust_x_n"] * hc ** 3 / (2 * 3 * E_MPA * Ic)
    k = 48 * E_MPA * Ib / span ** 3 * 1000                                  # N/m
    m_eff = fl["moving_kg"] + 17 / 35 * (beam_kg + fl["x_module_static_kg"])
    f1 = math.sqrt(k / m_eff) / (2 * math.pi)
    return {"span_mm": round(span, 2), "beam_I_mm4": round(Ib, 0), "column_I_mm4": round(Ic, 0), "column_h_mm": round(hc, 2),
            "sag_mm": round(sag, 4), "sway_mm": round(sway, 4), "deflection_mm": round(math.hypot(sag, sway), 4),
            "f1_vertical_hz": round(f1, 2),
            "formulas": ["垂直：5qL⁴/(384EI) + PL³/(48EI)（简支）", "侧移：F·h³/(2·3EI)（两根悬臂立柱）",
                         "频率：(1/2π)√(48EI/L³ / (M + 17/35·m))（瑞利法）"]}


def frame_step(cad: Mapping, path: Path) -> dict:
    """门架一个实体（横梁 + 立柱 + 地脚板 + 跨中垫块）写成 STEP，返回面编号要用的位置"""
    from analysis.fea.geometry import _LOCK, _gmsh

    L, D = cad["layout"], DESIGN
    xm = sum(L["col_x_mm"]) / 2
    zb = L["beam_bottom_mm"]
    y0 = L["x_ref_mm"][1]
    px, py, pt = D["pad_mm"]
    pad = [[xm - px / 2, y0 - py / 2, zb - pt], [xm + px / 2, y0 + py / 2, zb]]
    with _LOCK:
        gm = _gmsh()
        gm.clear()
        gm.model.add("frame")
        tags = [_tube_rect(*L["beam"], D["beam_wall_mm"], 0)]
        for c, f in zip(L["columns"], L["feet"], strict=True):
            tags += [_tube_rect(*c, D["col_wall_mm"], 2), _box(*f)]
        tags.append(_box(*pad))
        _fuse(tags)
        _occ().synchronize()
        gm.write(str(path))
        gm.clear()
    return {"pad": pad, "zb": zb, "x_mid": xm}


def frame_study(cad: Mapping, fl: Mapping, mv: Mapping, step: str, geo: Mapping, size_mm: float) -> dict:
    import analysis

    L = cad["layout"]
    faces = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]

    def plane(z, inside):
        return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][2] - z) < 1e-6 and inside(f["bbox"])]
    feet = plane(0.0, lambda bb: True)
    xl, xr = L["col_x_mm"]
    cw = DESIGN["col_w_mm"]
    beam_bottom = plane(geo["zb"], lambda bb: bb[0] >= xl + cw / 2 - 1 and bb[3] <= xr - cw / 2 + 1)
    pad_bottom = plane(geo["pad"][0][2], lambda bb: True)
    if len(feet) != 2 or not beam_bottom or len(pad_bottom) != 1:
        raise CadError(f"门架的面没找全（地脚 {len(feet)}、横梁底 {len(beam_bottom)}、垫块 {len(pad_bottom)}）")
    jx, jz = (a["joint"] for a in L["axes"])
    dx = geo["x_mid"] - L["x_ref_mm"][0]                                    # 运动部分搬到跨中
    cx = (np.asarray(mv[jx]["cog_mm"]) + [dx, 0, 0]).tolist()
    cz = (np.asarray(mv[jz]["cog_mm"]) + [dx, 0, 0]).tolist()
    st = {"format": "fea-study/1", "name": "gantry-frame", "bodies": [{"id": "frame", "step_path": step, "material": MATERIAL}],
          "supports": [{"type": "fixed", "body": "frame", "faces": feet}],
          "loads": [{"type": "gravity", "body": "frame", "acceleration_m_s2": [0, 0, -G]},
                    {"type": "mass", "body": "frame", "faces": beam_bottom, "mass_kg": round(fl["x_module_static_kg"], 4),
                     "label": "X 模组本体"},
                    {"type": "mass", "body": "frame", "faces": pad_bottom, "mass_kg": round(fl["moving_kg"], 4),
                     "label": "运动部分（跨中）"},
                    {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": [round(v, 3) for v in cx],
                     "force_n": [round(fl["thrust_x_n"], 3), 0.0, 0.0]},
                    {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": [round(v, 3) for v in cz],
                     "force_n": [0.0, 0.0, -round(fl["inertia_z_n"], 3)]}],
          "steps": [{"id": "s", "type": "static"}, {"id": "m", "type": "modal", "n_modes": N_MODES}],
          "mesh": {"size_mm": size_mm}, "checks": {"convergence": False}, "time_limit_s": TIME_LIMIT_S,
          "probes": [{"id": "pad", "point_mm": [geo["x_mid"], L["x_ref_mm"][1], geo["pad"][0][2]]}],
          "provenance": {"drafted_by": "human", "confirmed_by_human": True}}
    r = analysis.run("fea", st)
    if r.get("status") != "ok":
        raise CadError("门架有限元没算成：" + "；".join(r.get("messages") or []))
    s, m = r["data"]["steps"]
    u = s["probes"][0]["u_mm"]
    notes = ["固定：两块地脚板底面", ("加载：重力；X 模组本体质量分在横梁底面；运动部分质量放在跨中垫块；"
                                      "X 轴最大推力的反作用加在 X 运动部分重心、Z 轴最大惯性力（推力减重量）加在 Z 运动部分重心（都搬到跨中）")]
    return {"study": {k: v for k, v in st.items() if k != "bodies"}, "notes": notes, "size_mm": size_mm,
            "u_pad_mm": [round(float(v), 5) for v in u], "u_pad_abs_mm": round(float(np.linalg.norm(u)), 5),
            "u_max_mm": s.get("u_max_mm"), "vm_max_mpa": s.get("vm_max_mpa"),
            "balance": s.get("balance"), "freqs_hz": [f["hz"] for f in m["freqs"]],
            "elements": (r["data"].get("mesh") or {}).get("elements")}


def frame_fea(cad: Mapping, fl: Mapping, mv: Mapping, work: Path) -> dict:
    """同一个门架算两遍（网格 FEA_MESH_MM 与它的 1/1.5），差别作网格误差的估计"""
    work.mkdir(parents=True, exist_ok=True)
    step = work / "frame.step"
    geo = frame_step(cad, step)
    runs = [frame_study(cad, fl, mv, str(step), geo, h) for h in (FEA_MESH_MM, round(FEA_MESH_MM / 1.5, 3))]
    a, b = runs
    du = abs(a["u_pad_abs_mm"] - b["u_pad_abs_mm"]) / max(b["u_pad_abs_mm"], 1e-12)
    df = abs(a["freqs_hz"][0] - b["freqs_hz"][0]) / b["freqs_hz"][0]
    return {"runs": runs, "result": b, "mesh_change": {"u_pad": round(du, 4), "f1": round(df, 4)}, "limits": LIMITS}


def judge(fea: Mapping, formula: Mapping, rep: Mapping, cond: Mapping, cyc: Mapping) -> dict:
    """变形：门架在跨中的变形（有限元，细网格）+ 各轴重复定位精度 ≤ 放料定位精度 → pass；一阶频率只报数（附停留时间里的振动周期数）"""
    tol = cond.get("repeatability")
    u = fea["result"]["u_pad_abs_mm"]
    worst = (rep or {}).get("worst_mm")
    if not isinstance(tol, (int, float)) or worst is None:
        d = {"status": "unknown", "note": "需求没给定位精度或模组重复定位精度缺数据"}
    else:
        tot = u + worst
        d = {"status": "pass" if tot <= tol + 1e-9 else "fail", "deflection_mm": u, "repeatability_mm": worst, "total_mm": round(tot, 4),
             "limit_mm": tol,
             "note": f"门架跨中变形 {u:.3g} mm（重力 + 两轴最大惯性力同时作用）+ 模组重复定位精度 ±{worst:g} mm = {tot:.3g} mm，"
                     f"要求 ±{tol:g} mm；公式（偏保守）{formula['deflection_mm']:.3g} mm"}
    f1 = fea["result"]["freqs_hz"][0]
    dw = [s["dwell_s"] for s in cyc["segments"] if s.get("dwell_s")]
    f = {"status": "report", "f1_hz": f1, "f1_formula_hz": formula["f1_vertical_hz"], "freqs_hz": fea["result"]["freqs_hz"],
         "note": f"门架一阶固有频率 {f1:.3g} Hz（公式按简支梁的竖直一阶 {formula['f1_vertical_hz']:.3g} Hz）"
                 + (f"；放料前停留 {min(dw):g} s 里振 {min(dw) * f1:.0f} 个周期" if dw else "")
                 + "。没有公开的判定值，只报数；阻尼没有数据，余振多久衰减到 ±0.1 mm 以内算不了"}
    return {"deflection": d, "frequency": f}


# ---------------------------------------------------------------- 整条
def run(concept_result: Mapping, build_result: Mapping, out_dir: str | Path, fea: bool = True) -> dict:
    lib = GB._library()
    concept = copy.deepcopy(dict(concept_result["chosen"]))
    cond = concept_result.get("conditions") or {}
    gp = build_result.get("gripper") or {}
    gcomp = lib.get(gp.get("component")) if gp.get("component") else None
    if gcomp is None:
        raise CadError("第一步没有选定抓手")
    genv = _env(gcomp)
    cache: dict = {}

    def lay(picks, grip_kg, part_kg):
        pk = dict(picks, _gripper={"envelope": genv})
        key = json.dumps({j: p.get("component") for j, p in picks.items()}, sort_keys=True)
        if key not in cache:
            cache[key] = assemble(concept, cond, pk, lib)
        cad = cache[key]
        b = bodies(cad, picks, part_kg, grip_kg)
        cache["last"] = (cad, b, picks)
        return b

    start = {j: p for j, p in build_result["picks"].items()}
    out = GB.build(concept, cond, layout=lay, start=start)
    if out["status"] == "fail" and not out.get("loads"):
        return {"format": FORMAT, "status": "fail", "note": out.get("note"), "reverify": out}
    picks = out["picks"]
    out_dir = Path(out_dir)
    cad = assemble(concept, cond, dict(picks, _gripper={"envelope": genv}), lib, out_dir / "cad")
    b = bodies(cad, picks, float(cond["part_mass"]), gp.get("mass_kg"))
    mv = moving(cad, b)
    fl = frame_loads(cad, picks, mv, out["loads"])
    formula = frame_formula(cad, fl)
    res = {"format": FORMAT, "design": DESIGN, "cad": cad, "moving": {j: {"mass_kg": round(v["mass_kg"], 4),
                                                                          "cog_mm": [round(float(x), 2) for x in v["cog_mm"]]}
                                                                      for j, v in mv.items()},
           "reverify": _compact(out, build_result), "frame_loads": {k: round(v, 4) for k, v in fl.items()}, "frame_formula": formula}
    if fea:
        fr = frame_fea(cad, fl, mv, out_dir / "cad")
        res["frame_fea"] = fr
        res["judge"] = judge(fr, formula, out.get("repeatability"), cond, out["cycle"])
    ok = [cad["status"] == "pass", out["status"] == "pass", not fea or res["judge"]["deflection"]["status"] != "fail"]
    res["status"] = "pass" if all(ok) else "fail"
    res["open_items"] = _open(res, out)
    return res


def _compact(out: Mapping, first: Mapping) -> dict:
    """复核结果（不带时间历程）与第一步的对照"""
    picks = {j: {k: p.get(k) for k in ("component", "model", "mass_kg", "carriage_kg", "body_kg")}
             | {"checks": [{k: c.get(k) for k in ("check", "status", "message")} for c in (p.get("check") or {}).get("checks", [])]}
             for j, p in out["picks"].items()}
    cmp_ = {}
    for j, ld in (out.get("loads") or {}).items():
        f0 = (first.get("loads") or {}).get(j) or {}
        cmp_[j] = {k: {"step1": f0.get(k), "cad": ld[k]} for k in ("thrust_n", "force_lateral_n", "force_normal_n",
                                                                    "moment_roll_nm", "moment_pitch_nm", "moment_yaw_nm")}
    same = {j: (first["picks"].get(j) or {}).get("component") == p["component"] for j, p in out["picks"].items()}
    return {"status": out["status"], "rounds": out["rounds"], "loads": out.get("loads"), "picks": picks, "same_as_step1": same,
            "loads_vs_step1": cmp_, "cycle_time": out.get("cycle_time"), "repeatability": out.get("repeatability"),
            "motors": out.get("motors"), "moving_masses": out.get("moving_masses"),
            "mbd": {k: (out.get("mbd") or {}).get(k) for k in ("drives", "tracking_error_mm", "settle_window_s", "reactions_max_abs")},
            "open_items": out.get("open_items")}


def _open(res: Mapping, out: Mapping) -> list[str]:
    L = res["cad"]["layout"]
    items = list(out.get("open_items") or [])
    items.append(f"X 滑台面高 {L['slide_x_mm']:g} mm（方案的关节原点 {L['concept_slide_x_mm']:g} mm）：为让 Z 模组下端高出一叠裁片，"
                 "X 模组的安装高度由三维装配定，末端点的运动不变")
    xl, xr = L["col_x_mm"]
    items.append(f"立柱在 x = {xl:g} mm 与 {xr:g} mm（门架跨度 {L['span_mm']:g} mm）：落脚处要有与台面同高、能打螺栓的安装面；"
                 "裁床与送料台之间、立柱旁边的通道位置没有资料，要现场核")
    items.append("X 模组装在横梁下面用的安装件（型材连接件、滑块螺母）、电机与电机套件的外形没建")
    return items


def summary(res: Mapping) -> str:
    c = res["cad"]
    lines = [f"结论：{res['status']}；三维装配 {c['status']}（干涉 {len(c['interferences'])} 处，进取放区 {len(c['keepout_hits'])} 处）"]
    for p in c["parts"]:
        lines.append(f"  {p['name']}：" + (f"{p['mass_kg']:g} kg（体积算）" if p.get("mass_kg") is not None else "质量用目录值 / 缺"))
    rv = res["reverify"]
    lines.append("复核选件：" + "；".join(f"{j} {p['model']}（与第一步{'相同' if rv['same_as_step1'][j] else '不同'}）"
                                         for j, p in rv["picks"].items()))
    for j, d in rv["loads_vs_step1"].items():
        lines.append(f"  {j} 推力 {d['thrust_n']['step1']} → {d['thrust_n']['cad']} N；俯仰力矩 {d['moment_pitch_nm']['step1']} → "
                     f"{d['moment_pitch_nm']['cad']} N·m")
    f = res["frame_formula"]
    lines.append(f"门架公式：跨中垂直 {f['sag_mm']:g} mm、侧移 {f['sway_mm']:g} mm、一阶 {f['f1_vertical_hz']:g} Hz")
    if res.get("frame_fea"):
        r = res["frame_fea"]["result"]
        lines.append(f"门架有限元：跨中变形 {r['u_pad_abs_mm']:g} mm、频率 {r['freqs_hz']} Hz、最大应力 {r['vm_max_mpa']} MPa；"
                     f"网格加密变化 {res['frame_fea']['mesh_change']}")
        lines.append(f"判定：{res['judge']['deflection']['note']}；{res['judge']['frequency']['note']}")
    lines += [f"待确认：{x}" for x in res["open_items"]]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m assist.gantry_cad", description="龙门取放机器人：三维装配、复核选件、门架有限元（ADR-0115 44.5.5）")
    ap.add_argument("concept_result", type=Path)
    ap.add_argument("build_result", type=Path, help="assist.gantry_build 的结果（第一步）")
    ap.add_argument("-o", "--out", type=Path, required=True, help="输出目录（cad-result.json、cad/assembly.step、cad/frame.step）")
    ap.add_argument("--no-fea", action="store_true")
    a = ap.parse_args(argv)
    cr = json.loads(a.concept_result.read_text(encoding="utf-8"))
    br = json.loads(a.build_result.read_text(encoding="utf-8"))
    try:
        res = run(cr, br, a.out, fea=not a.no_fea)
    except (CadError, GB.BuildError) as ex:
        print(f"算不了：{ex}", file=sys.stderr)
        return 1
    print(summary(res), file=sys.stderr)
    (a.out / "cad-result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0 if res["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
