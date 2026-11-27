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
import hashlib
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
FEA_MESH_MM = (20.0, 15.0)       # 门架 2.4 m 长、壁厚 6 mm：20 mm（约 6 万个节点）与 15 mm（约 11 万个）两层对照；
FEA_MESH_XYZ_MM = (25.0, 20.0)   # 案例 B2 门架跨度 3.2 m：15 mm 约 15 万个节点、估计要 7.8 GB 内存（2026-11-26 实算），超过本机 7 GB
TIME_LIMIT_S = 3000              # 12 mm 约 16 万个节点、求解器估计要 9.7 GB 内存，超过本机 7 GB
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
    if [a["dir"] for a in ax] == [0, 1, 2]:
        return layout_xyz(concept, cond, picks, lib)
    if len(ax) != 2 or ax[0]["dir"] != 0 or ax[1]["dir"] != 2:
        raise CadError("三维装配只做 X（水平，沿 x）– Z（竖直）两轴龙门，或 X–Y–Z 三轴龙门（末端可加 C 轴）")
    if GB.wrist(concept) is not None:
        raise CadError("两轴龙门的三维装配没有做末端 C 轴")
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
    if L.get("kind") == "xyz":
        return _solids_xyz(L)
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


def _chain(L: Mapping) -> list[dict]:
    """运动构件从基座往外的顺序：[{"body", "dir"（0/1/2，转动是 "rot"）, "lo", "hi"}]"""
    if L.get("kind") == "xyz":
        return L["chain"]
    ax_x, ax_z = L["axes"]
    return [{"body": "x", "dir": 0, "lo": ax_x["lo"], "hi": ax_x["hi"]}, {"body": "z", "dir": 2, "lo": ax_z["lo"], "hi": ax_z["hi"]}]


def _rel(L: Mapping, fix: str, mov: str) -> tuple[dict, bool]:
    """mov 相对 fix 能走的范围 {方向: (lo, hi)} 与是否还会绕 C 轴转（mov 在 fix 的下游）"""
    order = ["base"] + [c["body"] for c in _chain(L)]
    i, k = order.index(fix), order.index(mov)
    dq, rot = {}, False
    for c in _chain(L)[i:k]:
        if c["dir"] == "rot":
            rot = True
        else:
            dq[c["dir"]] = (c["lo"], c["hi"])
    return dq, rot


def _downstream(L: Mapping, a: str, b: str) -> bool:
    order = ["base"] + [c["body"] for c in _chain(L)]
    return order.index(b) > order.index(a)


def _sweep_box(tag: int, dq: Mapping[int, tuple[float, float]], rot_xy=None):
    """外接长方体沿行程扫过；rot_xy 给定时先绕过该点的竖直轴转一整圈（水平面上取外接圆的外接正方形，偏保守）"""
    bb = _occ().getBoundingBox(3, tag)
    lo, hi = list(bb[:3]), list(bb[3:])
    if rot_xy is not None:
        r = max(math.hypot(x - rot_xy[0], y - rot_xy[1]) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]))
        lo[0], hi[0], lo[1], hi[1] = rot_xy[0] - r, rot_xy[0] + r, rot_xy[1] - r, rot_xy[1] + r
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


ROT_STEP_DEG = 10.0


def _rot_overlap(fix: int, mov: int, axis_xy, c: Mapping) -> float:
    from assist.robot_cad import _overlap

    occ = _occ()
    n = max(math.ceil((c["hi"] - c["lo"]) / ROT_STEP_DEG), 1)
    worst = 0.0
    for k in range(n + 1):
        ang = math.radians(c["lo"] + (c["hi"] - c["lo"]) * k / n)
        cp = occ.copy([(3, mov)])
        occ.rotate(cp, axis_xy[0], axis_xy[1], 0.0, 0, 0, 1, ang)
        occ.synchronize()
        worst = max(worst, _overlap(fix, cp[0][1]))
        occ.remove(cp, recursive=True)
        occ.synchronize()
    return worst


def interferences(parts: list[dict], L: Mapping) -> tuple[list[dict], list[dict]]:
    """返回（零件之间的干涉, 进了取放区的零件）；体积 > 1 mm³ 才算（贴合面相交是零体积）"""
    from assist.robot_cad import _overlap

    occ = _occ()
    axis = L.get("c_axis_xy")
    hits = []
    for i in range(len(parts)):
        for k in range(i + 1, len(parts)):
            a, b = parts[i], parts[k]
            if a["body"] == b["body"]:
                vol = _overlap(a["tag"], b["tag"])
                how = "零位实体相交"
            else:
                mov, fix = (b, a) if _downstream(L, a["body"], b["body"]) else (a, b)
                dq, rot = _rel(L, fix["body"], mov["body"])
                if rot and not dq:                       # 只差 C 轴转动（同轴的零件）：实体按行程每 ROT_STEP_DEG 转一次求交
                    vol = _rot_overlap(fix["tag"], mov["tag"], axis, L["chain"][-1])
                    how = f"{mov['name']}绕 C 轴在行程内每 {ROT_STEP_DEG:g}° 转一次的实体相交"
                else:
                    lo, hi = _sweep_box(mov["tag"], dq, axis if rot else None)
                    tmp = _box(lo, hi)
                    occ.synchronize()
                    vol = _overlap(fix["tag"], tmp)
                    occ.remove([(3, tmp)], recursive=True)
                    occ.synchronize()
                    how = f"{mov['name']}的外接长方体沿行程扫过" + ("（含绕 C 轴转一圈）" if rot else "")
            if vol > 1.0:
                hits.append({"a": a["name"], "b": b["name"], "volume_mm3": round(vol, 1), "how": how})
    keep = []
    for p in parts:
        if p.get("tool"):
            continue
        dq, rot = _rel(L, "base", p["body"])
        lo, hi = _sweep_box(p["tag"], dq, axis if rot else None)
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


