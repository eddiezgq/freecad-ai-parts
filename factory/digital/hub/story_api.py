# -*- coding: utf-8 -*-
"""第 19 轮接口：情景导演（两周情景）——剧本、开始、下一幕、自动演示、时间线、复盘。只在教学模式；执行只给老师。"""
from fastapi import Body, Depends, HTTPException

from hub import story as ST


def mount(app, H, user_of, who, reset_teach):
    def wrap(fn, *a, **k):
        try:
            return fn(*a, **k)
        except KeyError as e:
            raise HTTPException(404, "没有：{}".format(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    def teacher(u):
        if u["mode"] != "teach":
            raise HTTPException(403, "情景导演只在教学模式")
        if not u.get("teacher"):
            raise HTTPException(403, "情景导演只给老师")

    @app.get("/api/story/scenarios")
    def scenarios(u=Depends(user_of)):
        return {"scenarios": [ST._sc_head(s) for s in ST.scenarios().values()]}

    @app.get("/api/story/state")
    def state(u=Depends(user_of)):
        if u["mode"] != "teach":
            raise HTTPException(403, "情景导演只在教学模式")
        return wrap(ST.state, H.db)

    @app.post("/api/story/start")
    def start(body: dict = Body(default={}), u=Depends(user_of)):
        teacher(u)
        if u["role"] != "manager":
            raise HTTPException(403, "请用厂长（教师）角色开始情景")
        return wrap(ST.start, H, who(u), body.get("scenario") or "two_weeks", body.get("speed"), bool(body.get("auto")), reset_teach,
                    body.get("wrapup", True) is not False)

    @app.post("/api/story/next")
    def nxt(u=Depends(user_of)):
        teacher(u)
        return wrap(ST.next_beat, H, who(u))

    @app.post("/api/story/beat/{n}")
    def beat(n: int, u=Depends(user_of)):
        teacher(u)
        return wrap(ST.next_beat, H, who(u), n)

    @app.post("/api/story/auto")
    def auto(body: dict = Body(default={}), u=Depends(user_of)):
        teacher(u)
        return wrap(ST.set_auto, H.db, bool(body.get("on", True)), body.get("dwell_s"))

    @app.post("/api/story/ff")
    def ff(body: dict = Body(default={}), u=Depends(user_of)):
        teacher(u)
        return wrap(ST.fast_forward, H, bool(body.get("on", True)), body.get("speed"))

    @app.post("/api/story/end")
    def end(u=Depends(user_of)):
        teacher(u)
        return wrap(ST.end, H.db, who(u))

    @app.get("/api/story/review")
    def review(report: int = 0, u=Depends(user_of)):
        if u["mode"] != "teach":
            raise HTTPException(403, "情景只在教学模式")
        return wrap(ST.review, H, "teach", bool(report))
