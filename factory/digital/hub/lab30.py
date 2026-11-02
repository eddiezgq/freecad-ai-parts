# -*- coding: utf-8 -*-
"""实验 30“一台轮式人形从订单到交付”（第 74 轮，机器人厂）：六个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

和实验 24 同一套做法（订单、按层下达、检验、开票、成本都用平台里的事实，函数借 lab24 的），多了 WQ-H1 才有的两样：
底盘是一台 WQ-AGV300，要在这张单里先造出来（整机里套整机）；两种整机抢同一个标定工位 CAL-1，而且只有一个人会。
任务成绩存在 task_result，编号加前缀 l30_。"""
import datetime as dt

from factory import data as F
from hub import lab24 as L24

PRODUCT = "WQ-H1"
OTHER = "WQ-CR5"
CHASSIS = "WQ-AGV300"
SHIFT_MIN = 480            # 一班 8 小时（人员与排班：机器人厂只上白班）
TASKS = [
    {"id": "l30_t1", "points": 10, "title": "接单、算料",
     "desc": "在“订单与计划”里接 1 台 WQ-H1（客户、交期自定），点“算料”，看清楚再提交、确认。回答：这张单要下几张工单？一台 WQ-H1 用几个关节模组？下半身的底盘 WQ-AGV300 从哪来？",
     "hint": "工单 = 整机 + 每一种自制件和部件各一张；看看算料结果里有没有 WQ-AGV300 和它的驱动单元。"},
    {"id": "l30_t2", "points": 10, "title": "按层下达",
     "desc": "工单表里从最底层下达：机加件 → 关节模组、AGV 驱动单元 → AGV 底盘 → 人形整机。每张工单要等它用到的下一层做完、入库了再下达。平台记下每张工单的下达时刻自动评分。",
     "hint": "这台机器的层数比协作臂多一层：底盘自己也是一台整机。上一层比它用到的下一层先下达，每有一处扣 5 分。"},
    {"id": "l30_t3", "points": 10, "title": "两种整机抢一个工位",
     "desc": "和 WQ-H1 同一周（前后 7 天内）再接 1 台 WQ-CR5。看“订单与计划”的产能和“人员与排班”的技能矩阵：两种整机都要用、又只有一个人会的是哪个工位？这一周怎么办（选出所有可行的）？",
     "hint": "接了两张单记 3 分；工位（填设备编号）4 分；对策 3 分——平台按这一周这个工位的负荷和会的人数判哪几个可行。"},
    {"id": "l30_t4", "points": 10, "title": "判一台人形合不合格",
     "desc": "人形联调时测双臂相对位姿误差、手眼标定误差、走到桌前双手抓箱的节拍。选你这张单的一台，对照“质量”页的公差判合不合格；不合格的写出哪一项超了。",
     "hint": "三项都在公差内才合格。"},
    {"id": "l30_t5", "points": 10, "title": "完工入库、开票",
     "desc": "人形联调、包装后入库；订单的工单都做完，系统自动开销售发票。到了自动打勾。",
     "hint": "ERPNext 里整机工单变成“已完成”记 5 分，有了这张订单的销售发票再记 5 分。"},
    {"id": "l30_t6", "points": 10, "title": "这台人形的成本",
     "desc": "在“生产成本”页看这张单每张工单的标准成本和实际成本。整台人形的实际成本比标准成本高（低）百分之几？差得最多的是哪张工单（填它的物料编号）？",
     "hint": "整台标准成本 = 材料（按物料清单逐层，含底盘）+ 各工单的标准工时成本；实际 = 材料 + 各工单的实际工时成本。误差 1 个百分点以内都算对。"},
]
REPORT_POINTS = 40
T1_SOURCES = [("make", "这张单里自己造（算料排出 AGV 驱动单元和 AGV 底盘的工单）"), ("stock", "从成品库拿一台卖剩的 AGV"),
              ("buy", "外购一台 AGV")]
T3_OPTIONS = [("stagger", "错开排产：两台整机的标定排在这一周的不同时段"),
              ("train", "带徒：再培养一个会这个工位的人（这一周起步，下一次就不卡）"),
              ("outsource", "外协标定：把人形送到外面的计量机构做双臂与手眼标定"),
              ("skip", "人形先不做双臂与手眼标定，联调时再说")]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


