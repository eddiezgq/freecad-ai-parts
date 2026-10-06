# -*- coding: utf-8 -*-
"""完整闭环测试（对运行中的服务）：总线 + 历史库/枢纽 + 仿真车间 + Node-RED 桥接 + 模拟 ERPNext。

按实验 7 走一遍：教师重置情景 → 学生读看板答题 → 计划员接单算料并确认 → 工艺员发布新版设计与 G 代码 →
下达车间、操作工逐道开工 → 10 根轴做完 → 质检处置 → 成本分析；
然后在模拟 ERPNext 里核对：订单、工单、7 张作业卡（工时不重叠）、每件一张质量检验单、完工入库扣料加成品；
最后核对总线消息全部合规、看板指标更新、AI 能回答成本问题并注明来源。

用法：python3 tests/closed_loop.py [--hub http://localhost:8100] [--erp http://localhost:8091]
真 ERPNext（第 3 轮服务器演练）：加 --erp-kind real --erp-key <API Key> --erp-secret <API Secret>
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.parse
import urllib.request

P = argparse.ArgumentParser()
P.add_argument("--hub", default="http://localhost:8100")
P.add_argument("--erp", default="http://localhost:8091")
P.add_argument("--speed", type=float, default=300)
P.add_argument("--timeout", type=float, default=600)
P.add_argument("--erp-kind", choices=("mock", "real"), default="mock")
P.add_argument("--erp-key", default="")
P.add_argument("--erp-secret", default="")
P.add_argument("--diag", default="", help="出错时把 ERPNext 错误日志写到这个文件（CI 用）")
A = P.parse_args()

FAILS = []


def call(method, url, body=None, token=None, headers=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"x-wq-token": token} if token else {}),
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError("{} {} → {} {}".format(method, url, e.code, e.read().decode()[:400])) from None


def hub(method, path, body=None, token=None):
    return call(method, A.hub + path, body, token)


def erp(path):
    return call("GET", A.erp + urllib.parse.quote(path))


REAL = A.erp_kind == "real"


def erp_docs(doctype):
    """某类单据的全部记录（只含主表字段）：模拟 ERPNext 用它的调试接口，真 ERPNext 用 REST 接口。"""
    if not REAL:
        return erp("/api/mock/db/" + doctype)
    q = urllib.parse.urlencode({"fields": '["*"]', "limit_page_length": 0})
    return call("GET", "{}/api/resource/{}?{}".format(A.erp, urllib.parse.quote(doctype), q),
                headers={"Authorization": "token {}:{}".format(A.erp_key, A.erp_secret)})["data"]


def erp_error_log(n=4):
    """真 ERPNext 的错误日志（Error Log）：最近几条出错的最后几行，写到 --diag 文件并打印。"""
    q = urllib.parse.urlencode({"fields": '["name","method","error","creation"]', "order_by": "creation desc",
                                "limit_page_length": 30})
    try:
        rows = call("GET", "{}/api/resource/Error%20Log?{}".format(A.erp, q),
                    headers={"Authorization": "token {}:{}".format(A.erp_key, A.erp_secret)})["data"]
    except RuntimeError as e:
        rows = [{"method": "读不到 Error Log", "error": str(e), "creation": ""}]
    out, seen = [], set()
    for r in rows:
        tail = [x for x in (r.get("error") or "").strip().splitlines() if x.strip()][-6:]
        key = tail[-1] if tail else r.get("method")
        if key in seen:
            continue
        seen.add(key)
        out.append("[ERPNext 错误日志] {} {}".format(r.get("creation", "")[:19], r.get("method") or ""))
        out += ["    " + x.strip()[:280] for x in tail]
        if len(seen) >= n:
            break
    text = "\n".join(out) or "[ERPNext 错误日志] 空"
    print(text)
    if A.diag:
        with open(A.diag, "w", encoding="utf-8") as f:
            f.write(text + "\n")


def delivery_date():
    d = dt.date.today() + dt.timedelta(days=16)
    return (d + dt.timedelta(days=(7 - d.weekday()) % 7 if d.weekday() >= 5 else 0)).isoformat()


def check(cond, what):
    print(("  ✓ " if cond else "  ✗ ") + what)
    if not cond:
        FAILS.append(what)


def login(name, role):
    return hub("POST", "/api/login", {"name": name, "role": role, "mode": "teach"})["token"]


def wait(fn, what, timeout=None, every=2):
    t0 = time.time()
    while time.time() - t0 < (timeout or A.timeout):
        try:
            v = fn()
        except RuntimeError as e:
            # 桥接第一次写设计版本时才给 ERPNext 物料加自定义字段：字段定义已有、数据库列还没加好的那一刻，
            # 读物料会报 “Unknown column”。这是正在建字段，不是失败——稍后再读
            if "Unknown column" not in str(e):
                raise
            v = None
        if v:
            return v
        time.sleep(every)
    check(False, "等待超时：" + what)
    return None


def main():
    student = "测试学生" + time.strftime("%H%M%S")
    teacher = login("测试教师", "manager")
    print("1. 教师重置实验 7 情景")
    if not REAL:
        call("POST", A.erp + "/api/mock/reset")
    steel0 = None if not REAL else sum(b["actual_qty"] for b in erp_docs("Bin") if b["item_code"] == "RM-45-D50")
    hub("POST", "/api/scenario/reset", {"speed": 1, "scores": True}, teacher)
    ov = wait(lambda: (lambda o: o if o["demo"] and any(m["state"] == "down" for m in o["machines"]) else None)(
        hub("GET", "/api/overview", token=teacher)), "情景载入", 60)
    check(ov is not None, "情景载入：看板有演示数据，GRD-01 停机")

    mgr = login(student, "manager")
    print("2. 任务 1：读懂看板")
    r = hub("POST", "/api/teach/t1", {"machine": "grd-01", "order": "SAL-ORD-2026-00019", "material": "BRG-6207"}, mgr)
    check(r["score"] == 15, "任务 1 满分（{}）".format(r))

    print("3. 任务 2：接单与算料（计划员表单 → 提议 → 确认 → 桥接写入 ERPNext）")
    planner = login(student, "planner")
    pv = hub("POST", "/api/plan/order", {"customer": "示例·绿谷输送设备 GreenValley Conveyor (Demo)",
                                         "item": "WQR-105", "qty": 10, "delivery_date": delivery_date()}, planner)
    steel = next(r for r in pv["mrp"] if r["item_code"] == "RM-45-D50")
    check(pv["work_orders"][0]["qty"] == 10 and pv["work_orders"][0]["production_item"] == "SH-301", "算料：SH-301 工单 10 件")
    check(any(m["item_code"] == "RM-45-D50" for m in pv["material_requests"]),
          "算料：45 钢要请购（毛需求 {} kg，库存 {} kg，占用 {} kg）".format(steel["gross"], steel["stock"], steel["committed"]))
    check(any(m["item_code"] == "BRG-6207" for m in pv["material_requests"]), "算料：BRG-6207 要请购")
    p = hub("POST", "/api/proposals", {"customer": "示例·绿谷输送设备 GreenValley Conveyor (Demo)", "item": "WQR-105",
                                       "qty": 10, "delivery_date": delivery_date()}, planner)
    pid = p["proposal_id"]
    hub("POST", "/api/proposals/{}/confirm".format(pid), token=planner)
    prop = wait(lambda: (lambda x: x if x["status"] in ("executed", "failed") else None)(
        hub("GET", "/api/proposals/" + pid, token=planner)), "桥接执行提议", 60, 1)
    check(prop and prop["status"] == "executed", "提议已执行：{}".format(prop and prop.get("result")))
    wo = next(d["name"] for d in prop["results"] if d["doctype"] == "Work Order")
    so = next(d["name"] for d in prop["results"] if d["doctype"] == "Sales Order")
    print("   订单 {}，工单 {}".format(so, wo))
    st = hub("GET", "/api/teach", token=planner)
    check(st["tasks"][1]["score"] == 20, "任务 2 满分（{}）".format(st["tasks"][1]["score"]))

    print("4. 任务 3：工艺员发布新版设计（模拟 FreeCAD 宏）")
    sys.path[:0] = [__file__.rsplit("/tests/", 1)[0] + "/freecad"]
    import wq_publish  # noqa: E402
    eng = login(student, "engineer")
    res = wq_publish.publish(hub_url=A.hub, token=eng, author=student,
                             params={"segments": [[30, 40], [35, 12], [40, 60], [35, 25], [30, 30]],
                                     "chamfer": 1.5, "keyway": {"segment": 2, "b": 12.0, "t": 5.0, "L": 42.0}},
                             change_note="键槽长 45 → 42 mm", step_bytes=b"ISO-10303-21; (test)")
    check(res["revision"] >= 2, "发布 rev {}，G 代码 {} 行".format(res["revision"], res["gcode_lines"]))
    wait(lambda: any(d["name"] == "SH-301" and d.get("wq_revision") == res["revision"]
                     for d in erp_docs("Item")), "ERPNext 物料版本更新", 30, 1)
    item = next(d for d in erp_docs("Item") if d["name"] == "SH-301")
    check(item.get("wq_revision") == res["revision"], "ERPNext 里 SH-301 版本 = {}".format(item.get("wq_revision")))
    files = wait(lambda: (lambda fs: fs if len(fs) >= 2 else None)(
        [f for f in erp_docs("File") if f.get("attached_to_name") == "SH-301"]), "SH-301 附件", 30, 1) or []
    check(len(files) >= 2, "SH-301 附件 {} 个（STEP、G 代码…）".format(len(files)))
    st = hub("GET", "/api/teach", token=eng)
    check(st["tasks"][2]["score"] == 15, "任务 3 满分")
    alerts = hub("GET", "/api/overview", token=eng)["alerts"]
    check(any("设计改版" in a["title"] for a in alerts), "AI 提醒了设计改版的影响")

    print("4b. 网页设计台在线发布（第 6 轮 W3：不装 FreeCAD，服务器出 STEP）")
    p = hub("GET", "/api/design/SH-301/params", token=eng)
    check(p["revision"] == res["revision"] and p["params"]["keyway"]["L"] == 42, "设计台读到现行参数 rev {}".format(p["revision"]))
    bad = dict(p["params"], keyway=dict(p["params"]["keyway"], L=70))
    check(not hub("POST", "/api/design/SH-301/check", {"params": bad}, eng)["ok"], "键槽超长校核不通过")
    web = hub("POST", "/api/design/SH-301/publish", {"params": dict(p["params"], keyway=dict(p["params"]["keyway"], L=40)),
                                                     "change_note": "网页设计台：键槽长 42 → 40 mm"}, eng)
    check(web["revision"] == res["revision"] + 1 and web["step"], "在线发布 rev {}，带 STEP".format(web["revision"]))
    wait(lambda: any(d["name"] == "SH-301" and d.get("wq_revision") == web["revision"]
                     for d in erp_docs("Item")), "ERPNext 物料版本随在线发布更新", 30, 1)

    print("5. 任务 4：下达车间，操作工逐道开工（仿真倍速 {:g}）".format(A.speed))
    hub("POST", "/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": A.speed}, teacher)
    op = login(student, "operator")
    rel = hub("POST", "/api/mes/release", {"work_order": wo}, op)["dispatched"]
    check(len(rel) == 7, "下达 7 道工序")
    time.sleep(1)
    for d in rel:
        hub("POST", "/api/mes/cmd", {"unit": d["unit"], "command": "start", "work_order": wo, "operation": d["operation"]}, op)
    t0 = time.time()
    def finished():
        evs = [e for e in hub("GET", "/api/history?type=machine.event&corr={}&limit=500".format(wo), token=op)
               if e["data"]["event"] == "op_complete"]
        return evs if any(e["data"].get("last_op") for e in evs) else None
    done = wait(finished, "10 根轴全部完工", A.timeout, 3)
    print("   用时 {:.0f} 秒".format(time.time() - t0))
    check(done and len(done) == 7, "7 道工序全部完工")
    if REAL:
        # 真 ERPNext 每记一次工时要一两秒，桥接按顺序补记：等作业卡全部提交、完工入库做完再核对
        t1 = time.time()

        def erp_caught_up():
            jc = [j for j in erp_docs("Job Card") if j["work_order"] == wo]
            n_sub = sum(1 for j in jc if j["docstatus"] == 1)
            se = [x for x in erp_docs("Stock Entry") if x.get("work_order") == wo and x["docstatus"] == 1]
            print("   ERPNext 进度（{:.0f} 秒）：作业卡已提交 {}/{}，完工入库 {} 张".format(time.time() - t1, n_sub, len(jc), len(se)))
            return len(jc) == 7 and n_sub == 7 and se
        wait(erp_caught_up, "ERPNext 作业卡与完工入库", 360, 15)
    time.sleep(6)       # 等桥接把最后的入库写完
    st = hub("GET", "/api/teach", token=op)
    check(st["tasks"][3]["score"] == 20, "任务 4 满分")

    print("6. 核对{} ERPNext".format("真实" if REAL else "模拟"))
    jcs = [j for j in erp_docs("Job Card") if j["work_order"] == wo]
    check(len(jcs) == 7 and all(j["docstatus"] == 1 for j in jcs), "7 张作业卡全部提交")
    check(len(jcs) == 7 and all(j["total_completed_qty"] == 10 for j in jcs), "每张作业卡完成 10 件（{} 张）".format(len(jcs)))
    qis = [q for q in erp_docs("Quality Inspection") if any(q["reference_name"] == j["name"] for j in jcs)]
    check(len(qis) == 10, "每件一张质量检验单（{} 张）".format(len(qis)))
    good = sum(1 for q in qis if q["status"] == "Accepted")
    ses = [s for s in erp_docs("Stock Entry") if s.get("work_order") == wo and s["docstatus"] == 1]
    check(len(ses) == 1 and ses[0]["docstatus"] == 1 and ses[0]["fg_completed_qty"] == good,
          "完工入库 {} 件（合格数）".format(ses[0]["fg_completed_qty"] if ses else 0))
    wod = next(w for w in erp_docs("Work Order") if w["name"] == wo)
    check(wod["produced_qty"] == good, "工单完工数 {}".format(wod["produced_qty"]))
    bins = {b["item_code"]: b for b in erp_docs("Bin") if "原材料" in b["warehouse"] or "半成品" in b["warehouse"]}
    start = steel0 if REAL else 60
    check(abs(bins["RM-45-D50"]["actual_qty"] - (start - 2.8 * good)) < 1e-6,
          "45 钢扣料：{} → {} kg".format(start, bins["RM-45-D50"]["actual_qty"]))
    check(bins["SH-301"]["actual_qty"] == good, "SH-301 入库 {} 件".format(bins["SH-301"]["actual_qty"]))
    if not REAL:
        errs = erp("/api/mock/errors")["errors"]
        check(not errs, "ERPNext 字段校验无错误" + ("：" + "；".join(errs[:5]) if errs else ""))

    print("7. 任务 5、6：质检处置与成本分析")
    q = login(student, "quality")
    for n in hub("GET", "/api/ncr", token=q):
        if n["work_order"] == wo and n["status"] == "open":
            hub("POST", "/api/ncr/" + n["ncr_id"], {"disposition": "rework", "note": "返修：重新磨削"}, q)
    r = hub("POST", "/api/teach/t5", {"reason": "磨床砂轮逐渐磨损"}, q)
    check(r["score"] == 15, "任务 5 满分（{}）".format(r["feedback"]))
    cost = hub("GET", "/api/work_orders/{}/cost".format(wo), token=mgr)
    check(cost["actual_cost"] > cost["std_cost"] > 0, "成本：标准 ${} 实际 ${}（{:+}%）".format(
        cost["std_cost"], cost["actual_cost"], cost["variance_pct"]))
    r = hub("POST", "/api/teach/t6", {"variance_pct": cost["variance_pct"], "reason": "主要是调整和换刀时间"}, mgr)
    check(r["score"] == 15, "任务 6 满分")
    st = hub("GET", "/api/teach", token=mgr)
    check(st["score"] == 100, "实验 7 总分 {} / 100".format(st["score"]))

    print("8. 看板、AI 与总线")
    ov = hub("GET", "/api/overview", token=mgr)
    check(any(o["name"] == so for o in ov["orders"]), "看板“订单与交期”出现新订单 " + so)
    out = next(k for k in ov["kpis"] if k["key"] == "output")
    check(out["value"] >= good, "本周完工 {} 件（含本批 {}）".format(out["value"], good))
    ans = hub("POST", "/api/ai/chat", {"messages": [{"role": "user", "content": "{} 的实际成本比标准高多少？为什么？".format(wo)}]},
              mgr)
    # 第 17 轮 D 期起后台是 AI 代理：学生得到提示；老师得到带引用 [n] 的完整回答，且数字核对通过
    check("提示" in ans["answer"] or ("[1]" in ans["answer"] and (ans.get("check") or {}).get("ok")),
          "AI 回答（学生给提示 / 老师带引用、数字核对通过）：" + ans["answer"][:60])
    bad = hub("GET", "/api/health")
    check(bad["ok"] and bad["bus"], "枢纽健康，历史库 {} 条消息".format(bad["messages"]))

    print("9. 厂情中枢：工厂本体（第 17 轮 A 期）")
    h = wait(lambda: (lambda x: x if x["behind"] == 0 else None)(hub("GET", "/api/ont/health", token=teacher)), "本体同步追上", 60, 2)
    check(h is not None and h["errors"] == 0, "本体同步追上总线，没有跳过的消息（{}）".format(h))
    o = hub("GET", "/api/ont/obj/SalesOrder/" + urllib.parse.quote(so), token=teacher)
    check(any(g["link"] == "SalesOrder.customer" for g in o["links"]), "销售订单 {} 在本体里，连着客户".format(so))
    o = hub("GET", "/api/ont/obj/WorkOrder/" + urllib.parse.quote(wo), token=teacher)
    grp = {g["link"]: g for g in o["links"]}
    check("OperationTask.work_order" in grp and len(grp["OperationTask.work_order"]["items"]) >= 7,
          "工单 {} 连着 {} 道工序任务".format(wo, len(grp.get("OperationTask.work_order", {}).get("items", []))))
    parts = hub("POST", "/api/ont/query", {"type": "PartSerial", "link": {"name": "PartSerial.work_order", "key": wo}}, teacher)["objects"]
    check(len(parts) >= 10, "工单产出 {} 根零件实物".format(len(parts)))
    if parts:
        p0 = hub("GET", "/api/ont/obj/PartSerial/" + urllib.parse.quote(parts[0]["key"]), token=teacher)
        proc = [i for g in p0["links"] if g["link"] == "PartSerial.processed" for i in g["items"]]
        grd = [i for i in proc if (i["props"] or {}).get("machine") == "grd-01"]
        check(len(proc) >= 7 and grd and grd[0]["props"].get("tool_life_pct") is not None,
              "零件 {} 有 {} 条加工记录，磨削时砂轮剩余 {}%".format(parts[0]["key"], len(proc), grd[0]["props"].get("tool_life_pct") if grd else "?"))
        meas = [g for g in p0["links"] if g["link"] == "Measurement.part"]
        check(meas and len(meas[0]["items"]) >= 3, "零件挂着检验测量")
    for q in ("6207", "A-BRG-DG/6207"):
        r = hub("GET", "/api/ont/search?q=" + urllib.parse.quote(q), token=teacher)["results"]
        check(r and r[0]["key"] == "BRG-6207", "搜“{}”找到物料 BRG-6207".format(q))
    types = hub("GET", "/api/ont/types", token=teacher)
    have = [t for d in types["domains"] for t in d["types"] if t["maturity"] in ("have", "sim")]
    empty = [t["label"] for t in have if not t["count"]]
    print("  （有数据的对象类型 {} / {}；这一轮流程没碰到的：{}）".format(len(have) - len(empty), len(have), "、".join(empty) or "无"))

    print("10. 厂情中枢：异常、追因与指挥台（第 17 轮 B 期）")
    t0 = time.time()
    hub("POST", "/api/mes/cmd", {"unit": "cnc-l01-b", "command": "inject_fault", "minutes": 120, "reason": "闭环测试：主轴过热"}, teacher)
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"]
                            if x["rule"] == "P1" and (x["subject"] or {}).get("key") == "cnc-l01-b"), None), "停机异常", 90, 2)
    check(an is not None and time.time() - t0 <= 60, "CNC-L01-B 停机后 {:.0f} 秒出现异常".format(time.time() - t0))
    if an:
        d = hub("GET", "/api/ont/anomalies/{}".format(an["id"]), token=teacher)
        types = {n["type"] for n in d["chain"]["nodes"]}
        check({"Machine", "Anomaly"} <= types and d["chain"]["summary"], "因果链：{}".format("；".join(d["chain"]["summary"])[:120]))
        check(all(e["basis"]["how"] for e in d["chain"]["edges"]), "因果链每条边都有依据（{} 条）".format(len(d["chain"]["edges"])))
        r = hub("POST", "/api/ont/anomalies/{}/close".format(an["id"]), {"text": "闭环测试：复位"}, teacher)
        check(r["status"] == "closed", "异常可以关闭并留记录")
    hub("POST", "/api/mes/cmd", {"unit": "cnc-l01-b", "command": "reset"}, teacher)
    sit = hub("GET", "/api/ont/situation", token=teacher)
    check(len(sit["cards"]) == 15 and sum(1 for x in sit["cards"] if x["waiting"]) == 3, "全厂态势 15 块，3 块待接入")
    rl = hub("GET", "/api/ont/rules", token=teacher)["rules"]
    live = [x for x in rl if not x["waiting"]]
    check(len(live) == 20 and not [x["id"] for x in live if x["error"]], "规则 20 条在跑，没有出错（{}）".format([x["id"] for x in live if x["error"]]))

    print("11. 厂情中枢：推演与动作（第 17 轮 C 期）")
    r = hub("POST", "/api/ont/shifts", {"mode": "shift"}, teacher)
    check(r["calendar"]["mode"] == "shift", "车间切到按班次")
    hub("POST", "/api/mes/cmd", {"unit": "cnc-l01-b", "command": "inject_fault", "minutes": 240, "reason": "闭环测试：推演"}, teacher)
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"]
                            if x["rule"] == "P1" and (x["subject"] or {}).get("key") == "cnc-l01-b"), None), "停机异常", 90, 2)
    if an:
        t0 = time.time()
        o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
        kinds = [x["kind"] for x in o["options"]]
        check(kinds[:1] == ["none"] and "overtime" in kinds and "expedite" in kinds and o["recommended"],
              "预案推演 {} 个方案，用时 {:.1f} 秒，{}快照；{}".format(len(kinds), time.time() - t0, "精确" if o["exact"] else "近似", o["reason"]))
        exp = next(x for x in o["options"] if x["kind"] == "expedite")
        a = hub("POST", "/api/ont/actions", {"changes": exp["changes"], "anomaly_id": an["id"], "snapshot_id": o["snapshot_id"]}, teacher)
        before = next(m for m in hub("GET", "/api/overview", token=teacher)["machines"] if m["unit"] == "cnc-l01-b")["down_until_s"] or 0
        d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
        check(d["status"] == "done", "维修加急：批准并执行（{}）".format(d["result"]["text"]))
        after = wait(lambda: (lambda m: m if m["down_until_s"] is not None and m["down_until_s"] < before * 0.8 else None)(
            next(m for m in hub("GET", "/api/overview", token=teacher)["machines"] if m["unit"] == "cnc-l01-b")), "车间停机缩短", 30, 2)
        check(after is not None, "车间里 CNC-L01-B 的剩余停机从 {:.0f} 分钟缩短".format(before / 60))
        ot = next(x for x in o["options"] if x["kind"] == "overtime")
        a = hub("POST", "/api/ont/actions", {"changes": ot["changes"], "anomaly_id": an["id"]}, teacher)
        d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
        cal = hub("GET", "/api/ont/shifts", token=teacher)["calendar"]
        check(d["status"] == "done" and any(v == ot["changes"][0]["minutes"] for v in cal["overtime"].values()),
              "加班：班次表已改并发给车间（{}）".format(cal["overtime"]))
    tomorrow = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    a = hub("POST", "/api/ont/actions", {"changes": [{"type": "urgent_purchase", "item": "BRG-6207", "qty": 10, "arrive": tomorrow}]}, teacher)
    d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
    check(d["status"] == "executing" and d["result"].get("proposal_id"), "紧急采购：交给 ERPNext（提议 {}）".format(d["result"].get("proposal_id")))
    d = wait(lambda: (lambda x: x if x["status"] in ("done", "failed") else None)(hub("GET", "/api/ont/actions/{}".format(a["ids"][0]), token=teacher)),
             "ERPNext 生成请购单", 120, 3)
    check(d is not None and d["status"] == "done", "ERPNext 生成了请购单：{}".format((d or {}).get("result", {}).get("erp")))
    mrs = [m for m in erp_docs("Material Request") if str(m.get("schedule_date"))[:10] == tomorrow]
    check(bool(mrs), "ERPNext 里有需求日为 {} 的请购单（{}）".format(tomorrow, "、".join(m["name"] for m in mrs)))
    hub("POST", "/api/mes/cmd", {"unit": "cnc-l01-b", "command": "reset"}, teacher)
    hub("POST", "/api/ont/shifts", {"mode": "continuous"}, teacher)
    acts = hub("GET", "/api/ont/actions?box=all", token=teacher)["actions"]
    check(len(acts) >= 3, "动作收件箱里有 {} 个动作".format(len(acts)))

    print("12. 厂情中枢：AI 代理、提醒、日报与复盘（第 17 轮 D 期）")
    hub("POST", "/api/mes/cmd", {"unit": "grd-01", "command": "inject_fault", "minutes": 600, "reason": "闭环测试：AI 代理"}, teacher)
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"]
                            if x["rule"] == "P1" and (x["subject"] or {}).get("key") == "grd-01"), None), "磨床停机异常", 90, 2)
    ans = hub("POST", "/api/ai/chat", {"messages": [{"role": "user", "content": "外圆磨床要是再停一天，哪张订单受影响？怎么办最划算？"}]}, teacher)
    check("compare_options" in ans["tools"] and ans["refs"] and ans["check"]["ok"],
          "AI 代理（{}）：调了 {}，{} 条引用，数字核对{}".format(ans["engine"], "、".join(ans["tools"]), len(ans["refs"]),
                                                       "通过" if ans["check"]["ok"] else "没通过：{}".format(ans["check"]["unverified"][:2])))
    if an:
        ans = hub("POST", "/api/ont/anomalies/{}/analyze".format(an["id"]), {}, teacher)
        check(ans["run_id"] and ans["refs"], "让 AI 分析 A-{:05d}：{}".format(an["id"], ans["answer"][:60].replace("\n", " ")))
        run = hub("GET", "/api/ai/runs/{}".format(ans["run_id"]), token=teacher)
        check(len(run["steps"]) >= 2, "运行记录：{} 步（{}）".format(len(run["steps"]), "、".join(s["tool"] for s in run["steps"])))
        b = hub("GET", "/api/ont/banner", token=teacher)["items"]
        check(any(x["id"] == an["id"] for x in b) or bool(b), "首页提醒条 {} 条".format(len(b)))
        n = wait(lambda: next((x for x in hub("GET", "/api/notifications", token=teacher)["items"] if x["ref"] == "A-{:05d}".format(an["id"])), None),
                 "铃铛通知", 60, 3)
        check(n is not None, "铃铛里有这个异常的通知：{}".format((n or {}).get("title")))
    rp = hub("POST", "/api/reports/generate", {"kind": "daily"}, teacher)
    check(rp["data"]["anomalies"]["open"] >= 1 and "厂情日报" in rp["text"], "日报：{}".format(rp["text"].split("\n")[0][:80]))
    st = hub("GET", "/api/lab15", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 15 页：5 个任务，自动评 60 分")
    hub("POST", "/api/mes/cmd", {"unit": "grd-01", "command": "reset"}, teacher)
    print()
    if FAILS:
        # 桥接写 ERPNext 出错时会把原因作为 erp.doc（action=failed）发到总线：列出来，便于定位
        errs = [e for e in hub("GET", "/api/history?type=erp.doc&limit=500", token=mgr) if e["data"].get("action") == "failed"]
        if errs:
            print("ERPNext 退回的出错（最近 {} 条）：".format(min(len(errs), 12)))
            seen = set()
            for e in errs:
                k = (e["data"].get("doctype"), e["data"].get("error", "")[:160])
                if k in seen:
                    continue
                seen.add(k)
                print("  - {} {}：{}".format(e["data"].get("doctype"), e["data"].get("name"), e["data"].get("error", "")[:400]))
                if len(seen) >= 12:
                    break
        if REAL:
            erp_error_log()
        print("失败 {} 项：".format(len(FAILS)))
        for f in FAILS:
            print("  - " + f)
        sys.exit(1)
    print("完整闭环全部通过。")


if __name__ == "__main__":
    main()
