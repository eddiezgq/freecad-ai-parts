# -*- coding: utf-8 -*-
"""电机厂的质量规则（第 131 轮）：MT1 齿槽转矩变大（磁钢贴歪）、MT2 三相电阻不平衡（按绕线机分层）、MT3 反电势常数下降（充磁不足）、
MT4 耐压漏电流上升（浸漆没固化透）。读测量记录（quality.measurement）；只在清单 wenquest-motor 的厂里登记进规则目录。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=6000)
    rows = c.get("motor_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


def _v(m):
    return float(m["data"]["value_mm"])


def _mean_rule(c, p, r, code, label, unit, subject, low=False):
    rows = _recent(c, code, p["last"])
    if len(rows) < p["last"]:
        return []
    v = list(map(_v, rows))
    mean = sum(v) / len(v)
    if (mean >= p["below"]) if low else (mean <= p["above"]):
        return []
    lim = rows[0]["data"]["lower_tol_mm" if low else "upper_tol_mm"]
    out = [x for x in v if (x < lim if low else x > lim)]
    return [Finding(code, "{}：最近 {} 台均值 {:.2f} {}".format(label, len(v), mean, unit),
                    "超出{}限 {:g} {} 的 {} 台：{}".format("下" if low else "上", lim, unit, len(out),
                                                        "、".join(m["data"]["part_serial"] for m in rows[:6])),
                    severity="critical" if out else "warn", subject=subject, evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 3), "out": len(out)})]


@rule("motor_cog")
def motor_cog(c, p, r):
    return _mean_rule(c, p, r, "mt_cog", "齿槽转矩变大", "%", ("Machine", "mg-1"))


@rule("motor_ke")
def motor_ke(c, p, r):
    return _mean_rule(c, p, r, "mt_ke", "反电势常数下降", "%", ("Machine", "mz-1"), low=True)


@rule("motor_leak")
def motor_leak(c, p, r):
    return _mean_rule(c, p, r, "st_leak", "耐压漏电流上升", "mA", ("Machine", "vo-1"))


@rule("motor_r_unbal")
def motor_r_unbal(c, p, r):
    rows = _recent(c, "st_r_unbal", p["last"])
    if len(rows) < p["last"]:
        return []
    by = {}
    for m in rows:
        by.setdefault(m["data"].get("assembled_on") or "—", []).append(_v(m))
    means = {k: sum(v) / len(v) for k, v in by.items()}
    hi_k = max(means, key=means.get)
    lo = min(means.values())
    if means[hi_k] <= p["above"] and means[hi_k] - lo < p["gap"]:
        return []
    return [Finding("st_r_unbal", "三相电阻不平衡偏大：{} 绕的定子均值 {:.2f} %".format(hi_k, means[hi_k]),
                    "按绕线机：" + "；".join("{} {:.2f} %（{} 台）".format(k, v, len(by[k])) for k, v in sorted(means.items())),
                    subject=("Machine", hi_k) if hi_k != "—" else ("Item", "WQ-SM400"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_winder": {k: round(v, 3) for k, v in means.items()}})]
