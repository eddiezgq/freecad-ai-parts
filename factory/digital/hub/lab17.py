# -*- coding: utf-8 -*-
"""实验 17“安全隐患的识别、评估与停机决策”（第 18 轮 E2-9）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：老师注入重大隐患（某台设备防护缺失等）→ 学生先做风险评估（选危险源、可能性 × 严重度）→ 自己追影响（停这台设备影响哪些工单、订单，
不处理和停机整改各晚几天）→ 比较三个方案、选一个说明理由（比对模式，沿用实验 15）→ 起草停机挂牌整改，老师批准，车间里设备停下 →
维修工整改完，学生验收解锁 → 看订单的实际影响。评分全部依据平台里的事实。任务成绩存在 task_result，编号加前缀 l17_。"""
import datetime as dt
import json

TASKS = [
    {"id": "l17_t1", "points": 10, "title": "风险评估",
     "desc": "老师注入重大隐患后，在“安全环保 → 隐患”里找到它。先不看指挥台：这条隐患对应危险源清单里的哪一条？防护缺了以后，可能性和严重度各是几分（1–5）？风险值多少、属于哪一级？",
     "hint": "严重度看“出了事有多严重”，防护缺失不改变它；可能性看“多容易出事”，防护缺失要往上调。风险值 = 可能性 × 严重度：≥ 15 重大，8–14 较大。"},
    {"id": "l17_t2", "points": 15, "title": "自己追影响",
     "desc": "如果这台设备停下来整改：排在它上面的哪些工单、哪张订单受影响？整改按隐患种类的标准工时算。在首页“车间实况”和“订单与交期”里找，填在下面。",
     "hint": "设备 → 它的派工队列 → 工单 → 订单。整改时长在隐患详情里（标准工时）。"},
    {"id": "l17_t3", "points": 10, "title": "选一个处理方案并说明理由",
     "desc": "在指挥台打开这条隐患的异常，右栏有几个方案（不处理只作对照、立即停机挂牌、限时整改、停机 + 改派或加班），比较交期和花费。选一个，写理由和代价。提交以后指挥台和 AI 才显示中枢的建议。",
     "hint": "重大隐患先保安全：带着重大隐患继续生产不行；“限时整改”要说清临时措施和风险。理由里同时说到安全和交期 / 成本。"},
    {"id": "l17_t4", "points": 15, "title": "停机挂牌、整改、验收解锁",
     "desc": "在指挥台“采纳”你选的方案，生成“停机挂牌整改”动作，请老师（厂长）批准：车间里这台设备会停下，挂牌上锁许可出现在“作业许可”里。维修工整改完后，你在“隐患”里验收关闭，设备解锁恢复。",
     "hint": "要用“安全员”角色登录才能发起。整改人不能验收自己的整改。"},
    {"id": "l17_t5", "points": 10, "title": "看实际影响",
     "desc": "设备恢复后，受影响的订单现在预测能按时交吗？晚几天？",
     "hint": "首页“订单与交期”。"},
]
REPORT_POINTS = 40
BUCKETS = ["按时", "晚 1 天", "晚 2 天及以上"]
LEVELS = ["一般", "较大", "重大"]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l17_start"):
        _save(db, user, "l17_start", 0, {})


