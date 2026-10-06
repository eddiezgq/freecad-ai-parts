# -*- coding: utf-8 -*-
"""第 17 轮 A 期：工厂本体——定义校验、同步与重放一致、数字主线、血缘、别名、权限。"""
import os
import shutil

import pytest
import yaml

import wqbus
from hub.ont import schema as S

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_ont_test"


# ---------------------------------------------------------------- 定义
def test_ontology_loads_and_covers_15_domains():
    o = S.load()
    assert len([d for d in o.domains if d["domain"] != "core"]) == 15      # 15 个业务域 + 厂情中枢自身（异常、行动……）
    assert len(o.types) >= 90
    for t, sp in o.types.items():
        assert sp["maturity"] in S.MATURITY, t
    # 打通数字主线需要的链接都在
    for ft, ln in [("PartSerial", "processed"), ("PartSerial", "installed_in"), ("PartSerial", "became"),
                   ("FieldUnit", "customer"), ("OperationTask", "machine"), ("Machine", "tool")]:
        assert (ft, ln) in o.links, (ft, ln)


def test_ontology_rejects_bad_link_target(tmp_path):
    d = tmp_path / "onto"
    shutil.copytree(S.DIR, d)
    f = d / "07_production.yaml"
    y = yaml.safe_load(f.read_text(encoding="utf-8"))
    first = next(iter(y["types"]))
    y["types"][first].setdefault("links", {})["oops"] = {"to": "NoSuchType", "l": "错"}
    f.write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
    with pytest.raises(S.OntologyError) as e:
        S.load(str(d))
    assert "NoSuchType" in str(e.value)


def test_ontology_rejects_unknown_maturity(tmp_path):
    d = tmp_path / "onto"
    shutil.copytree(S.DIR, d)
    f = d / "12_ehs.yaml"
    y = yaml.safe_load(f.read_text(encoding="utf-8"))
    first = next(iter(y["types"]))
    y["types"][first]["maturity"] = "maybe"
    f.write_text(yaml.safe_dump(y, allow_unicode=True), encoding="utf-8")
    with pytest.raises(S.OntologyError):
        S.load(str(d))


# ---------------------------------------------------------------- 同步（需要数据库）
@pytest.fixture
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_ont_test with (force)")
            c.execute("create database wq_ont_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


def _factory(db, monkeypatch):
    """仿真器加工 10 根 SH-301（经过 grd-01 磨削、检验），消息经 Historian 入库；再跑合一台 WQR-105，孪生按先进先出装上一根合格轴"""
    from hub import twin as TW
    from hub.historian import Historian
    from sim.engine import torque_record
    from tests.test_sim import FakeClock, dispatch_all, run_to_end
    from sim.engine import Engine
    monkeypatch.setattr(TW, "FIELD_MODES", ["teach"])
    holder = {}

    def publish(tp, type_, source, data, corr=None, mode=None):
        msg = wqbus.make(type_, source, data, mode=mode or "teach", corr=corr)
        holder["hist"].handle(tp, msg)
        return msg
    tw = TW.TwinService(db, publish)
    tw.init()
    hist = holder["hist"] = Historian(db, tw.on_message)
    clock = FakeClock()
    eng = Engine(lambda tp, ty, src, data, corr: hist.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)),
                 clock, mode="teach", auto_start=True, seed=3, status_every_s=1e9)
    dispatch_all(eng, wo="WO-ONT-1", qty=10)
    run_to_end(eng, clock)
    rec = torque_record("WQR105-ONT-01", "WO-ONT-A", "WQR-105")
    hist.handle("wq/gearbox/machining/test-01/torque", wqbus.make("test.torque", "sim/test-01", rec, mode="teach"))
    return tw


def _sync(db):
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    s = Sync(db, Store(db))
    s.init()
    return s


def _snapshot(db):
    objs = {(r["type"], r["key"]): r["props"] for r in db.q("select type, key, props from ont_object where mode='teach'")}
    links = {(r["type"], r["src_key"], r["dst_key"]): r["props"] for r in db.q("select * from ont_link where mode='teach'")}
    return objs, links


