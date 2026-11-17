"""实体零件 → 柔性构件的模态数据（ADR-0097 D6b，补充十五）：gmsh 二阶四面体 + CalculiX 整体矩阵 + Craig-Bampton。

本机跑 gmsh 与 CalculiX（子进程），不联网、不调用 LLM。输出 schema 里 `flex`（`modal`）的字典，单位按 schema（mm、kg、Hz、MPa）。
"""

from __future__ import annotations

import os
import re
import tempfile

import numpy as np
import scipy.linalg as sla
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from analysis.mbd.dae.flex import RIGID_TOL, FlexError

MM = 1e-3


def _write_inp(path, ntags, xyz, tets, mat, steps):
    from analysis.fea.solve import GMSH2CCX_TET10

    with open(path, "w") as w:
        w.write("*HEADING\nWenQuest MBD flex\n*NODE, NSET=NALL\n")
        w.writelines("{},{:.12g},{:.12g},{:.12g}\n".format(t, *p) for t, p in zip(ntags, xyz, strict=True))
        w.write("*ELEMENT, TYPE=C3D10, ELSET=EALL\n")
        w.writelines("{},{}\n".format(i, ",".join(str(int(e[j])) for j in GMSH2CCX_TET10)) for i, e in enumerate(tets, 1))
        w.write("*MATERIAL, NAME=M\n*ELASTIC\n{:.9g},{:.9g}\n*DENSITY\n{:.9g}\n".format(
            mat["elastic_modulus_mpa"], mat["poisson_ratio"], mat["density_kg_m3"] * 1e-12))
        w.write("*SOLID SECTION, ELSET=EALL, MATERIAL=M\n")
        w.write(steps)


