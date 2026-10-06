# -*- coding: utf-8 -*-
"""设计优化（第 14 轮 H4、H5）：Optuna（MIT，TPE 贝叶斯优化，支持约束和多目标）驱动有限元 / 温度场，每次评估就是一次真实分析。

问题 spec = {
  "problem": "shaft" | "housing" | "heatsink" | "beam",
  "base": {...}              # 现行参数（SH-301 设计台参数、示例零件参数）
  "vars": [{"name": "d_gear", "low": 36, "high": 46, "step": 0.5}, ...],    # 只能从该问题的 VARS 里选
  "objectives": ["mass"] 或 ["mass", "t_max"]（两个目标 → 帕累托前沿）,
  "constraints": {"sf_min": 1.5, "life": "infinite" 或 小时数, "t_max": 80},
  "material_id": "45-QT", "n_trials": 30（≤ 60）, "time_limit_s": 900, "mesh_div": 24
}
每次评估返回：mass_kg、sf、life_h（或 inf）、t_max、是否满足约束、违反量。第一次评估固定是现行设计，便于对比。"""
import copy
import math
import time

import numpy as np

MAX_TRIALS = 60
OBJ = {"mass": ("质量", "kg", "min"), "t_max": ("最高温度", "℃", "min"), "sf": ("安全系数", "", "max")}

# 各问题可优化的变量：名字 → (说明, 默认下限, 默认上限, 步长, 取值是否整数)
VARS = {
    "shaft": {"d_gear": ("齿轮位直径 mm", 36.0, 46.0, 0.5, False), "d_end": ("两端轴伸直径 mm", 26.0, 33.0, 0.5, False)},
    # 轴承位 Ø35 由轴承 6207 定死，不参加优化
    "housing": {"fins": ("每侧散热筋数", 0, 12, 1, True), "fin_h": ("散热筋高 mm", 10.0, 40.0, 2.5, False),
                "wall": ("壁厚 mm", 8.0, 14.0, 1.0, False)},
    "heatsink": {"fins": ("散热片数", 5, 20, 1, True), "fin_h": ("片高 mm", 15.0, 45.0, 2.5, False),
                 "fin_t": ("片厚 mm", 1.0, 3.0, 0.25, False)},
    "beam": {"h": ("截面高 mm", 10.0, 30.0, 0.1, False)},
}
LABELS = {"shaft": "输出轴 SH-301（扭矩 350 N·m，强度 + 疲劳）", "housing": "WQR-105 简化箱体（热平衡）",
          "heatsink": "CPU 散热片", "beam": "悬臂梁（标准题：定强度最轻截面）"}
DEFAULT_SPEC = {
    "shaft": {"vars": ["d_gear", "d_end"], "objectives": ["mass"], "constraints": {"sf_min": 1.3, "life": "infinite"}, "material_id": "45-QT"},
    "housing": {"vars": ["fins", "fin_h"], "objectives": ["mass", "t_max"], "constraints": {"t_max": 80}, "material_id": "HT200"},
    "heatsink": {"vars": ["fins", "fin_h", "fin_t"], "objectives": ["mass"], "constraints": {"t_max": 85}, "material_id": "6061-T6"},
    "beam": {"vars": ["h"], "objectives": ["mass"], "constraints": {"sf_min": 2.0}, "material_id": "45-QT"},
}
BEAM = {"L": 200.0, "b": 20.0, "h": 25.0, "F": 1000.0}


# ---------------------------------------------------------------- 各问题：参数 → 几何 → 分析
def _shaft_params(base, x):
    p = copy.deepcopy(base)
    segs = [list(s) for s in p["segments"]]
    if "d_gear" in x:
        segs[2][0] = x["d_gear"]
    if "d_end" in x:
        segs[0][0] = segs[4][0] = x["d_end"]
    p["segments"] = [tuple(s) for s in segs]
    return p


