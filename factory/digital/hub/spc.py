# -*- coding: utf-8 -*-
"""质量统计（第 13 轮〔SPC〕：《机械制造技术》第 53、56、57 章用）：控制图、判异、过程能力、测量系统分析。

纯计算函数，输入是测量值的列表；`for_characteristic` 从历史库取三坐标检验记录（quality.measurement）直接算。
公式按 Montgomery《Introduction to Statistical Quality Control》与 AIAG《SPC》《MSA》手册的通行写法：

- 均值–极差图：控制限 x̿ ± A₂R̄，R 图 D₃R̄–D₄R̄；单值–移动极差图：x̄ ± 2.66 MR̄（2.66 = 3/d₂，d₂ = 1.128）；
- 组内标准差 σ̂ = R̄/d₂（算 Cp、Cpk），总标准差 s（算 Pp、Ppk）；
- 判异：西电规则 1–4（1 点出 3σ；连续 3 点中 2 点在 2σ 外同侧；连续 5 点中 4 点在 1σ 外同侧；连续 8 点在中心线同侧）；
- 测量系统分析：方差分析法（零件 × 检验员 × 重复），给出 EV、AV、GRR、PV、TV（标准差，单位与测量值相同）、
  %GRR（对总变差）与可区分类别数 ndc = 1.41·PV/GRR。
"""
import math
import statistics as st

# 控制图常数（子组容量 n = 2…10）：d₂、A₂、D₃、D₄
D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}
A2 = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577, 6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
D3 = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
D4 = {2: 3.267, 3: 2.574, 4: 2.282, 5: 2.114, 6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}


def subgroups(values, n):
    return [values[i:i + n] for i in range(0, len(values) - len(values) % n, n)]


def xbar_r(values, n=5):
    """均值–极差图。返回中心线、控制限、各子组均值与极差、组内 σ̂。"""
    if n not in D2:
        raise ValueError("子组容量 n 取 2–10")
    g = subgroups(list(values), n)
    if len(g) < 2:
        raise ValueError("至少要 2 个子组")
    xb = [st.fmean(x) for x in g]
    rr = [max(x) - min(x) for x in g]
    xbb, rb = st.fmean(xb), st.fmean(rr)
    return {"kind": "xbar_r", "n": n, "k": len(g), "xbar": xb, "R": rr, "center": xbb, "Rbar": rb,
            "UCL": xbb + A2[n] * rb, "LCL": xbb - A2[n] * rb, "UCL_R": D4[n] * rb, "LCL_R": D3[n] * rb,
            "sigma_within": rb / D2[n]}


def i_mr(values):
    """单值–移动极差图（每件测一次时用）。"""
    v = list(values)
    if len(v) < 3:
        raise ValueError("至少要 3 个值")
    mr = [abs(b - a) for a, b in zip(v, v[1:])]
    xb, mrb = st.fmean(v), st.fmean(mr)
    s = mrb / D2[2]
    return {"kind": "i_mr", "x": v, "MR": mr, "center": xb, "MRbar": mrb, "UCL": xb + 3 * s, "LCL": xb - 3 * s,
            "UCL_MR": D4[2] * mrb, "sigma_within": s}


def special_causes(points, center, sigma):
    """西电规则 1–4：返回 [{rule, index, text}]，index 是触发那一点的序号（从 0 起）。同一规则连续触发时只报第一点。"""
    z = [(p - center) / sigma if sigma > 0 else 0.0 for p in points]

    def hit(rule, i):
        if rule == 1:
            return abs(z[i]) > 3
        if rule == 4:
            return i >= 7 and (all(x > 0 for x in z[i - 7:i + 1]) or all(x < 0 for x in z[i - 7:i + 1]))
        m, k, lim = (3, 2, 2) if rule == 2 else (5, 4, 1)
        if i < m - 1:
            return False
        w = z[i - m + 1:i + 1]
        return any(sum(1 for x in w if sg * x > lim) >= k and sg * z[i] > lim for sg in (1, -1))

    text = {1: "第 {} 点超出 3σ 控制限", 2: "连续 3 点中有 2 点在 2σ 外同侧（到第 {} 点）",
            3: "连续 5 点中有 4 点在 1σ 外同侧（到第 {} 点）", 4: "连续 8 点在中心线同一侧（到第 {} 点），过程均值可能漂移"}
    out = []
    for rule in (1, 2, 3, 4):
        prev = False
        for i in range(len(z)):
            h = hit(rule, i)
            if h and not prev:
                out.append({"rule": rule, "index": i, "text": text[rule].format(i + 1)})
            prev = h
    return sorted(out, key=lambda o: (o["index"], o["rule"]))


