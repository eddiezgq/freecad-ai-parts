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
          "drill": "drill.fcstd", "chamfer_mill": "chamfer.fcstd", "face_mill": "endmill.fcstd"}
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
    if tool["kind"] == "chamfer_mill":           # 倒角刀：FreeCAD 的锥角叫 CuttingEdgeAngle、刀尖平头叫 TipDiameter（缺省 60° / Ø5，不能用缺省）
        bit.CuttingEdgeAngle = float(tool["tip_angle_deg"])
        bit.TipDiameter = float(tool.get("tip_diameter_mm", 0.0))
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


OWN = ("csink", "tap", "cbore", "chamfer", "thread_mill")   # 问渠自己出刀路的工序（FreeCAD CAM 1.0 没有攻丝；锪孔口、沉孔按孔特征直接算；
                                             # 倒角 FreeCAD Deburr 遇到型腔口的倒角算不出来，改为按倒角面自己算）
CHAMFER_EXTRA = 0.5      # 倒角刀刀尖比倒角底边再低 0.5 mm，不用刀尖切


def sim_tool(t: dict, n: int) -> dict:
    """cam-tool/1 刀具 → 中间格式程序里的刀（仿真用的种类、直径；丝锥的螺距，倒角刀的锥角、刀尖直径）"""
    kind = {"drill": "drill", "tap": "tap", "chamfer_mill": "chamfer", "thread_mill": "thread_mill"}.get(t["kind"], "endmill")
    out = {"n": n, "name": t.get("name", t["id"]), "d": float(t["diameter_mm"]), "kind": kind}
    if kind == "tap":
        out["pitch"] = float(t["pitch_mm"])
    if kind == "chamfer":
        out["angle"] = float(t["tip_angle_deg"])
        out["tip_d"] = float(t.get("tip_diameter_mm", 0.0))
    return out


def chamfer_moves(shape, faces, tool: dict, f: float, f_plunge: float, safe: float = 5.0, seg: float = 0.05) -> list[dict]:
    """倒角（ADR-0106 Q3b）：倒角面的下边（与竖直壁相交的那圈）往空的一侧偏 (刀尖半径 + 多下的深度·tan(半锥角))，
    刀尖低于倒角底边 CHAMFER_EXTRA，锥面正好贴着倒角面。外轮廓往外偏，型腔口往里偏（按下边内侧是不是实体判断）。
    圆弧按弦高 seg 拆成直线。程序坐标 Z0 在零件顶面。"""
    import FreeCAD
    import Part

    top = shape.BoundBox.ZMax
    half = math.radians(float(tool["tip_angle_deg"]) / 2)
    r0 = float(tool.get("tip_diameter_mm", 0.0)) / 2
    fs = [shape.getElement(n) for n in faces]
    zb = min(f_.BoundBox.ZMin for f_ in fs)
    if float(tool["diameter_mm"]) / 2 < r0 + (CHAMFER_EXTRA + top - zb) * math.tan(half) - 1e-9:
        raise CamFcError(f"倒角刀 Ø{tool['diameter_mm']:g} 不够大：锥面盖不住整个倒角")
    low = [e for f_ in fs for e in f_.Edges if abs(e.BoundBox.ZMin - zb) < 1e-6 and abs(e.BoundBox.ZMax - zb) < 1e-6]
    if not low:
        raise CamFcError("倒角：找不到倒角面的下边")
    off = r0 + CHAMFER_EXTRA * math.tan(half)
    mv = [{"t": "comment", "text": f"倒角：倒角刀 {tool['tip_angle_deg']:g}°，刀尖低于倒角底边 {CHAMFER_EXTRA:g}"}]
    for edges in Part.sortEdges(low):
        w = Part.Wire(edges)
        if not w.isClosed():
            raise CamFcError("倒角面的下边不是封闭的一圈（只倒了一部分边），还不支持")
        e0 = w.Edges[0]
        p = e0.valueAt((e0.FirstParameter + e0.LastParameter) / 2)
        t = e0.tangentAt((e0.FirstParameter + e0.LastParameter) / 2)
        n = FreeCAD.Vector(-t.y, t.x, 0).normalize()
        face = Part.Face(w)
        inward = n if face.isInside(p + n * 0.01, 1e-6, True) else -n        # 指向这圈里面
        solid_inside = shape.isInside(p + inward * 0.01 + FreeCAD.Vector(0, 0, -0.01), 1e-6, True)
        ow = w.makeOffset2D(off if solid_inside else -off, 0, False, False, False)
        pts = ow.discretize(Deflection=seg)
        z = zb - CHAMFER_EXTRA - top
        p0 = pts[0]
        mv += [{"t": "rapid", "x": p0.x, "y": p0.y, "z": safe}, {"t": "rapid", "x": p0.x, "y": p0.y, "z": z + 2.0},
               {"t": "feed", "x": p0.x, "y": p0.y, "z": z, "f": f_plunge}]
        mv += [{"t": "feed", "x": q.x, "y": q.y, "z": z, "f": f} for q in pts[1:]]
        mv += [{"t": "feed", "x": p0.x, "y": p0.y, "z": z, "f": f}, {"t": "rapid", "x": p0.x, "y": p0.y, "z": safe}]
    return mv


