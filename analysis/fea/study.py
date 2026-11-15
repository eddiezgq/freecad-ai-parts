"""有限元算例模型（ADR-0093，schema/fea-study.schema.json）：校验、旧 setup 转换、按算例计算并做可信度核查。

只做确定性的事：校验、换算、调用求解、核查。AI 起草算例在别处（F6），起草的算例 provenance.drafted_by = "ai"，
没有人确认（confirmed_by_human = false）的不算。
"""

from __future__ import annotations

import copy
import itertools
import math
import time

import numpy as np

from analysis.common import materials
from analysis.fea import trust

FORMAT = "fea-study/1"
SUPPORT_TYPES = ("fixed", "cyl_support")


class StudyInvalid(ValueError):
    pass


def validate(study: dict) -> None:
    from kb.validation import errors

    errs = errors("fea-study.schema.json", study)
    if errs:
        raise StudyInvalid("算例不符合格式：" + "；".join(errs[:5]))
    ids = [b["id"] for b in study["bodies"]]
    if len(set(ids)) != len(ids):
        raise StudyInvalid("实体的 id 重复")
    refs = [x["body"] for x in study["supports"] + study.get("loads", [])]
    for c in study.get("connections") or []:
        refs += [c["body"]] if c["type"] == "bolt_preload" else [c["a"]["body"], c["b"]["body"]]
        if c["type"] != "bolt_preload" and c["a"]["body"] == c["b"]["body"]:
            raise StudyInvalid("连接的两侧要在不同的实体上")
    for r in refs:
        if r not in ids:
            raise StudyInvalid(f"没有实体 {r!r}")
    for b in study["bodies"]:
        pl = b.get("plasticity")
        if pl and pl["model"] == "curve":
            eps = [p["plastic_strain"] for p in pl["points"]]
            if eps[0] != 0 or any(b2 <= a2 for a2, b2 in itertools.pairwise(eps)):
                raise StudyInvalid(f"实体 {b['id']} 的塑性曲线：第一个点的塑性应变要为 0，之后递增")
    kinds = {s["type"] for s in study["steps"]}
    if "buckling" in kinds:
        if any(b.get("plasticity") for b in study["bodies"]):
            raise StudyInvalid("线性屈曲不能用弹塑性材料（线性屈曲以线弹性为前提）")
        if any(c["type"] in ("contact", "bolt_preload") for c in study.get("connections") or []):
            raise StudyInvalid("线性屈曲不能带接触或螺栓预紧（连接要是固定的）")
        if not study.get("loads"):
            raise StudyInvalid("线性屈曲要有参考载荷")
    dyn = [s for s in study["steps"] if s["type"] in ("modal", "harmonic", "random", "transient")]
    if dyn:
        if any(b.get("plasticity") for b in study["bodies"]):
            raise StudyInvalid("模态与动力学只用于线性模型：不能用弹塑性材料")
        if any(c["type"] in ("contact", "bolt_preload") for c in study.get("connections") or []):
            raise StudyInvalid("模态与动力学只用于线性模型：连接只能是绑定（不能带接触、螺栓预紧）")
    for s in dyn:
        if s["type"] in ("harmonic", "random", "transient"):
            if any(x["type"] == "temperature" for x in study.get("loads", [])):
                raise StudyInvalid("动力学的分析步不能带温度载荷")
            if moved_any(study):
                raise StudyInvalid("动力学的分析步不能带非零的强制位移")
        if s["type"] == "harmonic" and s["f_max_hz"] <= s["f_min_hz"]:
            raise StudyInvalid("谐响应的上限频率要大于下限频率")
        if s["type"] in ("harmonic", "transient") and not study.get("loads"):
            raise StudyInvalid("谐响应、瞬态要有载荷（载荷值为幅值）")
        if s["type"] == "random":
            fs = [p["frequency_hz"] for p in s["asd"]]
            if any(b <= a for a, b in itertools.pairwise(fs)):
                raise StudyInvalid("功率谱的频率要递增")
            if not any(s["direction"]):
                raise StudyInvalid("随机振动的激励方向不能是零向量")
        if s["type"] == "transient":
            ts = [p["time_s"] for p in s["amplitude"]]
            if any(b <= a for a, b in itertools.pairwise(ts)):
                raise StudyInvalid("载荷随时间的变化：时间要递增")
            if s["end_time_s"] / s["time_step_s"] > 20000:
                raise StudyInvalid("瞬态的输出点超过 20000 个：把输出间隔调大")
    pv = study.get("provenance")
    if pv and pv["drafted_by"] == "ai" and not pv["confirmed_by_human"]:
        raise StudyInvalid("这个算例是 AI 起草的，还没有人确认，不计算")
    moved = any(x["type"] == "displacement" and any(x.get(k) for k in ("ux_mm", "uy_mm", "uz_mm")) for x in study["supports"])
    bolts = any(c["type"] in ("bolt_preload", "contact") for c in study.get("connections") or [])   # 预紧、过盈本身就是载荷
    if not study.get("loads") and not moved and not bolts and any(s["type"] == "static" for s in study["steps"]):
        raise StudyInvalid("静力分析还没有加载荷")