# ---------------------------------------------------------------- 三轴龙门加 C 轴（案例 B2，ADR-0115 44.5.6.3）
DESIGN_XYZ = {
    "arm_wall_mm": 4.0,          # Z 轴竖杆：方案给的是型材外形（宽 × 高），壁厚没给；按矩形管、壁厚 4 mm（第一版设计值）
    "adapter_x_mm": 160.0,       # Y 模组连接板：沿 x 长（夹在 X 滑台面与 Y 模组上面之间，沿 y 与 X 模组同宽），厚同 plate_mm
    "c_gap_mm": 3.0,             # C 轴支架上板离转动模组上端（从动舵盘也在转，让开）
    "c_bracket_t_mm": 8.0,       # C 轴支架（L 形：上板接竖杆，侧板用螺钉接转动模组侧面安装面）板厚、沿 y 宽
    "c_bracket_w_mm": 60.0,
    "c_side_clear_mm": 5.0,      # 侧板下端离转动头板（转动头板在转）
    "c_sweep_clear_mm": 10.0,    # 转动头板转一圈的外圆离 Z 模组滑台面（Z 滑台上下时转动头板从模组旁边过）
    "boss_pocket_mm": [11.0, 6.0],  # 转动头板上让开输出轴凸台的盲孔：直径、深
    # 下面三项改案例 B 的同名设计值：B2 的 Z 模组（EGC-50，宽 48）、竖杆（宽 40）比案例 B 的小，Z 轴连接板宽取模组宽 + 两边各 6、
    # 管夹宽取竖杆宽 + 两边各 5、管夹高 40。照案例 B 的尺寸（宽 100、70，高 60）时 Z 上的自制件重 0.5 kg 以上，
    # 复核选件一轮轮加大（Z → EGC-70，Y → EGC-120），X 用到最大的 EGC-185 载荷比较系数也是 1.024 > 1，选不出（2026-11-26 实算，ADR-0115 44.5.6.3 记录）
    "bracket_w_mm": 60.0,
    "clamp_w_mm": 50.0,
    "clamp_h_mm": 40.0,
}
DENSITY_KG_MM3["7075-T6"] = 2.81e-6   # analysis/common/materials.yaml 的 7075-T6
NU = 0.33                             # 同上，6061-T6 的泊松比（扭转用剪切模量 G = E / 2(1 + ν)）


def _link(concept: Mapping, lid: str) -> Mapping:
    return next((lk for lk in concept.get("links") or [] if lk["id"] == lid), None) or {}


def _zones(concept: Mapping, cond: Mapping, side: float) -> list[dict]:
    """取放区：有取料区（取放条件里有取料区长宽，方案第 3–6 点是四角）时取料区 = 四角的外接矩形向外各让半个裁片长边，
    放料区 = 以放料点（第 2 点）为中心、边长取裁片长边的正方形；高都到一叠最高处"""
    pts = [np.asarray(p, float) for p in (concept.get("workspace") or {}).get("points_mm") or []]
    stack = float(cond.get("stack_height") or 0.0)
    if len(pts) < 6 or not isinstance(cond.get("area_length"), (int, float)):
        raise CadError("三轴龙门要取料区：取放条件里的取料区长宽、方案的取料区四角（第 3–6 点）")
    c = np.asarray(pts[2:6])
    lo, hi = c.min(axis=0) - side / 2, c.max(axis=0) + side / 2
    place = pts[1]
    return [{"name": "取料区（几叠裁片）", "box": [[lo[0], lo[1], 0.0], [hi[0], hi[1], stack]]},
            {"name": "放料区", "box": [[place[0] - side / 2, place[1] - side / 2, 0.0], [place[0] + side / 2, place[1] + side / 2, stack]]}]


