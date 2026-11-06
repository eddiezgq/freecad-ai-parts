# -*- coding: utf-8 -*-
"""教学模式下首页只在演示工厂（减速器厂）取实验 7 的任务；机器人厂开教学模式时首页不能去调减速器厂的任务（2026-11-05 Eddie 报：首页报错）。"""
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
from hub import app as A
class Boom:
    def check(self, user): raise RuntimeError("调用了实验 7")
    def status(self, user): raise RuntimeError("调用了实验 7")
class Lab7:
    def check(self, user): return self.status(user)
    def status(self, user): return {{"tasks": [{{"done": False, "title": "读懂首页看板", "desc": "d", "role": "manager", "score": 0}}]}}
A.H.teach = Lab7() if A.DEMO_PLANT else Boom()
u = {{"mode": "teach", "role": "manager", "name": "s1"}}
ov = {{"proposals": [], "quality": {{"ncr": []}}, "alerts": []}}
print(json.dumps({{"demo": A.DEMO_PLANT, "todos": A.todos_for(u, ov)}}, ensure_ascii=False))
"""


def _run(plant):
    env = dict(os.environ)
    env.pop("WQ_PLANT_FILE", None)
    if plant:
        env["WQ_PLANT_FILE"] = plant
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_robot_plant_teach_home_skips_lab7():
    o = _run(ROBOT)
    assert o["demo"] is False
    assert o["todos"] == []


def test_demo_plant_teach_home_keeps_lab7():
    o = _run(None)
    assert o["demo"] is True
    assert o["todos"][0]["src"] == "实验 7 · 读懂首页看板"
