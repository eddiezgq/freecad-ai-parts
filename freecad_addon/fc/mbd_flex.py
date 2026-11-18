"""装配体里把零件设成柔性，并在 FreeCAD 里显示变形与应力云图（ADR-0097 D8b，补充二十二）。需要 FreeCAD，不需要界面。

设成柔性：零件形状导出 STEP → 界面放在挂在这个零件上的运动副点（同一点只放一个）→ analysis.mbd.flexsolid.reduce_step
（gmsh + CalculiX 缩减，带应力振型）→ 模型里这个构件的质量属性换成 flex。界面半径按“运动副点到零件表面的最近距离 × 1.5”
（孔中心到孔壁的距离就是孔半径，乘 1.5 把孔壁整圈包进去）；点在表面上（距离几乎为零）时用两倍网格尺寸。
材料从材料库取（analysis/common/materials），缺弹性模量、泊松比或密度就报错，不估。

显示：Mesh::Feature 画表面网格，每帧改点坐标；有应力振型时加一个 VertexColors 颜色表、开 Coloring 显示云图；
原零件在显示期间隐藏，restore() 恢复。
"""

from __future__ import annotations

import math
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
        if spec.get("kind") == "nonlinear_beam":                 # ADR-0101 F3：细长件按大变形梁
            pts = [j["point_mm"] for j in model.get("joints", []) if bid in (j.get("body_i"), j.get("body_j"))]
            flex, sec = beam_from_part(shape, mat, pts, elements=int(spec.get("elements", 20)))
            b = bodies[bid]
            m_solid = b.get("mass_kg")
            for k in ("mass_kg", "cm_mm", "inertia_kg_mm2", "inertia_kg_m2"):
                b.pop(k, None)
            b["flex"] = flex
            m_beam = mat["density_kg_m3"] * sec["area_mm2"] * sec["length_mm"] * 1e-9
            notes.append(f"{bid}：大变形梁（{mat['name']}，长 {sec['length_mm']:.4g} mm，截面 {sec['area_mm2']:.4g} mm²，"
                         f"{flex.get('elements', 20)} 段）" + (f"；梁质量 {m_beam:.4g} kg，实体 {m_solid:.4g} kg（孔、倒角不计）"
                                                             if m_solid else ""))
            continue
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


SLENDER_MIN = 8.0          # 长度 / √截面积 小于这个就不算细长件
PRISMATIC_TOL = 0.02       # 四分之一、中间、四分之三处截面积相差不超过 2%


def _section(shape, ex, d):
    """在 n·x = d 的平面上切截面，返回面"""
    import Part

    wires = shape.slice(App.Vector(*ex), d)
    if not wires:
        return None
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


