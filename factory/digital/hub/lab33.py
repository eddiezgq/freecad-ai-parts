# -*- coding: utf-8 -*-
"""实验 33“一张非标订单：从询价到收款”（第 139 轮 139h）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

学生在“按单设计（ETO）”页走完一张非标订单：估算 → 报价、接单 → 设计（复制为新件）、发布、倒排计划 → 下达车间、终检 →
按里程碑开票。每个任务一部分由平台按事实自动检查（auto），一部分要学生填数（q），两部分相加是这个任务的分。
学生在任务 1 填自己的作业号，后面的任务都看这张作业（换角色做也不影响）。任务编号前缀 l33_。

判定只看平台记下的事实（估算、作业状态、发布的设计、检验记录、开票记录），不经过 AI。"""
import json

TASKS = [
    {"id": "l33_t1", "points": 10, "title": "估算",
     "desc": "在“按单设计”页新建一张询价（数量 2 件，数量阶梯里也写上 2），用“AI 起草”出估算，把标着“未知”的行补齐（调整时间、单价、工时），"
             "直到估算没有未知项。然后填你的作业号和 2 件那一档的报价总额。",
     "hint": "报价 = 小计 ×（1 + 风险预留）×（1 + 加价率）。有一行未知，整张就不能报价。"},
    {"id": "l33_t2", "points": 10, "title": "报价与接单",
     "desc": "生成报价提议，请老师（厂长）确认（ERPNext 里出报价单和项目）；再点“客户接受报价”生成接单提议并确认（出销售订单，带分期付款计划）。",
     "hint": "接单提议里能看到付款计划：订金、发货、验收三期。平台自动检查，不用填。"},
    {"id": "l33_t3", "points": 15, "title": "设计与计划",
     "desc": "在“设计（物料清单与工艺）”里照估算起草，把客户要改的那个件“复制为新件”（编号以作业号开头），发布设计；再到“计划”里看倒排结果，填最早能交货的日期。",
     "hint": "发布前检查不过会列出原因。最早交货日期在计划页上方。"},
    {"id": "l33_t4", "points": 15, "title": "车间与质量",
     "desc": "在“物料”里生成算料提议并确认，在“车间与成本”里下达车间，操作工逐道开工；批准检验计划，至少做完 1 件终检并合格。然后在“车间与成本”里找实际工序成本和估算的工序成本，"
             "填“实际 − 估算”（美元，可以是负数）。",
     "hint": "车间做得越多，实际工序成本越高；填你提交那一刻页面上的数。"},
    {"id": "l33_t5", "points": 10, "title": "开票与毛利",
     "desc": "在“开票与毛利”里给订金那一期“起草发票”并确认。再试着给“发货”那一期起草发票，看平台怎么说，选出原因。",
     "hint": "分期开票只按事实：每一期的里程碑到了才能开。"},
]
REPORT_POINTS = 40
REASONS = [{"value": "milestone", "label": "这一期的里程碑（发货）还没到"},
           {"value": "amount", "label": "开票金额超过了订单金额"},
           {"value": "approver", "label": "没有人能批准开票"},
           {"value": "erp", "label": "ERPNext 暂时连不上"}]
POINTS = {t["id"]: t["points"] for t in TASKS}


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def _ev(db, user, tid):
    r = _get(db, user, tid)
    return dict(r["evidence"] or {}) if r else {}


def _put(db, user, tid, **parts):
    """任务分 = 自动检查（auto）+ 学生填的（q）；两部分分别记，取各自的最好成绩"""
    ev = _ev(db, user, tid)
    for k, v in parts.items():
        if k in ("auto", "q"):
            ev[k] = max(int(ev.get(k) or 0), int(v))
        else:
            ev[k] = v
    s = min(POINTS[tid], int(ev.get("auto") or 0) + int(ev.get("q") or 0))
    _save(db, user, tid, s, ev)
    return s


def start(db, user):
    if not _get(db, user, "l33_start"):
        _save(db, user, "l33_start", 0, {})


def job_no(db, user):
    return _ev(db, user, "l33_start").get("job_no")


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


# ---------------------------------------------------------------- 按事实的检查（纯读）
def facts(db, jn):
    """这张作业现在的事实：估算能否报价、2 件报价、接单与付款计划、发布的设计里有没有复制的新件、终检合格件数、订金开票"""
    from hub import eto as E
    from hub import eto_billing as EB
    from hub import eto_design as ED
    from hub import eto_quality as EQ
    d = E.detail(db, "teach", jn)
    if not d:
        return None
    j, res = d["job"], d["result"]
    two = next((b for b in res["breaks"] if b["qty"] == 2), None)
    rel = ED.released(db, "teach", jn)
    copied = [i["code"] for i in ((rel or {}).get("spec") or {}).get("items") or [] if i.get("from")]
    finals = [r for r in EQ.records(db, "teach", jn) if r["kind"] == "final" and r["result"] == "pass" and not r.get("voided_at")]
    ms = EB.milestones(db, "teach", jn) if j.get("sales_order") else []
    dep = [m for m in ms if m.get("on") == "order"]
    return {"job": j, "has_estimate": bool(d["estimate"]), "can_quote": res["can_quote"], "unknown": res["unknown"] + res["errors"],
            "price_2": two["price"] if two else None, "has_2": bool(two),
            "ordered": bool(j.get("sales_order")), "schedule": len(EB.schedule_of(db, "teach", j)) if j.get("sales_order") else 0,
            "released": bool(rel), "copied": copied,
            "final_pass": len({(r["work_order"], r["piece"]) for r in finals}),
            "deposit_invoiced": bool(dep) and all(m["state"] == "invoiced" for m in dep)}


