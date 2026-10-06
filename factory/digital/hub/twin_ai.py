# -*- coding: utf-8 -*-
"""数字孪生的 AI（第 15 轮 T6、T7）：诊断说明（规则先写，有模型时改写——国内 DeepSeek，美国 Claude）、维修单内容、机队反馈设计。"""
import json

from twin import models as M

ACTION_NAME = {"oil": "换油", "cooling": "清洁散热、检查风扇和油位", "bearing": "更换轴承"}


def rules_explain(d):
    sm, st = d["summary"], d["state"]
    ev = [e for e in d.get("events") or [] if e["status"] == "open" and e["kind"] != "maint"]
    lines = ["这台 {} 在{}，{} 起运行，累计 {:.0f} 小时、起动 {} 次，平均每天 {:.1f} 小时。".format(
        d["serial"], d.get("customer") or "现场", d.get("start_day"), st["run_h"], st["starts"], sm["hours_per_day"])]
    w = sm["worst_bearing"]
    lines.append("寿命：最先到期的是{}（{}），已用 L10 的 {:.0%}{}；输出轴疲劳损伤 {:.2%}，远没到 1。中间轴轴承 B 离第二级小齿轮近、"
                 "转速又是输出轴的 3.5 倍，所以总是它最先到期——这和设计手算一致。".format(
                     w["name"], w["model"], w["used"], "，按最近一个月的用法约 {:.0f} 天后到 L10".format(w["remaining_days"]) if w["remaining_days"] else "",
                     sm["shaft"]["used"]))
    if not ev:
        lines.append("现在没有报警：油温和热平衡模型对得上（差 {:+.1f} ℃），振动 {} 区。".format(sm["resid_c"] or 0, sm["vib_zone"] or "—"))
    for e in ev:
        x = e["detail"]
        lines.append("【{}】{} {} 依据：{} 建议：{}".format({"warn": "警告", "critical": "严重", "info": "提示"}[e["level"]], e["title"],
                                                          x.get("detail", ""), x.get("cause", ""), x.get("advice", "")))
    if any(e["kind"] == "cooling" for e in ev) and any(e["kind"] == "bearing" for e in ev):
        lines.append("油温和振动同时异常时先查轴承：轴承损坏会摩擦发热，修好轴承油温多半跟着恢复。")
    return {"text": "\n".join(lines), "engine": "rules"}


EXPLAIN_TOOL = {
    "name": "explain",
    "description": "给维修工程师讲清这台减速器怎么了",
    "input_schema": {"type": "object", "required": ["text"], "properties": {
        "text": {"type": "string", "description": "4–8 句中文：现在的状态、最要紧的问题和依据（引用给出的数字）、最可能的原因、先做什么后做什么、多急；不要编造没给的数字"}}},
}


def explain(llm, d):
    base = rules_explain(d)
    if llm is None or not llm.available():
        return base
    got = {}

    def call_tool(name, args):
        got.update(args)
        return {"ok": True}
    ctx = {"serial": d["serial"], "customer": d.get("customer"), "summary": d["summary"],
           "open_alerts": [{"title": e["title"], "level": e["level"], **(e["detail"] or {})} for e in d.get("events") or []
                           if e["status"] == "open" and e["kind"] != "maint"],
           "recent": [{k: r.get(k) for k in ("day", "oil_t_c", "oil_model_c", "vib_mm_s", "torque_mean_nm", "torque_max_nm", "t_amb_c")}
                      for r in (d.get("log") or [])[-10:]], "rule_notes": base["text"]}
    try:
        llm.run("你是减速器的预测性维护工程师，根据数字孪生的数据给维修工程师讲解。只用给出的数据；调用 explain 一次。",
                [{"role": "user", "content": json.dumps(ctx, ensure_ascii=False, default=str)[:12000]}], [EXPLAIN_TOOL], call_tool, max_turns=2)
    except Exception:  # noqa: BLE001
        return base
    return {"text": got["text"].strip(), "engine": llm.name} if got.get("text") else base


