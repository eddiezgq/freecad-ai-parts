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

import itertools
import json
import math

import numpy as np

from assist.i18n import tr as T

GROUP = "问渠CAM"
STATUS = ["草稿", "已确认"]
TURN_KINDS = {"rough": "粗车外圆", "finish": "精车外圆", "groove": "切槽", "thread": "车螺纹", "drill": "钻孔", "bore": "镗孔",
              "face_groove": "端面槽", "part": "切断"}
MILL_KINDS = {"face": "面铣", "pocket": "铣型腔", "adaptive": "自适应开粗", "rest": "残料清角", "profile": "铣外轮廓", "drill": "钻孔", "cbore": "铣沉孔", "csink": "锪孔口", "tap": "攻丝",
              "chamfer": "倒角", "thread_mill": "铣螺纹", "helix": "螺旋铣孔", "surface": "曲面平行精铣", "waterline": "曲面等高精铣"}
HOLE_KINDS = ("cbore", "csink", "tap", "thread_mill", "helix")
MILL_ALLOW_KINDS = ("pocket", "adaptive", "rest", "profile")             # 铣：可留侧壁 / 底面余量
MILL_FC_KINDS = ("face", "pocket", "adaptive", "rest", "profile", "drill", "surface", "waterline")  # 铣：FreeCAD CAM 出刀路的（安全高度、快移高度可改）     # 按孔特征出刀路（ADR-0106 Q3b）：孔表存在工序的 HoleData 里
TURN_TOOL_N = {"rough": 1, "finish": 2, "groove": 3, "thread": 4, "drill": 5, "bore": 6, "part": 8, "face_groove": 9}
LIVE_KINDS = {"live_face": "端面铣（动力刀）", "live_keyway": "圆柱面键槽（动力刀）", "live_flat": "圆柱面平底槽（Y 轴）"}     # 车铣中心（ADR-0106 C2b 界面）
FIVE_KINDS = {"swarf5": "五轴侧刃铣（直纹面）", "surface5": "五轴曲面精加工（球头刀）", "curve5": "五轴沿曲线"}           # 五轴联动（ADR-0106 C3d）


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
        _add(obj, "App::PropertyFloat", "StockTop", "铣：面铣余量——毛坯顶面高出零件顶面 mm（0 = 毛坯顶面就是零件顶面，不面铣）", 0.0)
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
        _add(obj, "App::PropertyString", "Frame", "3+2 倾斜面（JSON：工件坐标的原点、X、Z 方向；空 = 不倾斜，ADR-0106 C2a）", "", hidden=True)

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
        _add(obj, "App::PropertyFloat", "AllowRadial", "粗加工留的径向余量 mm（0 = 缺省：车 0.5、镗 0.3；铣：侧壁余量，0 = 不留）")
        _add(obj, "App::PropertyFloat", "AllowAxial", "粗车留的轴向余量 mm（0 = 缺省 0.1）")
        _add(obj, "App::PropertyFloat", "Clearance", "安全距离 mm：快移到离工件这么远再切（0 = 缺省 2）")
        _add(obj, "App::PropertyFloat", "Retract", "退刀量 mm：每层切完斜着退开（0 = 缺省 0.5）")
        _add(obj, "App::PropertyString", "HoleData", "铣：这道孔工序加工哪些孔（JSON：直径、孔表，程序坐标）", "{}", hidden=True)
        _add(obj, "App::PropertyString", "Moves", "刀路（JSON，中间格式）", hidden=True)
        _add(obj, "App::PropertyString", "Spindle", "主轴（JSON：rpm 或 css）", hidden=True)
        _add(obj, "App::PropertyString", "Frame", "倾斜面工序的工作平面（JSON，刀路是平面坐标；重算刀路时按装夹的倾斜面定，平面 Z0 在零件沿法向的最高处）",
             "", hidden=True)
        # 五轴联动（ADR-0106 C3d）：只对 swarf5 / surface5 / curve5 有用
        _add(obj, "App::PropertyFloat", "Lead", "五轴：前倾角（度，刀轴往走刀方向或固定方向倒）")
        _add(obj, "App::PropertyFloat", "Tilt", "五轴：侧倾角（度，往走刀方向左侧倒）")
        _add(obj, "App::PropertyString", "LeadDir", "五轴：固定前倾方向（空 = 跟走刀方向；x / y = 往工件 +X / +Y 倒，之字形用）")
        _add(obj, "App::PropertyFloat", "Below", "五轴侧刃铣：刀尖比直纹面底边再往下伸（mm）")
        _add(obj, "App::PropertyFloat", "Depth5", "五轴沿曲线：往面里进给的深度（mm）")
        _add(obj, "App::PropertyFloat", "PoleMin", "五轴：刀轴离回转轴至少几度（让开奇异点；0 = 不让）")
        _add(obj, "App::PropertyBool", "AvoidCollision", "五轴：刀杆、刀柄碰零件时自动加大倾角")

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
        from freecad_addon.fc import cam_fc

        bb = cam_fc.exact_bbox(shape)
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
    names = {**TURN_KINDS, **LIVE_KINDS} if job.Kind == "turn" else {**MILL_KINDS, **FIVE_KINDS}
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
    if op.OpKind in HOLE_KINDS:
        hd = _js(op, "HoleData", {})
        if not hd.get("holes"):
            raise CamObjError(f"{op.Label} 没有要加工的孔")
        spec = {"type": op.OpKind, "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "d": float(hd["d"]),
                "holes": [tuple(h) for h in hd["holes"]], "title": op.Label, **({"pitch": hd["pitch"]} if "pitch" in hd else {})}
        if op.OpKind == "thread_mill":
            rc = (float(hd["d"]) - d) / 2
            spec["feed_mm_min"] = round(op.Feed * (tool.get("flutes") or 3) * rpm * rc / (float(hd["d"]) / 2), 1)
        if op.OpKind == "csink":
            spec["feed_mm_min"] = round(op.Feed * rpm, 1)
        elif op.OpKind in ("cbore", "helix"):
            spec["feed_mm_min"] = round(op.Feed * (tool.get("flutes") or 4) * rpm, 1)
            spec["step_down_mm"] = op.Ap or 2.0
        return spec
    if op.OpKind == "chamfer":
        hd = _js(op, "HoleData", {})
        z = tool.get("flutes") or 2
        return {"type": "chamfer", "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "feed_mm_min": round(op.Feed * z * rpm, 1),
                "plunge_mm_min": round(op.Feed * z * rpm / 3, 1), "faces": faces or hd.get("faces") or [], "width": float(hd.get("width", 0.0))}
    if op.OpKind == "drill":
        return {"type": "drill", "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "feed_mm_min": round(op.Feed * rpm, 1),
                "faces": faces, **_mill_heights(op)}
    z = tool.get("flutes") or 4
    feed = op.Feed * z * rpm
    spec = {"type": op.OpKind, "tool": tool, "number": op.ToolNumber, "rpm": round(rpm), "feed_mm_min": round(feed, 1),
            "plunge_mm_min": round(feed / 3, 1), "step_down_mm": op.Ap or 5.0, "faces": faces}
    if op.OpKind in ("pocket", "adaptive", "rest") and op.StepOver > 0:
        spec["step_over_pct"] = 100 * op.StepOver
    if op.OpKind in ("surface", "waterline"):      # 曲面：行距 / 等高步距按目标残留高度（工序的 StepOver 存行距占刀径的比例）
        from freecad_addon.fc import cam_doc

        s_ = op.StepOver * d if op.StepOver > 0 else cam_doc.scallop_step(d / 2)
        spec["step_over_pct"] = 100 * s_ / d
        spec["step_down_mm"] = op.Ap or round(s_ * math.sqrt(0.5), 3)
    return {**spec, **_mill_heights(op)}


