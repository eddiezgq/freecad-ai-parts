# -*- coding: utf-8 -*-
"""实验 24“一台协作机器人从订单到交付”（第 47 轮，机器人厂）：六个任务的自动评分（60 分）+ 报告（40 分，老师在课程里批改）。

依据全是平台里的事实：学生自己提交的 WQ-CR5 订单（提议 → ERPNext 的销售订单、工单）、每张工单的下达时刻（MES 派工消息）、
车间完工（最后一道工序做完）、测试台的测量值、ERPNext 的工单状态与销售发票、工单成本。任务成绩存在 task_result，编号加前缀 l24_。"""
import json

from factory import data as F

PRODUCT = "WQ-CR5"
TASKS = [
    {"id": "l24_t1", "points": 10, "title": "接单、算料",
     "desc": "在“订单与计划”里接 1 台 WQ-CR5（客户、交期自定），点“算料”，看清楚再提交、确认。回答：这张单要下几张工单？一台 WQ-CR5 用几台关节模组？",
     "hint": "工单 = 整机 + 每一种自制件和部件各一张；关节模组分大、中、小三种。"},
    {"id": "l24_t2", "points": 15, "title": "按层下达",
     "desc": "在“订单与计划”的工单表里下达车间：先下达最底层的自制件，等它们完工入库，再下达关节模组，最后整机。平台记下每张工单的下达时刻自动评分。",
     "hint": "上一层的工单比它用到的下一层先下达，每有一处扣 5 分。"},
    {"id": "l24_t3", "points": 10, "title": "判一台关节合不合格",
     "desc": "关节模组在关节测试台上测背隙、空载摩擦力矩、编码器零位标定残差。在下面选一台你这张单的关节，对照“质量”页的公差判它合不合格；不合格的写出哪一项超了。",
     "hint": "三项都在公差内才合格。"},
    {"id": "l24_t4", "points": 10, "title": "整机标定、入库、开票",
     "desc": "整机装配后在整机标定工位测位置重复精度和绝对定位误差，跑合、出厂检验后入库。订单的工单都做完，系统自动开销售发票。到了自动打勾。",
     "hint": "ERPNext 里整机工单变成“已完成”记 5 分，有了这张订单的销售发票再记 5 分。"},
    {"id": "l24_t5", "points": 10, "title": "这台机器人的成本",
     "desc": "在“生产成本”页看这张单每张工单的标准成本和实际成本。整台机器人的实际成本比标准成本高（低）百分之几？差得最多的是哪张工单（填它的物料编号）？",
     "hint": "整台标准成本 = 材料（按物料清单逐层）+ 各工单的标准工时成本；实际 = 材料 + 各工单的实际工时成本（含调整、换刀）。误差 1 个百分点以内都算对。"},
    {"id": "l24_t6", "points": 5, "title": "复盘：机器人厂多了什么",
     "desc": "和减速器厂（实验 7 只做一根输出轴）比，造一台协作机器人多了哪些环节？选出所有对的。",
     "hint": "想想物料清单有几层、哪些工序出测量数据。"},
]
REPORT_POINTS = 40
T6_OPTIONS = [("bom", "多层物料清单展开，一张单下十几张工单", True), ("layers", "工单要按层下达", True),
              ("joint_test", "关节逐台上测试台测背隙、摩擦力矩、零位", True), ("calib", "整机标定", True),
              ("temper", "调质热处理", False), ("dress", "砂轮修整", False)]


def _get(db, user, tid):
    return db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))


def _save(db, user, tid, score, evidence):
    db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
         "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
         "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))


def start(db, user):
    if not _get(db, user, "l24_start"):
        _save(db, user, "l24_start", 0, {})


def locked(db, u, anomaly_id=None):
    return False


def expected_counts(product=PRODUCT):
    from hub import mrp
    makes = mrp.explode_make(product, 1)
    joints = sum(q for c, q in makes.items() if F.ITEMS[c][1] == "sub" and c.startswith("WQJ-"))
    return {"work_orders": len(makes) + 1, "joints": int(round(joints))}


