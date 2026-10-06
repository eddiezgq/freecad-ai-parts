# -*- coding: utf-8 -*-
"""客户服务：V1 现场设备报警（读孪生）、V2 同批多台报警、V3 服务工单超时"""
import datetime as dt

from hub.ont.anomaly import Finding
from hub.ont.rules import rule

LEVEL = {"red": "critical", "yellow": "warn"}


def fleet(c):
    from hub import twin as TW
    return c.get("fleet", lambda: TW.fleet(c.db, c.mode))


def field_today(c):
    r = c.db.one("select * from field_clock where mode=%s", (c.mode,))
    if not r:
        return None
    if r["paused"]:
        return r["anchor_day"]
    mins = (c.now - r["anchor_real"]).total_seconds() / 60
    return r["anchor_day"] + dt.timedelta(days=int(mins * r["days_per_min"]))


@rule("field_alarm")
def field_alarm(c, p, r):
    out = []
    for u in fleet(c):
        if u["health"] not in LEVEL:
            continue
        titles = [a["title"] for a in u["alerts"]] or ["健康度 {}".format(u["health"])]
        out.append(Finding(u["serial"], "现场设备 {}（{}）报警：{}".format(u["serial"], u["customer"], titles[0]),
                           "；".join(titles), severity=LEVEL[u["health"]], subject=("FieldUnit", u["serial"]),
                           evidence=[{"topic": "wq/gearbox/field/{}/telemetry".format(u["serial"])}],
                           hint="在数字孪生页查看寿命与建议；查同批设备", about=[("FieldUnit", u["serial"]), ("Customer", u["customer"])],
                           values={"health": u["health"], "customer": u["customer"], "site": u["site"], "alerts": titles}))
    return out


def shaft_batch(c, serials):
    """现场设备 → 出厂输出轴 → 磨削它的砂轮、它的工单（从本体读）"""
    out = {}
    for s in serials:
        sh = c.db.one("select src_key from ont_link where mode=%s and type='PartSerial.installed_in' and dst_key=%s", (c.mode, s))
        if not sh:
            continue
        g = c.db.one("select props from ont_link where mode=%s and type='PartSerial.processed' and src_key=%s and props->>'machine'='grd-01'",
                     (c.mode, sh["src_key"]))
        wo = c.db.one("select props->>'work_order' as wo from ont_object where mode=%s and type='PartSerial' and key=%s", (c.mode, sh["src_key"]))
        out[s] = {"shaft": sh["src_key"], "wheel": (g["props"] or {}).get("tool") if g else None, "work_order": wo["wo"] if wo else None}
    return out


@rule("field_batch")
def field_batch(c, p, r):
    kinds = set(p.get("kinds") or [])
    alarmed = [u["serial"] for u in fleet(c) if u["health"] in LEVEL and any(a.get("kind") in kinds for a in u["alerts"])]
    if len(alarmed) < p["min_units"]:
        return []
    b = shaft_batch(c, alarmed)
    groups = {}
    for s, x in b.items():
        if x["wheel"]:
            groups.setdefault(("Tool", x["wheel"]), []).append(s)
        if x["work_order"]:
            groups.setdefault(("WorkOrder", x["work_order"]), []).append(s)
    out = []
    for (t, k), units in groups.items():
        if len(units) < p["min_units"]:
            continue
        what = "同一片砂轮 {}".format(k) if t == "Tool" else "同一张工单 {}".format(k)
        out.append(Finding("{}:{}".format(t, k), "同批多台报警：{} 台设备的输出轴出自{}".format(len(units), what),
                           "报警设备：{}。同批的其他设备要排查".format("、".join(sorted(units))), subject=(t, k),
                           hint="看因果链里的“建议排查范围”，安排预防性服务；查这批轴的检验数据",
                           about=[(t, k)] + [("FieldUnit", s) for s in units] + [("PartSerial", b[s]["shaft"]) for s in units],
                           values={"units": sorted(units), "by": t, "batch": k}))
    return out


@rule("service_overdue")
def service_overdue(c, p, r):
    today = field_today(c)
    if today is None:
        return []
    out = []
    for e in c.db.q("select id, serial, day, title, status, detail from twin_event where mode=%s and kind='order' and status='ordered'", (c.mode,)):
        if not e["day"]:
            continue
        d = (today - e["day"]).days
        if d > p["days"]:
            key = (e["detail"] or {}).get("issue") or "TW-{}".format(e["id"])
            out.append(Finding(key, "服务工单 {} 已开 {} 个现场日未关闭：{}".format(key, d, e["title"]), "设备 {}".format(e["serial"]),
                               subject=("ServiceOrder", key), about=[("ServiceOrder", key), ("FieldUnit", e["serial"])],
                               values={"days": d, "serial": e["serial"]}))
    return out
