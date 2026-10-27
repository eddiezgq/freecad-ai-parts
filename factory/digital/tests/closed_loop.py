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
P.add_argument("--only", default="", help="只跑某一段（本地调试用）：story = 第 20 段全厂联调情景")
P.add_argument("--upto", type=int, default=0, help="只跑前几段（本地版 CI 跑 1–3 段：--upto 3）")
P.add_argument("--teacher-password", default="", help="本地版（WQ_EDITION=local）当老师要的密码：factory/digital/.env 的 WQ_TEACHER_PASSWORD")
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
    body = {"name": name, "role": role, "mode": "teach"}
    if A.teacher_password:            # 本地版：带老师密码，和服务器演练一样人人是老师（第 30 轮 H-5）
        body["teacher_password"] = A.teacher_password
    return hub("POST", "/api/login", body)["token"]


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
    if A.only == "story":
        story(login("测试教师", "manager"))
        return finish(login("测试教师", "manager"))
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

    if A.upto and A.upto < 4:
        return finish(mgr)
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
    wt = [x["domain"] for x in sit["cards"] if x["waiting"]]
    check(len(sit["cards"]) == 15 and set(wt) <= {"energy"}, "全厂态势 15 块，待接入：{}（第 18 轮 E6 起能源有计量读数后也接上）".format("、".join(wt) or "没有"))
    rl = hub("GET", "/api/ont/rules", token=teacher)["rules"]
    live = [x for x in rl if not x["waiting"]]
    check(len(live) == 61 and not [x["id"] for x in live if x["error"]], "规则 61 条在跑，没有出错（{}）".format([x["id"] for x in live if x["error"]]))

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
              "处理方案推演 {} 个，用时 {:.1f} 秒，{}快照；{}".format(len(kinds), time.time() - t0, "精确" if o["exact"] else "近似", o["reason"]))
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
    customer_and_service(teacher)
    safety(teacher)
    maintenance(teacher)
    people(teacher)
    supply(teacher)
    energy(teacher)
    finance(teacher)
    story(teacher)
    finish(mgr)


def finish(mgr):
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