def layout_xyz(concept: Mapping, cond: Mapping, picks: Mapping, lib) -> dict:
    """三轴龙门加 C 轴的布置（mm，方案坐标系，零位）：
    横梁沿 x 在后面，X 模组倒挂在横梁下（滑台面朝下）；Y 模组用连接板挂在 X 滑台下、沿 +y 悬臂伸出（滑台面朝下，
    模组后端与 X 模组后沿齐平）；Z 模组竖直装在 L 形连接板上（上板接 Y 滑台，竖板接 Z 模组背面，滑台面朝 +y），同案例 B；
    竖杆（矩形管）用管夹装在 Z 滑台上，下端是 C 轴支架、转动模组（输出朝下、轴线在末端点正上方）、转动头板和吸盘。
    高度由下往上定：吸盘口 = 末端点；Z 模组下端高出一叠最高处（同案例 B）"""
    from analysis.robot import kinematics as K

    ax = GB.axes(concept)
    w = GB.wrist(concept)
    if w is None:
        raise CadError("三轴龙门的三维装配只做末端带 C 轴的（案例 B2）")
    if (concept.get("base") or {}).get("mount") not in (None, "table", "floor"):
        raise CadError("龙门只做装在台面或地面上的")
    m = K.build(concept)
    tool0 = np.asarray(K.tool_point(m), float)
    D, X = {**DESIGN, **DESIGN_XYZ}, DESIGN_XYZ
    jx, jy, jz = (a["joint"] for a in ax)
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
    wp = picks.get(w["joint"]) or {}
    wc = lib.get(wp.get("component")) if wp.get("component") else None
    if wc is None:
        raise CadError(f"{w['joint']} 还没有选定转动模组")
    env = (wc.get("envelope") or {}).get("parts") or []
    if not env or any(not isinstance((q.get("length_mm") or {}).get("value"), (int, float)) for q in env):
        raise CadError(f"{wc.get('model')} 的外形数据不全")
    side_port = next((q for q in wc.get("ports") or [] if q["id"] == "mount_side_r" and q.get("frame")), None)
    if side_port is None:
        raise CadError(f"{wc.get('model')} 没有侧面安装面的数据：C 轴支架接不上")
    zl_lo = min(q["z_start_mm"] for q in env)
    zl_hi = max(q["z_start_mm"] + q["length_mm"]["value"] for q in env)
    xs = float(side_port["frame"]["origin_mm"][0])
    arm = _link(concept, next(j.child for j in m.joints if j.id == jz))
    asec = arm.get("section") or {}
    if arm.get("shape") not in ("profile", "box") or not asec.get("width_mm") or not asec.get("height_mm"):
        raise CadError("Z 轴杆件不是矩形截面（型材）：竖杆按矩形管做")
    head = _link(concept, w["link"])
    hsec = head.get("section") or {}
    if head.get("shape") != "plate" or not (hsec.get("width_mm") and hsec.get("thickness_mm") and head.get("length_mm")):
        raise CadError("C 轴杆件不是板（长、宽、厚）：转动头板做不了")
    grip = ((picks.get("_gripper") or {}).get("envelope") or {})
    cup_h, cup_d = grip.get("length_mm"), grip.get("diameter_mm")
    if cup_h is None or cup_d is None:
        raise CadError("吸盘的外形尺寸不全")
    side = max(float(cond.get("part_length") or 0.0), float(cond.get("part_width") or 0.0))
    if side <= 0:
        raise CadError("取放条件里没有裁片尺寸：取放区的避让查不了")
    zones = _zones(concept, cond, side)
    stack = float(cond.get("stack_height") or 0.0)
    (cx, ex), (cy, ey), (cz, ez) = (comps[j] for j in (jx, jy, jz))
    (xlo, xhi), (ylo, yhi), (zlo, zhi) = ((a["lo"], a["hi"]) for a in ax)
    ox, oy, zt = (float(v) for v in tool0)
    aw, ah = float(asec["width_mm"]), float(asec["height_mm"])          # 竖杆沿 x、沿 y
    # 末端：吸盘 → 转动头板 → 转动模组（输出舵盘面 zh、翻过来输出朝下）→ C 轴支架 → 竖杆
    tp = float(hsec["thickness_mm"])
    zh = zt + cup_h + tp
    _pk_d, pk_h = X["boss_pocket_mm"]
    if zl_hi > pk_h + 1e-9:
        raise CadError(f"转动模组输出轴凸台高 {zl_hi:g} mm，比转动头板上的让位孔深 {pk_h:g} mm 还高")
    act_top = zh - zl_lo
    cb_t, cb_w = X["c_bracket_t_mm"], X["c_bracket_w_mm"]
    cb_z0 = act_top + X["c_gap_mm"]
    arm_lo = cb_z0 + cb_t
    # 上面：Z 模组（同案例 B 的尺寸链）
    Lz = ez["length_mm"] + (zhi - zlo)
    Hz, Bz = ez["height_mm"], ez["width_mm"]
    zsy = stack + D["stack_clear_mm"] + Lz + D["z_top_gap_mm"] + D["plate_mm"]     # Y 滑台面（朝下）
    ztop = zsy - D["plate_mm"] - D["z_top_gap_mm"]
    zc0 = ztop - zhi - ez["length_mm"] / 2
    arm_hi = zc0 + D["clamp_h_mm"] / 2
    if arm_hi - arm_lo < D["clamp_h_mm"]:
        raise CadError(f"竖杆太短（{arm_hi - arm_lo:.1f} mm），夹不住：Z 滑台离末端太近")
    r_c = max(math.hypot(head["length_mm"] / 2, hsec["width_mm"] / 2), cup_d / 2)       # C 轴上转的零件离轴线最远处
    # Z 滑台上下时转动头板从 Z 模组旁边过：C 轴离 Z 滑台面至少“转一圈的外圆 + 间隙”。竖杆照案例 B 贴着管夹（管夹后面 clamp_back_mm），
    # 不够远时竖杆不在 C 轴上、往后让，由 C 轴支架上板向前搭过去（不把管夹做成厚实心块）
    need = r_c + X["c_sweep_clear_mm"]
    ys = oy - max(ah / 2 + D["clamp_back_mm"], need)
    ya = ys + D["clamp_back_mm"] + ah / 2                                          # 竖杆中心的 y
    yzb = ys - Hz
    yw = yzb - D["web_mm"]
    yf = ya + ah / 2 + D["clamp_front_mm"]
    yref = (yw + yf) / 2                                                         # Y 滑台面中心 = Z 连接板上板中心
    # Y 模组（悬臂）与 X 模组
    Ly = ey["length_mm"] + (yhi - ylo)
    Hy, By = ey["height_mm"], ey["width_mm"]
    yb0, yb1 = yref + ylo - ey["length_mm"] / 2, yref + yhi + ey["length_mm"] / 2
    Lx = ex["length_mm"] + (xhi - xlo)
    Hx, Bx = ex["height_mm"], ex["width_mm"]
    yx = yb0 + Bx / 2                                                            # Y 模组后端与 X 模组后沿齐平
    zsx = zsy + Hy + D["plate_mm"]                                               # X 滑台面（朝下）
    zb = zsx + Hx
    xmod = [ox + xlo - ex["length_mm"] / 2, ox + xhi + ex["length_mm"] / 2]
    cw = D["col_w_mm"]
    xl = min(min(z["box"][0][0] for z in zones) - D["keepout_clear_mm"], xmod[0]) - cw / 2
    xr = max(max(z["box"][1][0] for z in zones) + D["keepout_clear_mm"], xmod[1]) + cw / 2
    refs = {jx: [ox, yx, zsx], jy: [ox, yref, zsy], jz: [ox, ys, zc0], w["joint"]: [ox, oy, zh]}
    return {
        "kind": "xyz", "axes": ax, "tool0_mm": tool0.tolist(), "slide_x_mm": zsx, "slide_y_mm": zsy, "zc0_mm": zc0, "y_slide_z_mm": ys,
        "x_ref_mm": refs[jx], "refs_mm": refs, "c_axis_xy": [ox, oy],
        "chain": [{"body": "x", "joint": jx, "dir": 0, "lo": xlo, "hi": xhi}, {"body": "y", "joint": jy, "dir": 1, "lo": ylo, "hi": yhi},
                  {"body": "z", "joint": jz, "dir": 2, "lo": zlo, "hi": zhi},
                  {"body": "c", "joint": w["joint"], "dir": "rot", "lo": w["lo"], "hi": w["hi"]}],
        "modules": {jx: {"component": cx["id"], "model": cx.get("model"), "box": [[xmod[0], yx - Bx / 2, zsx], [xmod[1], yx + Bx / 2, zb]],
                         "length_mm": Lx},
                    jy: {"component": cy["id"], "model": cy.get("model"), "box": [[ox - By / 2, yb0, zsy], [ox + By / 2, yb1, zsy + Hy]],
                         "length_mm": Ly},
                    jz: {"component": cz["id"], "model": cz.get("model"), "box": [[ox - Bz / 2, yzb, ztop - Lz], [ox + Bz / 2, ys, ztop]],
                         "length_mm": Lz}},
        "actuator": {"joint": w["joint"], "component": wc["id"], "model": wc.get("model"), "horn_z_mm": zh, "top_z_mm": act_top,
                     "side_x_mm": xs},
        "adapter": [[ox - X["adapter_x_mm"] / 2, yx - Bx / 2, zsy + Hy], [ox + X["adapter_x_mm"] / 2, yx + Bx / 2, zsx]],
        "beam": [[xl - cw / 2, yx - D["beam_w_mm"] / 2, zb], [xr + cw / 2, yx + D["beam_w_mm"] / 2, zb + D["beam_h_mm"]]],
        "columns": [[[x - cw / 2, yx - cw / 2, D["foot_t_mm"]], [x + cw / 2, yx + cw / 2, zb]] for x in (xl, xr)],
        "feet": [[[x - D["foot_mm"] / 2, yx - D["foot_mm"] / 2, 0.0], [x + D["foot_mm"] / 2, yx + D["foot_mm"] / 2, D["foot_t_mm"]]]
                 for x in (xl, xr)],
        "bracket": {"top": [[ox - D["bracket_w_mm"] / 2, yw, zsy - D["plate_mm"]], [ox + D["bracket_w_mm"] / 2, yf, zsy]],
                    "web": [[ox - D["bracket_w_mm"] / 2, yw, ztop - Lz], [ox + D["bracket_w_mm"] / 2, yzb, zsy - D["plate_mm"]]]},
        "clamp": [[ox - D["clamp_w_mm"] / 2, ys, zc0 - D["clamp_h_mm"] / 2], [ox + D["clamp_w_mm"] / 2, yf, zc0 + D["clamp_h_mm"] / 2]],
        "arm": {"box": [[ox - aw / 2, ya - ah / 2, arm_lo], [ox + aw / 2, ya + ah / 2, arm_hi]], "wall_mm": X["arm_wall_mm"]},
        "arm_offset_mm": oy - ya, "c_sweep_r_mm": r_c,
        "c_bracket": {"top": [[min(ox - aw / 2, ox - xs), min(ya - ah / 2, oy - cb_w / 2), cb_z0],
                              [ox + xs + cb_t, max(ya + ah / 2, oy + cb_w / 2), cb_z0 + cb_t]],
                      "side": [[ox + xs, oy - cb_w / 2, zh + X["c_side_clear_mm"]], [ox + xs + cb_t, oy + cb_w / 2, cb_z0]]},
        "head": {"box": [[ox - head["length_mm"] / 2, oy - hsec["width_mm"] / 2, zt + cup_h], [ox + head["length_mm"] / 2,
                                                                                                  oy + hsec["width_mm"] / 2, zh]],
                 "material": head.get("material") or MATERIAL},
        "cup": {"z0": zt, "z1": zt + cup_h, "r": cup_d / 2},
        "keepouts": zones, "span_mm": xr - xl, "col_x_mm": [xl, xr], "beam_bottom_mm": zb,
        "part_size_mm": ([float(cond["part_length"]), float(cond["part_width"])]
                         if isinstance(cond.get("part_length"), (int, float)) and isinstance(cond.get("part_width"), (int, float)) else None),
        "concept_slide_x_mm": float(next(j for j in m.joints if j.id == jx).origin[2]),
    }


