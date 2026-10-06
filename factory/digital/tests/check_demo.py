# -*- coding: utf-8 -*-
"""服务器演练用（第 9 轮）：企业版演示工厂闭环（真 ERPNext 的 demo 站点）。

生产模式提交 STEP → 另一人批准 → demo 站点物料“设计版本”加一；配置器报价 → 订单提议 → 确认 → demo 站点有销售订单（单价按报价）；
教学工厂的 ERPNext 不受影响。
用法：python tests/check_demo.py --hub http://localhost:8101 --erp http://localhost:8092 --key K --secret S \
        --teach-erp http://localhost:8090 --teach-key K2 --teach-secret S2
"""
import argparse
import os
import sys
import tempfile
import time

import requests

P = argparse.ArgumentParser()
P.add_argument("--hub", default="http://localhost:8101")
P.add_argument("--erp", default="http://localhost:8092")
P.add_argument("--key", required=True)
P.add_argument("--secret", required=True)
P.add_argument("--teach-erp", default="http://localhost:8090")
P.add_argument("--teach-key", required=True)
P.add_argument("--teach-secret", required=True)
A = P.parse_args()
ok = True


def check(cond, what):
    global ok
    print(("  ✓ " if cond else "  ✗ ") + what)
    ok &= bool(cond)
    return cond


def login(name, role):
    r = requests.post(A.hub + "/api/login", json={"name": name, "role": role, "mode": "prod"}, timeout=30)
    r.raise_for_status()
    return {"x-wq-token": r.json()["token"]}


def erp_get(base, key, secret, path, **params):
    r = requests.get(base + path, params=params, headers={"Authorization": "token {}:{}".format(key, secret)}, timeout=30)
    return r.json().get("data") if r.status_code == 200 else None


def wait(fn, what, timeout=90):
    t = time.time()
    while time.time() - t < timeout:
        v = fn()
        if v:
            return v
        time.sleep(2)
    check(False, "等待超时：" + what)
    return None


print("1. 演示工厂默认生产模式")
cfg = requests.get(A.hub + "/api/config", timeout=30).json()
check(cfg["default_mode"] == "prod", "default_mode = {}".format(cfg["default_mode"]))

print("2. 提交 → 批准 → demo 站点物料版本加一")
import build123d as bd  # noqa: E402
p = os.path.join(tempfile.mkdtemp(), "cap.step")
bd.export_step(bd.Box(80, 60, 14) - bd.Cylinder(16, 20), p)
eng, apr = login("演示工程师", "engineer"), login("演示审批人", "approver")
s = requests.post(A.hub + "/api/plm/submit", headers=eng, data={"item": "CAP-52-T", "note": "演示：加厚"},
                  files={"step": open(p, "rb")}, timeout=120).json()
check(s.get("status") == "pending", "提交进待审（{}）".format(s.get("status") or s))
d = requests.post(A.hub + "/api/plm/submissions/{}/decision".format(s.get("id")), headers=apr,
                  json={"decision": "approve", "note": "可以"}, timeout=60).json()
check(d.get("status") == "approved", "批准生效 rev {}".format(d.get("revision")))
item = wait(lambda: (lambda it: it if it and it.get("wq_revision") == d.get("revision") else None)(
    erp_get(A.erp, A.key, A.secret, "/api/resource/Item/CAP-52-T")), "demo 站点物料版本")
check(item, "demo 站点 CAP-52-T 设计版本 = {}".format(item and item.get("wq_revision")))
teach = erp_get(A.teach_erp, A.teach_key, A.teach_secret, "/api/resource/Item/CAP-52-T") or {}
check(teach.get("wq_revision") in (None, 0, 1), "教学工厂 ERPNext 不受影响（{}）".format(teach.get("wq_revision")))

print("3. 配置器 → 订单提议 → 确认 → demo 站点销售订单")
sales = login("演示销售", "sales")
vals = {"ratio": "21-75-18-72", "power_kw": 3}
q = requests.post(A.hub + "/api/configurator/WQR-105/evaluate", headers=sales, json={"values": vals, "qty": 2}, timeout=30).json()
check(q["ok"], "校核通过，单价 {}".format(q["quote"]["unit_price"]))
cust = cfg["customers"][0]
due = time.strftime("%Y-%m-%d", time.localtime(time.time() + 30 * 86400))
o = requests.post(A.hub + "/api/configurator/WQR-105/order", headers=sales,
                  json={"values": vals, "qty": 2, "customer": cust, "delivery_date": due}, timeout=60).json()
check(o.get("proposal_id"), "生成提议 {}".format(o.get("proposal_id")))
mgr = login("演示厂长", "manager")
c = requests.post(A.hub + "/api/proposals/{}/confirm".format(o.get("proposal_id")), headers=mgr, timeout=60).json()
check(c.get("status") == "confirmed", "确认提议（{}）".format(c.get("status")))


def so():
    rows = erp_get(A.erp, A.key, A.secret, "/api/resource/Sales Order", fields='["name","grand_total","customer"]',
                   limit_page_length=50) or []
    for r in rows:
        doc = erp_get(A.erp, A.key, A.secret, "/api/resource/Sales Order/" + r["name"])
        if doc and any(abs(float(i.get("rate", 0)) - q["quote"]["unit_price"]) < 0.01 for i in doc.get("items", [])):
            return doc
    return None


doc = wait(so, "demo 站点销售订单", 180)
check(doc, "demo 站点销售订单 {}，单价 {}".format(doc and doc["name"], q["quote"]["unit_price"]))

print("演示工厂演练{}".format("全部通过。" if ok else "有失败。"))
sys.exit(0 if ok else 1)
