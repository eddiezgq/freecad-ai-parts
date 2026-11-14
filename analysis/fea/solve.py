"""有限元求解：Gmsh 二阶四面体网格 → CalculiX 线性静力 → 节点应力、位移、表面结果（搬自问渠数字工厂第 11 轮，ADR-0056）。

载荷（单位：mm、N、MPa、N·mm）：
  {"type": "fixed", "faces": [3]}
  {"type": "cyl_support", "faces": [5], "axis": {"origin": [...], "dir": [...]}, "dofs": ["radial", "axial"], "band_mm": 1}
  {"type": "force", "faces": [2], "vector_n": [0, -100, 0]}        面上总力，均匀分布
  {"type": "pressure", "faces": [4], "value_mpa": 1.0}             正值压向表面
  {"type": "torque", "faces": [9], "value_nmm": 3.5e5, "axis": {...}}  按 r 线性分布的切向力
"""

from __future__ import annotations

import math
import os
import subprocess
import tempfile
import time

import numpy as np

from analysis.common import materials
from analysis.fea.geometry import _LOCK, _gmsh, load_step

MAX_ELEMENTS = 200000
TIME_LIMIT_S = 300


class TooBig(ValueError):
    pass


def _ccx(ccx, tmp, limit):
    try:
        return subprocess.run([ccx, "-i", "job"], cwd=tmp, capture_output=True, text=True, timeout=limit, check=False,
                              env=dict(os.environ, OMP_NUM_THREADS=os.environ.get("FAP_CCX_THREADS", "2")))
    except subprocess.TimeoutExpired:
        raise TooBig(f"计算超过 {limit} 秒：请把网格尺寸调大") from None


# 二阶四面体边中点顺序：gmsh（类型 11）01,12,20,03,23,13；CalculiX C3D10 01,12,20,03,13,23 —— 最后两个对调
GMSH2CCX_TET10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


def mesh(gmsh, size_mm, fine_faces=(), max_elements=MAX_ELEMENTS, refine=None):
    """refine（ADR-0093 F1，网格收敛用）：{"center_mm": [x, y, z], "radius_mm": R, "size_mm": hs}——半径 R 的球内单元尺寸 hs"""
    bb = gmsh.model.getBoundingBox(-1, -1)
    diag = math.dist(bb[:3], bb[3:])
    h = size_mm or diag / 30
    gmsh.option.setNumber("Mesh.MeshSizeMax", h)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h / 8)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
    # 先生成一阶网格、再升二阶（边中点放在曲面上）；升阶后有翻转或很扭曲的单元（最小缩放雅可比 < 0.1）时，改成直边二阶单元
    # （边中点取在弦的中点，单元不会翻转，曲面按弦近似）。不用 gmsh 的高阶优化：薄板这类网格上它会抛出无法捕获的 C++ 异常、
    # 整个进程退出（ADR-0093 F2，NAFEMS LE1 的 0.1 m 薄板就会）
    gmsh.option.setNumber("Mesh.ElementOrder", 1)
    gmsh.option.setNumber("Mesh.HighOrderOptimize", 0)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)        # HXT，快
    gmsh.option.setNumber("Mesh.MaxNumThreads3D", int(os.environ.get("FAP_MESH_THREADS", "1")))  # 1：网格每次相同，数字可复现
    fields = []
    f = gmsh.model.mesh.field
    if fine_faces:                                        # 载荷、圆角处加密
        d = f.add("Distance")
        f.setNumbers(d, "SurfacesList", list(fine_faces))
        t = f.add("Threshold")
        f.setNumber(t, "InField", d)
        f.setNumber(t, "SizeMin", h / 3)
        f.setNumber(t, "SizeMax", h)
        f.setNumber(t, "DistMin", h / 2)
        f.setNumber(t, "DistMax", 3 * h)
        fields.append(t)
    if refine:                                            # 球内加密：尺寸 hs，球外渐变到 h（过渡带宽一个半径）
        hs = float(refine["size_mm"])
        gmsh.option.setNumber("Mesh.MeshSizeMin", min(hs, h / 8))
        c, r = [float(x) for x in refine["center_mm"]], float(refine["radius_mm"])
        # Ball 场：球内尺寸 hs，球外一个半径的过渡带内渐变到 h。不往几何里加点（加一个孤立的几何点会把网格搞乱）
        tb = f.add("Ball")
        for k, v in (("XCenter", c[0]), ("YCenter", c[1]), ("ZCenter", c[2]), ("Radius", r), ("Thickness", r),
                     ("VIn", hs), ("VOut", h)):
            f.setNumber(tb, k, v)
        fields.append(tb)
    if fields:
        if len(fields) > 1:
            m = f.add("Min")
            f.setNumbers(m, "FieldsList", fields)
            f.setAsBackgroundMesh(m)
        else:
            f.setAsBackgroundMesh(fields[0])
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.model.mesh.generate(2)
    # 曲面网格自检：个别曲面（例如椭圆柱面）在加了尺寸场以后，缺省的 Frontal-Delaunay 会在参数平面里连出横跨整个面的三角形；
    # 有边长超过 3 倍单元尺寸的面，改用 MeshAdapt 重新划分（ADR-0093 F2，NAFEMS LE1 加密核查时出现）
    bad = []
    for _, tag in gmsh.model.getEntities(2):
        nt, xyz, _ = gmsh.model.mesh.getNodes(2, tag, includeBoundary=True)
        et, _, en = gmsh.model.mesh.getElements(2, tag)
        if not len(nt) or not len(et):
            continue
        X = dict(zip(nt, np.asarray(xyz, float).reshape(-1, 3)))
        tri = np.asarray(en[0], np.int64).reshape(-1, 3)
        A, B, C = (np.array([X[n] for n in tri[:, i]]) for i in range(3))
        L = np.max([np.linalg.norm(A - B, axis=1), np.linalg.norm(B - C, axis=1), np.linalg.norm(C - A, axis=1)])
        if L > 3 * h:
            bad.append(tag)
    if bad:
        gmsh.model.mesh.clear()
        for tag in bad:
            gmsh.model.mesh.setAlgorithm(2, tag, 1)
        gmsh.model.mesh.generate(2)
    gmsh.model.mesh.generate(3)
    gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
    gmsh.model.mesh.setOrder(2)
    et, etg, _ = gmsh.model.mesh.getElements(3)
    if 11 in list(et):
        sj = gmsh.model.mesh.getElementQualities(list(etg[list(et).index(11)]), "minSJ")
        if len(sj) and min(sj) < 0.1:
            gmsh.model.mesh.setOrder(1)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
            gmsh.model.mesh.setOrder(2)
            gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
            gmsh.model.setAttribute("fap_straight_sided", ["1"])          # quality() 报出来
    etypes, _etags, enodes = gmsh.model.mesh.getElements(3)
    if 11 not in list(etypes):
        raise ValueError("网格没有生成二阶四面体")
    k = list(etypes).index(11)
    tets = np.asarray(enodes[k], np.int64).reshape(-1, 10)
    if len(tets) > max_elements:
        raise TooBig(f"网格 {len(tets)} 个单元，超过上限 {max_elements}：请把网格尺寸调大")
    ntags, xyz, _ = gmsh.model.mesh.getNodes()
    return np.asarray(ntags, np.int64), np.asarray(xyz, float).reshape(-1, 3), tets


