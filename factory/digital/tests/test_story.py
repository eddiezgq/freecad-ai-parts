# -*- coding: utf-8 -*-
"""第 19 轮：两周情景——剧本、按幕执行（复用各领域的注入）、核对异常、后果连上（动作费用记主线订单、空转电分摊、逾期的是订单自己的发票）、
钱的因果链、复盘、自动收尾、快进；实验 23（分组、每幕的小组决定、比对模式、全组同分、复盘）。"""
import datetime as dt
import json
import os
import re

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "web", "src")


class FakeMes:
    def __init__(self):
        self.sent = []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(dict({"unit": unit, "command": command, "mode": mode, "work_order": work_order}, **extra))

    def release(self, name, mode, user, units=None):
        from sim.engine import OP_UNITS, routing_for
        out = [{"operation": op, "unit": OP_UNITS[op][0]} for op, _ in routing_for("SH-301")]
        self.sent.append({"release": name, "command": "release", "unit": None})
        return out


@pytest.fixture(scope="module")
def env():
    pytest.importorskip("psycopg")
    from hub.ont import evals as EV
    try:
        H, eng = EV.sandbox(DSN, name="wq_story_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    H.db.x("delete from anomaly where mode='teach'")         # 情景开始时异常是清空的（reset_teach）；沙盒里预先注入的让它们重新出现
    return H, eng


def _erp(db, doctype, name, mode="teach", **data):
    import wqbus
    msg = wqbus.make("erp.doc", "bridge", dict({"doctype": doctype, "name": name, "action": "updated"}, **data), mode=mode,
                     ts=dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"))
    db.insert_message("wq/gearbox/office/erp/doc", msg)


def _execute(db, pid, created):
    db.x("update ai_proposal set status='executed', result=%s where proposal_id=%s", (json.dumps({"created": created}), pid))


def _detect(H):
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))


def _beat(st, n):
    return next(b for b in st["beats"] if b["n"] == n)


# ---------------------------------------------------------------- 剧本
def test_script_is_consistent():
    """八幕：每一步都认得、每个预计的规则在规则目录里、负责的角色学生能用、“去看”的页面都有路由"""
    import yaml
    from hub import story as ST
    sc = ST.scenario("two_weeks")
    assert [b["n"] for b in sc["beats"]] == list(range(1, 9)) and sc["qty"] == 20 and sc["due_days"] == 12
    rules = set()
    for f in os.listdir(os.path.join(os.path.dirname(HERE), "ontology", "rules")):
        d = yaml.safe_load(open(os.path.join(os.path.dirname(HERE), "ontology", "rules", f), encoding="utf-8")) or {}
        rules |= set((d.get("rules") or {}).keys())
    app = open(os.path.join(os.path.dirname(HERE), "hub", "app.py"), encoding="utf-8").read()
    STUDENT_ROLES = re.findall(r'"(\w+)"', re.search(r"^STUDENT_ROLES = \(([^)]*)\)", app, re.M).group(1))
    routes = open(os.path.join(WEB, "main.js"), encoding="utf-8").read()
    doms = set()
    for b in sc["beats"]:
        assert all(s["step"] in ST.STEPS for s in b["do"]), b["n"]
        assert all(e.get("rule") in rules or e.get("check") == "order_released" for e in b["expect"]), b["n"]
        assert b["roles"] and set(b["roles"]) <= set(STUDENT_ROLES), b["n"]
        for lk in b["look"]:
            assert "'{}'".format(lk["to"]) in routes, lk["to"]
        doms.add(b["domain"])
    assert {"customer", "supply", "people", "ehs", "maintenance", "energy", "finance"} <= doms           # 七个领域都出场
    assert sc["beats"][7]["wait"] == "order_done"


