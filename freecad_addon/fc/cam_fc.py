"""问渠CAM：2.5 轴铣用 FreeCAD 自带的 CAM 工作台出刀路（ADR-0104 第 2 节“刀路”块，C1）。

FreeCAD CAM 的 2.5 轴铣（型腔、外轮廓、钻孔）成熟，直接用它算刀路；但**不用它的后处理**：
它的刀路命令（Path.Command）在这里换成问渠CAM 的中间格式（工序 → 刀具、转速、动作表），交给 `analysis.cam.run` 的 program 模式，
走同一套切削仿真、整机仿真、后处理与回读比对（ADR-0104 安全底线）。

- 型腔：零件上所有朝上的、低于顶面的平面当型腔底（PocketShape）；
- 外轮廓：整个零件外轮廓（Profile，外侧）；
- 钻孔：FreeCAD 找出能钻的孔（Drillable），只取直径等于钻头直径的（Drilling，G81 / G83 换成我们的钻孔动作）；通孔多钻一个钻尖长。
程序坐标：XY 与零件相同，Z0 在零件顶面（FreeCAD 里是零件的最高点）。
刀具从 cam-tool/1 刀具库来：平底立铣刀用 FreeCAD 的 endmill 形状，钻头用 drill 形状，只把直径、刃长、柄径、总长、钻尖角传过去。
FreeCAD 1.0 在没有界面时，作业里有多把刀会在新建工序时报错（findToolController 要弹窗问用户），所以先建工序、再加刀、最后指定。
"""

from __future__ import annotations

import math
from pathlib import Path

SHAPES = {"flat_endmill": "endmill.fcstd", "bull_endmill": "bullnose.fcstd", "ball_endmill": "ballend.fcstd",
          "drill": "drill.fcstd", "chamfer_mill": "chamfer.fcstd"}
ARC_DEG = 5.0      # 圆弧拆成直线段，每段不超过 5°


class CamFcError(ValueError):
    pass


def _bit(tool: dict):
    import Path.Tool.Bit as PathToolBit

    shape = SHAPES.get(tool["kind"])
    if shape is None:
        raise CamFcError(f"刀具 {tool['id']} 的种类 {tool['kind']} 在 2.5 轴铣里还不支持")
    bit = PathToolBit.Factory.Create(tool["id"], PathToolBit.findToolShape(shape))
    bit.Diameter = float(tool["diameter_mm"])
    for k, prop in (("flute_length_mm", "CuttingEdgeHeight"), ("overall_length_mm", "Length"),
                    ("shank_diameter_mm", "ShankDiameter"), ("tip_angle_deg", "TipAngle")):
        if k in tool and hasattr(bit, prop):
            setattr(bit, prop, float(tool[k]))
    if tool["kind"] == "bull_endmill" and "corner_radius_mm" in tool and hasattr(bit, "FlatRadius"):
        bit.FlatRadius = float(tool["diameter_mm"]) / 2 - float(tool["corner_radius_mm"])
    return bit


def pocket_floors(shape, top: float) -> list[str]:
    """型腔底：朝上、低于顶面的平面；沉孔的环形底面不算（沉孔另有工序，ADR-0106 Q3b）"""
    from freecad_addon.fc import cam_doc

    cb = [(h["x"], h["y"], h["cbore"]["d"]) for h in cam_doc.mill_holes(shape) if h["cbore"]]
    out = []
    for i, f in enumerate(shape.Faces):
        if type(f.Surface).__name__ != "Plane":
            continue
        n = f.normalAt(*f.ParameterRange[0::2])
        if n.z > 1 - 1e-9 and shape.BoundBox.ZMin + 1e-6 < f.BoundBox.ZMax < top - 1e-6:
            bb = f.BoundBox
            if any(abs(bb.Center.x - x) < 1e-3 and abs(bb.Center.y - y) < 1e-3 and abs(bb.XLength - d) < 1e-3 for x, y, d in cb):
                continue
            out.append(f"Face{i + 1}")
    return out


OWN = ("csink", "tap", "cbore")     # 问渠自己出刀路的孔工序（FreeCAD CAM 1.0 没有攻丝；锪孔口、沉孔按孔特征直接算）


def sim_tool(t: dict, n: int) -> dict:
    """cam-tool/1 刀具 → 中间格式程序里的刀（仿真用的种类、直径；丝锥的螺距，倒角刀的锥角、刀尖直径）"""
    kind = {"drill": "drill", "tap": "tap", "chamfer_mill": "chamfer"}.get(t["kind"], "endmill")
    out = {"n": n, "name": t.get("name", t["id"]), "d": float(t["diameter_mm"]), "kind": kind}
    if kind == "tap":
        out["pitch"] = float(t["pitch_mm"])
    if kind == "chamfer":
        out["angle"] = float(t["tip_angle_deg"])
        out["tip_d"] = float(t.get("tip_diameter_mm", 0.0))
    return out


