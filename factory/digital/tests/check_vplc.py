# -*- coding: utf-8 -*-
"""服务器演练（第 18 轮第 8 步《PLC 原理及实践》）：在真镜像里，经枢纽把第 15 章参考程序（程序 15.5.1）下载到
虚拟 PLC，控制轴承压装工位跑一个缩短的班次（半小时），再让分拣线参考程序跑一个；核对班次记录里的产量与报警，
以及总线上的消息（来源 plc/<设备>）进了历史库；两个程序都通过 OpenPLC 兼容性检查。
用法：python tests/check_vplc.py --hub http://localhost:8100"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--hub", default="http://localhost:8100")
ap.add_argument("--hours", type=float, default=0.5)
ap.add_argument("--timeout", type=float, default=900)
A = ap.parse_args()


def call(method, path, body=None, token=None, form=None):
    data, ct = None, "application/json"
    if form is not None:
        data, ct = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(A.hub + path, method=method, data=data,
                                 headers={"Content-Type": ct, **({"x-wq-token": token} if token else {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


tok = call("POST", "/api/login", {"name": "PLC 检查", "role": "engineer", "mode": "teach"})["token"]
ov = call("GET", "/api/plc", token=tok)
assert {u["unit"] for u in ov["units"]} == {"press-01", "sort-01"}, ov
runs = {}
for unit in ("press-01", "sort-01"):
    runs[unit] = call("POST", "/api/plc/runs", token=tok, form={"unit": unit, "example": "1", "hours": str(A.hours)})["id"]
t0 = time.time()
done = {}
while len(done) < len(runs) and time.time() - t0 < A.timeout:
    time.sleep(5)
    for unit, rid in runs.items():
        r = call("GET", "/api/plc/runs/" + rid, token=tok)
        if r["status"] in ("done", "failed", "cancelled"):
            done[unit] = r
        else:
            print("  {} {} {} 进度 {:.0%} 产量 {}".format(unit, rid, r["status"], (r["live"] or {}).get("progress") or 0, (r["live"] or {}).get("n") or 0))
for unit in runs:
    r = done.get(unit)
    assert r, "{} 的班次 {} 秒内没有跑完".format(unit, A.timeout)
    assert r["status"] == "done", (unit, r["status"], r.get("error"))
    s = r["summary"]
    print("{}：产量 {}，合格 {}，不合格 {}，平均节拍 {} s，报警 {}，停机 {} 分钟".format(unit, s["parts"], s["good"], s["nok"], s["cycle_mean_s"],
                                                                     s["alarms"], s["downtime_min"]))
    assert s["parts"] > (50 if unit == "press-01" else 200) * A.hours / 0.5 and s["hazards"] == 0 and not s["plc_error"]
    assert r["live"]["n"] == s["parts"], "回放的最后一件与汇总不一致"
# OpenPLC 兼容性检查（同一程序在 OpenPLC 运行时上编译，并按真实时间控制设备 90 秒）
t0 = time.time()
compat = {}
while len(compat) < len(runs) and time.time() - t0 < A.timeout:
    for unit, rid in runs.items():
        r = call("GET", "/api/plc/runs/" + rid, token=tok)
        if r.get("compat"):
            compat[unit] = r["compat"]
    if len(compat) < len(runs):
        time.sleep(10)
for unit in runs:
    c = compat.get(unit)
    assert c, "{} 的 OpenPLC 兼容性检查 {} 秒内没有结果".format(unit, A.timeout)
    print("{} OpenPLC：{} {}，90 秒产量 {}".format(unit, c["stage"], "通过" if c["ok"] else "不通过", (c.get("summary") or {}).get("parts")))
    assert c["ok"] and c["summary"]["parts"] >= (3 if unit == "press-01" else 10) and c["summary"]["hazards"] == 0, c.get("log")
hist = call("GET", "/api/history?type=plc.shift&hours=2&limit=20", token=tok)
items = hist if isinstance(hist, list) else hist.get("messages") or hist.get("items") or []
assert any(m.get("source") == "plc/press-01" for m in items), "历史库里没有虚拟 PLC 的班次消息"
print("虚拟 PLC 演练通过")