# ---------------------------------------------------------------- 情景主线
def test_story_flow(env):
    from factory import data as F
    from hub import finance as FN
    from hub import story as ST
    H, _ = env
    db = H.db
    st = ST.start(H, "王老师", speed=30)
    assert st["run"]["status"] == "ready" and st["next"]["ok"] and all(b["status"] == "todo" for b in st["beats"])
    assert {"unit": "sim", "command": "set_speed", "mode": "teach", "work_order": None, "speed": 30.0} in H.mes.sent
    with pytest.raises(ValueError):
        ST.next_beat(H, "王老师", 3)                                    # 一幕一幕来

    # 第 1 幕：下急单 → 提议（自动确认）→ ERPNext 回来 → 下达车间
    st = ST.next_beat(H, "王老师")
    b1 = _beat(st, 1)
    assert b1["status"] == "waiting" and "40" in b1["note"] and b1["pending"]
    pid = ST.run(db)["state"]["order_pid"]
    p = db.one("select * from ai_proposal where proposal_id=%s", (pid,))
    assert p["action"] == "create_order_and_plan" and p["status"] == "confirmed" and p["preview"]["sales_order"]["qty"] == 20
    assert p["preview"]["sales_order"]["customer"] == F.CUSTOMERS[2]
    assert not ST.can_next(H, ST.run(db), ST.scenario())[0]            # 等订单写进 ERPNext
    SO, WO = "SAL-ORD-2026-00131", "MFG-WO-2026-00131"
    _execute(db, pid, [["Sales Order", SO], ["Work Order", WO]])
    _erp(db, "Sales Order", SO, customer=F.CUSTOMERS[2], docstatus=1, status="To Deliver and Bill", per_billed=0,
         delivery_date=(dt.date.today() + dt.timedelta(days=12)).isoformat(), transaction_date=dt.date.today().isoformat(),
         items=[{"item_code": "WQR-105", "qty": 20, "rate": 1650}])
    _erp(db, "Work Order", WO, production_item="SH-301", qty=20, produced_qty=0, status="In Process", docstatus=1, sales_order=SO)
    st = ST.tick(H)
    assert st["run"]["so"] == SO and _beat(st, 1)["status"] == "ok" and any(x.get("release") == WO for x in H.mes.sent)
    assert sum(1 for x in H.mes.sent if x["command"] == "start" and x["work_order"] == WO) == 7

    # 第 2 幕：采购单（这一批到货时不合格）；缺料 W1
    st = ST.next_beat(H, "王老师")
    lid = ST.run(db)["state"]["lot_id"]
    assert db.one("select status from lot where id=%s", (lid,))["status"] == "ordered"
    from hub import supply as SP
    assert any(v.get("bad") for v in SP._state(db, "teach")["inject"].values())       # 这家供应商下一批不合格（发货时定）
    with pytest.raises(ValueError):                                    # 采购单还没进 ERPNext，第 3 幕演不了
        ST.next_beat(H, "王老师")
    db.x("update lot set status='transit', truth_bad=true, po='PUR-ORD-2026-00131' where id=%s", (lid,))
    _detect(H)
    st = ST.tick(H)
    b2 = _beat(st, 2)
    assert b2["status"] == "ok" and b2["seen"][0]["rule"] == "W1" and "BRG-6207" in b2["seen"][0]["title"]

    # 第 3 幕：到货、来料检验不合格 → W3
    ST.next_beat(H, "王老师")
    assert db.one("select status from lot where id=%s", (lid,))["status"] == "rejected"
    _detect(H)
    b3 = _beat(ST.tick(H), 3)
    assert b3["status"] == "ok" and b3["seen"][0]["rule"] == "W3"

    # 第 4 幕：磨床那一班的人请假 → H2
    st = ST.next_beat(H, "王老师")
    assert "GRD-01" in _beat(st, 4)["note"]
    _detect(H)
    # 同一件事情景开始前就开着（前面的实验让同一个人同一班请过假）：first_seen 是以前的，只要情景里规则又看到了也算
    db.x("update anomaly set first_seen = first_seen - interval '3 days', last_seen = last_seen - interval '3 days' where mode='teach' and rule='H2'")
    assert not _beat(ST.tick(H), 4)["seen"]
    _detect(H)
    assert _beat(ST.tick(H), 4)["seen"][0]["rule"] == "H2"

    # 第 5 幕：重大隐患 → E1
    ST.next_beat(H, "王老师")
    _detect(H)
    assert _beat(ST.tick(H), 5)["seen"][0]["rule"] == "E1"

    # 第 6 幕：保养逾期（运行小时 = 周期 × 1.4，发给车间）
    ST.next_beat(H, "王老师")
    assert any(x["command"] == "set_run_h" and x["unit"] == "grd-01" for x in H.mes.sent)

    # 第 7 幕：带锯床忘关 + 峰时开炉（情景的问题不让模拟器自动修好）
    ST.next_beat(H, "王老师")
    from hub import energy as EN
    fs = EN._state(db, "teach")["faults"]
    assert fs["forgot:saw-01"]["lab"] and fs["ht_peak"]["lab"]
    db.x("insert into anomaly (mode, rule, fkey, domain, subject_type, subject_key, severity, role, title, detail, first_seen, last_seen) "
         "values ('teach','N2','saw-01','energy','Machine','saw-01','info','planner','SAW-01 空转 12 小时','{}'::jsonb, now(), now())")
    assert _beat(ST.tick(H), 7)["seen"][0]["rule"] == "N2"

    # 第 8 幕要等订单做完
    r = ST.run(db)
    db.x("update story_beat set ok=true where run_id=%s", (r["id"],))
    ok, why = ST.can_next(H, r, ST.scenario())
    assert not ok and "等车间做完" in why

    # 后果连上：因第 2 幕的异常采纳的动作，费用全记主线订单（不分给别的订单）
    from hub.ont import actions as AC
    w1 = _beat(ST.state(db), 2)["seen"][0]["id"]
    PL = {"name": "学生计划员", "role": "planner", "teacher": False, "mode": "teach"}
    aid = AC.create(db, "teach", PL, "urgent_purchase", {"item": "BRG-6207", "qty": 40, "arrive": dt.date.today().isoformat()}, None, w1,
                    {"cost_total": 240.0, "sales_orders": [{"name": "SAL-ORD-2026-00020"}]})
    db.x("update action set status='done' where id=%s", (aid,))
    assert ST.story_anomalies(db, "teach")[w1] == SO

    # 订单做完（车间最后一道工序）→ 开票 → 第 8 幕：这张发票逾期
    import wqbus
    for i in range(20):
        db.insert_message("wq/gearbox/machining/qc-01/event", wqbus.make("machine.event", "sim", {
            "event": "cycle_end", "work_order": WO, "operation": "零件检验 Part inspection", "op_index": 6, "n_ops": 7, "item": "SH-301",
            "part_serial": "SH301-131-{:02d}".format(i), "cycle_time_s": 360, "std_time_s": 360,
            "factory_ts": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")}, corr=WO))
    db.insert_message("wq/gearbox/machining/qc-01/event", wqbus.make("machine.event", "sim", {
        "event": "op_complete", "work_order": WO, "operation": "零件检验 Part inspection", "last_op": True}, corr=WO))
    st = ST.state(db)
    assert st["order"]["done"] and st["order"]["parts"] == 20 and st["next"]["ok"]
    st = ST.next_beat(H, "王老师")
    inv = db.one("select * from invoice where mode='teach' and kind='ar' and ref=%s", (SO,))
    assert inv["no_pay"] and inv["amount"] == 20 * 1650 and FN.overdue_days("teach", inv) >= 14.9
    _execute(db, inv["proposal_id"], [["Sales Invoice", "ACC-SINV-2026-00131"]])
    FN.sync(db, "teach")
    _detect(H)
    st = ST.tick(H)
    b8 = _beat(st, 8)
    assert b8["status"] == "ok" and b8["seen"][0]["rule"] == "F2"

    # 毛利：动作费用全记 SO；别的订单不再分这笔；多了空转电分摊
    m = FN.margin(db, "teach", SO, store=False)
    acts = next(x for x in m["lines"] if x["key"] == "actions")
    assert any(a["id"] == aid and a["usd"] == 240.0 for a in acts["actions"])
    assert "idle" in {x["key"] for x in m["lines"]}
    other = FN.margin(db, "teach", "SAL-ORD-2026-00019", store=False)
    assert not any(a["id"] == aid for a in next(x for x in other["lines"] if x["key"] == "actions")["actions"])

    # 钱的因果链：应收逾期 → 发票 → 订单 → 动作 → 源头异常（缺料）
    a = db.one("select * from anomaly where id=%s", (b8["seen"][0]["id"],))
    assert a["detail"]["values"]["sales_order"] == SO
    from hub.ont.anomaly import Ctx
    from hub.ont.chain import for_anomaly
    g = for_anomaly(Ctx(db, "teach", dt.datetime.now(dt.timezone.utc)), a)
    assert g["kind"] == "money" and any(n["type"] == "Anomaly" and n["values"].get("规则") == "W1" for n in g["nodes"])
    assert any(e["label"] == "开票自" for e in g["edges"])

    # 复盘
    rv = ST.review(H)
    assert rv["sales_order"] == SO and rv["invoice"]["doc"] == "ACC-SINV-2026-00131"
    assert next(b for b in rv["beats"] if b["n"] == 2)["cost"] == 240.0 and rv["top_beat"] == 2
    assert any(n["type"] == "Anomaly" for n in rv["chain"]["nodes"]) and "最早的源头：第 2 幕" in " ".join(rv["chain"]["summary"])
    assert ST.next_beat.__name__ and not ST.state(db)["next"]["ok"]           # 八幕演完


def test_wrapup_fast_forward_and_end(env):
    from hub import ehs as EH
    from hub import story as ST
    H, _ = env
    db = H.db
    r = ST.run(db)
    assert r is not None
    iss = db.one("select issue_id from story_beat b, jsonb_to_record(b.injected->'hazard') as x(issue_id bigint) where run_id=%s and beat_no=5", (r["id"],))
    iid = iss["issue_id"]
    db.x("insert into work_permit (mode, kind, unit, status, minutes, delay_minutes, issue_id, requested_by) values ('teach','loto','grd-01','active',60,0,%s,'学生安全员')",
         (iid,))
    assert ST._wrapup(H, ST.run(db)) == []                              # 第一次看到：记下工厂时间
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).isoformat()
    st = ST.run(db)["state"]
    ST._patch(db, r["id"], {"wrap_seen": {k: past for k in st["wrap_seen"]}})
    done = ST._wrapup(H, ST.run(db))
    assert done and "SI-{:05d}".format(iid) in done[0]
    assert db.one("select status from safety_issue where id=%s", (iid,))["status"] == "closed"
    assert ST.state(db)["run"]["wrap_log"]
    assert EH is not None
    ST.fast_forward(H, True)
    assert ST.run(db)["state"]["ff"] and H.mes.sent[-1]["speed"] == 300.0
    ST.fast_forward(H, False)
    assert H.mes.sent[-1]["speed"] == 30.0
    st = ST.set_auto(db, True, 20)
    assert st["run"]["auto"] and st["run"]["dwell_s"] == 20
    st = ST.end(db, "王老师")
    assert st["run"]["status"] == "ended" and ST.run(db) is None and ST.last_run(db)["id"] == r["id"]


def test_lab23(env):
    from hub import lab23 as L
    from hub import story as ST
    H, _ = env
    db = H.db
    r = ST.last_run(db)
    db.x("update story_run set status='ready', ended_at=null where id=%s", (r["id"],))
    P = {"name": "甲计划员", "role": "planner", "teacher": False, "mode": "teach"}
    Q = {"name": "甲质量", "role": "quality", "teacher": False, "mode": "teach"}
    with pytest.raises(ValueError):
        L.decide(H, P, 2, "x", "理由理由理由理由理由理由理由理由")      # 还没登记
    assert L.register(db, P["name"], "第一组", "planner")["score"] == 5
    L.register(db, Q["name"], "第一组", "quality")
    assert {m["user"] for m in L.status(db, P["name"])["members"]} == {"甲计划员", "甲质量"}
    w1 = L.beat_anomaly(db, r["id"], 2)
    assert L.locked(db, P, w1["id"]) and L.locked(db, P) and not L.locked(db, TEA)

    def fake_options(u, aid, snapshot_id=0):
        return {"options": [{"kind": "none", "label": "不处理（对照）", "recommended": False},
                            {"kind": "urgent_purchase", "label": "紧急采购", "recommended": True}]}, None, {}, True
    H.anomaly_options = fake_options
    with pytest.raises(PermissionError):
        L.decide(H, P, 4, "none", "理由要写满十五个字理由要写满十五个字")      # 第 4 幕该班组长
    with pytest.raises(ValueError):
        L.decide(H, P, 2, "urgent_purchase", "太短")
    L.decide(H, P, 2, "urgent_purchase", "加急多花 $240，但交期不晚，风险小")
    assert not L.locked(db, P, w1["id"]) and L.locked(db, P)            # 第 2 幕交了，别的幕还锁着
    with pytest.raises(ValueError):
        L.decide(H, P, 2, "none", "再交一次再交一次再交一次再交一次")
    db.x("update lab23_decision set at = (select executed_at from story_beat where run_id=%s and beat_no=2) where beat_no=2", (r["id"],))
    st = L.check(db, Q["name"])                                         # 全组同分
    t2 = next(t for t in st["tasks"] if t["id"] == "l23_t2")
    assert t2["score"] == round(25 / 7) and next(t for t in L.check(db, P["name"])["tasks"] if t["id"] == "l23_t2")["score"] == t2["score"]
    aid = db.one("select id from action where anomaly_id=%s order by id limit 1", (w1["id"],))["id"]
    db.x("update action set initiator=%s where id=%s", (P["name"], aid))
    t3 = next(t for t in L.check(db, Q["name"])["tasks"] if t["id"] == "l23_t3")
    assert t3["score"] == 1                                             # 第 2 幕执行了：10 × 1/7
    rv = ST.review(H)
    m = rv["margin"]
    acts = next(x["usd"] for x in m["lines"] if x["key"] == "actions")
    r4 = L.answer(H, P["name"], "l23_t4", {"margin_pct": round(m["margin_pct"] * 100, 1), "top_beat": rv["top_beat"], "actions_usd": acts})
    assert r4["score"] == 20
    st = L.status(db, P["name"])
    assert st["of"] == 60 and st["report_points"] == 40 and len(st["beats"]) == 8
    assert any(c["team"] == "第一组" for c in L.class_view(db))


def test_labs_catalogue(env):
    from hub import labs_api as LA
    H, _ = env
    labs = LA.catalogue(H.db, "甲计划员")
    assert [x["no"] for x in labs] == [7, 15, 16, 17, 18, 19, 20, 21, 22, 23]
    l23 = labs[-1]
    assert l23["of"] == 60 and l23["score"] >= 25 and l23["team"] and l23["guide"] == "/api/cae/lab23/guide.docx"
    assert re.match(r"/lab\d+|/teach", labs[0]["path"])
