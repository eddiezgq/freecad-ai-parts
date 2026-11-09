# -*- coding: utf-8 -*-
"""传感器厂的质量规则（第 125 轮，电子 E12）：SN1 编码器精度变差、SN2 一次谐波偏大（按粘接对心机分层）、SN3 读头信号幅值下降、
SN4 码盘污点（幅值掉坑）、SN5 扭矩传感器蠕变升高。读测量记录（quality.measurement）；只在清单 wenquest-sensor 的厂里登记进规则目录。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=4000)
    rows = c.get("sensor_meas", load)
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


@rule("sensor_enc_acc")
def sensor_enc_acc(c, p, r):
    return _mean_rule(c, p, r, "enc_acc", "编码器精度变差", "″", ("Item", "WQ-ENC17"))


@rule("sensor_enc_amp")
def sensor_enc_amp(c, p, r):
    return _mean_rule(c, p, r, "enc_amp", "读头信号幅值下降", "%", ("Machine", "hm-1"), low=True)


@rule("sensor_ts_creep")
def sensor_ts_creep(c, p, r):
    return _mean_rule(c, p, r, "ts_creep", "扭矩传感器蠕变升高", "%FS", ("Machine", "cur-1"))


@rule("sensor_enc_h1")
def sensor_enc_h1(c, p, r):
    rows = _recent(c, "enc_h1", p["last"])
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
    return [Finding("enc_h1", "一次谐波偏大：{} 粘的码盘均值 {:.1f}″".format(hi_k, means[hi_k]),
                    "按粘接对心机：" + "；".join("{} {:.1f}″（{} 台）".format(k, v, len(by[k])) for k, v in sorted(means.items())),
                    subject=("Machine", hi_k) if hi_k != "—" else ("Item", "WQ-ENC17"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_station": {k: round(v, 2) for k, v in means.items()}})]


@rule("sensor_enc_dirt")
def sensor_enc_dirt(c, p, r):
    rows = _recent(c, "enc_amp_min", p["last"])
    if len(rows) < p["last"]:
        return []
    bad = [m for m in rows if _v(m) < p["below"]]
    if len(bad) < p["count"]:
        return []
    return [Finding("enc_amp_min", "码盘污点：最近 {} 台里 {} 台信号幅值在某处掉到 {:g} % 以下".format(len(rows), len(bad), p["below"]),
                    "编码器：" + "、".join("{} 最低 {:.0f} %".format(m["data"]["part_serial"], _v(m)) for m in bad[:6]),
                    subject=("Machine", "dcl-1"), evidence=_ev(bad), hint=r.get("hint"),
                    values={"count": len(bad), "serials": [m["data"]["part_serial"] for m in bad]})]
