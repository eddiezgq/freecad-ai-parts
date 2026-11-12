# -*- coding: utf-8 -*-
"""第 159 轮 159c：平缝机控制器 CTRL-LS 的仿真核对（ngspice）。

和 sim.py 一样：只启动 ngspice 子进程，不联网、不调 AI；没有 ngspice 时判“未知”。
网表在这里生成，参数取自设计描述和 eda/parts，
跑完拿仿真读数和计算书里的公式值对照，超出容差判不通过。

- 升压校正（pfc_boost）：
  ① 开关级：纹波最大处（输入瞬时值 = V_o/2）定频 65 kHz、占空比 1 − V_x/V_o，量电感电流纹波，对照 ΔI = V_x·D/(L·f)；
  ② 平均模型：校正级给母线的电流 = (P/V_o)·(1 − cos 2ωt)，负载恒流，量母线二倍工频纹波，对照 P/(2π·f_工频·C·V_o)；
  ③ 掉电：恒功率负载从 V_o 放到 V_min 的时间，对照 C·(V_o² − V_min²)/(2P)。
- 电磁铁（solenoid_drive）：线圈 R、L 通电到稳态后开关断开，经“二极管 + 稳压管”钳位，量电流降到零的时间和漏极电压，
  对照 τ·ln(1 + I₀R/V_z) 与 V_24 + V_z。"""

from __future__ import annotations

import math

from .blocks import common as c
from .blocks.mains import pfc
from .sim import _circuit

READING = {
    "iripple": ("电感电流纹波（峰峰，V_x = V_o/2 处）", "A"),
    "vripple": ("母线二倍工频纹波（峰峰）", "V"),
    "t_hold": ("掉电保持时间", "s"),
    "t_off": ("释放时间（电流降到 1 %）", "s"),
    "v_ds": ("关断时漏极电压最高", "V"),
}


def pfc_cases(spec, p, dev):
    r = pfc(spec, p, dev)
    vo, f, L = r["vo"], p["f_sw"], r["L"]
    vx = r["vx"]
    d = 1 - vx / vo
    per = 1 / f
    # ① 开关级：输入恒压 V_x，输出钳在 V_o（大电容等效为电压源），电感电流从平均值起步
    i_avg = r["iin"]  # 起步电流取工频平均值附近；纹波峰峰值与直流分量无关
    sw = (
        "* CTRL-LS PFC boost switching cell at v_in = Vo/2\n"
        "Vin in 0 {vx:g}\nL1 in sw {L:g} ic={ia:g}\nVg g 0 PULSE(0 1 0 1n 1n {ton:g} {per:g})\n"
        "S1 sw 0 g 0 swm\n.model swm sw(vt=0.5 vh=0 ron=1m roff=100meg)\n"
        "D1 sw out dm\n.model dm d(is=1e-12 n=0.05 rs=1m)\nVo out 0 {vo:g}\n"
        ".tran {st:g} {ts:g} 0 {st:g} uic\n"
        ".meas tran imax MAX i(L1) FROM={t1:g} TO={ts:g}\n.meas tran imin MIN i(L1) FROM={t1:g} TO={ts:g}\n"
        ".meas tran iripple PARAM='imax-imin'\n.end\n"
    ).format(vx=vx, L=L, ia=i_avg, ton=d * per - 2e-9, per=per, vo=vo, st=per / 400, ts=40 * per, t1=38 * per)
    # ② 平均模型：二倍工频纹波（恒流负载 I_o；从稳态起步，量最后两个工频周期）
    c1 = dev.value(p["cap"], "c")
    cb = None if c1 is None else p["n_caps"] * c1
    f2 = 2 * spec["f_line_min_hz"]
    io = r["po"] / vo
    rip = None
    if cb is not None:
        rip = (
            "* CTRL-LS bus 2nd-harmonic ripple (average model)\n"
            "Bpfc 0 bus I={io:g}*(1-cos(2*3.14159265358979*{f2:g}*time))\n"
            "Cb bus 0 {cb:g} ic={vo:g}\nIload bus 0 DC {io:g}\n"
            ".tran 20u {ts:g} 0 20u uic\n"
            ".meas tran vmax MAX v(bus) FROM={t1:g} TO={ts:g}\n.meas tran vmin MIN v(bus) FROM={t1:g} TO={ts:g}\n"
            ".meas tran vripple PARAM='vmax-vmin'\n.end\n"
        ).format(io=io, f2=f2, cb=cb, vo=vo, ts=6 / f2, t1=4 / f2)
    # ③ 掉电：恒功率负载
    hold = None
    if cb is not None:
        hold = (
            "* CTRL-LS bus hold-up with constant-power load\n"
            "Cb bus 0 {cb:g} ic={vo:g}\nBload bus 0 I={po:g}/max(v(bus),1)\n"
            ".tran 50u {ts:g} 0 50u uic\n.meas tran t_hold WHEN v(bus)={vmin:g} FALL=1\n.end\n"
        ).format(cb=cb, vo=vo, po=r["po"], vmin=p["v_holdup_min"], ts=0.2)
    formulas = {
        "iripple": vx * d / (L * f),
        "vripple": None if cb is None else r["po"] / (2 * math.pi * spec["f_line_min_hz"] * cb * vo),
        "t_hold": None if cb is None else cb * (vo**2 - p["v_holdup_min"] ** 2) / (2 * r["po"]),
    }
    nets = {"switching": sw}
    if rip:
        nets.update(ripple=rip, holdup=hold)
    return {
        "example": "CTRL-LS 校正级",
        "params": {"L_uH": round(L * 1e6, 1), "f_kHz": f / 1000, "C_uF": None if cb is None else round(cb * 1e6)},
        "netlists": nets,
        "formulas": formulas,
        "checks": [("iripple", 0.03), ("vripple", 0.05), ("t_hold", 0.03)],
    }


