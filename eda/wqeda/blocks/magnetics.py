# -*- coding: utf-8 -*-
"""定制磁性元件按理论选磁芯（第 159 轮 159d2b；Eddie 11-12：“无法选型就按理论”）。纯函数：不联网、不调 AI。

面积积法（McLyman《变压器与电感器设计手册》第 5、8 章；Erickson《电力电子学基础》第 14 章）：
    A_p = A_e · A_N ≥ L · I_峰 · I_有效 / (B_max · J · K_u)
    N = ⌈L · I_峰 / (B_max · A_e)⌉，气隙 l_g ≈ μ0 · N² · A_e / L
    （不计边缘磁通，偏保守：实际气隙要稍大，绕制厂按实测电感调）
    导线截面 A_w = I_有效 / J，窗口占用 = Σ N·A_w / A_N ≤ K_u；铜损 = I_有效² · ρ · N · l_N / A_w
B_max、J、K_u 是教材取值（设计描述 magnetics 里给，计算书逐行标“按理论”），磁芯数据来自 eda/parts（规格书）。
铁损要材料的损耗曲线，本版不算，判“未知”。"""

from __future__ import annotations

import math

from . import common as c

MU0 = 4e-7 * math.pi
RHO_CU_100C = 2.3e-8  # 铜 100 ℃ 电阻率 Ω·m（20 ℃ 1.72e-8 × (1 + 0.00393 × 80)，教材值）


def _rule(m):
    return "B_max {:g} T、J {:g} A/mm²、K_u {:g}（按理论，教材取值）".format(m["b_max"], m["j"] / 1e6, m["ku"])


def inductor(key_prefix, name, L, i_pk, i_rms, core, m, dev):
    """单绕组储能电感（升压电感）：返回 (items, checks)"""
    ae, an, ln = (dev.value(core, k) for k in ("ae", "an", "ln"))
    refs = [(core, "ae"), (core, "an"), (core, "ln")]
    src = "；".join(dict.fromkeys(dev.source(core, k) for k in ("ae", "an") if dev.source(core, k)))
    ap_need = L * i_pk * i_rms / (m["b_max"] * m["j"] * m["ku"])
    items = [
        c.item(
            key_prefix + "ap_need",
            name + "：要的面积积",
            ap_need * 1e8,
            "cm⁴",
            "A_p = L · I_峰 · I_有效 / (B_max · J · K_u)",
            note=_rule(m),
        )
    ]
    if None in (ae, an, ln):
        return items, [
            c.judge(
                key_prefix + "ap",
                name + "：磁芯面积积够",
                ap_need * 1e8,
                None,
                "cm⁴",
                "A_e · A_N ≥ 要的",
                status=c.UNKNOWN,
                note="{} 的磁芯数据没录".format(core),
            )
        ]
    n = math.ceil(L * i_pk / (m["b_max"] * ae))
    b_pk = L * i_pk / (n * ae)
    lg = MU0 * n**2 * ae / L
    aw = i_rms / m["j"]
    fill = n * aw / an
    p_cu = i_rms**2 * RHO_CU_100C * n * ln / aw
    items += [
        c.item(key_prefix + "ap", name + "：磁芯面积积", ae * an * 1e8, "cm⁴", "A_e · A_N", source=src, note=core),
        c.item(key_prefix + "n", name + "：匝数", n, "匝", "N = ⌈L · I_峰 / (B_max · A_e)⌉"),
        c.item(
            key_prefix + "lg",
            name + "：气隙（总）",
            lg * 1e3,
            "mm",
            "l_g ≈ μ0 · N² · A_e / L",
            note="不计边缘磁通，绕制厂按实测电感调",
        ),
        c.item(key_prefix + "b_pk", name + "：峰值磁密", b_pk, "T", "B = L · I_峰 / (N · A_e)"),
        c.item(
            key_prefix + "aw", name + "：导线截面", aw * 1e6, "mm²", "A_w = I_有效 / J", note="用多股绞线（利兹线）"
        ),
        c.item(
            key_prefix + "p_cu",
            name + "：铜损（100 ℃）",
            p_cu,
            "W",
            "I² · ρ · N · l_N / A_w",
            note="不含高频趋肤、邻近效应",
        ),
    ]
    checks = [
        c.judge(
            key_prefix + "ap",
            name + "：磁芯面积积够",
            ap_need * 1e8,
            ae * an * 1e8,
            "cm⁴",
            "A_e · A_N ≥ 要的",
            status=_st(dev, refs, ae * an >= ap_need),
        ),
        c.judge(
            key_prefix + "fill",
            name + "：窗口放得下",
            fill,
            m["ku"],
            "",
            "N · A_w / A_N ≤ K_u",
            status=_st(dev, refs, fill <= m["ku"]),
        ),
        c.judge(
            key_prefix + "p_fe",
            name + "：铁损",
            None,
            None,
            "W",
            "要材料损耗曲线",
            status=c.UNKNOWN,
            note="铁损要磁芯材料的损耗曲线（N87 的 Steinmetz 系数），本版没录",
        ),
    ]
    return items, checks


