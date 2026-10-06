# -*- coding: utf-8 -*-
"""教学模式：实验 7“数字工厂闭环”的六个任务与自动评分（满分 100）。

评分全部依据总线历史和历史库，不看学生自己怎么说——订单是否真的建了、轴是否真的做完了。
"""
import datetime as dt
import json

from factory import data as F
from hub import kpi, mrp
from hub.privacy import is_me

TASKS = [
    {"id": "t1", "points": 15, "role": "manager", "title": "读懂首页看板",
     "desc": "打开首页，回答三个问题：现在哪台设备停机？哪张在手订单有延期风险？哪种物料低于安全库存？",
     "hint": "设备看“车间实况”的红色卡片；订单看“订单与交期”的标签；物料看“关键物料”。"},
    {"id": "t2", "points": 20, "role": "planner", "title": "接单与算料",
     "desc": "绿谷输送设备订购 10 台 WQR-105，交期由老师给定（默认 10 月 15 日）。在计划员工作区新建订单，读懂算料结果后确认提交。",
     "hint": "看算料表里 SH-301 要几根、45 钢够不够。安全库存为什么也要算进去？"},
    {"id": "t3", "points": 15, "role": "engineer", "title": "设计发布",
     "desc": "在 FreeCAD 里修改输出轴参数（例如键槽长度 45 → 42 mm），运行“发布”宏；在工艺员工作区确认新版本和键槽 G 代码。",
     "hint": "发布宏在 digital/freecad 里；发布后看 AI 提醒：在制工单受不受影响？"},
    {"id": "t4", "points": 20, "role": "operator", "title": "车间执行",
     "desc": "把你的 SH-301 工单下达到车间；在车间终端逐道工序点“开工”，直到 10 根轴全部完工。可以在 3D 车间里观察。",
     "hint": "一道工序开工后，零件做完一件就会被 AGV 送到下一道；下一道也要有人开工。"},
    {"id": "t5", "points": 15, "role": "quality", "title": "质检与处置",
     "desc": "在质检员工作区看控制图和不合格品，完成评审；并回答：轴承位直径为什么会逐渐变大？",
     "hint": "对照磨床 GRD-01 的砂轮寿命和换刀事件看控制图。"},
    {"id": "t6", "points": 15, "role": "manager", "title": "成本分析",
     "desc": "在厂长工作区打开你的工单成本分解，填写实际加工成本比标准高百分之几，并用一句话说明主要原因。",
     "hint": "标准只含单件工时；实际还包括调整和换刀。"},
]
T5_CHOICES = ["磨床砂轮逐渐磨损", "车床主轴转速太高", "热处理温度不够", "测量仪器没校准"]


