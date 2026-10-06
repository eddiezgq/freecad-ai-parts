"""设计优化（ADR-0056，M10 第四步）：Optuna（TPE 贝叶斯优化，带约束）驱动有限元，每次评估都是一次真实分析，
在满足强度（与疲劳）要求的前提下找最轻的尺寸。搬自问渠数字工厂第 14 轮的做法；几何改由 Gmsh 按参数生成。

设置：
  problem: "beam" | "shaft"
  beam:  {"length_mm", "width_mm", "force_n"}，变量 h（截面高 mm）
  shaft: {"segments": [[直径 mm, 长度 mm], ...]（从左到右）, "torque_nm"}，左端面固定、右端面加扭矩；
         变量 d<段号>（如 d0、d2；同一个变量名可用 "segments": [0, 4] 让两段同时变）
  vars: [{"name": "h", "low", "high", "step"}] 或 [{"name": "d0", "segments": [0, 4], "low", "high", "step"}]
  material（材料库 id）、constraints: {"sf_min": 1.3, "fatigue": {"surface_factor", "size_factor", "miner",
         "load_series": [...], "life": "infinite" 或 小时数, "block_seconds"}}（疲劳为可选，用于轴）
  n_trials（≤ 60）、seed、mesh_div（网格尺寸 = 最小特征尺寸 / mesh_div 的倍数，缺省 4）、time_limit_s
结果 data：每次评估（变量、质量、安全系数、寿命、是否满足、违反项），第一次固定是现行设计；best：满足要求的最轻几组。
"""

from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path

from analysis.common import materials, result

MODULE = {
    "id": "optimize", "name": "设计优化", "version": "1",
    "description": "在强度、疲劳要求下自动找最轻尺寸（Optuna 驱动有限元，本机计算）",
    "python": ["optuna", "gmsh", "numpy", "scipy"], "solvers": ["ccx"],
    "install": '安装：pip install -e ".[optimize,fea]"；CalculiX 用 FreeCAD 自带的，或设置环境变量 FAP_CCX',
}
MAX_TRIALS = 60
LIMITS = ["每次评估是一次线弹性有限元（网格按尺寸自动划分），最优点附近的差别可能小于网格误差",
          "TPE 是随机搜索，次数有限时找到的是“较优”而非严格最优；固定 seed 时结果可复现"]


class OptError(ValueError):
    pass


def _step(fn, name: str, tmp: Path) -> str:
    """按参数生成几何并写 STEP；与有限元共用同一个 gmsh 会话（不注册信号，后台线程中也能用）。"""
    from analysis.fea.geometry import _LOCK, _gmsh

    path = tmp / f"{name}.step"
    with _LOCK:
        gmsh = _gmsh()
        gmsh.clear()
        gmsh.model.add(name)
        fn(gmsh)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
        gmsh.clear()
    return str(path)


def _faces_at(faces, axis: int, value: float) -> list[int]:
    return [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][axis] - value) < 1e-6]


def _segments(spec: dict, x: dict) -> list[list[float]]:
    segs = [list(map(float, s)) for s in spec["segments"]]
    for v in spec["_vars"]:
        for i in v["segments"]:
            segs[i][0] = x[v["name"]]
    return segs


