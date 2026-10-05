"""库浏览器的筛选与详情（ADR-0048 第 3 条）。纯函数，不依赖 FreeCAD 与 Qt。

- rows：按品类、文字、参数范围筛选，返回列表行（厂商、型号、主要参数）
- detail：一个组件的参数与端口规格，逐项写出值、单位、工况、来源页码与复核状态
- instance_name：放入布局时按品类自动编号的实例名（motor、motor2……）
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

CATEGORIES = {"servo_motor": "电机", "reducer": "减速器", "drive": "驱动器", "bearing": "轴承", "adapter": "转接件"}
INSTANCE_BASE = {"servo_motor": "motor", "reducer": "reducer", "drive": "drive", "bearing": "bearing",
                 "adapter": "adapter"}

# 列表中显示的主要参数：(标签, 路径)；路径为 params/<名> 或 ports/<端口>/<名>
KEY_FIELDS: dict[str, list[tuple[str, str]]] = {
    "servo_motor": [("额定扭矩", "params/rated_torque_nm"), ("额定转速", "params/rated_speed_rpm"),
                    ("额定功率", "params/rated_power_w"), ("轴径", "ports/shaft/diameter_mm")],
    "reducer": [("减速比", "params/ratio"), ("额定扭矩", "params/rated_torque_nm"),
                ("输入孔", "ports/input_bore/diameter_mm"), ("质量", "params/mass_kg")],
    "drive": [("额定电流", "ports/motor_out/rated_current_a"), ("峰值电流", "ports/motor_out/peak_current_a"),
              ("供电电压", "ports/power_in/voltage_v"), ("总线", "ports/bus/protocol")],
    "bearing": [("内径", "ports/inner/diameter_mm"), ("外径", "ports/outer/diameter_mm"),
                ("宽度", "params/width_mm")],
    "adapter": [],
}

UNITS = (("_kgm2", "kg·m²"), ("_nm_per_arcmin", "N·m/arcmin"), ("_nm_per_a", "N·m/A"), ("_nm", "N·m"),
         ("_rpm", "rpm"), ("_kg", "kg"), ("_mm", "mm"), ("_w", "W"), ("_v", "V"), ("_a", "A"),
         ("_arcmin", "arcmin"), ("_n", "N"), ("_c", "°C"))

PORT_KINDS = {"mechanical": "机械", "electrical": "电源", "signal": "信号"}


def unit_of(name: str) -> str:
    return next((u for suffix, u in UNITS if name.endswith(suffix)), "")


def lookup(comp: Mapping, path: str) -> dict | None:
    """按 params/<名> 或 ports/<端口>/<名> 取参数值对象。"""
    parts = path.split("/")
    if parts[0] == "params":
        return comp.get("params", {}).get(parts[1])
    port = next((p for p in comp.get("ports", []) if p.get("id") == parts[1]), None)
    return None if port is None else port.get("spec", {}).get(parts[2])


def number(pv: Mapping | None) -> tuple[float | None, float | None]:
    """参数值的数值范围（单值、范围、名义值都折成上下端）；不是数时返回 (None, None)。"""
    if not pv:
        return None, None
    num = lambda x: x if isinstance(x, (int, float)) and not isinstance(x, bool) else None
    if "value" in pv:
        v = num(pv["value"])
        return v, v
    if "nominal" in pv:
        n = num(pv["nominal"])
        if n is None:
            return None, None
        return n + (num(pv.get("tol_lower")) or 0), n + (num(pv.get("tol_upper")) or 0)
    return num(pv.get("min")), num(pv.get("max"))


def show(pv: Mapping | None, unit: str = "") -> str:
    """参数值的简短文字：单值、范围（a–b）、名义值加公差、曲线点数。"""
    if not pv:
        return "—"
    u = f" {unit}" if unit else ""
    fmt = lambda x: f"{x:g}" if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)
    if "points" in pv:
        return f"曲线 {len(pv['points'])} 点"
    if "value" in pv:
        v = pv["value"]
        return ("、".join(map(fmt, v)) if isinstance(v, list) else fmt(v)) + u
    if "nominal" in pv:
        return f"{fmt(pv['nominal'])}{u}（{fmt(pv.get('tol_upper', 0))} / {fmt(pv.get('tol_lower', 0))}）"
    lo, hi = pv.get("min"), pv.get("max")
    return f"{fmt(lo) if lo is not None else ''}–{fmt(hi) if hi is not None else ''}{u}"


def review(pv: Mapping | None) -> str:
    if not pv:
        return ""
    if pv.get("reviewed"):
        note = (pv.get("source") or {}).get("note", "")
        if "人工录入" in note:
            return "人工录入"
        if "人工确认" in note:
            return "人工确认"
        return "已复核"
    return {"computed": "推导", "standard": "标准"}.get(pv.get("method", ""), "未复核")


def source(pv: Mapping | None) -> str:
    src = (pv or {}).get("source") or {}
    if not src.get("doc"):
        return ""
    return f"{src['doc']} 第 {src['page']} 页" if src.get("page") else src["doc"]


@dataclass
class Row:
    id: str
    category: str
    vendor: str
    model: str
    key: list[tuple[str, str]] = field(default_factory=list)  # (标签, 显示值)


def rows(components: Iterable[Mapping], category: str | None = None, text: str = "",
         ranges: Mapping[str, tuple[float | None, float | None]] | None = None) -> list[Row]:
    """筛选：品类相同；文字出现在 id、厂商或型号中（不分大小写）；每个范围条件的参数落在 [lo, hi] 内。
    参数缺失或不是数的组件，在有该参数的范围条件时不显示。"""
    words = text.casefold().split()
    out = []
    for comp in components:
        cat = comp.get("category", "")
        if category and cat != category:
            continue
        hay = " ".join(str(comp.get(k, "")) for k in ("id", "vendor", "model")).casefold()
        if any(w not in hay for w in words):
            continue
        ok = True
        for path, (lo, hi) in (ranges or {}).items():
            a, b = number(lookup(comp, path))
            if a is None or (lo is not None and b < lo) or (hi is not None and a > hi):
                ok = False
                break
        if not ok:
            continue
        key = [(label, show(lookup(comp, path), unit_of(path))) for label, path in KEY_FIELDS.get(cat, [])]
        out.append(Row(comp["id"], cat, comp.get("vendor", ""), comp.get("model", ""), key))
    out.sort(key=lambda r: (r.category, r.vendor, r.model))
    return out


def detail(comp: Mapping) -> dict:
    """组件详情：概要、参数表与端口表，每项带单位、工况、来源与复核状态。"""
    def item(name: str, pv: Mapping) -> dict:
        return {"name": name, "value": show(pv, unit_of(name)), "condition": (pv or {}).get("condition", ""),
                "source": source(pv), "review": review(pv)}

    params = [item(n, pv) for n, pv in sorted(comp.get("params", {}).items())]
    ports = []
    for p in comp.get("ports", []):
        kind = PORT_KINDS.get(p.get("type", "").split(".")[0], "")
        ports.append({"id": p["id"], "type": p.get("type", ""), "kind": kind, "dir": p.get("dir", ""),
                      "configurable": bool(p.get("configurable")),
                      "spec": [item(n, pv) for n, pv in sorted(p.get("spec", {}).items())]})
    values = [pv for pv in comp.get("params", {}).values()] + [
        pv for p in comp.get("ports", []) for pv in p.get("spec", {}).values()]
    docs = sorted({(pv.get("source") or {}).get("doc") for pv in values if (pv.get("source") or {}).get("doc")})
    reviewed = sum(1 for pv in values if pv.get("reviewed"))
    return {"id": comp["id"], "title": f"{comp.get('vendor', '')} {comp.get('model', '')}".strip(),
            "category": CATEGORIES.get(comp.get("category", ""), comp.get("category", "")),
            "license": comp.get("license", ""), "note": comp.get("note", ""), "docs": docs,
            "reviewed": f"{reviewed}/{len(values)}", "params": params, "ports": ports}


def instance_name(category: str, existing: Iterable[str]) -> str:
    """按品类自动编号：第一个用基名（motor），其后 motor2、motor3……"""
    base = INSTANCE_BASE.get(category, category)
    taken = set(existing)
    if base not in taken:
        return base
    n = 2
    while f"{base}{n}" in taken:
        n += 1
    return f"{base}{n}"
