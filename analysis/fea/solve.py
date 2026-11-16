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
import shutil
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
    nt_all, xyz_all, _ = gmsh.model.mesh.getNodes()          # 全部节点：面上的三角形可能用到别的实体上的节点（周期面的接缝、退化点）
    X = dict(zip(nt_all, np.asarray(xyz_all, float).reshape(-1, 3)))
    for _, tag in gmsh.model.getEntities(2):
        et, _, en = gmsh.model.mesh.getElements(2, tag)
        if not len(et):
            continue
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
    """线性静力（单个实体）。返回 (统计, 表面结果, 全部节点应力)。多个实体、连接见 solve_bodies。

    支承：fixed（三个方向都固定）；cyl_support（圆柱面，按柱坐标限制 radial 径向 / tangential 转动 / axial 轴向——
    轴承一般限径向，止推的那个再限轴向，联轴器限转动）。
    约束面附近应力受边界条件影响（圣维南原理），“评估最大应力”不计约束面 1.5 个网格尺寸以内的点；云图照常显示。"""
    body = {"id": "b1", "step_path": step_path, "material": setup["material"], "loads": setup.get("loads") or [],
            "refine_faces": setup.get("refine_faces")}
    return solve_bodies([body], setup, ccx, workdir)


def _prep_body(gmsh, body, setup, tmp):
    """一个实体：读 STEP、划网格、处理它的支承和载荷。节点编号是这一个实体自己的（之后统一加偏移）"""
    mat = body["material"]
    loads = body.get("loads") or []
    load_step(gmsh, body["step_path"], tmp)
    all_faces = [t for _, t in gmsh.model.getEntities(2)]
    conn_faces = sorted(set(body.get("connection_faces") or []))
    used = sorted({f for l in loads for f in l.get("faces") or []} | set(conn_faces))
    bad = [f for f in used if f not in all_faces]
    if bad:
        raise ValueError(f"实体 {body['id']} 没有这些面：{bad}")
    all_edges = [t for _, t in gmsh.model.getEntities(1)]
    bad = sorted({e for l in loads for e in l.get("edges") or [] if e not in all_edges})
    if bad:
        raise ValueError(f"实体 {body['id']} 没有这些边：{bad}")
    size = body.get("size_mm") or (setup.get("mesh") or {}).get("size_mm")
    # 接触面不自动加密：面-面接触的接触单元数随两面三角形数的乘积增长，加密后一次迭代要十几秒（要加密用 refine_faces）
    fine = [f for l in loads if l["type"] not in (*SUPPORTS, "mass") for f in l.get("faces") or []] + list(body.get("refine_faces") or [])
    ntags, xyz, tets = mesh(gmsh, size, fine, setup.get("max_elements", MAX_ELEMENTS), refine=setup.get("refine"))
    h = float(gmsh.option.getNumber("Mesh.MeshSizeMax"))
    qual = quality(gmsh)
    P = {int(t): p for t, p in zip(ntags, xyz)}
    fixed, cyl, forces, constrained = set(), [], {}, set()
    dsp, rect, springs, dload = [], [], [], []
    sup_dofs = []                                      # 各支承：(设置, 节点, 限制的整体自由度)——报各支承的反力
    body_f, delta_t = {}, 0.0                          # 体力的等效节点力（只用于核对平衡）
    masses = {}                                        # 附加质量：节点 → t
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
                    dload.append("{{elset}},GRAV,{:.9g},{:.9g},{:.9g},{:.9g}".format(g, *(acc / g)))
                    for n, f in body_nodal(gmsh, rho, accel=acc).items():
                        body_f[n] = body_f.get(n, 0) + f
            elif t == "centrifugal":
                o, d = _axis(l)
                w2 = (float(l["speed_rpm"]) * 2 * math.pi / 60) ** 2
                dload.append("{{elset}},CENTRIF,{:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g},{:.9g}".format(w2, *o, *d))
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
        if t == "mass":                                    # 附加质量：按节点面积分（ADR-0093 补充十）
            na = {n: a for n, a in nodal_areas(tris, P).items() if a > 0}
            tot = sum(na.values())
            for n, a in na.items():
                masses[n] = masses.get(n, 0.0) + float(l["mass_t"]) * a / tot
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
    if not forces and not dload and not delta_t and not any(v for _n, vals in dsp for v in vals.values()) \
            and not body.get("passive"):
        raise ValueError("还没有加载荷")
    acc_total = sum((np.array(l["acceleration_mm_s2"], float) for l in loads if l["type"] == "gravity"), np.zeros(3))
    if masses and any(l["type"] == "centrifugal" for l in loads):
        raise ValueError("附加质量不能与离心载荷用在同一个实体上（ADR-0093 补充十）")
    if masses and np.any(acc_total):                   # 附加质量的重量按节点加在外载里（t × mm/s² = N）
        add({n: m * acc_total for n, m in masses.items()})
    surf = np.concatenate([face_tris(gmsh, f) for f in all_faces])
    face_of = np.concatenate([np.full(len(face_tris(gmsh, f)), f) for f in all_faces])
    conn = {f: face_tris(gmsh, f) for f in conn_faces}
    return {"id": body["id"], "mat": mat, "plastic": body.get("plastic"), "ntags": np.asarray(ntags, np.int64), "xyz": xyz, "tets": np.asarray(tets, np.int64),
            "P": P, "fixed": fixed, "cyl": cyl, "dsp": dsp, "rect": rect, "springs": springs, "forces": forces,
            "body_f": body_f, "sup_dofs": sup_dofs, "constrained": constrained, "dload": dload, "delta_t": delta_t,
            "surf": surf, "face_of": face_of, "conn": conn, "h": h, "qual": qual, "masses": masses}


def _shift(B, off):
    """实体的节点编号整体加 off（多个实体合成一个模型）"""
    if not off:
        return B
    m = lambda ns: {int(n) + off for n in ns}
    B["ntags"] = B["ntags"] + off
    B["tets"] = B["tets"] + off
    B["P"] = {n + off: p for n, p in B["P"].items()}
    B["fixed"] = m(B["fixed"])
    B["constrained"] = m(B["constrained"])
    B["cyl"] = [(m(ns), o, d, dofs) for ns, o, d, dofs in B["cyl"]]
    B["rect"] = [(m(ns), a, b, dofs) for ns, a, b, dofs in B["rect"]]
    B["dsp"] = [(m(ns), v) for ns, v in B["dsp"]]
    B["springs"] = [(int(n) + off, k) for n, k in B["springs"]]
    B["forces"] = {int(n) + off: f for n, f in B["forces"].items()}
    B["body_f"] = {int(n) + off: f for n, f in B["body_f"].items()}
    B["masses"] = {int(n) + off: v for n, v in B.get("masses", {}).items()}
    B["sup_dofs"] = [(l, m(ns), dofs) for l, ns, dofs in B["sup_dofs"]]
    B["surf"] = B["surf"] + off
    B["conn"] = {f: t + off for f, t in B["conn"].items()}
    return B


