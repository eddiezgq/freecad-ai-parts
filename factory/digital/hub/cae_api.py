# -*- coding: utf-8 -*-
"""仿真与分析（第 11 轮）：枢纽这边核对身份、取零件 STEP，转交给 cae 计算服务。

所有工厂共用一个 cae 服务，任务上带工厂编号（历史库名，如 wq_factory / wq_demo / wq_c_pilot）和提交人。
学生看自己的任务；老师（厂长角色、班级任课老师）看本厂全部任务。
"""
import math
import os
import urllib.parse

import httpx
from fastapi import Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

CAE_URL = os.environ.get("WQ_CAE_URL", "http://cae:8200")
FACTORY_ID = os.environ.get("WQ_FACTORY_ID") or urllib.parse.urlparse(
    os.environ.get("WQ_DB", "postgresql://x@h/wq_factory")).path.strip("/") or "wq_factory"
CLIENT = None                 # 测试时换成计算服务的 TestClient
import logging  # noqa: E402
logging.getLogger("httpx").setLevel(logging.WARNING)


def client():
    global CLIENT
    if CLIENT is None:
        CLIENT = httpx.Client(base_url=CAE_URL, timeout=120)
    return CLIENT


def call(method, path, **kw):
    try:
        r = client().request(method, path, **kw)
    except httpx.HTTPError:
        raise HTTPException(503, "计算服务暂时连不上，请稍后再试") from None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:  # noqa: BLE001
            detail = r.text[:200]
        raise HTTPException(r.status_code, detail)
    return r