def flyback(key_prefix, name, lp, ip, d, outs, vor, vf, core, m, dev):
    """断续反激变压器：初级 N_p 按 B_max，次级按匝比；窗口按各绕组电流有效值分（三角波 I_rms = I_峰 · √(D/3)）"""
    ae, an, ln = (dev.value(core, k) for k in ("ae", "an", "ln"))
    refs = [(core, "ae"), (core, "an"), (core, "ln")]
    ip_rms = ip * math.sqrt(d / 3)
    ap_need = lp * ip * ip_rms / (m["b_max"] * m["j"] * m["ku"])
    items = [
        c.item(
            key_prefix + "ap_need",
            name + "：要的面积积",
            ap_need * 1e8,
            "cm⁴",
            "A_p = L_p · I_p · I_p,有效 / (B_max · J · K_u)",
            note=_rule(m) + "；I_p,有效 = I_p · √(D/3)",
        )
    ]
    if None in (ae, an, ln):
        return items, [
            c.judge(
                key_prefix + "ap",
                name + "：磁芯面积积够",
                ap_need * 1e8,
                None,
                "cm⁴",
                "A_e · A_N ≥ 要的",
                status=c.UNKNOWN,
            )
        ]
    np_ = math.ceil(lp * ip / (m["b_max"] * ae))
    lg = MU0 * np_**2 * ae / lp
    area = np_ * ip_rms / m["j"]
    turns = []
    for o in outs:
        ns = max(1, round(np_ * (o["v"] + vf) / vor))
        # 次级三角波：峰值 = I_p · N_p/N_s，导通占 (1 − D) 以内，有效值按 √((1 − D)/3) 上限估
        is_rms = ip * np_ / ns * math.sqrt((1 - d) / 3)
        area += ns * is_rms / m["j"]
        turns.append("{} {} 匝".format(o["name"].split("（")[0], ns))
    fill = area / an
    items += [
        c.item(
            key_prefix + "ap",
            name + "：磁芯面积积",
            ae * an * 1e8,
            "cm⁴",
            "A_e · A_N",
            source=dev.source(core, "ae"),
            note=core,
        ),
        c.item(
            key_prefix + "np",
            name + "：初级匝数",
            np_,
            "匝",
            "N_p = ⌈L_p · I_p / (B_max · A_e)⌉",
            note="次级：" + "、".join(turns),
        ),
        c.item(
            key_prefix + "lg",
            name + "：气隙（总）",
            lg * 1e3,
            "mm",
            "l_g ≈ μ0 · N_p² · A_e / L_p",
            note="绕制厂按实测电感调",
        ),
        c.item(key_prefix + "fill", name + "：窗口占用", fill, "", "Σ N · I_有效 / J / A_N"),
    ]
    checks = [
        c.judge(
            key_prefix + "ap",
            name + "：磁芯面积积够",
            ap_need * 1e8,
            ae * an * 1e8,
            "cm⁴",
            "A_e · A_N ≥ 要的",
            status=_st(dev, refs, ae * an >= ap_need),
        ),
        c.judge(
            key_prefix + "fill",
            name + "：窗口放得下",
            fill,
            m["ku"],
            "",
            "占用 ≤ K_u",
            status=_st(dev, refs, fill <= m["ku"]),
        ),
    ]
    return items, checks


def rcd_clamp(lp, ip, f, vc, vor, llk_ratio):
    """RCD 钳位（按理论）：漏感取初级电感的一个比例（教材经验值），
    P = ½ · L_lk · I_p² · f · V_c / (V_c − V_OR)，R = V_c² / P，
    C 让钳位电压纹波 ≤ 10 %：C ≥ V_c / (0.1 · V_c · R · f) = 10 / (R · f)"""
    llk = lp * llk_ratio
    p = 0.5 * llk * ip**2 * f * vc / (vc - vor)
    r = vc**2 / p
    cmin = 10 / (r * f)
    return {"llk": llk, "p": p, "r": r, "c_min": cmin}


def _st(dev, refs, ok):
    if any(not dev.checked(p, k) for p, k in refs):
        return c.PENDING
    return c.PASS if ok else c.FAIL