# CalculiX C3D10 的四个面（按 CalculiX 的节点次序 1..4）：S1 = 1-2-3、S2 = 1-4-2、S3 = 2-4-3、S4 = 3-4-1
_CCX_FACES = {1: (0, 1, 2), 2: (0, 3, 1), 3: (1, 3, 2), 4: (2, 3, 0)}


def _element_faces(tets_ccx, eid0, tris):
    """面上的三角形 → (单元号, 面号)，用于 *SURFACE TYPE=ELEMENT（接触、绑定的主面）"""
    want = {frozenset(int(x) for x in t[:3]) for t in tris}
    out = []
    for i, e in enumerate(tets_ccx):
        for fn, (a, b, c) in _CCX_FACES.items():
            if frozenset((e[a], e[b], e[c])) in want:
                out.append((eid0 + i + 1, fn))
    return out


_GMSH_MID = {4: (0, 1), 5: (1, 2), 6: (0, 2), 7: (0, 3), 8: (2, 3), 9: (1, 3)}   # gmsh 二阶四面体的边中节点


def _tri6_area_vector(x):
    """六节点曲边三角形（角点 0-2，边中 01、12、20）的面积向量 ∫ ∂x/∂ξ × ∂x/∂η，三点积分（被积函数二次，精确）"""
    x = np.asarray(x, float)
    out = np.zeros(3)
    for xi, eta in ((1 / 6, 1 / 6), (2 / 3, 1 / 6), (1 / 6, 2 / 3)):
        l0 = 1 - xi - eta
        dxi = np.array([-(4 * l0 - 1), 4 * xi - 1, 0, 4 * (l0 - xi), 4 * eta, -4 * eta])
        deta = np.array([-(4 * l0 - 1), 0, 4 * eta - 1, -4 * xi, 4 * xi, 4 * (l0 - eta)])
        out += np.cross(dxi @ x, deta @ x) / 6
    return out


def _bolt_cut(B, bolt, next_id):
    """螺栓预紧截面：按单元形心在截面哪一侧把实体分成两半，截面上的节点复制一份给“上侧”的单元，
    两侧用约束方程连接。返回 (节点对 [(下侧, 上侧)], 截面面积 mm²)，并改写 B 的单元与表面三角形。"""
    p0 = np.asarray(bolt["point_mm"], float)
    d = np.asarray(bolt["axis_dir"], float)
    d = d / np.linalg.norm(d)
    P = B["P"]
    corners = B["tets"][:, :4]
    cen = np.array([np.mean([P[int(n)] for n in e], axis=0) for e in corners])
    up = (cen - p0) @ d > 0
    if up.all() or not up.any():
        raise ValueError(f"螺栓预紧截面没有穿过实体 {B['id']}")
    lo_nodes = {int(n) for n in B["tets"][~up].ravel()}
    up_nodes = {int(n) for n in B["tets"][up].ravel()}
    sec = sorted(lo_nodes & up_nodes)
    dup = {n: next_id + i for i, n in enumerate(sec)}
    t = B["tets"].copy()
    for i in np.nonzero(up)[0]:
        t[i] = [dup.get(int(n), int(n)) for n in t[i]]
    B["tets"] = t
    for n in sec:
        B["P"][dup[n]] = P[n]
    B["ntags"] = np.concatenate([B["ntags"], np.array([dup[n] for n in sec], np.int64)])
    B["xyz"] = np.vstack([B["xyz"], np.array([P[n] for n in sec])])
    sc = np.array([np.mean([P[int(n)] for n in tri[:3]], axis=0) for tri in B["surf"]])
    sup = (sc - p0) @ d > 0
    s2 = B["surf"].copy()
    for i in np.nonzero(sup)[0]:
        s2[i] = [dup.get(int(n), int(n)) for n in s2[i]]
    B["surf"] = s2
    # 截面：下侧单元上角点都在截面节点上的面（截面按单元形心切开，是锯齿状的）。面积取它在垂直于轴线的平面上的投影
    # （按单元外法向带符号相加，锯齿的折返部分正负抵消）；螺栓力由 CalculiX 在这些面上积分应力得到（*SECTION PRINT）
    area = 0.0
    secset = set(sec)
    faces = []
    for i in np.nonzero(~up)[0]:
        e = corners[i]
        mid = {frozenset((int(B["tets"][i][x]), int(B["tets"][i][y]))): int(B["tets"][i][m]) for m, (x, y) in _GMSH_MID.items()}
        for fn, (a, b, c) in _CCX_FACES.items():
            f = [int(e[a]), int(e[b]), int(e[c])]
            if all(x in secset for x in f):
                other = next(int(x) for x in e if int(x) not in f)
                ms = [mid[frozenset((f[0], f[1]))], mid[frozenset((f[1], f[2]))], mid[frozenset((f[2], f[0]))]]
                a6 = _tri6_area_vector([P[x] for x in f + ms])
                if np.dot(np.cross(P[f[1]] - P[f[0]], P[f[2]] - P[f[0]]), P[other] - P[f[0]]) > 0:
                    a6 = -a6
                area += float(np.dot(a6, d))
                faces.append((int(i), fn))
    return [(n, dup[n]) for n in sec], abs(area), d, faces


