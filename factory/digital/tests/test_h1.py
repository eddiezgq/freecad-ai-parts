# -*- coding: utf-8 -*-
"""第 71 轮：机器人厂的第三种整机——轮式人形 WQ-H1。物料清单展开到 16 个关节模组、一台 WQ-AGV300（整机里套整机）；
仿真车间里一台 WQ-H1 走完人形总装 → 双臂与手眼标定 → 人形联调 → 包装，出三项检验数据；现场售后先只管 WQ-CR5。"""
import json
import os
import subprocess
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")

RUN = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from factory import data as F
from sim.engine import Engine, routing_for, OP_UNITS
from hub import rfield as RF

def explode(item, q=1.0, out=None):
    out = {{}} if out is None else out
    for c, n in (F.BOMS.get(item) or ("", []))[1]:
        out[c] = out.get(c, 0) + q * n
        explode(c, q * n, out)
    return out

ex = explode("WQ-H1")
o = {{"joints": {{k: ex.get(k, 0) for k in ("WQJ-L", "WQJ-M", "WQJ-S")}}, "hd": {{k: ex.get(k, 0) for k in ("HD-CSF-32-100", "HD-CSF-25-100", "HD-CSF-17-100")}},
     "agv": ex.get("WQ-AGV300"), "wqr": ex.get("WQR-105"), "price": F.PRODUCTS.get("WQ-H1"), "robot_items": RF.robot_items()}}
msgs = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: msgs.append(wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
             mode="teach", auto_start=True, seed=7, status_every_s=1e9)
ops = routing_for("WQ-H1")
o["ops"] = [op for op, _ in ops]
for op, _ in ops:
    ok, why = eng.command(OP_UNITS[op][0], {{"command": "dispatch", "work_order": "WO-H1", "operation": op, "qty": 2, "item": "WQ-H1", "routing": ops}}, "WO-H1")
    assert ok, why
while eng.q and clock.t < 30 * 86400:
    clock.t = max(clock.t, eng.next_event_time())
    eng.run_due()
ms = [m["data"] for m in msgs if m["type"] == "quality.measurement" and m["data"]["item"] == "WQ-H1"]
o["chars"] = sorted({{(d["characteristic"], d["operation"].split(" ")[0]) for d in ms}})
o["n"] = len(ms)
o["done"] = sum(1 for m in msgs if m["type"] == "machine.event" and m["data"]["event"] == "cycle_end" and m["data"].get("work_order") == "WO-H1"
                and m["data"]["operation"].startswith("包装"))
print(json.dumps(o, ensure_ascii=False))
"""


def test_h1_bom_and_shop():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["joints"] == {"WQJ-L": 2, "WQJ-M": 4, "WQJ-S": 10} and sum(o["joints"].values()) == 16
    assert o["hd"] == {"HD-CSF-32-100": 2, "HD-CSF-25-100": 4, "HD-CSF-17-100": 10}
    assert o["agv"] == 1 and o["wqr"] == 2                     # 整机里套整机：底盘的两个驱动单元各一台 WQR-105
    assert o["price"] == 68000 and o["robot_items"] == ["WQ-CR5"]
    assert o["ops"][:3] == ["人形总装 Humanoid assembly", "双臂与手眼标定 Dual-arm & hand-eye calibration", "人形联调 Humanoid integration test"]
    assert o["chars"] == [["h1_cycle", "人形联调"], ["h1_dual", "双臂与手眼标定"], ["h1_handeye", "双臂与手眼标定"]]
    assert o["n"] == 6 and o["done"] == 2
