# -*- coding: utf-8 -*-
"""第 18 轮 E1 接口：销售漏斗（线索 → 商机 → 报价 → 合同 → 订单）、投诉、服务派工与排班、回访、客户 360、教学注入。

线索、商机、报价、合同经桥接写进 ERPNext（提议 → 自动确认：这是数据录入，不是要审批的动作），桥接轮询读回历史库。"""
import datetime as dt

from fastapi import Body, Depends, HTTPException

from factory import data as F
from hub import crm
from hub import service as SV

SALES = ("sales", "manager")
SERVICE = ("service", "manager", "sales")


def mount(app, H, user_of, who):
    def can(u, roles):
        return bool(u.get("teacher")) or u.get("role") in roles

    def need(u, roles, what):
        if not can(u, roles):
            raise HTTPException(403, "{}由{}操作".format(what, "、".join({"sales": "销售", "manager": "厂长", "service": "售后"}[r] for r in roles)))

    def record(u, action, pv, title):
        pid = H.ai.propose(action, pv, u["mode"], u["name"], title, source="crm/" + who(u), role=u.get("role"))
        H.ai.decide(pid, u["name"], True, role=u.get("role"))
        return pid

    # ---------------------------------------------------------------- 销售漏斗
    @app.get("/api/crm/pipeline")
    def pipeline(u=Depends(user_of)):
        p = crm.pipeline(H.db, u["mode"])
        p["contracts"] = [c for c in crm.contracts(H.db, u["mode"])]
        p["can_edit"] = can(u, SALES)
        p["price"] = F.FG_SELLING_PRICE
        p["customers"] = sorted({c for c in F.CUSTOMERS} | {c["customer"] for c in p["contracts"] if c["customer"]})
        return p

    @app.post("/api/crm/leads")
    def lead_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, SALES, "线索")
        name = (body.get("company_name") or "").strip()
        if not name:
            raise HTTPException(400, "填公司名称")
        return {"proposal_id": record(u, "crm_lead", {"lead_name": (body.get("lead_name") or ("采购部 · " + name))[:100], "company_name": name[:100],
                                                     "note": (body.get("note") or "")[:300]}, "线索：" + name)}

    @app.post("/api/crm/opportunities")
    def opp_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, SALES, "商机")
        frm = body.get("from") or "Lead"
        if frm not in ("Lead", "Customer") or not body.get("party"):
            raise HTTPException(400, "商机要来自一条线索或一个客户")
        qty = int(body.get("qty") or 1)
        amount = float(body.get("amount") or qty * F.FG_SELLING_PRICE)
        return {"proposal_id": record(u, "crm_opportunity", {"from": frm, "party": body["party"], "amount": amount,
                                                            "expected_closing": body.get("expected_closing")}, "商机：" + body["party"])}

    @app.post("/api/crm/quotations")
    def quote_new(body: dict = Body(...), u=Depends(user_of)):
        """报价：数量 × 参数配置器的标准售价（WQR-105 $1,650 / 台）"""
        need(u, SALES, "报价")
        qty = int(body.get("qty") or 0)
        if qty <= 0:
            raise HTTPException(400, "填数量")
        rate = float(body.get("rate") or F.FG_SELLING_PRICE)
        valid = body.get("valid_till") or (dt.date.today() + dt.timedelta(days=14)).isoformat()
        to = body.get("quotation_to") or "Customer"
        if not body.get("party"):
            raise HTTPException(400, "报价给哪个客户（或线索）")
        pv = {"quotation_to": to, "party": body["party"], "opportunity": body.get("opportunity"), "valid_till": valid,
              "items": [{"item_code": body.get("item") or "WQR-105", "qty": qty, "rate": rate}]}
        return {"proposal_id": record(u, "crm_quotation", pv, "报价：{} × {}".format(body["party"], qty)), "amount": qty * rate}

    @app.post("/api/crm/contracts")
    def contract_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, SALES, "合同")
        cust = (body.get("customer") or "").strip()
        if not cust:
            raise HTTPException(400, "填客户（报价给线索的，签合同时会建成 ERPNext 客户）")
        start = body.get("start") or dt.date.today().isoformat()
        end = body.get("end") or (dt.date.fromisoformat(start) + dt.timedelta(days=365 * 2)).isoformat()
        pen, resp, wm = float(body.get("penalty_per_day") or 0), float(body.get("response_h") or 24), int(body.get("warranty_months") or 12)
        if pen < 0 or not 1 <= resp <= 720 or not 0 <= wm <= 120:
            raise HTTPException(400, "违约金不能为负；响应时限 1–720 小时；保修 0–120 个月")
        text = ("供货合同：{}。保修期 {} 个月；投诉响应时限 {:g} 小时；延期交货违约金每天 ${:,.0f}。"
                "（问渠数字工厂 · 销售漏斗录入）").format(cust, wm, resp, pen)
        pv = {"customer": cust, "quotation": body.get("quotation"), "amount": float(body.get("amount") or 0), "start": start, "end": end,
              "penalty_per_day": pen, "response_h": resp, "warranty_months": wm, "text": text, "signee": body.get("signee") or cust}
        return {"proposal_id": record(u, "crm_contract", pv, "合同：" + cust)}

    @app.post("/api/crm/contracts/{name}/order")
    def contract_order(name: str, body: dict = Body(...), u=Depends(user_of)):
        """合同转订单：沿用“接单并算料”提议（销售订单 + 工单 + 请购单），人确认后写入 ERPNext；订单号回填到合同"""
        from hub import mrp
        from hub.ai import _order_title
        need(u, SALES, "下单")
        c = next((x for x in crm.contracts(H.db, u["mode"]) if x["name"] == name), None)
        if c is None:
            raise HTTPException(404, "没有这份合同")
        qty, due = int(body.get("qty") or 0), body.get("delivery_date")
        if qty <= 0 or not due:
            raise HTTPException(400, "填数量和交期")
        pv = mrp.plan_order(H.db, c["customer"], "WQR-105", qty, due, u["mode"])
        pv["contract"] = name
        pid = H.ai.propose("create_order_and_plan", pv, u["mode"], u["name"], _order_title(pv), role=u.get("role"))
        return {"proposal_id": pid, "preview": pv}

    # ---------------------------------------------------------------- 投诉
    @app.get("/api/complaints")
    def complaints(status: str = "", u=Depends(user_of)):
        SV.init(H.db)
        w, a = ["mode=%s"], [u["mode"]]
        if status == "open":
            w.append("status<>'closed'")
        elif status:
            w.append("status=%s")
            a.append(status)
        us = SV.units(H.db, u["mode"])
        rows = H.db.q("select * from complaint where {} order by id desc limit 300".format(" and ".join(w)), a)
        out = []
        for c in rows:
            r = SV.complaint_row(H.db, c, us)
            an = H.db.one("select id from anomaly where mode=%s and rule in ('C1','C3') and fkey=%s order by id desc limit 1", (u["mode"], r["key"])) \
                if H.db.one("select to_regclass('anomaly') is not null as ok")["ok"] else None
            r["anomaly_id"] = an["id"] if an else None
            out.append(r)
        return {"complaints": out, "can_edit": can(u, SERVICE), "severities": SV.SEVERITY, "statuses": SV.STATUS,
                "units": sorted(us.values(), key=lambda x: x["serial"])}

    @app.post("/api/complaints")
    def complaint_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, SERVICE, "登记投诉")
        try:
            cid = SV.create_complaint(H, u["mode"], body, who(u))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"id": cid, "key": "CP-{:05d}".format(cid)}

    @app.post("/api/complaints/{cid}/respond")
    def complaint_respond(cid: int, body: dict = Body(...), u=Depends(user_of)):
        need(u, SERVICE, "处理投诉")
        c = H.db.one("select id from complaint where id=%s and mode=%s", (cid, u["mode"]))
        if c is None:
            raise HTTPException(404, "没有这张投诉")
        try:
            SV.respond(H.db, cid, who(u), body.get("status") or "doing", body.get("text") or "")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {"ok": True}

    # ---------------------------------------------------------------- 服务
    @app.get("/api/service/units")
    def service_units(u=Depends(user_of)):
        return {"units": sorted(SV.units(H.db, u["mode"]).values(), key=lambda x: (-x["risk"], x["serial"])), "today": SV.field_today(H.db, u["mode"]).isoformat()}

    @app.get("/api/service/jobs")
    def service_jobs(status: str = "", u=Depends(user_of)):
        SV.init(H.db)
        w, a = ["mode=%s"], [u["mode"]]
        if status:
            w.append("status=%s")
            a.append(status)
        engs = {e["id"]: e["name"] for e in SV.engineers(H.db, u["mode"])}
        rows = H.db.q("select * from service_job where {} order by coalesce(day, '2100-01-01'), id limit 300".format(" and ".join(w)), a)
        out = [{"id": j["id"], "key": "SJ-{:05d}".format(j["id"]), "serial": j["serial"], "customer": j["customer"], "kind": j["kind"],
                "kind_label": SV.kind_label(j["kind"]), "engineer": j["engineer"], "engineer_name": engs.get(j["engineer"]),
                "day": j["day"].isoformat() if j["day"] else None, "status": j["status"], "warranty": j["warranty"], "cost": j["cost"],
                "issue": SV.issue_of(H.db, j), "complaint_id": j["complaint_id"], "anomaly_id": j["anomaly_id"], "action_id": j["action_id"],
                "done_day": j["done_day"].isoformat() if j["done_day"] else None, "result": j["result"]} for j in rows]
        return {"jobs": out, "today": SV.field_today(H.db, u["mode"]).isoformat(), "can_edit": can(u, SERVICE)}

    @app.post("/api/service/jobs/{jid}/done")
    def service_done(jid: int, body: dict = Body(default={}), u=Depends(user_of)):
        need(u, SERVICE, "服务完工")
        try:
            return SV.complete_job(H, u["mode"], jid, who(u), (body.get("note") or "")[:300])
        except KeyError:
            raise HTTPException(404, "没有这张服务工单")
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/service/schedule")
    def service_schedule(days: int = 14, u=Depends(user_of)):
        return SV.schedule(H.db, u["mode"], None, max(7, min(int(days), 28)))

    @app.post("/api/service/estimate")
    def service_estimate(body: dict = Body(...), u=Depends(user_of)):
        jobs = [j for j in body.get("jobs") or [] if j.get("serial")]
        if not jobs:
            raise HTTPException(400, "选要上门的设备")
        return SV.estimate(H.db, u["mode"], [{"serial": j["serial"], "kind": j.get("kind") or "inspect"} for j in jobs])

    @app.get("/api/service/kpis")
    def service_kpis(u=Depends(user_of)):
        k = SV.kpis(H.db, u["mode"])
        p = crm.pipeline(H.db, u["mode"])
        k.update(funnel_amount=p["funnel_amount"], won_month=p["won_month"])
        return k

    @app.get("/api/followups")
    def followups(u=Depends(user_of)):
        SV.init(H.db)
        rows = H.db.q("select f.*, j.kind, j.engineer from follow_up f left join service_job j on j.id=f.job_id where f.mode=%s order by f.id desc limit 200",
                      (u["mode"],))
        return {"followups": [{"id": f["id"], "key": "FU-{:05d}".format(f["id"]), "serial": f["serial"], "customer": f["customer"],
                               "kind": SV.kind_label(f["kind"]) if f["kind"] else None, "due_day": f["due_day"].isoformat() if f["due_day"] else None,
                               "score": float(f["score"]) if f["score"] is not None else None, "comment": f["comment"], "by": f["by_name"],
                               "done_at": f["done_at"].isoformat() if f["done_at"] else None} for f in rows],
                "satisfaction": SV.satisfaction(H.db, u["mode"]), "can_edit": can(u, SERVICE)}

    @app.post("/api/followups/{fid}")
    def followup_score(fid: int, body: dict = Body(...), u=Depends(user_of)):
        need(u, SERVICE, "回访")
        f = H.db.one("select id from follow_up where id=%s and mode=%s", (fid, u["mode"]))
        if f is None:
            raise HTTPException(404, "没有这条回访")
        try:
            SV.score_follow_up(H.db, fid, body.get("score"), body.get("comment"), who(u))
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e) or "满意度 1–5 分")
        return {"ok": True}

    @app.get("/api/service/notices")
    def notices(u=Depends(user_of)):
        SV.init(H.db)
        rows = H.db.q("select * from customer_notice where mode=%s order by id desc limit 100", (u["mode"],))
        return {"notices": [dict(r, created_at=r["created_at"].isoformat(), sent_at=r["sent_at"].isoformat() if r["sent_at"] else None) for r in rows]}

    # ---------------------------------------------------------------- 教学：批次投诉情景
    @app.post("/api/teach/batch-complaint")
    def batch_complaint(body: dict = Body(default={}), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有老师在教学模式下能注入")
        try:
            return SV.inject_batch(H, u["mode"], int(body.get("n") or 3))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ---------------------------------------------------------------- 客户 360
    @app.get("/api/ont/customer360/{customer:path}")
    def customer360(customer: str, u=Depends(user_of)):
        from hub.ont.api import level
        r = c360(H.db, u["mode"], customer)
        if r.get("contract") and level(u) < 2 and u.get("role") not in ("sales", "service"):   # 合同条款是 2 级敏感；销售、售后要用
            r["contract"] = {"name": r["contract"]["name"], "hidden": True}
        return r


def c360(db, mode, customer):
    """客户 360：订单、合同、现场设备、投诉、服务、满意度（AI 代理的工具也用它）"""
    SV.init(db)
    orders = [{"name": m["data"]["name"], "status": m["data"].get("status"), "delivery_date": str(m["data"].get("delivery_date") or "")[:10],
               "qty": sum(float(i.get("qty") or 0) for i in m["data"].get("items") or [])}
              for m in db.erp_docs("Sales Order", mode) if m["data"].get("customer") == customer]
    t = crm.terms_for(db, mode, customer)
    us = [x for x in SV.units(db, mode).values() if x["customer"] == customer]
    comps = db.q("select id, subject, status, severity, created_at, serial from complaint where mode=%s and customer=%s order by id desc limit 20", (mode, customer))
    jobs = db.q("select id, serial, kind, status, day, engineer from service_job where mode=%s and customer=%s order by id desc limit 20", (mode, customer))
    fu = db.q("select score from follow_up where mode=%s and customer=%s and score is not null order by done_at desc limit 5", (mode, customer))
    return {"customer": customer, "contract": t, "orders": orders[:20],
            "units": [{k: x[k] for k in ("serial", "site", "health", "alerts", "warranty_until", "in_warranty", "risk")} for x in us],
            "complaints": [{"key": "CP-{:05d}".format(c["id"]), "subject": c["subject"], "status": SV.STATUS[c["status"]], "severity": SV.SEVERITY[c["severity"]],
                            "date": c["created_at"].date().isoformat(), "serial": c["serial"]} for c in comps],
            "jobs": [{"key": "SJ-{:05d}".format(j["id"]), "serial": j["serial"], "kind": SV.kind_label(j["kind"]), "status": j["status"],
                      "day": j["day"].isoformat() if j["day"] else None} for j in jobs],
            "satisfaction": round(sum(float(x["score"]) for x in fu) / len(fu), 2) if fu else None, "surveys": len(fu)}
