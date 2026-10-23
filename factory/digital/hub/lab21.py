# -*- coding: utf-8 -*-
"""实验 21“能源：空转、错峰与单件碳足迹”（第 18 轮 E6-10）：五个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

流程：学生在“能源与环境”页找空转最多的设备 → 按运行功率和标准工时算输出轴 SH-301（不含热处理）每件的运行电量和碳排放 →
老师注入“卧加下班忘关 + 热处理峰时开炉”→ 学生在指挥台比较“空闲 10 / 30 分钟自动待机、全部机加设备待机、不处理”（比对模式）→
执行，厂长批准后车间按新设定运行 → 算错峰一个月省多少电费、少排多少碳，卧加每晚待机一个月少排多少碳。任务编号前缀 l21_。"""
import json

UNIT = "hmc-01"                  # 老师注入：卧式加工中心下班忘关
WORK_DAYS = 22                   # 错峰按每月 22 个工作日
NIGHTS = 30                      # 待机按每月 30 晚、每晚 12 小时
TASKS = [
    {"id": "l21_t1", "points": 10, "title": "找空转最多的设备",
     "desc": "在“能源与环境 → 总览”看每台设备的电量条（灰色是空转），找出近 12 小时空转电量最多的设备（热处理炉保温不算）。",
     "hint": "“单耗”一栏下面有近 12 小时各设备的空转电量。"},
    {"id": "l21_t2", "points": 15, "title": "单件电量与碳足迹",
     "desc": "输出轴 SH-301 的加工工序（不含调质热处理）每件的运行电量 = Σ 运行功率 × 每件标准工时；再乘电网排放因子得到每件的碳排放。",
     "hint": "运行功率在“计量点”一栏；标准工时见工艺路线（下料 3、粗车 18、精车 15、铣键槽 10、磨外圆 12、检验 6 分钟）。"},
    {"id": "l21_t3", "points": 10, "title": "比较方案，选一个",
     "desc": "老师注入后，在指挥台打开“{} 空转”的异常，右栏比较：空闲 10 分钟 / 30 分钟自动待机、全部机加设备 10 分钟、不处理（对照）。选一个写理由。提交后才显示中枢的建议。".format(UNIT.upper()),
     "hint": "看每个方案一天省多少度、多少钱，再开要预热会不会耽误交期。"},
    {"id": "l21_t4", "points": 15, "title": "执行",
     "desc": "在指挥台采纳你选的方案，生成“节能设定”动作，请老师（厂长）批准。批准后车间按新设定运行。",
     "hint": "节能设定由计划员、维修工或厂长发起，厂长批准。"},
    {"id": "l21_t5", "points": 10, "title": "一个月省多少",
     "desc": "① 热处理错峰：一炉 110 kW × 3 小时从峰时挪到平时，每月 {} 个工作日，一个月省多少电费？② 错峰少排多少碳？"
             "③ {} 每晚 12 小时从空转（6 kW）改为待机（0.7 kW），一个月 {} 晚少排多少 kg 碳？".format(WORK_DAYS, UNIT.upper(), NIGHTS),
     "hint": "电价、排放因子看“能源与环境”页上的参数。想一想：错峰省的是钱还是电？"},
]
REPORT_POINTS = 40
OPTIONS = [{"value": "standby10", "label": "{} 空闲 10 分钟待机".format(UNIT.upper())}, {"value": "standby30", "label": "{} 空闲 30 分钟待机".format(UNIT.upper())},
           {"value": "all10", "label": "全部机加设备 10 分钟待机"}, {"value": "none", "label": "不处理（对照）"}]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l21_start"):
        _save(db, user, "l21_start", 0, {})


def locked(db, u, anomaly_id=None):
    if not u or u.get("mode") != "teach" or u.get("teacher"):
        return False
    try:
        if not _get(db, u["name"], "l21_start"):
            return False
        r = _get(db, u["name"], "l21_t3")
        return not (r and (r["evidence"] or {}).get("submitted"))
    except Exception:  # noqa: BLE001
        return False


def expected_t2(db):
    from hub import energy as EN
    from sim import energy as SE
    from factory import data as F
    from sim.engine import OP_UNITS
    p = EN.params(db, "teach")
    kwh = 0.0
    for op, m in F.ROUTINGS[F.BOMS["SH-301"][0]]:
        u = (OP_UNITS.get(op) or [None])[0]
        if u and u != "ht-01":
            kwh += SE.POWER[u][0] * m / 60
    return round(kwh, 3), round(kwh * float(p["co2_factor"]), 3)


def expected_t5(db):
    from hub import energy as EN
    from sim import energy as SE
    p = EN.params(db, "teach")
    pr, f = p["price"], float(p["co2_factor"])
    run, idle, stby = SE.POWER[UNIT]
    return {"tou_usd": round(110 * 3 * (float(pr["peak"]) - float(pr["flat"])) * WORK_DAYS, 2), "tou_co2": 0.0,
            "standby_co2": round((idle - stby) * 12 * NIGHTS * f, 1)}


def target(db):
    """老师注入后这台设备的空转异常"""
    a = db.one("select id, status from anomaly where mode='teach' and rule='N2' and subject_key=%s order by id desc limit 1", (UNIT,))
    return a


def _close(x, want, tol=0.03):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return False
    return abs(x - want) <= max(0.02, abs(want) * tol)


