# -*- coding: utf-8 -*-
"""工艺路线的计算库（第 13 轮十二（3）；《机械制造技术》第 56 章，书、实验和 AI 工艺评审员共用）。

- 加工方案链：由一个表面的要求（公差等级 IT、粗糙度 Ra、是否淬硬后加工）从加工方法表（std/route_methods.yaml，
  工厂工艺标准）倒推出可行的方案链，并检查一条已有的方案链（最后一环够不够、有没有“跳级”、淬硬后用的方法能不能加工淬硬钢）；
- 路线的节拍与成本：按每道工序的单件工时、准备与终结时间和工作中心的小时费率（factory/data.py WORKSTATIONS）
  算单件时间、瓶颈、单件成本，以及两条路线的临界批量。成本只算机床与人工（第 57 章再加材料、刀具、工装）。
"""
from __future__ import annotations

import itertools
import math
import os

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
STD = os.path.join(HERE, "..", "std")
HEAT_DISTORT = 1        # 渗碳淬火的变形使精度降低约一级（热处理后不再精加工的表面，热处理前要高一级；示意）
HEAT_RA = 1.6           # 热处理后不再加工的表面，粗糙度要求不能高于 Ra 1.6（氧化皮、变形；齿面另按精度等级）
BLANK_IT = {"热轧圆钢": 14, "模锻件": 15, "自由锻件": 16, "铸件": 15}     # 毛坯表面相当的公差等级（示意：棒料直径公差约 IT14）


