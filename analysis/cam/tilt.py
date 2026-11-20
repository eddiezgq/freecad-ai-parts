"""倾斜工作平面（3+2 定位，ADR-0104 C2、ADR-0106 C2a）：工作平面 ↔ 旋转矩阵 ↔ 各数控系统的角度写法。

工作平面 frame = {"origin": [x, y, z], "x": [..], "z": [..]}（工件坐标；z = 平面法向 = 刀轴方向，指向刀具一侧；x 与 z 垂直）。
旋转矩阵 R 的三列是平面的 X、Y、Z 轴在工件坐标里的方向：工件坐标 = origin + R · 平面坐标。

角度写法（都是“从工件坐标转到平面坐标”的同一个 R，只是分解方法不同）：
- FANUC G68.2 的欧拉角 I J K：先绕 Z 转 I，再绕新的 X 转 J，再绕新的 Z 转 K（Z-X-Z 内旋）：R = Rz(I)·Rx(J)·Rz(K)。
- 海德汉 PLANE SPATIAL SPA SPB SPC：依次绕机床固定的 A（X）、B（Y）、C（Z）转（外旋）：R = Rz(SPC)·Ry(SPB)·Rx(SPA)。
- 西门子 CYCLE800 逐轴旋转（顺序 X、Y、Z，每次绕已转过的新轴，内旋）：R = Rx(A)·Ry(B)·Rz(C)。
角度单位度；分解在奇异处（第二个角 0 或 180°）取第三个角为 0。
"""

from __future__ import annotations

import math

import numpy as np

EPS = 1e-12


class TiltError(ValueError):
    pass


def _rx(a):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(a):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(a):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def matrix(frame: dict) -> np.ndarray:
    """frame → R（列：平面 X、Y、Z）。x 不严格垂直于 z 时投影到平面上；x 与 z 平行报错"""
    z = np.asarray(frame["z"], float)
    nz = np.linalg.norm(z)
    if nz < EPS:
        raise TiltError("工作平面的法向是零向量")
    z = z / nz
    x = np.asarray(frame.get("x") or _default_x(z), float)
    x = x - z * float(x @ z)
    nx = np.linalg.norm(x)
    if nx < 1e-9:
        raise TiltError("工作平面的 X 方向与法向平行")
    x = x / nx
    return np.column_stack([x, np.cross(z, x), z])


def _default_x(z):
    """没给 X 方向：取工件 X 在平面上的投影；法向就是 ±X 时取工件 Y"""
    ex = np.array([1.0, 0.0, 0.0])
    return ex if abs(float(ex @ z)) < 1 - 1e-9 else np.array([0.0, 1.0, 0.0])


def frame_from(R, origin=(0.0, 0.0, 0.0)) -> dict:
    R = np.asarray(R, float)
    return {"origin": [float(v) for v in origin], "x": [float(v) for v in R[:, 0]], "z": [float(v) for v in R[:, 2]]}


def to_work(frame: dict, p) -> np.ndarray:
    """平面坐标 → 工件坐标"""
    return np.asarray(frame["origin"], float) + matrix(frame) @ np.asarray(p, float)


def to_plane(frame: dict, p) -> np.ndarray:
    """工件坐标 → 平面坐标"""
    return matrix(frame).T @ (np.asarray(p, float) - np.asarray(frame["origin"], float))


def _clean(a):
    a = math.degrees(a)
    a = (a + 180.0) % 360.0 - 180.0
    return 0.0 if abs(a) < 1e-10 else (180.0 if abs(a + 180.0) < 1e-10 else a)


# ---------------------------------------------------------------- FANUC G68.2：Z-X-Z 欧拉角
def euler_zxz(R) -> tuple[float, float, float]:
    R = np.asarray(R, float)
    j = math.acos(max(-1.0, min(1.0, R[2, 2])))
    if math.sin(j) > 1e-9:
        i = math.atan2(R[0, 2], -R[1, 2])
        k = math.atan2(R[2, 0], R[2, 1])
    else:                                          # J = 0 或 180°：I、K 合成一个角，K 取 0
        k = 0.0
        i = math.atan2(R[1, 0], R[0, 0])           # J = 0：R = Rz(I+K)；J = 180°：R = Rz(I−K)·Rx(180°)，K = 0 时第一列都是 Rz(I)
    return _clean(i), _clean(j), _clean(k)


def from_zxz(i, j, k) -> np.ndarray:
    return _rz(i) @ _rx(j) @ _rz(k)


# ---------------------------------------------------------------- 海德汉 PLANE SPATIAL：外旋 A、B、C
def spatial_abc(R) -> tuple[float, float, float]:
    """R = Rz(C)·Ry(B)·Rx(A) → (A, B, C)"""
    R = np.asarray(R, float)
    b = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    if math.cos(b) > 1e-9:
        a = math.atan2(R[2, 1], R[2, 2])
        c = math.atan2(R[1, 0], R[0, 0])
    else:
        c = 0.0
        a = math.atan2(-R[1, 2], R[1, 1])
    return _clean(a), _clean(b), _clean(c)


def from_spatial(a, b, c) -> np.ndarray:
    return _rz(c) @ _ry(b) @ _rx(a)


# ---------------------------------------------------------------- 西门子 CYCLE800 逐轴 X-Y-Z（内旋）
def axis_xyz(R) -> tuple[float, float, float]:
    """R = Rx(A)·Ry(B)·Rz(C) → (A, B, C)"""
    R = np.asarray(R, float)
    b = math.asin(max(-1.0, min(1.0, R[0, 2])))
    if math.cos(b) > 1e-9:
        a = math.atan2(-R[1, 2], R[2, 2])
        c = math.atan2(-R[0, 1], R[0, 0])
    else:
        c = 0.0
        a = math.atan2(R[2, 1], R[1, 1])
    return _clean(a), _clean(b), _clean(c)


def from_axis_xyz(a, b, c) -> np.ndarray:
    return _rx(a) @ _ry(b) @ _rz(c)