def auto_scores(f, ops_actual):
    """纯函数：各任务按事实的自动分。ops_actual：实际工序成本（美元，没有为 0）"""
    if not f:
        return {}
    return {"l33_t1": 5 if f["can_quote"] else 0,
            "l33_t2": (5 if f["ordered"] else 0) + (5 if f["schedule"] else 0),
            "l33_t3": 8 if f["released"] and f["copied"] else 0,
            "l33_t4": (5 if ops_actual > 0 else 0) + (5 if f["final_pass"] >= 1 else 0),
            "l33_t5": 6 if f["deposit_invoiced"] else 0}


def _ops(db, jn):
    """作业成本里的工序：实际、估算（估算没报过价时为 None）"""
    from hub import eto_exec as EX
    c = EX.cost(db, "teach", jn)
    return float(c["actual"].get("operations") or 0), (c.get("estimate") or {}).get("operations")


# ---------------------------------------------------------------- 学生填的
def answer(db, user, tid, ans):
    from hub import eto as E
    from hub import eto_plan as EP
    start(db, user)
    if tid == "l33_t1":
        jn = str(ans.get("job_no") or "").strip().upper()
        if not jn or not E.job(db, "teach", jn):
            return {"score": 0, "of": 10, "feedback": "没有作业 {}：在“按单设计”页新建询价后，把作业号（如 JOB-2026-0001）填进来".format(jn or "")}
        _save(db, user, "l33_start", 0, dict(_ev(db, user, "l33_start"), job_no=jn))
        refresh(db, user)
        f = facts(db, jn)
        if not f["can_quote"]:
            s = _put(db, user, tid, job_no=jn)
            return {"score": s, "of": 10, "feedback": "记下了作业 {}。估算还有未知项，不能报价：{}".format(jn, "；".join(f["unknown"][:3]))}
        if not f["has_2"]:
            s = _put(db, user, tid, auto=5, job_no=jn)
            return {"score": s, "of": 10, "feedback": "数量阶梯里没有 2 件这一档：改询价的数量阶梯后再填"}
        p = _num(ans.get("price"))
        if p is None:
            return {"score": _put(db, user, tid, auto=5, job_no=jn), "of": 10, "feedback": "报价总额填数字（美元）"}
        ok = abs(p - f["price_2"]) <= 0.01
        s = _put(db, user, tid, auto=5, q=5 if ok else 0, job_no=jn, answer=p, expected=f["price_2"])
        return {"score": s, "of": 10, "feedback": "正确。" if ok else "平台算的 2 件报价是 ${:,.2f}：对照估算表的小计、风险预留、加价率再算一遍。".format(f["price_2"])}
    jn = job_no(db, user)
    if not jn:
        return {"score": 0, "of": POINTS.get(tid, 0), "feedback": "先在任务 1 填你的作业号"}
    refresh(db, user)                       # 先按事实把自动部分记上，答题反馈里的分数才是这个任务的总分
    if tid == "l33_t3":
        try:
            want = EP.schedule(db, "teach", jn)["earliest"]
        except E.EtoError as e:
            return {"score": 0, "of": 15, "feedback": str(e)}
        got = str(ans.get("earliest") or "").strip()[:10]
        ok = got == want
        s = _put(db, user, tid, q=7 if ok else 0, answer=got, expected=want)
        return {"score": s, "of": 15, "feedback": "正确。" if ok else "计划页上算的最早交货日是 {}。".format(want)}
    if tid == "l33_t4":
        act, est = _ops(db, jn)
        if est is None:
            return {"score": 0, "of": 15, "feedback": "这张作业还没报价，没有估算的工序成本"}
        if act <= 0:
            return {"score": 0, "of": 15, "feedback": "车间还没报工，实际工序成本是 0：先让操作工开工"}
        v = _num(ans.get("diff"))
        if v is None:
            return {"score": 0, "of": 15, "feedback": "填数字（美元，实际 − 估算，可以是负数）"}
        want = round(act - est, 2)
        ok = abs(v - want) <= max(1.0, abs(est) * 0.02)
        s = _put(db, user, tid, q=5 if ok else 0, answer=v, expected=want, actual=round(act, 2), estimate=est)
        return {"score": s, "of": 15, "feedback": "正确。" if ok else "现在实际 ${:,.2f}、估算 ${:,.2f}，差 ${:,.2f}。".format(act, est, want)}
    if tid == "l33_t5":
        r = ans.get("reason")
        if r not in [x["value"] for x in REASONS]:
            return {"score": 0, "of": 10, "feedback": "选一个原因"}
        ok = r == "milestone"
        s = _put(db, user, tid, q=4 if ok else 0, answer=r)
        return {"score": s, "of": 10, "feedback": "正确：分期开票按事实，发货那一期要等发货单出来。" if ok else "再去点一下“开票”，看平台给的原因。"}
    raise KeyError(tid)


def refresh(db, user):
    """自动部分：按这张作业现在的事实重算（只升不降）"""
    jn = job_no(db, user)
    if jn:
        f = facts(db, jn)
        try:
            ops = _ops(db, jn)[0] if f and f["ordered"] else 0.0
        except Exception:  # noqa: BLE001  成本还算不出来（例如还没工单）：工序这项当 0
            ops = 0.0
        for tid, a in auto_scores(f, ops).items():
            if a > int(_ev(db, user, tid).get("auto") or 0):
                _put(db, user, tid, auto=a)


def check(db, user):
    start(db, user)
    refresh(db, user)
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l33_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    return {"user": user, "job_no": job_no(db, user), "tasks": tasks, "score": sum(t["score"] for t in tasks),
            "of": sum(t["points"] for t in TASKS), "report_points": REPORT_POINTS, "reasons": REASONS}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l33_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
