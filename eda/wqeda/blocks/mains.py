# -*- coding: utf-8 -*-
"""交流输入的功能块（第 159 轮 159b，平缝机控制器 CTRL-LS）：
交流输入与浪涌、整流桥、连续导通升压功率因数校正、反激辅助电源、散热器。

全是计算器（纯函数：不联网、不调 AI）。器件参数一律从 eda/parts/ 读（parts.Devices），带出处；
没录的判“未知”，录了没核对的判“待核对”。
公式在每一行的 formula 里写明；效率、功率因数等没有器件数据可依的量来自设计描述 spec（标“假设”），
不在这里编。
各块算出的损耗记进 d["losses"]，散热器块（放在最后）按它们算要多大的散热器。"""

from __future__ import annotations

import math

from . import common as c
from . import magnetics

SQ2 = math.sqrt(2.0)


def stat(dev, refs, ok):
    """一条判定用到若干器件参数：任何一个没录 → 未知；都录了但有没核对的 → 待核对；否则按 ok 判"""
    for part, key in refs:
        if dev.value(part, key) is None and not (dev._p(part, key) or {}).get("max"):
            return c.UNKNOWN
    if ok is None:
        return c.UNKNOWN
    if any(not dev.checked(part, key) for part, key in refs):
        return c.PENDING
    return c.PASS if ok else c.FAIL


def src(dev, refs):
    return "；".join(dict.fromkeys(dev.source(p, k) for p, k in refs if dev.source(p, k)))


def le(dev, key, name, x, limit, unit, rule, refs, note=""):
    """x ≤ limit 的判定（limit 来自器件数据）：表里写成 要求 = x、实有 = limit，实有 ≥ 要求为过"""
    ok = None if x is None or limit is None else limit >= x - 1e-12
    return c.judge(key, name, x, limit, unit, rule, status=stat(dev, refs, ok), source=src(dev, refs), note=note)


def power_budget(spec):
    """母线功率与交流输入功率（spec 里的效率、功率因数是假设值）"""
    p_bus = spec["motor_power_w"] / spec["eta_motor"] / spec["eta_inverter"] + spec["aux_power_w"]
    p_in = p_bus / spec["eta_pfc"]
    vmin = spec["vin_min_vac"]
    i_in = p_in / (vmin * spec["power_factor"])
    return {"p_bus": p_bus, "p_in": p_in, "i_in": i_in, "i_in_pk": SQ2 * i_in}


def _losses(d):
    return d.setdefault("losses", {})


# ------------------------------------------------------------------------------------------------- 交流输入与浪涌


