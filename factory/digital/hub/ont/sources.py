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
    from factory import plant
    if plant.is_demo():
        B.obj(mode, "Plant", "wqr", {"name": "问渠减速器厂", "product_line": "WQR-105 二级圆柱齿轮减速器", "mode": mode})
    else:                                       # 企业工厂（第 30 轮；freecad-ai-parts ADR-0064）：工厂对象用清单里的公司
        c = plant.company()
        B.obj(mode, "Plant", "wqr", {"name": c["name"], "mode": mode})
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
    service_objs(B, db, mode)
    ehs_objs(B, db, mode)
    maint_objs(B, db, mode)
    people_objs(B, db, mode)
    supply_objs(B, db, mode)
    energy_objs(B, db, mode)
    finance_objs(B, db, mode)
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


def service_objs(B, db, mode):
    """客户与服务（第 18 轮 E1）：投诉、服务工程师、服务工单的派工、回访与满意度、保修"""
    if not db.one("select to_regclass('complaint') is not null as ok")["ok"]:
        return
    from hub import service as SV
    for r in db.q("select * from complaint where mode=%s and created_at > now() - interval '180 days'", (mode,)):
        key = "CP-{:05d}".format(r["id"])
        B.obj(mode, "Complaint", key, {"subject": r["subject"], "severity": SV.SEVERITY.get(r["severity"]), "status": SV.STATUS.get(r["status"]),
                                       "date": _ts(r["created_at"])[:10] if r["created_at"] else None, "channel": r["channel"], "issue": r["issue"]},
              ts=_ts(r["created_at"]), upd_ts=_now(), text="登记：" + r["subject"])
        if r["customer"]:
            B.obj(mode, "Customer", r["customer"], {"name": r["customer"]})
            B.link(mode, "Complaint", key, "customer", r["customer"])
        if r["serial"]:
            B.link(mode, "Complaint", key, "field_unit", r["serial"])
    for e in db.q("select * from engineer where mode=%s", (mode,)):
        B.obj(mode, "ServiceEngineer", e["id"], {"name": e["name"], "region": e["region"]})
    for j in db.q("select * from service_job where mode=%s and created_at > now() - interval '180 days'", (mode,)):
        if j["issue"]:
            B.obj(mode, "ServiceOrder", j["issue"], {"engineer": j["engineer"], "visit_day": str(j["day"]) if j["day"] else None,
                                                     "action": SV.kind_label(j["kind"]), "opened": _ts(j["created_at"])[:10]})
            if j["engineer"]:
                B.link(mode, "ServiceOrder", j["issue"], "engineer", j["engineer"])
            B.link(mode, "ServiceOrder", j["issue"], "unit", j["serial"])
    for f in db.q("select * from follow_up where mode=%s and created_at > now() - interval '180 days'", (mode,)):
        key = "FU-{:05d}".format(f["id"])
        B.obj(mode, "FollowUp", key, {"score": float(f["score"]) if f["score"] is not None else None, "due": str(f["due_day"]) if f["due_day"] else None},
              ts=_ts(f["created_at"]), upd_ts=_now(), text="回访")
        j = db.one("select issue from service_job where id=%s", (f["job_id"],)) if f["job_id"] else None
        if j and j["issue"]:
            B.link(mode, "FollowUp", key, "order", j["issue"])
        if f["score"] is not None:
            sk = "SV-{:05d}".format(f["id"])
            B.obj(mode, "SatisfactionSurvey", sk, {"score": float(f["score"]), "date": _ts(f["done_at"])[:10] if f["done_at"] else None,
                                                   "comment": f["comment"]}, ts=_ts(f["done_at"]), upd_ts=_now(), text="打分")
            if f["customer"]:
                B.link(mode, "SatisfactionSurvey", sk, "customer", f["customer"])
            if j and j["issue"]:
                B.link(mode, "SatisfactionSurvey", sk, "job", j["issue"])
    try:
        for s_, u in SV.units(db, mode).items():
            B.obj(mode, "Warranty", s_, {"until": u["warranty_until"], "in_warranty": u["in_warranty"]})
            B.link(mode, "Warranty", s_, "unit", s_)
    except Exception:  # noqa: BLE001
        pass