_save = L24._save


def start(db, user):
    if not _get(db, user, "l30_start"):
        _save(db, user, "l30_start", 0, {})


def locked(db, u, anomaly_id=None):
    return False


def expected_counts():
    return L24.expected_counts(PRODUCT)


def my_order(db, user):
    return L24.my_order(db, user, PRODUCT)


# ---------------------------------------------------------------- 任务 3：两种整机共用的单点工位
def _units(product):
    from sim.engine import OP_UNITS, routing_for
    return {u for op, _ in routing_for(product) for u in OP_UNITS[op]}


def _minutes_on(product, unit):
    from sim.engine import OP_UNITS, routing_for
    return sum(float(m) for op, m in routing_for(product) if unit in OP_UNITS[op])


def conflict(db):
    """两种整机都用、又只有一个人会的设备，这一周它的负荷（一台 WQ-H1 + 一台 WQ-CR5）和可行的对策——当场按平台数据算"""
    from hub import people as PE
    shared = _units(PRODUCT) & _units(OTHER)
    single = {x["unit"] for x in PE.single_points(db, "teach")}
    hot = sorted(shared & single)
    unit = hot[0] if hot else None
    load = _minutes_on(PRODUCT, unit) + _minutes_on(OTHER, unit) if unit else 0.0
    cap = 5 * SHIFT_MIN
    ok = set()
    if unit and load <= cap:
        ok.add("stagger")          # 一周的班次装得下：错开就行
    if unit in single:
        ok.add("train")            # 只有一个人会：带徒才能解掉单点依赖
    return {"shared": sorted(shared), "single": sorted(single), "units": hot, "unit": unit,
            "code": unit.upper() if unit else None,
            "load_min": load, "capacity_min": cap, "feasible": sorted(ok)}


def _same_week(a, b):
    if not a or not b:
        return False
    ta, tb = a["created_at"], b["created_at"]
    if isinstance(ta, str):
        ta, tb = dt.datetime.fromisoformat(ta), dt.datetime.fromisoformat(tb)
    return abs((ta - tb).total_seconds()) <= 7 * 86400


def _norm_unit(s):
    return str(s or "").strip().lower().replace("_", "-")


