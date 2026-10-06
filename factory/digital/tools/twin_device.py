# -*- coding: utf-8 -*-
"""模拟一台“真设备”（第 15 轮验收用）：像现场采集器那样，每天把运行摘要用 HTTPS 发给数字工厂。

用法：python tools/twin_device.py --hub https://factory.<域名> --key <WQ_TWIN_DEVICE_KEY> --serial REAL-0001 --days 3
真采集器（ESP32、PLC 网关……）照这个格式 POST 到 /api/twin/telemetry 即可：
  serial、day（YYYY-MM-DD）、period_h、run_h、starts、n_in_rpm、torque_mean_nm、torque_max_nm、t_amb_c、oil_t_c、oil_t_max_c、vib_mm_s、
  rainflow（输出转矩雨流计数 [[幅值, 平均值, 次数], ...]）、load_hist（[[转矩, 运行小时], ...]）
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.request

sys.path[:0] = [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
from twin import field as F  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--hub", default="http://localhost:8100")
ap.add_argument("--key", required=True)
ap.add_argument("--serial", default="REAL-0001")
ap.add_argument("--site", default="port", choices=list(F.SITES))
ap.add_argument("--days", type=int, default=3)
ap.add_argument("--mode", default="teach")
A = ap.parse_args()

start = dt.date.today() - dt.timedelta(days=A.days)
for i in range(A.days):
    d = F.day_summary(A.serial, A.site, start + dt.timedelta(days=i))
    d.pop("customer", None)
    d.update(site="real", mode=A.mode)
    req = urllib.request.Request(A.hub + "/api/twin/telemetry", data=json.dumps(d).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + A.key})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(d["day"], json.loads(r.read()))
