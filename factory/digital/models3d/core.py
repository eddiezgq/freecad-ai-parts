# -*- coding: utf-8 -*-
"""三维模型的公共部分（第 13 轮 8.3 R1）：零件、装配体、网格化与导出。

零件用 build123d 造型；书里的三维图（textbook/tools/render3d.py）、三维动画、数字工厂和零件库的 glb 都由这里网格化。
坐标与单位：mm；夹具类装配体 z 向上、x 沿工件轴线；轴类零件轴线沿 x，左端面在 x = 0。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# 技术插图的配色（浅色着色 + 黑色轮廓）。按材料或功能取色，书中各图一致
COLORS = {
    "steel": "#c9ced3",        # 一般钢件
    "steel_dark": "#9aa3ab",   # 标准件、螺栓
    "hardened": "#b8c7d9",     # 淬硬的定位元件
    "cast": "#d9d3c7",         # 铸铁夹具体
    "work": "#e8c39e",         # 工件
    "work_cut": "#f0d9bf",     # 工件已加工表面（需要区分时）
    "machined": "#d28b52",     # 本工序加工面
    "tool": "#e0b84f",         # 刀具
    "red": "#c0504d",          # 强调（键槽、误差）
    "blue": "#4f7fb8",         # 强调（定位）
    "green": "#5a9e6f",
    "rubber": "#4a4f55",
    "section": "#f4e1d2",      # 剖面
    "glass": "#dfe8f0",
}


@dataclass
class Part:
    """装配体里的一个零件：名称、build123d 形体、颜色、序号（总图和三维图的零件序号）、爆炸方向（mm）。"""
    name: str
    shape: object
    color: str = "steel"
    number: int | None = None
    explode: tuple = (0.0, 0.0, 0.0)
    opacity: float = 1.0
    tags: tuple = ()
    face_color: object = None      # 可选：face → 颜色名或 None（按面着色，如本工序加工面）

    @property
    def hex(self) -> str:
        return COLORS.get(self.color, self.color)


@dataclass
class Assembly:
    name: str
    parts: list = field(default_factory=list)
    anchors: dict = field(default_factory=dict)     # 命名的点（标注、箭头、尺寸用）：{名称: (x, y, z)}

    def add(self, *a, **k) -> Part:
        p = a[0] if a and isinstance(a[0], Part) else Part(*a, **k)
        self.parts.append(p)
        return p

    def part(self, name: str) -> Part:
        return next(p for p in self.parts if p.name == name)

    def bbox(self):
        lo, hi = [math.inf] * 3, [-math.inf] * 3
        for p in self.parts:
            b = p.shape.bounding_box()
            for i, (a, c) in enumerate(((b.min.X, b.max.X), (b.min.Y, b.max.Y), (b.min.Z, b.max.Z))):
                lo[i], hi[i] = min(lo[i], a), max(hi[i], c)
        return lo, hi


def tessellate(shape, tol: float = 0.05, angular: float = 0.3, section_plane=None, face_color=None):
    """形体 → 顶点、三角形。section_plane = (点, 法向)：落在剖切平面上的三角形单独标出（画剖面颜色）。
    face_color：face → 颜色或 None。返回 (vertices, triangles, on_section [bool...], colors [每个三角形的颜色或 None])。"""
    verts, tris, sec, cols = [], [], [], []
    for face in shape.faces():
        try:
            vs, ts = face.tessellate(tol, angular)
        except AttributeError:          # 极小的退化面（布尔运算留下的碎面）没有网格，跳过
            continue
        base = len(verts)
        verts.extend([[v.X, v.Y, v.Z] for v in vs])
        flag = False
        if section_plane is not None:
            (px, py, pz), (nx, ny, nz) = section_plane
            nn = math.sqrt(nx * nx + ny * ny + nz * nz)
            dist = max(abs(((v.X - px) * nx + (v.Y - py) * ny + (v.Z - pz) * nz) / nn) for v in vs) if vs else 1
            flag = dist < 1e-3
        c = face_color(face) if face_color else None
        for t in ts:
            tris.append([base + t[0], base + t[1], base + t[2]])
            sec.append(flag)
            cols.append(c)
    return verts, tris, sec, cols


def cut_half(shape, point, normal, size: float = 2000.0):
    """剖切：去掉法向 normal 一侧的材料（保留 −normal 一侧），用于剖视的三维图。"""
    import build123d as bd
    nx, ny, nz = normal
    plane = bd.Plane(origin=point, z_dir=(nx, ny, nz))
    box = plane * bd.Box(size, size, size, align=(bd.Align.CENTER, bd.Align.CENTER, bd.Align.MIN))
    return shape - box


def mesh_parts(asm: Assembly, tol: float = 0.05, section=None, hide=()):
    """装配体 → 渲染用的数据（每个零件：名称、颜色、透明度、序号、爆炸方向、顶点、三角形、剖面三角形标记）。
    section = (点, 法向)：沿该平面剖开（只剖 tags 里没有 "nocut" 的零件）。"""
    out = []
    for p in asm.parts:
        if p.name in hide:
            continue
        shp = p.shape
        sp = None
        if section is not None and "nocut" not in p.tags:
            shp = cut_half(shp, *section)
            sp = section
        if shp is None or not shp.faces():
            continue
        v, t, s, c = tessellate(shp, tol, section_plane=sp, face_color=p.face_color)
        groups, k = [], 0                      # 按面着色：[[起始三角形, 个数, 颜色]]
        while k < len(c):
            j = k
            while j < len(c) and c[j] == c[k]:
                j += 1
            if c[k]:
                groups.append([k, j - k, COLORS.get(c[k], c[k])])
            k = j
        out.append({"name": p.name, "color": p.hex, "opacity": p.opacity, "number": p.number, "explode": list(p.explode),
                    "v": [round(x, 4) for xyz in v for x in xyz], "t": [i for tri in t for i in tri],
                    "s": [k for k, f in enumerate(s) if f], "g": groups})
    return out


def save_glb(asm: Assembly, path: str, tol: float = 0.05) -> str:
    """装配体导出 glb（每个零件一个节点，带颜色），供零件库、数字工厂的三维显示和书中三维实验页用。"""
    import numpy as np
    import trimesh
    scene = trimesh.Scene()
    for p in asm.parts:
        v, t, _, _ = tessellate(p.shape, tol)
        if not t:
            continue
        m = trimesh.Trimesh(vertices=np.array(v) / 1000.0, faces=np.array(t), process=False)   # glb 用米
        h = p.hex.lstrip("#")
        rgba = [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [int(255 * p.opacity)]
        m.visual = trimesh.visual.ColorVisuals(m, face_colors=np.tile(rgba, (len(t), 1)))
        scene.add_geometry(m, node_name=p.name, geom_name=p.name)
    scene.export(path)
    return path
