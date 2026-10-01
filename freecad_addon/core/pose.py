"""刚体位姿（ADR-0032）：单位四元数表示旋转，加平移；只用标准库。

坐标单位为 mm，角度对外用度。位姿 p 把实例坐标系中的点 x 变到世界坐标：p(x) = R·x + t。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Vec = tuple[float, float, float]
Quat = tuple[float, float, float, float]  # (w, x, y, z)

EPS = 1e-12


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k, a[2] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def unit(a: Vec) -> Vec:
    n = norm(a)
    if n < EPS:
        raise ValueError("零向量不能归一化")
    return scale(a, 1.0 / n)


def angle_deg(a: Vec, b: Vec) -> float:
    """两向量夹角（度），用 atan2 以免接近 0 时精度损失。"""
    return math.degrees(math.atan2(norm(cross(a, b)), dot(a, b)))


def _qmul(p: Quat, q: Quat) -> Quat:
    w1, x1, y1, z1 = p
    w2, x2, y2, z2 = q
    return (
        w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
        w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
        w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
        w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
    )


def _qnormalize(q: Quat) -> Quat:
    n = math.sqrt(sum(c * c for c in q))
    q = tuple(c / n for c in q)
    # 统一符号（q 与 -q 表示同一旋转），便于比较与序列化
    if q[0] < 0 or (q[0] == 0 and next((c for c in q[1:] if c != 0), 0) < 0):
        q = tuple(-c for c in q)
    return q  # type: ignore[return-value]


def quat_axis_angle(axis: Vec, deg: float) -> Quat:
    a = unit(axis)
    h = math.radians(deg) / 2
    s = math.sin(h)
    return _qnormalize((math.cos(h), a[0] * s, a[1] * s, a[2] * s))


def rotate(q: Quat, v: Vec) -> Vec:
    w, x, y, z = q
    r = _qmul(_qmul(q, (0.0, *v)), (w, -x, -y, -z))
    return (r[1], r[2], r[3])


def shortest_arc(u: Vec, v: Vec) -> Quat:
    """把方向 u 转到方向 v 的最短弧旋转。反向时绕与 u 垂直的确定轴转 180°。"""
    u, v = unit(u), unit(v)
    c = dot(u, v)
    if c > 1 - 1e-15:
        return (1.0, 0.0, 0.0, 0.0)
    if c < -1 + 1e-15:
        # 取与 u 最不平行的坐标轴叉乘，得到确定的垂直轴
        basis = min(((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)), key=lambda e: abs(dot(u, e)))
        return quat_axis_angle(cross(u, basis), 180.0)
    axis = cross(u, v)
    return quat_axis_angle(axis, angle_deg(u, v))


@dataclass(frozen=True)
class Pose:
    rotation: Quat = (1.0, 0.0, 0.0, 0.0)
    translation: Vec = (0.0, 0.0, 0.0)

    def apply(self, p: Vec) -> Vec:
        return add(rotate(self.rotation, p), self.translation)

    def apply_dir(self, d: Vec) -> Vec:
        return rotate(self.rotation, d)

    def compose(self, other: Pose) -> Pose:
        """self ∘ other：先 other 后 self。"""
        return Pose(_qnormalize(_qmul(self.rotation, other.rotation)),
                    add(rotate(self.rotation, other.translation), self.translation))

    def inverse(self) -> Pose:
        w, x, y, z = self.rotation
        qi = (w, -x, -y, -z)
        return Pose(_qnormalize(qi), scale(rotate(qi, self.translation), -1.0))

    def axis_angle(self) -> tuple[Vec, float]:
        """旋转轴（单位向量）与转角（度，0–180）。无旋转时轴取 z。"""
        w, x, y, z = self.rotation
        s = math.sqrt(x * x + y * y + z * z)
        if s < 1e-15:
            return (0.0, 0.0, 1.0), 0.0
        return (x / s, y / s, z / s), math.degrees(2 * math.atan2(s, w))

    def to_dict(self) -> dict:
        axis, deg = self.axis_angle()
        return {"position_mm": [_clean(c) for c in self.translation],
                "rotation": {"axis": [_clean(c) for c in axis], "angle_deg": _clean(deg)}}

    @staticmethod
    def from_dict(d: dict) -> Pose:
        pos = tuple(float(c) for c in d.get("position_mm", (0, 0, 0)))
        rot = d.get("rotation") or {}
        axis = tuple(float(c) for c in rot.get("axis", (0, 0, 1)))
        if len(pos) != 3 or len(axis) != 3:
            raise ValueError("position_mm 与 rotation.axis 须为 3 个数")
        deg = float(rot.get("angle_deg", 0.0))
        q = quat_axis_angle(axis, deg) if deg else (1.0, 0.0, 0.0, 0.0)  # type: ignore[arg-type]
        return Pose(q, pos)  # type: ignore[arg-type]


def _clean(x: float, nd: int = 9) -> float:
    """序列化时去掉浮点噪声与 -0.0，保证同一场景每次输出相同。"""
    r = round(x, nd)
    return 0.0 if r == 0 else r