def locked(db, u, anomaly_id=None):
    """比对模式：学生开始了实验 17、还没提交任务 3 → 不显示建议和推荐理由"""
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l17_start"):
            return False
        r = _get(db, u["name"], "l17_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def _issue(db, iid):
    from hub import ehs as EH
    EH.init(db)
    try:
        iid = int(str(iid).replace("SI-", ""))
    except (TypeError, ValueError):
        return None
    return db.one("select * from safety_issue where id=%s and mode='teach'", (iid,))


def _anomaly_for(db, iid):
    return db.one("select * from anomaly where mode='teach' and rule='E1' and fkey=%s order by id desc limit 1", ("SI-{:05d}".format(iid),))


def _chosen(db, user):
    r = _get(db, user, "l17_t1")
    return (r["evidence"] or {}).get("issue_id") if r else None


def expected_hazard(db, x):
    """隐患对应的危险源：同一台设备上严重度最高的那条"""
    return db.one("select * from hazard where mode='teach' and unit=%s order by severity desc, likelihood desc, id limit 1", (x["unit"],)) if x["unit"] else None


def scope(db, x):
    """停这台设备：系统因果链里的工单、订单"""
    from hub.ont import anomaly as A
    from hub.ont import chain as CH
    sc = CH.chain_down(A.Ctx(db, "teach"), x["unit"]).scope if x["unit"] else {}
    return set(sc.get("work_orders") or []), set(sc.get("sales_orders") or [])


def answer(db, user, tid, ans, snaps=None):
    from hub import ehs as EH
    start(db, user)
    if tid == "l17_t1":
        x = _issue(db, ans.get("issue_id"))
        if x is None or x["level"] != "major":
            return {"score": 0, "of": 10, "feedback": "先选老师注入的那条重大隐患"}
        hz = expected_hazard(db, x)
        try:
            r = EH.risk(ans.get("likelihood"), ans.get("severity"))
        except (TypeError, ValueError) as e:
            return {"score": 0, "of": 10, "feedback": str(e)}
        s = 0
        if hz and ans.get("hazard_id") == hz["id"]:
            s += 4
        if hz and r["severity"] == hz["severity"]:
            s += 3
        if hz and r["likelihood"] > hz["likelihood"] and ans.get("level") == r["level"] and r["level"] == "重大":
            s += 3
        _save(db, user, tid, s, {"issue_id": x["id"], "answer": ans, "risk": r,
                                 "expected": {"hazard_id": hz["id"] if hz else None, "severity": hz["severity"] if hz else None,
                                              "likelihood_min": (hz["likelihood"] + 1) if hz else None}})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                "得 {} / 10 分。对照：危险源 {}（{}），严重度 {}；防护缺失后可能性至少 {}，风险值 ≥ 15，属于重大。".format(
                    s, hz["id"] if hz else "—", hz["name"] if hz else "—", hz["severity"] if hz else "—", (hz["likelihood"] + 1) if hz else "—")}
    if tid == "l17_t2":
        x = _issue(db, _chosen(db, user))
        if x is None:
            return {"score": 0, "of": 15, "feedback": "先完成任务 1（选定隐患）"}
        wos, sos = scope(db, x)
        my_w, my_s = set(ans.get("work_orders") or []), set(ans.get("sales_orders") or [])
        s = 5 if my_w == wos else (2 if my_w & wos else 0)
        s += 5 if my_s == sos else (2 if my_s & sos else 0)
        try:
            mins = int(ans.get("fix_minutes"))
        except (TypeError, ValueError):
            mins = None
        if mins is not None and x["fix_minutes"] and abs(mins - x["fix_minutes"]) <= 10:
            s += 5
        _save(db, user, tid, s, {"issue_id": x["id"], "answer": ans, "expected": {"work_orders": sorted(wos), "sales_orders": sorted(sos),
                                                                                    "fix_minutes": x["fix_minutes"]}})
        return {"score": s, "of": 15, "feedback": "全部正确。" if s == 15 else
                "得 {} / 15 分。对照：工单 {}，订单 {}，整改约 {} 分钟。".format(s, "、".join(sorted(wos)) or "无", "、".join(sorted(sos)) or "无",
                                                                   x["fix_minutes"])}
    if tid == "l17_t3":
        x = _issue(db, _chosen(db, user))
        if x is None:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（选定隐患）"}
        reason = str(ans.get("reason") or "").strip()
        kind = str(ans.get("option") or "")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：安全、交期、成本"}
        if kind not in ("none", "lockout", "temp", "lockout_plus"):
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        s = {"lockout": 6, "lockout_plus": 6, "temp": 4, "none": 0}[kind]
        s += 4 if any(k in reason for k in ("安全", "风险", "伤")) and any(k in reason for k in ("交期", "按时", "晚", "成本", "钱", "费")) else 2
        _save(db, user, tid, s, {"submitted": True, "issue_id": x["id"], "option": kind, "reason": reason})
        fb = "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)
        if kind == "none":
            fb += "带着重大隐患继续生产不符合安全规定。"
        elif kind == "temp":
            fb += "限时整改要有可靠的临时措施，风险比立即停机大。"
        return {"score": s, "of": 10, "feedback": fb}
    if tid == "l17_t5":
        x = _issue(db, _chosen(db, user))
        if x is None or x["status"] != "closed":
            return {"score": 0, "of": 10, "feedback": "先把隐患整改、验收关闭（设备解锁）"}
        _, sos = scope(db, x)
        ev = (_get(db, user, "l17_t2") or {}).get("evidence") or {}
        names = sos or set((ev.get("expected") or {}).get("sales_orders") or [])
        from hub import kpi
        late = 0
        for o in kpi.overview(db, None, "teach")["orders"]:
            if o["name"] in names and o.get("projected") and o.get("delivery_date"):
                late = max(late, (dt.date.fromisoformat(o["projected"][:10]) - dt.date.fromisoformat(o["delivery_date"][:10])).days)
        right = BUCKETS[0] if late <= 0 else (BUCKETS[1] if late == 1 else BUCKETS[2])
        s = 10 if ans.get("bucket") == right else 3
        _save(db, user, tid, s, {"answer": ans, "expected": right, "late": late})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "看板现在是“{}”。".format(right)}
    raise KeyError(tid)