def moved_any(study: dict) -> bool:
    return any(x["type"] == "displacement" and any(x.get(k) for k in ("ux_mm", "uy_mm", "uz_mm")) for x in study["supports"])


def _axis(a: dict) -> dict:
    return {"origin": list(a["origin_mm"]), "dir": list(a["dir"])}


def internal_loads(study: dict) -> list[dict]:
    """算例的支承与载荷 → 求解器内部的写法（solve.py：mm、N、N·mm、mm/s²；支承和载荷混在一个表里）"""
    out = []
    for x in study["supports"] + study.get("loads", []):
        t = x["type"]
        d = {"type": t}
        if "faces" in x:
            d["faces"] = list(x["faces"])
        if "edges" in x:
            d["edges"] = list(x["edges"])
        if t == "cyl_support":
            d["axis"] = _axis(x["axis"])
            d["dofs"] = list(x.get("dofs") or ["radial"])
            if "band_mm" in x:
                d["band_mm"] = x["band_mm"]
        elif t == "displacement":
            d.update({k: float(x[k]) for k in ("ux_mm", "uy_mm", "uz_mm") if k in x})
        elif t == "elastic_support":
            d["stiffness_n_per_mm3"] = float(x["stiffness_n_per_mm3"])
        elif t == "force":
            d["vector_n"] = list(x["vector_n"])
        elif t == "pressure":
            d["value_mpa"] = float(x["value_mpa"])
        elif t == "torque":
            d["value_nmm"] = float(x["value_nm"]) * 1000
            d["axis"] = _axis(x["axis"])
        elif t == "moment":
            d["vector_nmm"] = [float(v) * 1000 for v in x["vector_nm"]]
        elif t == "gravity":
            d["acceleration_mm_s2"] = [float(v) * 1000 for v in x["acceleration_m_s2"]]
        elif t == "centrifugal":
            d["speed_rpm"] = float(x["speed_rpm"])
            d["axis"] = _axis(x["axis"])
        elif t == "remote_load":
            d["point_mm"] = list(x["point_mm"])
            if "force_n" in x:
                d["vector_n"] = list(x["force_n"])
            if "vector_nm" in x:
                d["vector_nmm"] = [float(v) * 1000 for v in x["vector_nm"]]
        elif t == "bearing_load":
            d["vector_n"] = list(x["force_n"])
            d["axis"] = _axis(x["axis"])
        elif t == "temperature":
            d["delta_t_k"] = float(x["delta_t_k"])
        out.append(d)
    return out


def from_setup(setup: dict) -> dict:
    """旧写法（step_path + material + loads 混写）→ 算例模型。旧写法缺省不做网格收敛（ADR-0093 补充）"""
    sup, lds = [], []
    for ld in setup.get("loads") or []:
        x = {"type": ld["type"], "body": "b1", "faces": list(ld.get("faces") or [])}
        if "axis" in ld:
            x["axis"] = {"origin_mm": list(ld["axis"]["origin"]), "dir": list(ld["axis"]["dir"])}
        for k in ("dofs", "band_mm", "vector_n", "value_mpa", "value_nm"):
            if k in ld:
                x[k] = ld[k]
        if ld["type"] == "moment" and "vector_nmm" in ld:
            x["vector_nm"] = [v / 1000 for v in ld["vector_nmm"]]
        (sup if ld["type"] in SUPPORT_TYPES else lds).append(x)
    kind = setup.get("analysis", "static")
    step = {"id": "s1", "type": kind}
    if kind == "modal":
        step["n_modes"] = int(setup.get("n_modes", 6))
    st = {"format": FORMAT, "name": "legacy", "bodies": [{"id": "b1", "step_path": setup["step_path"],
                                                           "material": setup.get("material", "")}],
          "supports": sup, "loads": lds, "steps": [step], "checks": {"convergence": False}}
    if setup.get("mesh"):
        st["mesh"] = {k: v for k, v in setup["mesh"].items() if k in ("size_mm",)}
    return st


