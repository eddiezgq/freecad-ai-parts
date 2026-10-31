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
P.add_argument("--item", action="append", default=[], help="要接单的产品（可写多次，“产品:数量”可单独定数量）；不写 = 清单里第一种成品")
P.add_argument("--qty", type=int, default=1)
P.add_argument("--expect-buy", action="append", default=[], help="算料的请购里必须有的物料")
P.add_argument("--expect-products", default="", help="“订单与计划”里必须有的产品，逗号分隔")
P.add_argument("--speed", type=float, default=300)
P.add_argument("--timeout", type=float, default=900)
P.add_argument("--teacher-password", default="", help="本地版（WQ_EDITION=local）当厂长要的老师密码")
P.add_argument("--lab24", action="store_true", help="接 WQ-CR5 后按实验 24 的六个任务答题，核对拿满 60 分（第 47 轮）")
P.add_argument("--lab26", action="store_true", help="WQ-CR5 做到整机标定后，看标定页、按实验 26 的六个任务答题，核对拿满 60 分（第 55 轮）")
P.add_argument("--lab28", action="store_true", help="WQ-CR5 做到整机标定后，看负载跑合页、按实验 28 的六个任务答题，核对拿满 60 分（第 58 轮）")
P.add_argument("--reliability", type=float, default=None, help="开始前把设备可靠性系数设成这个数（0 = 演练时设备不随机坏，第 59 轮）")
P.add_argument("--domains", action="store_true", help="设备维护、能源、经营财务三个页面按本厂设备出数（设备台账进 ERPNext），第 59 轮")
P.add_argument("--lab27", action="store_true", help="工业园那一段走完后，按实验 27 的六个任务答题（AGV 订单要 2 台：--item WQ-AGV300:2），核对 60 分（第 57 轮）")
P.add_argument("--park-hub", default="", help="工业园兄弟厂（问渠减速器厂）的枢纽：核对 WQR-105 的采购单送过去、那边接单生产发货、"
                                              "这边到货检验入库（第 51 轮）")
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


QTYS = {}


def qty_of(item):
    return QTYS.get(item, A.qty)


