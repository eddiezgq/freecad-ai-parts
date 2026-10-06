# -*- coding: utf-8 -*-
"""热分析（第 14 轮 H1）：Gmsh 二阶四面体 → CalculiX 稳态 / 瞬态温度场，或热—结构耦合（温度 + 热应力、热变形）。

单位制（与第 11 轮一致：mm、N、t、s）：能量 mJ、功率 mW、温度 ℃。
  导热系数 W/(m·K) = mW/(mm·K)（数值不变）；比热 J/(kg·K) × 10⁶ → mJ/(t·K)；
  换热系数 W/(m²·K) × 10⁻³ → mW/(mm²·K)；功率 W × 10³ → mW。

setup = {
  "analysis": "thermal" | "thermo_mech",
  "material": materials.get(...),
  "thermal": [
    {"type": "temperature", "faces": [..], "value_c": 80},                         # 固定温度
    {"type": "convection",  "faces": [..] 或 "rest", "h_w_m2k": 17.45, "t_inf_c": 20},   # 对流换热（rest = 其余所有面）
    {"type": "heat_flux",   "faces": [..], "power_w": 300},                         # 面上总发热功率，均匀分布
    {"type": "heat_body",   "power_w": 50},                                         # 整个零件体积均匀发热
  ],
  "transient": None 或 {"duration_s": 600, "steps": 60, "t0_c": 20},
  "loads": [...]（热—结构耦合时的支承和机械载荷，同第 11 轮）,
  "ref_temp_c": 20（无应力的参考温度，热—结构耦合用）,
  "mesh": {...}
}"""
import os
import re
import subprocess
import tempfile
import time

import numpy as np

from cae.geometry import _LOCK, _gmsh, load_step
from cae.solve import (GMSH2CCX_TET10, SOLVER, SUPPORT_DOFS, SUPPORTS, TIME_LIMIT_S, CCX, TooBig, _axis, _nset,
                       consistent_loads, face_tris, mesh, von_mises)

# C3D10 的面（按角点，CalculiX 编号）：F1 1-2-3，F2 1-4-2，F3 2-4-3，F4 3-4-1
TET_FACES = [(0, 1, 2), (0, 3, 1), (1, 3, 2), (2, 3, 0)]


def _face_index(tets):
    """角点三元组（排序后）→ (单元号, 面号)"""
    idx = {}
    for e, t in enumerate(tets, 1):
        for k, (a, b, c) in enumerate(TET_FACES, 1):
            idx[tuple(sorted((int(t[a]), int(t[b]), int(t[c]))))] = (e, k)
    return idx


def _tri_area(P, t):
    return float(np.linalg.norm(np.cross(P[t[1]] - P[t[0]], P[t[2]] - P[t[0]])) / 2)