def _plastic(body: dict, mat: dict) -> list | None:
    """塑性 → 求解器的 (真应力, 塑性应变) 表；理想弹塑性用材料库的屈服强度（没有就报缺数据，不估）"""
    pl = body.get("plasticity")
    if not pl:
        return None
    if pl["model"] == "perfectly_plastic":
        materials.require(mat, ["yield_strength_mpa"], "弹塑性")
        return [(float(mat["yield_strength_mpa"]), 0.0)]
    return [(float(p["true_stress_mpa"]), float(p["plastic_strain"])) for p in pl["points"]]


def _inner(study: dict, mats: dict) -> dict:
    """算例 → 求解器的输入：每个实体各自的支承与载荷、连接（实体用下标）、螺栓预紧"""
    m = study.get("mesh") or {}
    ids = [b["id"] for b in study["bodies"]]
    loads = internal_loads(study)
    owner = [x["body"] for x in study["supports"] + study.get("loads", [])]
    bodies = []
    for b in study["bodies"]:
        bodies.append({"id": b["id"], "step_path": b["step_path"], "material": mats[b["id"]], "plastic": _plastic(b, mats[b["id"]]),
                       "loads": [ld for ld, o in zip(loads, owner) if o == b["id"]],
                       "refine_faces": list(m.get("refine_faces") or []) if len(ids) == 1 else []})
    conns, bolts = [], []
    for c in study.get("connections") or []:
        if c["type"] == "bolt_preload":
            bolts.append({"id": c.get("id"), "body": ids.index(c["body"]), "point_mm": list(c["point_mm"]),
                          "axis_dir": list(c["axis_dir"]), "force_n": float(c["force_n"])})
        else:
            conns.append({"type": c["type"], "id": c.get("id"), "a_body": ids.index(c["a"]["body"]), "a_faces": list(c["a"]["faces"]),
                          "b_body": ids.index(c["b"]["body"]), "b_faces": list(c["b"]["faces"]),
                          "mu": float(c.get("friction_coefficient") or 0), "tolerance_mm": c.get("tolerance_mm")})
    inner = {"bodies": bodies, "connections": conns, "bolts": bolts, "mesh": {"size_mm": m.get("size_mm")},
             # 单个实体时模态分析仍用旧的单体接口
             "material": bodies[0]["material"], "loads": bodies[0]["loads"]}
    if m.get("refine_faces") and len(ids) == 1:
        inner["refine_faces"] = list(m["refine_faces"])
    if m.get("max_elements"):
        inner["max_elements"] = m["max_elements"]
    if study.get("time_limit_s"):
        inner["time_limit_s"] = study["time_limit_s"]
    if study.get("probes"):
        inner["probes"] = study["probes"]
    return inner