def test_digital_thread_from_field_unit_to_grinding_wheel(db, monkeypatch):
    _factory(db, monkeypatch)
    s = _sync(db)
    n = s.replay()
    assert n > 50 and s.errors == 0, s.last_error
    one = lambda sql, *a: db.one(sql, a)  # noqa: E731
    # 现场设备 ← 由哪台总成变成
    fu = one("select * from ont_object where mode='teach' and type='FieldUnit' and key='WQR105-ONT-01'")
    assert fu is not None
    asm = one("select * from ont_link where mode='teach' and type='PartSerial.became' and dst_key='WQR105-ONT-01'")
    assert asm["src_key"] == "WQR105-ONT-01"
    # ← 装进去的输出轴
    sh = one("select * from ont_link where mode='teach' and type='PartSerial.installed_in' and dst_key=%s", asm["src_key"])
    assert sh is not None and sh["src_key"].startswith("SH301")
    shaft = sh["src_key"]
    # 输出轴 → 磨削工序（grd-01），带当时的砂轮和剩余寿命
    grind = [r for r in db.q("select * from ont_link where mode='teach' and type='PartSerial.processed' and src_key=%s", (shaft,))
             if r["props"].get("machine") == "grd-01"]
    assert len(grind) == 1
    tool, life = grind[0]["props"]["tool"], grind[0]["props"]["tool_life_pct"]
    assert tool and tool.startswith("grd-01/") and life is not None and 0 < life <= 100
    # 同一片砂轮磨过的其他轴
    same = db.q("select src_key from ont_link where mode='teach' and type='PartSerial.processed' and props->>'tool'=%s", (tool,))
    assert len({r["src_key"] for r in same}) >= 2
    # 砂轮对象本身存在，挂在磨床上
    assert one("select 1 from ont_link where mode='teach' and type='Machine.tool' and src_key='grd-01' and dst_key=%s", tool)
    # 检验数据挂在这根轴上
    assert one("select count(*) as n from ont_link where mode='teach' and type='Measurement.part' and dst_key=%s", shaft)["n"] >= 3


def test_incremental_sync_equals_replay(db, monkeypatch):
    _factory(db, monkeypatch)
    s = _sync(db)
    # 增量：小批量一段一段追上（模拟后台线程）
    import hub.ont.sync as SY
    monkeypatch.setattr(SY, "BATCH", 37)
    s.catch_up()
    s.reconcile()
    live = _snapshot(db)
    s2 = _sync(db)
    s2.replay()
    again = _snapshot(db)
    assert set(live[0]) == set(again[0])
    assert live[0] == again[0]
    assert live[1] == again[1]
    # 重启后从保存的游标和上下文接着走，不重复
    s3 = _sync(db)
    assert s3.step(lag="0 seconds") == 0
    assert s3.ctx.tool == s2.ctx.tool


def test_lineage_points_to_the_source_message(db, monkeypatch):
    """任取 20 个属性值，都能追到原始消息且数值一致"""
    _factory(db, monkeypatch)
    s = _sync(db)
    s.replay()
    direct = {"Measurement": {"value_mm": "value_mm", "result": "result", "characteristic": "characteristic", "part": "part_serial"},
              "PartSerial": {"item": "item", "work_order": "work_order"},
              "OperationTask": {"operation": "operation", "op_index": "op_index"}}
    checked = 0
    for t, props in direct.items():
        for o in db.q("select * from ont_object where mode='teach' and type=%s order by key limit 3", (t,)):
            for p, field in props.items():
                seq = o["prop_src"].get(p)
                if seq is None or p not in o["props"]:
                    continue
                raw = db.one("select payload from bus_message where seq=%s", (seq,))
                assert raw["payload"]["data"].get(field) == o["props"][p], (t, o["key"], p)
                checked += 1
    assert checked >= 20, checked


def test_aliases_and_api(db, monkeypatch):
    from fastapi.testclient import TestClient
    import hub.app as app_mod
    _factory(db, monkeypatch)
    s = _sync(db)
    s.replay()
    monkeypatch.setattr(app_mod.H, "db", db)
    monkeypatch.setattr(app_mod.H, "ont", s, raising=False)
    c = TestClient(app_mod.app)

    def tok(role, mode="teach", teacher=True):
        return {"X-WQ-Token": app_mod._sign({"name": "t", "role": role, "mode": mode, "teacher": teacher, "exp": 9e12})}
    h = tok("manager")
    for q in ("6207", "A-BRG-DG/6207", "BRG-6207"):
        r = c.get("/api/ont/search", params={"q": q}, headers=h).json()["results"]
        assert r and r[0]["type"] == "Item" and r[0]["key"] == "BRG-6207", (q, r)
    # 360：链接分组、血缘
    shaft = db.one("select src_key from ont_link where mode='teach' and type='PartSerial.installed_in'")["src_key"]
    o = c.get("/api/ont/obj/PartSerial/" + shaft, headers=h).json()
    assert any(g["link"] == "PartSerial.processed" for g in o["links"])
    assert any(g["link"] == "PartSerial.installed_in" for g in o["links"])
    g = c.get("/api/ont/obj/PartSerial/{}/graph".format(shaft), params={"depth": 2}, headers=h).json()
    assert any(n["type"] == "FieldUnit" for n in g["nodes"]) and any(n["type"] == "OperationTask" for n in g["nodes"])
    tl = c.get("/api/ont/obj/PartSerial/{}/timeline".format(shaft), headers=h).json()["events"]
    assert any(e["kind"] == "processed" for e in tl)
    seq = next(e["seq"] for e in tl if e["seq"])
    assert c.get("/api/ont/lineage/{}".format(seq), headers=h).json()["seq"] == seq
    # 对象集：同一片砂轮磨过的轴
    tool = next(i["props"]["tool"] for gg in o["links"] if gg["link"] == "PartSerial.processed" for i in gg["items"]
                if (i["props"] or {}).get("machine") == "grd-01")
    q = c.post("/api/ont/query", json={"type": "Tool", "where": [{"prop": "machine", "op": "=", "value": "grd-01"}]}, headers=h).json()
    assert tool in [x["key"] for x in q["objects"]]
    types = c.get("/api/ont/types", headers=h).json()
    assert len(types["domains"]) == 16 and types["level"] == 3
    assert c.get("/api/ont/health", headers=h).json()["errors"] == 0


