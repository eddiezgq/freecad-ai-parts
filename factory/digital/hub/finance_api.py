# -*- coding: utf-8 -*-
"""第 18 轮 E7 接口：经营目标（指标树）、订单毛利、应收应付与信用、现金流预测、预算；老师开关与注入。"""
from fastapi import Body, Depends, HTTPException

from hub import finance as FN


def mount(app, H, user_of, who):
    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    def boss(u):
        return bool(u.get("teacher")) or u.get("role") == "manager"

    @app.get("/api/finance/objectives")
    def objectives(u=Depends(user_of)):
        return {"objectives": FN.objectives(H.db, u["mode"]), "can_edit": boss(u), "kpis": FN.kpis(H.db, u["mode"])}

    @app.post("/api/finance/objectives")
    def objectives_set(body: dict = Body(...), u=Depends(user_of)):
        if not boss(u):
            raise HTTPException(403, "经营目标由厂长改")
        return {"objectives": wrap(FN.set_objective, H.db, u["mode"], body.get("code"), body.get("target"), who(u))}

    @app.get("/api/finance/margins")
    def margins(u=Depends(user_of)):
        ms = FN.margins(H.db, u["mode"])
        return {"margins": ms, "gross_margin": FN.gross_margin(H.db, u["mode"]),
                "target": next((o["target"] for o in FN.objectives(H.db, u["mode"]) if o["metric"] == "gross_margin"), 0.25)}

    @app.get("/api/finance/margins/{so}")
    def margin(so: str, u=Depends(user_of)):
        return wrap(FN.margin, H.db, u["mode"], so, False)

    @app.get("/api/finance/ar")
    def ar(u=Depends(user_of)):
        return dict(FN.ar(H.db, u["mode"]), credit=FN.credit(H.db, u["mode"]), dso=FN.dso(H.db, u["mode"]), day_s=FN.day_s(u["mode"]),
                    teacher=bool(u.get("teacher")) and u["mode"] == "teach", sim=FN.sim_on(H.db, u["mode"]))

    @app.post("/api/finance/invoices/{iid}/receive")
    def receive(iid: int, u=Depends(user_of)):
        """会计登记客户付款（ERPNext 收款单）；付给供应商走“付款”动作，要厂长批"""
        if not (boss(u) or u.get("role") == "sales"):
            raise HTTPException(403, "收款由销售或厂长登记")
        x = H.db.one("select kind from invoice where id=%s and mode=%s", (iid, u["mode"]))
        if x is None:
            raise HTTPException(404, "没有这张发票")
        if x["kind"] != "ar":
            raise HTTPException(400, "付给供应商走“付款”动作（厂长批）")
        return wrap(FN.pay, H, u["mode"], iid, who(u))

    @app.get("/api/finance/ap")
    def ap(u=Depends(user_of)):
        return FN.ap(H.db, u["mode"])

    @app.get("/api/finance/cashflow")
    def cashflow(u=Depends(user_of)):
        return FN.cashflow(H.db, u["mode"])

    @app.get("/api/finance/budget")
    def budget(u=Depends(user_of)):
        return dict(FN.budget_view(H.db, u["mode"]), can_edit=boss(u), centers=FN.CENTERS)

    @app.post("/api/finance/budget")
    def budget_set(body: dict = Body(...), u=Depends(user_of)):
        """厂长直接改预算（也可以走“调整预算”动作）"""
        if not boss(u):
            raise HTTPException(403, "预算由厂长改")
        wrap(FN.exec_budget, H, u["mode"], body, u)
        return budget(u)

    @app.get("/api/finance/kpis")
    def kpis(u=Depends(user_of)):
        return FN.kpis(H.db, u["mode"])

    @app.post("/api/finance/sim")
    def sim(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能开关、注入")
        if body.get("sim") is not None:
            FN.set_sim(H.db, "teach", bool(body["sim"]))
        if body.get("inject"):
            x = body["inject"]
            return wrap(FN.inject, H, "teach", x.get("customer"), who(u), x.get("days") or 15, x.get("qty") or 8)
        return {"sim": FN.sim_on(H.db, "teach")}