def solenoid_cases(spec, p, dev):
    R, L = p["coil_r"], p["coil_l"]
    v24 = spec["v24"]
    i0 = v24 / R
    vbr, vf = dev.value(p["tvs"], "vbr_max"), dev.value(p["diode"], "vf_max")
    if None in (vbr, vf):
        return None
    vz = vbr + vf
    tau = L / R
    t0 = 6 * tau  # 先通电到稳态
    net = (
        "* CTRL-LS solenoid turn-off with diode + zener clamp\n"
        "V24 vp 0 {v:g}\nRc vp a {R:g}\nLc a d {L:g} ic={i0:g}\n"
        "Vg g 0 PWL(0 1 {t0:g} 1 {t1:g} 0)\nS1 d 0 g 0 swm\n.model swm sw(vt=0.5 vh=0 ron=10m roff=100meg)\n"
        "* 钳位：漏极 d → 二极管 → 稳压管（电压源加理想二极管等效）→ 电源 vp\n"
        "D1 d k dm\nVz k vp {vz0:g}\n.model dm d(is=1e-12 n=0.05 rs=1m)\n"
        ".tran 1u {ts:g} 0 1u uic\n"
        ".meas tran v_ds MAX v(d) FROM={t0:g} TO={ts:g}\n"
        ".meas tran t_end WHEN i(Lc)={i1:g} FALL=1 FROM={t0:g}\n"
        ".meas tran t_off PARAM='t_end-{t0:g}'\n.end\n"
    ).format(v=v24, R=R, L=L, i0=i0, t0=t0, t1=t0 + 1e-7, vz0=vz - vf, ts=t0 + 6 * tau, i1=0.01 * i0)
    # 电流到 1 % 的时间：i(t) = (I₀ + V_z/R)·e^(−t/τ) − V_z/R（钳位期间线圈两端 −V_z）
    t1pct = tau * math.log((i0 + vz / R) / (0.01 * i0 + vz / R))
    return {
        "example": "CTRL-LS 电磁铁关断",
        "params": {"R_ohm": R, "L_mH": L * 1000, "Vz_V": round(vz, 2)},
        "netlists": {"turnoff": net},
        "formulas": {"t_off": t1pct, "v_ds": v24 + vz},
        "checks": [("t_off", 0.03), ("v_ds", 0.03)],
        "note": "仿真里二极管压降用理想模型近似，钳位电压按 V_BR,max + V_F 加在等效电压源上；"
        "读数“释放时间”取电流降到 1 %",
    }


CASES = {"pfc_boost": pfc_cases, "solenoid_drive": solenoid_cases}


def run_unit(u, spec, dev, have_ngspice=True):
    fn = CASES.get(u["type"])
    if fn is None:
        return None
    case = fn(spec, u["params"], dev)
    if case is None:
        return {
            "example": u["type"],
            "params": {},
            "note": "器件数据缺，仿真核对判未知",
            "rows": [c.judge("sim", "仿真核对", None, None, status=c.UNKNOWN, note="器件数据缺")],
        }
    entry = {"example": case["example"], "params": case["params"], "rows": [], "note": case.get("note", "")}
    if not have_ngspice:
        entry["note"] = "本机没有 ngspice，仿真核对判未知"
        entry["rows"] = [c.judge("sim", "仿真核对", None, None, status=c.UNKNOWN, note=entry["note"])]
        return entry
    circuit = _circuit()
    meas = {}
    for net in case["netlists"].values():
        meas.update(circuit.run(net, timeout=60, vectors=False)["meas"])
    for name, allow in case["checks"]:
        fm, sim = case["formulas"].get(name), meas.get(name)
        diff = None if sim is None or not fm else abs(sim - fm) / abs(fm)
        st = c.UNKNOWN if diff is None else (c.PASS if diff <= allow else c.FAIL)
        lab, unit = READING[name]
        entry["rows"].append(
            c.judge(
                name,
                "仿真：" + lab,
                fm,
                sim,
                unit,
                "要求列是公式值、实有列是仿真值，相差 ≤ {:g}%".format(100 * allow),
                status=st,
                note="" if diff is None else "相差 {:.2f}%".format(100 * diff),
            )
        )
    return entry