def answer(db, user, tid, ans):
    from hub import energy as EN
    start(db, user)
    if tid == "l21_t1":
        idle = sorted(EN.idle_by_unit(db, "teach"), key=lambda x: -x["idle_kwh"])
        if not idle or not idle[0]["idle_kwh"]:
            return {"score": 0, "of": 10, "feedback": "还没有计量读数，等车间跑一会儿"}
        got = str(ans.get("unit") or "").lower()
        top = [x["unit"] for x in idle[:3]]
        s = 10 if got == top[0] else (5 if got in top else 0)
        _save(db, user, tid, s, {"answer": got, "expected": top[0], "top3": top})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "得 {} / 10 分：近 12 小时空转最多的是 {}。".format(s, top[0].upper())}
    if tid == "l21_t2":
        kwh, co2 = expected_t2(db)
        s = (8 if _close(ans.get("kwh"), kwh) else 0) + (7 if _close(ans.get("co2_kg"), co2) else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": {"kwh": kwh, "co2_kg": co2}})
        return {"score": s, "of": 15, "feedback": "正确。" if s == 15 else "得 {} / 15 分：每件 {:.2f} 度、{:.2f} kg CO2e。".format(s, kwh, co2)}
    if tid == "l21_t3":
        a = target(db)
        if not a:
            return {"score": 0, "of": 10, "feedback": "还没有 {} 的空转异常：老师注入后，车间空转满 1 小时（工厂时间）才报".format(UNIT.upper())}
        reason = str(ans.get("reason") or "").strip()
        kind = ans.get("option")
        if len(reason) < 15:
            return {"score": 0, "of": 10, "feedback": "理由写完整一点（至少 15 个字）：省多少电和钱、预热会不会耽误交期"}
        if kind not in [o["value"] for o in OPTIONS]:
            return {"score": 0, "of": 10, "feedback": "选一个方案"}
        best = (EN._state(db, "teach").get("recommended") or {}).get(str(a["id"])) or "standby10"
        s = 6 if kind == best else (4 if kind != "none" else 2)
        s += 4 if any(k in reason for k in ("度", "电", "钱", "费", "$")) and any(k in reason for k in ("交期", "预热", "订单", "等", "慢")) else 2
        _save(db, user, tid, s, {"submitted": True, "option": kind, "reason": reason, "system": best, "anomaly_id": a["id"]})
        return {"score": s, "of": 10, "feedback": "提交了。现在可以在指挥台看中枢的建议，和你的选择对比。" if s == 10 else "提交了（得 {} 分）。".format(s)}
    if tid == "l21_t5":
        e = expected_t5(db)
        s = (4 if _close(ans.get("tou_usd"), e["tou_usd"]) else 0) + (2 if _close(ans.get("tou_co2"), 0.0) else 0) + \
            (4 if _close(ans.get("standby_co2"), e["standby_co2"]) else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": e})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else "平台算的：错峰省 ${:,.2f}、少排碳 0（电没少用，只是换了时段），待机少排 {:g} kg。".format(
            e["tou_usd"], e["standby_co2"])}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 4：节能设定动作 已提交 5 / 已执行 10；车间设定里这台已经自动待机 +5"""
    from hub import energy as EN
    start(db, user)
    acts = db.q("select id, type, status, params from action where mode='teach' and initiator=%s and type in ('energy_setting','tou_rule') order by id", (user,))
    mine = [a for a in acts if a["type"] == "energy_setting" and UNIT in (a["params"].get("units") or [])]
    if mine:
        s = 10 if any(a["status"] in ("done", "executing") for a in mine) else (5 if any(a["status"] in ("submitted", "approved") for a in mine) else 2)
        on = UNIT in EN.settings(db, "teach")["standby"]
        if s == 10 and on:
            s += 5
        _save(db, user, "l21_t4", s, {"actions": [{"id": a["id"], "status": a["status"]} for a in mine], "standby_on": on})
    return status(db, user)


def status(db, user):
    from hub import energy as EN
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l21_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    a = target(db)
    t3 = rows.get("l21_t3")
    p = EN.params(db, "teach")
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "anomaly_id": a["id"] if a else None, "unit": UNIT,
            "locked": not (t3 and (t3["evidence"] or {}).get("submitted")), "options": OPTIONS, "sim": EN.sim_on(db, "teach"),
            "lab": EN._state(db, "teach").get("lab21"), "units": [{"value": u, "label": "{} {}".format(u.upper(), n)} for u, n in EN.UNIT_NAME.items() if u != "ht-01"],
            "price": p["price"], "factor": p["co2_factor"]}


def inject(H, u, body):
    """老师：打开能源模拟器；卧加下班忘关（24 小时，工厂时间）+ 下一个峰时段热处理开炉"""
    import datetime as dt
    from hub import energy as EN
    if u["mode"] != "teach" or not u.get("teacher"):
        raise PermissionError("只有教学模式的老师能注入")
    EN.set_sim(H.db, "teach", True if body.get("enable") is None else bool(body.get("enable")))
    if body.get("only_toggle"):
        return {"text": "能源模拟器已{}".format("打开" if EN.sim_on(H.db, "teach") else "关闭")}
    r1 = EN.inject(H, "teach", "forgot", u.get("name") or "老师", unit=UNIT, hours=24)
    r2 = EN.inject(H, "teach", "ht_peak", u.get("name") or "老师")
    st = EN._state(H.db, "teach")
    for k in ("forgot:" + UNIT, "ht_peak"):
        if k in (st.get("faults") or {}):
            EN._patch_in(H.db, "teach", "faults", k, dict(st["faults"][k], lab=True))     # 实验的问题不让模拟器自动“修好”
    EN._patch(H.db, "teach", {"lab21": {"unit": UNIT, "at": dt.datetime.now(dt.timezone.utc).isoformat()}})
    return {"text": "{}；{}。约 3 分钟（真实时间）后 {} 的空转满 1 小时，厂情中枢出异常".format(r1["text"], r2["text"], UNIT.upper())}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l21_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
