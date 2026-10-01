"""位姿：实现在 engine.geometry（ADR-0034：引擎不依赖视图层，布局工具复用引擎的几何）。"""

from engine.geometry import (
    EPS,
    Pose,
    Quat,
    Vec,
    add,
    angle_deg,
    cross,
    dot,
    norm,
    quat_axis_angle,
    rotate,
    scale,
    shortest_arc,
    sub,
    unit,
)

__all__ = ["EPS", "Pose", "Quat", "Vec", "add", "angle_deg", "cross", "dot", "norm", "quat_axis_angle", "rotate",
           "scale", "shortest_arc", "sub", "unit"]
