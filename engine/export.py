"""方案导出（M4a #68）：BOM（CSV / JSON）与系统 JSON。纯函数。URDF 需要布局结果，在 M4b 实现。

BOM 每行一个组件型号（同型号多个实例合并数量），带厂商、型号、质量、原厂模型链接、许可，
以及该组件数据引用的全部来源文档，便于追溯。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import Any

from engine.values import capacity

EXPORT_FORMAT = "fap-export/1"
BOM_COLUMNS = ("item", "component_id", "category", "vendor", "model", "quantity", "instances", "unit_mass_kg",
               "total_mass_kg", "license", "vendor_cad_url", "source_docs", "all_params_reviewed")


def _source_docs(node: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        src = node.get("source")
        if isinstance(src, dict) and isinstance(src.get("doc"), str):
            found.add(src["doc"])
        for v in node.values():
            found |= _source_docs(v)
    elif isinstance(node, list):
        for v in node:
            found |= _source_docs(v)
    return found


def bom_rows(system: dict, resolve: Callable[[str], dict | None]) -> list[dict]:
    groups: dict[str, list[str]] = {}
    for c in system["components"]:
        groups.setdefault(c["component"], []).append(c["instance"])
    rows = []
    for n, (cid, instances) in enumerate(groups.items(), start=1):
        comp = resolve(cid)
        if comp is None:
            raise ValueError(f"找不到组件 {cid}")
        mass = capacity(comp["params"].get("mass_kg"))
        rows.append({
            "item": n, "component_id": cid, "category": comp["category"], "vendor": comp["vendor"],
            "model": comp["model"], "quantity": len(instances), "instances": instances,
            "unit_mass_kg": mass, "total_mass_kg": None if mass is None else mass * len(instances),
            "license": comp["license"], "vendor_cad_url": comp.get("vendor_cad_url"),
            "source_docs": sorted(_source_docs(comp)),
            "all_params_reviewed": all(pv.get("reviewed") is True for pv in comp["params"].values()),
        })
    return rows


def bom_json(system: dict, resolve: Callable[[str], dict | None]) -> dict:
    rows = bom_rows(system, resolve)
    masses = [r["total_mass_kg"] for r in rows]
    return {
        "format": EXPORT_FORMAT, "kind": "bom", "system": system["id"], "rows": rows,
        "total_mass_kg": None if any(m is None for m in masses) else round(sum(masses), 9),
        "note": "质量缺失时总质量为空；source_docs 为该组件数据引用的来源文档（data/sources.yaml）",
    }


def bom_csv(system: dict, resolve: Callable[[str], dict | None]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(BOM_COLUMNS)
    for r in bom_rows(system, resolve):
        w.writerow(["" if r[k] is None else ";".join(r[k]) if isinstance(r[k], list) else r[k] for k in BOM_COLUMNS])
    return buf.getvalue()


def system_json(system: dict, resolve: Callable[[str], dict | None], report: dict) -> dict:
    """系统、校验报告与所用组件的完整数据，一个文件即可复现校验。"""
    ids = list(dict.fromkeys(c["component"] for c in system["components"]))
    return {"format": EXPORT_FORMAT, "kind": "system", "system": system, "report": report,
            "components": {cid: resolve(cid) for cid in ids}}
