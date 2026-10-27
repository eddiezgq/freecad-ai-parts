#!/usr/bin/env python3
"""任意一座工厂（清单第 2 版，第 45 轮）的订单到开票闭环演练：接单 → 算料 → 提议确认写进 ERPNext → 自制件、
总装逐个工单下达开工 → 车间完工 → 测试标定出测量值 → ERPNext 作业卡、完工入库 → 订单做完开票。

和 closed_loop.py（减速器厂的完整演练）不同，这里不认任何具体物料：产品、BOM、测量特性都从 /api/config、
/api/plan/order、/api/quality/characteristics 读。

用法：python tests/plant_loop.py --hub http://localhost:8100 --erp http://localhost:8091 --item WQ-AGV300 \\
         --expect-buy WQR-105 [--erp-kind real --erp-key K --erp-secret S]
"""
import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

P = argparse.ArgumentParser()
P.add_argument("--hub", default="http://localhost:8100")
P.add_argument("--erp", default="http://localhost:8091")
P.add_argument("--erp-kind", choices=("mock", "real"), default="mock")
P.add_argument("--erp-key", default="")
P.add_argument("--erp-secret", default="")
P.add_argument("--item", action="append", default=[], help="要接单的产品（可写多次）；不写 = 清单里第一种成品")
P.add_argument("--qty", type=int, default=1)
P.add_argument("--expect-buy", action="append", default=[], help="算料的请购里必须有的物料")
P.add_argument("--expect-products", default="", help="“订单与计划”里必须有的产品，逗号分隔")
P.add_argument("--speed", type=float, default=300)
P.add_argument("--timeout", type=float, default=900)
P.add_argument("--teacher-password", default="", help="本地版（WQ_EDITION=local）当厂长要的老师密码")
P.add_argument("--lab24", action="store_true", help="接 WQ-CR5 后按实验 24 的六个任务答题，核对拿满 60 分（第 47 轮）")
A = P.parse_args()
REAL = A.erp_kind == "real"
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


def erp_docs(doctype):
    if not REAL:
        return call("GET", A.erp + "/api/mock/db/" + urllib.parse.quote(doctype))
    q = urllib.parse.urlencode({"fields": '["*"]', "limit_page_length": 0})
    return call("GET", "{}/api/resource/{}?{}".format(A.erp, urllib.parse.quote(doctype), q),
                headers={"Authorization": "token {}:{}".format(A.erp_key, A.erp_secret)})["data"]


def erp_doc(doctype, name):
    if not REAL:
        return next((d for d in erp_docs(doctype) if d["name"] == name), None)
    return call("GET", "{}/api/resource/{}/{}".format(A.erp, urllib.parse.quote(doctype), urllib.parse.quote(name)),
                headers={"Authorization": "token {}:{}".format(A.erp_key, A.erp_secret)})["data"]


def erp_error_log(n=4):
    """真 ERPNext 的错误日志：最近几条出错的最后几行（等不到完工入库时打印，CI 诊断用）"""
    if not REAL:
        return
    q = urllib.parse.urlencode({"fields": '["name","method","error","creation"]', "order_by": "creation desc", "limit_page_length": 20})
    try:
        rows = call("GET", "{}/api/resource/Error%20Log?{}".format(A.erp, q),
                    headers={"Authorization": "token {}:{}".format(A.erp_key, A.erp_secret)})["data"]
    except RuntimeError as e:
        rows = [{"method": "读不到 Error Log", "error": str(e), "creation": ""}]
    seen = set()
    for r in rows:
        tail = [x for x in (r.get("error") or "").strip().splitlines() if x.strip()][-4:]
        key = tail[-1] if tail else r.get("method")
        if key in seen:
            continue
        seen.add(key)
        print("  ✗ 诊断 ERPNext 错误日志 {} {}：{}".format(str(r.get("creation", ""))[:19], r.get("method") or "", " | ".join(x.strip()[:200] for x in tail)))
        if len(seen) >= n:
            break


def check(cond, what):
    print(("  ✓ " if cond else "  ✗ ") + what)
    if not cond:
        FAILS.append(what)
    return cond


def wait(fn, what, timeout=None, every=3):
    t0 = time.time()
    while time.time() - t0 < (timeout or A.timeout):
        try:
            v = fn()
        except RuntimeError as e:
            if "Unknown column" not in str(e):
                raise
            v = None
        if v:
            return v
        time.sleep(every)
    check(False, "等待超时：" + what)
    return None


def delivery_date():
    d = dt.date.today() + dt.timedelta(days=21)
    return (d + dt.timedelta(days=(7 - d.weekday()) % 7 if d.weekday() >= 5 else 0)).isoformat()


def login(role):
    body = {"name": "清单演练", "role": role, "mode": "teach"}
    if A.teacher_password:
        body["teacher_password"] = A.teacher_password
    return hub("POST", "/api/login", body)["token"]


def release(wo, tok):
    rel = hub("POST", "/api/mes/release", {"work_order": wo}, tok)["dispatched"]
    time.sleep(1)
    for d in rel:
        hub("POST", "/api/mes/cmd", {"unit": d["unit"], "command": "start", "work_order": wo, "operation": d["operation"]}, tok)
    return rel


