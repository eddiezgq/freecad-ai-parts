# -*- coding: utf-8 -*-
"""第 17 轮 C 期第 4–5 步：处理预案、动作框架（审批、执行器、回写）、班次接口、时间回看。"""
import datetime as dt
import json
import os

import pytest

import wqbus
from sim.calendar import Calendar

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)


class FakeMES:
    def __init__(self):
        self.sent = []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(dict(extra, unit=unit, command=command, mode=mode, work_order=work_order, operation=operation))


class FakeSnaps:
    """推演用的快照：实验 7 情景引擎的精确快照（按需换成按班次）"""

    def __init__(self, db, eng):
        self.db, self.eng, self.cal = db, eng, None

    def take(self, mode, timeout=5.0):
        from psycopg.types.json import Jsonb
        st = json.loads(json.dumps(self.eng.snapshot()))
        if self.cal:
            st["calendar"] = self.cal
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), true, %s) returning id", (mode, Jsonb(st)))
        return r["id"], st, True


@pytest.fixture(scope="module")
def env():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_act_test with (force)")
            c.execute("create database wq_act_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.historian import Historian
    from hub.ont import actions as AC
    from hub.ont import plan as P
    from sim import scenario
    from tests_helpers import make_engine
    db = DB(BASE + "/wq_act_test")
    db.init()
    P.init(db)
    AC.init(db)
    h = Historian(db)
    eng, clock, _ = make_engine(auto=False)
    clock.t = scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    return db, eng


@pytest.fixture
def client(env, monkeypatch):
    from fastapi.testclient import TestClient
    import hub.app as app_mod
    from hub.ai import Assistant

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    db, eng = env
    sent = []
    mes = FakeMES()
    monkeypatch.setattr(app_mod.H, "db", db)
    monkeypatch.setattr(app_mod.H, "ai", Assistant(db, lambda *a: sent.append(a), NoLLM()))
    monkeypatch.setattr(app_mod.H, "mes", mes)
    snaps = FakeSnaps(db, eng)
    monkeypatch.setattr(app_mod.H, "plan_snaps", snaps, raising=False)
    app_mod.H.ai.detector().run("teach", NOW)
    c = TestClient(app_mod.app)

    def tok(name, role, teacher=False, mode="teach"):
        return {"X-WQ-Token": app_mod._sign({"name": name, "role": role, "mode": mode, "teacher": teacher, "exp": 9e12})}
    return c, tok, mes, snaps, sent, app_mod


def _down(db):
    return db.one("select * from anomaly where rule='P1' and fkey='grd-01' and status in ('open','ack','doing')")


def test_playbook_options_for_downtime(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    db, eng = env
    a = _down(db)
    assert a
    r = c.get("/api/ont/anomalies/{}/options".format(a["id"]), headers=tok("甲", "operator")).json()
    kinds = [o["kind"] for o in r["options"]]
    assert kinds[0] == "none" and "expedite" in kinds
    assert "overtime" not in kinds                                     # 24 小时连续：没有加班方案
    assert "reassign" not in kinds                                     # 磨床没有同类设备
    rec = next(o for o in r["options"] if o["recommended"])
    exp = next(o for o in r["options"] if o["kind"] == "expedite")
    none = next(o for o in r["options"] if o["kind"] == "none")
    assert exp["result"]["work_orders"]["MFG-WO-2026-00016"]["finish"] < none["result"]["work_orders"]["MFG-WO-2026-00016"]["finish"]
    assert r["reason"] and rec["key"] in r["reason"] or "不处理" in r["reason"]
    # 换成按班次：出现加班方案
    snaps.cal = Calendar("shift").to_dict()
    r2 = c.get("/api/ont/anomalies/{}/options".format(a["id"]), headers=tok("甲", "operator")).json()
    assert "overtime" in [o["kind"] for o in r2["options"]]
    snaps.cal = None


def test_action_approval_rules_and_execution(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    db, eng = env
    a = _down(db)
    stu_planner, stu_planner2 = tok("学生甲", "planner"), tok("学生乙", "planner")
    stu_op = tok("学生丙", "operator")
    teacher = tok("王老师", "manager", teacher=True)
    ch = [{"type": "expedite", "unit": "grd-01", "factor": 0.5}]
    assert c.post("/api/ont/actions", json={"changes": ch, "anomaly_id": a["id"]}, headers=stu_op).status_code == 400   # 操作工不能发起
    r = c.post("/api/ont/actions", json={"changes": ch, "anomaly_id": a["id"]}, headers=stu_planner).json()
    aid = r["ids"][0]
    assert r["trial"]["cost_total"] > 0 and r["trial"]["base"]
    x = c.get("/api/ont/actions/{}".format(aid), headers=stu_planner).json()
    assert x["status"] == "submitted" and not x["can_approve"]
    assert c.post("/api/ont/actions/{}/approve".format(aid), headers=stu_planner).status_code == 400        # 自己不能批
    y = c.post("/api/ont/actions/{}/approve".format(aid), headers=stu_planner2)
    assert y.status_code == 400 and "厂长" in y.json()["detail"]                                         # 花钱的要厂长批
    z = c.post("/api/ont/actions/{}/approve".format(aid), headers=teacher).json()
    assert z["status"] == "done" and z["approver"] == "王老师"
    assert mes.sent[-1]["command"] == "expedite_repair" and mes.sent[-1]["unit"] == "grd-01"
    assert [n["kind"] for n in z["log"]] == ["create", "submit", "approve", "execute"]
    # 不花钱的（调序）：另一位计划员可以批
    pending = [w for w, i in eng.snapshot()["machines"]["grd-01"]["jobs"]]
    if pending:
        r = c.post("/api/ont/actions", json={"changes": [{"type": "reorder", "unit": "grd-01", "work_order": pending[-1]}]}, headers=stu_planner).json()
        assert c.post("/api/ont/actions/{}/approve".format(r["ids"][0]), headers=stu_planner2).json()["status"] == "done"
    # 驳回要写原因
    r = c.post("/api/ont/actions", json={"changes": ch}, headers=stu_planner).json()
    assert c.post("/api/ont/actions/{}/reject".format(r["ids"][0]), json={"text": ""}, headers=teacher).status_code == 400
    assert c.post("/api/ont/actions/{}/reject".format(r["ids"][0]), json={"text": "先等维修评估"}, headers=teacher).json()["status"] == "rejected"
    # 收件箱：待我批准
    todo = c.get("/api/ont/actions?box=todo", headers=teacher).json()["actions"]
    assert all(t["can_approve"] for t in todo)


def test_overtime_action_changes_shift_calendar(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    db, eng = env
    teacher = tok("王老师", "manager", teacher=True)
    planner = tok("学生甲", "planner")
    assert c.post("/api/ont/shifts", json={"mode": "shift"}, headers=planner).status_code == 403
    r = c.post("/api/ont/shifts", json={"mode": "shift"}, headers=teacher).json()
    assert r["calendar"]["mode"] == "shift" and mes.sent[-1]["command"] == "set_calendar"
    snaps.cal = r["calendar"]
    day = "2026-10-20"
    x = c.post("/api/ont/actions", json={"changes": [{"type": "overtime", "day": day, "unit": "*", "minutes": 120}]}, headers=planner).json()
    done = c.post("/api/ont/actions/{}/approve".format(x["ids"][0]), headers=teacher).json()
    assert done["status"] == "done"
    cal = c.get("/api/ont/shifts", headers=planner).json()["calendar"]
    assert cal["overtime"]["2026-10-20|*"] == 120
    assert mes.sent[-1]["command"] == "set_calendar" and mes.sent[-1]["calendar"]["overtime"]["2026-10-20|*"] == 120
    c.post("/api/ont/shifts", json={"mode": "continuous"}, headers=teacher)
    snaps.cal = None


def test_prod_mode_forbids_self_approval_even_for_teacher(client, env):
    from hub.ont import actions as AC
    db, eng = env
    a = {"type": "reorder", "initiator": "王老师", "mode": "prod"}
    assert not AC.can_approve({"name": "王老师", "role": "manager", "teacher": True}, a)[0]
    assert AC.can_approve({"name": "王老师", "role": "manager", "teacher": True}, dict(a, mode="teach"))[0]


def test_erp_actions_go_through_proposals(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    db, eng = env
    teacher = tok("王老师", "manager", teacher=True)
    so = "SAL-ORD-2026-00019"
    x = c.post("/api/ont/actions", json={"changes": [{"type": "split_delivery", "sales_order": so, "first_qty": 4, "first_date": "2026-10-22"},
                                                     {"type": "urgent_purchase", "item": "BRG-6207", "qty": 12, "arrive": "2026-10-21"}]},
               headers=teacher).json()
    assert len(x["ids"]) == 2
    for aid in x["ids"]:
        r = c.post("/api/ont/actions/{}/approve".format(aid), headers=teacher).json()
        assert r["status"] == "executing" and r["result"]["proposal_id"]
        p = db.one("select * from ai_proposal where proposal_id=%s", (r["result"]["proposal_id"],))
        assert p["status"] == "confirmed" and p["action"] in ("so_comment", "purchase_request")
        # 桥接执行完发回 erp.doc（corr = 提议编号）
        app_mod.H.ai.on_erp_result({"corr": p["proposal_id"], "data": {"action": "created", "doctype": "Comment", "proposal_done": True,
                                                                        "created": [["Comment", "C-1"]]}})
        assert c.get("/api/ont/actions/{}".format(aid), headers=teacher).json()["status"] == "done"


def test_history_and_ontology_mirror(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    db, eng = env
    from hub.ont.store import Store
    Store(db).init()                                         # 枢纽启动时就建好本体表
    at = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).isoformat()
    h = c.get("/api/ont/history", params={"at": at}, headers=tok("甲", "operator")).json()
    assert len(h["cards"]) == 15 and h["at"]
    assert c.get("/api/ont/history", params={"at": "2020-01-01T00:00:00Z"}, headers=tok("甲", "operator")).status_code == 400
    from hub.ont import sources as SRC
    st = Store(db)
    st.init()
    B = st.batch()
    SRC.plans(B, db, "teach")
    B.flush()
    assert db.one("select count(*) n from ont_object where type='ActionRun'")["n"] >= 3
    assert db.one("select count(*) n from ont_link where type='ActionRun.about' and dst_type='Machine' and dst_key='grd-01'")["n"] >= 1


def test_scenarios_save_and_simulate_endpoint(client, env):
    c, tok, mes, snaps, sent, app_mod = client
    planner = tok("学生甲", "planner")
    r = c.post("/api/ont/simulate", json={"changes": [{"type": "expedite", "unit": "grd-01", "factor": 0.5}]}, headers=planner).json()
    assert r["work_orders"] and r["snapshot_id"]
    s = c.post("/api/ont/scenarios", json={"title": "磨床加急", "snapshot_id": r["snapshot_id"],
                                           "changes": [{"type": "expedite", "unit": "grd-01", "factor": 0.5}]}, headers=planner).json()
    got = c.get("/api/ont/scenarios/{}".format(s["id"]), headers=planner).json()
    assert got["title"] == "磨床加急" and got["result"]["cost_total"] == r["cost_total"]
    assert c.post("/api/ont/simulate", json={"changes": [{"type": "nonsense"}]}, headers=planner).status_code == 400
