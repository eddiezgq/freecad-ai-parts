# -*- coding: utf-8 -*-
"""孪生的状态更新（第 15 轮 T3）：每收到一条运行摘要，累加寿命消耗、算模型油温和残差，记一行日志。纯函数，不碰数据库。

状态 state：
  run_h、starts、days、shaft_D（输出轴 Miner 损伤）、brg_D{轴承: L10 分数}、oil_eq_h（本次换油后的当量小时）、
  oil_first_done（磨合后首次换油做过没有）、resid（油温残差的指数平均）、window（最近 30 个现场日的消耗，算剩余寿命）、
  vib（最近 21 条振动：[日期, mm/s]）、last（最近一条摘要）、torque_max（见过的最大转矩）
"""
import datetime as dt
import math

from twin import models as M

WINDOW_DAYS = 30
EWMA = 0.5


def new_state():
    return {"run_h": 0.0, "starts": 0, "days": 0, "shaft_D": 0.0, "brg_D": {b[0]: 0.0 for b in M.BEARINGS},
            "oil_eq_h": 0.0, "oil_first_done": False, "resid": None, "window": [], "vib": [], "last": None,
            "torque_max": 0.0, "first_day": None, "last_day": None, "maint": []}


def update(state, t, design=None):
    """t：一条运行摘要（twin.telemetry 的 data）。返回 (新状态, 日志行)"""
    s = dict(state)
    s["brg_D"] = dict(state["brg_D"])
    days = t.get("period_h", 24) / 24
    run_h = float(t.get("run_h") or 0)
    n_in = float(t.get("n_in_rpm") or M.N_IN_RPM)
    ds = M.shaft_damage(t.get("rainflow") or [], design)
    db = M.bearing_damage(t.get("load_hist") or [], n_in, design)
    for k, v in db.items():
        s["brg_D"][k] = s["brg_D"].get(k, 0.0) + v
    s["shaft_D"] += ds
    s["run_h"] += run_h
    s["starts"] += int(t.get("starts") or 0)
    s["days"] += days
    s["first_day"] = s["first_day"] or t["day"]
    s["last_day"] = t["day"]
    row = {"day": t["day"], "period_h": t.get("period_h", 24), "run_h": run_h, "starts": t.get("starts", 0),
           "t_amb_c": t.get("t_amb_c"), "torque_mean_nm": t.get("torque_mean_nm"), "torque_max_nm": t.get("torque_max_nm"),
           "oil_t_c": t.get("oil_t_c"), "oil_t_max_c": t.get("oil_t_max_c"), "vib_mm_s": t.get("vib_mm_s"),
           "n_in_rpm": n_in, "d_shaft": ds, "d_brg": db,
           "rainflow": t.get("rainflow") or [], "load_hist": t.get("load_hist") or []}
    if run_h > 0 and t.get("torque_mean_nm") is not None and t.get("oil_t_c") is not None:
        model = M.oil_temp_model(t["torque_mean_nm"], t["t_amb_c"], n_in)
        r = t["oil_t_c"] - model
        s["resid"] = r if s["resid"] is None else EWMA * r + (1 - EWMA) * s["resid"]
        row.update(oil_model_c=round(model, 1), resid_c=round(r, 2), resid_ewma=round(s["resid"], 2))
        s["oil_eq_h"] += M.oil_equiv_hours(run_h, t["oil_t_c"])
    if t.get("vib_mm_s") is not None and run_h > 0:
        s["vib"] = (state["vib"] + [[t["day"], t["vib_mm_s"]]])[-21:]
        row["vib_zone"] = M.vib_zone(t["vib_mm_s"])
    s["torque_max"] = max(state["torque_max"], float(t.get("torque_max_nm") or 0))
    s["window"] = (state["window"] + [[t["day"], days, run_h, ds, max(db.values()) if db else 0.0, db]])
    cut = dt.date.fromisoformat(t["day"]) - dt.timedelta(days=WINDOW_DAYS)
    s["window"] = [w for w in s["window"] if dt.date.fromisoformat(w[0]) > cut]
    s["last"] = {k: t.get(k) for k in ("day", "run_h", "starts", "torque_mean_nm", "torque_max_nm", "t_amb_c", "oil_t_c",
                                       "oil_t_max_c", "vib_mm_s", "n_in_rpm", "site", "customer")}
    return s, row


def maintain(state, action, day):
    """维修完成回写（T6）：换油 / 换轴承 / 清洁散热"""
    s = dict(state)
    s["brg_D"] = dict(state["brg_D"])
    if action == "oil":
        s["oil_eq_h"] = 0.0
        s["oil_first_done"] = True
    elif action.startswith("bearing"):
        bid = action.split(":", 1)[1] if ":" in action else None
        for k in s["brg_D"]:
            if bid in (None, k):
                s["brg_D"][k] = 0.0
        s["vib"] = []
    elif action == "cooling":
        s["resid"] = 0.0
    s["maint"] = (state.get("maint") or []) + [[day, action]]
    return s


def _remaining_days(D, rate_per_day):
    if D >= 1:
        return 0.0
    if rate_per_day <= 0:
        return math.inf
    return (1 - D) / rate_per_day


def summary(state, as_built=None):
    """剩余寿命、换油、健康度（页面和诊断用）"""
    w = state.get("window") or []
    span = sum(x[1] for x in w) or 0.0
    run = sum(x[2] for x in w)
    rs = sum(x[3] for x in w) / span if span else 0.0
    rb = {}
    for x in w:
        for k, v in (x[5] or {}).items():
            rb[k] = rb.get(k, 0.0) + v
    rb = {k: v / span for k, v in rb.items()} if span else {}
    hours_per_day = run / span if span else 0.0
    brg = []
    for bid, name, model, C, shaft in M.BEARINGS:
        D = state["brg_D"].get(bid, 0.0)
        rem = _remaining_days(D, rb.get(bid, 0.0))
        brg.append({"id": bid, "name": name, "model": model, "C_n": C, "used": D, "remaining_days": None if math.isinf(rem) else rem})
    worst = max(brg, key=lambda b: b["used"])
    rem_s = _remaining_days(state["shaft_D"], rs)
    due = M.OIL_INTERVAL_H if state.get("oil_first_done") else M.OIL_FIRST_H
    oil_left = due - state.get("oil_eq_h", 0.0)
    oil_days = (oil_left / hours_per_day) if hours_per_day > 0 and oil_left > 0 else (0.0 if oil_left <= 0 else None)
    vib = state.get("vib") or []
    return {"shaft": {"used": state["shaft_D"], "remaining_days": None if math.isinf(rem_s) else rem_s},
            "bearings": brg, "worst_bearing": worst,
            "oil": {"eq_h": state.get("oil_eq_h", 0.0), "due_h": due, "left_h": oil_left, "days": oil_days},
            "hours_per_day": hours_per_day, "resid_c": state.get("resid"),
            "vib": vib[-1][1] if vib else None, "vib_zone": M.vib_zone(vib[-1][1]) if vib else None}