def _solids_xyz(L: Mapping) -> list[dict]:
    from assist import robot_cad as RC

    occ, D = _occ(), {**DESIGN, **DESIGN_XYZ}
    jx, jy, jz, jc = (c["joint"] for c in L["chain"])
    parts = [{"name": "横梁（矩形管）", "kind": "frame", "body": "base", "tag": _tube_rect(*L["beam"], D["beam_wall_mm"], 0), "material": MATERIAL}]
    for k, (c, f) in enumerate(zip(L["columns"], L["feet"], strict=True)):
        parts.append({"name": f"立柱与地脚板 {'左右'[k]}", "kind": "frame", "body": "base",
                      "tag": _fuse([_tube_rect(*c, D["col_wall_mm"], 2), _box(*f)]), "material": MATERIAL})
    for jid, body in ((jx, "base"), (jy, "x"), (jz, "y")):
        mo = L["modules"][jid]
        parts.append({"name": f"{jid} 直线模组 {mo['model']}（外形）", "kind": "module", "body": body, "tag": _box(*mo["box"]),
                      "component": mo["component"], "joint": jid})
    parts.append({"name": "Y 模组连接板", "kind": "made", "body": "x", "tag": _box(*L["adapter"]), "material": MATERIAL})
    br = _fuse([_box(*L["bracket"]["top"]), _box(*L["bracket"]["web"])])
    occ.synchronize()
    web = L["bracket"]["web"]
    y_in, z_in = web[1][1], web[1][2]

    def inner(P):
        return bool(np.all(np.abs(P[:, 1] - y_in) < 1e-6) and np.all(np.abs(P[:, 2] - z_in) < 1e-6))
    br = RC._fillet(br, inner, D["bracket_fillet_mm"])
    parts.append({"name": "Z 轴连接板（L 形）", "kind": "made", "body": "y", "tag": br, "material": MATERIAL})
    a = L["arm"]["box"]
    hole = [[a[0][0], a[0][1], L["clamp"][0][2] - 1], [a[1][0], a[1][1], L["clamp"][1][2] + 1]]
    parts.append({"name": "管夹", "kind": "made", "body": "z", "tag": _cut(_box(*L["clamp"]), [_box(*hole)]), "material": MATERIAL})
    w = (a[1][0] - a[0][0], a[1][1] - a[0][1])
    parts.append({"name": f"竖杆 {w[0]:g}×{w[1]:g}×{L['arm']['wall_mm']:g} 矩形管（长 {a[1][2] - a[0][2]:.1f} mm）", "kind": "made",
                  "body": "z", "tag": _tube_rect(*a, L["arm"]["wall_mm"], 2), "material": MATERIAL,
                  "length_mm": round(a[1][2] - a[0][2], 2), "tool": True})
    cb = L["c_bracket"]
    parts.append({"name": "C 轴支架（L 形）", "kind": "made", "body": "z", "tag": _fuse([_box(*cb["top"]), _box(*cb["side"])]),
                  "material": MATERIAL, "tool": True})
    from assist import gantry_build as _GB

    act = L["actuator"]
    comp = _GB._library().get(act["component"])
    ox, oy = L["c_axis_xy"]
    t = RC.actuator_solid(comp)
    A = np.array([[1.0, 0, 0, ox], [0, -1.0, 0, oy], [0, 0, -1.0, act["horn_z_mm"]], [0, 0, 0, 1.0]])   # 绕 x 转 180°：输出朝下
    RC._place(t, A)
    parts.append({"name": f"{jc} 转动模组 {act['model']}（外形）", "kind": "actuator", "body": "z", "tag": t,
                  "component": act["component"], "joint": jc, "tool": True})
    h = L["head"]["box"]
    pk_d, pk_h = DESIGN_XYZ["boss_pocket_mm"]
    holes = RC._horn_holes(h[0][2], h[1][2])
    for q in holes:
        _occ().translate([(3, q)], ox, oy, 0)
    holes.append(_cyl_z(ox, oy, h[1][2] - pk_h, h[1][2] + 1, pk_d / 2))
    head = RC._cut(_box(*h), holes)
    parts.append({"name": "转动头板", "kind": "made", "body": "c", "tag": head, "material": L["head"]["material"], "tool": True})
    c = L["cup"]
    parts.append({"name": "吸盘（外形）", "kind": "gripper", "body": "c", "tag": _cyl_z(ox, oy, c["z0"], c["z1"], c["r"]), "tool": True})
    occ.synchronize()
    return parts


def _bodies_xyz(cad: Mapping, picks: Mapping, part_kg: float, gripper_kg: float | None) -> dict:
    """同 bodies：每个运动构件的集中质量（相对该构件参考点）；工件放在 C 轴构件上、按裁片长宽当薄板（转动惯量）"""
    L = cad["layout"]
    refs = {c["body"]: (c["joint"], np.asarray(L["refs_mm"][c["joint"]])) for c in L["chain"]}
    rows = {c["joint"]: [] for c in L["chain"]}
    missing = []
    for c in L["chain"][:3]:
        p = picks[c["joint"]]
        if p.get("carriage_kg") is not None:
            rows[c["joint"]].append((f"{p['model']} 滑台", p["carriage_kg"], [0.0, 0.0, 0.0]))
        else:
            missing.append(f"{p['model']} 的滑台质量厂商没给")
    for q in cad["parts"]:
        if q["body"] not in refs:
            continue
        jid, r = refs[q["body"]]
        rel = (np.asarray(q["cog_mm"]) - r).tolist()
        if q["kind"] == "module":
            kg = picks[q["joint"]].get("body_kg")
            if kg is None:
                missing.append(f"{q['name']} 的本体质量算不了")
                continue
            rows[jid].append((f"{picks[q['joint']]['model']} 本体（不含滑台）", kg, rel))
        elif q["kind"] == "actuator":
            kg = picks[q["joint"]].get("mass_kg")
            if kg is None:
                missing.append(f"{q['name']} 的质量厂商没给")
                continue
            rows[jid].append((f"{picks[q['joint']]['model']} 转动模组", kg, rel))
        elif q["kind"] == "gripper":
            if gripper_kg is None:
                missing.append("抓手质量厂商没给（未计入运动质量）")
            else:
                rows[jid].append((q["name"], gripper_kg, rel))
        else:
            rows[jid].append((q["name"], q["mass_kg"], rel))
    jc, rc = refs["c"]
    size = L.get("part_size_mm")
    rows[jc].append(("工件（单片）", part_kg, (np.asarray(L["tool0_mm"]) - rc).tolist(), *([tuple(size)] if size else [])))
    if not size:
        missing.append("裁片尺寸没给：工件按集中质量算，C 轴转动惯量偏小")
    org, prev = {}, np.zeros(3)
    for c in L["chain"]:
        r = np.asarray(L["refs_mm"][c["joint"]])
        org[c["joint"]] = (r - prev).tolist()
        prev = r
    return {"bodies": rows, "missing": missing, "origins": org}