def _write_multi(path, Bs, conns, bolts, contact, reactions=True, nlgeom=False, buckle=0, sup_sets=(), frequency=0, prestress=False):
    """多个实体、连接、螺栓预紧的输入文件（ADR-0093 F3）"""
    with open(path, "w") as w:
        w.write("*HEADING\nWenQuest CAE\n*NODE, NSET=NALL\n")
        for B in Bs:
            w.writelines("{},{:.9g},{:.9g},{:.9g}\n".format(t, *B["P"][int(t)]) for t in B["ntags"])
        w.writelines("{},{:.9g},{:.9g},{:.9g}\n".format(bl["ref"], *bl["point"]) for bl in bolts)
        eid = 0
        for k, B in enumerate(Bs, 1):
            w.write(f"*ELEMENT, TYPE=C3D10, ELSET=B{k}\n")
            B["eid0"] = eid
            B["ccx"] = [[int(e[j]) for j in GMSH2CCX_TET10] for e in B["tets"]]
            w.writelines("{},{}\n".format(eid + i, ",".join(map(str, e))) for i, e in enumerate(B["ccx"], 1))
            eid += len(B["tets"])
        w.write("*ELSET, ELSET=EALL\n" + ",".join(f"B{k}" for k in range(1, len(Bs) + 1)) + "\n")
        j = 0
        for B in Bs:                                               # 附加质量：每个节点一个 MASS 单元（不在 EALL 里，不受 GRAV）
            for n, m in sorted(B.get("masses", {}).items()):
                eid += 1
                j += 1
                w.write(f"*ELEMENT, TYPE=MASS, ELSET=MS{j}\n{eid},{n}\n*MASS, ELSET=MS{j}\n{m:.9g}\n")
        fixed = set().union(*(B["fixed"] for B in Bs))
        cyl = [c for B in Bs for c in B["cyl"]]
        rect = [c for B in Bs for c in B["rect"]]
        dsp = [c for B in Bs for c in B["dsp"] if c[0]]
        springs = [c for B in Bs for c in B["springs"]]
        if fixed:
            _nset(w, "FIX", fixed)
        for k, (nodes, o, d, _dofs) in enumerate(cyl, 1):
            _nset(w, f"CYL{k}", nodes)
            a, b = np.asarray(o, float), np.asarray(o, float) + 100 * np.asarray(d, float)
            w.write("*TRANSFORM, NSET=CYL{}, TYPE=C\n{}\n".format(k, ",".join(f"{x:.9g}" for x in [*a, *b])))
        for k, (nodes, a, b, _dofs) in enumerate(rect, 1):
            _nset(w, f"REC{k}", nodes)
            w.write("*TRANSFORM, NSET=REC{}, TYPE=R\n{}\n".format(k, ",".join(f"{x:.9g}" for x in [*a, *b])))
        for k, (nodes, _vals) in enumerate(dsp, 1):
            _nset(w, f"DSP{k}", nodes)
        for k, (n, kk) in enumerate(springs, 1):
            for dof in (1, 2, 3):
                eid += 1
                w.write(f"*ELEMENT, TYPE=SPRING1, ELSET=SP{k}_{dof}\n{eid},{int(n)}\n*SPRING, ELSET=SP{k}_{dof}\n{dof}\n{kk:.9g}\n")
        # 连接
        for k, c in enumerate(conns, 1):
            Ba, Bb = Bs[c["a_body"]], Bs[c["b_body"]]
            ta = np.concatenate([Ba["conn"][f] for f in c["a_faces"]])
            tb = np.concatenate([Bb["conn"][f] for f in c["b_faces"]])
            sb = _element_faces(Bb["ccx"], Bb["eid0"], tb)
            w.write(f"*SURFACE, NAME=M{k}, TYPE=ELEMENT\n" + "".join(f"{e},S{f}\n" for e, f in sb))
            if c["type"] == "bonded":
                _nset(w, f"SN{k}", {int(n) for n in ta.ravel()})
                w.write(f"*SURFACE, NAME=S{k}, TYPE=NODE\nSN{k}\n")
                w.write("*TIE, NAME=T{}, POSITION TOLERANCE={:.9g}\nS{},M{}\n".format(k, c["tolerance_mm"], k, k))
            else:
                sa = _element_faces(Ba["ccx"], Ba["eid0"], ta)
                w.write(f"*SURFACE, NAME=S{k}, TYPE=ELEMENT\n" + "".join(f"{e},S{f}\n" for e, f in sa))
                w.write(f"*CONTACT PAIR, INTERACTION=I{k}, TYPE=SURFACE TO SURFACE\nS{k},M{k}\n")
                w.write("*SURFACE INTERACTION, NAME=I{}\n*SURFACE BEHAVIOR, PRESSURE-OVERCLOSURE=LINEAR\n{:.9g}\n".format(
                    k, c["penalty"]))
                if c.get("mu"):
                    w.write("*FRICTION\n{:.9g},{:.9g}\n".format(c["mu"], c["stick_slope"]))
        # 螺栓预紧：上侧 − 下侧的法向相对位移 = 参考节点的位移（第 1 自由度）；切向两侧一起动
        if bolts:
            w.write("*EQUATION\n")
        for bl in bolts:
            d = bl["dir"]
            t1 = np.cross(d, [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0])
            t1 /= np.linalg.norm(t1)
            t2 = np.cross(d, t1)
            dofs = list(np.argsort(-np.abs(d)))                    # 上侧节点的被消去自由度：三个方程各用一个
            dep = [dofs[0]]
            for v in (t1, t2):
                rest = [i for i in np.argsort(-np.abs(v)) if i not in dep]
                dep.append(rest[0])
            for lo, up in bl["pairs"]:
                for v, j, ref in ((d, dep[0], True), (t1, dep[1], False), (t2, dep[2], False)):
                    terms = [(up, j + 1, v[j])] + [(up, i + 1, v[i]) for i in range(3) if i != j and abs(v[i]) > 1e-12]
                    terms += [(lo, i + 1, -v[i]) for i in range(3) if abs(v[i]) > 1e-12]
                    if ref:
                        terms.append((bl["ref"], 1, -1.0))
                    w.write(f"{len(terms)}\n" + ",".join("{},{},{:.12g}".format(*x) for x in terms) + "\n")
            _nset(w, f"BREF{bl['k']}", {bl["ref"]})
            e0 = Bs[bl["body"]]["eid0"]
            w.write(f"*SURFACE, NAME=BS{bl['k']}, TYPE=ELEMENT\n" + "".join(f"{e0 + i + 1},S{fn}\n" for i, fn in bl["faces"]))
        for k, B in enumerate(Bs, 1):
            m = B["mat"]
            w.write("*MATERIAL, NAME=M{}\n*ELASTIC\n{:.9g},{:.9g}\n*DENSITY\n{:.9g}\n".format(
                k, m["elastic_modulus_mpa"], m["poisson_ratio"], m["density_kg_m3"] * 1e-12))   # kg/m³ → t/mm³
            if B.get("plastic"):                                   # Mises 屈服、各向同性硬化：真应力, 塑性应变（最后一点之后水平）
                w.write("*PLASTIC\n" + "".join(f"{sg:.9g},{ep:.9g}\n" for sg, ep in B["plastic"]))
            if any(x["delta_t"] for x in Bs):
                if not m.get("thermal_expansion_per_k"):
                    raise ValueError(f"实体 {B['id']} 的材料缺线膨胀系数，不能加温度载荷")
                w.write("*EXPANSION\n{:.9g}\n".format(m["thermal_expansion_per_k"]))
            w.write(f"*SOLID SECTION, ELSET=B{k}, MATERIAL=M{k}\n")
        delta_t = sum(B["delta_t"] for B in Bs)
        if delta_t:
            w.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\nNALL,20\n")
        plastic = any(B.get("plastic") for B in Bs)
        freq_step = f"*STEP{', PERTURBATION' if prestress else ''}\n*FREQUENCY, SOLVER={SOLVER}\n{int(frequency)}\n"
        if buckle:
            head = f"*STEP\n*BUCKLE, SOLVER={SOLVER}\n{int(buckle)}\n"
        elif prestress:                                            # 预应力模态：先大变形静力（应力刚度要 NLGEOM 才进入下一步）
            head = f"*STEP, NLGEOM, INC=100\n*STATIC, SOLVER={SOLVER}\n0.25,1\n"
        elif plastic or nlgeom:                                    # 非线性：小增量起步，增量不超过 5 %（载荷—位移历程看得清）
            head = "*STEP{}, INC=2000\n*STATIC, SOLVER={}\n0.02,1,1e-5,0.05\n".format(", NLGEOM" if nlgeom else "", SOLVER)
        elif contact:
            head = f"*STEP, INC=300\n*STATIC, SOLVER={SOLVER}\n0.1,1\n"
        else:
            head = f"*STEP\n*STATIC, SOLVER={SOLVER}\n"
        out = "*NODE FILE\n{}\n*EL FILE\n{}\n{}".format("U,RF" if reactions else "U", "S,PEEQ" if plastic else "S",
                                                         "*CONTACT FILE\nCSTR\n" if contact else "")
        if buckle:
            out = "*NODE FILE\nU\n"
        for name, nodes in sup_sets:                               # 非线性：各支承每个增量的反力合力（载荷—位移历程）
            _nset(w, name, nodes)
        out += "".join(f"*NODE PRINT, NSET={name}, TOTALS=ONLY\nRF\n" for name, _n in sup_sets)
        if bolts:
            out += "".join(f"*SECTION PRINT, SURFACE=BS{bl['k']}, NAME=SP{bl['k']}\nSOF\n" for bl in bolts)

        def bcs():
            w.write("*BOUNDARY\n")
            if fixed:
                w.write("FIX,1,3,0\n")
            for k, (_, _, _, dofs) in enumerate(cyl, 1):
                w.writelines(f"CYL{k},{dof},{dof},0\n" for dof in dofs)
            for k, (_, _, _, dofs) in enumerate(rect, 1):
                w.writelines(f"REC{k},{dof},{dof},0\n" for dof in dofs)
        if frequency and not prestress:                            # 模态：只有支承，没有载荷
            w.write(freq_step)
            bcs()
            for k, (_, vals) in enumerate(dsp, 1):                 # 强制位移在这里都是 0（非零的已拒算）
                w.writelines(f"DSP{k},{dof},{dof},{v:.9g}\n" for dof, v in sorted(vals.items()))
            w.write("*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")
            return
        if bolts:                                                  # 第一步：只加预紧
            w.write(head)
            bcs()
            w.write("*CLOAD\n" + "".join("{},1,{:.9g}\n".format(bl["ref"], -bl["force"]) for bl in bolts))
            w.write(out + "*END STEP\n")
        w.write(head)
        bcs()
        for k, (_, vals) in enumerate(dsp, 1):
            w.writelines(f"DSP{k},{dof},{dof},{v:.9g}\n" for dof, v in sorted(vals.items()))
        if bolts:
            w.write("*BOUNDARY, FIXED\n" + "".join("{},1\n".format(bl["ref"]) for bl in bolts))
        forces = {}
        for B in Bs:
            for n, f in B["forces"].items():
                forces[n] = forces.get(n, 0) + f
        if forces or bolts:
            w.write("*CLOAD{}\n".format(", OP=NEW" if bolts else ""))
            for n, f in forces.items():
                for d in range(3):
                    if abs(f[d]) > 0:
                        w.write(f"{int(n)},{d + 1},{f[d]:.9g}\n")
        dl = [x.format(elset=f"B{k}") for k, B in enumerate(Bs, 1) for x in B["dload"]]
        if dl:
            w.write("*DLOAD\n" + "".join(x + "\n" for x in dl))
        if delta_t:
            w.write(f"*TEMPERATURE\nNALL,{20 + float(delta_t):.9g}\n")
        w.write(out + "*END STEP\n")
        if prestress:
            w.write(freq_step + "*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")