def customer_and_service(teacher):
    """第 18 轮 E1：销售漏斗（线索 → 商机 → 报价 → 合同）写进 ERPNext；投诉 → 异常 → 服务方案 → 派工（Issue）、备件出库（Stock Entry）→ 完工"""
    print("13. 客户与服务（第 18 轮 E1）")
    sales = login("测试销售", "sales")
    svc = login("测试售后", "service")
    co = "闭环测试客户" + time.strftime("%H%M%S")

    def card(stage, pred):
        return next((x for x in hub("GET", "/api/crm/pipeline", token=sales)["cards"] if x["stage"] == stage and pred(x)), None)
    hub("POST", "/api/crm/leads", {"company_name": co, "note": "闭环测试"}, sales)
    lead = wait(lambda: card("lead", lambda x: x["title"] == co), "ERPNext 建好线索", 120, 3)
    check(lead is not None, "线索写进 ERPNext：{}".format((lead or {}).get("name")))
    if not lead:
        return
    hub("POST", "/api/crm/opportunities", {"from": "Lead", "party": lead["name"], "qty": 4}, sales)
    opp = wait(lambda: card("opportunity", lambda x: x.get("lead") == lead["name"]), "ERPNext 建好商机", 120, 3)
    check(opp is not None and opp["amount"], "商机：{}（${}）".format((opp or {}).get("name"), (opp or {}).get("amount")))
    if not opp:
        return
    hub("POST", "/api/crm/quotations", {"quotation_to": "Lead", "party": lead["name"], "opportunity": opp["name"], "qty": 4}, sales)
    q = wait(lambda: card("quotation", lambda x: x.get("opportunity") == opp["name"]), "ERPNext 建好报价（已提交）", 120, 3)
    check(q is not None and abs(float(q["amount"] or 0) - 6600) < 1, "报价：{}，${}".format((q or {}).get("name"), (q or {}).get("amount")))
    if q:
        hub("POST", "/api/crm/contracts", {"customer": co, "quotation": q["name"], "amount": 6600, "penalty_per_day": 50, "response_h": 24,
                                           "warranty_months": 12}, sales)
        c = wait(lambda: next((x for x in hub("GET", "/api/crm/pipeline", token=sales)["contracts"] if x["customer"] == co and x["signed"]), None),
                 "ERPNext 建好合同", 150, 3)
        check(c is not None and c["penalty_per_day"] == 50, "合同：{}（违约金 $50/天，读回自定义字段）".format((c or {}).get("name")))
    for dt_ in ("Lead", "Opportunity", "Quotation", "Contract"):
        check(len(erp_docs(dt_)) >= 1, "ERPNext 里有 {}".format(dt_))

    us = hub("GET", "/api/service/units", token=svc)["units"]
    check(len(us) >= 6, "现场设备 {} 台".format(len(us)))
    if not us:
        return
    # 不碰有轴承报警的那台：后面“数字孪生”演练（check_cae）要用它开维修单
    s = next((u["serial"] for u in us if "bearing" not in (u.get("alert_kinds") or []) and u["health"] != "green"),
             next(u["serial"] for u in us if "bearing" not in (u.get("alert_kinds") or [])))
    cp = hub("POST", "/api/complaints", {"serial": s, "subject": "闭环测试：减速器异响", "severity": "serious", "channel": "电话"}, svc)
    iss = wait(lambda: next((x for x in erp_docs("Issue") if cp["key"] in (x.get("subject") or "") or "闭环测试：减速器异响" in (x.get("subject") or "")), None),
               "投诉进 ERPNext（Issue）", 120, 3)
    check(iss is not None, "投诉 {} 进 ERPNext：{}".format(cp["key"], (iss or {}).get("name")))
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "C1" and cp["key"] in x["title"]), None),
              "投诉异常 C1", 90, 3)
    check(an is not None, "投诉变成异常 C1：{}".format((an or {}).get("title")))
    if not an:
        return
    d = hub("GET", "/api/ont/anomalies/{}".format(an["id"]), token=teacher)
    check(d["chain"].get("kind") == "field" or any(n["type"] == "FieldUnit" for n in d["chain"]["nodes"]),
          "追溯链：{}".format("；".join(d["chain"]["summary"])[:120]))
    o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
    check(o.get("service") and o["options"] and o["recommended"], "服务方案 {} 个：{}".format(len(o["options"]), (o.get("reason") or "")[:100]))
    # 只采纳“只修出问题的”（不动排查范围里的其他设备），备件出库单独发一张
    best = next(x for x in o["options"] if x["kind"] == "repair_one")
    best = dict(best, changes=[c for c in best["changes"] if c["type"] != "spare_ship"] +
                [{"type": "spare_ship", "items": [{"item_code": "BRG-6206", "qty": 1}]}])
    a = hub("POST", "/api/ont/actions", {"changes": best["changes"], "anomaly_id": an["id"]}, svc)
    check(len(a["ids"]) == len(best["changes"]), "售后起草并提交 {} 个动作".format(len(a["ids"])))
    for i in a["ids"]:
        hub("POST", "/api/ont/actions/{}/approve".format(i), {}, teacher)
    for i in a["ids"]:
        x = wait(lambda: (lambda r: r if r["status"] in ("done", "failed") else None)(hub("GET", "/api/ont/actions/{}".format(i), token=teacher)),
                 "动作执行", 150, 3)
        check(x is not None and x["status"] == "done", "{}：{}".format((x or {}).get("title"), ((x or {}).get("result") or {}).get("text")))
    jobs = wait(lambda: (lambda js: js if js and all(j["issue"] for j in js) else None)(
        [j for j in hub("GET", "/api/service/jobs", token=svc)["jobs"] if j["anomaly_id"] == an["id"]]), "服务工单进 ERPNext", 150, 3)
    check(bool(jobs), "服务工单 {} 张，ERPNext Issue：{}".format(len(jobs or []), "、".join(j["issue"] for j in jobs or [])))
    if any(c["type"] == "spare_ship" for c in best["changes"]):
        se = [x for x in erp_docs("Stock Entry") if x.get("stock_entry_type") == "Material Issue" or x.get("purpose") == "Material Issue"]
        check(bool(se), "备件出库：ERPNext 出库单 {}".format("、".join(x["name"] for x in se[-2:])))
    if jobs:
        try:
            hub("POST", "/api/service/jobs/{}/done".format(jobs[0]["id"]), {"note": "闭环测试：已更换"}, svc)
        except RuntimeError as e:
            # 加速运行时现场工程师（模拟）可能先一步完工：同一个完工流程，下面照样查 ERPNext 服务单已解决
            if "已经完成" not in str(e):
                raise
            print("  （服务工单已由现场工程师完工）")
        r = wait(lambda: next((x for x in erp_docs("Issue") if x["name"] == jobs[0]["issue"] and x.get("status") in ("Resolved", "Closed")), None),
                 "ERPNext 服务单改为已解决", 120, 3)
        check(r is not None, "完工：ERPNext {} 已解决".format(jobs[0]["issue"]))
        f = hub("GET", "/api/followups", token=svc)["followups"]
        check(any(x["serial"] == jobs[0]["serial"] for x in f), "完工后生成回访")
    st = hub("GET", "/api/lab16", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 16 页：5 个任务，自动评 60 分")
    k = hub("GET", "/api/service/kpis", token=teacher)
    check("open_complaints" in k and "funnel_amount" in k, "客户与服务态势：开着的投诉 {}，漏斗 ${}".format(k.get("open_complaints"), k.get("funnel_amount")))


def safety(teacher):
    """第 18 轮 E2：隐患随手拍 → 异常 E1 → 停机挂牌（车间里设备真的停下、不能复位）→ 整改、验收解锁；许可缺资质；整改工单进 ERPNext"""
    print("14. 安全环保（第 18 轮 E2）")
    saf = login("测试安全员", "safety")
    unit = "key-01"

    def mach():
        return next(m for m in hub("GET", "/api/overview", token=teacher)["machines"] if m["unit"] == unit)
    r = hub("POST", "/api/ehs/issues", {"unit": unit, "kind": "guard", "level": "major", "subject": "闭环测试：键槽铣床防护罩缺失"}, saf)
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "E1" and r["key"] in x["title"]), None),
              "重大隐患异常 E1", 90, 3)
    check(an is not None, "随手拍 {} → 异常 E1：{}".format(r["key"], (an or {}).get("title")))
    if not an:
        return
    o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
    kinds = [x["kind"] for x in o["options"]]
    check(o.get("ehs") and kinds[:3] == ["none", "lockout", "temp"], "处理方案：{}；{}".format("、".join(x["label"] for x in o["options"]), o.get("reason")))
    lock = next(x for x in o["options"] if x["kind"] == "lockout")
    a = hub("POST", "/api/ont/actions", {"changes": lock["changes"], "anomaly_id": an["id"], "snapshot_id": o["snapshot_id"]}, saf)
    d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
    check(d["status"] == "done", "停机挂牌：{}".format((d.get("result") or {}).get("text")))
    m = wait(lambda: (lambda m: m if m.get("locked") and m["state"] == "down" else None)(mach()), "车间里设备挂牌上锁", 60, 2)
    check(m is not None, "车间里 {} 停下，挂牌上锁 {}".format(unit.upper(), (m or {}).get("locked")))
    hub("POST", "/api/mes/cmd", {"unit": unit, "command": "reset"}, teacher)
    time.sleep(4)
    check(bool(mach().get("locked")), "挂着锁时“复位”被车间拒绝")
    hub("POST", "/api/ehs/issues/{}/fix".format(r["id"]), {"note": "闭环测试：装回防护罩"}, teacher)
    try:
        hub("POST", "/api/ehs/issues/{}/verify".format(r["id"]), token=teacher)
        check(False, "整改人不能验收自己的整改")
    except RuntimeError as e:
        check("403" in str(e), "整改人不能验收自己的整改")
    v = hub("POST", "/api/ehs/issues/{}/verify".format(r["id"]), token=saf)
    check(v.get("unlock", {}).get("status") == "closed", "安全员验收关闭、许可关闭")
    m = wait(lambda: (lambda m: m if not m.get("locked") and m["state"] != "down" else None)(mach()), "设备解锁恢复", 60, 2)
    check(m is not None, "{} 解锁恢复（{}）".format(unit.upper(), (m or {}).get("state")))
    p = hub("POST", "/api/ehs/permits", {"kind": "confined", "unit": "ht-01", "holder_id": "P07", "reason": "闭环测试：炉膛检修"}, saf)
    check(p["status"] == "blocked", "受限空间许可缺资质被拦下：{}".format(p.get("why")))
    e3 = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "E3" and p["key"] in x["title"]), None),
              "缺资质异常 E3", 90, 3)
    check(e3 is not None, "异常 E3：{}".format((e3 or {}).get("title")))
    a = hub("POST", "/api/ont/actions", {"changes": [{"type": "rectify_order", "unit": unit, "subject": "闭环测试：防护罩加固", "minutes": 60,
                                                      "issue_id": r["id"]}]}, saf)
    hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
    x = wait(lambda: (lambda q: q if q["status"] in ("done", "failed") else None)(hub("GET", "/api/ont/actions/{}".format(a["ids"][0]), token=teacher)),
             "整改工单进 ERPNext", 120, 3)
    check(x is not None and x["status"] == "done", "整改工单：{}".format(((x or {}).get("result") or {}).get("erp")))
    iss = [i for i in erp_docs("Issue") if "安全整改" in (i.get("subject") or "")]
    check(bool(iss), "ERPNext 里有安全整改工单 {}".format("、".join(i["name"] for i in iss[-2:])))
    st = hub("GET", "/api/lab17", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 17 页：5 个任务，自动评 60 分")
    k = hub("GET", "/api/ehs/kpis", token=teacher)
    check(k["locked"] == 0 and "training_due" in k, "安全环保态势：开着的隐患 {}，挂锁 {} 台".format(k["open_issues"], k["locked"]))


def maintenance(teacher):
    """第 18 轮 E3：ERPNext 资产台账与维护计划；点检异常 → M3；保养逾期 → M2 → 保养工单（挂牌上锁）→ 做完 → 验收解锁 → 运行小时清零、
    ERPNext 保养记录；维修单（挂牌上锁）→ ERPNext 资产维修 → 完成"""
    print("15. 设备维护与资产（第 18 轮 E3）")
    mnt = login("测试维修工", "maintenance")
    unit, runit = "hob-01", "vmc-01"

    def mach(u):
        return next(m for m in hub("GET", "/api/overview", token=teacher)["machines"] if m["unit"] == u)
    rows = wait(lambda: (lambda a: a if all(x["asset"] for x in a) else None)(hub("GET", "/api/maint/assets", token=teacher)["assets"]),
                "ERPNext 资产台账", 480, 4)
    check(rows is not None and len(rows) == 13, "ERPNext 资产台账 13 台（{}）".format("、".join(x["asset"] for x in (rows or [])[:3])))
    if rows is None:                                    # 诊断：建台账的提议走到哪一步了
        for p in hub("GET", "/api/proposals", token=teacher):
            if p.get("action") == "maint_setup":
                print("    提议 {} {}：{}".format(p.get("proposal_id"), p.get("status"), json.dumps(p.get("result"), ensure_ascii=False)[:600]))
    mts = erp_docs("Asset Maintenance")
    check(len(mts) >= 13, "ERPNext 维护计划 {} 条".format(len(mts)))
    d = hub("GET", "/api/maint/assets/" + unit, token=teacher)
    check(d["maintenance"] is not None and d["risk"]["beta"] > 1, "台账详情：维护计划 {}，β={}".format((d["maintenance"] or {}).get("name"), d["risk"]["beta"]))
    # 点检
    items = hub("GET", "/api/maint/checklist/" + unit, token=mnt)["items"]
    ic = hub("POST", "/api/maint/inspections", {"unit": unit, "results": [{"item": items[0], "ok": False, "note": "闭环测试"}]}, mnt)
    m3 = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "M3" and unit.upper() in x["title"]), None), "点检异常 M3", 90, 3)
    check(m3 is not None, "点检 {} 有异常 → 异常 M3：{}".format(ic["key"], (m3 or {}).get("title")))
    hub("POST", "/api/maint/inspections/{}/watch".format(ic["id"]), {}, mnt)
    # 保养逾期 → M2 → 保养工单
    pm_h = d["risk"]["pm_h"]
    hub("POST", "/api/lab18/inject", {"factor": 0, "unit": unit, "hours": pm_h + 200}, teacher)
    m = wait(lambda: (lambda m: m if (m.get("run_h_pm") or 0) > pm_h else None)(mach(unit)), "车间运行小时拨到逾期", 60, 2)
    check(m is not None, "车间里 {} 自上次保养运行 {} 小时（周期 {:g}）".format(unit.upper(), (m or {}).get("run_h_pm"), pm_h))
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "M2" and unit.upper() in x["title"]), None),
              "保养逾期异常 M2", 90, 3)
    check(an is not None, "异常 M2：{}".format((an or {}).get("title")))
    if not an:
        return
    o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
    kinds = [x["kind"] for x in o["options"]]
    check(o.get("maint") and kinds == ["none", "pm_now", "pm_later"], "保养时机三方案：{}；{}".format("、".join(x["label"] for x in o["options"]), o.get("reason")))
    now = next(x for x in o["options"] if x["kind"] == "pm_now")
    a = hub("POST", "/api/ont/actions", {"changes": now["changes"], "anomaly_id": an["id"], "snapshot_id": o["snapshot_id"]}, mnt)
    dd = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
    check(dd["status"] == "done", "保养工单：{}".format((dd.get("result") or {}).get("text")))
    m = wait(lambda: (lambda m: m if m.get("locked") and m["state"] == "down" else None)(mach(unit)), "保养挂牌上锁", 60, 2)
    check(m is not None, "车间里 {} 停下保养，挂牌上锁 {}".format(unit.upper(), (m or {}).get("locked")))
    pm = next((x for x in hub("GET", "/api/maint/repairs", token=teacher)["pms"] if x["unit"] == unit and x["status"] == "doing"), None)
    check(pm is not None, "保养单 {}".format((pm or {}).get("key")))
    if not pm:
        return
    hub("POST", "/api/maint/pms/{}/done".format(pm["id"]), {"note": "闭环测试：换油、清洁"}, teacher)
    try:
        hub("POST", "/api/maint/pms/{}/verify".format(pm["id"]), token=teacher)
        check(False, "保养人不能验收自己的保养")
    except RuntimeError as e:
        check("403" in str(e), "保养人不能验收自己的保养")
    hub("POST", "/api/maint/pms/{}/verify".format(pm["id"]), token=mnt)
    m = wait(lambda: (lambda m: m if not m.get("locked") and m["state"] != "down" and (m.get("run_h_pm") or 0) < 5 else None)(mach(unit)),
             "保养后解锁、运行小时清零", 60, 2)
    check(m is not None, "{} 验收解锁，自上次保养回到 {} 小时".format(unit.upper(), (m or {}).get("run_h_pm")))
    lg = wait(lambda: [x for x in erp_docs("Asset Maintenance Log") if x.get("maintenance_status") == "Completed"], "ERPNext 保养记录", 120, 3)
    check(bool(lg), "ERPNext 保养记录 {}".format("、".join(x["name"] for x in (lg or [])[-2:])))
    # 维修单
    r = hub("POST", "/api/maint/repairs", {"unit": runit, "title": "闭环测试：主轴异响"}, mnt)
    m = wait(lambda: (lambda m: m if m.get("locked") else None)(mach(runit)), "维修挂牌上锁", 60, 2)
    check(m is not None, "维修单 {}：{} 挂牌上锁".format(r["key"], runit.upper()))
    ar = wait(lambda: [x for x in erp_docs("Asset Repair") if r["key"] in (x.get("description") or "")], "ERPNext 资产维修单", 120, 3)
    check(bool(ar), "ERPNext 资产维修 {}".format("、".join(x["name"] for x in (ar or []))))
    hub("POST", "/api/maint/repairs/{}/done".format(r["id"]), {"note": "闭环测试：换轴承"}, mnt)
    hub("POST", "/api/maint/repairs/{}/verify".format(r["id"]), token=teacher)                  # 维修工开单、修好，厂长验收
    m = wait(lambda: (lambda m: m if not m.get("locked") else None)(mach(runit)), "维修后解锁", 60, 2)
    check(m is not None, "{} 维修验收解锁".format(runit.upper()))
    done = wait(lambda: [x for x in erp_docs("Asset Repair") if r["key"] in (x.get("description") or "") and x.get("repair_status") == "Completed"],
                "ERPNext 资产维修完成", 120, 3)
    check(bool(done), "ERPNext 资产维修改为完成")
    st = hub("GET", "/api/lab18", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 18 页：5 个任务，自动评 60 分")
    k = hub("GET", "/api/maint/kpis", token=teacher)
    check("mtbf" in k and k["factor"] == 0, "设备维护态势：逾期 {} 台，未关维修单 {}".format(k["overdue"], k["open_repairs"]))


def people(teacher):
    """第 18 轮 E4：员工档案进 ERPNext；车间“要有人”（请假 → 这一班人员等级 0）；关键人请假 → 排班缺口 H2 → 四个方案 → 调班 → 有人了；
    单点依赖 H1 → 技能培训 → 考核通过 → 单点依赖少一台"""
    print("16. 人员与组织（第 18 轮 E4）")
    lead = login("测试班组长", "lead")
    hub("POST", "/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": 1}, teacher)     # 排班按班次：车间回到正常速度，免得一个班两分钟就过去
    time.sleep(5)                                                                                # 等车间发出带工厂时间的状态

    def mach(u):
        return next(m for m in hub("GET", "/api/overview", token=teacher)["machines"] if m["unit"] == u)
    es = wait(lambda: (lambda e: e if all(x["erp_id"] for x in e) else None)(hub("GET", "/api/people/employees", token=teacher)["employees"]),
              "ERPNext 员工档案", 480, 4)
    check(es is not None and len(es) == 30, "ERPNext 员工档案 30 人（{}）".format("、".join("{} {}".format(x["id"], x["erp_id"]) for x in (es or [])[:2])))
    if es is None:
        for p in hub("GET", "/api/proposals", token=teacher):
            if p.get("action") == "people_setup":
                print("    提议 {} {}：{}".format(p.get("proposal_id"), p.get("status"), json.dumps(p.get("result"), ensure_ascii=False)[:600]))
    deps = [d for d in erp_docs("Department") if d.get("department_name") in ("机加一班", "设备组")]
    check(len(deps) == 2, "ERPNext 部门：{}".format("、".join(d["name"] for d in deps)))
    hub("POST", "/api/people/staffing", {"enabled": True}, teacher)
    td = hub("GET", "/api/people/today", token=teacher)
    op = next((p for p in td["people"] if "saw-01" in p["units"]), None)
    check(op is not None, "这一班锯床是 {}".format((op or {}).get("name")))
    if op:
        m = wait(lambda: (lambda m: m if m.get("staff_level") == 2 else None)(mach("saw-01")), "车间收到排班", 60, 2)
        check(m is not None, "车间“要有人”打开，锯床这一班人员等级 2")
        hub("POST", "/api/people/attendance", {"emp_id": op["id"], "status": "leave", "day": td["day"], "shift": td["shift"]}, lead)
        m = wait(lambda: (lambda m: m if m.get("staff_level") == 0 else None)(mach("saw-01")), "请假后锯床没人", 60, 2)
        check(m is not None, "{} 请假：锯床这一班没人能开（人员等级 0）".format(op["name"]))
        hub("POST", "/api/people/attendance/clear", {"emp_id": op["id"], "day": td["day"], "shift": td["shift"]}, lead)
        m = wait(lambda: (lambda m: m if m.get("staff_level") == 2 else None)(mach("saw-01")), "恢复在岗", 60, 2)
        check(m is not None, "恢复在岗：锯床人员等级回到 2")
    r = hub("POST", "/api/lab19/inject", {"enable": True, "emp_id": "P01"}, teacher)
    check("请假" in r.get("text", ""), "老师注入：{}".format(r.get("text")))
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "H2" and "GRD-01" in x["title"]), None),
              "排班缺口异常 H2", 90, 3)
    check(an is not None, "异常 H2：{}".format((an or {}).get("title")))
    if an:
        o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
        kinds = [x["kind"] for x in o["options"]]
        check(o.get("people") and kinds[:2] == ["none", "swap"], "缺人四方案：{}；{}".format("、".join(x["label"] for x in o["options"]), o.get("reason")))
        sw = next(x for x in o["options"] if x["kind"] == "swap")
        a = hub("POST", "/api/ont/actions", {"changes": sw["changes"], "anomaly_id": an["id"], "snapshot_id": o["snapshot_id"]}, lead)
        d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
        check(d["status"] == "done", "调班：{}".format((d.get("result") or {}).get("text")))
        ch = sw["changes"][0]
        ro = hub("GET", "/api/people/roster?week=" + ch["day"], token=teacher)
        cell = next(r for r in ro["rows"] if r["day"] == ch["day"] and r["shift"] == ch["shift"])["cells"]["grd-01"]
        check(cell["level"] == 2 and cell["source"] == "swap", "排班里 {} {} 磨床由 {} 顶岗".format(ch["day"], ch["shift"], cell["name"]))
    h1 = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "H1" and "HOB-01" in x["title"]), None),
              "单点依赖异常 H1", 60, 3)
    check(h1 is not None, "异常 H1：{}".format((h1 or {}).get("title")))
    if h1:
        o = hub("GET", "/api/ont/anomalies/{}/options".format(h1["id"]), token=teacher)
        t = next(x for x in o["options"] if x["kind"] == "training")
        a = hub("POST", "/api/ont/actions", {"changes": t["changes"], "anomaly_id": h1["id"]}, lead)
        d = hub("POST", "/api/ont/actions/{}/approve".format(a["ids"][0]), {}, teacher)
        check(d["status"] == "done", "技能培训：{}".format((d.get("result") or {}).get("text")))
        tr = next(x for x in hub("GET", "/api/people/trainings", token=teacher)["trainings"] if x["status"] == "doing" and x["unit"] == "hob-01")
        hub("POST", "/api/people/trainings/{}/pass".format(tr["id"]), {}, lead)
        sk = hub("GET", "/api/people/skills", token=teacher)
        check("hob-01" not in [x["unit"] for x in sk["single_points"]], "考核通过：滚齿机不再是单点依赖（还剩 {} 台）".format(len(sk["single_points"])))
    st = hub("GET", "/api/lab19", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 19 页：5 个任务，自动评 60 分")
    k = hub("GET", "/api/people/kpis", token=teacher)
    check("attendance_rate" in k and k["enabled"], "人员态势：出勤率 {:.0%}，缺口 {}，单点依赖 {} 台".format(k["attendance_rate"], k["gaps"], k["single_points"]))
    hub("POST", "/api/people/staffing", {"enabled": False}, teacher)
    hub("POST", "/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": A.speed}, teacher)   # 后面的虚拟 PLC 演练按原来的倍速