# ---------------------------------------------------------------- 学生的订单
def my_order(db, user):
    """学生最近一张已执行的 WQ-CR5 接单提议：销售订单、各工单（物料 → 工单号）"""
    rows = db.q("select proposal_id, preview, result from ai_proposal where mode='teach' and action='create_order_and_plan' "
                "and status='executed' and requested_by=%s order by created_at desc limit 20", (user,))
    for r in rows:
        pv = r["preview"] if isinstance(r["preview"], dict) else json.loads(r["preview"] or "{}")
        item = (pv.get("sales_order") or {}).get("item_code") or pv.get("item")
        if item != PRODUCT:
            continue
        res = r["result"] if isinstance(r["result"], dict) else json.loads(r["result"] or "{}")
        created = res.get("created") or []
        so = next((n for d, n in created if d == "Sales Order"), None)
        wo_names = [n for d, n in created if d == "Work Order"]
        wos = {}
        docs = {m["data"]["name"]: m["data"] for m in db.erp_docs("Work Order", "teach")}
        for n in wo_names:
            d = docs.get(n)
            if d:
                wos[d.get("production_item")] = n
        if so:
            return {"proposal_id": r["proposal_id"], "sales_order": so, "work_orders": wos, "erp": {n: docs.get(n) or {} for n in wo_names}}
    return None


def _release_ts(db, wo):
    m = [x for x in db.messages(["machine.cmd"], corr=wo, mode="teach") if x["data"].get("command") == "dispatch"]
    return min(x["ts"] for x in m) if m else None


def _done_ts(db, wo):
    ev = [x for x in db.messages(["machine.event"], corr=wo, mode="teach")
          if x["data"].get("event") == "op_complete" and x["data"].get("last_op")]
    return min(x["ts"] for x in ev) if ev else None


def layers(db, order):
    """按层下达的核对：每张工单的下达时刻、它用到的下一层工单的完工时刻"""
    wos = order["work_orders"]
    rows, bad = [], []
    for item, wo in wos.items():
        kids = [c for c, _ in F.BOMS.get(item, ("", []))[1] if c in wos]
        rel = _release_ts(db, wo)
        done = {c: _done_ts(db, wos[c]) for c in kids}
        late = [c for c, t in done.items() if rel and (t is None or str(t) > str(rel))]
        rows.append({"item": item, "work_order": wo, "released": rel, "children": kids, "released_before_children_done": late})
        if late:
            bad.append(item)
    return rows, bad


def joints(db, order):
    """这张单的关节在测试台上的测量值：{序列号: {物料, 各特性 [值, 下限, 上限, 判定]}}"""
    names = {wo for item, wo in order["work_orders"].items() if item.startswith("WQJ-")}
    out = {}
    for m in db.messages(["quality.measurement"], mode="teach", order="asc", limit=20000):
        d = m["data"]
        if d.get("work_order") in names:
            j = out.setdefault(d["part_serial"], {"item": d["item"], "chars": {}})
            j["chars"][d["characteristic"]] = {"name": d.get("name"), "value": d["value_mm"], "lo": d["lower_tol_mm"],
                                               "hi": d["upper_tol_mm"], "unit": d.get("unit"), "result": d["result"]}
    return out


def order_cost(db, order):
    from hub import mrp
    lines = []
    for item, wo in order["work_orders"].items():
        c = mrp.wo_cost(db, wo, "teach")
        if c:
            lines.append({"item": item, "work_order": wo, "std": c["std_cost"], "actual": c["actual_cost"], "variance": c["variance"]})
    tree = mrp.std_rollup(PRODUCT)
    mat = tree["material"]
    std = mat + sum(x["std"] for x in lines)
    act = mat + sum(x["actual"] for x in lines)
    worst = max(lines, key=lambda x: x["variance"]) if lines else None
    return {"material": round(mat, 2), "std": round(std, 2), "actual": round(act, 2),
            "variance_pct": round((act - std) / std * 100, 1) if std else None, "worst": worst["item"] if worst else None,
            "lines": lines, "std_tree": {k: round(v, 2) for k, v in tree.items()}}


