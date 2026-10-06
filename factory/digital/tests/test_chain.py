# -*- coding: utf-8 -*-
"""第 17 轮 B 期：追因与影响面——两个验收故事、链条依据可核、权限、临时影响面。"""
import datetime as dt
import os

import pytest

import wqbus

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]


def _fresh(name):
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists {} with (force)".format(name))
            c.execute("create database {}".format(name))
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(BASE + "/" + name)
    d.init()
    return d


def _sync(db):
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    s = Sync(db, Store(db))
    s.init()
    s.replay()
    assert s.errors == 0, s.last_error
    return s


# ---------------------------------------------------------------- 故事二：现场报警 → 砂轮 → 排查范围
@pytest.fixture(scope="module")
def plant():
    """仿真器加工 30 根 SH-301（中途 GRD-01 换一次砂轮），再跑合 30 台 WQR-105，孪生按先进先出装轴"""
    from hub import twin as TW
    from hub.historian import Historian
    from sim.engine import Engine, torque_record
    from tests.test_sim import FakeClock, dispatch_all, run_to_end
    db = _fresh("wq_chain_test")
    old = TW.FIELD_MODES
    TW.FIELD_MODES = ["teach"]
    holder = {}

    def publish(tp, type_, source, data, corr=None, mode=None):
        msg = wqbus.make(type_, source, data, mode=mode or "teach", corr=corr)
        holder["h"].handle(tp, msg)
        return msg
    tw = TW.TwinService(db, publish)
    tw.init()
    hist = holder["h"] = Historian(db, tw.on_message)
    clock = FakeClock()
    eng = Engine(lambda tp, ty, src, data, corr: hist.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)),
                 clock, mode="teach", auto_start=True, seed=3, status_every_s=1e9)
    dispatch_all(eng, wo="WO-CH-1", qty=30)
    run_to_end(eng, clock)
    for i in range(30):
        rec = torque_record("WQR105-CH-{:02d}".format(i + 1), "WO-CH-A", "WQR-105")
        hist.handle("wq/gearbox/machining/test-01/torque", wqbus.make("test.torque", "sim/test-01", rec, mode="teach"))
    TW.FIELD_MODES = old
    _sync(db)
    return db


def _wheels_by_hand(db):
    """不用本体，直接数总线消息：GRD-01 每换一次砂轮序号加一；每根轴磨削开工时用的是第几片"""
    n, wheel = 1, {}
    for m in db.messages(["machine.event"], mode="teach", topic_like="wq/gearbox/machining/grd-01/%"):
        e = m["data"]["event"]
        if e == "tool_change":
            n += 1
        elif e == "cycle_start":
            wheel[m["data"]["part_serial"]] = "grd-01/{}".format(n)
    unit_shaft = {r["serial"]: r["as_built"]["shaft"]["serial"] for r in db.q("select serial, as_built from twin where mode='teach'")
                  if (r["as_built"] or {}).get("shaft")}
    cust = {r["serial"]: r["customer"] for r in db.q("select serial, customer from twin where mode='teach'")}
    return wheel, unit_shaft, cust


def _fleet(db, red=(), yellow=()):
    cust = {r["serial"]: r["customer"] for r in db.q("select serial, customer from twin where mode='teach'")}
    return lambda d, mode: [{"serial": s, "customer": c, "site": "port",
                             "health": "red" if s in red else "yellow" if s in yellow else "green",
                             "alerts": [{"title": "中间轴轴承 B 损伤加快", "level": "red", "kind": "bearing"}] if s in red or s in yellow else []}
                            for s, c in cust.items()]


