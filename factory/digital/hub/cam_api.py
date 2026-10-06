# -*- coding: utf-8 -*-
"""数控编程（第 13 轮）：枢纽这边取工艺规程、设计参数和零件 STEP，排成“编程单”，交给 cae 计算服务生成程序、仿真、检查。

工艺规程从哪来（依次）：最新生效的工艺规程 → 教材样例工艺规程（std/<物料>_process.yaml，还没有生效的工艺规程时）→ 工厂数据的现行工艺。
只用工艺规程模块的后台数据，不改它的界面（C8）。
"""
import os
import urllib.parse

import yaml
from fastapi import Body, Depends, HTTPException
from fastapi.responses import Response

from hub.cae_api import FACTORY_ID, call

STD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "std")


def plan_for(db, mode, item):
    """→ (工艺规程 dict, 出处文字, 版本号)"""
    from hub import process
    try:
        r = db.one("select plan, revision from process_submission where mode=%s and item=%s and status='approved' "
                   "order by revision desc limit 1", (mode, item))
    except Exception:  # noqa: BLE001 —— 旧库没有这张表
        r = None
    if r:
        return dict(r["plan"]), "生效的工艺规程第 {} 版".format(r["revision"]), r["revision"]
    p = os.path.join(STD, "{}_process.yaml".format(item))
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f), "教材样例工艺规程（本厂还没有生效的工艺规程）", 0
    try:
        return process.factory_plan(item), "工厂数据的现行工艺（没有切削参数，按默认值编）", 0
    except Exception:  # noqa: BLE001
        return None, "", 0


def shaft_params(db, mode):
    """SH-301 现行设计参数：最近批准的提交 → 最近发布消息 → 默认（第 1 版）"""
    from hub import design as D
    try:
        r = db.one("select params from design_submission where mode=%s and item='SH-301' and status='approved' and params is not null "
                   "order by decided_at desc limit 1", (mode,))
    except Exception:  # noqa: BLE001
        r = None
    if r and r["params"]:
        return D.normalize(r["params"])
    for m in db.messages(["design.release"], mode=mode, order="desc", limit=200):
        if m["data"].get("item") == "SH-301" and m["data"].get("params"):
            return D.normalize(m["data"]["params"])
    return D.normalize(D.defaults())


def op_kind(op):
    from cae import cam_post
    m = cam_post.machine_of(op.get("workstation"))
    if not m:
        return None, "这道工序不在数控机床上"
    kind = cam_post.MACHINES[m]["kind"]
    name = op.get("operation", "")
    if kind == "lathe":
        return "turn", ""
    if "键槽" in name or "Keyway" in name:
        return "slot", ""
    return "mill25", ""


