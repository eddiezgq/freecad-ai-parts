# -*- coding: utf-8 -*-
"""第 141 轮：缝纫机厂实验 32（照实验 25）——五种隐藏问题各走一遍：注入 → 判异（任务 1）→ 分层并说出设备（任务 2）→ 8D、
对症措施、验证有效、关闭（任务 3–5），满分 60；分层答错扣分；实验列表只在缝纫机厂显示。仿真在子进程里按缝纫机厂清单跑。"""
import json
import os
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
SEW = os.path.join(FAC, "plants", "wenquest-sewing.yaml")
BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]

LAB32 = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_lab32_test with (force)")
    c.execute("create database wq_lab32_test")
from hub.db import DB
from hub.historian import Historian
from hub import lab32, qproblem
from sim.engine import Engine, routing_for, OP_UNITS
db = DB(BASE + "/wq_lab32_test")
db.init()
h = Historian(db)
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: h.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
             mode="teach", auto_start=True, seed=11, status_every_s=1e9)
eng.set_reliability(0)
def send(cmd, **k):
    if cmd == "set_problem":
        eng.errors.inject(k["problem"], k.get("magnitude"))
    elif cmd == "apply_fix":
        eng.errors.apply_fix(k["fix"])
n = [0]
def run(item, qty, pick=None):
    n[0] += 1
    wo = "WO-{{}}".format(n[0])
    ops = routing_for(item)
    for op, _ in ops:
        u = next((v for k, v in (pick or {{}}).items() if op.startswith(k)), OP_UNITS[op][0])
        ok, why = eng.command(u, {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": item, "routing": ops}}, wo)
        assert ok, why
    while eng.q and clock.t < 365 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()
B1 = {{"LS30": "hmc-1", "LS80": "hmc-1"}}
B3 = {{"LS30": "hmc-3", "LS80": "hmc-3"}}
def batch():
    if {item!r} == "HSG-LS":
        run("HSG-LS", 5, B1)
        run("HSG-LS", 5, B3)
    else:
        run({item!r}, 8)
STU, TEA = "学生甲", {{"name": "王老师", "mode": "teach", "teacher": True}}
out = {{}}
batch()
out["inject_text"] = lab32.inject(db, send, TEA, {kind!r})["text"]
for _ in range(3):
    batch()
sig = lab32.signals(db, {item!r}, {char!r})
out["t1"] = lab32.answer(db, STU, "l32_t1", {{"characteristic": {item!r} + "|" + {char!r}, "rule": sig[0]["rule"] if sig else 0}})["score"]
out["t2"] = lab32.answer(db, STU, "l32_t2", {answer2})["score"]
out["t2_wrong"] = lab32.answer(db, "学生乙", "l32_t2", {wrong2})["score"]
s = qproblem.create(db, "teach", STU, None, {item!r}, {char8d!r}, "数据异常", {{"d1": "我", "d2": "数据", "d3": "隔离", "d4": "原因", "d5": "措施"}})
qproblem.update(db, s["id"], {{}}, {fix!r})
qproblem.submit_fix(db, s["id"])
qproblem.decide_fix(db, send, s["id"], "王老师", True)
for _ in range(2):
    batch()
v = qproblem.verify(db, s["id"])
out["verify"] = {{"effective": v["effective"], "after": v["after"]}}
qproblem.update(db, s["id"], {{"d7": "防错"}})
qproblem.close(db, s["id"], "学生甲")
st = lab32.check(db, STU)
out["tasks"] = {{t["id"]: t["score"] for t in st["tasks"]}}
out["score"] = st["score"]
out["chars"] = [c["value"] for c in st["characteristics"]]
out["strata"] = lab32.strata(db, "HSG-LS|hs_pos")
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _lab32(kind, item, char, answer2, wrong2, fix, char8d=None):
    psycopg = pytest.importorskip("psycopg")
    try:
        psycopg.connect(BASE + "/postgres").close()
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    env = dict(os.environ, WQ_PLANT_FILE=SEW)
    code = LAB32.format(dig=DIG, fac=FAC, base=BASE, kind=kind, item=item, char=char, char8d=char8d or char, answer2=repr(answer2), wrong2=repr(wrong2), fix=fix)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=1200)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _full(out):
    assert out["t1"] == 10 and out["t2"] == 15, out
    assert out["verify"]["effective"], out
    assert out["score"] == 60, out


def test_lab32_hmc_pin_station():
    out = _lab32("hmc_pin", "HSG-LS", "hs_pos", {"by": "station", "group": "hmc-3"}, {"by": "shared", "group": "age-1"}, "replace_hmc_pins")
    _full(out)
    assert out["t2_wrong"] == 0, out
    st = out["strata"]["station"]
    assert st["hmc-3"]["mean"] - st["hmc-1"]["mean"] > 0.01, st


def test_lab32_age_tc_shared():
    out = _lab32("age_tc", "HSG-LS", "hs_coax_up", {"by": "shared", "group": "age-1"}, {"by": "station", "group": "hmc-3"}, "calibrate_age_tc")
    _full(out)
    assert out["t2_wrong"] == 0, out


def test_lab32_foundry_problems():
    out = _lab32("inoc_fade", "CAST-LS", "cast_hb", {"by": "shared", "group": "POUR-1"}, {"by": "shared", "group": "mix-1"}, "dry_inoculant")
    _full(out)
    assert out["t2_wrong"] == 10, out                       # 层对、设备错
    out = _lab32("sand_moist", "CAST-LS", "cast_moist", {"by": "shared", "group": "mix-1"}, {"by": "station", "group": "hmc-1"}, "control_sand_water",
                 char8d="cast_pores")
    _full(out)


def test_lab32_induction():
    out = _lab32("ind_coil", "LS-101", "ls_hrc", {"by": "shared", "group": "ihd-1"}, {"by": "shared", "group": "ind-1"}, "replace_ind_coil")
    _full(out)
    assert "LS-101|ls_hrc" in out["chars"] and any(c.startswith("CAST-LS|smp_") for c in out["chars"]), out["chars"][:20]
    assert not any(c.startswith(("WQ-LS|", "WQ-OL|")) for c in out["chars"])


def test_sewing_labs_listed_only_in_sewing_plant():
    code = ("import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import labs_api as L\n"
            "print(json.dumps([l['no'] for l in L.labs_here()]))").format(DIG, FAC)
    env = dict(os.environ, WQ_PLANT_FILE=SEW)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout) == [32, 34]


def test_lab32_docs():
    sys.path[:0] = [DIG, FAC]
    from cae import labdoc
    assert len(labdoc.guide_docx("lab32")) > 10000 and len(labdoc.report_template_docx("lab32")) > 10000
