# -*- coding: utf-8 -*-
"""实验 22“经营：订单毛利、应收与现金”（第 18 轮 E7-10）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：学生在指标树里找没达标的经营指标 → 按分解表算一张做完的订单的毛利率，找出料以外花得最多的一项 →
老师注入“某客户一笔发票逾期不付”→ 比较“发催款函 / 信用冻结 / 不处理”（比对模式，看现金流预测）→ 执行，客户付款 →
算应收周转天数，找现金最紧的一周。任务编号前缀 l22_。"""
import json

TASKS = [
    {"id": "l22_t1", "points": 10, "title": "找没达标的经营指标",
     "desc": "在“经营与财务 → 经营目标”里看指标树，把现在没达标（黄或红）的指标全部勾上提交。",
     "hint": "指标的数取自各领域态势卡；方向看“≥”还是“≤”。"},
    {"id": "l22_t2", "points": 15, "title": "一张订单的毛利",
     "desc": "在“订单毛利”里打开老师指定的订单（没指定就选第一张），按分解表算毛利率 =（收入 − 各项成本）÷ 收入；再找出“料”以外花得最多的一项。",
     "hint": "毛利率填百分数（如 27.9）。分解里每一项都写了来源：实测还是标准。"},
    {"id": "l22_t3", "points": 10, "title": "比较方案，选一个",
     "desc": "老师注入后，在指挥台打开这笔“应收逾期”异常，右栏三个方案：发催款函 / 信用冻结 / 不处理（对照）。看每个方案预计几天收到钱、现金流最低在哪一周。选一个写理由。提交后才显示中枢的建议。",
     "hint": "逾期不长先催；逾期太久或欠得太多才冻结。冻结会影响他在做的订单发货。"},
    {"id": "l22_t4", "points": 15, "title": "执行",
     "desc": "在指挥台采纳你选的方案，生成动作（催款或信用冻结），请老师（厂长）或销售批准。客户收到催款后几天内付款，这笔应收清零。",
     "hint": "催款由销售、计划员或厂长发起，销售或厂长批准。"},
    {"id": "l22_t5", "points": 10, "title": "应收周转与现金",
     "desc": "应收周转天数（DSO）= 应收余额 ÷ 近 30 天日均开票额。在“应收应付”里找到这两个数算一算；再看现金流预测，现金最紧的是第几周。",
     "hint": "天数都是“账期日”：教学模式 1 天 = 真实 2 分钟。"},
]
REPORT_POINTS = 40
OPTIONS = [{"value": "dunning", "label": "发催款函"}, {"value": "hold", "label": "信用冻结"}, {"value": "none", "label": "不处理（对照）"}]
COSTS = [{"value": "labor", "label": "工（折旧 + 人工）"}, {"value": "energy", "label": "电"}, {"value": "idle", "label": "空转电（分摊）"}, {"value": "scrap", "label": "废品返工"},
         {"value": "actions", "label": "急单、加班、外协、加急"}, {"value": "warranty", "label": "保修"}]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l22_start"):
        _save(db, user, "l22_start", 0, {})


