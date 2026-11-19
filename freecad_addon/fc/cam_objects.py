"""问渠CAM 的加工树（ADR-0106 Q1）：作业 → 装夹 → 工序，都是 FreeCAD 文档对象，存在 FCStd 里。

- 作业 `WqCamJob`（组）：零件（链接）、加工方式、机床、数控系统、材料行、刀具库、零件数据（车削：各段、倒角、槽、螺纹、内孔；铣削：毛坯）、
  夹具、工件零点高度、刀长；算完的结果（摘要、检查、正式程序）也存在这里。
- 装夹 `WqCamSetup`（组）：车削两个（右端第一次装夹、左端调头装夹），铣削一个。
- 工序 `WqCamOp`（Part::FeaturePython）：工序类型、刀具、切削参数、状态（草稿 / 已确认）、理由；刀路存在隐藏属性 Moves（JSON），
  Shape 是刀路线框（快移、切削各成一组边）。
- 刀路不在文档重算时自动生成（FreeCAD CAM 要另开临时文档，放在重算里不稳；打开文件也不该改动结果）：
  起草、面板里“应用”、右键“重算刀路”时调用 regenerate()；execute() 只按 Moves 画线框。
- 计算并检查：按模型树顺序把工序拼成程序（车削走 analysis.cam 的 turn + ops，铣削走 program 模式），过切削仿真、整机仿真、后处理与回读比对；
  还有草稿工序时照样仿真，但不出正式程序。
"""

from __future__ import annotations

import json
import math

from assist.i18n import tr as T

GROUP = "问渠CAM"
STATUS = ["草稿", "已确认"]
TURN_KINDS = {"rough": "粗车外圆", "finish": "精车外圆", "groove": "切槽", "thread": "车螺纹", "drill": "钻孔", "bore": "镗孔",
              "face_groove": "端面槽", "part": "切断"}
MILL_KINDS = {"pocket": "铣型腔", "profile": "铣外轮廓", "drill": "钻孔"}
TURN_TOOL_N = {"rough": 1, "finish": 2, "groove": 3, "thread": 4, "drill": 5, "bore": 6, "part": 8, "face_groove": 9}


class CamObjError(ValueError):
    pass


def _add(obj, typ, name, doc, value=None, hidden=False):
    if not hasattr(obj, name):
        obj.addProperty(typ, name, GROUP, doc)
        if value is not None:
            setattr(obj, name, value)
        if hidden:
            obj.setEditorMode(name, 2)


def _js(obj, name, default):
    try:
        return json.loads(getattr(obj, name) or "null") or default
    except ValueError:
        return default


