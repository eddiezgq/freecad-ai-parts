# -*- coding: utf-8 -*-
"""电路板厂的质量规则（第 85 轮，电子 E3）：QE1 AOI 缺陷率突升、QE2 回流炉温越界、QE3 锡膏体积偏低、QE4 电流采样误差按批次偏大。
读测量记录（quality.measurement）；只在清单 wenquest-pcb 的厂里登记进规则目录（ontology/rules/electronics.yaml 的 plant）。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    """某个特性最近 n 条测量（新的在前）"""
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=4000)
    rows = c.get("pcb_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


@rule("pcb_aoi_spike")
def pcb_aoi_spike(c, p, r):
    rows = _recent(c, "aoi_defects", p["recent"] + p["base"])
    if len(rows) < p["recent"] + 10:
        return []
    rec, base = rows[:p["recent"]], rows[p["recent"]:]
    nd = sum(float(m["data"]["value_mm"]) for m in rec)
    rate = nd / len(rec)
    brate = sum(float(m["data"]["value_mm"]) for m in base) / max(1, len(base))
    if nd < p["min_defects"] or rate < max(p["floor"], p["factor"] * brate):
        return []
    bad = [m for m in rec if float(m["data"]["value_mm"]) > 0]
    return [Finding("aoi", "AOI 缺陷率突升：最近 {} 块板 {:g} 个缺陷（每块 {:.2f}），之前每块 {:.2f}".format(len(rec), nd, rate, brate),
                    "有缺陷的板：{}".format("、".join(m["data"]["part_serial"] for m in bad[:8])),
                    subject=("InspectionPlan", "AOI"), evidence=_ev(bad), hint=r.get("hint"),
                    values={"recent_rate": round(rate, 3), "base_rate": round(brate, 3), "defects": nd,
                            "parts": [m["data"]["part_serial"] for m in bad]})]


@rule("pcb_reflow_window")
def pcb_reflow_window(c, p, r):
    out = []
    for code, label, unit in (("reflow_peak", "峰值温度", "℃"), ("reflow_tal", "液相线以上时间", "s")):
        rows = _recent(c, code, p["last"])
        if len(rows) < p["last"]:
            continue
        d = rows[0]["data"]
        lo, hi = d["lower_tol_mm"], d["upper_tol_mm"]
        v = [float(m["data"]["value_mm"]) for m in rows]
        mean = sum(v) / len(v)
        outside = [x for x in v if not lo <= x <= hi]
        if outside:
            sev = "critical"
        elif mean - lo < p["margin"] or hi - mean < p["margin"]:
            sev = "warn"
        else:
            continue
        out.append(Finding(code, "回流炉{}{}：最近 {} 块均值 {:.1f} {}（窗口 {:g}–{:g}）".format(
            label, "超出工艺窗口" if outside else "接近窗口边缘", len(v), mean, unit, lo, hi),
            "越界 {} 块".format(len(outside)) if outside else "尚未越界", severity=sev, subject=("Machine", "rf-1"),
            evidence=_ev(rows), hint=r.get("hint"), values={"characteristic": code, "mean": round(mean, 2), "outside": len(outside)}))
    return out


@rule("pcb_spi_low")
def pcb_spi_low(c, p, r):
    rows = _recent(c, "spi_volume", p["last"])
    if len(rows) < p["last"]:
        return []
    mean = sum(float(m["data"]["value_mm"]) for m in rows) / len(rows)
    if mean >= p["below"]:
        return []
    return [Finding("spi_volume", "锡膏体积偏低：最近 {} 块均值 {:.1f} %（名义 100 %）".format(len(rows), mean), "低于 {:g} %".format(p["below"]),
                    subject=("Machine", "sp-1"), evidence=_ev(rows), hint=r.get("hint"), values={"mean": round(mean, 2)})]


@rule("pcb_isense_lot")
def pcb_isense_lot(c, p, r):
    rows = _recent(c, "fct_isense", p["last"])
    if len(rows) < p["last"]:
        return []
    mean = sum(float(m["data"]["value_mm"]) for m in rows) / len(rows)
    if mean <= p["above"]:
        return []
    by = {}
    for m in rows:
        by.setdefault(m["data"].get("lot") or "—", []).append(float(m["data"]["value_mm"]))
    lots = sorted(((k, sum(v) / len(v), len(v)) for k, v in by.items()), key=lambda x: -x[1])
    return [Finding("fct_isense", "驱动板相电流采样误差偏大：最近 {} 块均值 {:+.2f} %".format(len(rows), mean),
                    "按采样电阻卷号：" + "；".join("{} {:+.2f} %（{} 块）".format(k, a, n) for k, a, n in lots),
                    subject=("Item", "DRV-JOINT"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 3), "lots": [[k, round(a, 3), n] for k, a, n in lots]})]