# ---------------------------------------------------------------- 复核用的质量与参考点
def bodies(cad: Mapping, picks: Mapping, part_kg: float, gripper_kg: float | None) -> dict:
    """多体动力学的集中质量：{关节: [(名称, kg, 相对该构件参考点的位置 mm)]}；构件原点 = 滑台面中心（三维装配的真实位置）"""
    L = cad["layout"]
    if L.get("kind") == "xyz":
        return _bodies_xyz(cad, picks, part_kg, gripper_kg)
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
    if L.get("kind") == "xyz":
        out = {}
        for c in L["chain"]:
            r = np.asarray(L["refs_mm"][c["joint"]])
            m = sum(k for _n, k, _p, *_ in b["bodies"][c["joint"]])
            out[c["joint"]] = {"mass_kg": m, "cog_mm": sum(k * (np.asarray(p) + r) for _n, k, p, *_ in b["bodies"][c["joint"]]) / m}
        tot = sum(v["mass_kg"] for v in out.values())
        out["all"] = {"mass_kg": tot, "cog_mm": sum(v["mass_kg"] * v["cog_mm"] for v in list(out.values())) / tot}
        return out
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
    if L.get("kind") == "xyz":
        jx, jy, jz, jc = (c["joint"] for c in L["chain"])
        (_, _ylo, yhi), (_, zlo, _zhi) = ((c["lo"], c["lo"], c["hi"]) for c in L["chain"][1:3])
        sh = {jx: np.zeros(3), jy: np.array([0.0, yhi, 0.0]), jz: np.array([0.0, yhi, zlo]), jc: np.array([0.0, yhi, zlo])}

        def comb(js):                                  # 最不利位置（Y 伸到最远、Z 降到最低）的合成重心
            m = sum(mv[j]["mass_kg"] for j in js)
            return m, (sum(mv[j]["mass_kg"] * (np.asarray(mv[j]["cog_mm"]) + sh[j]) for j in js) / m).tolist()
        _m, c_all = comb([jx, jy, jz, jc])
        _m_y, c_y = comb([jy, jz, jc])
        m_z, c_z = comb([jz, jc])
        return {"x_module_static_kg": picks[jx].get("body_kg") or 0.0, "moving_kg": mv["all"]["mass_kg"],
                "thrust_x_n": loads[jx]["thrust_n"], "thrust_y_n": loads[jy]["thrust_n"],
                "inertia_z_n": max(loads[jz]["thrust_n"] - m_z * G, 0.0),
                "cog_all_worst_mm": c_all, "cog_y_worst_mm": c_y, "cog_z_worst_mm": c_z,
                "tool_worst_mm": (np.asarray(L["tool0_mm"]) + sh[jc]).tolist()}
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
    cols = sum(p["mass_kg"] for p in cad["parts"] if p["name"].startswith("立柱"))
    m_top = beam_kg + fl["x_module_static_kg"] + fl["moving_kg"] + 33 / 140 * cols
    fs = math.sqrt(2 * 3 * E_MPA * Ic / hc ** 3 * 1000 / m_top) / (2 * math.pi)
    Iz = (h * b ** 3 - (h - 2 * t) * (b - 2 * t) ** 3) / 12                 # 横梁绕竖直轴（水平方向弯曲）
    fl_ = math.sqrt(48 * E_MPA * Iz / span ** 3 * 1000 / m_eff) / (2 * math.pi)
    if L.get("kind") == "xyz":
        return _formula_xyz(L, fl, span, b, h, t, Ib, Ic, hc, sag, sway, f1, fs, fl_, Iz)
    return {"span_mm": round(span, 2), "beam_I_mm4": round(Ib, 0), "column_I_mm4": round(Ic, 0), "column_h_mm": round(hc, 2),
            "sag_mm": round(sag, 4), "sway_mm": round(sway, 4), "deflection_mm": round(math.hypot(sag, sway), 4),
            "beam_I_lateral_mm4": round(Iz, 0),
            "f1_vertical_hz": round(f1, 2), "f1_sway_hz": round(fs, 2), "f1_lateral_hz": round(fl_, 2),
            "formulas": ["垂直：5qL⁴/(384EI) + PL³/(48EI)（简支）", "侧移：F·h³/(2·3EI)（两根悬臂立柱）",
                         "竖直频率：(1/2π)√(48EI/L³ / (M + 17/35·m))（瑞利法）",
                         "横梁水平弯曲频率：同上，I 取绕竖直轴（横梁宽只有 80 mm，这个方向最弱）",
                         "侧摆频率：(1/2π)√(2·3EI/h³ / (柱顶以上全部质量 + 33/140·立柱))（两根悬臂立柱，质量当集中在柱顶，不计偏心）"]}


