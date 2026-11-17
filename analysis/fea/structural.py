"""壳单元与梁单元（ADR-0095）。纯计算：不联网、不调用 LLM；调用本机 CalculiX。

- 壳：STEP 是中面；gmsh 划二阶三角形 → CalculiX S6，`*SHELL SECTION` 给厚度。
- 梁：STEP 是轴线；gmsh 划二阶线段 → CalculiX B32R（减缩积分；管截面只认它），`*BEAM SECTION`（RECT / CIRC / PIPE）。
- 支承：固定 = 夹紧（1–6 自由度）；强制位移只约束写出的平动分量。作用在边（壳）、顶点（梁）上，也可在面上。
- 载荷一律化成节点力（`*CLOAD`），这样支承节点上加了多少载荷是知道的，反力平衡才核得准：
  力（顶点：均分到各顶点；边：二阶线段等效节点力 1/6、4/6、1/6；面：二阶三角形等效节点力，角点 0、边中点各 1/3）、
  压力（壳的面，正值沿面法向的反方向压——法向按 STEP 面的方向，与实体“压向表面”一致）、重力（质量 × 加速度，同样按等效节点力分）。
- 结果：CalculiX 把壳、梁展开成三维单元算，frd 里是展开后的节点（壳的上下表面、梁截面外缘）：最大位移、最大 von Mises 取其中最大。
- 可信度：三层整体加密（比值 1.6），最大位移、最大应力分别按 trust.convergence 判；反力平衡只核对力
  （壳、梁固定端的反力矩 CalculiX 不单独输出）；壳的单元形状质量（gamma），梁不适用。
"""

from __future__ import annotations

import math
import os
import shutil
import tempfile
import time

import numpy as np

from analysis.fea import trust
from analysis.fea.geometry import _LOCK, _gmsh, load_step
from analysis.fea.solve import _ccx, read_frd_rf, von_mises

LEVELS, RATIO = 3, 1.6
LIMITS = ["壳、梁为线弹性、小变形；壳按中面计算，不计厚度方向的挤压；梁不计截面翘曲与局部屈曲",
          "梁的最大应力取自求解器展开截面上的点，比梁理论的外缘值偏低：矩形约 1 %、管约 3 %（对照题核实），校核时留出这个余量",
          "壳、梁的最大应力包含约束处（固定端弯矩最大是真实的，不避开）；尖角、点载荷处的应力可能随网格加密一直增大（奇异点），见网格收敛核查",
          "反力平衡只核对力：壳、梁固定端的反力矩求解器不单独输出"]


def _section(sec: dict) -> tuple[str, list[float], list[float] | None]:
    """→（CalculiX 截面名, 尺寸行, 局部 1 轴方向）"""
    if sec["shape"] == "rect":
        return "RECT", [float(sec["width_mm"]), float(sec["height_mm"])], [float(x) for x in sec["orientation"]]
    if sec["shape"] == "circle":
        # 实心圆按“壁厚 = 半径”的管截面算：CalculiX 2.21 的 CIRC 截面挠度对、应力低约 13 %（展开截面的取点问题），
        # PIPE(r, r) 挠度与应力都与梁理论相差 < 0.5 %（对照题核实，见 ADR-0095 施工记录）
        r = float(sec["diameter_mm"]) / 2
        return "PIPE", [r, r], None
    ro = float(sec["outer_diameter_mm"]) / 2
    return "PIPE", [ro, float(sec["wall_mm"])], None


def section_props(sec: dict) -> dict:
    """截面面积与惯性矩（mm²、mm⁴）：A、I1（绕局部 1 轴）、I2（绕局部 2 轴）。对照题与重力合力用"""
    if sec["shape"] == "rect":
        b, h = float(sec["width_mm"]), float(sec["height_mm"])
        return {"area_mm2": b * h, "i1_mm4": b * h ** 3 / 12, "i2_mm4": h * b ** 3 / 12}
    if sec["shape"] == "circle":
        d = float(sec["diameter_mm"])
        return {"area_mm2": math.pi * d ** 2 / 4, "i1_mm4": math.pi * d ** 4 / 64, "i2_mm4": math.pi * d ** 4 / 64}
    do = float(sec["outer_diameter_mm"])
    di = do - 2 * float(sec["wall_mm"])
    i = math.pi * (do ** 4 - di ** 4) / 64
    return {"area_mm2": math.pi * (do ** 2 - di ** 2) / 4, "i1_mm4": i, "i2_mm4": i}