def shop_done(wo, tok):
    evs = hub("GET", "/api/history?type=machine.event&corr={}&limit=500".format(urllib.parse.quote(wo)), token=tok)
    return any(e["data"].get("event") == "op_complete" and e["data"].get("last_op") for e in evs)


def one(item, mgr):
    cfg = hub("GET", "/api/config", token=mgr)
    customer = cfg["customers"][0]
    print("— 接单：{} × {}（客户 {}）".format(item, A.qty, customer.split(" ")[0]))
    pv = hub("POST", "/api/plan/order", {"customer": customer, "item": item, "qty": A.qty, "delivery_date": delivery_date()}, mgr)
    made = [w["production_item"] for w in pv["work_orders"]]
    buys = {m["item_code"] for m in pv["material_requests"]}
    check(item in made, "算料：{} 的工单 {} 张（{}）".format(item, len(made), "、".join(made)))
    p = hub("POST", "/api/proposals", {"action": "create_order_and_plan", "customer": customer, "item": item, "qty": A.qty,
                                       "delivery_date": delivery_date()}, mgr)
    pid = p["proposal_id"]
    hub("POST", "/api/proposals/{}/confirm".format(pid), token=mgr)
    prop = wait(lambda: (lambda x: x if x["status"] in ("executed", "failed") else None)(
        hub("GET", "/api/proposals/" + pid, token=mgr)), "桥接执行提议", 120, 2)
    if not check(prop and prop["status"] == "executed", "提议已执行：{}".format(prop and str(prop.get("result"))[:200])):
        return
    res = prop["results"]
    so = next(d["name"] for d in res if d["doctype"] == "Sales Order")
    wos = {}
    for d in res:
        if d["doctype"] == "Work Order":
            w = erp_doc("Work Order", d["name"])
            wos[w["production_item"]] = d["name"]
    mrs = [d["name"] for d in res if d["doctype"] == "Material Request"]
    check(set(wos) == set(made), "ERPNext 订单 {}，工单 {} 张与算料一致".format(so, len(wos)))
    mr_items = {i["item_code"] for n in mrs for i in (erp_doc("Material Request", n) or {}).get("items", [])}
    check(bool(mr_items) or not buys, "ERPNext 请购单 {} 张，{} 种物料".format(len(mrs), len(mr_items)))
    for b in A.expect_buy:
        if item_needs(item, b, cfg):
            check(b in mr_items, "请购单里有 {}".format(b))

    op = login("operator")
    hub("POST", "/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": A.speed}, mgr)
    # 按 BOM 层次下达：一张工单的自制件、部件在 ERPNext 里完工入库了，它才下达（不然完工入库时半成品库存不足）
    comps = {w["production_item"]: [c for c, src in (w.get("sources") or {}).items() if src == "semi" and c in wos]
             for w in pv["work_orders"]}
    pending, finished = set(made), set()

    def erp_completed(i):
        """完成：ERPNext 工单 Completed；有不合格品时按合格数入库，工单停在“进行中”也算这一层做完（不合格品单另行处置）"""
        w = erp_doc("Work Order", wos[i]) or {}
        return w.get("status") == "Completed" or float(w.get("produced_qty") or 0) > 0
    while pending:
        ready = sorted(i for i in pending if all(c in finished for c in comps.get(i, [])))
        if not ready:
            check(False, "BOM 有环？还没下达：{}".format("、".join(sorted(pending))))
            break
        for i in ready:
            check(len(release(wos[i], op)) > 0, "下达 {}（{}）".format(i, wos[i]))
        if not wait(lambda: all(shop_done(wos[i], op) for i in ready), "车间完工：" + "、".join(ready), A.timeout, 5):
            break
        if not wait(lambda: all(erp_completed(i) for i in ready), "ERPNext 完工入库：" + "、".join(ready),
                    600 if REAL else 120, 10 if REAL else 3):
            for i in ready:
                jcs = [j for j in erp_docs("Job Card") if j.get("work_order") == wos[i]]
                check(False, "诊断 {} 的作业卡：{}".format(i, "，".join("{} {}".format(j.get("operation"), j.get("docstatus")) for j in jcs)))
            erp_error_log()
            break
        check(True, "完工入库：{}".format("、".join(ready)))
        pending -= set(ready)
        finished |= set(ready)
    check(not pending, "{} 的工单逐层做完（{} 张）".format(item, len(finished)))

    chars = [c for c in hub("GET", "/api/quality/characteristics", token=mgr) if c["item"] in made]
    for c in chars:
        rows = wait(lambda c=c: hub("GET", "/api/quality/measurements?characteristic={}&item={}".format(
            urllib.parse.quote(c["key"]), urllib.parse.quote(c["item"])), token=mgr), "测量值 " + c["key"], 60, 3) or []
        check(len(rows) >= 1, "测量 {} {}：{} 个值（{}）".format(c["item"], c.get("name") or c["key"], len(rows),
                                                          ", ".join("{:g}".format(r["value_mm"]) for r in rows[:3])))

    def erp_done():
        ws = [erp_doc("Work Order", n) for n in wos.values()]
        print("   ERPNext 工单：{}".format(", ".join("{} {}".format(w["production_item"], w.get("status")) for w in ws)))
        return all(w.get("status") == "Completed" or float(w.get("produced_qty") or 0) > 0 for w in ws)
    check(bool(wait(erp_done, "ERPNext 工单全部完成", 600 if REAL else 120, 15 if REAL else 4)), "ERPNext 工单全部完成、完工入库")
    se = [s for s in erp_docs("Stock Entry") if s.get("work_order") in wos.values() and s.get("docstatus") == 1]
    check(len(se) >= len(wos), "完工入库 {} 张".format(len(se)))
    inv = wait(lambda: next((d for d in erp_docs("Sales Invoice") if d.get("docstatus") == 1 and
                             so in json.dumps(erp_doc("Sales Invoice", d["name"]), ensure_ascii=False)), None),
               "订单做完开票", 300, 5)
    price = next((f.get("price") for f in cfg["fg"] if f["item_code"] == item), None)
    check(inv is not None, "开票 {}：${}（售价 {} × {}）".format((inv or {}).get("name"), (inv or {}).get("grand_total"), price, A.qty))
    if A.lab24 and item == "WQ-CR5":
        lab24(mgr, made)


