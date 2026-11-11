# -*- coding: utf-8 -*-
"""电路分析（第 79 轮，电子 E1）：关节伺服驱动板 DRV-JOINT 上的 6 道例题、网表检查、服务器 ngspice、蒙特卡洛容差。

每道例题 = 可调参数 → 若干张网表（每种分析一张，读数用 ngspice 的 .meas 算，浏览器版和服务器版同一张网表、同一个 .meas）
         + 手算公式（同一组参数）+ 对照表（读数 ↔ 公式，允许的差写在题里，公式是近似时说明为什么差）。
浏览器里跑 ngspice 的 WebAssembly 版（eecircuit-engine，随网页一起放在我们的服务器上）；服务器跑系统 ngspice（CAE 镜像 apt 装）。
参数全是 **示例值**：电机取 cae/motors.py（伺服 400 W：额定 1.27 N·m、峰值 4.46 N·m），母线电压、力矩常数、电缆、线数等本题设定写在 BOARD 并注明。
纯计算 + 子进程 ngspice；不联网。
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import tempfile

try:
    from cae import motors
except ImportError:                             # pragma: no cover
    motors = None

# ---------------------------------------------------------------- 驱动板的设定（示例值）
MOTOR = "伺服 400 W"
BOARD = {
    "vbus": 48.0,            # 母线电压 V（示例：低压伺服常用 48 V）
    "kt": 0.15,              # 力矩常数 N·m/A（示例：400 W、48 V 一类电机的量级）
    "adc_fs": 3.3,           # ADC 满量程 V；相电流双向，零点在 1.65 V
    "f_pwm": 20e3,           # 逆变器开关频率 Hz（示例）
    "enc_lines": 2500,       # 增量编码器线数（示例）
    "rpm_max": 6000,         # 电机最高转速（取 cae/motors.py）
    "r_ph": 0.8,             # 电机相电阻 Ω（示例）
    "l_ph": 1.2e-3,          # 电机相电感 H（示例）
}


def motor_row(name=MOTOR):
    if motors is None:
        return (name, 400, 1.27, 4.46, 6000, 0.42e-4)
    return next(m for m in motors.MOTORS if m[0] == name)


def i_peak():
    """峰值相电流 A = 峰值力矩 / 力矩常数"""
    return motor_row()[3] / BOARD["kt"]


def i_rated():
    return motor_row()[2] / BOARD["kt"]


# ---------------------------------------------------------------- 通用器件模型（示例参数，不用厂商模型）
OPAMP = """.subckt wqop inp inn out
* generic op-amp macromodel (example): open-loop gain a0, one pole so that GBW = gbw; Rin 10 Meg, Rout 50 ohm (linear, no rail limits)
Rin inp inn 10meg
Eg a 0 inp inn {a0}
Rp a b 1k
Cp b 0 {1/(2*3.141592653589793*1k*gbw/a0)}
Eo c 0 b 0 1
Ro c out 50
.ends"""

NMOS = (".model wqfet vdmos(vto=3 kp=40 rd=4m rs=2m rg=1 cgs=1.6n cgdmax=0.9n cgdmin=60p a=0.3 cjo=0.6n is=1e-12 rb=5m)"
        "  $ generic 60 V power MOSFET, example parameters (ngspice VDMOS)")


# ---------------------------------------------------------------- 例题
def _p(v, d):
    return float(v) if v not in (None, "") else d


def ex_sense(p):
    """① 相电流采样放大：采样电阻 + 差分放大，零点 1.65 V"""
    rs = _p(p.get("rs_mohm"), 2.0) * 1e-3
    g = _p(p.get("gain"), 20.0)
    gbw = _p(p.get("gbw_mhz"), 10.0) * 1e6
    r1 = 1e3
    r2 = g * r1
    ip = i_peak()
    vref = BOARD["adc_fs"] / 2
    head = "* (1) phase current sense amplifier, DRV-JOINT\n.param a0=1e5 gbw={:g}\n{}\n".format(gbw, OPAMP)
    body = ("Iph 0 sh DC 0 AC 1\nRs sh 0 {rs:g}\nVref ref 0 {vref:g}\n"
            "R1 sh n1 {r1:g}\nR2 n1 out {r2:g}\nR3 0 p1 {r1:g}\nR4 p1 ref {r2:g}\nXop p1 n1 out wqop\n").format(rs=rs, vref=vref, r1=r1, r2=r2)
    # 注：电流从地流向 sh，采样电压 v(sh) = I·Rs；同相端接地侧，反相端接 sh——输出 = Vref − G·I·Rs（双向，零点 1.65 V）
    dc = head + body + (".dc Iph {a:g} {b:g} {s:g}\n"
                        ".meas dc vout_peak FIND v(out) AT={ip:g}\n"
                        ".meas dc vout_zero FIND v(out) AT=0\n.end\n").format(a=-1.2 * ip, b=1.2 * ip, s=2.4 * ip / 240, ip=ip)
    ac = head + body + (".ac dec 40 10 100meg\n"
                        ".meas ac g_lf FIND vdb(out) AT=100\n"
                        ".meas ac f3db WHEN vdb(out)={t:g} FALL=1\n.end\n").format(t=20 * math.log10(g * rs) - 3)
    swing = g * rs * ip
    f = {"vout_peak": vref - swing, "vout_zero": vref, "f3db": gbw / (1 + g),
         "g_lf": 20 * math.log10(g * rs)}
    return {
        "netlists": {"dc": dc, "ac": ac},
        "formulas": f,
        "derived": {"i_peak_A": round(ip, 2), "i_rated_A": round(i_rated(), 2), "shunt_mV_at_peak": round(1e3 * rs * ip, 1),
                    "p_shunt_W_rated": round(i_rated() ** 2 * rs, 3), "headroom_V": round(vref - swing, 3)},
        "checks": [("vout_peak", 0.005), ("vout_zero", 0.005), ("f3db", 0.03)],
        "mc": {"analysis": "dc", "meas": "vout_peak", "tol": {"R1": 0.01, "R2": 0.01, "R3": 0.01, "R4": 0.01, "Rs": 0.01}},
        "plots": {"dc": ["v(out)"], "ac": ["v(out)"]},
    }


def ex_gate(p):
    """② 栅极驱动与开关：低边管开通（感性负载被二极管钳在母线上，电流按恒流算），米勒平台"""
    rg = _p(p.get("rg_ohm"), 10.0)
    vdrv = _p(p.get("vdrv"), 12.0)
    il = _p(p.get("i_load"), i_rated())
    vbus = BOARD["vbus"]
    head = "* (2) gate drive of the low-side MOSFET, DRV-JOINT\n{}\n".format(NMOS)
    body = ("Vbus bus 0 {vbus:g}\nIl bus d {il:g}\nDfw d bus dfw\n.model dfw d(is=1e-9 rs=5m cjo=200p tt=10n)\n"
            "Vdrv dr 0 PULSE(0 {vd:g} 1u 5n 5n 3u 10u)\nRg dr g {rg:g}\nM1 d g 0 wqfet\n").format(vbus=vbus, il=il, vd=vdrv, rg=rg)
    tran = head + body + (".tran 1n 6u 0 2n\n"
                          ".meas tran t_on TRIG v(d) VAL={a:g} FALL=1 TARG v(d) VAL={b:g} FALL=1\n"
                          ".meas tran t_off TRIG v(d) VAL={b:g} RISE=1 TARG v(d) VAL={a:g} RISE=1\n"
                          ".meas tran td_off TRIG v(dr) VAL={h:g} FALL=1 TARG v(d) VAL={b:g} RISE=1\n"
                          ".meas tran vplat FIND v(g) WHEN v(d)={m:g} FALL=1\n.end\n").format(
        a=0.9 * vbus, b=0.1 * vbus, h=vdrv / 2, m=vbus / 2)
    # 公式（栅电荷法，和器件手册的 Qg 曲线同一个道理）：
    #   平台电压（芯片内部）由平方律 I = kp/2·(Vgs − Vth)² 求；页面量的是外部栅极 g，要加上内部栅电阻 1 Ω 上的压降。
    #   漏压摆动期间栅电流几乎全部给 Cgd 充放电：t ≈ Q_gd·(Rg + rg_内)/(Vdrv − Vplat)（开通）、Q_gd·(Rg + rg_内)/Vplat（关断）。
    #   Q_gd 由第三张网表“量”出来：栅极固定在平台电压，漏极从 90% 扫到 10% 母线电压，积分栅电流（器件手册的 Q_gd 就是这么定义的）。
    rg_int, vth, kp = 1.0, 3.0, 40.0
    vpi = vth + math.sqrt(2 * il / kp)
    ig_on = (vdrv - vpi) / (rg + rg_int)
    qgd = (head + "Vd d 0 PWL(0 {a:g} 1u {b:g})\nVg g 0 {vp:g}\nM1 d g 0 wqfet\n.tran 1n 1u\n"
           ".meas tran qgd INTEG i(Vg) FROM=0 TO=1u\n.end\n").format(a=0.9 * vbus, b=0.1 * vbus, vp=vpi)
    return {
        "netlists": {"tran": tran, "qgd": qgd},
        "formulas": {"vplat": vpi + rg_int * ig_on,
                     "t_on": lambda m: abs(m["qgd"]) * (rg + rg_int) / (vdrv - vpi),
                     "t_off": lambda m: abs(m["qgd"]) * (rg + rg_int) / vpi},
        "derived": {"i_load_A": round(il, 2), "vplat_internal_V": round(vpi, 3), "ig_on_A": round(ig_on, 3)},
        "checks": [("vplat", 0.05), ("t_on", 0.25), ("t_off", 0.1)],
        "mc": None,
        "plots": {"tran": ["v(g)", "v(d)"]},
        "note_formula": "Q_gd 是在平台电压下量的；开通后期 Vgs 已越过平台、Cgd 随漏压变化很大，开通时间的公式偏差大些。死区至少要大于关断延时 td_off 再留余量",
    }


def ex_bus(p):
    """③ 母线电容与输入滤波：逆变器拉脉动电流，电缆电感 + 母线电容构成 LC"""
    c = _p(p.get("c_uf"), 470.0) * 1e-6
    esr = _p(p.get("esr_mohm"), 15.0) * 1e-3
    lc = _p(p.get("l_cable_uh"), 10.0) * 1e-6
    rdamp = _p(p.get("r_cable_mohm"), 10.0) * 1e-3
    il = _p(p.get("i_load"), i_rated())
    d = 0.5
    f = BOARD["f_pwm"]
    vbus = BOARD["vbus"]
    head = "* (3) DC-link capacitor and input LC, DRV-JOINT\n"
    body = ("Vs src 0 DC {v:g} AC 1\nRc src a {r:g}\nLc a bus {l:g}\nCb bus e {c:g}\nResr e 0 {esr:g}\n").format(
        v=vbus, r=rdamp, l=lc, c=c, esr=esr)
    per = 1 / f
    tran = head + body + ("Iinv bus 0 PULSE(0 {il:g} 0 50n 50n {ton:g} {per:g})\n"
                          ".ic v(bus)={v:g}\n.tran 20n {tstop:g} 0 20n\n"
                          ".meas tran vmax MAX v(bus) FROM={t1:g} TO={t2:g}\n.meas tran vmin MIN v(bus) FROM={t1:g} TO={t2:g}\n"
                          ".meas tran ripple PARAM='vmax-vmin'\n.end\n").format(
        il=il, ton=d * per - 50e-9, per=per, v=vbus, tstop=60 * per, t1=50 * per, t2=60 * per)
    ac = head + body + ("Iinv bus 0 DC 0\n.ac dec 50 100 1meg\n"
                        ".meas ac g_peak MAX vdb(bus)\n.end\n")       # MAX 同时给出最大值所在的频率（读成 g_peak_at）
    f0 = 1 / (2 * math.pi * math.sqrt(lc * c))
    z0 = math.sqrt(lc / c)
    q = z0 / (rdamp + esr)
    # 纹波：电容供给开关电流的交流分量。方波电流 I·D 的电荷 ΔQ = I·D(1−D)/f；电容压降 ΔQ/C + ESR 上的 I·ESR
    ripple_c = il * d * (1 - d) / (c * f)
    ripple = ripple_c + il * esr
    return {
        "netlists": {"tran": tran, "ac": ac},
        "formulas": {"ripple": ripple, "g_peak_at": f0, "g_peak": 20 * math.log10(q) if q > 0 else 0},
        "derived": {"f0_Hz": round(f0, 1), "Z0_ohm": round(z0, 4), "Q": round(q, 2), "ripple_cap_V": round(ripple_c, 4),
                    "ripple_esr_V": round(il * esr, 4)},
        "checks": [("ripple", 0.15), ("g_peak_at", 0.05), ("g_peak", 0.15)],
        "mc": None,
        "plots": {"tran": ["v(bus)"], "ac": ["v(bus)"]},
    }


def ex_encoder(p):
    """④ 编码器差分信号接收：线接收器输出经 RC 滤波进比较器（阈值 1.65 V、回差 ±0.2 V）"""
    r = _p(p.get("r_ohm"), 1000.0)
    c = _p(p.get("c_pf"), 220.0) * 1e-12
    rpm = _p(p.get("rpm"), BOARD["rpm_max"])
    lines = BOARD["enc_lines"]
    fe = rpm / 60 * lines                       # 每相脉冲频率
    per = 1 / fe
    vcc = 3.3
    tau = r * c
    head = "* (4) encoder channel A receiver with RC filter, DRV-JOINT\n"
    body = ("Vin in 0 PULSE(0 {v:g} 0 10n 10n {hw:g} {per:g})\nR1 in f {r:g}\nC1 f 0 {c:g}\n"
            "Bcmp q 0 V = {v:g}*(1+tanh(200*(v(f)-1.65)))/2\n").format(v=vcc, hw=per / 2 - 10e-9, per=per, r=r, c=c)
    tran = head + body + (".tran {st:g} {ts:g} 0 {st:g}\n"
                          ".meas tran vf_max MAX v(f) FROM={t1:g} TO={t2:g}\n.meas tran vf_min MIN v(f) FROM={t1:g} TO={t2:g}\n"
                          ".meas tran delay TRIG v(in) VAL=1.65 RISE=5 TARG v(q) VAL=1.65 RISE=5\n.end\n").format(
        st=per / 400, ts=8 * per, t1=6 * per, t2=8 * per)
    ac = head.replace("PULSE", "") + ("Vin in 0 DC 0 AC 1\nR1 in f {r:g}\nC1 f 0 {c:g}\n.ac dec 50 1k 100meg\n"
                                       ".meas ac fc WHEN vdb(f)=-3 FALL=1\n.end\n").format(r=r, c=c)
    x = math.exp(-per / 2 / tau)
    vmax = vcc / (1 + x)                        # 方波过 RC 的稳态：最高 Vcc/(1+x)、最低 Vcc·x/(1+x)
    vmin = vcc * x / (1 + x)
    delay = tau * math.log((vcc - vmin) / (vcc - 1.65)) if vmin < 1.65 else float("nan")
    return {
        "netlists": {"tran": tran, "ac": ac},
        "formulas": {"vf_max": vmax, "vf_min": vmin, "fc": 1 / (2 * math.pi * tau), "delay": delay},
        "derived": {"f_pulse_Hz": round(fe, 1), "tau_ns": round(tau * 1e9, 2), "fc_over_fpulse": round(1 / (2 * math.pi * tau) / fe, 2)},
        "checks": [("vf_max", 0.01), ("vf_min", 0.03), ("fc", 0.01), ("delay", 0.05)],
        "mc": None,
        "plots": {"tran": ["v(in)", "v(f)", "v(q)"], "ac": ["v(f)"]},
    }


def ex_buck(p):
    """⑤ 24 V → 5 V 同步降压（开环，占空比固定）：电感纹波、输出纹波、效率"""
    vi = _p(p.get("vin"), 24.0)
    vo_set = _p(p.get("vout"), 5.0)
    io = _p(p.get("iout"), 1.0)
    l = _p(p.get("l_uh"), 22.0) * 1e-6
    c = _p(p.get("c_uf"), 22.0) * 1e-6
    f = _p(p.get("f_khz"), 300.0) * 1e3
    ron, dcr, esr = 0.05, 0.03, 0.01
    rl = vo_set / io
    d = (vo_set + io * (ron + dcr)) / vi        # 补上导通压降的占空比
    per = 1 / f
    head = "* (5) 24 V to 5 V synchronous buck (logic supply of DRV-JOINT, example)\n"
    body = ("Vin vi 0 {vi:g}\nVgh gh 0 PULSE(0 1 0 5n 5n {ton:g} {per:g})\nVgl gl 0 PULSE(1 0 0 5n 5n {ton:g} {per:g})\n"
            "S1 vi sw gh 0 sw1\nS2 sw 0 gl 0 sw1\n.model sw1 sw(vt=0.5 vh=0 ron={ron:g} roff=1meg)\n"
            "L1 sw x {l:g} ic={io:g}\nRdcr x o {dcr:g}\nC1 o e {c:g} ic={vo:g}\nResr e 0 {esr:g}\nRload o 0 {rl:g}\n").format(
        vi=vi, ton=d * per - 10e-9, per=per, ron=ron, l=l, dcr=dcr, c=c, esr=esr, rl=rl, io=io, vo=vo_set)
    t1, t2 = 380 * per, 400 * per          # 电感电流、电容电压从稳态值起步（ic=），不用等启动振荡衰减
    tran = head + body + (".tran {st:g} {ts:g} 0 {st:g} uic\n"
                          ".meas tran vo_avg AVG v(o) FROM={t1:g} TO={t2:g}\n"
                          ".meas tran vmax MAX v(o) FROM={t3:g} TO={t2:g}\n.meas tran vmin MIN v(o) FROM={t3:g} TO={t2:g}\n"
                          ".meas tran vripple PARAM='vmax-vmin'\n"
                          ".meas tran imax MAX i(L1) FROM={t3:g} TO={t2:g}\n.meas tran imin MIN i(L1) FROM={t3:g} TO={t2:g}\n"
                          ".meas tran iripple PARAM='imax-imin'\n"
                          ".meas tran pin AVG par('-v(vi)*i(Vin)') FROM={t1:g} TO={t2:g}\n"
                          ".meas tran pout AVG par('v(o)*v(o)/{rl:g}') FROM={t1:g} TO={t2:g}\n"
                          ".meas tran eff PARAM='pout/pin'\n.end\n").format(
        st=per / 400, ts=t2, t1=t1, t2=t2, t3=t2 - per, rl=rl)     # 纹波看最后一个开关周期（LC 的慢振荡不算进去）
    di = (vi - vo_set) * d / (l * f)
    dv = math.hypot(di / (8 * c * f), di * esr)   # 电容上的纹波与 ESR 上的纹波相位差约 90°：按平方和开方合成
    irms2 = io ** 2 + di ** 2 / 12
    p_loss = irms2 * (ron + dcr) + (di ** 2 / 12) * esr
    eff = vo_set * io / (vo_set * io + p_loss)
    return {
        "netlists": {"tran": tran},
        "formulas": {"vo_avg": vo_set, "iripple": di, "vripple": dv, "eff": eff},
        "derived": {"duty": round(d, 4), "fc_LC_Hz": round(1 / (2 * math.pi * math.sqrt(l * c)), 1), "r_load_ohm": round(rl, 3)},
        "checks": [("vo_avg", 0.02), ("iripple", 0.05), ("vripple", 0.1), ("eff", 0.02)],
        "mc": None,
        "plots": {"tran": ["v(o)", "i(l1)"]},
        "note_formula": "效率公式只算导通损耗（理想开关没有开关损耗）；输出纹波 = 电容项 ΔI/(8Cf) 与 ESR 项 ΔI·ESR 按平方和开方合成（两项相位差约 90°，直接相加会偏大）",
    }


def ex_current_loop(p):
    """⑥ 电机绕组电流环：开环 RL 阶跃；PI 零点对消电气极点后闭环是一阶，带宽 = 设定值"""
    r, l = BOARD["r_ph"], BOARD["l_ph"]
    fbw = _p(p.get("f_bw_hz"), 1000.0)
    iref = _p(p.get("i_ref"), i_rated())
    wc = 2 * math.pi * fbw
    kp, ki = l * wc, r * wc
    vmax = BOARD["vbus"]
    head = "* (6) motor winding current loop, one phase as RL (DRV-JOINT, example values)\n"
    open_ = head + ("Vs s 0 PULSE(0 {v:g} 0 1n 1n 1 2)\nR1 s x {r:g}\nL1 x 0 {l:g}\n.tran 1u {ts:g}\n"
                    ".meas tran i_final FIND i(L1) AT={ts:g}\n"
                    ".meas tran t63 WHEN i(L1)={i63:g} RISE=1\n.end\n").format(
        v=iref * r, r=r, l=l, ts=8 * l / r, i63=iref * (1 - math.exp(-1)))
    closed = head + ("Vref ref 0 PULSE(0 {ir:g} 0 1n 1n 1 2)\n"
                     "* PI: u = Kp*e + Ki*integral(e); integrator = 1 F capacitor fed by a current source; output clamped to +-Vbus\n"
                     "Bint 0 ix I = v(ref)-i(Vsen)\nCint ix 0 1\n"
                     "Bu u 0 V = max(-{vm:g}, min({vm:g}, {kp:g}*(v(ref)-i(Vsen)) + {ki:g}*v(ix)))\n"
                     "R1 u x {r:g}\nL1 x y {l:g}\nVsen y 0 0\n.tran 0.5u {ts:g}\n"
                     ".meas tran t_rise TRIG i(Vsen) VAL={a:g} RISE=1 TARG i(Vsen) VAL={b:g} RISE=1\n"
                     ".meas tran i_max MAX i(Vsen)\n.meas tran u_max MAX v(u)\n.end\n").format(
        ir=iref, vm=vmax, kp=kp, ki=ki, r=r, l=l, ts=10 / wc, a=0.1 * iref, b=0.9 * iref)
    # 交流：闭环 I/Iref（线性，不限幅）
    ac = head + ("Vref ref 0 DC 0 AC 1\nBint 0 ix I = v(ref)-i(Vsen)\nCint ix 0 1\n"
                 "Bu u 0 V = {kp:g}*(v(ref)-i(Vsen)) + {ki:g}*v(ix)\n"
                 "R1 u x {r:g}\nL1 x y {l:g}\nVsen y 0 0\nHs isen 0 Vsen 1\n.ac dec 50 10 1meg\n"
                 ".meas ac f3db WHEN vdb(isen)=-3 FALL=1\n.end\n").format(kp=kp, ki=ki, r=r, l=l)
    return {
        "netlists": {"open": open_, "tran": closed, "ac": ac},
        "formulas": {"i_final": iref, "t63": l / r, "t_rise": math.log(9) / wc, "i_max": iref, "f3db": fbw, "u_max": min(kp * iref, vmax)},
        "derived": {"tau_e_ms": round(1e3 * l / r, 3), "Kp_V_per_A": round(kp, 3), "Ki_V_per_As": round(ki, 1),
                    "u_needed_V": round(kp * iref, 1), "vbus_V": vmax, "saturated": kp * iref > vmax},
        "checks": [("i_final", 0.01), ("t63", 0.02), ("t_rise", 0.03), ("i_max", 0.01), ("f3db", 0.02), ("u_max", 0.02)],
        "mc": None,
        "plots": {"open": ["i(l1)"], "tran": ["i(vsen)", "v(u)"], "ac": ["v(isen)"]},
    }


EXAMPLES = {
    "sense": {"no": 1, "title": "相电流采样放大", "fn": ex_sense,
              "question": "400 W 关节电机峰值相电流约 {ip:.0f} A：采样电阻取多少毫欧、放大多少倍，峰值才落在 ADC 量程（0–3.3 V，零点 1.65 V）里？带宽够不够电流环用？",
              "params": [("rs_mohm", "采样电阻 mΩ", 2.0, 0.5, 20), ("gain", "放大倍数", 20.0, 2, 100), ("gbw_mhz", "运放增益带宽积 MHz", 10.0, 1, 100)]},
    "gate": {"no": 2, "title": "栅极驱动与开关时间", "fn": ex_gate,
             "question": "驱动电阻怎么选：太大开关慢、损耗大；太小振铃、干扰大。漏压下降、上升各要多久？死区至少多长才不会上下管直通？",
             "params": [("rg_ohm", "驱动电阻 Ω", 10.0, 1, 100), ("vdrv", "驱动电压 V", 12.0, 8, 15), ("i_load", "负载电流 A", None, 1, 30)]},
    "bus": {"no": 3, "title": "母线电容与输入滤波", "fn": ex_bus,
            "question": "48 V 母线上逆变器的电流一开一关：母线电容要多大，纹波才不超过 1 V？电缆电感和母线电容会不会谐振？",
            "params": [("c_uf", "母线电容 μF", 470.0, 22, 4700), ("esr_mohm", "电容 ESR mΩ", 15.0, 1, 500),
                       ("l_cable_uh", "电缆电感 μH", 10.0, 0.1, 50), ("r_cable_mohm", "电缆电阻 mΩ", 10.0, 1, 1000), ("i_load", "逆变器电流 A", None, 1, 30)]},
    "encoder": {"no": 4, "title": "编码器信号接收与滤波", "fn": ex_encoder,
                "question": "编码器信号进驱动板前加 RC 滤波防干扰：滤波太强，高速时的脉冲会不会被吃掉？比较器翻转晚多少？",
                "params": [("r_ohm", "滤波电阻 Ω", 1000.0, 10, 100000), ("c_pf", "滤波电容 pF", 220.0, 10, 10000), ("rpm", "电机转速 r/min", None, 100, 6000)]},
    "buck": {"no": 5, "title": "24 V → 5 V 降压电源", "fn": ex_buck,
             "question": "驱动板的逻辑部分要 5 V、1 A：电感、电容取多少，电感电流纹波、输出纹波和效率是多少？",
             "params": [("vin", "输入 V", 24.0, 12, 48), ("vout", "输出 V", 5.0, 1.8, 12), ("iout", "负载 A", 1.0, 0.1, 3),
                        ("l_uh", "电感 μH", 22.0, 2.2, 220), ("c_uf", "输出电容 μF", 22.0, 4.7, 470), ("f_khz", "开关频率 kHz", 300.0, 100, 1000)]},
    "current_loop": {"no": 6, "title": "电机电流环", "fn": ex_current_loop,
                     "question": "电机绕组的 R、L 决定电流上升多快：开环给电压阶跃要多久？PI 电流环怎么调，才又快又不超调？电压够不够？",
                     "params": [("f_bw_hz", "电流环带宽 Hz", 1000.0, 100, 5000), ("i_ref", "电流指令 A", None, 0.5, 30)]},
}

# 第 130 轮：英文版的题目与问题（参数、读数的名字在网页英文表 web/src/locales/en.json 里）
EN = {
    "sense": ("Phase-current sensing amplifier",
              "The 400 W joint motor's peak phase current is about {ip:.0f} A. What shunt resistance (mΩ) and gain put the peak inside the ADC range "
              "(0–3.3 V, zero at 1.65 V)? Is the bandwidth enough for the current loop?"),
    "gate": ("Gate drive and switching time",
             "How to choose the gate resistor: too large switches slowly with high loss; too small rings and causes interference. "
             "How long do the drain-voltage fall and rise take? How long must the dead time be so the high and low sides never conduct together?"),
    "bus": ("DC-bus capacitor and input filter",
            "The inverter current on the 48 V bus switches on and off: how large must the bus capacitor be to keep the ripple under 1 V? "
            "Will the cable inductance resonate with the bus capacitor?"),
    "encoder": ("Encoder signal receiver and filter",
                "An RC filter in front of the drive board blocks interference on the encoder signals: if it filters too hard, are pulses lost at high speed? "
                "How much later does the comparator switch?"),
    "buck": ("24 V → 5 V buck regulator",
             "The board's logic needs 5 V at 1 A: what inductor and capacitor, and what are the inductor-current ripple, output ripple and efficiency?"),
    "current_loop": ("Motor current loop",
                     "The winding R and L set how fast the current rises: how long does an open-loop voltage step take? "
                     "How should the PI current loop be tuned to be fast without overshoot? Is there enough voltage?"),
}

READING_NAMES = {
    "vout_peak": ("峰值电流时的输出", "V"), "vout_zero": ("零电流时的输出", "V"), "f3db": ("−3 dB 带宽", "Hz"), "g_lf": ("低频跨阻增益", "dB"),
    "vplat": ("米勒平台电压", "V"), "t_on": ("漏压下降时间（90%→10%）", "s"), "t_off": ("漏压上升时间（10%→90%）", "s"),
    "td_off": ("关断延时（驱动信号到漏压 10%）", "s"),
    "ripple": ("母线电压纹波（峰峰）", "V"), "g_peak_at": ("LC 谐振频率", "Hz"), "g_peak": ("谐振峰", "dB"),
    "vf_max": ("滤波后最高电压", "V"), "vf_min": ("滤波后最低电压", "V"), "fc": ("RC 截止频率", "Hz"), "delay": ("比较器翻转延时", "s"),
    "vo_avg": ("输出电压平均值", "V"), "iripple": ("电感电流纹波（峰峰）", "A"), "vripple": ("输出电压纹波（峰峰）", "V"), "eff": ("效率", ""),
    "vpeak": ("启动过冲最高电压", "V"),
    "i_final": ("开环稳态电流", "A"), "t63": ("开环时间常数（到 63%）", "s"), "t_rise": ("闭环上升时间（10%→90%）", "s"),
    "i_max": ("闭环最大电流（超调）", "A"), "u_max": ("阶跃时 PI 输出电压最大值", "V"),
}


def defaults(key):
    ex = EXAMPLES[key]
    out = {}
    for k, _, d, _, _ in ex["params"]:
        if d is None:
            d = round(i_rated(), 2) if k in ("i_load", "i_ref") else BOARD["rpm_max"]
        out[k] = d
    return out


def _save_all(net):
    """批处理不带 -r 时，.meas 用的 vdb() 之类要先 .save all 才有数据"""
    out, done = [], False
    for ln in net.split("\n"):
        if not done and re.match(r"^\.(dc|ac|tran|op|noise)\b", ln.strip(), re.I):
            out.append(".save all")
            done = True
        out.append(ln)
    return "\n".join(out)


def build(key, params=None):
    """例题 → {netlists, formulas, derived, checks, ...}（参数缺的用缺省值，越界的夹到范围内）"""
    ex = EXAMPLES[key]
    p = defaults(key)
    for k, _, _, lo, hi in ex["params"]:
        v = (params or {}).get(k)
        if v not in (None, ""):
            p[k] = min(max(float(v), lo), hi)
    out = ex["fn"](p)
    out["netlists"] = {k: _save_all(v) for k, v in out["netlists"].items()}
    out.update(key=key, no=ex["no"], title=ex["title"], params=p,
               question=ex["question"].format(ip=i_peak()),
               title_en=EN[key][0], question_en=EN[key][1].format(ip=i_peak()),
               param_defs=[{"key": k, "label": lb, "min": lo, "max": hi} for k, lb, _, lo, hi in ex["params"]])
    return out


def catalog():
    return [{"key": k, "no": v["no"], "title": v["title"], "question": v["question"].format(ip=i_peak()), "defaults": defaults(k),
             "title_en": EN[k][0], "question_en": EN[k][1].format(ip=i_peak()),
             "params": [{"key": a, "label": b, "min": lo, "max": hi} for a, b, _, lo, hi in v["params"]]}
            for k, v in EXAMPLES.items()]


# ---------------------------------------------------------------- 网表检查（网表模式）
FORBID = re.compile(r"^\s*(\.control|\.endc|\.include|\.inc|\.lib|\.libfile|\.save\s+all\s+\S*/|\.?shell|\.?source|\.?write|\.?set\b|\.?load|\.?cd\b|"
                    r"\.?exec|\.?run\b|\.?rusage|\.?wrdata|\.?wrs2p|\.?codemodel|\.?pre_|\.?osdi|\.?echo|\.?print\s+\S*>)", re.I)
ANALYSES = (".save", ".op", ".dc", ".ac", ".tran", ".noise", ".tf", ".pz", ".sens", ".disto", ".four", ".meas", ".measure", ".param", ".model",
            ".subckt", ".ends", ".ic", ".nodeset", ".options", ".option", ".temp", ".end", ".global", ".func", ".csparam", ".step", ".title")
MAX_LINES = 2000


def check_netlist(text):
    """返回 (问题列表, 节点名)。不许 .control 段、读写文件、shell 等；只许常见分析与器件。"""
    errs, nodes = [], set()
    lines = (text or "").replace("\r", "").split("\n")
    if len(lines) > MAX_LINES:
        errs.append("网表太长（超过 {} 行）".format(MAX_LINES))
    analyses = 0
    for i, ln in enumerate(lines[1:], 2):         # 第一行是标题（SPICE 规矩）
        s = ln.strip()
        if not s or s.startswith("*") or s.startswith("+"):
            continue
        if FORBID.match(s):
            errs.append("第 {} 行：网表模式不支持“{}”（只做电路分析，不读写文件、不运行命令）".format(i, s.split()[0]))
            continue
        if s.startswith("."):
            w = s.split()[0].lower()
            if w not in ANALYSES:
                errs.append("第 {} 行：不认识的控制语句 {}".format(i, w))
            if w in (".op", ".dc", ".ac", ".tran", ".noise", ".tf", ".pz"):
                analyses += 1
            continue
        tok = s.split()
        if tok[0][0].lower() in "rlcvidqmjkegfhbswtxuyzop" and len(tok) >= 3:
            for t in tok[1:3]:
                if "=" not in t and "(" not in t:
                    nodes.add(t.lower())
        elif tok[0][0].lower() not in "abcdefghijklmnopqrstuvwxyz":
            errs.append("第 {} 行：看不懂“{}”".format(i, s[:30]))
    if analyses == 0:
        errs.append("网表里没有分析语句（.op / .dc / .ac / .tran 等）")
    nodes.discard("0")
    return errs, sorted(nodes)


# ---------------------------------------------------------------- 服务器 ngspice
AT = re.compile(r"\bat\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)", re.I)
NUM = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)", re.I)


MEAS_NAME = re.compile(r"^\s*\.meas(?:ure)?\s+\w+\s+(\w+)", re.I)


def meas_names(netlist):
    return {m.group(1).lower() for m in map(MEAS_NAME.match, netlist.split("\n")) if m}


def parse_meas(text, names=None):
    """ngspice 输出里的 .meas 结果：“name = 1.23e-03 …”；names 给了就只认这些名字"""
    out = {}
    for ln in (text or "").splitlines():
        m = NUM.match(ln)
        if m and (names is None or m.group(1).lower() in names):
            out[m.group(1).lower()] = float(m.group(2))
            at = AT.search(ln)                   # MAX / MIN 还给出在哪里（时间或频率）
            if at:
                out[m.group(1).lower() + "_at"] = float(at.group(1))
    return out


def parse_raw_ascii(text):
    """ngspice 的 ASCII raw 文件 → [{plot, names, real, data: {name: [..]}}]（复数取 [re, im]）"""
    plots, i, L = [], 0, text.splitlines()
    while i < len(L):
        if not L[i].startswith("Title:") or i + 1 >= len(L):
            i += 1
            continue
        hdr = {}
        while i < len(L) and not L[i].startswith("Variables:"):
            if ":" in L[i]:
                k, v = L[i].split(":", 1)
                hdr[k.strip()] = v.strip()
            i += 1
        nv, npts = int(hdr["No. Variables"]), int(hdr["No. Points"])
        cplx = "complex" in hdr.get("Flags", "")
        i += 1
        names = []
        for _ in range(nv):
            parts = L[i].split()
            names.append(parts[1].lower())
            i += 1
        while not L[i].startswith("Values:"):
            i += 1
        i += 1
        data = {n: [] for n in names}
        vals = []
        while i < len(L) and len(vals) < (nv + 1) * npts:
            for t in L[i].split():
                vals.append(t)
            i += 1
        # 每点：点号、第一个值；之后每行一个值
        k = 0
        for _ in range(npts):
            k += 1                               # 点号
            for n in names:
                t = vals[k]
                k += 1
                if cplx:
                    a, b = t.split(",")
                    data[n].append([float(a), float(b)])
                else:
                    data[n].append(float(t))
        plots.append({"plot": hdr.get("Plotname", ""), "names": names, "complex": cplx, "data": data})
    return plots


def ngspice_bin():
    return shutil.which("ngspice")


def run(netlist, timeout=20, max_points=4000, vectors=True):
    """服务器 ngspice 跑一张网表 → {meas, plots, log}。plots 均匀抽到 max_points 点以内。"""
    exe = ngspice_bin()
    if not exe:
        raise RuntimeError("服务器上没有 ngspice")
    with tempfile.TemporaryDirectory(prefix="wq-spice-") as d:
        cir, raw = os.path.join(d, "c.cir"), os.path.join(d, "c.raw")
        if not re.search(r"^\s*\.save\b", netlist, re.I | re.M):
            netlist = _save_all(netlist)          # 批处理不写 raw 时 .meas 要先 .save
        with open(cir, "w", encoding="utf-8") as f:
            f.write(netlist if netlist.endswith("\n") else netlist + "\n")
        env = dict(os.environ, SPICE_ASCIIRAWFILE="1")
        mcir = os.path.join(d, "m.cir")           # 读 .meas 的那一遍：同时有 .op 和别的分析时 ngspice 不打印 .meas，去掉 .op
        body = netlist
        if re.search(r"^\s*\.(dc|ac|tran)\b", body, re.I | re.M):
            body = re.sub(r"^\s*\.op\b.*$", "* .op（读数这一遍不做）", body, flags=re.I | re.M)
        with open(mcir, "w", encoding="utf-8") as f:
            f.write(body if body.endswith("\n") else body + "\n")
        try:                                     # 批处理带 -r 时 ngspice 不打印 .meas：读数、曲线各跑一遍（电路小，很快）
            r = subprocess.run([exe, "-b", mcir], capture_output=True, text=True, timeout=timeout, cwd=d, env=env)
            if vectors:
                subprocess.run([exe, "-b", "-r", raw, cir], capture_output=True, text=True, timeout=timeout, cwd=d, env=env)
        except subprocess.TimeoutExpired:
            raise RuntimeError("仿真超过 {} 秒，停了（步长太小或时间太长？）".format(timeout)) from None
        log = (r.stdout or "") + "\n" + (r.stderr or "")
        plots = []
        if vectors and os.path.exists(raw):
            with open(raw, encoding="utf-8", errors="replace") as f:
                plots = parse_raw_ascii(f.read())
    for pl in plots:
        n = len(next(iter(pl["data"].values()))) if pl["data"] else 0
        if n > max_points:
            step = math.ceil(n / max_points)
            pl["data"] = {k: v[::step] for k, v in pl["data"].items()}
    errs = [ln.strip() for ln in log.splitlines() if re.search(r"\berror\b|failed", ln, re.I)]
    return {"meas": parse_meas(r.stdout, meas_names(netlist)), "plots": plots, "errors": errs[:20], "log": log[-4000:]}


# ---------------------------------------------------------------- 对照与蒙特卡洛
def compare(key, params, meas):
    """读数 ↔ 公式：[{name, label, unit, sim, formula, diff, ok, allow}]"""
    b = build(key, params)
    rows = []
    for name, allow in b["checks"]:
        lab, unit = READING_NAMES.get(name, (name, ""))
        sim, fm = meas.get(name), b["formulas"].get(name)
        if callable(fm):
            try:
                fm = fm(meas)
            except (KeyError, TypeError, ZeroDivisionError):
                fm = None
        diff = None if sim is None or fm in (None, 0) or (isinstance(fm, float) and math.isnan(fm)) else abs(sim - fm) / abs(fm)
        rows.append({"name": name, "label": lab, "unit": unit, "sim": sim, "formula": fm, "diff": diff, "allow": allow,
                     "ok": diff is not None and diff <= allow})
    return rows


def simulate(key, params=None):
    """服务器把一道例题的每张网表跑一遍 → {meas（全部合在一起）, by_analysis, compare}"""
    b = build(key, params)
    allm, by = {}, {}
    for an, net in b["netlists"].items():
        r = run(net)
        by[an] = r
        allm.update(r["meas"])
    return {"meas": allm, "by_analysis": by, "compare": compare(key, b["params"], allm), "derived": b["derived"]}


def _scale(netlist, name, factor):
    """把元件 name 的值乘 factor（只认 'Rx a b 值' 这种两端元件）"""
    out = []
    for ln in netlist.split("\n"):
        t = ln.split()
        if t and t[0].lower() == name.lower() and len(t) >= 4:
            v = t[3]
            try:
                val = float(v)
            except ValueError:
                val = _spice_num(v)
            t[3] = "{:.9g}".format(val * factor)
            ln = " ".join(t)
        out.append(ln)
    return "\n".join(out)


SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}


def _spice_num(s):
    m = re.match(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(meg|[tgkmunpf])?", s, re.I)
    if not m:
        raise ValueError(s)
    return float(m.group(1)) * SUFFIX.get((m.group(2) or "").lower(), 1.0)


def montecarlo(key, params=None, n=200, seed=1):
    """元件按容差（均匀分布，±tol）随机取值，跑 n 次，统计一个读数：均值、标准差、最小、最大、3σ 区间、直方图"""
    import random
    b = build(key, params)
    mc = b.get("mc")
    if not mc:
        raise ValueError("这道题没有容差分析")
    n = max(10, min(int(n), 1000))
    rnd = random.Random(seed)
    base = b["netlists"][mc["analysis"]]
    vals = []
    for _ in range(n):
        net = base
        for el, tol in mc["tol"].items():
            net = _scale(net, el, 1 + rnd.uniform(-tol, tol))
        v = run(net, vectors=False)["meas"].get(mc["meas"])
        if v is not None:
            vals.append(v)
    m = sum(vals) / len(vals)
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / max(1, len(vals) - 1))
    lo, hi = min(vals), max(vals)
    bins = 20
    w = (hi - lo) / bins or 1.0
    hist = [0] * bins
    for x in vals:
        hist[min(bins - 1, int((x - lo) / w))] += 1
    nominal = run(base, vectors=False)["meas"].get(mc["meas"])
    return {"meas": mc["meas"], "n": len(vals), "seed": seed, "nominal": nominal, "mean": m, "std": sd, "min": lo, "max": hi,
            "lo3": m - 3 * sd, "hi3": m + 3 * sd, "hist": hist, "bin_lo": lo, "bin_w": w, "tol": mc["tol"]}
