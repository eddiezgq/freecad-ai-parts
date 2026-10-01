"""方案导出：BOM（CSV / JSON）与系统 JSON（M4a #68）；URDF（M4b #87，ADR-0035，需要系统带 layout）。纯函数。

BOM 每行一个组件型号（同型号多个实例合并数量），带厂商、型号、质量、原厂模型链接、许可，
以及该组件数据引用的全部来源文档，便于追溯。
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from typing import Any

from engine.geometry import Pose, rpy, shortest_arc, unit
from engine.values import capacity, nominal

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


# ---------------------------------------------------------------- URDF（ADR-0035）

MM = 0.001  # URDF 长度单位为米：输出格式的固定比例，内部数据仍为 mm


def _f(x: float) -> str:
    v = round(x, 9)
    return repr(0.0 if v == 0 else v)


def _origin(xyz_mm, q) -> str:
    r = rpy(q)
    return (f'<origin xyz="{" ".join(_f(c * MM) for c in xyz_mm)}" '
            f'rpy="{" ".join(_f(a) for a in r)}"/>')


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("--", "- -")


def urdf(system: dict, resolve: Callable[[str], dict | None]) -> str:
    """由带 layout 的系统生成 URDF。缺布局、缺位姿、缺包络尺寸或没有唯一的带输出法兰的减速器时抛出 ValueError。"""
    from engine.system import load_system

    sys_ = load_system(system, resolve)
    if sys_.poses is None:
        raise ValueError("导出 URDF 需要系统带 layout（各实例的位姿）；请先布局（ADR-0034、ADR-0035）")
    chain = [n for n, c in sys_.instances.items() if c["category"] != "drive"]
    clash = sorted(set(chain) & {"base", "output"})
    if clash:
        raise ValueError(f"实例名 {', '.join(clash)} 与 URDF 的固定连杆名（base、output）冲突，请改名后再导出")
    missing = [n for n in chain if n not in sys_.poses]
    if missing:
        raise ValueError(f"以下实例没有位姿，无法导出 URDF：{', '.join(missing)}")
    reducers = [n for n in chain if sys_.instances[n]["category"] == "reducer"]
    out_port = None
    if len(reducers) == 1:
        out_port = next((p for p in sys_.instances[reducers[0]]["ports"]
                         if p["id"] == "output_flange" and "frame" in p), None)
    if out_port is None:
        raise ValueError("导出 URDF 需要恰好一个带输出法兰（output_flange）的减速器，作为输出关节")

    lines = ['<?xml version="1.0"?>',
             '<!-- 由 freecad-ai-parts 生成（ADR-0035）：长度单位 m，角度单位 rad；未写 inertial（无整件惯性数据） -->',
             f'<robot name="{system["id"]}">', '  <link name="base"/>']
    for name in chain:
        comp = sys_.instances[name]
        mass = nominal(comp.get("params", {}).get("mass_kg"))
        lines.append(f"  <!-- {name}: {_xml_text(comp['id'])}（{_xml_text(comp.get('vendor', ''))} "
                     f"{_xml_text(comp.get('model', ''))}）；质量 {'未知' if mass is None else f'{mass:g} kg'} -->")
        lines.append(f'  <link name="{name}">')
        for i, part in enumerate(comp["envelope"]["parts"]):
            length = nominal(part.get("length_mm"))
            if part["shape"] == "cylinder":
                d = nominal(part.get("diameter_mm"))
                if length is None or d is None:
                    raise ValueError(f"{name} 包络第 {i} 段缺少尺寸")
                geom = f'<cylinder radius="{_f(d / 2 * MM)}" length="{_f(length * MM)}"/>'
            else:
                w, h = nominal(part.get("width_mm")), nominal(part.get("height_mm"))
                if length is None or w is None or h is None:
                    raise ValueError(f"{name} 包络第 {i} 段缺少尺寸")
                geom = f'<box size="{_f(w * MM)} {_f(h * MM)} {_f(length * MM)}"/>'
            origin = _origin((0.0, 0.0, part["z_start_mm"] + length / 2), (1.0, 0.0, 0.0, 0.0))
            for tag in ("visual", "collision"):
                lines.append(f"    <{tag}>{origin}<geometry>{geom}</geometry></{tag}>")
        lines.append("  </link>")
        pose = sys_.poses[name]
        lines.append(f'  <joint name="{name}_mount" type="fixed"><parent link="base"/><child link="{name}"/>'
                     f"{_origin(pose.translation, pose.rotation)}</joint>")
    frame = Pose(shortest_arc((0.0, 0.0, 1.0), unit(tuple(out_port["frame"]["axis"]))),
                 tuple(out_port["frame"]["origin_mm"]))
    joint = (f'  <joint name="output_joint" type="continuous"><parent link="{reducers[0]}"/><child link="output"/>'
             f'{_origin(frame.translation, frame.rotation)}<axis xyz="0 0 1"/></joint>')
    lines += ['  <link name="output"/>', joint, "</robot>", ""]
    return "\n".join(lines)