def run_static(step_path: str, inner: dict, ccx: str, checks: dict) -> tuple[dict, dict, dict]:
    """静力 + 可信度核查。返回 (这一步的结果, 表面结果, 核查)"""
    from analysis.fea import solve

    conv = checks.get("convergence", True)
    levels = int(checks.get("levels", 3))
    r = float(checks.get("refine_ratio", 1.6))
    tol = float(checks.get("tolerance_ratio", 0.05))
    btol = float(checks.get("balance_tolerance_ratio", 1e-3))
    stats, surface, _ = solve.solve_bodies(inner["bodies"], inner, ccx)
    runs = [stats]
    center = stats["vm_max_at"]
    if conv:
        h0 = stats["mesh_size_mm"]
        s0 = stats["vm_max_local_h_mm"]
        rad = max(2 * h0, 4 * s0)
        for k in range(levels):
            lv = copy.deepcopy(inner)
            if k:
                lv["refine"] = {"center_mm": center, "radius_mm": rad, "size_mm": s0 / r ** k}
            lv["exclude_h_mm"] = h0
            lv["track_point_mm"], lv["track_radius_mm"] = center, rad
            if not k:                                     # 第 0 层：原网格，只补算加密球内的最大值
                stats["vm_at_track_mpa"], stats["track_local_h_mm"] = stats["vm_max_mpa"], s0
                continue
            st_k, surf_k, _ = solve.solve_bodies(lv["bodies"], lv, ccx)
            runs.append(st_k)
            stats, surface = st_k, surf_k
    items = [trust.balance(stats["balance"], btol), trust.mesh_quality(stats["mesh_quality"])]
    nl = stats.get("nonlinear")
    if nl:
        if nl["completed"]:
            items.append(trust.item("载荷加完", trust.PASS, "全部载荷都加上了", load_fraction_reached=1.0))
        else:
            items.append(trust.item("载荷加完", trust.FAIL,
                                    "只加到 {:.1%} 的载荷就算不下去了：结构在这一载荷下失去承载（塑性垮塌、失稳）或数值不收敛".format(
                                        nl["load_fraction_reached"]), load_fraction_reached=nl["load_fraction_reached"]))
    if conv:
        vals = [x["vm_at_track_mpa"] for x in runs]
        hs = [x["track_local_h_mm"] for x in runs]
        items.append(trust.convergence(vals, r, tol, "最大应力", hs))
        items.append(trust.convergence([x["u_max_mm"] for x in runs], r, tol, "最大位移"))
        # 最细一层里别处（没有加密的地方）的应力比核查的那一点还大：那一处没有核查过收敛
        top, at = runs[-1]["vm_max_mpa"], runs[-1]["vm_max_at"]
        far = math.dist(at, center) > rad
        if far and top > vals[-1] * (1 + tol):
            items.append(trust.item("最大应力的位置", trust.UNKNOWN,
                                    f"别处 {at} 的应力 {top:.4g} MPa 比核查的这一点（{vals[-1]:.4g} MPa）还大，那一处没有核查收敛：在那里另做核查",
                                    other_vm_mpa=top, other_at=at))
    else:
        items.append(trust.item("网格收敛", trust.UNKNOWN, "没有做网格收敛核查（checks.convergence = false）"))
    tr = {"verdict": trust.verdict(items), "items": items,
          "checked_at": center if conv else None,
          "levels": [{"mesh_size_mm": x["mesh_size_mm"], "local_h_mm": h_, "elements": x["elements"],
                      "vm_checked_mpa": v_, "vm_max_mpa": x["vm_max_mpa"], "u_max_mm": x["u_max_mm"]}
                     for x, v_, h_ in zip(runs, vals if conv else [runs[0]["vm_max_mpa"]],
                                          hs if conv else [runs[0]["vm_max_local_h_mm"]])]}
    return stats, surface, tr


def run_buckling(inner: dict, ccx: str, n_modes: int) -> tuple[dict, dict]:
    """线性屈曲：参考载荷 × 系数 = 屈曲载荷。核查：网格质量；系数 < 1 表示参考载荷下就会失稳（这是结论，不是可信度）"""
    from analysis.fea import solve

    stats, _s, _n = solve.solve_bodies(inner["bodies"], dict(inner, buckle=n_modes), ccx)
    lf = stats["load_factors"]
    stats["buckles_under_reference_load"] = bool(lf and min(lf) < 1)
    items = [trust.mesh_quality(stats["mesh_quality"]),
             trust.item("网格收敛", trust.UNKNOWN, "屈曲系数没有做网格收敛核查")]
    return stats, {"verdict": trust.verdict(items), "items": items}


def _modal(inner: dict, ccx: str, n: int, prestress: bool, cache: dict) -> dict:
    from analysis.fea import solve

    key = (n, prestress)
    if key not in cache:
        cache[key] = solve.solve_bodies(inner["bodies"], dict(inner, frequency=n, prestress=prestress), ccx)[0]
    return cache[key]


