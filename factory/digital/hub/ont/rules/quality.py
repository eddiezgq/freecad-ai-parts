# -*- coding: utf-8 -*-
"""质量：Q1 SPC 判异、Q2 趋近公差限（原“质量趋势”）、Q3 不合格品未处置（原“不合格品”）、Q4 一次合格率下降、Q5 8D 久拖未关"""
import datetime as dt

from wqbus.topics import unit_topic

from hub.ont.anomaly import Finding
from hub.ont.rules import rule


@rule("spc_signal")
def spc_signal(c, p, r):
    from hub import spc
    from sim.errors import CHARS
    out = []
    for code, name, *_ in CHARS:
        res = spc.for_characteristic(c.db, c.mode, p.get("item", "SH-301"), code, n=p.get("n", 5))
        if not res.get("signals"):
            continue
        ng = len(res["chart"]["xbar"])
        recent = [s for s in res["signals"] if s["index"] >= ng - p["recent_groups"]]
        if not recent:
            continue
        rules_hit = sorted({s["rule"] for s in recent})
        out.append(Finding(
            code, "{} 控制图判异（西电规则 {}）".format(name, "、".join(map(str, rules_hit))),
            "；".join(s["text"] for s in recent) + "。均值–极差图，每组 {} 件，共 {} 组".format(p.get("n", 5), ng),
            severity="critical" if 1 in rules_hit else "warn", subject=("InspectionPlan", p.get("item", "SH-301")),
            evidence=[{"topic": unit_topic("qc-01", "measurement"), "id": i} for i in res.get("evidence", [])],
            hint="查看控制图；判异不等于超差，先找原因（刀具、热变形、夹具），再决定是否调整",
            values={"characteristic": code, "rules": rules_hit, "groups": ng, "cpk": (res.get("capability") or {}).get("cpk")}))
    return out


@rule("near_limit")
def near_limit(c, p, r):
    ch = c.ov["quality"]["chart"]
    if not (ch.get("points") and len(ch["points"]) >= 5):
        return []
    band = (ch["upper"] - ch["lower"]) * 1000
    if not (ch["margin_um"] <= band * p["margin_frac"] and ch["shift_um"] >= p["shift_um"]):
        return []
    return [Finding(
        ch["characteristic"], "{} 测量值上移，趋近上限".format(ch["title"]),
        "最近 5 件均值 {:.4f} mm，比公差中值高 {:.1f} µm，距上限只余 {:.1f} µm，尚未超差".format(ch["mean_last5"], ch["shift_um"], ch["margin_um"]),
        subject=("InspectionPlan", "SH-301"), evidence=[{"topic": ch["src"], "id": x["id"]} for x in ch["points"][-5:]],
        hint="检查磨床 GRD-01 砂轮磨损，考虑提前修整",
        values={"characteristic": ch["characteristic"], "margin_um": ch["margin_um"], "shift_um": ch["shift_um"],
                "parts": [x.get("part_serial") for x in ch["points"][-5:] if x.get("part_serial")]},
        alert_key="trend:" + ch["characteristic"])]


@rule("ncr_open")
def ncr_open(c, p, r):
    out = []
    for n in c.ov["quality"]["ncr"]:
        d = n["detail"]
        age_h = (c.now - dt.datetime.fromisoformat(n["created_at"])).total_seconds() / 3600
        out.append(Finding(
            n["ncr_id"], "不合格品 {}：{} 超差".format(n["ncr_id"], n["part_serial"]),
            "{} 实测 {} mm，公差 {}–{}".format(d.get("name"), d.get("value_mm"), d.get("lower_tol_mm"), d.get("upper_tol_mm")),
            severity="critical" if age_h > p["escalate_h"] else "warn", subject=("Ncr", n["ncr_id"]),
            evidence=[{"topic": unit_topic("qc-01", "measurement"), "id": d.get("message_id")}],
            hint="质检员评审：返修、报废或让步接收", about=[("Ncr", n["ncr_id"]), ("PartSerial", n["part_serial"])],
            values={"age_h": round(age_h, 1), "part": n["part_serial"], "characteristic": d.get("characteristic")},
            alert_key="ncr:" + n["ncr_id"]))
    return out


@rule("fpy_drop")
def fpy_drop(c, p, r):
    rows = c.db.messages(["quality.measurement"], mode=c.mode, order="desc", limit=p["last_parts"] * 12)
    parts = {}
    for m in rows:
        x = m["data"]
        if x.get("item") != p.get("item", "SH-301"):
            continue
        k = x["part_serial"]
        if k not in parts and len(parts) >= p["last_parts"]:
            continue
        q = parts.setdefault(k, {"ok": True, "ev": m})
        q["ok"] = q["ok"] and x["result"] == "pass"
    if len(parts) < p["min_parts"]:
        return []
    ok = sum(1 for q in parts.values() if q["ok"])
    fpy = ok / len(parts)
    if fpy >= p["below"]:
        return []
    bad = [k for k, q in parts.items() if not q["ok"]]
    return [Finding(p.get("item", "SH-301"), "{} 一次合格率 {:.0%}（最近 {} 件），低于 {:.0%}".format(p.get("item", "SH-301"), fpy, len(parts), p["below"]),
                    "不合格：{}".format("、".join(bad)), subject=("Item", p.get("item", "SH-301")),
                    evidence=[{"topic": parts[k]["ev"]["_topic"], "id": parts[k]["ev"]["id"], "seq": parts[k]["ev"]["_seq"]} for k in bad[:5]],
                    about=[("Item", p.get("item", "SH-301"))] + [("PartSerial", k) for k in bad[:10]],
                    values={"fpy": round(fpy, 4), "parts": len(parts), "bad": bad})]


@rule("q8d_stale")
def q8d_stale(c, p, r):
    out = []
    for q in c.db.q("select id, title, status, created_at, item from quality_8d where mode=%s and closed_at is null", (c.mode,)):
        days = (c.now - q["created_at"]).total_seconds() / 86400
        if days > p["days"]:
            out.append(Finding(q["id"], "8D {} 开了 {:.0f} 天还没关闭：{}".format(q["id"], days, q["title"]),
                               "当前状态：{}".format(q["status"]), subject=("Q8d", q["id"]),
                               values={"days": round(days, 1), "status": q["status"]}))
    return out