def _formula_xyz(L, fl, span, b, h, t, Ib, Ic, hc, sag, sway, f1, fs, fl_, Iz) -> dict:
    """三轴龙门：在两轴的公式上加 Y 悬臂造成的扭转与沿 y 的侧移（各项同号相加；扭转没计截面畸变、地脚板柔度，不一定偏保守）：
    扭矩 T = (运动部分重量 + Z 惯性力) × 重心离横梁中心的 y 距离 + Y 推力 × 重心离横梁中心的高度差（Y 伸到最远、Z 降到最低、在跨中）；
    横梁两端在立柱上不转、T 加在跨中：θ = T·L / (4·G·J)，闭口薄壁矩形管 J = 2t(b−t)²(h−t)² / (b + h − 2t)（布雷特公式）；
    两根立柱各受 T/2 的弯矩、柱顶转角 (T/2)·h / (E·I)；末端点的位移 = 转角 × 末端点到横梁中心的距离"""
    D = DESIGN
    Gm = E_MPA / (2 * (1 + NU))
    J = 2 * t * (b - t) ** 2 * (h - t) ** 2 / (b + h - 2 * t)
    yc, zc = L["x_ref_mm"][1], L["beam_bottom_mm"] + D["beam_h_mm"] / 2
    ca, cy, tw = fl["cog_all_worst_mm"], fl["cog_y_worst_mm"], fl["tool_worst_mm"]
    P = fl["moving_kg"] * G + fl["inertia_z_n"]
    T = P * abs(ca[1] - yc) + fl["thrust_y_n"] * abs(zc - cy[2])                         # N·mm
    th_b = T * span / (4 * Gm * J)
    th_c = (T / 2) * hc / (E_MPA * Ic)
    lever = math.hypot(tw[1] - yc, zc - tw[2])
    twist = (th_b + th_c) * lever
    sway_y = fl["thrust_y_n"] * hc ** 3 / (2 * 3 * E_MPA * Ic)
    tool = sag + sway + sway_y + twist
    return {"span_mm": round(span, 2), "beam_I_mm4": round(Ib, 0), "column_I_mm4": round(Ic, 0), "column_h_mm": round(hc, 2),
            "sag_mm": round(sag, 4), "sway_mm": round(sway, 4), "deflection_mm": round(math.hypot(sag, sway), 4),
            "beam_I_lateral_mm4": round(Iz, 0), "beam_J_mm4": round(J, 0), "torque_nm": round(T / 1000, 3),
            "twist_beam_rad": round(th_b, 7), "twist_columns_rad": round(th_c, 7), "tool_lever_mm": round(lever, 2),
            "twist_tool_mm": round(twist, 4), "sway_y_mm": round(sway_y, 4), "tool_frame_mm": round(tool, 4),
            "f1_vertical_hz": round(f1, 2), "f1_sway_hz": round(fs, 2), "f1_lateral_hz": round(fl_, 2),
            "formulas": ["垂直：5qL⁴/(384EI) + PL³/(48EI)（简支）", "侧移：F·h³/(2·3EI)（两根悬臂立柱；沿 x 用 X 推力、沿 y 用 Y 推力）",
                         "扭转：θ = T·L/(4GJ)（横梁）+ (T/2)·h/(EI)（立柱），J = 2t(b−t)²(h−t)²/(b+h−2t)（布雷特）；末端位移 = θ × 力臂",
                         "末端点（只算门架）：垂直 + 两个方向侧移 + 扭转，同号相加（偏保守）",
                         "竖直频率：(1/2π)√(48EI/L³ / (M + 17/35·m))（瑞利法）",
                         "横梁水平弯曲频率：同上，I 取绕竖直轴",
                         "侧摆频率：(1/2π)√(2·3EI/h³ / (柱顶以上全部质量 + 33/140·立柱))（两根悬臂立柱，质量当集中在柱顶，不计偏心）"]}


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
    dx = geo["x_mid"] - L["x_ref_mm"][0]                                    # 运动部分搬到跨中
    base = [{"type": "gravity", "body": "frame", "acceleration_m_s2": [0, 0, -G]},
            {"type": "mass", "body": "frame", "faces": beam_bottom, "mass_kg": round(fl["x_module_static_kg"], 4),
             "label": "X 模组本体"},
            {"type": "mass", "body": "frame", "faces": pad_bottom, "mass_kg": round(fl["moving_kg"], 4),
             "label": "运动部分（跨中）"}]
    probes = [{"id": "pad", "point_mm": [geo["x_mid"], L["x_ref_mm"][1], geo["pad"][0][2]]}]
    if L.get("kind") == "xyz":
        extra, more = _loads_xyz(L, fl, geo, pad_bottom, dx)
        base += extra
        probes += more
    else:
        jx, jz = (a["joint"] for a in L["axes"])
        cx = (np.asarray(mv[jx]["cog_mm"]) + [dx, 0, 0]).tolist()
        cz = (np.asarray(mv[jz]["cog_mm"]) + [dx, 0, 0]).tolist()
        base += [{"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": [round(v, 3) for v in cx],
                  "force_n": [round(fl["thrust_x_n"], 3), 0.0, 0.0]},
                 {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": [round(v, 3) for v in cz],
                  "force_n": [0.0, 0.0, -round(fl["inertia_z_n"], 3)]}]
    st = {"format": "fea-study/1", "name": "gantry-frame", "bodies": [{"id": "frame", "step_path": step, "material": MATERIAL}],
          "supports": [{"type": "fixed", "body": "frame", "faces": feet}],
          "loads": base,
          "steps": [{"id": "s", "type": "static"}, {"id": "m", "type": "modal", "n_modes": N_MODES},
                    {"id": "m1", "type": "modal", "n_modes": 1}],                # 只取第一阶：看它的有效质量在哪个方向
          "mesh": {"size_mm": size_mm}, "checks": {"convergence": False}, "time_limit_s": TIME_LIMIT_S,
          "probes": probes,
          "provenance": {"drafted_by": "human", "confirmed_by_human": True}}
    r = analysis.run("fea", st)
    if r.get("status") != "ok":
        raise CadError("门架有限元没算成：" + "；".join(r.get("messages") or []))
    s, m, m1 = r["data"]["steps"]
    em = m1.get("effective_mass_fraction") or {}
    u = s["probes"][0]["u_mm"]
    notes = ["固定：两块地脚板底面", ("加载：重力；X 模组本体质量分在横梁底面；运动部分质量放在跨中垫块；"
                                      "X 轴最大推力的反作用加在 X 运动部分重心、Z 轴最大惯性力（推力减重量）加在 Z 运动部分重心（都搬到跨中）")]
    extra_out = {}
    if L.get("kind") == "xyz":
        notes[1] = ("加载：重力；X 模组本体质量分在横梁底面；运动部分质量放在跨中垫块，它的重量偏在横梁前面造成的扭矩另加（力偶）；"
                    "X、Y 轴最大推力的反作用、Z 轴最大惯性力（推力减重量）加在各自运动部分的重心（Y 伸到最远、Z 降到最低、都搬到跨中）")
        extra_out = _tool_from_probes(L, fl, geo, s["probes"], dx)
    return {**extra_out, "study": {k: v for k, v in st.items() if k != "bodies"}, "notes": notes, "size_mm": size_mm,
            "u_pad_mm": [round(float(v), 5) for v in u], "u_pad_abs_mm": round(float(np.linalg.norm(u)), 5),
            "u_max_mm": s.get("u_max_mm"), "vm_max_mpa": s.get("vm_max_mpa"),
            "balance": s.get("balance"), "freqs_hz": [f["hz"] for f in m["freqs"]],
            "mode1_effective_mass": em, "mode1_direction": max(em, key=em.get) if em else None,
            "elements": (r["data"].get("mesh") or {}).get("elements")}