def quality(gmsh):
    """网格质量（ADR-0093 F1）：每个二阶四面体的最小缩放雅可比（minSJ，≤ 0 为翻转、不能用）和形状因子 gamma
    （内切球 / 外接球半径之比 × 3，正四面体为 1）。返回统计；判定在 analysis/fea/trust.py"""
    et, etags, _ = gmsh.model.mesh.getElements(3)
    k = list(et).index(11)
    tags = list(etags[k])
    sj = np.asarray(gmsh.model.mesh.getElementQualities(tags, "minSJ"), float)
    gam = np.asarray(gmsh.model.mesh.getElementQualities(tags, "gamma"), float)
    straight = "fap_straight_sided" in gmsh.model.getAttributeNames()
    return {"elements": len(tags), "straight_sided": straight, "min_sj_min": round(float(sj.min()), 4), "inverted": int((sj <= 0).sum()),
            "gamma_min": round(float(gam.min()), 4), "gamma_p01": round(float(np.percentile(gam, 1)), 4),
            "gamma_below_0_1": int((gam < 0.1).sum())}


def face_tris(gmsh, tag):
    """某个面上的二阶三角形（6 节点：3 角点 + 3 边中点）"""
    et, _, en = gmsh.model.mesh.getElements(2, tag)
    for t, n in zip(et, en):
        if t == 9:                                        # 6 节点三角形
            return np.asarray(n, np.int64).reshape(-1, 6)
    return np.zeros((0, 6), np.int64)


# 二阶三角形（6 节点：角点 0 1 2，边中点 3 = 0–1、4 = 1–2、5 = 2–0）上的 7 点高斯积分（5 阶，Radon）。
# 面力按真实的二阶曲面（位置、法向随点变化）积分：曲面上的压力合力与解析值一致（ADR-0093 F2；F1 按角点平面分配时，
# 厚壁圆筒内压的合力有 1.7 × 10⁻⁴ 倍总压力的轴向残量）。平面三角形上与原来的“角点 0、边中点各 1/3”完全相同。
_A1, _A2 = (6 - math.sqrt(15)) / 21, (6 + math.sqrt(15)) / 21
_W0, _W1, _W2 = 9 / 80, (155 + math.sqrt(15)) / 2400, (155 - math.sqrt(15)) / 2400
_T6_GAUSS = [(1 / 3, 1 / 3, _W0)] + [(x, y, _W1) for x, y in ((_A1, _A1), (1 - 2 * _A1, _A1), (_A1, 1 - 2 * _A1))] + \
            [(x, y, _W2) for x, y in ((_A2, _A2), (1 - 2 * _A2, _A2), (_A2, 1 - 2 * _A2))]


def _t6(xi, eta):
    l1, l2, l3 = 1 - xi - eta, xi, eta
    N = np.array([l1 * (2 * l1 - 1), l2 * (2 * l2 - 1), l3 * (2 * l3 - 1), 4 * l1 * l2, 4 * l2 * l3, 4 * l3 * l1])
    dxi = np.array([-(4 * l1 - 1), 4 * l2 - 1, 0, 4 * (l1 - l2), 4 * l3, -4 * l3])
    deta = np.array([-(4 * l1 - 1), 0, 4 * l3 - 1, -4 * l2, 4 * l2, 4 * (l1 - l3)])
    return N, dxi, deta


_T6_TAB = [(*_t6(x, y), w) for x, y, w in _T6_GAUSS]


