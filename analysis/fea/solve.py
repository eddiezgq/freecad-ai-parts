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


def mesh(gmsh, size_mm, fine_faces=(), max_elements=MAX_ELEMENTS):
    bb = gmsh.model.getBoundingBox(-1, -1)
    diag = math.dist(bb[:3], bb[3:])
    h = size_mm or diag / 30
    gmsh.option.setNumber("Mesh.MeshSizeMax", h)
    gmsh.option.setNumber("Mesh.MeshSizeMin", h / 8)
    gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 16)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.HighOrderOptimize", 1)
    gmsh.option.setNumber("Mesh.Algorithm3D", 10)        # HXT，快
    gmsh.option.setNumber("Mesh.MaxNumThreads3D", int(os.environ.get("FAP_MESH_THREADS", "1")))  # 1：网格每次相同，数字可复现
    if fine_faces:                                        # 载荷、圆角处加密
        f = gmsh.model.mesh.field
        d = f.add("Distance")
        f.setNumbers(d, "SurfacesList", list(fine_faces))
        t = f.add("Threshold")
        f.setNumber(t, "InField", d)
        f.setNumber(t, "SizeMin", h / 3)
        f.setNumber(t, "SizeMax", h)
        f.setNumber(t, "DistMin", h / 2)
        f.setNumber(t, "DistMax", 3 * h)
        f.setAsBackgroundMesh(t)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
    gmsh.model.mesh.generate(3)
    etypes, _etags, enodes = gmsh.model.mesh.getElements(3)
    if 11 not in list(etypes):
        raise ValueError("网格没有生成二阶四面体")
    k = list(etypes).index(11)
    tets = np.asarray(enodes[k], np.int64).reshape(-1, 10)
    if len(tets) > max_elements:
        raise TooBig(f"网格 {len(tets)} 个单元，超过上限 {max_elements}：请把网格尺寸调大")
    ntags, xyz, _ = gmsh.model.mesh.getNodes()
    return np.asarray(ntags, np.int64), np.asarray(xyz, float).reshape(-1, 3), tets


def face_tris(gmsh, tag):
    """某个面上的二阶三角形（6 节点：3 角点 + 3 边中点）"""
    et, _, en = gmsh.model.mesh.getElements(2, tag)
    for t, n in zip(et, en):
        if t == 9:                                        # 6 节点三角形
            return np.asarray(n, np.int64).reshape(-1, 6)
    return np.zeros((0, 6), np.int64)


def consistent_loads(tris, P, traction_fn):
    """面上分布力 → 节点力。二阶三角形均布面力：角点 0、边中点各 1/3（一致载荷）。traction_fn(中心, 法向) → 每单位面积的力"""
    out = {}
    for tri in tris:
        a, b, c = P[tri[0]], P[tri[1]], P[tri[2]]
        n = np.cross(b - a, c - a)
        area = np.linalg.norm(n) / 2
        if area <= 0:
            continue
        n = n / (2 * area)
        t = traction_fn((a + b + c) / 3, n)
        f = t * area / 3
        for m in tri[3:]:
            out[m] = out.get(m, 0) + f
    return out


def _nset(w, name, nodes):
    w.write(f"*NSET, NSET={name}\n")
    ns = sorted(nodes)
    for i in range(0, len(ns), 12):
        w.write(",".join(str(int(n)) for n in ns[i:i + 12]) + "\n")


def write_inp(path, ntags, xyz, tets, fixed_nodes, cyl_supports, nodal_forces, mat):
    """cyl_supports: [(节点集合, 轴心, 轴向, [限制的局部自由度 1 径向 2 切向 3 轴向])]"""
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
        w.write("*MATERIAL, NAME=M\n*ELASTIC\n{:.9g},{:.9g}\n*DENSITY\n{:.9g}\n".format(
            mat["elastic_modulus_mpa"], mat["poisson_ratio"], mat["density_kg_m3"] * 1e-12))  # kg/m³ → t/mm³
        w.write("*SOLID SECTION, ELSET=EALL, MATERIAL=M\n")
        w.write(f"*STEP\n*STATIC, SOLVER={SOLVER}\n*BOUNDARY\n")
        if fixed_nodes:
            w.write("FIX,1,3,0\n")
        for k, (_, _, _, dofs) in enumerate(cyl_supports, 1):
            w.writelines(f"CYL{k},{dof},{dof},0\n" for dof in dofs)
        if nodal_forces:
            w.write("*CLOAD\n")
            for n, f in nodal_forces.items():
                for d in range(3):
                    if abs(f[d]) > 0:
                        w.write(f"{int(n)},{d + 1},{f[d]:.9g}\n")
        w.write("*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")