def _read_blocks(path, upto=None):
    """.frd 里最后一步的各结果块 {名字: {节点: 数值}}。upto=(分析步, 增量)：只读到这个增量为止——
    非线性没收敛时 CalculiX 会把最后一次没收敛的迭代也写进 .frd（供排错），那一块不能当结果"""
    blocks, cur, here = {}, None, (0, 0)
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("    1PSTEP"):
                v = line.split()
                here = (int(v[3]), int(v[2])) if len(v) >= 4 else here
            elif line.startswith(" -4"):
                name = line.split()[1]
                cur = blocks.setdefault(name, {}) if upto is None or here <= upto else None
            elif line.startswith(" -3"):
                cur = None
            elif cur is not None and line.startswith(" -1"):
                nid = int(line[3:13])
                vals = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line.rstrip("\n")) - 13) // 12)]
                cur[nid] = vals
    return blocks


def _last_converged(sta):
    """.sta 里最后一个收敛的 (分析步, 增量)：尝试号后面带 U 的是没收敛、要减小增量重试的"""
    last = None
    if not os.path.exists(sta):
        return last
    with open(sta, errors="replace") as f:
        for line in f:
            v = line.split()
            if len(v) >= 4 and v[0].isdigit() and v[1].isdigit() and not v[2].endswith("U"):
                last = (int(v[0]), int(v[1]))
    return last


def _read_dat_totals(path, sets):
    """.dat 里非线性各增量的 *NODE PRINT TOTALS=ONLY：[{load_fraction, totals: {集合名: (fx, fy, fz)}}]（时间就是载荷比例）"""
    out, cur, want = [], None, False
    if not os.path.exists(path) or not sets:
        return out
    with open(path, errors="replace") as f:
        for line in f:
            low = line.strip().lower()
            if low.startswith("total force (fx,fy,fz) for set"):
                name = line.split("for set")[1].split()[0].upper()
                t = float(low.split("time")[-1])
                cur, want = (name, t), name in sets
                continue
            if cur and want and line.strip():
                v = tuple(float(x) for x in line.split()[:3])
                if not out or abs(out[-1]["load_fraction"] - cur[1]) > 1e-12:
                    out.append({"load_fraction": cur[1], "totals": {}})
                out[-1]["totals"][cur[0]] = v
                cur, want = None, False
    return out


