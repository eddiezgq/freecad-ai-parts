# -*- coding: utf-8 -*-
"""实验 18“设备维护策略：保养时机的决策”（第 18 轮 E3-9）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：老师打开车间可靠性（建议加速 ×5），把一台设备的保养拨成逾期 → 学生看台账和失效率曲线，手算未来 80 运行小时坏掉的概率和预期损失 →
在指挥台比较“现在保养 / 下班后保养 / 不做”，选一个说明理由（比对模式）→ 起草保养工单，老师批准，到时间挂牌上锁 → 维修工做完，验收解锁 →
一段时间（工厂时间）后对比保养过的设备和没保养的设备的故障记录 → 用故障记录估平均故障间隔。评分依据平台里的事实。任务编号前缀 l18_。"""
import json

TASKS = [
    {"id": "l18_t1", "points": 15, "title": "手算故障概率和预期损失",
     "desc": "在“设备维护 → 设备台账”里找到保养逾期的设备，点“详情”看失效率曲线和参数（β、η）。自己算：自上次保养已运行 t 小时，再运行 80 小时内坏掉的概率 "
             "P = 1 − exp(−[((t+80)/η)^β − (t/η)^β])；预期损失 = P ×（修理费 + 停机损失）。可靠性系数 k 不是 1 时，t 和 80 都先乘 k。",
     "hint": "先算 (t/η)^β 和 ((t+80)/η)^β，相减，再算 1 − e 的负这么多次方。"},
    {"id": "l18_t2", "points": 10, "title": "比较方案，选一个",
     "desc": "在指挥台打开这台设备的“保养逾期”异常，右栏三个方案：现在保养 / 下班后保养 / 不做（对照）。比较交期、花费和预期故障损失，选一个，写理由。提交后才显示中枢的建议。",
     "hint": "保养的花费是确定的，不保养的损失是“概率 × 损失”。理由里同时说到概率（风险）和钱。"},
    {"id": "l18_t3", "points": 15, "title": "执行保养",
     "desc": "在指挥台采纳你选的方案（不做就不用采纳），生成保养工单，请老师批准：到时间车间里这台设备挂牌上锁停下，维修工做完后你在“设备维护 → 保养”里验收解锁。",
     "hint": "要用“维修工”角色登录才能发起保养工单。保养做完后，台账里“自上次保养”回到 0。"},
    {"id": "l18_t4", "points": 10, "title": "对比做了和没做",
     "desc": "车间继续运行一段时间（工厂时间）。在设备台账的“详情”里数一数：保养以后，你保养的这台设备坏了几次？保养逾期最多的另一台坏了几次？",
     "hint": "看“最近的故障”表，只数你保养完成以后的。"},
    {"id": "l18_t5", "points": 10, "title": "估平均故障间隔（MTBF）",
     "desc": "用平台的故障记录估全厂近 30 天的平均故障间隔：30 天 × 每天 16 运行小时 ÷ 故障次数。",
     "hint": "故障次数在各设备“详情”的故障表里，加起来。"},
]
REPORT_POINTS = 40
OPTIONS = [{"value": "pm_now", "label": "现在保养"}, {"value": "pm_later", "label": "下班后（或几小时后）保养"}, {"value": "none", "label": "不做（对照）"}]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l18_start"):
        _save(db, user, "l18_start", 0, {})


def locked(db, u, anomaly_id=None):
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l18_start"):
            return False
        r = _get(db, u["name"], "l18_t2")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def _unit(db, user):
    r = _get(db, user, "l18_t1")
    return (r["evidence"] or {}).get("unit") if r else None


