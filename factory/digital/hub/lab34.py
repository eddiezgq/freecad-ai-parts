# -*- coding: utf-8 -*-
"""实验 34“一台平缝机从订单到交付”（第 145 轮，缝纫机厂）：六个任务的自动评分（60 分）+ 报告（40 分）。

照实验 24（机器人厂）：学生自己接 1 台 WQ-LS → 算料 → 按层下达（铸件 → 机壳；关键零件、机壳 → 整机）→ 判一台平缝机出厂检验
合不合格 → 完工入库、开票 → 这台平缝机的成本 → 复盘。找订单、按层核对、测量值、成本都用实验 24 的函数（按产品取）。
任务成绩编号加前缀 l34_。"""
import json

from factory import data as F
from hub import lab24 as L24

PRODUCT = "WQ-LS"
KEY_PREFIX = "LS-"          # 自制关键零件：上轴、下轴、针杆、旋梭、偏心
TASKS = [
    {"id": "l34_t1", "points": 10, "title": "接单、算料",
     "desc": "在“订单与计划”里接 1 台平缝机 WQ-LS（客户、交期自定），点“算料”，看清楚再提交、确认。回答：这张单要下几张工单？一台 WQ-LS 用几种自制关键零件？",
     "hint": "工单 = 整机 + 每一种自制件各一张（铸件、机壳也是自制件）；关键零件是关键零件车间做的轴、针杆、旋梭、偏心，按种数算，不按个数。"},
    {"id": "l34_t2", "points": 15, "title": "按层下达",
     "desc": "在“订单与计划”的工单表里下达车间：先下达铸件和关键零件，铸件完工入库后再下达机壳，机壳和关键零件都完工入库后再下达整机。平台记下每张工单的下达时刻自动评分。",
     "hint": "上一层的工单比它用到的下一层先完工就下达了，每有一处扣 5 分。"},
    {"id": "l34_t3", "points": 10, "title": "判一台平缝机合不合格",
     "desc": "平缝机总装后在调试工位、跑合台、试缝台测梭尖间隙、钩线定时、送布牙高度、跑合温升、空载噪声、停针定位、试缝跳针。在下面选你这张单的一台平缝机，对照公差判它合不合格；不合格的写出哪一项超了。",
     "hint": "各项都在公差内才合格。"},
    {"id": "l34_t4", "points": 10, "title": "入库、开票",
     "desc": "出厂检验后整机入库。订单的工单都做完，系统自动开销售发票。到了自动打勾。",
     "hint": "ERPNext 里整机工单变成“已完成”记 5 分，有了这张订单的销售发票再记 5 分。"},
    {"id": "l34_t5", "points": 10, "title": "这台平缝机的成本",
     "desc": "在“生产成本”页看这张单每张工单的标准成本和实际成本。整台平缝机的实际成本比标准成本高（低）百分之几？差得最多的是哪张工单（填它的物料编号）？",
     "hint": "整台标准成本 = 材料（按物料清单逐层）+ 各工单的标准工时成本；实际 = 材料 + 各工单的实际工时成本。误差 1 个百分点以内都算对。"},
    {"id": "l34_t6", "points": 5, "title": "复盘：缝纫机厂多了什么",
     "desc": "和减速器厂（实验 7 只做一根输出轴）比，造一台平缝机多了哪些环节？选出所有对的。",
     "hint": "想想毛坯从哪里来、机壳加工中间做了什么、整机出厂前做了什么。"},
]
REPORT_POINTS = 40
T6_OPTIONS = [("foundry", "自己铸造机壳毛坯（混砂、造型、浇注、清理、时效）", True), ("age2", "机壳粗加工后第二次时效", True),
              ("cmm", "机壳上三坐标全检", True), ("runin", "整机跑合、试缝", True),
              ("joint_test", "关节逐台上测试台测背隙", False), ("calib", "整机运动学标定", False)]


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not db.one("select 1 from task_result where user_name=%s and task_id='l34_start'", (user,)):
        _save(db, user, "l34_start", 0, {})


def locked(db, u, anomaly_id=None):
    return False


def expected_counts(product=PRODUCT):
    from hub import mrp
    makes = mrp.explode_make(product, 1)
    return {"work_orders": len(makes) + 1, "key_parts": len([c for c in makes if c.startswith(KEY_PREFIX)])}


