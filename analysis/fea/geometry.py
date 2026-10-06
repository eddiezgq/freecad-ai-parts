"""读 STEP，列出每个面（编号、类型、面积、中心、法向或轴线）——搬自问渠数字工厂第 11 轮（ADR-0056）。

约束与载荷按面编号指定；FreeCAD 中选的面按中心与面积对应到这里的编号。
"""

from __future__ import annotations

import math
import shutil
import tempfile
import threading
from pathlib import Path

import numpy as np

_LOCK = threading.Lock()           # gmsh 是全局状态，同一进程里一次只做一件事


def _gmsh():
    import gmsh
    if not gmsh.isInitialized():
        gmsh.initialize(interruptible=False)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.Verbosity", 1)
    return gmsh


def load_step(gmsh, step_path, tmp):
    p = str(Path(tmp) / "part.step")
    shutil.copyfile(step_path, p)
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
    except Exception:  # noqa: BLE001, S110 — 某些曲面取不到法向，不影响其余信息
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
        _w, v = np.linalg.eigh(nrm.T @ nrm)
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
    except Exception:  # noqa: BLE001, S110 — 拟合失败时不给轴线
        pass


def faces(step_path, size_hint=None) -> tuple[list[dict], dict]:
    """返回（面清单, 实体信息）。"""
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_path, tmp)
        bb = gmsh.model.getBoundingBox(-1, -1)
        diag = math.dist(bb[:3], bb[3:])
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_hint or diag / 40)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 24)
        gmsh.model.mesh.generate(2)
        out = [_face_info(gmsh, tag) for _, tag in gmsh.model.getEntities(2)]
        vol = sum(gmsh.model.occ.getMass(3, t) for _, t in gmsh.model.getEntities(3))
        solid = {"bbox_mm": [round(x, 3) for x in bb], "volume_mm3": round(vol, 1), "faces": len(out),
                 "solids": len(gmsh.model.getEntities(3))}
    return out, solid
