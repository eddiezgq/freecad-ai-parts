"""整机方案 + 选定的关节模组：装不装得下（ADR-0115 44.3 之二第 3 步之一）。纯几何：不联网、不调用 AI。

一体化关节模组（如 Dynamixel X540）只有输出舵盘会转；能固定的面（底面、两侧面）都与输出轴平行。由此每个关节分两类：
  · 侧摆（U 形支架）：子杆与关节轴垂直——子杆通过一个跨在前后两个舵盘上的 U 形支架带动，U 的底板在离轴线 d 处，杆从底板伸出。
  · 轴转（法兰）：子杆沿关节轴——子杆接在输出舵盘端面的法兰上。
关节模组的壳体用底面装在父杆末端（壳体底座）。

查三件事：
  1 转角够不够（侧摆）：U 的底板随关节转动，不能碰到自己的壳体和下面的父杆（父杆与壳体底座看成从壳体底面一直往下的一条，
    宽度取壳体宽与父杆外径中大的）。二维（垂直关节轴的平面）用分离轴法判两个凸矩形相交；在 0.5° 一步上找最大转角，
    再二分找满足方案行程所需的最小 d（d_min）。行程超过几何上限的判不通过。
  2 装法做得到吗（轴转）：子杆沿轴、父杆也沿轴（共线）时，壳体要从背面固定，而背面是惰轮舵盘（会转），没有固定面——判不通过，
    说清楚要怎么改（让轴线偏开，或换带后端固定法兰的模组）。
  3 长度够不够：下一关节的壳体（底面朝着本关节装在本杆上）沿杆向离本关节轴线最近的点，要在本关节 U 底板（d_min）之外；
    侧摆、轴转（轴线偏开）两种下一关节都按壳体的八个角算。剩下的长度给支架板厚、杆套和管子，不足的判不通过。
  5 直管：下一关节壳体底面要正对本杆、管子落在底面以内（杆件都做直管，弯的、异形的连接件这一步不做）。
  4 装在基座上的关节：壳体要在安装面朝机器人的一侧（输出舵盘在关节原点、壳体在它后面——原点贴着安装面时壳体就钻到桌面下了）。
板厚、管套长度等由支架设计（第 3 步之二）定，这里只给几何上必需的最小值。
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np

from analysis.robot import kinematics as K
from analysis.robot import mjcf

STEP_DEG = 0.5
D_MAX_MM = 300.0
PLATE_DEPTH_MM = 25.0           # U 底板加杆套伸出的径向深度（只用来判碰撞的外形，偏保守取 25 mm）


def _rect(cx0: float, cx1: float, cy0: float, cy1: float) -> np.ndarray:
    return np.array([[cx0, cy0], [cx1, cy0], [cx1, cy1], [cx0, cy1]], float)


def _overlap(a: np.ndarray, b: np.ndarray) -> bool:
    """两个凸多边形是否相交（分离轴定理；只接触不算）"""
    for poly in (a, b):
        for i in range(len(poly)):
            e = poly[(i + 1) % len(poly)] - poly[i]
            n = np.array([-e[1], e[0]])
            pa, pb = a @ n, b @ n
            if pa.max() <= pb.min() + 1e-9 or pb.max() <= pa.min() + 1e-9:
                return False
    return True


def _rot(poly: np.ndarray, deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return poly @ np.array([[c, s], [-s, c]])


def clevis_reach(d: float, plate_width: float, housing: Mapping, parent_width: float) -> float:
    """U 底板离轴线 d 时，从伸直位往一侧能转的最大角（°）。壳体：轴线在原点，x 半宽 housing["half_width"]，
    y 从 housing["bottom"]（负）到 housing["top"]；父杆从壳体底面往下（宽 parent_width）。对称，两侧相同"""
    hw = housing["half_width"]
    obstacles = [_rect(-hw, hw, housing["bottom"], housing["top"]),
                 _rect(-parent_width / 2, parent_width / 2, housing["bottom"] - 1000.0, housing["bottom"])]
    plate = _rect(-plate_width / 2, plate_width / 2, d, d + PLATE_DEPTH_MM)
    best = -1.0
    for th in np.arange(0.0, 180.0 + 1e-9, STEP_DEG):
        p = _rot(plate, th)
        if any(_overlap(p, o) for o in obstacles):
            break
        best = float(th)
    return best


def d_min(required_deg: float, plate_width: float, housing: Mapping, parent_width: float) -> float | None:
    """转到 required_deg 所需的最小 d（mm，二分到 0.1 mm）；到 D_MAX_MM 也不够返回 None"""
    if clevis_reach(D_MAX_MM, plate_width, housing, parent_width) < required_deg:
        return None
    lo, hi = 0.0, D_MAX_MM
    while hi - lo > 0.1:
        mid = (lo + hi) / 2
        if clevis_reach(mid, plate_width, housing, parent_width) >= required_deg:
            hi = mid
        else:
            lo = mid
    return round(hi, 1)


def housing_geometry(comp: Mapping) -> dict | None:
    """从模组的端口算壳体在垂直输出轴平面里的外形（轴线为原点，+y 朝顶面）；缺端口返回 None"""
    ports = {p["id"]: p for p in comp.get("ports") or []}
    if not {"output_flange", "mount_bottom", "mount_side_r", "mount_side_l"} <= set(ports):
        return None
    bottom = ports["mount_bottom"]["frame"]["origin_mm"][1]
    half_w = abs(ports["mount_side_r"]["frame"]["origin_mm"][0])
    body = next((p for p in comp["envelope"]["parts"] if p.get("label") == "body"), None)
    if body is None:
        return None
    top = body["height_mm"]["value"] / 2                    # 包络按轴线居中、高取保守：顶面不超过它
    horn = next((p for p in comp["envelope"]["parts"] if p.get("label") == "output_horn"), None)
    return {"half_width": half_w, "bottom": bottom, "top": min(top, -bottom), "axis_to_bottom": -bottom,
            "horn_diameter": horn["diameter_mm"]["value"] if horn else None}


def _corners(c: K.Joint, kind: str, g: Mapping, toward: np.ndarray) -> list[np.ndarray]:
    """关节 c 的壳体八个角（父件坐标系）。壳体底面朝 toward 方向（垂直于 c 的轴的分量）；
    侧摆关节的原点在两舵盘中间（壳体沿轴 ±22），轴转关节的原点在输出舵盘端面（壳体在其后 2.5–46.5）"""
    a = c.axis / np.linalg.norm(c.axis)
    o = np.asarray(c.origin, float)
    back = toward - (toward @ a) * a
    if np.linalg.norm(back) < 1e-9:
        back = np.cross(a, [1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.cross(a, [0.0, 1.0, 0.0])
    bdir = back / np.linalg.norm(back)
    side = np.cross(a, bdir)
    zs = (-22.0, 22.0) if kind == "clevis" else (-46.5, -2.5)
    return [o + z * a + t * bdir + w * side for z in zs for t in (-g["top"], g["axis_to_bottom"])
            for w in (-g["half_width"], g["half_width"])]


def base_clearance(c: K.Joint, kind: str, g: Mapping, mount: str) -> dict:
    """装在基座上的关节：壳体要在安装面朝机器人的一侧（桌面、地面装：z ≥ 0；吊装：z ≤ 0）。返回 {"status", "note", ...}"""
    if mount not in ("table", "floor", "ceiling"):
        return {"status": "unknown", "note": f"安装方式 {mount}：安装面朝哪边方案里没写，判不了"}
    sign = -1.0 if mount == "ceiling" else 1.0
    pts = _corners(c, kind, g, -np.asarray(c.origin, float) if np.linalg.norm(c.origin) > 1e-9 else np.array([0, 0, -sign]))
    low = min(sign * float(p[2]) for p in pts)
    need = sign * float(c.origin[2]) - low
    if low >= -1e-9:
        return {"status": "pass", "clear_mm": round(low, 1), "note": f"{c.id} 的壳体在安装面以上 {low:.1f} mm 起"}
    return {"status": "fail", "clear_mm": round(low, 1),
            "note": (f"{c.id} 的模组壳体会伸到安装面另一侧 {-low:.1f} mm（输出舵盘在原点处，壳体在它后面）："
                     f"把 {c.id} 的原点抬到离安装面至少 {need:.1f} mm（再加底座板厚），臂展点等按新的高度重算")}


def _nearest(c: K.Joint, kind: str, g: Mapping, u: np.ndarray) -> float:
    """下一关节 c 的壳体（底面朝本关节）沿杆向 u 离本关节轴线（杆件坐标原点）最近的距离（mm）"""
    o = np.asarray(c.origin, float)
    toward = -o if np.linalg.norm(o) > 1e-9 else -u
    return float(min(pt @ u for pt in _corners(c, kind, g, toward)))


def _straight(c: K.Joint, kind: str, g: Mapping, u: np.ndarray) -> str:
    """杆件是直管：下一关节壳体的底面要正对本杆（底面法线沿杆向、朝着本关节），管子的轴线要穿过底面（支架板可以比底面大，
    管子粗些没关系；轴线落在底面以外，支架就成了悬臂，不做）。
    通过返回空串，否则返回原因与改法"""
    a = c.axis / np.linalg.norm(c.axis)
    zmid = 0.0 if kind == "clevis" else -24.5
    centre = np.asarray(c.origin, float) + zmid * a          # 壳体中心（轴转关节的原点在舵盘端面，中心在它后面 24.5）
    if np.linalg.norm(centre) > 1e-9:
        u = centre / np.linalg.norm(centre)                 # 直管沿本关节到下一壳体中心
    if abs(float(a @ u)) > math.sin(math.radians(1.0)):
        ang = math.degrees(math.asin(min(1.0, abs(float(a @ u)))))
        return (f"{c.id} 的轴线与本杆（本关节到 {c.id} 壳体中心）不垂直（偏 {ang:.0f}°）：模组的底面与轴线平行，底面朝不了杆向，直管接不上。"
                f"改法：让 {c.id} 的轴线垂直于本杆（轴转关节就让它的子杆垂直于本杆伸出"
                + ("；轴转关节的原点在输出舵盘端面、壳体中心在它后面 24.5 mm，原点要沿它的轴线前移 24.5 mm，壳体中心才落在杆轴上"
                   if kind == "flange" else "") + "）")
    lat = centre - (centre @ u) * u
    side = np.cross(a, -u)
    ea, es = abs(float(lat @ a)), abs(float(lat @ side))
    lim_a, lim_s = 22.0, g["half_width"]
    if ea <= lim_a + 1e-9 and es <= lim_s + 1e-9:
        return ""
    hint = (f"轴转关节的原点在输出舵盘端面，壳体中心在它后面 24.5 mm：把 {c.id} 的原点沿它的轴线挪到让壳体中心落在本杆轴线上"
            if kind == "flange" else f"把 {c.id} 的原点放在本杆轴线上")
    return (f"本杆的管子要接在 {c.id} 壳体底面上，管轴离底面中心沿 {c.id} 轴向 {ea:.1f} mm、侧向 {es:.1f} mm，"
            f"落在底面以外（底面半长 {lim_a:g}、半宽 {lim_s:g} mm）。改法：{hint}")


def _tube_od(link: Mapping) -> float:
    s = link.get("section") or {}
    return float(s.get("od_mm") or max(s.get("width_mm") or 0, s.get("height_mm") or 0) or 0.0)


def check(concept: Mapping, actuators: Mapping[str, Mapping]) -> dict:
    """actuators：{关节 id: 模组组件}。返回 {"joints": [...], "links": [...], "overall"}"""
    m = K.build(concept)
    out_j, out_l = [], []
    kind: dict[str, str] = {}
    need: dict[str, float] = {}
    geo: dict[str, dict] = {}
    for j in m.joints:
        comp = actuators.get(j.id)
        g = housing_geometry(comp) if comp else None
        row = {"joint": j.id, "actuator": comp["id"] if comp else None}
        if g is None:
            row.update(status="unknown", note="模组没有机械接口数据（舵盘、安装孔、外形），装不装得下判不了")
            out_j.append(row)
            continue
        geo[j.id] = g
        end = mjcf._segment(m, j.child)
        n = float(np.linalg.norm(end))
        if n < 1e-6:
            kind[j.id] = "flange"
            row.update(type="轴转（法兰）", status="pass", note="子件没有长度（末端）：接在输出舵盘法兰上")
            out_j.append(row)
            continue
        cosang = abs(float(np.dot(end / n, j.axis)))
        if cosang < 1e-6:
            kind[j.id] = "clevis"
            parent = m.links.get(j.parent)
            pw = max(2 * g["half_width"], _tube_od(parent) if parent else 0.0)
            req = max(abs(j.lo or 0.0), abs(j.hi or 0.0))
            plate_w = max(2 * g["half_width"], g["horn_diameter"] or 0.0, _tube_od(m.links[j.child]))
            dm = d_min(req, plate_w, g, pw)
            row.update(type="侧摆（U 形支架）", required_deg=req, parent_width_mm=pw, plate_width_mm=plate_w)
            if dm is None:
                cap = clevis_reach(D_MAX_MM, plate_w, g, pw)
                row.update(status="fail", note=f"行程 ±{req:g}° 超出几何上限（U 底板再远也只能转 {cap:g}°，会碰到自己的壳体或下面的父杆）")
            else:
                need[j.id] = dm
                row.update(status="pass", d_min_mm=dm, note=f"U 底板离轴线至少 {dm:g} mm 才能转到 ±{req:g}°")
        elif abs(cosang - 1) < 1e-6:
            kind[j.id] = "flange"
            parent_dir = None
            pj = m.by_child.get(j.parent)
            if pj is not None:
                pe = mjcf._segment(m, j.parent)
                if np.linalg.norm(pe) > 1e-6:
                    parent_dir = pe / np.linalg.norm(pe)
            collinear = parent_dir is not None and abs(abs(float(np.dot(parent_dir, j.axis))) - 1) < 1e-6
            row.update(type="轴转（法兰）")
            if collinear and j.parent != "base":
                row.update(status="fail", note=("父杆与子杆都沿这个关节的轴线（共线轴转）：模组能固定的面（底面、侧面）都与输出轴平行，"
                                                 f"背面是会转的惰轮舵盘，共线装不上。改法：让轴线相对父杆偏开至少 {g['axis_to_bottom']:g} mm"
                                                 "（壳体底面装在父杆上），或换带后端固定法兰的模组"))
            else:
                row.update(status="pass", note="子杆接在输出舵盘法兰上；壳体底面装在父件上（轴线与父件偏开）")
        else:
            row.update(status="unknown", note="子杆与关节轴既不垂直也不平行：支架型式这一步不处理")
        if j.parent == "base" and row.get("status") == "pass":
            bc = base_clearance(j, kind[j.id], g, concept["base"]["mount"])
            if bc["status"] != "pass":
                row.update(status=bc["status"], note=row["note"] + "；" + bc["note"])
            else:
                row["base_clear_mm"] = bc["clear_mm"]
        out_j.append(row)
    for j in m.joints:
        nxt = [c for c in m.joints if c.parent == j.child]
        end = mjcf._segment(m, j.child)
        if not nxt or float(np.linalg.norm(end)) < 1e-6:
            continue
        u = end / np.linalg.norm(end)
        for c in nxt:
            row = {"link": j.child, "from": j.id, "to": c.id, "length_mm": round(float(np.linalg.norm(c.origin)), 1)}
            failed = {r["joint"] for r in out_j if r["status"] != "pass"}
            if j.id not in kind or c.id not in geo or c.id not in kind or {j.id, c.id} & failed:
                row.update(status="unknown", note="两端有一端装法没定（见关节一栏），长度判不了")
                out_l.append(row)
                continue
            prox = need.get(j.id, 0.0) if kind[j.id] == "clevis" else 0.0
            near = _nearest(c, kind[c.id], geo[c.id], u)
            spare = near - prox
            row.update(min_mm=round(prox, 1), body_near_mm=round(near, 1), spare_mm=round(spare, 1),
                       status="pass" if spare > 0 else "fail",
                       note=(f"{c.id} 的壳体离 {j.id} 最近 {near:.1f} mm（沿杆向），{j.id} 的 U 底板要 {prox:g} mm；"
                             + (f"余 {spare:.1f} mm 给支架板厚、杆套与管子" if spare > 0
                                else f"差 {-spare:.1f} mm：{c.id} 的壳体伸进了 {j.id} 的 U 形支架转动范围")))
            straight = _straight(c, kind[c.id], geo[c.id], u)
            if straight:
                row["status"] = "fail"
                row["note"] += "；" + straight
            out_l.append(row)
    st = {r["status"] for r in out_j + out_l}
    overall = "fail" if "fail" in st else "unknown" if "unknown" in st else "pass"
    return {"joints": out_j, "links": out_l, "overall": overall}
