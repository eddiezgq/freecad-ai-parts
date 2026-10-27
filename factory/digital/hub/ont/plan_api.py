# -*- coding: utf-8 -*-
"""第 17 轮 C 期接口：班次、快照、推演、场景、方案（预案推演）、动作、时间回看。"""
import datetime as dt

from fastapi import Body, Depends, HTTPException
from psycopg.types.json import Jsonb

from hub.ont import actions as AC
from hub.ont import plan as P
from hub.ont import playbook as PB


SERVICE_RULES = ("C1", "C3", "C4", "V1", "V2")
EHS_RULES = ("E1", "E3")
MAINT_RULES = ("M2", "M3", "M4", "M5")
PEOPLE_RULES = ("H1", "H2")
SUPPLY_RULES = ("W3", "W4", "W6")
ENERGY_RULES = ("N1", "N2", "N3", "N4", "N5", "N6")
FINANCE_RULES = ("F2", "F3", "F4", "F5", "F6", "F7")


def mount(app, H, user_of, who):
    def snaps():
        return H.plan_snaps

    def is_boss(u):
        return bool(u.get("teacher")) and u.get("role") == "manager"

    def ctx_for(u, snap):
        return P.context(H.db, u["mode"], dt.datetime.fromisoformat(snap["factory_now"]))

    def snap_of(u, sid=None):
        if sid:
            r = H.db.one("select id, state, exact from sim_snapshot where id=%s and mode=%s", (sid, u["mode"]))
            if r is None:
                raise HTTPException(404, "没有这张快照")
            return r["id"], r["state"], r["exact"]
        return snaps().take(u["mode"])

    # ---------------------------------------------------------------- 班次
    @app.get("/api/ont/shifts")
    def shifts(u=Depends(user_of)):
        cal = P.calendar(H.db, u["mode"])
        return {"calendar": cal.to_dict(), "can_edit": is_boss(u), "max_overtime_min": 240}

    @app.post("/api/ont/shifts")
    def shifts_set(body: dict = Body(...), u=Depends(user_of)):
        """切换“按班次 / 24 小时连续”；加班走动作（要审批）"""
        if not is_boss(u):
            raise HTTPException(403, "只有厂长（教师）可以改班次模式")
        cal = P.calendar(H.db, u["mode"])
        mode = body.get("mode")
        if mode not in ("shift", "continuous"):
            raise HTTPException(400, "模式只能是 shift（按班次）或 continuous（24 小时连续）")
        cal.mode = mode
        P.save_calendar(H.db, u["mode"], cal, who(u))
        P.push_calendar(H.mes, H.db, u["mode"], who(u))
        return shifts(u)

    # ---------------------------------------------------------------- 快照与推演
    @app.post("/api/ont/snapshot")
    def snapshot(u=Depends(user_of)):
        sid, st, exact = snaps().take(u["mode"])
        return {"id": sid, "exact": exact, "factory_now": st["factory_now"]}

    @app.get("/api/ont/snapshots")
    def snapshots(hours: int = 24 * 7, u=Depends(user_of)):
        rows = H.db.q("select id, ts, exact, state->>'factory_now' as fnow from sim_snapshot where mode=%s and ts > now() - make_interval(hours => %s) "
                      "order by ts desc limit 1000", (u["mode"], max(1, min(int(hours), 24 * 30))))
        return {"snapshots": [{"id": r["id"], "ts": r["ts"].isoformat(), "exact": r["exact"], "factory_now": r["fnow"]} for r in rows]}

    @app.post("/api/ont/simulate")
    def simulate(body: dict = Body(default={}), u=Depends(user_of)):
        sid, st, exact = snap_of(u, body.get("snapshot_id"))
        try:
            r = P.simulate(st, body.get("changes") or [], ctx_for(u, st))
        except P.PlanError as e:
            raise HTTPException(400, str(e))
        from sim.engine import OP_UNITS
        brief = {"machines": {k: {"state": m["state"], "jobs": m["jobs"]} for k, m in st["machines"].items()},
                 "wos": {k: {"ops": w["ops"]} for k, w in st["wos"].items()}, "op_units": OP_UNITS}
        return dict(r, snapshot_id=sid, exact=exact, snapshot_state=brief)

    @app.get("/api/ont/scenarios")
    def scenarios(anomaly_id: int = 0, u=Depends(user_of)):
        w, a = ["mode=%s"], [u["mode"]]
        if anomaly_id:
            w.append("anomaly_id=%s")
            a.append(anomaly_id)
        rows = H.db.q("select id, title, snapshot_id, changes, created_by, anomaly_id, created_at, result->'cost_total' as cost "
                      "from scenario where {} order by id desc limit 200".format(" and ".join(w)), a)
        return {"scenarios": [dict(r, created_at=r["created_at"].isoformat()) for r in rows]}

    @app.post("/api/ont/scenarios")
    def scenario_save(body: dict = Body(...), u=Depends(user_of)):
        title = (body.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "给场景起个名字")
        sid, st, exact = snap_of(u, body.get("snapshot_id"))
        try:
            r = P.simulate(st, body.get("changes") or [], ctx_for(u, st))
        except P.PlanError as e:
            raise HTTPException(400, str(e))
        row = H.db.one("insert into scenario (mode, title, snapshot_id, changes, result, created_by, anomaly_id) values (%s,%s,%s,%s,%s,%s,%s) "
                       "returning id", (u["mode"], title, sid, Jsonb(body.get("changes") or []), Jsonb(r), u.get("name"), body.get("anomaly_id")))
        return {"id": row["id"], "result": r, "snapshot_id": sid}

    @app.get("/api/ont/scenarios/{sc}")
    def scenario_get(sc: int, u=Depends(user_of)):
        r = H.db.one("select * from scenario where id=%s and mode=%s", (sc, u["mode"]))
        if r is None:
            raise HTTPException(404, "没有这个场景")
        return dict(r, created_at=r["created_at"].isoformat())

    # ---------------------------------------------------------------- 异常的候选方案（预案推演）
    def compute_options(u, aid, snapshot_id=0):
        """异常的候选方案与推荐（第 19 轮：抽成函数，实验 23 评“和中枢推荐比”也用它）→ (结果, 快照号, 快照, 是否精确)"""
        a = H.db.one("select * from anomaly where id=%s and mode=%s", (aid, u["mode"]))
        if a is None:
            raise HTTPException(404, "没有这个异常")
        if a["rule"] in SERVICE_RULES:          # 第 18 轮 E1：投诉、现场报警的处理方案按派工排班估算，不进车间仿真
            from hub import service as SV
            r = SV.anomaly_options(H.db, u["mode"], a)
            sid, st, exact = None, {"factory_now": SV.field_today(H.db, u["mode"]).isoformat(), "calendar": {}}, True
        elif a["rule"] in MAINT_RULES:         # 第 18 轮 E3：保养时机（车间推演 + 失效风险）、点检异常、等备件
            from hub import maint as MT
            if a["rule"] == "M3":
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = MT.inspection_options(H.db, u["mode"], a)
            elif a["rule"] == "M5":
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = MT.parts_options(H.db, u["mode"], a)
            else:
                sid, st, exact = snap_of(u, snapshot_id or None)
                try:
                    r = MT.options(H.db, u["mode"], a, st, ctx_for(u, st))
                except P.PlanError as e:
                    raise HTTPException(400, str(e))
            r["maint"] = True
        elif a["rule"] in SUPPLY_RULES:       # 第 18 轮 E5：来料不合格（推演到料日）、准时率低 / 单一来源（开发备选）
            from hub import supply as SP
            if a["rule"] == "W3":
                sid, st, exact = snap_of(u, snapshot_id or None)
                try:
                    r = SP.options(H.db, u["mode"], a, st, ctx_for(u, st))
                except P.PlanError as e:
                    raise HTTPException(400, str(e))
            else:
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = SP.alt_options(H.db, u["mode"], a)
            r["supply"] = True
        elif a["rule"] in FINANCE_RULES:      # 第 18 轮 E7：应收逾期、信用、现金、预算（不进车间推演，看现金流）；毛利、指标给分解
            from hub import finance as FN
            sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
            r = FN.options(H.db, u["mode"], a)
            r["finance"] = a["rule"]
        elif a["rule"] in ENERGY_RULES:       # 第 18 轮 E6：空转（自动待机）、峰时 / 需量（错峰）用车间推演；单耗突增、漏气、环境超限给整改
            from hub import energy as EN
            if a["rule"] in ("N2", "N3", "N5"):
                sid, st, exact = snap_of(u, snapshot_id or None)
                try:
                    r = EN.options(H.db, u["mode"], a, st, ctx_for(u, st))
                except P.PlanError as e:
                    raise HTTPException(400, str(e))
            else:
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = EN.fix_options(H.db, u["mode"], a)
            r["energy"] = a["rule"]
        elif a["rule"] in PEOPLE_RULES:       # 第 18 轮 E4：排班缺口（车间推演）、单点依赖（技能培训）
            from hub import people as PE
            if a["rule"] == "H1":
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = PE.training_options(H.db, u["mode"], a)
            else:
                sid, st, exact = snap_of(u, snapshot_id or None)
                try:
                    r = PE.options(H.db, u["mode"], a, st, ctx_for(u, st))
                except P.PlanError as e:
                    raise HTTPException(400, str(e))
            r["people"] = True
        elif a["rule"] in EHS_RULES:          # 第 18 轮 E2：重大隐患（车间推演）、作业许可缺资质（复训 / 换人）
            from hub import ehs as EH
            if a["rule"] == "E3":
                sid, st, exact = None, {"factory_now": dt.datetime.now(dt.timezone.utc).isoformat(), "calendar": {}}, True
                r = EH.permit_options(H.db, u["mode"], a)
            else:
                sid, st, exact = snap_of(u, snapshot_id or None)
                try:
                    r = EH.options(H.db, u["mode"], a, st, ctx_for(u, st))
                except P.PlanError as e:
                    raise HTTPException(400, str(e))
            r["ehs"] = True
        else:
            sid, st, exact = snap_of(u, snapshot_id or None)
            try:
                r = PB.evaluate(a, st, ctx_for(u, st))
            except P.PlanError as e:
                raise HTTPException(400, str(e))
        return r, sid, st, exact

    H.anomaly_options = compute_options

    @app.get("/api/ont/anomalies/{aid}/options")
    def options(aid: int, snapshot_id: int = 0, u=Depends(user_of)):
        r, sid, st, exact = compute_options(u, aid, snapshot_id)
        locked = H.compare_locked(u, aid) if hasattr(H, "compare_locked") else False
        if locked:                          # 实验 15 比对模式：学生提交自己的分析前，不显示建议和推荐理由
            r = dict(r, reason=None, recommended=None, options=[dict(o, recommended=False) for o in r["options"]], locked=True)
        elif r.get("reason") and u["mode"] != "teach" and H.ai is not None and H.ai.llm.available():
            from hub.ont import narrate as NR
            facts = [{"方案": o["key"] + " " + o["label"], "订单": o["result"]["sales_orders"], "多花": o["result"]["cost_total"],
                      "加班分钟": o["result"]["overtime_min"]} for o in r["options"]]
            p = NR.polish(H.ai.llm, r["reason"], facts, "把推荐理由改写成给厂长看的两三句话：推荐哪个、为什么、代价是什么")
            r = dict(r, reason=p["text"], reason_by=p["by"])
        return dict(r, snapshot_id=sid, exact=exact, factory_now=st["factory_now"], shift_mode=(st.get("calendar") or {}).get("mode"),
                    can_initiate=AC.can_initiate(u, "dunning") if r.get("finance") else
                    AC.can_initiate(u, {"N1": "repair_order", "N4": "rectify_order", "N6": "rectify_order"}.get(r.get("energy"), "energy_setting")) if r.get("energy") else
                    AC.can_initiate(u, "service_batch" if r.get("service") else ("lockout" if r.get("ehs") else ("pm_order" if r.get("maint") else
                                                                                                                       ("shift_swap" if r.get("people") else ("purchase_order" if r.get("supply") else "reassign"))))))

    # ---------------------------------------------------------------- 动作
    @app.get("/api/ont/actions")
    def actions(box: str = "all", u=Depends(user_of)):
        rows = H.db.q("select * from action where mode=%s order by id desc limit 300", (u["mode"],))
        rows = [AC.sync(H.db, a) for a in rows]
        out = []
        for a in rows:
            ok, why = AC.can_approve(u, a) if a["status"] == "submitted" else (False, "")
            r = dict(AC.row(a), can_approve=ok, why_not=why, mine=a["initiator"] == u.get("name"))
            if box == "mine" and a["initiator"] != u.get("name"):
                continue
            if box == "todo" and not ok:
                continue
            out.append(r)
        return {"actions": out, "statuses": AC.STATUS, "types": {k: v["label"] for k, v in AC.TYPES.items()},
                "can_initiate": AC.can_initiate(u)}

    @app.get("/api/ont/actions/{aid}")
    def action_get(aid: int, u=Depends(user_of)):
        a = AC.get(H.db, aid)
        if a is None or a["mode"] != u["mode"]:
            raise HTTPException(404, "没有这个动作")
        a = AC.sync(H.db, a)
        ok, why = AC.can_approve(u, a) if a["status"] == "submitted" else (False, "")
        return dict(AC.row(a), can_approve=ok, why_not=why, mine=a["initiator"] == u.get("name"), log=AC.notes(H.db, aid))

    @app.post("/api/ont/actions")
    def action_create(body: dict = Body(...), u=Depends(user_of)):
        """{changes: [...]（一种动作一条，推演里的改动原样提交）, scenario_id?, anomaly_id?, snapshot_id?, submit: true}"""
        changes = body.get("changes") or []
        if not changes:
            raise HTTPException(400, "没有要做的动作")
        ids = []
        try:
            if all(AC.TYPES.get(c.get("type"), {}).get("service") for c in changes):
                tr = AC.service_trial(H.db, u["mode"], changes)           # 服务类：按排班估算，不用车间快照
            elif all(AC.no_sim(c.get("type")) for c in changes):
                tr = AC.plain_trial(changes)                               # 整改工单、解锁、培训：不用推演
            else:
                sid, st, exact = snap_of(u, body.get("snapshot_id"))
                if H.db.one("select 1 as x from sim_snapshot where id=%s and ts < now() - interval '2 hours'", (sid,)):
                    raise AC.ActionError("这是过去的快照，只能做复盘推演，不能变成动作；请用最新快照")
                tr = dict(AC.trial(H.db, snaps(), u["mode"], changes, st), snapshot_id=sid)
            for c in changes:
                t = c.get("type")
                if t in ("insert_order", "breakdown"):
                    continue                    # 插单、假设停机只在推演里用；真正下达工单走“订单与计划”
                aid = AC.create(H.db, u["mode"], u, t, c, body.get("scenario_id"), body.get("anomaly_id"), tr)
                if body.get("submit", True):
                    AC.submit(H.db, aid, u, tr)
                ids.append(aid)
        except AC.ActionError as e:
            raise HTTPException(400, str(e))
        except P.PlanError as e:
            raise HTTPException(400, str(e))
        if body.get("anomaly_id"):
            try:
                H.ai.detector().note(body["anomaly_id"], who(u), "action", "生成动作：{}".format("、".join("ACT-{:05d}".format(i) for i in ids)))
            except Exception:  # noqa: BLE001
                pass
        return {"ids": ids, "trial": tr}

    @app.post("/api/ont/actions/{aid}/{kind}")
    def action_do(aid: int, kind: str, body: dict = Body(default={}), u=Depends(user_of)):
        a = AC.get(H.db, aid)
        if a is None or a["mode"] != u["mode"]:
            raise HTTPException(404, "没有这个动作")
        try:
            if kind == "submit":
                if a["initiator"] != u.get("name") and not u.get("teacher"):
                    raise AC.ActionError("只有发起人可以提交")
                AC.submit(H.db, aid, u, AC.trial(H.db, snaps(), u["mode"], [a["params"]]))
            elif kind == "rerun":
                tr = AC.trial(H.db, snaps(), u["mode"], [a["params"]])
                old = a["trial"] or {}
                H.db.x("update action set trial=%s where id=%s", (Jsonb(tr), aid))
                AC.log(H.db, aid, u.get("name"), "rerun", "用最新快照重新试运行：{}{}".format(
                    AC._trial_text(tr), "（与提交时不同，请再看一下）" if AC._trial_text(old) != AC._trial_text(tr) else ""))
            elif kind == "approve":
                AC.approve(H, aid, u, who(u))
            elif kind == "reject":
                AC.reject(H.db, aid, u, body.get("text", ""))
            else:
                raise HTTPException(404, "没有这个操作")
        except AC.ActionError as e:
            raise HTTPException(400, str(e))
        except P.PlanError as e:
            raise HTTPException(400, str(e))
        return action_get(aid, u)

    # ---------------------------------------------------------------- 时间回看
    @app.get("/api/ont/history")
    def history(at: str, u=Depends(user_of)):
        """某个过去时刻：态势卡（按那时重算）、设备状态（那时最近的快照）、那时开着的异常"""
        from hub.ont import situation as SIT
        try:
            t = dt.datetime.fromisoformat(at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(400, "时刻格式不对")
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        now = dt.datetime.now(dt.timezone.utc)
        if t > now or t < now - dt.timedelta(days=7):
            raise HTTPException(400, "只能回看过去 7 天内")
        d = H.ai.detector()
        d.init()
        cards = SIT.cards(H.db, d, u["mode"], t, live=False)
        an = H.db.q("select id, rule, domain, severity, title, first_seen, closed_at from anomaly where mode=%s and first_seen <= %s "
                    "and (closed_at is null or closed_at > %s) order by severity, first_seen", (u["mode"], t, t))
        snap = H.db.one("select id, ts, exact, state from sim_snapshot where mode=%s and ts <= %s order by ts desc limit 1", (u["mode"], t))
        machines = None
        if snap:
            machines = {k: {"state": m["state"], "jobs": len(m["jobs"]), "queue": len(m["inbox"]), "busy": len(m["active"])}
                        for k, m in snap["state"]["machines"].items()}
        return dict(cards, at=t.isoformat(), anomalies=[dict(a, first_seen=a["first_seen"].isoformat(),
                                                             closed_at=a["closed_at"].isoformat() if a["closed_at"] else None) for a in an],
                    snapshot={"id": snap["id"], "ts": snap["ts"].isoformat(), "exact": snap["exact"]} if snap else None, machines=machines)