def _read_mode_blocks(path):
    """频率步的每一阶：[{"DISP": {节点: [ux, uy, uz]}, "STRESS": {节点: [6 个分量]}}]（按阶次）"""
    modes, cur, mode = {}, None, None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("  100C"):
                v = line.split()
                mode = next((int(x[:-5]) for x in v if x.endswith("MODAL") and x[:-5].isdigit()), None)
            elif line.startswith(" -4"):
                name = line.split()[1]
                cur = modes.setdefault(mode, {}).setdefault(name, {}) if mode is not None and name in ("DISP", "STRESS") else None
            elif line.startswith(" -3"):
                cur = None
            elif cur is not None and line.startswith(" -1"):
                cur[int(line[3:13])] = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line.rstrip("\n")) - 13) // 12)]
    return [modes[k] for k in sorted(modes)]


def _read_participation(path):
    """频率步 .dat 里的参与系数、有效质量（各阶 x、y、z 平动）和总有效质量（t）"""
    gam, eff, total, sec = [], [], None, None
    if not os.path.exists(path):
        return gam, eff, total
    with open(path, errors="replace") as f:
        for line in f:
            if "P A R T I C I P A T I O N" in line:
                sec = "g"
                continue
            if "T O T A L   E F F E C T I V E" in line:
                sec = "t"
                continue
            if "E F F E C T I V E   M O D A L" in line:
                sec = "e"
                continue
            v = line.split()
            if not v or sec is None:
                continue
            try:
                nums = [float(x) for x in v]
            except ValueError:
                continue
            if sec == "g" and len(nums) >= 4:
                gam.append(nums[1:4])
            elif sec == "e" and len(nums) >= 4:
                eff.append(nums[1:4])
            elif sec == "t" and len(nums) >= 3:
                total = nums[:3]
                sec = None
    return gam, eff, total


def _modal_result(Bs, tmp, n_nodes, n_el, t0, prestress):
    """模态结果（质量归一化的振型，CalculiX 缺省如此）：频率、振型、振型应力、参与系数、有效质量，加上载荷向量和表面，
    供 analysis/fea/dynamics.py 做模态叠加"""
    from analysis.fea.modal import RIGID_HZ, read_freqs

    dat, frd = os.path.join(tmp, "job.dat"), os.path.join(tmp, "job.frd")
    freqs = [hz for _k, hz in read_freqs(dat)]
    blocks = _read_mode_blocks(frd)
    gam, eff, total = _read_participation(dat)
    keep = [i for i, hz in enumerate(freqs) if hz >= RIGID_HZ and i < len(blocks)]
    if not keep:
        raise RuntimeError("没有求出弹性振型（支承是否太少？）")
    P = {}
    for B in Bs:
        P.update(B["P"])
    ids = np.array(sorted(P), np.int64)
    phi = np.zeros((len(ids), 3, len(keep)))
    sig = np.zeros((len(ids), 6, len(keep)))
    for j, i in enumerate(keep):
        d, st = blocks[i].get("DISP", {}), blocks[i].get("STRESS", {})
        phi[:, :, j] = np.array([d.get(int(n), [0, 0, 0])[:3] for n in ids])
        sig[:, :, j] = np.array([st.get(int(n), [0] * 6)[:6] for n in ids])
    ext = {}
    for B in Bs:
        for src in (B["forces"], B["body_f"]):
            for n, f in src.items():
                ext[n] = ext.get(n, 0) + np.asarray(f, float)
    F = np.zeros((len(ids), 3))
    pos = {int(n): k for k, n in enumerate(ids)}
    for n, f in ext.items():
        F[pos[int(n)]] += f
    surf = np.concatenate([B["surf"] for B in Bs])
    corner = surf[:, :3]
    used = np.unique(corner)
    return {"nodes": n_nodes, "elements": n_el, "mesh_size_mm": round(min(B["h"] for B in Bs), 3),
            "seconds": round(time.time() - t0, 1), "mesh_quality": _merge_quality([B["qual"] for B in Bs]),
            "prestress": prestress, "rigid_modes": sum(1 for hz in freqs if hz < RIGID_HZ),
            "freqs_hz": np.array([freqs[i] for i in keep]), "node_ids": ids, "xyz": np.array([P[int(n)] for n in ids]),
            "phi": phi, "sig": sig, "load": F,
            "gamma": np.array([gam[i] for i in keep]) if len(gam) >= len(freqs) else None,
            "eff_mass": np.array([eff[i] for i in keep]) if len(eff) >= len(freqs) else None,
            "total_mass": np.array(total) if total else None,
            "constrained": set().union(*(B["constrained"] for B in Bs)),
            "surface": {"positions": np.array([P[int(n)] for n in used]), "triangles": np.searchsorted(used, corner).astype(np.int32),
                        "face_of_triangle": np.concatenate([B["face_of"] for B in Bs]).astype(np.int32), "nodes": used}}, None, None


def _read_buckling(path):
    """.dat 里的屈曲系数（*BUCKLE）"""
    out, on = [], False
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for line in f:
            if "B U C K L I N G" in line:
                on = True
                continue
            if on:
                v = line.split()
                if len(v) == 2 and v[0].isdigit():
                    out.append(float(v[1]))
                elif out and not line.strip():
                    on = False
    return out


def _ext_total(Bs):
    out = {}
    for B in Bs:
        for n, f in B["forces"].items():
            out[n] = out.get(n, 0) + f
    return out


def _history(history, sup_sets, sup_dofs, ext):
    """载荷—位移历程：每个增量的载荷比例、各支承的反力合力（减去按比例加在这些节点上的载荷）"""
    names = [(name, i) for (name, nodes), i in zip(sup_sets, [int(n[3:]) - 1 for n, _ in sup_sets])]
    out = []
    for h in history:
        t = h["load_fraction"]
        row = {"load_fraction": round(t, 6), "supports": []}
        for name, i in names:
            l, nodes, _d = sup_dofs[i]
            v = np.asarray(h["totals"].get(name, (0, 0, 0)), float)
            v = v - t * sum((np.asarray(ext.get(n, np.zeros(3)), float) for n in nodes), np.zeros(3))
            row["supports"].append({"type": l["type"], "faces": l.get("faces"), "force_n": [round(float(x), 4) for x in v]})
        out.append(row)
    return out


def _read_dat_sof(path, sets):
    """.dat 里 *SECTION PRINT 的截面合力：{面名: [每个时间点的 (fx, fy, fz)]}"""
    out, cur, want = {}, None, False
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as f:
        for line in f:
            low = line.strip().lower()
            if low.startswith("statistics for surface set"):
                name = line.split("surface set")[1].split()[0].upper()
                cur = name if name in sets else None
                want = False
                continue
            if cur and low.startswith("total surface force"):
                want = True
                continue
            if cur and want and line.strip():
                out.setdefault(cur, []).append(tuple(float(x) for x in line.split()[:3]))
                cur, want = None, False
    return out


