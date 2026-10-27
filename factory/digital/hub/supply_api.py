# -*- coding: utf-8 -*-
"""第 18 轮 E5 接口：采购单与批次、到货、来料检验（抽样数据、判定）、批次追溯、供应商评分卡、老师开关与注入。"""
from fastapi import Body, Depends, HTTPException

from hub import supply as SP

INSPECT = ("quality", "manager")          # 来料检验
RECEIVE = ("planner", "quality", "manager")   # 到货登记


def mount(app, H, user_of, who):
    def can(u, roles):
        return bool(u.get("teacher")) or u.get("role") in roles

    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/supply/lots")
    def lots(status: str = "", u=Depends(user_of)):
        st = [x for x in status.split(",") if x] or None
        return {"lots": SP.lots(H.db, u["mode"], st), "kpis": SP.kpis(H.db, u["mode"]), "can_inspect": can(u, INSPECT), "can_receive": can(u, RECEIVE),
                "status": SP.STATUS, "teacher": bool(u.get("teacher")) and u["mode"] == "teach"}

    @app.get("/api/supply/requests")
    def requests(u=Depends(user_of)):
        """还没转采购单的请购单，每个物料可选的供应商（默认、在用的备选）"""
        db, mode = H.db, u["mode"]
        done = set(SP._state(db, mode).get("mr_done") or [])
        ordered = {r["mr"] for r in db.q("select distinct mr from lot where mode=%s and mr is not null", (mode,))}
        out = []
        for m in db.erp_docs("Material Request", mode):
            d = m["data"]
            if d.get("docstatus") != 1 or d.get("status") not in ("Pending", "Partially Ordered", None) or d["name"] in done or d["name"] in ordered:
                continue
            for it in d.get("items") or []:
                ps = [p for p in SP.profiles(db, mode, SP.cat_of(it["item_code"])) if p["active"]]
                out.append({"mr": d["name"], "item_code": it["item_code"], "qty": float(it["qty"]), "schedule_date": it.get("schedule_date"),
                            "row": it.get("name"), "suppliers": [{"name": p["supplier"], "role": p["role"], "price_index": float(p["price_index"]),
                                                                  "lead_days": p["lead_days"]} for p in ps]})
        return {"requests": out[:100]}

    @app.get("/api/supply/lots/{lid}/sample")
    def sample(lid: int, u=Depends(user_of)):
        return wrap(SP.sample, H.db, u["mode"], lid)

    @app.post("/api/supply/lots/{lid}/arrive")
    def arrive(lid: int, body: dict = Body(default={}), u=Depends(user_of)):
        if not can(u, RECEIVE):
            raise HTTPException(403, "到货登记由计划员、质量或厂长操作")
        return wrap(SP.arrive, H.db, u["mode"], lid, who(u), body.get("qty"))

    @app.post("/api/supply/lots/{lid}/inspect")
    def inspect(lid: int, body: dict = Body(...), u=Depends(user_of)):
        if not can(u, INSPECT):
            raise HTTPException(403, "来料检验由质量或厂长操作")
        if body.get("accept") is None:
            raise HTTPException(400, "选合格或不合格")
        return wrap(SP.inspect, H, u["mode"], lid, bool(body["accept"]), who(u), (body.get("note") or "")[:300])

    @app.post("/api/supply/lots/{lid}/suspect")
    def suspect(lid: int, body: dict = Body(...), u=Depends(user_of)):
        if not can(u, INSPECT):
            raise HTTPException(403, "判定可疑批次由质量或厂长操作")
        SP.mark_suspect(H.db, u["mode"], lid, who(u), (body.get("why") or "事后发现问题")[:200])
        return {"ok": True}

    @app.get("/api/supply/trace")
    def trace(lot: str = "", serial: str = "", u=Depends(user_of)):
        if not lot and not serial:
            raise HTTPException(400, "给批号或序列号")
        return SP.trace(H.db, u["mode"], lot or None, serial or None)

    @app.get("/api/supply/suppliers")
    def suppliers(u=Depends(user_of)):
        return {"suppliers": SP.scorecard(H.db, u["mode"]), "single_source": SP.single_source(H.db, u["mode"]), "cat_names": SP.CAT_NAME}

    @app.get("/api/supply/kpis")
    def kpis(u=Depends(user_of)):
        return SP.kpis(H.db, u["mode"])

    @app.post("/api/supply/sim")
    def sim(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能开关、注入")
        if body.get("enabled") is not None:
            SP.set_enabled(H.db, "teach", bool(body["enabled"]))
        if body.get("supplier"):
            return wrap(SP.inject, H, "teach", body["supplier"], who(u), body.get("late_days"), body.get("bad"), body.get("item"), body.get("qty"))
        return {"enabled": SP.enabled(H.db, "teach")}
