"""MCP 工具与 REST 共用的工具函数（M4a）。纯 Python 函数：入参与出参都是 JSON 可序列化的对象。

出错时抛出 ToolInputError，说明哪里不对；不静默忽略未知参数。
"""

from __future__ import annotations

from typing import Any

from engine.values import bounds
from ingest.llm_extract import CATEGORIES, targets
from kb.library import Library

SEARCH_LIMIT_MAX = 200


class ToolInputError(ValueError):
    """工具入参不合法。"""


def _summary(comp: dict) -> dict:
    tm = targets(comp["category"])
    key = {t.split("/", 1)[1]: comp["params"][t.split("/", 1)[1]] for t, (spec, _) in tm.items()
           if spec.key and t.startswith("params/") and t.split("/", 1)[1] in comp["params"]}
    return {
        "id": comp["id"], "category": comp["category"], "vendor": comp["vendor"], "model": comp["model"],
        "key_params": {k: {x: v[x] for x in ("value", "min", "max", "nominal", "tol_upper", "tol_lower", "condition")
                           if x in v} for k, v in sorted(key.items())},
    }


def _field(comp: dict, name: str) -> dict | None:
    """params/<名> 或 ports/<端口>/<字段> 的参数值；也接受裸参数名。"""
    if name.startswith("ports/"):
        _, pid, field = name.split("/", 2)
        port = next((p for p in comp["ports"] if p["id"] == pid), None)
        return None if port is None else port["spec"].get(field)
    return comp["params"].get(name.removeprefix("params/"))


def _check_filters(category: str | None, params: dict) -> dict[str, tuple[float | None, float | None]]:
    if not isinstance(params, dict):
        raise ToolInputError("params 须为对象：{参数名: {min, max}}")
    if params and category is None:
        raise ToolInputError("按参数筛选时须指定品类 category")
    valid = {t for t in targets(category)} if category else set()
    out = {}
    for name, rng in params.items():
        target = name if name.startswith(("params/", "ports/")) else f"params/{name}"
        if target not in valid or target.startswith("dims/"):
            raise ToolInputError(f"品类 {category} 没有参数 {name!r}")
        spec = targets(category)[target][0]
        if spec.kind not in ("number", "integer"):
            raise ToolInputError(f"{name} 不是数值参数，不能按范围筛选")
        if not isinstance(rng, dict) or not rng or set(rng) - {"min", "max"}:
            raise ToolInputError(f"{name} 的筛选须写成 {{min, max}}（单位为标准单位 {spec.unit or '无'}）")
        lo, hi = rng.get("min"), rng.get("max")
        for v in (lo, hi):
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise ToolInputError(f"{name} 的范围须为数字")
        if lo is not None and hi is not None and lo > hi:
            raise ToolInputError(f"{name} 的 min 大于 max")
        out[target] = (lo, hi)
    return out