# ---------------------------------------------------------------- 回答
def answer(db, user, tid, ans):
    start(db, user)
    if tid == "l24_t1":
        exp = expected_counts()
        s = (5 if int(ans.get("work_orders") or 0) == exp["work_orders"] else 0) + (5 if int(ans.get("joints") or 0) == exp["joints"] else 0)
        _save(db, user, tid, s, {"answer": ans, "expected": exp})
        return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                "得 {} / 10 分。对照算料结果数一数工单，再看物料清单里三种关节模组各用几台。".format(s)}
    if tid == "l24_t3":
        order = my_order(db, user)
        if not order:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1（接一台 WQ-CR5 并确认）"}
        js = joints(db, order)
        j = js.get(ans.get("serial"))
        if not j or len(j["chars"]) < 3:
            return {"score": 0, "of": 10, "feedback": "这台关节还没测完（三项都测了才能判）"}
        fails = sorted(k for k, c in j["chars"].items() if c["result"] == "fail")
        verdict = "fail" if fails else "pass"
        s = 0
        if ans.get("verdict") == verdict:
            s = 10 if verdict == "pass" or ans.get("char") in fails else 6
        _save(db, user, tid, s, {"answer": ans, "serial": ans.get("serial"), "expected": verdict, "fails": fails})
        return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                ("判对了，但超的是：{}。".format("、".join(j["chars"][k]["name"] for k in fails)) if s else
                 "不对：这台关节{}。".format("三项都在公差内，合格" if verdict == "pass" else "不合格"))}
    if tid == "l24_t5":
        order = my_order(db, user)
        if not order:
            return {"score": 0, "of": 10, "feedback": "先完成任务 1"}
        c = order_cost(db, order)
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
    if tid == "l24_t6":
        mine = set(ans.get("choices") or [])
        right = {k for k, _, ok in T6_OPTIONS if ok}
        s = 5 if mine == right else (2 if mine and mine <= right else 0)
        _save(db, user, tid, s, {"answer": sorted(mine), "expected": sorted(right)})
        return {"score": s, "of": 5, "feedback": "正确。" if s == 5 else "多层物料清单、按层下达、关节测试、整机标定都是机器人厂多出来的；调质、砂轮修整两座厂都有或只在减速器厂。"}
    raise KeyError(tid)


def check(db, user):
    """自动检查任务 2、4"""
    start(db, user)
    order = my_order(db, user)
    if order:
        rows, bad = layers(db, order)
        if all(r["released"] for r in rows):
            _save(db, user, "l24_t2", max(0, 15 - 5 * len(bad)), {"layers": rows, "violations": bad})
        prod_wo = order["work_orders"].get(PRODUCT)
        docs = {m["data"]["name"]: m["data"] for m in db.erp_docs("Work Order", "teach")}
        s = 5 if prod_wo and (docs.get(prod_wo) or {}).get("status") == "Completed" else 0
        inv = db.one("select doc from invoice where mode='teach' and kind='ar' and ref=%s and doc is not null limit 1",
                     (order["sales_order"],)) if s else None
        s += 5 if inv else 0
        if s:
            _save(db, user, "l24_t4", s, {"work_order": prod_wo, "invoice": inv and inv["doc"]})
    return status(db, user)


def status(db, user):
    rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like 'l24_%%'", (user,))}
    tasks = []
    for t in TASKS:
        r = rows.get(t["id"])
        tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
    order = my_order(db, user)
    js = joints(db, order) if order else {}
    return {"user": user, "tasks": tasks, "score": sum(t["score"] for t in tasks), "of": sum(t["points"] for t in TASKS),
            "report_points": REPORT_POINTS, "order": order and {"sales_order": order["sales_order"], "work_orders": order["work_orders"]},
            "layers": layers(db, order)[0] if order else [],
            "joints": [{"serial": k, "item": v["item"], "chars": {c: {kk: vv for kk, vv in x.items() if kk != "result"}
                                                                  for c, x in v["chars"].items()}} for k, v in sorted(js.items())],
            "t6_options": [{"value": k, "label": t} for k, t, _ in T6_OPTIONS],
            "std": _std()}


def _std():
    """整台 WQ-CR5 的标准成本（逐层累加）：材料、全部工序；任务 5 用"""
    from hub import mrp
    r = mrp.std_rollup(PRODUCT)
    return {"material": round(r["material"], 2), "operations": round(r["operations"], 2), "total": round(r["material"] + r["operations"], 2)}


def class_view(db):
    rows = db.q("select user_name, task_id, score from task_result where task_id like 'l24_t%%'")
    out = {}
    for r in rows:
        out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
    return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]
