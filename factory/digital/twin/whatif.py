# -*- coding: utf-8 -*-
"""假如分析（第 15 轮 T5）：拿最近 30 个现场日的实测工况（转矩分布、雨流计数、环境温度），改一个条件重算消耗速度和油温，
换算成剩余寿命。降载按比例缩放转矩；加风扇把散热系数从 17.45 提到 31（濮良贵：轴端装风扇约 31–38；第 16 轮起有箱体风扇冷却的流体分析结果时改用它算出的值）；换材料用材料库的 S-N。"""
from twin import engine as E
from twin import models as M

MATS = {"45-QT": "45 钢调质（现行）", "40Cr-QT": "40Cr 调质"}
K_FAN = 31.0


def _mat(mid):
    from cae import materials as MAT
    m = MAT.get(mid)
    return {"sigma_1": m["sigma_1"], "N_D": m["N_D"], "k": m["k"], "ultimate_mpa": m["ultimate_mpa"]}


def rates(logs, design=None, load=1.0, k_s=M.K_S, mat="45-QT"):
    """返回每个现场日的消耗速度和平均油温"""
    days = sum(r.get("period_h", 24) for r in logs) / 24 or 1
    m = _mat(mat)
    brg = {b[0]: 0.0 for b in M.BEARINGS}
    shaft = oil_eq = run = oil_sum = 0.0
    for r in logs:
        n_in = r.get("n_in_rpm") or M.N_IN_RPM
        for k, v in M.bearing_damage([[t * load, h] for t, h in r.get("load_hist") or []], n_in, design).items():
            brg[k] += v
        shaft += M.shaft_damage([[a * load, mm * load, n] for a, mm, n in r.get("rainflow") or []], design, m)
        if r.get("run_h") and r.get("torque_mean_nm") is not None:
            # 实测油温里含“模型没算到的部分”（残差），按原样保留
            t_oil = M.oil_temp_model(r["torque_mean_nm"] * load, r["t_amb_c"], n_in, k_s) + (r.get("resid_c") or 0)
            oil_eq += M.oil_equiv_hours(r["run_h"], t_oil)
            run += r["run_h"]
            oil_sum += t_oil * r["run_h"]
    return {"brg": {k: v / days for k, v in brg.items()}, "shaft": shaft / days, "oil_eq_per_day": oil_eq / days,
            "oil_t_c": oil_sum / run if run else None}


def compare(state, logs, design=None, load=1.0, fan=False, mat="45-QT", k_fan=K_FAN):
    """现状 vs 假如：剩余天数（最先到期的轴承、输出轴）、换油间隔天数、平均油温"""
    logs = [r for r in logs if r.get("load_hist") is not None][-30:]
    base = rates(logs, design)
    alt = rates(logs, design, load, k_fan if fan else M.K_S, mat)

    def life(rt):
        b = {k: E._remaining_days(state["brg_D"].get(k, 0.0), v) for k, v in rt["brg"].items()}
        worst = min(b, key=b.get)
        due = M.OIL_INTERVAL_H
        return {"bearing": worst, "bearing_days": b[worst], "shaft_days": E._remaining_days(state["shaft_D"], rt["shaft"]),
                "oil_interval_days": due / rt["oil_eq_per_day"] if rt["oil_eq_per_day"] else None, "oil_t_c": rt["oil_t_c"]}
    out = {"base": life(base), "alt": life(alt), "load": load, "fan": fan, "fan_k": k_fan, "mat": mat, "days": len(logs)}
    for k in ("base", "alt"):
        for f in ("bearing_days", "shaft_days"):
            if out[k][f] == float("inf"):
                out[k][f] = None
    return out
