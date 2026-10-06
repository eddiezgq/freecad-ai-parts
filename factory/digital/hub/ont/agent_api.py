# -*- coding: utf-8 -*-
"""第 17 轮 D 期接口：让 AI 分析异常、AI 运行记录（含反馈）、评测集。

要在 mount_anomaly 之前挂载：/api/ont/anomalies/{aid}/analyze 与那边的 /{kind} 同形。"""
import threading

from fastapi import Body, Depends, HTTPException

from hub.ont import agent as AG
from hub.ont import evals as EV

_eval_lock = threading.Lock()


def mount(app, H, user_of, who, ai_quota):
    def is_boss(u):
        return bool(u.get("teacher")) or (u.get("mode") == "prod" and u.get("role") == "manager")

    @app.post("/api/ont/anomalies/{aid}/analyze")
    def analyze(aid: int, u=Depends(user_of)):
        if H.agent is None:
            raise HTTPException(503, "AI 代理还没就绪")
        a = H.db.one("select id from anomaly where id=%s and mode=%s", (aid, u["mode"]))
        if a is None:
            raise HTTPException(404, "没有这个异常")
        ai_quota(u)
        return H.agent.analyze(u, aid)

    @app.get("/api/ai/runs")
    def runs(mine: int = 0, bad: int = 0, kind: str = "", u=Depends(user_of)):
        if not is_boss(u) and not mine:
            raise HTTPException(403, "运行记录由厂长或老师查看；你可以看自己的")
        return {"runs": AG.runs(H.db, u["mode"], user=u.get("name") if (mine or not is_boss(u)) else None, only_bad=bool(bad), kind=kind or None),
                "engine": H.ai.llm.name if H.ai else "rules"}

    @app.get("/api/ai/runs/{rid}")
    def run_get(rid: int, u=Depends(user_of)):
        r = H.db.one("select * from ai_run where id=%s and mode=%s", (rid, u["mode"]))
        if r is None or (not is_boss(u) and r["user"] != u.get("name")):
            raise HTTPException(404, "没有这条运行记录")
        return dict(r, created_at=r["created_at"].isoformat())

    @app.post("/api/ai/runs/{rid}/feedback")
    def feedback(rid: int, body: dict = Body(...), u=Depends(user_of)):
        r = H.db.one("select id, \"user\" from ai_run where id=%s and mode=%s", (rid, u["mode"]))
        if r is None or r["user"] != u.get("name"):
            raise HTTPException(404, "只能给自己的提问反馈")
        v = int(body.get("value") or 0)
        if v not in (-1, 0, 1):
            raise HTTPException(400, "反馈只能是 👍（1）或 👎（-1）")
        H.db.x("update ai_run set feedback=%s, feedback_text=%s where id=%s", (v or None, (body.get("text") or "")[:500] or None, rid))
        return {"ok": True}

    # ---------------------------------------------------------------- 评测集
    @app.get("/api/ai/evals")
    def evals(u=Depends(user_of)):
        if not is_boss(u):
            raise HTTPException(403, "评测由厂长或老师查看")
        hist = EV.history(H.db)
        last = H.db.one("select * from ai_eval_run where finished_at is not null order by id desc limit 1")
        items = EV.load()
        return {"history": hist, "last": dict(last, started_at=last["started_at"].isoformat(), finished_at=last["finished_at"].isoformat()) if last else None,
                "items": [{"id": x["id"], "domain": x["domain"], "q": x["q"], "as": x.get("as", "teacher")} for x in items],
                "engine": H.ai.llm.name if H.ai else "rules", "model": bool(H.ai and H.ai.llm.available()),
                "running": _eval_lock.locked()}

    @app.post("/api/ai/evals/run")
    def evals_run(u=Depends(user_of)):
        if not is_boss(u):
            raise HTTPException(403, "评测由厂长或老师启动")
        if H.agent is None:
            raise HTTPException(503, "AI 代理还没就绪")
        if not _eval_lock.acquire(blocking=False):
            raise HTTPException(409, "评测正在跑，稍等")

        def go():
            try:
                # 在临时数据库里载入实验 7 情景再考（与测试同一套情景），不碰正在用的工厂数据
                sb, _eng = EV.sandbox(H.db.dsn, llm=H.ai.llm)
                EV.run(AG.Agent(sb, H.ai.llm), sb.db, mode="teach", engine=H.ai.llm.name, started_by=u.get("name"), record_db=H.db)
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger("evals").exception("评测出错")
            finally:
                _eval_lock.release()
        threading.Thread(target=go, daemon=True, name="evals").start()
        return {"started": True, "engine": H.ai.llm.name}

    # ---------------------------------------------------------------- 主动提醒（D6）
    from hub.ont import notify as NT

    def boss_prod_or_teacher(u):
        return bool(u.get("teacher")) or u.get("role") == "manager"

    @app.get("/api/notifications")
    def notifications(u=Depends(user_of)):
        return NT.feed(H.db, u)

    @app.post("/api/notifications/read")
    def notifications_read(body: dict = Body(default={}), u=Depends(user_of)):
        ids = body.get("ids")
        if body.get("all"):
            ids = [x["id"] for x in NT.feed(H.db, u, limit=300)["items"] if not x["read"]]
        NT.mark_read(H.db, u["name"], ids or [])
        return {"ok": True}

    @app.get("/api/notifications/subs")
    def notify_subs(u=Depends(user_of)):
        from hub.ont import schema as S
        NT.init_once(H.db)
        out = {"sub": NT.sub_of(H.db, u["name"], u["mode"], u.get("role")), "role_default": NT.ROLE_DEFAULT.get(u.get("role") or ""),
               "domains": [{"domain": d["domain"], "label": d["label"]} for d in S.get().domains],
               "severities": NT.SEV_LABEL, "smtp": NT.smtp_ready(), "external": u["mode"] != "teach",
               "can_channels": boss_prod_or_teacher(u), "channel_kinds": NT.CHANNEL_KINDS}
        if boss_prod_or_teacher(u):
            out["channels"] = [{"id": c["id"], "kind": c["kind"], "name": c["name"], "domain": c["domain"], "min_severity": c["min_severity"],
                                "tail": c["tail"], "created_by": c["created_by"]}
                               for c in H.db.q("select * from notify_channel where mode=%s order by id", (u["mode"],))]
        return out

    @app.post("/api/notifications/subs")
    def notify_subs_save(body: dict = Body(...), u=Depends(user_of)):
        try:
            NT.init_once(H.db)
            NT.save_sub(H.db, u["name"], u["mode"], u.get("role"), body)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return notify_subs(u)

    @app.post("/api/notifications/channels")
    def channel_add(body: dict = Body(...), u=Depends(user_of)):
        if not boss_prod_or_teacher(u):
            raise HTTPException(403, "群机器人由厂长（或老师）设置")
        kind, url = body.get("kind"), (body.get("url") or "").strip()
        if kind not in NT.CHANNEL_KINDS:
            raise HTTPException(400, "只支持企业微信、钉钉、飞书群机器人")
        if not url.startswith("https://"):
            raise HTTPException(400, "群机器人地址要以 https:// 开头（在群设置 → 群机器人 → 复制 Webhook 地址）")
        sev = body.get("min_severity") or "warn"
        if sev not in NT.RANK:
            raise HTTPException(400, "严重程度不对")
        NT.init_once(H.db)
        H.db.x("insert into notify_channel (mode, kind, name, domain, min_severity, url_enc, tail, created_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
               (u["mode"], kind, (body.get("name") or NT.CHANNEL_KINDS[kind])[:60], body.get("domain") or None, sev, NT.enc(url), url[-4:], u["name"]))
        return notify_subs(u)

    @app.delete("/api/notifications/channels/{cid}")
    def channel_del(cid: int, u=Depends(user_of)):
        if not boss_prod_or_teacher(u):
            raise HTTPException(403, "群机器人由厂长（或老师）设置")
        H.db.x("delete from notify_channel where id=%s and mode=%s", (cid, u["mode"]))
        return notify_subs(u)

    @app.post("/api/notifications/test")
    def notify_test(body: dict = Body(default={}), u=Depends(user_of)):
        """发一条测试通知：站内给自己；生产模式下按订阅发邮件，厂长还会发到各个群机器人"""
        NT.init_once(H.db)
        out = {"inbox": True, "email": None, "groups": []}
        NT.emit(H.db, u["mode"], "@" + u["name"], "test", "测试通知：厂情中枢的提醒能收到", "这是一条测试，可以忽略。", "/ont", external=False)
        if u["mode"] != "teach":
            s = NT.sub_of(H.db, u["name"], u["mode"], u.get("role"))
            if s["email"] and (s["channels"] or {}).get("email"):
                out["email"] = NT.send_mail(s["email"], "【问渠厂情中枢】测试通知", "测试通知：厂情中枢的提醒能收到。")
            if boss_prod_or_teacher(u):
                for c in H.db.q("select * from notify_channel where mode=%s", (u["mode"],)):
                    out["groups"].append({"id": c["id"], "name": c["name"],
                                          "ok": NT.send_group(c["kind"], NT.dec(c["url_enc"]), "问渠厂情中枢 · 测试通知", "问渠厂情中枢 · 测试通知\n群机器人能收到厂情提醒。")})
        return out

    @app.get("/api/ont/banner")
    def banner(u=Depends(user_of)):
        try:
            return {"items": NT.banner(H.db, u["mode"])}
        except Exception:  # noqa: BLE001
            return {"items": []}

    # ---------------------------------------------------------------- 厂情日报 / 经营周报（D7）
    from hub.ont import report as RP

    @app.get("/api/reports")
    def reports(kind: str = "", u=Depends(user_of)):
        RP.init(H.db)
        w, a = ["mode=%s"], [u["mode"]]
        if kind:
            w.append("kind=%s")
            a.append(kind)
        rows = H.db.q("select * from report where {} order by id desc limit 200".format(" and ".join(w)), a)
        return {"reports": [RP.row(r) for r in rows], "teach": u["mode"] == "teach",
                "can_generate": u["mode"] == "teach" or boss_prod_or_teacher(u)}

    @app.get("/api/reports/{rid}")
    def report_get(rid: int, u=Depends(user_of)):
        r = H.db.one("select * from report where id=%s and mode=%s", (rid, u["mode"]))
        if r is None:
            raise HTTPException(404, "没有这份报告")
        return RP.row(r, full=True)

    @app.post("/api/reports/generate")
    def report_generate(body: dict = Body(default={}), u=Depends(user_of)):
        """教学模式：老师、学生都可以即时生成（最近 24 小时 / 7 天）；生产模式：厂长手动补生成"""
        kind = body.get("kind") or "daily"
        if u["mode"] != "teach" and not boss_prod_or_teacher(u):
            raise HTTPException(403, "生产模式的报告按时自动生成；厂长可以手动补生成")
        ai_quota(u)
        try:
            rid = RP.generate(H.db, u["mode"], kind, by=u.get("name"), llm=H.ai.llm if H.ai else None, notify=u["mode"] != "teach")
        except ValueError as e:
            raise HTTPException(400, str(e))
        return report_get(rid, u)

    # ---------------------------------------------------------------- 复盘（D8）
    from hub.ont import retro as RT

    @app.get("/api/ont/anomalies/{aid}/retro")
    def retro_get(aid: int, u=Depends(user_of)):
        RT.init(H.db)
        r = H.db.one("select * from retro where anomaly_id=%s and mode=%s order by id desc limit 1", (aid, u["mode"]))
        has_act = H.db.one("select 1 as x from action where anomaly_id=%s and status in ('done','failed') limit 1", (aid,))
        return {"retro": RT.row(r) if r else None, "can_create": bool(has_act) and boss_prod_or_teacher(u)}

    @app.post("/api/ont/anomalies/{aid}/retro")
    def retro_make(aid: int, u=Depends(user_of)):
        """现在就复盘（受影响的工单还没做完的，标“未完”，之后会自动更新）"""
        if not boss_prod_or_teacher(u):
            raise HTTPException(403, "复盘由厂长或老师发起")
        a = H.db.one("select id from anomaly where id=%s and mode=%s", (aid, u["mode"]))
        if a is None:
            raise HTTPException(404, "没有这个异常")
        from hub.ont import plan as P
        try:
            rid = RT.create(H.db, aid, force=True)
        except P.PlanError as e:
            raise HTTPException(400, str(e))
        if not rid:
            raise HTTPException(400, "这个异常还没有执行完的动作，没法复盘")
        return retro_get(aid, u)
