# -*- coding: utf-8 -*-
"""实验 19“排班与技能：缺人时的决策”（第 18 轮 E4-10）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：老师打开“要有人”，让一位关键操作工某一班请假 → 学生在技能矩阵里找单点依赖 → 手算缺人一班瓶颈少做多少件 →
在指挥台比较“调人顶岗 / 学徒带教 / 加班顶班 / 不处理”，选一个说明理由（比对模式）→ 起草调班或加班动作，班组长或厂长批准，车间按新排班开 →
设计技能培训计划，把单点依赖降到 0。评分依据平台里的事实。任务编号前缀 l19_。"""
import json

TASKS = [
    {"id": "l19_t1", "points": 10, "title": "找单点依赖",
     "desc": "在“人员 → 技能矩阵”里找出熟练以上只有一个人的设备（标红的列），全部勾上提交。",
     "hint": "学徒不算能独立操作；过期的资质按学徒算。"},
    {"id": "l19_t2", "points": 15, "title": "手算缺人一班的影响",
     "desc": "老师让一位操作工请假后，在“人员 → 排班”里找到缺口（标红）。算：这一班这台设备停多少小时？按轴（磨外圆 12 分钟一件）算少做多少件？",
     "hint": "一个班 12 小时；件数 = 小时 × 60 ÷ 每件分钟（先不算调整时间）。"},
    {"id": "l19_t3", "points": 10, "title": "比较方案，选一个",
     "desc": "在指挥台打开这个“排班缺口”异常，右栏四个方案：调人顶岗 / 学徒带教 / 加班顶班 / 不处理（对照）。比较交期、花费和对别的班的影响，选一个写理由。提交后才显示中枢的建议。",
     "hint": "调人不花钱，但他原来的岗位会空出来；加班不影响别的班，但要花加班费、有上限。"},
    {"id": "l19_t4", "points": 15, "title": "执行",
     "desc": "在指挥台采纳你选的方案，生成调班或加班顶班动作，请班组长或老师批准。批准后“排班”里这一班这台设备有人了，车间按新排班开。",
     "hint": "要用“班组长”或“计划员”角色发起。不处理的同学，这一步改为对缺口用调班。"},
    {"id": "l19_t5", "points": 10, "title": "技能培训计划",
     "desc": "在指挥台打开“关键资质单点依赖”异常，为每台单点依赖的设备采纳一个“技能培训”动作（谁来学、带教多少小时），把单点依赖降到 0。",
     "hint": "选已经是学徒、或在同一个班的人，带教快、不用调班。"},
]
REPORT_POINTS = 40
OPTIONS = [{"value": "swap", "label": "调人顶岗"}, {"value": "apprentice", "label": "学徒带教"}, {"value": "overtime", "label": "加班顶班"},
           {"value": "none", "label": "不处理（对照）"}]
STD_MIN = {"grd-01": 12, "hob-01": 20, "key-01": 6, "cnc-l01-a": 10, "cnc-l01-b": 10, "saw-01": 3, "vmc-01": 15, "hmc-01": 20, "ht-01": 12,
           "asm-01": 30, "press-01": 5}
SHIFT_H = 12


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l19_start"):
        _save(db, user, "l19_start", 0, {})


