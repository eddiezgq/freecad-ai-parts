# -*- coding: utf-8 -*-
"""AI 工厂助手（决定 F5）：主动提醒、今日简报、问答、起草提议。

- 所有判断都基于历史库（hub.kpi），每条提醒和回答都附来源（主题、单号、消息编号）。
- 写操作只起草 ai.proposal，人确认后由桥接或 MES 执行（附录 A.4 第 2 条）。
- 教学模式：只提示方向、不代做——不给学生起草订单，简报写成提问。
"""
import datetime as dt
import json
import logging
import re
import threading
import uuid

from factory import data as F
from wqbus import UNITS
from wqbus.topics import topic, unit_topic
from hub import kpi, mrp
from hub.llm import LLM
from hub.privacy import actor

log = logging.getLogger("ai")
# 扩展（第 30 轮 H-8）：提议在 ERP 里执行完以后要做的事 fn(db, action, preview, mode)。
# freecad-ai-parts 的新产品登记（hub/products.py）挂在这里；问渠这边为空
ON_PROPOSAL_DONE = []

LEVEL_RANK = {"info": 0, "warn": 1, "critical": 2}


def _pct(x, digits=0):
    return "—" if x is None else ("{:." + str(digits) + "f}%").format(x * 100)


class Assistant:
    def __init__(self, db, publish, llm=None):
        """publish(topic, type, source, data, corr=None, mode=None)"""
        self.db, self.publish = db, publish
        self.llm = llm or LLM()
        self._sent = {}            # 提醒去重：key → (level, 时间)（第 17 轮 B 期起由异常生命周期去重，这里只留给旧调用方）
        self._detector = None
        self._lock = threading.Lock()

    # ================================================================ 提醒
    def evaluate(self, mode="teach", now=None):
        """按规则检查全厂，返回新发出的提醒。

        第 17 轮 B 期起由厂情中枢的规则库检测（hub/ont/anomaly.py）：原来这里的停机、刀具、质量趋势、不合格品、
        订单延期、缺料 6 项检查迁成规则 P1、P2、Q2、Q3、S1、W1，文字不变；异常新开、升级、重开时照旧发 ai.alert。"""
        out = []
        for data in self.detector().run(mode, now):
            if not self.detector().catalog[data["rule"]].get("alert", True):
                continue                     # 例如 V1：孪生自己已经发过提醒
            self.publish(topic("ai", "alert"), "ai.alert", "ai", data, None, mode)
            out.append(data)
        return out

    def detector(self):
        if self._detector is None:
            from hub.ont.anomaly import Detector
            self._detector = Detector(self.db)
        return self._detector

    def on_design_release(self, msg):
        """设计改版：检查在制工单是否受影响（第六节第 2 步）。"""
        d = msg["data"]
        item = d["item"]
        affected = []
        for w in self.db.erp_docs("Work Order", msg["mode"]):
            wd = w["data"]
            if wd.get("production_item") != item or wd.get("status") in ("Completed", "Cancelled", "Stopped"):
                continue
            started = self.db.messages(["machine.event"], corr=wd["name"], mode=msg["mode"])
            n = len({e["data"]["part_serial"] for e in started if e["data"]["event"] == "cycle_start"})
            affected.append((wd["name"], n, int(float(wd.get("qty", 0)))))
        if affected:
            txt = "；".join("{} 已开工 {} / {} 件".format(*a) for a in affected)
            level = "warn" if any(a[1] for a in affected) else "info"
            detail = "{} 发布第 {} 版（{}）。在制工单：{}。已开工的零件按旧版继续还是返工，需工艺员决定。".format(
                item, d["revision"], d.get("change_note") or "参数修改", txt)
        else:
            level, detail = "info", "{} 发布第 {} 版，没有在制工单受影响；之后下达的工单按新版执行。".format(item, d["revision"])
        data = {"level": level, "title": "{} 设计改版 rev {}".format(item, d["revision"]), "detail": detail,
                "evidence": [{"topic": msg.get("_topic") or topic("design", item.lower(), "release"), "id": msg["id"]}],
                "action_hint": "工艺员确认工艺与 G 代码是否需要同步更新", "key": "release:{}:{}".format(item, d["revision"])}
        self.publish(topic("ai", "alert"), "ai.alert", "ai", data, msg.get("corr"), msg["mode"])
        return data

    # ================================================================ 今日简报
    def briefing(self, mode="teach", now=None, publish=True):
        ov = kpi.overview(self.db, now, mode)
        facts = self._facts(ov)
        teach = mode == "teach"
        items = []
        for f in facts[:4]:
            items.append({"text": f["hint"] if teach else f["text"], "evidence": f["evidence"], "tone": f["tone"]})
        if not items:
            items.append({"text": "全厂运行平稳：没有停机、延期风险或低库存。" if not teach else
                          "现在工厂看起来一切正常。看板上哪个指标离目标最远？", "evidence": [], "tone": "good"})
        summary = "；".join(i["text"].split("，")[0] for i in items[:3])
        if self.llm.available() and not teach:
            try:
                items = self._polish(items) or items
            except Exception:  # noqa: BLE001
                log.exception("简报润色失败，用规则版本")
        data = {"summary": summary, "items": items, "generated_by": self.llm.name if not teach else "rules",
                "local_time": ov["local_time"]}
        if publish:
            self.publish(topic("ai", "briefing"), "ai.briefing", "ai", data, None, mode)
        return data

    def _facts(self, ov):
        """把看板数据整理成“事实”：正常口吻 text、教学口吻 hint、来源 evidence、紧急程度。"""
        facts = []
        for m in ov["machines"]:
            if m["state"] in ("down", "fault"):
                hit = [o for o in ov["orders"] if o["tone"] == "bad"]
                ord_txt = "；{} {}".format(hit[0]["name"], hit[0]["risk"]) if hit else ""
                facts.append({"rank": 3, "tone": "bad",
                              "text": "{}（{}）{}：{}，已停 {} 分钟，前面排队 {} 件{}。建议：{}".format(
                                  m["name"], m["code"], "故障" if m["state"] == "fault" else "停机", m["reason"],
                                  self._down_minutes(m), m["queue"], ord_txt,
                                  "今晚加开 2 小时，或把部分件转到其他班次" if m.get("bottleneck") else "尽快恢复"),
                              "hint": "{}（{}）停机了。想一想：它会影响哪张订单？在“车间实况”和“订单与交期”里找答案。".format(
                                  m["name"], m["code"]),
                              "evidence": [{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}]})
        low = [mt for mt in ov["materials"] if mt["tone"] == "bad"]
        if low:
            facts.append({"rank": 2, "tone": "warn",
                          "text": "；".join("{}（{}）{}：库存 {}，在手工单与订单还需 {:g}".format(
                              mt["name"], mt["code"], mt["status"], mt["qty_text"], mt["need"]) for mt in low)
                          + "。建议今天起草请购单。",
                          "hint": "有{}种物料的库存不够了。作为计划员，你要决定什么时候请购、请购多少。".format(
                              "一" if len(low) == 1 else "几"),
                          "evidence": [{"topic": "wq/gearbox/office/erp/bin", "item": mt["code"]} for mt in low]})
        ch = ov["quality"]["chart"]
        if ch.get("points") and len(ch["points"]) >= 5 and ch["shift_um"] >= 2:
            facts.append({"rank": 2 if ch["margin_um"] < 5 else 1, "tone": "info",
                          "text": "{} 最近 5 件均值上移 {:.1f} µm，距上限还有 {:.1f} µm，尚未超差。建议检查磨床砂轮。".format(
                              ch["title"], ch["shift_um"], ch["margin_um"]),
                          "hint": "{} 的测量值在上移。质检员会关心什么？可能是什么原因？".format(ch["title"]),
                          "evidence": [{"topic": ch["src"], "id": p["id"]} for p in ch["points"][-5:]]})
        for o in ov["orders"]:
            if o["tone"] == "bad" and not any(o["name"] in f["text"] for f in facts):
                facts.append({"rank": 2, "tone": "warn", "text": "{}（{}）{}，交期 {}。".format(
                    o["name"], o["customer"].split(" ")[0], o["risk"], o["delivery_date"]),
                    "hint": "有一张订单可能赶不上交期。找出是哪一张，原因是什么。",
                    "evidence": [{"topic": "wq/gearbox/office/erp/sales_order", "name": o["name"]}]})
            elif o["risk"].startswith("待排产") and o["short"]:
                facts.append({"rank": 1, "tone": "warn", "text": "{}（{}）待排产，缺 {}。".format(
                    o["name"], o["customer"].split(" ")[0], "、".join(o["short"])),
                    "hint": "有一张订单还没排产，而且缺料。先解决哪一个？",
                    "evidence": [{"topic": "wq/gearbox/office/erp/sales_order", "name": o["name"]}]})
        facts.sort(key=lambda f: -f["rank"])
        return facts

    @staticmethod
    def _down_minutes(m):
        return "{:.0f}".format((m.get("down_for_s") or 0) / 60)

    def _polish(self, items):
        system = ("你是工厂的 AI 助手。把下面的事实改写成给厂长看的今日简报，每条一两句，中文，"
                  "保留全部数字和单号，不增加事实。只输出 JSON 数组，每项是字符串，与输入一一对应。")
        text, _ = self.llm.run(system, [{"role": "user", "content": json.dumps([i["text"] for i in items], ensure_ascii=False)}],
                               [], lambda n, a: None, max_turns=1)
        arr = json.loads(text[text.index("["): text.rindex("]") + 1])
        if len(arr) != len(items):
            return None
        return [dict(i, text=str(t)) for i, t in zip(items, arr)]

    # ================================================================ 提议
    def propose(self, action, preview, mode, requested_by, title, source="ai", role=None):
        pid = "P-" + uuid.uuid4().hex[:8].upper()
        self.db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, requested_by) "
                  "values (%s,%s,%s,%s,%s,%s)", (pid, mode, action, title, json.dumps(preview, ensure_ascii=False),
                                                   requested_by))
        self.publish(topic("ai", "proposal"), "ai.proposal", source,
                     {"proposal_id": pid, "action": action, "title": title, "preview": preview,
                      "requires_confirm": True, "status": "pending", "requested_by": actor(requested_by, role)}, pid, mode)
        return pid

    def decide(self, pid, user, accept, executor=None, role=None):
        p = self.db.one("select * from ai_proposal where proposal_id=%s", (pid,))
        if p is None:
            raise KeyError(pid)
        if p["status"] != "pending":
            raise ValueError("提议 {} 已经{}".format(pid, {"confirmed": "确认", "rejected": "否决", "executed": "执行",
                                                        "failed": "执行失败"}.get(p["status"], p["status"])))
        status = "confirmed" if accept else "rejected"
        self.db.x("update ai_proposal set status=%s, confirmed_by=%s, decided_at=now() where proposal_id=%s",
                  (status, user, pid))
        who = actor(user, role)
        self.publish(topic("ai", "proposal"), "ai.proposal", "workbench/" + who,
                     {"proposal_id": pid, "action": p["action"], "title": p["title"], "preview": p["preview"],
                      "requires_confirm": True, "status": status, "confirmed_by": who if accept else None,
                      "rejected_by": None if accept else who, "requested_by": actor(p["requested_by"])}, pid, p["mode"])
        if accept and executor and p["action"] in executor:
            try:
                result = executor[p["action"]](p)
                self.db.x("update ai_proposal set status='executed', result=%s where proposal_id=%s",
                          (json.dumps(result, ensure_ascii=False, default=str), pid))
            except Exception as e:  # noqa: BLE001
                self.db.x("update ai_proposal set status='failed', result=%s where proposal_id=%s",
                          (json.dumps({"error": str(e)}, ensure_ascii=False), pid))
                raise
        return status

    def on_erp_result(self, msg):
        """桥接执行提议后发回的 erp.doc（corr = 提议编号）。"""
        pid = msg.get("corr") or ""
        if not pid.startswith("P-"):
            return
        d = msg["data"]
        if d["action"] == "failed":
            self.db.x("update ai_proposal set status='failed', result=%s where proposal_id=%s",
                      (json.dumps({"error": d.get("error"), "doctype": d.get("doctype")}, ensure_ascii=False), pid))
        elif d.get("proposal_done"):
            self.db.x("update ai_proposal set status='executed', result=%s where proposal_id=%s and status<>'failed'",
                      (json.dumps({"created": d.get("created", [])}, ensure_ascii=False), pid))
            if ON_PROPOSAL_DONE:
                p = self.db.one("select action, preview, mode from ai_proposal where proposal_id=%s", (pid,))
                for fn in ON_PROPOSAL_DONE if p else ():
                    fn(self.db, p["action"], p["preview"], p["mode"])

    # ================================================================ 问答
    def chat(self, messages, mode="teach", role="manager", user="user"):
        question = messages[-1]["content"] if messages else ""
        if self.llm.available():
            try:
                return self._chat_llm(messages, mode, role, user)
            except Exception as e:  # noqa: BLE001
                log.exception("模型调用失败，改用规则回答")
                ans = self._chat_rules(question, mode, role, user)
                ans["note"] = "模型暂时不可用（{}），以下为规则回答".format(type(e).__name__)
                return ans
        return self._chat_rules(question, mode, role, user)

    # ---- 工具（模型与规则回答共用）
    def tool(self, name, args, mode, user):
        if name == "get_overview":
            ov = kpi.overview(self.db, None, mode)
            sec = args.get("section", "all")
            keep = {"kpis", "machines", "orders", "week", "quality", "materials", "oee", "cost", "on_time", "wip",
                    "bottleneck", "local_time"}
            return {k: v for k, v in ov.items() if k in keep and (sec == "all" or k == sec)}
        if name == "query_messages":
            hours = min(float(args.get("hours", 24)), 24 * 14)
            since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
            rows = self.db.messages(args.get("types"), since=since, mode=mode, topic_like=args.get("topic_like"),
                                    corr=args.get("corr"), limit=min(int(args.get("limit", 30)), 50), order="desc")
            return [{"id": r["id"], "ts": r["ts"], "topic": r["_topic"], "type": r["type"], "corr": r.get("corr"),
                     "data": r["data"]} for r in rows]
        if name == "work_order_cost":
            return mrp.wo_cost(self.db, args["work_order"], mode) or {"error": "该工单还没有加工记录"}
        if name == "plan_order":
            return mrp.plan_order(self.db, args.get("customer") or F.CUSTOMERS[0], args.get("item", "WQR-105"),
                                  int(args["qty"]), args["delivery_date"], mode)
        if name == "propose_order":
            if mode == "teach":
                return {"error": "教学模式下 AI 不代做：请学生在计划员工作区自己录入订单"}
            pv = mrp.plan_order(self.db, args.get("customer") or F.CUSTOMERS[0], args.get("item", "WQR-105"),
                                int(args["qty"]), args["delivery_date"], mode)
            pid = self.propose("create_order_and_plan", pv, mode, user, _order_title(pv))
            return {"proposal_id": pid, "status": "pending", "preview": pv}
        return {"error": "未知工具 " + name}

    TOOLS = [
        {"name": "get_overview", "description": "取首页看板数据（全部从历史库计算）。section 可选 kpis/machines/orders/week/quality/materials/oee/cost/all",
         "input_schema": {"type": "object", "properties": {"section": {"type": "string"}}}},
        {"name": "query_messages", "description": "查总线历史消息。types 如 [\"machine.event\"]，topic_like 用 SQL like（如 wq/gearbox/machining/grd-01/%），corr 为工单号或提议号",
         "input_schema": {"type": "object", "properties": {"types": {"type": "array", "items": {"type": "string"}},
                                                           "topic_like": {"type": "string"}, "corr": {"type": "string"},
                                                           "hours": {"type": "number"}, "limit": {"type": "integer"}}}},
        {"name": "work_order_cost", "description": "按总线历史算一张工单的标准成本、实际成本和按工序的差异",
         "input_schema": {"type": "object", "properties": {"work_order": {"type": "string"}}, "required": ["work_order"]}},
        {"name": "plan_order", "description": "对一张假设的新订单做算料（MRP），只计算不写入",
         "input_schema": {"type": "object", "properties": {"customer": {"type": "string"}, "item": {"type": "string"},
                                                           "qty": {"type": "integer"}, "delivery_date": {"type": "string"}},
                          "required": ["qty", "delivery_date"]}},
        {"name": "propose_order", "description": "起草“接单并算料”提议（销售订单 + 工单 + 请购单），等人确认后才写入 ERPNext。仅生产模式可用",
         "input_schema": {"type": "object", "properties": {"customer": {"type": "string"}, "item": {"type": "string"},
                                                           "qty": {"type": "integer"}, "delivery_date": {"type": "string", "description": "YYYY-MM-DD"}},
                          "required": ["qty", "delivery_date"]}},
    ]

    def _system(self, mode, role):
        from factory import plant
        if plant.is_demo():
            facts = ("工厂数据：唯一成品 WQR-105 二级圆柱齿轮减速器，"
                     "售价 ${}；本轮闭环零件是输出轴 SH-301（工艺 RT-轴：下料 3 → 粗车 18 → 调质 12 → 精车 15 → 铣键槽 10 → 磨外圆 12 → 零件检验 6 分钟）。"
                     "客户：{}。").format(F.FG_SELLING_PRICE, "、".join(c.split(" ")[0] for c in F.CUSTOMERS))
        else:                                   # 企业工厂（第 30 轮；freecad-ai-parts ADR-0064）：概况来自工厂清单
            facts = plant.brief()
        base = ("你是“{}”的 AI 工厂助手，是全厂员工的同事。你通过统一数据总线和历史库看到全厂实时状态。"
                "回答用中文，简洁，先给结论再给依据；每个结论都要注明来源（主题、单号或消息编号），数据只来自工具结果，"
                "不要编造。写操作只能起草提议，由人确认后执行。{}今天是 {}。").format(
                    plant.display_name(), facts, dt.datetime.now(kpi.TZ).strftime("%Y-%m-%d %A"))
        if mode == "teach":
            base += ("\n现在是教学模式，对方是扮演“{}”的学生。你是助教：引导他思考、指出去看板哪里找数据、解释概念，"
                     "但不要直接替他完成任务，不要直接给出实验题的答案，不起草订单。").format(ROLE_NAMES.get(role, role))
        else:
            base += "\n现在是生产模式，对方是{}。可以直接帮他把事办完（仍需他确认提议）。".format(ROLE_NAMES.get(role, role))
        return base

    def _chat_llm(self, messages, mode, role, user):
        tools = [t for t in self.TOOLS if not (mode == "teach" and t["name"] == "propose_order")]
        text, trace = self.llm.run(self._system(mode, role), messages[-12:], tools,
                                   lambda n, a: self.tool(n, a, mode, user))
        props = [t["output"]["proposal_id"] for t in trace if t["tool"] == "propose_order" and "proposal_id" in (t["output"] or {})]
        return {"answer": text, "proposals": props, "tools": [t["tool"] for t in trace], "engine": self.llm.name}

    # ---- 规则回答（无模型时）
    def _chat_rules(self, q, mode, role, user):
        teach = mode == "teach"
        ov = kpi.overview(self.db, None, mode)
        m = re.search(r"(\d+)\s*台.*?(\d{1,2})\s*月\s*(\d{1,2})\s*日", q)
        if m and re.search(r"订单|安排|接单|生产|交货|WQR", q):
            qty, mon, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            year = dt.datetime.now(kpi.TZ).year
            due = dt.date(year, mon, day)
            cust = next((c for c in F.CUSTOMERS if any(k in q for k in _cust_keys(c))), F.CUSTOMERS[0])
            if teach:
                pv = mrp.plan_order(self.db, cust, "WQR-105", qty, due.isoformat(), mode)
                return {"answer": ("这是计划员的任务，我不替你录入。提示：① 在“计划员”工作区点“新建订单”；"
                                   "② 看算料结果里 SH-301 要几根、45 钢够不够——现在库存 {:g} kg，每根用 2.8 kg；"
                                   "③ 想想安全库存为什么也要算进去。").format(
                    next((r["stock"] for r in pv["mrp"] if r["item_code"] == "RM-45-D50"), 0)),
                    "proposals": [], "engine": "rules"}
            pv = mrp.plan_order(self.db, cust, "WQR-105", qty, due.isoformat(), mode)
            pid = self.propose("create_order_and_plan", pv, mode, user, _order_title(pv))
            wo = pv["work_orders"][0] if pv["work_orders"] else None
            mr = "、".join("{} {:g}{}".format(x["item_code"], x["qty"], kpi.unit_label(x["uom"])) for x in pv["material_requests"])
            ans = ("已起草提议 {}：销售订单 {} × {} 台，交期 {}；工单 SH-301 × {}，计划 {} 至 {}；请购：{}。"
                   "{}请在下方预览后确认，确认后才写入 ERPNext。来源：office/erp/bin 库存快照、在手订单。").format(
                pid, cust.split(" ")[0], qty, due.isoformat(), wo["qty"] if wo else 0,
                wo["planned_start_date"] if wo else "—", wo["expected_delivery_date"] if wo else "—", mr or "无",
                ("注意：" + "；".join(pv["warnings"]) + "。") if pv["warnings"] else "")
            return {"answer": ans, "proposals": [pid], "engine": "rules"}
        wo_m = re.search(r"(MFG-WO-\d{4}-\d{5})", q)
        if re.search(r"成本", q):
            wo = wo_m.group(1) if wo_m else self._latest_wo(mode)
            c = mrp.wo_cost(self.db, wo, mode) if wo else None
            if not c:
                return {"answer": "还没有找到可计算成本的加工记录。", "engine": "rules"}
            if teach:
                return {"answer": ("提示：成本差异 = 实际 − 标准。标准只按单件工时算；实际还要加上每道工序的调整时间和换刀。"
                                   "在“厂长”工作区打开 {} 的成本分解，看哪道工序差得最多，再想想为什么。").format(wo),
                        "engine": "rules"}
            ans = ("{} 已完工 {} 件：加工标准成本 ${:.2f}，实际 ${:.2f}，高 ${:.2f}（{:+.1f}%）。其中调整与换刀 ${:.2f}，"
                   "加工超时 ${:.2f}；差得最多的是“{}”。来源：{} 的 {} 条完工事件（corr={}）。").format(
                wo, c["parts_finished"], c["std_cost"], c["actual_cost"], c["variance"], c["variance_pct"] or 0,
                c["setup_cost"], c["overrun_cost"], c["worst_operation"], c["evidence"]["topic"],
                c["evidence"]["messages"], wo)
            return {"answer": ans, "engine": "rules"}
        so_m = re.search(r"(SAL-ORD-\d{4}-\d{5})", q)
        if so_m or re.search(r"延期|晚|交期|来得及", q):
            o = next((x for x in ov["orders"] if so_m and x["name"] == so_m.group(1)), None) or \
                next((x for x in ov["orders"] if x["tone"] == "bad"), None) or (ov["orders"][0] if ov["orders"] else None)
            if not o:
                return {"answer": "目前没有在手订单。", "engine": "rules"}
            down = [m for m in ov["machines"] if m["state"] in ("down", "fault")]
            if teach:
                return {"answer": "提示：先看“订单与交期”里 {} 的进度，再看“车间实况”里有没有设备停机、哪里在排队。交期风险 = 剩余工作量 ÷ 瓶颈能力。".format(o["name"]),
                        "engine": "rules"}
            ans = "{}（{}，{:g} 台，交期 {}）：{}。预计完成 {}；工单：{}。{}来源：office/erp/sales_order · {}，machining/*/status。".format(
                o["name"], o["customer"].split(" ")[0], o["qty"], o["delivery_date"], o["risk"], o["projected"] or "—",
                o["work_orders"], ("{} 停机（{}），排队 {} 件，是主要原因。".format(down[0]["code"], down[0]["reason"], down[0]["queue"])
                                   if down else ""), o["name"])
            return {"answer": ans, "engine": "rules"}
        if re.search(r"瓶颈", q):
            b = ov["week"]["bottleneck"]
            if teach:
                return {"answer": "提示：瓶颈是负荷最满、前面排队最多的设备。对比“车间实况”各台设备的排队件数，再看“本周计划与实际”下方的说明。", "engine": "rules"}
            oee = ov["oee"]["machines"].get(b, {}) if b else {}
            return {"answer": "本周瓶颈是 {}（{}）：负荷最高，今日 OEE {}，停机 {:.0f} 分钟。来源：machine_state_log、machining/{}/status。".format(
                (b or "—").upper(), UNITS[b][1] if b else "", _pct(oee.get("oee")), (oee.get("down_s", 0)) / 60, b), "engine": "rules"}
        k = {x["key"]: x for x in ov["kpis"]}
        ans = "现在 {}：OEE {}，在制品 {} 件，本周完工 {}/{}，一次合格率 {}。{}".format(
            ov["local_time"], _pct(k["oee"]["value"]), k["wip"]["value"], k["output"]["value"], k["output"]["total"],
            _pct(k["fpy"]["value"], 1), "可以问我：某张订单为什么延期、本周瓶颈在哪、某张工单的成本为什么超了。")
        return {"answer": ans, "engine": "rules"}

    def _latest_wo(self, mode):
        r = self.db.one("select corr from bus_message where type='machine.event' and mode=%s and corr like 'MFG-WO-%%' "
                        "and payload->'data'->>'event'='op_complete' order by ts desc limit 1", (mode,))
        return r["corr"] if r else None


ROLE_NAMES = {"planner": "计划员", "engineer": "工艺员", "operator": "操作工", "quality": "质检员", "manager": "厂长",
              "approver": "审批人", "service": "售后", "sales": "销售", "safety": "安全员", "maintenance": "维修工", "lead": "班组长"}


def _cust_keys(c):
    zh = c.split(" ")[0].replace("示例·", "")
    return [zh, zh[:2], c.split(" ")[1] if len(c.split(" ")) > 1 else zh]


def _order_title(pv):
    so = pv["sales_order"]
    return "接单并算料：{} {} × {}，交期 {}".format(so["customer"].split(" ")[0].replace("示例·", ""), so["item_code"],
                                              so["qty"], so["delivery_date"])