def tri_points(tris, P):
    """每个高斯点：(三角形下标, 形函数值, 位置, 单位法向, 面积权 w·|J|)。法向的朝向同角点 (b − a) × (c − a)"""
    out = []
    for k, tri in enumerate(tris):
        X = np.array([P[int(n)] for n in tri])
        for N, dxi, deta, w in _T6_TAB:
            x, t1, t2 = N @ X, dxi @ X, deta @ X
            n = np.cross(t1, t2)
            j = float(np.linalg.norm(n))
            if j <= 0:
                continue
            out.append((k, N, x, n / j, w * j))
    return out


def face_area_centroid(tris, P):
    pts = tri_points(tris, P)
    a = sum(q[4] for q in pts)
    c = sum(q[2] * q[4] for q in pts) / a if a > 0 else np.zeros(3)
    return a, c, pts


def consistent_loads(tris, P, traction_fn, pts=None):
    """面上分布力 → 节点力：f_i = ∫ N_i t dA，二阶曲面上 7 点高斯积分。traction_fn(点, 单位法向) → 每单位面积的力"""
    out = {}
    pts = tri_points(tris, P) if pts is None else pts
    for k, N, x, n, wj in pts:
        t = np.asarray(traction_fn(x, n), float) * wj
        for i, m in enumerate(tris[k]):
            if N[i]:
                out[int(m)] = out.get(int(m), 0) + N[i] * t
    return out


def nodal_areas(tris, P):
    """节点的“分摊面积” ∫ N_i dA（弹性支承用；平面二阶三角形的角点为 0、边中点为 1/3 面积）"""
    out = {}
    for k, N, _x, _n, wj in tri_points(tris, P):
        for i, m in enumerate(tris[k]):
            out[int(m)] = out.get(int(m), 0.0) + N[i] * wj
    return out


def edge_nodes(gmsh, tag):
    et, _, en = gmsh.model.mesh.getElements(1, tag)
    nodes = set()
    for t, n in zip(et, en):
        nodes |= {int(x) for x in n}
    return nodes


def body_nodal(gmsh, rho, accel=None, omega2=0.0, o=None, d=None):
    """体力（重力 / 离心）的等效节点力 f_i = ∫ N_i ρ b dV，与 CalculiX C3D10 一样用 4 点积分。只用于核对反力平衡：
    CalculiX 报的 RF 含受约束节点上的体力份额，要减掉；载荷本身由 CalculiX 的 *DLOAD 加。返回 {节点: 力}"""
    lc, w = gmsh.model.mesh.getIntegrationPoints(11, "Gauss2")
    ng = len(w)
    _jac, dets, xyz = gmsh.model.mesh.getJacobians(11, lc)
    dets = np.asarray(dets, float).reshape(-1, ng)
    xyz = np.asarray(xyz, float).reshape(-1, ng, 3)
    _nc, N, _no = gmsh.model.mesh.getBasisFunctions(11, lc, "Lagrange")
    N = np.asarray(N, float).reshape(ng, -1)                       # 每个积分点 10 个形函数（gmsh 节点次序）
    _et, enodes = gmsh.model.mesh.getElementsByType(11)
    enodes = np.asarray(enodes, np.int64).reshape(len(dets), -1)
    dv = rho * dets * np.asarray(w, float)[None, :]                 # (单元, 积分点)
    b = np.zeros(xyz.shape)
    if accel is not None:
        b += np.asarray(accel, float)
    if omega2:
        r = xyz - o
        b += omega2 * (r - (r @ d)[..., None] * d)
    fe = np.einsum("eg,gi,egk->eik", dv, N, b)                      # (单元, 节点, 3)
    out = {}
    flat_n, flat_f = enodes.ravel(), fe.reshape(-1, 3)
    for n, f in zip(flat_n, flat_f):
        out[int(n)] = out.get(int(n), 0) + f
    return out


def _nset(w, name, nodes):
    w.write(f"*NSET, NSET={name}\n")
    ns = sorted(nodes)
    for i in range(0, len(ns), 12):
        w.write(",".join(str(int(n)) for n in ns[i:i + 12]) + "\n")


