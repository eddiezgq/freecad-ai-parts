# -*- coding: utf-8 -*-
"""“从订单到交付”实验的通用实现（第 149 轮，照实验 24、34）：一座厂写一份配置，就有一个实验——
学生接 1 个单位的本厂产品 → 算料（几张工单、某种料要领多少）→ 按层下达 → 判一个单位出厂检验合不合格 → 完工入库、开票 →
这张单的成本差异 → 复盘本厂多了什么。找订单、按层核对、测量值、成本都用实验 24 的函数（按产品取）。

用法（实验模块里）：
    from hub import labo
    globals().update(labo.build(CFG))
CFG 键：no、title、product（产品物料号）、unit（量词 + 名称，如“块驱动板”）、count_item（任务 1 问要领多少的那种料）、
t1_desc、t1_hint、t2_desc、t3_desc、t3_hint、t6_desc、t6_hint、t6_options（[(代号, 文字, 对不对)]）、t6_feedback、worst_hint。"""
import json

from factory import data as F
from hub import lab24 as L24


def build(cfg):
    no, product = cfg["no"], cfg["product"]
    pre = "l{}_".format(no)
    tasks = [
        {"id": pre + "t1", "points": 10, "title": "接单、算料", "desc": cfg["t1_desc"], "hint": cfg["t1_hint"]},
        {"id": pre + "t2", "points": 15, "title": "按层下达", "desc": cfg["t2_desc"],
         "hint": "上一层的工单比它用到的下一层先完工就下达了，每有一处扣 5 分。"},
        {"id": pre + "t3", "points": 10, "title": "判出厂检验合不合格", "desc": cfg["t3_desc"], "hint": cfg["t3_hint"]},
        {"id": pre + "t4", "points": 10, "title": "入库、开票",
         "desc": "出厂检验后成品入库。订单的工单都做完，系统自动开销售发票。到了自动打勾。",
         "hint": "ERPNext 里成品工单变成“已完成”记 5 分，有了这张订单的销售发票再记 5 分。"},
        {"id": pre + "t5", "points": 10, "title": "这张单的成本",
         "desc": "在“生产成本”页看这张单每张工单的标准成本和实际成本。整张单的实际成本比标准成本高（低）百分之几？差得最多的是哪张工单（填它的物料编号）？",
         "hint": "标准成本 = 材料（按物料清单逐层）+ 各工单的标准工时成本；实际 = 材料 + 各工单的实际工时成本。误差 1 个百分点以内都算对。" + cfg.get("worst_hint", "")},
        {"id": pre + "t6", "points": 5, "title": "复盘：这座厂多了什么", "desc": cfg["t6_desc"], "hint": cfg["t6_hint"]},
    ]
    t6 = [tuple(x) for x in cfg["t6_options"]]

    def _save(db, user, tid, score, evidence):
        db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
             "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
             "evidence=excluded.evidence, done_at=now()", (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))

    def start(db, user):
        if not db.one("select 1 from task_result where user_name=%s and task_id=%s", (user, pre + "start")):
            _save(db, user, pre + "start", 0, {})

    def locked(db, u, anomaly_id=None):
        return False

    def expected_counts():
        from hub import mrp
        need = mrp.explode(product, 1)
        return {"work_orders": len(mrp.explode_make(product, 1)) + 1, "count": round(float(need.get(cfg["count_item"], 0)), 3)}

    def _chars_needed():
        return sum(len(cs) for (it, _op), cs in F.MEASURE.items() if it == product)

    def units(db, order):
        return L24.joints(db, order, items=(product,))

    def my_order(db, user):
        return L24.my_order(db, user, product)

    def answer(db, user, tid, ans):
        start(db, user)
        if tid == pre + "t1":
            exp = expected_counts()

            def num(k):
                try:
                    return float(ans.get(k))
                except (TypeError, ValueError):
                    return None
            w, c = num("work_orders"), num("count")
            s = (5 if w is not None and int(w) == exp["work_orders"] else 0) + \
                (5 if c is not None and abs(c - exp["count"]) <= max(0.01, 0.01 * exp["count"]) else 0)
            _save(db, user, tid, s, {"answer": ans, "expected": exp})
            return {"score": s, "of": 10, "feedback": "全部正确。" if s == 10 else
                    "得 {} / 10 分。对照算料结果数一数工单（每一种自制的半成品都算一张），再看物料清单逐层乘下来要领多少。".format(s)}
        if tid == pre + "t3":
            order = my_order(db, user)
            if not order:
                return {"score": 0, "of": 10, "feedback": "先完成任务 1（接单并确认）"}
            m = units(db, order).get(ans.get("serial"))
            if not m or len(m["chars"]) < _chars_needed():
                return {"score": 0, "of": 10, "feedback": "这一件还没测完（各项都测了才能判）"}
            fails = sorted(k for k, c in m["chars"].items() if c["result"] == "fail")
            verdict = "fail" if fails else "pass"
            s = 0
            if ans.get("verdict") == verdict:
                s = 10 if verdict == "pass" or ans.get("char") in fails else 6
            _save(db, user, tid, s, {"answer": ans, "serial": ans.get("serial"), "expected": verdict, "fails": fails})
            return {"score": s, "of": 10, "feedback": "正确。" if s == 10 else
                    ("判对了，但超的是：{}。".format("、".join(m["chars"][k]["name"] for k in fails)) if s else
                     ("不对：各项都在公差内，合格。" if verdict == "pass" else "不对：这一件不合格。"))}
        if tid == pre + "t5":
            order = my_order(db, user)
            if not order:
                return {"score": 0, "of": 10, "feedback": "先完成任务 1"}
            c = L24.order_cost(db, order, product)
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
                    "得 {} / 10 分。整张单：标准 ${:,.0f}，实际 ${:,.0f}（{:+.1f}%），差得最多的是 {}。".format(
                        s, c["std"], c["actual"], c["variance_pct"], c["worst"])}
        if tid == pre + "t6":
            mine = set(ans.get("choices") or [])
            right = {k for k, _, ok in t6 if ok}
            s = 5 if mine == right else (2 if mine and mine <= right else 0)
            _save(db, user, tid, s, {"answer": sorted(mine), "expected": sorted(right)})
            return {"score": s, "of": 5, "feedback": "正确。" if s == 5 else cfg["t6_feedback"]}
        raise KeyError(tid)

    def check(db, user):
        """自动检查任务 2、4"""
        start(db, user)
        order = my_order(db, user)
        if order:
            rows, bad = L24.layers(db, order)
            if all(r["released"] for r in rows):
                _save(db, user, pre + "t2", max(0, 15 - 5 * len(bad)), {"layers": rows, "violations": bad})
            prod_wo = order["work_orders"].get(product)
            docs = {m["data"]["name"]: m["data"] for m in db.erp_docs("Work Order", "teach")}
            s = 5 if prod_wo and (docs.get(prod_wo) or {}).get("status") == "Completed" else 0
            inv = db.one("select doc from invoice where mode='teach' and kind='ar' and ref=%s and doc is not null limit 1",
                         (order["sales_order"],)) if s else None
            s += 5 if inv else 0
            if s:
                _save(db, user, pre + "t4", s, {"work_order": prod_wo, "invoice": inv and inv["doc"]})
        return status(db, user)

    def status(db, user, teacher=False):
        rows = {r["task_id"]: r for r in db.q("select * from task_result where user_name=%s and task_id like %s", (user, pre + "%"))}
        out_tasks = []
        for t in tasks:
            r = rows.get(t["id"])
            out_tasks.append(dict(t, score=r["score"] if r else 0, done=bool(r and r["score"] >= t["points"]), evidence=r["evidence"] if r else None))
        order = my_order(db, user)
        ms = units(db, order) if order else {}
        from hub import mrp
        r = mrp.std_rollup(product)
        return {"user": user, "no": no, "title": cfg["title"], "product": product, "unit": cfg["unit"], "count_item": cfg["count_item"],
                "tasks": out_tasks, "score": sum(t["score"] for t in out_tasks), "of": sum(t["points"] for t in tasks), "report_points": 40,
                "order": order and {"sales_order": order["sales_order"], "work_orders": order["work_orders"]},
                "layers": L24.layers(db, order)[0] if order else [],
                "machines": [{"serial": k, "item": v["item"], "chars": {c: {kk: vv for kk, vv in x.items() if kk != "result"}
                                                                        for c, x in v["chars"].items()}} for k, v in sorted(ms.items())],
                "t6_options": [{"value": k, "label": t} for k, t, _ in t6],
                "std": {"material": round(r["material"], 2), "operations": round(r["operations"], 2),
                        "total": round(r["material"] + r["operations"], 2)}}

    def class_view(db):
        rows = db.q("select user_name, task_id, score from task_result where task_id like %s", (pre + "t%",))
        out = {}
        for r in rows:
            out.setdefault(r["user_name"], {})[r["task_id"]] = r["score"]
        return [{"user": k, "scores": v, "total": sum(v.values())} for k, v in sorted(out.items())]

    return {"TASKS": tasks, "REPORT_POINTS": 40, "PRODUCT": product, "T6_OPTIONS": t6,
            "start": start, "locked": locked, "expected_counts": expected_counts, "my_order": my_order, "units": units,
            "answer": answer, "check": check, "status": status, "class_view": class_view}