def _mill_heights(op) -> dict:
    """铣工序的余量与高度（ADR-0106 Q3b）：0 = 不写（FreeCAD 缺省、不留余量）"""
    out = {}
    for prop, key, kinds in (("AllowRadial", "allow_side", MILL_ALLOW_KINDS), ("AllowAxial", "allow_floor", MILL_ALLOW_KINDS),
                             ("Clearance", "safe_h", MILL_FC_KINDS), ("Retract", "clear_h", MILL_FC_KINDS)):
        v = float(getattr(op, prop, 0.0) or 0.0)
        if v > 0 and op.OpKind in kinds:
            out[key] = v
    return out


def regenerate_mill(op) -> None:
    from freecad_addon.fc import cam_fc

    job = job_of(op)
    specs = [_mill_spec(job, op)]
    if op.OpKind == "rest":                       # 残料清角要知道前面工序铣到哪里：把本装夹里排在前面的去料工序一起算
        before = ops(setup_of(op))
        before = before[:before.index(op)]
        specs = [_mill_spec(job, o) for o in before if o.OpKind in ("face", "pocket", "adaptive", "rest", "profile")] + specs
    fr = _js(setup_of(op), "Frame", None) if setup_of(op) is not None else None
    if fr:                                        # 倾斜面（ADR-0106 C2a）：零件转到平面坐标里算刀路，平面 Z0 取零件沿法向的最高处
        shape = plane_shape(job, fr)
        prog, _stock = cam_fc.program(shape, specs, stock_top=plane_stock_top(job, fr), stock_box=plane_stock(job, fr))
        top = cam_fc.exact_bbox(shape).ZMax
        from analysis.cam import tilt

        origin = tilt.to_work(fr, [0.0, 0.0, top])
        op.Frame = json.dumps({"origin": [float(v) for v in origin], "x": fr.get("x"), "z": fr["z"]})
    else:
        prog, _stock = cam_fc.program(job.Model.Shape, specs, stock_top=float(getattr(job, "StockTop", 0.0)))
        if getattr(op, "Frame", ""):
            op.Frame = ""
    o = prog["ops"][-1]
    op.Moves = json.dumps(o["moves"])
    op.Spindle = json.dumps(o["spindle"])


def plane_shape(job, fr):
    """零件模型 → 倾斜面的平面坐标（工件坐标 = 模型坐标减去零件顶面高 z_top；平面坐标 = Rᵀ·(工件坐标 − 原点)）"""
    import FreeCAD

    from analysis.cam import tilt

    z_top = _js(job, "PartData", {}).get("z_top", 0.0)
    R = tilt.matrix(fr)
    o = fr["origin"]
    m = FreeCAD.Matrix()
    for i in range(3):
        for j in range(3):
            setattr(m, f"A{i + 1}{j + 1}", float(R[j, i]))
    t = -(R.T @ [o[0], o[1], o[2] + z_top])
    m.A14, m.A24, m.A34 = (float(v) for v in t)
    sh = job.Model.Shape.copy()
    sh.transformShape(m)
    return sh


def plane_stock(job, fr) -> dict:
    """作业的毛坯（工件坐标的长方体，顶面高出零件 StockTop）→ 平面坐标里斜放的长方体：{"extent", "corner", "rotation"}（FreeCAD 模型坐标同平面坐标）"""
    from analysis.cam import tilt

    d = _js(job, "PartData", {})
    st = d["stock"]
    top = float(getattr(job, "StockTop", 0.0))
    x0, y0, x1, y1 = st["box"]
    corner_w = [x0, y0, top - float(st["height"])]
    R = tilt.matrix(fr)
    corner_p = R.T @ (np.asarray(corner_w, float) - np.asarray(fr["origin"], float))
    return {"extent": [x1 - x0, y1 - y0, float(st["height"]) + top], "corner": [float(v) for v in corner_p],
            "rotation": [[float(v) for v in row] for row in R.T]}


def plane_stock_top(job, fr) -> float:
    """平面坐标里毛坯最高处比零件最高处高多少（倾斜面上要不要面铣、铣多深）"""
    from itertools import product

    sb = plane_stock(job, fr)
    R = np.asarray(sb["rotation"], float)                  # 平面坐标 = corner + R·(长方体局部坐标)，R = 倾斜面旋转的转置
    c = np.asarray(sb["corner"], float)
    zs = [float((c + R @ (np.asarray(e, float) * sb["extent"]))[2]) for e in product((0, 1), repeat=3)]
    return max(0.0, max(zs) - plane_shape(job, fr).BoundBox.ZMax)


def face_frame(job, sub: str) -> dict:
    """零件上的一个平面 → 倾斜面（工件坐标）：原点在面的形心，Z = 面朝外的法向，X = 工件 X 在面上的投影（法向是 ±X 时取工件 Y）"""
    face = job.Model.Shape.getElement(sub)
    surf = face.Surface
    if not hasattr(surf, "Axis") or type(surf).__name__ != "Plane":
        raise CamObjError(f"{sub} 不是平面，定不了倾斜面")
    n = surf.Axis * (1 if face.Orientation == "Forward" else -1)
    c = face.CenterOfMass
    z_top = _js(job, "PartData", {}).get("z_top", 0.0)
    from analysis.cam import tilt

    fr = {"origin": [c.x, c.y, c.z - z_top], "z": [n.x, n.y, n.z]}
    R = tilt.matrix(fr)
    return {"origin": fr["origin"], "x": [float(v) for v in R[:, 0]], "z": [float(v) for v in R[:, 2]]}