def write_inp(path, ntags, xyz, tets, fixed_nodes, cyl_supports, nodal_forces, mat, reactions=False, extra=None):
    """cyl_supports: [(节点集合, 轴心, 轴向, [限制的局部自由度 1 径向 2 切向 3 轴向])]
    extra（ADR-0093 F2，可无）：{"disp": [(节点集合, {自由度: 值})], "rect": [(节点集合, a, b, [局部自由度])],
      "springs": [(节点, 刚度 N/mm)], "dload": ["EALL,GRAV,..."], "delta_t_k": ΔT}"""
    ex = extra or {}
    with open(path, "w") as w:
        w.write("*HEADING\nWenQuest CAE\n*NODE, NSET=NALL\n")
        w.writelines("{},{:.9g},{:.9g},{:.9g}\n".format(t, *p) for t, p in zip(ntags, xyz))
        w.write("*ELEMENT, TYPE=C3D10, ELSET=EALL\n")
        w.writelines("{},{}\n".format(i, ",".join(str(int(e[j])) for j in GMSH2CCX_TET10)) for i, e in enumerate(tets, 1))
        if fixed_nodes:
            _nset(w, "FIX", fixed_nodes)
        for k, (nodes, o, d, dofs) in enumerate(cyl_supports, 1):
            _nset(w, f"CYL{k}", nodes)
            a, b = np.asarray(o, float), np.asarray(o, float) + 100 * np.asarray(d, float)
            # 柱坐标系：局部 1 径向、2 切向、3 轴向（CalculiX *TRANSFORM TYPE=C，两点定轴）
            w.write("*TRANSFORM, NSET=CYL{}, TYPE=C\n{}\n".format(k, ",".join(f"{x:.9g}" for x in [*a, *b])))
        for k, (nodes, a, b, _dofs) in enumerate(ex.get("rect", []), 1):
            _nset(w, f"REC{k}", nodes)
            # 直角坐标系：局部 x 沿 a，局部 xy 平面含 b（*TRANSFORM TYPE=R）；对称面 a = 法向
            w.write("*TRANSFORM, NSET=REC{}, TYPE=R\n{}\n".format(k, ",".join(f"{x:.9g}" for x in [*a, *b])))
        for k, (nodes, _vals) in enumerate(ex.get("disp", []), 1):
            _nset(w, f"DSP{k}", nodes)
        eid = len(tets)
        for k, (n, kk) in enumerate(ex.get("springs", []), 1):
            for dof in (1, 2, 3):
                eid += 1
                w.write(f"*ELEMENT, TYPE=SPRING1, ELSET=SP{k}_{dof}\n{eid},{int(n)}\n*SPRING, ELSET=SP{k}_{dof}\n{dof}\n{kk:.9g}\n")
        w.write("*MATERIAL, NAME=M\n*ELASTIC\n{:.9g},{:.9g}\n*DENSITY\n{:.9g}\n".format(
            mat["elastic_modulus_mpa"], mat["poisson_ratio"], mat["density_kg_m3"] * 1e-12))  # kg/m³ → t/mm³
        if ex.get("delta_t_k"):
            w.write("*EXPANSION\n{:.9g}\n".format(mat["thermal_expansion_per_k"]))
        w.write("*SOLID SECTION, ELSET=EALL, MATERIAL=M\n")
        if ex.get("delta_t_k"):
            w.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\nNALL,20\n")
        w.write(f"*STEP\n*STATIC, SOLVER={SOLVER}\n*BOUNDARY\n")
        if fixed_nodes:
            w.write("FIX,1,3,0\n")
        for k, (_, _, _, dofs) in enumerate(cyl_supports, 1):
            w.writelines(f"CYL{k},{dof},{dof},0\n" for dof in dofs)
        for k, (_, _, _, dofs) in enumerate(ex.get("rect", []), 1):
            w.writelines(f"REC{k},{dof},{dof},0\n" for dof in dofs)
        for k, (_, vals) in enumerate(ex.get("disp", []), 1):
            w.writelines(f"DSP{k},{dof},{dof},{v:.9g}\n" for dof, v in sorted(vals.items()))
        if nodal_forces:
            w.write("*CLOAD\n")
            for n, f in nodal_forces.items():
                for d in range(3):
                    if abs(f[d]) > 0:
                        w.write(f"{int(n)},{d + 1},{f[d]:.9g}\n")
        if ex.get("dload"):
            w.write("*DLOAD\n" + "".join(x + "\n" for x in ex["dload"]))
        if ex.get("delta_t_k"):
            w.write("*TEMPERATURE\nNALL,{:.9g}\n".format(20 + float(ex["delta_t_k"])))
        w.write("*NODE FILE\n{}\n*EL FILE\nS\n*END STEP\n".format("U,RF" if reactions else "U"))


def read_frd(path):
    """CalculiX .frd（文本）里的节点位移 DISP 和节点应力 STRESS"""
    disp, stress, _ = read_frd_rf(path)
    return disp, stress


def read_frd_rf(path):
    """同 read_frd，另返回节点反力 FORC（*NODE FILE 里要求了 RF 时才有）"""
    disp, stress, forc, block = {}, {}, {}, None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith(" -4"):
                name = line.split()[1]
                block = {"DISP": disp, "STRESS": stress, "FORC": forc}.get(name)
                continue
            if block is None:
                continue
            if line.startswith(" -3"):
                block = None
                continue
            if line.startswith(" -1"):
                nid = int(line[3:13])
                vals = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line.rstrip()) - 13) // 12)]
                block[nid] = vals
    return disp, stress, forc


def von_mises(s):
    sxx, syy, szz, sxy, syz, szx = s[:6]
    return math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))


SOLVER = os.environ.get("FAP_CCX_SOLVER", "SPOOLES")
SUPPORT_DOFS = {"radial": 1, "tangential": 2, "axial": 3}
SUPPORTS = ("fixed", "cyl_support", "displacement", "symmetry", "elastic_support")
BODY_LOADS = ("gravity", "centrifugal", "temperature")


def band_nodes(nodes, P, o, d, band_mm):
    """轴承支承只限制轴承位中间宽 band_mm（建议 1 mm）的一圈（第 11 轮《机械设计》）：整个轴承位都限径向，相当于把轴夹住、不让它在
    轴承里转一点角度，弯曲刚度和固有频率都会偏高；单列深沟球轴承更接近“铰支”。band_mm 为空或 0 = 整个面（原来的做法）"""
    if not band_mm:
        return nodes
    zs = {n: float(np.dot(P[n] - o, d)) for n in nodes}
    mid = (min(zs.values()) + max(zs.values())) / 2
    gaps = sorted(abs(z - mid) for z in zs.values())
    thr = max(float(band_mm) / 2, gaps[min(11, len(gaps) - 1)])       # 网格粗时一圈里节点少：至少留 12 个
    keep = {n for n, z in zs.items() if abs(z - mid) <= thr + 1e-9}
    return keep or nodes


