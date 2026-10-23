# -*- coding: utf-8 -*-
"""实验 20“供应链：来料不合格与供应商选择”（第 18 轮 E5-8）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：学生看供应商评分卡，找出单一来源的物料类别 → 老师向五大湖轴承下一张 BRG-6207 的单，注入“这一批不合格”，到货后留给学生 →
学生（质量角色）看抽样数据，判定合格 / 不合格，数超差的件 → 在指挥台比较“退货等补发 / 备选急单 / 让步接收 / 不处理”（比对模式）→
执行，批准后这一批不再卡着 → 算默认和备选两家轴承供应商的每件总拥有成本。评分依据平台里的事实。任务编号前缀 l20_。"""
import json

TASKS = [
    {"id": "l20_t1", "points": 10, "title": "找单一来源",
     "desc": "在“采购与来料 → 供应商”里看评分卡：哪几类物料只有一家在用的供应商？全部勾上提交。",
     "hint": "备选供应商“未启用”的不算在用。"},
    {"id": "l20_t2", "points": 15, "title": "来料检验",
     "desc": "老师注入的那一批轴承到货后，在“采购与来料 → 到货与检验”里打开它，看抽样数据（量具读数），按检验模板判定合格还是不合格并提交；在这里填有几处超差。",
     "hint": "要用“质量”角色登录。每件每一项都要在上下限之内，一处超差整批不合格。"},
    {"id": "l20_t3", "points": 10, "title": "比较方案，选一个",
     "desc": "在指挥台打开“来料检验不合格”异常，右栏四个方案：退货等补发 / 向备选供应商下急单 / 让步接收全检 / 不处理（对照）。比较到料日、交期和花费，选一个写理由。提交后才显示中枢的建议。",
     "hint": "轴承是关键件：让步接收要全检、要质量批；备选贵但快；退货不花钱但要等。"},
    {"id": "l20_t4", "points": 15, "title": "执行",
     "desc": "在指挥台采纳你选的方案，生成动作，请老师（或质量、计划员）批准。批准后这一批不再是“不合格待处理”。",
     "hint": "退货、采购单由计划员或质量发起；让步接收要质量或厂长批准。"},
    {"id": "l20_t5", "points": 10, "title": "总拥有成本",
     "desc": "用评分卡上的单价、价格指数和过去一年的准时率、合格率，算两家轴承供应商每件 BRG-6207 的总拥有成本：单价 × 价格指数 + (1 − 合格率) × $4 + (1 − 准时率) × $3。",
     "hint": "BRG-6207 单价 $8。两家都算，保留两位小数。"},
]
REPORT_POINTS = 40
OPTIONS = [{"value": "return", "label": "退货等补发"}, {"value": "alt", "label": "备选供应商急单"}, {"value": "concession", "label": "让步接收全检"},
           {"value": "none", "label": "不处理（对照）"}]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l20_start"):
        _save(db, user, "l20_start", 0, {})