def ehs_objs(B, db, mode):
    """安全环保（第 18 轮 E2）：危险源、隐患、作业许可、事故（3 级敏感）、员工与培训、化学品、废弃物"""
    if not db.one("select to_regclass('safety_issue') is not null as ok")["ok"]:
        return
    from hub import ehs as EH
    for h in db.q("select * from hazard where mode=%s", (mode,)):
        rk = EH.risk(h["likelihood"], h["severity"])
        B.obj(mode, "Hazard", h["id"], {"name": h["name"], "level": rk["level"], "area": h["area"], "score": rk["score"], "controls": h["controls"]})
        if h["unit"] in UNITS:
            B.link(mode, "Hazard", h["id"], "machine", h["unit"])
    for r in db.q("select * from safety_issue where mode=%s and found_at > now() - interval '365 days'", (mode,)):
        k = "SI-{:05d}".format(r["id"])
        B.obj(mode, "SafetyIssue", k, {"subject": r["subject"], "level": EH.LEVEL[r["level"]], "status": EH.STATUS[r["status"]],
                                        "due": str(r["due_day"]) if r["due_day"] else None, "owner": r["owner"], "found_by": r["found_by"]},
              ts=_ts(r["found_at"]), upd_ts=_now(), text="随手拍：" + r["subject"])
        if r["unit"] in UNITS:
            B.link(mode, "SafetyIssue", k, "machine", r["unit"])
        if r["hazard_id"]:
            B.link(mode, "SafetyIssue", k, "hazard", r["hazard_id"])
        if r["permit_id"]:
            B.link(mode, "SafetyIssue", k, "lockout", "PTW-{:05d}".format(r["permit_id"]))
    for p in db.q("select * from ehs_person where mode=%s", (mode,)):
        B.obj(mode, "Employee", p["id"], {"name": p["name"], "status": "在岗" if p["active"] else "离岗", "post": p["post"], "team": p["team"]})
    for t in EH.trainings(db, mode):
        k = "{}:{}".format(t["person_id"], t["kind"])
        B.obj(mode, "SafetyTraining", k, {"topic": t["label"], "date": t["done_day"], "valid_months": EH.TRAININGS.get(t["kind"], ("", 0))[1],
                                          "valid_until": t["valid_until"]})
        B.link(mode, "SafetyTraining", k, "employee", t["person_id"])
    for r in db.q("select * from work_permit where mode=%s and created_at > now() - interval '180 days'", (mode,)):
        k = "PTW-{:05d}".format(r["id"])
        B.obj(mode, "WorkPermit", k, {"kind": EH.PERMITS[r["kind"]], "status": EH.PERMIT_STATUS[r["status"]], "valid_from": _ts(r["valid_from"]) if r["valid_from"] else None,
                                      "valid_to": _ts(r["valid_to"]) if r["valid_to"] else None}, ts=_ts(r["created_at"]), upd_ts=_now(), text="作业许可")
        if r["unit"] in UNITS:
            B.link(mode, "WorkPermit", k, "machine", r["unit"])
        if r["holder_id"]:
            B.link(mode, "WorkPermit", k, "holder", r["holder_id"])
    for r in db.q("select * from incident where mode=%s and day > now() - interval '365 days'", (mode,)):
        k = "IN-{:05d}".format(r["id"])
        B.obj(mode, "Incident", k, {"kind": EH.INCIDENT_KINDS.get(r["kind"]), "severity": r["severity"], "date": str(r["day"]), "root_cause": r["root_cause"]})
        if r["unit"] in UNITS:
            B.link(mode, "Incident", k, "machine", r["unit"])
    for r in db.q("select * from chemical where mode=%s", (mode,)):
        B.obj(mode, "Chemical", r["code"], {"name": r["name"], "stock_kg": float(r["stock_kg"]), "sds": r["sds"]})
    for r in db.q("select * from waste where mode=%s and produced_day > now() - interval '365 days'", (mode,)):
        B.obj(mode, "Waste", "W-{:05d}".format(r["id"]), {"kind": EH.WASTES.get(r["kind"], (r["kind"],))[0], "qty_kg": float(r["qty_kg"]),
                                                          "disposed_by": r["disposed_by"]})


