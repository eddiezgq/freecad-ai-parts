"""把 AI 设计的阶梯轴放进 FreeCAD 文档（ADR-0100 42.4，§3.1 第 2 条）：三维模型、TechDraw 工程图、BOM 表。

- 三维模型：42.3 生成并回读一致的 STEP，导入为 Part 特征；
- 工程图：A3 图框，主视图（轴线水平）；尺寸由代码加——各段直径（竖直距离）、各段长度与总长（水平距离），
  引用视图上的顶点，按设计数据找；加完后读回每个尺寸的值与设计数据核对（差 > 0.01 mm 就报错，不交一张错图）；
  台阶圆角写在注释里；标题栏写名称、图号、材料、“AI 设计，代码校核”，确认人一栏空着（入库确认后才有）；
- BOM：表格（Spreadsheet）一行一个物料，与 42.3 的 bom.json 同一份数据。

要在 FreeCAD 里运行（TechDraw 的投影要界面线程的事件循环）。
"""

from __future__ import annotations

import time
from itertools import pairwise
from pathlib import Path

import FreeCAD

from assist.i18n import tr as T

TEMPLATES = ("A3_Landscape_ISO5457_minimal.svg", "A3_Landscape_blank.svg")
DIM_TOL_MM = 0.01
SCALES = (1.0, 0.5, 0.4, 0.25, 0.2)
TEXTS = {"approval_person": "", "general_tolerances": "", "legal_owner_1": "", "legal_owner_2": "", "legal_owner_3": "",
         "legal_owner_4": "", "revision_index": "", "sheet_number": "1 / 1"}


class DrawingError(RuntimeError):
    pass


def _process_events() -> None:
    try:
        from PySide import QtCore

        QtCore.QCoreApplication.processEvents()
    except Exception:  # noqa: BLE001 — 没有 Qt 时就只等
        return


def _wait(view, timeout_s: float = 30.0) -> None:
    t0 = time.monotonic()
    while not view.getVisibleEdges():
        if time.monotonic() - t0 > timeout_s:
            raise DrawingError("工程图的视图没有算出来（TechDraw 投影超时）")
        _process_events()
        time.sleep(0.05)
        view.recompute()


def _vertices(view) -> list[tuple[int, float, float]]:
    out, i = [], 0
    while True:
        try:
            v = view.getVertexByIndex(i)
        except Exception:  # noqa: BLE001 — 越界就是取完了
            break
        if v is None:
            break
        out.append((i, float(v.Point.x), float(v.Point.y)))
        i += 1
    return out


def _find(verts, x, y, tol=1e-3) -> int:
    best = min(verts, key=lambda v: (v[1] - x) ** 2 + (v[2] - y) ** 2)
    if abs(best[1] - x) > tol or abs(best[2] - y) > tol:
        raise DrawingError(f"视图上找不到顶点 ({x:.3f}, {y:.3f})")
    return best[0]


def template_file() -> Path:
    """A3 横向图框。各版本 FreeCAD 放模板的地方不同（1.0 在 Templates/ 下，1.1 有子目录），按文件名在模板目录里找；
    找不到首选的，用 TechDraw 设置里的缺省模板，再不行用任意一个 A3 横向模板（2026-11-18 问渠 CAD 1.1.4 上找不到）"""
    roots = [Path(FreeCAD.getResourceDir()) / "Mod" / "TechDraw" / "Templates",
             Path(FreeCAD.getResourceDir()) / "share" / "Mod" / "TechDraw" / "Templates"]
    roots = [r for r in roots if r.is_dir()]
    for name in TEMPLATES:
        for r in roots:
            hit = sorted(r.rglob(name))
            if hit:
                return hit[0]
    pref = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files").GetString("TemplateFile", "")
    if pref and Path(pref).is_file():
        return Path(pref)
    for r in roots:
        hit = sorted(f for f in r.rglob("*.svg") if "A3" in f.name and "Landscape" in f.name)
        if hit:
            return hit[0]
    raise DrawingError(T(f"找不到 TechDraw 的图框模板（找过：{'；'.join(str(r) for r in roots) or FreeCAD.getResourceDir()}）"))


def _scale(total: float) -> float:
    return next((s for s in SCALES if total * s <= 330), SCALES[-1])


