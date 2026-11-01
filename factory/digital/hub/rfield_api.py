# -*- coding: utf-8 -*-
"""第 64 轮接口：机器人厂的客户与服务——现场的机器人（台账、详情、投诉、服务工单、回访、老师推进现场时钟）。"""
from fastapi import Body, Depends, HTTPException

from hub import rfield as RF


def mount(app, H, user_of, who):
    def wrap(fn, *a, **k):
        if not RF.enabled():
            raise HTTPException(404, "本厂没有现场的机器人（只在机器人厂）")
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/rfield/fleet")
    def fleet(u=Depends(user_of)):
        return wrap(lambda: {"robots": RF.fleet(H.db, u["mode"]), "kpis": RF.kpis(H.db, u["mode"]), "customers": RF.customers(),
                             "kinds": RF.KIND, "engineers": [{"id": e, "name": n} for e, n in RF.ENGINEERS],
                             "teacher": bool(u.get("teacher")) and u["mode"] == "teach"})

    @app.get("/api/rfield/robots/{serial}")
    def robot(serial: str, u=Depends(user_of)):
        return wrap(RF.detail, H.db, u["mode"], serial)

    @app.get("/api/rfield/kpis")
    def kpis(u=Depends(user_of)):
        return wrap(RF.kpis, H.db, u["mode"])

    @app.get("/api/rfield/complaints")
    def complaints(u=Depends(user_of)):
        return wrap(lambda: {"complaints": RF.complaints(H.db, u["mode"]), "jobs": RF.jobs(H.db, u["mode"])})

    @app.post("/api/rfield/complaints")
    def new_complaint(body: dict = Body(...), u=Depends(user_of)):
        return wrap(lambda: {"id": RF.create_complaint(H, u["mode"], body, who(u))})

    @app.post("/api/rfield/complaints/{cid}/score")
    def score(cid: int, body: dict = Body(...), u=Depends(user_of)):
        return wrap(RF.score, H.db, u["mode"], cid, body.get("score", 0), body.get("comment"), who(u))

    @app.post("/api/rfield/jobs")
    def new_job(body: dict = Body(...), u=Depends(user_of)):
        return wrap(lambda: {"id": RF.plan_job(H, u["mode"], body.get("serial") or "", body.get("kind"), who(u), body.get("joint"),
                                               body.get("complaint_id"))})

    @app.post("/api/rfield/jobs/{jid}/done")
    def job_done(jid: int, body: dict = Body(default={}), u=Depends(user_of)):
        return wrap(RF.complete_job, H, u["mode"], jid, who(u), (body or {}).get("note", ""))

    @app.post("/api/rfield/advance")
    def advance(body: dict = Body(default={}), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能推进现场时钟")
        return wrap(lambda: {"days": RF.advance(H.db, u["mode"], min(365, int((body or {}).get("days", 30)))), "kpis": RF.kpis(H.db, u["mode"])})