def test_story2_field_alarm_traces_to_wheel_and_check_scope(plant, monkeypatch):
    from hub import twin as TW
    from hub.ont.anomaly import Detector
    db = plant
    wheel, unit_shaft, cust = _wheels_by_hand(db)
    assert len(set(wheel.values())) == 2, "测试数据应有两片砂轮"
    by_wheel = {}
    for u, s in unit_shaft.items():
        by_wheel.setdefault(wheel[s], set()).add(u)
    assert len(by_wheel) == 2, "两片砂轮磨出的轴都应装进了设备"
    w1 = sorted(by_wheel)[0]
    u0 = sorted(by_wheel[w1])[0]
    expect_units = by_wheel[w1] - {u0}
    expect_cust = {cust[u] for u in expect_units}

    monkeypatch.setattr(TW, "fleet", _fleet(db, red={u0}))
    D = Detector(db)
    D.run("teach")
    a = db.one("select * from anomaly where rule='V1' and fkey=%s", (u0,))
    assert a and a["severity"] == "critical" and a["chain"]
    sc = a["chain"]["scope"]
    assert sc["wheels"] == [w1]
    assert set(sc["check_units"]) == expect_units, (sc["check_units"], expect_units)
    assert set(sc["customers"]) == expect_cust
    assert not set(sc["check_units"]) & by_wheel[sorted(by_wheel)[1]]          # 另一片砂轮的设备不在范围里
    # 每条边都有依据；链接类的依据都能在本体里核到
    for e in a["chain"]["edges"]:
        assert e["basis"]["how"], e
    for e in a["chain"]["edges"]:
        if e["basis"]["how"].startswith("链接 PartSerial.processed") and e["basis"]["seq"]:
            raw = db.one("select payload from bus_message where seq=%s", (e["basis"]["seq"],))
            assert raw["payload"]["data"]["event"] == "cycle_end"

    # 同一片砂轮的第二台也报警 → V2“同批多台”，严重
    u1 = sorted(by_wheel[w1])[1]
    monkeypatch.setattr(TW, "fleet", _fleet(db, red={u0}, yellow={u1}))
    D.run("teach")
    b = db.one("select * from anomaly where rule='V2' and status='open'")
    assert b and b["severity"] == "critical" and b["subject_type"] == "Tool" and b["subject_key"] == w1
    assert set(b["chain"]["scope"]["alarmed"]) == {u0, u1}
    assert set(b["chain"]["scope"]["check_units"]) == by_wheel[w1] - {u0, u1}


def test_impact_of_a_wheel_lists_shafts_and_field_units(plant):
    from hub.ont import chain as CH
    from hub.ont.anomaly import Ctx
    db = plant
    wheel, unit_shaft, _ = _wheels_by_hand(db)
    w = sorted(set(wheel.values()))[0]
    g = CH.for_object(Ctx(db, "teach"), "Tool", w)
    shafts = {n["key"] for n in g["nodes"] if n["type"] == "PartSerial" and n["key"].startswith("SH301")}
    assert shafts == {s for s, x in wheel.items() if x == w}
    fus = {n["key"] for n in g["nodes"] if n["type"] == "FieldUnit"}
    assert fus == {u for u, s in unit_shaft.items() if wheel[s] == w}


# ---------------------------------------------------------------- 故事一：停机 → 工序 → 工单 → 订单 → 客户（实验 7 情景）
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)


@pytest.fixture(scope="module")
def lab7():
    from hub.historian import Historian
    from sim import scenario
    from tests_helpers import make_engine
    db = _fresh("wq_chain_lab7")
    h = Historian(db)
    eng, clock, _ = make_engine(auto=False)
    scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    _sync(db)
    return db


