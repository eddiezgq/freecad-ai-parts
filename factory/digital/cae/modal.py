# -*- coding: utf-8 -*-
"""固有频率（模态分析，第 11 轮《机械设计》F2）：同一套 Gmsh 二阶四面体网格和支承，CalculiX *FREQUENCY 求前几阶
固有频率和振型——高速轴（如平缝机上轴）校核临界转速、看会不会与激振频率重合。

只用支承（fixed、cyl_support），载荷不起作用；零件上装的齿轮、曲柄等附加质量不计（教学版，书中另用梁单元法计入）。
支承只限径向时，零件还能绕轴线转动、沿轴线移动，这些“刚体运动”的频率接近 0，结果里去掉（小于 1 Hz 的都算刚体运动）。
"""
import os
import re
import subprocess
import tempfile
import time

import numpy as np

from cae import solve as S
from cae.geometry import _LOCK, _gmsh, load_step

RIGID_HZ = 1.0


def write_inp(path, ntags, xyz, tets, fixed, cyl, mat, n_modes):
    S.write_inp(path, ntags, xyz, tets, fixed, cyl, {}, mat)
    txt = open(path).read()
    txt = re.sub(r"\*STATIC, SOLVER=[^\n]*\n", "*FREQUENCY\n{}\n".format(int(n_modes)), txt)
    txt = txt.replace("*EL FILE\nS\n", "")
    open(path, "w").write(txt)


def read_freqs(dat):
    """job.dat 里的特征值表：返回 [(阶次, Hz)]"""
    out, on = [], False
    for line in open(dat, errors="replace"):
        if "E I G E N V A L U E   O U T P U T" in line:
            on = True
            continue
        if on:
            p = line.split()
            if len(p) >= 5 and p[0].isdigit():
                out.append((int(p[0]), float(p[3])))
            elif out and not p:
                break
    return out


def read_modes(frd):
    """每一阶的节点位移 [{节点: (ux, uy, uz)}]"""
    modes, cur = [], None
    for line in open(frd, errors="replace"):
        if line.startswith(" -4"):
            if line.split()[1] == "DISP":
                cur = {}
                modes.append(cur)
            else:
                cur = None
            continue
        if cur is None:
            continue
        if line.startswith(" -3"):
            cur = None
            continue
        if line.startswith(" -1"):
            nid = int(line[3:13])
            cur[nid] = [float(line[13 + 12 * i:25 + 12 * i]) for i in range(3)]
    return modes


def solve(step_bytes, setup, workdir=None, n_modes=6):
    """返回 (统计, 表面结果)。统计里 freqs = [{mode, hz, rpm}]（去掉刚体运动）。表面结果的 u 是第一阶弹性振型（最大 1）"""
    t0 = time.time()
    mat = setup["material"]
    sup = [l for l in setup.get("loads") or [] if l["type"] in S.SUPPORTS]
    if not sup:
        raise ValueError("算固有频率也要有支承（固定面或轴承支承），否则全是刚体运动")
    with _LOCK, tempfile.TemporaryDirectory(dir=workdir) as tmp:
        gmsh = _gmsh()
        load_step(gmsh, step_bytes, tmp)
        all_faces = [t for _, t in gmsh.model.getEntities(2)]
        size = (setup.get("mesh") or {}).get("size_mm")
        ntags, xyz, tets = S.mesh(gmsh, size, [])
        P = {int(t): p for t, p in zip(ntags, xyz)}
        fixed, cyl = set(), []
        for l in sup:
            tris = np.concatenate([S.face_tris(gmsh, f) for f in l["faces"]])
            nodes = {int(n) for n in tris.ravel()}
            if l["type"] == "fixed":
                fixed |= nodes
            else:
                o, d = S._axis(l)
                nodes = S.band_nodes(nodes, P, o, d, l.get("band_mm"))
                dofs = sorted({S.SUPPORT_DOFS[k] for k in l.get("dofs") or ["radial"]})
                if l.get("band_mm") and 3 in dofs and len(dofs) > 1:          # 同 solve.py：铰支的止推只限一个节点的轴向
                    n0 = min(nodes)
                    cyl.append((nodes - {n0}, o, d, [x for x in dofs if x != 3]))
                    cyl.append(({n0}, o, d, dofs))
                else:
                    cyl.append((nodes, o, d, dofs))
        seen = set(fixed)
        for nodes, *_ in cyl:
            nodes -= seen
            seen |= nodes
        cyl = [c for c in cyl if c[0]]
        surf = np.concatenate([S.face_tris(gmsh, f) for f in all_faces])
        write_inp(os.path.join(tmp, "job.inp"), ntags, xyz, tets, fixed, cyl, mat, n_modes + 3)
        try:
            r = subprocess.run([S.CCX, "-i", "job"], cwd=tmp, capture_output=True, text=True, timeout=S.TIME_LIMIT_S,
                               env=dict(os.environ, OMP_NUM_THREADS=os.environ.get("WQ_CAE_THREADS", "2")))
        except subprocess.TimeoutExpired:
            raise S.TooBig("计算超过 {} 秒：请把网格尺寸调大".format(S.TIME_LIMIT_S)) from None
        dat, frd = os.path.join(tmp, "job.dat"), os.path.join(tmp, "job.frd")
        if r.returncode != 0 or not os.path.exists(dat) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]))
        freqs = read_freqs(dat)
        modes = read_modes(frd) if os.path.exists(frd) else []
    elastic = [(k, m, hz) for k, (m, hz) in enumerate(freqs) if hz >= RIGID_HZ][:n_modes]
    if not elastic:
        raise RuntimeError("没有求出弹性振型（支承是否太少？）")
    corner = surf[:, :3]
    used = np.unique(corner)
    pos = np.array([P[int(n)] for n in used])
    k0 = elastic[0][0]
    U = np.array([(modes[k0] if k0 < len(modes) else {}).get(int(n), [0, 0, 0]) for n in used], float)
    U /= max(np.linalg.norm(U, axis=1).max(), 1e-12)
    stats = {"analysis": "modal", "nodes": len(ntags), "elements": len(tets), "seconds": round(time.time() - t0, 1),
             "freqs": [{"mode": i + 1, "hz": round(hz, 2), "rpm": round(hz * 60, 0)} for i, (_, _, hz) in enumerate(elastic)],
             "rigid_modes": sum(1 for _, hz in freqs if hz < RIGID_HZ)}
    surface = {"positions": pos.astype(np.float32), "triangles": np.searchsorted(used, corner).astype(np.int32),
               "u": U.astype(np.float32), "vm": np.linalg.norm(U, axis=1).astype(np.float32)}
    return stats, surface