def calc_ac_input(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    pb = power_budget(spec)
    vmax = spec["vin_max_vac"]
    vpk_max = SQ2 * vmax * (1 + spec["line_tolerance"])
    r25 = dev.value(p["ntc"], "r25")
    c_bus = spec["c_bus_f"]
    items = [
        c.item(
            "p_bus",
            "母线功率",
            pb["p_bus"],
            "W",
            "P_母线 = P_电机 / η_电机 / η_逆变 + P_辅助",
            note="η_电机 {:g}、η_逆变 {:g} 是假设值".format(spec["eta_motor"], spec["eta_inverter"]),
        ),
        c.item(
            "p_in",
            "交流输入功率",
            pb["p_in"],
            "W",
            "P_输入 = P_母线 / η_校正",
            note="η_校正 {:g} 是假设值".format(spec["eta_pfc"]),
        ),
        c.item(
            "i_in",
            "输入电流有效值（最低电压）",
            pb["i_in"],
            "A",
            "I = P_输入 / (V_最低 · PF)",
            note="V_最低 {:g} V，PF {:g}（假设）".format(spec["vin_min_vac"], spec["power_factor"]),
        ),
        c.item("vpk_max", "输入峰值（最高电压加波动）", vpk_max, "V", "√2 · V_最高 · (1 + 波动)"),
    ]
    if r25:
        items.append(
            c.item(
                "i_inrush",
                "上电浪涌电流峰值（热敏电阻冷态）",
                vpk_max / r25,
                "A",
                "I = V_峰 / R_25",
                source=dev.source(p["ntc"], "r25"),
                note=dev.note(p["ntc"], "r25"),
            )
        )
    fuse, ntc = p["fuse"], p["ntc"]
    checks = [
        dev.judge(fuse, "v_rated", "保险丝额定电压", vmax, "V", "额定电压 ≥ 最高输入电压"),
        dev.judge(
            fuse, "i_rated", "保险丝额定电流", pb["i_in"] * m["fuse"], "A", "I_额定 ≥ {:g} × I_输入".format(m["fuse"])
        ),
        dev.judge(
            p["mov"],
            "v_rms",
            "压敏电阻最高工作电压",
            vmax * (1 + spec["line_tolerance"]),
            "V",
            "V_RMS ≥ 最高输入电压 ×（1 + 波动）",
        ),
        dev.judge(
            p["x_cap"],
            "v_ac_rated",
            "X 电容额定电压",
            vmax * (1 + spec["line_tolerance"]),
            "V",
            "额定 ≥ 最高输入电压 ×（1 + 波动）",
        ),
        dev.judge(ntc, "i_max", "热敏电阻最大电流", pb["i_in"], "A", "I_max ≥ I_输入（继电器旁路前）"),
        dev.judge(ntc, "ct_230", "热敏电阻允许的负载电容（230 V）", c_bus, "F", "C_T ≥ 母线电容"),
        dev.judge(
            p["relay"],
            "contact_a_250vac",
            "旁路继电器触点电流",
            pb["i_in"] * m["fuse"],
            "A",
            "触点额定 ≥ {:g} × I_输入".format(m["fuse"]),
        ),
        dev.judge(p["cmc"], "i_rated", "共模电感额定电流", pb["i_in"], "A", "额定（温升约 35 ℃）≥ I_输入"),
        # 159d2：继电器线圈 12 V 用在 15 V 辅助电源上
        dev.judge(
            p["relay"],
            "coil_v_max_pct",
            "继电器线圈电压（12 V 线圈接 15 V）",
            100 * spec["vcc_aux_v"] / p["relay_coil_v"],
            "%",
            "最高允许电压（额定的 %）≥ 15 V / 12 V",
        ),
    ]
    return items, checks


# ------------------------------------------------------------------------------------------------- 整流桥


def calc_bridge(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    br = p["bridge"]
    pb = power_budget(spec)
    i_avg = 2 * SQ2 / math.pi * pb["i_in"]  # 全波整流后的平均电流
    vf = dev.value(br, "vf_10a")
    loss = None if vf is None else 2 * vf * i_avg  # 任一时刻两只二极管导通
    if loss is not None:
        _losses(d)[block["key"] + ":bridge"] = {
            "p": loss,
            "rjc": dev.value(br, "rth_jc_leg"),
            "split": 4,
            "tj_max": dev.value(br, "tj_max"),
            "name": "整流桥 " + br,
            "refs": [(br, "vf_10a"), (br, "rth_jc_leg"), (br, "tj_max")],
        }
    vrr = SQ2 * spec["vin_max_vac"] * (1 + spec["line_tolerance"])
    i_inrush = None
    r25 = dev.value(p["ntc"], "r25")
    if r25:
        i_inrush = vrr / r25
    items = [
        c.item("i_avg", "整流后平均电流", i_avg, "A", "I_平均 = 2√2/π · I_输入"),
        c.item(
            "p_loss",
            "整流桥损耗",
            loss,
            "W",
            "P = 2 · V_F · I_平均（任一时刻两只导通）",
            source=dev.source(br, "vf_10a"),
            note="V_F 取 10 A 时的最大值，偏保守",
        ),
    ]
    checks = [
        dev.judge(br, "vrrm", "反向耐压", vrr * m["diode"], "V", "V_RRM ≥ {:g} × 输入峰值".format(m["diode"])),
        dev.judge(br, "if_av_100c", "平均整流电流（壳温 100 ℃ 额定）", i_avg, "A", "I_F(AV) ≥ I_平均"),
        c.judge(
            "ifsm",
            "浪涌电流",
            i_inrush,
            dev.value(br, "ifsm"),
            "A",
            "I_FSM ≥ 上电浪涌（热敏电阻冷态）",
            status=stat(
                dev,
                [(br, "ifsm"), (p["ntc"], "r25")],
                None if i_inrush is None or dev.value(br, "ifsm") is None else dev.value(br, "ifsm") >= i_inrush,
            ),
            source=src(dev, [(br, "ifsm"), (p["ntc"], "r25")]),
        ),
    ]
    return items, checks


# ------------------------------------------------------------------------------------------------- 升压功率因数校正


def pfc(spec, p, dev):
    """连续导通升压的主要量（Erickson 第 18 章的式子；电流取最低输入电压时）"""
    vo = spec["bus_voltage_v"]
    po = spec["motor_power_w"] / spec["eta_motor"] / spec["eta_inverter"] + spec["aux_power_w"]
    pin = po / spec["eta_pfc"]
    vin = spec["vin_min_vac"]
    iin = pin / vin  # 校正后功率因数按 1 算电流波形（最低电压）
    ipk = SQ2 * iin
    f = p["f_sw"]
    di = p["ripple_ratio"] * ipk
    # 纹波最大处：V_输入,瞬时 = V_o / 2；在输入范围内时 L 按它取，否则按最低电压峰值
    v_lo, v_hi = SQ2 * vin, SQ2 * spec["vin_max_vac"] * (1 + spec["line_tolerance"])
    vx = vo / 2 if v_lo <= vo / 2 <= v_hi else v_lo
    L = vx * (1 - vx / vo) / (f * di)
    i_l_pk = ipk + di / 2
    i_d_rms2 = 8 * SQ2 * iin**2 * vin / (3 * math.pi * vo)
    i_q_rms = iin * math.sqrt(max(0.0, 1 - 8 * SQ2 * vin / (3 * math.pi * vo)))
    io = po / vo
    i_c_rms = math.sqrt(max(0.0, i_d_rms2 - io**2))
    return {
        "vo": vo,
        "po": po,
        "pin": pin,
        "iin": iin,
        "ipk": ipk,
        "di": di,
        "L": L,
        "vx": vx,
        "i_l_pk": i_l_pk,
        "i_q_rms": i_q_rms,
        "i_d_rms": math.sqrt(i_d_rms2),
        "io": io,
        "i_c_rms": i_c_rms,
    }


def calc_pfc_boost(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    ctl, q, dd, cap = p["controller"], p["fet"], p["diode"], p["cap"]
    r = pfc(spec, p, dev)
    vo, f = r["vo"], p["f_sw"]
    n_caps = p["n_caps"]
    c1 = dev.value(cap, "c")
    c_tot = None if c1 is None else n_caps * c1
    # 电流采样电阻：峰值限流阈值（最小幅值）对应的电流 ≥ 余量 × 电感峰值电流
    v_pcl = dev.value(ctl, "v_pcl_min")
    r_shunt_max = None if v_pcl is None else v_pcl / (p["pcl_margin"] * r["i_l_pk"])
    r_shunt = c.parse(p["r_shunt"])
    # 开关管：导通损耗按 150 ℃ 典型值 × 25 ℃ 的 最大/典型 之比；
    # 开关损耗 = 交叠（规格书 t_r、t_f）+ 输出电容能量 + 二极管容性电荷
    rq150, rq25, rq25t = dev.value(q, "rds_on_typ_150c"), dev.value(q, "rds_on_max"), dev.value(q, "rds_on_typ_25c")
    r_hot = None if None in (rq150, rq25, rq25t) else rq150 * rq25 / rq25t
    p_q_cond = None if r_hot is None else r["i_q_rms"] ** 2 * r_hot
    tr, tf, eoss, qc = dev.value(q, "tr"), dev.value(q, "tf"), dev.value(q, "eoss_400v"), dev.value(dd, "qc")
    i_sw_avg = 2 * SQ2 / math.pi * r["iin"]
    p_q_sw = None if None in (tr, tf, eoss, qc) else (0.5 * vo * i_sw_avg * (tr + tf) + eoss + qc * vo) * f
    p_q = None if None in (p_q_cond, p_q_sw) else p_q_cond + p_q_sw
    vf = dev.value(dd, "vf_max_hot")
    p_d = None if vf is None else vf * r["io"]
    p_r = r["i_q_rms"] ** 2 * r_shunt
    if p_q is not None:
        _losses(d)[block["key"] + ":fet"] = {
            "p": p_q,
            "rjc": dev.value(q, "rth_jc"),
            "split": 1,
            "tj_max": dev.value(q, "tj_max"),
            "name": "升压开关管 " + q,
            "refs": [(q, "rth_jc"), (q, "tj_max")],
        }
    if p_d is not None:
        _losses(d)[block["key"] + ":diode"] = {
            "p": p_d,
            "rjc": dev.value(dd, "rth_jc"),
            "split": 1,
            "tj_max": dev.value(dd, "tj_max"),
            "name": "升压二极管 " + dd,
            "refs": [(dd, "rth_jc"), (dd, "tj_max")],
        }
    # 母线：二倍工频纹波、保持时间、分压
    # 电容电流 = I_o·cos(2ωt)：幅值 I_o/(2ω·C)，峰峰值翻倍 → ΔV = P_o / (2π·f_工频·C·V_o)
    # （159c 仿真核对时发现原来少乘了 2，改正）
    fl = spec["f_line_min_hz"]
    dv = None if c_tot is None else r["po"] / (2 * math.pi * fl * c_tot * vo)
    t_hold = None if c_tot is None else c_tot * (vo**2 - p["v_holdup_min"] ** 2) / (2 * r["po"])
    vref = dev.value(ctl, "v_vsref")
    rb = c.parse(p["r_vs_bottom"])
    r_top = None if vref is None else rb * (vo / vref - 1)
    v_ovp = vo * 1.08  # 控制器 OVP1 = 108 % 额定母线（规格书 4.3.6）
    items = [
        c.item("iin", "输入电流有效值（最低电压）", r["iin"], "A", "I = P_输入 / V_最低（校正后按纯正弦）"),
        c.item("i_pk", "输入电流峰值", r["ipk"], "A", "√2 · I"),
        c.item(
            "di",
            "电感电流纹波（峰峰）",
            r["di"],
            "A",
            "ΔI = 纹波系数 × I_峰",
            note="纹波系数 {:g}".format(p["ripple_ratio"]),
        ),
        c.item(
            "L",
            "升压电感（最少）",
            r["L"],
            "H",
            "L = V_x(1 − V_x/V_o) / (f · ΔI)，V_x 取纹波最大处 V_o/2",
            note="V_x = {:.0f} V，f = {:g} kHz（规格书 R_FREQ = 67 kΩ 时的典型值）".format(r["vx"], f / 1000),
        ),
        c.item("i_l_pk", "电感峰值电流", r["i_l_pk"], "A", "I_峰 + ΔI/2"),
        c.item(
            "r_shunt_max",
            "电流采样电阻上限",
            r_shunt_max,
            "Ω",
            "R ≤ |V_PCL,min| / (余量 × I_L峰)",
            source=dev.source(ctl, "v_pcl_min"),
            note="余量 {:g}；选 {}".format(p["pcl_margin"], p["r_shunt"]),
        ),
        c.item("i_q_rms", "开关管电流有效值", r["i_q_rms"], "A", "I_Q = I · √(1 − 8√2·V_in/(3π·V_o))"),
        c.item(
            "r_hot",
            "开关管高温导通电阻",
            r_hot,
            "Ω",
            "R_150℃,典型 × R_25℃,最大 / R_25℃,典型",
            source=dev.source(q, "rds_on_typ_150c"),
        ),
        c.item("p_q_cond", "开关管导通损耗", p_q_cond, "W", "I_Q² · R_高温"),
        c.item(
            "p_q_sw",
            "开关管开关损耗",
            p_q_sw,
            "W",
            "(½·V_o·I_平均·(t_r + t_f) + E_oss + Q_c·V_o) · f",
            source=src(dev, [(q, "tr"), (q, "eoss_400v"), (dd, "qc")]),
            note="t_r、t_f 是规格书 5.6 A 时的典型值，按工频平均电流估",
        ),
        c.item("p_d", "升压二极管导通损耗", p_d, "W", "V_F(175 ℃ 最大) · I_o", source=dev.source(dd, "vf_max_hot")),
        c.item("p_shunt", "采样电阻损耗", p_r, "W", "I_Q² · R"),
        c.item(
            "i_c_rms",
            "母线电容纹波电流（校正级产生）",
            r["i_c_rms"],
            "A",
            "√(I_D,rms² − I_o²)，I_D,rms² = 8√2·I²·V_in/(3π·V_o)",
        ),
        c.item(
            "dv_bus",
            "母线二倍工频纹波（峰峰）",
            dv,
            "V",
            "ΔV = P_o / (2π · f_工频 · C · V_o)（峰峰）",
            note="f_工频取 {:g} Hz".format(spec["f_line_min_hz"]),
        ),
        c.item(
            "t_hold",
            "掉电保持时间（降到 {:g} V）".format(p["v_holdup_min"]),
            t_hold,
            "s",
            "t = C·(V_o² − V_min²) / (2·P_o)",
        ),
        c.item(
            "r_vs_top",
            "母线分压上臂",
            r_top,
            "Ω",
            "R_上 = R_下 · (V_o / V_VSREF − 1)",
            source=dev.source(ctl, "v_vsref"),
            note="R_下 = {}".format(p["r_vs_bottom"]),
        ),
        c.item("v_ovp", "过压保护动作的母线电压", v_ovp, "V", "1.08 × V_o（OVP1 = 108 % 额定，规格书 4.3.6）"),
    ]
    checks = [
        dev.in_range(ctl, "f_sw_range", "开关频率在控制器范围内", f, "Hz"),
        c.judge(
            "r_shunt",
            "采样电阻不大于上限",
            r_shunt,
            r_shunt_max,
            "Ω",
            "R ≤ 上限",
            source=dev.source(ctl, "v_pcl_min"),
            status=stat(dev, [(ctl, "v_pcl_min")], None if r_shunt_max is None else r_shunt <= r_shunt_max),
        ),
        dev.judge(q, "vds", "开关管耐压", v_ovp * m["mosfet"], "V", "V_DS ≥ {:g} × 过压点".format(m["mosfet"])),
        dev.judge(q, "id_100c", "开关管电流（壳温 100 ℃）", r["i_l_pk"], "A", "I_D(100℃) ≥ 电感峰值电流"),
        dev.judge(dd, "vrrm", "升压二极管耐压", v_ovp * m["diode"], "V", "V_RRM ≥ {:g} × 过压点".format(m["diode"])),
        dev.judge(dd, "if_135c", "升压二极管电流（壳温 135 ℃）", r["io"], "A", "I_F ≥ I_o"),
        dev.judge(
            cap, "v_rated", "母线电容耐压", vo * m["capacitor"], "V", "V_额定 ≥ {:g} × V_o".format(m["capacitor"])
        ),
        dev.judge(cap, "v_rated", "母线电容耐压（过压点）", v_ovp, "V", "V_额定 ≥ 过压保护点"),
        c.judge(
            "ripple",
            "母线电容纹波电流",
            r["i_c_rms"],
            None if dev.value(cap, "ripple_120hz_105c") is None else n_caps * dev.value(cap, "ripple_120hz_105c"),
            "A",
            "{} 只 × 额定（120 Hz，偏保守）≥ I_C".format(n_caps),
            status=stat(
                dev,
                [(cap, "ripple_120hz_105c")],
                None
                if dev.value(cap, "ripple_120hz_105c") is None
                else n_caps * dev.value(cap, "ripple_120hz_105c") >= r["i_c_rms"],
            ),
            source=dev.source(cap, "ripple_120hz_105c"),
        ),
        c.judge(
            "dv_bus",
            "母线纹波不超过要求",
            dv,
            p["dv_bus_max"],
            "V",
            "ΔV ≤ {:g} V".format(p["dv_bus_max"]),
            status=stat(dev, [(cap, "c")], None if dv is None else dv <= p["dv_bus_max"]),
            source=dev.source(cap, "c"),
        ),
        c.judge(
            "t_hold",
            "掉电保持时间",
            p["t_hold_min_s"],
            t_hold,
            "s",
            "t ≥ {:g} s".format(p["t_hold_min_s"]),
            status=stat(dev, [(cap, "c")], None if t_hold is None else t_hold >= p["t_hold_min_s"]),
            source=dev.source(cap, "c"),
        ),
        dev.judge(ctl, "vcc_abs", "控制器供电绝对最大值", spec["vcc_aux_v"], "V", "V_CC,max ≥ 辅助 15 V"),
    ]
    if p.get("core"):  # 159d2b：定制电感按理论选磁芯
        mi, mc = magnetics.inductor("l_", "升压电感", r["L"], r["i_l_pk"], r["iin"], p["core"], spec["magnetics"], dev)
        items += mi
        checks += mc
    return items, checks


# ------------------------------------------------------------------------------------------------- 反激辅助电源


def fly(spec, p):
    """断续反激的主要量（计算器和生成器共用）"""
    po = sum(o["v"] * o["i"] for o in p["outputs"])
    pin = po / p["eta"]
    vmin = SQ2 * spec["vin_min_vac"] * (1 - spec["line_tolerance"])  # 校正级没起来时，从整流后的峰值取电
    vmax = spec["bus_voltage_v"] * 1.08
    vor, f = p["v_or"], p["f_sw"]
    dmax = vor / (vor + vmin)
    i_pk = 2 * pin / (vmin * dmax)  # 断续模式三角波
    lp = vmin * dmax / (i_pk * f)
    return {"po": po, "pin": pin, "vmin": vmin, "vmax": vmax, "vor": vor, "f": f, "dmax": dmax, "i_pk": i_pk, "lp": lp}


def calc_flyback_aux(block, spec, d, parts):
    p, m, dev = block["params"], d["derating"], d["devices"]
    ic, dout = p["ic"], p["out_diode"]
    outs = p["outputs"]
    fl = fly(spec, p)
    keys = ("po", "pin", "vmin", "vmax", "vor", "f", "dmax", "i_pk", "lp")
    po, pin, vmin, vmax, vor, f, dmax, i_pk, lp = (fl[k] for k in keys)
    main = outs[0]
    n = vor / (main["v"] + p["vf_out"])
    v_ds = vmax + p["v_clamp"]
    v_rev = main["v"] + vmax / n
    items = [
        c.item(
            "po",
            "输出功率（各路平均负载之和）",
            po,
            "W",
            "Σ V·I",
            note="负载是设计给定的示例值：" + "、".join("{} {:g} A".format(o["name"], o["i"]) for o in outs),
        ),
        c.item("pin", "输入功率", pin, "W", "P_o / η", note="η {:g} 是假设值".format(p["eta"])),
        c.item("vmin", "最低输入直流", vmin, "V", "√2 · V_最低 · (1 − 波动)（校正级未工作时）"),
        c.item(
            "dmax", "最低输入时占空比", dmax, "", "D = V_OR / (V_OR + V_min)", note="反射电压 V_OR = {:g} V".format(vor)
        ),
        c.item("i_pk", "初级峰值电流", i_pk, "A", "I_p = 2·P_in / (V_min · D)（断续）"),
        c.item("lp", "初级电感（最多）", lp, "H", "L_p = V_min · D / (I_p · f)", note="f = {:g} kHz".format(f / 1000)),
        c.item("n", "匝比 N_p : N_24V", n, "", "n = V_OR / (V_o + V_F)"),
        c.item("v_ds", "开关管最高漏极电压", v_ds, "V", "过压点 + 钳位电压", note="钳位 {:g} V".format(p["v_clamp"])),
        c.item("v_rev", "24 V 整流管反向电压", v_rev, "V", "V_o + V_max / n"),
    ]
    checks = [
        dev.judge(ic, "p_open_wide", "芯片功率（85–265 V 开放式）", po, "W", "P_表 ≥ P_o（校正级未起时按宽电压栏）"),
        le(
            dev,
            "i_pk",
            "初级峰值电流低于限流",
            i_pk * p["ilim_margin"],
            dev.value(ic, "ilimit_min"),
            "A",
            "{:g} × I_p ≤ I_LIMIT,min".format(p["ilim_margin"]),
            [(ic, "ilimit_min")],
        ),
        le(
            dev,
            "dmax",
            "占空比低于最大占空比",
            dmax,
            dev.value(ic, "dc_max_min"),
            "",
            "D ≤ DC_MAX,min",
            [(ic, "dc_max_min")],
        ),
        dev.judge(
            ic, "bvdss", "开关管耐压", v_ds * m["mosfet"], "V", "BV_DSS ≥ {:g} × (过压点 + 钳位)".format(m["mosfet"])
        ),
        c.judge(
            "clamp",
            "钳位电压高于反射电压",
            vor * p["clamp_ratio_min"],
            p["v_clamp"],
            "V",
            "V_钳位 ≥ {:g} × V_OR".format(p["clamp_ratio_min"]),
        ),
        dev.judge(
            dout, "vrrm", "24 V 整流管耐压", v_rev * m["diode"], "V", "V_RRM ≥ {:g} × 反向电压".format(m["diode"])
        ),
        dev.judge(dout, "if_av", "24 V 整流管电流", main["i"], "A", "I_F(AV) ≥ 24 V 平均电流"),
    ]
    if p.get("core"):  # 159d2b：定制变压器按理论选磁芯；RCD 钳位按理论（漏感取初级电感的比例）
        mg = dict(spec["magnetics"], ku=p.get("ku", spec["magnetics"]["ku"]))
        mi, mc = magnetics.flyback("t_", "反激变压器", lp, i_pk, dmax, outs, vor, p["vf_out"], p["core"], mg, dev)
        items += mi
        checks += mc
    if p.get("llk_ratio"):
        cl = magnetics.rcd_clamp(lp, i_pk, f, p["v_clamp"], vor, p["llk_ratio"])
        items += [
            c.item("llk", "漏感（按理论）", cl["llk"], "H", "L_lk = 比例 × L_p",
                   note="比例 {:g}（教材经验值 1–3 %，按样机实测改）".format(p["llk_ratio"])),
            c.item("p_clamp", "钳位电阻功耗", cl["p"], "W", "½ · L_lk · I_p² · f · V_c / (V_c − V_OR)"),
            c.item("r_clamp", "钳位电阻（最多）", cl["r"], "Ω", "R = V_c² / P"),
            c.item("c_clamp", "钳位电容（最少）", cl["c_min"], "F", "C ≥ 10 / (R · f)（钳位电压纹波 ≤ 10 %）"),
        ]
    return items, checks


# ------------------------------------------------------------------------------------------------- 散热器（放在最后）


def calc_heatsink(block, spec, d, parts):
    """前面各块记下的损耗 → 共用一块散热器要多小的热阻。
    每个器件：T_j = T_s + P_芯片·R_jc + P·R_cs ≤ T_j,max − 余量；功率模块另限壳温。"""
    p, dev = block["params"], d["devices"]
    ta, margin, rcs = spec["ambient_c"], spec["tj_margin_c"], p["r_cs"]
    losses = d.get("losses") or {}
    total = sum(x["p"] for x in losses.values())
    items = [
        c.item(
            "p_total",
            "装在散热器上的总损耗",
            total,
            "W",
            "Σ 各器件损耗",
            note="、".join("{} {:.2f} W".format(x["name"], x["p"]) for x in losses.values()),
        )
    ]
    limits, refs = [], []
    for x in losses.values():
        refs += x["refs"]
        if x["rjc"] is None or x["tj_max"] is None:
            continue
        p_chip = x.get("p_chip", x["p"] / x["split"])  # 热阻 R_jc 对应的那一颗芯片的损耗
        ts_allow = x["tj_max"] - margin - p_chip * x["rjc"] - x["p"] * rcs
        limits.append(ts_allow)
        items.append(
            c.item(
                "ts_" + x["name"],
                "散热器温度上限（{}，按结温）".format(x["name"]),
                ts_allow,
                "℃",
                "T_j,max − 余量 − P_芯片·R_jc − P·R_cs",
                note="P_芯片 {:.2f} W".format(p_chip),
            )
        )
        if x.get("tc_max") is not None:  # 器件还限壳温（如功率模块的推荐壳温）
            ts_case = x["tc_max"] - x["p"] * rcs
            limits.append(ts_case)
            items.append(
                c.item(
                    "tsc_" + x["name"],
                    "散热器温度上限（{}，按壳温）".format(x["name"]),
                    ts_case,
                    "℃",
                    "T_c,max − P·R_cs",
                    note="T_c,max {:g} ℃".format(x["tc_max"]),
                )
            )
    ts = min(limits) if limits else None
    r_sa = None if ts is None or total <= 0 else (ts - ta) / total
    items.append(
        c.item(
            "r_sa",
            "散热器热阻要求（散热器到空气）",
            r_sa,
            "K/W",
            "(T_s,允许 − T_环境) / P_总",
            note="电控箱内环境 {:g} ℃（示例），导热垫 R_cs {:g} K/W（示例）".format(ta, rcs),
        )
    )
    checks = [
        c.judge(
            "r_sa",
            "选的散热器热阻够小",
            p["r_sa_selected"],
            r_sa,
            "K/W",
            "R_sa,要求 ≥ R_sa,选用",
            status=stat(dev, refs, None if r_sa is None else r_sa >= p["r_sa_selected"]),
            note="选用值 {:g} K/W 是设计给定（散热器型号在 159d 定）".format(p["r_sa_selected"]),
        )
    ]
    return items, checks
