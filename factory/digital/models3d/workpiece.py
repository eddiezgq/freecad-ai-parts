# -*- coding: utf-8 -*-
"""工件的三维模型：SH-301 输出轴从毛坯到成品的各工序状态（尺寸取自工艺规程 std/SH-301_process.yaml）。

轴线沿 x，左端面 x = 0（毛坯从 −7 起：两端各留 7 mm，与毛坯 182、工序 20 总长 168 相应）。
状态：blank 下料 → op20 粗车（两端中心孔）→ op40 精车（倒角）→ op50 铣键槽 → op60 磨外圆（成品）。
"""
from __future__ import annotations

import functools
import math
import os

import yaml

from .core import Assembly, Part

STD = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "std"))
STATES = ("blank", "op20", "op40", "op50", "op60")
STATE_NAMES = {"blank": ("下料（工序 10）", "Sawn blank (op 10)"), "op20": ("粗车后（工序 20）", "After rough turning (op 20)"),
               "op40": ("精车后（工序 40）", "After finish turning (op 40)"), "op50": ("铣键槽后（工序 50）", "After keyway milling (op 50)"),
               "op60": ("磨外圆后（工序 60，成品）", "After grinding (op 60, finished)")}


@functools.lru_cache(maxsize=1)
def plan() -> dict:
    with open(os.path.join(STD, "SH-301_process.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _op(seq):
    return next(o for o in plan()["operations"] if o["seq"] == seq)


def segments(state: str):
    """各段 (直径, 长度) 与左端面的 x 位置。"""
    p = plan()
    if state == "blank":
        return [(float(p["blank"]["spec"].lstrip("Ø")), float(p["blank"]["length_mm"]))], -7.0
    if state == "op20":
        st = _op(20)["sketch"]["stock"]
        x0 = -(sum(L for _, L in st) - 167) / 2          # 总长 168：两端各留 0.5（工序 40 车到 167）
        return [(float(d), float(L)) for d, L in st], x0
    if state in ("op40", "op50"):
        return [(float(d), float(L)) for d, L in _op(40)["sketch"]["stock"]], 0.0
    return [(float(d), float(L)) for d, L in _op(60)["sketch"]["stock"]], 0.0


def stepped_profile(segs, x0=0.0, chamfer=0.0, inner_chamfer=0.0):
    """阶梯轴的回转轮廓（x, r），端部倒角 chamfer，轴肩外缘倒角 inner_chamfer。"""
    pts = [(x0, 0.0)]
    x = x0
    r0 = segs[0][0] / 2
    pts += [(x0, r0 - chamfer), (x0 + chamfer, r0)] if chamfer else [(x0, r0)]
    for k, (d, L) in enumerate(segs):
        r = d / 2
        x_end = x + L
        if k + 1 < len(segs):
            rn = segs[k + 1][0] / 2
            c = inner_chamfer if abs(rn - r) > inner_chamfer * 1.5 else 0.0
            if rn > r:            # 台阶向上：在大的一侧倒角
                pts += [(x_end, r), (x_end, rn - c), (x_end + c, rn)] if c else [(x_end, r), (x_end, rn)]
            else:
                pts += [(x_end - c, r), (x_end, r - c), (x_end, rn)] if c else [(x_end, r), (x_end, rn)]
        else:
            pts += [(x_end - chamfer, r), (x_end, r - chamfer)] if chamfer else [(x_end, r)]
            pts.append((x_end, 0.0))
        x = x_end
    # 去掉重复点
    out = []
    for q in pts:
        if not out or (abs(out[-1][0] - q[0]) > 1e-9 or abs(out[-1][1] - q[1]) > 1e-9):
            out.append(q)
    return out


def revolve_x(profile):
    """（x, r）轮廓绕 x 轴回转成实体。"""
    import build123d as bd
    with bd.BuildPart() as bp:
        with bd.BuildSketch(bd.Plane.XY):
            with bd.BuildLine():
                bd.Polyline(*profile, close=True)
            bd.make_face()
        bd.revolve(axis=bd.Axis.X)
    return bp.part


def center_hole(x_face: float, toward: int, d: float = 3.15, D: float = 6.7, pilot: float = 3.0):
    """A 型中心孔（60° 锥面 + 小孔），端面在 x_face，toward = +1 向 x 正向钻入。"""
    import build123d as bd
    h_cone = (D - d) / 2 / math.tan(math.radians(30))
    prof = [(0, 0), (0, D / 2), (h_cone, d / 2), (h_cone + pilot, d / 2), (h_cone + pilot, 0)]
    if toward < 0:
        prof = [(-a, b) for a, b in prof]
    prof = [(x_face + a, b) for a, b in prof]
    # 往外多伸 0.01，保证布尔减干净
    prof[0] = (prof[0][0] - 0.01 * toward, 0)
    prof[1] = (prof[1][0] - 0.01 * toward, prof[1][1])
    return revolve_x(prof)


def keyway(state: str):
    """齿轮位键槽（两端圆头，铣刀 Ø12）：x 从 52 + offset 起，长 L；槽底在轴线上方 r_bottom。"""
    import build123d as bd
    k = plan()["part"]["keyway"]
    b, L, t = float(k["b"]), float(k["L"]), float(k["t"])
    x1 = 52.0 + float(k["offset_mm"])
    r_bottom = 20.0 - t                                     # 成品：d − t₁ = 35，槽底离轴线 15
    top = 25.0
    slot = bd.Pos(x1 + L / 2, 0, r_bottom + top / 2) * bd.extrude(bd.SlotOverall(L, b), amount=top / 2, both=True)
    return slot


def sh301(state: str = "op60", color: str = "work", highlight: bool = False) -> Part:
    """SH-301 的某一工序状态。highlight=True 时本工序加工的面用“machined”颜色。"""
    import build123d as bd
    if state not in STATES:
        raise ValueError(state)
    segs, x0 = segments(state)
    if state == "blank":
        body = bd.Pos(x0, 0, 0) * bd.Cylinder(segs[0][0] / 2, segs[0][1], rotation=(0, 90, 0),
                                              align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    else:
        ch = float(plan()["part"]["chamfer_mm"]) if state != "op20" else 0.0
        body = revolve_x(stepped_profile(segs, x0, chamfer=ch, inner_chamfer=0.5 if state != "op20" else 0.0))
        L = sum(Lk for _, Lk in segs)
        body = body - center_hole(x0, +1) - center_hole(x0 + L, -1)
    if state in ("op50", "op60"):
        body = body - keyway(state)
    fc = None
    if highlight and state != "blank":
        fc = _highlighter(state)
    return Part(f"SH-301 {state}", body, color, face_color=fc)


def _highlighter(state):
    """本工序加工的面：粗车、精车——全部回转面；铣键槽——键槽面；磨削——两轴承位、齿轮位外圆。"""
    import build123d as bd

    def f(face):
        gt = face.geom_type
        c = face.center()
        if state in ("op20", "op40"):
            return "machined"
        if state == "op50":
            r = math.hypot(c.Y, c.Z)
            return "machined" if (c.Z > 10 and 59 <= c.X <= 105 and r < 20.1 and gt != bd.GeomType.CYLINDER or
                                  (gt == bd.GeomType.CYLINDER and c.Z > 12 and 59 <= c.X <= 105 and r < 19.9)) else None
        if state == "op60":
            if gt == bd.GeomType.CYLINDER:
                r = math.hypot(c.Y, c.Z) if abs(c.Y) + abs(c.Z) > 1e-6 else face.radius
                try:
                    rad = face.radius
                except Exception:   # noqa: BLE001
                    rad = r
                if abs(rad - 17.5) < 0.01 or abs(rad - 20.0) < 0.01:
                    return "machined"
        return None
    return f


def sh301_assembly(state: str = "op60", highlight=False) -> Assembly:
    a = Assembly(f"SH-301 {state}")
    a.add(sh301(state, highlight=highlight))
    return a