def new_tilt_setup(job, sub: str):
    """铣削作业加一个倾斜面装夹（3+2，ADR-0106 C2a）：点的面定工作平面；面朝上（法向 +Z）的不用倾斜"""
    if job.Kind == "turn":
        raise CamObjError("车削作业没有倾斜面")
    fr = face_frame(job, sub)
    if abs(fr["z"][2] - 1.0) < 1e-9:
        raise CamObjError(f"{sub} 朝上，不用倾斜：直接在装夹 1 里加工序")
    doc = job.Document
    s = doc.addObject("App::DocumentObjectGroupPython", "WqCamSetup")
    SetupProxy(s)
    _attach_vp(s, SetupVP)
    n = len(setups(job)) + 1
    s.Side = str(n)
    s.Label = T("倾斜面 {}（{}）").format(n, sub)
    s.Frame = json.dumps(fr)
    job.addObject(s)
    doc.recompute()
    return s


def regenerate(op) -> None:
    if op.OpKind in LIVE_KINDS:
        regenerate_live(op)
    elif op.OpKind in FIVE_KINDS:
        regenerate_five(op)
    else:
        (regenerate_turn if job_of(op).Kind == "turn" else regenerate_mill)(op)
    op.recompute()


# ---------------------------------------------------------------- 车铣中心的动力刀工序（ADR-0106 C2b 界面）
def _is_mill_turn(job) -> bool:
    from analysis.cam import machines

    return job.Kind == "turn" and machines.get(job.Machine)["kind"] == "mill_turn"


def _design_prof(job):
    from analysis.cam import paths as P

    d = _js(job, "PartData", {})
    return d.get("profile") or P.design_profile(d["segments"], d.get("chamfer_mm", 0.0))   # t 从左端 0 起向右


def _turned_r(job, z_work: float, side: str = "right") -> float:
    """车完的外圆半径（这次装夹的工件坐标 z：右端装夹 Z0 在右端面，调头装夹 Z0 在原来的左端面，都向卡盘为负）"""
    from analysis.cam import paths as P

    prof = _design_prof(job)
    t = z_work + float(prof[-1][0]) if side == "right" else -z_work
    return P.d_at(prof, t) / 2.0


def _to_side(job, side: str):
    """模型坐标 → 这次装夹的工件坐标（右端：z − z_right；调头：绕 Y 轴转 180°，x → −x，z → z_left − z）"""
    zr = float(_js(job, "PartData", {})["z_right"])
    if side == "right":
        return lambda x, y, z: (x, y, z - zr)
    zl = zr - float(_design_prof(job)[-1][0])
    return lambda x, y, z: (-x, y, zl - z)


def _exact_box(face):
    """面的精确包围盒（顶点 + 圆弧在轴向极值处的点；BoundBox 按三角化算，有时偏松）：[xmin, ymin, zmin, xmax, ymax, zmax]"""
    import math as _m

    pts = [v.Point for v in face.Vertexes]
    for e in face.Edges:
        if type(e.Curve).__name__ != "Circle":
            continue
        a0, a1 = e.ParameterRange
        if a1 - a0 >= 2 * _m.pi - 1e-9:
            pts += [e.valueAt(a0 + k * _m.pi / 2) for k in range(4)]
            continue
        k0 = _m.ceil((a0 - 1e-12) / (_m.pi / 2))
        k = k0
        while k * _m.pi / 2 <= a1 + 1e-12:              # 圆弧参数里每过 90° 一个极值点（圆弧在坐标平面里时）
            pts.append(e.valueAt(k * _m.pi / 2))
            k += 1
        pts += [e.valueAt(a0), e.valueAt(a1)]
    xs, ys, zs = [p.x for p in pts], [p.y for p in pts], [p.z for p in pts]
    return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]


def live_feature(job, sub: str, kind: str, side: str = "right") -> dict:
    """点的面 → 动力刀工序的特征（这次装夹的工件坐标：Z0 在朝外的端面，向卡盘为负；调头装夹绕 Y 轴转 180°）。
    端面铣：法向朝外端的平底面（长圆槽或圆角矩形型腔的底）；圆柱面键槽：法向径向的平底面（沿 Z 的长圆）"""
    import math as _m

    from analysis.cam import millturn as MT

    tw = _to_side(job, side)
    end = "右端" if side == "right" else "左端"
    face = job.Model.Shape.getElement(sub)
    if type(face.Surface).__name__ != "Plane":
        raise CamObjError(f"{sub} 不是平面：点槽底或型腔底")
    n0 = face.normalAt(0, 0)
    n = tw(n0.x, n0.y, n0.z)
    n = (n[0], n[1], n0.z if side == "right" else -n0.z)       # 方向只转不平移
    bx = _exact_box(face)
    corners = [tw(x, y, z) for x in (bx[0], bx[3]) for y in (bx[1], bx[4]) for z in (bx[2], bx[5])]
    x0, y0, z0 = (round(min(c[i] for c in corners), 6) for i in range(3))
    x1, y1 = (round(max(c[i] for c in corners), 6) for i in range(2))
    if kind == "live_face":
        if n[2] < 1 - 1e-6:
            raise CamObjError(f"{sub} 不朝{end}：端面铣点{end}端面上的槽底、型腔底")
        if not all(type(e.Curve).__name__ in ("Line", "LineSegment", "Circle") for e in face.OuterWire.Edges):
            raise CamObjError(f"{sub} 的外形不是直线和圆弧：只做长圆槽、圆角矩形型腔")
        ft = MT.classify_face(face.Area, x0, y0, x1, y1)
        if ft is None or len(face.Wires) > 1:
            raise CamObjError(f"{sub} 认不出是长圆槽还是圆角矩形型腔：别的形状还没做")
        # 槽口在这次装夹朝外的端面（Z0）；落在台阶端面上的还不做
        ft.update({"z0": 0.0, "depth": round(-z0, 6)})
        if ft["depth"] <= 0:
            raise CamObjError(f"{sub} 不在{end}端面以下")
        return ft
    if abs(n[2]) > 1e-6:
        raise CamObjError(f"{sub} 不是沿轴向的平面：圆柱面键槽点键槽底")
    if kind == "live_flat":
        return _flat_feature(job, face, sub, tw, n, side)
    c0 = face.CenterOfMass
    c = tw(c0.x, c0.y, c0.z)
    r_bot = c[0] * n[0] + c[1] * n[1]                     # 槽底到轴线的距离（法向朝外）
    if r_bot <= 0:
        raise CamObjError(f"{sub} 的法向朝里：点键槽底面")
    ang = _m.degrees(_m.atan2(n[1], n[0]))
    ends: dict = {}                                       # 圆弧按圆心归并（一段半圆有时被切成两条边）
    for e in face.Edges:
        if type(e.Curve).__name__ == "Circle":
            k = tw(e.Curve.Center.x, e.Curve.Center.y, e.Curve.Center.z)
            ends.setdefault(tuple(round(v, 6) for v in k), set()).add(round(e.Curve.Radius, 6))
    radii = {r for rs in ends.values() for r in rs}
    if len(ends) != 2 or len(radii) != 1:
        raise CamObjError(f"{sub} 不是两端半圆的键槽底：别的形状还没做")
    w = 2 * radii.pop()                                   # 两端半圆：槽宽 = 直径，圆心定两端
    zb, za = sorted(k[2] for k in ends)
    st = (za - zb) * w + _m.pi * w * w / 4
    if abs(face.Area - st) > 0.01 * face.Area:
        raise CamObjError(f"{sub} 不是两端半圆的键槽底：别的形状还没做")
    r_out = _turned_r(job, (za + zb) / 2, side)
    return {"type": "keyway", "angle": round(ang, 6) + 0.0, "width": round(w, 6), "za": round(za, 6), "zb": round(zb, 6),
            "r_outer": round(r_out, 6), "depth": round(r_out - r_bot, 6)}


