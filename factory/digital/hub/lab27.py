# -*- coding: utf-8 -*-
"""实验 27“两厂之间的一张订单”（第 57 轮，机器人厂）：六个任务的自动评分（60 分）+ 报告（40 分）。

学生是机器人厂的计划员兼采购员：接 2 台 AGV → 算料（WQR-105 要不要请购、请购几台）→ 请购转采购单、送到问渠减速器厂（第 51 轮的
工业园订单）→ 减速器厂接单生产、发货 → 到货、来料检验入库 → 算交期；再做一道安全库存与订货点的计算题、一道复盘选择题。
评分只看机器人厂自己的数据（订单、请购、批次），不看减速器厂内部。任务成绩编号加前缀 l27_。"""
import json
import math
import zlib

from hub import supply as SP

PRODUCT = "WQ-AGV300"
PART = "WQR-105"
QTY = 2
Z95 = 1.65
TASKS = [
    {"id": "l27_t1", "points": 10, "title": "接 2 台 AGV、算料",
     "desc": "以计划员身份在“订单与计划”接 2 台 WQ-AGV300（客户、交期自定），算料后提交。WQR-105 要请购几台？",
     "hint": "净需求 = 毛需求 + 其他订单占用 + 安全库存 − 库存 − 在途，大于 0 才请购，按采购批量（10 台）向上取整。"},
    {"id": "l27_t2", "points": 10, "title": "采购单送到减速器厂",
     "desc": "请购单转成采购单（自己在“采购与来料”里转，或等 3 分钟采购员模拟器转），平台把它送到问渠减速器厂。填对方的工业园订单号。",
     "hint": "“采购与来料”里 WQR-105 那一行的状态后面写着“工业园订单 N”。"},
    {"id": "l27_t3", "points": 10, "title": "到货、来料检验、入库",
     "desc": "减速器厂做完发货，这一批在途约 2 分钟后到货。用质检员身份检验（噪声、渗漏），合格入库。数据到了自动打勾。",
     "hint": "3 分钟没人检验，质检员模拟器会检验；自己检验更好。"},
    {"id": "l27_t4", "points": 10, "title": "交期：用了几天",
     "desc": "从采购单发出到到货，用了几天（教学时间：1 天 = 2 分钟）？比承诺的提前期（10 天）早还是晚？",
     "hint": "批次一行的下单时间、到货时间相减，除以 2 分钟。"},
    {"id": "l27_t5", "points": 10, "title": "安全库存与订货点",
     "desc": "实验页给你一组 WQR-105 的日需求（均值、标准差）和减速器厂的提前期。服务水平 95%（z = 1.65），算安全库存和订货点。",
     "hint": "安全库存 SS = z·σ_d·√L；订货点 ROP = d·L + SS。"},
    {"id": "l27_t6", "points": 10, "title": "复盘：两厂共享需求信息",
     "desc": "如果机器人厂把每周的 AGV 需求预测直接共享给减速器厂，最主要的好处是什么？",
     "hint": "想想需求波动沿供应链往上游传时会怎样。"},
]
REPORT_POINTS = 40
T6_CHOICES = [
    ("bullwhip", "减速器厂提前看到真实需求，可以提前排产、少备库存，需求波动不再沿供应链逐级放大（牛鞭效应）"),
    ("price", "减速器厂可以按需求涨价"),
    ("none", "没有好处：各厂管好自己的库存就行"),
]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def _j(v):
    return v if isinstance(v, (dict, list)) or v is None else json.loads(v)


def my_order(db, user):
    """学生最近一张已执行的 AGV 接单提议：销售订单、请购单、算料里 WQR-105 的请购数量"""
    rows = db.q("select proposal_id, preview, result, created_at from ai_proposal where mode='teach' and action='create_order_and_plan' "
                "and status='executed' and requested_by=%s order by created_at desc limit 20", (user,))
    for r in rows:
        pv = _j(r["preview"]) or {}
        so = pv.get("sales_order") or {}
        if so.get("item_code") != PRODUCT:
            continue
        created = (_j(r["result"]) or {}).get("created") or []
        mrq = sum(float(m["qty"]) for m in pv.get("material_requests") or [] if m["item_code"] == PART)
        return {"proposal_id": r["proposal_id"], "qty": so.get("qty"), "sales_order": next((n for d, n in created if d == "Sales Order"), None),
                "material_request": next((n for d, n in created if d == "Material Request"), None), "wqr_request": mrq,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None}
    return None