def _axis(l):
    o = np.array(l["axis"]["origin"], float)
    d = np.array(l["axis"]["dir"], float)
    return o, d / np.linalg.norm(d)


def solve(step_path, setup, ccx, workdir=None):
    """线性静力。返回 (统计, 表面结果, 全部节点应力)。

    支承：fixed（三个方向都固定）；cyl_support（圆柱面，按柱坐标限制 radial 径向 / tangential 转动 / axial 轴向——
    轴承一般限径向，止推的那个再限轴向，联轴器限转动）。
    约束面附近应力受边界条件影响（圣维南原理），“评估最大应力”不计约束面 1.5 个网格尺寸以内的点；云图照常显示。"""
    t0 = time.time()
    mat = setup["material"]  # 材料库条目（已检查 E、ν、密度）
    loads = setup.get("loads") or []
    if not any(l["type"] in SUPPORTS for l in loads):
        raise ValueError("至少要有一个固定或支承面，否则零件会整体移动、算不出来")
    moved = any(l["type"] == "displacement" and any(l.get(k) for k in ("ux_mm", "uy_mm", "uz_mm")) for l in loads)
    if not any(l["type"] not in SUPPORTS for l in loads) and not moved:
        raise ValueError("还没有加载荷")
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_path, tmp)
        all_faces = [t for _, t in gmsh.model.getEntities(2)]
        used = sorted({f for l in loads for f in l.get("faces") or []})
        bad = [f for f in used if f not in all_faces]
        if bad:
            raise ValueError(f"没有这些面：{bad}")
        all_edges = [t for _, t in gmsh.model.getEntities(1)]
        bad = sorted({e for l in loads for e in l.get("edges") or [] if e not in all_edges})
        if bad:
            raise ValueError(f"没有这些边：{bad}")
        size = (setup.get("mesh") or {}).get("size_mm")
        fine = [f for l in loads if l["type"] not in SUPPORTS for f in l.get("faces") or []] + list(setup.get("refine_faces") or [])
        ntags, xyz, tets = mesh(gmsh, size, fine, setup.get("max_elements", MAX_ELEMENTS), refine=setup.get("refine"))
        h = float(gmsh.option.getNumber("Mesh.MeshSizeMax"))
        qual = quality(gmsh)
        P = {int(t): p for t, p in zip(ntags, xyz)}
        fixed, cyl, forces, constrained = set(), [], {}, set()
        dsp, rect, springs, dload = [], [], [], []
        sup_dofs = []                                      # 各支承：(设置, 节点, 限制的整体自由度)——报各支承的反力
        body_f, delta_t = {}, 0.0                          # 体力的等效节点力（只用于核对平衡）
        rho = mat["density_kg_m3"] * 1e-12

        def add(d):
            for n, f in d.items():
                forces[n] = forces.get(n, 0) + f

        def moment_traction(pts, o, d, T):
            # 切向面力 τ = T·r⊥ / J，J = ∫ r⊥² dA：合力矩正好是 T（右手定则绕 d）
            J = sum(float(np.dot(r, r)) * wj for _k, _N, x, _n, wj in pts for r in [(x - o) - d * np.dot(x - o, d)])
            return lambda x, n: T / J * np.cross(d, (x - o) - d * np.dot(x - o, d))
        for l in loads:
            t = l["type"]
            if t in BODY_LOADS:
                if t == "gravity":
                    acc = np.array(l["acceleration_mm_s2"], float)
                    g = float(np.linalg.norm(acc))
                    if g:
                        dload.append("EALL,GRAV,{:.9g},{:.9g},{:.9g},{:.9g}".format(g, *(acc / g)))
                        for n, f in body_nodal(gmsh, rho, accel=acc).items():
                            body_f[n] = body_f.get(n, 0) + f
                elif t == "centrifugal":
                    o, d = _axis(l)
                    w2 = (float(l["speed_rpm"]) * 2 * math.pi / 60) ** 2
                    dload.append("EALL,CENTRIF,{:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g}".format(w2, *o, *d))
                    for n, f in body_nodal(gmsh, rho, omega2=w2, o=o, d=d).items():
                        body_f[n] = body_f.get(n, 0) + f
                else:
                    if not mat.get("thermal_expansion_per_k"):
                        raise ValueError("材料缺线膨胀系数，不能加温度载荷")
                    delta_t += float(l["delta_t_k"])
                continue
            if l.get("edges"):
                nodes = set().union(*(edge_nodes(gmsh, e) for e in l["edges"]))
                tris = np.zeros((0, 6), np.int64)
            else:
                tris = np.concatenate([face_tris(gmsh, f) for f in l["faces"]]) if l.get("faces") else np.zeros((0, 6), np.int64)
                nodes = {int(n) for n in tris.ravel()}
            if t == "fixed":
                sup_dofs.append((l, set(nodes), (1, 2, 3)))
                fixed |= nodes
                constrained |= nodes
                continue
            if t == "cyl_support":
                o, d = _axis(l)
                dofs = sorted({SUPPORT_DOFS[k] for k in l.get("dofs") or ["radial"]})
                nodes = band_nodes(nodes, P, o, d, l.get("band_mm"))
                if l.get("band_mm") and 3 in dofs and len(dofs) > 1:
                    # 铰支的止推：轴向只限一个节点（只消除沿轴线的刚体移动）；整圈都限轴向会把截面夹住、不让它转角
                    n0 = min(nodes)
                    cyl.append((nodes - {n0}, o, d, [x for x in dofs if x != 3]))
                    cyl.append(({n0}, o, d, dofs))
                else:
                    cyl.append((nodes, o, d, dofs))
                sup_dofs.append((l, set(nodes), (1, 2, 3)))         # 局部坐标的约束：反力整个算给它
                constrained |= nodes
                continue
            if t == "displacement":
                vals = {i + 1: float(l[k]) for i, k in enumerate(("ux_mm", "uy_mm", "uz_mm")) if k in l}
                dsp.append((nodes, vals))
                sup_dofs.append((l, set(nodes), tuple(vals)))
                constrained |= nodes
                continue
            if t == "symmetry":
                ns = np.array([q[3] for q in tri_points(tris, P)])
                m = ns.mean(0)
                m /= np.linalg.norm(m)
                if np.min(np.abs(ns @ m)) < 1 - 1e-6:
                    raise ValueError("对称面必须是平面：面 {} 不是".format(l["faces"]))
                ax = int(np.argmax(np.abs(m)))
                if abs(m[ax]) > 1 - 1e-9:                         # 与坐标轴平行：直接限该方向
                    dsp.append((nodes, {ax + 1: 0.0}))
                    sup_dofs.append((l, set(nodes), (ax + 1,)))
                else:
                    b = np.cross(m, [1, 0, 0] if abs(m[0]) < 0.9 else [0, 1, 0])
                    rect.append((nodes, m, b, [1]))
                    sup_dofs.append((l, set(nodes), (1, 2, 3)))
                constrained |= nodes
                continue
            if t == "elastic_support":
                k = float(l["stiffness_n_per_mm3"])
                springs += [(n, k * a) for n, a in nodal_areas(tris, P).items() if a > 0]
                sup_dofs.append((l, {n for n, a in nodal_areas(tris, P).items() if a > 0}, (1, 2, 3)))
                continue
            area, cen, pts = face_area_centroid(tris, P)
            if t == "force":
                v = np.array(l["vector_n"], float)
                add(consistent_loads(tris, P, lambda x, n, v=v, A=area: v / A, pts))
            elif t == "pressure":
                p = float(l["value_mpa"])
                add(consistent_loads(tris, P, lambda x, n, p=p: -p * n, pts))
            elif t in ("torque", "moment"):
                if t == "moment":
                    # 问渠第 66 轮：任意方向的力矩 = 绕“过面形心、沿力矩方向”的轴的“扭矩”。面力 = (M/J)·d × r⊥：对端面加弯矩时
                    # d 在面内，d × r⊥ 垂直于面、与到中性轴的距离成正比——正好是梁弯曲的线性正应力分布
                    mv = np.array(l["vector_nmm"], float)
                    if not np.linalg.norm(mv):
                        raise ValueError("力矩的大小是 0")
                    o, d, T = cen, mv / np.linalg.norm(mv), float(np.linalg.norm(mv))
                else:
                    (o, d), T = _axis(l), float(l["value_nmm"])
                add(consistent_loads(tris, P, moment_traction(pts, o, d, T), pts))
            elif t == "remote_load":
                # 远端载荷（RBE3 式的静力等效分配，不增加刚度）：搬到面形心 C：F 不变，M' = M + (Q − C) × F
                F = np.array(l.get("vector_n") or [0, 0, 0], float)
                M = np.array(l.get("vector_nmm") or [0, 0, 0], float) + np.cross(np.array(l["point_mm"], float) - cen, F)
                if np.linalg.norm(F):
                    add(consistent_loads(tris, P, lambda x, n, v=F, A=area: v / A, pts))
                if np.linalg.norm(M):
                    add(consistent_loads(tris, P, moment_traction(pts, cen, M / np.linalg.norm(M), float(np.linalg.norm(M))), pts))
            elif t == "bearing_load":
                # 轴承载荷：受压的半圈上 p = p0·cosθ（θ 为“指向面内的法向”与力方向的夹角），p0 由合力 = |F| 定
                o, d = _axis(l)
                F = np.array(l["vector_n"], float)
                fm = float(np.linalg.norm(F))
                if not fm or abs(np.dot(F, d)) > 1e-6 * fm:
                    raise ValueError("轴承载荷必须是垂直于轴线的径向力")
                fh = F / fm
                c2 = sum(max(float(np.dot(-n, fh)), 0.0) ** 2 * wj for _k, _N, _x, n, wj in pts)
                p0 = fm / c2
                add(consistent_loads(tris, P, lambda x, n, p0=p0, fh=fh: p0 * max(float(np.dot(-n, fh)), 0.0) * (-n), pts))
            else:
                raise ValueError(f"不认识的载荷类型 {t}")
        if not forces and not dload and not delta_t and not any(v for _n, vals in dsp for v in vals.values()):
            raise ValueError("还没有加载荷")
        # 一个节点只能有一个局部坐标系：固定的优先，其次整体坐标下的强制位移（含与坐标轴平行的对称面），再按先后
        seen = set(fixed) | {n for nodes, _v in dsp for n in nodes}
        for nodes, *_ in cyl + rect:
            nodes -= seen
            seen |= nodes
        cyl = [c for c in cyl if c[0]]
        rect = [c for c in rect if c[0]]
        for nodes, _v in dsp:
            nodes -= fixed
        surf = np.concatenate([face_tris(gmsh, f) for f in all_faces])
        face_of = np.concatenate([np.full(len(face_tris(gmsh, f)), f) for f in all_faces])
        n_el, n_nodes = len(tets), len(ntags)
        write_inp(os.path.join(tmp, "job.inp"), ntags, xyz, tets, fixed, cyl, forces, mat, reactions=True,
                  extra={"disp": [x for x in dsp if x[0]], "rect": rect, "springs": springs, "dload": dload, "delta_t_k": delta_t})
        r = _ccx(ccx, tmp, setup.get("time_limit_s", TIME_LIMIT_S))
        frd = os.path.join(tmp, "job.frd")
        if r.returncode < 0:
            raise TooBig("计算被系统中止（多半是内存不够）：请把网格尺寸调大")
        if r.returncode != 0 or not os.path.exists(frd) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]))
        disp, stress, forc = read_frd_rf(frd)
    # 表面节点重新编号
    corner = surf[:, :3]
    used_nodes = np.unique(corner)
    pos = np.array([P[int(n)] for n in used_nodes])
    U = np.array([disp.get(int(n), [0, 0, 0])[:3] for n in used_nodes])
    vm_all = {n: von_mises(s) for n, s in stress.items()}
    VM = np.array([vm_all.get(int(n), 0.0) for n in used_nodes])
    tri_idx = np.searchsorted(used_nodes, corner)
    umag = np.linalg.norm(U, axis=1)
    jmax = int(np.argmax(umag))
    # 评估用：离约束面 1.5h 以外的点（全部节点里找）
    allid = np.array(sorted(vm_all), np.int64)
    allp = np.array([P[int(n)] for n in allid])
    allvm = np.array([vm_all[int(n)] for n in allid])
    ok = np.ones(len(allid), bool)
    if constrained:
        from scipy.spatial import cKDTree
        cp = np.array([P[n] for n in constrained])
        dist, _ = cKDTree(cp).query(allp)
        ok = dist > 1.5 * float(setup.get("exclude_h_mm") or h)     # 收敛核查时各层都按原网格尺寸避开，评估区域不变
    if not ok.any():
        ok[:] = True
    ie = int(np.argmax(np.where(ok, allvm, -1)))
    ia = int(np.argmax(allvm))

    def face_at(nid):
        hit = [int(face_of[k]) for k in np.nonzero((surf == nid).any(axis=1))[0]]
        return sorted(set(hit)) or None

    stats = {"nodes": n_nodes, "elements": n_el, "mesh_size_mm": round(h, 3), "seconds": round(time.time() - t0, 1),
             "vm_max_mpa": round(float(allvm[ie]), 3), "vm_max_at": [round(float(x), 3) for x in allp[ie]],
             "vm_max_faces": face_at(int(allid[ie])),
             "vm_peak_all_mpa": round(float(allvm[ia]), 3), "vm_peak_all_at": [round(float(x), 3) for x in allp[ia]],
             "u_max_mm": round(float(umag.max()), 6), "u_max_at": [round(float(x), 3) for x in pos[jmax]],
             "applied_force_n": [round(float(x), 3) for x in sum(forces.values(), np.zeros(3))]}
    stats["mesh_quality"] = qual
    spring_r = {int(n): [-k * x for x in disp.get(int(n), [0, 0, 0])[:3]] for n, k in springs}
    ext = dict(forces)                                     # 全部外载的节点力：面上的 + 体力的
    for n, f in body_f.items():
        ext[n] = ext.get(n, 0) + f
    stats["balance"] = _balance(ext, {n: v for n, v in forc.items() if n in constrained}, P, springs=spring_r)
    if body_f:
        stats["body_force_n"] = [round(float(x), 6) for x in sum(body_f.values(), np.zeros(3))]
    stats["probes"] = _probes(setup.get("probes") or [], P, disp, stress)
    stats["support_reactions"] = _support_reactions(sup_dofs, forc, ext, spring_r, P)
    stats["vm_max_node"] = int(allid[ie])
    stats["vm_max_local_h_mm"] = _local_h(tets, P, int(allid[ie]), h)
    if setup.get("track_point_mm") is not None:              # 收敛核查：加密球内（各层同一区域）的最大应力
        q = np.asarray(setup["track_point_mm"], float)
        near = ok & (np.linalg.norm(allp - q, axis=1) <= float(setup["track_radius_mm"]))
        cand = np.nonzero(near if near.any() else ok)[0]
        it = int(cand[np.argmax(allvm[cand])])
        stats["vm_at_track_mpa"] = round(float(allvm[it]), 3)
        stats["track_local_h_mm"] = _local_h(tets, P, int(allid[it]), h)
    materials.safety(stats, mat, optional=bool(setup.get("strength_optional")))
    surface = {"positions": np.round(pos, 4), "triangles": tri_idx.astype(np.int32),
               "face_of_triangle": face_of.astype(np.int32), "vm": np.round(VM, 4), "u": np.round(U, 7)}
    return stats, surface, {"vm": vm_all, "nodes": P}


