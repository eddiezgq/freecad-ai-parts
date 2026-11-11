# -*- coding: utf-8 -*-
"""按单设计（ETO，第 139 轮）的网页接口：作业、估算、AI 起草、发报价（提议 → 人确认 → 桥接写入 ERPNext）。"""
import logging

from fastapi import Body, Depends, File, HTTPException, UploadFile

from hub import ai as _ai
from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub import eto_mrp as EM
from hub import eto_plan as EP
from hub import eto_exec as EX
from hub import eto_quality as EQ
from hub import eto_billing as EB
from hub import eto_change as EC

log = logging.getLogger("eto")
ROLES = ("sales", "planner", "engineer", "manager", "approver")


def mount(app, H, user_of, who, ai_quota=None):
    for fn in (E.on_proposal_done, ED.on_proposal_done, EX.on_proposal_done, EQ.on_proposal_done, EB.on_proposal_done,
               EC.on_proposal_done):
        if fn not in _ai.ON_PROPOSAL_DONE:
            _ai.ON_PROPOSAL_DONE.append(fn)

    def can(u):
        if u.get("role") not in ROLES and not u.get("teacher"):
            raise HTTPException(403, "估算和报价由销售、计划、设计或厂长做")

    def found(d, jn):
        if d is None:
            raise HTTPException(404, "没有作业 {}".format(jn))
        return d

    @app.get("/api/eto/config")
    def eto_config(u=Depends(user_of)):
        """配置，以及估算表要选的工序、原材料和外购件"""
        from factory import data as F
        return dict(E.config(), operations=list(F.OPERATIONS),
                    items=[{"code": c, "name": v[0], "kind": v[1], "uom": v[2]} for c, v in F.ITEMS.items() if v[1] in ("raw", "buy")],
                    all_items=[{"code": c, "name": v[0], "kind": v[1], "uom": v[2], "bom": c in F.BOMS} for c, v in F.ITEMS.items()
                               if not str(v[6] or "").startswith("按单设计")],
                    suppliers={k: v["name"] for k, v in F.SUPPLIERS.items()})

    @app.get("/api/eto/jobs")
    def eto_jobs(u=Depends(user_of)):
        return E.jobs(H.db, u["mode"])

    @app.post("/api/eto/jobs")
    def eto_new(body: dict = Body(...), u=Depends(user_of)):
        can(u)
        try:
            return E.new_job(H.db, u["mode"], who(u), body.get("customer"), body.get("title"), body.get("requirement"),
                             body.get("qty"), body.get("qty_breaks"), body.get("due_date"))
        except E.EtoError as e:
            raise HTTPException(400, str(e))

    def with_feas(d, u):
        """第 139d 段：报价时能否按期（按估算粗算）；第 150 轮 150c：加上其他作业和在制工单占的工位"""
        if d:
            lines = (d.get("estimate") or {}).get("lines") or []
            f = EP.feasibility(d["job"], lines)
            try:
                f["capacity"] = EP.quote_capacity(H.db, u["mode"], d["job"], lines)
            except Exception:  # noqa: BLE001  （负荷算不出来不挡报价页，只是不显示）
                log.exception("报价时工位负荷")
                f["capacity"] = None
            if f["capacity"]:
                f["ok"] = False
            d["feasibility"] = f
        return d

    @app.get("/api/eto/jobs/{job_no}")
    def eto_detail(job_no: str, u=Depends(user_of)):
        try:
            return with_feas(found(E.detail(H.db, u["mode"], job_no), job_no), u)
        except E.EtoError as e:
            raise HTTPException(400, str(e))

    @app.put("/api/eto/jobs/{job_no}/estimate")
    def eto_save(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        can(u)
        try:
            E.save_estimate(H.db, u["mode"], job_no, body.get("lines"), body.get("note"), who(u), body.get("source") or "human")
        except KeyError:
            raise HTTPException(404, "没有作业 {}".format(job_no))
        except E.EtoError as e:
            raise HTTPException(409, str(e))
        return with_feas(E.detail(H.db, u["mode"], job_no), u)

    @app.post("/api/eto/jobs/{job_no}/draft")
    def eto_draft(job_no: str, u=Depends(user_of)):
        """起草估算行（AI；没有模型照现有产品）。只返回草稿，估算员看过再存。"""
        can(u)
        j = found(E.job(H.db, u["mode"], job_no), job_no)
        j["drawing_text"] = EQ.drawing_text(H.db, u["mode"], job_no)
        llm = getattr(getattr(H, "ai", None), "llm", None)
        if llm is not None and llm.available() and ai_quota:
            ai_quota(u)
        try:
            return E.draft(llm, j)
        except Exception as ex:  # noqa: BLE001 —— 模型出错：退回规则起草
            log.warning("AI 起草估算出错，改用规则：%s", ex)
            d = E.draft(None, j)
            d["note"] = "AI 起草出错（{}），".format(str(ex)[:120]) + d["note"]
            return d

    @app.post("/api/eto/jobs/{job_no}/quote")
    def eto_quote(job_no: str, u=Depends(user_of)):
        """发报价：生成提议（预览），人确认后桥接在 ERPNext 建 Project、物料、报价单"""
        can(u)
        try:
            pv = E.quote_preview(H.db, u["mode"], job_no)
        except KeyError:
            raise HTTPException(404, "没有作业 {}".format(job_no))
        except E.EtoError as e:
            raise HTTPException(409, str(e))
        title = "报价 {}：{} {} 件，{:.2f}".format(job_no, pv["job"]["customer"], pv["quotation"]["qty"], pv["quotation"]["amount"])
        pid = H.ai.propose("eto_quote", pv, u["mode"], u["name"], title, source="workbench/" + who(u), role=u["role"])
        return {"proposal_id": pid, "preview": pv, "title": title}

    # ------------------------------------------------------------ 139b：接单、设计、设计发布
    def propose(u, action, pv, title):
        pid = H.ai.propose(action, pv, u["mode"], u["name"], title, source="workbench/" + who(u), role=u["role"])
        return {"proposal_id": pid, "preview": pv, "title": title}

    def guard(fn):
        try:
            return fn()
        except KeyError as e:
            raise HTTPException(404, "没有作业 {}".format(e.args[0] if e.args else ""))
        except E.EtoError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/eto/jobs/{job_no}/order")
    def eto_order(job_no: str, body: dict = Body(default={}), u=Depends(user_of)):
        """客户接受报价：销售订单提议（单价按报出去的那一版，付款计划按里程碑）"""
        can(u)
        pv = guard(lambda: ED.order_preview(H.db, u["mode"], job_no, body.get("delivery_date")))
        so = pv["sales_order"]
        return propose(u, "eto_order", pv, "接单 {}：{} {} 件，{:.2f}".format(job_no, so["customer"], so["qty"], so["amount"]))

    @app.get("/api/eto/jobs/{job_no}/design")
    def eto_design_get(job_no: str, u=Depends(user_of)):
        return found(ED.detail(H.db, u["mode"], job_no), job_no)

    @app.put("/api/eto/jobs/{job_no}/design")
    def eto_design_save(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        can(u)
        guard(lambda: ED.save(H.db, u["mode"], job_no, body.get("spec"), who(u)))
        return ED.detail(H.db, u["mode"], job_no)

    @app.post("/api/eto/jobs/{job_no}/design/draft")
    def eto_design_draft(job_no: str, u=Depends(user_of)):
        """照报出去的那一版估算起草设计（只返回草稿，设计员看过再存）"""
        can(u)
        j = found(E.job(H.db, u["mode"], job_no), job_no)
        rev = j.get("quoted_rev")
        est = H.db.one("select lines from eto_estimate where mode=%s and job_no=%s " + ("and rev=%s" if rev else "order by rev desc limit 1"),
                       (u["mode"], job_no, rev) if rev else (u["mode"], job_no))
        return ED.from_estimate(j, (est or {}).get("lines") or [])

    @app.post("/api/eto/jobs/{job_no}/design/copy")
    def eto_design_copy(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """把父件里的一个现有自制件复制为本单新件（只改草稿，不存）"""
        can(u)
        return guard(lambda: ED.copy_as_new(body["spec"], job_no, body.get("parent") or job_no, body.get("code"),
                                            str(body.get("suffix") or "").strip() or "X"))

    @app.post("/api/eto/jobs/{job_no}/design/release")
    def eto_design_release(job_no: str, u=Depends(user_of)):
        """设计发布：校验通过、已接单 → 提议；人确认后桥接在 ERPNext 建新物料和物料清单"""
        can(u)
        pv = guard(lambda: ED.release_preview(H.db, u["mode"], job_no))
        return propose(u, "eto_release", pv, "设计发布 {} 第 {} 版（{} 个新物料、{} 组物料清单）".format(
            job_no, pv["job"]["rev"], len(pv["items"]), len(pv["boms"])))

    # ------------------------------------------------------------ 第 150 轮 150a：设计变更处理
    @app.get("/api/eto/jobs/{job_no}/change")
    def eto_change_plan(job_no: str, u=Depends(user_of)):
        """这一次设计变更：受影响的工单、请购单、采购单和建议"""
        return guard(lambda: EC.plan(H.db, u["mode"], job_no))

    @app.post("/api/eto/jobs/{job_no}/change")
    def eto_change_propose(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """逐条选好 → 提议；人确认后桥接在 ERPNext 里取消 / 停止 / 改量 / 关闭，“照用”只记下"""
        if u.get("role") not in ("planner", "manager", "engineer") and not u.get("teacher"):
            raise HTTPException(403, "设计变更由计划员、工艺员或厂长处理")
        pv = guard(lambda: EC.preview(H.db, u["mode"], job_no, body.get("choices") or {}, who(u)))
        n = {}
        for a in pv["actions"]:
            n[a["action_zh"]] = n.get(a["action_zh"], 0) + 1
        return propose(u, "eto_change", pv, "设计变更处理 {} 第 {} 版：{}".format(
            job_no, pv["job"]["rev"], "、".join("{} {}".format(k, v) for k, v in n.items())))

    # ------------------------------------------------------------ 139c：作业算料、长周期件提前采购
    @app.get("/api/eto/jobs/{job_no}/materials")
    def eto_materials(job_no: str, u=Depends(user_of)):
        """算料预览（不下单）"""
        return guard(lambda: EM.plan(H.db, u["mode"], job_no))

    @app.post("/api/eto/jobs/{job_no}/materials")
    def eto_materials_propose(job_no: str, u=Depends(user_of)):
        """算料 → 提议：工单、请购单都挂作业号；人确认后桥接写入 ERPNext"""
        can(u)
        if ED.pending(H.db, u["mode"], "eto_materials", job_no):
            raise HTTPException(409, "已经有一份算料提议在等确认")
        pv = guard(lambda: EM.plan(H.db, u["mode"], job_no))
        if not pv["work_orders"] and not pv["material_requests"]:
            raise HTTPException(409, "都够用了：没有要下的工单和请购")
        return propose(u, "eto_materials", pv, "作业算料 {}：工单 {} 张、请购 {} 项".format(
            job_no, len(pv["work_orders"]), len(pv["material_requests"])))

    @app.get("/api/eto/jobs/{job_no}/early-buy")
    def eto_early_candidates(job_no: str, u=Depends(user_of)):
        return EM.early_candidates(H.db, u["mode"], job_no)

    @app.post("/api/eto/jobs/{job_no}/early-buy")
    def eto_early_buy(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """长周期件提前采购（设计发布前）：单独的提议，人确认"""
        can(u)
        pv = guard(lambda: EM.early_buy_preview(H.db, u["mode"], job_no, list(body.get("items") or [])))
        return propose(u, "eto_early_buy", pv, "提前采购 {}：{}".format(job_no, "、".join(r["item_code"] for r in pv["material_requests"])))

    # ------------------------------------------------------------ 139d：倒排与负荷
    @app.get("/api/eto/jobs/{job_no}/schedule")
    def eto_schedule(job_no: str, u=Depends(user_of)):
        def run():
            t = EP.schedule(H.db, u["mode"], job_no)
            t["load"] = EP.load(H.db, u["mode"], job_no)
            return t
        return guard(run)

    # ------------------------------------------------------------ 139e：车间执行与作业成本
    @app.get("/api/eto/jobs/{job_no}/shop")
    def eto_shop(job_no: str, u=Depends(user_of)):
        return guard(lambda: {"work_orders": EX.work_orders(H.db, u["mode"], job_no), "cost": EX.cost(H.db, u["mode"], job_no),
                              "hours": EX.hours(H.db, u["mode"], job_no)})

    @app.get("/api/eto/jobs/{job_no}/traveler/{wo}")
    def eto_traveler(job_no: str, wo: str, u=Depends(user_of)):
        return guard(lambda: EX.traveler(H.db, u["mode"], job_no, wo))

    @app.post("/api/eto/jobs/{job_no}/release")
    def eto_release_wo(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """下达车间：查过设计版本再走原来的“下达工单”提议（人确认后车间按工艺路线逐道做）"""
        if u.get("role") not in ("planner", "manager", "lead") and not u.get("teacher"):
            raise HTTPException(403, "下达车间由计划员或厂长做")
        w = guard(lambda: EX.release_check(H.db, u["mode"], job_no, str(body.get("work_order") or "")))
        return propose(u, "release_work_order", {"work_order": w["name"], "job": {"job_no": job_no}},
                       "下达工单 {}（作业 {}，{} × {:g}）".format(w["name"], job_no, w["item"], w["qty"]))

    @app.post("/api/eto/jobs/{job_no}/hours")
    def eto_hours(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """登记设计工时 → ERPNext Timesheet（数据录入：提议后自动确认，留记录）"""
        can(u)
        pv = guard(lambda: EX.hours_preview(H.db, u["mode"], job_no, body.get("hours"), body.get("note"), who(u), body.get("day")))
        r = propose(u, "eto_hours", pv, "设计工时 {}：{:g} 小时".format(job_no, pv["hours"]))
        H.ai.decide(r["proposal_id"], u["name"], True, role=u["role"])
        return r

    # ------------------------------------------------------------ 139f：客户图纸、检验计划、首件与终检、发货、合格证
    QROLES = ("quality", "manager")

    def qcan(u):
        if u.get("role") not in QROLES and not u.get("teacher"):
            raise HTTPException(403, "检验计划和检验记录由质量人员做")

    @app.post("/api/eto/jobs/{job_no}/files")
    async def eto_upload(job_no: str, file: UploadFile = File(...), u=Depends(user_of)):
        """客户图纸：存进平台文件库，PDF 抽出文字给 AI 读"""
        import hashlib
        can(u)
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(413, "图纸超过 20 MB")
        sha = hashlib.sha256(data).hexdigest()
        H.db.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s) on conflict (sha256) do nothing",
               (sha, file.filename, file.content_type, len(data), data))
        text = EQ.pdf_text(data) if (file.content_type == "application/pdf" or str(file.filename).lower().endswith(".pdf")) else ""
        guard(lambda: EQ.add_file(H.db, u["mode"], job_no, sha, file.filename, file.content_type, len(data), text, who(u)))
        return {"sha256": sha, "name": file.filename, "text_chars": len(text), "url": "/api/files/" + sha}

    @app.get("/api/eto/jobs/{job_no}/quality")
    def eto_quality(job_no: str, u=Depends(user_of)):
        def run():
            j = E.job(H.db, u["mode"], job_no)
            if not j:
                raise KeyError(job_no)
            items = EQ.job_items(H.db, u["mode"], job_no)
            plan = EQ.plan_latest(H.db, u["mode"], job_no)
            wos = EX.work_orders(H.db, u["mode"], job_no) if j.get("sales_order") else []
            recs = EQ.records(H.db, u["mode"], job_no)
            appr = EQ.plan_approved(H.db, u["mode"], job_no)
            return {"files": EQ.files(H.db, u["mode"], job_no), "items": items, "plan": plan, "approved": appr,
                    "errors": EQ.check_plan(plan["chars"], items, job_no) if plan else [], "work_orders": wos, "records": recs,
                    "ship_block": EQ.ship_check(dict(j, shipped=bool(j.get("delivery_note"))), wos, appr, recs),
                    "delivery_note": j.get("delivery_note")}
        return guard(run)

    @app.post("/api/eto/jobs/{job_no}/quality/plan/draft")
    def eto_qplan_draft(job_no: str, u=Depends(user_of)):
        qcan(u)
        j = found(E.job(H.db, u["mode"], job_no), job_no)
        d = ED.released(H.db, u["mode"], job_no) or ED.latest(H.db, u["mode"], job_no)
        llm = getattr(getattr(H, "ai", None), "llm", None)
        if llm is not None and llm.available() and ai_quota:
            ai_quota(u)
        args = (j, EQ.job_items(H.db, u["mode"], job_no), (d or {}).get("spec"), EQ.drawing_text(H.db, u["mode"], job_no))
        try:
            return EQ.draft_plan(llm, *args)
        except Exception as ex:  # noqa: BLE001
            log.warning("AI 起草检验计划出错，改用规则：%s", ex)
            return EQ.draft_plan(None, *args)

    @app.put("/api/eto/jobs/{job_no}/quality/plan")
    def eto_qplan_save(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        qcan(u)
        guard(lambda: EQ.save_plan(H.db, u["mode"], job_no, body.get("chars"), who(u)))
        return eto_quality(job_no, u)

    @app.post("/api/eto/jobs/{job_no}/quality/plan/approve")
    def eto_qplan_approve(job_no: str, u=Depends(user_of)):
        qcan(u)
        guard(lambda: EQ.approve_plan(H.db, u["mode"], job_no, who(u)))
        return eto_quality(job_no, u)

    @app.post("/api/eto/jobs/{job_no}/quality/inspect")
    def eto_inspect(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """记一件的检验：判定、不合格开不合格品单；写进 ERPNext 质量检验单（数据录入：提议后自动确认）"""
        qcan(u)
        wos = guard(lambda: EX.work_orders(H.db, u["mode"], job_no))
        rec = guard(lambda: EQ.record(H.db, u["mode"], job_no, body.get("kind"), body.get("work_order"), body.get("piece"),
                                      body.get("readings") or {}, who(u), wos))
        w = next(x for x in wos if x["name"] == body.get("work_order"))
        ops = [op for op, _ in F.ROUTINGS[F.BOMS[w["item"]][0]]] if w["item"] in F.BOMS else []
        pv = EQ.inspection_preview(job_no, dict(rec, kind=body.get("kind"), piece=int(body.get("piece"))), w, who(u), ops)
        r = propose(u, "eto_inspection", pv, "{} {} 第 {} 件：{}".format("首件检验" if pv["kind"] == "fai" else "终检", w["name"], pv["piece"],
                                                                  {"pass": "合格", "fail": "不合格", "unknown": "未知"}[rec["result"]]))
        H.ai.decide(r["proposal_id"], u["name"], True, role=u["role"])
        return dict(rec, proposal_id=r["proposal_id"])

    @app.post("/api/eto/jobs/{job_no}/quality/inspect/{insp_id}/void")
    def eto_inspect_void(job_no: str, insp_id: int, body: dict = Body(...), u=Depends(user_of)):
        qcan(u)
        guard(lambda: EQ.void(H.db, u["mode"], insp_id, who(u), body.get("reason")))
        return {"ok": True}

    @app.post("/api/eto/jobs/{job_no}/ship")
    def eto_ship(job_no: str, u=Depends(user_of)):
        """发货：关口（完工、首件、终检、不合格品）都过了才生成提议；人确认后 ERPNext 建发货单"""
        can(u)
        pv = guard(lambda: EQ.ship_preview(H.db, u["mode"], job_no, EX.work_orders(H.db, u["mode"], job_no)))
        return propose(u, "eto_ship", pv, "发货 {}：{} {} 件".format(job_no, pv["job"]["customer"], pv["qty"]))

    @app.get("/api/eto/jobs/{job_no}/certificate")
    def eto_certificate(job_no: str, u=Depends(user_of)):
        def run():
            j = E.job(H.db, u["mode"], job_no)
            if not j:
                raise KeyError(job_no)
            return EQ.certificate(j, EQ.plan_approved(H.db, u["mode"], job_no), EQ.records(H.db, u["mode"], job_no),
                                  ED.released(H.db, u["mode"], job_no))
        return guard(run)

    # ------------------------------------------------------------ 139g：按里程碑分期开票、客户验收、收付与毛利
    @app.get("/api/eto/jobs/{job_no}/billing")
    def eto_billing(job_no: str, u=Depends(user_of)):
        def run():
            j = E.job(H.db, u["mode"], job_no)
            if not j:
                raise KeyError(job_no)
            acc = H.db.one("select day, note, who from eto_accept where mode=%s and job_no=%s", (u["mode"], job_no))
            c = EX.cost(H.db, u["mode"], job_no) if j.get("sales_order") else None
            return {"milestones": EB.milestones(H.db, u["mode"], job_no),
                    "money": EB.money(H.db, u["mode"], job_no, c),
                    "purchases": (c or {}).get("purchases") or [], "invoice_pending": (c or {}).get("invoice_pending") or [],
                    "accepted": {"day": acc["day"].isoformat(), "note": acc["note"], "who": acc["who"]} if acc else None,
                    "sales_order": j.get("sales_order"), "delivery_note": j.get("delivery_note")}
        return guard(run)

    @app.post("/api/eto/jobs/{job_no}/invoice")
    def eto_invoice(job_no: str, body: dict = Body(...), u=Depends(user_of)):
        """里程碑到了的那一期：销售发票提议；人确认后桥接在 ERPNext 开票"""
        can(u)
        pv = guard(lambda: EB.invoice_preview(H.db, u["mode"], job_no, body.get("key")))
        r = propose(u, "eto_invoice", pv, "开票 {}：{} {}% ${:,.2f}".format(job_no, pv["description"], pv["pct"], pv["amount"]))
        EB.mark_invoicing(H.db, u["mode"], pv, r["proposal_id"])
        return r

    @app.post("/api/eto/jobs/{job_no}/accept")
    def eto_accept(job_no: str, body: dict = Body(default={}), u=Depends(user_of)):
        """客户验收：发货后登记验收日期（验收那一期才能开票）"""
        can(u)
        guard(lambda: EB.accept(H.db, u["mode"], job_no, body.get("day"), body.get("note"), who(u)))
        return eto_billing(job_no, u)