def my_lot(db, order):
    """这张订单的请购单转出的 WQR-105 批次（最新一行）；这张请购单里没有 WQR-105（库存、在途够了）时，
    取接单之后下的第一批 WQR-105（同一个学生后面的订单补的货）"""
    if not order:
        return None
    SP.init(db)
    x = None
    if order.get("material_request"):
        x = db.one("select * from lot where mode='teach' and item=%s and mr=%s order by id desc limit 1", (PART, order["material_request"]))
    if not x and order.get("created_at"):
        x = db.one("select * from lot where mode='teach' and item=%s and ordered_at >= %s order by id limit 1", (PART, order["created_at"]))
    return SP._lot_row(x) if x else None


def lot_days(x):
    """下单到到货的教学天数（1 天 = DAY_S 秒）"""
    if not x or not x.get("arrived_at"):
        return None
    import datetime as dt
    a, o = dt.datetime.fromisoformat(x["arrived_at"]), dt.datetime.fromisoformat(x["ordered_at"])
    return round((a - o).total_seconds() / SP.DAY_S, 1)


def demand(user):
    """任务 5 的数据（每个学生不同，示例值）：日需求均值 d、标准差 σ_d（台/天）、提前期 L（天）"""
    h = zlib.crc32(("lab27|" + user).encode())
    d = 2 + (h % 5)                      # 2–6 台/天
    sd = round(0.5 + ((h >> 4) % 16) / 10, 1)     # 0.5–2.0
    lead = 10
    ss = Z95 * sd * math.sqrt(lead)
    return {"d": d, "sigma_d": sd, "lead_days": lead, "z": Z95, "ss": round(ss, 2), "rop": round(d * lead + ss, 2)}


def answer(db, user, tid, ans):
    order = my_order(db, user)
    if tid == "l27_t1":
        if not order:
            return {"score": 0, "of": 10, "feedback": "先接 2 台 WQ-AGV300、算料、提交并确认"}
        try:
            v = float(ans.get("qty"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填请购台数"}
        s = (5 if order["qty"] == QTY else 0) + (5 if abs(v - order["wqr_request"]) < 1e-6 else 0)
        _save(db, user, tid, s, {"order": order, "answer": v})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                ("订单数量要 2 台。" if order["qty"] != QTY else "再看算料表里 WQR-105 那一行的净需求和动作。")}
    if tid == "l27_t2":
        x = my_lot(db, order)
        park = (x or {}).get("park") or {}
        if not x or park.get("state") not in ("sent", "shipped"):
            return {"score": 0, "of": 10, "feedback": "WQR-105 的采购单还没送到减速器厂（先转采购单，等采购单进 ERPNext）"}
        s = 10 if str(ans.get("order") or "").strip().lstrip("#") == str(park.get("order")) else 5
        _save(db, user, tid, s, {"lot": x["id"], "po": x["po"], "park_order": park.get("order"), "answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "采购单送到了；订单号再核对一下（批次一行的说明里）。"}
    if tid == "l27_t4":
        x = my_lot(db, order)
        days = lot_days(x)
        if days is None:
            return {"score": 0, "of": 10, "feedback": "这一批还没到货"}
        try:
            v = float(ans.get("days"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填天数"}
        on_time = days <= 10
        s = (5 if abs(v - days) <= 0.5 else 0) + (5 if bool(ans.get("on_time")) == on_time else 0)
        _save(db, user, tid, s, {"lot": x["id"], "days": days, "answer": ans})
        return {"score": s, "of": 10, "feedback": "正确（{:g} 天）。".format(days) if s == 10 else "用到货时间减下单时间，除以 2 分钟；和 10 天比。"}
    if tid == "l27_t5":
        dm = demand(user)
        try:
            ss, rop = float(ans.get("ss")), float(ans.get("rop"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填安全库存和订货点"}
        s = (5 if abs(ss - dm["ss"]) <= 0.01 * dm["ss"] + 0.01 else 0) + (5 if abs(rop - dm["rop"]) <= 0.01 * dm["rop"] else 0)
        _save(db, user, tid, s, {"data": dm, "answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "SS = 1.65 × σ_d × √L；ROP = d × L + SS。"}
    if tid == "l27_t6":
        s = 10 if ans.get("choice") == "bullwhip" else 0
        _save(db, user, tid, s, {"answer": ans})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "再想想：下游的订单是上游唯一看得到的需求信号。"}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 3：这一批合格入库"""
    x = my_lot(db, my_order(db, user))
    if x and x["status"] == "accepted":
        _save(db, user, "l27_t3", 10, {"lot": x["lot"], "inspection": (x.get("inspection") or {}).get("status")})


def status(db, user):
    check(db, user)
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l27_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    order = my_order(db, user)
    x = my_lot(db, order)
    dm = demand(user)
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "order": order, "lot": x, "lot_days": lot_days(x),
            "demand": {k: dm[k] for k in ("d", "sigma_d", "lead_days", "z")},
            "t6_choices": [{"value": k, "label": v} for k, v in T6_CHOICES]}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l27_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