def _balance(forces, reactions, P, springs=None):
    """反力与外载的平衡（ADR-0093 F1）：ΣF + ΣR = 0、Σr×F + Σr×R = 0（对坐标原点）。外载含面上的节点力和体力（重力、离心）的合力、
    合力矩；反力含支承反力和弹性支承的弹簧力。相对误差以外载合力（或各力的模之和）和外载力矩量级为分母。判定在 analysis/fea/trust.py"""
    F = np.zeros(3)
    M = np.zeros(3)
    fsum = 0.0
    msum = 0.0
    for n, f in forces.items():
        f = np.asarray(f, float)
        F += f
        fsum += np.linalg.norm(f)
        m = np.cross(P[n], f)
        M += m
        msum += np.linalg.norm(m)
    R = np.zeros(3)
    MR = np.zeros(3)
    rsum = 0.0
    if not reactions and not springs:
        return {"available": False}
    for n, r in reactions.items():
        # CalculiX 的 RF 是节点上的全部外力（支承反力 + 加在这个节点上的载荷），整体坐标；减去载荷才是支承反力
        r = np.asarray(r[:3], float) - np.asarray(forces.get(n, np.zeros(3)), float)
        R += r
        rsum += np.linalg.norm(r)
        MR += np.cross(P[int(n)], r)
    for n, r in (springs or {}).items():
        r = np.asarray(r, float)
        R += r
        rsum += np.linalg.norm(r)
        MR += np.cross(P[int(n)], r)
    mrsum = sum(float(np.linalg.norm(np.cross(P[int(n)], np.asarray(r[:3], float) - np.asarray(forces.get(n, np.zeros(3)), float))))
                for n, r in reactions.items()) + sum(float(np.linalg.norm(np.cross(P[int(n)], np.asarray(r, float))))
                                                     for n, r in (springs or {}).items())
    # 下限 1 N、1 N × 模型尺寸：没有外载（只有温度变化、强制位移）时力都接近 0，相对误差没有意义
    size = max(float(np.linalg.norm(p)) for p in P.values()) or 1.0
    scale_f = max(np.linalg.norm(F), (fsum + rsum) * 1e-3, 1.0)
    scale_m = max(np.linalg.norm(M), (msum + mrsum) * 1e-3, size)
    return {"available": True, "applied_n": [round(float(x), 6) for x in F], "reaction_n": [round(float(x), 6) for x in R],
            "force_error_ratio": float(np.linalg.norm(F + R) / scale_f),
            "moment_error_ratio": float(np.linalg.norm(M + MR) / scale_m)}


