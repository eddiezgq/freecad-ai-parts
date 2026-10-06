# -*- coding: utf-8 -*-
"""有限元第一步（第 11 轮 F1、F3）：读 STEP，列出每个面（编号、类型、面积、中心、法向或轴线），
并生成按面分开的网页模型——浏览器点到哪个面，就知道是几号面；AI 也按这份面清单选面。"""
import json
import math
import os
import tempfile
import threading

import numpy as np

_LOCK = threading.Lock()           # gmsh 是全局状态，同一进程里一次只做一件事


def _gmsh():
    import gmsh
    if not gmsh.isInitialized():
        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
    return gmsh


def load_step(gmsh, step_bytes, tmp):
    p = os.path.join(tmp, "part.step")
    open(p, "wb").write(step_bytes)
    gmsh.clear()
    gmsh.model.add("part")
    gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
    gmsh.model.occ.importShapes(p)
    gmsh.model.occ.synchronize()
    vols = gmsh.model.getEntities(3)
    if not vols:
        raise ValueError("STEP 里没有实体（只有曲面或线框），不能做有限元")
    return vols


def _face_info(gmsh, tag):
    typ = gmsh.model.getType(2, tag)
    area = gmsh.model.occ.getMass(2, tag)
    c = gmsh.model.occ.getCenterOfMass(2, tag)
    bb = gmsh.model.getBoundingBox(2, tag)
    info = {"id": int(tag), "kind": {"Plane": "plane", "Cylinder": "cylinder", "Cone": "cone", "Sphere": "sphere",
                                     "Torus": "torus"}.get(typ, "other"),
            "area_mm2": round(area, 3), "center": [round(x, 4) for x in c],
            "bbox": [round(x, 4) for x in bb]}
    # 法向（平面）或轴线（圆柱）：在面中心附近取参数点求法向
    try:
        uv = gmsh.model.getParametrization(2, tag, list(c))
        n = gmsh.model.getNormal(tag, uv)
        n = np.array(n[:3], float)
        if np.linalg.norm(n) > 0:
            n = n / np.linalg.norm(n)
            info["normal"] = [round(float(x), 4) for x in n]
    except Exception:  # noqa: BLE001
        pass
    if info["kind"] == "cylinder":
        _axis_fit(gmsh, tag, info)
    return info


def _axis_fit(gmsh, tag, info):
    """圆柱、圆锥面：用网格节点处的法向求轴线方向（法向都垂直于轴线），再在垂直面上拟合圆得到轴心和半径"""
    try:
        _, xyz, uv = gmsh.model.mesh.getNodes(2, tag, includeBoundary=False, returnParametricCoord=True)
        if len(xyz) < 9:
            return
        pts = np.asarray(xyz, float).reshape(-1, 3)
        nrm = np.asarray(gmsh.model.getNormal(tag, list(uv)), float).reshape(-1, 3)
        w, v = np.linalg.eigh(nrm.T @ nrm)
        d = v[:, 0] / np.linalg.norm(v[:, 0])
        e1 = np.cross(d, [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(d, e1)
        x, y = pts @ e1, pts @ e2
        A = np.c_[2 * x, 2 * y, np.ones_like(x)]
        (cx, cy, k), *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
        r = math.sqrt(max(k + cx * cx + cy * cy, 0))
        o = cx * e1 + cy * e2 + d * float(np.mean(pts @ d))
        info["axis"] = [round(float(t), 4) + 0.0 for t in d]
        info["axis_origin"] = [round(float(t), 4) + 0.0 for t in o]
        info["radius_mm"] = round(r, 3)
    except Exception:  # noqa: BLE001
        pass


def faces(step_bytes, size_hint=None):
    """返回 (面清单, 按面分开的 glb 字节, 实体信息)。glb 里每个面一个节点，名字 f<编号>（毫米）"""
    import trimesh
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_bytes, tmp)
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = math.dist(bb[:3], bb[3:])
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_hint or diag / 40)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.model.mesh.generate(2)
        scene = trimesh.Scene()
        out = []
        for _, tag in gmsh.model.getEntities(2):
            out.append(_face_info(gmsh, tag))
            ntags, xyz, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)
            etypes, _, enodes = gmsh.model.mesh.getElements(2, tag)
            if not len(ntags) or not etypes:
                continue
            idx = {int(t): i for i, t in enumerate(ntags)}
            tri = np.array([idx[int(n)] for n in enodes[0]], int).reshape(-1, 3)
            m = trimesh.Trimesh(np.asarray(xyz, float).reshape(-1, 3) / 1000.0, tri, process=False)   # glb 用米
            scene.add_geometry(m, node_name="f{}".format(tag), geom_name="f{}".format(tag))
        vol = sum(gmsh.model.occ.getMass(3, t) for _, t in gmsh.model.getEntities(3))
        solid = {"bbox_mm": [round(x, 3) for x in bb], "volume_mm3": round(vol, 1), "faces": len(out),
                 "solids": len(gmsh.model.getEntities(3))}
        glb = scene.export(file_type="glb")
    return out, glb, solid


if __name__ == "__main__":
    import sys
    f, g, s = faces(open(sys.argv[1], "rb").read())
    print(json.dumps(s, ensure_ascii=False))
    for x in f:
        print(x)