def locked(db, u, anomaly_id=None):
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l19_start"):
            return False
        r = _get(db, u["name"], "l19_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def gap(db):
    """老师注入的缺口（这一天这一班这台设备）"""
    from hub import people as PE
    return PE._state(db, "teach").get("lab19")


def answer(db, user, tid, ans):
    from hub import people as PE
    start(db, user)
    if tid == "l19_t1":
        want = {x["unit"] for x in PE.single_points(db, "teach")}
        got = {str(x).lower() for x in ans.get("units") or []}
        if not want:
            return {"score": 0, "of": 10, "feedback": "现在没有单点依赖的设备"}
        s = max(0, round(10 * (len(got & want) - len(got - want)) / len(want)))
        _save(db, user, tid, s, {"answer": sorted(got), "expected": sorted(want)})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else "得 {} / 10 分（多选的倒扣）。".format(s)}
    if tid == "l19_t2":
        g = gap(db)
        if not g:
            return {"score": 0, "of": 15, "feedback": "老师还没有注入请假"}
        try:
            h, n = float(ans.get("hours")), float(ans.get("parts"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 15, "feedback": "填数字"}
        exp_n = SHIFT_H * 60 // STD_MIN.get(g["unit"], 12)
        s = (5 if abs(h - SHIFT_H) <= 0.5 else 0) + (10 if abs(n - exp_n) <= max(2, exp_n * 0.1) else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": {"hours": SHIFT_H, "parts": exp_n, "unit": g["unit"]}})
        return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else "平台的算法：一个班 {} 小时，{} 每件 {} 分钟，少做约 {} 件。".format(
            SHIFT_H, g["unit"].upper(), STD_MIN.get(g["unit"], 12), exp_n)}
    if tid == "l19_t3":
        g = gap(db)
        if not g:
            return {"score": 0, "of": 10, "feedback": "老师还没有注入请假"}
        reason = str(ans.get("reason") or "").strip()
        kind = ans.get("option")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：交期、花费、对别的班的影响"}
        if kind not in ("swap", "apprentice", "overtime", "none"):
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        best = _system_choice(db, g)
        s = 6 if kind == best else (4 if kind != "none" else 2)
        s += 4 if any(k in reason for k in ("交期", "订单", "产量", "少做", "件")) and any(k in reason for k in ("钱", "费", "成本", "$", "加班", "班")) else 2
        _save(db, user, tid, s, {"submitted": True, "option": kind, "reason": reason, "system": best})
        return {"score": s, "of": 10, "feedback": "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)}
    raise KeyError(tid)


def _system_choice(db, g):
    """中枢一般推荐：同班有空闲熟练工 → 调人；有另一班的熟练工 → 调人（不花钱）；只有学徒 → 学徒带教"""
    import datetime as dt

    from hub import people as PE
    free, cross, appr = PE._candidates(db, "teach", dt.date.fromisoformat(g["day"]), g["shift"], g["unit"])
    return "swap" if (free or cross) else ("apprentice" if appr else "overtime")


def check(db, user):
    """自动检查任务 4（调班 / 加班顶班动作 5 → 执行 10 → 这一班有人了 +5）、任务 5（单点依赖的设备都有技能培训：按比例）"""
    import datetime as dt

    from hub import people as PE
    start(db, user)
    g = gap(db)
    if g:
        acts = [a for a in db.q("select id, status, params from action where mode='teach' and initiator=%s and type in ('shift_swap','overtime_assign') "
                                "order by id", (user,)) if a["params"].get("unit") == g["unit"] and str(a["params"].get("day"))[:10] == g["day"]
                and a["params"].get("shift") == g["shift"]]
        if acts:
            s = 10 if any(a["status"] == "done" for a in acts) else (5 if any(a["status"] in ("submitted", "approved", "executing") for a in acts) else 2)
            lv = PE.levels(db, "teach", [dt.date.fromisoformat(g["day"])]).get("{}|{}|{}".format(g["day"], g["shift"], g["unit"]), 0)
            if s == 10 and lv >= 1:
                s += 5
            _save(db, user, "l19_t4", s, {"actions": [{"id": a["id"], "status": a["status"]} for a in acts], "level": lv})
    sp0 = PE._state(db, "teach").get("lab19_single") or [x["unit"] for x in PE.single_points(db, "teach")]
    tr = db.q("select a.id, a.status, a.params from action a where a.mode='teach' and a.initiator=%s and a.type='skill_training' order by a.id", (user,))
    if tr and sp0:
        covered = {a["params"].get("unit") for a in tr if a["status"] in ("submitted", "approved", "executing", "done")}
        s = round(10 * len(covered & set(sp0)) / len(sp0))
        _save(db, user, "l19_t5", s, {"covered": sorted(covered & set(sp0)), "single_points": sp0,
                                      "actions": [{"id": a["id"], "status": a["status"], "unit": a["params"].get("unit")} for a in tr]})
    return status(db, user)


def status(db, user):
    from hub import people as PE
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l19_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    g = gap(db)
    a = db.one("select id from anomaly where mode='teach' and rule='H2' and fkey=%s order by id desc limit 1",
               ("{}/{}/{}".format(g["day"], g["shift"], g["unit"]),)) if g else None
    a1 = db.one("select id from anomaly where mode='teach' and rule='H1' and status in ('open','ack','doing') order by id limit 1")
    t3 = rows.get("l19_t3")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "gap": g, "anomaly_id": a["id"] if a else None, "h1_anomaly_id": a1["id"] if a1 else None,
            "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "options": OPTIONS, "enabled": PE.enabled(db, "teach"),
            "units": [{"value": u, "label": u.upper()} for u in PE.STF.NEEDS],
            "people": [{"value": p["id"], "label": "{} {}（{}，{}）".format(p["id"], p["name"], p["post"], PE.SHIFT_NAME.get(p["shift"], ""))}
                       for p in db.q("select id, name, post, shift from ehs_person where mode='teach' and active and post in ('操作工','装配工') order by id")]}


def inject(H, u, body):
    """老师：打开“要有人”；让某人下一个班请假（例如王强，磨床早班）"""
    from hub import people as PE
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    db = H.db
    PE.set_enabled(H, "teach", True if body.get("enable") is None else bool(body.get("enable")), u.get("name"))
    emp = body.get("emp_id")
    if not emp:
        return {"text": "车间“要有人”已{}".format("打开" if PE.enabled(db, "teach") else "关闭")}
    p = PE.person(db, "teach", emp)
    if p is None:
        raise ValueError("没有这个人")
    d, sh, units = PE.leave_next_shift(H, "teach", emp, u.get("name"))
    st = PE._state(db, "teach")
    st["lab19"] = {"emp_id": emp, "name": p["name"], "day": d.isoformat(), "shift": sh, "unit": units[0]}
    st["lab19_single"] = [x["unit"] for x in PE.single_points(db, "teach")]
    PE._save_state(db, "teach", st)
    return {"text": "已让 {} {} {} 请假（{} 这一班没人）".format(p["name"], d.isoformat(), PE.SHIFT_NAME[sh], units[0].upper())}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l19_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