def _shaft_mass_mm3(p):
    v = sum(math.pi * d * d / 4 * l for d, l in p["segments"])
    kw = p.get("keyway")
    if kw:
        v -= kw["b"] * kw["t"] * (kw["L"] - kw["b"]) + math.pi * kw["b"] ** 2 / 4 * kw["t"]
    c = p.get("chamfer") or 0
    for d in (p["segments"][0][0], p["segments"][-1][0]):
        v -= math.pi * d * c * c / 2                          # 倒角去掉的小三角环（近似）
    return v


def _shaft_setup(faces, p):
    d_brg = p["segments"][1][0] / 2
    d_end = p["segments"][4][0] / 2
    brg = sorted([f for f in faces if f.get("radius_mm") and abs(f["radius_mm"] - d_brg) < 1e-3 and abs(f["axis"][2]) > 0.99],
                 key=lambda f: f["center"][2])
    out = sorted([f for f in faces if f.get("radius_mm") and abs(f["radius_mm"] - d_end) < 1e-3 and abs(f["axis"][2]) > 0.99],
                 key=lambda f: -f["center"][2])
    wall = [f for f in faces if f["kind"] == "plane" and f.get("normal") and abs(abs(f["normal"][0]) - 1) < 1e-3]
    if len(brg) < 2 or not out or not wall:
        raise ValueError("找不到轴承位、轴伸或键槽侧面")
    ax = {"origin": [0, 0, 0], "dir": [0, 0, 1]}
    return [{"type": "cyl_support", "faces": [brg[0]["id"]], "axis": ax, "dofs": ["radial", "axial"]},
            {"type": "cyl_support", "faces": [brg[1]["id"]], "axis": ax, "dofs": ["radial"]},
            {"type": "cyl_support", "faces": [out[0]["id"]], "axis": ax, "dofs": ["tangential"]},
            {"type": "torque", "faces": [wall[0]["id"]], "value_nmm": 350e3, "axis": ax}]


def evaluate(problem, base, x, mat, cons, mesh_div=32):
    """一次评估：返回 dict（mass_kg, sf, life_h, t_max, ok, violation[], note）"""
    from cae import geometry as G
    t0 = time.time()
    out = {"x": x}
    if problem == "shaft":
        from hub import design as D
        p = _shaft_params(base, x)
        chk = D.check(p)
        if not chk["ok"]:
            return dict(out, ok=False, violation=["几何：" + "；".join(chk["errors"])], mass_kg=None, seconds=0)
        step = D.step_bytes(p)
        out["mass_kg"] = _shaft_mass_mm3(p) * mat["density"] * 1e-6
        faces = G.faces(step)[0]
        from cae import solve as S
        dm = max(d for d, _ in p["segments"])
        diag = math.sqrt(2 * dm * dm + sum(l for _, l in p["segments"]) ** 2)          # 同“仿真与分析”页：包围盒对角线 / 份数
        st, _, aux = S.solve(step, {"material": mat, "loads": _shaft_setup(faces, p), "mesh": {"size_mm": diag / mesh_div}})
        out["sf"] = st["safety_factor"]
        out["vm_max"] = st["vm_max_mpa"]
        if cons.get("life") is not None:
            from cae import fatigue as FT
            vm = np.array([v for v in aux["vm"].values() if v <= st["vm_max_mpa"] * 1.0001])      # 避开约束面奇异点（同静强度评估）
            _, fs = FT.compute(vm, 350.0, [350.0, 0.0], 1.0, mat, surface="ground", size_factor=0.85, kf=1.0, haibach=False)
            out["life_inf"] = bool(fs.get("infinite"))
            out["life_h"] = None if out["life_inf"] else float(fs["life_hours"])          # JSON 不能存无穷大
        out["warnings"] = chk["warnings"]
    elif problem == "beam":
        import build123d as bd
        from cae import solve as S
        from cae.thermal_parts import tempfile_step
        p = dict(BEAM, **x)
        step = tempfile_step(bd.Box(p["L"], p["b"], p["h"], align=(bd.Align.MIN, bd.Align.CENTER, bd.Align.CENTER)))
        faces = G.faces(step)[0]
        f0 = [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0]) < 1e-6]
        f1 = [f["id"] for f in faces if f["kind"] == "plane" and abs(f["center"][0] - p["L"]) < 1e-6]
        st, _, _ = S.solve(step, {"material": mat, "mesh": {"size_mm": min(p["h"], p["b"]) / 4},
                                  "loads": [{"type": "fixed", "faces": f0}, {"type": "force", "faces": f1, "vector_n": [0, 0, -p["F"]]}]})
        out["mass_kg"] = p["L"] * p["b"] * p["h"] * mat["density"] * 1e-6
        out["sf"], out["vm_max"] = st["safety_factor"], st["vm_max_mpa"]
    else:
        from cae import thermal as TH
        from cae import thermal_parts as TP
        p = TP.params_of(problem, dict(base, **x))
        step = TP.build(problem, p)
        faces = G.faces(step)[0]
        ex = TP.example(problem, p, faces)
        st, _, _ = TH.solve(step, {"material": mat, "thermal": ex["thermal"], "mesh": {"size_mm": ex["mesh_mm"]}})
        out["mass_kg"] = st["volume_mm3"] * mat["density"] * 1e-6
        out["t_max"] = st["t_max_c"]
    out["seconds"] = round(time.time() - t0, 1)
    v = []
    if cons.get("sf_min") is not None and out.get("sf") is not None and out["sf"] < cons["sf_min"]:
        v.append("安全系数 {:.2f} < {}".format(out["sf"], cons["sf_min"]))
    if cons.get("life") is not None and "life_inf" in out and not out["life_inf"]:
        if cons["life"] == "infinite" or out["life_h"] < float(cons["life"]):
            v.append("疲劳寿命 {:.3g} h 不够".format(out["life_h"]))
    if cons.get("t_max") is not None and out.get("t_max") is not None and out["t_max"] > cons["t_max"]:
        v.append("最高温度 {:.1f} ℃ > {}".format(out["t_max"], cons["t_max"]))
    out["violation"] = v
    out["ok"] = not v
    return out


