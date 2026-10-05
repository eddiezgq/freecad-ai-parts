"""拖动回写（ADR-0049 第 3 条）：零件在 FreeCAD 中的新位姿 → place_component 的参数。纯函数。"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


def place_args(instance: str, base: Sequence[float], axis: Sequence[float], angle_rad: float,
               current: Mapping | None, tol_mm: float = 1e-4, tol_deg: float = 1e-4) -> dict | None:
    """零件的新位置与转轴、转角（弧度）；与场景中的当前位姿（布局状态中该实例的项）一致时返回 None。"""
    deg = math.degrees(angle_rad)
    pos = [float(c) for c in base]
    ax = [float(c) for c in axis]
    if deg < 0:  # 统一成正转角
        deg, ax = -deg, [-c for c in ax]
    if current is not None:
        cpos = current.get("position_mm", [0, 0, 0])
        rot = current.get("rotation") or {}
        cdeg, cax = rot.get("angle_deg", 0.0), rot.get("axis", [0, 0, 1])
        same_pos = all(abs(a - b) <= tol_mm for a, b in zip(pos, cpos, strict=True))
        same_rot = abs(deg - cdeg) <= tol_deg and (deg <= tol_deg or all(
            abs(a - b) <= 1e-6 for a, b in zip(ax, cax, strict=True)))
        if same_pos and same_rot:
            return None
    return {"instance": instance, "position_mm": pos, "rotation_axis": ax, "rotation_deg": deg}