# ---------------------------------------------------------------- 对象
class JobProxy:
    Type = "WqCamJob"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        _add(obj, "App::PropertyLink", "Model", "要加工的零件")
        _add(obj, "App::PropertyEnumeration", "Kind", "加工方式：turn 车削 / mill 铣削")
        if not obj.getEnumerationsOfProperty("Kind"):
            obj.Kind = ["turn", "mill"]
        for n, d in (("Machine", "机床 id"), ("Post", "数控系统（后处理）"), ("Kienzle", "工件材料（Kienzle 表的行）"),
                     ("ToolLibrary", "刀具库文件（空 = 示例刀具库）"), ("Item", "零件名")):
            _add(obj, "App::PropertyString", n, d)
        _add(obj, "App::PropertyString", "PartData", "零件数据（JSON）", hidden=True)
        _add(obj, "App::PropertyString", "Fixture", "夹具：车 = 卡爪夹持长度, 外径；铣 = 平口钳夹持高度", "")
        _add(obj, "App::PropertyFloat", "WorkOffsetZ", "铣：工件顶面离工作台 mm", 40.0)
        _add(obj, "App::PropertyString", "ToolLengths", "铣刀刀长 JSON（刀具 id → mm）", "{}")
        _add(obj, "App::PropertyString", "Result", "计算结果摘要（JSON）", hidden=True)
        _add(obj, "App::PropertyString", "Programs", "正式程序（JSON：文件名 → 文本）", hidden=True)
        _add(obj, "App::PropertyString", "Replay", "回放数据（JSON：每个程序的仿真程序、毛坯、刀具、带行号的检查）", hidden=True)
        _add(obj, "App::PropertyBool", "Cycles", "车削正式程序用固定循环（G71 / G70 / G76；FANUC、广数）", False)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class SetupProxy:
    Type = "WqCamSetup"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        _add(obj, "App::PropertyString", "Side", "车：right 第一次装夹 / left 调头；铣：1、2…")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class OpProxy:
    Type = "WqCamOp"

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        _add(obj, "App::PropertyString", "OpKind", "工序类型：车 rough / finish / groove / thread / drill / bore；铣 pocket / profile / drill")
        _add(obj, "App::PropertyInteger", "FeatureIndex", "第几个槽 / 螺纹（零件数据里的序号）", -1)
        _add(obj, "App::PropertyString", "ToolId", "刀具库里的刀具 id")
        _add(obj, "App::PropertyInteger", "ToolNumber", "刀号 T", 1)
        _add(obj, "App::PropertyFloat", "Vc", "切削速度 vc m/min")
        _add(obj, "App::PropertyFloat", "Feed", "进给：车 f mm/r；铣 fz mm/齿")
        _add(obj, "App::PropertyFloat", "Ap", "切深 ap mm（0 = 不适用）")
        _add(obj, "App::PropertyFloat", "StepOver", "铣型腔行距（占刀径的比例）")
        _add(obj, "App::PropertyLinkSubList", "Geometry", "点选的面（铣：型腔底面、孔；空 = 自动找）")
        _add(obj, "App::PropertyEnumeration", "Status", "草稿 / 已确认")
        if not obj.getEnumerationsOfProperty("Status"):
            obj.Status = STATUS
        _add(obj, "App::PropertyString", "Reason", "起草理由")
        _add(obj, "App::PropertyString", "Check", "参数核对结论")
        # 余量与分层、高度与进退刀（ADR-0106 Q3a；0 = 用缺省值）
        _add(obj, "App::PropertyFloat", "AllowRadial", "粗加工留的径向余量 mm（0 = 缺省：车 0.5、镗 0.3）")
        _add(obj, "App::PropertyFloat", "AllowAxial", "粗车留的轴向余量 mm（0 = 缺省 0.1）")
        _add(obj, "App::PropertyFloat", "Clearance", "安全距离 mm：快移到离工件这么远再切（0 = 缺省 2）")
        _add(obj, "App::PropertyFloat", "Retract", "退刀量 mm：每层切完斜着退开（0 = 缺省 0.5）")
        _add(obj, "App::PropertyString", "Moves", "刀路（JSON，中间格式）", hidden=True)
        _add(obj, "App::PropertyString", "Spindle", "主轴（JSON：rpm 或 css）", hidden=True)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        obj.Shape = path_shape(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None


class _VP:
    icon = ""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def getIcon(self):
        from pathlib import Path

        p = Path(__file__).resolve().parents[1] / "gui" / "icons" / self.icon
        return str(p) if p.is_file() else ""

    def claimChildren(self):
        return list(getattr(self.Object, "Group", []) or [])

    def doubleClicked(self, vobj):
        from freecad_addon.gui import cam_tree_panels

        cam_tree_panels.edit(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


class JobVP(_VP):
    icon = "wq-cam-job.svg"


class SetupVP(_VP):
    icon = "wq-cam-setup.svg"


class OpVP(_VP):
    icon = "wq-cam-op.svg"

    def claimChildren(self):
        return []

    def getIcon(self):
        draft = getattr(self.Object, "Status", "") == "草稿"
        self.icon = "wq-cam-op-draft.svg" if draft else "wq-cam-op.svg"
        return super().getIcon()


def is_job(o) -> bool:
    return getattr(getattr(o, "Proxy", None), "Type", "") == JobProxy.Type


def is_setup(o) -> bool:
    return getattr(getattr(o, "Proxy", None), "Type", "") == SetupProxy.Type


def is_op(o) -> bool:
    return getattr(getattr(o, "Proxy", None), "Type", "") == OpProxy.Type


def job_of(o):
    for p in o.InList:
        if is_job(p):
            return p
        if is_setup(p):
            return job_of(p)
    return None


def setup_of(op):
    return next((p for p in op.InList if is_setup(p)), None)


def setups(job):
    return [o for o in job.Group if is_setup(o)]


def ops(setup):
    return [o for o in setup.Group if is_op(o)]


# ---------------------------------------------------------------- 新建
def _attach_vp(obj, vp_cls):
    if obj.ViewObject is not None:
        vp_cls(obj.ViewObject)


def new_job(doc, model, kind: str, *, machine: str | None = None, post: str = "fanuc", kienzle: str = "C45E",
            tool_library: str = "", threads: str = ""):
    """选中的零件 → 作业（车：读回转体轮廓；铣：零件包围盒当毛坯）+ 装夹"""
    from freecad_addon.fc import cam_doc

    job = doc.addObject("App::DocumentObjectGroupPython", "WqCamJob")
    JobProxy(job)
    _attach_vp(job, JobVP)
    job.Label = T("问渠CAM 作业：{}").format(model.Label)       # 名字按界面语言起（存进文档后就是用户数据）
    job.Model = model
    job.Kind = kind
    job.Machine = machine or ("EX-LATHE" if kind == "turn" else "EX-VMC")
    job.Post, job.Kienzle, job.ToolLibrary, job.Item = post, kienzle, tool_library, model.Label
    shape = model.Shape
    if kind == "turn":
        ft = cam_doc.turn_features(shape)
        data = {"segments": ft["segments"], "chamfer_mm": ft["chamfer_mm"], "grooves": ft["grooves"],
                "bore": ft["bore"], "threads": _threads(threads), "z_right": ft["z_right"]}
        for key in ("bore_profile", "profile", "face_grooves"):
            if ft.get(key):
                data[key] = ft[key]
        job.Fixture = "15, 80"
        names = (("right", "右端（第一次装夹）"), ("left", "左端（调头装夹）"))
    else:
        bb = shape.BoundBox
        data = {"stock": {"box": [bb.XMin, bb.YMin, bb.XMax, bb.YMax], "top": 0.0, "height": bb.ZLength}, "z_top": bb.ZMax}
        job.Fixture = "10"
        names = (("1", "装夹 1"),)
    job.PartData = json.dumps(data, ensure_ascii=False)
    for side, label in names:
        s = doc.addObject("App::DocumentObjectGroupPython", "WqCamSetup")
        SetupProxy(s)
        _attach_vp(s, SetupVP)
        s.Side, s.Label = side, T(label)
        job.addObject(s)
    doc.recompute()
    return job


def thread_text(t: dict) -> str:
    from assist import i18n

    zh = i18n.lang() == "zh"
    extra = ([("内" if zh else "in")] if t.get("internal") else []) + ([f"1:{1 / t['taper']:g}"] if t.get("taper") else []) + \
        ([f"{t['starts']} " + ("头" if zh else "starts")] if int(t.get("starts") or 1) > 1 else []) + \
        ([t["form"].upper()] if t.get("form") in ("r", "npt") else [])
    return ", ".join([f"{t['z_start']:g}", f"{t['z_end']:g}", f"{t['d']:g}", f"{t['pitch']:g}", *extra])


def parse_threads(text: str) -> list[dict]:
    """螺纹表：每行 Z 起, Z 止, 大径, 螺距，后面可选“内”（内螺纹）、“1:16”（锥度）、“2 头”（多头）、
    “R” / “NPT”（锥管螺纹牙型：ISO 7-1 55°、ASME B1.20.1；不写锥度时按 1:16）"""
    import re

    out = []
    for n, line in enumerate(text.replace("，", ",").splitlines(), 1):
        parts = [p.strip() for p in line.split(",") if p.strip()]
        if not parts:
            continue
        try:
            za, zb, d, pch = (float(x) for x in parts[:4])
        except ValueError as exc:
            raise CamObjError(f"螺纹第 {n} 行要先写 4 个数：Z 起, Z 止, 大径, 螺距") from exc
        t = {"z_start": za, "z_end": zb, "d": d, "pitch": pch}
        for p in parts[4:]:
            if p in ("内", "in", "internal"):
                t["internal"] = True
            elif re.fullmatch(r"1\s*:\s*[\d.]+", p):
                t["taper"] = 1.0 / float(p.split(":")[1])
            elif re.fullmatch(r"\d+\s*(头|starts?)", p):
                t["starts"] = int(re.match(r"\d+", p).group(0))
            elif p.lower() in ("r", "npt"):
                t["form"] = p.lower()
            else:
                raise CamObjError(f"螺纹第 {n} 行的“{p}”看不懂：可写 内、1:16、2 头、R、NPT")
        if t.get("form") and "taper" not in t:
            t["taper"] = 1.0 / 16
        out.append(t)
    return out


def _threads(text: str) -> list:
    return parse_threads(text)


def new_op(setup, kind: str, *, index: int = -1, tool_id: str = "", tool_n: int = 1, vc=0.0, feed=0.0, ap=0.0, stepover=0.0,
           reason: str = "", status: str = "草稿"):
    doc = setup.Document
    op = doc.addObject("Part::FeaturePython", "WqCamOp")
    OpProxy(op)
    _attach_vp(op, OpVP)
    op.OpKind, op.FeatureIndex, op.ToolId, op.ToolNumber = kind, int(index), tool_id, int(tool_n)
    op.Vc, op.Feed, op.Ap, op.StepOver = float(vc), float(feed or 0.0), float(ap or 0.0), float(stepover or 0.0)
    op.Reason, op.Status = reason, status
    job = job_of(setup) or next(p for p in setup.InList if is_job(p))
    names = TURN_KINDS if job.Kind == "turn" else MILL_KINDS
    op.Label = T(names.get(kind, kind)) + (f" {index + 1}" if index >= 0 and kind in FEATURE_KINDS else "")
    setup.addObject(op)
    return op


# ---------------------------------------------------------------- 车削：零件数据 → analysis.cam 的设置
def turn_setup(job) -> dict:
    d = _js(job, "PartData", {})
    s = {"mode": "turn", "machine": job.Machine, "item": job.Item, "segments": d["segments"], "chamfer_mm": d.get("chamfer_mm", 0.0),
         "cycles": bool(getattr(job, "Cycles", False))}
    if job.Kienzle:
        s["kienzle"] = job.Kienzle
    if d.get("grooves"):
        s["grooves"] = [dict(g) for g in d["grooves"]]
    if d.get("profile"):
        s["profile"] = d["profile"]
    if d.get("face_grooves"):
        s["face_grooves"] = [dict(g) for g in d["face_grooves"]]
    if d.get("parting"):
        s["parting"] = dict(d["parting"])
    if d.get("threads"):
        s["threads"] = [dict(t) for t in d["threads"]]
    if d.get("bore"):
        s["bore"] = {"segments": d["bore"]}
        if d.get("bore_profile"):
            s["bore"]["profile"] = d["bore_profile"]
        drill = _drill_d(job)
        if drill:
            s["bore"]["drill_d"] = drill
    return s


def _lib(job):
    from analysis.cam import tools as TL

    return TL.load(job.ToolLibrary) if job.ToolLibrary else TL.load()


def _drill_d(job):
    from analysis.cam import tools as TL

    lib = _lib(job)
    for s in setups(job):
        for op in ops(s):
            if op.OpKind == "drill" and op.ToolId:
                return float(TL.get(lib, op.ToolId)["diameter_mm"])
    return None


def _turn_cut(job, op) -> dict:
    from analysis.cam import tools as TL

    k = op.OpKind
    c = {"vc": op.Vc}
    if k != "thread":
        c["f"] = op.Feed
    if k in ("rough", "bore") and op.Ap > 0:
        c["ap"] = op.Ap
    if k == "bore":
        c["f_finish"] = op.Feed
    if k == "groove" and op.ToolId:
        w = (TL.get(_lib(job), op.ToolId).get("insert") or {}).get("width_mm")
        if w:
            c["tool_w"] = float(w)
    if k in ("rough", "finish", "bore") and op.ToolId:
        r = (TL.get(_lib(job), op.ToolId).get("insert") or {}).get("nose_radius_mm")
        if r is not None:
            c["nose_r"] = float(r)
    for prop, key in (("AllowRadial", "allow_r"), ("AllowAxial", "allow_z"), ("Clearance", "clear"), ("Retract", "retract")):
        v = float(getattr(op, prop, 0.0) or 0.0)
        if v > 0:
            c[key] = v
    return c


FEATURE_KINDS = ("groove", "thread", "face_groove")      # 带序号（零件数据里第几个）的工序


def _local_index(sc, kind, gi):
    lst, key = {"groove": (sc["grooves"], "gi"), "thread": (sc["threads"], "gi"),
                "face_groove": (sc.get("face_grooves") or [], "fi")}[kind]
    for i, x in enumerate(lst):
        if x.get(key) == gi:
            return i
    return None


def _turn_spec(job, op, side):
    k = op.OpKind
    spec = {"kind": k, "cut": _turn_cut(job, op)}
    if k in FEATURE_KINDS:
        spec["gi"] = op.FeatureIndex
    return spec


def regenerate_turn(op) -> None:
    from analysis import cam
    from analysis.cam import machines

    job = job_of(op)
    setup = turn_setup(job)
    tw = _turn_cut(job, op).get("tool_w")
    if op.OpKind == "groove" and tw:
        setup["grooves"][op.FeatureIndex]["tool_w"] = tw
    mach = machines.get(job.Machine)
    ctx = cam.turn_context(setup, mach)
    side = setup_of(op).Side
    sc = next((x for x in ctx["sides"] if x["side"] == side), None)
    if sc is None:
        raise CamObjError(f"{setup_of(op).Label} 没有要车的轮廓")
    spec = {"kind": op.OpKind}
    if op.OpKind in FEATURE_KINDS:
        i = _local_index(sc, op.OpKind, op.FeatureIndex)
        if i is None:
            raise CamObjError(f"{op.Label} 不在这次装夹里")
        spec["i"] = i
    c = cam._cut(_turn_cut(job, op), cam.turn_default_cut(setup, sc, spec))
    b = cam.turn_build_op(ctx, sc, spec, c)
    op.Moves = json.dumps(b["op"]["moves"])
    op.Spindle = json.dumps(b["op"]["spindle"])


# ---------------------------------------------------------------- 铣削
def _mill_spec(job, op):
    from analysis.cam import machines
    from analysis.cam import tools as TL

    tool = TL.get(_lib(job), op.ToolId)
    d = float(tool["diameter_mm"])
    rpm = min(1000.0 * op.Vc / (math.pi * d), float(machines.get(job.Machine)["max_rpm"]))
    faces = [sub for (_o, subs) in op.Geometry for sub in subs] if op.Geometry else []
    if op.OpKind == "drill":
        return {"type": "drill", "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "feed_mm_min": round(op.Feed * rpm, 1),
                "faces": faces}
    z = tool.get("flutes") or 4
    feed = op.Feed * z * rpm
    spec = {"type": op.OpKind, "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "feed_mm_min": round(feed, 1),
            "plunge_mm_min": round(feed / 3, 1), "step_down_mm": op.Ap or 5.0, "faces": faces}
    if op.OpKind == "pocket" and op.StepOver > 0:
        spec["step_over_pct"] = 100 * op.StepOver
    return spec


def regenerate_mill(op) -> None:
    from freecad_addon.fc import cam_fc

    job = job_of(op)
    prog, _stock = cam_fc.program(job.Model.Shape, [_mill_spec(job, op)])
    o = prog["ops"][0]
    op.Moves = json.dumps(o["moves"])
    op.Spindle = json.dumps(o["spindle"])


def regenerate(op) -> None:
    (regenerate_turn if job_of(op).Kind == "turn" else regenerate_mill)(op)
    op.recompute()


# ---------------------------------------------------------------- 刀路线框
def to_model(job, side, x, y, z):
    """程序坐标 → 零件模型坐标。铣：XY 不变，Z0 在零件顶面；车：(x 直径, z) → (半径, 0, z)，
    右端装夹 Z0 在零件右端面，调头装夹 Z0 在原来的左端面、Z 方向反过来。"""
    d = _js(job, "PartData", {})
    if job.Kind != "turn":
        return x, y, z + d.get("z_top", 0.0)
    zr = d.get("z_right", 0.0)
    if side == "left":
        total = float(d["profile"][-1][0]) if d.get("profile") else sum(float(L) for _, L in d.get("segments") or [])
        return x / 2, 0.0, (zr - total) - z
    return x / 2, 0.0, z + zr


def path_shape(op):
    import FreeCAD
    import Part

    mv = _js(op, "Moves", [])
    job = job_of(op)
    if not mv or job is None:
        return Part.Shape()
    s = setup_of(op)
    side = getattr(s, "Side", "") if s is not None else ""
    pos = None
    edges = []
    for m in mv:
        if m.get("t") not in ("rapid", "feed", "thread", "drill"):
            continue
        p = FreeCAD.Vector(*to_model(job, side, m["x"], m.get("y", 0.0), m["z"]))
        if m["t"] == "drill":
            top = FreeCAD.Vector(*to_model(job, side, m["x"], m.get("y", 0.0), m.get("safe", 5.0)))
            edges.append(Part.LineSegment(top, p).toShape())
            pos = top
            continue
        if pos is not None and (p - pos).Length > 1e-9:
            edges.append(Part.LineSegment(pos, p).toShape())
        pos = p
    return Part.Compound(edges) if edges else Part.Shape()


# ---------------------------------------------------------------- 起草
def draft(job, client=None, note: str = "") -> dict:
    """起草：在每个装夹下建草稿工序（已有的工序先删掉）。返回 cam_process 的草稿（工艺卡用）"""
    from assist import cam_edition
    from freecad_addon.core import cam_study as S

    if client is not None:
        cam_edition.gate(feature="ai")
    doc = job.Document
    for s in setups(job):
        for o in ops(s):
            doc.removeObject(o.Name)
    if job.Kind == "turn":
        part = turn_setup(job)
        if part.get("bore"):
            part["bore"] = {k: v for k, v in part["bore"].items() if k in ("segments", "profile")}
        d = S.draft(part, client=client, tool_library=job.ToolLibrary or None, note=note)
        from analysis import cam
        from analysis.cam import machines

        card = {c["id"]: c for c in d["card"]}
        setup = d["setup"]
        ctx = cam.turn_context(setup, machines.get(job.Machine))
        for sc in ctx["sides"]:
            s = next(x for x in setups(job) if x.Side == sc["side"])
            for spec in cam.turn_op_specs(sc):
                k = spec["kind"]
                gi = (sc["grooves"][spec["i"]]["gi"] if k == "groove" else sc["threads"][spec["i"]]["gi"] if k == "thread"
                      else sc["face_grooves"][spec["i"]]["fi"] if k == "face_groove" else -1)
                cid = f"{k}{gi + 1}" if k in FEATURE_KINDS else k
                row = card[cid]
                p = row["params"]
                op = new_op(s, k, index=gi, tool_id=row["tool"], tool_n=TURN_TOOL_N[k], vc=p["vc"], feed=p.get("f", 0.0),
                            ap=p.get("ap", 0.0), reason=row.get("reason", ""))
                op.Check = "在样本范围内" if row["status"] == "pass" else "待确认"
                regenerate(op)
        doc.recompute()
        return d
    from analysis.cam import machines
    from freecad_addon.fc import cam_doc

    flags = {"pocket": True, "profile": False, "drill": True}
    plan = cam_doc.mill_plan(job.Model.Shape, _lib(job), S.iso_group(job.Kienzle), max_rpm=float(machines.get(job.Machine)["max_rpm"]),
                             **flags)
    s = setups(job)[0]
    for spec, row in zip(plan["ops"], plan["card"], strict=True):
        p = row["params"]
        kind = spec["type"] if spec["type"] != "drill" else "drill"
        op = new_op(s, kind, tool_id=row["tool"], tool_n=spec["number"], vc=p["vc"], feed=p.get("fz", p.get("f", 0.0)),
                    ap=p.get("ap", 0.0), stepover=p.get("stepover", 0.0))
        op.Label = T(row["title"])
        op.Check = "在样本范围内" if row["status"] == "pass" else "待确认"
        regenerate(op)
    doc.recompute()
    return {"setup": {"mode": "program", "machine": job.Machine, "item": job.Item, "kienzle": job.Kienzle}, "card": plan["card"],
            "notes": plan["notes"], "by": "规则（没有用 AI）", "explanation": "", "iso_group": S.iso_group(job.Kienzle)}


# ---------------------------------------------------------------- 核对、确认
def check_op(op) -> list[dict]:
    """工序参数按刀具样本范围核对：[{item, level, text}]"""
    from analysis.cam import tools as TL
    from freecad_addon.core import cam_study as S

    job = job_of(op)
    if not op.ToolId:
        return [{"item": "刀具", "level": "error", "text": "没有选刀"}]
    tool = TL.get(_lib(job), op.ToolId)
    iso = S.iso_group(job.Kienzle)
    kw = {"vc": op.Vc}
    turn = job.Kind == "turn"
    if op.OpKind != "thread":
        kw["f" if (turn or op.OpKind == "drill") else "fz"] = op.Feed
    if op.Ap > 0:
        kw["ap"] = op.Ap
    return TL.check_cutting(tool, iso, **kw)


def confirm(op) -> None:
    from analysis.cam import tools as TL

    bad = [c for c in check_op(op) if c["level"] == "error"]
    if bad:
        raise CamObjError("；".join(c["text"] for c in bad) + "——改好才能确认")
    v = TL.verdict(check_op(op))
    op.Check = "在样本范围内" if v == "pass" else "待确认"
    op.Status = "已确认"


def add_op(setup, kind: str):
    """新建一道工序（草稿）：刀和参数按规则起草的同一套办法定（能用的刀里取、样本范围的中间值），加在本装夹最后。
    车削的切槽 / 车螺纹取本装夹里还没有工序的第一个槽 / 螺纹。"""
    from analysis.cam import machines
    from freecad_addon.core import cam_study as S

    job = job_of(setup) or next(p for p in setup.InList if is_job(p))
    if job.Kind == "turn":
        if kind not in TURN_KINDS:
            raise CamObjError(f"车削没有这种工序：{kind}")
        from analysis import cam

        part = turn_setup(job)
        if part.get("bore"):
            part["bore"] = {k: v for k, v in part["bore"].items() if k in ("segments", "profile")}
        d = S.draft(part, tool_library=job.ToolLibrary or None)
        ctx = cam.turn_context(d["setup"], machines.get(job.Machine))
        sc = next((x for x in ctx["sides"] if x["side"] == setup.Side), None)
        specs = [s for s in (cam.turn_op_specs(sc) if sc else []) if s["kind"] == kind]
        if not specs:
            raise CamObjError(f"{setup.Label} 上没有能{TURN_KINDS[kind]}的地方")
        used = {o.FeatureIndex for o in ops(setup) if o.OpKind == kind}
        gi = -1
        if kind in FEATURE_KINDS:
            lst, key = {"groove": (sc["grooves"], "gi"), "thread": (sc["threads"], "gi"),
                        "face_groove": (sc.get("face_grooves") or [], "fi")}[kind]
            free = [lst[s["i"]][key] for s in specs if lst[s["i"]][key] not in used]
            gi = free[0] if free else lst[specs[0]["i"]][key]
        row = {c["id"]: c for c in d["card"]}[f"{kind}{gi + 1}" if gi >= 0 else kind]
        p = row["params"]
        op = new_op(setup, kind, index=gi, tool_id=row["tool"], tool_n=TURN_TOOL_N[kind], vc=p["vc"], feed=p.get("f", 0.0),
                    ap=p.get("ap", 0.0), reason=row.get("reason", ""))
    else:
        if kind not in MILL_KINDS:
            raise CamObjError(f"铣削没有这种工序：{kind}")
        from freecad_addon.fc import cam_doc

        flags = {k: k == kind for k in MILL_KINDS}
        plan = cam_doc.mill_plan(job.Model.Shape, _lib(job), S.iso_group(job.Kienzle),
                                 max_rpm=float(machines.get(job.Machine)["max_rpm"]), **flags)
        if not plan["ops"]:
            raise CamObjError("；".join(plan["notes"]) or f"零件上没有能{MILL_KINDS[kind]}的几何")
        spec, row = plan["ops"][0], plan["card"][0]
        p = row["params"]
        op = new_op(setup, kind, tool_id=row["tool"], tool_n=spec["number"], vc=p["vc"], feed=p.get("fz", p.get("f", 0.0)),
                    ap=p.get("ap", 0.0), stepover=p.get("stepover", 0.0))
        op.Label = T(row["title"])
    op.Check = "待确认"
    regenerate(op)
    return op


def copy_op(op):
    """复制一道工序（草稿），放在原工序后面"""
    s = setup_of(op)
    c = new_op(s, op.OpKind, index=op.FeatureIndex, tool_id=op.ToolId, tool_n=op.ToolNumber, vc=op.Vc, feed=op.Feed, ap=op.Ap,
               stepover=op.StepOver, reason=op.Reason)
    c.Geometry = op.Geometry
    c.Label = op.Label + T("（副本）")
    c.Moves, c.Spindle, c.Check = op.Moves, op.Spindle, "待确认"
    g = list(s.Group)
    g.remove(c)
    g.insert(g.index(op) + 1, c)
    s.Group = g
    c.recompute()
    return c


def move(op, delta: int) -> None:
    """在本装夹里上移（-1）/ 下移（+1）"""
    s = setup_of(op)
    g = list(s.Group)
    i = g.index(op)
    j = max(0, min(len(g) - 1, i + delta))
    g.insert(j, g.pop(i))
    s.Group = g


# ---------------------------------------------------------------- 计算并检查
def _ms(job, tool_rows) -> dict:
    from freecad_addon.core import cam_study as S

    ms = {"tools": {}}
    if job.ToolLibrary:
        ms["tool_library"] = job.ToolLibrary
    lengths = _js(job, "ToolLengths", {})
    for n, tid in tool_rows:
        e = {"tool": tid}
        if tid in lengths:
            e["length_mm"] = float(lengths[tid])
        ms["tools"][str(n)] = e
    nums = [float(x) for x in (job.Fixture or "").replace("，", ",").split(",") if x.strip()]
    if job.Kind == "turn" and len(nums) == 2:
        ms["chuck"] = {"jaw_len": nums[0], "jaw_d": nums[1]}    # 每次装夹的夹持长度在计算时按没车的部分取
    if job.Kind == "mill":
        ms["work_offset_mm"] = [0.0, 0.0, float(job.WorkOffsetZ)]
        if nums:
            ms["fixtures"] = S.vise_jaws(_js(job, "PartData", {})["stock"], nums[0])
    return ms


def build_setup(job) -> dict:
    """加工树 → analysis.cam.run 的设置（工序按树里的顺序与参数）"""
    all_ops = [(s, o) for s in setups(job) for o in ops(s)]
    if not all_ops:
        raise CamObjError("作业里还没有工序：先起草或新建工序")
    tool_rows = sorted({(o.ToolNumber, o.ToolId) for _s, o in all_ops if o.ToolId})
    if job.Kind == "turn":
        setup = turn_setup(job)
        setup["ops"] = {s.Side: [_turn_spec(job, o, s.Side) for o in ops(s)] for s in setups(job)}
        for g in setup.get("grooves") or []:
            gop = next((o for _s, o in all_ops if o.OpKind == "groove" and o.FeatureIndex == setup["grooves"].index(g)), None)
            if gop is not None and _turn_cut(job, gop).get("tool_w"):
                g["tool_w"] = _turn_cut(job, gop)["tool_w"]
        # 每次装夹里的槽 / 螺纹在 _turn 里用本装夹的序号：按 gi 换
        from analysis import cam
        from analysis.cam import machines

        ctx = cam.turn_context(setup, machines.get(job.Machine))
        for sc in ctx["sides"]:
            for spec in setup["ops"].get(sc["side"], []):
                if spec["kind"] in FEATURE_KINDS:
                    spec["i"] = _local_index(sc, spec["kind"], spec.pop("gi"))
    else:
        d = _js(job, "PartData", {})
        prog_ops = []
        for _s, o in all_ops:
            mv = _js(o, "Moves", [])
            if not mv:
                raise CamObjError(f"{o.Label} 还没有刀路：右键“重算刀路”")
            from analysis.cam import tools as TL

            t = TL.get(_lib(job), o.ToolId)
            from freecad_addon.core import cam_study as _S

            cc = TL.cutting_for(t, _S.iso_group(job.Kienzle)) or {}          # 刀具样本的 ap、ae 上限：仿真逐段核对（ADR-0106 Q3b）
            prog_ops.append({"tool": {"n": o.ToolNumber, "name": t.get("name", t["id"]), "d": float(t["diameter_mm"]),
                                      "kind": "drill" if t["kind"] == "drill" else "endmill",
                                      **({"ap_max": cc["ap_max_mm"]} if "ap_max_mm" in cc else {}),
                                      **({"ae_max": cc["ae_max_mm"]} if "ae_max_mm" in cc else {})},
                             "spindle": _js(o, "Spindle", {}), "moves": mv, "title": o.Label,
                             "safe": max((x["z"] for x in mv if x.get("t") == "rapid"), default=5.0)})
        setup = {"mode": "program", "machine": job.Machine, "item": job.Item, "stock": d["stock"],
                 "program": {"number": 6001, "title": f"{job.Item} 铣削", "ops": prog_ops, "generator": "FreeCAD CAM"}}
        if job.Kienzle:
            setup["kienzle"] = job.Kienzle
    setup["machine_sim"] = _ms(job, tool_rows)
    return setup


def calculate(job) -> dict:
    """计算并检查。全部工序确认后才出正式程序（给数控系统）；还有草稿时只仿真"""
    from freecad_addon.core import cam_study as S

    setup = build_setup(job)
    drafts = [o.Label for s in setups(job) for o in ops(s) if o.Status != "已确认"]
    if not drafts:
        setup["post"] = job.Post
    r = S.run(setup)
    if drafts:
        for p in r["data"]["programs"]:
            p["checks"].append({"line": None, "level": "warn",
                                "text": f"还有 {len(drafts)} 道工序是草稿（{'、'.join(drafts[:4])}{'…' if len(drafts) > 4 else ''}），确认后才出正式程序"})
    progs = {f"O{int(p.get('number', 1)):04d}_{p['release']['controller']}.nc": p["release"]["text"]
             for p in r["data"]["programs"] if p.get("release")}
    job.Programs = json.dumps(progs, ensure_ascii=False)
    if job.Kind == "mill" and job.Model is not None:   # 三维比对：加工完的毛坯与零件模型（ADR-0106 Q2 第 6 步）
        _mill_deviation_checks(job, r, progs)
        job.Programs = json.dumps(progs, ensure_ascii=False)
    if not hasattr(job, "Replay"):                # Q1 存的文档没有这个属性
        job.Proxy.setup(job)
    job.Replay = json.dumps([{"title": p.get("title", ""), "side": p.get("side", ""), "gcode": p.get("gcode"),
                              "replay_in": p.get("replay_in"),
                              "checks": [c for c in p["checks"] if c.get("line") is not None]}
                             for p in r["data"]["programs"] if p.get("replay_in")], ensure_ascii=False)
    job.Result = json.dumps({"summary": S.summary(r), "checks": S.checks(r),
                             "fingerprints": [(p.get("machine_sim") or {}).get("fingerprint") for p in r["data"]["programs"]]},
                            ensure_ascii=False)
    return r


def _mill_deviation_checks(job, r, progs):
    """铣削程序按回放的 dexel 切一遍，与零件模型比：过切 → 错误、不出正式程序；多留 → 提示"""
    from analysis.cam import machines
    from analysis.cam import replay as R
    from freecad_addon.fc import cam_deviation as CD

    mach = machines.get(job.Machine)
    for p in r["data"]["programs"]:
        if not p.get("replay_in"):
            continue
        rp = R.Replay(p.get("gcode"), mach, p["replay_in"])
        extra = CD.checks_for(job, rp, p.get("side", ""))
        p["checks"] += extra
        if any(c["level"] == "error" for c in extra) and p.get("release"):
            progs.pop(f"O{int(p.get('number', 1)):04d}_{p['release']['controller']}.nc", None)
            p["release"] = None
            p["checks"].append({"line": None, "level": "error", "text": "三维比对有过切，程序没有输出（改好再算）"})


def card_doc(job) -> dict:
    """工艺卡要的草稿结构（assist.cam_card）：工序表按加工树现在的工序、刀具和参数"""
    from freecad_addon.core import cam_study as S

    rows = []
    n = 0
    for s in setups(job):
        for o in ops(s):
            n += 1
            p = {"vc": o.Vc}
            if o.OpKind != "thread":
                p["f" if (job.Kind == "turn" or o.OpKind == "drill") else "fz"] = o.Feed
            if o.Ap > 0:
                p["ap"] = o.Ap
            if job.Kind == "turn":
                rid = f"{o.OpKind}{o.FeatureIndex + 1}" if o.OpKind in FEATURE_KINDS else o.OpKind
            else:
                rid = f"f{o.ToolNumber}"
            rows.append({"id": rid, "title": o.Label, "tool": o.ToolId, "tool_name": "", "params": p,
                         "status": "pass" if o.Check == "在样本范围内" else "unknown", "reason": o.Reason})
    return {"setup": build_setup(job), "card": rows, "notes": [], "by": "加工树（人已确认）", "explanation": "",
            "iso_group": S.iso_group(job.Kienzle)}
