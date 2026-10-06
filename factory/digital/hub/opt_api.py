# -*- coding: utf-8 -*-
"""设计优化（第 14 轮 H4、H5）：枢纽这边补上现行设计参数，交给 cae 计算服务排队优化；结果可送设计台（SH-301）或回“仿真与分析”（示例零件）。"""
import json
import urllib.parse

from fastapi import Body, Depends, HTTPException

from hub.cae_api import FACTORY_ID, call


def mount(app, H, user_of, who, uid_of, is_teacher, ai_quota=None):

    def mine(u, j):
        if j.get("factory") != FACTORY_ID or j.get("kind") not in ("opt", "topo"):
            raise HTTPException(404, "没有这个优化任务")
        if is_teacher(u) or str(j.get("owner")) == uid_of(u):
            return j
        raise HTTPException(403, "这是别人的优化任务")

    @app.get("/api/opt/problems")
    def opt_problems(u=Depends(user_of)):
        from hub.cam_api import shaft_params
        r = call("GET", "/opt/problems").json()
        p = shaft_params(H.db, u["mode"])
        for x in r["problems"]:
            if x["id"] == "shaft":
                x["base"] = p
                x["current"] = {"d_gear": p["segments"][2][0], "d_end": p["segments"][4][0]}
            else:
                from cae import thermal_parts as TP
                x["base"] = TP.DEFAULTS[x["id"]]
                x["current"] = TP.DEFAULTS[x["id"]]
        return r

    @app.post("/api/opt/jobs")
    def opt_submit(body: dict = Body(...), u=Depends(user_of)):
        from hub.cam_api import shaft_params
        spec = dict(body.get("spec") or {})
        if spec.get("problem") == "shaft":
            spec["base"] = shaft_params(H.db, u["mode"])            # 总是以现行设计为起点
            item = "SH-301"
        else:
            item = None
        return call("POST", "/opt/jobs", json={"spec": spec, "title": (body.get("title") or "")[:80], "item": item,
                                               "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/opt/jobs")
    def opt_jobs(u=Depends(user_of)):
        params = {"factory": FACTORY_ID, "limit": 100, "kind": "opt"}
        if not is_teacher(u):
            params["owner"] = uid_of(u)
        return call("GET", "/jobs", params=params).json()

    @app.get("/api/opt/jobs/{jid}")
    def opt_job(jid: str, u=Depends(user_of)):
        return mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())

    @app.get("/api/opt/jobs/{jid}/trials")
    def opt_trials(jid: str, u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        return call("GET", "/opt/jobs/{}/trials".format(urllib.parse.quote(jid))).json()

    @app.post("/api/opt/jobs/{jid}/use")
    def opt_use(jid: str, body: dict = Body(...), u=Depends(user_of)):
        """用某一组结果：SH-301 → 设计台参数（还没发布）；示例零件 → 回“仿真与分析”按这组参数重算"""
        from cae import optimize as O
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        spec, x = j["spec"], body.get("x") or {}
        if spec["problem"] == "shaft":
            p = O._shaft_params(spec["base"], {k: float(v) for k, v in x.items()})
            b = spec["base"]["segments"]
            note = "设计优化：齿轮位 Ø{:g} → Ø{:g}，轴伸 Ø{:g} → Ø{:g}".format(b[2][0], p["segments"][2][0], b[4][0], p["segments"][4][0])
            return {"kind": "design", "url": "/work/engineer?" + urllib.parse.urlencode({"suggest": json.dumps(p, ensure_ascii=False), "note": note})}
        params = dict(spec.get("base") or {}, **x)
        return {"kind": "example", "url": "/cae?" + urllib.parse.urlencode({"example": spec["problem"], "params": json.dumps(params)})}

    @app.post("/api/opt/ai-setup")
    def opt_ai_setup(body: dict = Body(...), u=Depends(user_of)):
        from cae import optimize as O
        from hub import opt_ai
        prob = body.get("problem")
        if prob not in O.VARS:
            raise HTTPException(400, "不认识的优化问题")
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)
        try:
            return opt_ai.setup(H.ai.llm if H.ai else None, body.get("text"), prob, body.get("form") or {}, list(O.VARS[prob]))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/opt/jobs/{jid}/explain")
    def opt_explain(jid: str, u=Depends(user_of)):
        from hub import opt_ai
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["status"] != "done":
            raise HTTPException(409, "优化还没做完")
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)
        res = call("GET", "/opt/jobs/{}/trials".format(urllib.parse.quote(jid))).json()
        return opt_ai.explain(H.ai.llm if H.ai else None, j, res)

    # ---------- 拓扑优化（平面件，第 14 轮 H6） ----------
    @app.get("/api/opt/topo/presets")
    def topo_presets(u=Depends(user_of)):
        return call("GET", "/topo/presets").json()

    @app.post("/api/opt/topo")
    def topo_submit(body: dict = Body(...), u=Depends(user_of)):
        return call("POST", "/topo/jobs", json={"spec": body.get("spec") or {}, "title": (body.get("title") or "")[:80],
                                                "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/opt/topo/jobs")
    def topo_jobs(u=Depends(user_of)):
        params = {"factory": FACTORY_ID, "limit": 50, "kind": "topo"}
        if not is_teacher(u):
            params["owner"] = uid_of(u)
        return call("GET", "/jobs", params=params).json()

    @app.get("/api/opt/topo/{jid}/result")
    def topo_result(jid: str, u=Depends(user_of)):
        from hub import opt_ai
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("GET", "/topo/jobs/{}/result".format(urllib.parse.quote(jid))).json()
        r["explain"] = opt_ai.topo_explain(j, r)
        return r

    @app.post("/api/opt/topo/{jid}/to-fea")
    def topo_to_fea(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("POST", "/topo/jobs/{}/to-fea".format(urllib.parse.quote(jid)), json=body).json()
        r["geometry"]["model_url"] = "/api/cae/geometry/{}/model.glb".format(r["geometry"]["sha"])
        r["geometry"]["name"] = r["title"]
        return r