def solve_bodies(bodies, setup, ccx, workdir=None):
    """线性静力；多个实体（各自的材料）、绑定、接触、螺栓预紧（ADR-0093 F3）。
    bodies：[{id, step_path, material, loads, refine_faces?, connection_faces?, contact_faces?, passive?}]；
    setup["connections"]：[{type: bonded / contact, a_body, a_faces, b_body, b_faces, mu?, tolerance_mm?}]（a_body 为下标）；
    setup["bolts"]：[{body（下标）, point_mm, axis_dir, force_n}]"""
    t0 = time.time()
    allloads = [l for b in bodies for l in b.get("loads") or []]
    if not any(l["type"] in SUPPORTS for l in allloads):
        raise ValueError("至少要有一个固定或支承面，否则零件会整体移动、算不出来")
    moved = any(l["type"] == "displacement" and any(l.get(k) for k in ("ux_mm", "uy_mm", "uz_mm")) for l in allloads)
    bolts_in = setup.get("bolts") or []
    conns_in = setup.get("connections") or []
    pressed = any(c["type"] == "contact" for c in conns_in)        # 过盈配合：初始穿透本身就是载荷
    frequency = int(setup.get("frequency") or 0)
    prestress = bool(setup.get("prestress")) and bool(frequency)
    if not any(l["type"] not in (*SUPPORTS, "mass") for l in allloads) and not moved and not bolts_in and not pressed \
            and (not frequency or prestress):
        raise ValueError("还没有加载荷")
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        Bs, off = [], 0
        for k, body in enumerate(bodies):
            if k:
                gmsh.clear()
            b = dict(body)
            b["passive"] = len(bodies) > 1 or bool(bolts_in) or pressed or bool(frequency)
            b["connection_faces"] = [f for c in conns_in for side in ("a", "b") if c[side + "_body"] == k for f in c[side + "_faces"]]
            b["contact_faces"] = [f for c in conns_in if c["type"] == "contact" for side in ("a", "b")
                                  if c[side + "_body"] == k for f in c[side + "_faces"]]
            B = _shift(_prep_body(gmsh, b, setup, tmp), off)
            off = int(max(B["ntags"].max(), max(B["P"]))) + 1
            Bs.append(B)
        # 一个节点只能有一个局部坐标系：固定的优先，其次整体坐标下的强制位移（含与坐标轴平行的对称面），再按先后
        fixed = set().union(*(B["fixed"] for B in Bs))
        seen = set(fixed) | {n for B in Bs for nodes, _v in B["dsp"] for n in nodes}
        for B in Bs:
            for nodes, *_ in B["cyl"] + B["rect"]:
                nodes -= seen
                seen |= nodes
            B["cyl"] = [c for c in B["cyl"] if c[0]]
            B["rect"] = [c for c in B["rect"] if c[0]]
            for nodes, _v in B["dsp"]:
                nodes -= fixed
        bolts = []
        for k, bl in enumerate(bolts_in, 1):
            B = Bs[bl["body"]]
            ref = off
            pairs, area, d, faces = _bolt_cut(B, bl, off + 1)
            off += len(pairs) + 2
            bolts.append({"k": k, "ref": ref, "pairs": pairs, "dir": d, "force": float(bl["force_n"]), "body": bl["body"], "faces": faces,
                          "point": np.asarray(bl["point_mm"], float), "area": area, "id": bl.get("id") or f"bolt{k}"})
        hmin = min(B["h"] for B in Bs)
        emax = max(B["mat"]["elastic_modulus_mpa"] for B in Bs)
        conns = []
        for c in conns_in:
            c = dict(c)
            if c["type"] == "bonded":
                c["tolerance_mm"] = float(c.get("tolerance_mm") or 0.1 * hmin)
            else:
                # 罚刚度（N/mm³）：10·E/h——穿透量约为接触压力的 h/(10E)，与单元变形相比可忽略、又不至于让迭代难收敛
                c["penalty"] = 10 * emax / hmin
                c["mu"] = float(c.get("mu") or 0)
                c["stick_slope"] = c["penalty"] / 10
            conns.append(c)
        contact = any(c["type"] == "contact" for c in conns)
        n_el = sum(len(B["tets"]) for B in Bs)
        n_nodes = sum(len(B["ntags"]) for B in Bs)
        nlgeom = bool(setup.get("nlgeom"))
        buckle = int(setup.get("buckle") or 0)
        plastic = any(B.get("plastic") for B in Bs)
        if buckle and (contact or bolts or plastic):
            raise ValueError("线性屈曲不能带接触、螺栓预紧或弹塑性材料（线性屈曲以线弹性、固定的连接为前提）")
        nonlin = (plastic or nlgeom) and not buckle
        sup_sets = []
        if nonlin:
            for i, (l, nodes, _d) in enumerate(sup_dofs_all := [c for B in Bs for c in B["sup_dofs"]], 1):
                if l["type"] != "elastic_support" and nodes:
                    sup_sets.append((f"SUP{i}", nodes))
        if frequency and (contact or bolts or plastic or nlgeom or buckle):
            raise ValueError("模态与动力学只用于线性模型：不能带接触、螺栓预紧、弹塑性、大变形")
        if frequency and (any(B["delta_t"] for B in Bs) or any(v for B in Bs for _n, vals in B["dsp"] for v in vals.values())):
            raise ValueError("模态与动力学不能带温度载荷或非零的强制位移")
        _write_multi(os.path.join(tmp, "job.inp"), Bs, conns, bolts, contact, nlgeom=nlgeom, buckle=buckle, sup_sets=sup_sets,
                     frequency=frequency, prestress=prestress)
        r = _ccx(ccx, tmp, setup.get("time_limit_s", TIME_LIMIT_S))
        frd = os.path.join(tmp, "job.frd")
        dat = os.path.join(tmp, "job.dat")
        if r.returncode < 0:
            raise TooBig("计算被系统中止（多半是内存不够）：请把网格尺寸调大")
        history = _read_dat_totals(dat, {n for n, _ in sup_sets}) if nonlin else []
        partial = False
        if nonlin and (r.returncode != 0 or "*ERROR" in r.stdout) and history and os.path.exists(frd):
            partial = True                                          # 没算完全部载荷：如实报算到哪一成（塑性垮塌或不收敛）
        elif r.returncode != 0 or not os.path.exists(frd) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            hint = "；可能有零件没有被约束住（只靠无摩擦接触时会整体滑动）" if contact else ""
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]) + hint)
        if setup.get("keep_dir") and not partial:           # 留下求解器的输入与结果文件（FreeCAD 原生后处理读，ADR-0093 补充十二）
            os.makedirs(setup["keep_dir"], exist_ok=True)
            for name in ("job.inp", "job.frd", "job.dat"):
                if os.path.exists(os.path.join(tmp, name)):
                    shutil.copy(os.path.join(tmp, name), os.path.join(setup["keep_dir"], name))
        if frequency:
            return _modal_result(Bs, tmp, n_nodes, n_el, t0, prestress)
        if buckle:
            factors = _read_buckling(dat)
            if not factors:
                raise RuntimeError("求解失败：没有读到屈曲系数")
            return ({"nodes": n_nodes, "elements": n_el, "mesh_size_mm": round(min(B["h"] for B in Bs), 3),
                     "seconds": round(time.time() - t0, 1), "mesh_quality": _merge_quality([B["qual"] for B in Bs]),
                     "load_factors": [round(f, 6) for f in factors]}, None, None)
        upto = _last_converged(os.path.join(tmp, "job.sta")) if partial else None
        if partial and upto is None:
            raise RuntimeError("求解失败：第一个增量就没有收敛（检查约束是否足够、载荷是否过大）")
        blocks = _read_blocks(frd, upto)
        disp, stress, forc = blocks.get("DISP", {}), blocks.get("STRESS", {}), blocks.get("FORC", {})
        peeq = {n: v[0] for n, v in (blocks.get("PE") or {}).items()}
        bolt_sof = _read_dat_sof(dat, {f"BS{bl['k']}" for bl in bolts})
    P = {}
    for B in Bs:
        P.update(B["P"])
    constrained = set().union(*(B["constrained"] for B in Bs))
    forces, body_f = {}, {}
    for B in Bs:
        for n, f in B["forces"].items():
            forces[n] = forces.get(n, 0) + f
        for n, f in B["body_f"].items():
            body_f[n] = body_f.get(n, 0) + f
    springs = [c for B in Bs for c in B["springs"]]
    sup_dofs = [c for B in Bs for c in B["sup_dofs"]]
    h = Bs[0]["h"] if len(Bs) == 1 else hmin
    # 表面节点重新编号
    surf = np.concatenate([B["surf"] for B in Bs])
    face_of = np.concatenate([B["face_of"] for B in Bs])
    body_of = np.concatenate([np.full(len(B["surf"]), k) for k, B in enumerate(Bs)])
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
    allid = np.array(sorted(n for n in vm_all if n in P), np.int64)
    allp = np.array([P[int(n)] for n in allid])
    allvm = np.array([vm_all[int(n)] for n in allid])
    node_body = np.zeros(len(allid), np.int64)
    for k, B in enumerate(Bs):
        node_body[np.isin(allid, np.fromiter(B["P"].keys(), np.int64))] = k
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

    tets_all = np.concatenate([B["tets"] for B in Bs])
    stats = {"nodes": n_nodes, "elements": n_el, "mesh_size_mm": round(h, 3), "seconds": round(time.time() - t0, 1),
             "vm_max_mpa": round(float(allvm[ie]), 3), "vm_max_at": [round(float(x), 3) for x in allp[ie]],
             "vm_max_faces": face_at(int(allid[ie])),
             "vm_peak_all_mpa": round(float(allvm[ia]), 3), "vm_peak_all_at": [round(float(x), 3) for x in allp[ia]],
             "u_max_mm": round(float(umag.max()), 6), "u_max_at": [round(float(x), 3) for x in pos[jmax]],
             "applied_force_n": [round(float(x), 3) for x in sum(forces.values(), np.zeros(3))]}
    if len(Bs) > 1:
        stats["vm_max_body"] = Bs[int(node_body[ie])]["id"]
    if nonlin:
        frac = history[-1]["load_fraction"] if history else 1.0
        if partial:
            frac = min(frac, 0.999999)
        stats["nonlinear"] = {"large_deformation": nlgeom, "plasticity": plastic, "completed": not partial,
                              "load_fraction_reached": round(frac, 6), "increments": len(history),
                              "history": _history(history, sup_sets, sup_dofs_all, _ext_total(Bs))}
        if partial:                                                 # 外载按已加到的比例核对平衡
            forces = {n: f * frac for n, f in forces.items()}
            body_f = {n: f * frac for n, f in body_f.items()}
    if plastic:
        pe = {n: v for n, v in peeq.items() if n in P}
        if pe:
            n_pe = max(pe, key=pe.get)
            stats["peeq_max"] = round(float(pe[n_pe]), 6)
            stats["peeq_max_at"] = [round(float(x), 3) for x in P[n_pe]]
        else:
            stats["peeq_max"] = 0.0
    stats["mesh_quality"] = _merge_quality([B["qual"] for B in Bs])
    spring_r = {int(n): [-k * x for x in disp.get(int(n), [0, 0, 0])[:3]] for n, k in springs}
    ext = dict(forces)                                     # 全部外载的节点力：面上的 + 体力的
    for n, f in body_f.items():
        ext[n] = ext.get(n, 0) + f
    # 接触力作用在两面的同一个空间点上；按原位置算力矩时，它落在相距“两侧相对位移”的两个材料点上，多出
    # Σ 相对位移 × 接触力 的力偶（摩擦滑动 0.2 mm 时约占 0.5 %；过盈配合两环轴向伸缩不同也有）。这一项估出上界，从力矩误差里扣除
    slip_m = sum(_contact_couple(c, Bs, P, disp, blocks.get("CONTACT") or {}) for c in conns if c["type"] == "contact")
    # 大变形：平衡在变形后的位置上成立，力矩按变形后的位置算（节点力的方向 CalculiX 已按整体坐标给出，载荷方向不随转动）
    Pb = {n: np.asarray(p) + np.asarray(disp.get(n, [0, 0, 0])[:3]) for n, p in P.items()} if nlgeom else P
    stats["balance"] = _balance(ext, _constrained_rf(sup_dofs, forc, ext), Pb, springs=spring_r, slip_moment=slip_m)
    if body_f:
        stats["body_force_n"] = [round(float(x), 6) for x in sum(body_f.values(), np.zeros(3))]
    stats["probes"] = _probes(setup.get("probes") or [], P, disp, stress)
    stats["support_reactions"] = _support_reactions(sup_dofs, forc, ext, spring_r, P)
    stats["vm_max_node"] = int(allid[ie])
    stats["vm_max_local_h_mm"] = _local_h(tets_all, P, int(allid[ie]), h)
    if setup.get("track_point_mm") is not None:              # 收敛核查：加密球内（各层同一区域）的最大应力
        q = np.asarray(setup["track_point_mm"], float)
        near = ok & (np.linalg.norm(allp - q, axis=1) <= float(setup["track_radius_mm"]))
        cand = np.nonzero(near if near.any() else ok)[0]
        it = int(cand[np.argmax(allvm[cand])])
        stats["vm_at_track_mpa"] = round(float(allvm[it]), 3)
        stats["track_local_h_mm"] = _local_h(tets_all, P, int(allid[it]), h)
    if len(Bs) == 1:
        materials.safety(stats, Bs[0]["mat"], optional=bool(setup.get("strength_optional")))
    else:                                                  # 每个实体按自己的材料；总的安全系数取最小
        per = []
        for k, B in enumerate(Bs):
            sel = ok & (node_body == k)
            if not sel.any():
                sel = node_body == k
            j = int(np.argmax(np.where(sel, allvm, -1)))
            st = {"vm_max_mpa": round(float(allvm[j]), 3)}
            materials.safety(st, B["mat"], optional=bool(setup.get("strength_optional")))
            per.append({"id": B["id"], "vm_max_mpa": st["vm_max_mpa"], "vm_max_at": [round(float(x), 3) for x in allp[j]],
                        **{k2: st[k2] for k2 in ("strength_mpa", "strength_kind", "safety_factor") if k2 in st}})
        stats["bodies"] = per
        sfs = [x["safety_factor"] for x in per if "safety_factor" in x]
        if sfs:
            worst = min(per, key=lambda x: x.get("safety_factor", math.inf))
            stats.update(strength_mpa=worst["strength_mpa"], strength_kind=worst["strength_kind"], safety_factor=min(sfs),
                         safety_body=worst["id"])
    if bolts:
        stats["bolts"] = []
        for bl in bolts:
            sof = bolt_sof.get(f"BS{bl['k']}") or []
            final = float(np.dot(sof[-1], bl["dir"])) if sof else None          # 正为拉
            stats["bolts"].append({"id": bl["id"], "preload_n": bl["force"], "section_area_mm2": round(bl["area"], 3),
                                   "force_n": round(final, 3) if final is not None else None})
    cont = blocks.get("CONTACT") or {}
    if conns and any(c["type"] == "contact" for c in conns):
        press = [v[3] for v in cont.values() if len(v) > 3]
        stats["contact"] = {"max_pressure_mpa": round(float(max(press)), 4) if press else 0.0,
                            "nodes_in_contact": int(sum(1 for x in press if x > 1e-9))}
    surface = {"positions": np.round(pos, 4), "triangles": tri_idx.astype(np.int32),
               "face_of_triangle": face_of.astype(np.int32), "vm": np.round(VM, 4), "u": np.round(U, 7)}
    if len(Bs) > 1:
        surface["body_of_triangle"] = body_of.astype(np.int32)
    return stats, surface, {"vm": vm_all, "nodes": P}