def answer(db, user, tid, ans):
    from hub import maint as MT
    start(db, user)
    if tid == "l18_t1":
        unit = ans.get("unit")
        if not MT.REL.params(unit or ""):
            return {"score": 0, "of": 15, "feedback": "选一台设备"}
        rk = MT.risk(db, "teach", unit)
        s = 0
        try:
            if abs(float(ans.get("run_h")) - rk["run_h"]) <= max(10, rk["run_h"] * 0.05):
                s += 3
            if abs(float(ans.get("p_fail")) / (100 if float(ans.get("p_fail")) > 1 else 1) - rk["p_fail"]) <= max(0.01, rk["p_fail"] * 0.1):
                s += 7
            if abs(float(ans.get("loss")) - rk["expected_loss_usd"]) <= max(5, rk["expected_loss_usd"] * 0.1):
                s += 5
        except (TypeError, ValueError):
            return {"score": 0, "of": 15, "feedback": "填数字"}
        _save(db, user, tid, s, {"unit": unit, "answer": ans, "expected": {k: rk[k] for k in ("run_h", "p_fail", "expected_loss_usd", "factor")}})
        return {"score": s, "of": 15, "feedback": "全部正确。" if s == 15 else
                "得 {} / 15 分。平台按提交时的数据算：运行 {:g} 小时，概率 {:.1%}，预期损失 ${:,.0f}（可靠性系数 {:g}）。".format(
                    s, rk["run_h"], rk["p_fail"], rk["expected_loss_usd"], rk["factor"])}
    if tid == "l18_t2":
        unit = _unit(db, user)
        if not unit:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（选定设备）"}
        reason = str(ans.get("reason") or "").strip()
        kind = ans.get("option")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：概率、损失、花费"}
        if kind not in ("pm_now", "pm_later", "none"):
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        best = _system_choice(db, unit)
        s = 6 if kind == best else (4 if kind != "none" else 2)
        s += 4 if any(k in reason for k in ("概率", "风险", "可能")) and any(k in reason for k in ("钱", "成本", "损失", "费", "$")) else 2
        _save(db, user, tid, s, {"submitted": True, "unit": unit, "option": kind, "reason": reason, "system": best})
        return {"score": s, "of": 10, "feedback": "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)}
    if tid == "l18_t4":
        unit = _unit(db, user)
        pm = _my_pm(db, user, unit)
        if not pm or pm["status"] not in ("fixed", "closed"):
            return {"score": 0, "of": 10, "feedback": "先完成任务 3（保养做完）"}
        since = pm["fixed_at"]
        mine = db.one("select count(*) as n from maint_failure where mode='teach' and unit=%s and at > %s", (unit, since))["n"]
        other = _other(db, unit)
        theirs = db.one("select count(*) as n from maint_failure where mode='teach' and unit=%s and at > %s", (other, since))["n"] if other else 0
        s = 0
        try:
            s += 5 if int(ans.get("mine")) == mine else 0
            s += 5 if int(ans.get("other")) == theirs else 0
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填次数"}
        _save(db, user, tid, s, {"answer": ans, "expected": {"mine": mine, "other": theirs, "other_unit": other}})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "平台记录：{} 保养后坏了 {} 次；{} 同期坏了 {} 次。".format(
            unit.upper(), mine, (other or "—").upper(), theirs)}
    if tid == "l18_t5":
        m = MT.mtbf(db, "teach")
        if m is None:
            return {"score": 0, "of": 10, "feedback": "近 30 天还没有故障记录（请老师打开车间可靠性）"}
        try:
            v = float(ans.get("mtbf"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填数字"}
        s = 10 if abs(v - m) <= m * 0.2 else (5 if abs(v - m) <= m * 0.5 else 0)
        _save(db, user, tid, s, {"answer": v, "expected": m})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "平台估的是 {:g} 运行小时。".format(m)}
    raise KeyError(tid)


def _system_choice(db, unit):
    """中枢会推荐哪个（用最新快照推演；推演不了就按预期损失和保养花费比）"""
    from hub import maint as MT
    rk = MT.risk(db, "teach", unit)
    return "pm_now" if rk["expected_loss_usd"] > rk["pm_usd"] else "none"


def _my_pm(db, user, unit):
    a = db.one("select id from action where mode='teach' and initiator=%s and type='pm_order' and params->>'unit'=%s order by id desc limit 1", (user, unit)) \
        if unit else None
    if not a:
        return None
    return db.one("select * from maint_pm where action_id=%s order by id desc limit 1", (a["id"],))


def _other(db, unit):
    from hub import maint as MT
    rows = sorted([x for x in MT.assets(db, "teach") if x["unit"] != unit], key=lambda x: -x["overdue_h"] - x["run_h"] / 1000)
    return rows[0]["unit"] if rows else None


def check(db, user):
    """自动检查任务 3：保养工单执行 8；验收关闭 +4；运行小时清零 +3"""
    from hub import maint as MT
    start(db, user)
    unit = _unit(db, user)
    if unit:
        acts = db.q("select id, status from action where mode='teach' and initiator=%s and type='pm_order' and params->>'unit'=%s order by id", (user, unit))
        if acts:
            s = 8 if any(a["status"] == "done" for a in acts) else (5 if any(a["status"] in ("submitted", "approved", "executing") for a in acts) else 2)
            pm = _my_pm(db, user, unit)
            if pm and pm["status"] == "closed":
                s += 4
            if pm and pm["status"] in ("fixed", "closed") and MT.run_hours(db, "teach", unit) < 50:
                s += 3
            _save(db, user, "l18_t3", s, {"actions": [{"id": a["id"], "status": a["status"]} for a in acts], "pm": pm["status"] if pm else None})
    return status(db, user)


def status(db, user):
    from hub import maint as MT
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l18_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    unit = _unit(db, user)
    a = db.one("select id from anomaly where mode='teach' and rule in ('M2','M4') and subject_key=%s order by id desc limit 1", (unit,)) if unit else None
    t2 = rows.get("l18_t2")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "unit": unit, "anomaly_id": a["id"] if a else None,
            "locked": not (t2 and (t2["evidence"] or {}).get("submitted")), "options": OPTIONS,
            "units": [{"value": u, "label": u.upper()} for u in MT.units()], "factor": MT.factor(db, "teach")}


def inject(H, u, body):
    from hub import maint as MT
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    if body.get("factor") is not None:
        MT.set_factor(H, "teach", float(body["factor"]), u.get("name"))
    unit = body.get("unit") or "grd-01"
    hours = float(body.get("hours") or 0)
    if hours > 0:
        return MT.inject_overdue(H, "teach", unit, hours, u.get("name"))
    return {"text": "可靠性系数 {:g}".format(MT.factor(H.db, "teach"))}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l18_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
