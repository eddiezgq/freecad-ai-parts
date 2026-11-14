"""有限元结果的可信度核查（ADR-0093 F1）。纯函数：只看计算出来的数，不调用求解器、不调用 LLM。

每一项给“通过 / 不通过 / 未知”（pass / fail / unknown）和一句说明；总结论取最严的一项：有不通过就不通过，否则有未知就未知。

- 反力平衡：外载合力、合力矩与支承反力相抵，相对误差 ≤ 容差（缺省 0.1 %）。不平衡说明模型或求解出了问题。
- 网格质量：有翻转单元（最小缩放雅可比 ≤ 0）不通过；形状因子 gamma < 0.1 的单元超过 0.1 % 判未知（结果可能受坏单元影响）。
  阈值是常用的经验值，写在这里、可改，不是标准规定的数。
- 网格收敛：同一位置附近逐层加密（单元尺寸之比 r 固定），用 Richardson 外推和网格收敛指数 GCI（Roache 1994、1998）
  估计最大应力的网格误差。
    观察阶 p = ln((f3 − f2) / (f2 − f1)) / ln r（f1 最粗、f3 最细）
    外推值 f_ext = f3 + (f3 − f2) / (r^p − 1)
    GCI = 1.25 · |(f3 − f2) / f3| / (r^p − 1)
  判定：各层相差不超过容差的 1/5 → 直接通过；
        差值单调变小、p 在 [0.5, 6] 内且 GCI ≤ 容差 → 通过；
        越加密差值越不变小（后一差 ≥ 前一差的 0.8 倍）且一直在长 → 不通过：“疑似应力奇异点”（尖角、点载荷一类，
        理论上应力无穷大，这个点的应力不能当设计依据）；
        加密后来回振荡时，按 Stern 等（2001）的做法取不确定度 U = (最大 − 最小) / 2，相对值 ≤ 容差 → 通过；
        其余（阶数不合理、误差超限）→ 未知。
"""

from __future__ import annotations

import math

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
GAMMA_BAD = 0.1
GAMMA_BAD_FRACTION = 0.001


def item(name: str, verdict: str, text: str, **values) -> dict:
    return {"name": name, "verdict": verdict, "text": text, **values}


def balance(b: dict, tol: float = 1e-3) -> dict:
    if not b or not b.get("available"):
        return item("反力平衡", UNKNOWN, "没有读到支承反力")
    ef, em = b["force_error_ratio"], b["moment_error_ratio"]
    ok = ef <= tol and em <= tol
    return item("反力平衡", PASS if ok else FAIL,
                "外载与支承反力相抵" if ok else "外载与支承反力不平衡：模型或求解有问题，结果不能用",
                force_error_ratio=ef, moment_error_ratio=em, tolerance_ratio=tol)


def mesh_quality(q: dict) -> dict:
    if not q:
        return item("网格质量", UNKNOWN, "没有网格质量数据")
    if q["inverted"] > 0:
        return item("网格质量", FAIL, f"有 {q['inverted']} 个翻转单元（雅可比 ≤ 0），结果不能用", **q)
    frac = q["gamma_below_0_1"] / max(q["elements"], 1)
    if frac > GAMMA_BAD_FRACTION:
        return item("网格质量", UNKNOWN, f"形状很差的单元（gamma < {GAMMA_BAD}）占 {frac:.2%}，可能影响结果", **q)
    return item("网格质量", PASS, "没有翻转单元，形状很差的单元很少", **q)


