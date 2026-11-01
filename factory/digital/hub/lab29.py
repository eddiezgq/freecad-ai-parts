# -*- coding: utf-8 -*-
"""实验 29“一台机器人的售后追溯”（第 68 轮，机器人厂）：六个任务的自动评分（60 分）+ 报告（40 分）。

学生是售后工程师兼质量工程师。平台给每个学生“种”一个场景（hub/rfield.py 的现场机器人）：一批有问题的谐波减速器装在 3 台机器人的 J2 上，
1 台用得久、背隙已超上限，另 2 台出厂不久、还在上限以内（每个学生的批号、序列号不同）。学生要：① 找出报警的那台和关节；② 读出厂档案
（批号、出厂背隙）；③ 判原因；④ 定召回范围（同批还装在哪几台）；⑤ 派对症的服务工单并做完（数据到了自动打勾）；⑥ 算账：同批全部预防性
更换 vs 等报警了再换。场景、费用、损失都是示例值。任务成绩编号加前缀 l29_。"""
import datetime as dt
import json
import zlib

from psycopg.types.json import Jsonb

from hub import rfield as RF

MODE = "teach"
JOINT = "J2"
RISE = (0.45, 0.12, 0.06)                 # 三台的 J2 背隙比出厂涨了多少（arcmin）：第 1 台超限，另两台还没（按客户现场的强度折算成出厂天数）
LOSS_PER_COMPLAINT = 1500.0               # 等报警了再换：每次投诉客户停线、加急的损失（示例值，$）
TASKS = [
    {"id": "l29_t1", "points": 10, "title": "找出报警的机器人和关节",
     "desc": "在“客户与服务 → 现场的机器人”或厂情中枢的报警里，找出你这批场景里背隙超了上限的那台机器人和关节。",
     "hint": "看“健康”为红、原因写着“背隙超过上限”的那一行；序列号以 WQ-CR5-L29 开头的是你的场景。"},
    {"id": "l29_t2", "points": 10, "title": "读出厂档案",
     "desc": "点开这台机器人，在“出厂档案”里读出这个关节用的谐波减速器批号和出厂背隙。",
     "hint": "出厂档案一行一个关节：关节序列号、减速器批次、出厂背隙、现在的背隙。"},
    {"id": "l29_t3", "points": 10, "title": "判断原因",
     "desc": "这个关节的背隙为什么超了？",
     "hint": "比一比：出厂多久、背隙涨得多快、同批的别的机器人怎样。"},
    {"id": "l29_t4", "points": 10, "title": "定召回范围",
     "desc": "同一批减速器还装在哪几台机器人上？填它们的序列号（不含已经报警的那台也可以）。",
     "hint": "出厂档案里“同批还装在”一列；或者在厂情中枢看“同批减速器多台报警”。"},
    {"id": "l29_t5", "points": 10, "title": "派工并做完",
     "desc": "给报警的那台派对症的服务工单，工程师做完后背隙复位。数据到了自动打勾。",
     "hint": "背隙超限：上门换关节模组（选对关节）。到日子工程师会做完，也可以点“做完”。"},
    {"id": "l29_t6", "points": 10, "title": "算一笔账",
     "desc": "同批 3 台：A 现在全部预防性更换；B 等它们一台台报警了再换（每次另加客户停线等损失 $1,500，示例值）。A、B 各花多少？",
     "hint": "一次上门换关节模组 = 人工 + 差旅 + 备件（大关节 WQJ-L 的售价）。"},
]
REPORT_POINTS = 40
T3_CHOICES = [
    ("bad_lot", "这批谐波减速器有问题，磨得快：出厂不久背隙就涨得比正常快，同批的别的机器人也在涨"),
    ("age", "用得太久，正常磨损到了寿命"),
    ("lube", "润滑脂老化"),
    ("collision", "撞过一次，零位偏了"),
]