def live_side(job, sub: str, kind: str) -> str:
    """点的面该在哪次装夹铣：端面铣看面朝哪端；键槽看它在第一次装夹车到的范围内（右端到最大直径段）还是在调头后车的那一头"""
    from analysis.cam import paths as P

    face = job.Model.Shape.getElement(sub)
    if kind == "live_face":
        return "right" if face.normalAt(0, 0).z > 0 else "left"
    # 键槽、平底槽：按所在的轴段
    zr = float(_js(job, "PartData", {})["z_right"])
    reach = P.setup_profile(_design_prof(job), "right")[1]
    return "right" if face.CenterOfMass.z - zr >= -reach - 1e-9 else "left"


def _flat_feature(job, face, sub, tw, n, side):
    """圆柱面上的平底槽（C 分度 + Y 轴铣）：槽底平面坐标 u = 切向（分度后的机床 Y）、v = Z；外形按圆弧认长圆或圆角矩形"""
    import math as _m

    ang = _m.degrees(_m.atan2(n[1], n[0]))
    tu = (-n[1], n[0])
    c0 = face.CenterOfMass
    c = tw(c0.x, c0.y, c0.z)
    r_bot = c[0] * n[0] + c[1] * n[1]
    if r_bot <= 0:
        raise CamObjError(f"{sub} 的法向朝里：点平底槽的底面")
    uv = lambda p: (round(p[0] * tu[0] + p[1] * tu[1], 6), round(p[2], 6))
    arcs: dict = {}
    for e in face.Edges:
        if type(e.Curve).__name__ == "Circle":
            k = uv(tw(e.Curve.Center.x, e.Curve.Center.y, e.Curve.Center.z))
            arcs.setdefault(k, set()).add(round(e.Curve.Radius, 6))
        elif type(e.Curve).__name__ not in ("Line", "LineSegment"):
            raise CamObjError(f"{sub} 的外形不是直线和圆弧：只做长圆、圆角矩形平底槽")
    radii = {r for rs in arcs.values() for r in rs}
    if len(radii) > 1 or len(face.Wires) > 1:
        raise CamObjError(f"{sub} 认不出是长圆还是圆角矩形平底槽：别的形状还没做")
    if len(arcs) == 2:
        (a, b), r = sorted(arcs), radii.pop()
        shape = {"type": "slot", "a": [a[0], a[1]], "b": [b[0], b[1]], "width": round(2 * r, 6)}
        area = _m.dist(a, b) * 2 * r + _m.pi * r * r
    elif len(arcs) in (0, 4):
        r = radii.pop() if radii else 0.0
        pts = [uv(tw(v.Point.x, v.Point.y, v.Point.z)) for v in face.Vertexes] if not arcs else \
            [(cu + su * r, cv + sv * r) for cu, cv in arcs for su in (-1, 1) for sv in (-1, 1)]
        u0, v0 = min(p[0] for p in pts), min(p[1] for p in pts)
        u1, v1 = max(p[0] for p in pts), max(p[1] for p in pts)
        shape = {"type": "pocket", "rect": [u0, v0, u1, v1], "corner_r": round(r, 6)}
        area = (u1 - u0) * (v1 - v0) - (4 - _m.pi) * r * r
    else:
        raise CamObjError(f"{sub} 认不出是长圆还是圆角矩形平底槽：别的形状还没做")
    if abs(face.Area - area) > 0.01 * face.Area:
        raise CamObjError(f"{sub} 认不出是长圆还是圆角矩形平底槽：别的形状还没做")
    r_out = _turned_r(job, c[2], side)
    return {"type": "flat", "angle": round(ang, 6) + 0.0, "r_outer": round(r_out, 6), "depth": round(r_out - r_bot, 6), "shape": shape}


def _endmills(job, d_max: float, exact: float | None = None):
    lib = _lib(job)
    em = [t for t in lib["tools"] if t.get("kind") in ("endmill", "flat_endmill") and t.get("diameter_mm")]
    if exact is not None:
        return [t for t in em if abs(float(t["diameter_mm"]) - exact) < 1e-6]
    return sorted([t for t in em if float(t["diameter_mm"]) <= d_max + 1e-9], key=lambda t: -float(t["diameter_mm"]))