def own_moves(spec: dict) -> list[dict]:
    """spec["holes"]：程序坐标（Z0 在零件顶面）。csink [(x, y, 孔口 z)]；tap [(x, y, 孔口 z, 攻到 z)]；cbore [(x, y, 孔口 z, 深)]"""
    from analysis.cam import paths as P

    t, k = spec["tool"], spec["type"]
    if k == "csink":
        return P.mill_csink(spec["holes"], spec["d"], float(t["tip_angle_deg"]), spec["feed_mm_min"],
                            tip_d=float(t.get("tip_diameter_mm", 0.0)))
    if k == "tap":
        return P.mill_tap(spec["holes"], float(t["pitch_mm"]))
    mv = []
    for x, y, ze, dp in spec["holes"]:
        mv += P.mill_cbore(x, y, spec["d"], dp, ze, float(t["diameter_mm"]), spec["step_down_mm"], spec["feed_mm_min"])
    return mv


def build_job(doc, model, ops: list[dict]):
    """ops：[{"type": "pocket" | "profile" | "drill", "tool": cam-tool/1 刀具, "number": 刀号, "rpm", "feed_mm_min",
             "plunge_mm_min", "step_down_mm", "step_over_pct", "faces": 点选的面（可选：型腔底面、孔的圆柱面；不给时自动找）}]。
    返回 (作业, [(op 设置, FreeCAD 工序)])"""
    import Path.Tool.Controller as PathToolController
    from Path.Base import Drillable
    from Path.Main import Job as PathJob
    from Path.Op import Drilling, PocketShape, Profile

    job = PathJob.Create("Job", [model])
    jm = job.Model.Group[0]
    top = jm.Shape.BoundBox.ZMax
    made = []
    for spec in ops:
        k = spec["type"]
        if k == "pocket":
            floors = list(spec.get("faces") or []) or pocket_floors(jm.Shape, top)
            if not floors:
                raise CamFcError("零件上没有找到型腔底面（朝上、低于顶面的平面）")
            op = PocketShape.Create(f"Pocket{len(made) + 1}")
            op.Base = [(jm, floors)]
            op.StepOver = round(float(spec.get("step_over_pct", 40)))
            op.OffsetPattern = "ZigZagOffset"      # 之字形清中间 + 最后贴壁一圈：直角转角铣到刀具够得着的地方（ADR-0106 Q2 色差图查出来的）
        elif k == "profile":
            op = Profile.Create(f"Profile{len(made) + 1}")
        elif k == "drill":
            d = float(spec["tool"]["diameter_mm"])
            picked = set(spec.get("faces") or [])
            holes = [h for h in Drillable.getDrillableTargets(jm)
                     if abs(2 * jm.Shape.getElement(h[1]).Surface.Radius - d) < 1e-6 and (not picked or h[1] in picked)]
            if not holes:
                raise CamFcError(f"零件上没有直径 {d:g} 的孔")
            op = Drilling.Create(f"Drill{len(made) + 1}")
            op.Base = [(jm, [h[1] for h in holes])]
            zmin = jm.Shape.BoundBox.ZMin
            if all(jm.Shape.getElement(h[1]).BoundBox.ZMin <= zmin + 1e-6 for h in holes):
                op.ExtraOffset = "Drill Tip"          # 通孔：多钻一个钻尖长，孔底整圈钻透（ADR-0106 Q2 色差图查出来的）
        else:
            raise CamFcError(f"工序类型 {k!r} 不认识：pocket、profile、drill")
        if "step_down_mm" in spec and hasattr(op, "StepDown"):
            op.setExpression("StepDown", None)      # FreeCAD 缺省按刀径的表达式，会盖掉我们给的每层切深
            op.StepDown = float(spec["step_down_mm"])
        made.append((spec, op))
    default = list(job.Tools.Group)
    tcs = {}
    for spec, op in made:
        n = int(spec["number"])
        if n not in tcs:
            tc = PathToolController.Create(f"T{n}", _bit(spec["tool"]), n)
            tc.SpindleSpeed = float(spec["rpm"])
            tc.HorizFeed = f"{float(spec['feed_mm_min'])} mm/min"
            tc.VertFeed = f"{float(spec.get('plunge_mm_min', spec['feed_mm_min']))} mm/min"
            job.Proxy.addToolController(tc)
            tcs[n] = tc
        op.ToolController = tcs[n]
    for tc in default:
        job.Tools.removeObject(tc)
        doc.removeObject(tc.Name)
    doc.recompute()
    return job, made, top


def _arc(p0, p1, c, cw, f):
    """XY 平面圆弧（可带 Z 螺旋）拆成直线段"""
    a0 = math.atan2(p0[1] - c[1], p0[0] - c[0])
    a1 = math.atan2(p1[1] - c[1], p1[0] - c[0])
    r = math.hypot(p0[0] - c[0], p0[1] - c[1])
    sweep = a1 - a0
    if cw and sweep >= -1e-12:
        sweep -= 2 * math.pi
    if not cw and sweep <= 1e-12:
        sweep += 2 * math.pi
    n = max(1, math.ceil(abs(math.degrees(sweep)) / ARC_DEG))
    out = []
    for i in range(1, n + 1):
        a = a0 + sweep * i / n
        z = p0[2] + (p1[2] - p0[2]) * i / n
        out.append({"t": "feed", "x": c[0] + r * math.cos(a), "y": c[1] + r * math.sin(a), "z": z, "f": f})
    out[-1].update({"x": p1[0], "y": p1[1], "z": p1[2]})
    return out


