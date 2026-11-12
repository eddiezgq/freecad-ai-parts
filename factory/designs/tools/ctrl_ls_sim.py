# -*- coding: utf-8 -*-
"""第 159 轮 159c：平缝机控制器 CTRL-LS 的系统级仿真复核（电路级的 ngspice 核对在 eda/wqeda/sim_ctrl.py，进计算书）。

    python3 factory/designs/tools/ctrl_ls_sim.py        # 写到 docs/设计/WQ-LS/GC/控制器仿真/

① 主轴伺服复算：用第 138 轮 tools/wqls/gc_sim.py 的模型（不改它），把力矩限幅换成本控制器能给的
   T_限 = K_t × I_限（K_t 由“5000 r/min 线反电势峰值 ≤ 300 V”推出，I_限 = 峰值力矩对应的相电流），重跑一个工作周期；
   再把力矩换成相电流，按计算书同一套式子算功率模块在这个周期里的平均损耗，并核对电压余量。
② 电控箱温度：第 62 轮的缝纫机电控箱模型（铝外壳兼散热器，功率器件贴顶板里面，CalculiX 稳态热分析），
   发热取计算书算出的损耗：最坏工况（90 V 输入、550 W 连续）与典型缝纫（230 V 输入、第 138 轮一转平均力矩）两种。

只启动本机求解器（CalculiX），不联网、不调 AI。"""

from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "设计" / "WQ-LS" / "GC" / "控制器仿真"
DESIGN = ROOT / "factory" / "designs" / "ctrl-ls" / "design.yaml"
sys.path.insert(0, str(ROOT / "eda"))
sys.path.insert(0, str(ROOT / "factory" / "digital"))
sys.path.insert(0, str(ROOT / "tools" / "wqls"))

from wqeda import blocks, parts  # noqa: E402
from wqeda.blocks import servo  # noqa: E402
from wqeda.schema import design  # noqa: E402


def losses(doc, dev):
    """计算书同一套计算器跑一遍（与 blocks.calculate 相同的顺序），取各块记下的、装在散热器上的损耗"""
    d = {"derating": doc["spec"]["derating"], "devices": dev}
    hs = {}
    for u in blocks.units(doc):
        items, _ = blocks.CALCULATORS[u["type"]](u, doc["spec"], d, [])
        if u["type"] == "heatsink":
            hs = {i["key"]: i["value"] for i in items}
    fly = unit(doc, "flyback_aux")
    p_out = sum(o["v"] * o["i"] for o in fly["outputs"])
    L = d.get("losses", {})
    return {
        "heatsink_w": round(sum(x["p"] for x in L.values()), 2),
        "by_part": {x["name"]: round(x["p"], 2) for x in L.values()},
        "aux_loss_w": round(p_out / fly["eta"] - p_out, 2),
        # 箱内底板的发热：反激自身损耗 + 15 V、5 V 两路输出（功率模块驱动、校正控制器、主控都在箱内，电全变成热）；
        # 24 V 主要供箱外的电磁铁、步进电机，不计
        "aux_in_box_w": round(
            p_out / fly["eta"] - p_out + sum(o["v"] * o["i"] for o in fly["outputs"] if o["v"] < 24), 2
        ),
        "r_sa_need": hs.get("r_sa"),
        "ts_allow_c": min(v for k, v in hs.items() if k.startswith("ts")),
    }


def unit(doc, t):
    return next(u for u in blocks.units(doc) if u["type"] == t)["params"]


def typical(doc):
    """典型缝纫：230 V 输入；电机功率按第 138 轮一转平均力矩 0.122 N·m × 5000 r/min"""
    d2 = copy.deepcopy(doc)
    s = d2["spec"]
    s["vin_min_vac"] = 230.0
    s["motor_power_w"] = 0.122 * 5000 * 2 * math.pi / 60
    return d2


def servo_cycle(spec, dev):
    import gc_sim
    import numpy as np

    mo = servo.motor(spec)
    i_lim = spec["torque_peak_nm"] / mo["kt"]
    gc_sim.T_PEAK = mo["kt"] * i_lim  # 本控制器的力矩限幅（第 138 轮按 3.2 N·m）
    t_trim = 0.62 + 60 / 300 * 1.0
    lg = gc_sim.simulate(
        gc_sim.cycle(), f_s=40.0, ff=0.0, stop_at=(t_trim, 70.0), t_end=t_trim + 0.25, trim_window=(0.62, t_trim)
    )
    t, rpm, Tm, ang = lg[:, 0], lg[:, 1], lg[:, 2], lg[:, 3]
    settle = None
    for k in np.where((t > t_trim) & (np.abs(rpm) < 1))[0]:
        if np.all(np.abs(rpm[k : k + 200]) < 1):
            settle = float(t[k])
            break
    err = (float(ang[-1]) - 70 + 180) % 360 - 180
    i_ph = np.abs(Tm) / mo["kt"]  # 相电流峰值（磁场定向控制下与力矩成正比）
    p = unit(DOC, "ipm_inverter")
    ipm = p["ipm"]
    loss = [
        servo.ipm_losses(dev, ipm, spec["bus_voltage_v"], float(i), p["f_pwm"], p["m_index"], p["cos_phi"])
        for i in i_ph
    ]
    p_mod = np.array([6 * (x["igbt"] + x["diode"]) for x in loss])
    v_emf = spec["bemf_ll_peak_max_v"] / math.sqrt(3) * np.abs(rpm) / spec["speed_max_rpm"]
    res = {
        "t_peak_limit_nm": round(gc_sim.T_PEAK, 3),
        "t_reach_5000_s": float(t[np.argmax(rpm >= 0.98 * 5000)]),
        "stop_error_deg": round(err, 3),
        "t_settle_s": settle,
        "t_from_release_s": None if settle is None else round(settle - 0.50, 4),
        "torque_peak_nm": round(float(np.max(np.abs(Tm))), 3),
        "torque_rms_nm": round(float(np.sqrt(np.mean(Tm**2))), 3),
        "i_phase_peak_a": round(float(np.max(i_ph)), 3),
        "i_trip_a": unit(DOC, "low_side_sense")["i_trip"],
        "p_ipm_cycle_avg_w": round(float(np.mean(p_mod)), 2),
        "p_ipm_cycle_max_w": round(float(np.max(p_mod)), 2),
        "v_emf_phase_peak_max_v": round(float(np.max(v_emf)), 1),
        "v_phase_avail_v": round(spec["bus_voltage_v"] / math.sqrt(3), 1),
    }
    return res, (t, rpm, Tm, i_ph, p_mod, lg[:, 4], t_trim)


