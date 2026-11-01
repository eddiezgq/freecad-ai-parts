# -*- coding: utf-8 -*-
"""第 67 轮：机器人厂的 AI 巡检和 AI 助手接上已打开的领域。规则在机器人厂跑起来（客户投诉 C1–C4 除外）、没有出错；
种子数据里本来就有的问题能触发（人员单点依赖 H1、危险废物超期 E7、应收逾期 F2、现场机器人报警 RS1 / 同批 RS2），处理方案不出错；
规则版助手答得出“保养 / 应收 / 现场机器人”。机器人厂在子进程里按清单跑；需要 PostgreSQL。"""
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
import json, sys, types, time
sys.path[:0] = [{dig!r}, {fac!r}]
from hub.db import DB
from hub.ai import Assistant
from hub import maint as MT, ehs as EH, people as PE, finance as FN, energy as EG, supply as SP, rfield as RF
from hub.ont import actions as AC, anomaly as A
from hub.ont.agent import Agent
db = DB({db!r}); db.init(); AC.init(db)
M = "teach"
class NoLLM:
    name = "rules"
    def available(self):
        return False
for f in (MT.seed, EH.seed, PE.seed, FN.seed, EG.seed, RF.seed):
    f(db, M)
SP.init(db)
RF.advance(db, M, 300)
ai = Assistant(db, lambda *a: None, NoLLM())
det = ai.detector()
cat = A.load_catalog()
out = {{"waiting": sorted(k for k, r in cat.items() if r["waiting"]), "live": len([r for r in cat.values() if not r["waiting"]])}}
det.run(M)
out["errors"] = {{k: v["error"] for k, v in det.stats.items() if v.get("error")}}
an = db.q("select id, rule, subject_key, detail, title from anomaly where mode=%s and status in ('open','ack','doing') order by id", (M,))
out["fired"] = sorted({{a["rule"] for a in an}})
opts = {{}}
for a in an:
    try:
        if a["rule"] in ("RS1", "RS2"):
            r = RF.anomaly_options(db, M, a)
        elif a["rule"] == "H1":
            r = PE.training_options(db, M, a)
        elif a["rule"] in ("F2", "F3", "F4", "F6", "F5", "F7"):
            r = FN.options(db, M, a)
        elif a["rule"] in ("E7", "E4", "E6"):
            r = EH.options(db, M, a, {{}}, {{}}) if hasattr(EH, "options") else {{"options": []}}
        else:
            continue
        opts[a["rule"]] = (len(r["options"]), r["recommended"])
    except Exception as e:
        opts[a["rule"]] = "ERR {{}}: {{}}".format(type(e).__name__, e)
out["opts"] = opts
H = types.SimpleNamespace(db=db, ai=ai, plan_snaps=None, mes=None)
u = {{"name": "王老师", "role": "manager", "teacher": True, "mode": M}}
ans = {{}}
for q in ("哪台设备保养逾期？", "哪个客户应收逾期？", "现场哪台机器人在报警？"):
    r = Agent(H, NoLLM()).ask(u, [{{"role": "user", "content": q}}])
    ans[q] = r.get("answer") or r.get("text") or json.dumps(r, ensure_ascii=False)[:400]
out["ans"] = ans
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


def test_robot_plant_rules_and_assistant():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, db=_fresh("wq_robot_rules_test"))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=600)
    assert r.returncode == 0, r.stderr[-4000:]
    o = json.loads(r.stdout.strip().splitlines()[-1])
    assert o["waiting"] == ["C1", "C2", "C3", "C4"]                    # 只有读减速器厂投诉表的四条不跑
    assert o["live"] == 59
    assert o["errors"] == {}
    assert {"H1", "E7", "RS1"} <= set(o["fired"]), o["fired"]
    for k, v in o["opts"].items():
        assert not str(v).startswith("ERR"), (k, v)
    assert o["opts"]["RS1"][0] >= 2 and o["opts"]["H1"][0] >= 1
    a = o["ans"]
    assert "本厂没有这个领域" not in "".join(a.values()), a
    assert "现场的机器人" in a["现场哪台机器人在报警？"] and "WQ-CR5-F" in a["现场哪台机器人在报警？"]