class Teach:
    def __init__(self, db):
        self.db = db

    def _result(self, user, tid):
        return self.db.one("select * from task_result where user_name=%s and task_id=%s", (user, tid))

    def _save(self, user, tid, score, evidence):
        self.db.x("insert into task_result (user_name, task_id, score, evidence) values (%s,%s,%s,%s) "
                  "on conflict (user_name, task_id) do update set score=greatest(task_result.score, excluded.score), "
                  "evidence=excluded.evidence, done_at=now()",
                  (user, tid, score, json.dumps(evidence, ensure_ascii=False, default=str)))

    def start(self, user):
        if not self._result(user, "start"):
            self._save(user, "start", 0, {})

    def my_work_order(self, user):
        """学生在任务 2 里建的 SH-301 工单（由他确认执行的提议生成）。"""
        rows = self.db.q("select proposal_id from ai_proposal where mode='teach' and action='create_order_and_plan' "
                         "and (requested_by=%s or confirmed_by=%s) and status in ('executed','confirmed') "
                         "order by created_at desc", (user, user))
        for r in rows:
            for m in self.db.messages(["erp.doc"], corr=r["proposal_id"], mode="teach"):
                d = m["data"]
                if d["doctype"] == "Work Order" and d.get("production_item") == "SH-301":
                    return d["name"], r["proposal_id"]
        return None, None

    # ------------------------------------------------------------ 自动检查
    def check(self, user):
        self.start(user)
        wo, pid = self.my_work_order(user)
        # 任务 2：由学生确认、桥接执行的接单提议
        if pid and not self._full(user, "t2"):
            docs = [m["data"] for m in self.db.messages(["erp.doc"], corr=pid, mode="teach")]
            so = next((d for d in docs if d["doctype"] == "Sales Order"), None)
            s = 0
            ev = {"proposal": pid}
            if so:
                it = (so.get("items") or [{}])[0]
                if it.get("item_code") == "WQR-105" and float(it.get("qty", 0)) == 10 and "绿谷" in so.get("customer", ""):
                    s += 10
                ev["sales_order"] = so["name"]
            if wo:
                w = next(d for d in docs if d["doctype"] == "Work Order" and d["name"] == wo)
                if float(w.get("qty", 0)) == 10:
                    s += 5
                ev["work_order"] = wo
            if any(d["doctype"] == "Material Request" and any(i.get("item_code") == "RM-45-D50" for i in d.get("items", []))
                   for d in docs):
                s += 5
            if s:
                self._save(user, "t2", s, ev)
        # 任务 3：学生本人发布的 SH-301 新版本
        if not self._full(user, "t3"):
            st = self._result(user, "start")["done_at"]
            rel = self.db.messages(["design.release"], since=st, mode="teach")
            mine = [m for m in rel if m["data"]["item"] == "SH-301" and (not m["data"].get("author")
                                                                       or is_me(m["data"]["author"], user))]
            if mine:
                g = self.db.messages(["design.gcode"], since=st, mode="teach")
                self._save(user, "t3", 15 if g else 10, {"release": mine[-1]["id"], "revision": mine[-1]["data"]["revision"],
                                                         "gcode": bool(g)})
        # 任务 4：工单各工序完工
        if wo and not self._full(user, "t4"):
            done = [m for m in self.db.messages(["machine.event"], corr=wo, mode="teach")
                    if m["data"]["event"] == "op_complete"]
            if done:
                last = any(m["data"].get("last_op") for m in done)
                self._save(user, "t4", 20 if last else min(19, 3 * len(done)),
                           {"work_order": wo, "operations_done": len(done)})
        return self.status(user)

    def _full(self, user, tid):
        r = self._result(user, tid)
        pts = next(t["points"] for t in TASKS if t["id"] == tid)
        return bool(r and r["score"] >= pts)

    # ------------------------------------------------------------ 学生提交答案
    def answer(self, user, tid, ans):
        self.start(user)
        if tid == "t1":
            ov = kpi.overview(self.db, None, "teach")
            down = {m["unit"] for m in ov["machines"] if m["state"] in ("down", "fault")}
            risky = {o["name"] for o in ov["orders"] if o["tone"] in ("bad", "warn")}
            low = {m["code"] for m in ov["materials"] if m["status"] == "低于安全库存"}
            s = 5 * (ans.get("machine") in down) + 5 * (ans.get("order") in risky) + 5 * (ans.get("material") in low)
            self._save(user, "t1", s, {"answer": ans, "expected": {"machine": sorted(down), "order": sorted(risky),
                                                                  "material": sorted(low)}})
            return {"score": s, "of": 15, "feedback": _fb(s, 15, "对照看板再找一找标红的项目")}
        if tid == "t5":
            wo, _ = self.my_work_order(user)
            s = 8 if ans.get("reason") == T5_CHOICES[0] else 0
            open_ncr = self.db.q("select ncr_id from ncr where work_order=%s and status='open'", (wo,)) if wo else []
            finished = bool(wo) and any(m["data"].get("last_op") for m in self.db.messages(["machine.event"], corr=wo, mode="teach")
                                        if m["data"]["event"] == "op_complete")
            if finished and not open_ncr:
                s += 7
            self._save(user, "t5", s, {"answer": ans, "open_ncr": [r["ncr_id"] for r in open_ncr], "finished": finished})
            msg = "原因判断正确。" if s >= 8 else "原因再想想：什么在逐件变化？"
            if not finished:
                msg += "工单完工、所有不合格品评审后，再提交一次可拿到另外 7 分。"
            elif open_ncr:
                msg += "还有不合格品没评审：" + "、".join(r["ncr_id"] for r in open_ncr)
            return {"score": s, "of": 15, "feedback": msg}
        if tid == "t6":
            wo, _ = self.my_work_order(user)
            c = mrp.wo_cost(self.db, wo, "teach") if wo else None
            if not c:
                return {"score": 0, "of": 15, "feedback": "你的工单还没有加工记录。"}
            try:
                v = float(str(ans.get("variance_pct")).replace("%", ""))
            except ValueError:
                return {"score": 0, "of": 15, "feedback": "请填数字，例如 12.5"}
            diff = abs(v - (c["variance_pct"] or 0))
            s = 12 if diff <= 2 else (6 if diff <= 5 else 0)
            reason = str(ans.get("reason", ""))
            if any(k in reason for k in ("调整", "换刀", "准备", "setup", "装夹")):
                s += 3
            self._save(user, "t6", s, {"answer": ans, "expected_pct": c["variance_pct"], "work_order": wo})
            return {"score": s, "of": 15, "feedback": "系统算得 {:+.1f}%。".format(c["variance_pct"]) if s < 15 else "完全正确。"}
        raise KeyError(tid)

    def status(self, user):
        rows = {r["task_id"]: r for r in self.db.q("select * from task_result where user_name=%s", (user,))}
        start = rows.get("start")
        tasks, current = [], None
        for i, t in enumerate(TASKS):
            r = rows.get(t["id"])
            score = r["score"] if r else 0
            done = score >= t["points"]
            if current is None and not done:
                current = i
            tasks.append(dict(t, score=score, done=done, evidence=r["evidence"] if r else None))
        total = sum(t["score"] for t in tasks)
        elapsed = int((dt.datetime.now(dt.timezone.utc) - start["done_at"]).total_seconds() / 60) if start else 0
        wo, _ = self.my_work_order(user)
        return {"user": user, "tasks": tasks, "current": current if current is not None else len(TASKS) - 1,
                "score": total, "of": 100, "elapsed_min": elapsed, "work_order": wo, "t5_choices": T5_CHOICES,
                "t1_options": self._t1_options()}

    def _t1_options(self):
        ov = kpi.overview(self.db, None, "teach")
        return {"machines": [{"value": m["unit"], "label": "{} {}".format(m["code"], m["name"])} for m in ov["machines"]],
                "orders": [{"value": o["name"], "label": "{} {}".format(o["name"], o["customer"].split(" ")[0])}
                           for o in ov["orders"]],
                "materials": [{"value": c, "label": "{} {}".format(c, F.ITEMS[c][0].split(" ")[0])}
                              for c in ["RM-45-D50", "BRG-6205", "BRG-6206", "BRG-6207", "RM-40CR-F225", "OIL-CKC220"]]}


def _fb(s, of, tip):
    return "全部正确。" if s == of else "得 {} / {} 分。{}".format(s, of, tip)