def _run(ccx, tmp, limit=1800):
    from analysis.fea.solve import _ccx

    r = _ccx(ccx, tmp, limit)
    if r.returncode != 0 or "*ERROR" in r.stdout:
        err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x]
        raise FlexError("CalculiX 失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-300:]))


def _read_sym(path, n):
    d = np.loadtxt(path, ndmin=2)
    i, j, v = d[:, 0].astype(int) - 1, d[:, 1].astype(int) - 1, d[:, 2]
    A = sp.coo_matrix((v, (i, j)), shape=(n, n)).tocsr()
    return A + sp.triu(A, 1).T


def _read_stress_steps(frd, nsteps):
    """多步静力的 .frd：每一步的节点应力 {节点: [6]}"""
    out, cur = [], None
    with open(frd, errors="replace") as f:
        for line in f:
            if line.startswith(" -4"):
                cur = {} if line.split()[1] == "STRESS" else None
                if cur is not None:
                    out.append(cur)
                continue
            if cur is None:
                continue
            if line.startswith(" -3"):
                cur = None
                continue
            if line.startswith(" -1"):
                cur[int(line[3:13])] = [float(line[13 + 12 * k:25 + 12 * k]) for k in range(6)]
    if len(out) != nsteps:
        raise FlexError(f"应力振型：CalculiX 输出了 {len(out)} 步，应为 {nsteps}")
    return out


def reduce_step(step_path, material, interfaces, *, size_mm=None, fixed_interface_modes=8, keep_modes=None,
                damping_ratio=0.0, stress=True, ccx=None, workdir=None):
    """material：{elastic_modulus_mpa, poisson_ratio, density_kg_m3}；interfaces：[{"name", "center_mm", "radius_mm", "normal"?}]——
    中心半径球内的表面节点（给了 normal 就只取过中心、垂直 normal 的那个平面上的）刚性跟随中心的参考节点
    （参考节点就是界面节点，运动副挂在它上面）。孔用球（取孔壁），端面用平面。返回 (flex 字典, 信息)"""
    from analysis.common.solvers import find_ccx
    from analysis.fea import solve as S
    from analysis.fea.geometry import _LOCK, _gmsh, load_step

    ccx = ccx or find_ccx()
    if ccx is None:
        raise FlexError("没有找到 CalculiX（ccx）")
    if not interfaces:
        raise FlexError("至少要一个界面（运动副挂的地方）")
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_path, tmp)
        ntags, xyz, tets = S.mesh(gmsh, size_mm)
        surf = np.concatenate([S.face_tris(gmsh, f) for _, f in gmsh.model.getEntities(2)])
        _write_inp(os.path.join(tmp, "job.inp"), ntags, xyz, tets, material,
                   "*STEP\n*FREQUENCY, SOLVER=MATRIXSTORAGE\n1\n*END STEP\n")
        _run(ccx, tmp)
        with open(os.path.join(tmp, "job.dof")) as fdof:
            dofs = [x.strip() for x in fdof if x.strip()]
        n = len(dofs)
        K = _read_sym(os.path.join(tmp, "job.sti"), n) * 1e3            # N/mm → N/m
        Mc = _read_sym(os.path.join(tmp, "job.mas"), n) * 1e3           # t → kg
        pos = {int(t): k for k, t in enumerate(ntags)}
        N = len(ntags)
        perm = np.zeros(n, int)                                           # .dof 顺序 → 节点下标 × 3 + 方向
        for k, d in enumerate(dofs):
            a, b = d.split(".")
            perm[k] = 3 * pos[int(a)] + int(b) - 1
        P = sp.coo_matrix((np.ones(n), (perm, np.arange(n))), shape=(3 * N, n)).tocsr()
        K = (P @ K @ P.T).tocsr()
        Mc = (P @ Mc @ P.T).tocsr()
        # HRZ 对角集中质量：每个方向按对角元比例分总质量
        diag = Mc.diagonal().reshape(N, 3)
        tot = np.array([Mc[d::3, :][:, d::3].sum() for d in range(3)])
        m = diag[:, 0] * tot[0] / diag[:, 0].sum()
        X = xyz * MM
        # 界面：刚性蜘蛛
        snodes = np.unique(surf.ravel())
        sidx = np.array([pos[int(t)] for t in snodes])
        slaves, refs = {}, []
        for itf in interfaces:
            c = np.asarray(itf["center_mm"], float) * MM
            r = float(itf["radius_mm"]) * MM
            sel = sidx[np.linalg.norm(X[sidx] - c, axis=1) <= r]
            if "normal" in itf:                       # 平面界面（端面）：只取这个平面上的节点，不带进侧面
                nrm = np.asarray(itf["normal"], float)
                nrm = nrm / np.linalg.norm(nrm)
                sel = sel[np.abs((X[sel] - c) @ nrm) <= 1e-6 * max(r, MM)]
            sel = [s for s in sel if s not in slaves]
            if len(sel) < 3:
                raise FlexError(f"界面 {itf.get('name', '')}：球内只有 {len(sel)} 个表面节点，请加大 radius_mm 或网格加密")
            for s in sel:
                slaves[s] = len(refs)
            refs.append(c)
        R = len(refs)
        free = [k for k in range(N) if k not in slaves]
        col = {k: 3 * i for i, k in enumerate(free)}
        nr = 3 * len(free) + 6 * R
        rows, cols, vals = [], [], []
        for k in free:
            for d in range(3):
                rows.append(3 * k + d), cols.append(col[k] + d), vals.append(1.0)
        for s, ri in slaves.items():
            o = 3 * len(free) + 6 * ri
            v = X[s] - refs[ri]
            Sk = np.array([[0, v[2], -v[1]], [-v[2], 0, v[0]], [v[1], -v[0], 0]])      # u = u_ref − ṽ θ = u_ref + θ × v
            for d in range(3):
                rows.append(3 * s + d), cols.append(o + d), vals.append(1.0)
                for e in range(3):
                    if Sk[d, e]:
                        rows.append(3 * s + d), cols.append(o + 3 + e), vals.append(Sk[d, e])
        T = sp.coo_matrix((vals, (rows, cols)), shape=(3 * N, nr)).tocsr()
        Md = sp.diags(np.repeat(m, 3))
        Kr = (T.T @ K @ T).tocsc()
        Mr = (T.T @ Md @ T).tocsc()
        b = np.arange(3 * len(free), nr)
        i = np.arange(3 * len(free))
        Kii, Kib = Kr[i][:, i].tocsc(), Kr[i][:, b]
        lu = spla.splu(Kii)
        Psi = -lu.solve(Kib.toarray())
        nfim = min(fixed_interface_modes, len(i) - 2)
        cols_ = [np.vstack([Psi, np.eye(len(b))])]
        if nfim > 0:
            Mii = Mr[i][:, i].tocsc()
            lam, V = spla.eigsh(Kii, k=nfim, M=Mii, sigma=0, which="LM")
            cols_.append(np.vstack([V, np.zeros((len(b), nfim))]))
        Tcb_ib = np.hstack(cols_)                                         # 行：先内部、后边界
        order = np.concatenate([i, b])
        Tcb = np.zeros((nr, Tcb_ib.shape[1]))
        Tcb[order] = Tcb_ib
        Kc = Tcb.T @ (Kr @ Tcb)
        Mcb = Tcb.T @ (Mr @ Tcb)
        lam, V = sla.eigh((Kc + Kc.T) / 2, (Mcb + Mcb.T) / 2)
        rigid = lam < RIGID_TOL * abs(lam).max()
        if int(rigid.sum()) != 6:
            raise FlexError(f"缩减后刚体模态是 {int(rigid.sum())} 个（应为 6）")
        lam, V = lam[~rigid], V[:, ~rigid]
        if keep_modes:
            lam, V = lam[:keep_modes], V[:, :keep_modes]
        red = Tcb @ V                                                     # 缩减坐标下的振型（质量归一）
        full = T @ red                                                    # 实体节点平动（m）
        nm = red.shape[1]
        shapes = np.zeros((nm, N + R, 6))
        shapes[:, :N, :3] = full.T.reshape(nm, N, 3) / MM                 # → mm
        for ri in range(R):
            o = 3 * len(free) + 6 * ri
            shapes[:, N + ri, :3] = red[o:o + 3].T / MM
            shapes[:, N + ri, 3:] = red[o + 3:o + 6].T
        freqs = np.sqrt(lam) / (2 * np.pi)
        out = {"type": "modal", "nodes_mm": np.vstack([xyz, np.array(refs) / MM]).tolist(),
               "node_mass_kg": np.concatenate([m, np.zeros(R)]).tolist(), "shapes": shapes.tolist(),
               "frequencies_hz": freqs.tolist(), "interface_nodes": list(range(N, N + R)),
               "damping_ratio": damping_ratio,
               "source": f"CalculiX {_ccx_version(ccx)} 二阶四面体 {len(tets)} 个单元、{N} 个节点，Craig-Bampton（固定界面模态 {nfim} 阶）"
                         "正交化后去刚体模态（ADR-0097 D6b）"}
        surf_ix = np.searchsorted(ntags, surf[:, :3]) if np.all(np.diff(ntags) > 0) else \
            np.vectorize(pos.get)(surf[:, :3])
        out["surface_triangles"] = surf_ix.astype(int).tolist()
        if stress:
            used = np.unique(surf_ix[:, :3].ravel())
            steps = []
            for k in range(nm):
                u = shapes[k, :N, :3]
                lines = "".join(f"{int(ntags[j])},{d + 1},{d + 1},{u[j, d]:.12g}\n" for j in range(N) for d in range(3))
                steps.append(f"*STEP\n*STATIC\n*BOUNDARY, OP=NEW\n{lines}*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")
            for f_ in os.listdir(tmp):
                if f_.startswith("job."):
                    os.remove(os.path.join(tmp, f_))
            _write_inp(os.path.join(tmp, "job.inp"), ntags, xyz, tets, material, "".join(steps))
            _run(ccx, tmp)
            st = _read_stress_steps(os.path.join(tmp, "job.frd"), nm)
            out["stress_nodes"] = used.tolist()
            out["stress_shapes_mpa"] = [[st[k][int(ntags[j])] for j in used] for k in range(nm)]
    info = {"nodes": N, "elements": len(tets), "modes": nm, "interface_slaves": {itf.get("name", str(k)): sum(
        1 for v in slaves.values() if v == k) for k, itf in enumerate(interfaces)}}
    return out, info


def _ccx_version(ccx):
    import subprocess

    try:
        r = subprocess.run([ccx, "-v"], capture_output=True, text=True, timeout=10, check=False)
        m_ = re.search(r"Version\s+([\d.]+)", r.stdout + r.stderr)
        return m_.group(1) if m_ else ""
    except Exception:  # noqa: BLE001 — 版本号只是记录
        return ""


def von_mises(s):
    """s: (..., 6) [sxx, syy, szz, sxy, syz, szx]"""
    s = np.asarray(s, float)
    a, b, c, d, e, f = (s[..., k] for k in range(6))
    return np.sqrt(0.5 * ((a - b) ** 2 + (b - c) ** 2 + (c - a) ** 2) + 3 * (d * d + e * e + f * f))