def add_live_op(setup, kind: str, sub: str):
    """车铣中心的车削作业：右端装夹加一道动力刀工序（点的面定特征；刀从刀具库里按槽宽 / 圆角挑；参数取样本的中间值）"""
    from freecad_addon.core import cam_study as S

    job = job_of(setup) or next(p for p in setup.InList if is_job(p))
    if kind not in LIVE_KINDS:
        raise CamObjError(f"没有这种动力刀工序：{kind}")
    if not _is_mill_turn(job):
        raise CamObjError("动力刀工序要在车铣中心上：作业的机床选车铣中心")
    ft = live_feature(job, sub, kind, setup.Side)
    if ft["type"] == "flat":                              # 平底槽：刀不大于槽宽（长圆）或 2× 圆角（圆角矩形）
        sh = ft["shape"]
        if sh["type"] == "slot":
            lim = sh["width"]
        else:
            w = min(sh["rect"][2] - sh["rect"][0], sh["rect"][3] - sh["rect"][1])
            lim = min(2 * sh["corner_r"], w) if sh["corner_r"] > 0 else w / 2
        tools = _endmills(job, lim)
        if not tools:
            raise CamObjError(f"刀具库里没有不大于 Ø{lim:g} 的立铣刀")
    elif kind == "live_keyway" or ft["type"] == "slot":
        tools = _endmills(job, 0, exact=ft["width"])
        if not tools:
            raise CamObjError(f"刀具库里没有 Ø{ft['width']:g} 的立铣刀：键槽、端面槽按槽宽选刀，请先在刀具库里加")
    else:
        w = min(ft["rect"][2] - ft["rect"][0], ft["rect"][3] - ft["rect"][1])
        lim = min(2 * ft["corner_r"], w) if ft["corner_r"] > 0 else w / 2
        tools = _endmills(job, lim)
        if not tools:
            raise CamObjError(f"刀具库里没有不大于 Ø{lim:g} 的立铣刀")
    t = tools[0]
    from analysis.cam import tools as TL

    cc = TL.cutting_for(t, S.iso_group(job.Kienzle)) or {}
    mid = lambda r: (r.get("min", 0.0) + r.get("max", 0.0)) / 2 if r and r.get("min") is not None and r.get("max") is not None else 0.0
    vc, fz = mid(cc.get("vc_m_min")), mid(cc.get("fz_mm"))
    taken = [o.ToolNumber for s_ in setups(job) for o in ops(s_)] + list(TURN_TOOL_N.values())
    same = [o.ToolNumber for s_ in setups(job) for o in ops(s_) if o.ToolId == t["id"] and o.OpKind in LIVE_KINDS]
    op = new_op(setup, kind, tool_id=t["id"], tool_n=same[0] if same else max(taken) + 1, vc=vc, feed=fz,
                ap=min(ft["depth"], float(t["diameter_mm"]) / 2),
                reason=("刀具样本没有这个材料组的参数，vc、fz 待填" if not (vc and fz) else "槽宽 / 圆角定刀径；参数取样本范围的中间值"))

    op.Geometry = [(job.Model, sub)]
    op.HoleData = json.dumps({"feature": ft}, ensure_ascii=False)
    if vc and fz:
        regenerate(op)
    op.Check = "待确认"
    return op


def live_program_op(job, op) -> dict:
    """动力刀工序 → 车铣程序里的工序（analysis.cam 的 live_ops）"""
    mv = _js(op, "Moves", [])
    if not mv:
        raise CamObjError(f"{op.Label} 还没有刀路：填好 vc、fz 后右键“重算刀路”")
    ft = _js(op, "HoleData", {})["feature"]
    from analysis.cam import tools as TL

    d = float(TL.get(_lib(job), op.ToolId)["diameter_mm"])
    interp = {"cyl": ft["r_outer"]} if ft["type"] == "keyway" else {"index": ft["angle"]} if ft["type"] == "flat" else "polar"
    return {"tool": {"n": op.ToolNumber, "d": d}, "spindle": _js(op, "Spindle", {}), "title": op.Label, "interp": interp, "moves": mv}


def regenerate_live(op) -> None:
    from analysis.cam import millturn as MT
    from analysis.cam import paths as P
    from analysis.cam import tools as TL

    job = job_of(op)
    ft = _js(op, "HoleData", {})["feature"]
    t = TL.get(_lib(job), op.ToolId)
    d = float(t["diameter_mm"])
    z_teeth = int(t.get("flutes") or t.get("teeth") or 0)
    if op.Vc <= 0 or op.Feed <= 0 or z_teeth <= 0:
        raise CamObjError(f"{op.Label}：vc、fz 要大于 0，刀具要写刃数")
    from analysis.cam import machines

    rpm = P.spindle_rpm(op.Vc, d, float(machines.get(job.Machine)["max_rpm"]))
    f = P.mill_feed(op.Feed, z_teeth, rpm)
    ap = op.Ap if op.Ap > 0 else d / 2
    if ft["type"] == "keyway":
        mv = MT.keyway_moves(ft["angle"], ft["r_outer"], ft["depth"], ft["za"], ft["zb"], d, ap, f, f / 2)
    elif ft["type"] == "flat":
        mv = MT.flat_moves(ft, d, ap, f, f / 2, stepover=op.StepOver or 0.5)
    else:
        mv = MT.face_moves(ft, d, ap, f, f / 2, stepover=op.StepOver or 0.5)
    op.Moves = json.dumps(mv)
    op.Spindle = json.dumps({"rpm": round(rpm)})


# ---------------------------------------------------------------- 五轴联动工序（ADR-0106 C3d）
def _five_tool(job, kind: str, need_len: float = 0.0):
    """侧刃铣：刃长够直纹线长的平底刀里最粗的（没有刃长数据的不挑）；曲面精加工、沿曲线：不超过 Ø10 的球头刀里最粗的"""
    lib = _lib(job)
    if kind == "swarf5":
        c = [t for t in lib["tools"] if t.get("kind") in ("endmill", "flat_endmill") and t.get("diameter_mm")
             and float(t.get("flute_length_mm") or 0.0) >= need_len - 1e-9]
        if not c:
            raise CamObjError(f"刀具库里没有刃长不小于 {need_len:.1f} mm 的平底立铣刀（侧刃铣要刃长盖住整条直纹线）")
    else:
        c = [t for t in lib["tools"] if t.get("kind") == "ball_endmill" and t.get("diameter_mm") and float(t["diameter_mm"]) <= 10 + 1e-9]
        if not c:
            raise CamObjError("刀具库里没有不超过 Ø10 的球头刀")
    return max(c, key=lambda t: (float(t["diameter_mm"]), t["id"]))


def _has_rotary(job) -> bool:
    from analysis.cam import machines

    return bool(machines.get(job.Machine).get("rotary"))