def locked(db, u, anomaly_id=None):
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l22_start"):
            return False
        r = _get(db, u["name"], "l22_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def lab(db):
    from hub import finance as FN
    return FN._state(db, "teach").get("lab22") or {}


def target_so(db):
    from hub import finance as FN
    so = lab(db).get("sales_order")
    if so:
        return so
    ms = FN.margins(db, "teach")
    return sorted(m["sales_order"] for m in ms)[0] if ms else None


def target(db):
    """老师注入的那笔应收和它的异常"""
    lb = lab(db)
    if not lb.get("invoice_id"):
        return None
    x = db.one("select * from invoice where id=%s", (lb["invoice_id"],))
    a = db.one("select id from anomaly where mode='teach' and rule='F2' and fkey=%s order by id desc limit 1", ("INV-{:05d}".format(lb["invoice_id"]),))
    return {"invoice": x, "anomaly_id": a["id"] if a else None}


def answer(db, user, tid, ans):
    from hub import finance as FN
    start(db, user)
    if tid == "l22_t1":
        want = {o["code"] for o in FN.objectives(db, "teach") if o["tone"] in ("warn", "bad")}
        got = {str(x) for x in ans.get("codes") or []}
        s = 10 if got == want else max(0, round(10 * (len(got & want) - len(got - want)) / max(1, len(want))))
        _save(db, user, tid, s, {"answer": sorted(got), "expected": sorted(want)})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else "得 {} / 10 分（多选的倒扣）。".format(s)}
    if tid == "l22_t2":
        so = target_so(db)
        if not so:
            return {"score": 0, "of": 15, "feedback": "还没有做完的订单"}
        m = FN.margin(db, "teach", so, store=False)
        top = max([x for x in m["lines"] if x["key"] != "material"], key=lambda x: x["usd"])["key"]
        s = 0
        try:
            if abs(float(ans.get("margin_pct")) - m["margin_pct"] * 100) <= 1.0:
                s += 8
        except (TypeError, ValueError):
            return {"score": 0, "of": 15, "feedback": "毛利率填数字（百分数）"}
        if ans.get("top") == top:
            s += 7
        _save(db, user, tid, s, {"answer": ans, "expected": {"sales_order": so, "margin_pct": round(m["margin_pct"] * 100, 2), "top": top}})
        return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else "得 {} / 15 分：{} 毛利率 {:.1%}，料以外最多的是“{}”。".format(
            s, so, m["margin_pct"], next(x["label"] for x in m["lines"] if x["key"] == top))}
    if tid == "l22_t3":
        t = target(db)
        if not t or not t["anomaly_id"]:
            return {"score": 0, "of": 10, "feedback": "老师还没有注入，或者厂情中枢还没报出这笔逾期（20 秒内会报）"}
        reason = str(ans.get("reason") or "").strip()
        kind = ans.get("option")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：几天收到钱、现金、客户关系"}
        if kind not in [o["value"] for o in OPTIONS]:
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        best = (FN._state(db, "teach").get("recommended") or {}).get(str(t["anomaly_id"])) or "dunning"
        s = 6 if kind == best else (4 if kind != "none" else 2)
        s += 4 if any(k in reason for k in ("现金", "收", "钱", "$", "款")) and any(k in reason for k in ("关系", "客户", "发货", "订单")) else 2
        _save(db, user, tid, s, {"submitted": True, "option": kind, "reason": reason, "system": best, "anomaly_id": t["anomaly_id"]})
        return {"score": s, "of": 10, "feedback": "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)}
    if tid == "l22_t5":
        d = FN.dso(db, "teach")
        cf = FN.cashflow(db, "teach")
        s = 0
        try:
            if d is not None and abs(float(ans.get("dso")) - d) <= max(1.0, d * 0.05):
                s += 6
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填数字"}
        if str(ans.get("low_week")) == str(cf["low"]["week"]):
            s += 4
        _save(db, user, tid, s, {"answer": ans, "expected": {"dso": d, "low_week": cf["low"]["week"]}})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "平台算的：DSO {} 天，现金最紧在第 {} 周。".format(d, cf["low"]["week"])}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 4：催款 / 信用冻结动作 已提交 5 / 已执行 10；这笔应收付清了 +5"""
    start(db, user)
    t = target(db)
    if t and t["invoice"]:
        inv = t["invoice"]
        acts = db.q("select id, type, status, params from action where mode='teach' and initiator=%s and type in ('dunning','credit_hold') order by id", (user,))
        mine = [a for a in acts if (a["type"] == "dunning" and str(a["params"].get("invoice_id")) == str(inv["id"])) or
                (a["type"] == "credit_hold" and a["params"].get("customer") == inv["party"])]
        if mine:
            s = 10 if any(a["status"] in ("done", "executing") for a in mine) else (5 if any(a["status"] in ("submitted", "approved") for a in mine) else 2)
            x = db.one("select status from invoice where id=%s", (inv["id"],))
            if s == 10 and x and x["status"] == "paid":
                s += 5
            _save(db, user, "l22_t4", s, {"actions": [{"id": a["id"], "type": a["type"], "status": a["status"]} for a in mine], "invoice": x["status"] if x else None})
    return status(db, user)


def status(db, user):
    from hub import finance as FN
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l22_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    tg = target(db)
    t3 = rows.get("l22_t3")
    inv = tg["invoice"] if tg else None
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "anomaly_id": tg["anomaly_id"] if tg else None,
            "target": {"invoice_id": inv["id"], "customer": inv["party"], "amount": inv["amount"], "status": FN.STATUS.get(inv["status"])} if inv else None,
            "sales_order": target_so(db), "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "options": OPTIONS, "costs": COSTS,
            "objectives": [{"value": o["code"], "label": o["name"]} for o in FN.objectives(db, "teach")], "sim": FN.sim_on(db, "teach")}


def inject(H, u, body):
    """老师：打开财务模拟器；某客户（默认海港起重）一笔发票逾期 15 天、不催就不付；可以指定任务 2 的订单"""
    from hub import finance as FN
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    FN.set_sim(H.db, "teach", True if body.get("enable") is None else bool(body.get("enable")))
    if body.get("only_toggle"):
        return {"text": "财务模拟器已{}".format("打开" if FN.sim_on(H.db, "teach") else "关闭")}
    r = FN.inject(H, "teach", body.get("customer"), u.get("name") or "老师", body.get("days") or 15, body.get("qty") or 8)
    if body.get("sales_order"):
        FN._patch(H.db, "teach", {"lab22": dict(FN._state(H.db, "teach").get("lab22") or {}, sales_order=body["sales_order"])})
    return dict(r, text=r["text"] + "；20 秒内厂情中枢出“应收逾期”")


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l22_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
