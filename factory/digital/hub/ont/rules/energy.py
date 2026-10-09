# -*- coding: utf-8 -*-
"""能源与环境（第 18 轮 E6）：N1 单耗突增、N2 空转能耗高、N3 峰时用电占比高、N4 压缩空气基荷高（可能漏气）、
N5 需量接近合同需量、N6 车间环境指标超限。数据来自计量读数（hub/energy.py，工厂时间）。"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


def _end(c):
    """最新读数的结束时刻；没有读数、读数停了 3 小时以上（车间没在跑）就不判"""
    from hub import energy as EN
    if not c.get("has_energy_read", lambda: bool(c.db.one("select to_regclass('energy_read') is not null as ok")["ok"])):
        return None
    t = EN.latest_ts(c.db, c.mode)
    if t is None:
        return None
    end = t + dt.timedelta(minutes=15)
    now = EN.now_of(c.db, c.mode) if c.mode == "teach" else c.now
    if (now - end).total_seconds() > 3 * 3600:
        return None
    return end


@rule("unit_energy_jump")
def unit_energy_jump(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    out = []
    for x in EN.unit_energy(c.db, c.mode, end, recent_parts=int(p.get("parts", 3)), recent_h=float(p.get("recent_h", 24))):
        if x["unit"] in ("ht-01",) or x["change"] is None or x["recent_parts"] < int(p.get("min_parts", 2)):
            continue
        if x["change"] <= float(p.get("pct", 0.25)):
            continue
        out.append(Finding("{}/{}".format(x["unit"], x["item"]), "{} 单件能耗比基线高 {:.0%}（{}）".format(x["unit"].upper(), x["change"], x["item"]),
                           "最近 {} 件每件 {:.2f} 度；基线 {:.2f} 度（{}）。多半是设备在劣化：主轴轴承、刀具 / 砂轮".format(
                               x["recent_parts"], x["recent"], x["base"], "近 7 天" if x["base_from"] == "history" else "标准工时 × 运行功率"),
                           severity="warn", subject=("Machine", x["unit"]), about=[("Machine", x["unit"]), ("Meter", "E-" + x["unit"].upper())],
                           hint=r.get("hint"), values={"unit": x["unit"], "item": x["item"], "recent": x["recent"], "base": x["base"], "change": x["change"]}))
    return out


@rule("idle_energy")
def idle_energy(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    hits = [x for x in EN.idle_by_unit(c.db, c.mode, float(p.get("hours", 12)), end)
            if x["idle_share"] > float(p.get("share", 0.3)) and x["idle_h"] >= float(p.get("min_h", 1)) and x["idle_kwh"] >= float(p.get("min_kwh", 10))]
    hits.sort(key=lambda x: -x["idle_kwh"])
    price = float(EN.params(c.db, c.mode)["price"]["flat"])
    out = []
    for x in hits[:int(p.get("top", 3))]:
        out.append(Finding(x["unit"], "{} 空转 {:g} 小时，空转电量占 {:.0%}".format(x["unit"].upper(), x["idle_h"], x["idle_share"]),
                           "近 {:g} 小时空转 {:.1f} 度（约 ${:,.2f}）：开着没活".format(float(p.get("hours", 12)), x["idle_kwh"], x["idle_kwh"] * price),
                           severity="info", subject=("Machine", x["unit"]), about=[("Machine", x["unit"]), ("Meter", "E-" + x["unit"].upper())],
                           hint=r.get("hint"), values=dict(x)))
    return out


@rule("peak_share_high")
def peak_share_high(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    x = EN.peak_share(c.db, c.mode, 24, end)
    if x["hours"] < float(p.get("min_h", 20)) or x["share"] <= float(p.get("share", 0.3)):
        return []
    day = end.strftime("%Y-%m-%d")
    return [Finding(day, "峰时用电占 {:.0%}（目标 {:.0%} 以下）".format(x["share"], float(p.get("share", 0.3))),
                    "近 24 小时 {:.0f} 度，峰时 {:.0f} 度，其中热处理炉 {:.0f} 度".format(x["kwh"], x["peak_kwh"], x["ht_peak_kwh"]),
                    severity="warn", subject=("Meter", "E-TOTAL"), about=[("Meter", "E-TOTAL"), ("Machine", "ht-01")], hint=r.get("hint"), values=dict(x))]


@rule("air_base_high")
def air_base_high(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    x = EN.air_excess(c.db, c.mode, float(p.get("hours", 4)), end)
    if x["hours"] < float(p.get("min_h", 2)) or x["excess_kw"] <= float(p.get("kw", 3)):
        return []
    return [Finding("E-AIR", "空压机比该用的多 {:.1f} kW（可能漏气）".format(x["excess_kw"]),
                    "近 {:g} 小时平均 {:.1f} kW，按开着的用气设备应 {:.1f} kW".format(x["hours"], x["actual_kw"], x["expected_kw"]),
                    severity="warn", subject=("Meter", "E-AIR"), hint=r.get("hint"), values=dict(x))]


@rule("demand_near")
def demand_near(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    x = EN.demand(c.db, c.mode, end)
    if x["ratio"] <= float(p.get("ratio", 0.9)):
        return []
    return [Finding((x["at"] or "")[:7], "本月最大需量 {:.0f} kW，到合同需量的 {:.0%}".format(x["kw"], x["ratio"]),
                    "合同需量 {:.0f} kW；{}超了要按超出部分加价".format(x["contract_kw"], "已经" if x["ratio"] > 1 else "再高一点就"),
                    severity="critical" if x["ratio"] > 1 else "warn", subject=("Meter", "E-TOTAL"), about=[("Meter", "E-TOTAL"), ("Machine", "ht-01")],
                    hint=r.get("hint"), values=dict(x))]


@rule("env_over")
def env_over(c, p, r):
    from hub import energy as EN
    end = _end(c)
    if end is None:
        return []
    out = []
    for pt, x in EN.env_now(c.db, c.mode, float(p.get("hours", 1)), end).items():
        if not x["over"] or x["n"] < 2:
            continue
        out.append(Finding(pt, "{} {:.1f} {}，超过限值 {:g}".format(x["label"], x["value"], x["unit"], x["limit"]),
                           "近 {:g} 小时平均；最高 {:.1f}".format(float(p.get("hours", 1)), x["max"] or x["value"]),
                           severity="warn", subject=("Meter", "ENV-" + pt.upper()), hint=r.get("hint"),
                           values={"point": pt, "value": x["value"], "limit": x["limit"]}))
    return out
