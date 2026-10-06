# -*- coding: utf-8 -*-
"""数字孪生的网页接口（第 15 轮）"""
import hmac
import os

from fastapi import Body, Depends, Header, HTTPException

from hub import twin as TW


def mount(app, H, user_of, who, uid_of, is_teacher, ai_quota=None):

    @app.post("/api/twin/telemetry")
    def twin_device_telemetry(body: dict = Body(...), authorization: str = Header(default="")):
        """真设备接入口（T2）：现场的采集器（例如 ESP32）用 HTTPS 发一条运行摘要（格式同 twin.telemetry 的 data），
        钥匙放在 Authorization: Bearer <WQ_TWIN_DEVICE_KEY>。校验后发到总线 wq/gearbox/field/<序列号>/telemetry，和模拟器走同一条路。"""
        import wqbus
        from wqbus.topics import topic
        key = os.environ.get("WQ_TWIN_DEVICE_KEY", "")
        if not key or not hmac.compare_digest(authorization.encode(), ("Bearer " + key).encode()):
            raise HTTPException(401, "设备钥匙不对（或服务器没设 WQ_TWIN_DEVICE_KEY）")
        mode = body.pop("mode", None) or os.environ.get("WQ_MODE", "teach")
        serial = str(body.get("serial") or "")
        if not serial or "/" in serial or "+" in serial or "#" in serial or len(serial) > 40:
            raise HTTPException(422, "序列号不对")
        try:
            msg = wqbus.make("twin.telemetry", "device/" + serial, body, mode=mode, corr=serial)
        except wqbus.ValidationError as e:
            raise HTTPException(422, "数据不合规范：{}".format(e)) from None
        tp = topic("field", serial, "telemetry")
        if H.bus is not None:
            H.bus.publish_msg(tp, msg)
        H.hist.handle(tp, msg)
        return {"id": msg["id"], "topic": tp}

    @app.get("/api/twin/fleet")
    def twin_fleet(u=Depends(user_of)):
        mode = u["mode"]
        if mode in TW.FIELD_MODES:
            H.twin.touch(mode)
        c = H.twin._clock(mode)
        return TW.json_safe({"units": TW.fleet(H.db, mode), "field_today": H.twin.field_today(mode).isoformat(),
                             "clock": {"days_per_min": c["days_per_min"], "paused": c["paused"], "simulated": mode in TW.FIELD_MODES},
                             "sites": {k: {"label": v["label"], "customer": v["customer"], "note": v["note"]} for k, v in TW.F.SITES.items()}})

    @app.get("/api/twin/units/{serial}")
    def twin_unit(serial: str, u=Depends(user_of)):
        r = TW.detail(H.db, u["mode"], serial)
        if r is None:
            raise HTTPException(404, "没有这台设备的孪生")
        return TW.json_safe(r)

    @app.post("/api/twin/units/{serial}/whatif")
    def twin_whatif(serial: str, body: dict = Body(default={}), u=Depends(user_of)):
        """假如：降载、加风扇、换输出轴材料 → 剩余寿命、换油间隔、油温"""
        from twin import whatif as W
        r = H.db.one("select state, as_built from twin where serial=%s and mode=%s", (serial, u["mode"]))
        if r is None:
            raise HTTPException(404, "没有这台设备的孪生")
        load = float(body.get("load", 1.0))
        if not 0.3 <= load <= 1.5:
            raise HTTPException(400, "负载倍数要在 0.3–1.5 之间")
        mat = body.get("mat") or "45-QT"
        if mat not in W.MATS:
            raise HTTPException(400, "输出轴材料只能选 " + "、".join(W.MATS))
        logs = [x["data"] for x in reversed(H.db.q(
            "select data from twin_log where serial=%s and mode=%s order by day desc limit 30", (serial, u["mode"])))]
        if not logs:
            raise HTTPException(409, "还没有现场数据")
        fk = fan_k()
        out = W.compare(r["state"], logs, (r["as_built"] or {}).get("design"), load, bool(body.get("fan")), mat, fk["k"])
        out["fan_src"] = fk["src"]
        return TW.json_safe(out)

    def fan_k():
        """加风扇后的散热系数：本厂最近一次“WQR-105 箱体 + 换热”的流体分析（外表面平均对流 + 辐射）；没有就用教材 31"""
        from twin import whatif as W
        try:
            from hub.cae_api import FACTORY_ID, call
            from hub.cfd_api import h_rad
            for j in call("GET", "/jobs", params={"factory": FACTORY_ID, "kind": "cfd", "limit": 50}).json()["jobs"]:
                s, st = j.get("setup") or {}, j.get("stats") or {}
                if j["status"] == "done" and (s.get("example") or {}).get("key") == "housing" and s.get("heat") and st.get("h_mean"):
                    k = st["h_mean"] + h_rad(float(st.get("wall_t_c") or 70), float(st.get("air_t_c") or 25))
                    return {"k": round(k, 1), "src": "流体分析“{}”：{} m/s 时对流 {:.1f} + 辐射 {:.1f}".format(
                        j.get("title") or j["id"], st.get("velocity_ms"), st["h_mean"], k - st["h_mean"])}
        except Exception:  # noqa: BLE001
            pass
        return {"k": W.K_FAN, "src": "教材：轴端装风扇约 31–38，取 31"}

    @app.get("/api/twin/fan")
    def twin_fan(u=Depends(user_of)):
        return fan_k()

    def _detail(u, serial):
        d = TW.detail(H.db, u["mode"], serial)
        if d is None:
            raise HTTPException(404, "没有这台设备的孪生")
        return TW.json_safe(d)

    @app.post("/api/twin/units/{serial}/explain")
    def twin_explain(serial: str, u=Depends(user_of)):
        from hub import twin_ai
        d = _detail(u, serial)
        if ai_quota and H.ai and H.ai.llm.available():
            ai_quota(u)
        return twin_ai.explain(H.ai.llm if H.ai else None, d)

    @app.post("/api/twin/units/{serial}/order")
    def twin_order(serial: str, body: dict = Body(...), u=Depends(user_of)):
        """开维修单：body = {event_id?, action, preview_only?}。确认后经桥接写进 ERPNext（Issue 服务工单），报警标“已派单”"""
        from hub import twin_ai
        d = _detail(u, serial)
        action = str(body.get("action") or "")
        if action.split(":")[0] not in ("oil", "cooling", "bearing") or (action.startswith("bearing:") and action[8:] not in TW.M.BRG):
            raise HTTPException(400, "维修内容只能是换油、清洁散热、更换某个轴承")
        ev = next((e for e in d["events"] if e["id"] == body.get("event_id")), None) if body.get("event_id") else None
        pv = twin_ai.order_preview(d, ev, action)
        if body.get("preview_only"):
            return pv
        pid = H.ai.propose("twin_service_order", pv, u["mode"], u["name"], pv["subject"], source="twin/" + who(u), role=u["role"])
        H.ai.decide(pid, u["name"], True, None, role=u["role"])
        H.db.x("insert into twin_event (serial, mode, day, kind, level, title, status, detail) values (%s,%s,%s,'order','info',%s,'ordered',%s)",
               (serial, u["mode"], d["state"].get("last_day"), "维修单：" + pv["what"], TW.Jsonb(dict(pv, proposal_id=pid, by=who(u)))))
        if ev:
            H.db.x("update twin_event set status='ordered' where id=%s", (ev["id"],))
        return {"proposal_id": pid, "preview": pv}

    @app.post("/api/twin/units/{serial}/done")
    def twin_done(serial: str, body: dict = Body(...), u=Depends(user_of)):
        """维修完成：寿命复位、现场故障消失；ERPNext 的服务工单改为已解决"""
        o = H.db.one("select * from twin_event where id=%s and serial=%s and mode=%s and kind='order'", (body.get("order_id"), serial, u["mode"]))
        if o is None:
            raise HTTPException(404, "没有这张维修单")
        if o["status"] == "done":
            raise HTTPException(409, "这张维修单已经完成")
        pv = o["detail"]
        H.twin.repair(u["mode"], serial, pv["action"])
        note = (body.get("note") or "").strip()[:500]
        H.db.x("update twin_event set status='done', detail=detail || %s where id=%s",
               (TW.Jsonb({"done_by": who(u), "note": note}), o["id"]))
        p = H.db.one("select result from ai_proposal where proposal_id=%s", (pv.get("proposal_id"),))
        res = (p or {}).get("result") or {}
        if isinstance(res, str):
            res = __import__("json").loads(res)
        issue = next((c[1] for c in res.get("created", []) if c[0] == "Issue"), None)
        if issue:
            pid = H.ai.propose("twin_service_done", {"issue": issue, "serial": serial, "what": pv["what"], "note": note},
                               u["mode"], u["name"], "完成维修单 " + issue, source="twin/" + who(u), role=u["role"])
            H.ai.decide(pid, u["name"], True, None, role=u["role"])
        return {"ok": True, "issue": issue}

    @app.get("/api/twin/feedback")
    def twin_feedback(u=Depends(user_of)):
        """机队数据反馈设计：每类客户的实际载荷 vs 设计假设、寿命最短的部位"""
        from hub import twin_ai
        rows = []
        for site, info in TW.F.SITES.items():
            units = []
            for r in H.db.q("select serial from twin where mode=%s and site=%s", (u["mode"], site)):
                units.append([x["data"] for x in H.db.q(
                    "select data from twin_log where serial=%s and mode=%s and day > (select max(day) from twin_log where serial=%s and mode=%s) - 365",
                    (r["serial"], u["mode"], r["serial"], u["mode"]))])
            if units:
                rows.append((site, info["label"], units))
        return TW.json_safe(twin_ai.feedback(rows))

    @app.get("/api/twin/robots")
    def twin_robots(u=Depends(user_of)):
        return TW.json_safe({"robots": TW.robots(H.db, u["mode"])})

    @app.post("/api/twin/robots")
    def twin_robot_add(body: dict = Body(...), u=Depends(user_of)):
        """机械臂关节孪生：从“运动与动力分析”的一次计算（一个搬运循环）建，按每天运行小时累计谐波减速器寿命"""
        import urllib.parse
        from hub.cae_api import call
        jid = str(body.get("mbd_job") or "")
        h = float(body.get("hours_per_day") or 16)
        if not 1 <= h <= 24:
            raise HTTPException(400, "每天运行 1–24 小时")
        j = call("GET", "/jobs/" + urllib.parse.quote(jid)).json()
        if j.get("kind") != "mbd" or (not is_teacher(u) and str(j.get("owner")) != uid_of(u)):
            raise HTTPException(404, "没有这次动力学计算")
        life = call("GET", "/mbd/jobs/{}/reducer-life".format(urllib.parse.quote(jid))).json()
        name = (body.get("name") or j.get("title") or "机械臂")[:60]
        rid = H.twin.add_robot(u["mode"], name, life, h, who(u))
        return {"id": rid, "life": life}

    @app.get("/api/twin/faults")
    def twin_faults(u=Depends(user_of)):
        """老师控制台：可以制造的故障，以及每台现在有哪些（学生看不到）"""
        if not is_teacher(u):
            raise HTTPException(403, "只有老师能看")
        rows = H.db.q("select serial, site, faults from field_unit where mode=%s order by serial", (u["mode"],))
        return TW.json_safe({"catalog": TW.F.FAULTS, "units": rows})

    @app.post("/api/twin/units/{serial}/fault")
    def twin_fault(serial: str, body: dict = Body(...), u=Depends(user_of)):
        if not is_teacher(u):
            raise HTTPException(403, "只有老师能制造故障")
        if u["mode"] not in TW.FIELD_MODES:
            raise HTTPException(409, "这个模式下没有客户现场模拟器")
        try:
            return {"faults": H.twin.set_fault(u["mode"], serial, body.get("kind"))}
        except KeyError:
            raise HTTPException(404, "这台不在模拟的客户现场") from None
        except ValueError as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/twin/clock")
    def twin_clock(body: dict = Body(...), u=Depends(user_of)):
        """老师：现场时钟快慢（每分钟多少个现场日，0 = 暂停）"""
        if not is_teacher(u):
            raise HTTPException(403, "只有老师能调现场时钟")
        mode = u["mode"]
        if mode not in TW.FIELD_MODES:
            raise HTTPException(409, "这个模式下没有客户现场模拟器（等真设备的数据）")
        v = float(body.get("days_per_min", 1))
        if not 0 <= v <= 30:
            raise HTTPException(400, "每分钟 0–30 个现场日")
        if v == 0:
            today = H.twin.field_today(mode)
            H.db.x("update field_clock set paused=true, days_per_min=0, anchor_day=%s where mode=%s", (today, mode))
        else:
            H.twin.set_rate(mode, v)
        return {"ok": True, "field_today": H.twin.field_today(mode).isoformat()}