# ---------------------------------------------------------------- 回答
def answer(db, user, tid, ans):
    start(db, user)
    if tid == "l30_t1":
        exp = expected_counts()
        s = (4 if int(ans.get("work_orders") or 0) == exp["work_orders"] else 0) + \
            (3 if int(ans.get("joints") or 0) == exp["joints"] else 0) + (3 if ans.get("chassis") == "make" else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": dict(exp, chassis="make")})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                "得 {} / 10 分。对照算料结果数一数工单（底盘和它的驱动单元也各有一张）；关节模组：双臂、腰、头加起来；"
                "底盘在这张单里自己造——成品库里的 AGV 是给别的客户的。".format(s)}
    if tid == "l30_t3":
        c = conflict(db)
        mine = my_order(db, user)
        other = L24.my_order(db, user, OTHER)
        s = 3 if _same_week(mine, other) else 0
        key = _norm_unit(ans.get("unit"))
        right_unit = c["unit"] and key in (_norm_unit(c["unit"]), _norm_unit(c["code"]))
        s += 4 if right_unit else 0
        picks = set(ans.get("choices") or [])
        want = set(c["feasible"])
        s += 3 if picks == want else (1 if picks and picks <= want else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": {"unit": c["unit"], "choices": sorted(want)}, "conflict": c,
                                 "orders": [mine and mine["sales_order"], other and other["sales_order"]]})
        fb = []
        if not (mine and other):
            fb.append("还没找到你的两张单（WQ-H1、WQ-CR5 各一张，都要确认执行）")
        elif not _same_week(mine, other):
            fb.append("两张单不在同一周（前后 7 天内）")
        if not right_unit:
            fb.append("工位不对：两种整机都要用、技能矩阵里只有一个人会的那一个")
        if picks != want:
            fb.append("对策：这一周 {} 的负荷 {:.0f} 分钟、一周能排 {:.0f} 分钟，只有一个人会——可行的是错开排产和带徒；"
                      "外协做不了（标定要用本厂工位和这台机器的数据），跳过标定不能出厂".format(c["code"] or c["unit"], c["load_min"], c["capacity_min"]))
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else "得 {} / 10 分。{}。".format(s, "；".join(fb))}
    if tid == "l30_t4":
        order = my_order(db, user)
        if not order:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（接一台 WQ-H1 并确认）"}
        js = L24.joints(db, order, items={PRODUCT})
        j = js.get(ans.get("serial"))
        if not j or len(j["chars"]) < 3:
            return {"score": 0, "of": 10, "feedback": "这台人形还没测完（人形联调做完三项才能判）"}
        fails = sorted(k for k, c in j["chars"].items() if c["result"] == "fail")
        verdict = "fail" if fails else "pass"
        s = 0
        if ans.get("verdict") == verdict:
            s = 10 if verdict == "pass" or ans.get("char") in fails else 6
        _save(db, user, tid, s, {"answer": ans, "serial": ans.get("serial"), "expected": verdict, "fails": fails})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                ("判对了，但超的是：{}。".format("、".join(j["chars"][k]["name"] for k in fails)) if s else
                 "不对：这台人形{}。".format("三项都在公差内，合格" if verdict == "pass" else "不合格"))}
    if tid == "l30_t6":
        order = my_order(db, user)
        if not order:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1"}
        c = L24.order_cost(db, order, PRODUCT)
        if c["variance_pct"] is None or len(c["lines"]) < len(order["work_orders"]):
            return {"score": 0, "of": 10, "feedback": "还有工单没做完，成本还算不全"}
        try:
            pct = float(ans.get("variance_pct"))
        except (TypeError, ValueError):
            return {"score": 0, "of": 10, "feedback": "填一个百分数（高于标准为正）"}
        s = (7 if abs(pct - c["variance_pct"]) <= 1.0 else 0) + (3 if str(ans.get("worst") or "").strip().upper() == c["worst"] else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": {"variance_pct": c["variance_pct"], "worst": c["worst"]},
                                 "std": c["std"], "actual": c["actual"]})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                "得 {} / 10 分。整台：标准 ${:,.0f}，实际 ${:,.0f}（{:+.1f}%），差得最多的是 {}。".format(
                    s, c["std"], c["actual"], c["variance_pct"], c["worst"])}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 2、5"""
    start(db, user)
    order = my_order(db, user)
    if order:
        rows, bad = L24.layers(db, order)
        if all(r["released"] for r in rows):
            _save(db, user, "l30_t2", max(0, 10 - 5 * len(bad)), {"layers": rows, "violations": bad})
        prod_wo = order["work_orders"].get(PRODUCT)
        docs = {m["data"]["name"]: m["data"] for m in db.erp_docs("Work Order", "teach")}
        s = 5 if prod_wo and (docs.get(prod_wo) or {}).get("status") == "Completed" else 0
        inv = db.one("select doc from invoice where mode='teach' and kind='ar' and ref=%s and doc is not null limit 1",
                     (order["sales_order"],)) if s else None
        s += 5 if inv else 0
        if s:
            _save(db, user, "l30_t5", s, {"work_order": prod_wo, "invoice": inv and inv["doc"]})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l30_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    order = my_order(db, user)
    other = L24.my_order(db, user, OTHER)
    hs = L24.joints(db, order, items={PRODUCT}) if order else {}
    from hub import mrp
    r = mrp.std_rollup(PRODUCT)
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "order": order and {"sales_order": order["sales_order"], "work_orders": order["work_orders"]},
            "other_order": other and other["sales_order"],
            "layers": L24.layers(db, order)[0] if order else [],
            "units": [{"serial": k, "item": v["item"], "chars": {c: {kk: vv for kk, vv in x.items() if kk != "result"}
                                                                 for c, x in v["chars"].items()}} for k, v in sorted(hs.items())],
            "t1_sources": [{"value": k, "label": t} for k, t in T1_SOURCES],
            "t3_options": [{"value": k, "label": t} for k, t in T3_OPTIONS],
            "std": {"material": round(r["material"], 2), "operations": round(r["operations"], 2), "total": round(r["material"] + r["operations"], 2)}}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l30_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]


def answers(db, user):
    """测试与演练用：按平台数据算出的正确答案（不进页面）"""
    c = conflict(db)
    return {"t1": dict(expected_counts(), chassis="make"), "t3": {"unit": c["code"] or c["unit"], "choices": c["feasible"]}}