def richardson(f: list[float], r: float, hs: list[float] | None = None) -> dict:
    """三层（或更多层取最后三层）由粗到细的值 → 观察阶、外推值、GCI、差值比。
    给了各层实际的局部单元尺寸 hs 时，相邻两层的加密比不必相等，按 Celik 等（2008，J. Fluids Eng. 130:078001）的迭代式求观察阶：
      p = |ln|e_c / e_f| + ln((r_f^p − s) / (r_c^p − s))| / ln r_f，s = sign(e_c / e_f)
    其中 r_c、r_f 是粗—中、中—细两层的尺寸比，e_c、e_f 是对应两层的差。"""
    f1, f2, f3 = f[-3], f[-2], f[-1]
    e21, e32 = f2 - f1, f3 - f2
    out = {"values": [float(x) for x in f], "refine_ratio": r, "diff_ratio": None, "order_p": None, "extrapolated": None,
           "gci_ratio": None}
    if hs and len(hs) >= 3 and min(hs[-3:]) > 0:
        rc, rf = hs[-3] / hs[-2], hs[-2] / hs[-1]
        out["local_h_mm"] = [float(x) for x in hs]
    else:
        rc = rf = r
    if abs(e21) < 1e-12 * max(abs(f3), 1.0):
        out.update(diff_ratio=0.0, extrapolated=f3, gci_ratio=0.0)
        return out
    q = e32 / e21
    out["diff_ratio"] = q
    if q <= 0 or q >= 1 or rc <= 1 or rf <= 1:
        return out
    p = math.log(1 / q) / math.log(rf)
    for _ in range(200):
        try:
            pn = abs(math.log(abs(e21 / e32)) + math.log((rf ** p - 1) / (rc ** p - 1))) / math.log(rf)
        except (ValueError, ZeroDivisionError, OverflowError):
            return out
        if abs(pn - p) < 1e-8:
            p = pn
            break
        p = pn
    else:
        return out
    rp = rf ** p - 1
    out.update(order_p=p, extrapolated=f3 + e32 / rp, gci_ratio=1.25 * abs(e32 / f3) / rp if f3 else None)
    return out


def convergence(values: list[float], r: float, tol: float = 0.05, what: str = "最大应力", hs: list[float] | None = None) -> dict:
    if len(values) < 3:
        return item(f"网格收敛（{what}）", UNKNOWN, "层数不够（至少 3 层）", values=values)
    rr = richardson(values, r, hs)
    q = rr["diff_ratio"]
    f1, f2, f3 = values[-3:]
    spread = (max(values[-3:]) - min(values[-3:])) / max(abs(f3), 1e-12)
    if spread <= 0.2 * tol:                                     # 各层几乎一样：不必再看收敛阶
        return item(f"网格收敛（{what}）", PASS, f"各层相差不超过 {spread:.2%}", tolerance_ratio=tol, spread_ratio=spread, **rr)
    growing = f3 > f2 > f1
    if q is not None and q >= 0.8 and growing:
        return item(f"网格收敛（{what}）", FAIL,
                    "越加密越大、不收敛：疑似应力奇异点（尖角、点载荷一类），这一点的应力不能当设计依据" if what == "最大应力"
                    else "越加密越大、不收敛", **rr)
    if q is not None and q < 0:                                   # 振荡收敛
        u = 0.5 * (max(values[-3:]) - min(values[-3:])) / max(abs(f3), 1e-12)
        rr["oscillation_ratio"] = u
        if u <= tol:
            return item(f"网格收敛（{what}）", PASS, f"加密后在 ±{u:.2%} 内来回（≤ {tol:.0%}）", tolerance_ratio=tol, **rr)
        return item(f"网格收敛（{what}）", UNKNOWN, f"加密后来回振荡 ±{u:.1%}，大于 {tol:.0%}：再加密网格", tolerance_ratio=tol, **rr)
    p, gci = rr["order_p"], rr["gci_ratio"]
    if gci is not None and gci <= tol and (q == 0 or (p is not None and 0.5 <= p <= 6)):
        return item(f"网格收敛（{what}）", PASS, f"网格误差估计 {gci:.1%}（≤ {tol:.0%}）", tolerance_ratio=tol, **rr)
    if gci is not None and gci > tol:
        return item(f"网格收敛（{what}）", UNKNOWN, f"网格误差估计 {gci:.1%}，大于 {tol:.0%}：再加密网格", tolerance_ratio=tol, **rr)
    return item(f"网格收敛（{what}）", UNKNOWN, "加密后的变化不规则，估计不出网格误差", tolerance_ratio=tol, **rr)


def verdict(items: list[dict]) -> str:
    vs = [i["verdict"] for i in items]
    if FAIL in vs:
        return FAIL
    if UNKNOWN in vs or not vs:
        return UNKNOWN
    return PASS