def capability(values, lsl, usl, sigma_within=None):
    """Cp、Cpk（组内 σ̂）与 Pp、Ppk（总标准差 s）。sigma_within 不给时用移动极差估计。"""
    v = list(values)
    mu, s = st.fmean(v), st.stdev(v)
    sw = sigma_within if sigma_within else i_mr(v)["sigma_within"]
    tol = usl - lsl
    return {"mean": mu, "s": s, "sigma_within": sw, "Cp": tol / (6 * sw), "Cpk": min(usl - mu, mu - lsl) / (3 * sw),
            "Pp": tol / (6 * s), "Ppk": min(usl - mu, mu - lsl) / (3 * s), "n": len(v), "LSL": lsl, "USL": usl}


def grr_anova(data, tol=None):
    """测量系统分析（方差分析法）。data[检验员][零件] = [各次重复读数]，各格重复次数相同。

    方差分量：重复性 σ²_EV = MS_E；检验员 σ²_o = (MS_O − MS_OP)/(p·r)；交互 σ²_op = (MS_OP − MS_E)/r；
    零件 σ²_p = (MS_P − MS_OP)/(o·r)；负值取 0（AIAG 做法）。再现性 AV² = σ²_o + σ²_op。
    """
    ops = list(data)
    parts = list(data[ops[0]])
    o, p, r = len(ops), len(parts), len(data[ops[0]][parts[0]])
    allv = [x for a in ops for b in parts for x in data[a][b]]
    gm = st.fmean(allv)
    mo = {a: st.fmean([x for b in parts for x in data[a][b]]) for a in ops}
    mp = {b: st.fmean([x for a in ops for x in data[a][b]]) for b in parts}
    mc = {(a, b): st.fmean(data[a][b]) for a in ops for b in parts}
    ss_o = p * r * sum((mo[a] - gm) ** 2 for a in ops)
    ss_p = o * r * sum((mp[b] - gm) ** 2 for b in parts)
    ss_op = r * sum((mc[(a, b)] - mo[a] - mp[b] + gm) ** 2 for a in ops for b in parts)
    ss_e = sum((x - mc[(a, b)]) ** 2 for a in ops for b in parts for x in data[a][b])
    ms_o, ms_p = ss_o / (o - 1), ss_p / (p - 1)
    ms_op, ms_e = ss_op / ((o - 1) * (p - 1)), ss_e / (o * p * (r - 1))
    v_e = ms_e
    v_o = max(0.0, (ms_o - ms_op) / (p * r))
    v_op = max(0.0, (ms_op - ms_e) / r)
    v_p = max(0.0, (ms_p - ms_op) / (o * r))
    ev, av = math.sqrt(v_e), math.sqrt(v_o + v_op)
    grr = math.sqrt(v_e + v_o + v_op)
    pv = math.sqrt(v_p)
    tv = math.sqrt(grr ** 2 + pv ** 2)
    out = {"EV": ev, "AV": av, "GRR": grr, "PV": pv, "TV": tv, "pct_GRR": 100 * grr / tv if tv else float("nan"),
           "ndc": int(1.41 * pv / grr) if grr else None, "operators": o, "parts": p, "trials": r}
    if tol:
        out["pct_GRR_tol"] = 100 * 6 * grr / tol
    pct = out["pct_GRR"]
    out["verdict"] = "可接受" if pct < 10 else ("有条件接受（视用途、成本）" if pct <= 30 else "不可接受，要改进量具或测量方法")
    return out


# ---------------------------------------------------------------- 历史库
def for_characteristic(db, mode, item, characteristic, n=5, limit=200):
    """从三坐标记录取某零件某特性的测量值，给出控制图、判异与过程能力。"""
    rows = [m for m in db.messages(["quality.measurement"], mode=mode, order="asc", limit=5000)
            if m["data"]["item"] == item and m["data"]["characteristic"] == characteristic][-limit:]
    if len(rows) < 2 * n:
        return {"item": item, "characteristic": characteristic, "count": len(rows),
                "note": "测量值不足 {} 个，还不能画均值–极差图".format(2 * n)}
    v = [r["data"]["value_mm"] for r in rows]
    lo, hi = rows[-1]["data"]["lower_tol_mm"], rows[-1]["data"]["upper_tol_mm"]
    ch = xbar_r(v, n)
    sig = ch["sigma_within"] / math.sqrt(n)
    out = {"item": item, "characteristic": characteristic, "count": len(v), "chart": ch,
           "signals": special_causes(ch["xbar"], ch["center"], sig),
           "capability": capability(v, lo, hi, ch["sigma_within"]),
           "evidence": [r["id"] for r in rows[-3:]]}
    return out