def drawing(doc, part, segs: list[dict], *, name: str, drawing_no: str, material: str, bore: float = 0.0,
            notes: list[str] | None = None):
    """建工程图页并加尺寸。bore > 0（空心轴）时加一个端视图标内孔直径；notes 写进技术要求。返回 (page, [{"what", "design", "drawing"}])"""
    import TechDraw  # noqa: F401 — 注册 TechDraw 的文档对象

    from assist import shaft_model

    rs = shaft_model.runs(segs)
    total = rs[-1]["z1"]
    scale = _scale(total)
    page = doc.addObject("TechDraw::DrawPage", "AiShaftDrawing")
    page.Label = T(f"{name} 工程图")
    tpl = doc.addObject("TechDraw::DrawSVGTemplate", "AiShaftTemplate")
    tpl.Template = str(template_file())
    page.Template = tpl
    texts = dict(tpl.EditableTexts)
    want = {**TEXTS, "title": name, "identification_number": drawing_no or "—", "part_material": material or "",
            "creator": T("AI 设计，代码校核"), "document_type": T("零件图"), "scale": f"1 : {1 / scale:g}",
            "language_code": "ZH" if T("零件图") == "零件图" else "EN"}
    tpl.EditableTexts = {k: want.get(k, v) for k, v in texts.items()}
    view = doc.addObject("TechDraw::DrawViewPart", "AiShaftView")
    page.addView(view)
    view.Source = [part]
    view.Direction = FreeCAD.Vector(0, -1, 0)
    view.XDirection = FreeCAD.Vector(0, 0, 1)
    view.Scale = scale
    view.X, view.Y = 210.0, 170.0
    doc.recompute()
    _wait(view)
    verts = _vertices(view)
    xs = [v[1] for v in verts]
    x0, k = min(xs), (max(xs) - min(xs)) / total           # 视图坐标 = (z → x0 + k·z, 半径 → k·r)

    def at(z, r):
        return _find(verts, x0 + k * z, k * r, tol=1e-3 * max(1.0, k))

    dims, checks = [], []
    rmax = max(r["d"] for r in rs) / 2

    def dim(kind, a, b, value, what, x, y):
        d = doc.addObject("TechDraw::DrawViewDimension", "AiShaftDim")
        d.Type = kind
        d.MeasureType = "Projected"
        d.References2D = [(view, f"Vertex{a}"), (view, f"Vertex{b}")]
        if kind == "DistanceY":
            d.FormatSpec = "⌀%.4w"
        page.addView(d)
        d.X, d.Y = x, y                                    # 尺寸数字的位置（视图坐标）
        dims.append((d, value, what))

    for i, r in enumerate(rs):                             # 直径：圆柱面起点的上下两个顶点；数字写在该段中间，短段交替放上方
        z = r["z0"] + r["r_left"]
        zm = (r["z0"] + r["z1"]) / 2
        y = 0.0 if r["z1"] - r["z0"] >= 25 else k * rmax + 8 + 7 * (i % 2)
        dim("DistanceY", at(z, r["d"] / 2), at(z, -r["d"] / 2), r["d"], T(f"直径 Ø{r['d']:g}"), x0 + k * zm, y)
    bounds = [0.0] + [r["z1"] for r in rs]
    for i, (za, zb) in enumerate(pairwise(bounds)):
        ra = rs[i]["d"] / 2 if i == 0 else max(rs[i - 1]["d"], rs[i]["d"]) / 2
        rb = rs[i]["d"] / 2 if i == len(rs) - 1 else max(rs[i]["d"], rs[i + 1]["d"]) / 2
        dim("DistanceX", at(za, ra), at(zb, rb), zb - za, T(f"长度 {zb - za:g}"), x0 + k * (za + zb) / 2, -(k * rmax + 12 + 9 * (i % 2)))
    dim("DistanceX", at(0.0, rs[0]["d"] / 2), at(total, rs[-1]["d"] / 2), total, T(f"总长 {total:g}"), x0 + k * total / 2, -(k * rmax + 36))
    if bore > 0:                                           # 内孔在主视图里是不可见轮廓，取不到顶点：加端视图，按圆标直径
        end = doc.addObject("TechDraw::DrawViewPart", "AiShaftEndView")
        page.addView(end)
        end.Source = [part]
        end.Direction = FreeCAD.Vector(0, 0, -1)
        end.XDirection = FreeCAD.Vector(1, 0, 0)
        end.Scale = scale
        end.X, end.Y = min(390.0, 210.0 + scale * (total / 2 + rmax) + 30), 170.0
        doc.recompute()
        _wait(end)
        edge = None
        for i in range(64):
            try:
                e = end.getEdgeByIndex(i)
            except Exception:  # noqa: BLE001 — 越界就是取完了
                break
            if e is None:
                break
            if abs(getattr(e.Curve, "Radius", -1.0) - scale * bore / 2) < 1e-3 * max(1.0, scale) or abs(getattr(e.Curve, "Radius", -1.0) - bore / 2) < 1e-3:
                edge = i
                break
        if edge is None:
            raise DrawingError(T(f"端视图上找不到内孔 Ø{bore:g} 的圆"))
        d = doc.addObject("TechDraw::DrawViewDimension", "AiShaftDim")
        d.Type = "Diameter"
        d.MeasureType = "Projected"
        d.References2D = [(end, f"Edge{edge}")]
        page.addView(d)
        dims.append((d, bore, T(f"内孔 Ø{bore:g}")))
    doc.recompute()
    for d, value, what in dims:
        got = float(d.getRawValue())                       # 模型尺寸（与比例无关）
        checks.append({"what": what, "design": value, "drawing": round(got, 4)})
        if abs(got - value) > DIM_TOL_MM:
            raise DrawingError(T(f"工程图尺寸与设计不符：{what}，图上 {got:g}"))
    steps = [f"z {a['z1']:g}：R{(a['r_right'] or b['r_left']):g}" for a, b in pairwise(rs) if (a["r_right"] or b["r_left"])]
    if len(steps) < len(rs) - 1:
        steps.append(T("其余台阶不倒圆"))
    note = doc.addObject("TechDraw::DrawViewAnnotation", "AiShaftNotes")
    lines = ["，".join(steps[i:i + 2]) for i in range(0, len(steps), 2)]   # 两个一行，免得注释超出图纸被缩小
    extra = [f"{i}. {T(x)}" for i, x in enumerate(notes or [], 3)]
    note.Text = [T("技术要求："), T("1. 台阶圆角：") + (lines[0] if lines else ""), *["   " + x for x in lines[1:]],
                 T("2. 尺寸由程序按设计数据标注，模型已回读核对"), *extra]
    page.addView(note)
    width = max(sum(4.0 if ord(ch) > 255 else 2.3 for ch in str(x)) for x in note.Text)   # 注释按中心定位：左边留在图框里
    note.X, note.Y = max(120.0, 30.0 + width / 2), 75.0
    if hasattr(note, "TextSize"):
        note.TextSize = 4.0
    doc.recompute()
    return page, checks