def _loads_xyz(L: Mapping, fl: Mapping, geo: Mapping, pad_bottom: list, dx: float) -> tuple[list, list]:
    pc = np.array([geo["x_mid"], L["x_ref_mm"][1], geo["pad"][0][2]])
    sh = np.array([dx, 0.0, 0.0])
    ca, cy, cz = (np.asarray(fl[k]) + sh for k in ("cog_all_worst_mm", "cog_y_worst_mm", "cog_z_worst_mm"))
    wt = np.array([0.0, 0.0, -fl["moving_kg"] * G])
    mo = np.cross((ca - pc) / 1000, wt)                                    # 重量从垫块搬回重心差的力偶（N·m）
    r = [lambda v: [round(float(x), 3) for x in v]][0]
    loads = [{"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": r(pc), "vector_nm": [round(float(x), 5) for x in mo]},   # 运动部分重量偏在横梁前面的扭矩
             {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": r(ca), "force_n": [round(fl["thrust_x_n"], 3), 0.0, 0.0]},
             {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": r(cy), "force_n": [0.0, round(fl["thrust_y_n"], 3), 0.0]},
             {"type": "remote_load", "body": "frame", "faces": pad_bottom, "point_mm": r(cz), "force_n": [0.0, 0.0, -round(fl["inertia_z_n"], 3)]}]
    zb, y0, xm, d = geo["zb"], L["x_ref_mm"][1], geo["x_mid"], PROBE_OFFSET_MM
    probes = [{"id": "yp", "point_mm": [xm, y0 + d, zb]}, {"id": "ym", "point_mm": [xm, y0 - d, zb]},
              {"id": "xp", "point_mm": [xm + 2 * d, y0, zb]}, {"id": "xm", "point_mm": [xm - 2 * d, y0, zb]}]
    return loads, probes


PROBE_OFFSET_MM = 35.0          # 横梁底面上、跨中两侧的测点（离中心线；沿 x 取两倍，在垫块外）：由位移差算横梁截面的转角


def _tool_from_probes(L: Mapping, fl: Mapping, geo: Mapping, probes: list, dx: float) -> dict:
    """横梁跨中截面当刚体：由四个测点的位移差得转角，末端点（Y 伸到最远、Z 降到最低）的位移 = 垫块位移 + 转角 × 力臂；
    Y、Z 模组与竖杆当刚体（它们自己的变形不在这里）"""
    u = {p["id"]: np.asarray(p["u_mm"], float) for p in probes}
    d = PROBE_OFFSET_MM
    th = np.array([(u["yp"][2] - u["ym"][2]) / (2 * d), -(u["xp"][2] - u["xm"][2]) / (4 * d), -(u["yp"][0] - u["ym"][0]) / (2 * d)])
    pc = np.array([geo["x_mid"], L["x_ref_mm"][1], geo["pad"][0][2]])
    tool = np.asarray(fl["tool_worst_mm"]) + [dx, 0.0, 0.0]
    ut = u["pad"] + np.cross(th, tool - pc)
    return {"rotation_rad": [round(float(x), 8) for x in th], "u_tool_frame_mm": [round(float(x), 5) for x in ut],
            "u_tool_frame_abs_mm": round(float(np.linalg.norm(ut)), 5), "tool_point_mm": [round(float(x), 3) for x in tool]}


def _mesh(cad: Mapping) -> tuple[float, float]:
    return FEA_MESH_XYZ_MM if cad["layout"].get("kind") == "xyz" else FEA_MESH_MM


def frame_fea(cad: Mapping, fl: Mapping, mv: Mapping, work: Path) -> dict:
    """同一个门架用两层网格（FEA_MESH_MM）各算一遍，差别作网格误差的估计"""
    work.mkdir(parents=True, exist_ok=True)
    step = work / "frame.step"
    geo = frame_step(cad, step)
    runs = [frame_study(cad, fl, mv, str(step), geo, h) for h in _mesh(cad)]
    a, b = runs
    du = abs(a["u_pad_abs_mm"] - b["u_pad_abs_mm"]) / max(b["u_pad_abs_mm"], 1e-12)
    df = abs(a["freqs_hz"][0] - b["freqs_hz"][0]) / b["freqs_hz"][0]
    return {"runs": runs, "result": b, "mesh_change": {"u_pad": round(du, 4), "f1": round(df, 4)}, "limits": LIMITS}


def judge(fea: Mapping, formula: Mapping, rep: Mapping, cond: Mapping, cyc: Mapping) -> dict:
    """变形：门架在跨中的变形（有限元，细网格）+ 各轴重复定位精度 ≤ 放料定位精度 → pass；一阶频率只报数（附停留时间里的振动周期数）"""
    tol = cond.get("repeatability")
    u = fea["result"]["u_pad_abs_mm"]
    worst = (rep or {}).get("worst_mm")
    xyz = "u_tool_frame_abs_mm" in fea["result"]
    if xyz and isinstance(tol, (int, float)) and worst is not None:
        ut = fea["result"]["u_tool_frame_abs_mm"]
        tot = ut + worst
        d = {"status": "fail" if tot > tol + 1e-9 else "unknown", "deflection_mm": ut, "repeatability_mm": worst, "total_mm": round(tot, 4),
             "limit_mm": tol, "u_pad_mm": u, "missing": ["Y 模组（悬臂）、Z 模组与竖杆自身的弯曲：零件库没有模组型材的截面惯性矩"],
             "note": f"只算门架：末端点（Y 伸到最远、Z 降到最低、在跨中）的位移 {ut:.3g} mm（跨中垫块 {u:.3g} mm，加横梁截面转角 × 力臂）"
                     f"+ 模组重复定位精度 ±{worst:g} mm = {tot:.3g} mm，要求 ±{tol:g} mm；公式估 {formula['tool_frame_mm']:.3g} mm"
                     "（扭转按闭口薄壁管的布雷特公式，没计截面畸变与地脚板的柔度，比有限元小）。"
                     + ("已超出：再加模组自身的弯曲只会更大，判不通过" if tot > tol + 1e-9 else
                        "Y 模组悬臂自身的下垂没算：零件库没有费斯托模组型材的截面惯性矩，判待确认")}
    elif not isinstance(tol, (int, float)) or worst is None:
        d = {"status": "unknown", "note": "需求没给定位精度或模组重复定位精度缺数据"}
    else:
        tot = u + worst
        d = {"status": "pass" if tot <= tol + 1e-9 else "fail", "deflection_mm": u, "repeatability_mm": worst, "total_mm": round(tot, 4),
             "limit_mm": tol,
             "note": f"门架跨中变形 {u:.3g} mm（重力 + 两轴最大惯性力同时作用）+ 模组重复定位精度 ±{worst:g} mm = {tot:.3g} mm，"
                     f"要求 ±{tol:g} mm；公式（偏保守）{formula['deflection_mm']:.3g} mm"}
    f1 = fea["result"]["freqs_hz"][0]
    dw = [s["dwell_s"] for s in cyc["segments"] if s.get("dwell_s")]
    dname = {"x": "沿横梁（x）", "y": "垂直于横梁的水平方向（y）", "z": "竖直（z）"}
    d1 = fea["result"].get("mode1_direction")
    em = (fea["result"].get("mode1_effective_mass") or {}).get(d1)
    f = {"status": "report", "f1_hz": f1, "f1_direction": d1, "freqs_hz": fea["result"]["freqs_hz"],
         "f1_formula_vertical_hz": formula["f1_vertical_hz"], "f1_formula_sway_hz": formula["f1_sway_hz"],
         "f1_formula_lateral_hz": formula["f1_lateral_hz"],
         "note": f"门架一阶固有频率 {f1:.3g} Hz" + (f"，主要沿{dname.get(d1, d1)}摆（有效质量占 {em:.0%}）" if d1 and em is not None else "")
                 + f"（公式：横梁水平弯曲 {formula['f1_lateral_hz']:.3g} Hz、立柱侧摆 {formula['f1_sway_hz']:.3g} Hz、"
                   f"跨中竖直 {formula['f1_vertical_hz']:.3g} Hz）"
                 + (f"；放料前停留 {min(dw):g} s 里振 {min(dw) * f1:.0f} 个周期" if dw else "")
                 + "。没有公开的判定值，只报数；阻尼没有数据，余振多久衰减到 ±0.1 mm 以内算不了"}
    return {"deflection": d, "frequency": f}


# ---------------------------------------------------------------- 整条
def run(concept_result: Mapping, build_result: Mapping, out_dir: str | Path, fea: bool = True, reuse: Mapping | None = None) -> dict:
    """三维装配 + 按真实质量复核选件 + 门架公式；fea=True 再做门架有限元（add_fea）。reuse：已算过的 frame_fea，指纹一样就用它"""
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
    xyz = cad["layout"].get("kind") == "xyz"
    res = {"format": FORMAT, "design": {**DESIGN, **DESIGN_XYZ} if xyz else DESIGN, "cad": cad, "moving": {j: {"mass_kg": round(v["mass_kg"], 4),
                                                                          "cog_mm": [round(float(x), 2) for x in v["cog_mm"]]}
                                                                      for j, v in mv.items()},
           "reverify": _compact(out, build_result), "frame_loads": {k: round(v, 4) if isinstance(v, float) else _round(v) for k, v in fl.items()}, "frame_formula": formula}
    _finish(res)
    if fea:
        add_fea(res, cond, out["cycle"], out_dir, reuse)
    return res


def _finish(res: dict) -> None:
    """总结论与待确认：装配通过、复核通过、做了有限元的话变形不是“不通过”"""
    ok = [res["cad"]["status"] == "pass", res["reverify"]["status"] == "pass",
          ((res.get("judge") or {}).get("deflection") or {}).get("status") != "fail"]
    res["status"] = "pass" if all(ok) else "fail"
    res["open_items"] = _open(res, res["reverify"])


def _sig(x):
    """浮点取 5 位有效数字（指纹用；JSON 往返不变）"""
    if isinstance(x, bool) or x is None or isinstance(x, (str, int)):
        return x
    if isinstance(x, float):
        return float(f"{x:.5g}")
    if isinstance(x, Mapping):
        return {str(k): _sig(v) for k, v in sorted(x.items())}
    if isinstance(x, (list, tuple)):
        return [_sig(v) for v in x]
    return x


def fea_fingerprint(res: Mapping) -> str:
    """门架有限元的输入指纹：布置（全部尺寸）、设计值、载荷、运动部分、网格、阶数、材料。一样就说明有限元的输入一样"""
    key = {"layout": res["cad"]["layout"], "design": res["design"], "frame_loads": res["frame_loads"], "moving": res["moving"],
           "mesh_mm": list(_mesh(res["cad"])), "n_modes": N_MODES, "material": MATERIAL, "e_mpa": E_MPA}
    return hashlib.sha256(json.dumps(_sig(_round(key)), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def add_fea(res: dict, cond: Mapping, cycle: Mapping, out_dir: str | Path, reuse: Mapping | None = None) -> dict:
    """门架有限元与判定，写进 res（就地）。载荷、重心取 res 里保存的值，保存的结果重算也是同一个输入。
    reuse 的指纹与这次一样就用它（标 reused），不一样就现算"""
    fp = fea_fingerprint(res)
    if reuse and reuse.get("fingerprint") == fp:
        fr = dict(copy.deepcopy(dict(reuse)), reused=True)
    else:
        fr = frame_fea(res["cad"], res["frame_loads"], res["moving"], Path(out_dir) / "cad")
        fr["fingerprint"] = fp
    res["frame_fea"] = fr
    res["judge"] = judge(fr, res["frame_formula"], res["reverify"].get("repeatability"), cond, cycle)
    _finish(res)
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
    if L.get("kind") == "xyz":
        items.append(f"Y 模组悬臂伸出 {L['modules'][L['chain'][1]['joint']]['length_mm']:g} mm，自身的下垂与扭转没算："
                     "零件库没有费斯托模组型材的截面惯性矩（目录里有，要登记后才能算）")
        items.append("真空气路过 C 轴：要旋转接头或随转的软管（C 轴行程 ±100°，软管也行），没建；吸盘接在转动头板下面")
        items.append(f"竖杆按 {DESIGN_XYZ['arm_wall_mm']:g} mm 壁厚的矩形管建（方案只给了型材外形）；为让转动头板转一圈（外圆半径 "
                     f"{L['c_sweep_r_mm']:.1f} mm）随 Z 上下时从 Z 模组旁边过，竖杆在 C 轴后面 {L['arm_offset_mm']:.1f} mm，由 C 轴支架上板搭过去")
        items.append("转动模组用侧面安装面接 C 轴支架（螺钉孔没建）；转动头板用输出舵盘的 8 个孔")
    j = (res.get("judge") or {}).get("frequency") or {}
    if j.get("f1_direction") == "y" and L.get("kind") == "xyz":
        items.append(f"门架一阶 {j['f1_hz']:.3g} Hz 主要沿 y（垂直于横梁的水平方向）：Y 悬臂在前面，可把横梁加宽或在立柱后面加斜撑——这一版没改")
    elif j.get("f1_direction") == "y":
        items.append(f"门架一阶 {j['f1_hz']:.3g} Hz 是横梁沿 y 的水平弯曲（横梁宽 {DESIGN['beam_w_mm']:g} mm，为让 Z 模组贴着 X 模组背后上下，"
                     "不能比 X 模组宽）；要停得更快，可把横梁只向 +y 一侧加宽或加斜撑——这一版没改，留给按停稳时间核的那一步")
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
    lines.append(f"门架公式：跨中垂直 {f['sag_mm']:g} mm、侧移 {f['sway_mm']:g} mm、侧摆 {f['f1_sway_hz']:g} Hz、横梁水平弯曲 {f['f1_lateral_hz']:g} Hz、竖直 {f['f1_vertical_hz']:g} Hz")
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
