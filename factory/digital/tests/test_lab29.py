# -*- coding: utf-8 -*-
"""第 68 轮：实验 29“一台机器人的售后追溯”——种场景（3 台同批、1 台超限）、按正确答案 60 分、答错拿不到、派错工单不算。
机器人厂在子进程里按清单跑；需要 PostgreSQL。"""
import json
import os
import subprocess
import sys

import pytest

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")

RUN = r"""
import json, sys, types
sys.path[:0] = [{dig!r}, {fac!r}]
from hub.db import DB
from hub import lab29 as L, rfield as RF
db = DB({db!r}); db.init()
H = types.SimpleNamespace(db=db, ai=None)
out = {{}}
st = L.status(db, "stu")
cs = L.case("stu")
fl = {{x["serial"]: x for x in RF.fleet(db, "teach")}}
out["health"] = [fl[s]["health"] for s in cs["serials"]]
out["case2"] = L.case("stu2")["lot"] != cs["lot"]
d = RF.detail(db, "teach", cs["serials"][0])
j2 = next(j for j in d["as_built"]["joints"] if j["joint"] == "J2")
out["same"] = next(x["others"] for x in d["same_lot"] if x["joint"] == "J2")
wrong = {{"t1": L.answer(db, "stu2", "l29_t1", {{"serial": "X", "joint": "J1"}})["score"],
          "t3": L.answer(db, "stu2", "l29_t3", {{"choice": "age"}})["score"],
          "t4": L.answer(db, "stu2", "l29_t4", {{"serials": L.case("stu2")["serials"][1]}})["score"]}}
out["wrong"] = wrong
sc = {{}}
sc["t1"] = L.answer(db, "stu", "l29_t1", {{"serial": cs["serials"][0].lower(), "joint": "J2"}})["score"]
sc["t2"] = L.answer(db, "stu", "l29_t2", {{"lot": j2["lot"], "backlash0": round(j2["backlash0"], 2)}})["score"]
sc["t3"] = L.answer(db, "stu", "l29_t3", {{"choice": "bad_lot"}})["score"]
sc["t4"] = L.answer(db, "stu", "l29_t4", {{"serials": "、".join(cs["serials"][1:])}})["score"]
jw = RF.plan_job(H, "teach", cs["serials"][0], "lube", "stu")                  # 派错：补润滑脂不算
RF.complete_job(H, "teach", jw, "stu")
out["after_wrong"] = L.status(db, "stu")["score"]
jid = RF.plan_job(H, "teach", cs["serials"][0], "swap", "stu", "J2")
RF.complete_job(H, "teach", jid, "stu")
t = L.answers("stu")
sc["t6"] = L.answer(db, "stu", "l29_t6", {{"A": t["A"], "B": t["B"]}})["score"]
sc["t2_after_swap"] = L.answer(db, "stu", "l29_t2", {{"lot": j2["lot"], "backlash0": round(j2["backlash0"], 2)}})["score"]
out["sc"] = sc
out["t"] = t
out["final"] = L.status(db, "stu")["score"]
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _fresh(name):
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute("drop database if exists {} with (force)".format(name))
            c.execute("create database {}".format(name))
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    return base + "/" + name


def test_lab29_flow():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, db=_fresh("wq_lab29_test"))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["health"][0] == "red" and o["health"][1] != "red" and o["health"][2] != "red"     # 1 台超限，2 台还没
    assert o["case2"] and o["same"] == 2
    assert o["wrong"] == {"t1": 0, "t3": 0, "t4": 5}
    assert o["sc"] == {"t1": 10, "t2": 10, "t3": 10, "t4": 10, "t6": 10, "t2_after_swap": 10}
    assert o["after_wrong"] == 40                                                            # 派错的工单不给任务 5
    assert o["t"] == {"A": 3 * 2600.0, "B": 3 * 4100.0, "one": 2600.0}
    assert o["final"] == 60
