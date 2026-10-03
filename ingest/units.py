"""单位归一化（issue #26）：把规格书中的来源单位换算成标准单位。

标准单位由字段名后缀决定（实施细则第四节）。原则：
- 认不出的单位、与字段量纲不符的单位，一律报错，不猜测
- 量纲相同但含义不同的单位（角度与百分比都是无量纲；转/分与 Hz 都是 1/时间）用白名单区分
- 电流：标准为有效值。规格书写成幅值（A(0-p)、Apk）时按正弦电流除以 √2；只写 A 视为有效值
- 换算后在来源备注中记下原值与原单位，便于复核
"""

from __future__ import annotations

import copy
import math
import re
from functools import cache

import pint


class UnitError(ValueError):
    """单位无法识别或与字段不符。"""


# 字段后缀 → 标准单位（pint 写法）。按后缀长度从长到短匹配。
SUFFIX_UNITS: dict[str, str] = {
    "_nm_per_arcmin": "N*m/arcmin",
    "_nm_per_a": "N*m/A",
    "_kgm2": "kg*m**2",
    "_arcmin": "arcmin",
    "_ratio": "dimensionless",
    "_rpm": "rpm",
    "_deg": "degree",
    "_hz": "Hz",
    "_mm": "mm",
    "_nm": "N*m",
    "_kg": "kg",
    "_w": "W",
    "_v": "V",
    "_a": "A",
    "_n": "N",
}

# 量纲有歧义的字段，只接受白名单中的写法（规范化后的形式）
_ANGLE = {"arcmin", "arcsec", "arc min", "arc-min", "arc sec", "arc-sec", "degree", "deg", "rad", "radian", "'", '"', "°"}
_RATIO = {"", "1", "dimensionless", "%", "percent"}
_SPEED = {"rpm", "r/min", "rev/min", "min^-1", "min-1", "1/min", "rps", "r/s", "rev/s"}
_FREQ = {"Hz", "kHz"}
WHITELIST: dict[str, set[str]] = {
    "_arcmin": _ANGLE, "_deg": _ANGLE, "_ratio": _RATIO, "_rpm": _SPEED, "_hz": _FREQ,
}

# 规格书常见写法 → pint 写法
_TORQUE_SUFFIXES = {"_nm", "_nm_per_a", "_nm_per_arcmin"}
_TORQUE_ALIASES = {"nm": "N*m", "n.m": "N*m", "n-m": "N*m"}  # 只用于扭矩字段，避免与纳米（nm）混淆
_ALIASES = {
    "r/min": "rpm", "rev/min": "rpm", "min^-1": "rpm", "min-1": "rpm", "1/min": "rpm",
    "rps": "rpm*60", "r/s": "rpm*60", "rev/s": "rpm*60",
    "'": "arcmin", '"': "arcsec", "°": "degree", "deg": "degree",
    "arc min": "arcmin", "arc-min": "arcmin", "arc sec": "arcsec", "arc-sec": "arcsec",
    "%": "percent", "": "dimensionless", "1": "dimensionless",
    "arms": "A", "a rms": "A", "a(rms)": "A",
    "vdc": "V", "vac": "V", "v dc": "V", "v ac": "V", "vrms": "V", "v(rms)": "V",
}
_AMPLITUDE = {"a(0-p)", "a0-p", "a (0-p)", "apk", "a peak", "a(peak)", "a(pk)"}


@cache
def _ureg() -> pint.UnitRegistry:
    return pint.UnitRegistry()


def _clean(unit: str) -> str:
    u = unit.strip().replace("−", "-")  # 排版用的减号
    u = re.sub(r"^[×x]\s*10\s*-\s*(\d+)", r"*10^-\1 ", u)  # “×10-4 kg·m²”：上标压平后的写法
    u = re.sub(r"(?i)(?<![A-Za-z])A\s*rms(?![A-Za-z])", "A", u) if "/" in u else u  # “Nm/Arms”
    u = re.sub(r"(?<![A-Za-z])kg\s*m\s*(?:\^|²)?2?(?![A-Za-z0-9])", "kg*m^2", u) if re.search(r"kg\s*m\s*(\^?2|²)", u) else u
    u = u.replace("⁻¹", "^-1").replace("²", "^2").replace("³", "^3").replace("·", "*").replace("×", "*")
    u = re.sub(r"\s*\*\s*", "*", u)
    return u.lstrip("*")  # “×10⁻⁴ kg·m²”这类前置乘号写法


def standard_unit(field: str) -> tuple[str, str]:
    """返回字段对应的 (后缀, 标准单位)；后缀不认识时报错。"""
    for suffix in sorted(SUFFIX_UNITS, key=len, reverse=True):
        if field.endswith(suffix):
            return suffix, SUFFIX_UNITS[suffix]
    raise UnitError(f"字段 {field} 没有可识别的单位后缀")


def _factor(unit: str, field: str) -> float:
    """来源单位换算到标准单位的乘数。"""
    suffix, target = standard_unit(field)
    cleaned = _clean(unit)
    key = cleaned.casefold()
    if suffix == "_a" and key in _AMPLITUDE:
        return 1 / math.sqrt(2)
    if suffix in WHITELIST:
        allowed = {_clean(w).casefold() for w in WHITELIST[suffix]}
        if key not in allowed:
            raise UnitError(f"字段 {field} 不接受单位 {unit!r}（只接受 {sorted(WHITELIST[suffix])}）")
    if suffix in _TORQUE_SUFFIXES and key in _TORQUE_ALIASES:
        expr = _TORQUE_ALIASES[key]
    elif suffix in _TORQUE_SUFFIXES and key.startswith(("nm/", "nm*")):
        expr = "N*m" + cleaned[2:]
    else:
        expr = _ALIASES.get(key, cleaned)
    expr = re.sub(r"10\^(-?\d+)\s*\*?\s*", r"1e\1*", expr).replace("^", "**")
    ureg = _ureg()
    try:
        source = ureg.parse_expression(expr)
        if not isinstance(source, pint.Quantity):  # 纯数值
            source = ureg.Quantity(source, "dimensionless")
    except Exception as exc:  # pint 的解析错误类型较多，统一转为 UnitError
        raise UnitError(f"无法识别的单位 {unit!r}") from exc
    try:
        return float(source.to(target).magnitude)
    except pint.DimensionalityError as exc:
        raise UnitError(f"单位 {unit!r} 与字段 {field}（标准单位 {target}）量纲不符") from exc


def to_standard(value: float, unit: str, field: str) -> float:
    """把一个数值从来源单位换算到字段的标准单位。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise UnitError(f"字段 {field} 的值 {value!r} 不是有限数值")
    return value * _factor(unit, field)


_NUMERIC_KEYS = ("value", "min", "max", "nominal", "tol_upper", "tol_lower")


def normalize_param(param: dict, unit: str, field: str) -> dict:
    """换算参数值对象中的全部数值，并在 source.note 中记下原值与原单位；返回新对象。

    单位已是标准写法、乘数为 1 时不改动、不加备注。
    """
    factor = _factor(unit, field)
    if factor == 1:
        return copy.deepcopy(param)
    out = copy.deepcopy(param)
    originals = []
    for key in _NUMERIC_KEYS:
        v = out.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if not math.isfinite(v):
            raise UnitError(f"字段 {field} 的 {key} 不是有限数值")
        out[key] = v * factor
        originals.append(f"{key}={v}")
    if originals:
        note = f"原单位 {unit}：" + "，".join(originals)
        source = out.setdefault("source", {})
        source["note"] = f"{source['note']}；{note}" if source.get("note") else note
    return out