def beam_from_part(shape, mat, joint_points, *, elements=20):
    """细长等截面直杆 → nonlinear_beam 定义（ADR-0101 F3）。
    梁轴取最小主惯量方向；长度由零件在轴上的投影范围定；截面在中间切，面积、惯性矩由截面面算，扭转常数用
    圣维南近似 J ≈ A⁴/(4π²Iₚ)（圆、椭圆精确，方截面偏大约 8%）。运动副点进 nodes_at_mm。"""
    import numpy as np

    sol = shape.Solids
    if len(sol) != 1:
        raise FlexSetupError("大变形梁要求零件是一个实体")
    pp = sol[0].PrincipalProperties
    moms = list(pp["Moments"])
    axes = [pp["FirstAxisOfInertia"], pp["SecondAxisOfInertia"], pp["ThirdAxisOfInertia"]]
    ex = np.array(tuple(axes[int(np.argmin(moms))]))
    ex /= np.linalg.norm(ex)
    pts = [np.array(tuple(v.Point)) for v in shape.Vertexes]
    for e in shape.Edges:
        pts += [np.array(tuple(p)) for p in e.discretize(16)]
    s_ = np.array([p @ ex for p in pts])
    smin, smax = float(s_.min()), float(s_.max())
    length = smax - smin
    faces = [_section(shape, ex, smin + f * length) for f in (0.25, 0.5, 0.75)]
    if any(f is None for f in faces):
        raise FlexSetupError("沿长轴切不出截面，零件不是直杆")
    areas = [f.Area for f in faces]
    if (max(areas) - min(areas)) / max(areas) > PRISMATIC_TOL:
        raise FlexSetupError(f"零件不是等截面直杆（四分之一、中间、四分之三处截面积 {', '.join(f'{a:.4g}' for a in areas)} mm²）")
    face = faces[1]
    area = face.Area
    if length / math.sqrt(area) < SLENDER_MIN:
        raise FlexSetupError(f"零件不够细长（长 {length:.4g} mm，截面 √A = {math.sqrt(area):.4g} mm，长细比要 ≥ {SLENDER_MIN:g}），用实体柔性体")
    c = np.array(tuple(face.CenterOfMass))
    M = face.MatrixOfInertia                                        # 对截面形心的面积惯性矩（mm⁴）
    T = np.array([[M.A11, M.A12, M.A13], [M.A21, M.A22, M.A23], [M.A31, M.A32, M.A33]])
    seed = np.array([0.0, 0.0, 1.0]) if abs(ex[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = np.cross(ex, seed)
    u /= np.linalg.norm(u)
    v = np.cross(ex, u)
    P = np.column_stack([u, v])
    # 截面内的二阶矩：∫(y² + z²) 型的惯性张量投影到截面内，换成 ∫z² dA、∫y² dA
    Ip = float(ex @ T @ ex)                                         # 极惯性矩 ∫(y² + z²) dA
    T2 = P.T @ T @ P                                                # [[∫(v²+x²)…]]：x 方向（梁轴）厚度为零，所以 T_uu = ∫v² dA
    w, vec = np.linalg.eigh(np.array([[T2[1, 1], -T2[0, 1]], [-T2[0, 1], T2[0, 0]]]))   # ∫u²、∫uv、∫v² 的矩阵
    ey = P @ vec[:, 0]                                              # 截面 y 轴：∫y² 较小的主方向
    ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    Izz, Iyy = float(w[0]), float(w[1])                             # Izz = ∫y² dA，Iyy = ∫z² dA
    J = area ** 4 / (4 * math.pi ** 2 * Ip)
    fp = [np.array(tuple(p)) - c for e in face.Edges for p in e.discretize(32)]
    fy = max(abs(p @ ey) for p in fp)
    fz = max(abs(p @ ez) for p in fp)
    sc = float(c @ ex)
    a = c + ex * (smin - sc)
    b = c + ex * (smax - sc)
    E = mat["elastic_modulus_mpa"]
    flex = {"type": "nonlinear_beam", "from_mm": a.tolist(), "to_mm": b.tolist(), "y_axis": ey.tolist(),
            "youngs_modulus_mpa": E, "shear_modulus_mpa": E / (2 * (1 + mat["poisson_ratio"])),
            "density_kg_m3": mat["density_kg_m3"], "area_mm2": area, "iyy_mm4": Iyy, "izz_mm4": Izz, "ixx_mm4": J,
            "elements": elements, "fiber_y_mm": fy, "fiber_z_mm": fz,
            "source": f"由 FreeCAD 零件量出（截面在中间切；扭转常数为圣维南近似），材料 {mat['name']}（ADR-0101 F3）"}
    if joint_points:
        flex["nodes_at_mm"] = [[float(x) for x in p] for p in joint_points]
    return flex, {"length_mm": length, "area_mm2": area, "iyy_mm4": Iyy, "izz_mm4": Izz, "ixx_mm4": J, "ip_mm4": Ip}


class BeamShow:
    """大变形梁的显示：节点连成折线（Part::Feature），每帧换形状；原零件隐藏"""

    def __init__(self, doc, data, body_id, *, hide=None):
        self.nodes = data["flex"][body_id]["nodes_mm"]
        self.stress = data["flex"][body_id].get("max_stress_mpa")
        self.obj = doc.addObject("Part::Feature", f"Beam_{body_id}")
        self.obj.Label = f"{body_id} 大变形梁"
        self.hidden = hide
        if hide is not None and getattr(hide, "ViewObject", None) is not None:
            hide.ViewObject.Visibility = False
        vo = getattr(self.obj, "ViewObject", None)
        if vo is not None and hasattr(vo, "LineWidth"):
            vo.LineWidth = 4.0
        self.apply(0)

    def apply(self, k):
        import Part

        self.obj.Shape = Part.makePolygon([App.Vector(*p) for p in self.nodes[k]])
        vo = getattr(self.obj, "ViewObject", None)
        if self.stress and vo is not None and hasattr(vo, "LineColor"):
            hi = max(self.stress) or 1.0
            vo.LineColor = colors([self.stress[k]], 0.0, hi)[0]

    def remove(self):
        self.obj.Document.removeObject(self.obj.Name)
        if self.hidden is not None and getattr(self.hidden, "ViewObject", None) is not None:
            self.hidden.ViewObject.Visibility = True


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