def read_frd_all(path):
    """所有结果块：[(时间, 名称, {节点: 值列表})]"""
    out, cur, name, tval = [], None, None, 0.0
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("  100C"):
                try:
                    tval = float(line[12:24])
                except ValueError:
                    pass
                continue
            if line.startswith(" -4"):
                name = line.split()[1]
                cur = {}
                out.append((tval, name, cur))
                continue
            if cur is None:
                continue
            if line.startswith(" -3"):
                cur = None
                continue
            if line.startswith(" -1"):
                nid = int(line[3:13])
                cur[nid] = [float(line[13 + 12 * i:25 + 12 * i]) for i in range((len(line.rstrip()) - 13) // 12)]
    return out


def solve(step_bytes, setup, workdir=None):
    t0 = time.time()
    mat = setup["material"]
    kind = setup.get("analysis", "thermal")
    th = setup.get("thermal") or []
    tr = setup.get("transient")
    mech = setup.get("loads") or [] if kind == "thermo_mech" else []
    if not any(l["type"] in ("temperature", "convection") for l in th):
        raise ValueError("至少要有一个固定温度或对流换热的面，否则热量散不出去、温度算不出来")
    if kind == "thermo_mech" and not any(l["type"] in SUPPORTS for l in mech):
        raise ValueError("热—结构耦合至少要有一个固定或支承面")
    k = float(mat["k_w_mk"])
    c = float(mat["c_j_kgk"]) * 1e6
    rho = float(mat.get("density_t_mm3", mat.get("density", 7.85) * 1e-9))
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_bytes, tmp)
        all_faces = [t for _, t in gmsh.model.getEntities(2)]
        named = {f for l in th + mech if isinstance(l.get("faces"), list) for f in l["faces"]}
        bad = sorted(f for f in named if f not in all_faces)
        if bad:
            raise ValueError("没有这些面：{}".format(bad))
        size = (setup.get("mesh") or {}).get("size_mm")
        ntags, xyz, tets = mesh(gmsh, size, [])           # 温度场平滑，发热面不用加密
        h_mesh = float(gmsh.option.getNumber("Mesh.MeshSizeMax"))
        P = {int(t): p for t, p in zip(ntags, xyz)}
        tris_of = {f: face_tris(gmsh, f) for f in all_faces}
        fidx = _face_index(tets)
        vol = 0.0
        for t in tets:
            a, b, cc, d = (P[int(t[i])] for i in range(4))
            vol += abs(np.dot(b - a, np.cross(cc - a, d - a))) / 6
        # “其余面”
        used = {f for l in th if isinstance(l.get("faces"), list) for f in l["faces"]}
        rest = [f for f in all_faces if f not in used]
        films, dflux, fixed_t = [], [], {}
        film_groups, power_in = [], 0.0
        for gi, l in enumerate(th):
            faces = rest if l.get("faces") == "rest" else (l.get("faces") or [])
            tris = np.concatenate([tris_of[f] for f in faces]) if faces else np.zeros((0, 6), np.int64)
            if l["type"] == "temperature":
                for n in tris.ravel():
                    fixed_t[int(n)] = float(l["value_c"])
            elif l["type"] == "convection":
                hh = float(l["h_w_m2k"]) * 1e-3
                for t in tris:
                    films.append((fidx[tuple(sorted(map(int, t[:3])))], float(l["t_inf_c"]), hh))
                film_groups.append((gi, faces, float(l["h_w_m2k"]), float(l["t_inf_c"])))
            elif l["type"] == "heat_flux":
                A = sum(_tri_area(P, t) for t in tris)
                if A <= 0:
                    raise ValueError("发热面面积为 0")
                q = float(l["power_w"]) * 1e3 / A
                for t in tris:
                    e, fn = fidx[tuple(sorted(map(int, t[:3])))]
                    dflux.append("{},S{},{:.9g}".format(e, fn, q))
                power_in += float(l["power_w"])
            elif l["type"] == "heat_body":
                q = float(l["power_w"]) * 1e3 / vol
                dflux.append("EALL,BF,{:.9g}".format(q))
                power_in += float(l["power_w"])
            else:
                raise ValueError("不认识的热载荷 {}".format(l["type"]))
        # 机械（耦合）
        fixed, cyl, forces, constrained = set(), [], {}, set()
        for l in mech:
            tris = np.concatenate([tris_of[f] for f in l["faces"]]) if l.get("faces") else np.zeros((0, 6), np.int64)
            nodes = {int(n) for n in tris.ravel()}
            if l["type"] == "fixed":
                fixed |= nodes
                constrained |= nodes
            elif l["type"] == "cyl_support":
                o, d = _axis(l)
                cyl.append((nodes, o, d, sorted({SUPPORT_DOFS[x] for x in l.get("dofs") or ["radial"]})))
                constrained |= nodes
            elif l["type"] == "force":
                A = sum(_tri_area(P, t) for t in tris)
                v = np.array(l["vector_n"], float)
                for n, f in consistent_loads(tris, P, lambda cc, nn, v=v, A=A: v / A).items():
                    forces[n] = forces.get(n, 0) + f
            elif l["type"] == "pressure":
                p = float(l["value_mpa"])
                for n, f in consistent_loads(tris, P, lambda cc, nn, p=p: -p * nn).items():
                    forces[n] = forces.get(n, 0) + f
        seen = set(fixed)
        for nodes, o, d, dofs in cyl:
            nodes -= seen
            seen |= nodes
        cyl = [x for x in cyl if x[0]]
        ref = float(setup.get("ref_temp_c", 20.0))
        T0 = float((tr or {}).get("t0_c", ref))
        inp = os.path.join(tmp, "job.inp")
        with open(inp, "w") as w:
            w.write("*HEADING\nWenQuest thermal\n*NODE, NSET=NALL\n")
            for t, p in zip(ntags, xyz):
                w.write("{},{:.9g},{:.9g},{:.9g}\n".format(t, *p))
            w.write("*ELEMENT, TYPE=C3D10, ELSET=EALL\n")
            for i, e in enumerate(tets, 1):
                w.write("{},{}\n".format(i, ",".join(str(int(e[j])) for j in GMSH2CCX_TET10)))
            if fixed:
                _nset(w, "FIX", fixed)
            for kk, (nodes, o, d, dofs) in enumerate(cyl, 1):
                _nset(w, "CYL{}".format(kk), nodes)
                a, b = np.asarray(o, float), np.asarray(o, float) + 100 * np.asarray(d, float)
                w.write("*TRANSFORM, NSET=CYL{}, TYPE=C\n{}\n".format(kk, ",".join("{:.9g}".format(x) for x in [*a, *b])))
            w.write("*MATERIAL, NAME=M\n*CONDUCTIVITY\n{:.9g}\n*SPECIFIC HEAT\n{:.9g}\n*DENSITY\n{:.9g}\n".format(k, c, rho))
            if kind == "thermo_mech":
                w.write("*ELASTIC\n{:.9g},{:.9g}\n*EXPANSION, ZERO={:.9g}\n{:.9g}\n".format(mat["E_mpa"], mat["nu"], ref, mat["alpha_1e6"] * 1e-6))
            w.write("*SOLID SECTION, ELSET=EALL, MATERIAL=M\n")
            w.write("*INITIAL CONDITIONS, TYPE=TEMPERATURE\nNALL,{:.9g}\n".format(T0))
            w.write("*STEP{}\n".format(", INC=100000" if tr else ""))
            if kind == "thermo_mech":
                w.write("*COUPLED TEMPERATURE-DISPLACEMENT, STEADY STATE, SOLVER={}\n1.,1.\n".format(SOLVER))
            elif tr:
                # 隐式（后向欧拉）时间积分：步长取 时长/（4×输出点数），至少 200、至多 400 步，误差约 1–2%
                n_inc = min(400, max(200, 4 * int(tr.get("steps", 50))))
                dt = float(tr["duration_s"]) / n_inc
                w.write("*HEAT TRANSFER, DIRECT, SOLVER={}\n{:.9g},{:.9g}\n".format(SOLVER, dt, float(tr["duration_s"])))
            else:
                w.write("*HEAT TRANSFER, STEADY STATE, SOLVER={}\n1.,1.\n".format(SOLVER))
            if fixed_t or fixed or cyl:
                w.write("*BOUNDARY\n")
                for n, v in fixed_t.items():
                    w.write("{},11,11,{:.9g}\n".format(n, v))
                if fixed:
                    w.write("FIX,1,3,0\n")
                for kk, (_, _, _, dofs) in enumerate(cyl, 1):
                    for dof in dofs:
                        w.write("CYL{},{},{},0\n".format(kk, dof, dof))
            if films:
                w.write("*FILM\n")
                for (e, fn), tinf, hh in films:
                    w.write("{},F{},{:.9g},{:.9g}\n".format(e, fn, tinf, hh))
            if dflux:
                w.write("*DFLUX\n" + "\n".join(dflux) + "\n")
            if forces:
                w.write("*CLOAD\n")
                for n, f in forces.items():
                    for dd in range(3):
                        if abs(f[dd]) > 0:
                            w.write("{},{},{:.9g}\n".format(int(n), dd + 1, f[dd]))
            freq = max(1, n_inc // min(int(tr.get("steps", 50)), 100)) if tr else 1
            w.write("*NODE FILE{}\nNT{}\n".format(", FREQUENCY={}".format(freq) if tr else "", ",U" if kind == "thermo_mech" else ""))
            if kind == "thermo_mech":
                w.write("*EL FILE\nS\n")
            w.write("*END STEP\n")
        try:
            r = subprocess.run([CCX, "-i", "job"], cwd=tmp, capture_output=True, text=True, timeout=TIME_LIMIT_S,
                               env=dict(os.environ, OMP_NUM_THREADS=os.environ.get("WQ_CAE_THREADS", "2")))
        except subprocess.TimeoutExpired:
            raise TooBig("计算超过 {} 秒：请把网格尺寸调大".format(TIME_LIMIT_S)) from None
        frd = os.path.join(tmp, "job.frd")
        if r.returncode != 0 or not os.path.exists(frd) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]))
        blocks = read_frd_all(frd)
        surf = np.concatenate([tris_of[f] for f in all_faces])
        face_of = np.concatenate([np.full(len(tris_of[f]), f) for f in all_faces])
        n_el, n_nodes = len(tets), len(ntags)
    temps = [(t, b) for t, nm, b in blocks if nm == "NDTEMP"]
    if not temps:
        raise RuntimeError("求解结果里没有温度")
    T = {n: v[0] for n, v in temps[-1][1].items()}
    corner = surf[:, :3]
    used_nodes = np.unique(corner)
    pos = np.array([P[int(n)] for n in used_nodes])
    TS = np.array([T.get(int(n), T0) for n in used_nodes])
    tri_idx = np.searchsorted(used_nodes, corner)
    allid = np.array(sorted(T), np.int64)
    allT = np.array([T[int(n)] for n in allid])
    imax, imin = int(allT.argmax()), int(allT.argmin())

    def mean_on(faces):
        A = Tsum = 0.0
        for f in faces:
            for t in tris_of[f]:
                a = _tri_area(P, t)
                A += a
                Tsum += a * np.mean([T.get(int(n), T0) for n in t[:3]])
        return Tsum / A if A else None, A
    out_w, groups = 0.0, []
    for gi, faces, hcoef, tinf in film_groups:
        tm, A = mean_on(faces)
        q = hcoef * A * 1e-6 * (tm - tinf)
        out_w += q
        groups.append({"load": gi, "area_m2": round(A * 1e-6, 6), "mean_c": round(float(tm), 3), "heat_w": round(float(q), 3)})
    stats = {"analysis": kind, "nodes": n_nodes, "elements": n_el, "mesh_size_mm": round(h_mesh, 3),
             "seconds": round(time.time() - t0, 1), "volume_mm3": round(vol, 1),
             "t_max_c": round(float(allT[imax]), 3), "t_max_at": [round(float(x), 3) for x in P[int(allid[imax])]],
             "t_min_c": round(float(allT[imin]), 3), "t_min_at": [round(float(x), 3) for x in P[int(allid[imin])]],
             "t_surface_mean_c": round(mean_on(all_faces)[0], 3), "heat_in_w": round(power_in, 3),
             "heat_out_convection_w": round(out_w, 3), "film_groups": groups}
    if tr:
        stats["series"] = [[0.0, T0, T0]] + [[round(t, 4), round(float(max(b[n][0] for n in b)), 4),
                            round(float(np.mean([v[0] for v in b.values()])), 4)] for t, b in temps]
    surface = {"positions": pos.astype(np.float32), "triangles": tri_idx.astype(np.int32),
               "face_of_triangle": face_of.astype(np.int32), "temp": TS.astype(np.float32),
               "vm": np.zeros(len(pos), np.float32), "u": np.zeros((len(pos), 3), np.float32)}
    if kind == "thermo_mech":
        disp = {n: v for t, nm, b in blocks if nm == "DISP" for n, v in b.items()}
        stress = {n: v for t, nm, b in blocks if nm == "STRESS" for n, v in b.items()}
        vm_all = {n: von_mises(s) for n, s in stress.items()}
        U = np.array([disp.get(int(n), [0, 0, 0])[:3] for n in used_nodes])
        surface["u"] = U.astype(np.float32)
        surface["vm"] = np.array([vm_all.get(int(n), 0.0) for n in used_nodes], np.float32)
        vid = np.array(sorted(vm_all), np.int64)
        vv = np.array([vm_all[int(n)] for n in vid])
        ok = np.ones(len(vid), bool)
        if constrained:
            from scipy.spatial import cKDTree
            cp = np.array([P[n] for n in constrained])
            dist, _ = cKDTree(cp).query(np.array([P[int(n)] for n in vid]))
            ok = dist > 1.5 * h_mesh
            if not ok.any():
                ok[:] = True
        ie = int(np.argmax(np.where(ok, vv, -1)))
        umag = np.linalg.norm(U, axis=1)
        stats.update(vm_max_mpa=round(float(vv[ie]), 3), vm_max_at=[round(float(x), 3) for x in P[int(vid[ie])]],
                     vm_peak_all_mpa=round(float(vv.max()), 3), u_max_mm=round(float(umag.max()), 6),
                     u_max_at=[round(float(x), 3) for x in pos[int(umag.argmax())]])
        strength = mat.get("strength_mpa") or mat.get("yield_mpa")
        if strength:
            stats["strength_mpa"] = strength
            stats["safety_factor"] = round(strength / max(stats["vm_max_mpa"], 1e-9), 3)
    aux = {"T": T, "nodes": P}
    if kind == "thermo_mech":
        aux.update(U=disp, vm=vm_all)
    return stats, surface, aux
