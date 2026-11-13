# -*- coding: utf-8 -*-
"""计算机厂的质量规则（第 166 轮）：CP1 CPU 满载温度偏高（按点胶机分层）、CP2 BGA 空洞率上升（回流焊）、CP3 机箱孔位偏（折弯机后挡料）、
CP4 内存测试某个测试座不良偏多（按测试座分层）。读测量记录（quality.measurement）；只在清单 wenquest-computer 的厂里登记进规则目录。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=6000)
    rows = c.get("computer_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


def _v(m):
    return float(m["data"]["value_mm"])


def _by(rows, f):
    by = {}
    for m in rows:
        by.setdefault(m["data"].get("assembled_on") or "—", []).append(f(m))
    return {k: (sum(v) / len(v), len(v)) for k, v in by.items()}


@rule("pc_tmax_station")
def pc_tmax_station(c, p, r):
    """满载温度离上限的余量，按点胶机分开（台式、笔记本、服务器上限不同，所以比余量）"""
    rows = _recent(c, "pc_tmax", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, lambda m: float(m["data"]["upper_tol_mm"]) - _v(m))
    if len(st) < 1:
        return []
    worst = min(st, key=lambda k: st[k][0])
    best = max(v[0] for v in st.values())
    if st[worst][0] >= p["margin"] and best - st[worst][0] < p["gap"]:
        return []
    out = sum(1 for m in rows if _v(m) > float(m["data"]["upper_tol_mm"]))
    return [Finding("pc_tmax", "CPU 满载温度偏高：{} 涂硅脂的整机离上限平均只剩 {:.1f} ℃".format(worst, st[worst][0]),
                    "按点胶机（离上限的余量）：" + "；".join("{} {:.1f} ℃（{} 台）".format(k, v[0], v[1]) for k, v in sorted(st.items())),
                    severity="critical" if out else "warn", subject=("Machine", worst) if worst != "—" else ("Item", "WQ-PC1"),
                    evidence=_ev(rows), hint=r.get("hint"), values={"by_dispenser": {k: round(v[0], 2) for k, v in st.items()}, "out": out})]


def _mean_rule(c, p, r, code, label, unit, subject, f=_v):
    rows = _recent(c, code, p["last"])
    if len(rows) < p["last"]:
        return []
    v = list(map(f, rows))
    mean = sum(v) / len(v)
    if mean <= p["above"]:
        return []
    out = [m for m in rows if not (float(m["data"]["lower_tol_mm"]) <= _v(m) <= float(m["data"]["upper_tol_mm"]))]
    return [Finding(code, "{}：最近 {} 件均值 {:.2f} {}".format(label, len(v), mean, unit),
                    "超出公差的 {} 件：{}".format(len(out), "、".join(m["data"]["part_serial"] for m in out[:6]) or "—"),
                    severity="critical" if out else "warn", subject=subject, evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 3), "out": len(out)})]


@rule("pc_bga_void")
def pc_bga_void(c, p, r):
    return _mean_rule(c, p, r, "mb_void", "BGA 焊点空洞率上升", "%", ("Machine", "rf-1"))


@rule("pc_chassis_hole")
def pc_chassis_hole(c, p, r):
    return _mean_rule(c, p, r, "chs_hole", "机箱安装孔位置偏", "mm", ("Machine", "pb-1"), f=lambda m: abs(_v(m)))


@rule("pc_mem_socket")
def pc_mem_socket(c, p, r):
    rows = _recent(c, "mem_margin", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, _v)
    if len(st) < 2:
        return []
    low = min(st, key=lambda k: st[k][0])
    rest = [v[0] for k, v in st.items() if k != low]
    others = sum(rest) / len(rest)
    if others - st[low][0] < p["gap"]:
        return []
    return [Finding("mem_margin", "内存测试：{} 的时序余量比其他座低 {:.0f} ps".format(low, others - st[low][0]),
                    "按测试座：" + "；".join("{} {:.0f} ps（{} 条）".format(k, v[0], v[1]) for k, v in sorted(st.items())),
                    subject=("Machine", "mt-1"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_socket": {k: round(v[0], 1) for k, v in st.items()}, "socket": low})]