def own_moves(spec: dict, shape=None) -> list[dict]:
    """spec["holes"]：程序坐标（Z0 在零件顶面）。csink [(x, y, 孔口 z)]；tap [(x, y, 孔口 z, 攻到 z)]；cbore [(x, y, 孔口 z, 深)]；
    chamfer 按 spec["faces"]（要零件形体）"""
    from analysis.cam import paths as P

    t, k = spec["tool"], spec["type"]
    if k == "chamfer":
        return chamfer_moves(shape, spec["faces"], t, spec["feed_mm_min"], spec.get("plunge_mm_min", spec["feed_mm_min"]))
    if k == "csink":
        return P.mill_csink(spec["holes"], spec["d"], float(t["tip_angle_deg"]), spec["feed_mm_min"],
                            tip_d=float(t.get("tip_diameter_mm", 0.0)))
    if k == "tap":
        return P.mill_tap(spec["holes"], float(t["pitch_mm"]))
    if k == "thread_mill":
        teeth = float(t.get("flute_length_mm", 0.0)) if t.get("pitch_mm") else 0.0     # 多齿（写了螺距）按有齿长度；单齿走多圈
        return P.mill_thread(spec["holes"], spec["d"], spec["pitch"], float(t["diameter_mm"]), spec["feed_mm_min"], teeth_len=teeth)
    mv = []
    for x, y, ze, dp in spec["holes"]:
        mv += P.mill_cbore(x, y, spec["d"], dp, ze, float(t["diameter_mm"]), spec["step_down_mm"], spec["feed_mm_min"])
    return mv


def top_faces(shape, top: float) -> list[str]:
    """零件顶面（朝上、在最高处的平面）：面铣的几何"""
    out = []
    for i, f in enumerate(shape.Faces):
        if type(f.Surface).__name__ == "Plane" and f.BoundBox.ZMin > top - 1e-6 and f.normalAt(*f.ParameterRange[0::2]).z > 1 - 1e-9:
            out.append(f"Face{i + 1}")
    return out


def _apply_heights(op, spec: dict, stock_z: float) -> None:
    """余量与高度（ADR-0106 Q3b）：allow_side 侧壁余量（型腔往里让、外轮廓往外让、自适应 StockToLeave），
    allow_floor 底面余量（最终深度抬高），safe_h / clear_h 安全高度、快移高度（毛坯顶面以上）。没给的用 FreeCAD 缺省。"""
    side = float(spec.get("allow_side") or 0.0)
    if side > 0:
        if hasattr(op, "StockToLeave"):
            op.StockToLeave = side
        elif hasattr(op, "OffsetExtra"):
            op.OffsetExtra = side
        elif hasattr(op, "ExtraOffset"):
            op.ExtraOffset = side                 # PocketShape：正数是往里让（实测：−0.3 型腔反而大了 0.6）
    floor = float(spec.get("allow_floor") or 0.0)
    if floor > 0 and hasattr(op, "FinalDepth"):
        op.recompute()                           # 先算出缺省的最终深度，再抬高
        z = float(op.FinalDepth.Value) + floor
        op.setExpression("FinalDepth", None)
        op.FinalDepth = z
    for key, prop in (("safe_h", "SafeHeight"), ("clear_h", "ClearanceHeight")):
        if spec.get(key) and hasattr(op, prop):
            op.setExpression(prop, None)
            setattr(op, prop, stock_z + float(spec[key]))


