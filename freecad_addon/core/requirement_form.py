"""需求表单与需求的互转（ADR-0051 第 1 条）：选型面板与校验窗口共用。纯函数。

表单中都是文字；空栏不写进需求（不估、不补默认值，安全系数由引擎按 ADR-0008 处理）。
"""

from __future__ import annotations

from collections.abc import Mapping

FIELDS = (("output_torque_cont_nm", "连续扭矩 N·m"), ("output_torque_peak_nm", "峰值扭矩 N·m"),
          ("output_speed_rpm", "输出转速 rpm"), ("ambient_temp_c", "环境温度 °C"),
          ("max_envelope_diameter_mm", "外径上限 mm"), ("voltage_v", "供电电压 V"), ("phases", "相数（0 直流、1、3）"))
REQUIRED = ("output_torque_cont_nm", "output_speed_rpm")
LABELS = dict(FIELDS)
_SUPPLY = ("voltage_v", "phases")


def from_texts(texts: Mapping[str, str]) -> tuple[dict | None, str | None]:
    """表单文字 → (需求, 错误)。有错误时需求为 None。"""
    vals: dict[str, float] = {}
    for key, _ in FIELDS:
        text = (texts.get(key) or "").strip()
        if not text:
            continue
        try:
            vals[key] = float(text)
        except ValueError:
            return None, f"{LABELS[key]} 须为数字"
    missing = [LABELS[k] for k in REQUIRED if k not in vals]
    if missing:
        return None, f"至少要填{'和'.join(missing)}"
    req = {k: v for k, v in vals.items() if k not in _SUPPLY}
    if "phases" in vals and "voltage_v" not in vals:
        return None, "填了相数也要填供电电压"
    if "voltage_v" in vals:
        phases = vals.get("phases", 3.0)
        if phases not in (0.0, 1.0, 3.0):
            return None, "相数只能是 0（直流）、1 或 3"
        req["supply"] = {"current_type": "dc" if phases == 0 else "ac", "voltage_v": vals["voltage_v"],
                         "phases": int(phases)}
    return req, None


def to_texts(req: Mapping | None) -> dict[str, str]:
    """需求 → 表单文字；需求中没有的栏为空。"""
    req = req or {}
    flat = {**req, **{k: v for k, v in (req.get("supply") or {}).items() if k in _SUPPLY}}
    out = {}
    for key, _ in FIELDS:
        v = flat.get(key)
        out[key] = "" if v is None else f"{v:g}" if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    return out