def mount(app, H, user_of, who, uid_of, is_teacher, ai_quota=None):
    from hub import plm

    def mine(u, j):
        if j.get("factory") != FACTORY_ID or j.get("kind") != "cam":
            raise HTTPException(404, "没有这个编程记录")
        if is_teacher(u) or str(j.get("owner")) == uid_of(u):
            return j
        raise HTTPException(403, "这是别人的编程记录")

    @app.get("/api/cam/machines")
    def cam_machines(u=Depends(user_of)):
        return call("GET", "/cam/machines").json()

    @app.get("/api/cam/parts")
    def cam_parts(u=Depends(user_of)):
        from cae.cam_geom import EXAMPLES
        items = []
        for i in plm.items_with_step(H.db, u["mode"]):
            plan, src, _ = plan_for(H.db, u["mode"], i)
            items.append(dict(plm.item_info(i) or {"item": i}, item=i, has_plan=bool(plan), plan_source=src))
        return {"items": items, "examples": [{"id": k, "name": v} for k, v in EXAMPLES.items()]}

    @app.get("/api/cam/ops")
    def cam_ops(item: str, u=Depends(user_of)):
        plan, src, rev = plan_for(H.db, u["mode"], item)
        if not plan:
            raise HTTPException(404, "{} 没有工艺规程".format(item))
        ops = []
        for o in plan.get("operations", []):
            k, why = op_kind(o)
            if k == "slot" and item != "SH-301":
                k, why = None, "键槽编程目前只支持网页设计台的输出轴 SH-301"
            ops.append({"seq": o["seq"], "operation": o["operation"], "workstation": o.get("workstation"), "minutes": o.get("minutes"),
                        "cut": o.get("cut"), "cam": k, "why": why})
        return {"item": item, "plan_source": src, "plan_revision": rev, "ops": ops}

    def _design_profile(item, mode):
        from cae import cam
        if item == "SH-301":
            p = shaft_params(H.db, mode)
            return cam.design_profile(p["segments"], p["chamfer"]), p, "网页设计台现行参数"
        step = plm.current_step(H.db, mode, item)
        if not step:
            raise HTTPException(404, "{} 还没有发布过三维模型（STEP）".format(item))
        g = call("POST", "/geometry", content=step, headers={"content-type": "application/step"}).json()
        r = call("POST", "/cam/recognize", json={"sha": g["sha"]}).json()
        if r["turn"].get("error"):
            raise HTTPException(422, "认不出回转轮廓：" + r["turn"]["error"])
        return [tuple(x) for x in r["turn"]["profile"]], None, "从现行 STEP 识别的回转轮廓"

    @app.post("/api/cam/spec")
    def cam_spec(body: dict = Body(...), u=Depends(user_of)):
        """工艺规程的一道工序 → 编程单"""
        from cae import cam_job as J
        item, seq = body.get("item"), body.get("seq")
        plan, src, prev = plan_for(H.db, u["mode"], item)
        if not plan:
            raise HTTPException(404, "{} 没有工艺规程".format(item))
        op = next((o for o in plan["operations"] if str(o["seq"]) == str(seq)), None)
        if not op:
            raise HTTPException(404, "没有工序 {}".format(seq))
        k, why = op_kind(op)
        rev = plm.current_revision(H.db, u["mode"], item)
        try:
            if k == "turn":
                design, _, dsrc = _design_profile(item, u["mode"])
                spec = J.plan_turn(plan, seq, design, rev)
                spec.setdefault("sources", {})["design"] = dsrc
            elif k == "slot":
                if item != "SH-301":
                    raise HTTPException(400, "键槽编程目前只支持 SH-301")
                spec = J.plan_slot(plan, seq, shaft_params(H.db, u["mode"]), rev)
                spec.setdefault("sources", {})["design"] = "网页设计台现行参数"
            elif k == "mill25":
                step = plm.current_step(H.db, u["mode"], item)
                if not step:
                    raise HTTPException(404, "{} 还没有发布过三维模型（STEP）".format(item))
                g = call("POST", "/geometry", content=step, headers={"content-type": "application/step"}).json()
                r = call("POST", "/cam/recognize", json={"sha": g["sha"]}).json()
                if r["mill"].get("error"):
                    raise HTTPException(422, "认不出铣削特征：" + r["mill"]["error"])
                from cae import cam_post
                spec = J.plan_mill(r["mill"], cam_post.machine_of(op.get("workstation")), plan.get("material", "45"), 2.0, item)
                spec["op"] = {"seq": int(op["seq"]), "name": op["operation"], "minutes": op.get("minutes"), "content": op.get("content", "")}
                spec["revision"] = rev
            else:
                raise HTTPException(400, why or "这道工序不需要数控编程")
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        spec["plan_source"] = src
        spec["plan_revision"] = prev
        return spec

    @app.post("/api/cam/spec/geometry")
    def cam_spec_geometry(body: dict = Body(...), u=Depends(user_of)):
        """读入的 STEP（上传或示例）→ 编程单。kind = mill（2.5 轴铣）或 turn（粗车 + 精车两道，选 seq 10 / 20）"""
        from cae import cam_job as J
        sha = body.get("sha")
        r = call("POST", "/cam/recognize", json={"sha": sha}).json()
        kind = body.get("kind") or ("turn" if not r["turn"].get("error") else "mill")
        name = body.get("name") or "零件"
        try:
            if kind == "turn":
                if r["turn"].get("error"):
                    raise HTTPException(422, "认不出回转轮廓：" + r["turn"]["error"])
                design = [tuple(x) for x in r["turn"]["profile"]]
                plan = J.generic_turn_plan(design, name, body.get("stock_d"))
                spec = J.plan_turn(plan, int(body.get("seq") or 10), design)
                spec["plan_source"] = "没有工艺规程：按“粗车留 0.5 → 精车”两道工序、默认切削参数"
            else:
                if r["mill"].get("error"):
                    raise HTTPException(422, "认不出铣削特征：" + r["mill"]["error"])
                spec = J.plan_mill(r["mill"], body.get("machine") or "VMC-01", body.get("material") or "45",
                                   float(body.get("stock_margin", 2.0)), name)
                spec["plan_source"] = "没有工艺规程：按识别出的特征排工步、默认切削参数"
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        spec["recognized"] = {"turn": not r["turn"].get("error"), "mill": not r["mill"].get("error")}
        return spec

    @app.post("/api/cam/ai-setup")
    def cam_ai_setup(body: dict = Body(...), u=Depends(user_of)):
        """一句话编程：只改编程单（返回修改清单，网页写回表格，人确认后才生成）"""
        from hub import cam_ai
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)
        try:
            return cam_ai.setup(H.ai.llm if H.ai else None, body.get("text"), body.get("spec") or {})
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/cam/jobs/{jid}/explain")
    def cam_explain(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        """逐段讲解 G 代码、指出风险"""
        from hub import cam_ai
        j = mine(u, call("GET", "/jobs/{}".format(jid)).json())
        k = int(body.get("k") or 0)
        if j["status"] != "done" or not 0 <= k < len(j.get("programs") or []):
            raise HTTPException(404, "没有这个程序")
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)
        nc = call("GET", "/cam/jobs/{}/{}.nc".format(jid, k)).text
        return cam_ai.explain(H.ai.llm if H.ai else None, j, k, nc)

    @app.post("/api/cam/examples/{key}")
    def cam_example(key: str, u=Depends(user_of)):
        from cae.cam_geom import EXAMPLES, example_step
        if key not in EXAMPLES:
            raise HTTPException(404, "没有这个示例")
        g = call("POST", "/geometry", content=example_step(key), headers={"content-type": "application/step"}).json()
        return {"sha": g["sha"], "name": key, "title": EXAMPLES[key], "model_url": "/api/cae/geometry/{}/model.glb".format(g["sha"])}

    @app.post("/api/cam/jobs")
    def cam_submit(body: dict = Body(...), u=Depends(user_of)):
        spec = body.get("spec") or {}
        return call("POST", "/cam/jobs", json={"spec": spec, "title": (body.get("title") or "")[:80],
                                               "owner": uid_of(u), "owner_name": who(u), "factory": FACTORY_ID}).json()

    @app.get("/api/cam/jobs")
    def cam_jobs(u=Depends(user_of)):
        params = {"factory": FACTORY_ID, "limit": 100, "kind": "cam"}
        if not is_teacher(u):
            params["owner"] = uid_of(u)
        js = call("GET", "/jobs", params=params).json()["jobs"]
        return {"jobs": [{k: j.get(k) for k in ("id", "title", "item", "owner_name", "created", "status", "stats", "error", "compare")}
                         | {"op": (j.get("spec") or {}).get("op"), "kind": (j.get("spec") or {}).get("kind")} for j in js]}

    @app.get("/api/cam/jobs/{jid}")
    def cam_job(jid: str, u=Depends(user_of)):
        return mine(u, call("GET", "/jobs/{}".format(jid)).json())

    @app.get("/api/cam/jobs/{jid}/{k}.nc")
    def cam_nc(jid: str, k: int, u=Depends(user_of)):
        j = mine(u, call("GET", "/jobs/{}".format(jid)).json())
        txt = call("GET", "/cam/jobs/{}/{}.nc".format(jid, k)).text
        p = (j.get("programs") or [{}] * (k + 1))[k] if k < len(j.get("programs") or []) else {}
        name = "O{:04d}-{}.nc".format(int(p.get("number") or 1), j.get("item") or "program")
        return Response(txt, media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": "inline; filename*=UTF-8''" + urllib.parse.quote(name)})

    @app.get("/api/cam/jobs/{jid}/h{k}.bin")
    def cam_height(jid: str, k: int, u=Depends(user_of)):
        mine(u, call("GET", "/jobs/{}".format(jid)).json())
        return Response(call("GET", "/cam/jobs/{}/h{}.bin".format(jid, k)).content, media_type="application/octet-stream")


# ---------------------------------------------------------------- 下发（C8）：程序挂到工艺规程的工序上，走工艺规程审批
CUT_KEYS = {"vc": "vc_m_min", "f": "f_mm_r", "ap": "ap_mm"}


def attach_to_plan(db, store, mode, job, nc_texts):
    """把一次编程的程序挂到工艺规程这道工序上，返回 (新的工艺规程, 提交说明)。
    切削参数改过的，写回这道工序的 cut（程序和工艺规程保持一致），说明里列出改了什么。"""
    spec = job["spec"]
    op_ref = spec.get("op") or {}
    item = spec.get("item")
    plan, src, prev = plan_for(db, mode, item)
    if not plan:
        raise ValueError("{} 没有工艺规程".format(item))
    plan = __import__("copy").deepcopy(plan)
    op = next((o for o in plan.get("operations", []) if int(o["seq"]) == int(op_ref.get("seq", -1))), None)
    if not op:
        raise ValueError("工艺规程里没有工序 {}".format(op_ref.get("seq")))
    from cae import cam_post
    m = cam_post.machine_of(op.get("workstation")) or spec["machine"]
    progs = []
    for k, (p, text) in enumerate(zip(job["programs"], nc_texts)):
        f = store(db, "{}-OP{}-O{:04d}.nc".format(item, op["seq"], int(p["number"])), "text/plain", text.encode("utf-8"))
        progs.append({"number": int(p["number"]), "setup": p.get("setup"), "title": p.get("title"), "url": f["url"], "sha256": f["sha256"],
                      "machine": m, "est_time_s": round(p["time"]["total_s"], 1), "lines": p.get("lines"), "cam_job": job["id"],
                      "design_revision": spec.get("revision")})
    op["programs"] = progs
    notes = ["数控程序：工序 {} {}，{} 个程序（{}），合计 {} 分（工艺规程工时 {} 分）".format(
        op["seq"], op["operation"], len(progs), "、".join("O{:04d}".format(p["number"]) for p in progs),
        (job.get("compare") or {}).get("program_minutes"), op.get("minutes"))]
    cut = op.get("cut")
    if spec.get("kind") == "turn" and cut:
        diff = []
        for k, key in CUT_KEYS.items():
            v = spec["cut"].get(k)
            if key in cut and v is not None and abs(float(cut[key]) - float(v)) > 1e-9:
                diff.append("{} {} → {}".format(key, cut[key], v))
                cut[key] = v
        if diff:
            notes.append("编程时改了切削参数，已写回工序：" + "，".join(diff))
    if src.startswith("教材样例"):
        notes.append("以教材样例工艺规程为底稿（本厂还没有生效的工艺规程）")
    return plan, "；".join(notes)


def release_programs(db, emit, sub):
    """工艺规程批准生效后：每个挂了程序的工序，每个程序发一条 design.gcode（ERPNext 附到物料上；MES 派工时随工序发给机床；3D 车间回放）"""
    from hub import plm
    if sub.get("status") != "approved":
        return 0
    n = 0
    item = sub["item"]
    for o in sub["plan"].get("operations", []):
        for p in o.get("programs") or []:
            emit("wq/gearbox/design/{}/gcode".format(item.lower()), "design.gcode", {
                "item": item, "revision": int(p.get("design_revision") or 1), "operation": o["operation"],
                "machine": plm.machine_for(o["operation"]) or str(p["machine"]).lower(), "gcode_ref": p["url"], "gcode_url": p["url"], "sha256": p.get("sha256"),
                "est_time_s": p.get("est_time_s"), "program": p["number"], "setup": p.get("setup"),
                "process_revision": sub.get("revision"), "source": "数控编程"})
            n += 1
    return n


def mount_release(app, H, user_of, who, uid_of, is_teacher, emit_as, can_submit):
    from hub import plm, process

    @app.post("/api/cam/jobs/{jid}/submit")
    def cam_submit_plan(jid: str, body: dict = Body(default={}), u=Depends(user_of)):
        """程序挂到工艺规程工序上，提交工艺规程审批（教学、生产模式都进待审）"""
        can_submit(u)
        j = call("GET", "/jobs/{}".format(jid)).json()
        if j.get("factory") != FACTORY_ID or j.get("kind") != "cam":
            raise HTTPException(404, "没有这个编程记录")
        if not is_teacher(u) and str(j.get("owner")) != uid_of(u):
            raise HTTPException(403, "只能提交自己的程序")
        if j["status"] != "done":
            raise HTTPException(409, "程序没有生成成功")
        if not (j.get("spec") or {}).get("op"):
            raise HTTPException(400, "这次编程不是从工艺规程的工序出发的（示例或上传的零件），不能挂到工艺规程上")
        errs = [c for p in j["programs"] for c in p["checks"] if c["level"] == "error"]
        if errs:
            raise HTTPException(409, "检查还有 {} 个错误（{}），改好再提交".format(len(errs), errs[0]["text"]))
        texts = [call("GET", "/cam/jobs/{}/{}.nc".format(jid, k)).text for k in range(len(j["programs"]))]
        try:
            plan, note = attach_to_plan(H.db, plm.store, u["mode"], j, texts)
            extra = (body.get("note") or "").strip()[:200]
            s = process.submit(H.db, emit_as(u), u["mode"], who(u), uid_of(u), plan, (note + ("；" + extra if extra else ""))[:500])
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e)) from None
        call("POST", "/cam/jobs/{}/submission".format(jid), json={"submission": s["id"]})
        return {"submission": s["id"], "status": s["status"], "note": s["note"],
                "comments": s["comments"], "review": s.get("review")}
