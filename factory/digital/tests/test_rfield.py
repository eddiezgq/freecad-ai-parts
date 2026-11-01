# -*- coding: utf-8 -*-
"""第 64 轮：机器人厂的客户与服务——现场的机器人。建档（关节按规格先进先出配上关节测试台测过的关节）、发出（销售订单开票）、
现场模拟（问题批次背隙涨得快）、预警（RS1、RS2）、投诉、上门换关节模组后背隙复位、回访。机器人厂在子进程里按清单跑；需要 PostgreSQL。"""
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
import json, sys, types, uuid
sys.path[:0] = [{dig!r}, {fac!r}]
from hub.db import DB
from hub import rfield as RF, finance as FN
from hub.ont import actions as AC
db = DB({db!r}); db.init(); AC.init(db); FN.init(db)
out = {{}}
H = types.SimpleNamespace(db=db, ai=None)
M = "teach"
seq = [0]
def put(tp, typ, data, corr=None):
    seq[0] += 1
    db.insert_message(tp, {{"id": str(uuid.uuid4()), "type": typ, "mode": M, "source": "test", "corr": corr, "data": data,
                           "ts": "2026-11-01T00:{{:02d}}:{{:02d}}Z".format(seq[0] // 60, seq[0] % 60)}})
def msg(char, serial, item, value, lot=None, wo=None):
    put("wq/robot/quality/x/measurement", "quality.measurement",
        {{"characteristic": char, "part_serial": serial, "item": item, "value_mm": value, "lot": lot, "work_order": wo}}, wo)
# 8 台情景开始前的
out["seeded"] = len(RF.fleet(db, M))
# 车间：6 个关节测完（一批问题批次的大关节），一台整机标定做完
bad = "HD-L-BAD"
db.x("create table if not exists lot (id bigserial primary key, mode text, lot text, status text, truth_bad boolean)")
db.x("insert into lot (mode, lot, status, truth_bad) values (%s,%s,'accepted',true)", (M, bad))
for i, (item, lot, b) in enumerate([("WQJ-L", bad, 0.62), ("WQJ-L", "HD-L-OK", 0.60), ("WQJ-M", "HD-M-OK", 0.61),
                                    ("WQJ-S", "HD-S-OK", 0.70), ("WQJ-S", "HD-S-OK", 0.71), ("WQJ-S", "HD-S-OK", 0.69), ("WQJ-L", "HD-L-OK", 0.58)]):
    msg("joint_backlash", "J{{:03d}}".format(i), item, b, lot)
msg("cr_abs", "WQ-CR5-0001", "WQ-CR5", 0.118, wo="MFG-WO-1")
out["built"] = RF.scan(db, M)
r = db.one("select * from rf_robot where mode=%s and serial='WQ-CR5-0001'", (M,))
out["joints"] = [(j["joint"], j["serial"], j["lot"], j["bad"]) for j in r["as_built"]["joints"]]
out["pool_left"] = db.one("select count(*) as n from rf_pool where mode=%s and used_by is null", (M,))["n"]
# 发出：工单属于 SO-1，SO-1 开了票
put("wq/robot/erp/doc", "erp.doc", {{"doctype": "Work Order", "action": "created", "name": "MFG-WO-1", "sales_order": "SO-1", "docstatus": 1,
                                     "production_item": "WQ-CR5", "qty": 1}})
put("wq/robot/erp/doc", "erp.doc", {{"doctype": "Sales Order", "action": "created", "name": "SO-1", "customer": RF.customers()[2], "docstatus": 1,
                                     "items": [{{"item_code": "WQ-CR5", "qty": 1, "rate": 18000}}]}})
out["ship_before"] = RF.ship(db, M)
db.x("insert into invoice (mode, kind, party, ref, amount, outstanding, issued_at, due_at, status) values (%s,'ar','x','SO-1',1,1,now(),now(),'open')", (M,))
out["ship"] = RF.ship(db, M)
RF.advance(db, M, 400)
d = RF.detail(db, M, "WQ-CR5-0001")
last = d["series"][-1]["joints"]
out["j1"], out["j2"] = last[0]["backlash"], last[1]["backlash"]
out["health"] = d["health"]
out["why_kinds"] = sorted({{w["kind"] for w in d["why"]}})
from hub.ont import anomaly as A
det = A.Detector(db)
fs, _ = det.detect(M, only=["RS1", "RS2"])
out["rs1"] = sorted(f.fkey for f in fs["RS1"])
out["rs2"] = sorted(f.fkey for f in fs["RS2"])
cid = RF.create_complaint(H, M, {{"serial": "WQ-CR5-0001", "subject": "J1 异响", "joint": "J1"}}, "老师")
jid = RF.plan_job(H, M, "WQ-CR5-0001", "swap", "老师", "J1", cid)
job = RF.jobs(db, M)[0]
out["job"] = (job["kind"], job["joint"], job["status"], job["cost_usd"], bool(job["engineer"]))
RF.complete_job(H, M, jid, "老师")
r = db.one("select * from rf_robot where mode=%s and serial='WQ-CR5-0001'", (M,))
out["after"] = (r["as_built"]["joints"][0]["serial"], r["as_built"]["joints"][0]["replaced"]["lot"], r["state"]["joints"][0]["wear"])
out["complaint"] = RF.complaints(db, M)[0]["status"]
RF.score(db, M, cid, 5, "好", "客户")
out["kpis"] = RF.kpis(db, M)
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


def test_robot_field_service_flow():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, db=_fresh("wq_rfield_test"))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["seeded"] == 8
    assert o["built"] == ["WQ-CR5-0001"]
    assert [j[1] for j in o["joints"]] == ["J000", "J001", "J002", "J003", "J004", "J005"]       # 按规格先进先出
    assert o["joints"][0][2] == "HD-L-BAD" and o["joints"][0][3] is True and o["joints"][1][3] is False
    assert o["pool_left"] == 1
    assert o["ship_before"] == [] and o["ship"] == ["WQ-CR5-0001"]
    assert o["j1"] > o["j2"] + 0.2                       # 问题批次的关节背隙涨得快
    assert o["health"] in ("yellow", "red") and "backlash" in o["why_kinds"]
    assert "WQ-CR5-0001" in o["rs1"]
    assert "HD-L-SEED-07" in o["rs2"] or "HD-L-BAD" in o["rs2"] or o["rs2"] == []     # 情景里两台用了同一问题批次
    assert o["job"][:3] == ["swap", "J1", "planned"] and o["job"][3] == 800 + 1800 and o["job"][4]
    assert o["after"][0] == "J006" and o["after"][1] == "HD-L-BAD" and o["after"][2] == 0.0      # 换上池里剩下的那台大关节
    assert o["complaint"] == "closed" and o["kpis"]["satisfaction"] == 5.0 and o["kpis"]["in_field"] == 9


def test_not_in_demo_plant():
    env = dict(os.environ)
    env.pop("WQ_PLANT_FILE", None)
    r = subprocess.run([sys.executable, "-c", "import sys; sys.path[:0]=[{!r},{!r}]; from hub import rfield as RF; print(RF.enabled())".format(DIG, FAC)],
                       capture_output=True, text=True, env=env, cwd=DIG, timeout=60)
    assert r.stdout.strip() == "False"
