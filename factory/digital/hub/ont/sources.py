# -*- coding: utf-8 -*-
"""不在总线上的来源 → 本体（定时对账，每分钟一次；没变化就不写库）。

工厂主数据（产品、物料、BOM、设备、客户、供应商、仓库、检验计划、零件库对应）、PLM 表（设计提交、工艺规程）、
质量表（不合格品、8D、问题情景）、数字孪生（现场设备、总成装配、服务工单）、计算服务作业、任务单、提议、虚拟 PLC、指标、工单成本。
来源序号记作 None（属性来源写成 "表名"），在 360 页上显示为“来自 xx 表”。"""
import datetime as dt
import logging

from factory import data as F
from sim import errors as ERR
from wqbus import UNITS

log = logging.getLogger("hub.ont")

ITEM_KIND = {"raw": "原材料", "buy": "外购件", "make": "自制零件", "fg": "成品", "sub": "部件"}


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _ts(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def master(B, mode):
    """工厂主数据（每次启动和重放时写一次；值不变就不产生写入）"""
    B.obj(mode, "Plant", "wqr", {"name": "问渠减速器厂", "product_line": "WQR-105 二级圆柱齿轮减速器", "mode": mode})
    B.obj(mode, "Product", "WQR-105", {"name": "二级圆柱齿轮减速器", "price": F.FG_SELLING_PRICE, "rated_torque_nm": 350.0})
    B.link(mode, "Product", "WQR-105", "item", "WQR-105")
    sup_name = {k: v["name"] for k, v in F.SUPPLIERS.items()}
    for k, v in F.SUPPLIERS.items():
        B.obj(mode, "Supplier", v["name"], {"name": v["name"], "lead_days": v["lead"], "category": k})
    for code, it in F.ITEMS.items():
        name, kind, uom, cost, sup = it[0], it[1], it[2], it[3], it[4]
        B.obj(mode, "Item", code, {"name": name, "kind": ITEM_KIND.get(kind, kind), "uom": uom, "std_cost": cost,
                                   "safety_stock": F.SAFETY_STOCK.get(code)})
        if sup in sup_name:
            B.link(mode, "Item", code, "supplier", sup_name[sup])
        ref = F.LIBRARY_REFS.get(code)
        if ref:
            B.obj(mode, "LibraryEntry", ref, {"name": name})
            B.link(mode, "Item", code, "library", ref)
            B.alias(mode, ref, "Item", code)
            B.alias(mode, ref.split("/")[-1], "Item", code)                    # 6207、M12x110……
    for code, (rt, lines) in F.BOMS.items():
        key = "BOM-" + code
        B.obj(mode, "Bom", key, {"lines": [{"item_code": c, "qty": q} for c, q in lines], "active": True})
        B.link(mode, "Bom", key, "item", code)
        for c, q in lines:
            B.link(mode, "Bom", key, "component", c, {"qty": q})
    for c in F.CUSTOMERS:
        B.obj(mode, "Customer", c, {"name": c, "demo": "(Demo)" in c})
    for w in F.WAREHOUSES:
        B.obj(mode, "Warehouse", w, {"kind": w.split(" ")[0]})
    for u, info in UNITS.items():
        if not u.startswith(("agv-", "store-")):
            B.obj(mode, "Machine", u, {"code": u.upper(), "name": info[1], "kind": info[3] if len(info) > 3 else info[1]})
            B.alias(mode, u.upper(), "Machine", u)
    B.obj(mode, "InspectionPlan", "SH-301", {"chars": [{"code": c[0], "name": c[1], "nominal": c[2], "lower": c[3], "upper": c[4]}
                                                       for c in ERR.CHARS]})
    B.link(mode, "InspectionPlan", "SH-301", "item", "SH-301")



def tables(B, db, mode):
    """PLM、质量、孪生、任务单、提议、虚拟 PLC"""
    for r in db.q("select * from design_submission where mode=%s", (mode,)):
        B.obj(mode, "DesignSubmission", r["id"], {"item": r["item"], "status": r["status"], "author": r["author"], "note": r["note"],
                                                  "revision": r["revision"], "submitted_at": _ts(r["ts"]), "decided_by": r["decided_by"]},
              ts=_ts(r["ts"]), upd_ts=_now(), text="提交设计")
        B.link(mode, "DesignSubmission", r["id"], "item", r["item"])
        if r["revision"]:
            B.link(mode, "DesignRevision", "{}-rev{}".format(r["item"], r["revision"]), "submission", r["id"])
    for r in db.q("select * from process_submission where mode=%s", (mode,)):
        ops = (r["plan"] or {}).get("ops") if isinstance(r["plan"], dict) else None
        B.obj(mode, "ProcessPlan", r["id"], {"item": r["item"], "status": r["status"], "revision": r["revision"], "author": r["author"],
                                             "ops": ops}, ts=_ts(r["ts"]), upd_ts=_now(), text="提交工艺规程")
        B.link(mode, "ProcessPlan", r["id"], "item", r["item"])
        if r["status"] == "approved":
            B.link(mode, "Item", r["item"], "process_plan", r["id"])
    for r in db.q("select * from ncr where mode=%s or mode is null", (mode,)):
        B.obj(mode, "Ncr", r["ncr_id"], {"part": r["part_serial"], "status": r["status"], "detail": r.get("detail"),
                                         "created": _ts(r["created_at"])}, ts=_ts(r["created_at"]), upd_ts=_now(), text="开不合格品单")
        B.link(mode, "Ncr", r["ncr_id"], "part", r["part_serial"])
        if r.get("work_order"):
            B.link(mode, "Ncr", r["ncr_id"], "work_order", r["work_order"])
    for r in db.q("select * from quality_8d where mode=%s", (mode,)):
        B.obj(mode, "Q8d", r["id"], {"title": r["title"], "status": r["status"], "characteristic": r["characteristic"], "author": r["author"],
                                     "created": _ts(r["created_at"])}, ts=_ts(r["created_at"]), upd_ts=_now(), text="开 8D")
        B.link(mode, "Q8d", r["id"], "item", r["item"])
    for r in db.q("select * from quality_problem where mode=%s", (mode,)):
        p = ERR.PROBLEMS.get(r["problem"], {})
        B.obj(mode, "QualityProblem", str(r["id"]), {"name": p.get("name", r["problem"]), "unit": p.get("unit"), "magnitude": r["magnitude"],
                                                     "injected_at": _ts(r["injected_at"]), "cleared_at": _ts(r["cleared_at"])},
              ts=_ts(r["injected_at"]), upd_ts=_now(), text="老师注入")
        if p.get("unit"):
            B.link(mode, "QualityProblem", str(r["id"]), "machine", p["unit"])
    twin(B, db, mode)
    for r in db.q("select * from task_sheet"):
        spec = r["spec"] or {}
        t = spec.get("标题") or ["", ""]
        B.obj(mode, "TaskSheet", r["id"], {"code": r["code"], "title": t[0] if isinstance(t, list) else t, "course": r["course_name"],
                                           "due": str(r["due"])[:10] if r["due"] else None, "status": r["status"]})
    for r in db.q("select * from ai_proposal where mode=%s", (mode,)):
        B.obj(mode, "Proposal", r["proposal_id"], {"title": r["title"], "action": r["action"], "status": r["status"],
                                                   "requested_by": r["requested_by"], "confirmed_by": r["confirmed_by"],
                                                   "created": _ts(r["created_at"])}, ts=_ts(r["created_at"]), upd_ts=_now(), text="提议")
    anomalies(B, db, mode)
    plans(B, db, mode)
    agent_objs(B, db, mode)
    try:
        for r in db.q("select id, unit, created_by, summary, alarms, status from plc_run where mode=%s", (mode,)):
            sm = r["summary"] or {}
            B.obj(mode, "PlcRun", r["id"], {"unit": r["unit"], "author": r["created_by"], "cycles": sm.get("n"),
                                            "faults": len(r["alarms"] or [])})
            B.link(mode, "PlcRun", r["id"], "machine", r["unit"])
    except Exception:  # noqa: BLE001  —— 没有虚拟 PLC 表时跳过
        pass


def anomalies(B, db, mode):
    """厂情中枢的异常（第 17 轮 B 期）：开着的和 30 天内结束的，映射成本体对象，连到涉及的对象"""
    if not db.one("select to_regclass('anomaly') is not null as ok")["ok"]:
        return
    for r in db.q("select * from anomaly where mode=%s and (status in ('open', 'ack', 'doing') or closed_at > now() - interval '30 days')",
                  (mode,)):
        key = "A-{:05d}".format(r["id"])
        B.obj(mode, "Anomaly", key, {"title": r["title"], "rule": r["rule"], "domain": r["domain"], "severity": r["severity"],
                                     "status": r["status"], "role": r["role"], "first_seen": _ts(r["first_seen"]),
                                     "last_seen": _ts(r["last_seen"]), "hits": r["hits"]},
              ts=_ts(r["first_seen"]), upd_ts=_now(), text="发现：" + r["title"])
        for t, k in ((r["detail"] or {}).get("about") or []):
            if t in B.onto.types and k:
                B.link(mode, "Anomaly", key, "about", k, to_type=t)


def plans(B, db, mode):
    """推演场景和动作（第 17 轮 C 期）"""
    if not db.one("select to_regclass('action') is not null and to_regclass('scenario') is not null as ok")["ok"]:
        return
    for r in db.q("select id, title, changes, result->'cost_total' as cost, created_by, anomaly_id, created_at from scenario "
                  "where mode=%s and created_at > now() - interval '60 days'", (mode,)):
        key = "SC-{:05d}".format(r["id"])
        B.obj(mode, "Scenario", key, {"title": r["title"], "changes": r["changes"], "cost_total": r["cost"], "created_by": r["created_by"],
                                      "created": _ts(r["created_at"])}, ts=_ts(r["created_at"]), upd_ts=_now(), text="推演：" + r["title"])
        if r["anomaly_id"]:
            B.link(mode, "Scenario", key, "anomaly", "A-{:05d}".format(r["anomaly_id"]))
    unit_of = {"reassign": "from_unit", "reorder": "unit", "expedite": "unit", "outsource": "unit"}
    for r in db.q("select * from action where mode=%s and created_at > now() - interval '60 days'", (mode,)):
        key = "ACT-{:05d}".format(r["id"])
        p = r["params"] or {}
        B.obj(mode, "ActionRun", key, {"title": r["title"], "type": r["type"], "status": r["status"], "initiator": r["initiator"],
                                       "approver": r["approver"], "result": (r["result"] or {}).get("text") or (r["result"] or {}).get("error"),
                                       "created": _ts(r["created_at"]), "executed": _ts(r["executed_at"])},
              ts=_ts(r["created_at"]), upd_ts=_now(), text="起草：" + r["title"])
        if r["anomaly_id"]:
            B.link(mode, "ActionRun", key, "anomaly", "A-{:05d}".format(r["anomaly_id"]))
        if r["scenario_id"]:
            B.link(mode, "ActionRun", key, "scenario", "SC-{:05d}".format(r["scenario_id"]))
        targets = []
        if unit_of.get(r["type"]) and p.get(unit_of[r["type"]]):
            targets.append(("Machine", p[unit_of[r["type"]]]))
        if p.get("work_order"):
            targets.append(("WorkOrder", p["work_order"]))
        if p.get("item"):
            targets.append(("Item", p["item"]))
        if p.get("sales_order"):
            targets.append(("SalesOrder", p["sales_order"]))
        for t, k in targets:
            B.link(mode, "ActionRun", key, "about", k, to_type=t)


def agent_objs(B, db, mode):
    """AI 运行、厂情报告、复盘（第 17 轮 D 期）"""
    ok = db.one("select to_regclass('ai_run') is not null as a, to_regclass('report') is not null as r, to_regclass('retro') is not null as t")
    if (ok or {}).get("a"):
        for r in db.q('select id, kind, question, "user", engine, steps, refs, "check", feedback, anomaly_id, created_at from ai_run '
                      "where mode=%s and created_at > now() - interval '60 days'", (mode,)):
            key = "AI-{:05d}".format(r["id"])
            B.obj(mode, "AiRun", key, {"question": (r["question"] or "")[:200], "kind": r["kind"], "user": r["user"], "engine": r["engine"],
                                       "tools": [x.get("tool") for x in r["steps"] or []], "verified": (r["check"] or {}).get("ok"),
                                       "feedback": r["feedback"], "created": _ts(r["created_at"])},
                  ts=_ts(r["created_at"]), upd_ts=_now(), text="提问：" + (r["question"] or "")[:60])
            if r["anomaly_id"]:
                B.link(mode, "AiRun", key, "anomaly", "A-{:05d}".format(r["anomaly_id"]))
            for f in r["refs"] or []:
                if f.get("kind") == "object" and f.get("type") in B.onto.types:
                    B.link(mode, "AiRun", key, "looked_at", f["key"].split("|", 1)[1], to_type=f["type"])
                elif f.get("kind") == "action":
                    B.link(mode, "AiRun", key, "drafted", "ACT-{:05d}".format(int(f["key"])))
    if (ok or {}).get("r"):
        for r in db.q("select id, kind, title, period_start, period_end, engine, data, created_at from report where mode=%s "
                      "and created_at > now() - interval '120 days'", (mode,)):
            key = "RPT-{:05d}".format(r["id"])
            B.obj(mode, "Report", key, {"title": r["title"], "kind": r["kind"], "period_start": _ts(r["period_start"]),
                                        "period_end": _ts(r["period_end"]), "engine": r["engine"], "created": _ts(r["created_at"])},
                  ts=_ts(r["created_at"]), upd_ts=_now(), text="生成：" + r["title"])
            for aid in ((r["data"] or {}).get("anomaly_ids") or [])[:40]:
                B.link(mode, "Report", key, "mentions", "A-{:05d}".format(aid), to_type="Anomaly")
    if (ok or {}).get("t"):
        for r in db.q("select * from retro where mode=%s and created_at > now() - interval '120 days'", (mode,)):
            key = "RT-{:05d}".format(r["id"])
            dv = r["deviation"] or {}
            B.obj(mode, "Retro", key, {"title": r["title"], "predicted_cost": (r["predicted"] or {}).get("cost_total"),
                                       "actual_cost": (r["actual"] or {}).get("cost_total"), "deviation_pct": dv.get("finish_pct"),
                                       "causes": [c.get("text") for c in r["causes"] or []], "created": _ts(r["created_at"])},
                  ts=_ts(r["created_at"]), upd_ts=_now(), text="复盘：" + r["title"])
            if r["anomaly_id"]:
                B.link(mode, "Retro", key, "anomaly", "A-{:05d}".format(r["anomaly_id"]))
            if r["scenario_id"]:
                B.link(mode, "Retro", key, "scenario", "SC-{:05d}".format(r["scenario_id"]))
            if r["action_id"]:
                B.link(mode, "Retro", key, "action", "ACT-{:05d}".format(r["action_id"]))


def twin(B, db, mode):
    from hub import twin as TW
    try:
        units = TW.fleet(db, mode)
    except Exception:  # noqa: BLE001
        return
    rows = db.q("select serial, as_built, created from twin where mode=%s", (mode,))
    built = {r["serial"]: r["as_built"] or {} for r in rows}
    born = {r["serial"]: r["created"] for r in rows}
    for u in units:
        s, sm = u["serial"], u["summary"]
        wb = sm["worst_bearing"]
        B.obj(mode, "FieldUnit", s, {"customer": u["customer"], "site": u["site"], "start_day": u["start_day"], "run_h": round(u["run_h"], 1),
                                     "health": u["health"], "worst_bearing": "{}（{}）".format(wb["name"], wb["model"]),
                                     "worst_bearing_used": round(wb["used"] * 100, 2), "shaft_damage": round(sm["shaft"]["used"], 5),
                                     "oil_t_c": (u.get("last") or {}).get("oil_t_c"), "vib_mm_s": sm.get("vib"),
                                     "alerts": [a["title"] for a in u["alerts"]] or None},
              ts=_ts(born.get(s)), upd_ts=_now(), text="建档（跑合试验通过，出厂）")
        if u["customer"]:
            B.obj(mode, "Customer", u["customer"], {"name": u["customer"]})
            B.link(mode, "FieldUnit", s, "customer", u["customer"])
        ab = built.get(s, {})
        B.obj(mode, "PartSerial", s, {"item": u["item"], "work_order": ab.get("work_order")})
        B.link(mode, "PartSerial", s, "became", s)
        sh = (ab.get("shaft") or {}).get("serial")
        if sh:
            B.obj(mode, "PartSerial", sh, {"item": "SH-301", "work_order": (ab.get("shaft") or {}).get("work_order")})
            B.link(mode, "PartSerial", sh, "installed_in", s)
    for e in db.q("select id, serial, ts, day, title, status, detail from twin_event where mode=%s and kind='order'", (mode,)):
        key = (e["detail"] or {}).get("issue") or "TW-{}".format(e["id"])
        B.obj(mode, "ServiceOrder", key, {"subject": e["title"], "status": e["status"], "action": (e["detail"] or {}).get("action"),
                                          "opened": str(e["day"]) if e["day"] else None}, ts=_ts(e["ts"]), upd_ts=_now(), text="开维修单")
        B.link(mode, "ServiceOrder", key, "unit", e["serial"])


def jobs(B, mode, factory_id, call):
    """计算服务的作业（强度、疲劳、温度、流体、动力学、优化、拓扑、数控编程）"""
    try:
        rows = call("GET", "/jobs", params={"factory": factory_id, "limit": 500}).json()["jobs"]
    except Exception:  # noqa: BLE001  —— 计算服务不在时跳过，下次再对
        return
    for j in rows:
        if (j.get("mode") or mode) != mode and j.get("mode"):
            continue
        st = j.get("stats") or {}
        res = {k: st[k] for k in ("vm_max_mpa", "safety_factor", "t_max_c", "h_mean", "drag_n", "life_hours", "best", "cells") if k in st} or None
        B.obj(mode, "AnalysisJob", j["id"], {"title": j.get("title") or j.get("kind"), "kind": j.get("kind") or "static",
                                             "status": j.get("status"), "owner": j.get("owner_name"), "created": j.get("created"),
                                             "result": res})
        if j.get("item"):
            B.link(mode, "AnalysisJob", j["id"], "item", j["item"])


def metrics(B, db, mode):
    from hub import kpi
    try:
        ov = kpi.overview(db, mode=mode)
    except Exception:  # noqa: BLE001
        return
    for k in ov["kpis"]:
        v = k["value"]
        B.obj(mode, "Metric", k["key"], {"name": k["label"], "value": round(v, 4) if isinstance(v, float) else v,
                                         "target": {"on_time": 0.95, "oee": 0.75, "fpy": 0.97}.get(k["key"]),
                                         "unit": {"pct0": "比例", "pct1": "比例", "pct_signed": "比例", "int": k.get("unit", "")}.get(k["fmt"], "")},
              silent=True)


def costs(B, db, mode):
    from hub import mrp
    for o in db.q("select key from ont_object where mode=%s and type='WorkOrder' and coalesce(props->>'demo','false') <> 'true' "
                  "order by updated_at desc limit 30", (mode,)):
        c = mrp.wo_cost(db, o["key"], mode)
        if c:
            B.obj(mode, "CostRecord", o["key"], {"std_total": c["std_cost"], "act_total": c["actual_cost"], "variance_pct": c["variance_pct"]})
            B.link(mode, "CostRecord", o["key"], "work_order", o["key"])
