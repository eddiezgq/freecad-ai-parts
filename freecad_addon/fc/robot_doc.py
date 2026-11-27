"""「AI 设计整机」的结果放进 FreeCAD 文档（ADR-0115 44.4）：三维装配逐件导入、按零件名命名、着色；BOM 放成表格。

- 装配 STEP 里没有零件名：按 cad-result.json 的零件表，用重心（自制件再加体积）认出每个实体；
- 颜色：外购模组灰色，自制件铝色；有限元做完后支架按结论着色（通过绿、待确认黄、不通过红）；
- BOM：与 out/bom.json 同一份数据（robot_report.bom；龙门是 gantry_report.bom）。
- 龙门（案例 B）：零件表在 out/cad-result.json · cad.parts，装配在 out/cad/assembly.step；直线模组与吸盘灰色，
  门架（横梁、立柱）按门架有限元的变形结论着色。
"""

from __future__ import annotations

import json
from pathlib import Path

from assist.i18n import tr as T

GREY = (0.35, 0.35, 0.38)
ALUMINIUM = (0.80, 0.82, 0.85)
VERDICT = {"pass": (0.20, 0.65, 0.30), "unknown": (0.90, 0.70, 0.10), "fail": (0.80, 0.15, 0.12)}
# 认零件的容差：STEP 读回来后，各版几何内核对 B 样条实体的体积、重心积分精度不同。2026-11-26 在问渠 CAD 1.1.4
# （OCCT 7.8.1）上，同一个装配文件的自制件体积比写出前小 0.27%–0.81%、重心偏 0.005–0.053 mm（面积、包围盒一致）；
# OCCT 7.9.3 上与写出前一致。所以体积按相对 2%、重心按 0.5 mm 认；零件之间重心相距都在毫米以上，不会认错。
COG_TOL_MM = 0.5
VOL_REL_TOL = 0.02


class PlaceError(ValueError):
    pass


def match(solids, parts) -> list[int]:
    """每个零件对应装配里的第几个实体：重心最近（自制件体积也要对得上），一一对应；认不出就报错"""
    taken, out = set(), []
    for p in parts:
        best, dist = None, None
        for k, s in enumerate(solids):
            if k in taken:
                continue
            c = s.CenterOfMass
            d = ((c.x - p["cog_mm"][0]) ** 2 + (c.y - p["cog_mm"][1]) ** 2 + (c.z - p["cog_mm"][2]) ** 2) ** 0.5
            v = p.get("volume_mm3")
            if v and abs(s.Volume - v) > VOL_REL_TOL * v + 0.5:
                continue
            if dist is None or d < dist:
                best, dist = k, d
        if best is None or (p.get("volume_mm3") and dist > COG_TOL_MM) or dist > 5.0:
            raise PlaceError(T(f"装配里认不出 {p['name']}"))
        taken.add(best)
        out.append(best)
    return out


def _color(obj, rgb) -> None:
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    vo.ShapeColor = rgb


def bom_sheet(doc, bom: dict):
    sheet = doc.addObject("Spreadsheet::Sheet", "RobotBOM")
    sheet.Label = T("BOM（AI 设计整机）")
    head = [T("序号"), T("类别"), T("图号 / 零件库编号"), T("名称 / 型号"), T("数量"), T("材料"), T("单件质量 kg")]
    for j, h in enumerate(head):
        sheet.set(f"{chr(65 + j)}1", h)
    rows = [("外购件", r) for r in bom["purchased"]] + [("自制件", r) for r in bom["made"]] \
        + [("紧固件", r) for r in bom.get("fasteners") or []]
    for i, (kind, r) in enumerate(rows, start=2):
        name = r.get("name") or r.get("model") or ""
        if r.get("grip_mm") is not None:
            name += T(f"（夹紧 {r['grip_mm']:g} mm，长度待定）")
        mass = r.get("mass_kg", r.get("mass_kg_each"))
        vals = [i - 1, T(kind), r.get("drawing_no") or r.get("component") or "", name,
                r.get("qty"), r.get("material") or "", "" if mass is None else mass]
        for j, v in enumerate(vals):
            sheet.set(f"{chr(65 + j)}{i}", "" if v is None else (f"'{v}" if isinstance(v, str) else str(v)))
    doc.recompute()
    return sheet, len(rows)


def place(doc, out_dir: str | Path, kind: str = "arm") -> dict:
    """装配与 BOM 放进 doc。返回 {"objects": {零件名: 对象}, "group", "sheet", "bom_rows"}"""
    import Part

    o = Path(out_dir) / "out"
    if kind == "gantry":
        res = json.loads((o / "cad-result.json").read_text(encoding="utf-8"))
        cad = res["cad"]
    else:
        res = None
        cad = json.loads((o / "cad" / "cad-result.json").read_text(encoding="utf-8"))
    shape = Part.read(str(o / "cad" / cad.get("step", "assembly.step")))
    solids = shape.Solids
    if len(solids) != len(cad["parts"]):
        raise PlaceError(T(f"装配里有 {len(solids)} 个实体，零件表有 {len(cad['parts'])} 个"))
    idx = match(solids, cad["parts"])
    group = doc.addObject("App::DocumentObjectGroup", "RobotAssembly")
    group.Label = T("整机装配")
    objs = {}
    for p, k in zip(cad["parts"], idx):
        ob = doc.addObject("Part::Feature", "Part")
        ob.Label = p["name"]
        ob.Shape = solids[k]
        group.addObject(ob)
        _color(ob, GREY if p["kind"] in ("actuator", "module", "gripper") else ALUMINIUM)
        objs[p["name"]] = ob
    fea = o / "fea-result.json"
    if kind == "gantry":
        color_frame(objs, cad["parts"], res)
    elif fea.exists():
        color_by_fea(objs, json.loads(fea.read_text(encoding="utf-8")))
    sheet, n = None, 0
    if (o / "bom.json").exists():
        sheet, n = bom_sheet(doc, json.loads((o / "bom.json").read_text(encoding="utf-8")))
    doc.recompute()
    return {"objects": objs, "group": group, "sheet": sheet, "bom_rows": n}


def color_frame(objs: dict, parts: list[dict], res: dict) -> None:
    """龙门：门架（横梁、立柱）按门架有限元的变形结论着色；没做有限元就不改（铝色）"""
    st = (((res or {}).get("judge") or {}).get("deflection") or {}).get("status")
    if st not in VERDICT:
        return
    for p in parts:
        if p["kind"] == "frame" and p["name"] in objs:
            _color(objs[p["name"]], VERDICT[st])


def color_by_fea(objs: dict, fea: dict) -> None:
    for i in fea.get("items") or []:
        if i["part"] in objs and i.get("status") in VERDICT:
            _color(objs[i["part"]], VERDICT[i["status"]])
