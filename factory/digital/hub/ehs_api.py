# -*- coding: utf-8 -*-
"""第 18 轮 E2 接口：隐患随手拍与整改验收、作业许可（资质核对、挂牌上锁）、事故与未遂、员工与培训、危险源与风险评估、
化学品与废弃物、态势，以及实验 17 的老师注入。"""
from fastapi import Body, Depends, HTTPException

from hub import ehs as EH

MANAGE = ("safety", "manager")


def mount(app, H, user_of, who):
    def can(u, roles=MANAGE):
        return bool(u.get("teacher")) or u.get("role") in roles

    def need(u, what, roles=MANAGE):
        if not can(u, roles):
            raise HTTPException(403, "{}由安全员或厂长操作".format(what))

    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ---------------------------------------------------------------- 隐患
    @app.get("/api/ehs/issues")
    def issues(status: str = "open", u=Depends(user_of)):
        EH.seed(H.db, u["mode"])
        w = "status<>'closed'" if status == "open" else "true"
        rows = H.db.q("select * from safety_issue where mode=%s and {} order by (level='major') desc, id desc limit 300".format(w), (u["mode"],))
        out = []
        for r in rows:
            x = EH.issue_row(r)
            a = H.db.one("select id from anomaly where mode=%s and rule in ('E1','E2') and fkey=%s order by id desc limit 1",
                         (u["mode"], x["key"])) if H.db.one("select to_regclass('anomaly') is not null as ok")["ok"] else None
            x["anomaly_id"] = a["id"] if a else None
            out.append(x)
        return {"issues": out, "kinds": {k: {"label": v[0], "level": v[1], "minutes": v[2]} for k, v in EH.ISSUE_KINDS.items()},
                "levels": EH.LEVEL, "can_manage": can(u), "people": EH.people(H.db, u["mode"]),
                "hazards": H.db.q("select id, name, unit from hazard where mode=%s order by id", (u["mode"],))}

    @app.post("/api/ehs/issues")
    def issue_new(body: dict = Body(...), u=Depends(user_of)):
        iid = wrap(EH.create_issue, H, u["mode"], body, who(u))           # 随手拍：所有角色都能报
        return {"id": iid, "key": "SI-{:05d}".format(iid)}

    @app.post("/api/ehs/issues/{iid}/assign")
    def issue_assign(iid: int, body: dict = Body(...), u=Depends(user_of)):
        need(u, "指派整改")
        if not body.get("owner"):
            raise HTTPException(400, "选整改人")
        wrap(EH.assign, H.db, iid, body["owner"], body.get("due_day"), who(u))
        return {"ok": True}

    @app.post("/api/ehs/issues/{iid}/fix")
    def issue_fix(iid: int, body: dict = Body(default={}), u=Depends(user_of)):
        wrap(EH.fix, H.db, iid, who(u), (body.get("note") or "")[:300])
        return {"ok": True}

    @app.post("/api/ehs/issues/{iid}/verify")
    def issue_verify(iid: int, u=Depends(user_of)):
        need(u, "验收")
        return wrap(EH.verify, H, u["mode"], iid, who(u))

    # ---------------------------------------------------------------- 作业许可
    @app.get("/api/ehs/units")
    def units(u=Depends(user_of)):
        """第 61 轮：页面上“设备”下拉框的清单随工厂变（车间里的设备和物流小车）"""
        from wqbus import UNITS
        return {"units": {k: v[1] for k, v in UNITS.items() if v[0] in ("machining", "quality", "logistics")}}

    @app.get("/api/ehs/permits")
    def permits(u=Depends(user_of)):
        EH.seed(H.db, u["mode"])
        names = {p["id"]: p["name"] for p in H.db.q("select id, name from ehs_person where mode=%s", (u["mode"],))}
        rows = H.db.q("select * from work_permit where mode=%s order by (status in ('active','requested','blocked')) desc, id desc limit 200", (u["mode"],))
        return {"permits": [EH.permit_row(H.db, r, names) for r in rows], "kinds": EH.PERMITS, "statuses": EH.PERMIT_STATUS,
                "can_manage": can(u), "people": EH.people(H.db, u["mode"])}

    @app.post("/api/ehs/permits")
    def permit_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, "申请作业许可", MANAGE + ("operator", "engineer"))
        return wrap(EH.request_permit, H.db, u["mode"], body, who(u))

    @app.post("/api/ehs/permits/{pid}/approve")
    def permit_approve(pid: int, u=Depends(user_of)):
        need(u, "批准作业许可")
        return wrap(EH.approve_permit, H, u["mode"], pid, who(u))

    @app.post("/api/ehs/permits/{pid}/close")
    def permit_close(pid: int, u=Depends(user_of)):
        need(u, "关闭 / 解锁")
        return wrap(EH.close_permit, H, u["mode"], pid, who(u))

    # ---------------------------------------------------------------- 事故与未遂（3 级敏感：详情只给厂长和老师）
    @app.get("/api/ehs/incidents")
    def incidents(u=Depends(user_of)):
        EH.init(H.db)
        rows = H.db.q("select * from incident where mode=%s order by day desc, id desc limit 200", (u["mode"],))
        full = bool(u.get("teacher")) or u.get("role") == "manager"
        counts = {}
        for r in rows:
            counts[r["kind"]] = counts.get(r["kind"], 0) + 1
        out = {"counts": {EH.INCIDENT_KINDS[k]: v for k, v in counts.items()}, "full": full, "kinds": EH.INCIDENT_KINDS}
        if full:
            out["incidents"] = [dict(r, key="IN-{:05d}".format(r["id"]), day=r["day"].isoformat(), created_at=r["created_at"].isoformat(),
                                     kind_label=EH.INCIDENT_KINDS[r["kind"]]) for r in rows]
        return out

    @app.post("/api/ehs/incidents")
    def incident_new(body: dict = Body(...), u=Depends(user_of)):
        iid = wrap(EH.create_incident, H.db, u["mode"], body, who(u))       # 谁都能报未遂
        return {"id": iid, "key": "IN-{:05d}".format(iid)}

    # ---------------------------------------------------------------- 员工、培训、危险源、风险评估
    @app.get("/api/ehs/people")
    def people(u=Depends(user_of)):
        return {"people": EH.people(H.db, u["mode"]), "kinds": {k: v[0] for k, v in EH.TRAININGS.items()}, "can_manage": can(u)}

    @app.post("/api/ehs/trainings")
    def training_new(body: dict = Body(...), u=Depends(user_of)):
        need(u, "登记培训")
        if body.get("kind") not in EH.TRAININGS or not body.get("people"):
            raise HTTPException(400, "选培训种类和参加的人")
        return wrap(EH.exec_training, H, u["mode"], {"kind": body["kind"], "people": body["people"], "day": body.get("day")}, u)

    @app.get("/api/ehs/hazards")
    def hazards(u=Depends(user_of)):
        EH.seed(H.db, u["mode"])
        return {"hazards": [dict(h, risk=EH.risk(h["likelihood"], h["severity"])) for h in H.db.q("select * from hazard where mode=%s order by id", (u["mode"],))]}

    @app.post("/api/ehs/risk")
    def risk(body: dict = Body(...), u=Depends(user_of)):
        return wrap(EH.risk, body.get("likelihood"), body.get("severity"))

    # ---------------------------------------------------------------- 化学品、废弃物
    @app.get("/api/ehs/chemicals")
    def chems(u=Depends(user_of)):
        return {"chemicals": EH.chemicals(H.db, u["mode"]), "wastes": EH.wastes(H.db, u["mode"]), "limit_days": EH.WASTE_LIMIT_DAYS, "can_manage": can(u)}

    @app.post("/api/ehs/waste/{wid}/dispose")
    def waste_dispose(wid: int, body: dict = Body(...), u=Depends(user_of)):
        need(u, "危废处置登记")
        wrap(EH.dispose, H.db, u["mode"], wid, body.get("by") or "")
        return {"ok": True}

    @app.get("/api/ehs/kpis")
    def kpis(u=Depends(user_of)):
        return EH.kpis(H.db, u["mode"])
