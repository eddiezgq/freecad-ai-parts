"""凸体碰撞检查（ADR-0104 第 2 节“仿真”块；C1：长方体、圆柱）。

机床部件、夹具、刀具、刀柄用长方体（可以斜放）、圆柱表示，机床部件还可以是三角网格（STL，ADR-0106 Q2 第 2 步）。
凸体之间用 GJK：两个凸体各自“往某方向最远的点”（support）组成闵可夫斯基差，看它是否包含原点。`margin` 是安全间隙：
两体距离小于 margin 也算碰（把其中一个往外胀 margin）。
三角网格：三角形包围盒树粗筛，与对方包围盒（胀 margin）相交的三角形逐个用 GJK 判（三角形是凸的）；
一个三角形都没碰到时，再看对方是不是整个在网格里面（网格要封闭；射线奇偶判断），在里面也算碰。
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


@dataclass
class Triangle:
    v: np.ndarray            # (3, 3)

    def support(self, d: np.ndarray) -> np.ndarray:
        return self.v[int(np.argmax(self.v @ d))]

    def moved(self, T: np.ndarray) -> Triangle:
        return Triangle(self.v @ T[:3, :3].T + T[:3, 3])

    def bound(self) -> tuple[np.ndarray, float]:
        c = self.v.mean(0)
        return c, float(np.linalg.norm(self.v - c, axis=1).max())


def aabb(s) -> tuple[np.ndarray, np.ndarray]:
    """凸体的轴向包围盒（用 support）"""
    if isinstance(s, Mesh):
        return s.world_box()
    e = np.eye(3)
    hi = np.array([s.support(e[i])[i] for i in range(3)])
    lo = np.array([s.support(-e[i])[i] for i in range(3)])
    return lo, hi


class Mesh:
    """三角网格（局部坐标的三角形 + 包围盒树）放在位姿 T（4×4）上。moved 只改位姿，不动三角形。"""

    LEAF = 8

    def __init__(self, tris, T=None, _tree=None):
        self.tris = np.asarray(tris, float).reshape(-1, 3, 3)
        self.T = np.eye(4) if T is None else np.asarray(T, float)
        self.tree = _tree if _tree is not None else self._build()

    def _build(self):
        """节点：(lo, hi, 左, 右, 三角形下标)；叶子的左右为 -1"""
        lo_t, hi_t = self.tris.min(1), self.tris.max(1)
        cen = self.tris.mean(1)
        nodes = []

        def rec(idx):
            lo, hi = lo_t[idx].min(0), hi_t[idx].max(0)
            k = len(nodes)
            nodes.append(None)
            if len(idx) <= self.LEAF:
                nodes[k] = (lo, hi, -1, -1, idx)
                return k
            ax = int(np.argmax(hi - lo))
            order = idx[np.argsort(cen[idx, ax])]
            half = len(order) // 2
            left = rec(order[:half])
            right = rec(order[half:])
            nodes[k] = (lo, hi, left, right, None)
            return k

        if len(self.tris):
            rec(np.arange(len(self.tris)))
        return nodes

    def moved(self, T: np.ndarray) -> Mesh:
        return Mesh(self.tris, np.asarray(T, float) @ self.T, self.tree)

    def bound(self) -> tuple[np.ndarray, float]:
        lo, hi = self.tree[0][0], self.tree[0][1]
        c = (lo + hi) / 2
        return self.T[:3, :3] @ c + self.T[:3, 3], float(np.linalg.norm(hi - lo) / 2)

    def world_box(self):
        lo, hi = self.tree[0][0], self.tree[0][1]
        corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
        w = corners @ self.T[:3, :3].T + self.T[:3, 3]
        return w.min(0), w.max(0)

    def candidates(self, lo, hi):
        """局部坐标下与盒子 [lo, hi] 相交的三角形下标"""
        out, stack = [], [0] if self.tree else []
        while stack:
            nlo, nhi, left, right, idx = self.tree[stack.pop()]
            if (nlo > hi).any() or (nhi < lo).any():
                continue
            if left < 0:
                out.extend(idx.tolist())
            else:
                stack += [left, right]
        return out

    def contains(self, p_world) -> bool:
        """点是否在封闭网格里面（沿一个不平行于坐标轴的方向打射线，数交点奇偶）"""
        Ti = np.linalg.inv(self.T)
        p = Ti[:3, :3] @ np.asarray(p_world, float) + Ti[:3, 3]
        d = np.array([0.5773502691896258, 0.5773502692896258, 0.5773502690896258])
        a, b, c = self.tris[:, 0], self.tris[:, 1], self.tris[:, 2]
        e1, e2 = b - a, c - a
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-14
        f = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = p - a
        u = f * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, e1)
        v = f * (q @ d)
        t = f * np.einsum("ij,ij->i", e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-12)
        return bool(hit.sum() % 2)


def read_stl(path) -> np.ndarray:
    """STL（二进制或 ASCII）→ 三角形 (n, 3, 3)，单位按文件里的数（问渠的机床文件约定 mm）"""
    data = open(path, "rb").read()  # noqa: SIM115
    if len(data) >= 84:
        n = int(np.frombuffer(data[80:84], "<u4")[0])
        if len(data) == 84 + 50 * n:
            rec = np.frombuffer(data[84:], np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), n)
            return rec["v"].astype(float)
    txt = data.decode("utf-8", errors="replace").split()
    vs = [[float(txt[i + 1]), float(txt[i + 2]), float(txt[i + 3])] for i, w in enumerate(txt) if w == "vertex"]
    if not vs or len(vs) % 3:
        raise ValueError(f"{path}：读不出三角形（不是 STL？）")
    return np.asarray(vs, float).reshape(-1, 3, 3)


_MESH_CACHE: dict = {}


def shape(spec: dict, base_dir=None):
    """cam-machine/1 部件或夹具的外形（box_mm / cylinder_mm / mesh）→ Box / Cylinder / Mesh。
    网格文件相对 base_dir（机床文件所在目录）；读不到返回 None（调用方报“未知”）"""
    if "mesh" in spec:
        from pathlib import Path

        if base_dir is None:
            return None
        p = (Path(base_dir) / spec["mesh"]).resolve()
        if not p.is_file():
            return None
        key = (str(p), p.stat().st_mtime_ns)
        if key not in _MESH_CACHE:
            _MESH_CACHE[key] = Mesh(read_stl(p))
        return _MESH_CACHE[key]
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
    """两个物体（距离小于 margin 也算）是否相碰。凸体之间用 GJK；有一方是三角网格时见模块说明。"""
    if isinstance(a, Mesh) or isinstance(b, Mesh):
        return _hit_mesh(a, b, margin)
    return _gjk(a, b, margin)


def _hit_mesh(a, b, margin):
    if not isinstance(a, Mesh):
        a, b = b, a
    ca, ra = a.bound()
    cb, rb = b.bound()
    if np.linalg.norm(ca - cb) > ra + rb + margin:
        return False
    Ti = np.linalg.inv(a.T)
    bl = b.moved(Ti)                                  # 对方搬到网格的局部坐标
    lo, hi = aabb(bl)
    for i in a.candidates(lo - margin, hi + margin):
        tri = Triangle(a.tris[i])
        if isinstance(bl, Mesh):
            if _hit_mesh(bl, tri, margin):
                return True
        elif _gjk(tri, bl, margin):
            return True
    # 一个三角形都没碰到：看对方是不是整个在网格里（或网格整个在对方里——对方是凸体时看网格的一个顶点）
    probe = bl.tris[0, 0] @ bl.T[:3, :3].T + bl.T[:3, 3] if isinstance(bl, Mesh) else bl.support(np.array([1.0, 0, 0]))
    if Mesh(a.tris, np.eye(4), a.tree).contains(probe):
        return True
    if isinstance(bl, Mesh):
        return Mesh(bl.tris, bl.T, bl.tree).contains(a.tris[0, 0])
    return _gjk(Triangle(np.repeat(a.tris[0, :1], 3, 0)), bl, margin)


def _gjk(a, b, margin: float = 0.0) -> bool:
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
