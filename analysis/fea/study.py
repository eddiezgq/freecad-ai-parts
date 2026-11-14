"""有限元算例模型（ADR-0093，schema/fea-study.schema.json）：校验、旧 setup 转换、按算例计算并做可信度核查。

只做确定性的事：校验、换算、调用求解、核查。AI 起草算例在别处（F6），起草的算例 provenance.drafted_by = "ai"，
没有人确认（confirmed_by_human = false）的不算。
"""

from __future__ import annotations

import copy
import math
import time

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
    ids = {b["id"] for b in study["bodies"]}
    for x in study["supports"] + study.get("loads", []):
        if x["body"] not in ids:
            raise StudyInvalid(f"没有实体 {x['body']!r}")
    pv = study.get("provenance")
    if pv and pv["drafted_by"] == "ai" and not pv["confirmed_by_human"]:
        raise StudyInvalid("这个算例是 AI 起草的，还没有人确认，不计算")
    if not study.get("loads") and any(s["type"] == "static" for s in study["steps"]):
        raise StudyInvalid("静力分析还没有加载荷")


def _axis(a: dict) -> dict:
    return {"origin": list(a["origin_mm"]), "dir": list(a["dir"])}


def internal_loads(study: dict) -> list[dict]:
    """算例的支承与载荷 → 求解器内部的写法（solve.py：mm、N、N·mm；支承和载荷混在一个表里）"""
    out = []
    for x in study["supports"] + study.get("loads", []):
        d = {"type": x["type"], "faces": list(x["faces"])}
        t = x["type"]
        if t == "cyl_support":
            d["axis"] = _axis(x["axis"])
            d["dofs"] = list(x.get("dofs") or ["radial"])
            if "band_mm" in x:
                d["band_mm"] = x["band_mm"]
        elif t == "force":
            d["vector_n"] = list(x["vector_n"])
        elif t == "pressure":
            d["value_mpa"] = float(x["value_mpa"])
        elif t == "torque":
            d["value_nmm"] = float(x["value_nm"]) * 1000
            d["axis"] = _axis(x["axis"])
        elif t == "moment":
            d["vector_nmm"] = [float(v) * 1000 for v in x["vector_nm"]]
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


def _inner(study: dict, mat: dict) -> dict:
    m = study.get("mesh") or {}
    inner = {"material": mat, "loads": internal_loads(study), "mesh": {"size_mm": m.get("size_mm")}}
    if m.get("refine_faces"):
        inner["refine_faces"] = list(m["refine_faces"])
    if m.get("max_elements"):
        inner["max_elements"] = m["max_elements"]
    if study.get("time_limit_s"):
        inner["time_limit_s"] = study["time_limit_s"]
    return inner


def run_static(step_path: str, inner: dict, ccx: str, checks: dict) -> tuple[dict, dict, dict]:
    """静力 + 可信度核查。返回 (这一步的结果, 表面结果, 核查)"""
    from analysis.fea import solve

    conv = checks.get("convergence", True)
    levels = int(checks.get("levels", 3))
    r = float(checks.get("refine_ratio", 1.6))
    tol = float(checks.get("tolerance_ratio", 0.05))
    btol = float(checks.get("balance_tolerance_ratio", 1e-3))
    stats, surface, _ = solve.solve(step_path, inner, ccx)
    runs = [stats]
    if conv:
        h0 = stats["mesh_size_mm"]
        s0 = stats["vm_max_local_h_mm"]
        center = stats["vm_max_at"]
        for k in range(1, levels):
            lv = copy.deepcopy(inner)
            lv["refine"] = {"center_mm": center, "radius_mm": max(2 * h0, 4 * s0), "size_mm": s0 / r ** k}
            lv["exclude_h_mm"] = h0
            st_k, surf_k, _ = solve.solve(step_path, lv, ccx)
            runs.append(st_k)
            stats, surface = st_k, surf_k
    items = [trust.balance(stats["balance"], btol), trust.mesh_quality(stats["mesh_quality"])]
    if conv:
        items.append(trust.convergence([x["vm_max_mpa"] for x in runs], r, tol, "最大应力", [x["vm_max_local_h_mm"] for x in runs]))
        items.append(trust.convergence([x["u_max_mm"] for x in runs], r, tol, "最大位移"))
        moved = math.dist(runs[0]["vm_max_at"], runs[-1]["vm_max_at"])
        if moved > 2 * runs[0]["mesh_size_mm"]:
            ok = items[-2]["verdict"] == trust.PASS
            items.append(trust.item("最大应力的位置", trust.PASS if ok else trust.UNKNOWN,
                                    f"加密后最大应力的位置移动了 {moved:.2f} mm" +
                                    ("，但各层最大值一致：应力相近的区域不止一处（例如整圈均匀受力）" if ok
                                     else "：可能有几处应力相近，逐处核查"), moved_mm=moved))
    else:
        items.append(trust.item("网格收敛", trust.UNKNOWN, "没有做网格收敛核查（checks.convergence = false）"))
    tr = {"verdict": trust.verdict(items), "items": items,
          "levels": [{"mesh_size_mm": x["mesh_size_mm"], "local_h_mm": x["vm_max_local_h_mm"], "elements": x["elements"],
                      "vm_max_mpa": x["vm_max_mpa"], "u_max_mm": x["u_max_mm"]} for x in runs]}
    return stats, surface, tr


def run(study: dict, ccx: str) -> tuple[dict, list[str]]:
    """按算例计算。返回 (data, 局限说明)。抛 StudyInvalid / ValueError / RuntimeError / materials.MissingData"""
    from analysis.fea import LIMITS_MODAL, LIMITS_STATIC, _lists, modal

    validate(study)
    body = study["bodies"][0]
    mat = materials.get(body["material"])
    materials.require(mat, ["elastic_modulus_mpa", "poisson_ratio", "density_kg_m3"], "有限元")
    inner = _inner(study, mat)
    checks = study.get("checks") or {}
    steps, limits, verdicts = [], [], []
    for st in study["steps"]:
        t0 = time.time()
        if st["type"] == "static":
            stats, surface, tr = run_static(body["step_path"], inner, ccx, checks)
            res = {"id": st["id"], "type": "static", **stats, "trust": tr, "surface": _lists(surface)}
            if tr["verdict"] != trust.PASS and "safety_factor" in res:
                res["safety_factor"] = None
                res["safety_factor_withheld"] = "可信度核查没有通过（结论：{}），不给安全系数".format(
                    {"fail": "不通过", "unknown": "未知"}[tr["verdict"]])
            verdicts.append(tr["verdict"])
            limits += [x for x in LIMITS_STATIC if x not in limits]
        else:
            stats, surface = modal.solve(body["step_path"], inner, ccx, n_modes=int(st.get("n_modes", 6)))
            res = {"id": st["id"], "type": "modal", **stats, "surface": _lists(surface)}
            limits += [x for x in LIMITS_MODAL if x not in limits]
        res["seconds"] = round(time.time() - t0, 1)
        steps.append(res)
    data = {"study": study.get("name", ""), "steps": steps,
            "trust_verdict": trust.verdict([{"verdict": v} for v in verdicts]) if verdicts else None}
    return data, limits