def evaluate(problem: str, spec: dict, x: dict, mat: dict, cons: dict, tmp: Path) -> dict:
    """一次评估：几何 → 有限元（→ 疲劳）→ 质量、安全系数、寿命、违反项。"""
    import analysis

    out: dict = {"x": dict(x)}
    rho = mat["density_kg_m3"] * 1e-9  # kg/mm³
    if problem == "beam":
        L, b, F = float(spec["length_mm"]), float(spec["width_mm"]), float(spec["force_n"])
        h = x["h"]
        step = _step(lambda g: g.model.occ.addBox(0, -b / 2, -h / 2, L, b, h), "beam", tmp)
        faces = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]
        setup = {"step_path": step, "material": mat["id"], "mesh": {"size_mm": min(h, b) / spec.get("mesh_div", 4)},
                 "loads": [{"type": "fixed", "faces": _faces_at(faces, 0, 0)},
                           {"type": "force", "faces": _faces_at(faces, 0, L), "vector_n": [0, 0, -F]}]}
        out["mass_kg"] = L * b * h * rho
        load_ref = F
    else:
        segs = _segments(spec, x)
        total = sum(seg[1] for seg in segs)

        def build(g):
            z, tags = 0.0, []
            for d, length in segs:
                tags.append((3, g.model.occ.addCylinder(0, 0, z, 0, 0, length, d / 2)))
                z += length
            if len(tags) > 1:
                g.model.occ.fuse(tags[:1], tags[1:])
                g.model.occ.removeAllDuplicates()

        step = _step(build, "shaft", tmp)
        faces = analysis.run("fea", {"analysis": "faces", "step_path": step})["data"]["faces"]
        T = float(spec["torque_nm"])
        setup = {"step_path": step, "material": mat["id"], "mesh": {"size_mm": min(d for d, _ in segs) / spec.get("mesh_div", 4)},
                 "loads": [{"type": "fixed", "faces": _faces_at(faces, 2, 0)},
                           {"type": "torque", "faces": _faces_at(faces, 2, total), "value_nm": T,
                            "axis": {"origin": [0, 0, 0], "dir": [0, 0, 1]}}]}
        out["mass_kg"] = sum(math.pi * d * d / 4 * length for d, length in segs) * rho
        load_ref = T
    fea = analysis.run("fea", setup)
    if fea["status"] != "ok":
        return {**out, "ok": False, "violation": ["分析失败：" + "；".join(fea["messages"])[:120]], "sf": None}
    out["sf"], out["vm_max_mpa"] = fea["data"]["safety_factor"], fea["data"]["vm_max_mpa"]
    fat = cons.get("fatigue")
    if fat:
        fr = analysis.run("fatigue", {"material": mat["id"], "stress_ref_mpa": out["vm_max_mpa"], "load_ref": load_ref,
                                      "load_series": fat["load_series"], "block_seconds": fat.get("block_seconds", 1),
                                      "surface_factor": fat["surface_factor"], "size_factor": fat["size_factor"],
                                      "miner": fat.get("miner", "original")})
        if fr["status"] != "ok":
            raise OptError("疲劳设置有误：" + "；".join(fr["messages"]))
        out["life_infinite"] = fr["data"]["infinite"]
        out["life_hours"] = fr["data"]["life_hours"]
    v = []
    if cons.get("sf_min") is not None and out["sf"] < cons["sf_min"]:
        v.append(f"安全系数 {out['sf']:.2f} < {cons['sf_min']}")
    if fat and not out["life_infinite"]:
        need = fat.get("life", "infinite")
        if need == "infinite" or (out["life_hours"] or 0) < float(need):
            v.append("疲劳寿命不够")
    out["violation"], out["ok"] = v, not v
    return out


def _constraint_values(ev: dict, cons: dict) -> list[float]:
    """Optuna 约束：每项 ≤ 0 为满足。"""
    if ev.get("sf") is None:
        return [1.0]
    c = []
    if cons.get("sf_min") is not None:
        c.append(cons["sf_min"] - ev["sf"])
    if cons.get("fatigue"):
        c.append(0.0 if ev.get("ok") or "疲劳寿命不够" not in ev.get("violation", []) else 1.0)
    return c or [0.0]


