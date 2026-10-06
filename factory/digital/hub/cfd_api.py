# -*- coding: utf-8 -*-
"""流体分析（第 16 轮）：枢纽这边转发给计算服务，并把算出的散热系数送进“仿真与分析”的温度场。"""
import urllib.parse

from fastapi import Body, Depends, HTTPException

from hub.cae_api import FACTORY_ID, call


def thermal_rows(faces, air_t, example=None):
    """CFD 每个面的 h → 温度场的对流行（h 相近的面合成一行）；示例零件保留它的发热，底面等不散热的面不给对流"""
    skip = set()
    rows = []
    if example:
        from cae import thermal_parts as TP
        for t in example["thermal"]:
            if t["type"] in ("heat_flux", "heat_body", "temperature"):
                rows.append(dict(t))
        g = example.get("groups") or {}
        skip |= set(g.get("bottom") or []) | set(g.get("pad") or [])          # 底面装在机座 / 车上，CPU 接触面贴着芯片
        if example.get("key") != "agv_box":
            skip |= set(g.get("inner") or [])                                 # 减速器箱内壁泡在油里，不吹风（电控箱内壁照样吹风）
        _ = TP
    fs = sorted((f for f in faces if f["id"] not in skip and f.get("h_w_m2k") is not None), key=lambda f: f["h_w_m2k"])
    groups = []                                    # h 相差不到 12% 的面合成一行（面积加权平均），一般零件也就五六行
    for f in fs:
        if groups and f["h_w_m2k"] <= groups[-1][0]["h_w_m2k"] * 1.12 + 0.5:
            groups[-1].append(f)
        else:
            groups.append([f])
    for g in sorted(groups, key=lambda g: -g[-1]["h_w_m2k"]):
        A = sum(max(f.get("area_mm2") or 0, 1e-9) for f in g)
        h = sum(f["h_w_m2k"] * max(f.get("area_mm2") or 0, 1e-9) for f in g) / A
        rows.append({"type": "convection", "faces": sorted(f["id"] for f in g), "h_w_m2k": round(h * 2) / 2, "t_inf_c": air_t, "source": "cfd"})
    return rows


def h_rad(wall_c, air_c, eps=0.9):
    """辐射等效散热系数 h_r = εσ(T_w² + T_a²)(T_w + T_a)，W/(m²·K)"""
    tw, ta = wall_c + 273.15, air_c + 273.15
    return eps * 5.670e-8 * (tw * tw + ta * ta) * (tw + ta)


