"""效率曲线查表（ADR-0047）。纯函数。

目录只以曲线给出效率时，组件的 efficiency_curve 存的是图上网格温度的读点（环境温度、输入转速、效率）。
- 取不低于所需输入转速的最低一条转速曲线；所需转速高于图上最高转速时查不到
- 给了环境温度：相邻网格温度之间线性插值；超出图的温度范围时查不到
- 没给环境温度：取这条曲线上的最低值（偏保守）；对需要效率上端的公式（C6）取最高值
"""

from __future__ import annotations

from itertools import pairwise


def lookup(curve: dict | None, input_speed_rpm: float | None,
           ambient_temp_c: float | None) -> tuple[float, float, str] | None:
    """返回 (效率下端, 效率上端, 说明)；查不到时返回 None。"""
    if not curve or input_speed_rpm is None:
        return None
    pts = curve.get("points") or []
    speeds = sorted({p["input_speed_rpm"] for p in pts})
    speed = next((s for s in speeds if s >= input_speed_rpm * (1 - 1e-12)), None)
    if speed is None:
        return None
    line = sorted((p["ambient_temp_c"], p["efficiency_ratio"]) for p in pts if p["input_speed_rpm"] == speed)
    if len(line) < 2:
        return None
    where = f"效率按曲线取（ADR-0047）：{speed:g} rpm 曲线"
    if ambient_temp_c is None:
        lo, hi = min(e for _, e in line), max(e for _, e in line)
        return lo, hi, f"{where}，需求未给环境温度，取最低 {lo:g}"
    if not line[0][0] <= ambient_temp_c <= line[-1][0]:
        return None
    for (t0, e0), (t1, e1) in pairwise(line):
        if t0 <= ambient_temp_c <= t1:
            eta = e0 if t1 == t0 else e0 + (e1 - e0) * (ambient_temp_c - t0) / (t1 - t0)
            return eta, eta, f"{where}，环境温度 {ambient_temp_c:g} °C，取 {eta:.3g}"
    return None
