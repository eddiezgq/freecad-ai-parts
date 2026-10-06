# -*- coding: utf-8 -*-
"""实验 15“车间异常的追因、推演与决策”（第 17 轮 D 期 D9）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：老师注入问题（停机 / 缺料 / 质量漂移）→ 学生先自己追因（填因果链）→ 在推演工作台试 ≥ 3 个方案、保存场景 →
选一个、写理由并提交（提交前是“比对模式”：指挥台和 AI 都不显示建议和推荐理由）→ 采纳、老师批准、看执行结果 → 看自动复盘、填复盘结论。

评分全部依据平台里的事实：系统因果链、学生保存的场景、动作的执行状态、复盘记录——不看学生自己怎么说。
任务成绩存在 task_result（与实验 7 同一张表），任务编号加前缀 l15_，不和实验 7 冲突。"""
import datetime as dt
import json

from factory import data as F

TASKS = [
    {"id": "l15_t1", "points": 15, "title": "先自己追因",
     "desc": "老师注入问题后，先不看厂情中枢的建议，用首页、车间终端、订单页自己找：出了什么异常？它影响哪些工单、哪张订单？订单会晚几天？在下面填你的因果链。",
     "hint": "停机：车间实况 → 这台设备前面排着哪些工单 → 订单与交期。缺料：关键物料 → 用到它的工单 → 订单。"},
    {"id": "l15_t2", "points": 15, "title": "推演至少 3 个方案",
     "desc": "在推演工作台用当前快照试至少 3 个处理方案（可以包括“不处理”作对照），每个都起名保存成场景，关联到这个异常。",
     "hint": "从指挥台右栏“在推演工作台细调”进去，场景会自动关联到异常。比较：准时吗？多花多少钱？加班多久？"},
    {"id": "l15_t3", "points": 10, "title": "选一个方案并说明理由",
     "desc": "从你保存的场景里选一个，写清楚为什么选它、代价是什么。提交以后，指挥台和 AI 才显示中枢的建议，你可以对比。",
     "hint": "理由至少写一句完整的话：交期、成本、风险三方面。"},
    {"id": "l15_t4", "points": 10, "title": "采纳并执行",
     "desc": "把选定的方案提交为动作，请老师（厂长）批准，看车间 / ERPNext 的执行结果。",
     "hint": "推演工作台“把这些改动提交为动作”，或在指挥台右栏“采纳”。动作收件箱里能看到状态。"},
    {"id": "l15_t5", "points": 10, "title": "看复盘、填结论",
     "desc": "异常解决、受影响的工单做完后，平台自动生成复盘。回答：推演的完工时间和实际差了多少？",
     "hint": "复盘在指挥台这个异常的详情里（关闭的异常显示“复盘”）。"},
]
REPORT_POINTS = 40
BUCKETS = ["相差不到 5%", "相差 5%–10%", "相差超过 10%"]
INJECT = {
    "down": "设备停机（选设备、时长）",
    "shortage": "物料短缺（库存降到很少）",
    "quality": "质量漂移（磨床砂轮修整间隔过长）",
}


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l15_start"):
        _save(db, user, "l15_start", 0, {})


