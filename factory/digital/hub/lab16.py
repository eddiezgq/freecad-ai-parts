# -*- coding: utf-8 -*-
"""实验 16“客户投诉的追溯、召回与服务决策”（第 18 轮 E1-12）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：老师注入批次投诉（同一片砂轮磨的几根轴，装在不同客户那里，陆续出轴承问题）→ 学生先自己从投诉的设备往回追，列出排查范围 →
标出高风险的设备 → 在指挥台比较三个服务方案（客户数、费用、天数、风险），选一个、写理由并提交（提交前是“比对模式”，沿用实验 15）→
起草动作（服务派工 + 客户通知），老师批准、执行 → 工程师上门、回访打分后，读回访结果。

评分全部依据平台里的事实：系统的追溯链、孪生的健康度、动作的执行状态、回访记录。任务成绩存在 task_result，编号加前缀 l16_。"""
import json

TASKS = [
    {"id": "l16_t1", "points": 15, "title": "先自己追溯、列排查范围",
     "desc": "老师注入批次投诉后，先选一条投诉，不看指挥台的因果链：在“数字孪生”页找到这台设备装的输出轴，再在“零件追溯”里查它是哪片砂轮磨的；"
             "同一片砂轮磨的轴还装在哪些现场设备上？在下面勾出排查范围。",
     "hint": "设备 → 出厂总成 → 装的输出轴 → 磨削工序用的砂轮（grd-01/S…）→ 同一片砂轮磨的其他轴 → 装在哪台设备、哪个客户。"},
    {"id": "l16_t2", "points": 10, "title": "标出高风险的设备",
     "desc": "排查范围里，哪些设备风险高、应该优先上门？看每台的健康度和最先到期的轴承用了多少。",
     "hint": "高风险 = 健康度红或黄，或者最先到期的轴承寿命已用 50% 以上。"},
    {"id": "l16_t3", "points": 10, "title": "选一个服务方案并说明理由",
     "desc": "在指挥台打开这条投诉的异常，右栏有三个方案（只修出问题的 / 修 + 高风险点检 / 整批排查），比较客户数、费用、天数、有没有漏掉高风险设备。"
             "选一个，写清楚理由和代价。提交以后，指挥台和 AI 才显示中枢的建议。",
     "hint": "理由至少一句完整的话：费用、风险（漏掉的高风险设备）、客户（要通知几家、保修内谁出钱）。"},
    {"id": "l16_t4", "points": 15, "title": "起草派工和客户通知，批准、执行",
     "desc": "在指挥台“采纳”你选的方案：会生成服务派工、备件出库、客户通知几个动作草稿。提交后请老师（厂长）批准，看排班表和 ERPNext 的服务单。",
     "hint": "要用“售后”角色登录才能发起服务动作。教学模式的客户通知只记录、不发邮件。"},
    {"id": "l16_t5", "points": 10, "title": "看回访结果",
     "desc": "工程师按排班上门做完以后，客户回访会打分（1–5 分）。你这次服务的回访平均分在哪个区间？",
     "hint": "“客户与服务”页的“回访”一栏。现场时钟可以在数字孪生页调快。"},
]
REPORT_POINTS = 40
BUCKETS = ["4.5 分及以上", "3.5 到 4.5 分", "低于 3.5 分"]
SERVICE_TYPES = ("service_batch", "spare_ship", "customer_notice")


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l16_start"):
        _save(db, user, "l16_start", 0, {})


