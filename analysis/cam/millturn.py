"""车铣复合的插补换算（ADR-0104 C2、ADR-0106 C2b 第 1 步）：程序坐标 ↔ 工件坐标（随 C 轴转的工件坐标，x y z，mm）。

- 极坐标插补 G12.1（端面铣）：程序在虚拟平面 X–C 里写，X 是直径（与车削一样），C 是毫米（虚拟轴）。
  工件坐标：(X/2, C, Z)。机床：半径 r = √((X/2)² + C²)，C 轴角度由整机仿真按机床模型逆解（转向按机床文件）。
- 圆柱插补 G7.1 C r（圆柱面铣）：程序写 Z 和 C（度），X 是刀尖所在直径（下刀深度）；工件坐标：(x/2·cos C, x/2·sin C, Z)。
  展开图上的弧长 = r·C（弧度），r 是 G7.1 给的圆柱半径（进给按展开图算）。
直线插补在圆柱面上是螺旋线：`cyl_segment` 按角度不超过 2° 拆成小段。
"""

from __future__ import annotations

import itertools
import math

MAX_STEP_DEG = 2.0


def polar_to_work(x_dia: float, c_mm: float, z: float) -> tuple[float, float, float]:
    return (x_dia / 2.0, c_mm, z)


def work_to_polar(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (2.0 * x, y, z)


def polar_machine(x_dia: float, c_mm: float) -> tuple[float, float]:
    """虚拟平面上的点 → 机床直径、点所在的极角（度，工件坐标里）"""
    u = x_dia / 2.0
    return 2.0 * math.hypot(u, c_mm), math.degrees(math.atan2(c_mm, u))


def cyl_to_work(x_dia: float, c_deg: float, z: float) -> tuple[float, float, float]:
    r = x_dia / 2.0
    a = math.radians(c_deg)
    return (r * math.cos(a), r * math.sin(a), z)


def work_to_cyl(x: float, y: float, z: float) -> tuple[float, float, float]:
    return (2.0 * math.hypot(x, y), math.degrees(math.atan2(y, x)), z)


def index_to_work(p, theta_deg: float) -> tuple[float, float, float]:
    """C 轴分度 θ 后的 Y 轴铣（G19，ADR-0106 C2b）：程序 (X 直径, Y, Z) → 工件坐标 Rz(θ)·(X/2, Y, Z)（θ 同圆柱插补的 C：刀在工件上的角度）"""
    a = math.radians(theta_deg)
    u, v = p[0] / 2.0, p[1]
    return (u * math.cos(a) - v * math.sin(a), u * math.sin(a) + v * math.cos(a), p[2])


def index_axis(theta_deg: float) -> tuple[float, float, float]:
    """分度铣的刀轴（径向动力刀，从刀尖指向刀座）：Rz(θ)·(1, 0, 0)"""
    a = math.radians(theta_deg)
    return (math.cos(a), math.sin(a), 0.0)


def arc_length(c_deg: float, r: float) -> float:
    """圆柱插补展开图上的长度（mm）"""
    return math.radians(c_deg) * r


def cyl_segment(a: tuple[float, float, float], b: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    """圆柱插补的一段直线（程序坐标 直径、C 度、Z）→ 工件坐标里的小段终点（含 b），角度每段不超过 2°"""
    n = max(1, math.ceil(abs(b[1] - a[1]) / MAX_STEP_DEG))
    out = []
    for k in range(1, n + 1):
        t = k / n
        out.append(cyl_to_work(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t))
    return out


# ---------------------------------------------------------------- 第 3 步：车完的形状上切铣削段（ADR-0106 C2b）
def revolved_triangles(profile, n: int = 256):
    """车削外形 [(z, r), …]（z 从右往左，首尾 r 可为 0 或不为 0）→ 绕 Z 轴回转的封闭三角网格 (m, 3, 3)，两端补端面"""
    import numpy as np

    prof = [(float(z), float(r)) for z, r in profile]
    ang = np.linspace(0.0, 2 * math.pi, n + 1)
    cs, sn = np.cos(ang), np.sin(ang)
    tris = []
    for (z0, r0), (z1, r1) in itertools.pairwise(prof):
        for k in range(n):
            p00 = (r0 * cs[k], r0 * sn[k], z0)
            p01 = (r0 * cs[k + 1], r0 * sn[k + 1], z0)
            p10 = (r1 * cs[k], r1 * sn[k], z1)
            p11 = (r1 * cs[k + 1], r1 * sn[k + 1], z1)
            if r0 > 0:
                tris.append((p00, p01, p11))
            if r1 > 0:
                tris.append((p00, p11, p10))
    for z, r in (prof[0], prof[-1]):                  # 端面
        if r <= 0:
            continue
        for k in range(n):
            tris.append(((0.0, 0.0, z), (r * cs[k], r * sn[k], z), (r * cs[k + 1], r * sn[k + 1], z)))
    return np.asarray(tris, float)


def mill_on_turned(parsed, profile, tools: dict, h: float = 0.25):
    """车铣程序的铣削段在车完的外形上切（三向 dexel，按每小段的刀轴）。tools：{刀号: dexel.Tool.from_spec 的 spec}。
    → {"removed_mm3", "dexel", "issues"}：快移切到材料报错"""
    from analysis.cam import dexel as DX

    rmax = max(r for _z, r in profile)
    zs = [z for z, _r in profile]
    pad = max([float(s["d"]) for s in tools.values()] + [1.0]) + 2 * h
    tri = revolved_triangles(profile)
    st = DX.Dexel.from_triangles(tri, h, lo=[-rmax - pad, -rmax - pad, min(zs) - pad], hi=[rmax + pad, rmax + pad, max(zs) + pad])
    built = {t: DX.Tool.from_spec(s) for t, s in tools.items()}
    v0 = st.volume()
    issues = []
    for mv in parsed["moves"]:
        if not mv.get("mill"):
            continue
        tl = built.get(mv["tool"])
        if tl is None:
            continue
        cut = 0.0
        for p0, p1, w in mv["pieces"]:
            cut += st.cut(tl, p0, p1, w=w)["volume"]
        if mv["t"] == "rapid" and cut > h ** 3:
            issues.append({"line": mv["line"], "level": "error", "text": f"快移撞到工件：切掉 {cut:.1f} mm³（快移不能切削）"})
    return {"removed_mm3": v0 - st.volume(), "dexel": st, "issues": issues}


# ---------------------------------------------------------------- 车铣作业的动力刀工序（ADR-0106 C2b 界面）
def to_polar_moves(moves: list[dict], z0: float = 0.0) -> list[dict]:
    """端面坐标里的铣削刀路（x, y, z，z 从端面量）→ 极坐标插补程序（x 直径、c = y 毫米、z = z0 + z）"""
    out = []
    for m in moves:
        if m.get("t") == "comment":
            out.append(dict(m))
            continue
        q = {"t": m["t"], "x": 2.0 * float(m["x"]), "c": float(m["y"]), "z": z0 + float(m["z"])}
        if "f" in m:
            q["f"] = m["f"]
        out.append(q)
    return out


def face_moves(feature: dict, tool_d: float, step_down: float, f: float, f_plunge: float, stepover: float = 0.5,
               safe: float = 5.0) -> list[dict]:
    """端面上的槽 / 型腔 → 极坐标插补刀路。feature：{"type": "slot", "a", "b", "width", "depth", "z0"} 或
    {"type": "pocket", "rect", "corner_r", "depth", "z0"}（端面坐标 mm；z0 = 槽口所在端面的 Z，深度往 −Z 量）"""
    from analysis.cam import paths as P

    if feature["type"] == "slot":
        mv = P.mill_slot(feature["a"], feature["b"], feature["width"], feature["depth"], tool_d, step_down, f, f_plunge, safe=safe)
    elif feature["type"] == "pocket":
        mv = P.mill_pocket(feature["rect"], feature.get("corner_r", 0.0), feature["depth"], tool_d, stepover, step_down, f, f_plunge,
                           safe=safe)
    else:
        raise ValueError(f"端面动力刀工序只做槽和型腔：{feature['type']!r}")
    return to_polar_moves(mv, float(feature.get("z0", 0.0)))


def keyway_moves(angle_deg: float, r_outer: float, depth: float, za: float, zb: float, tool_d: float, step_down: float,
                 f: float, f_plunge: float, safe: float = 2.0) -> list[dict]:
    """圆柱面上沿 Z 的键槽（槽宽 = 刀径，两端圆心 za、zb）→ 圆柱插补刀路（x 直径、c 度、z）。
    每层在 za 处下到这一层，走到 zb、再回 za；最后退到外圆以外 safe。"""
    if depth <= 0 or tool_d <= 0:
        raise ValueError("键槽深度、刀径要大于 0")
    layers = max(1, math.ceil(depth / step_down - 1e-9))
    x_out = 2.0 * (r_outer + safe)
    mv = [{"t": "comment", "text": f"圆柱面键槽：宽 {tool_d:g} 深 {depth:g}，分 {layers} 层"},
          {"t": "rapid", "x": x_out, "c": angle_deg, "z": za}]
    for k in range(layers):
        x = 2.0 * (r_outer - depth * (k + 1) / layers)
        mv += [{"t": "feed", "x": x, "c": angle_deg, "z": za, "f": f_plunge},
               {"t": "feed", "x": x, "c": angle_deg, "z": zb, "f": f},
               {"t": "feed", "x": x, "c": angle_deg, "z": za, "f": f}]
    mv.append({"t": "rapid", "x": x_out, "c": angle_deg, "z": za})
    return mv


def classify_face(area: float, xmin: float, ymin: float, xmax: float, ymax: float, tol: float = 0.01) -> dict | None:
    """端面上一个平底面（槽底 / 型腔底）的外形：按包围盒和面积认长圆槽或圆角矩形；都对不上返回 None。
    长圆：短边 w，面积 (L − w)·w + π·w²/4；圆角矩形：面积 W·H − (4 − π)·r²，r 由面积反算（0 ≤ r ≤ 短边一半）。"""
    W, H = xmax - xmin, ymax - ymin
    w, L = min(W, H), max(W, H)
    if w <= 0:
        return None
    st = (L - w) * w + math.pi * w * w / 4
    if abs(area - st) <= tol * area:
        cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
        h = (L - w) / 2
        a, b = ((cx - h, cy), (cx + h, cy)) if W >= H else ((cx, cy - h), (cx, cy + h))
        return {"type": "slot", "a": [a[0], a[1]], "b": [b[0], b[1]], "width": w}
    r2 = (W * H - area) / (4 - math.pi)
    if r2 >= -tol * area and r2 <= (w / 2) ** 2 * (1 + tol):
        r = math.sqrt(max(r2, 0.0))
        return {"type": "pocket", "rect": [xmin, ymin, xmax, ymax], "corner_r": min(r, w / 2)}
    return None


def flat_moves(feature: dict, tool_d: float, step_down: float, f: float, f_plunge: float, stepover: float = 0.5,
               safe: float = 2.0) -> list[dict]:
    """圆柱面上的平底槽（C 轴分度 + Y 轴铣，ADR-0106 C2b）→ 程序动作（x 直径、y、z）。feature：{"type": "flat", "angle", "r_outer",
    "depth", "shape": {"type": "slot", "a", "b", "width"} 或 {"type": "pocket", "rect", "corner_r"}}；形状在槽底平面坐标里给
    （u = 切向 = 分度后的机床 Y，v = Z）。铣槽、型腔刀路的深度坐标 z（0 在外圆最高处，向下为负）换成 X = 2·(r_外 + z)。"""
    from analysis.cam import paths as P

    sh, depth, r = feature["shape"], float(feature["depth"]), float(feature["r_outer"])
    if sh["type"] == "slot":
        mv = P.mill_slot(sh["a"], sh["b"], sh["width"], depth, tool_d, step_down, f, f_plunge, safe=safe)
    elif sh["type"] == "pocket":
        mv = P.mill_pocket(sh["rect"], sh.get("corner_r", 0.0), depth, tool_d, stepover, step_down, f, f_plunge, safe=safe)
    else:
        raise ValueError(f"圆柱面平底槽只做长圆和圆角矩形：{sh['type']!r}")
    out = []
    for m in mv:
        if m.get("t") == "comment":
            out.append(dict(m))
            continue
        q = {"t": m["t"], "x": 2.0 * (r + float(m["z"])), "y": float(m["x"]), "z": float(m["y"])}
        if "f" in m:
            q["f"] = m["f"]
        out.append(q)
    return out
