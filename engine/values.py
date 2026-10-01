"""从参数值对象取数（ADR-0025）。缺数据返回 None，由校验判为 unknown，绝不猜测。"""

from __future__ import annotations

from typing import Any


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def capacity(pv: dict | None) -> float | None:
    """能力类数值（额定扭矩、极限转速、额定电流等）：单值取值；公差取名义值；范围取下限（保守）。"""
    if not pv:
        return None
    for key in ("value", "nominal", "min"):
        v = _num(pv.get(key))
        if v is not None:
            return v
    return None


def nominal(pv: dict | None) -> float | None:
    """尺寸类数值（直径、分度圆）：单值或名义值；只有范围时不取，返回 None。"""
    if not pv:
        return None
    for key in ("value", "nominal"):
        v = _num(pv.get(key))
        if v is not None:
            return v
    return None


def span(pv: dict | None) -> tuple[float, float] | None:
    """范围类数值（供电电压）：范围取 [min, max]；单值视为 [v, v]；缺一端时返回 None。"""
    if not pv:
        return None
    v = _num(pv.get("value"))
    if v is not None:
        return v, v
    lo, hi = _num(pv.get("min")), _num(pv.get("max"))
    if lo is None or hi is None:
        return None
    return lo, hi


def text(pv: dict | None) -> str | None:
    if not pv:
        return None
    v = pv.get("value")
    return v if isinstance(v, str) else None


def items(pv: dict | None) -> list | None:
    """字符串或列表 → 列表。"""
    if not pv:
        return None
    v = pv.get("value")
    if isinstance(v, list):
        return v
    return [v] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else None