def locked(db, u, anomaly_id=None):
    """比对模式：教学模式的学生开始了实验 16、还没提交任务 3 → 不显示建议和推荐理由"""
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l16_start"):
            return False
        r = _get(db, u["name"], "l16_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def _complaint(db, cid):
    from hub import service as SV
    SV.init(db)
    try:
        cid = int(str(cid).replace("CP-", ""))
    except (TypeError, ValueError):
        return None
    return db.one("select * from complaint where id=%s and mode='teach'", (cid,))


def trace(db, serial):
    """系统的追溯结果：砂轮、同一片砂轮磨的轴装在哪些设备上"""
    from hub.ont import anomaly as A
    from hub.ont import chain as CH
    sc = CH.chain_field(A.Ctx(db, "teach"), [serial], label="投诉").out().get("scope") or {}
    return {"wheels": sc.get("wheels") or [], "units": sc.get("check_units") or [], "customers": sc.get("customers") or []}


def _anomaly_for(db, c):
    key = "CP-{:05d}".format(c["id"])
    return db.one("select * from anomaly where mode='teach' and rule in ('C1','C3') and detail->'values'->>'complaint'=%s order by id desc limit 1", (key,))


def _chosen(db, user):
    r = _get(db, user, "l16_t1")
    return (r["evidence"] or {}).get("complaint_id") if r else None


def answer(db, user, tid, ans):
    from hub import service as SV
    start(db, user)
    if tid == "l16_t1":
        c = _complaint(db, ans.get("complaint_id"))
        if c is None:
            return {"score": 0, "of": 15, "feedback": "先选一条投诉（老师注入的那批）"}
        if not c["serial"]:
            return {"score": 0, "of": 15, "feedback": "这条投诉没有设备序列号，追不到出厂数据；换一条"}
        t = trace(db, c["serial"])
        exp, mine = set(t["units"]), set(ans.get("units") or [])
        s = 3
        if exp:
            s += 8 if mine == exp else (4 if mine & exp and not (mine - exp) else (2 if mine & exp else 0))
        elif not mine:
            s += 8
        if ans.get("wheel") and ans.get("wheel") in t["wheels"]:
            s += 4
        _save(db, user, tid, s, {"complaint_id": c["id"], "serial": c["serial"], "answer": ans, "expected": t})
        return {"score": s, "of": 15, "feedback": "全部正确。" if s == 15 else
                "得 {} / 15 分。对照系统的追溯：砂轮 {}，排查范围 {}。".format(s, "、".join(t["wheels"]) or "—", "、".join(sorted(exp)) or "只有这一台")}
    if tid == "l16_t2":
        cid = _chosen(db, user)
        c = _complaint(db, cid) if cid else None
        if c is None:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（选定投诉）"}
        us = SV.units(db, "teach")
        scope = [s for s in trace(db, c["serial"])["units"] if s in us]
        exp = {s for s in scope if SV.is_high(us[s])}
        mine = set(ans.get("units") or [])
        right, wrong = len(mine & exp), len(mine - exp)
        missed = len(exp - mine)
        s = 10 if mine == exp else max(0, 10 - 3 * wrong - 3 * missed)
        _save(db, user, tid, s, {"complaint_id": c["id"], "answer": sorted(mine), "expected": sorted(exp),
                                 "detail": {x: {"health": us[x]["health"], "bearing_used": us[x]["worst_bearing"]["used"]} for x in scope}})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                "得 {} / 10 分（对 {}，多标 {}，漏标 {}）。系统判定的高风险：{}。".format(s, right, wrong, missed, "、".join(sorted(exp)) or "没有")}
    if tid == "l16_t3":
        cid = _chosen(db, user)
        c = _complaint(db, cid) if cid else None
        if c is None:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（选定投诉）"}
        reason = str(ans.get("reason") or "").strip()
        key = str(ans.get("option") or "").strip().upper()
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：费用、风险、客户"}
        a = _anomaly_for(db, c) or {"subject_type": "FieldUnit", "subject_key": c["serial"], "detail": {"values": {"units": [c["serial"]]}}}
        opts = {o["key"]: o for o in SV.options(db, "teach", a)["options"]}
        o = opts.get(key)
        if o is None:
            return {"score": 0, "of": 10, "feedback": "选 A、B 或 C（现有方案：{}）".format("、".join(opts) or "无")}
        covered = not o["uncovered_high"]
        s = (6 if covered else 2) + (4 if any(k in reason for k in ("成本", "钱", "费")) and any(k in reason for k in ("风险", "客户", "保修")) else 2)
        _save(db, user, tid, s, {"submitted": True, "complaint_id": c["id"], "option": key, "label": o["label"], "reason": reason,
                                 "uncovered_high": o["uncovered_high"], "cost": o["service"]["cost"]["total"], "days": o["service"]["days"]})
        return {"score": s, "of": 10, "feedback": ("提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else
                                                    "提交了（得 {} 分）。{}".format(s, "你选的方案漏掉了 {} 台高风险设备。".format(len(o["uncovered_high"]))
                                                                                if not covered else "理由里最好同时说到费用和风险。"))}
    if tid == "l16_t5":
        acts = _my_actions(db, user)
        ids = [x["id"] for x in acts if x["type"] == "service_batch"]
        rows = db.q("select f.score from follow_up f join service_job j on j.id=f.job_id where j.action_id = any(%s) and f.score is not null", (ids,)) if ids else []
        if not rows:
            return {"score": 0, "of": 10, "feedback": "还没有回访打分：要等工程师上门做完、回访到期（现场时钟可以调快）"}
        avg = sum(float(r["score"]) for r in rows) / len(rows)
        right = BUCKETS[0] if avg >= 4.5 else (BUCKETS[1] if avg >= 3.5 else BUCKETS[2])
        s = 10 if ans.get("bucket") == right else 3
        _save(db, user, tid, s, {"answer": ans, "expected": right, "avg": round(avg, 2), "n": len(rows)})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "回访平均 {:.1f} 分，是“{}”。".format(avg, right)}
    raise KeyError(tid)