def maint_objs(B, db, mode):
    """设备维护（第 18 轮 E3）：点检、故障记录、平台维修单、备件、保养计划的运行小时"""
    if not db.one("select to_regclass('maint_repair') is not null as ok")["ok"]:
        return
    from hub import maint as MT
    for r in db.q("select * from maint_inspection where mode=%s and at > now() - interval '90 days'", (mode,)):
        k = "IC-{:05d}".format(r["id"])
        B.obj(mode, "Inspection", k, {"result": "异常：" + "、".join(x["item"] for x in r["abnormal"]) if r["abnormal"] else "正常",
                                      "at": _ts(r["at"]), "by": r["by_name"]}, ts=_ts(r["at"]), upd_ts=_now(), text="点检")
        B.link(mode, "Inspection", k, "machine", r["unit"])
    for r in db.q("select * from maint_failure where mode=%s and at > now() - interval '365 days'", (mode,)):
        k = "FL-{:05d}".format(r["id"])
        B.obj(mode, "FailureRecord", k, {"mode": r["name"], "cause": r["code"], "down_min": float(r["down_min"] or 0),
                                         "run_h": float(r["run_h"]) if r["run_h"] is not None else None}, ts=_ts(r["at"]), upd_ts=_now(), text="故障")
        B.link(mode, "FailureRecord", k, "machine", r["unit"])
    for r in db.q("select * from maint_repair where mode=%s and created_at > now() - interval '365 days'", (mode,)):
        k = "MR-{:05d}".format(r["id"])
        B.obj(mode, "RepairOrder", k, {"status": MT.STATUS.get(r["status"]), "description": r["title"],
                                       "cost": sum((r["cost"] or {}).values()) if r["cost"] else None}, ts=_ts(r["created_at"]), upd_ts=_now(), text="维修单")
        B.link(mode, "RepairOrder", k, "machine", r["unit"])
    for code, lo in MT.SPARE_MIN.items():
        B.obj(mode, "SparePart", code, {"stock": MT.stock_of(db, mode, code), "min_stock": lo})
        B.link(mode, "SparePart", code, "item", code)


def supply_objs(B, db, mode):
    """供应链（第 18 轮 E5）：批次、来料检验、供应商评价"""
    if not db.one("select to_regclass('lot') is not null as ok")["ok"]:
        return
    from hub import supply as SP
    for x in db.q("select * from lot where mode=%s and lot is not null and ordered_at > now() - interval '180 days'", (mode,)):
        n = db.one("select count(distinct part_serial) as n from batch_use where mode=%s and lot=%s", (mode, x["lot"]))["n"]
        B.obj(mode, "Batch", x["lot"], {"qty": float(x["qty"]), "qty_left": float(x["qty_left"] or 0), "status": SP.STATUS.get(x["status"]),
                                        "po": x["po"], "parts": n}, ts=_ts(x["ordered_at"]), upd_ts=_now(), text="批次")
        B.link(mode, "Batch", x["lot"], "item", x["item"])
        B.link(mode, "Batch", x["lot"], "supplier", x["supplier"])
        ins = x["inspection"] or {}
        if ins:
            k = "IQ-{}".format(x["lot"])
            B.obj(mode, "IncomingInspection", k, {"result": "合格" if ins.get("status") == "Accepted" else "不合格"}, ts=_ts(x["ordered_at"]), upd_ts=_now(),
                  text="来料检验")
    for s_ in SP.scorecard(db, mode):
        k = "{}-30d".format(s_["supplier"])
        B.obj(mode, "SupplierRating", k, {"on_time": round(s_["on_time"] * 100, 1) if s_["on_time"] is not None else None,
                                          "quality": round(s_["pass_rate"] * 100, 1) if s_["pass_rate"] is not None else None,
                                          "price_index": s_["price_index"], "role": "默认" if s_["role"] == "default" else "备选"})
        B.link(mode, "SupplierRating", k, "supplier", s_["supplier"])
        B.obj(mode, "Supplier", s_["supplier"], {"name": s_["supplier"], "lead_days": s_["lead_days"], "category": s_["cat_name"]})


