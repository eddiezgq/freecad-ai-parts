"""装配体多体动力学的一次“研究”（ADR-0097 D5c，补充十二）：界面无关的流程，面板只管显示。需要 FreeCAD，不需要界面。

导入 STEP → 找候选、起草（AI 或规则）→ 人确认后建 Assembly → 设驱动和分析 → 生成模型、计算 → 曲线、核查、动画。
"""

from __future__ import annotations

import math

import FreeCAD as App

from analysis.mbd import assembly as A
from analysis.mbd import mates as MT

ANALYSES = [("kinematic", "运动学（给定驱动，反算驱动力）"), ("dynamic", "动力学"), ("static", "静平衡"),
            ("static_then_dynamic", "先静平衡再动力学"), ("linear", "线性化（模态）"), ("static_then_linear", "先静平衡再线性化")]
DRIVE_KINDS = [("none", "不驱动"), ("speed", "匀速 rpm（转动副）或 mm/s（移动副）"), ("function", "位移函数（° 或 mm，time 为时间 s）")]


def draft_from_step(path, doc, client=None, note=""):
    """STEP → (零件对象, 面摘要, 候选, 草稿)。给了 client（用 AI 起草）时，问渠多体动力学免费版拒绝（ADR-0102 第 4 步）"""
    from assist import mbd_edition
    from assist import mbd_mates as AM

    if client is not None:
        mbd_edition.gate(feature="AI 帮着挑运动副")
    from freecad_addon.fc import mbd_mates as MM

    objs = MM.import_step(path, doc)
    parts, found = MM.find(objs)
    return objs, parts, found, AM.draft(parts, found, client, note=note)


def build(doc, objs, found, accepted, ground):
    """人确认的候选 → Assembly"""
    from freecad_addon.fc import mbd_mates as MM

    return MM.build_assembly(doc, objs, ground, MT.to_assembly_joints(found, accepted))


def make_model(assembly, drives, analysis, *, gravity_mm_s2=None, mass_overrides=None, flex_parts=None):
    """drives: [{"joint": 模型里的运动副 id, "kind": speed|function, "value": 数或表达式}]；有问题抛 AssemblyError。
    flex_parts：构件 id → {"material": 材料库 id, "size_mm"?}，这些零件按实体柔性体算（ADR-0097 D8b，要 gmsh 和 CalculiX）"""
    from freecad_addon.fc import mbd_assembly as MA

    model, msgs = MA.model_from_assembly(assembly, gravity_mm_s2=gravity_mm_s2, mass_overrides=mass_overrides,
                                         analysis=analysis)
    joints = {j["id"]: j for j in model["joints"]}
    motions = []
    for d in drives:
        if d.get("kind", "none") == "none":
            continue
        j = joints.get(d["joint"])
        if j is None:
            raise A.AssemblyError([f"驱动的运动副 {d['joint']} 不在模型里"])
        if j["type"] not in ("revolute", "translational", "cylindrical"):
            raise A.AssemblyError([f"运动副 {d['joint']}（{j['type']}）不能加驱动"])
        dof = "translation" if j["type"] == "translational" else "rotation"
        m = {"id": f"drive_{d['joint']}"[:64], "joint": d["joint"], "dof": dof}
        if d["kind"] == "speed":
            m["speed"] = float(d["value"])
        else:
            m["function"] = str(d["value"])
        motions.append(m)
    model["motions"] = motions
    if flex_parts:
        from freecad_addon.fc import mbd_flex as MF

        try:
            msgs = list(msgs) + MF.make_flexible(model, body_objects(model, assembly.Document), flex_parts)
        except (MF.FlexSetupError, ValueError) as exc:
            raise A.AssemblyError([str(exc)]) from exc
    return model, msgs


def run(model, base_dir=None):
    """计算；问渠多体动力学免费版用到专业版功能（柔性体、接触、控制器、线性化……）时拒绝，说明是哪一项（ADR-0102 第 4 步）。
    base_dir：模型文件里相对路径（FMU 等）的起点"""
    from analysis.mbd.dae import run as R
    from assist import mbd_edition

    mbd_edition.gate(model)
    return R.run_model(model, base_dir)


def write_report(model, data, out_dir, client=None, lang=None):
    """结果 → 正式报告（Word，有 LibreOffice 时另出 PDF）与出处账、改版记录，另存 model.json、result.json（ADR-0102 第 1 步）；
    给了 client 就让 AI 写解释段落（数字仍由程序填，不合规的段落退回）。问渠多体动力学免费版拒绝（第 4 步）。
    返回 build_docx 的结果，另加 "explanation"：{"paragraphs", "rejected"}"""
    import json
    from pathlib import Path

    from assist import i18n, mbd_edition, mbd_report

    mbd_edition.gate(feature="正式报告")
    lang = lang or i18n.lang()                          # 缺省同界面语言（ADR-0102 第 2 步）
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (out_dir / "model.json").write_text(json.dumps(model, ensure_ascii=False), encoding="utf-8")
    data = json.loads(json.dumps(data))
    ex = mbd_report.explain(data, mbd_report.facts(data), client, mbd_model=model) if client else None
    got = mbd_report.build_docx(model, data, out_dir / "report.docx", explanation=ex, lang=lang)
    got["explanation"] = ex or {"paragraphs": [], "rejected": []}
    return got