def test_story1_downtime_reaches_orders_and_customers(lab7):
    from hub.ont.anomaly import Detector
    from hub import kpi
    db = lab7
    D = Detector(db)
    D.run("teach", NOW)
    a = db.one("select * from anomaly where rule='P1' and fkey='grd-01'")
    assert a and a["chain"], "GRD-01 停机应开异常并算出链条"
    ch = a["chain"]
    types = {n["type"] for n in ch["nodes"]}
    ov = kpi.overview(db, NOW, "teach")
    grd = next(m for m in ov["machines"] if m["unit"] == "grd-01")
    pending = [j for j in grd["dispatched"] if j["done"] < j["qty"]]
    if pending:
        assert {"OperationTask", "WorkOrder"} <= types
        assert set(ch["scope"]["work_orders"]) == {j["work_order"] for j in pending}
    # 链条里的订单预测与看板“订单与交期”一致
    orders = {o["name"]: o for o in ov["orders"]}
    for n in ch["nodes"]:
        if n["type"] == "SalesOrder" and n["key"] in orders and n["values"].get("预计完成"):
            assert n["values"]["预计完成"] == orders[n["key"]]["projected"]
            assert n["values"]["交期"] == orders[n["key"]]["delivery_date"]
    assert ch["summary"][0].startswith("GRD-01 停机")


def test_quality_chain_hides_teacher_problem_from_students(lab7):
    """质量链条里，老师注入的“质量问题情景”在学生面前换成“原因待查”"""
    from hub.ont import chain as CH
    from hub.ont import api as API
    from hub.ont.anomaly import Ctx
    db = lab7
    db.x("insert into quality_problem (mode, problem, magnitude, injected_at) values ('teach', 'dressing_interval', 2.5, now())")
    parts = [m["data"]["part_serial"] for m in db.messages(["quality.measurement"], mode="teach", order="desc", limit=30)][:3]
    g = CH.chain_quality(Ctx(db, "teach", NOW), parts, "grd-01", "bearing_seat_d35").out()
    assert any(n["type"] == "QualityProblem" for n in g["nodes"])
    stu = API.filter_chain(g, 1)
    assert not any(n["type"] == "QualityProblem" for n in stu["nodes"])
    assert any(n.get("hidden") and n["display"] == "原因待查" for n in stu["nodes"])
    tea = API.filter_chain(g, 3)
    assert any(n["type"] == "QualityProblem" for n in tea["nodes"])


def test_every_open_anomaly_in_lab7_gets_a_chain(lab7):
    """实验 7 情景里开出的每个异常都算出链条，没有出错，且至少连到一个对象"""
    from hub.ont import chain as CH
    from hub.ont.anomaly import Ctx, Detector
    from hub.ont.store import Store
    db = lab7
    Detector(db).run("teach", NOW)
    rows = db.q("select * from anomaly where mode='teach' and status in ('open','ack','doing')")
    assert {r["rule"] for r in rows} >= {"P1", "Q1", "Q2", "W1"}
    c = Ctx(db, "teach", NOW)
    for r in rows:
        ch = CH.for_anomaly(c, r)
        assert not ch.get("error") and len(ch["nodes"]) >= 2 and ch["edges"], (r["rule"], ch)
    for t, k in (("Item", "BRG-6207"), ("SalesOrder", "SAL-ORD-2026-00019"), ("Machine", "grd-01")):
        g = CH.for_object(c, t, k)
        assert len(g["nodes"]) >= 2, (t, k)
    # 对账后，异常也是本体对象，连着它涉及的对象
    from hub.ont import sources as SRC
    B = Store(db).batch()
    SRC.anomalies(B, db, "teach")
    B.flush()
    assert db.one("select count(*) n from ont_link where mode='teach' and type='Anomaly.about'")["n"] >= len(rows)


# ---------------------------------------------------------------- 接口、权限、AI 润色
@pytest.fixture
def client(lab7, monkeypatch):
    from fastapi.testclient import TestClient
    import hub.app as app_mod
    from hub.ai import Assistant

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    monkeypatch.setattr(app_mod.H, "db", lab7)
    monkeypatch.setattr(app_mod.H, "ai", Assistant(lab7, lambda *a: None, NoLLM()))
    c = TestClient(app_mod.app)

    def tok(role, teacher=True):
        return {"X-WQ-Token": app_mod._sign({"name": "王" if teacher else "学生甲", "role": role, "mode": "teach", "teacher": teacher, "exp": 9e12})}
    return c, tok, app_mod