def _check(setup: dict) -> tuple[str, dict, list[dict]]:
    problem = setup.get("problem")
    if problem not in ("beam", "shaft"):
        raise OptError("problem 须为 beam 或 shaft")
    spec = dict(setup.get(problem) or {})
    allowed = {"h"} if problem == "beam" else None
    vars_ = []
    for v in setup.get("vars") or []:
        name = v.get("name")
        if problem == "beam" and name not in allowed:
            raise OptError("悬臂梁只能优化 h")
        segs = v.get("segments") or ([int(name[1:])] if problem == "shaft" and str(name).startswith("d") else [])
        if problem == "shaft":
            n = len(spec.get("segments") or [])
            if not segs or any(not 0 <= i < n for i in segs):
                raise OptError(f"变量 {name} 的段号不对（共 {n} 段）")
        lo, hi = float(v["low"]), float(v["high"])
        if not 0 < lo <= hi:
            raise OptError(f"变量 {name} 的范围不对")
        vars_.append({"name": name, "segments": segs, "low": lo, "high": hi, "step": float(v.get("step", 0.5))})
    if not vars_:
        raise OptError("至少要优化一个尺寸")
    spec["_vars"] = vars_
    return problem, spec, vars_


def _base(problem: str, spec: dict, vars_: list[dict]) -> dict:
    if problem == "beam":
        return {"h": float(spec["height_mm"])} if "height_mm" in spec else {}
    return {v["name"]: float(spec["segments"][v["segments"][0]][0]) for v in vars_}


def run(setup: dict) -> dict:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    t0 = time.time()
    try:
        problem, spec, vars_ = _check(setup)
        mat = materials.get(setup.get("material", ""))
        materials.require(mat, ["elastic_modulus_mpa", "poisson_ratio", "density_kg_m3"], "设计优化")
        cons = dict(setup.get("constraints") or {})
        n_trials = max(2, min(int(setup.get("n_trials", 20)), MAX_TRIALS))
        limit = float(setup.get("time_limit_s", 900))
    except (OptError, materials.MissingData, KeyError, TypeError, ValueError) as exc:
        return result.failed("optimize", MODULE["version"], setup, f"设置有误：{exc}")
    rows: list[dict] = []
    cache: dict = {}
    with tempfile.TemporaryDirectory(prefix="fap-opt-") as tmpdir:
        tmp = Path(tmpdir)

        def objective(trial):
            x = {}
            for v in vars_:
                x[v["name"]] = v["low"] if v["high"] - v["low"] < 1e-9 else trial.suggest_float(
                    v["name"], v["low"], v["high"], step=v["step"])
            key = tuple(sorted(x.items()))
            if key not in cache:
                cache[key] = evaluate(problem, spec, x, mat, cons, tmp)
            ev = cache[key]
            cv = _constraint_values(ev, cons)
            trial.set_user_attr("c", cv)
            if hasattr(trial, "set_constraint"):  # Optuna 5：约束记在试验上
                for i, c in enumerate(cv):
                    trial.set_constraint(f"c{i}", float(c))
            rows.append({**ev, "trial": trial.number, "base": trial.number == 0 and bool(_base(problem, spec, vars_))})
            return ev["mass_kg"]

        kw = {} if hasattr(optuna.trial.Trial, "set_constraint") else {"constraints_func": lambda t: t.user_attrs["c"]}
        sampler = optuna.samplers.TPESampler(seed=int(setup.get("seed", 1)), n_startup_trials=min(6, n_trials // 3 + 1),
                                             **kw)
        study = optuna.create_study(direction="minimize", sampler=sampler)
        base = _base(problem, spec, vars_)
        if base:
            study.enqueue_trial(base)
        try:
            for _ in range(n_trials):
                if time.time() - t0 > limit:
                    break
                study.optimize(objective, n_trials=1)
        except OptError as exc:
            return result.failed("optimize", MODULE["version"], setup, str(exc))
    ok = sorted((r for r in rows if r["ok"]), key=lambda r: r["mass_kg"])
    seen, best = set(), []
    for r in ok:
        k = tuple(sorted(r["x"].items()))
        if k not in seen:
            seen.add(k)
            best.append(r)
    data = {"problem": problem, "trials": rows, "best": best[:5], "base": rows[0] if rows and rows[0]["base"] else None}
    msgs = [] if best else ["没有找到满足要求的尺寸：放宽范围或要求后再试"]
    return result.make("optimize", MODULE["version"], setup, data, limitations=LIMITS, messages=msgs,
                       solver={"name": "Optuna + CalculiX", "version": optuna.__version__}, elapsed_s=time.time() - t0)
