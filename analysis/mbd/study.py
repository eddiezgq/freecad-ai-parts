"""多体动力学参数研究（ADR-0097 D7b，补充十九）：扫描、试验设计、优化。每次评估都是一次真实的多体计算。"""

from __future__ import annotations

import copy
import itertools
import math
import time

import numpy as np

from analysis.mbd.dae.expr import ExprError, compile_expr

PENALTY = 1e6
MAX_EVAL = 300


class StudyError(ValueError):
    pass


# ---------------------------------------------------------------- 指标
def series(data: dict, path: str):
    """结果里的点号路径 → 数组（如 measures.th.values、motions.m.effort、actuators.motor、joints.J1.force_n.0）"""
    cur = data
    parts = path.split(".")
    for k, p in enumerate(parts):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        elif isinstance(cur, list) and p.isdigit() and cur and isinstance(cur[0], list):
            cur = [row[int(p)] for row in cur]           # 每个时刻的第几个分量
        else:
            raise StudyError(f"结果里没有 {'.'.join(parts[:k + 1])}")
    arr = np.asarray(cur, float)
    if arr.ndim == 2:                                     # 向量序列取大小
        arr = np.linalg.norm(arr, axis=1)
    return arr


def metric(data: dict, m: dict) -> float:
    if m["kind"] == "frequency":
        lin = data.get("linear")
        if not lin:
            raise StudyError(f"指标 {m['id']}：frequency 要用线性化分析")
        fs = sorted(x["frequency_hz"] for x in lin["modes"] if x["frequency_hz"] > 1e-6)
        n = m.get("mode", 1)
        if len(fs) < n:
            raise StudyError(f"指标 {m['id']}：只有 {len(fs)} 阶非零频率")
        return float(fs[n - 1])
    if "series" not in m:
        raise StudyError(f"指标 {m['id']}：要写 series")
    y = series(data, m["series"])
    t = np.asarray(data["times_s"], float)
    if len(y) != len(t):
        raise StudyError(f"指标 {m['id']}：{m['series']} 不是时间序列")
    sel = t >= m.get("from_time_s", -math.inf)
    t, y = t[sel], y[sel]
    k = m["kind"]
    if k == "max":
        return float(y.max())
    if k == "min":
        return float(y.min())
    if k == "peak_abs":
        return float(np.abs(y).max())
    if k == "final":
        return float(y[-1])
    if k == "mean":
        return float(np.trapezoid(y, t) / (t[-1] - t[0])) if len(t) > 1 else float(y[0])
    if k == "rms":
        return float(math.sqrt(np.trapezoid(y * y, t) / (t[-1] - t[0]))) if len(t) > 1 else float(abs(y[0]))
    if k == "ise":
        try:
            ref = compile_expr(m["reference"])
        except (KeyError, ExprError) as exc:
            raise StudyError(f"指标 {m['id']}：ise 要写 reference 表达式") from exc
        e = np.array([ref(tt) for tt in t]) - y
        return float(np.trapezoid(e * e, t))
    raise StudyError(f"不认识的指标 {k}")


# ---------------------------------------------------------------- 变量与取样
def _pointer_set(model, path, value):
    cur = model
    parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
    for p in parts[:-1]:
        cur = cur[int(p)] if isinstance(cur, list) else cur[p]
    last = parts[-1]
    if isinstance(cur, list):
        cur[int(last)] = value
    else:
        if last not in cur:
            raise StudyError(f"模型里没有 {path}")
        cur[last] = value


def _scale(v, u):
    if v.get("log"):
        return math.exp(math.log(v["low"]) + u * (math.log(v["high"]) - math.log(v["low"])))
    return v["low"] + u * (v["high"] - v["low"])


def _unscale(v, x):
    if v.get("log"):
        return (math.log(x) - math.log(v["low"])) / (math.log(v["high"]) - math.log(v["low"]))
    return (x - v["low"]) / (v["high"] - v["low"])


def grid(variables):
    axes = [[_scale(v, u) for u in np.linspace(0, 1, v.get("levels", 5))] for v in variables]
    return [dict(zip([v["name"] for v in variables], combo, strict=True)) for combo in itertools.product(*axes)]


def latin_hypercube(variables, n, seed=0):
    rng = np.random.default_rng(seed)
    cols = []
    for _ in variables:
        cols.append((rng.permutation(n) + rng.random(n)) / n)
    return [{v["name"]: _scale(v, float(cols[j][i])) for j, v in enumerate(variables)} for i in range(n)]


# ---------------------------------------------------------------- 运行
def check(study: dict):
    from kb.validation import errors

    errs = errors("mbd-study.schema.json", study)
    if errs:
        raise StudyError("研究设置不符合 schema：" + "；".join(errs[:5]))
    errs = errors("mbd-model.schema.json", study["model"])
    if errs:
        raise StudyError("模型不符合 schema：" + "；".join(errs[:5]))
    ids = {m["id"] for m in study["metrics"]}
    if study.get("objective") and study["objective"]["metric"] not in ids:
        raise StudyError(f"目标指标 {study['objective']['metric']} 不在 metrics 里")
    for c in study.get("constraints") or []:
        if c["metric"] not in ids:
            raise StudyError(f"约束指标 {c['metric']} 不在 metrics 里")
    for v in study["variables"]:
        if v["low"] >= v["high"]:
            raise StudyError(f"变量 {v['name']}：low 要小于 high")
        if v.get("log") and v["low"] <= 0:
            raise StudyError(f"变量 {v['name']}：按对数取值时 low 要大于 0")
        _pointer_set(copy.deepcopy(study["model"]), v["path"], v["low"])
    if study["method"] == "optimize" and not study.get("objective"):
        raise StudyError("优化要写 objective")