def commands_to_moves(cmds, top: float) -> list[dict]:
    """FreeCAD Path 命令（mm、mm/s）→ 中间格式动作（程序坐标 Z0 在零件顶面，进给 mm/min）"""
    pos = [0.0, 0.0, None]
    f = None
    out: list[dict] = []
    for c in cmds:
        name, p = c.Name, c.Parameters
        if name.startswith("(") or name in ("G90", "G98", "G99", "G80", "G17", "G21", "G40", "G49", "M6", "M3", "M5"):
            continue
        if "F" in p and p["F"] > 0:
            f = round(p["F"] * 60.0, 4)
        tgt = [p.get("X", pos[0]), p.get("Y", pos[1]), p["Z"] - top if "Z" in p else pos[2]]
        if name in ("G0", "G00"):
            if tgt[2] is not None:
                out.append({"t": "rapid", "x": tgt[0], "y": tgt[1], "z": tgt[2]})
            pos = tgt
        elif name in ("G1", "G01"):
            out.append({"t": "feed", "x": tgt[0], "y": tgt[1], "z": tgt[2], "f": f})
            pos = tgt
        elif name in ("G2", "G02", "G3", "G03"):
            c0 = (pos[0] + p.get("I", 0.0), pos[1] + p.get("J", 0.0))
            out += _arc(pos, tgt, c0, name in ("G2", "G02"), f)
            pos = tgt
        elif name in ("G81", "G82", "G83", "G73"):
            safe = pos[2]
            q = float(p.get("Q", 0.0)) if name in ("G83", "G73") else 0.0
            out.append({"t": "drill", "x": tgt[0], "y": tgt[1], "z": p["Z"] - top, "r": p["R"] - top, "q": q, "f": f,
                        "safe": safe})
            pos = [tgt[0], tgt[1], safe]
        else:
            raise CamFcError(f"FreeCAD 刀路里有还不认识的命令 {name}")
    return out


_RELOADED = False


def _reload_draft_for_gui() -> None:
    """Draft 的一些模块按导入时有没有界面决定带不带显示部分（`if App.GuiUp:`）。同一进程里先无界面导入过、后来界面才起来
    （例如测试），FreeCAD CAM 建作业时会报 Gui / ViewProviderClone 没定义：把这些模块按依赖顺序重新加载一次。
    真实使用时界面总是先起来，不会走到这里。"""
    global _RELOADED
    import FreeCAD

    if _RELOADED or not FreeCAD.GuiUp:
        return
    import importlib
    import sys

    names = [n for n, m in list(sys.modules.items())
             if n.startswith(("draftutils", "draftmake", "draftobjects", "draftviewproviders", "draftfunctions"))
             and getattr(m, "__file__", None) and "GuiUp" in Path(m.__file__).read_text(encoding="utf-8", errors="ignore")]
    if names:
        order = ("draftutils", "draftviewproviders", "draftobjects", "draftfunctions", "draftmake")
        for n in sorted(names, key=lambda n: next(i for i, p in enumerate(order) if n.startswith(p))):
            importlib.reload(sys.modules[n])
    _RELOADED = True


def program(shape, ops: list[dict], *, number: int = 6001, title: str = "2.5 轴铣（FreeCAD CAM 刀路）") -> dict:
    """零件（Part.Shape，Z 向上）+ 工序 → (中间格式程序, 毛坯)。毛坯取零件包围盒，顶面为程序 Z0"""
    import FreeCAD

    _reload_draft_for_gui()
    doc = FreeCAD.newDocument("WenQuestCamTmp")
    try:
        m = doc.addObject("Part::Feature", "Part")
        m.Shape = shape
        doc.recompute()
        fc_ops = [o for o in ops if o["type"] not in OWN]
        _job, made, top = build_job(doc, m, fc_ops) if fc_ops else (None, [], shape.BoundBox.ZMax)
        done = iter(made)
        prog_ops = []
        for spec0 in ops:
            if spec0["type"] in OWN:
                spec, mv, label = spec0, own_moves(spec0), spec0.get("title", spec0["type"])
            else:
                spec, op = next(done)
                mv, label = commands_to_moves(op.Path.Commands, top), op.Label
            if not mv:
                raise CamFcError(f"FreeCAD 的 {label} 没有出刀路")
            t = spec["tool"]
            prog_ops.append({"tool": sim_tool(t, int(spec["number"])),
                             "spindle": {"rpm": float(spec["rpm"])}, "moves": mv, "title": label,
                             "safe": max((x["z"] for x in mv if x["t"] == "rapid"), default=5.0)})
        bb = shape.BoundBox
        stock = {"box": [bb.XMin, bb.YMin, bb.XMax, bb.YMax], "top": 0.0, "height": bb.ZLength}
        return {"number": number, "title": title, "ops": prog_ops, "generator": "FreeCAD CAM"}, stock
    finally:
        FreeCAD.closeDocument(doc.Name)