def locked(db, u, anomaly_id=None):
    """比对模式：教学模式的学生开始了实验 15、还没提交任务 3（选方案）→ 不显示建议和推荐理由"""
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l15_start"):
            return False
        r = _get(db, u["name"], "l15_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def _anomaly(db, aid):
    return db.one("select * from anomaly where id=%s and mode='teach'", (int(aid),)) if aid else None


def _scope(db, a):
    """系统因果链的范围（工单、订单）；还没算就现算"""
    ch = a["chain"]
    if not ch:
        from hub.ont import anomaly as A
        from hub.ont import chain as CH
        ch = CH.for_anomaly(A.Ctx(db, "teach"), a)
    sc = (ch or {}).get("scope") or {}
    return set(sc.get("work_orders") or []), set(sc.get("sales_orders") or [])


def _my_scenarios(db, user, aid):
    return db.q("select id, title, changes, result from scenario where mode='teach' and created_by=%s and anomaly_id=%s order by id", (user, aid))


def answer(db, user, tid, ans):
    start(db, user)
    if tid == "l15_t1":
        a = _anomaly(db, ans.get("anomaly_id"))
        if a is None:
            return {"score": 0, "of": 15, "feedback": "先选一个异常（老师注入的那个）"}
        wos, sos = _scope(db, a)
        my_w, my_s = set(ans.get("work_orders") or []), set(ans.get("sales_orders") or [])
        s = 3                                                               # 找到了异常
        s += 4 if wos and my_w == wos else (2 if my_w & wos else 0)
        s += 4 if sos and my_s == sos else (2 if my_s & sos else 0)
        # 晚几天：与“不处理”的推演比，差 1 天以内算对
        base = _base_late(db, a)
        try:
            late = int(ans.get("late_days"))
        except (TypeError, ValueError):
            late = None
        if late is not None and base is not None and abs(late - base) <= 1:
            s += 4
        if not wos and not sos:
            s = max(s, 11) if late is not None else s                       # 质量类异常可能不连订单
        _save(db, user, tid, s, {"anomaly_id": a["id"], "answer": ans, "expected": {"work_orders": sorted(wos), "sales_orders": sorted(sos),
                                                                                    "late_days": base}})
        return {"score": s, "of": 15, "feedback": "全部正确。" if s == 15 else
                "得 {} / 15 分。对照系统的因果链：工单 {}，订单 {}，不处理时晚 {} 天。".format(s, "、".join(sorted(wos)) or "无", "、".join(sorted(sos)) or "无",
                                                                       base if base is not None else "—")}
    if tid == "l15_t3":
        aid = _chosen_anomaly(db, user)
        sc = db.one("select * from scenario where id=%s and created_by=%s and mode='teach'", (int(ans.get("scenario_id") or 0), user))
        reason = str(ans.get("reason") or "").strip()
        if sc is None:
            return {"score": 0, "of": 10, "feedback": "从你保存的场景里选一个"}
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：交期、成本、风险"}
        ok = bool((sc["result"] or {}).get("ok", True))
        s = (6 if ok else 2) + (4 if any(k in reason for k in ("交期", "按时", "晚")) and any(k in reason for k in ("成本", "钱", "费")) else 2)
        _save(db, user, tid, s, {"submitted": True, "anomaly_id": aid or sc["anomaly_id"], "scenario_id": sc["id"], "reason": reason, "ok": ok})
        return {"score": s, "of": 10, "feedback": ("提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else
                                                    "提交了（得 {} 分）。理由里最好同时说到交期和成本。".format(s))}
    if tid == "l15_t5":
        aid = _chosen_anomaly(db, user)
        r = db.one("select * from retro where anomaly_id=%s and partial=false order by id desc limit 1", (aid,)) if aid else None
        if r is None:
            return {"score": 0, "of": 10, "feedback": "复盘还没生成：要等异常解决、受影响的工单做完"}
        pct = abs((r["deviation"] or {}).get("finish_pct") or 0)
        right = BUCKETS[0] if pct < 5 else (BUCKETS[1] if pct <= 10 else BUCKETS[2])
        s = 10 if ans.get("bucket") == right else 3
        _save(db, user, tid, s, {"retro": r["id"], "answer": ans, "expected": right, "finish_pct": (r["deviation"] or {}).get("finish_pct")})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "复盘里是“{}”。再看看工单那一行。".format(right)}
    raise KeyError(tid)