def _my_actions(db, user):
    return db.q("select id, type, status, title from action where mode='teach' and initiator=%s and type = any(%s) order by id",
                (user, list(SERVICE_TYPES)))


def check(db, user):
    """自动检查任务 4（看动作的状态）"""
    start(db, user)
    acts = _my_actions(db, user)
    if acts:
        sb = [x for x in acts if x["type"] == "service_batch"]
        nt = [x for x in acts if x["type"] == "customer_notice"]
        s = 10 if any(x["status"] == "done" for x in sb) else (6 if any(x["status"] in ("submitted", "approved", "executing") for x in sb) else
                                                              (3 if sb else 0))
        s += 5 if any(x["status"] == "done" for x in nt) else (2 if nt else 0)
        _save(db, user, "l16_t4", s, {"actions": [{"id": x["id"], "type": x["type"], "status": x["status"]} for x in acts]})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l16_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    cid = _chosen(db, user)
    t3 = rows.get("l16_t3")
    c = _complaint(db, cid) if cid else None
    a = _anomaly_for(db, c) if c else None
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "complaint_id": cid, "anomaly_id": a["id"] if a else None,
            "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "buckets": BUCKETS, "options": _options(db, cid)}


def _options(db, cid):
    from hub import service as SV
    from hub.ont import anomaly as A
    from hub.ont.rules.service import shaft_batch
    SV.init(db)
    cs = db.q("select id, customer, serial, subject, status from complaint where mode='teach' order by id desc limit 30")
    us = SV.units(db, "teach")
    wheels = sorted({x["wheel"] for x in shaft_batch(A.Ctx(db, "teach"), list(us)).values() if x.get("wheel")})
    mine = _complaint(db, cid) if cid else None
    return {"complaints": [{"value": c["id"], "label": "CP-{:05d} {}（{}{}）".format(c["id"], c["subject"], c["customer"].split(" ")[0],
                                                                                    "，" + c["serial"] if c["serial"] else "")} for c in cs],
            "units": [{"value": s, "label": "{} {}".format(s, u["customer"].split(" ")[0]), "health": u["health"],
                       "bearing_used": u["worst_bearing"]["used"]} for s, u in sorted(us.items()) if not mine or s != mine["serial"]],
            "wheels": wheels}


# ---------------------------------------------------------------- 老师注入
def inject(H, u, body):
    from hub import service as SV
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入问题")
    r = SV.inject_batch(H, "teach", int(body.get("n") or 3))
    return dict(r, text="已注入：{} 磨的轴所在的 {} 台设备（{}）出轴承问题，客户会在 {} 陆续来电".format(
        r["wheel"], len(r["units"]), "、".join(r["units"]), "、".join(r["days"])))


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l16_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