def add_five_op(setup, kind: str, subs: list[str]):
    """铣削作业的装夹加一道五轴联动工序：subs 是点的面（侧刃铣、曲面精加工）或边（沿曲线）"""
    from analysis.cam import tools as TL
    from freecad_addon.core import cam_study as S
    from freecad_addon.fc import cam_5axis as C5

    job = job_of(setup) or next(p for p in setup.InList if is_job(p))
    if kind not in FIVE_KINDS:
        raise CamObjError(f"没有这种五轴工序：{kind}")
    if job.Kind == "turn":
        raise CamObjError("五轴联动工序要在铣削作业里加（机床选五轴加工中心）")
    if not _has_rotary(job):
        raise CamObjError(f"机床 {job.Machine} 没有回转轴，做不了五轴联动：作业的机床选五轴加工中心")
    want = "Edge" if kind == "curve5" else "Face"
    if not subs or any(not s_.startswith(want) for s_ in subs):
        raise CamObjError("五轴沿曲线要点边" if kind == "curve5" else "要点零件上的面")
    shape = job.Model.Shape
    need = 0.0
    if kind == "swarf5":
        for s_ in subs:
            b, t, _n = C5.ruled_rails(shape.getElement(s_), 8)
            need = max(need, float(max(np.linalg.norm(t - b, axis=1))))
    t = _five_tool(job, kind, need)
    cc = TL.cutting_for(t, S.iso_group(job.Kienzle)) or {}
    mid = lambda r: (r.get("min", 0.0) + r.get("max", 0.0)) / 2 if r and r.get("min") is not None and r.get("max") is not None else 0.0
    vc, fz = mid(cc.get("vc_m_min")), mid(cc.get("fz_mm"))
    taken = [o.ToolNumber for s_ in setups(job) for o in ops(s_)]
    same = [o.ToolNumber for s_ in setups(job) for o in ops(s_) if o.ToolId == t["id"]]
    op = new_op(setup, kind, tool_id=t["id"], tool_n=same[0] if same else (max(taken) + 1 if taken else 1), vc=vc, feed=fz,
                stepover=0.1 if kind == "surface5" else 0.0,
                reason=("刀具样本没有这个材料组的参数，vc、fz 待填" if not (vc and fz) else "按面选刀；参数取样本范围的中间值"))
    op.Geometry = [(job.Model, s_) for s_ in subs]
    op.Lead = 10.0 if kind == "surface5" else 0.0
    op.Below = 0.0                                   # 侧刃铣：倾斜的平底刀底面边缘正好到直纹面底边，再往下伸会切进底面
    op.Depth5 = 0.2 if kind == "curve5" else 0.0
    op.PoleMin = 3.0
    op.AvoidCollision = kind == "surface5"
    if vc and fz:
        regenerate(op)
    op.Check = "待确认"
    return op


def _tool_parts(t: dict, ball_r: float) -> tuple[list, str]:
    """刀具除刀刃外的部分（离球心 / 刀尖的高度起止、半径）：刀杆（刃长 → 伸出长）、刀柄外形；缺数据的部分不查，返回说明"""
    parts, miss = [], []
    flute = t.get("flute_length_mm")
    stick = t.get("stickout_mm")
    shank_r = float(t.get("shank_diameter_mm") or t["diameter_mm"]) / 2
    if stick:
        parts.append((float(flute or 2 * float(t["diameter_mm"])) - ball_r, float(stick) - ball_r, shank_r))
    else:
        miss.append("stickout")
    prof = (t.get("holder") or {}).get("profile_mm") or []
    for (r0, z0), (r1, z1) in itertools.pairwise(prof):
        if abs(r0 - r1) < 1e-9 and z1 > z0:
            parts.append((float(z0) - ball_r, float(z1) - ball_r, float(r0)))
    if not prof:
        miss.append("holder")
    note = {("stickout", "holder"): "；刀具没写伸出长和刀柄外形，刀杆、刀柄的碰撞没查", ("stickout",): "；刀具没写伸出长，刀杆的碰撞没查",
            ("holder",): "；刀具没写刀柄外形，刀柄的碰撞没查"}.get(tuple(miss), "")
    return parts, note


def _part_distance(shape, z_top: float):
    """零件（FreeCAD 网格，工件坐标）的距离函数：点 → 到零件表面的距离"""
    from analysis.cam import dexel as DX

    v, fc = shape.tessellate(0.2)
    V = np.array([[p.x, p.y, p.z - z_top] for p in v])
    tris = V[np.array(fc)]

    def dist(P_):
        return DX.point_triangle_distance(np.atleast_2d(P_), tris)
    return dist


def regenerate_five(op) -> None:
    from analysis.cam import fiveaxis as FA
    from analysis.cam import machines
    from analysis.cam import paths as P
    from analysis.cam import tools as TL
    from freecad_addon.fc import cam_5axis as C5

    job = job_of(op)
    t = TL.get(_lib(job), op.ToolId)
    d = float(t["diameter_mm"])
    R = d / 2
    z_teeth = int(t.get("flutes") or t.get("teeth") or 0)
    if op.Vc <= 0 or op.Feed <= 0 or z_teeth <= 0:
        raise CamObjError(f"{op.Label}：vc、fz 要大于 0，刀具要写刃数")
    mach = machines.get(job.Machine)
    rpm = P.spindle_rpm(op.Vc, d, float(mach["max_rpm"]))
    f = P.mill_feed(op.Feed, z_teeth, rpm)
    shape = job.Model.Shape
    z_top = _js(job, "PartData", {}).get("z_top", 0.0)
    shift = np.array([0.0, 0.0, -z_top])                         # 模型坐标 → 工件坐标（Z0 在零件顶面）
    subs = [s_ for _o, ss in op.Geometry for s_ in (ss if isinstance(ss, (list, tuple)) else [ss])]
    lead_dir = {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0]}.get((op.LeadDir or "").strip().lower())
    segs, note = [], ""
    if op.OpKind == "swarf5":
        left = 0.0
        for s_ in subs:
            b, tp, nr = C5.ruled_rails(shape.getElement(s_), max(8, math.ceil(shape.getElement(s_).Length / 4)))
            tips, axes = FA.swarf(b + shift, tp + shift, R, below=op.Below, normals=nr)
            tips, axes, chk = FA.swarf_clear(b + shift, tp + shift, tips, axes, R)     # 扭曲直纹面：啃进去的刀位推出来（ADR-0106 C3e）
            left = max(left, chk["leftover_mm"])
            segs.append((tips, axes))
        if left >= 0.01:
            note += f"；面是扭曲的直纹面，圆柱侧刃贴不严：刀位已推出不过切，那里最多剩料 {left:.2f} mm（留给后面清根或换球头多轴精加工）"
    elif op.OpKind == "surface5":
        face = shape.getElement(subs[0])
        rows = C5.raster_rows(face, max(0.05, (op.StepOver or 0.1) * d), max(0.2, d / 6))
        if lead_dir is not None:
            rows = FA.zigzag(rows)
        parts, note = _tool_parts(t, R) if op.AvoidCollision else ([], "")
        dist = _part_distance(shape, z_top)
        cut_rows = []
        for pts, nrm in rows:                        # 球心离零件不到 R（会切进旁边的面，如球冠和平面相接的凹角）的点去掉，行在那里断开
            ctr = pts + shift + R * nrm
            ok = dist(ctr) >= R - 0.005
            cur = []
            for k in range(len(pts)):
                if ok[k]:
                    cur.append(k)
                elif len(cur) >= 2:
                    cut_rows.append((pts[cur], nrm[cur]))
                    cur = []
                else:
                    cur = []
            if len(cur) >= 2:
                cut_rows.append((pts[cur], nrm[cur]))
        if not cut_rows:
            raise CamObjError(f"{op.Label}：球头刀 Ø{d:g} 在这个面上处处会切进旁边的面，换小一点的刀")
        if len(cut_rows) < len(rows) or sum(len(r[0]) for r in cut_rows) < sum(len(r[0]) for r in rows):
            note += "；旁边的面挡着的地方（球头刀会切进去）没走刀"
        for pts, nrm in cut_rows:
            tips, axes = FA.ball_surface(pts + shift, nrm, R, op.Lead, op.Tilt, lead_dir=lead_dir)
            if parts:
                r = FA.avoid_collision(tips, axes, R, parts, dist)
                if r["issues"]:
                    raise CamObjError(f"{op.Label}：{r['issues'][0]['text']}")
                tips, axes = r["tips"], r["axes"]
            segs.append((tips, axes))
    else:
        for s_ in subs:
            e = shape.getElement(s_)
            import Part

            faces = list(shape.ancestorsOfType(e, Part.Face))
            if not faces:
                raise CamObjError(f"{s_} 不在任何面上")
            fc = max(faces, key=lambda x: x.normalAt(*x.Surface.parameter(e.valueAt(e.FirstParameter))).z)
            pts, nrm = C5.edge_points(e, fc, max(0.2, d / 4))
            tips, axes = FA.curve_follow(pts + shift, nrm, depth=op.Depth5, lead=op.Lead)
            segs.append((tips, axes))
    if op.PoleMin > 0 and op.OpKind != "swarf5":                 # 侧刃铣的刀轴由曲面定，改了形状就变，不让
        pz = FA.pole(mach["model"])
        if pz is not None:
            new = []
            for tips, axes in segs:
                na, _ = FA.avoid_pole(axes, pz, op.PoleMin)
                new.append((FA.ball_reaxis(tips, axes, na, R), na))           # 球头刀：球心不动
            segs = new
    clear = 5.0 + float(getattr(job, "StockTop", 0.0))          # 退到毛坯顶以上 5 mm 再快移
    mv = FA.link_moves(segs, f, link="direct" if (op.OpKind == "surface5" and lead_dir is not None) else "lift", clear_z=clear)
    op.Moves = json.dumps(mv)
    op.Spindle = json.dumps({"rpm": round(rpm)})
    if note:
        op.Reason = (op.Reason or "") + note


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