def _support_reactions(sup_dofs, forc, ext, spring_r, P):
    """各支承的反力（整体坐标）与对原点的力矩。一个节点的某个方向被几个支承同时限制时，这个方向的反力算给先写的那个
    （例如拉杆端面的强制位移与侧面对称面共用的棱边节点：x 向反力归强制位移、y 向归对称面）"""
    owner = {}
    for i, (_l, nodes, dofs) in enumerate(sup_dofs):
        for n in nodes:
            for dof in dofs:
                owner.setdefault((n, dof), i)
    R = [np.zeros(3) for _ in sup_dofs]
    M = [np.zeros(3) for _ in sup_dofs]
    for (n, dof), i in owner.items():
        if sup_dofs[i][0]["type"] == "elastic_support":
            v = spring_r.get(n, [0, 0, 0])[dof - 1]
        elif n in forc:
            v = forc[n][dof - 1] - np.asarray(ext.get(n, np.zeros(3)), float)[dof - 1]
        else:
            continue
        e = np.zeros(3)
        e[dof - 1] = v
        R[i] += e
        M[i] += np.cross(P[n], e)
    return [{"type": l["type"], "faces": l.get("faces"), "edges": l.get("edges"),
             "force_n": [round(float(x), 6) for x in R[i]], "moment_nmm": [round(float(x), 4) for x in M[i]]}
            for i, (l, _n, _d) in enumerate(sup_dofs)]