def _mesh(gmsh, kind: str, size: float):
    gmsh.option.setNumber("Mesh.MeshSizeMax", size)
    gmsh.option.setNumber("Mesh.MeshSizeMin", size / 4)
    gmsh.option.setNumber("Mesh.ElementOrder", 2)
    gmsh.option.setNumber("Mesh.SecondOrderLinear", 0)
    gmsh.model.mesh.generate(2 if kind == "shell" else 1)
    ntags, xyz, _ = gmsh.model.mesh.getNodes()
    P = {int(t): xyz[3 * i:3 * i + 3].astype(float) for i, t in enumerate(ntags)}
    dim, etype = (2, 9) if kind == "shell" else (1, 8)
    elems = {}
    for _, tag in gmsh.model.getEntities(dim):
        ets, etags, enodes = gmsh.model.mesh.getElements(dim, tag)
        for et, eids, nodes in zip(ets, etags, enodes, strict=True):
            if et != etype:
                continue
            k = 6 if et == 9 else 3
            elems[int(tag)] = [(int(e), [int(n) for n in nodes[k * j:k * j + k]]) for j, e in enumerate(eids)]
    if not elems:
        raise ValueError("没有划出网格：壳的 STEP 要有曲面、梁的 STEP 要有曲线")
    return P, elems


def _entity_nodes(gmsh, dim: int, tags: list[int]) -> set[int]:
    out: set[int] = set()
    for t in tags:
        nt, _, _ = gmsh.model.mesh.getNodes(dim, int(t), includeBoundary=True)
        out |= {int(n) for n in nt}
    return out