def supply(teacher):
    """第 18 轮 E5：备选供应商进 ERPNext；采购单 → 在途 → 到货 → 来料检验不合格（ERPNext 检验单、收货单草稿）→ W3 → 四个方案 →
    退货 + 备选急单（ERPNext 采购单）→ 到货 → 检验合格 → 收货单提交入库、库存增加"""
    print("17. 供应链（第 18 轮 E5）")
    qa = login("测试质量", "quality")
    pl = login("测试计划员", "planner")

    def lot(lid):
        return next((x for x in hub("GET", "/api/supply/lots", token=teacher)["lots"] if x["id"] == lid), None)

    def stock(item):
        return sum(float(b.get("actual_qty") or 0) for b in erp_docs("Bin") if b.get("item_code") == item)
    sp = hub("GET", "/api/supply/suppliers", token=teacher)
    check(len(sp["suppliers"]) == 10 and {x["cat"] for x in sp["single_source"]} == {"castings", "forgings", "hardware", "lubricant"},
          "供应商 10 家（4 家备选），单一来源：{}".format("、".join(x["cat_name"] for x in sp["single_source"])))
    r = hub("POST", "/api/lab20/inject", {"enable": True}, teacher)
    lid = r.get("lot_id")
    check(bool(lid), "老师注入：{}".format(r.get("text")))
    if not lid:
        return
    x = wait(lambda: (lambda x: x if x and x["status"] == "transit" else None)(lot(lid)), "采购单进 ERPNext、供应商发货", 240, 4)
    check(x is not None and x["po"], "采购单 {}，在途，承诺 {} 到货".format((x or {}).get("po"), (x or {}).get("promised")))
    if not x:
        for p in hub("GET", "/api/proposals", token=teacher):
            if p.get("action") in ("purchase_order", "supply_setup"):
                print("    提议 {} {} {}：{}".format(p.get("action"), p.get("proposal_id"), p.get("status"), json.dumps(p.get("result"), ensure_ascii=False)[:500]))
        return
    pos = [p for p in erp_docs("Purchase Order") if p["name"] == x["po"]]
    check(bool(pos), "ERPNext 采购单 {}（{}）".format(x["po"], pos[0].get("supplier") if pos else "—"))
    hub("POST", "/api/supply/lots/{}/arrive".format(lid), {}, pl)
    sm = hub("GET", "/api/supply/lots/{}/sample".format(lid), token=qa)
    bad = [1 for row in sm["rows"] for p in sm["params"] if p["numeric"] and not (p["min"] <= row[p["specification"]] <= p["max"])]
    check(len(bad) >= 2, "抽样 {} 件，{} 处超差".format(sm["sample_size"], len(bad)))
    r = hub("POST", "/api/supply/lots/{}/inspect".format(lid), {"accept": False, "note": "闭环测试：内径偏差超差"}, qa)
    check(r["status"] == "rejected", "质量判不合格")
    pr = wait(lambda: (lambda p: p if p and p["status"] == "executed" else None)(hub("GET", "/api/proposals/{}".format(r["proposal_id"]), token=teacher)),
              "ERPNext 来料检验单", 120, 3)
    check(pr is not None, "ERPNext：{}".format(((pr or {}).get("result") or {}).get("created")))
    an = wait(lambda: next((a for a in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if a["rule"] == "W3" and x["lot"] in a["title"]), None),
              "来料不合格异常 W3", 90, 3)
    check(an is not None, "异常 W3：{}".format((an or {}).get("title")))
    if not an:
        return
    o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
    kinds = [y["kind"] for y in o["options"]]
    check(o.get("supply") and kinds == ["none", "return", "alt", "concession"], "来料不合格四方案：{}；{}".format("、".join(y["label"] for y in o["options"]), o.get("reason")))
    alt = next(y for y in o["options"] if y["kind"] == "alt")
    a = hub("POST", "/api/ont/actions", {"changes": alt["changes"], "anomaly_id": an["id"]}, pl)
    for aid in a["ids"]:
        d = hub("POST", "/api/ont/actions/{}/approve".format(aid), {}, teacher)
        check(d["status"] in ("done", "executing"), "{}：{}".format(d["title"], (d.get("result") or {}).get("text")))
    check(lot(lid)["status"] == "returned", "这一批退货")
    nl = wait(lambda: next((y for y in hub("GET", "/api/supply/lots", token=teacher)["lots"] if y["supplier"].startswith("示例·北方") and y["status"] == "transit"), None),
              "备选急单进 ERPNext", 240, 4)
    check(nl is not None, "备选供应商急单 {}：{} × {:g}".format((nl or {}).get("po"), (nl or {}).get("item"), (nl or {}).get("qty", 0)))
    if not nl:
        return
    s0 = stock("BRG-6207")
    hub("POST", "/api/supply/lots/{}/arrive".format(nl["id"]), {}, pl)
    sm = hub("GET", "/api/supply/lots/{}/sample".format(nl["id"]), token=qa)
    ok = all(p["min"] <= row[p["specification"]] <= p["max"] for row in sm["rows"] for p in sm["params"] if p["numeric"])
    r = hub("POST", "/api/supply/lots/{}/inspect".format(nl["id"]), {"accept": ok}, qa)
    check(r["status"] == ("accepted" if ok else "rejected"), "备选这一批检验：{}".format("合格" if ok else "不合格（随机）"))
    if ok:
        prs = wait(lambda: [p for p in erp_docs("Purchase Receipt") if p.get("docstatus") == 1 and (p.get("wq_lot") == nl["lot"] or nl["lot"] in str(p.get("remarks") or ""))],
                   "ERPNext 收货单提交", 120, 3)
        check(bool(prs), "ERPNext 收货单 {} 提交入库".format("、".join(p["name"] for p in (prs or []))))
        s1 = wait(lambda: (lambda v: v if v >= s0 + float(nl["qty"]) - 0.01 else None)(stock("BRG-6207")), "库存增加", 90, 3)
        check(s1 is not None, "BRG-6207 库存 {:g} → {:g}".format(s0, s1 or 0))
    st = hub("GET", "/api/lab20", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 20 页：5 个任务，自动评 60 分")
    k = hub("GET", "/api/supply/kpis", token=teacher)
    check("pass_rate" in k, "供应链态势：在途 {}，合格率 {}".format(k["in_transit"], k["pass_rate"]))
    hub("POST", "/api/supply/sim", {"enabled": False}, teacher)


def energy(teacher):
    """第 18 轮 E6：仿真车间每 15 分钟（工厂时间）发计量读数 → 平台入库 → 老师注入忘关 + 峰时开炉 → 空转异常 N2 → 四个方案 →
    计划员采纳自动待机、厂长批准 → 车间按新设定待机；态势、碳核算、实验 21 页"""
    print("18. 能源与环境（第 18 轮 E6）")
    pl = login("测试计划员", "planner")
    ov = wait(lambda: (lambda o: o if o["hours"] > 0 else None)(hub("GET", "/api/energy/overview", token=teacher)), "计量读数入库", 180, 3)
    check(ov is not None, "计量读数：{} 用电 {} 度，电费 ${}，{} 个计量点".format((ov or {}).get("day"), (ov or {}).get("kwh"), (ov or {}).get("cost"),
                                                                    len(hub("GET", "/api/energy/meters", token=teacher)["meters"])))
    if not ov:
        return
    r = hub("POST", "/api/lab21/inject", {"enable": True}, teacher)
    check("HMC-01" in r.get("text", ""), "老师注入：{}".format(r.get("text")))
    an = wait(lambda: next((a for a in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if a["rule"] == "N2"), None), "空转异常 N2", 240, 4)
    check(an is not None, "异常 N2：{}".format((an or {}).get("title")))
    if not an:
        return
    o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
    kinds = [y["kind"] for y in o["options"]]
    check(o.get("energy") == "N2" and kinds == ["none", "standby10", "standby30", "all10"], "空转四方案：{}；{}".format("、".join(y["label"] for y in o["options"]), o.get("reason")))
    sb = next(y for y in o["options"] if y["kind"] == "standby10")
    unit = sb["changes"][0]["units"][0]
    check((sb.get("saving") or {}).get("kwh", 0) > 0, "{}：{}".format(sb["label"], sb["note"]))
    a = hub("POST", "/api/ont/actions", {"changes": sb["changes"], "anomaly_id": an["id"]}, pl)
    for aid in a["ids"]:
        d = hub("POST", "/api/ont/actions/{}/approve".format(aid), {}, teacher)
        check(d["status"] == "done", "{}：{}".format(d["title"], (d.get("result") or {}).get("text")))
    on = wait(lambda: next((m for m in hub("GET", "/api/history?type=energy.reading&limit=5", token=teacher)
                            if unit in (m["data"].get("standby") or {})), None), "车间按新设定运行", 120, 3)
    check(on is not None, "车间读数里 {} 已设自动待机".format(unit.upper()))
    k = hub("GET", "/api/energy/kpis", token=teacher)
    check(k.get("kwh", 0) > 0, "能源态势：用电 {} 度，峰时 {}，空转 {}".format(k.get("kwh"), k.get("peak_share"), k.get("idle_share")))
    c = hub("GET", "/api/energy/carbon", token=teacher)
    check(c["t_co2e"] > 0, "碳核算 {}：{} 吨 CO2e".format(c["month"], c["t_co2e"]))
    st = hub("GET", "/api/lab21", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 21 页：5 个任务，自动评 60 分")
    hub("POST", "/api/energy/sim", {"sim": False}, teacher)


def finance(teacher):
    """第 18 轮 E7：订单做完 → ERPNext 销售发票；来料合格 → 采购发票；登记收款 → 收款单；付款动作 → 付款单；
    注入逾期 → 应收逾期 F2 → 三个方案 → 销售催款、厂长批准；毛利、指标树、预算、实验 22 页"""
    print("19. 经营与财务（第 18 轮 E7）")
    sa = login("测试销售", "sales")

    def inv(pred, what, timeout=240):
        return wait(lambda: next((x for x in hub("GET", "/api/finance/ar", token=teacher)["invoices"] if pred(x)), None), what, timeout, 4)
    si = inv(lambda x: x["doc"] and x["status"] in ("open", "paying"), "订单做完开票（ERPNext 销售发票）")
    check(si is not None, "销售发票 {}：{} ${:,.0f}，订单 {}".format((si or {}).get("doc"), str((si or {}).get("party") or "").split(" ")[0],
                                                             (si or {}).get("amount", 0), (si or {}).get("ref")))
    if si is None:                       # 诊断：开票提议、订单的工单状态
        for p in hub("GET", "/api/proposals", token=teacher):
            if p.get("action") == "sales_invoice":
                check(False, "诊断 开票提议 {} {}：{}".format(p.get("proposal_id"), p.get("status"), json.dumps(p.get("result"), ensure_ascii=False)[:400]))
        rows = hub("GET", "/api/finance/ar", token=teacher)["invoices"]
        check(False, "诊断 应收：{}".format([(x["id"], x["ref"], x["status"], x["doc"]) for x in rows]))
        wos = [(w["name"], w.get("status"), w.get("sales_order") or w.get("wq_sales_order"), w.get("produced_qty"), w.get("qty")) for w in erp_docs("Work Order")][-6:]
        check(False, "诊断 工单：{}".format(wos))
    if si:
        sis = [d for d in erp_docs("Sales Invoice") if d["name"] == si["doc"]]
        check(bool(sis) and sis[0].get("docstatus") == 1, "ERPNext 销售发票 {} 已提交，未付 ${}".format(si["doc"], sis[0].get("outstanding_amount") if sis else "—"))
        r = hub("POST", "/api/finance/invoices/{}/receive".format(si["id"]), {}, sa)
        check(r["status"] == "paying", "登记收款：{}".format(r.get("proposal_id")))
        paid = wait(lambda: next((x for x in erp_docs("Sales Invoice") if x["name"] == si["doc"] and float(x.get("outstanding_amount") or 0) <= 0.005), None),
                    "ERPNext 收款单冲销发票", 120, 3)
        check(paid is not None, "ERPNext 收款后 {} 已付清（{}）".format(si["doc"], (paid or {}).get("status")))
    ap = wait(lambda: next((x for x in hub("GET", "/api/finance/ap", token=teacher)["invoices"] if x["doc"]), None), "来料合格 → 采购发票", 240, 4)
    check(ap is not None, "采购发票 {}：{} ${:,.0f}（收货单 {}）".format((ap or {}).get("doc"), str((ap or {}).get("party") or "").split(" ")[0],
                                                                  (ap or {}).get("amount", 0), (ap or {}).get("ref")))
    if ap:
        a = hub("POST", "/api/ont/actions", {"changes": [{"type": "payment", "invoice_id": ap["id"]}]}, sa)
        for aid in a["ids"]:
            d = hub("POST", "/api/ont/actions/{}/approve".format(aid), {}, teacher)
            check(d["status"] in ("done", "executing"), "{}：{}".format(d["title"], (d.get("result") or {}).get("text")))
        pe = wait(lambda: next((x for x in erp_docs("Purchase Invoice") if x["name"] == ap["doc"] and float(x.get("outstanding_amount") or 0) <= 0.005), None),
                  "ERPNext 付款单", 120, 3)
        check(pe is not None, "ERPNext 付款后 {} 已付清".format(ap["doc"]))
    r = hub("POST", "/api/lab22/inject", {"enable": True}, teacher)
    check("海港" in r.get("text", ""), "老师注入：{}".format(r.get("text")))
    an = wait(lambda: next((x for x in hub("GET", "/api/ont/anomalies", token=teacher)["anomalies"] if x["rule"] == "F2" and "海港" in x["title"]), None),
              "应收逾期异常 F2", 90, 3)
    check(an is not None, "异常 F2：{}".format((an or {}).get("title")))
    if an:
        o = hub("GET", "/api/ont/anomalies/{}/options".format(an["id"]), token=teacher)
        kinds = [y["kind"] for y in o["options"]]
        check(o.get("finance") == "F2" and kinds == ["none", "dunning", "hold"], "应收逾期三方案：{}；{}".format("、".join(y["label"] for y in o["options"]), o.get("reason")))
        dn = next(y for y in o["options"] if y["kind"] == "dunning")
        a = hub("POST", "/api/ont/actions", {"changes": dn["changes"], "anomaly_id": an["id"]}, sa)
        for aid in a["ids"]:
            d = hub("POST", "/api/ont/actions/{}/approve".format(aid), {}, teacher)
            check(d["status"] == "done", "{}：{}".format(d["title"], (d.get("result") or {}).get("text")))
    m = hub("GET", "/api/finance/margins", token=teacher)
    check(bool(m["margins"]), "订单毛利：{} 张，毛利率 {}".format(len(m["margins"]), m["gross_margin"]))
    ob = hub("GET", "/api/finance/objectives", token=teacher)
    check(len(ob["objectives"]) == 7, "经营目标 7 个，达标 {} 个".format(sum(1 for x in ob["objectives"] if x["tone"] == "good")))
    b = hub("GET", "/api/finance/budget", token=teacher)
    check(len(b["rows"]) == 7, "{} 预算 7 个成本中心，已用 ${:,.0f} / ${:,.0f}".format(b["month"], b["total_actual"], b["total_budget"]))
    st = hub("GET", "/api/lab22", token=teacher)
    check(st["of"] == 60 and len(st["tasks"]) == 5, "实验 22 页：5 个任务，自动评 60 分")
    hub("POST", "/api/finance/sim", {"sim": False}, teacher)


def story(teacher):
    """第 19 轮：全厂体检——两周情景八幕在真 ERPNext 上跑一遍：每幕的异常出现；采纳方案、批准、执行；
    订单做完开票、逾期、催款；复盘里这张订单的毛利包含各幕的钱，因果链从钱追回源头异常"""
    print("20. 全厂联调：两周情景（第 19 轮）")
    roles = {"W1": ("测试计划员", "planner"), "W3": ("测试计划员", "planner"), "H2": ("测试班组长", "lead"), "E1": ("测试安全员", "safety"),
             "M2": ("测试维修工", "maintenance"), "N2": ("测试计划员", "planner"), "F2": ("测试销售", "sales")}
    prefer = {"W1": ["urgent_purchase", "expedite"], "W3": ["alt"], "H2": ["overtime"], "E1": ["lockout"], "M2": ["pm_later", "pm_now"],
              "N2": ["standby10"], "F2": ["dunning"]}

    def st():
        return hub("GET", "/api/story/state", token=teacher)

    def beat(n):
        return next(b for b in st()["beats"] if b["n"] == n)

    r = hub("POST", "/api/story/start", {"speed": max(60, min(A.speed, 300))}, teacher)
    check(r["run"] and len(r["beats"]) == 8, "开始两周情景：{} 幕，订单 {} × {}".format(len(r["beats"]), r["scenario"]["item"], r["scenario"]["qty"]))
    ok = wait(lambda: (lambda x: x if x["run"]["status"] == "ready" else None)(st()), "车间载入实验 7 情景", 120, 3)
    check(ok is not None, "情景载入，可以开演")
    if not ok:
        return
    for n in range(1, 9):
        if n == 8:
            done = wait(lambda: (lambda x: x if x["next"]["ok"] else None)(st()), "车间做完这张订单", A.timeout, 5)
            o = st()["order"]
            check(done is not None, "订单 {} 做完（{} / {} 根）".format(st()["run"]["so"], o.get("parts"), o.get("qty")))
            if not done:
                return
        res = wait(lambda: (lambda x: x if x["next"]["ok"] else None)(st()), "第 {} 幕可以演".format(n), 240, 3)
        if res is None:
            check(False, "第 {} 幕：{}".format(n, st()["next"]["why"]))
            return
        try:
            hub("POST", "/api/story/next", {}, teacher)
        except RuntimeError as e:
            if "还没进 ERPNext" in str(e):
                time.sleep(15)
                hub("POST", "/api/story/next", {}, teacher)
            else:
                raise
        b = wait(lambda: (lambda b: b if b["status"] == "ok" else None)(beat(n)), "第 {} 幕的异常".format(n), 240, 4)
        bb = beat(n)
        check(b is not None, "第 {} 幕“{}”：{}{}".format(n, bb["title"], (bb.get("note") or "")[:90],
                                                     "；" + "、".join(x["title"][:30] for x in bb["seen"]) if bb.get("seen") else ""))
        if not b:
            return
        for x in b["seen"]:
            if not x.get("id") or x["rule"] not in roles:
                continue
            o = hub("GET", "/api/ont/anomalies/{}/options".format(x["id"]), token=teacher)
            opts = [y for y in o["options"] if y.get("changes")]
            pick = next((y for k in prefer.get(x["rule"], []) for y in opts if y["kind"] == k), None) or \
                next((y for y in opts if y.get("recommended")), None) or (opts[0] if opts else None)
            if pick is None:                  # 例如缺料：第 2 幕已下的采购单在途、够用，推演只剩“不处理”——这也是一个结果，不算失败
                check(bool(o["options"]), "第 {} 幕 {} 只有“{}”，不用采纳".format(n, x["rule"], "、".join(y["label"] for y in o["options"])))
                continue
            who_ = login(*roles[x["rule"]])
            a = hub("POST", "/api/ont/actions", {"changes": pick["changes"], "anomaly_id": x["id"], "snapshot_id": o.get("snapshot_id")}, who_)
            for aid in a["ids"]:
                d = hub("POST", "/api/ont/actions/{}/approve".format(aid), {}, teacher)
                check(d["status"] in ("done", "executing"), "  {} → {}：{}".format(x["rule"], pick["label"], (d.get("result") or {}).get("text", d["status"])))
    rv = hub("GET", "/api/story/review?report=1", token=teacher)
    m = rv["margin"] or {}
    lines = {x["key"]: x for x in m.get("lines", [])}
    check(m and abs(sum(x["usd"] for x in m["lines"]) - m["cost"]) < 0.05, "复盘：{} 毛利率 {}（按标准 {}）".format(rv["sales_order"], m.get("margin_pct"), m.get("std_margin_pct")))
    acts = (lines.get("actions") or {}).get("actions") or []
    check(len(acts) >= 2 and lines["actions"]["usd"] > 0, "订单上记了 {} 笔动作费用 ${}（{}）".format(len(acts), (lines.get("actions") or {}).get("usd"),
                                                                                "、".join(a["title"][:16] for a in acts[:4])))
    check("idle" in lines, "空转电分摊：${}（{}）".format(lines.get("idle", {}).get("usd"), lines.get("idle", {}).get("how")))
    check(rv["invoice"] and rv["invoice"]["doc"], "逾期的是这张订单自己的发票 {}（{}，催过 {} 次）".format((rv["invoice"] or {}).get("doc"),
                                                                                    (rv["invoice"] or {}).get("status_name"), (rv["invoice"] or {}).get("dunned_n")))
    an = [n for n in rv["chain"]["nodes"] if n["type"] == "Anomaly"]
    check(len({n["domain"] for n in an}) >= 3, "复盘因果链：{} 个异常、{} 个领域；{}".format(len(an), len({n["domain"] for n in an}), "；".join(rv["chain"]["summary"])[:120]))
    f2 = next((x for b in rv["beats"] if b["n"] == 8 for x in b["anomalies"] if x.get("id")), None)
    if f2:
        d = hub("GET", "/api/ont/anomalies/{}".format(f2["id"]), token=teacher)
        srcs = [n for n in d["chain"]["nodes"] if n["type"] == "Anomaly" and n["key"] != "A-{:05d}".format(f2["id"])]
        check(any(n["values"].get("规则") in ("W1", "W3") for n in srcs), "应收逾期的因果链从发票 → 订单 → 动作，追回到缺料 / 来料不合格（{}）".format(
            "、".join(n["values"].get("规则") or "" for n in srcs)))
    check(rv.get("report") and "周报" in (rv["report"]["text"] or "") or bool(rv.get("report")), "两周的周报已生成")
    hub("POST", "/api/story/end", {}, teacher)


if __name__ == "__main__":
    main()
