# -*- coding: utf-8 -*-
"""问渠缝纫机厂的质量规则（第 134 轮）：SW1 型砂含水偏高（铸件气孔）、SW2 铸件硬度偏高（孕育衰退）、SW3 针杆孔位置度偏大（按精镗卧加分层）、
SW4 机壳平面度变差（时效不足）、SW5 轴颈硬度偏低（高频淬火）。读测量记录（quality.measurement）；只在清单 wenquest-sewing 的厂里登记进规则目录。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=6000)
    rows = c.get("sewing_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


def _v(m):
    return float(m["data"]["value_mm"])


def _mean_rule(c, p, r, code, label, unit, subject, low=False, fmt="{:.2f}"):
    rows = _recent(c, code, p["last"])
    if len(rows) < p["last"]:
        return []
    v = list(map(_v, rows))
    mean = sum(v) / len(v)
    if (mean >= p["below"]) if low else (mean <= p["above"]):
        return []
    lim = rows[0]["data"]["lower_tol_mm" if low else "upper_tol_mm"]
    out = [x for x in v if (x < lim if low else x > lim)]
    return [Finding(code, "{}：最近 {} 件均值 {} {}".format(label, len(v), fmt.format(mean), unit),
                    "超出{}限 {:g} {} 的 {} 件：{}".format("下" if low else "上", lim, unit, len(out),
                                                        "、".join(m["data"]["part_serial"] for m in rows[:6])),
                    severity="critical" if out else "warn", subject=subject, evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 4), "out": len(out)})]


@rule("sew_sand_moist")
def sew_sand_moist(c, p, r):
    return _mean_rule(c, p, r, "cast_moist", "型砂含水偏高", "%", ("Machine", "mix-1"))


@rule("sew_cast_hb")
def sew_cast_hb(c, p, r):
    return _mean_rule(c, p, r, "cast_hb", "铸件硬度偏高", "HB", ("Machine", "pour-1"), fmt="{:.0f}")


@rule("sew_flatness")
def sew_flatness(c, p, r):
    return _mean_rule(c, p, r, "hs_flat", "平缝机壳底面平面度变差", "mm", ("Machine", "age-1"), fmt="{:.4f}")


@rule("sew_shaft_hrc")
def sew_shaft_hrc(c, p, r):
    return _mean_rule(c, p, r, "ls_hrc", "轴颈硬度偏低", "HRC", ("Machine", "ihd-1"), low=True, fmt="{:.1f}")


@rule("sew_bore_pos")
def sew_bore_pos(c, p, r):
    rows = _recent(c, "hs_pos", p["last"])
    if len(rows) < p["last"]:
        return []
    by = {}
    for m in rows:
        by.setdefault(m["data"].get("assembled_on") or "—", []).append(_v(m))
    means = {k: sum(v) / len(v) for k, v in by.items()}
    hi_k = max(means, key=means.get)
    lo = min(means.values())
    if means[hi_k] <= p["above"] and (len(means) < 2 or means[hi_k] - lo < p["gap"]):
        return []
    return [Finding("hs_pos", "针杆孔位置度偏大：{} 精镗的机壳均值 {:.4f} mm".format(hi_k, means[hi_k]),
                    "按精镗卧加：" + "；".join("{} {:.4f} mm（{} 件）".format(k, v, len(by[k])) for k, v in sorted(means.items())),
                    severity="critical" if means[hi_k] > rows[0]["data"]["upper_tol_mm"] else "warn",
                    subject=("Machine", hi_k) if hi_k != "—" else ("Item", "HSG-LS"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_machine": {k: round(v, 4) for k, v in means.items()}})]