def _line_elems(gmsh, tag: int) -> list[list[int]]:
    ets, _, enodes = gmsh.model.mesh.getElements(1, int(tag))
    out = []
    for et, nodes in zip(ets, enodes, strict=True):
        if et == 8:
            out += [[int(n) for n in nodes[3 * j:3 * j + 3]] for j in range(len(nodes) // 3)]
    return out


def _distribute(total: np.ndarray, weights: dict[int, float]) -> dict[int, np.ndarray]:
    s = sum(weights.values())
    return {n: total * (w / s) for n, w in weights.items()} if s > 0 else {}


def _force_nodes(gmsh, P, elems, x: dict) -> dict[int, np.ndarray]:
    """力 → 节点力（合力 = vector_n）"""
    F = np.asarray(x["vector_n"], float)
    w: dict[int, float] = {}
    if x.get("vertices"):
        for n in _entity_nodes(gmsh, 0, x["vertices"]):
            w[n] = w.get(n, 0.0) + 1.0
    elif x.get("edges"):
        for t in x["edges"]:
            for a, b, m in _line_elems(gmsh, t):                     # gmsh 二阶线段：两端、中点
                L = float(np.linalg.norm(P[a] - P[m]) + np.linalg.norm(P[m] - P[b]))
                for n, f in ((a, 1 / 6), (m, 4 / 6), (b, 1 / 6)):
                    w[n] = w.get(n, 0.0) + f * L
    else:
        for t in x["faces"]:
            for _e, nd in elems.get(int(t), []):
                A = 0.5 * float(np.linalg.norm(np.cross(P[nd[1]] - P[nd[0]], P[nd[2]] - P[nd[0]])))
                for n in nd[3:]:
                    w[n] = w.get(n, 0.0) + A / 3
    if not w:
        raise ValueError("力作用的边、顶点或面上没有网格节点")
    return _distribute(F, w)


def _bc_nodes(gmsh, x: dict) -> set[int]:
    if x.get("vertices"):
        return _entity_nodes(gmsh, 0, x["vertices"])
    if x.get("edges"):
        return _entity_nodes(gmsh, 1, x["edges"])
    return _entity_nodes(gmsh, 2, x["faces"])


def _write(path, kind, body, mat, P, elems, sups, forces, frequency):
    allel = [(e, nd) for lst in elems.values() for e, nd in lst]
    with open(path, "w") as w:
        w.write("*NODE, NSET=NALL\n")
        w.writelines(f"{n},{p[0]:.10g},{p[1]:.10g},{p[2]:.10g}\n" for n, p in sorted(P.items()))
        if kind == "shell":
            w.write("*ELEMENT, TYPE=S6, ELSET=EALL\n")
            w.writelines(f"{e},{','.join(map(str, nd))}\n" for e, nd in allel)
        else:
            w.write("*ELEMENT, TYPE=B32R, ELSET=EALL\n")                         # B32R：PIPE 截面只认它
            w.writelines(f"{e},{nd[0]},{nd[2]},{nd[1]}\n" for e, nd in allel)   # gmsh：两端、中点 → CalculiX：端、中、端
        w.write("*MATERIAL, NAME=M\n*ELASTIC\n{:.9g},{:.9g}\n*DENSITY\n{:.9g}\n".format(
            mat["elastic_modulus_mpa"], mat["poisson_ratio"], mat["density_kg_m3"] * 1e-12))
        if kind == "shell":
            w.write(f"*SHELL SECTION, ELSET=EALL, MATERIAL=M\n{float(body['thickness_mm']):.9g}\n")
        else:
            name, dims, ori = _section(body["section"])
            w.write(f"*BEAM SECTION, ELSET=EALL, MATERIAL=M, SECTION={name}\n{dims[0]:.9g},{dims[1]:.9g}\n")
            w.write("{:.9g},{:.9g},{:.9g}\n".format(*(ori or _any_normal(P, allel))))
        sup_nodes = sorted({n for nodes, _ in sups for n in nodes})
        w.write("*NSET, NSET=NSUP\n" + "".join(f"{n},\n" for n in sup_nodes))
        w.write("*STEP\n" + (f"*FREQUENCY\n{int(frequency)}\n" if frequency else "*STATIC\n") + "*BOUNDARY\n")
        for nodes, dofs in sups:
            for n in sorted(nodes):
                w.writelines(f"{n},{d},{d},{v:.9g}\n" for d, v in dofs)
        if not frequency:
            if forces:
                w.write("*CLOAD\n")
                for n, f in sorted(forces.items()):
                    for d in range(3):
                        if abs(f[d]) > 0:
                            w.write(f"{n},{d + 1},{f[d]:.9g}\n")
            w.write("*NODE PRINT, NSET=NSUP\nRF\n")
        w.write("*NODE FILE\nU\n*EL FILE\nS\n*END STEP\n")


def _any_normal(P, allel) -> list[float]:
    """圆、管截面也要给局部 1 轴：取与第一个单元轴线垂直的任一方向"""
    _e, nd = allel[0]
    t = P[nd[1]] - P[nd[0]]
    t = t / np.linalg.norm(t)
    a = np.array([0.0, 0.0, 1.0]) if abs(t[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n = np.cross(t, a)
    return list(n / np.linalg.norm(n))


def _section_size(sec: dict) -> float:
    return max(float(sec.get(k, 0)) for k in ("width_mm", "height_mm", "diameter_mm", "outer_diameter_mm"))


def _read_rf(dat) -> dict[int, np.ndarray]:
    out, on = {}, False
    with open(dat, errors="replace") as f:
        for line in f:
            if "forces (fx,fy,fz)" in line:
                on, out = True, {}
                continue
            if on:
                p = line.split()
                if len(p) == 4 and p[0].isdigit():
                    out[int(p[0])] = np.array([float(v) for v in p[1:]])
                elif out and not p:
                    on = False
    return out


def _frd_nodes(frd) -> dict[int, np.ndarray]:
    P, on = {}, False
    with open(frd, errors="replace") as f:
        for line in f:
            if line.startswith("    2C"):
                on = True
                continue
            if on:
                if line.startswith(" -3"):
                    break
                if line.startswith(" -1"):
                    P[int(line[3:13])] = np.array([float(line[13 + 12 * i:25 + 12 * i]) for i in range(3)])
    return P


def solve_once(body: dict, mat: dict, supports: list, loads: list, ccx: str, size_mm: float, frequency: int = 0,
               keep_dir: str | None = None, time_limit: int = 300) -> dict:
    """壳或梁算一次。返回统计"""
    kind = body["kind"]
    t0 = time.time()
    with _LOCK, tempfile.TemporaryDirectory() as tmp:
        gmsh = _gmsh()
        gmsh.option.restoreDefaults()
        gmsh.option.setNumber("General.Terminal", 0)
        load_step(gmsh, body["step_path"], tmp, require_solid=False)
        P, elems = _mesh(gmsh, kind, size_mm)
        sups = []
        for x in supports:
            nodes = _bc_nodes(gmsh, x)
            if not nodes:
                raise ValueError(f"支承 {x['type']} 作用的位置上没有网格节点")
            if x["type"] == "fixed":
                dofs = [(d, 0.0) for d in range(1, 7)]
            else:
                dofs = [(i + 1, float(x[k])) for i, k in enumerate(("ux_mm", "uy_mm", "uz_mm")) if k in x]
            sups.append((nodes, dofs))
        forces: dict[int, np.ndarray] = {}

        def add(n, f):
            forces[n] = forces.get(n, np.zeros(3)) + f

        for x in loads:
            if x["type"] == "force":
                for n, f in _force_nodes(gmsh, P, elems, x).items():
                    add(n, f)
            elif x["type"] == "pressure":                       # 等效节点力：二阶三角形角点 0、边中点各 1/3（正值沿单元法向的反方向压）
                for t in x["faces"]:
                    for _e, nd in elems.get(int(t), []):
                        av = np.cross(P[nd[1]] - P[nd[0]], P[nd[2]] - P[nd[0]]) / 2   # 面积 × 法向（按节点顺序 = 面的方向）
                        for n in nd[3:]:
                            add(n, -float(x["value_mpa"]) * av / 3)
            elif x["type"] == "gravity":                         # 质量 × 加速度，按二阶单元的等效节点力分
                acc = np.asarray(x["acceleration_m_s2"], float) * 1000.0      # m/s² → mm/s²
                rho = mat["density_kg_m3"] * 1e-12                           # t/mm³
                for lst in elems.values():
                    for _e, nd in lst:
                        if kind == "shell":
                            m = rho * float(body["thickness_mm"]) * 0.5 * float(np.linalg.norm(
                                np.cross(P[nd[1]] - P[nd[0]], P[nd[2]] - P[nd[0]])))
                            for n in nd[3:]:
                                add(n, m * acc / 3)
                        else:
                            a_, b_, m_ = nd
                            L = float(np.linalg.norm(P[a_] - P[m_]) + np.linalg.norm(P[m_] - P[b_]))
                            m = rho * section_props(body["section"])["area_mm2"] * L
                            for n, f in ((a_, 1 / 6), (m_, 4 / 6), (b_, 1 / 6)):
                                add(n, m * f * acc)
        quality = None
        if kind == "shell":
            tags = [e for lst in elems.values() for e, _ in lst]
            gam = np.asarray(gmsh.model.mesh.getElementQualities(tags, "gamma"), float)
            quality = {"elements": len(tags), "gamma_min": round(float(gam.min()), 4),
                       "gamma_below_0_1": int((gam < 0.1).sum()), "inverted": 0, "min_sj_min": 1.0}
        inp = os.path.join(tmp, "job.inp")
        _write(inp, kind, body, mat, P, elems, sups, forces, frequency)
        r = _ccx(ccx, tmp, time_limit)
        frd, dat = os.path.join(tmp, "job.frd"), os.path.join(tmp, "job.dat")
        if r.returncode != 0 or not os.path.exists(frd) or "*ERROR" in r.stdout:
            err = [x for x in (r.stdout + r.stderr).splitlines() if "ERROR" in x or "error" in x]
            raise RuntimeError("求解失败：" + ("；".join(err[-3:]) or (r.stdout + r.stderr)[-400:]))
        if keep_dir:
            os.makedirs(keep_dir, exist_ok=True)
            for name in ("job.inp", "job.frd", "job.dat"):
                shutil.copy(os.path.join(tmp, name), os.path.join(keep_dir, name))
        n_el = sum(len(v) for v in elems.values())
        if frequency:
            from analysis.fea.modal import read_freqs

            fr = [hz for _k, hz in read_freqs(dat)]
            return {"freqs": [{"mode": i + 1, "hz": round(hz, 4), "rpm": round(hz * 60, 2)} for i, hz in enumerate(fr)],
                    "nodes": len(P), "elements": n_el, "mesh_size_mm": size_mm, "seconds": round(time.time() - t0, 1)}
        disp, stress, _ = read_frd_rf(frd)
        PX = _frd_nodes(frd)
        un = {n: float(np.linalg.norm(v[:3])) for n, v in disp.items()}
        vm = {n: von_mises(s) for n, s in stress.items()}
        nu, nv = max(un, key=un.get), max(vm, key=vm.get)
        rf = _read_rf(dat)
        # CalculiX 的 RF 是节点上的全部外力（支承反力 + 加在这个节点上的载荷）：减去载荷才是支承反力
        R = sum((np.asarray(v) - forces.get(n, np.zeros(3)) for n, v in rf.items()), np.zeros(3))
        applied = sum(forces.values(), np.zeros(3))
        scale = max(float(np.linalg.norm(applied)), 1.0)
        bal = {"available": bool(rf), "applied_n": [round(float(v), 6) for v in applied],
               "reaction_n": [round(float(v), 6) for v in R], "force_error_ratio": float(np.linalg.norm(applied + R) / scale)}
        return {"u_max_mm": round(un[nu], 6), "u_max_at": [round(float(v), 4) for v in PX.get(nu, np.zeros(3))],
                "vm_max_mpa": round(vm[nv], 4), "vm_max_at": [round(float(v), 4) for v in PX.get(nv, np.zeros(3))],
                "nodes": len(P), "elements": n_el, "mesh_size_mm": round(size_mm, 4), "balance": bal, "mesh_quality": quality,
                "seconds": round(time.time() - t0, 1)}


def run(study: dict, ccx: str, mats: dict, keep_dir: str | None = None) -> tuple[dict, list[str]]:
    """壳 / 梁算例：静力（带三层网格核查）与模态"""
    body = study["bodies"][0]
    mat = mats[body["id"]]
    checks = study.get("checks") or {}
    size0 = (study.get("mesh") or {}).get("size_mm")
    if not size0:
        size0 = _default_size(body)
    steps, verdicts = [], []
    for st in study["steps"]:
        kd = os.path.join(keep_dir, st["id"]) if keep_dir else None
        if st["type"] == "modal":
            m = solve_once(body, mat, study["supports"], [], ccx, size0, frequency=int(st.get("n_modes", 6)), keep_dir=kd)
            steps.append({"id": st["id"], "type": "modal", **m})
            continue
        loads = [x for x in study.get("loads") or []]
        levels = int(checks.get("levels", LEVELS)) if checks.get("convergence", True) else 1
        r = float(checks.get("refine_ratio", RATIO))
        runs = [solve_once(body, mat, study["supports"], loads, ccx, size0 / r ** k, keep_dir=kd) for k in range(levels)]
        s = dict(runs[-1])
        items = [_balance_item(s["balance"], float(checks.get("balance_tolerance_ratio", 1e-3)))]
        if s["mesh_quality"]:
            items.append(trust.mesh_quality(s["mesh_quality"]))
        else:
            items.append(trust.item("网格质量", trust.PASS, "梁单元是线段，没有形状质量问题（不适用）"))
        if levels > 1:
            tol = float(checks.get("tolerance_ratio", 0.05))
            hs = [x["mesh_size_mm"] for x in runs]
            items.append(_named(trust.convergence([x["vm_max_mpa"] for x in runs], r, tol, hs=hs), "网格收敛（最大应力）"))
            items.append(_named(trust.convergence([x["u_max_mm"] for x in runs], r, tol, what="最大位移", hs=hs), "网格收敛（最大位移）"))
            s["levels"] = [{"mesh_size_mm": x["mesh_size_mm"], "elements": x["elements"], "vm_max_mpa": x["vm_max_mpa"],
                            "u_max_mm": x["u_max_mm"]} for x in runs]
        else:
            items.append(trust.item("网格收敛", trust.UNKNOWN, "没有做网格收敛核查"))
        tr = {"verdict": trust.verdict(items), "items": items, "levels": s.pop("levels", [])}
        y = mat.get("yield_strength_mpa")
        res = {"id": st["id"], "type": "static", **{k: v for k, v in s.items() if k != "balance"}, "balance": s["balance"],
               "trust": tr}
        if y and tr["verdict"] == trust.PASS:
            res.update(safety_factor=round(float(y) / s["vm_max_mpa"], 3), strength_mpa=y, strength_kind="屈服强度")
        elif y:
            res.update(safety_factor=None, strength_mpa=y, strength_kind="屈服强度",
                       safety_factor_withheld="可信度核查没有通过（结论：{}），不给安全系数".format(
                           {"fail": "不通过", "unknown": "未知"}[tr["verdict"]]))
        verdicts.append(tr["verdict"])
        steps.append(res)
    data = {"study": study.get("name", ""), "element_kind": body["kind"], "steps": steps,
            "trust_verdict": trust.verdict([{"verdict": v} for v in verdicts]) if verdicts else None}
    return data, list(LIMITS)


def _named(it: dict, name: str) -> dict:
    return {**it, "name": name}


def _balance_item(b: dict, tol: float) -> dict:
    if not b.get("available"):
        return trust.item("反力平衡", trust.UNKNOWN, "没有读到支承反力")
    ok = b["force_error_ratio"] <= tol
    return trust.item("反力平衡", trust.PASS if ok else trust.FAIL,
                      "外载合力与支承反力相抵（只核对力）" if ok else "外载与支承反力不平衡：模型或求解有问题，结果不能用",
                      force_error_ratio=b["force_error_ratio"], tolerance_ratio=tol)


def _default_size(body: dict) -> float:
    """缺省网格尺寸：包围盒对角线 / 20（壳）或 / 40（梁）"""
    from analysis.fea.geometry import faces

    bb = faces(body["step_path"])[1]["bbox_mm"]
    diag = math.dist(bb[:3], bb[3:])
    return diag / (20 if body["kind"] == "shell" else 40)