def _probes(probes, P, disp, stress):
    """结果探针：取离给定点最近的节点，报应力张量（节点平均）、Von Mises、位移"""
    if not probes:
        return []
    ids = np.array(sorted(stress), np.int64)
    pts = np.array([P[int(n)] for n in ids])
    out = []
    for pr in probes:
        q = np.asarray(pr["point_mm"], float)
        k = int(np.argmin(np.linalg.norm(pts - q, axis=1)))
        n = int(ids[k])
        s6 = [round(float(x), 6) for x in stress[n][:6]]
        out.append({"id": pr["id"], "point_mm": [float(x) for x in q], "node_at_mm": [round(float(x), 4) for x in pts[k]],
                    "distance_mm": round(float(np.linalg.norm(pts[k] - q)), 4),
                    "stress_mpa": dict(zip(("xx", "yy", "zz", "xy", "yz", "zx"), s6)),
                    "vm_mpa": round(float(von_mises(stress[n])), 6),
                    "u_mm": [round(float(x), 9) for x in disp.get(n, [0, 0, 0])[:3]]})
    return out


def _local_h(tets, P, node, default):
    """某节点周围单元的平均边长（收敛核查按它逐层缩小局部尺寸）"""
    rows = tets[(tets == node).any(axis=1)][:, :4]
    if not len(rows):
        return round(float(default), 4)
    L = [np.linalg.norm(P[int(r[i])] - P[int(r[j])]) for r in rows for i in range(4) for j in range(i + 1, 4)]
    return round(float(np.mean(L)), 4)