def order_preview(d, event, action):
    """维修单（ERPNext 的 Issue / 服务工单）内容"""
    x = event["detail"] if event else {}
    kind = action.split(":")[0]
    bid = action.split(":")[1] if ":" in action else None
    what = ACTION_NAME.get(kind, action)
    if bid:
        b = M.BRG[bid]
        what = "更换{}（{}）".format(b[1], b[2])
    subject = "[{}] {}：{}".format(d["serial"], d.get("customer") or "现场", what)
    desc = "\n".join(x for x in [
        "设备：WQR-105 减速器 {}（{}起运行，累计 {:.0f} h）".format(d["serial"], d.get("start_day") or "", d["state"]["run_h"]),
        "诊断：" + event["title"] if event else "",
        x.get("detail", ""), "依据：" + x.get("cause", "") if x.get("cause") else "",
        "要做：" + what + ("。" + x["advice"] if x.get("advice") else ""),
        "来源：问渠数字工厂 · 数字孪生"] if x)
    return {"serial": d["serial"], "customer": d.get("customer"), "action": action, "what": what, "subject": subject[:140],
            "description": desc, "event_id": event["id"] if event else None,
            "priority": "紧急" if event and event["level"] == "critical" else "一般"}


def feedback(fleet_rows):
    """机队数据反馈设计（T7）：每类客户的实际载荷和设计假设（额定 350 N·m）比，寿命最短的部位。
    fleet_rows：[(site, label, logs)]，logs 是每台最近一年的日志行"""
    out = []
    for site, label, units in fleet_rows:
        hours = num_mean = num_cube = shocks = days = 0.0
        tmax = []
        rate = {b[0]: 0.0 for b in M.BEARINGS}
        span = 0.0
        for logs in units:
            for r in logs:
                for t, h in r.get("load_hist") or []:
                    hours += h
                    num_mean += t * h
                    num_cube += t ** 3 * h
                if r.get("run_h"):
                    days += r.get("period_h", 24) / 24
                    if r.get("torque_max_nm"):
                        tmax.append(r["torque_max_nm"])
                        if r.get("period_h", 24) <= 24 and r["torque_max_nm"] > 2 * M.RATED_T_NM:
                            shocks += 1
                for k, v in (r.get("d_brg") or {}).items():
                    rate[k] += v
                span += r.get("period_h", 24) / 24
        if not hours:
            continue
        tm, teq = num_mean / hours, (num_cube / hours) ** (1 / 3)
        tmax.sort()
        worst = max(rate, key=rate.get)
        out.append({"site": site, "label": label, "units": len(units), "run_h": hours, "hours_per_day": hours / span if span else 0,
                    "torque_mean_nm": tm, "torque_eq_nm": teq, "eq_vs_rated": teq / M.RATED_T_NM,
                    "torque_max_p95_nm": tmax[int(0.95 * (len(tmax) - 1))] if tmax else None,
                    "shock_days_pct": shocks / days if days else 0, "worst_bearing": worst, "worst_bearing_name": M.BRG[worst][1],
                    "worst_rate_per_year": rate[worst] / span * 365 if span else 0})
    notes = []
    for s in out:
        notes.append("{}：轴承当量转矩 {:.0f} N·m（额定的 {:.0%}），平均每天 {:.1f} h，{}每年用掉 L10 的 {:.0%}，约 {:.1f} 年到期。".format(
            s["label"], s["torque_eq_nm"], s["eq_vs_rated"], s["hours_per_day"], s["worst_bearing_name"],
            s["worst_rate_per_year"], 1 / s["worst_rate_per_year"] if s["worst_rate_per_year"] else float("inf")))
    heavy = [s for s in out if s["worst_rate_per_year"] > 0.25]
    if heavy:
        notes.append("设计建议：{}的中间轴轴承 B 不到 4 年就到 L10。可以把中间轴两端换成 6306（同内径 30 mm，SKF 样本 C = 29.6 kN，寿命约 (29.6/20.3)³ ≈ 3.1 倍，箱体轴承孔要跟着改），"
                     "或给这类客户选大一号的减速器；输出轴疲劳损伤很小，输出轴还有减重余地（见设计优化）。".format(
                         "、".join(s["label"] for s in heavy)))
    return {"sites": out, "notes": notes}
