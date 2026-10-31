# -*- coding: utf-8 -*-
"""第 18 轮 E4 接口：组织与员工、技能矩阵、排班、出勤与加班、技能培训、老师开关“要有人”。

员工数据 2 级敏感：电话只给厂长和老师；出勤明细（谁请假、迟到）给厂长、班组长和老师，其他人只看数量。"""
import datetime as dt

from fastapi import Body, Depends, HTTPException

from hub import people as PE

MANAGE = ("lead", "manager")          # 记出勤、考核通过
DETAIL = ("lead", "manager")          # 看出勤明细


def mount(app, H, user_of, who):
    def can(u, roles=MANAGE):
        return bool(u.get("teacher")) or u.get("role") in roles

    def need(u, what, roles=MANAGE):
        if not can(u, roles):
            raise HTTPException(403, "{}由班组长或厂长操作".format(what))

    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    def phone_ok(u):
        return bool(u.get("teacher")) or u.get("role") == "manager"

    @app.get("/api/people/employees")
    def employees(u=Depends(user_of)):
        rows = PE.employees(H.db, u["mode"])
        if not phone_ok(u):
            rows = [dict(r, phone=None) for r in rows]
        return {"employees": rows, "departments": [{"name": d, "en": e, "count": sum(1 for r in rows if r.get("dept") == d)} for d, e in PE.DEPTS],
                "posts": [{"name": k, "en": v} for k, v in PE.POSTS.items()], "kpis": PE.kpis(H.db, u["mode"]), "can_manage": can(u),
                "teacher": bool(u.get("teacher")) and u["mode"] == "teach"}

    @app.get("/api/people/employees/{pid}")
    def employee(pid: str, u=Depends(user_of)):
        db, mode = H.db, u["mode"]
        p = next((x for x in PE.employees(db, mode) if x["id"] == pid), None)
        if p is None:
            raise HTTPException(404, "没有这个人")
        if not phone_ok(u):
            p = dict(p, phone=None)
        from hub import ehs as EH
        tr = [t for t in EH.trainings(db, mode) if t["person_id"] == pid]
        att = [dict(r, day=r["day"].isoformat(), at=r["at"].isoformat())
               for r in db.q("select * from attendance where mode=%s and emp_id=%s order by day desc limit 30", (mode, pid))] if can(u, DETAIL) else None
        return {"employee": p, "safety_trainings": tr, "skill_trainings": [t for t in PE.trainings(db, mode) if t["emp_id"] == pid],
                "attendance": att, "overtime_h_week": PE.overtime_week(db, mode).get(pid, 0)}

    @app.get("/api/people/skills")
    def skills(u=Depends(user_of)):
        return dict(PE.matrix(H.db, u["mode"]), levels=PE.LEVELS, single_points=PE.single_points(H.db, u["mode"]))

    @app.get("/api/people/roster")
    def roster(week: str = "", u=Depends(user_of)):
        day = dt.date.fromisoformat(week) if week else None
        rows = PE.week(H.db, u["mode"], day)
        if not can(u, DETAIL):
            rows = [dict(r, cells={k: dict(c, attendance=None) for k, c in r["cells"].items()}) for r in rows]
        d, sh = PE.now_shift(None, H.db, u["mode"])
        return {"rows": rows, "now": {"day": d.isoformat(), "shift": sh}, "enabled": PE.enabled(H.db, u["mode"]),
                "gaps": PE.gaps(H.db, u["mode"]), "can_manage": can(u),
                "units": list(PE.STF.NEEDS), "shift_names": PE.SHIFT_NAME}            # 第 61 轮：随工厂变

    @app.get("/api/people/today")
    def today(u=Depends(user_of)):
        b = PE.today_board(H.db, u["mode"])
        if not can(u, DETAIL):
            b = dict(b, people=[dict(x, attendance="在岗" if x["attendance"] == "在岗" else "不在岗") for x in b["people"]])
        return b

    @app.post("/api/people/attendance")
    def attendance(body: dict = Body(...), u=Depends(user_of)):
        need(u, "记出勤")
        day = dt.date.fromisoformat(body["day"]) if body.get("day") else None
        return wrap(PE.record_attendance, H, u["mode"], body.get("emp_id"), body.get("status"), day, body.get("shift"), who(u),
                    body.get("minutes_late"))

    @app.post("/api/people/attendance/clear")
    def attendance_clear(body: dict = Body(...), u=Depends(user_of)):
        need(u, "改出勤")
        PE.clear_attendance(H, u["mode"], body.get("emp_id"), dt.date.fromisoformat(body["day"]), body.get("shift"), who(u))
        return {"ok": True}

    @app.get("/api/people/overtime")
    def overtime(u=Depends(user_of)):
        ot = PE.overtime_week(H.db, u["mode"])
        names = {p["id"]: p["name"] for p in PE.employees(H.db, u["mode"])}
        return {"week": [{"emp_id": k, "name": names.get(k, k), "hours": v} for k, v in sorted(ot.items(), key=lambda x: -x[1])],
                "limit_h": PE.OT_WEEK_LIMIT_H, "absence": PE.absence_rate(H.db, u["mode"])}

    @app.get("/api/people/kpis")
    def kpis(u=Depends(user_of)):
        return PE.kpis(H.db, u["mode"])

    @app.get("/api/people/trainings")
    def trainings(u=Depends(user_of)):
        return {"trainings": PE.trainings(H.db, u["mode"]), "can_manage": can(u)}

    @app.post("/api/people/trainings/{tid}/pass")
    def training_pass(tid: int, u=Depends(user_of)):
        need(u, "考核")
        return wrap(PE.pass_training, H, u["mode"], tid, who(u))

    @app.post("/api/people/staffing")
    def staffing(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能开关“要有人”")
        return PE.set_enabled(H, u["mode"], bool(body.get("enabled")), who(u))
