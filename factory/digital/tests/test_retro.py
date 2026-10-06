# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 5 步：复盘——推演 vs 实际、偏差原因、“如果当时”、未完的复盘、校准提示。

情景：实验 7（GRD-01 换砂轮停机）。厂长批准“维修加急”，真车间（同一个引擎接着跑，事件进历史库）做完以后自动复盘。"""
import datetime as dt
import json
import os

import pytest
from psycopg.types.json import Jsonb

import wqbus

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class Clock:
    t = 0.0

    def now(self):
        return self.t


class Snaps:
    def __init__(self, db, eng):
        self.db, self.eng = db, eng

    def take(self, mode, timeout=5.0):
        st = json.loads(json.dumps(self.eng.snapshot()))
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), true, %s) returning id", (mode, Jsonb(st)))
        return r["id"], st, True


class MES:
    """执行器发给车间的指令直接交给引擎（真车间）"""

    def __init__(self, eng):
        self.eng, self.sent = eng, []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(command)
        d = dict(extra, command=command)
        if work_order:
            d["work_order"] = work_order
        if operation:
            d["operation"] = operation
        return self.eng.command(unit, d)


@pytest.fixture(scope="module")
def plant():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_retro_test with (force)")
            c.execute("create database wq_retro_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    import types

    from hub.ai import Assistant
    from hub.db import DB
    from hub.historian import Historian
    from hub.ont import actions as AC
    from hub.ont import plan as P
    from hub.ont import retro as RT
    from sim import scenario
    from sim.engine import Engine
    from tests.test_agent import NoLLM
    db = DB(BASE + "/wq_retro_test")
    db.init()
    P.init(db)
    AC.init(db)
    RT.init(db)
    h = Historian(db)
    clock = Clock()
    eng = Engine(lambda tp, ty, src, data, corr: h.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
                 mode="teach", auto_start=False, seed=1, status_every_s=1e9)
    clock.t = scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    sy = Sync(db, Store(db))
    sy.init()
    sy.replay()
    ai = Assistant(db, lambda *a: None, NoLLM())
    ai.detector().run("teach", NOW)
    H = types.SimpleNamespace(db=db, ai=ai, mes=MES(eng), plan_snaps=Snaps(db, eng))
    return H, eng, clock


def _run_until(eng, clock, wo, limit_h=400):
    end = clock.t + limit_h * 3600
    while eng.q and clock.t < end:
        clock.t = max(clock.t, eng.q[0][0])
        eng.run_due()
        w = eng.wos.get(wo)
        if w and all(p.op_index >= len(w.ops) for p in w.parts):
            return True
    return False


def test_auto_retro_after_action_and_completion(plant):
    from hub.ont import actions as AC
    from hub.ont import retro as RT
    H, eng, clock = plant
    db = H.db
    a = db.one("select * from anomaly where rule='P1' and subject_key='grd-01' and status in ('open','ack','doing')")
    assert a
    boss = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
    sid, st, _ = H.plan_snaps.take("teach")
    ch = {"type": "expedite", "unit": "grd-01", "factor": 0.5}
    tr = dict(AC.trial(db, H.plan_snaps, "teach", [ch], st), snapshot_id=sid)
    aid = AC.create(db, "teach", boss, "expedite", ch, None, a["id"], tr)
    AC.submit(db, aid, boss, tr)
    assert AC.approve(H, aid, boss, "王老师")["status"] == "done" and H.mes.sent[-1] == "expedite_repair"
    # 还没做完：不复盘（异常解决了也一样）
    db.x("update anomaly set status='resolved', closed_at=now(), closed_reason='恢复' where id=%s", (a["id"],))
    assert RT.due(db, "teach") == []
    # 真车间接着跑到工单做完
    assert _run_until(eng, clock, "MFG-WO-2026-00016")
    a2 = db.one("select * from anomaly where id=%s", (a["id"],))
    acts = db.q("select * from action where anomaly_id=%s", (a["id"],))
    probe = RT.build(db, a2, acts)
    assert not probe["partial"], probe["deviation"]
    rids = RT.due(db, "teach")
    assert len(rids) == 1
    r = db.one("select * from retro where id=%s", (rids[0],))
    assert not r["partial"] and r["action_id"] == aid and r["snapshot_id"] == sid
    wo = next(x for x in r["deviation"]["work_orders"] if x["work_order"] == "MFG-WO-2026-00016")
    assert wo["actual"] and wo["predicted"] and abs(wo["pct"]) < 10          # 精确快照、没有新扰动：预测与实际相差 < 10%
    assert r["predicted"]["cost_total"] >= 300 and abs(r["deviation"]["cost_diff"]) < 1
    cf = r["counterfactual"]
    assert len(cf) >= 2 and sum(1 for o in cf if o["chosen"]) == 1 and next(o for o in cf if o["chosen"])["label"] == "维修加急"
    assert any(o["label"] == "不处理" for o in cf)
    # 复盘挂在异常上，异常记录里有一条
    assert db.one("select 1 as x from anomaly_note where anomaly_id=%s and kind='retro'", (a["id"],))
    assert RT.due(db, "teach") == []                                             # 不重复


def test_calibration_hint_after_three_slow_retros(plant):
    from hub.ont import retro as RT
    H, eng, clock = plant
    db = H.db
    for i in range(3):
        db.x("insert into retro (mode, title, causes) values ('calib', %s, %s)",
             ("复盘 {}".format(i), Jsonb([{"kind": "slow_op", "unit": "grd-01", "op": "磨外圆", "pct": 14.0 + i, "text": "慢"}])))
    hints = RT.calibration(db, "calib")
    assert len(hints) == 1 and hints[0]["unit"] == "grd-01" and "标准工时" in hints[0]["text"]
    db.x("insert into retro (mode, title, causes) values ('calib', '正常', %s)", (Jsonb([{"kind": "fast_op", "unit": "grd-01", "op": "磨外圆", "pct": -12}]),))
    assert RT.calibration(db, "calib") == []                                     # 最近一次不慢了，提示消失


def test_past_snapshot_simulation_ok_but_not_an_action(plant):
    from hub.ont import plan as P
    H, eng, clock = plant
    db = H.db
    old = db.one("select id, state from sim_snapshot order by id limit 1")
    db.x("update sim_snapshot set ts = now() - interval '3 hours' where id=%s", (old["id"],))
    ctx = P.context(db, "teach", dt.datetime.fromisoformat(old["state"]["factory_now"]))
    r = P.simulate(old["state"], [{"type": "expedite", "unit": "grd-01", "factor": 0.5}], ctx)       # 复盘推演照常能算
    assert r["work_orders"]
    assert db.one("select 1 as x from sim_snapshot where id=%s and ts < now() - interval '2 hours'", (old["id"],))
