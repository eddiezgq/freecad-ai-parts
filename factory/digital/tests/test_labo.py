# -*- coding: utf-8 -*-
"""第 149 轮：通用“从订单到交付”实验（hub/labo.py）——电路板厂实验 39、芯片封测厂实验 40：任务 1 的标准答案按物料清单算出，
答对答错的得分；任务 6 选项；按层核对；任务 3 用真仿真出的出厂检验数据判一件（答对 10 分、判反 0 分）；指导书和报告模板能生成。"""
import json
import os
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]

CODE = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
DBN = "wq_labo_{mod}_test"
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists " + DBN + " with (force)")
    c.execute("create database " + DBN)
from hub.db import DB
from hub.historian import Historian
from hub import lab24
import importlib
lab = importlib.import_module("hub." + {mod!r})
pre = {pre!r}
db = DB(BASE + "/" + DBN)
db.init()
P = lab.PRODUCT
out = {{"exp": lab.expected_counts()}}
e = out["exp"]
out["t1_right"] = lab.answer(db, "甲", pre + "t1", {{"work_orders": e["work_orders"], "count": e["count"]}})["score"]
out["t1_half"] = lab.answer(db, "乙", pre + "t1", {{"work_orders": e["work_orders"], "count": e["count"] * 2 + 1}})["score"]
out["t1_bad"] = lab.answer(db, "丙", pre + "t1", {{"work_orders": "x", "count": None}})["score"]
right = [k for k, _, ok in lab.T6_OPTIONS if ok]
wrong = [k for k, _, ok in lab.T6_OPTIONS if not ok]
out["t6_right"] = lab.answer(db, "甲", pre + "t6", {{"choices": right}})["score"]
out["t6_part"] = lab.answer(db, "乙", pre + "t6", {{"choices": right[:1]}})["score"]
out["t6_wrong"] = lab.answer(db, "丙", pre + "t6", {{"choices": right[:1] + wrong[:1]}})["score"]
out["t3_no_order"] = lab.answer(db, "甲", pre + "t3", {{"serial": "x", "verdict": "pass"}})["score"]
# 真仿真：做一张成品工单 W2（半成品工单 W1），出厂检验的测量记到这张单上
from sim.engine import Engine, routing_for, OP_UNITS
h = Historian(db)
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: h.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
             mode="teach", auto_start=True, seed=5, status_every_s=1e9)
eng.set_reliability(0)
ops = routing_for(P)
for op, _ in ops:
    ok, why = eng.command(OP_UNITS[op][0], {{"command": "dispatch", "work_order": "W2", "operation": op, "qty": 2, "item": P, "routing": ops}}, "W2")
    assert ok, why
while eng.q and clock.t < 365 * 86400:
    clock.t = max(clock.t, eng.next_event_time())
    eng.run_due()
sub = [c for c in lab24.F.BOMS[P][1] if c[0] in lab24.F.BOMS][0][0]
order = {{"sales_order": "SO-1", "work_orders": {{sub: "W1", P: "W2"}}}}
import hub.lab24 as L24
L24.my_order = lambda db, user, product=None: order if user == "甲" else None
us = lab.units(db, order)
out["n_units"] = len(us)
k, u = sorted(us.items())[0]
fails = sorted(c for c, x in u["chars"].items() if x["result"] == "fail")
v = "fail" if fails else "pass"
out["t3_right"] = lab.answer(db, "甲", pre + "t3", {{"serial": k, "verdict": v, "char": fails[0] if fails else ""}})["score"]
out["t3_wrong"] = lab.answer(db, "甲", pre + "t3", {{"serial": k, "verdict": "pass" if v == "fail" else "fail"}})["score"]
ts = {{"W1": ("2026-01-02T00:00:00Z", "2026-01-05T00:00:00Z"), "W2": ("2026-01-03T00:00:00Z", None)}}
lab24._release_ts = lambda db, wo: ts[wo][0]
lab24._done_ts = lambda db, wo: ts[wo][1]
out["bad"] = lab24.layers(db, order)[1]
st = lab.status(db, "甲")
out["score"] = st["score"]
out["std"] = st["std"]
out["machines"] = len(st["machines"])
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _run(plant, mod):
    psycopg = pytest.importorskip("psycopg")
    try:
        psycopg.connect(BASE + "/postgres").close()
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant)))
    code = CODE.format(dig=DIG, fac=FAC, base=BASE, mod=mod, pre=mod.replace("lab", "l") + "_")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


@pytest.mark.parametrize("plant,mod,exp,sub", [
    ("pcb", "lab39", {"work_orders": 2, "count": 6.0}, "SMT-DRV"),
    ("chip", "lab40", {"work_orders": 2, "count": 630.0}, "WAF-ENCIF-CP"),
])
def test_labo(plant, mod, exp, sub):
    out = _run(plant, mod)
    assert out["exp"] == exp, out
    assert (out["t1_right"], out["t1_half"], out["t1_bad"]) == (10, 5, 0), out
    assert (out["t6_right"], out["t6_part"], out["t6_wrong"]) == (5, 2, 0), out
    assert out["t3_no_order"] == 0
    assert out["n_units"] >= 1 and out["machines"] == out["n_units"], out
    assert (out["t3_right"], out["t3_wrong"]) == (10, 0), out
    assert out["bad"] == ["WQ-ENCIF" if plant == "chip" else "DRV-JOINT"], out    # 成品在半成品完工前就下达了
    assert out["score"] == 10 + 5 + 10 and out["std"]["total"] > out["std"]["material"] > 0, out


@pytest.mark.parametrize("lab", ["lab39", "lab40"])
def test_labo_docs(lab):
    sys.path[:0] = [DIG, FAC]
    from cae import labdoc
    assert len(labdoc.guide_docx(lab)) > 10000 and len(labdoc.report_template_docx(lab)) > 10000