def run_modal(inner: dict, ccx: str, st: dict, cache: dict) -> tuple[dict, dict]:
    """预应力模态、多个实体的模态（ADR-0093 F5）"""
    n = int(st.get("n_modes", 6))
    m = _modal(inner, ccx, n, bool(st.get("prestress")), cache)
    out = {"analysis": "modal", "nodes": m["nodes"], "elements": m["elements"], "prestress": m["prestress"],
           "freqs": [{"mode": i + 1, "hz": round(float(hz), 4), "rpm": round(float(hz) * 60, 0)} for i, hz in enumerate(m["freqs_hz"][:n])],
           "rigid_modes": m["rigid_modes"]}
    if m.get("eff_mass") is not None and m.get("total_mass") is not None:
        out["effective_mass_fraction"] = {k: round(float(m["eff_mass"][:n, i].sum() / m["total_mass"][i]), 6)
                                          for i, k in enumerate("xyz") if m["total_mass"][i] > 0}
    sf = m["surface"]                                      # 表面上画第一阶振型（最大为 1），同旧的模态输出
    rows = np.searchsorted(m["node_ids"], sf["nodes"])
    U = m["phi"][rows, :, 0]
    U = U / max(float(np.linalg.norm(U, axis=1).max()), 1e-12)
    surface = {"positions": np.round(sf["positions"], 4), "triangles": sf["triangles"], "u": np.round(U, 6),
               "vm": np.round(np.linalg.norm(U, axis=1), 6)}
    return out, surface


def run_dynamic(inner: dict, ccx: str, st: dict, cache: dict) -> tuple[dict, dict]:
    """谐响应、随机振动、瞬态（模态叠加）+ 核查：网格质量、模态截断、频率范围"""
    from analysis.fea import dynamics, solve

    n = int(st.get("n_modes", 30))
    m = _modal(inner, ccx, n, False, cache)
    z = float(st["damping_ratio"])
    probes = inner.get("probes") or []
    items = [trust.mesh_quality(m["mesh_quality"])]
    fmax = None
    if st["type"] == "harmonic":
        res = dynamics.harmonic(m, float(st["f_min_hz"]), float(st["f_max_hz"]), int(st.get("n_points", 200)), z, probes)
        fmax = float(st["f_max_hz"])
    elif st["type"] == "random":
        asd = [(float(p["frequency_hz"]), float(p["asd_m2_s4_per_hz"]) * 1e6) for p in st["asd"]]   # (m/s²)²/Hz → (mm/s²)²/Hz
        res = dynamics.random_vibration(m, st["direction"], asd, z, probes)
        fmax = asd[-1][0]
        fr = res["effective_mass_fraction"]
        if fr is None:
            items.append(trust.item("模态截断", trust.UNKNOWN, "没有读到有效质量"))
        else:
            ok = fr >= 0.9
            items.append(trust.item("模态截断", trust.PASS if ok else trust.UNKNOWN,
                                    f"所取 {len(m['freqs_hz'])} 阶在激励方向的有效质量占 {fr:.1%}" + ("" if ok else "，不到 90 %：加阶数"),
                                    effective_mass_fraction=fr))
    else:
        amp = [(float(p["time_s"]), float(p["factor"])) for p in st["amplitude"]]
        res = dynamics.transient(m, amp, float(st["end_time_s"]), float(st["time_step_s"]), z, probes)
    if st["type"] in ("harmonic", "transient"):                    # 0 Hz 时的模态叠加 vs 真正的静力解
        if "static" not in cache:
            cache["static"] = solve.solve_bodies(inner["bodies"], inner, ccx)[0]
        us = float(cache["static"]["u_max_mm"])
        um = float(np.linalg.norm(dynamics.static_from_modes(m), axis=1).max())
        err = abs(um - us) / max(us, 1e-30)
        ok = err <= 0.05
        items.append(trust.item("模态截断", trust.PASS if ok else trust.UNKNOWN,
                                f"0 Hz 时模态叠加的最大位移与静力解差 {err:.1%}" + ("" if ok else "，超过 5 %：加阶数"),
                                static_u_max_mm=us, modal_u_max_mm=um, error_ratio=err))
    if fmax is not None:
        top = float(m["freqs_hz"][-1])
        ok = top >= 1.5 * fmax
        items.append(trust.item("频率范围", trust.PASS if ok else trust.UNKNOWN,
                                f"所取最高一阶 {top:.4g} Hz，分析上限 {fmax:.4g} Hz" + ("" if ok else "：不到 1.5 倍，加阶数"),
                                highest_mode_hz=top, f_max_hz=fmax))
    res.update({"nodes": m["nodes"], "elements": m["elements"], "n_modes_used": len(m["freqs_hz"]),
                "mode_freqs_hz": [round(float(x), 4) for x in m["freqs_hz"]], "damping_ratio": z})
    return res, {"verdict": trust.verdict(items), "items": items}