def read_frd(path):
    """CalculiX .frd（文本）里的节点位移 DISP 和节点应力 STRESS"""
    disp, stress, block = {}, {}, None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith(" -4"):
                name = line.split()[1]
                block = {"DISP": disp, "STRESS": stress}.get(name)
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
    return disp, stress


def von_mises(s):
    sxx, syy, szz, sxy, syz, szx = s[:6]
    return math.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))


SOLVER = os.environ.get("FAP_CCX_SOLVER", "SPOOLES")
SUPPORT_DOFS = {"radial": 1, "tangential": 2, "axial": 3}
SUPPORTS = ("fixed", "cyl_support")


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
    if not any(l["type"] not in SUPPORTS for l in loads):
        raise ValueError("还没有加载荷")
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_path, tmp)
        all_faces = [t for _, t in gmsh.model.getEntities(2)]
        used = sorted({f for l in loads for f in l["faces"]})
        bad = [f for f in used if f not in all_faces]
        if bad:
            raise ValueError(f"没有这些面：{bad}")
        size = (setup.get("mesh") or {}).get("size_mm")
        ntags, xyz, tets = mesh(gmsh, size, [f for l in loads if l["type"] not in SUPPORTS for f in l["faces"]],
                                setup.get("max_elements", MAX_ELEMENTS))
        h = float(gmsh.option.getNumber("Mesh.MeshSizeMax"))
        P = {int(t): p for t, p in zip(ntags, xyz)}
        fixed, cyl, forces, constrained = set(), [], {}, set()

        def add(d):
            for n, f in d.items():
                forces[n] = forces.get(n, 0) + f
        for l in loads:
            tris = np.concatenate([face_tris(gmsh, f) for f in l["faces"]]) if l["faces"] else np.zeros((0, 6), np.int64)
            nodes = {int(n) for n in tris.ravel()}
            if l["type"] == "fixed":
                fixed |= nodes
                constrained |= nodes
                continue
            if l["type"] == "cyl_support":
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
                constrained |= nodes
                continue
            area = sum(np.linalg.norm(np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])) / 2 for t in tris)
            if l["type"] == "force":
                v = np.array(l["vector_n"], float)
                add(consistent_loads(tris, P, lambda c, n, v=v, A=area: v / A))
            elif l["type"] == "pressure":
                p = float(l["value_mpa"])
                add(consistent_loads(tris, P, lambda c, n, p=p: -p * n))
            elif l["type"] == "torque":
                o, d = _axis(l)
                # 切向面力 τ = T·r / J，J = ∫ r² dA：合力矩正好是 T（右手定则绕轴）
                J = 0.0
                for t in tris:
                    c = (P[t[0]] + P[t[1]] + P[t[2]]) / 3
                    r = (c - o) - d * np.dot(c - o, d)
                    J += np.dot(r, r) * np.linalg.norm(np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])) / 2
                T = float(l["value_nmm"])
                add(consistent_loads(tris, P, lambda c, n, o=o, d=d, T=T, J=J: T / J * np.cross(d, (c - o) - d * np.dot(c - o, d))))
            else:
                raise ValueError("不认识的载荷类型 {}".format(l["type"]))
        # 一个节点只能有一个局部坐标系：固定的优先，再按先后
        seen = set(fixed)
        for k, (nodes, o, d, dofs) in enumerate(cyl):
            nodes -= seen
            seen |= nodes
        cyl = [c for c in cyl if c[0]]
        surf = np.concatenate([face_tris(gmsh, f) for f in all_faces])
        face_of = np.concatenate([np.full(len(face_tris(gmsh, f)), f) for f in all_faces])
        n_el, n_nodes = len(tets), len(ntags)
        write_inp(os.path.join(tmp, "job.inp"), ntags, xyz, tets, fixed, cyl, forces, mat)
        r = _ccx(ccx, tmp, setup.get("time_limit_s", TIME_LIMIT_S))
        frd = os.path.join(tmp, "job.frd")
        if r.returncode < 0:
            raise TooBig("计算被系统中止（多半是内存不够）：请把网格尺寸调大")
        if r.returncode != 0 or not os.path.exists(frd) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]))
        disp, stress = read_frd(frd)
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
        ok = dist > 1.5 * h
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
    strength, kind = materials.strength_mpa(mat)
    stats["strength_mpa"], stats["strength_kind"] = strength, kind
    stats["safety_factor"] = round(strength / max(stats["vm_max_mpa"], 1e-9), 3)
    surface = {"positions": np.round(pos, 4), "triangles": tri_idx.astype(np.int32),
               "face_of_triangle": face_of.astype(np.int32), "vm": np.round(VM, 4), "u": np.round(U, 7)}
    return stats, surface, {"vm": vm_all, "nodes": P}