def test_anomaly_api_flow_and_permissions(client, lab7):
    c, tok, app_mod = client
    app_mod.H.ai.detector().run("teach", NOW)
    tea, stu_op, stu_q = tok("manager"), tok("operator", False), tok("quality", False)
    lst = c.get("/api/ont/anomalies", headers=stu_op).json()["anomalies"]
    assert lst and lst[0]["severity"] in ("critical", "warn")
    q = next(a for a in lst if a["rule"] in ("Q1", "Q2"))
    d = c.get("/api/ont/anomalies/{}".format(q["id"]), headers=stu_op).json()
    assert d["chain"]["nodes"] and d["text_rules"] and not d["can_act"]
    assert c.post("/api/ont/anomalies/{}/close".format(q["id"]), json={"text": "x"}, headers=stu_op).status_code == 403
    assert c.post("/api/ont/anomalies/{}/note".format(q["id"]), json={"text": "我看到 Ø35 在往上走"}, headers=stu_op).status_code == 200
    r = c.post("/api/ont/anomalies/{}/ack".format(q["id"]), headers=stu_q).json()
    assert r["status"] == "ack" and [n["kind"] for n in r["notes"]][-2:] == ["note", "ack"]
    assert c.post("/api/ont/anomalies/{}/close".format(q["id"]), json={"text": ""}, headers=stu_q).status_code == 400
    assert c.post("/api/ont/anomalies/{}/close".format(q["id"]), json={"text": "修整砂轮后恢复"}, headers=stu_q).json()["status"] == "closed"
    # 影响面、态势、规则目录
    g = c.get("/api/ont/impact/Machine/grd-01", headers=stu_op).json()
    assert g["nodes"] and g["summary"]
    sit = c.get("/api/ont/situation", headers=stu_op).json()
    assert len(sit["cards"]) == 15 and sum(1 for x in sit["cards"] if x["waiting"]) == 3
    assert any(m["trend"] for x in sit["cards"] for m in x["metrics"])          # 每天记一次，趋势从今天开始有点
    rules = c.get("/api/ont/rules", headers=tea).json()
    assert len(rules["rules"]) == 32 and rules["can_edit"]
    assert c.post("/api/ont/rules/P5", json={"params": {"above": 4}}, headers=stu_op).status_code == 403
    assert c.post("/api/ont/rules/P5", json={"params": {"above": 4}}, headers=tea).status_code == 200
    c.post("/api/ont/rules/P5", json={"params": {"above": 6}}, headers=tea)
    bt = c.post("/api/ont/rules/M1/backtest", json={"days": 2, "step_h": 12}, headers=tea).json()
    assert len(bt["points"]) >= 4 and all(p["error"] is None for p in bt["points"])


def test_narrate_rejects_invented_numbers():
    from hub.ont import narrate as NR
    a = {"title": "GRD-01 停机：换砂轮", "detail": {"text": "预计还要约 45 分钟", "hint": "查看受影响的订单"}}
    ch = {"summary": ["GRD-01 停机，预计还要约 45 分钟", "销售订单 SAL-ORD-2026-00019：晚 1 天"], "nodes": []}

    class Fake:
        name = "fake"

        def __init__(self, text):
            self.text = text

        def available(self):
            return True

        def run(self, *a, **k):
            return self.text, []
    assert NR.narrate(None, a, ch)["by"] == "rules"
    good = NR.narrate(Fake("磨床 GRD-01 换砂轮停机约 45 分钟，订单 SAL-ORD-2026-00019 会晚 1 天，请查看受影响的订单。"), a, ch)
    assert good["by"] == "fake"
    bad = NR.narrate(Fake("GRD-01 停机约 90 分钟，订单会晚 3 天。"), a, ch)
    assert bad["by"] == "rules" and "90" in bad["note"]