def build_job(doc, model, ops: list[dict], stock_top: float = 0.0):
    """ops：[{"type": "face" | "pocket" | "profile" | "drill", "tool": cam-tool/1 刀具, "number": 刀号, "rpm", "feed_mm_min",
             "plunge_mm_min", "step_down_mm", "step_over_pct", "faces": 点选的面（可选：型腔底面、孔的圆柱面；不给时自动找）}]。
    返回 (作业, [(op 设置, FreeCAD 工序)])"""
    import Path.Tool.Controller as PathToolController
    from Path.Base import Drillable
    from Path.Main import Job as PathJob
    from Path.Op import Adaptive, Drilling, MillFace, PocketShape, Profile

    job = PathJob.Create("Job", [model])
    if stock_top > 0:                            # 毛坯顶面高出零件顶面 stock_top（面铣余量；ADR-0106 Q3b）
        job.Stock.ExtZpos = float(stock_top)
        doc.recompute()
    jm = job.Model.Group[0]
    top = jm.Shape.BoundBox.ZMax
    made = []
    for spec in ops:
        k = spec["type"]
        if k in ("pocket", "rest"):
            floors = list(spec.get("faces") or []) or pocket_floors(jm.Shape, top)
            if not floors:
                raise CamFcError("零件上没有找到型腔底面（朝上、低于顶面的平面）")
            op = PocketShape.Create(f"Pocket{len(made) + 1}")
            op.Base = [(jm, floors)]
            op.StepOver = round(float(spec.get("step_over_pct", 40)))
            op.OffsetPattern = "ZigZagOffset"      # 之字形清中间 + 最后贴壁一圈：直角转角铣到刀具够得着的地方（ADR-0106 Q2 色差图查出来的）
            if k == "rest":                        # 残料清角：只铣前面工序（同一个 FreeCAD 作业里排在前面的）留下的料（ADR-0106 Q3b）
                op.UseRestMachining = True
        elif k == "adaptive":                      # 自适应开粗（恒定切宽）：FreeCAD Adaptive，型腔底面内侧
            floors = list(spec.get("faces") or []) or pocket_floors(jm.Shape, top)
            if not floors:
                raise CamFcError("零件上没有找到型腔底面（朝上、低于顶面的平面）")
            op = Adaptive.Create(f"Adaptive{len(made) + 1}")
            op.Base = [(jm, floors)]
            op.Side = "Inside"
            op.StepOver = round(float(spec.get("step_over_pct", 20)))
            op.StockToLeave = float(spec.get("stock_to_leave", 0.0))
        elif k == "profile":
            op = Profile.Create(f"Profile{len(made) + 1}")
        elif k == "face":
            faces = top_faces(jm.Shape, top)
            if not faces or stock_top <= 0:
                raise CamFcError("面铣：毛坯顶面要高出零件顶面（作业的“面铣余量”大于 0）")
            op = MillFace.Create(f"Face{len(made) + 1}")
            op.Base = [(jm, faces)]
            op.BoundaryShape = "Stock"           # 整个毛坯顶面铣平
            op.ClearEdges = True
            op.StepOver = round(float(spec.get("step_over_pct", 70)))
            op.OffsetPattern = "ZigZagOffset"    # 之字形 + 最后沿边一圈：只走之字形时边上每两行之间留三角形的料（色差查出来的）
            op.ExtraOffset = float(spec["tool"]["diameter_mm"]) / 2   # 边界往外放一个刀具半径：刀心走到毛坯边上，四个角才铣得到
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
            raise CamFcError(f"工序类型 {k!r} 不认识：face、pocket、rest、adaptive、profile、drill")
        _apply_heights(op, spec, top + float(stock_top))
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
    for _spec, op in made:                       # 换了刀以后要重算（Deburr 不会自己重算，还用着缺省刀的锥角、刀尖和进给）
        op.touch()
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


def program(shape, ops: list[dict], *, number: int = 6001, title: str = "2.5 轴铣（FreeCAD CAM 刀路）", stock_top: float = 0.0) -> dict:
    """零件（Part.Shape，Z 向上）+ 工序 → (中间格式程序, 毛坯)。毛坯取零件包围盒，顶面为程序 Z0"""
    import FreeCAD

    _reload_draft_for_gui()
    doc = FreeCAD.newDocument("WenQuestCamTmp")
    try:
        m = doc.addObject("Part::Feature", "Part")
        m.Shape = shape
        doc.recompute()
        fc_ops = [o for o in ops if o["type"] not in OWN]
        _job, made, top = build_job(doc, m, fc_ops, stock_top) if fc_ops else (None, [], shape.BoundBox.ZMax)
        done = iter(made)
        prog_ops = []
        for spec0 in ops:
            if spec0["type"] in OWN:
                spec, mv, label = spec0, own_moves(spec0, m.Shape), spec0.get("title", spec0["type"])
            else:
                spec, op = next(done)
                mv, label = commands_to_moves(op.Path.Commands, top), op.Label
                if spec["type"] == "profile" and spec.get("lead", True):      # 外轮廓：圆弧切入切出（半径 = 刀具半径）
                    from analysis.cam import paths as P

                    mv = P.lead_arcs(mv, float(spec["tool"]["diameter_mm"]) / 2,
                                     safe=max((x["z"] for x in mv if x["t"] == "rapid"), default=5.0))
            if not mv:
                raise CamFcError(f"FreeCAD 的 {label} 没有出刀路")
            t = spec["tool"]
            extra = {"ae_set": float(spec.get("step_over_pct", 20)) / 100 * float(t["diameter_mm"])} if spec["type"] == "adaptive" else {}
            st = sim_tool(t, int(spec["number"]))
            if st["kind"] == "thread_mill":           # 齿根直径 = 刀径 − 2 × 内螺纹牙深（ISO 68-1：0.5413P）
                st["core_d"] = float(t["diameter_mm"]) - 1.0825 * float(spec["pitch"])
            prog_ops.append({**extra, "tool": st,
                             "spindle": {"rpm": float(spec["rpm"])}, "moves": mv, "title": label,
                             "safe": max((x["z"] for x in mv if x["t"] == "rapid"), default=5.0)})
        bb = shape.BoundBox
        stock = {"box": [bb.XMin, bb.YMin, bb.XMax, bb.YMax], "top": float(stock_top), "height": bb.ZLength + float(stock_top)}
        return {"number": number, "title": title, "ops": prog_ops, "generator": "FreeCAD CAM"}, stock
    finally:
        FreeCAD.closeDocument(doc.Name)