def test_sensitivity_hides_restricted_types(db, monkeypatch):
    from fastapi.testclient import TestClient
    import hub.app as app_mod
    s = _sync(db)
    monkeypatch.setattr(app_mod.H, "db", db)
    monkeypatch.setattr(app_mod.H, "ont", s, raising=False)
    onto = S.get()
    secret = [t for t, sp in onto.types.items() if int(sp.get("sensitivity", 0) or 0) >= 2]
    assert secret, "本体里应该有部门级/受限级的类型（如人员、质量问题）"
    t = secret[0]
    from hub.ont.store import Store
    B = Store(db).batch()
    B.obj("teach", t, "X-1", {})
    B.flush()
    c = TestClient(app_mod.app)
    stu = {"X-WQ-Token": app_mod._sign({"name": "s", "role": "operator", "mode": "teach", "teacher": False, "exp": 9e12})}
    tea = {"X-WQ-Token": app_mod._sign({"name": "t", "role": "manager", "mode": "teach", "teacher": True, "exp": 9e12})}
    assert c.get("/api/ont/obj/{}/X-1".format(t), headers=stu).status_code == 404
    assert c.get("/api/ont/obj/{}/X-1".format(t), headers=tea).status_code == 200
    hidden = {x["name"]: x["hidden"] for d in c.get("/api/ont/types", headers=stu).json()["domains"] for x in d["types"]}
    assert hidden[t] is True
    assert c.post("/api/ont/replay", headers=stu).status_code == 403


# ---------------------------------------------------------------- 本地闭环走不到的几类对象：映射单独核对
class _FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def one(self, sql, args=None):
        if "to_regclass" in sql:
            return {"ok": False}                # 没有异常表
        r = self.q(sql, args)
        return r[0] if r else None

    def q(self, sql, args=None):
        for t, rows in self.rows.items():
            if " from {} ".format(t) in sql + " " or sql.rstrip().endswith("from " + t):
                return rows
        return []


class _MemStore:
    def __init__(self):
        self.onto = S.get()
        self.cache = {}

    def load(self, mode, t, k):
        return self.cache.get((mode, t, k))

    def get(self, mode, t, k):
        o = self.load(mode, t, k)
        return None if o is None else o["props"]


def test_mappers_for_types_outside_the_lab7_loop(monkeypatch):
    import datetime as dt
    from hub import twin as TW
    from hub.ont import mappers as MP
    from hub.ont import sources as SRC
    from hub.ont.store import Batch
    monkeypatch.setattr(TW, "fleet", lambda db, mode: [])
    now = dt.datetime(2026, 10, 5, 8, 0, tzinfo=dt.timezone.utc)
    st = _MemStore()
    B = Batch(st)
    db = _FakeDB({
        "process_submission": [{"id": "PS-1", "item": "SH-301", "status": "approved", "revision": 2, "author": "工艺员",
                                "plan": {"ops": 7}, "ts": now}],
        "plc_run": [{"id": "PLC-1", "unit": "grd-01", "created_by": "学生", "summary": {"n": 12}, "alarms": [1], "status": "done"}],
        "twin_event": [{"id": 5, "serial": "WQR105-X-01", "ts": now, "day": dt.date(2026, 10, 5), "title": "更换中间轴轴承",
                        "status": "open", "detail": {"issue": "ISS-0001", "action": "换轴承"}}],
    })
    SRC.tables(B, db, "teach")
    for name, d in [("PREC-0001", "Purchase Receipt"), ("DN-0001", "Delivery Note")]:
        MP.erp_doc(B, "teach", 1, now.isoformat(), {"data": {"doctype": d, "name": name, "action": "submit", "status": "Completed"}}, MP.Ctx())
    got = {t for (_, t, _) in st.cache}
    for t in ("ProcessPlan", "PlcRun", "ServiceOrder", "PurchaseReceipt", "DeliveryNote"):
        assert t in got, t
    assert ("teach", "Item.process_plan", "Item", "SH-301", "ProcessPlan", "PS-1") in B.links
    assert ("teach", "ServiceOrder.unit", "ServiceOrder", "ISS-0001", "FieldUnit", "WQR105-X-01") in B.links
    assert ("teach", "PlcRun.machine", "PlcRun", "PLC-1", "Machine", "grd-01") in B.links
