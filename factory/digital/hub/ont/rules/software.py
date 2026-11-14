# -*- coding: utf-8 -*-
"""软件公司的质量规则（第 167 轮）：SW1 测试通过率按构建服务器分层、SW2 长稳压测内存增长、SW3 中断延迟按硬件在环测试台分层、
SW4 服务延迟按宿主机分层、SW5 服务错误率按可用区分层。读测量记录（quality.measurement）；只在清单 wenquest-software 的厂里登记进规则目录。"""
from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _recent(c, code, n):
    def load():
        return c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=6000)
    rows = c.get("software_meas", load)
    return [m for m in rows if m["data"].get("characteristic") == code][:n]


def _ev(rows, k=5):
    return [{"topic": m.get("_topic"), "id": m.get("id"), "seq": m.get("_seq")} for m in rows[:k]]


def _v(m):
    return float(m["data"]["value_mm"])


def _by(rows, key, f=_v):
    by = {}
    for m in rows:
        by.setdefault(key(m) or "—", []).append(f(m))
    return {k: (sum(v) / len(v), len(v)) for k, v in by.items()}


def _fmt(st, unit, dec=2):
    return "；".join("{} {} {}（{} 个）".format(k, format(v[0], ".{}f".format(dec)), unit, v[1]) for k, v in sorted(st.items()))


def _host(m):
    return m["data"].get("assembled_on")


@rule("sw_runner")
def sw_runner(c, p, r):
    """测试通过率按构建服务器分开：某台平均比其他台低 gap 个百分点以上"""
    rows = _recent(c, "sw_pass", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, _host)
    if len(st) < 2:
        return []
    low = min(st, key=lambda k: st[k][0])
    rest = [v[0] for k, v in st.items() if k != low]
    others = sum(rest) / len(rest)
    if others - st[low][0] < p["gap"]:
        return []
    out = sum(1 for m in rows if _v(m) < float(m["data"]["lower_tol_mm"]))
    return [Finding("sw_pass", "测试通过率：{} 跑的构建比其他构建服务器低 {:.2f} 个百分点".format(low, others - st[low][0]),
                    "按构建服务器：" + _fmt(st, "%", 3), severity="critical" if out else "warn",
                    subject=("Machine", low) if low != "—" else ("Item", "REL-OS"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_runner": {k: round(v[0], 3) for k, v in st.items()}, "runner": low, "out": out})]


@rule("sw_leak")
def sw_leak(c, p, r):
    """长稳压测的内存增长速率：最近 last 个版本均值超过 above MB/h"""
    rows = _recent(c, "os_leak", p["last"])
    if len(rows) < p["last"]:
        return []
    mean = sum(map(_v, rows)) / len(rows)
    if mean <= p["above"]:
        return []
    out = [m for m in rows if _v(m) > float(m["data"]["upper_tol_mm"])]
    first = rows[-1]["data"]["part_serial"]
    return [Finding("os_leak", "长稳压测内存一直涨：最近 {} 个版本平均 {:.1f} MB/h".format(len(rows), mean),
                    "超过上限的版本：{}；最早的一个 {}".format("、".join(m["data"]["part_serial"] for m in out[:6]) or "—", first),
                    severity="critical" if out else "warn", subject=("Machine", "sk-1"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"mean": round(mean, 2), "out": len(out)})]


@rule("sw_irq_bench")
def sw_irq_bench(c, p, r):
    """最坏中断延迟离上限的余量，按硬件在环测试台分开（实时 OS 和机器人软件上限不同，所以比余量）"""
    rows = _recent(c, "rtos_irq", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, lambda m: (m["data"].get("sw") or {}).get("bench"), lambda m: float(m["data"]["upper_tol_mm"]) - _v(m))
    if len(st) < 2:
        return []
    low = min(st, key=lambda k: st[k][0])
    best = max(v[0] for v in st.values())
    if best - st[low][0] < p["gap"]:
        return []
    out = sum(1 for m in rows if _v(m) > float(m["data"]["upper_tol_mm"]))
    return [Finding("rtos_irq", "中断延迟：{} 测的版本离上限只剩 {:.1f} μs，比别的测试台少 {:.1f} μs".format(low, st[low][0], best - st[low][0]),
                    "按测试台（离上限的余量）：" + _fmt(st, "μs", 1), severity="critical" if out else "warn",
                    subject=("Machine", low) if low != "—" else ("Item", "REL-RTOS"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_bench": {k: round(v[0], 2) for k, v in st.items()}, "bench": low, "out": out})]


@rule("svc_host")
def svc_host(c, p, r):
    """服务延迟 p99 按宿主机分开：某台平均比其他台高 gap ms 以上"""
    rows = _recent(c, "cl_p99", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, _host)
    if len(st) < 2:
        return []
    hi = max(st, key=lambda k: st[k][0])
    rest = [v[0] for k, v in st.items() if k != hi]
    others = sum(rest) / len(rest)
    if st[hi][0] - others < p["gap"]:
        return []
    out = sum(1 for m in rows if _v(m) > float(m["data"]["upper_tol_mm"]))
    return [Finding("cl_p99", "服务延迟：{} 上的订阅比其他宿主机高 {:.0f} ms".format(hi, st[hi][0] - others),
                    "按宿主机：" + _fmt(st, "ms", 1), severity="critical" if out else "warn",
                    subject=("Machine", hi) if hi != "—" else ("Item", "SUB-CLOUD"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_host": {k: round(v[0], 2) for k, v in st.items()}, "host": hi, "out": out})]


@rule("svc_zone")
def svc_zone(c, p, r):
    """服务错误率按可用区分开（宿主机 cl-a* 是 A 区、cl-b* 是 B 区）：一个区比另一个区高 gap 个百分点以上"""
    rows = _recent(c, "cl_err", p["last"])
    if len(rows) < p["last"]:
        return []
    st = _by(rows, lambda m: {"cl-a": "A 区", "cl-b": "B 区"}.get(str(_host(m) or "")[:4]))
    if len(st) < 2:
        return []
    hi = max(st, key=lambda k: st[k][0])
    lo = min(v[0] for v in st.values())
    if st[hi][0] - lo < p["gap"]:
        return []
    out = sum(1 for m in rows if _v(m) > float(m["data"]["upper_tol_mm"]))
    return [Finding("cl_err", "服务错误率：{} 比另一个区高 {:.3f} 个百分点".format(hi, st[hi][0] - lo),
                    "按可用区：" + _fmt(st, "%", 3), severity="critical" if out else "warn",
                    subject=("Machine", "cl-a1" if hi == "A 区" else "cl-b1"), evidence=_ev(rows), hint=r.get("hint"),
                    values={"by_zone": {k: round(v[0], 4) for k, v in st.items()}, "zone": hi, "out": out})]
