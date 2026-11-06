# -*- coding: utf-8 -*-
"""芯片封测厂的质量规则（第 103 轮，电子 E9）：QS1 CP 良率突降、QS2 某个测试位失效集中（读晶圆图的按测试位统计）、
QS3 键合拉力下降（按键合机分层）、QS4 塑封空洞率升高、QS5 划片崩边增大。
读测量记录（quality.measurement）；只在清单 wenquest-chip 的厂里登记进规则目录（ontology/rules/chip.yaml 的 plant）。"""
import statistics

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=4000)
    rows = c.get("chip_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


def _v(m):
    return float(m["data"]["value_mm"])


@rule("chip_cp_drop")
def chip_cp_drop(c, p, r):
    rows = _recent(c, "cp_yield", p["last"] + p["base"])
    if len(rows) < p["last"] + 4:
        return []
    rec, base = rows[:p["last"]], rows[p["last"]:]
    a, b = sum(map(_v, rec)) / len(rec), sum(map(_v, base)) / len(base)
    if b - a < p["drop"]:
        return []
    return [Finding("cp_yield", "CP 良率突降：最近 {} 片均值 {:.1f} %，之前 {} 片 {:.1f} %".format(len(rec), a, len(base), b),
                    "晶圆：{}".format("、".join("{} {:.1f} %".format(m["data"]["part_serial"], _v(m)) for m in rec)),
                    subject=("InspectionPlan", "CP"), evidence=_ev(rec), hint=r.get("hint"),
                    values={"recent": round(a, 2), "base": round(b, 2), "wafers": [m["data"]["part_serial"] for m in rec]})]


@rule("chip_site_cluster")
def chip_site_cluster(c, p, r):
    rows = [m for m in _recent(c, "cp_yield", 50) if (m["data"].get("wafer") or {}).get("site_fail_pct")][:p["last"]]
    if len(rows) < p["last"]:
        return []
    n = len(rows[0]["data"]["wafer"]["site_fail_pct"])
    avg = [sum(m["data"]["wafer"]["site_fail_pct"][k] for m in rows) / len(rows) for k in range(n)]
    out = []
    for k, a in enumerate(avg):
        med = statistics.median(avg[:k] + avg[k + 1:])
        if a >= p["floor"] and a >= p["factor"] * max(med, 0.1):
            out.append(Finding("site{}".format(k + 1), "第 {} 个测试位失效集中：最近 {} 片平均失效 {:.1f} %，其余测试位中位数 {:.1f} %".format(
                k + 1, len(rows), a, med), "晶圆：" + "、".join(m["data"]["part_serial"] for m in rows), subject=("Machine", "prb-1"),
                evidence=_ev(rows), hint=r.get("hint"), values={"site": k + 1, "fail_pct": round(a, 2), "others_median": round(med, 2),
                                                                "wafers": [m["data"]["part_serial"] for m in rows]}))
    return out


@rule("chip_bond_pull")
def chip_bond_pull(c, p, r):
    rows = _recent(c, "bond_pull", p["last"])
    if len(rows) < p["last"]:
        return []
    by = {}
    for m in rows:
        by.setdefault(m["data"].get("assembled_on") or "—", []).append(_v(m))
    means = {k: sum(v) / len(v) for k, v in by.items()}
    lo_k = min(means, key=means.get)
    hi = max(means.values())
    if means[lo_k] >= p["below"] and hi - means[lo_k] < p["gap"]:
        return []
    return [Finding("bond_pull", "键合拉力下降：{} 键合的批次均值 {:.2f} gf".format(lo_k, means[lo_k]),
                    "按键合机：" + "；".join("{} {:.2f} gf（{} 批）".format(k, v, len(by[k])) for k, v in sorted(means.items())),
                    subject=("Machine", lo_k) if lo_k != "—" else ("Item", "WQ-ENCIF"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_bonder": {k: round(v, 3) for k, v in means.items()}})]


def _mean_rule(c, p, r, code, label, unit, subject):
    rows = _recent(c, code, p["last"])
    if len(rows) < p["last"]:
        return []
    v = list(map(_v, rows))
    mean = sum(v) / len(v)
    if mean <= p["above"]:
        return []
    hi = rows[0]["data"]["upper_tol_mm"]
    out = [x for x in v if x > hi]
    return [Finding(code, "{}：最近 {} 批均值 {:.2f} {}".format(label, len(v), mean, unit), "超上限 {:g} {} 的 {} 批".format(hi, unit, len(out)),
                    severity="critical" if out else "warn", subject=subject, evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 3), "over": len(out)})]


@rule("chip_mold_void")
def chip_mold_void(c, p, r):
    return _mean_rule(c, p, r, "mold_void", "塑封空洞率升高", "%", ("Machine", "mld-1"))


@rule("chip_chipping")
def chip_chipping(c, p, r):
    return _mean_rule(c, p, r, "chipping", "划片崩边增大", "µm", ("Machine", "dc-1"))