def one(item, mgr):
    cfg = hub("GET", "/api/config", token=mgr)
    customer = cfg["customers"][0]
    print("— 接单：{} × {}（客户 {}）".format(item, qty_of(item), customer.split(" ")[0]))
    pv = hub("POST", "/api/plan/order", {"customer": customer, "item": item, "qty": qty_of(item), "delivery_date": delivery_date()}, mgr)
    made = [w["production_item"] for w in pv["work_orders"]]
    buys = {m["item_code"] for m in pv["material_requests"]}
    check(item in made, "算料：{} 的工单 {} 张（{}）".format(item, len(made), "、".join(made)))
    p = hub("POST", "/api/proposals", {"action": "create_order_and_plan", "customer": customer, "item": item, "qty": qty_of(item),
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
    check(inv is not None, "开票 {}：${}（售价 {} × {}）".format((inv or {}).get("name"), (inv or {}).get("grand_total"), price, qty_of(item)))
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


def lab26(mgr):
    """实验 26：整机标定页（铺满 / 集中、30 / 8 个位姿）+ 六个任务，满分 60；标定前后误差的量级"""
    import math
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
    from sim import calib as C
    print("— 实验 26（整机标定）")
    lst = wait(lambda: (lambda x: x if x["robots"] else None)(hub("GET", "/api/calib", token=mgr)), "整机标定出数", 300, 5)
    if not check(bool(lst), "整机标定页有机器人"):
        return
    r0 = lst["robots"][0]
    check(r0["before_mm"] and 0.3 < r0["before_mm"] < 3 and r0["after_mm"] < 0.5 and r0["pass"],
          "{} 标定前 {} mm、标定后 {} mm（条件数 {}），合格".format(r0["serial"], r0["before_mm"], r0["after_mm"], r0["cond"]))
    q = urllib.parse.quote(r0["serial"])
    full = hub("GET", "/api/calib/{}?n=30&spread=full".format(q), token=mgr)
    clus = hub("GET", "/api/calib/{}?n=30&spread=cluster".format(q), token=mgr)
    few = hub("GET", "/api/calib/{}?n=8&spread=full".format(q), token=mgr)
    check(clus["cond"] > full["cond"] and clus["after_mean_mm"] > full["after_mean_mm"],
          "位姿集中：条件数 {} → {}，标定后 {} → {} mm".format(full["cond"], clus["cond"], full["after_mean_mm"], clus["after_mean_mm"]))
    st = hub("GET", "/api/lab26", token=mgr)
    hub("POST", "/api/lab26/pick", {"serial": r0["serial"]}, mgr)
    st = hub("GET", "/api/lab26", token=mgr)
    x, y, z = (C.fk([math.radians(v) for v in st["fk_q_deg"]]) * 1000).tolist()
    hub("POST", "/api/lab26/l26_t1", {"x": x, "y": y, "z": z}, mgr)
    hub("POST", "/api/lab26/l26_t2", {"larger": "cluster" if clus["cond"] > full["cond"] else "full"}, mgr)
    top = [p["joint"] for p in sorted(full["identified"], key=lambda p: -abs(p["dtheta_deg"]))[:2]]
    hub("POST", "/api/lab26/l26_t3", {"joints": top}, mgr)
    hub("POST", "/api/lab26/l26_t4", {"after_mm": full["after_mean_mm"], "pass": full["pass"]}, mgr)
    hub("POST", "/api/lab26/l26_t5", {"choice": "worse_ill"}, mgr)
    hub("POST", "/api/lab26/l26_t6", {"choice": "bench"}, mgr)
    st = hub("GET", "/api/lab26", token=mgr)
    check(st["score"] == 60, "实验 26 自动评分 {} / 60（{}）；8 个位姿：标定后 {} mm".format(
        st["score"], "、".join("{} {}".format(t["title"], t["score"]) for t in st["tasks"]), few["after_mean_mm"]))


def lab28(mgr):
    """实验 28：负载跑合页（实测与仿真、辨识、力矩裕量）+ 六个任务，满分 60；辨识出的 f_c 与关节测试台的值一致"""
    print("— 实验 28（负载跑合）")
    lst = wait(lambda: (lambda x: x if x["robots"] else None)(hub("GET", "/api/runin", token=mgr)), "负载跑合有机器人", 300, 5)
    if not check(bool(lst), "负载跑合页有机器人"):
        return
    r0 = lst["robots"][0]
    check(r0["bench"], "{} 带着关节测试台的空载摩擦力矩".format(r0["serial"]))
    c = hub("GET", "/api/runin/{}".format(urllib.parse.quote(r0["serial"])), token=mgr)
    J = {j["joint"]: j for j in c["joints"]}
    worst = max(abs(j["fc_hat"] - j["fc_bench"]) for j in c["joints"])
    check(worst < 0.1 and all(j["rms_diff_updated"] < 2 * j["noise_sigma"] for j in c["joints"]),
          "辨识 f_c 与测试台最多差 {:.3f} N·m；写回模型后均方根差 ≈ 噪声（{}）".format(worst, "、".join(str(j["rms_diff_updated"]) for j in c["joints"])))
    hub("POST", "/api/lab28/pick", {"serial": r0["serial"]}, mgr)
    hub("POST", "/api/lab28/l28_t1", {"peak": J["J2"]["peak_meas"]}, mgr)
    hub("POST", "/api/lab28/l28_t2", {"joint": max(c["joints"], key=lambda j: j["rms_diff"])["joint"]}, mgr)
    hub("POST", "/api/lab28/l28_t3", {"fc": J["J1"]["fc_hat"], "fv": J["J1"]["fv_hat"]}, mgr)
    hub("POST", "/api/lab28/l28_t4", {"choice": "viscous"}, mgr)
    hub("POST", "/api/lab28/l28_t5", {"rms": J["J2"]["rms_meas"], "pass": c["pass"]}, mgr)
    hub("POST", "/api/lab28/l28_t6", {"choice": "noise"}, mgr)
    st = hub("GET", "/api/lab28", token=mgr)
    check(st["score"] == 60, "实验 28 自动评分 {} / 60（{}）".format(st["score"], "、".join("{} {}".format(t["title"], t["score"]) for t in st["tasks"])))


def domains(mgr):
    """第 59 轮：设备维护、能源、经营财务在本厂打开——台账是本厂的设备并进了 ERPNext、能源有读数、财务出应收和指标"""
    print("— 设备维护、能源、经营财务（第 59 轮）")
    cfg = hub("GET", "/api/config", token=mgr)
    hidden = (cfg.get("plant") or {}).get("hidden") or []
    check(not any(p in hidden for p in ("/maint", "/energy", "/finance")), "三个页面入口没有隐藏（隐藏的：{}）".format(hidden))
    units = set((cfg.get("plant") or {}).get("units") or [])
    a = wait(lambda: (lambda x: x if x["assets"] and all(r["asset"] for r in x["assets"]) else None)(hub("GET", "/api/maint/assets", token=mgr)),
             "设备台账写进 ERPNext（资产、保养计划）", 600, 10) or hub("GET", "/api/maint/assets", token=mgr)
    names = [r["unit"] for r in a["assets"]]
    check(names and all(r.get("asset") for r in a["assets"]), "设备台账 {} 台：{}".format(len(names), "、".join(n.upper() for n in names[:6])))
    check(not units or set(names) <= units, "台账里都是本厂的设备")
    ov = wait(lambda: (lambda x: x if x.get("kwh") else None)(hub("GET", "/api/energy/overview", token=mgr)), "能源有读数", 600, 10) \
        or hub("GET", "/api/energy/overview", token=mgr)
    check(bool(ov.get("kwh")) and {u["unit"] for u in ov["units"]} == set(names),
          "能源：{} kWh，{} 台设备分表".format(ov.get("kwh"), len(ov.get("units") or [])))
    k = hub("GET", "/api/finance/kpis", token=mgr)
    check(isinstance(k, dict) and k, "经营财务指标：{}".format("、".join(sorted(k)[:5])))


def lab27(mgr):
    """实验 27：用接 AGV 的同一个账号答题（AGV 那一单要 2 台），WQR-105 那一批到货检验入库后满分 60"""
    import math
    print("— 实验 27（两厂之间的一张订单）")
    st = hub("GET", "/api/lab27", token=mgr)
    if not check(bool(st.get("order")), "实验 27 找到你的 AGV 订单：{}".format(st.get("order"))):
        return
    hub("POST", "/api/lab27/l27_t1", {"qty": st["order"]["wqr_request"]}, mgr)
    st = wait(lambda: (lambda x: x if x["lot"] and (x["lot"].get("park") or {}).get("order") else None)(hub("GET", "/api/lab27", token=mgr)),
              "WQR-105 的采购单送到减速器厂", 600, 5) or st
    if st.get("lot") and (st["lot"].get("park") or {}).get("order"):
        hub("POST", "/api/lab27/l27_t2", {"order": str(st["lot"]["park"]["order"])}, mgr)
    st = wait(lambda: (lambda x: x if x["lot"] and x["lot"]["status"] == "accepted" else None)(hub("GET", "/api/lab27", token=mgr)),
              "WQR-105 到货检验入库", max(A.timeout, 1200), 5) or hub("GET", "/api/lab27", token=mgr)
    if st.get("lot_days") is not None:
        hub("POST", "/api/lab27/l27_t4", {"days": st["lot_days"], "on_time": st["lot_days"] <= 10}, mgr)
    dm = st["demand"]
    ss = dm["z"] * dm["sigma_d"] * math.sqrt(dm["lead_days"])
    hub("POST", "/api/lab27/l27_t5", {"ss": round(ss, 2), "rop": round(dm["d"] * dm["lead_days"] + ss, 2)}, mgr)
    hub("POST", "/api/lab27/l27_t6", {"choice": "bullwhip"}, mgr)
    st = hub("GET", "/api/lab27", token=mgr)
    check(st["score"] == 60, "实验 27 自动评分 {} / 60（{}）".format(st["score"], "、".join("{} {}".format(t["title"], t["score"]) for t in st["tasks"])))


def item_needs(item, buy, cfg):
    """--expect-buy 只核对用得到它的产品：按算料预览判断"""
    return any(buy == m["item_code"] for m in NEEDS.get(item, []))


NEEDS = {}


def park(mgr):
    """第 51 轮：AGV 订单的 WQR-105 请购 → 采购单 → 送到减速器厂成为销售订单 → 那边自动接单、下达、做完发货 → 这边到货、来料检验入库"""
    print("工业园：机器人厂向问渠减速器厂采购 WQR-105")
    lot = wait(lambda: next((x for x in hub("GET", "/api/supply/lots", token=mgr)["lots"]
                             if x["item"] == "WQR-105" and (x.get("park") or {}).get("state") in ("sent", "shipped", "fallback")), None),
               "WQR-105 的采购单送到减速器厂", 600, 5)
    if not check(bool(lot), "WQR-105 请购转成采购单（采购员模拟器）"):
        try:                                  # 诊断：批次、还没转的请购、供应链相关的提议
            lt = hub("GET", "/api/supply/lots", token=mgr)
            print("    诊断 批次：{}".format([(x["item"], x["status"], x.get("park")) for x in lt["lots"][:12]]))
            print("    诊断 供应链态势：{}".format(lt["kpis"]))
            print("    诊断 还没转的请购：{}".format(json.dumps(hub("GET", "/api/supply/requests", token=mgr)["requests"][:6], ensure_ascii=False)[:800]))
            ps = [p for p in hub("GET", "/api/proposals", token=mgr) if p.get("action") in ("purchase_order", "supply_setup", "create_order_and_plan")]
            for p in ps[:8]:
                print("    诊断 提议 {} {} {}：{}".format(p.get("proposal_id"), p.get("action"), p.get("status"),
                                                   json.dumps(p.get("result"), ensure_ascii=False)[:300]))
            mrs = [(m["name"], m.get("status"), m.get("docstatus")) for m in erp_docs("Material Request")]
            print("    诊断 ERPNext 请购单：{}".format(mrs[:10]))
        except Exception as e:  # noqa: BLE001
            print("    诊断失败：{}".format(e))
        return
    check(lot["park"]["state"] != "fallback", "采购单送到减速器厂：{}".format(lot.get("note") or ""))
    def gb(m, p, b=None, token=None):
        return call(m, A.park_hub + p, b, token)
    gtok = gb("POST", "/api/login", dict({"name": "工业园演练", "role": "manager", "mode": "teach"},
                                         **({"teacher_password": A.teacher_password} if A.teacher_password else {})))["token"]
    gb("POST", "/api/mes/cmd", {"unit": "sim", "command": "set_speed", "speed": A.speed}, token=gtok)
    try:                                      # 前面的演练（两周情景第 6 幕的保养）可能给磨床留了挂牌上锁：验收、解锁，免得这张单做不完
        for p in gb("GET", "/api/ehs/permits", token=gtok)["permits"]:
            if p.get("kind") == "loto" and p.get("status") in ("active", "planned"):
                gb("POST", "/api/ehs/permits/{}/close".format(p["id"]), {}, token=gtok)
                print("  （减速器厂：关闭挂牌上锁许可 {}，{} 解锁）".format(p.get("key"), p.get("unit")))
    except RuntimeError as e:
        print("  （减速器厂：没能检查挂牌上锁：{}）".format(str(e)[:120]))
    o = wait(lambda: next((x for x in gb("GET", "/api/park", token=gtok)["orders"] if x["po"] == lot["po"] and x["status"] in ("released", "shipped")),
                          None), "减速器厂接单、订单和工单写进 ERPNext", 600, 5)
    if not check(bool(o), "减速器厂自动接单：{}".format(o and "订单 {}，工单 {}".format(o["so"], "、".join(o["work_orders"])))):
        print("    工业园订单：{}".format(json.dumps(gb("GET", "/api/park", token=gtok)["orders"][:3], ensure_ascii=False)[:600]))
        return
    wos = o["work_orders"]
    o = wait(lambda: next((x for x in gb("GET", "/api/park", token=gtok)["orders"] if x["po"] == lot["po"] and x["status"] == "shipped"), None),
             "减速器厂做完发货", max(A.timeout, 1200), 5)
    if not check(bool(o), "减速器厂做完发货：批 {}".format(o and o["shipment"]["lot"])):
        print("    工业园订单：{}".format(json.dumps(gb("GET", "/api/park", token=gtok)["orders"][:3], ensure_ascii=False)[:600]))
        try:                                  # 诊断：减速器厂车间里这张工单走到哪一步、设备状态
            for w in wos:
                evs = gb("GET", "/api/history?type=machine.event&corr={}&limit=500".format(urllib.parse.quote(w)), token=gtok)
                done = [e["data"]["operation"] for e in evs if e["data"].get("event") == "op_complete"]
                ends = sum(1 for e in evs if e["data"].get("event") == "cycle_end")
                print("    诊断 {}：完工工序 {}；加工完成 {} 件次".format(w, done, ends))
            ov = gb("GET", "/api/overview", token=gtok)
            print("    诊断 减速器厂设备：{}".format([(m.get("unit"), m.get("state"), m.get("down_until_s"), m.get("queue") or m.get("inbox"))
                                                 for m in ov.get("machines", [])]))
        except Exception as e:  # noqa: BLE001
            print("    诊断失败：{}".format(e))
        return
    got = wait(lambda: next((x for x in hub("GET", "/api/supply/lots", token=mgr)["lots"] if x["id"] == lot["id"] and x["status"] == "accepted"), None),
               "机器人厂到货、来料检验入库", 900, 5)
    check(bool(got) and got["lot"] == o["shipment"]["lot"], "机器人厂收货：批 {}，{}".format(got and got["lot"], got and got["status_label"]))
    if got and REAL:
        prs = [p for p in erp_docs("Purchase Receipt") if p.get("docstatus") == 1 and (p.get("wq_lot") == got["lot"] or got["lot"] in (p.get("remarks") or ""))]
        check(bool(prs), "机器人厂 ERPNext 收货单（批号 {}）：{}".format(got["lot"], "、".join(p["name"] for p in prs)))


def main():
    h = wait(lambda: (lambda x: x if x.get("ok") else None)(hub("GET", "/api/health")), "枢纽起来", 120, 3)
    check(bool(h), "枢纽健康")
    mgr = login("manager")
    if A.reliability is not None:
        try:
            hub("POST", "/api/maint/reliability", {"factor": A.reliability}, mgr)
            print("设备可靠性系数设为 {:g}".format(A.reliability))
        except Exception as e:  # noqa: BLE001
            print("（本厂没有设备维护，不设可靠性：{}）".format(e))
    cfg = hub("GET", "/api/config", token=mgr)
    prods = [f["item_code"] for f in cfg["fg"]]
    print("工厂：{}；产品：{}".format((cfg.get("plant") or {}).get("company") or cfg.get("factory_name") or "", "、".join(prods)))
    for p in [x for x in A.expect_products.split(",") if x]:
        check(p in prods, "“订单与计划”能接 {}".format(p))
    items = []
    for x in A.item or prods[:1]:
        it, _, q = x.partition(":")
        items.append(it)
        if q:
            QTYS[it] = int(q)
    for it in items:
        NEEDS[it] = hub("POST", "/api/plan/order", {"customer": cfg["customers"][0], "item": it, "qty": qty_of(it),
                                                    "delivery_date": delivery_date()}, mgr)["material_requests"]
    for b in A.expect_buy:
        check(any(item_needs(it, b, cfg) for it in items), "算料：{} 要请购（{}）".format(
            b, "、".join(it for it in items if item_needs(it, b, cfg)) or "没有产品用到"))
    for it in items:
        one(it, mgr)
    if A.lab26:
        lab26(mgr)
    if A.lab28:
        lab28(mgr)
    if A.park_hub:
        park(mgr)
    if A.lab27:
        lab27(mgr)
    if A.domains:
        domains(mgr)
    if not REAL:
        errs = call("GET", A.erp + "/api/mock/errors")["errors"]
        check(not errs, "ERPNext 字段校验无错误" + ("：" + "；".join(errs[:5]) if errs else ""))
    print("\n{}：{} 项不通过".format("通过" if not FAILS else "不通过", len(FAILS)))
    for f in FAILS:
        print("  ✗ " + f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
