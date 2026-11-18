"""柔性构件的变形与应力云图（ADR-0097 D8b，补充二十二）：结果的第 k 帧 → 表面网格各点的世界坐标（mm）和 von Mises 应力（MPa）。

纯计算，不依赖 FreeCAD；FreeCAD 里的显示在 freecad_addon/fc/mbd_flexview.py。和 analysis/mbd/dae/run.py 同一套公式：
构件系原点在未变形质心、初始姿态与模型坐标系一致，x(t) = r(t) + A(t)(X₀ − c + s·Σ ηₖ φₖ)，σ(t) = Σ ηₖ σₖ。
s 是变形放大倍数（只放大显示，应力不放大）。只支持实体柔性体（type: modal，带 surface_triangles）。
"""

from __future__ import annotations

import numpy as np

from analysis.mbd.dae.system import A_of


class FlexViewError(ValueError):
    pass


class FlexView:
    def __init__(self, flex_def: dict, data: dict, body_id: str):
        if flex_def.get("type") != "modal" or not flex_def.get("surface_triangles"):
            raise FlexViewError(f"柔性构件 {body_id}：只有实体柔性体（带表面网格）能画云图")
        if body_id not in (data.get("flex") or {}):
            raise FlexViewError(f"结果里没有柔性构件 {body_id}")
        X = np.asarray(flex_def["nodes_mm"], float)
        m = np.asarray(flex_def["node_mass_kg"], float)
        tri = np.asarray(flex_def["surface_triangles"], int)[:, :3]
        self.used = np.unique(tri.ravel())
        remap = np.full(len(X), -1, int)
        remap[self.used] = np.arange(len(self.used))
        self.triangles = remap[tri]
        self.x0 = X[self.used] - (m @ X) / m.sum()
        self.phi = np.asarray(flex_def["shapes"], float)[:, self.used, :3]            # nm × n × 3（mm）
        self.sigma = None
        if flex_def.get("stress_shapes_mpa"):
            sn = np.asarray(flex_def["stress_nodes"], int)
            if not np.array_equal(sn, self.used):
                raise FlexViewError(f"柔性构件 {body_id}：stress_nodes 与表面节点不一致")
            self.sigma = np.asarray(flex_def["stress_shapes_mpa"], float)              # nm × n × 6
        self.data, self.bid = data, body_id
        self.eta = np.asarray(data["flex"][body_id]["eta"], float)
        if self.eta.shape[1] != self.phi.shape[0]:
            raise FlexViewError(f"柔性构件 {body_id}：结果的模态数与柔性体定义不同")
        self.frames = len(self.eta)

    def points(self, k: int, scale: float = 1.0) -> np.ndarray:
        bd = self.data["bodies"][self.bid]
        r = np.asarray(bd["cm_mm"][k], float)
        A = A_of(np.asarray(bd["euler_parameters"][k], float))
        local = self.x0 + scale * np.einsum("k,kni->ni", self.eta[k], self.phi)
        return r + local @ A.T

    def von_mises(self, k: int) -> np.ndarray | None:
        if self.sigma is None:
            return None
        from analysis.mbd.flexsolid import von_mises

        return von_mises(np.einsum("k,kni->ni", self.eta[k], self.sigma))

    def stress_range(self) -> tuple[float, float] | None:
        """整段时间的应力范围（云图色标固定用它，各帧可比）"""
        if self.sigma is None:
            return None
        hi = max(float(self.von_mises(k).max()) for k in range(self.frames))
        return 0.0, hi


def colors(values, vmin: float, vmax: float) -> list[tuple[float, float, float]]:
    """蓝 → 青 → 绿 → 黄 → 红（和 FreeCAD FEM 云图同一走向）"""
    v = np.clip((np.asarray(values, float) - vmin) / max(vmax - vmin, 1e-30), 0, 1)
    stops = np.array([[0, 0, 1], [0, 1, 1], [0, 1, 0], [1, 1, 0], [1, 0, 0]], float)
    x = v * 4
    i = np.minimum(x.astype(int), 3)
    f = (x - i)[:, None]
    rgb = stops[i] * (1 - f) + stops[i + 1] * f
    return [tuple(map(float, c)) for c in rgb]