def ebox(p_heatsink, p_aux, fins=8):
    """第 62 轮电控箱模型：260 × 160 × 90 mm 铝盒，顶面 fins 片翅片，
    外表面 h = 10 W/(m²·K)（自然对流加辐射的量级），车间 40 ℃"""
    from cae import geometry as G
    from cae import materials as M
    from cae import thermal as TH
    from cae import thermal_parts as TP

    p = TP.params_of("sew_ebox", {"fins": fins, "p_ipm": p_heatsink, "p_aux": p_aux})
    s = TP.build("sew_ebox", p)
    ex = TP.example("sew_ebox", p, G.faces(s)[0])
    st, _, _ = TH.solve(
        s, {"material": M.get(ex["material_id"]), "thermal": ex["thermal"], "mesh": {"size_mm": ex["mesh_mm"]}}
    )
    return {
        "params": {k: p[k] for k in ("L", "W", "H", "wall", "fins", "fin_h", "h_out", "t_air")},
        "p_heatsink_w": round(p_heatsink, 2),
        "p_aux_w": round(p_aux, 2),
        "t_max_c": st["t_max_c"],
        "t_surface_mean_c": st["t_surface_mean_c"],
        "formula_t_case_c": ex["formula"]["t_est_c"],
        "heat_out_w": st["heat_out_convection_w"],
        "nodes": st["nodes"],
    }


def plot(tr, res):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    for f in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",):
        if os.path.exists(f):
            font_manager.fontManager.addfont(f)
    plt.rcParams.update(
        {
            "font.family": ["Noto Sans CJK JP", "DejaVu Sans"],
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    t, rpm, Tm, i_ph, p_mod, ref, t_trim = tr
    fig, ax = plt.subplots(4, 1, figsize=(8.6, 8.6), sharex=True, gridspec_kw=dict(hspace=0.12))
    ax[0].plot(t, ref, color="#7a8794", lw=1, ls="--", label="目标")
    ax[0].plot(t, rpm, color="#1d2733", lw=1.3, label="主轴转速")
    ax[0].set_ylabel("r/min")
    ax[0].legend(frameon=False, fontsize=8)
    ax[1].plot(t, Tm, color="#1f5fa8", lw=0.8)
    for s in (1, -1):
        ax[1].axhline(s * res["t_peak_limit_nm"], color="#c8102e", lw=0.6, ls=":")
    ax[1].set_ylabel("电机力矩 N·m")
    ax[2].plot(t, i_ph, color="#d98a1f", lw=0.8)
    ax[2].axhline(res["i_trip_a"], color="#c8102e", lw=0.6, ls=":")
    ax[2].text(0.01, res["i_trip_a"] + 0.2, "过流门限 {:g} A".format(res["i_trip_a"]), color="#c8102e", fontsize=7.5)
    ax[2].set_ylabel("相电流峰值 A")
    ax[3].plot(t, p_mod, color="#2e9e6a", lw=0.8)
    ax[3].axhline(res["p_ipm_cycle_avg_w"], color="#7a8794", lw=0.6, ls="--")
    ax[3].set_ylabel("功率模块损耗 W")
    ax[3].set_xlabel("时间 / s")
    fig.suptitle(
        "CTRL-LS 主轴伺服复算：力矩限幅 {:.2f} N·m（K_t × 峰值电流），停针误差 {:+.2f}°".format(
            res["t_peak_limit_nm"], res["stop_error_deg"]
        ),
        x=0.06,
        y=0.925,
        ha="left",
        fontsize=10.5,
    )
    fig.savefig(OUT / "1_伺服工作周期.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


DOC = design.read_yaml(str(DESIGN))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dev = parts.Devices.load()
    spec = DOC["spec"]
    res = {"servo": None, "ebox": {}}
    res["servo"], tr = servo_cycle(spec, dev)
    plot(tr, res["servo"])
    worst = losses(DOC, dev)
    typ = losses(typical(DOC), dev)
    res["losses"] = {"worst_90v_550w": worst, "typical_230v_sewing": typ}
    for name, L in (("worst_90v_550w", worst), ("typical_230v_sewing", typ)):
        res["ebox"][name] = ebox(L["heatsink_w"], L["aux_in_box_w"])
    (OUT / "仿真结果.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