def _my_actions(db, user):
    return db.q("select id, type, status, title, params from action where mode='teach' and initiator=%s and type in ('lockout','rectify_order','unlock') "
                "order by id", (user,))


def check(db, user):
    """自动检查任务 4：停机挂牌动作执行完 10 分；这条隐患验收关闭（解锁）再加 5 分"""
    start(db, user)
    iid = _chosen(db, user)
    acts = [a for a in _my_actions(db, user) if a["type"] == "lockout" and (not iid or int((a["params"] or {}).get("issue_id") or 0) == iid)]
    if acts:
        s = 10 if any(a["status"] == "done" for a in acts) else (6 if any(a["status"] in ("submitted", "approved", "executing") for a in acts) else 3)
        x = _issue(db, iid) if iid else None
        from hub.privacy import is_me
        if x is not None and x["status"] == "closed" and is_me(x["verified_by"], user):
            s += 5
        _save(db, user, "l17_t4", s, {"actions": [{"id": a["id"], "status": a["status"]} for a in acts],
                                      "issue_status": x["status"] if x else None})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l17_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    iid = _chosen(db, user)
    a = _anomaly_for(db, iid) if iid else None
    t3 = rows.get("l17_t3")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "issue_id": iid, "anomaly_id": a["id"] if a else None,
            "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "buckets": BUCKETS, "levels": LEVELS, "options": _options(db)}


def _options(db):
    from hub import ehs as EH
    from hub import kpi
    EH.seed(db, "teach")
    iss = db.q("select id, subject, unit, level, status from safety_issue where mode='teach' and level='major' order by id desc limit 20")
    ov = kpi.overview(db, None, "teach")
    wos = sorted({w["data"]["name"] for w in db.erp_docs("Work Order", "teach")
                  if w["data"].get("status") not in ("Completed", "Closed", "Cancelled", "Stopped")})
    return {"issues": [{"value": r["id"], "label": "SI-{:05d} {}（{}）".format(r["id"], r["subject"], EH.STATUS[r["status"]])} for r in iss],
            "hazards": [{"value": h["id"], "label": "{} {}（{}）".format(h["id"], h["name"], (h["unit"] or "").upper())}
                        for h in db.q("select id, name, unit from hazard where mode='teach' order by id")],
            "work_orders": wos, "sales_orders": [o["name"] for o in ov["orders"]],
            "option_kinds": [{"value": "none", "label": "不处理（对照）"}, {"value": "lockout", "label": "立即停机挂牌整改"},
                             {"value": "temp", "label": "限时整改（临时防护，延后停机）"}, {"value": "lockout_plus", "label": "停机整改 + 改派 / 加班"}],
            "kinds": {k: v[0] for k, v in EH.ISSUE_KINDS.items() if v[1] == "major"}}


# ---------------------------------------------------------------- 老师注入
def inject(H, u, body):
    from hub import ehs as EH
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    if body.get("kind") == "bypass":
        return EH.inject_bypass(H, "teach", body.get("unit") or "grd-01", u.get("name"))
    iid = EH.inject_major(H, "teach", body.get("unit") or "grd-01", body.get("issue_kind") or "guard", u.get("name"))
    return {"id": iid, "text": "已注入重大隐患 SI-{:05d}（{}）".format(iid, (body.get("unit") or "grd-01").upper())}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l17_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