def _base_late(db, a):
    """不处理时（推演）受影响订单最多晚几天"""
    from hub.ont import playbook as PB
    from hub.ont import plan as P
    snap = db.one("select state from sim_snapshot where mode='teach' order by id desc limit 1")
    if not snap:
        return None
    try:
        st = snap["state"]
        ctx = P.context(db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
        names = PB.affected(a, ctx)
        r = P.simulate(st, [], ctx)
        lates = [s["late_days"] for s in r["sales_orders"] if s["name"] in names and s["late_days"] is not None]
        return max(0, max(lates)) if lates else None
    except Exception:  # noqa: BLE001
        return None


def _chosen_anomaly(db, user):
    r = _get(db, user, "l15_t1")
    return (r["evidence"] or {}).get("anomaly_id") if r else None


def check(db, user):
    """自动检查任务 2、4（看场景和动作）"""
    start(db, user)
    aid = _chosen_anomaly(db, user)
    if aid:
        scs = _my_scenarios(db, user, aid)
        kinds = {json.dumps(sorted(c.get("type") for c in (x["changes"] or [])), ensure_ascii=False) for x in scs}
        n = len(kinds)
        if n:
            _save(db, user, "l15_t2", min(15, 5 * n), {"anomaly_id": aid, "scenarios": [x["id"] for x in scs], "distinct": n})
        acts = db.q("select id, status, title from action where mode='teach' and initiator=%s and anomaly_id=%s order by id", (user, aid))
        if acts:
            done = [x for x in acts if x["status"] == "done"]
            s = 10 if done else (6 if any(x["status"] in ("submitted", "approved", "executing") for x in acts) else 3)
            _save(db, user, "l15_t4", s, {"actions": [{"id": x["id"], "status": x["status"]} for x in acts]})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l15_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    aid = _chosen_anomaly(db, user)
    t3 = rows.get("l15_t3")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "anomaly_id": aid, "locked": not (t3 and (t3["evidence"] or {}).get("submitted")),
            "buckets": BUCKETS, "options": _options(db, user, aid)}


def _options(db, user, aid):
    from hub import kpi
    ov = kpi.overview(db, None, "teach")
    an = db.q("select id, title, rule, severity from anomaly where mode='teach' and (status in ('open','ack','doing') or closed_at > now() - interval '1 day') "
              "order by id desc limit 30")
    wos = sorted({w["data"]["name"] for w in db.erp_docs("Work Order", "teach")
                  if w["data"].get("status") not in ("Completed", "Closed", "Cancelled", "Stopped")})
    return {"anomalies": [{"value": a["id"], "label": "A-{:05d} {}".format(a["id"], a["title"])} for a in an],
            "work_orders": wos, "sales_orders": [o["name"] for o in ov["orders"]],
            "scenarios": [{"value": x["id"], "label": "SC-{:05d} {}".format(x["id"], x["title"])} for x in (_my_scenarios(db, user, aid) if aid else [])]}


# ---------------------------------------------------------------- 老师注入
def inject(H, u, kind, body):
    """教学模式的老师：停机（经车间）、物料短缺（改库存快照）、质量漂移（经质量问题情景）"""
    from hub import qproblem
    from wqbus.topics import topic
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入问题")
    who = u.get("name")
    if kind == "down":
        unit = body.get("unit") or "grd-01"
        mins = float(body.get("minutes") or 240)
        H.mes.command(unit, "inject_fault", "teach", who, minutes=mins, reason=body.get("reason") or "主轴故障，等备件")
        return {"text": "已让 {} 停机 {:.0f} 分钟".format(unit.upper(), mins)}
    if kind == "shortage":
        code = body.get("item") or "RM-45-D50"
        if code not in F.ITEMS:
            raise ValueError("没有这个物料：" + code)
        qty = float(body.get("qty") if body.get("qty") is not None else 5)
        kindw = F.ITEMS[code][1]
        wh = "{} - WQ".format(F.KIND_WAREHOUSE[kindw])
        H.publish(topic("office", "erp", "bin"), "erp.doc", "teach/inject",
                  {"doctype": "Bin", "name": "{}@{}".format(code, wh), "action": "snapshot", "demo": True, "item_code": code, "warehouse": wh,
                   "actual_qty": qty, "ordered_qty": 0, "reserved_qty": 0, "projected_qty": qty, "stock_uom": F.ITEMS[code][2]}, None, "teach")
        return {"text": "已把 {} 的库存降到 {:g}".format(code, qty)}
    if kind == "quality":
        def send(cmd, **extra):
            H.mes.command("sim", cmd, "teach", who, **extra)
        qproblem.inject(H.db, send, "teach", who, body.get("problem") or "dressing_interval", body.get("magnitude"))
        return {"text": "已注入质量问题：砂轮修整间隔过长（尺寸漂移加快）"}
    raise ValueError("注入种类只能是 down / shortage / quality")


def class_view(db):
    """老师看全班：每个人的分数"""
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l15_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]