def _cons_values(ev, cons):
    """Optuna 约束：每项 ≤ 0 为满足"""
    c = []
    if ev.get("mass_kg") is None:                              # 几何不合格
        return [1.0]
    if cons.get("sf_min") is not None:
        c.append(cons["sf_min"] - ev["sf"])
    if cons.get("life") is not None:
        need = 1e12 if cons["life"] == "infinite" else float(cons["life"])
        lh = 1e12 if ev.get("life_inf") else (ev.get("life_h") or 0)
        c.append(math.log10(need + 1) - math.log10(min(lh, 1e12) + 1))
    if cons.get("t_max") is not None:
        c.append(ev["t_max"] - cons["t_max"])
    return c or [0.0]


def base_values(problem, base, names):
    if problem == "shaft":
        segs = base["segments"]
        cur = {"d_gear": segs[2][0], "d_end": segs[4][0]}
    elif problem == "beam":
        cur = {"h": BEAM["h"]}
    else:
        from cae import thermal_parts as TP
        cur = TP.params_of(problem, base)
    return {n: cur[n] for n in names}


def run(spec, progress=None):
    """跑一次优化。progress(rows) 每完成一次评估回调一次（写进度文件）"""
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from cae import materials as M
    problem = spec["problem"]
    if problem not in VARS:
        raise ValueError("不认识的优化问题")
    mat = M.get(spec.get("material_id") or DEFAULT_SPEC[problem]["material_id"])
    base = spec.get("base") or ({} if problem != "shaft" else None)
    if problem == "shaft" and not base:
        from hub import design as D
        base = D.normalize(D.defaults())
    vars_ = []
    for v in spec.get("vars") or [{"name": n} for n in DEFAULT_SPEC[problem]["vars"]]:
        if v["name"] not in VARS[problem]:
            raise ValueError("这个问题不能优化 {}".format(v["name"]))
        lab, lo, hi, step, is_int = VARS[problem][v["name"]]
        lo, hi = float(v.get("low", lo)), float(v.get("high", hi))
        if hi < lo:
            raise ValueError("{} 的上限比下限小".format(lab))
        vars_.append({"name": v["name"], "label": lab, "low": lo, "high": hi, "step": float(v.get("step", step)), "int": is_int})
    objs = spec.get("objectives") or DEFAULT_SPEC[problem]["objectives"]
    for o in objs:
        if o not in OBJ:
            raise ValueError("不认识的目标 {}".format(o))
    cons = dict(spec.get("constraints") or DEFAULT_SPEC[problem]["constraints"])
    n_trials = max(4, min(int(spec.get("n_trials", 30)), MAX_TRIALS))
    t_limit = min(float(spec.get("time_limit_s", 900)), 900.0)
    mesh_div = int(spec.get("mesh_div", 32))
    cache, rows, t_start = {}, [], time.time()

    def fn(trial):
        x = {}
        for v in vars_:
            if v["int"]:
                x[v["name"]] = trial.suggest_int(v["name"], int(v["low"]), int(v["high"]), step=max(1, int(v["step"])))
            elif v["high"] - v["low"] < 1e-9:
                x[v["name"]] = v["low"]
            else:
                x[v["name"]] = trial.suggest_float(v["name"], v["low"], v["high"], step=v["step"])
        key = tuple(sorted(x.items()))
        if key in cache:
            ev = dict(cache[key], repeat=True)
        else:
            try:
                ev = evaluate(problem, base, x, mat, cons, mesh_div)
            except Exception as e:  # noqa: BLE001 —— 网格失败、几何冲突：记为不可行
                ev = {"x": x, "ok": False, "violation": ["分析失败：{}".format(str(e)[:80])], "mass_kg": None, "seconds": 0}
            cache[key] = ev
        cv = _cons_values(ev, cons)
        trial.set_user_attr("c", cv)
        if hasattr(trial, "set_constraint"):                    # Optuna 5：约束直接记在试验上
            for i, c in enumerate(cv):
                trial.set_constraint("c{}".format(i), float(c))
        rows.append(dict(ev, trial=trial.number, base=trial.number == 0))
        if progress:
            progress(rows)
        vals = []
        for o in objs:
            val = ev.get({"mass": "mass_kg", "t_max": "t_max", "sf": "sf"}[o])
            vals.append(1e9 if val is None else (-val if OBJ[o][2] == "max" else val))
        return vals[0] if len(vals) == 1 else tuple(vals)

    kw = {} if hasattr(optuna.trial.Trial, "set_constraint") else {"constraints_func": lambda t: t.user_attrs["c"]}
    sampler = optuna.samplers.TPESampler(seed=int(spec.get("seed", 1)), n_startup_trials=min(8, n_trials // 3 + 1),
                                         multivariate=True, **kw)
    study = optuna.create_study(directions=["minimize"] * len(objs), sampler=sampler)
    study.enqueue_trial(base_values(problem, base, [v["name"] for v in vars_ if v["high"] - v["low"] >= 1e-9]))
    deadline = t_start + t_limit
    for _ in range(n_trials):
        if time.time() > deadline:
            break
        study.optimize(fn, n_trials=1)
    ok = [r for r in rows if r["ok"] and not r.get("repeat")]
    res = {"problem": problem, "vars": vars_, "objectives": objs, "constraints": cons, "material_id": mat["id"],
           "trials": rows, "seconds": round(time.time() - t_start, 1), "base": rows[0] if rows else None}
    if len(objs) == 1:
        o = objs[0]
        key = {"mass": "mass_kg", "t_max": "t_max", "sf": "sf"}[o]
        best = sorted(ok, key=lambda r: r[key] * (-1 if OBJ[o][2] == "max" else 1))
        res["best"] = best[:5]
    else:
        keys = [{"mass": "mass_kg", "t_max": "t_max", "sf": "sf"}[o] for o in objs]
        sg = [(-1 if OBJ[o][2] == "max" else 1) for o in objs]
        pts = [(r, [r[k] * s for k, s in zip(keys, sg)]) for r in ok]
        front = [r for r, a in pts if not any(all(bb <= aa for aa, bb in zip(a, b)) and any(bb < aa for aa, bb in zip(a, b)) for _, b in pts)]
        res["pareto"] = sorted(front, key=lambda r: r[keys[0]])
        res["best"] = res["pareto"][:5]
    return res