def evaluate(study, x, base_dir=None):
    from analysis.mbd.dae.run import run_model

    model = copy.deepcopy(study["model"])
    for v in study["variables"]:
        _pointer_set(model, v["path"], float(x[v["name"]]))
    t0 = time.time()
    try:
        data, _ = run_model(model, base_dir)
        vals = {m["id"]: metric(data, m) for m in study["metrics"]}
    except Exception as exc:  # noqa: BLE001 — 单次评估失败记下原因，不中断整个研究
        return {"variables": dict(x), "metrics": None, "feasible": False, "error": str(exc), "elapsed_s": time.time() - t0}
    viol = []
    for c in study.get("constraints") or []:
        val = vals[c["metric"]]
        if "max" in c and val > c["max"]:
            viol.append(f"{c['metric']} = {val:.4g} > {c['max']}")
        if "min" in c and val < c["min"]:
            viol.append(f"{c['metric']} = {val:.4g} < {c['min']}")
    return {"variables": dict(x), "metrics": vals, "feasible": not viol, "violations": viol, "error": None,
            "elapsed_s": time.time() - t0}


def _score(study, ev):
    """优化用的目标值（越小越好）：违反约束加罚"""
    if ev["metrics"] is None:
        return PENALTY * 10
    obj = study["objective"]
    val = ev["metrics"][obj["metric"]]
    val = -val if obj.get("sense") == "maximize" else val
    pen = 0.0
    for c in study.get("constraints") or []:
        m = ev["metrics"][c["metric"]]
        scale = max(abs(c.get("max", c.get("min", 1.0))), 1e-12)
        if "max" in c and m > c["max"]:
            pen += (m - c["max"]) / scale
        if "min" in c and m < c["min"]:
            pen += (c["min"] - m) / scale
    return val + PENALTY * pen


def run(study: dict, base_dir=None) -> dict:
    check(study)
    t0 = time.time()
    vs = study["variables"]
    method = study["method"]
    evals = []
    if method == "grid":
        pts = grid(vs)
        if len(pts) > MAX_EVAL:
            raise StudyError(f"网格 {len(pts)} 个点，超过 {MAX_EVAL}：减少档数")
        evals = [evaluate(study, x, base_dir) for x in pts]
    elif method == "latin_hypercube":
        n = study.get("samples", 10 * len(vs))
        evals = [evaluate(study, x, base_dir) for x in latin_hypercube(vs, n, study.get("seed", 0))]
    else:
        opt = study.get("optimizer") or {}
        nmax = min(opt.get("max_evaluations", 60), MAX_EVAL)
        algo = opt.get("algorithm", "nelder_mead")
        names = [v["name"] for v in vs]
        if algo == "nelder_mead":
            from scipy.optimize import minimize

            x0 = opt.get("x0") or {}
            u0 = [min(max(_unscale(v, x0[v["name"]]), 0.0), 1.0) if v["name"] in x0 else 0.5 for v in vs]

            def f(u):
                if len(evals) >= nmax:
                    raise _Stop
                x = {n_: _scale(v, float(min(max(ui, 0.0), 1.0))) for n_, v, ui in zip(names, vs, u, strict=True)}
                ev = evaluate(study, x, base_dir)
                evals.append(ev)
                return _score(study, ev)

            try:
                minimize(f, u0, method="Nelder-Mead", bounds=[(0, 1)] * len(vs),
                         options={"maxfev": nmax, "xatol": 1e-4, "fatol": 1e-10, "initial_simplex": _simplex(u0)})
            except _Stop:
                pass
        else:
            try:
                import optuna
            except ImportError as exc:
                raise StudyError("TPE 要装 optuna：pip install -e \".[optimize]\"") from exc
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            sampler = optuna.samplers.TPESampler(seed=study.get("seed", 0))
            st = optuna.create_study(direction="minimize", sampler=sampler)

            def obj(trial):
                x = {v["name"]: trial.suggest_float(v["name"], v["low"], v["high"], log=bool(v.get("log"))) for v in vs}
                ev = evaluate(study, x, base_dir)
                evals.append(ev)
                return _score(study, ev)

            st.optimize(obj, n_trials=nmax)
    ok = [e for e in evals if e["metrics"] is not None and e["feasible"]]
    best = []
    if study.get("objective") and ok:
        sgn = -1 if study["objective"].get("sense") == "maximize" else 1
        best = sorted(ok, key=lambda e: sgn * e["metrics"][study["objective"]["metric"]])[:5]
    return {"name": study["name"], "method": method, "evaluations": evals, "best": best,
            "n_failed": sum(1 for e in evals if e["metrics"] is None), "elapsed_s": time.time() - t0}


class _Stop(Exception):
    pass


def _simplex(u0):
    n = len(u0)
    s = [list(u0)]
    for i in range(n):
        p = list(u0)
        p[i] = p[i] + 0.25 if p[i] <= 0.5 else p[i] - 0.25
        s.append(p)
    return np.array(s)
