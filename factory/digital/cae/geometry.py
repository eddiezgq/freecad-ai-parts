# -*- coding: utf-8 -*-
"""转接层（本仓库 ADR-0060）：读 STEP、列面只留一份，在 analysis/fea/geometry.py。工厂另要按面分开的网页模型（glb）。"""
import os

from analysis.fea import geometry as _G
from analysis.fea.geometry import _LOCK, _axis_fit, _face_info, _gmsh  # noqa: F401
from cae._fap import StepFile


def load_step(gmsh, step_bytes, tmp):
    if isinstance(step_bytes, (bytes, bytearray, memoryview)):
        p = os.path.join(tmp, "source.step")
        with open(p, "wb") as f:
            f.write(bytes(step_bytes))
        return _G.load_step(gmsh, p, tmp)
    return _G.load_step(gmsh, step_bytes, tmp)


def faces(step_bytes, size_hint=None):
    """返回 (面清单, 按面分开的 glb 字节, 实体信息)。glb 里每个面一个节点，名字 f<编号>（米）"""
    import trimesh
    with StepFile(step_bytes) as path:
        out, solid, meshes = _G.faces(path, size_hint, with_mesh=True)
    scene = trimesh.Scene()
    for tag, (xyz, tri) in meshes.items():
        m = trimesh.Trimesh(xyz / 1000.0, tri, process=False)
        scene.add_geometry(m, node_name="f{}".format(tag), geom_name="f{}".format(tag))
    return out, scene.export(file_type="glb"), solid