def mount(app, H, user_of, who, uid_of, is_teacher, ai_quota=None):
    from hub import plm

    def _ai_quota(u):                     # 只有真用到模型时才计次数（规则兜底不算）
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)

    def mine(u, j):
        if j.get("factory") != FACTORY_ID:
            raise HTTPException(404, "没有这个任务")
        if is_teacher(u) or str(j.get("owner")) == uid_of(u):
            return j
        raise HTTPException(403, "这是别人的计算任务")

    @app.get("/api/cae/{lab}/{kind}.docx")
    def cae_lab(lab: str, kind: str):
        """实验 8–12 的指导书 / 报告模板（Word，公开，课程里直接链接）"""
        from cae import labdoc
        titles = {"lab8": "实验8-输出轴强度与疲劳校核", "lab9": "实验9-机械臂关节力矩与电机选型",
                  "lab10": "实验10-输出轴数控车削与键槽铣削编程", "lab11": "实验11-减速器热平衡与输出轴轻量化",
                  "lab12": "实验12-一根轴的数字化设计与两个典型案例", "lab13": "实验13-减速器数字孪生与预测性维护",
                  "lab14": "实验14-减速器风扇冷却的流体与传热分析", "lab15": "实验15-车间异常的追因推演与决策"}
        if lab not in titles or kind not in ("guide", "report-template"):
            raise HTTPException(404, "没有这个文件")
        data = labdoc.guide_docx(lab) if kind == "guide" else labdoc.report_template_docx(lab)
        name = titles[lab] + "-" + ("实验指导书" if kind == "guide" else "实验报告模板") + ".docx"
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + urllib.parse.quote(name)})

    @app.get("/api/cae/health")
    def cae_health():
        """计算服务是否在线（上线检查用，不需要登录）"""
        return call("GET", "/health").json()

    @app.get("/api/cae/materials")
    def cae_materials(u=Depends(user_of)):
        return call("GET", "/materials").json()

    @app.get("/api/cae/parts")
    def cae_parts(u=Depends(user_of)):
        """可以直接分析的零件：有现行 STEP 的物料（SH-301 总有）；另外可以上传 STEP"""
        from cae import thermal_parts as TP
        return {"items": [dict(plm.item_info(i) or {"item": i}, item=i) for i in plm.items_with_step(H.db, u["mode"])],
                "examples": [{"key": k, "label": TP.LABELS[k], "params": TP.DEFAULTS[k], "names": TP.PARAM_NAMES[k]} for k in TP.DEFAULTS]}

    @app.post("/api/cae/geometry/example/{key}")
    def cae_geometry_example(key: str, body: dict = Body(default={}), u=Depends(user_of)):
        """热分析的参数化示例（第 14 轮）：按参数现做 STEP，读入，并给出自动填好的热载荷和教材公式估算"""
        from cae import thermal_parts as TP
        if key not in TP.DEFAULTS:
            raise HTTPException(404, "没有这个示例")
        try:
            p = TP.params_of(key, body.get("params"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        g = _geo(TP.build(key, p), name=TP.LABELS[key])
        g["example"] = dict(TP.example(key, p, g["faces"]), key=key, params=p)
        return g

    def _geo(step, item=None, name=None):
        g = call("POST", "/geometry", content=step, headers={"content-type": "application/step"}).json()
        g["item"], g["name"] = item, name
        g["model_url"] = "/api/cae/geometry/{}/model.glb".format(g["sha"])
        return g

    @app.post("/api/cae/geometry/item/{item}")
    def cae_geometry_item(item: str, u=Depends(user_of)):
        step = plm.current_step(H.db, u["mode"], item)
        if not step:
            raise HTTPException(404, "{} 还没有发布过三维模型（STEP）".format(item))
        return _geo(step, item=item, name=item)

    @app.post("/api/cae/geometry/upload")
    async def cae_geometry_upload(step: UploadFile = File(...), u=Depends(user_of)):
        data = await step.read()
        if len(data) > 30 * 1024 * 1024:
            raise HTTPException(413, "STEP 文件超过 30 MB，教学版不支持")
        return _geo(data, name=step.filename)

    @app.get("/api/cae/geometry/{sha}/model.glb")
    def cae_geometry_glb(sha: str):
        r = call("GET", "/geometry/{}/model.glb".format(sha))
        return Response(r.content, media_type="model/gltf-binary", headers={"Cache-Control": "max-age=86400"})

    @app.post("/api/cae/jobs")
    def cae_submit(body: dict = Body(...), u=Depends(user_of)):
        return call("POST", "/jobs", json={
            "step_sha": body.get("step_sha"), "setup": body.get("setup") or {}, "title": (body.get("title") or "")[:80],
            "item": body.get("item"), "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/cae/jobs")
    def cae_jobs(u=Depends(user_of)):
        params = {"factory": FACTORY_ID, "limit": 100, "kind": "fea"}
        if not is_teacher(u):
            params["owner"] = uid_of(u)
        return call("GET", "/jobs", params=params).json()

    # ------------------------------------------------------------ 运动与动力分析（第 12 轮）
    @app.get("/api/mbd/robots")
    def mbd_robots(u=Depends(user_of)):
        return call("GET", "/mbd/robots").json()

    @app.get("/api/mbd/mechs")
    def mbd_mechs(u=Depends(user_of)):
        return call("GET", "/mbd/mechs").json()

    def _with_url(info):
        info["model_url"] = "/api/mbd/models/{}/model.glb".format(info["key"])
        return info

    @app.post("/api/mbd/models/load")
    def mbd_load(body: dict = Body(...), u=Depends(user_of)):
        if body.get("source") not in ("library", "mech"):
            raise HTTPException(400, "模型来源不对")
        return _with_url(call("POST", "/mbd/models/load", json=body).json())

    @app.post("/api/mbd/models/upload")
    async def mbd_upload(file: UploadFile = File(...), u=Depends(user_of)):
        data = await file.read()
        if len(data) > 100 * 1024 * 1024:
            raise HTTPException(413, "文件超过 100 MB")
        return _with_url(call("POST", "/mbd/models/upload", params={"name": file.filename or "model.xml"}, content=data).json())

    @app.get("/api/mbd/models/{key}/model.glb")
    def mbd_glb(key: str):
        r = call("GET", "/mbd/models/{}/model.glb".format(urllib.parse.quote(key)))
        return Response(r.content, media_type="model/gltf-binary", headers={"Cache-Control": "max-age=86400"})

    @app.post("/api/mbd/jobs")
    def mbd_submit(body: dict = Body(...), u=Depends(user_of)):
        return call("POST", "/mbd/jobs", json={
            "model": body.get("model") or {}, "setup": body.get("setup") or {}, "title": (body.get("title") or "")[:80],
            "item": body.get("item"), "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/mbd/jobs")
    def mbd_jobs(u=Depends(user_of)):
        params = {"factory": FACTORY_ID, "limit": 100, "kind": "mbd"}
        if not is_teacher(u):
            params["owner"] = uid_of(u)
        return call("GET", "/jobs", params=params).json()

    @app.get("/api/mbd/jobs/{jid}")
    def mbd_job(jid: str, u=Depends(user_of)):
        return mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())

    @app.post("/api/mbd/jobs/{jid}/to-fea")
    def mbd_to_fea(jid: str, body: dict = Body(...), u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("POST", "/mbd/jobs/{}/to-fea".format(urllib.parse.quote(jid)), json=body).json()
        r["geometry"]["model_url"] = "/api/cae/geometry/{}/model.glb".format(r["geometry"]["sha"])
        r["geometry"]["name"] = r["title"]
        return r

    @app.get("/api/mbd/jobs/{jid}/motors")
    def mbd_motors(jid: str, safety: float = 1.2, u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        return call("GET", "/mbd/jobs/{}/motors".format(urllib.parse.quote(jid)), params={"safety": safety}).json()

    @app.post("/api/mbd/ai-setup")
    def mbd_ai_setup(body: dict = Body(...), u=Depends(user_of)):
        """一句话设置（动力学）：只填表。body = {text, model: {kind, joints, driver, labels, followers, bodies, end_body}}"""
        from hub import mbd_ai
        model = body.get("model") or {}
        if not model.get("joints"):
            raise HTTPException(400, "请先读入模型")
        _ai_quota(u)
        try:
            return mbd_ai.setup(H.ai.llm if H.ai else None, body.get("text"), model)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/mbd/jobs/{jid}/explain")
    def mbd_explain(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        from hub import mbd_ai
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["status"] != "done":
            raise HTTPException(409, "结果还没出来")
        _ai_quota(u)
        r = mbd_ai.explain(H.ai.llm if H.ai else None, j, body.get("labels") or {}, set(body.get("fixed_bodies") or []))
        call("POST", "/jobs/{}/note".format(urllib.parse.quote(jid)), json={"ai_text": r["text"]})
        return r

    @app.post("/api/mbd/jobs/{jid}/report")
    def mbd_report(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("POST", "/jobs/{}/report".format(urllib.parse.quote(jid)), json=body)
        return Response(r.content, media_type=r.headers.get("content-type"),
                        headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")})

    @app.get("/api/mbd/jobs/{jid}/{part}.bin")
    def mbd_bin(jid: str, part: str, u=Depends(user_of)):
        if part not in ("series", "anim"):
            raise HTTPException(404, "没有这个文件")
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("GET", "/jobs/{}/{}.bin".format(urllib.parse.quote(jid), part))
        return Response(r.content, media_type="application/octet-stream", headers={"Cache-Control": "max-age=86400"})

    @app.get("/api/cae/jobs/{jid}")
    def cae_job(jid: str, u=Depends(user_of)):
        return mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())

    @app.post("/api/cae/jobs/{jid}/report")
    def cae_report(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("POST", "/jobs/{}/report".format(urllib.parse.quote(jid)), json=body)
        return Response(r.content, media_type=r.headers.get("content-type"),
                        headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")})

    @app.post("/api/cae/ai-setup")
    def cae_ai_setup(body: dict = Body(...), u=Depends(user_of)):
        """一句话设置：只填表，人确认后才计算。body = {text, faces, solid}（面清单就是读入零件时拿到的）"""
        from hub import cae_ai
        faces = body.get("faces") or []
        if not faces:
            raise HTTPException(400, "请先读入零件")
        _ai_quota(u)
        try:
            return cae_ai.setup(H.ai.llm if H.ai else None, body.get("text"), faces, body.get("solid"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/cae/ai-setup-thermal")
    def cae_ai_setup_thermal(body: dict = Body(...), u=Depends(user_of)):
        """一句话设置热边界（第 14 轮）：只填表。body = {text, faces, solid, groups}（groups：示例零件按位置分好的面组）"""
        from hub import thermal_ai
        faces = body.get("faces") or []
        if not faces:
            raise HTTPException(400, "请先读入零件")
        _ai_quota(u)
        try:
            return thermal_ai.setup(H.ai.llm if H.ai else None, body.get("text"), faces, body.get("solid"), body.get("groups"))
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/cae/jobs/{jid}/explain")
    def cae_explain(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        """AI 解释结果 + 可执行建议（换材料重算、到设计台改尺寸）。解释记进任务，报告里带上"""
        from hub import cae_ai
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        if j["status"] != "done":
            raise HTTPException(409, "结果还没出来")
        _ai_quota(u)
        if (j.get("setup") or {}).get("analysis") in ("thermal", "thermo_mech"):       # 第 14 轮：温度场
            from hub import thermal_ai
            r = thermal_ai.explain(H.ai.llm if H.ai else None, j)
            call("POST", "/jobs/{}/note".format(urllib.parse.quote(jid)), json={"ai_text": r["text"]})
            return r
        params = None
        if j.get("item") == "SH-301":
            from hub import design as D
            rel = [r for r in H.db.messages(["design.release"], mode=u["mode"], order="desc", limit=50) if r["data"]["item"] == "SH-301"]
            params = rel[0]["data"].get("params") if rel and rel[0]["data"].get("params") else D.normalize(D.defaults())
        faces = body.get("faces") or call("GET", "/geometry/{}/faces".format(j["step_sha"])).json()["faces"]
        r = cae_ai.explain(H.ai.llm if H.ai else None, j, faces, params)
        call("POST", "/jobs/{}/note".format(urllib.parse.quote(jid)), json={"ai_text": r["text"]})
        return r

    @app.get("/api/cae/torque-logs")
    def cae_torque_logs(u=Depends(user_of)):
        """跑合试验台的转矩记录（疲劳寿命的载荷谱），最近 20 条"""
        rows = H.db.messages(["test.torque"], mode=u["mode"], order="desc", limit=200)
        out, seen = [], set()
        for r in rows:
            key = (r["data"]["part_serial"], r["data"].get("work_order"))
            if key in seen:                      # 重置情景会重发同一件的记录
                continue
            seen.add(key)
            if len(out) >= 20:
                break
            s = r["data"]["samples_nm"]
            out.append({"id": r["id"], "ts": r["ts"], "item": r["data"]["item"], "part_serial": r["data"]["part_serial"],
                        "program": r["data"].get("program"), "duration_s": len(s) / r["data"]["rate_hz"],
                        "peak_nm": max(s), "mean_nm": round(sum(s) / len(s), 1), "rated_nm": r["data"].get("rated_nm")})
        return {"logs": out}

    @app.get("/api/cae/torque-logs/{mid}")
    def cae_torque_log(mid: str, u=Depends(user_of)):
        r = H.db.one("select payload from bus_message where id=%s and type='test.torque'", (mid,))
        if not r:
            raise HTTPException(404, "没有这条转矩记录")
        return r["payload"]["data"]

    @app.post("/api/cae/jobs/{jid}/fatigue")
    def cae_fatigue(jid: str, body: dict = Body(...), u=Depends(user_of)):
        """spectrum: {kind: const, max, min, freq_hz} 或 {kind: log, id} 或 {kind: joint, job, joint}（第 11 轮）
        或 {kind: csv, values, duration_s, name}（第 11 轮）。
        计算工况里有扭矩时，载荷按 N·m（扭矩总和）；没有扭矩时按“计算工况的倍数”"""
        j = mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        torques = [l for l in j["setup"]["loads"] if l["type"] == "torque"]
        ref, unit = (sum(l["value_nmm"] for l in torques) / 1000, "N·m") if torques else (1.0, "× 计算工况")
        sp = body.get("spectrum") or {}
        if sp.get("kind") == "mbd":
            # 第 12 轮：载荷谱 = 动力学算出的这根杆件受力（沿有限元所加力的方向）随时间的变化
            src = j["setup"].get("source") or {}
            fl = [l for l in j["setup"]["loads"] if l["type"] == "force"]
            if not src.get("job") or len(fl) != 1:
                raise HTTPException(400, "这次有限元不是从动力学送来的，不能用动力学受力记录")
            mbd = mine(u, call("GET", "/jobs/" + urllib.parse.quote(src["job"])).json())
            v = fl[0]["vector_n"]
            ref, unit = math.sqrt(sum(x * x for x in v)), "N（沿所加力的方向）"
            r = call("GET", "/mbd/jobs/{}/member-series".format(urllib.parse.quote(mbd["id"])),
                     params={"member": src["member"], "direction": ",".join(str(x) for x in v)}).json()
            series, secs = r["values"], r["duration_s"]
            label = "动力学受力记录：{}（{:.2f} 秒一块，重复）".format(mbd.get("title") or mbd["id"], secs)
            keys = ("surface", "size_factor", "kf", "haibach")
            return call("POST", "/jobs/{}/fatigue".format(urllib.parse.quote(jid)), json=dict(
                {k: body[k] for k in keys if k in body}, ref_load=ref, ref_unit=unit, series=series, block_seconds=secs, label=label)).json()
        if sp.get("kind") == "joint":
            # 第 11 轮 F1：载荷谱 = “运动与动力分析”算出的某个关节的驱动力矩（机器人关节轴）；按扭矩载荷线性缩放
            if not torques:
                raise HTTPException(400, "关节力矩记录只能用在有扭矩载荷的计算上")
            mbd = mine(u, call("GET", "/jobs/" + urllib.parse.quote(str(sp.get("job") or ""))).json())
            r = call("GET", "/mbd/jobs/{}/joint-series".format(urllib.parse.quote(mbd["id"])), params={"joint": sp.get("joint") or ""}).json()
            series, secs = r["values"], r["duration_s"]
            label = "关节力矩记录：{} · {}（{:.2f} 秒一块，重复）".format(mbd.get("title") or mbd["id"], sp.get("joint"), secs)
            keys = ("surface", "size_factor", "kf", "haibach")
            return call("POST", "/jobs/{}/fatigue".format(urllib.parse.quote(jid)), json=dict(
                {k: body[k] for k in keys if k in body}, ref_load=ref, ref_unit=unit, series=series, block_seconds=secs, label=label)).json()
        if sp.get("kind") == "csv":
            # 第 11 轮 F1：自己的载荷记录（CSV 一列数，单位与计算工况相同），一段为一块
            try:
                series = [float(x) for x in sp.get("values") or []]
                secs = float(sp.get("duration_s") or 0)
            except (TypeError, ValueError):
                raise HTTPException(400, "载荷记录里有不是数字的值") from None
            if len(series) < 2 or len(series) > 200000 or secs <= 0:
                raise HTTPException(400, "载荷记录要有 2～200000 个数，并写明这一段有多少秒")
            label = "上传的载荷记录 {}（{} 个点，{:g} 秒一块）".format((sp.get("name") or "")[:60], len(series), secs)
            keys = ("surface", "size_factor", "kf", "haibach")
            return call("POST", "/jobs/{}/fatigue".format(urllib.parse.quote(jid)), json=dict(
                {k: body[k] for k in keys if k in body}, ref_load=ref, ref_unit=unit, series=series, block_seconds=secs, label=label)).json()
        if sp.get("kind") == "log":
            r = H.db.one("select payload from bus_message where id=%s and type='test.torque'", (sp.get("id"),))
            if not r:
                raise HTTPException(404, "没有这条转矩记录")
            d = r["payload"]["data"]
            if not torques:
                raise HTTPException(400, "转矩记录只能用在有扭矩载荷的计算上")
            series, secs = d["samples_nm"], len(d["samples_nm"]) / d["rate_hz"]
            label = "跑合试验台转矩记录 {}（{}，{:.0f} 秒一块）".format(d["part_serial"], d.get("program") or "", secs)
        else:
            try:
                hi, lo, f = float(sp.get("max")), float(sp.get("min")), float(sp.get("freq_hz") or 1)
            except (TypeError, ValueError):
                raise HTTPException(400, "恒幅载荷要填最大、最小值") from None
            if f <= 0 or hi == lo:
                raise HTTPException(400, "最大、最小值不能相同，频率要大于 0")
            series, secs = [hi, lo], 1 / f
            label = "恒幅：{:g} ~ {:g} {}，{:g} Hz".format(lo, hi, unit, f)
        keys = ("surface", "size_factor", "kf", "haibach")
        return call("POST", "/jobs/{}/fatigue".format(urllib.parse.quote(jid)), json=dict(
            {k: body[k] for k in keys if k in body}, ref_load=ref, ref_unit=unit, series=series, block_seconds=secs, label=label)).json()

    @app.post("/api/cae/jobs/{jid}/modal")
    def cae_modal(jid: str, u=Depends(user_of)):
        """固有频率（第 11 轮 F2）：前几阶固有频率和相当转速，高速轴看临界转速"""
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        return call("POST", "/jobs/{}/modal".format(urllib.parse.quote(jid)), timeout=420).json()

    @app.get("/api/cae/jobs/{jid}/surface.bin")
    def cae_surface(jid: str, u=Depends(user_of)):
        mine(u, call("GET", "/jobs/" + urllib.parse.quote(jid)).json())
        r = call("GET", "/jobs/{}/surface.bin".format(urllib.parse.quote(jid)))
        return Response(r.content, media_type="application/octet-stream", headers={"Cache-Control": "max-age=86400"})