def to_model_3d(job, side, x, y, z):
    """车削作业的工件坐标（x, y 是真实坐标，不是直径；车铣的铣削段、dexel 网格用）→ 零件模型坐标；调头装夹绕 Y 轴转回来"""
    d = _js(job, "PartData", {})
    zr = d.get("z_right", 0.0)
    if side == "left":
        total = float(d["profile"][-1][0]) if d.get("profile") else sum(float(L) for _, L in d.get("segments") or [])
        return -x, y, (zr - total) - z
    return x, y, z + zr


def _unframe(fr, x, y, z):
    """倾斜面工序的平面坐标 → 工件坐标"""
    if not fr:
        return x, y, z
    from analysis.cam import tilt

    return tuple(float(v) for v in tilt.to_work(fr, [x, y, z]))


def path_shape(op):
    import FreeCAD
    import Part

    mv = _js(op, "Moves", [])
    job = job_of(op)
    if not mv or job is None:
        return Part.Shape()
    s = setup_of(op)
    side = getattr(s, "Side", "") if s is not None else ""
    fr = _js(op, "Frame", None) if getattr(op, "Frame", "") else None
    pos = None
    edges = []
    for m in mv:
        if m.get("t") not in ("rapid", "feed", "thread", "drill"):
            continue
        p = FreeCAD.Vector(*to_model(job, side, *_unframe(fr, m["x"], m.get("y", 0.0), m["z"])))
        if m["t"] == "drill":
            top = FreeCAD.Vector(*to_model(job, side, *_unframe(fr, m["x"], m.get("y", 0.0), m.get("safe", 5.0))))
            edges.append(Part.LineSegment(top, p).toShape())
            pos = top
            continue
        if pos is not None and (p - pos).Length > 1e-9:
            edges.append(Part.LineSegment(pos, p).toShape())
        pos = p
    if op.OpKind in FIVE_KINDS:                       # 五轴联动：每隔几个刀位画一根沿刀轴的短线（看得出刀轴怎么倒，ADR-0106 C3d）
        feeds = [m for m in mv if m.get("t") == "feed" and m.get("axis")]
        for m in feeds[::max(1, len(feeds) // 40)]:
            p = FreeCAD.Vector(*to_model(job, side, m["x"], m["y"], m["z"]))
            a = FreeCAD.Vector(*m["axis"])
            edges.append(Part.LineSegment(p, p + a * 8.0).toShape())
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

    flags = {"face": float(getattr(job, "StockTop", 0.0)) > 0, "pocket": True, "profile": False, "drill": True, "holes": True,
             "chamfer": True}
    plan = cam_doc.mill_plan(job.Model.Shape, _lib(job), S.iso_group(job.Kienzle), max_rpm=float(machines.get(job.Machine)["max_rpm"]),
                             stock_top=float(getattr(job, "StockTop", 0.0)), **flags)
    s = setups(job)[0]
    for spec, row in zip(plan["ops"], plan["card"], strict=True):
        _mill_op_from_plan(s, spec, row)
    doc.recompute()
    return {"setup": {"mode": "program", "machine": job.Machine, "item": job.Item, "kienzle": job.Kienzle}, "card": plan["card"],
            "notes": plan["notes"], "by": "规则（没有用 AI）", "explanation": "", "iso_group": S.iso_group(job.Kienzle)}


def _mill_op_from_plan(setup, spec, row):
    p = row["params"]
    ap = spec["step_down_mm"] if spec["type"] == "waterline" else p.get("ap", 0.0)     # 等高步距按残留高度算的，不用规则切深
    op = new_op(setup, spec["type"], tool_id=row["tool"], tool_n=spec["number"], vc=p["vc"], feed=p.get("fz", p.get("f", 0.0)),
                ap=ap, stepover=p.get("stepover", 0.0), reason=row.get("reason", ""))
    op.Label = T(row["title"])
    if spec["type"] in HOLE_KINDS:
        op.HoleData = json.dumps({"d": spec["d"], "holes": [list(h) for h in spec["holes"]], **({"pitch": spec["pitch"]} if "pitch" in spec else {})})
    if spec["type"] == "chamfer":                  # 倒角：哪些倒角面、多宽
        op.HoleData = json.dumps({"faces": spec["faces"], "width": spec["width"]})
    op.Check = "在样本范围内" if row["status"] == "pass" else "待确认"
    regenerate(op)
    return op


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
    turn = job.Kind == "turn" and op.OpKind not in LIVE_KINDS          # 动力刀工序按铣刀核对每齿进给（ADR-0106 C2b）
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
        regenerate(op)
    else:
        if kind not in MILL_KINDS:
            raise CamObjError(f"铣削没有这种工序：{kind}")
        from freecad_addon.fc import cam_doc

        flags = {k: k == kind for k in ("face", "pocket", "adaptive", "rest", "profile", "drill", "chamfer", "surface", "waterline")}
        flags["holes"] = kind in HOLE_KINDS
        flags["taps"] = kind == "tap"
        flags["thread_mill"] = kind == "thread_mill"
        fr = _js(setup, "Frame", None) if getattr(setup, "Frame", "") else None
        shape = plane_shape(job, fr) if fr else job.Model.Shape           # 倾斜面：在平面坐标里找特征（ADR-0106 C2a）
        try:
            plan = cam_doc.mill_plan(shape, _lib(job), S.iso_group(job.Kienzle),
                                     max_rpm=float(machines.get(job.Machine)["max_rpm"]),
                                     stock_top=plane_stock_top(job, fr) if fr else float(getattr(job, "StockTop", 0.0)), **flags)
        except cam_doc.CamDocError as exc:
            raise CamObjError(str(exc)) from exc
        pairs = [(sp, r) for sp, r in zip(plan["ops"], plan["card"], strict=True) if sp["type"] == kind]
        if not pairs:
            raise CamObjError("；".join(plan["notes"]) or f"零件上没有能{MILL_KINDS[kind]}的几何")
        used = [_js(o, "HoleData", {}) for o in ops(setup) if o.OpKind == kind]
        free = [pr for pr in pairs if not any(u.get("holes", []) == [list(h) for h in pr[0].get("holes", [])] and u.get("faces") == pr[0].get("faces")
                                              for u in used)] or pairs   # 孔工序：先取还没加的那一组孔
        spec, row = free[0]
        same = [o.ToolNumber for s_ in setups(job) for o in ops(s_) if o.ToolId == row["tool"]]
        taken = [o.ToolNumber for s_ in setups(job) for o in ops(s_)]
        spec = {**spec, "number": same[0] if same else max(taken, default=0) + 1}   # 刀号：同一把刀沿用，新刀接着往后编
        op = _mill_op_from_plan(setup, spec, row)
    op.Check = "待确认"
    return op


def copy_op(op):
    """复制一道工序（草稿），放在原工序后面"""
    s = setup_of(op)
    c = new_op(s, op.OpKind, index=op.FeatureIndex, tool_id=op.ToolId, tool_n=op.ToolNumber, vc=op.Vc, feed=op.Feed, ap=op.Ap,
               stepover=op.StepOver, reason=op.Reason)
    c.Geometry = op.Geometry
    if hasattr(op, "HoleData"):
        c.HoleData = op.HoleData
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
    lib = _lib(job) if job.Kind == "turn" else None
    for n, tid in tool_rows:
        e = {"tool": tid}
        if tid in lengths:
            e["length_mm"] = float(lengths[tid])
        if lib is not None:                                   # 外圆车刀没写刀杆：按刀片配一把（ADR-0112）
            from analysis.cam import tools as TL
            from assist import cam_process as CP

            try:
                hd = CP.turn_holder(TL.get(lib, tid))
            except Exception:  # noqa: BLE001
                hd = None
            if hd:
                e["holder"] = hd
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
        setup["ops"] = {s.Side: [_turn_spec(job, o, s.Side) for o in ops(s) if o.OpKind not in LIVE_KINDS] for s in setups(job)}
        live = {s.Side: [live_program_op(job, o) for o in ops(s) if o.OpKind in LIVE_KINDS] for s in setups(job)}
        if any(live.values()):
            setup["live_ops"] = {k: v for k, v in live.items() if v}
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
            from freecad_addon.fc import cam_fc

            core = ({"core_d": float(t["diameter_mm"]) - 1.0825 * float(_js(o, "HoleData", {})["pitch"])}
                    if o.OpKind == "thread_mill" else {})              # 螺纹铣刀按齿根圆柱去料
            prog_ops.append({**({"ae_set": (o.StepOver or 0.2) * float(t["diameter_mm"])} if o.OpKind == "adaptive" else {}),
                             "tool": {**cam_fc.sim_tool(t, o.ToolNumber), **core,
                                      **({"ap_max": cc["ap_max_mm"]} if "ap_max_mm" in cc else {}),
                                      **({"ae_max": cc["ae_max_mm"]} if "ae_max_mm" in cc else {})},
                             "spindle": _js(o, "Spindle", {}), "moves": mv, "title": o.Label,
                             "safe": max((x["z"] for x in mv if x.get("t") == "rapid"), default=5.0),
                             **({"frame": _js(o, "Frame", None)} if getattr(o, "Frame", "") else {}),
                             **({"simul5": True} if o.OpKind in FIVE_KINDS else {})})
        st = float(getattr(job, "StockTop", 0.0))
        stock = {**d["stock"], "top": st, "height": float(d["stock"]["height"]) + st}
        setup = {"mode": "program", "machine": job.Machine, "item": job.Item, "stock": stock,
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
            turn = job.Kind == "turn" and o.OpKind not in LIVE_KINDS
            if o.OpKind != "thread":
                p["f" if (turn or o.OpKind == "drill") else "fz"] = o.Feed
            if o.Ap > 0:
                p["ap"] = o.Ap
            if o.OpKind in LIVE_KINDS:
                rid = f"{o.OpKind}{n}"
            elif job.Kind == "turn":
                rid = f"{o.OpKind}{o.FeatureIndex + 1}" if o.OpKind in FEATURE_KINDS else o.OpKind
            else:
                rid = f"f{o.ToolNumber}"
            rows.append({"id": rid, "title": o.Label, "tool": o.ToolId, "tool_name": "", "params": p,
                         "status": "pass" if o.Check == "在样本范围内" else "unknown", "reason": o.Reason})
    out = {"setup": build_setup(job), "card": rows, "notes": [], "by": "加工树（人已确认）", "explanation": "",
           "iso_group": S.iso_group(job.Kienzle)}
    if job.Kind == "mill" and job.Model is not None:   # 零件图、装夹图里的零件外形（ADR-0106 Q6a）：程序 Z0 在零件顶面
        from freecad_addon.fc import cam_figures_fc as FF

        shape = job.Model.Shape
        out["figures"] = {"part_views": FF.part_views(shape, -shape.BoundBox.ZMax)}
    return out
