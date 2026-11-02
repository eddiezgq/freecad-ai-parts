# -*- coding: utf-8 -*-
"""第 74 轮：实验 30“一台轮式人形从订单到交付”——算料答案（16 张工单、16 个关节、底盘自己造）、
两种整机抢的工位按平台数据算（CAL-1，可行对策：错开排产、带徒）、同周两张单、人形判定、按层下达扣分。
机器人厂在子进程里按清单跑；需要 PostgreSQL。完整流程（真 ERPNext 里做完、开票、成本）在服务器演练 --lab30 里核对。"""
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
import json, sys, uuid, datetime as dt
sys.path[:0] = [{dig!r}, {fac!r}]
from psycopg.types.json import Jsonb
from hub.db import DB
from hub import lab30 as L
db = DB({db!r}); db.init()
T0 = dt.datetime(2026, 11, 2, 1, 0, tzinfo=dt.timezone.utc)

def msg(ty, data, corr=None, t=T0):
    m = {{"id": str(uuid.uuid4()), "ts": t.isoformat(), "type": ty, "source": "test", "mode": "teach", "corr": corr, "data": data}}
    db.insert_message("t/" + ty, m)

def order(user, item, so, wos, t):
    for it, n in wos.items():
        msg("erp.doc", {{"doctype": "Work Order", "name": n, "production_item": it, "status": "Not Started", "action": "created"}}, t=t)
    db.x("insert into ai_proposal (proposal_id, created_at, mode, action, preview, status, requested_by, result) values (%s,%s,'teach','create_order_and_plan',%s,'executed',%s,%s)",
         (str(uuid.uuid4()), t, Jsonb({{"sales_order": {{"item_code": item}}}}), user, Jsonb({{"created": [["Sales Order", so]] + [["Work Order", n] for n in wos.values()]}})))

out = {{"conflict": L.conflict(db), "answers": L.answers(db, "x")}}
# 任务 1
out["t1_right"] = L.answer(db, "stu", "l30_t1", {{"work_orders": 16, "joints": 16, "chassis": "make"}})["score"]
out["t1_stock"] = L.answer(db, "stu2", "l30_t1", {{"work_orders": 16, "joints": 16, "chassis": "stock"}})["score"]
out["t1_cr5"] = L.answer(db, "stu3", "l30_t1", {{"work_orders": 14, "joints": 6, "chassis": "make"}})["score"]
# 两张单：stu 同一周，stu2 隔了 10 天
wos = {{"WQ-H1": "WO-H1", "WQ-AGV300": "WO-AGV", "DU-AGV": "WO-DU"}}
order("stu", "WQ-H1", "SO-H1", wos, T0)
order("stu", "WQ-CR5", "SO-CR5", {{"WQ-CR5": "WO-CR5"}}, T0 + dt.timedelta(days=2))
order("stu2", "WQ-H1", "SO-H1b", {{"WQ-H1": "WO-H1b"}}, T0)
order("stu2", "WQ-CR5", "SO-CR5b", {{"WQ-CR5": "WO-CR5b"}}, T0 + dt.timedelta(days=10))
out["t3_right"] = L.answer(db, "stu", "l30_t3", {{"unit": "cal-1", "choices": ["stagger", "train"]}})["score"]
out["t3_far"] = L.answer(db, "stu2", "l30_t3", {{"unit": "CAL-1", "choices": ["stagger", "train"]}})["score"]
out["t3_wrong"] = L.answer(db, "stu3", "l30_t3", {{"unit": "RA-1", "choices": ["outsource"]}})["score"]
# 任务 4：一台人形的三项测量，节拍超了
for code, name, v, lo, hi in [("h1_dual", "双臂相对位姿误差", 0.3, 0, 1.0), ("h1_handeye", "手眼标定误差", 1.1, 0, 3.0), ("h1_cycle", "走到桌前双手抓箱的节拍", 44, 0, 40)]:
    msg("quality.measurement", {{"work_order": "WO-H1", "part_serial": "H1-0001", "item": "WQ-H1", "characteristic": code, "name": name, "value_mm": v,
                                 "lower_tol_mm": lo, "upper_tol_mm": hi, "unit": "", "result": "fail" if not lo <= v <= hi else "pass"}}, corr="WO-H1")
out["t4_pass"] = L.answer(db, "stu", "l30_t4", {{"serial": "H1-0001", "verdict": "pass"}})["score"]
out["t4_fail"] = L.answer(db, "stu", "l30_t4", {{"serial": "H1-0001", "verdict": "fail", "char": "h1_cycle"}})["score"]
# 任务 2：底盘还没做完就下达了人形整机
msg("machine.cmd", {{"command": "dispatch"}}, corr="WO-DU", t=T0 + dt.timedelta(hours=1))
msg("machine.event", {{"event": "op_complete", "last_op": True}}, corr="WO-DU", t=T0 + dt.timedelta(hours=2))
msg("machine.cmd", {{"command": "dispatch"}}, corr="WO-AGV", t=T0 + dt.timedelta(hours=3))
msg("machine.cmd", {{"command": "dispatch"}}, corr="WO-H1", t=T0 + dt.timedelta(hours=4))
msg("machine.event", {{"event": "op_complete", "last_op": True}}, corr="WO-AGV", t=T0 + dt.timedelta(hours=5))
st = L.check(db, "stu")
out["t2"] = next(t["score"] for t in st["tasks"] if t["id"] == "l30_t2")
out["status"] = {{"order": st["order"]["sales_order"], "other": st["other_order"], "units": [u["serial"] for u in st["units"]], "score": st["score"]}}
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


def test_lab30_grading():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, db=_fresh("wq_lab30_test"))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    c = o["conflict"]
    assert c["unit"] == "cal-1" and c["code"] == "CAL-1" and "cal-1" in c["shared"] and c["load_min"] == 120.0   # 人形 60 + 协作臂 40 + 20
    assert c["feasible"] == ["stagger", "train"]
    assert o["answers"]["t1"] == {"work_orders": 16, "joints": 16, "chassis": "make"}
    assert (o["t1_right"], o["t1_stock"], o["t1_cr5"]) == (10, 7, 3)               # 底盘选“从成品库拿”拿不到那 3 分
    assert (o["t3_right"], o["t3_far"], o["t3_wrong"]) == (10, 7, 0)               # 两张单隔了 10 天不算同一周；工位填错拿不到
    assert (o["t4_pass"], o["t4_fail"]) == (0, 10)
    assert o["t2"] == 5                                                             # 人形整机在底盘做完前下达：扣 5 分
    assert o["status"]["order"] == "SO-H1" and o["status"]["other"] == "SO-CR5" and o["status"]["units"] == ["H1-0001"]