def bom_sheet(doc, rows: list[dict]):
    sheet = doc.addObject("Spreadsheet::Sheet", "AiShaftBOM")
    sheet.Label = T("BOM（AI 设计）")
    head = [T("序号"), T("类别"), T("图号 / 组件"), T("名称 / 型号"), T("数量"), T("材料"), T("质量 kg")]
    for j, h in enumerate(head):
        sheet.set(f"{chr(65 + j)}1", h)
    for i, r in enumerate(rows, start=2):
        vals = [r.get("item"), T({"custom_part": "自制件", "bearing": "轴承"}.get(r.get("kind"), r.get("kind", ""))),
                r.get("drawing_no") or r.get("component"), r.get("name") or f"{r.get('vendor', '')} {r.get('model', '')}".strip(),
                r.get("qty"), r.get("material", ""), r.get("mass_kg", "")]
        for j, v in enumerate(vals):
            sheet.set(f"{chr(65 + j)}{i}", "" if v is None else (f"'{v}" if isinstance(v, str) else str(v)))
    doc.recompute()
    return sheet


def place(doc, run_out: dict, segs: list[dict], *, name: str, drawing_no: str = "", bore: float = 0.0,
          notes: list[str] | None = None) -> dict:
    """三维模型 + 工程图 + BOM 放进 doc。返回 {"part", "page", "sheet", "dimension_checks"}"""
    import Part

    gen = run_out.get("model") or {}
    if gen.get("readback") != "pass":
        raise DrawingError(T("模型没有生成或回读不一致，不放进文档"))
    out = Path(run_out["out_dir"])
    part = doc.addObject("Part::Feature", "AiShaft")
    part.Label = name
    part.Shape = Part.read(str(out / gen["step"]))
    doc.recompute()
    material = run_out["result"]["conditions"].get("material") or ""
    page, checks = drawing(doc, part, segs, name=name, drawing_no=drawing_no, material=material, bore=bore, notes=notes)
    sheet = bom_sheet(doc, gen.get("bom") or [])
    return {"part": part, "page": page, "sheet": sheet, "dimension_checks": checks}