def _code(user):
    return "{:04X}".format(zlib.crc32(("lab29|" + user).encode()) % 0xFFFF)


def case(user):
    c = _code(user)
    return {"code": c, "lot": "HD-L-L29-" + c, "serials": ["WQ-CR5-L29-{}-{}".format(c, i + 1) for i in range(3)],
            "customer_idx": zlib.crc32(c.encode()) % 3}


def seed(db, user):
    """种场景：3 台机器人的 J2 用同一批问题减速器；第 1 台背隙已超限，另两台出厂不久"""
    RF.init(db)
    RF.seed(db, MODE)
    cs = case(user)
    if db.one("select 1 as x from rf_robot where mode=%s and serial=%s", (MODE, cs["serials"][0])):
        return cs
    today = RF.field_today(db, MODE)
    cust = RF.customers()[cs["customer_idx"] % len(RF.customers())]
    item = RF.robot_items()[0]
    site = RF.SITES[cs["customer_idx"] % len(RF.SITES)]
    per_day = site["hours"] * (0.6 + 0.5 * site["load"]) * RF.BAD_FACTOR * RF.WEAR_PER_H["L"]
    ages = [max(3, int(round(x / per_day))) for x in RISE]
    for k, (serial, age) in enumerate(zip(cs["serials"], ages)):
        rng = RF._rng("lab29", serial)
        joints = []
        for i, (j, size) in enumerate(zip(RF.JOINTS, RF.JOINT_SIZE)):
            bad = j == JOINT
            lot = cs["lot"] if bad else "HD-{}-{}".format(size, 100 + (zlib.crc32((serial + j).encode()) % 40))
            joints.append(RF._joint(j, size, "{}-{}".format(serial, j), lot, rng.gauss(RF.BACKLASH_NOM[size] + (0.04 if bad else 0), 0.02), bad))
        ab = {"joints": joints, "cr_abs": round(rng.gauss(0.12, 0.015), 3), "source": "实验 29 场景（示例）", "lab29": user}
        start = today - dt.timedelta(days=age)
        db.x("insert into rf_robot (serial, mode, item, customer, status, seeded, start_day, last_day, as_built, state) "
             "values (%s,%s,%s,%s,'field',false,%s,%s,%s,%s) on conflict do nothing",
             (serial, MODE, item, cust, start, start, Jsonb(ab), Jsonb(RF._init_state(ab))))
        RF.advance_one(db, MODE, serial, age, store_from=today - dt.timedelta(days=60))
    return cs


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def _worst(db, user):
    """场景里背隙超限最多的那台（第 1 台）与关节"""
    cs = case(user)
    best = None
    for s in cs["serials"]:
        last = RF.latest(db, MODE, s)
        if not last:
            continue
        for j in last["joints"]:
            r = j["backlash"] / j["limit"]
            if best is None or r > best[2]:
                best = (s, j["joint"], r)
    return best


def swap_cost():
    c = dict(RF.COST["swap"])
    c["parts"] = float(RF.F.PRODUCTS.get(RF.JOINT_ITEM["L"]) or 0)
    return round(sum(c.values()), 2)


def answers(user):
    """第 ⑥ 题的标准答案"""
    one = swap_cost()
    return {"A": round(3 * one, 2), "B": round(3 * (one + LOSS_PER_COMPLAINT), 2), "one": one}