def _chars_needed(item=PRODUCT):
    return sum(len(cs) for (it, _op), cs in F.MEASURE.items() if it == item)


def machines(db, order):
    """这张单的整机出厂检验：{序列号: {物料, 各特性}}"""
    return L24.joints(db, order, items=(PRODUCT,))


def answer(db, user, tid, ans):
    start(db, user)
    if tid == "l34_t1":
        exp = expected_counts()

        def num(k):
            try:
                return int(ans.get(k) or 0)
            except (TypeError, ValueError):
                return -1
        s = (5 if num("work_orders") == exp["work_orders"] else 0) + (5 if num("key_parts") == exp["key_parts"] else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": exp})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                "得 {} / 10 分。对照算料结果数一数工单（铸件、机壳也算），再数关键零件有几种。".format(s)}
    if tid == "l34_t3":
        order = L24.my_order(db, user, PRODUCT)
        if not order:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（接一台 WQ-LS 并确认）"}
        m = machines(db, order).get(ans.get("serial"))
        if not m or len(m["chars"]) < _chars_needed():
            return {"score": 0, "of": 10, "feedback": "这台平缝机还没测完（各项都测了才能判）"}
        fails = sorted(k for k, c in m["chars"].items() if c["result"] == "fail")
        verdict = "fail" if fails else "pass"
        s = 0
        if ans.get("verdict") == verdict:
            s = 10 if verdict == "pass" or ans.get("char") in fails else 6
        _save(db, user, tid, s, {"answer": ans, "serial": ans.get("serial"), "expected": verdict, "fails": fails})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                ("判对了，但超的是：{}。".format("、".join(m["chars"][k]["name"] for k in fails)) if s else
                 "不对：这台平缝机{}。".format("各项都在公差内，合格" if verdict == "pass" else "不合格"))}
    if tid == "l34_t5":
        order = L24.my_order(db, user, PRODUCT)
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
    if tid == "l34_t6":
        mine = set(ans.get("choices") or [])
        right = {k for k, _, ok in T6_OPTIONS if ok}
        s = 5 if mine == right else (2 if mine and mine <= right else 0)
        _save(db, user, tid, s, {"answer": sorted(mine), "expected": sorted(right)})
        return {"score": s, "of": 5, "feedback": "正确。" if s == 5 else
                "自己铸造毛坯、二次时效、机壳三坐标全检、整机跑合试缝是缝纫机厂多出来的；关节测试台、整机运动学标定是机器人厂的。"}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 2、4"""
    start(db, user)
    order = L24.my_order(db, user, PRODUCT)
    if order:
        rows, bad = L24.layers(db, order)
        if all(r["released"] for r in rows):
            _save(db, user, "l34_t2", max(0, 15 - 5 * len(bad)), {"layers": rows, "violations": bad})
        prod_wo = order["work_orders"].get(PRODUCT)
        docs = {m["data"]["name"]: m["data"] for m in db.erp_docs("Work Order", "teach")}
        s = 5 if prod_wo and (docs.get(prod_wo) or {}).get("status") == "Completed" else 0
        inv = db.one("select doc from invoice where mode='teach' and kind='ar' and ref=%s and doc is not null limit 1",
                     (order["sales_order"],)) if s else None
        s += 5 if inv else 0
        if s:
            _save(db, user, "l34_t4", s, {"work_order": prod_wo, "invoice": inv and inv["doc"]})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l34_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    order = L24.my_order(db, user, PRODUCT)
    ms = machines(db, order) if order else {}
    from hub import mrp
    r = mrp.std_rollup(PRODUCT)
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "order": order and {"sales_order": order["sales_order"], "work_orders": order["work_orders"]},
            "layers": L24.layers(db, order)[0] if order else [],
            "machines": [{"serial": k, "item": v["item"], "chars": {c: {kk: vv for kk, vv in x.items() if kk != "result"}
                                                                    for c, x in v["chars"].items()}} for k, v in sorted(ms.items())],
            "t6_options": [{"value": k, "label": t} for k, t, _ in T6_OPTIONS],
            "std": {"material": round(r["material"], 2), "operations": round(r["operations"], 2),
                    "total": round(r["material"] + r["operations"], 2)}}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l34_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
