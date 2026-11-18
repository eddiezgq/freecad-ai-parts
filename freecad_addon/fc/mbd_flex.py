"""装配体里把零件设成柔性，并在 FreeCAD 里显示变形与应力云图（ADR-0097 D8b，补充二十二）。需要 FreeCAD，不需要界面。

设成柔性：零件形状导出 STEP → 界面放在挂在这个零件上的运动副点（同一点只放一个）→ analysis.mbd.flexsolid.reduce_step
（gmsh + CalculiX 缩减，带应力振型）→ 模型里这个构件的质量属性换成 flex。界面半径按“运动副点到零件表面的最近距离 × 1.5”
（孔中心到孔壁的距离就是孔半径，乘 1.5 把孔壁整圈包进去）；点在表面上（距离几乎为零）时用两倍网格尺寸。
材料从材料库取（analysis/common/materials），缺弹性模量、泊松比或密度就报错，不估。

显示：Mesh::Feature 画表面网格，每帧改点坐标；有应力振型时加一个 VertexColors 颜色表、开 Coloring 显示云图；
原零件在显示期间隐藏，restore() 恢复。
"""

from __future__ import annotations

import os
import tempfile

import FreeCAD as App

from analysis.mbd.flexview import FlexView, colors

SNAP_SURFACE_MM = 1e-3


class FlexSetupError(ValueError):
    pass


def _interfaces(model, bid, shape, size_mm):
    import Part

    pts = []
    for j in model.get("joints", []):
        if bid in (j.get("body_i"), j.get("body_j")) and "point_mm" in j:
            p = [float(x) for x in j["point_mm"]]
            if not any(sum((a - b) ** 2 for a, b in zip(p, q, strict=True)) < 1e-12 for q in pts):
                pts.append(p)
    if not pts:
        raise FlexSetupError(f"零件 {bid} 上没有运动副，柔性体至少要一个界面")
    out = []
    for k, p in enumerate(pts):
        d = shape.distToShape(Part.Vertex(App.Vector(*p)))[0]
        r = 1.5 * d if d > SNAP_SURFACE_MM else 2.0 * size_mm
        out.append({"name": f"i{k}", "center_mm": p, "radius_mm": r})
    return out


def make_flexible(model: dict, objects: dict, flex_parts: dict, *, workdir=None) -> list[str]:
    """flex_parts：构件 id → {"material": 材料库 id, "size_mm": 网格尺寸?, "modes": 固定界面模态数?, "damping_ratio"?}；
    objects：构件 id → FreeCAD 对象。原地改 model，返回说明（每个柔性零件一行）。"""
    from analysis.common import materials
    from analysis.mbd import flexsolid as FS

    notes = []
    bodies = {b["id"]: b for b in model["bodies"]}
    for bid, spec in flex_parts.items():
        if bid not in bodies:
            raise FlexSetupError(f"模型里没有构件 {bid}")
        o = objects.get(bid)
        if o is None:
            raise FlexSetupError(f"找不到构件 {bid} 对应的 FreeCAD 零件")
        mat = materials.get(spec["material"])
        materials.require(mat, ["elastic_modulus_mpa", "poisson_ratio", "density_kg_m3"], "柔性体")
        shape = o.Shape.copy()
        if not shape.Solids:
            raise FlexSetupError(f"零件 {bid} 没有实体")
        size = float(spec.get("size_mm") or max(shape.BoundBox.DiagonalLength / 30.0, 1.0))
        itf = _interfaces(model, bid, shape, size)
        wd = workdir or tempfile.mkdtemp(prefix="fap_flex_")
        path = os.path.join(wd, f"{bid}.step")
        shape.exportStep(path)
        flex, info = FS.reduce_step(path, {k: mat[k] for k in ("elastic_modulus_mpa", "poisson_ratio", "density_kg_m3")}, itf,
                                    size_mm=size, fixed_interface_modes=int(spec.get("modes", 8)),
                                    damping_ratio=float(spec.get("damping_ratio", 0.0)))
        b = bodies[bid]
        for k in ("mass_kg", "cm_mm", "inertia_kg_mm2", "inertia_kg_m2"):
            b.pop(k, None)
        b["flex"] = flex
        notes.append(f"{bid}：柔性（{mat['name']}，网格 {size:.3g} mm，{info['nodes']} 个节点、{info['modes']} 阶模态，"
                     f"界面 {len(itf)} 个）")
    return notes


class FlexShow:
    """一个柔性构件的变形 / 应力云图显示"""

    def __init__(self, doc, flex_def, data, body_id, *, scale=1.0, hide=None):
        import Mesh

        self.v = FlexView(flex_def, data, body_id)
        self.scale = float(scale)
        self.rng = self.v.stress_range()
        self.tris = [tuple(int(i) for i in t) for t in self.v.triangles]
        self.obj = doc.addObject("Mesh::Feature", f"Flex_{body_id}")
        self.obj.Label = f"{body_id} 变形" + ("与应力" if self.rng else "")
        if self.rng:
            self.obj.addProperty("App::PropertyColorList", "VertexColors", "FAP", "von Mises 应力云图")
            self.obj.addProperty("App::PropertyFloat", "StressMaxMPa", "FAP", "色标上限（整段时间最大 von Mises，MPa）")
            self.obj.StressMaxMPa = self.rng[1]
        self.obj.addProperty("App::PropertyFloat", "DisplacementScale", "FAP", "变形放大倍数（只放大显示）")
        self.obj.DisplacementScale = self.scale
        self._Mesh = Mesh
        self.hidden = hide
        if hide is not None and getattr(hide, "ViewObject", None) is not None:
            hide.ViewObject.Visibility = False
        self.apply(0)

    def apply(self, k):
        pts = [App.Vector(*p) for p in self.v.points(k, self.scale)]
        self.obj.Mesh = self._Mesh.Mesh((pts, self.tris))
        if self.rng:
            self.obj.VertexColors = colors(self.v.von_mises(k), *self.rng)
            vo = getattr(self.obj, "ViewObject", None)
            if vo is not None and hasattr(vo, "Coloring"):
                vo.Coloring = True

    def remove(self):
        doc = self.obj.Document
        doc.removeObject(self.obj.Name)
        if self.hidden is not None and getattr(self.hidden, "ViewObject", None) is not None:
            self.hidden.ViewObject.Visibility = True