def _contact_couple(c, Bs, P, disp, cst):
    """接触对的力偶上界（N·mm）：每个从面节点的接触力（CPRESS、CSHEAR × 节点面积）× 它与最近主面节点的相对位移——
    法向力乘相对位移的切向分量，剪力乘整个相对位移"""
    from scipy.spatial import cKDTree
    ta = np.concatenate([Bs[c["a_body"]]["conn"][f] for f in c["a_faces"]])
    tb = np.concatenate([Bs[c["b_body"]]["conn"][f] for f in c["b_faces"]])
    mnodes = np.unique(tb.ravel())
    tree = cKDTree(np.array([P[int(n)] for n in mnodes]))
    nrm = {}
    for t in ta:
        nv = np.cross(P[int(t[1])] - P[int(t[0])], P[int(t[2])] - P[int(t[0])])
        for n in t:
            nrm[int(n)] = nrm.get(int(n), 0) + nv
    out = 0.0
    for n, A in nodal_areas(ta, P).items():
        v = cst.get(int(n))
        if not v or len(v) < 6 or A <= 0:
            continue
        _d, j = tree.query(P[int(n)])
        du = np.asarray(disp.get(int(mnodes[j]), [0, 0, 0])[:3], float) - np.asarray(disp.get(int(n), [0, 0, 0])[:3], float)
        nn = nrm[int(n)] / (np.linalg.norm(nrm[int(n)]) or 1.0)
        dn = float(np.dot(du, nn))
        dt = float(np.linalg.norm(du - dn * nn))
        out += A * (abs(v[3]) * dt + math.hypot(v[4], v[5]) * float(np.linalg.norm(du)))
    return out


