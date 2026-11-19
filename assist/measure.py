"""通道 C：从企业的三维模型（STEP）量出自制件的数据（ADR-0099 41.4）。

尺寸一律由代码从 B-rep 上量，AI 不给尺寸：
- 先查模型有效（能导入 FreeCAD 时用 Part 的几何检查；不能时至少要求是实体、体积为正）；无效的不测，说哪里坏了；
- 外形包络（长宽高）、最大回转直径、体积、表面积；给了材料（材料库 id）就按密度算质量，没给只给体积；
- 回转件的轴段：与主轴线同轴的外圆柱面，按轴向位置从一端排起（直径、长度、起点）；
- 孔组：同径平行孔，轴心在一个圆上（分布圆直径、孔数、孔径）。复用 `assist.features.recognize` 的面识别。

AI 只做两件事（另由人确认）：判断零件类型、给端口命名的建议；本模块只给它量好的数据，不收它的数字。

测量值写成企业库的参数值：method = measured，source.doc 是企业库里登记的模型文件（带 SHA-256），
source.note 写测量方法与容差。纯函数部分（排段、成组件）不联网、不调用 AI。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np

DIAMETER_TOL_MM = 0.001                 # 量出的直径的舍入（B-rep 精确圆柱，拟合误差远小于此）
LENGTH_TOL_MM = 0.01
PART_KINDS = ("shaft", "crank", "cam", "eccentric", "gear", "pulley", "lever", "link", "bracket", "housing", "plate",
              "pin", "bushing", "other")
METHOD_NOTE = "从三维模型由代码测量（assist.measure，B-rep 面识别）"


class GeometryInvalid(ValueError):
    """模型无效：不测"""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_geometry(step_path: str | Path) -> dict:
    """几何检查。能导入 FreeCAD 时用 Part 的检查（与问渠 CAD 的“检查几何”同一套 OCC 检查）；否则返回 checked=False"""
    try:
        import Part  # type: ignore[import-not-found]
    except ImportError:
        return {"checked": False, "note": "没有 FreeCAD：只做了“是实体、体积为正”的检查"}
    shape = Part.read(str(step_path))
    problems = []
    if not shape.Solids:
        problems.append("没有实体（只有曲面或线框）")
    if not shape.isValid():
        try:
            shape.check(True)
        except Exception as ex:  # noqa: BLE001 — Part 的检查以异常报告问题
            problems.append(str(ex).strip().splitlines()[0] if str(ex).strip() else "OCC 检查报告几何无效")
        else:
            problems.append("OCC 检查报告几何无效")
    for s in shape.Solids:
        if s.Volume <= 0:
            problems.append("有实体体积不为正（面的朝向反了？）")
        if not s.isClosed():
            problems.append("有实体不封闭")
    return {"checked": True, "valid": not problems, "problems": problems}


def _span(face: dict, axis: np.ndarray) -> tuple[float, float]:
    from assist.features import _corners

    e = [float(np.dot(np.array(c), axis)) for c in _corners(face["bbox"])]
    return min(e), max(e)


def segments(features: list[dict], faces: list[dict]) -> tuple[list[dict], dict | None]:
    """回转件的轴段：取总长最长的一组同轴外圆柱面当主轴线，按轴向位置从一端排起（纯函数）"""
    from assist.features import _coaxial

    shafts = [f for f in features if f.get("type") == "shaft_segment"]
    if not shafts:
        return [], None
    by_id = {f["id"]: f for f in faces}
    groups: list[list[dict]] = []
    for s in shafts:
        rep = by_id[s["faces"][0]]
        for g in groups:
            if _coaxial(by_id[g[0]["faces"][0]], rep):
                g.append(s)
                break
        else:
            groups.append([s])
    main = max(groups, key=lambda g: sum(s["length_mm"] for s in g))
    axis = np.array(main[0]["axis"], float)
    axis /= np.linalg.norm(axis)
    if axis[int(np.argmax(np.abs(axis)))] < 0:
        axis = -axis                                      # 轴线方向统一朝坐标正向：从坐标小的一端排起
    rows = []
    for s in main:
        lo = min(_span(by_id[i], axis)[0] for i in s["faces"])
        hi = max(_span(by_id[i], axis)[1] for i in s["faces"])
        rows.append({"diameter_mm": s["diameter_mm"], "lo": lo, "hi": hi})
    rows.sort(key=lambda r: r["lo"])
    origin = rows[0]["lo"]
    out = [{"diameter_mm": round(r["diameter_mm"], 3), "length_mm": round(r["hi"] - r["lo"], 2),
            "start_mm": round(r["lo"] - origin, 2)} for r in rows]
    return out, {"axis": [round(float(x), 6) for x in axis], "origin_mm": round(origin, 3) + 0.0}


def bores(features: list[dict], faces: list[dict], axis_info: dict | None) -> list[dict]:
    """与主轴线同轴的内孔（空心轴的通孔、轴端孔）：[{diameter_mm, length_mm, start_mm}]，起点与轴段同一原点（纯函数）"""
    from assist.features import _coaxial

    shafts = [f for f in features if f.get("type") == "shaft_segment"]
    if axis_info is None or not shafts:
        return []
    by_id = {f["id"]: f for f in faces}
    axis = np.array(axis_info["axis"], float)
    ref = max(shafts, key=lambda f: f["length_mm"])               # 主轴线上最长的一段外圆作参照
    out = []
    for b in (f for f in features if f.get("type") == "bore"):
        if not _coaxial(by_id[ref["faces"][0]], by_id[b["faces"][0]]):
            continue
        lo = min(_span(by_id[i], axis)[0] for i in b["faces"])
        hi = max(_span(by_id[i], axis)[1] for i in b["faces"])
        out.append({"diameter_mm": round(b["diameter_mm"], 3), "length_mm": round(hi - lo, 2),
                    "start_mm": round(lo - axis_info["origin_mm"], 2) + 0.0})
    return sorted(out, key=lambda r: r["start_mm"])


def measure(step_path: str | Path, material: str | None = None) -> dict:
    """量一个零件。返回尺寸、质量、轴段、孔组与检查结果；模型无效时抛 GeometryInvalid"""
    from assist.features import recognize

    step_path = Path(step_path)
    check = check_geometry(step_path)
    if check.get("checked") and not check["valid"]:
        raise GeometryInvalid("模型无效，不测：" + "；".join(check["problems"]))
    try:
        r = recognize(str(step_path))
    except ValueError as ex:
        raise GeometryInvalid(f"模型无效，不测：{ex}") from ex
    if r["volume_mm3"] <= 0:
        raise GeometryInvalid("模型无效，不测：体积不为正")
    bb = r["bbox_mm"]
    dims = sorted((bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]), reverse=True)
    segs, axis = segments(r["features"], r["faces"])
    out: dict[str, Any] = {
        "file": step_path.name, "sha256": sha256_file(step_path), "geometry_check": check,
        "envelope_mm": {"length": round(dims[0], 2), "width": round(dims[1], 2), "height": round(dims[2], 2)},
        "volume_mm3": round(r["volume_mm3"], 1),
        "surface_area_mm2": round(sum(f["area_mm2"] for f in r["faces"]), 1),
        "segments": segs, "axis": axis, "bores": bores(r["features"], r["faces"], axis),
        "hole_patterns": [{"count": f["count"], "diameter_mm": f["diameter_mm"], "pcd_mm": f["pcd_mm"]}
                          for f in r["features"] if f["type"] == "hole_pattern"],
        "features_text": r["text"],
    }
    if segs:
        out["max_diameter_mm"] = max(s["diameter_mm"] for s in segs)
    if material:
        from analysis.common import materials

        m = materials.get(material)
        rho = m.get("density_kg_m3")
        if rho is None:
            out["mass_note"] = f"材料 {material} 没有密度，只给体积"
        else:
            out["material"] = material
            out["density_kg_m3"] = rho
            out["mass_kg"] = round(r["volume_mm3"] * 1e-9 * rho, 4)
    return out


# ---------------------------------------------------------------- 成组件（纯函数）


def _slug(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t or "x"


def _measured(value, doc: str, what: str, tol: str) -> dict:
    return {"value": value, "source": {"doc": doc, "note": f"{METHOD_NOTE}：{what}；{tol}"},
            "method": "measured", "confidence": 1, "reviewed": False}


def to_component(meas: dict, *, enterprise: str, drawing_no: str, doc: str, part_kind: str | None = None,
                 kind_doc_note: str | None = None, vendor_slug: str | None = None) -> dict:
    """量好的数据 → 企业库的自制件组件（未复核；人确认后由企业库写入）。

    doc：企业库里登记的模型文件 id（src-…，登记时记了 SHA-256）。part_kind 由人确认（AI 可以先提议）。
    """
    if part_kind is not None and part_kind not in PART_KINDS:
        raise ValueError(f"零件类型 {part_kind!r} 不在清单里：{'、'.join(PART_KINDS)}")
    dtol = f"直径按 {DIAMETER_TOL_MM} mm 舍入"
    ltol = f"长度按 {LENGTH_TOL_MM} mm 舍入"
    p: dict[str, dict] = {}
    env = meas["envelope_mm"]
    p["envelope_length_mm"] = _measured(env["length"], doc, "包围盒最长边", ltol)
    p["envelope_width_mm"] = _measured(env["width"], doc, "包围盒次长边", ltol)
    p["envelope_height_mm"] = _measured(env["height"], doc, "包围盒最短边", ltol)
    p["volume_mm3"] = _measured(meas["volume_mm3"], doc, "实体体积", "按 0.1 mm³ 舍入")
    p["surface_area_mm2"] = _measured(meas["surface_area_mm2"], doc, "全部面的面积之和", "按 0.1 mm² 舍入")
    if "max_diameter_mm" in meas:
        p["max_diameter_mm"] = _measured(meas["max_diameter_mm"], doc, "主轴线上最大外圆", dtol)
    for i, s in enumerate(meas["segments"][:99], start=1):
        where = f"第 {i} 段外圆（从轴的一端起）"
        p[f"segment_{i}_diameter_mm"] = _measured(s["diameter_mm"], doc, where + "直径", dtol)
        p[f"segment_{i}_length_mm"] = _measured(s["length_mm"], doc, where + "长度", ltol)
        p[f"segment_{i}_start_mm"] = _measured(s["start_mm"], doc, where + "起点", ltol)
    for i, h in enumerate(meas["hole_patterns"][:99], start=1):
        p[f"holes_{i}_count"] = _measured(int(h["count"]), doc, f"第 {i} 组孔孔数", "计数")
        p[f"holes_{i}_diameter_mm"] = _measured(h["diameter_mm"], doc, f"第 {i} 组孔孔径", dtol)
        p[f"holes_{i}_pcd_mm"] = _measured(h["pcd_mm"], doc, f"第 {i} 组孔分布圆直径（最小二乘拟合）", dtol)
    if "mass_kg" in meas:
        p["material"] = {"value": meas["material"], "source": {"doc": doc, "note": "材料由人指定（材料库 id）"},
                         "method": "manual", "confidence": 1, "reviewed": False}
        p["mass_kg"] = {"value": meas["mass_kg"], "source": {
            "formula": f"volume_mm3 × 1e-9 × density_kg_m3（{meas['material']}：{meas['density_kg_m3']} kg/m³）",
            "doc": doc, "note": "体积从模型测量，密度取材料库"}, "method": "computed", "confidence": 1, "reviewed": False}
    if part_kind is not None:
        p["part_kind"] = {"value": part_kind, "source": {"doc": doc, "note": kind_doc_note or "零件类型由人确认"},
                          "method": "manual", "confidence": 1, "reviewed": False}
    if meas["segments"]:
        parts = [{"shape": "cylinder", "z_start_mm": s["start_mm"], "label": f"segment_{i}",
                  "length_mm": _measured(s["length_mm"], doc, f"第 {i} 段长度", ltol),
                  "diameter_mm": _measured(s["diameter_mm"], doc, f"第 {i} 段直径", dtol)}
                 for i, s in enumerate(meas["segments"], start=1)]
    else:
        parts = [{"shape": "box", "z_start_mm": 0, "label": "body",
                  "length_mm": _measured(env["height"], doc, "包围盒最短边", ltol),
                  "width_mm": _measured(env["length"], doc, "包围盒最长边", ltol),
                  "height_mm": _measured(env["width"], doc, "包围盒次长边", ltol)}]
    return {"id": f"custom_part.{vendor_slug or _slug(enterprise)}.{_slug(drawing_no)}", "category": "custom_part",
            "vendor": enterprise, "model": drawing_no, "status": "active", "license": "enterprise",
            "params": p, "ports": [], "envelope": {"parts": parts},
            "note": f"模型 {meas['file']}（SHA-256 {meas['sha256']}）；{METHOD_NOTE}"}


# ---------------------------------------------------------------- AI 提议零件类型（只提议，人确认）

KIND_PROMPT_VERSION = "part-kind/1"
KIND_TOOL = {"name": "propose_part_kind", "description": "提交零件类型与端口命名建议", "input_schema": {
    "type": "object", "properties": {
        "part_kind": {"enum": list(PART_KINDS)}, "reason": {"type": "string"},
        "ports": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "string"}, "feature": {"type": "string", "description": "对应特征清单里的哪一条（原文）"}},
            "required": ["id", "feature"]}}},
    "required": ["part_kind", "reason"]}}


def kind_request(meas: dict, name: str, *, model: str) -> dict:
    return {"model": model, "prompt_version": KIND_PROMPT_VERSION,
            "system": "你在帮机械企业整理自制件。根据名称和程序量出的特征清单判断零件类型，并建议哪些特征要做成端口（与别的零件配合的面）。"
                      "不要给任何尺寸。必须调用一次工具 propose_part_kind 提交结果。",
            "user": f"名称：{name}\n特征清单：\n{meas['features_text']}", "tool": KIND_TOOL}


def check_kind(proposal: Any, meas: dict) -> dict:
    """核对 AI 的零件类型提议：类型在清单里；端口建议对应的特征必须原样在特征清单里。都只是提议"""
    if not isinstance(proposal, dict) or proposal.get("part_kind") not in PART_KINDS:
        return {"part_kind": None, "rejected": ["零件类型不在清单里，未采用"], "ports": []}
    ports, rejected = [], []
    for p in proposal.get("ports") or []:
        if isinstance(p, dict) and isinstance(p.get("id"), str) and re.fullmatch(r"[a-z][a-z0-9_]{0,40}", p["id"]) \
                and isinstance(p.get("feature"), str) and p["feature"].strip() and p["feature"].strip() in meas["features_text"]:
            ports.append({"id": p["id"], "feature": p["feature"].strip()})
        else:
            rejected.append(f"端口建议 {p!r} 对不上特征清单，未采用")
    return {"part_kind": proposal["part_kind"], "reason": str(proposal.get("reason") or ""), "ports": ports,
            "rejected": rejected}