def _load():
    with open(os.path.join(STD, "route_methods.yaml"), encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return {r["key"]: r for r in d["rows"]}, d


METHODS, TABLE = _load()


def label():
    return TABLE["standard"]["short"]


def methods(feature):
    """某类表面（外圆、孔、平面、齿面、键槽）的加工方法，由粗到精。"""
    return sorted((r for r in METHODS.values() if r["feature"] == feature), key=lambda r: (-r["IT_max"], -r["IT_min"]))


def it_grade(size_mm, tol_mm):
    """尺寸 size 的公差 tol 相当的 IT 等级（GB/T 1800.1，取公差不大于它的最粗等级）。"""
    try:
        from hub import process
    except ImportError:          # hub 目录本身在 sys.path 上
        import process
    return process.it_grade(size_mm, tol_mm)


def check_chain(keys, it, ra=None, hardened_from=None, blank="热轧圆钢", grades=None):
    """检查一条方案链（方法代号的列表，由粗到精）。hardened_from：从第几环起是在淬硬以后（None 表示不淬硬）；
    grades：各环实际规定的公差等级（工艺规程里的工序尺寸公差；不给就按各方法经济精度的下限 IT_max 估计）。
    返回问题清单 [str]（空表示可行）。"""
    out = []
    prev_it = BLANK_IT.get(blank, 14)
    for i, k in enumerate(keys):
        m = METHODS[k]
        fol = m.get("follows") or []
        if i == 0 and fol:
            out.append("{}不能做第一道（它要接在{}之后）".format(m["method_zh"], "、".join(METHODS[x]["method_zh"] for x in fol)))
        elif i > 0 and keys[i - 1] not in fol:
            out.append("{}一般不接在{}之后".format(m["method_zh"], METHODS[keys[i - 1]]["method_zh"]))
        g = grades[i] if grades and i < len(grades) and grades[i] is not None else None
        if g is not None and g < m["IT_min"]:
            out.append("{}规定到 IT{}，超出它的经济精度 IT{}–IT{}".format(m["method_zh"], g, m["IT_min"], m["IT_max"]))
        if prev_it > m["prev_IT"]:
            out.append("{} 之前只到 IT{}，粗于它要求的 IT{}——中间缺了一环（“跳级”：余量和上道误差一次切不掉）"
                       .format(m["method_zh"], prev_it, m["prev_IT"]))
        if hardened_from is not None and i >= hardened_from and not m["hard_ok"]:
            out.append("{} 排在淬硬之后：淬硬钢（> 45 HRC）{}不动，淬硬后只能磨（或磨齿、珩齿）".format(
                m["method_zh"], "车" if "车" in m["method_zh"] else "加工"))
        prev_it = g if g is not None else m["IT_max"]
    last = METHODS[keys[-1]]
    if hardened_from is not None and hardened_from >= len(keys):      # 热处理以后不再加工：变形使精度降一级
        if last["IT_min"] + HEAT_DISTORT > it:
            out.append("热处理后不再精加工，{}的 IT{} 再降约 {} 级（热处理变形）就达不到要求的 IT{}".format(
                last["method_zh"], last["IT_min"], HEAT_DISTORT, it))
        if ra is not None and ra < HEAT_RA:
            out.append("热处理后表面有氧化皮、脱碳和变形，要求 Ra {} μm 的表面热处理后还要精加工（磨）".format(ra))
        return out
    if last["IT_min"] > it:
        out.append("最后一环{}的经济精度 IT{}–IT{} 达不到要求的 IT{}".format(last["method_zh"], last["IT_min"], last["IT_max"], it))
    if ra is not None and last.get("Ra_min_um") is not None and last["Ra_min_um"] > ra + 1e-9:
        out.append("最后一环{}的粗糙度 Ra {}–{} μm 达不到要求的 Ra {} μm".format(last["method_zh"], last["Ra_min_um"], last["Ra_max_um"], ra))
    return out


def chains(feature, it, ra=None, hardened=False, blank="热轧圆钢", max_len=4):
    """可行的方案链（由粗到精），最短的在前；hardened=True 表示最后要在淬硬后加工（链中插入“热处理”的位置 heat_at）。
    同样长度时，最后一环不过分精（要求在它的经济精度范围里）的在前。"""
    ms = [m["key"] for m in methods(feature)]
    out = []
    for n in range(1, max_len + 1):
        for combo in itertools.combinations(ms, n):          # methods() 已由粗到精排好，组合保持顺序
            for hf in (range(n + 1) if hardened else [None]):    # hf：淬硬后的第一环（= n：热处理后不再加工）
                if hf is not None and not all(METHODS[k]["hard_ok"] for k in combo[hf:]):
                    continue
                if hf is not None and any(METHODS[k]["hard_ok"] for k in combo[:hf]):
                    continue                                      # 能磨淬硬钢的方法留在热处理之后
                if check_chain(list(combo), it, ra, hf, blank):
                    continue
                last = METHODS[combo[-1]]
                names = [METHODS[k]["method_zh"] for k in combo]
                if hf is not None:
                    names = names[:hf] + ["热处理"] + names[hf:]
                out.append({"steps": list(combo), "heat_at": hf, "overkill": bool(it > last["IT_max"]), "n": n,
                            "zh": " → ".join(names)})
        if out:
            break
    out.sort(key=lambda c: (c["overkill"], c["n"]))
    return out


# ---------------------------------------------------------------- 节拍、瓶颈与成本
def _workstations():
    import sys
    root = os.path.abspath(os.path.join(HERE, "..", ".."))
    if root not in sys.path:
        sys.path.insert(0, root)
    from factory import data as F
    return F.WORKSTATIONS


EXTRA_WS = {}      # 书中比较方案用的、工厂里还没有的工作中心：{名称: (小时费率 元/h, 台数)}（如车铣复合中心）


def rate_per_hour(ws):
    """工作中心的小时费率（元/h：折旧 + 人工 + 能耗，factory/data.py WORKSTATIONS）与台数。"""
    if ws in EXTRA_WS:
        return float(EXTRA_WS[ws][0]), int(EXTRA_WS[ws][1])
    w = _workstations().get(ws)
    if not w:
        return 0.0, 1
    return float(sum(w[1])), int(w[0])


def route_cost(ops, batch):
    """一条路线（[{operation, workstation, minutes, setup_min}]）在批量 batch 下的单件时间、各工作中心的负荷、瓶颈和单件成本。
    热处理炉按装炉量（台数字段，如 HT-01 一炉 20 件）分摊。返回 dict。"""
    per = []
    load = {}
    cost = 0.0
    for o in ops:
        r, n = rate_per_hour(o["workstation"])
        t = o.get("minutes", 0) + (o.get("setup_min", 0) or 0) / max(batch, 1)
        furnace = "热处理" in o["workstation"]
        t_unit = t / n if furnace else t                      # 炉子一炉 n 件：每件占用 t/n
        c = t_unit / 60 * r
        per.append({"seq": o.get("seq"), "operation": o["operation"], "workstation": o["workstation"], "t_min": t, "t_unit": t_unit,
                    "cost": c})
        cost += c
        key = o["workstation"]
        load[key] = load.get(key, 0.0) + (t_unit if furnace else t / n)
    neck = max(load.items(), key=lambda kv: kv[1])
    return {"ops": per, "t_total": sum(p["t_unit"] for p in per), "load": load, "bottleneck": neck[0], "takt": neck[1],
            "cost": cost, "per_hour": 60 / neck[1] if neck[1] else math.inf}


def cost_line(ops):
    """单件成本 = a + S/批量：a 为与批量无关的部分，S 为准备与终结时间的成本（元/批）。"""
    a = S = 0.0
    for o in ops:
        r, n = rate_per_hour(o["workstation"])
        furnace = "热处理" in o["workstation"]
        a += o.get("minutes", 0) / (n if furnace else 1) / 60 * r
        S += (o.get("setup_min", 0) or 0) / (n if furnace else 1) / 60 * r
    return a, S


def critical_batch(ops1, ops2):
    """两条路线单件成本相等的批量（a₁ + S₁/N = a₂ + S₂/N → N = (S₁ − S₂)/(a₂ − a₁)）；不相交返回 None。"""
    a1, s1 = cost_line(ops1)
    a2, s2 = cost_line(ops2)
    if abs(a2 - a1) < 1e-12:
        return None
    n = (s1 - s2) / (a2 - a1)
    return n if n > 0 else None
