"""凸体碰撞检查（ADR-0104 第 2 节“仿真”块；C1：长方体、圆柱）。

机床部件、夹具、刀具、刀柄在 C1 都用长方体（可以斜放）和圆柱表示；三角网格部件在 C2 加（包围盒树 + OCC 精确距离）。
判断用 GJK：两个凸体各自“往某方向最远的点”（support）组成闵可夫斯基差，看它是否包含原点。`margin` 是安全间隙：
两体距离小于 margin 也算碰（把其中一个往外胀 margin）。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EPS = 1e-12


@dataclass
class Box:
    """中心 c、旋转 R（列是三根局部轴）、半边长 h"""
    c: np.ndarray
    R: np.ndarray
    h: np.ndarray

    @staticmethod
    def from_minmax(v) -> Box:
        lo, hi = np.asarray(v[:3], float), np.asarray(v[3:], float)
        return Box((lo + hi) / 2, np.eye(3), np.abs(hi - lo) / 2)

    def support(self, d: np.ndarray) -> np.ndarray:
        s = np.where(self.R.T @ d >= 0, 1.0, -1.0)
        return self.c + self.R @ (s * self.h)

    def moved(self, T: np.ndarray) -> Box:
        return Box(T[:3, :3] @ self.c + T[:3, 3], T[:3, :3] @ self.R, self.h)

    def bound(self) -> tuple[np.ndarray, float]:
        return self.c, float(np.linalg.norm(self.h))


@dataclass
class Cylinder:
    """端面圆心 p0、p1，半径 r"""
    p0: np.ndarray
    p1: np.ndarray
    r: float

    def support(self, d: np.ndarray) -> np.ndarray:
        u = self.p1 - self.p0
        L = np.linalg.norm(u)
        u = u / L if L > EPS else np.array([0.0, 0.0, 1.0])
        end = self.p1 if d @ u >= 0 else self.p0
        rad = d - (d @ u) * u
        n = np.linalg.norm(rad)
        return end + (self.r * rad / n if n > EPS else 0.0)

    def moved(self, T: np.ndarray) -> Cylinder:
        return Cylinder(T[:3, :3] @ self.p0 + T[:3, 3], T[:3, :3] @ self.p1 + T[:3, 3], self.r)

    def bound(self) -> tuple[np.ndarray, float]:
        c = (self.p0 + self.p1) / 2
        return c, float(np.hypot(np.linalg.norm(self.p1 - self.p0) / 2, self.r))


def shape(spec: dict):
    """cam-machine/1 部件或夹具的外形（box_mm / cylinder_mm）→ Box / Cylinder；mesh 在 C1 不支持，返回 None"""
    if "box_mm" in spec:
        return Box.from_minmax(spec["box_mm"])
    if "cylinder_mm" in spec:
        c = spec["cylinder_mm"]
        return Cylinder(np.asarray(c["p0"], float), np.asarray(c["p1"], float), float(c["r"]))
    return None


def _support(a, b, d, margin):
    n = np.linalg.norm(d)
    dn = d / n if n > EPS else d
    return a.support(d) - b.support(-d) + margin * dn


def _line(s, d):
    b, a = s
    ab, ao = b - a, -a
    if ab @ ao > 0:
        return [b, a], np.cross(np.cross(ab, ao), ab)
    return [a], ao


def _triangle(s, d):
    c, b, a = s
    ab, ac, ao = b - a, c - a, -a
    abc = np.cross(ab, ac)
    if np.cross(abc, ac) @ ao > 0:
        if ac @ ao > 0:
            return [c, a], np.cross(np.cross(ac, ao), ac)
        return _line([b, a], d)
    if np.cross(ab, abc) @ ao > 0:
        return _line([b, a], d)
    if abc @ ao > 0:
        return [c, b, a], abc
    return [b, c, a], -abc


def _tetra(s, d):
    d_, c, b, a = s
    ab, ac, ad, ao = b - a, c - a, d_ - a, -a
    abc, acd, adb = np.cross(ab, ac), np.cross(ac, ad), np.cross(ad, ab)
    if abc @ ao > 0:
        return _triangle([c, b, a], d), False
    if acd @ ao > 0:
        return _triangle([d_, c, a], d), False
    if adb @ ao > 0:
        return _triangle([b, d_, a], d), False
    return (s, d), True


def hit(a, b, margin: float = 0.0) -> bool:
    """两个凸体（距离小于 margin 也算）是否相碰"""
    ca, ra = a.bound()
    cb, rb = b.bound()
    if np.linalg.norm(ca - cb) > ra + rb + margin:
        return False
    d = cb - ca
    if np.linalg.norm(d) < EPS:
        d = np.array([1.0, 0.0, 0.0])
    s = [_support(a, b, d, margin)]
    d = -s[0]
    for _ in range(100):
        if np.linalg.norm(d) < 1e-14:
            return True          # 原点在单纯形上：接触
        p = _support(a, b, d, margin)
        if p @ d < 1e-12:
            return False
        s.append(p)
        if len(s) == 2:
            s, d = _line(s, d)
        elif len(s) == 3:
            s, d = _triangle(s, d)
        else:
            (s, d), inside = _tetra(s, d)
            if inside:
                return True
    return True                  # 不收敛按碰处理（宁可多报）
