# -*- coding: utf-8 -*-
"""第 18 轮 E6 接口：能源总览、计量点曲线、单耗、碳核算、车间环境、参数（厂长改电价、碳因子、合同需量、环境限值）、老师开关与注入。"""
import datetime as dt

from fastapi import Body, Depends, HTTPException

from hub import energy as EN


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

    @app.get("/api/energy/overview")
    def overview(day: str = "", u=Depends(user_of)):
        d = None
        if day:
            try:
                d = dt.date.fromisoformat(day)
            except ValueError:
                raise HTTPException(400, "日期格式 YYYY-MM-DD")
        o = EN.overview(H.db, u["mode"], d)
        o.update({"measuring": EN.measuring(H.db, u["mode"]), "sim": EN.sim_on(H.db, u["mode"]), "settings": EN.settings(H.db, u["mode"]),
                  "faults": EN.live_faults(H.db, u["mode"]) if u.get("teacher") else [], "teacher": bool(u.get("teacher")) and u["mode"] == "teach",
                  "can_params": boss(u), "env": EN.env_now(H.db, u["mode"]), "demand": EN.demand(H.db, u["mode"]),
                  "state_names": EN.STATE_NAME, "bucket_names": EN.BUCKET_NAME})
        return o

    @app.get("/api/energy/meters")
    def meters(u=Depends(user_of)):
        return {"meters": EN.meters(H.db, u["mode"])}

    @app.get("/api/energy/meters/{code}/series")
    def series(code: str, hours: int = 24, u=Depends(user_of)):
        hours = max(1, min(int(hours), 24 * 31))
        if code.startswith("ENV-"):
            return {"code": code, "series": EN.env_series(H.db, u["mode"], hours).get(code[4:].lower(), [])}
        return {"code": code, "series": EN.series(H.db, u["mode"], code, hours)}

    @app.get("/api/energy/unit")
    def unit(u=Depends(user_of)):
        return {"rows": EN.unit_energy(H.db, u["mode"]), "idle": EN.idle_by_unit(H.db, u["mode"]), "peak": EN.peak_share(H.db, u["mode"]),
                "air": EN.air_excess(H.db, u["mode"])}

    @app.get("/api/energy/carbon")
    def carbon(month: str = "", u=Depends(user_of)):
        return wrap(EN.carbon, H.db, u["mode"], month or None)

    @app.get("/api/energy/env")
    def env(hours: int = 24, u=Depends(user_of)):
        return {"now": EN.env_now(H.db, u["mode"]), "series": EN.env_series(H.db, u["mode"], max(1, min(int(hours), 24 * 7)))}

    @app.get("/api/energy/params")
    def params(u=Depends(user_of)):
        return dict(EN.params(H.db, u["mode"]), can_edit=boss(u))

    @app.post("/api/energy/params")
    def params_set(body: dict = Body(...), u=Depends(user_of)):
        if not boss(u):
            raise HTTPException(403, "电价、碳排放因子、合同需量、环境限值由厂长改")
        return wrap(EN.set_params, H.db, u["mode"], body)

    @app.get("/api/energy/kpis")
    def kpis(u=Depends(user_of)):
        return EN.kpis(H.db, u["mode"]) or {}

    @app.post("/api/energy/sim")
    def sim(body: dict = Body(...), u=Depends(user_of)):
        if not (u.get("teacher") and u["mode"] == "teach"):
            raise HTTPException(403, "只有教学模式的老师能开关、注入")
        if body.get("sim") is not None:
            EN.set_sim(H.db, "teach", bool(body["sim"]))
        if body.get("inject"):
            x = body["inject"]
            return wrap(EN.inject, H, "teach", x.get("kind"), who(u), x.get("unit"), x.get("hours"), x.get("pct"))
        if body.get("clear"):
            EN.clear(H, "teach", str(body["clear"]), who(u))
        return {"sim": EN.sim_on(H.db, "teach"), "faults": EN.live_faults(H.db, "teach")}
