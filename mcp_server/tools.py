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


__all__: list[Any] = ["SEARCH_LIMIT_MAX", "ToolInputError", "get_component", "search_components"]