def locked(db, u, anomaly_id=None):
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l20_start"):
            return False
        r = _get(db, u["name"], "l20_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def target(db):
    """老师注入的那一批"""
    from hub import supply as SP
    t = SP._state(db, "teach").get("lab20")
    if not t:
        return None
    x = db.one("select * from lot where id=%s", (t["lot_id"],))
    return dict(t, lot=x) if x else None


def answer(db, user, tid, ans):
    from hub import supply as SP
    start(db, user)
    if tid == "l20_t1":
        want = {x["cat"] for x in SP.single_source(db, "teach")}
        got = {str(x) for x in ans.get("cats") or []}
        s = max(0, round(10 * (len(got & want) - len(got - want)) / len(want))) if want else 0
        _save(db, user, tid, s, {"answer": sorted(got), "expected": sorted(want)})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else "得 {} / 10 分（多选的倒扣）。".format(s)}
    if tid == "l20_t2":
        t = target(db)
        if not t or t["lot"]["status"] in ("ordered", "transit"):
            return {"score": 0, "of": 15, "feedback": "那一批还没到货"}
        bad = len(SP.judge(SP.sample(db, "teach", t["lot_id"])))
        try:
            n = int(ans.get("bad_count"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 15, "feedback": "填超差的处数"}
        s = 5 if n == bad else 0
        ev = {"bad_count": n, "expected": bad}
        x = t["lot"]
        if x["inspected_by"] == user:
            right = (x["status"] == "rejected") == bool(bad) or (x["status"] in ("returned",) and bad)
            s += 10 if right else 0
            ev["judged"] = x["status"]
        _save(db, user, tid, s, ev)
        return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else "得 {} / 15 分。平台的抽样里有 {} 处超差{}。".format(
            s, bad, "" if x["inspected_by"] == user else "；判定要你自己在“到货与检验”里提交")}
    if tid == "l20_t3":
        t = target(db)
        if not t:
            return {"score": 0, "of": 10, "feedback": "老师还没有注入"}
        reason = str(ans.get("reason") or "").strip()
        kind = ans.get("option")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：到料日、交期、花费、质量风险"}
        if kind not in ("return", "alt", "concession", "none"):
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        best = (SP._state(db, "teach").get("recommended") or {}).get(str(t["lot_id"])) or "return"
        s = 6 if kind == best else (4 if kind != "none" else 2)
        s += 4 if any(k in reason for k in ("交期", "订单", "到料", "等")) and any(k in reason for k in ("钱", "费", "成本", "$", "贵", "质量", "风险")) else 2
        _save(db, user, tid, s, {"submitted": True, "option": kind, "reason": reason, "system": best})
        return {"score": s, "of": 10, "feedback": "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)}
    if tid == "l20_t5":
        sc = {x["role"]: x for x in SP.scorecard(db, "teach") if x["cat"] == "bearings"}
        exp = {k: SP.tco(SP.price_of("BRG-6207"), v["price_index"], v["hist_on_time"], v["hist_pass"]) for k, v in sc.items()}
        s = 0
        try:
            for k, f in (("default", "tco_default"), ("alt", "tco_alt")):
                if k in exp and abs(float(ans.get(f)) - exp[k]) <= max(0.02, exp[k] * 0.02):
                    s += 5
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填数字"}
        _save(db, user, tid, s, {"answer": ans, "expected": exp})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "平台算的：默认 ${:.2f}，备选 ${:.2f}。".format(exp.get("default", 0), exp.get("alt", 0))}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 4：这一批的退货 / 让步接收 / 采购单动作 5 → 执行 10 → 这一批不再是“不合格” +5"""
    start(db, user)
    t = target(db)
    if t:
        acts = db.q("select id, type, status, params from action where mode='teach' and initiator=%s and type in "
                    "('supplier_return','concession','purchase_order','alt_supplier') order by id", (user,))
        mine = [a for a in acts if str(a["params"].get("lot_id")) == str(t["lot_id"]) or
                (a["type"] == "purchase_order" and any(i.get("item_code") == t["item"] for i in a["params"].get("items") or []))]
        if mine:
            s = 10 if any(a["status"] in ("done", "executing") for a in mine) else (5 if any(a["status"] in ("submitted", "approved") for a in mine) else 2)
            x = db.one("select status from lot where id=%s", (t["lot_id"],))
            if s == 10 and x and x["status"] != "rejected":
                s += 5
            _save(db, user, "l20_t4", s, {"actions": [{"id": a["id"], "type": a["type"], "status": a["status"]} for a in mine], "lot": x["status"] if x else None})
    return status(db, user)


def status(db, user):
    from hub import supply as SP
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l20_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    tg = target(db)
    a = db.one("select id from anomaly where mode='teach' and rule='W3' and fkey=%s order by id desc limit 1", (tg["lot"]["lot"],)) \
        if tg and tg["lot"]["lot"] else None
    t3 = rows.get("l20_t3")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "anomaly_id": a["id"] if a else None,
            "target": {"lot_id": tg["lot_id"], "lot": tg["lot"]["lot"], "item": tg["item"], "supplier": tg["supplier"],
                       "status": SP.STATUS.get(tg["lot"]["status"])} if tg else None,
            "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "options": OPTIONS, "enabled": SP.enabled(db, "teach"),
            "cats": [{"value": k, "label": v} for k, v in SP.CAT_NAME.items()],
            "suppliers": [{"value": p["supplier"], "label": p["supplier"]} for p in SP.profiles(db, "teach") if p["role"] == "default"]}


def inject(H, u, body):
    """老师：打开供应商模拟器；向某家下一张单并注入“这一批不合格”（默认五大湖轴承 BRG-6207 × 40）"""
    from factory import data as F
    from hub import supply as SP
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    SP.set_enabled(H.db, "teach", True if body.get("enable") is None else bool(body.get("enable")))
    if body.get("only_toggle"):
        return {"text": "供应商模拟器已{}".format("打开" if SP.enabled(H.db, "teach") else "关闭")}
    sup = body.get("supplier") or F.SUPPLIERS["bearings"]["name"]
    return SP.inject(H, "teach", sup, u.get("name"), late_days=body.get("late_days"), bad=bool(body.get("bad", True)),
                     item=body.get("item") or "BRG-6207", qty=body.get("qty") or 40)


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l20_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