def _merge_quality(qs):
    if len(qs) == 1:
        return qs[0]
    n = sum(q["elements"] for q in qs)
    return {"elements": n, "straight_sided": any(q["straight_sided"] for q in qs), "min_sj_min": min(q["min_sj_min"] for q in qs),
            "inverted": sum(q["inverted"] for q in qs), "gamma_min": min(q["gamma_min"] for q in qs),
            "gamma_p01": min(q["gamma_p01"] for q in qs), "gamma_below_0_1": sum(q["gamma_below_0_1"] for q in qs)}


def _constrained_rf(sup_dofs, forc, ext):
    """只留被约束的方向上的节点力（其余方向换成该节点上的外载，减去后为 0）。绑定的从面节点同时在对称面上时，
    没被约束的方向上有约束方程传来的力，不是支承反力"""
    dofs = {}
    for l, nodes, ds in sup_dofs:
        if l["type"] == "elastic_support":
            continue
        for n in nodes:
            dofs.setdefault(n, set()).update(ds)
    out = {}
    for n, ds in dofs.items():
        if n not in forc:
            continue
        f = np.asarray(ext.get(n, np.zeros(3)), float)
        out[n] = [forc[n][i] if i + 1 in ds else f[i] for i in range(3)]
    return out


def _balance(forces, reactions, P, springs=None, slip_moment=0.0):
    """反力与外载的平衡（ADR-0093 F1）：ΣF + ΣR = 0、Σr×F + Σr×R = 0（对坐标原点）。外载含面上的节点力和体力（重力、离心）的合力、
    合力矩；反力含支承反力和弹性支承的弹簧力。相对误差以外载合力（或各力的模之和）和外载力矩量级为分母。判定在 analysis/fea/trust.py。
    slip_moment：接触滑移造成的力偶上界（N·mm），从力矩误差里扣除（ADR-0093 F3）"""
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
            "moment_error_ratio": float(max(np.linalg.norm(M + MR) - slip_moment, 0.0) / scale_m),
            **({"contact_slip_moment_nmm": round(float(slip_moment), 3),
                "moment_error_raw_ratio": float(np.linalg.norm(M + MR) / scale_m)} if slip_moment else {})}


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

