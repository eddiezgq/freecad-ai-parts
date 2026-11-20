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