def mount(app, H, user_of, who, uid_of, is_teacher, ai_quota=None):

    def mine(u, j):
        if j.get("factory") != FACTORY_ID or j.get("kind") not in ("cfd", "cfd_bench"):
            raise HTTPException(404, "没有这个流体分析任务")
        if is_teacher(u) or str(j.get("owner")) == uid_of(u):
            return j
        raise HTTPException(403, "这是别人的计算任务")

    @app.post("/api/cfd/jobs")
    def cfd_submit(body: dict = Body(...), u=Depends(user_of)):
        setup = dict(body.get("setup") or {})
        return call("POST", "/cfd/jobs", json={"step_sha": body.get("step_sha"), "setup": setup, "title": (body.get("title") or "")[:80],
                                               "item": body.get("item"), "owner": uid_of(u), "owner_name": who(u),
                                               "factory": FACTORY_ID}).json()

    @app.post("/api/cfd/bench")
    def cfd_bench(u=Depends(user_of)):
        """标准题核对（几分钟）：四道题和教材公式比"""
        return call("POST", "/cfd/jobs", json={"kind": "cfd_bench", "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/cfd/jobs")
    def cfd_jobs(u=Depends(user_of)):
        out = []
        for kind in ("cfd", "cfd_bench"):
            params = {"factory": FACTORY_ID, "limit": 50, "kind": kind}
            if not is_teacher(u):
                params["owner"] = uid_of(u)
            out += call("GET", "/jobs", params=params).json()["jobs"]
        return {"jobs": sorted(out, key=lambda j: j["created"], reverse=True)}

    @app.get("/api/cfd/jobs/{jid}")
    def cfd_job(jid: str, u=Depends(user_of)):
        return mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())

    @app.get("/api/cfd/jobs/{jid}/result")
    def cfd_result(jid: str, u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        return call("GET", "/cfd/jobs/{}/result".format(urllib.parse.quote(jid))).json()

    def llm_for(u):
        llm = H.ai.llm if getattr(H, "ai", None) else None
        if llm is not None and llm.available() and ai_quota:
            ai_quota(u)
        return llm

    @app.post("/api/cfd/ai-setup")
    def cfd_ai_setup(body: dict = Body(...), u=Depends(user_of)):
        """一句话 → 表单（AI 只填表，学生确认后再算）"""
        from hub import cfd_ai
        text = (body.get("text") or "").strip()[:300]
        if not text:
            raise HTTPException(400, "说一句要怎么吹风")
        r = cfd_ai.rules_setup(text, body.get("bbox"))
        if r["unmatched"] or not r["form"]:
            r = cfd_ai.setup(llm_for(u), text, body.get("bbox"))
        return r

    @app.post("/api/cfd/jobs/{jid}/explain")
    def cfd_explain(jid: str, u=Depends(user_of)):
        from hub import cfd_ai
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["kind"] != "cfd" or j["status"] != "done":
            raise HTTPException(409, "计算完成后才能解释")
        r = call("GET", "/cfd/jobs/{}/result".format(urllib.parse.quote(jid))).json()
        return cfd_ai.explain(llm_for(u), j["stats"], r["aux"]["faces"])

    @app.post("/api/cfd/jobs/{jid}/report")
    def cfd_report(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        """Word 报告：images = 浏览器截的三维图，ai_text = 页面上的解释"""
        from fastapi import Response
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["kind"] != "cfd":
            raise HTTPException(409, "标准题核对没有报告")
        r = call("POST", "/jobs/{}/report".format(urllib.parse.quote(jid)), json=body)
        return Response(r.content, media_type=r.headers.get("content-type"),
                        headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")})

    @app.post("/api/cfd/jobs/{jid}/to-thermal")
    def cfd_to_thermal(jid: str, u=Depends(user_of)):
        """把算出的散热系数送到温度场：零件（同一个 STEP）+ 每个面的对流行；示例零件带上它的发热和教材公式"""
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["kind"] != "cfd" or j["status"] != "done" or not j["setup"].get("heat"):
            raise HTTPException(409, "要先做一次带换热的流体分析")
        r = call("GET", "/cfd/jobs/{}/result".format(urllib.parse.quote(jid))).json()
        geo = call("GET", "/geometry/{}/faces".format(j["step_sha"])).json()
        geo["sha"] = j["step_sha"]
        geo["model_url"] = "/api/cae/geometry/{}/model.glb".format(j["step_sha"])
        ex = None
        exs = (j["setup"] or {}).get("example")
        if exs:
            from cae import thermal_parts as TP
            p = TP.params_of(exs["key"], exs.get("params"))
            ex = dict(TP.example(exs["key"], p, geo["faces"]), key=exs["key"], params=p)
            geo["example"] = ex
        air = float((j["setup"].get("flow") or {}).get("air_t_c", 25))
        rows = thermal_rows(r["aux"]["faces"], air, ex)
        st = j["stats"]
        extra = ""
        if ex and ex.get("key") == "housing":
            # 教材的 K_s 是对流 + 辐射的总散热系数；涂漆铸铁箱体发射率约 0.9，表面温度下的辐射等效系数加到每一行
            hr = h_rad(float(st.get("wall_t_c") or 70), air)
            for t in rows:
                if t.get("source") == "cfd":
                    t["h_w_m2k"] = round((t["h_w_m2k"] + hr) * 2) / 2
            outer = set((ex.get("groups") or {}).get("outer") or [])
            fs = [f for f in r["aux"]["faces"] if f["id"] in outer and f.get("h_w_m2k") is not None]
            A = sum(f["area_mm2"] for f in fs)
            if A > 0:
                hc = sum(f["h_w_m2k"] * f["area_mm2"] for f in fs) / A
                K = hc + hr
                fm = dict(ex["formula"])
                fm.update(K_s=round(K, 2), t0_c=air, t_oil_c=round(air + fm["loss_w"] / (K * fm["A_m2"]), 1),
                          note="K_s = 流体分析算出的外表面平均对流 {:.1f} + 辐射 {:.1f}（发射率 0.9）W/(m²·K)，不再查表；".format(hc, hr) + fm.get("note", ""))
                ex["formula"] = fm
            extra = "；箱体每行另加辐射 {:.1f} W/(m²·K)（涂漆铸铁发射率 0.9，教材 K_s 也含辐射）".format(hr)
        return {"geometry": geo, "thermal": rows, "material_id": ex["material_id"] if ex else None,
                "title": "{}（散热系数来自流体分析：{} m/s）".format(ex["title"] if ex else (j.get("title") or "零件"), st["velocity_ms"]),
                "note": "散热系数取自流体分析 {}：风速 {} m/s、来流 {}、表面 {} ℃ 时算出的各面平均 h（{} 个面，平均 {:.1f} W/(m²·K)）".format(
                    jid, st["velocity_ms"], st["direction"], st.get("wall_t_c"), len(r["aux"]["faces"]), st.get("h_mean") or 0) + extra,
                "mesh_mm": ex["mesh_mm"] if ex else None, "source": {"cfd": jid}}
