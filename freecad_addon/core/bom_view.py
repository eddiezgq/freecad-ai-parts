"""BOM 面板的整理（ADR-0051 第 2 条）：由当前场景组成系统，列出物料清单并导出。纯函数。

系统组成规则与校验窗口相同（live_check.system_from_layout）；行与导出内容来自 engine/export.py，
与 export_system 工具的 content 一致。质量缺失时总质量未知，不估算。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

from engine import export
from freecad_addon.core.browser import CATEGORIES
from freecad_addon.core.live_check import system_from_layout

HEADERS = ["#", "品类", "厂商", "型号", "数量", "实例", "单件质量", "合计质量", "来源文档", "参数全部已复核", "许可",
           "原厂 CAD"]
FORMATS = {"csv": ("bom_csv", "-bom.csv"), "json": ("bom_json", "-bom.json")}


def _system(layout: Mapping, lookup: Callable[[str], dict | None]) -> dict:
    system, _ = system_from_layout(layout, lookup)
    return system


def bom(layout: Mapping, lookup: Callable[[str], dict | None]) -> dict:
    """{rows, total_mass_kg, count}；场景为空时 rows 为空、总质量为 0。"""
    if not layout.get("instances"):
        return {"rows": [], "total_mass_kg": 0.0, "count": 0}
    out = export.bom_json(_system(layout, lookup), lookup)
    return {"rows": out["rows"], "total_mass_kg": out["total_mass_kg"],
            "count": sum(r["quantity"] for r in out["rows"])}


def _kg(v: float | None) -> str:
    return "未知" if v is None else f"{v:g} kg"


def cells(row: Mapping) -> list[str]:
    return [str(row["item"]), CATEGORIES.get(row["category"], row["category"]), row["vendor"], row["model"],
            str(row["quantity"]), "、".join(row["instances"]), _kg(row["unit_mass_kg"]), _kg(row["total_mass_kg"]),
            "、".join(row["source_docs"]) or "—", "是" if row["all_params_reviewed"] else "否", row["license"],
            row.get("vendor_cad_url") or "—"]


def total_text(b: Mapping) -> str:
    if not b["rows"]:
        return "场景中还没有零件"
    mass = b["total_mass_kg"]
    return f"共 {len(b['rows'])} 种、{b['count']} 件；总质量 {'未知（有零件缺质量数据）' if mass is None else f'{mass:g} kg'}"


def export_text(layout: Mapping, lookup: Callable[[str], dict | None], fmt: str) -> tuple[str, str]:
    """(建议文件名, 文本)。fmt 为 csv 或 json；内容与 export_system 的 bom_csv / bom_json 相同。"""
    if fmt not in FORMATS:
        raise ValueError(f"格式须为 {'、'.join(FORMATS)} 之一")
    if not layout.get("instances"):
        raise ValueError("场景中还没有零件")
    system = _system(layout, lookup)
    _, suffix = FORMATS[fmt]
    if fmt == "csv":
        return system["id"] + suffix, export.bom_csv(system, lookup)
    return system["id"] + suffix, json.dumps(export.bom_json(system, lookup), ensure_ascii=False, indent=2)