def finance_objs(B, db, mode):
    """经营与财务（第 18 轮 E7）：应收、应付（ERPNext 发票）、经营目标、本月预算"""
    if not db.one("select to_regclass('invoice') is not null as ok")["ok"]:
        return
    from hub import finance as FN
    for x in db.q("select * from invoice where mode=%s and doc is not null and issued_at > now() - interval '365 days'", (mode,)):
        t = "Receivable" if x["kind"] == "ar" else "Payable"
        props = {"amount": x["amount"], "due": x["due_at"].date().isoformat(), "status": FN.STATUS.get(x["status"]), "outstanding": x["outstanding"]}
        if x["kind"] == "ar":
            props["overdue_days"] = round(FN.overdue_days(mode, x), 1) if x["status"] == "open" else 0
        B.obj(mode, t, x["doc"], props)
        if x["kind"] == "ar":
            if x["ref"] and x["ref"] != "期初":
                B.link(mode, t, x["doc"], "sales_order", x["ref"])
            B.link(mode, t, x["doc"], "customer", x["party"])
        else:
            B.link(mode, t, x["doc"], "supplier", x["party"])
    for o in FN.objectives(db, mode):
        B.obj(mode, "Objective", o["code"], {"name": o["name"], "period": "本年", "owner": o["owner"], "target": o["target"], "value": o["value"],
                                              "status": {"good": "达标", "warn": "接近", "bad": "偏离", "mute": "没有数"}[o["tone"]]})
    bv = FN.budget_view(db, mode)
    for x in bv["rows"]:
        B.obj(mode, "Budget", "{}/{}".format(bv["month"], x["center"]), {"name": x["name"], "amount": x["budget"], "actual": x["actual"]})


def energy_objs(B, db, mode):
    """能源与环境（第 18 轮 E6）：计量点、近 7 天每天每个计量点的用量、本月碳核算"""
    if not db.one("select to_regclass('energy_read') is not null as ok")["ok"]:
        return
    from hub import energy as EN
    from hub import kpi
    if not db.one("select 1 as x from energy_read where mode=%s limit 1", (mode,)):
        return
    for m in EN.meters(db, mode):
        B.obj(mode, "Meter", m["code"], {"medium": m["medium"], "unit": m["unit"], "name": m["label"]})
        if m["machine"]:
            B.link(mode, "Meter", m["code"], "machine", m["machine"])
    end = EN._end(db, mode)
    for r in db.q("select meter, (ts at time zone %s)::date as d, sum(value) as v from energy_read where mode=%s and ts >= %s "
                  "group by 1, 2", (str(kpi.TZ), mode, end - dt.timedelta(days=7))):
        k = "{}/{}".format(r["meter"], r["d"])
        B.obj(mode, "EnergyUse", k, {"value": round(float(r["v"]), 3)})
        B.link(mode, "EnergyUse", k, "meter", r["meter"])
    c = EN.carbon(db, mode)
    B.obj(mode, "CarbonAccount", c["month"], {"t_co2e": c["t_co2e"]})


