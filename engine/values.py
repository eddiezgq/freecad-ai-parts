"""从参数值对象取数（ADR-0025、ADR-0028）。缺数据返回 None，由校验判为 unknown，绝不猜测。

参数值有三种写法：单值 value、范围 min/max、公差 nominal + tol_lower/tol_upper。范围或公差给出的数
按“对安全不利的一端”取：能力侧（额定扭矩、驱动器电流、极限转速……）取下端，需求侧（电机所需电流、
电机峰值扭矩输出、减速器输入惯量……）取上端。
"""

from __future__ import annotations

import math
from typing import Any


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x) if math.isfinite(float(x)) else None
    except OverflowError:
        return None


def bounds(pv: dict | None) -> tuple[float | None, float | None]:
    """参数值的下端与上端：单值两端相等；范围取 min、max；公差取 nominal + tol_lower、nominal + tol_upper
    （没写偏差的一侧按名义值）。缺的一端为 None。"""
    if not pv:
        return None, None
    v = _num(pv.get("value"))
    if v is not None:
        return v, v
    n = _num(pv.get("nominal"))
    if n is not None:
        lo, hi = _num(pv.get("tol_lower")), _num(pv.get("tol_upper"))
        return n + (lo or 0.0), n + (hi or 0.0)
    return _num(pv.get("min")), _num(pv.get("max"))


def capacity(pv: dict | None) -> float | None:
    """能力侧数值：取下端（保守）。"""
    return bounds(pv)[0]


def demand(pv: dict | None) -> float | None:
    """需求侧数值：取上端（保守）。"""
    return bounds(pv)[1]


def nominal(pv: dict | None) -> float | None:
    """尺寸类数值（直径、分度圆、孔数）：单值或名义值；只有范围时视为缺失。"""
    if not pv:
        return None
    for key in ("value", "nominal"):
        v = _num(pv.get(key))
        if v is not None:
            return v
    return None


def span(pv: dict | None) -> tuple[float, float] | None:
    """范围类数值（供电电压）：[下端, 上端]；缺一端时返回 None。"""
    lo, hi = bounds(pv)
    return None if lo is None or hi is None else (lo, hi)


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