def lab24(mgr, made):
    """实验 24：用同一个账号（就是下单的人）按六个任务答题，满分 60"""
    print("— 实验 24")
    st = hub("GET", "/api/lab24", token=mgr)
    exp_joints = {"WQJ-L": 2, "WQJ-M": 1, "WQJ-S": 3}
    hub("POST", "/api/lab24/l24_t1", {"work_orders": len(made), "joints": sum(exp_joints.values())}, mgr)
    js = wait(lambda: (lambda x: x["joints"] or None)(hub("GET", "/api/lab24", token=mgr)), "关节测量值", 60, 3) or []
    j = js[0]
    bad = [k for k, c in j["chars"].items() if not (c["lo"] <= c["value"] <= c["hi"])]
    hub("POST", "/api/lab24/l24_t3", {"serial": j["serial"], "verdict": "fail" if bad else "pass", "char": bad[0] if bad else ""}, mgr)
    st = hub("GET", "/api/lab24", token=mgr)
    mat = st["std"]["material"]
    lines = [dict(hub("GET", "/api/work_orders/{}/cost".format(urllib.parse.quote(wo)), token=mgr), item=it)
             for it, wo in st["order"]["work_orders"].items()]
    std = mat + sum(x["std_cost"] for x in lines)
    act = mat + sum(x["actual_cost"] for x in lines)
    worst = max(lines, key=lambda x: x["variance"])["item"]
    hub("POST", "/api/lab24/l24_t5", {"variance_pct": round((act - std) / std * 100, 1), "worst": worst}, mgr)
    hub("POST", "/api/lab24/l24_t6", {"choices": ["bom", "layers", "joint_test", "calib"]}, mgr)
    st = wait(lambda: (lambda x: x if x["score"] >= 60 else None)(hub("GET", "/api/lab24", token=mgr)), "实验 24 满分", 120, 5) \
        or hub("GET", "/api/lab24", token=mgr)
    check(st["score"] == 60, "实验 24 自动评分 {} / 60（{}）".format(
        st["score"], "、".join("{} {}".format(t["title"], t["score"]) for t in st["tasks"])))


def item_needs(item, buy, cfg):
    """--expect-buy 只核对用得到它的产品：按算料预览判断"""
    return any(buy == m["item_code"] for m in NEEDS.get(item, []))


NEEDS = {}


def main():
    h = wait(lambda: (lambda x: x if x.get("ok") else None)(hub("GET", "/api/health")), "枢纽起来", 120, 3)
    check(bool(h), "枢纽健康")
    mgr = login("manager")
    cfg = hub("GET", "/api/config", token=mgr)
    prods = [f["item_code"] for f in cfg["fg"]]
    print("工厂：{}；产品：{}".format((cfg.get("plant") or {}).get("company") or cfg.get("factory_name") or "", "、".join(prods)))
    for p in [x for x in A.expect_products.split(",") if x]:
        check(p in prods, "“订单与计划”能接 {}".format(p))
    items = A.item or prods[:1]
    for it in items:
        NEEDS[it] = hub("POST", "/api/plan/order", {"customer": cfg["customers"][0], "item": it, "qty": A.qty,
                                                    "delivery_date": delivery_date()}, mgr)["material_requests"]
    for b in A.expect_buy:
        check(any(item_needs(it, b, cfg) for it in items), "算料：{} 要请购（{}）".format(
            b, "、".join(it for it in items if item_needs(it, b, cfg)) or "没有产品用到"))
    for it in items:
        one(it, mgr)
    if not REAL:
        errs = call("GET", A.erp + "/api/mock/errors")["errors"]
        check(not errs, "ERPNext 字段校验无错误" + ("：" + "；".join(errs[:5]) if errs else ""))
    print("\n{}：{} 项不通过".format("通过" if not FAILS else "不通过", len(FAILS)))
    for f in FAILS:
        print("  ✗ " + f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