def people_objs(B, db, mode):
    """人员与组织（第 18 轮 E4）：部门、岗位、员工（补部门、班次）、技能资质、今明两天的排班、技能培训"""
    if not db.one("select to_regclass('roster_post') is not null as ok")["ok"]:
        return
    from hub import people as PE
    erp = {str(m["data"].get("employee_number") or ""): m["data"].get("name") for m in db.erp_docs("Employee", mode)}
    for d, en in PE.DEPTS:
        B.obj(mode, "Department", d, {"name": d})
    for k in PE.POSTS:
        B.obj(mode, "Position", k, {"name": k})
    for p in db.q("select * from ehs_person where mode=%s", (mode,)):
        B.obj(mode, "Employee", p["id"], {"name": p["name"], "status": "在岗" if p["active"] else "离岗", "post": p["post"], "team": p["team"],
                                         "dept": p.get("dept"), "shift": PE.SHIFT_NAME.get(p.get("shift")), "erp_id": erp.get(p["id"])})
        if p.get("dept"):
            B.link(mode, "Employee", p["id"], "department", p["dept"])
        B.link(mode, "Employee", p["id"], "position", p["post"])
    for r in db.q("select * from skill where mode=%s", (mode,)):
        k = "{}/{}".format(r["emp_id"], r["unit"])
        B.obj(mode, "Qualification", k, {"employee": r["emp_id"], "name": "{} {}".format(r["unit"].upper(), PE.LEVELS.get(r["level"], r["level"])),
                                          "level": r["level"], "valid_until": str(r["valid_until"]) if r["valid_until"] else None})
        B.link(mode, "Qualification", k, "employee", r["emp_id"])
        if r["unit"] in UNITS:
            B.link(mode, "Qualification", k, "machine", r["unit"])
    d0, _ = PE.now_shift(None, db, mode)
    for d in (d0, d0 + dt.timedelta(days=1)):
        for sh in ("day", "night"):
            for u, r in PE.roster_for(db, mode, d, sh).items():
                if not r["emp_id"]:
                    continue
                k = "{}/{}/{}".format(d.isoformat(), PE.SHIFT_NAME[sh], r["emp_id"])
                ab = PE.absences(db, mode, d, sh).get(r["emp_id"])
                B.obj(mode, "Roster", k, {"shift": PE.SHIFT_NAME[sh], "attended": not (ab and ab["status"] in ("leave", "absent")),
                                          "unit": u, "source": r["source"]})
                B.link(mode, "Roster", k, "employee", r["emp_id"])
                B.link(mode, "Roster", k, "machine", u)
    for t in PE.trainings(db, mode):
        B.obj(mode, "TrainingRecord", t["key"], {"date": t["started_at"][:10], "passed": t["status"] == "passed",
                                                 "topic": "{} 带教 {:g} 小时".format(t["unit"].upper(), float(t["hours"]))})
        B.link(mode, "TrainingRecord", t["key"], "employee", t["emp_id"])


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
            sb = TW.seed_batch(s) if (ab.get("shaft") or {}).get("how") == "情景数据" else None
            B.obj(mode, "PartSerial", sh, {"item": "SH-301", "work_order": sb[1] if sb else (ab.get("shaft") or {}).get("work_order")})
            B.link(mode, "PartSerial", sh, "installed_in", s)
            if sb:                 # 情景设备：出厂前的磨削记录（同批的轴同一片砂轮，第 18 轮 E1）
                op = "{}/5".format(sb[1])
                B.obj(mode, "OperationTask", op, {"work_order": sb[1], "op_index": 5, "operation": "磨外圆 Cylindrical grinding"})
                B.link(mode, "PartSerial", sh, "processed", op, {"machine": "grd-01", "tool": sb[0], "operation": "磨外圆 Cylindrical grinding",
                                                                  "tool_life_pct": sb[2], "seed": True})
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