def answer(db, user, tid, ans):
    cs = seed(db, user)
    if tid == "l29_t1":
        w = _worst(db, user)
        s_ok = str(ans.get("serial") or "").strip().upper() == w[0]
        j_ok = str(ans.get("joint") or "").strip().upper() == w[1]
        sc = (5 if s_ok else 0) + (5 if j_ok else 0)
        _save(db, user, tid, sc, {"answer": ans, "truth": w[:2]})
        return {"score": sc, "of": 10, "feedback": "正确。" if sc == 10 else "看健康为红、“背隙超过上限”的那一行（你的场景序列号以 WQ-CR5-L29 开头）。"}
    if tid == "l29_t2":
        r = db.one("select as_built from rf_robot where mode=%s and serial=%s", (MODE, cs["serials"][0]))
        jd = next(j for j in r["as_built"]["joints"] if j["joint"] == JOINT)
        orig = jd.get("replaced") or jd                     # 已经换过了：按换下来的那台关节判
        lot_ok = str(ans.get("lot") or "").strip().upper() == str(orig.get("lot") or cs["lot"]).upper()
        try:
            b_ok = abs(float(ans.get("backlash0")) - float(orig.get("backlash0") or 0)) <= 0.01
        except (TypeError, ValueError):
            b_ok = False
        sc = (5 if lot_ok else 0) + (5 if b_ok else 0)
        _save(db, user, tid, sc, {"answer": ans})
        return {"score": sc, "of": 10, "feedback": "正确。" if sc == 10 else "出厂档案里这个关节一行：减速器批次、出厂背隙（两位小数）。"}
    if tid == "l29_t3":
        sc = 10 if ans.get("choice") == "bad_lot" else 0
        _save(db, user, tid, sc, {"answer": ans})
        return {"score": sc, "of": 10, "feedback": "正确。" if sc == 10 else "这台出厂才几个月，同批出厂一两个月的也在涨——不是正常磨损。"}
    if tid == "l29_t4":
        got = {x.strip().upper() for x in str(ans.get("serials") or "").replace("，", ",").replace("、", ",").replace(" ", ",").split(",") if x.strip()}
        others = set(cs["serials"][1:])
        sc = 10 if others <= got <= set(cs["serials"]) else (5 if got & others else 0)
        _save(db, user, tid, sc, {"answer": sorted(got), "truth": sorted(others)})
        return {"score": sc, "of": 10, "feedback": "正确：同批还有 {} 台要处理。".format(len(others)) if sc == 10 else
                "再看出厂档案的“同批还装在”：同一批号的都算（填序列号，用逗号分开）。"}
    if tid == "l29_t6":
        t = answers(user)
        try:
            a, b = float(ans.get("A")), float(ans.get("B"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填 A、B 两个金额"}
        sc = (5 if abs(a - t["A"]) <= 0.01 * t["A"] else 0) + (5 if abs(b - t["B"]) <= 0.01 * t["B"] else 0)
        _save(db, user, tid, sc, {"answer": ans, "truth": t})
        return {"score": sc, "of": 10, "feedback": "正确：预防性更换省 ${:,.0f}。".format(t["B"] - t["A"]) if sc == 10 else
                "一次上门换大关节 = 人工 $600 + 差旅 $200 + 备件（WQJ-L 售价）；B 每台再加 $1,500。"}
    raise KeyError(tid)


def check(db, user):
    """任务 5：这个学生给报警那台派的上门换 J2 做完了"""
    cs = case(user)
    j = db.one("select * from rf_job where mode=%s and serial=%s and kind='swap' and joint=%s and status='done' and by_name=%s order by id desc limit 1",
               (MODE, cs["serials"][0], JOINT, user))
    if j:
        _save(db, user, "l29_t5", 10, {"job": j["id"], "done_day": j["done_day"]})


def status(db, user):
    cs = seed(db, user)
    check(db, user)
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l29_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    fl = {x["serial"]: x for x in RF.fleet(db, MODE) if x["serial"] in cs["serials"]}
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "case": {"customer": RF.customers()[cs["customer_idx"] % len(RF.customers())], "prefix": "WQ-CR5-L29-" + cs["code"],
                                                     "robots": [{"serial": s, "health": (fl.get(s) or {}).get("health")} for s in cs["serials"]]},
            "loss_per_complaint": LOSS_PER_COMPLAINT, "t3_choices": [{"value": k, "label": v} for k, v in T3_CHOICES]}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l29_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