def body_objects(model, doc):
    """模型构件 id → FreeCAD 对象（按 source 里记的对象名）"""
    out = {}
    for b in model["bodies"]:
        src = b.get("source", "")
        name = src.split()[1].split("，")[0] if src.startswith("FreeCAD ") else None
        o = doc.getObject(name) if name else None
        if o is not None:
            out[b["id"]] = o
    return out


class Animator:
    """把结果的第 k 帧摆到 FreeCAD 零件上：x(t) = r(t) + A(t)(x₀ − c₀)，新位姿 = T(t)·T₀⁻¹·原位姿"""

    def __init__(self, model, data, doc, *, flex_scale=1.0):
        """柔性构件（实体，带表面网格）画成变形网格 + 应力云图，原零件隐藏；flex_scale 是变形放大倍数（ADR-0097 D8b）"""
        self.data = data
        objs = body_objects(model, doc)
        self.flex = {}
        for b in model["bodies"]:
            f = b.get("flex")
            if f and f.get("type") == "modal" and f.get("surface_triangles") and b["id"] in (data.get("flex") or {}):
                from freecad_addon.fc.mbd_flex import FlexShow

                self.flex[b["id"]] = FlexShow(doc, f, data, b["id"], scale=flex_scale, hide=objs.get(b["id"]))
            elif f and f.get("type") == "nonlinear_beam" and b["id"] in (data.get("flex") or {}):
                from freecad_addon.fc.mbd_flex import BeamShow

                self.flex[b["id"]] = BeamShow(doc, data, b["id"], hide=objs.get(b["id"]))
        self.objs = {k: o for k, o in objs.items() if k not in self.flex}
        self.cm0 = {b["id"]: App.Vector(*b["cm_mm"]) for b in model["bodies"] if "cm_mm" in b}
        self.objs = {k: o for k, o in self.objs.items() if k in self.cm0}
        self.orig = {bid: App.Placement(o.Placement) for bid, o in self.objs.items()}
        self.frames = len(data["times_s"])

    def placement(self, bid, k):
        bd = self.data["bodies"][bid]
        r = App.Vector(*bd["cm_mm"][k])
        e0, e1, e2, e3 = bd["euler_parameters"][k]
        T = App.Placement(r, App.Rotation(e1, e2, e3, e0))
        T0inv = App.Placement(-self.cm0[bid], App.Rotation())
        return T.multiply(T0inv).multiply(self.orig[bid])

    def apply(self, k):
        k = max(0, min(int(k), self.frames - 1))
        for bid, o in self.objs.items():
            if bid in self.data["bodies"]:
                o.Placement = self.placement(bid, k)
        for fs in self.flex.values():
            fs.apply(k)
        return self.data["times_s"][k]

    def restore(self):
        for bid, o in self.objs.items():
            o.Placement = self.orig[bid]
        for fs in self.flex.values():
            fs.remove()
        self.flex = {}


def curves(data) -> dict:
    """能画的曲线：名称 → (单位, 数值列表)"""
    out = {}
    for mid, m in data.get("motions", {}).items():
        out[f"驱动 {mid}（{m['unit']}）"] = (m["unit"], m["effort"])
    for jid, j in data.get("joints", {}).items():
        out[f"运动副 {jid} 反力大小（N）"] = ("N", [math.sqrt(sum(x * x for x in f)) for f in j["force_n"]])
        out[f"运动副 {jid} 反力矩大小（N·m）"] = ("N·m", [math.sqrt(sum(x * x for x in f)) for f in j["torque_n_m"]])
    for bid, b in data.get("bodies", {}).items():
        for k, ax in enumerate("xyz"):
            out[f"{bid} 质心 {ax}（mm）"] = ("mm", [p[k] for p in b["cm_mm"]])
    for mid, m in data.get("measures", {}).items():
        out[f"测量 {mid}（{m['unit']}）"] = (m["unit"], m["values"])
    for cid, c in data.get("contacts", {}).items():
        out[f"接触 {cid} 法向力（N）"] = ("N", c["normal_force_n"])
    if data.get("energy"):
        out["动能（J）"] = ("J", data["energy"]["kinetic_j"])
    return out


def verdict(data) -> list[str]:
    """核查结论，一条一行"""
    names = {"pass": "通过", "fail": "不通过", "unknown": "不判"}
    lines = []
    for v in data.get("verification", []):
        val = v.get("value")
        lines.append(f"{v['name']}：{names.get(v['status'], v['status'])}"
                     + (f"（{val:.3g}" + (f"，限值 {v['limit']:.3g}）" if v.get("limit") is not None else "）")
                        if isinstance(val, (int, float)) else "")
                     + (f"——{v['note']}" if v["status"] != "pass" and v.get("note") else ""))
    return lines