def search_components(library: Library, *, category: str | None = None, vendor: str | None = None,
                      text: str | None = None, params: dict | None = None, limit: int = 50) -> dict:
    """结构化筛选组件。

    - category：品类；vendor：厂商（不分大小写）；text：关键词（全部出现在 id、厂商、型号、系列中）
    - params：{参数名: {min, max}}，标准单位；组件的值（范围或公差取两端）须全部落在区间内；缺该参数的组件不返回，
      数量记在 excluded_missing
    """
    if category is not None and category not in CATEGORIES:
        raise ToolInputError(f"未知品类 {category!r}，可选：{', '.join(CATEGORIES)}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ToolInputError(f"limit 须为 1–{SEARCH_LIMIT_MAX} 的整数")
    filters = _check_filters(category, params or {})
    words = (text or "").casefold().split()
    hits, missing = [], 0
    for comp in library.all(category):
        if vendor and comp["vendor"].casefold() != vendor.casefold():
            continue
        hay = " ".join(str(comp.get(k, "")) for k in ("id", "vendor", "model", "series")).casefold()
        if any(w not in hay for w in words):
            continue
        ok = True
        for name, (lo, hi) in filters.items():
            c_lo, c_hi = bounds(_field(comp, name))
            if c_lo is None or c_hi is None:
                ok = False
                missing += 1
                break
            if (lo is not None and c_lo < lo) or (hi is not None and c_hi > hi):
                ok = False
                break
        if ok:
            hits.append(comp)
    return {"total": len(hits), "excluded_missing": missing,
            "components": [_summary(c) for c in hits[:limit]], "truncated": len(hits) > limit}


def get_component(library: Library, component_id: str) -> dict:
    comp = library.get(component_id)
    if comp is None:
        raise ToolInputError(f"组件不存在：{component_id}")
    return comp


_RANK = {"pass": 0, "warn": 1, "unknown": 2, "fail": 3}


def find_compatible(library: Library, component_id: str, port_id: str, *, category: str | None = None,
                    include_unknown: bool = True, via_adapters: bool = True, limit: int = 50) -> dict:
    """能连到该端口的组件及端口，附单连接校验结果（engine.link.check_link）。

    - 只返回不为 fail 的连接；include_unknown 为假时也去掉 unknown（数据缺失）的
    - via_adapters：对直连不通过的圆柱与法兰端口，再找能补上的转接件（轴套、适配法兰板），结果注明 via
    """
    from engine.checks_interface import connects_to
    from engine.link import check_link

    src = get_component(library, component_id)
    sport = next((p for p in src["ports"] if p["id"] == port_id), None)
    if sport is None:
        raise ToolInputError(f"组件 {component_id} 没有端口 {port_id}")
    if category is not None and category not in CATEGORIES:
        raise ToolInputError(f"未知品类 {category!r}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ToolInputError(f"limit 须为 1–{SEARCH_LIMIT_MAX} 的整数")
    allowed = {"pass", "warn"} | ({"unknown"} if include_unknown else set())
    targets_types = connects_to(sport["type"])
    adapters = library.all("adapter") if via_adapters else []
    results = []
    for comp in library.all(category):
        if comp["id"] == component_id:
            continue
        for port in comp["ports"]:
            if port["type"] not in targets_types:
                continue
            direct = check_link(src, port_id, comp, port["id"])
            if direct["status"] in allowed:
                results.append({"component_id": comp["id"], "port_id": port["id"], **direct})
                continue
            if comp["category"] == "adapter" or port["type"] not in (
                    "mechanical.cyl_male", "mechanical.cyl_female", "mechanical.flange"):
                continue
            for ad in adapters:
                for p1 in ad["ports"]:
                    if p1["type"] not in targets_types:
                        continue
                    first = check_link(src, port_id, ad, p1["id"])
                    if first["status"] not in allowed:
                        continue
                    for p2 in ad["ports"]:
                        if p2["id"] == p1["id"] or port["type"] not in connects_to(p2["type"]):
                            continue
                        second = check_link(ad, p2["id"], comp, port["id"])
                        if second["status"] not in allowed:
                            continue
                        status = max(first["status"], second["status"], key=_RANK.__getitem__)
                        results.append({"component_id": comp["id"], "port_id": port["id"], "status": status,
                                        "via": {"adapter": ad["id"], "in": p1["id"], "out": p2["id"]},
                                        "findings": first["findings"] + second["findings"]})
    results.sort(key=lambda r: (_RANK[r["status"]], "via" in r, r["component_id"], r["port_id"],
                                (r.get("via") or {}).get("adapter", "")))
    return {"source": {"component_id": component_id, "port_id": port_id, "type": sport["type"]},
            "total": len(results), "results": results[:limit], "truncated": len(results) > limit}


def _schema_check(relative: str, obj: Any, what: str) -> None:
    from kb.validation import errors

    errs = errors(relative, obj)
    if errs:
        raise ToolInputError(f"{what}不符合 schema：" + "；".join(errs[:5]))


def _lang(lang: str) -> str:
    if lang not in ("zh", "en"):
        raise ToolInputError("lang 须为 zh 或 en")
    return lang


def verify_system(library: Library, system: dict, *, lang: str = "zh") -> dict:
    """对一个系统（schema/system.schema.json）做全部 11 项校验，返回结构化报告与说明。"""
    from engine.explain import explain
    from engine.system import SystemError_
    from engine.validate import validate

    _lang(lang)
    _schema_check("system.schema.json", system, "系统")
    try:
        report = validate(system, library.get)
    except SystemError_ as exc:
        raise ToolInputError(str(exc)) from exc
    return {"report": report, "explanation": explain(report, lang)}


def compose_chain(library: Library, requirement: dict, *, top_n: int = 5, include_unknown: bool = False,
                  lang: str = "zh") -> dict:
    """按需求从组件库组合“电机 →（转接件）→ 减速器 + 驱动器”，返回校验过、排好序的候选方案（ADR-0029）。"""
    from engine.compose import compose_chain as solve
    from engine.explain import explain, explain_candidates

    _lang(lang)
    _schema_check("requirement.schema.json", requirement, "需求")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 20:
        raise ToolInputError("top_n 须为 1–20 的整数")
    cands = solve(requirement, library.all(), top_n=top_n, include_unknown=include_unknown)
    return {
        "count": len(cands),
        "candidates": [{**c.to_dict(), "overall": c.overall, "explanation": explain(c.report, lang)} for c in cands],
        "explanation": explain_candidates(cands, lang),
    }


EXPORT_FORMATS = ("bom_csv", "bom_json", "system_json", "urdf")


def export_system(library: Library, system: dict, *, format: str = "bom_csv") -> dict:
    """导出方案：bom_csv / bom_json / system_json（含校验报告与所用组件数据）/ urdf（须带 layout，ADR-0035）。

    返回 {"filename", "media_type", "content"}；content 为文本（CSV）或对象（JSON）。
    """
    import json

    from engine import export
    from engine.system import SystemError_
    from engine.validate import validate

    if format not in EXPORT_FORMATS:
        raise ToolInputError(f"format 须为 {', '.join(EXPORT_FORMATS)} 之一")
    _schema_check("system.schema.json", system, "系统")
    try:
        report = validate(system, library.get)
    except SystemError_ as exc:
        raise ToolInputError(str(exc)) from exc
    sid = system["id"]
    if format == "bom_csv":
        return {"filename": f"{sid}-bom.csv", "media_type": "text/csv",
                "content": export.bom_csv(system, library.get), "overall": report["overall"]}
    if format == "bom_json":
        return {"filename": f"{sid}-bom.json", "media_type": "application/json",
                "content": export.bom_json(system, library.get), "overall": report["overall"]}
    if format == "urdf":
        try:
            text = export.urdf(system, library.get)
        except ValueError as exc:
            raise ToolInputError(str(exc)) from exc
        return {"filename": f"{sid}.urdf", "media_type": "application/xml", "content": text,
                "overall": report["overall"]}
    content = export.system_json(system, library.get, report)
    json.dumps(content, allow_nan=False)  # 确保是合法 JSON
    return {"filename": f"{sid}.json", "media_type": "application/json", "content": content,
            "overall": report["overall"]}


__all__: list[Any] = ["EXPORT_FORMATS", "SEARCH_LIMIT_MAX", "ToolInputError", "compose_chain", "export_system",
                      "find_compatible", "get_component", "search_components", "verify_system"]