def run(study: dict, ccx: str) -> tuple[dict, list[str]]:
    """按算例计算。返回 (data, 局限说明)。抛 StudyInvalid / ValueError / RuntimeError / materials.MissingData"""
    from analysis.fea import (
        LIMITS_BUCKLING,
        LIMITS_DYNAMIC,
        LIMITS_MODAL,
        LIMITS_STATIC,
        _lists,
    )

    validate(study)
    body = study["bodies"][0]
    mats = {}
    for b in study["bodies"]:
        mats[b["id"]] = materials.get(b["material"])
        materials.require(mats[b["id"]], ["elastic_modulus_mpa", "poisson_ratio", "density_kg_m3"], "有限元")
    inner = _inner(study, mats)
    checks = study.get("checks") or {}
    steps, limits, verdicts, cache = [], [], [], {}
    for st in study["steps"]:
        t0 = time.time()
        if st["type"] in ("harmonic", "random", "transient"):
            res, tr = run_dynamic(inner, ccx, st, cache)
            res = {"id": st["id"], "type": st["type"], **res, "trust": tr}
            verdicts.append(tr["verdict"])
            limits += [x for x in LIMITS_DYNAMIC if x not in limits]
        elif st["type"] == "modal":                       # 算例里的模态都走多实体求解（支承类型齐全、可加预应力，ADR-0093 F5）
            mres, surface = run_modal(inner, ccx, st, cache)
            res = {"id": st["id"], "type": "modal", **mres, "surface": _lists(surface)}
            limits += [x for x in LIMITS_MODAL if x not in limits]
        elif st["type"] == "buckling":
            res, tr = run_buckling(inner, ccx, int(st.get("n_modes", 3)))
            res = {"id": st["id"], "type": "buckling", **res, "trust": tr}
            verdicts.append(tr["verdict"])
            limits += [x for x in LIMITS_BUCKLING if x not in limits]
        elif st["type"] == "static":
            inner_s = dict(inner, nlgeom=bool(st.get("large_deformation")))
            stats, surface, tr = run_static(body["step_path"], inner_s, ccx, checks)
            res = {"id": st["id"], "type": "static", **stats, "trust": tr, "surface": _lists(surface)}
            plastic = any(b.get("plastic") for b in inner["bodies"])
            if plastic:                                    # 屈服之后“屈服强度 / 最大应力”没有意义：不给，改看塑性应变
                for k in ("safety_factor", "strength_mpa", "strength_kind", "safety_body"):
                    res.pop(k, None)
                for b in res.get("bodies") or []:
                    b.pop("safety_factor", None)
                res["safety_factor_withheld"] = "弹塑性计算不给“屈服强度 / 最大应力”的安全系数：看最大等效塑性应变和载荷是否加完"
            elif tr["verdict"] != trust.PASS and "safety_factor" in res:
                res["safety_factor"] = None
                res["safety_factor_withheld"] = "可信度核查没有通过（结论：{}），不给安全系数".format(
                    {"fail": "不通过", "unknown": "未知"}[tr["verdict"]])
            verdicts.append(tr["verdict"])
            first = "{}、{}".format("弹塑性（Mises、各向同性硬化）" if plastic else "线弹性",
                                   "大变形" if st.get("large_deformation") else "小变形")
            if not inner["connections"]:
                first += "；不计接触"
            first += "；不计残余应力与表面硬化"
            limits += [x for x in [first, *LIMITS_STATIC[1:]] if x not in limits]
        res["seconds"] = round(time.time() - t0, 1)
        steps.append(res)
    data = {"study": study.get("name", ""), "steps": steps,
            "trust_verdict": trust.verdict([{"verdict": v} for v in verdicts]) if verdicts else None}
    return data, limits
