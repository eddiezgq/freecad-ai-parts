# -*- coding: utf-8 -*-
"""第 18 轮 E5：供应链深化——供应商档案与备选、采购单 → 发货 → 到货 → 来料检验（抽样、判定）→ 入库 / 不合格；
退货、让步接收、开发备选；批次用料与追溯；W3 来料不合格的四个方案；态势与报告；AI 代理三个新工具；实验 20 自动评分。"""
import datetime as dt
import os
import random

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
PLN = {"name": "学生计划", "role": "planner", "teacher": False, "mode": "teach"}
QA = {"name": "学生质量", "role": "quality", "teacher": False, "mode": "teach"}
OPR = {"name": "学生操作工", "role": "operator", "teacher": False, "mode": "teach"}
BRG = "示例·五大湖轴承 Great Lakes Bearing (Demo)"
STEEL = "示例·中西部钢材 Midwest Steel (Demo)"
CAST = "示例·东岳铸造 Dongyue Castings (Demo)"


class FakeMes:
    def __init__(self):
        self.sent = []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(dict({"unit": unit, "command": command, "mode": mode}, **extra))


@pytest.fixture(scope="module")
def env():
    pytest.importorskip("psycopg")
    import wqbus
    from hub.historian import Historian
    from hub.ont import evals as EV
    try:
        H, eng = EV.sandbox(DSN, name="wq_supply_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    H.hist = Historian(H.db)
    H.pub = lambda tp, ty, src, data, corr=None: H.hist.handle(tp, wqbus.make(ty, src, data, corr=corr))
    return H, eng


def _po(H, sup, item, qty, po="PUR-ORD-T-0001"):
    """下单并假装桥接已经在 ERPNext 建好采购单（沙盘里没有桥接）"""
    from hub import supply as SP
    r = SP.place_po(H, "teach", sup, [{"item_code": item, "qty": qty}], "王老师")
    H.db.x("update lot set po=%s where id = any(%s)", (po, r["lots"]))
    return r["lots"][0]


def _bad_lot(H, item="BRG-6207", qty=40):
    """一批到货、抽检不合格的轴承"""
    from hub import supply as SP
    lid = _po(H, BRG, item, qty, "PUR-ORD-T-0{}".format(qty))
    H.db.x("update lot set status='transit', lot=%s, truth_bad=true where id=%s", ("L261002-{:04d}".format(lid), lid))
    SP.arrive(H.db, "teach", lid, "x")
    SP.inspect(H, "teach", lid, False, "学生质量")
    return lid


# ---------------------------------------------------------------- 供应商
def test_profiles_and_single_source(env):
    from hub import supply as SP
    H, _ = env
    ps = SP.profiles(H.db, "teach")
    assert len(ps) == 10 and sum(1 for p in ps if p["role"] == "alt") == 4
    assert {p["cat"] for p in ps if p["role"] == "alt" and not p["active"]} == {"castings", "forgings"}
    assert {x["cat"] for x in SP.single_source(H.db, "teach")} == {"castings", "forgings", "hardware", "lubricant"}
    with pytest.raises(ValueError):
        SP.place_po(H, "teach", SP.ALT["castings"][0], [{"item_code": "RM-HT200-BASE", "qty": 4}], "x")      # 还没开发
    with pytest.raises(ValueError):
        SP.place_po(H, "teach", BRG, [{"item_code": "RM-45-D50", "qty": 4}], "x")                           # 轴承厂不卖钢材
    assert SP.tco(8, 1.0, 0.9, 0.85) == round(8 + 0.15 * 4 + 0.1 * 3, 3)


def test_supplier_sim_statistics():
    """模拟器按各家的准时率晚到：东岳铸造大约一半晚，钢材很少晚（固定种子）"""
    from hub import supply as SP
    rng = random.Random(3)
    late = {k: sum(1 for _ in range(400) if rng.random() > SP.SIM_P[k][0]) / 400 for k in ("castings", "steel")}
    assert 0.45 < late["castings"] < 0.65 and late["steel"] < 0.1


# ---------------------------------------------------------------- 发货、到货、检验
def test_ship_arrive_and_inspect_steel(env):
    from hub import supply as SP
    H, _ = env
    db = H.db
    SP.set_enabled(db, "teach", False)
    lid = _po(H, STEEL, "RM-45-D50", 500, "PUR-ORD-T-0002")
    now = dt.datetime.now(dt.timezone.utc)
    SP.tick(H, "teach", now=now)
    x = db.one("select * from lot where id=%s", (lid,))
    assert x["status"] == "transit" and x["lot"] and x["late_days"] == 0 and not x["truth_bad"]           # 模拟器关：准时、不出问题
    SP.tick(H, "teach", now=now + dt.timedelta(seconds=SP.DAY_S * 6))
    assert db.one("select status from lot where id=%s", (lid,))["status"] == "arrived"
    r = SP.inspect(H, "teach", lid, False, "学生质量")                                                    # 钢材没有检验模板：直接收货
    x = db.one("select * from lot where id=%s", (lid,))
    assert r["status"] == "accepted" and float(x["qty_left"]) == 500
    pv = db.one("select preview from ai_proposal where proposal_id=%s", (r["proposal_id"],))["preview"]
    assert pv["purchase_order"] == "PUR-ORD-T-0002" and pv["accept"] and not pv["inspect"]
    with pytest.raises(ValueError):
        SP.inspect(H, "teach", lid, True, "x")


def test_sample_judge_and_reject(env):
    from hub import supply as SP
    H, _ = env
    db = H.db
    x = db.one("select * from lot where mode='teach' and status='rejected' order by id limit 1")          # 沙盘情景里那一批不合格的轴承
    sm = SP.sample(db, "teach", x["id"])
    assert sm["template"] == "进货检验-轴承" and sm["sample_size"] == 8 and len(SP.judge(sm)) >= 2
    assert sm == SP.sample(db, "teach", x["id"])                                                          # 同一批抽样数据固定
    pv = db.one("select preview from ai_proposal where proposal_id=%s", (x["receipt_pid"],))["preview"]
    assert pv["status"] == "Rejected" and not pv["accept"] and pv["inspect"] and any(not r["ok"] for r in pv["readings"])


def test_simulator_auto_ship_inspect_return(env):
    from hub import supply as SP
    H, _ = env
    db = H.db
    SP.set_enabled(db, "teach", True)
    st = SP._state(db, "teach")
    st["inject"] = {BRG: {"bad": True, "late_days": 2}}
    SP._save_state(db, "teach", st)
    lid = _po(H, BRG, "BRG-6206", 20, "PUR-ORD-T-0003")
    now = dt.datetime.now(dt.timezone.utc)
    SP.tick(H, "teach", now=now)
    x = db.one("select * from lot where id=%s", (lid,))
    assert x["truth_bad"] and x["late_days"] == 2
    t1 = now + dt.timedelta(seconds=SP.DAY_S * 10)
    got = SP.tick(H, "teach", now=t1)                                                         # 到货
    assert lid in got["arrived"] and not got["inspected"]
    got = SP.tick(H, "teach", now=t1 + dt.timedelta(seconds=SP.ARRIVE_AUTO_S + 5))           # 3 分钟没人检验：质检员（模拟器）检验
    assert lid in got["inspected"] and db.one("select status from lot where id=%s", (lid,))["status"] == "rejected"
    db.x("update lot set arrived_at = now() - interval '20 minutes' where id=%s", (lid,))
    got = SP.tick(H, "teach", now=dt.datetime.now(dt.timezone.utc))
    assert lid in got["returned"]
    re = db.one("select * from lot where mode='teach' and note like %s order by id desc limit 1", ("%退货%",))
    assert re["status"] == "ordered" and re["item"] == "BRG-6206"                                       # 供应商补发


def test_mr_auto_po(env):
    import wqbus
    from hub import supply as SP
    H, _ = env
    db = H.db
    SP.tick(H, "teach")                                                                                  # 第一次：以前的请购单不补
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
    H.hist.handle("wq/gearbox/office/erp/material_request", wqbus.make("erp.doc", "erpnext", {
        "doctype": "Material Request", "name": "MAT-MR-T-0009", "action": "submitted", "docstatus": 1, "status": "Pending",
        "items": [{"item_code": "SEAL-20", "qty": 50, "name": "r1"}]}, ts=old.isoformat()))
    got = SP.tick(H, "teach")
    assert got["pos"]
    x = db.one("select * from lot where mode='teach' and item='SEAL-20' order by id desc limit 1")
    assert x["supplier"].startswith("示例·先锋") and float(x["qty"]) == 50
    assert not SP.tick(H, "teach")["pos"]


# ---------------------------------------------------------------- 批次用料与追溯
def test_batch_use_fifo_and_trace(env):
    from hub import supply as SP
    H, _ = env
    db = H.db
    steel = db.one("select * from lot where mode='teach' and item='RM-45-D50' and status='accepted' order by id limit 1")
    st = SP._state(db, "teach")
    st["use_seq"] = SP._last_seq(db, "teach")
    SP._save_state(db, "teach", st)
    for i in range(3):
        H.pub("wq/gearbox/machining/saw-01/event", "machine.event", "sim/saw-01",
              {"event": "cycle_start", "work_order": "MFG-WO-T-1", "operation": "下料 Sawing", "op_index": 0, "n_ops": 8, "item": "SH-301",
               "part_serial": "SH301-T-{:02d}".format(i), "std_time_s": 180})
    assert SP.scan_use(db, "teach") == 3
    left = float(db.one("select qty_left from lot where id=%s", (steel["id"],))["qty_left"])
    assert abs(left - (500 - 3 * 2.8)) < 1e-6
    t = SP.trace(db, "teach", lot=steel["lot"])
    assert t["parts"] == ["SH301-T-00", "SH301-T-01", "SH301-T-02"] and t["work_orders"] == ["MFG-WO-T-1"]
    b = SP.trace(db, "teach", serial="SH301-T-01")
    assert [x["lot"] for x in b["lots"]] == [steel["lot"]] and b["lots"][0]["supplier"] == STEEL
    SP.mark_suspect(db, "teach", steel["id"], "王老师", "钢材化学成分复验不合格")
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    a = db.one("select * from anomaly where mode='teach' and rule='W7' and fkey=%s", (steel["lot"],))
    assert a is not None and a["severity"] == "critical"


# ---------------------------------------------------------------- 方案、动作
def test_w3_options(env):
    from hub import supply as SP
    from hub.ont import plan as P
    H, _ = env
    db = H.db
    lid = _bad_lot(H)
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    a = db.one("select * from anomaly where mode='teach' and rule='W3' and fkey=%s", (db.one("select lot from lot where id=%s", (lid,))["lot"],))
    assert a is not None and a["severity"] == "critical"
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    r = SP.options(db, "teach", a, st, ctx)
    kinds = [o["kind"] for o in r["options"]]
    assert kinds == ["none", "return", "alt", "concession"]
    alt = r["options"][2]
    assert [c["type"] for c in alt["changes"]] == ["supplier_return", "purchase_order"] and alt["changes"][1]["rush"]
    assert any("加价 20%" in c["what"] for c in alt["result"]["costs"])
    assert r["options"][3]["arrive"] < r["options"][1]["arrive"] and not r["options"][0]["recommended"]
    assert SP._state(db, "teach")["recommended"][str(r["lot"]["id"])] == next(o["kind"] for o in r["options"] if o["recommended"])
    assert "material_arrival" in P.CHANGE_TYPES


def test_actions_po_return_concession_alt(env):
    from hub import supply as SP
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    with pytest.raises(AC.ActionError):
        AC.create(db, "teach", OPR, "purchase_order", {"type": "purchase_order", "supplier": BRG, "items": []})
    ch = {"type": "purchase_order", "supplier": SP.ALT["bearings"][0], "items": [{"item_code": "BRG-6207", "qty": 40}], "rush": True}
    tr = AC.trial(db, H.plan_snaps, "teach", [ch])
    aid = AC.create(db, "teach", PLN, "purchase_order", ch, None, None, tr)
    AC.submit(db, aid, PLN, tr)
    assert AC.is_costly(AC.get(db, aid)) and not AC.can_approve(QA, AC.get(db, aid))[0]
    AC.approve(H, aid, TEA, TEA["name"])
    x = db.one("select * from lot where action_id=%s", (aid,))
    assert x["supplier"] == SP.ALT["bearings"][0] and float(x["rate"]) == 9.6 and x["note"] == "加急"
    # 退货：计划员发起、质量批
    bad = db.one("select * from lot where mode='teach' and status='rejected' order by id limit 1")
    aid = AC.create(db, "teach", PLN, "supplier_return", {"type": "supplier_return", "lot_id": bad["id"]}, None, None, None)
    AC.submit(db, aid, PLN, None)
    assert AC.can_approve(QA, AC.get(db, aid))[0]
    AC.approve(H, aid, QA, QA["name"])
    assert db.one("select status from lot where id=%s", (bad["id"],))["status"] == "returned"
    # 让步接收：要质量或厂长批
    lid = _po(H, BRG, "BRG-6205", 30, "PUR-ORD-T-0004")
    db.x("update lot set status='transit', lot='L261005-9999', truth_bad=true where id=%s", (lid,))
    SP.arrive(db, "teach", lid, "x")
    SP.inspect(H, "teach", lid, False, "学生质量")
    aid = AC.create(db, "teach", PLN, "concession", {"type": "concession", "lot_id": lid}, None, None, None)
    AC.submit(db, aid, PLN, None)
    assert not AC.can_approve({"name": "计划乙", "role": "planner", "mode": "teach"}, AC.get(db, aid))[0]
    AC.approve(H, aid, QA, QA["name"])
    x = db.one("select * from lot where id=%s", (lid,))
    assert x["status"] == "accepted" and x["concession"] and 20 <= float(x["qty_ok"]) < 30
    # 开发备选：铸件不再是单一来源
    aid = AC.create(db, "teach", PLN, "alt_supplier", {"type": "alt_supplier", "cat": "castings"}, None, None, None)
    AC.submit(db, aid, PLN, None)
    AC.approve(H, aid, TEA, TEA["name"])
    assert "castings" not in {x["cat"] for x in SP.single_source(db, "teach")}


# ---------------------------------------------------------------- 态势、报告
def test_kpis_situation_report(env):
    from hub import supply as SP
    from hub.ont import report as RP
    from hub.ont import situation as SI
    H, _ = env
    k = SP.kpis(H.db, "teach")
    assert k["in_transit"] >= 1 and k["pass_rate"] is not None and k["pass_rate"] < 1
    now = dt.datetime.now(dt.timezone.utc)
    sit = SI.cards(H.db, H.ai.detector(), "teach", now)
    card = next(c for c in sit["cards"] if c["domain"] == "supply")
    assert {"on_time", "pass_rate", "single_source"} <= {m["key"] for m in card["metrics"]}
    assert {"W3", "W7"} <= set(card["rules_live"])
    d = RP.build(H.db, "teach", "daily", now - dt.timedelta(days=1), now)
    assert d["supply"] is not None and d["supply"]["rejected"] >= 1


# ---------------------------------------------------------------- AI 代理
def test_agent_supply_tools_and_intent(env):
    from hub.ont.agent import Agent, Rules, Run, Tools
    H, _ = env
    t = Tools(H, TEA, Run(TEA))
    s = t.supplier_scorecard()
    assert len(s["suppliers"]) == 10 and "总拥有成本" in s["tco_formula"]
    lot = H.db.one("select lot from lot where mode='teach' and status='returned' order by id limit 1")["lot"]
    tr = t.batch_trace(lot=lot)
    assert tr["row"]["item"] == "BRG-6207" and t.batch_trace(lot="L000000-0000").get("error") and t.batch_trace().get("error")
    assert t.purchasing_status()["open_lots"]
    r = Rules(None, False)
    assert r.intent("各家供应商的准时率和合格率怎么样？") == "supplier" and r.intent("批次 L261001-0001 用到哪里去了？") == "supplier"
    assert r.intent("CP-00001 这批投诉的设备还装在谁家？") != "supplier"
    out = Agent(H, NoLLM()).ask(QA, [{"role": "user", "content": "各家供应商的准时率和合格率怎么样？"}])
    assert out["answer"].startswith("提示") and not out["tools"]


# ---------------------------------------------------------------- 实验 20
def test_lab20_flow(env):
    from hub import lab20
    from hub import supply as SP
    from hub.ont import actions as AC
    from hub.ont import plan as P
    H, _ = env
    db = H.db
    U = {"name": "学生质量丙", "role": "quality", "teacher": False, "mode": "teach"}
    with pytest.raises(PermissionError):
        lab20.inject(H, U, {})
    r = lab20.inject(H, TEA, {})
    lid = r["lot_id"]
    db.x("update lot set po='PUR-ORD-T-0020' where id=%s", (lid,))
    now = dt.datetime.now(dt.timezone.utc)
    SP.tick(H, "teach", now=now)
    assert db.one("select truth_bad from lot where id=%s", (lid,))["truth_bad"]
    SP.tick(H, "teach", now=now + dt.timedelta(days=1))
    db.x("update lot set arrived_at = now() - interval '30 minutes' where id=%s", (lid,))
    SP.tick(H, "teach")
    assert db.one("select status from lot where id=%s", (lid,))["status"] == "arrived"                  # 留给学生，模拟器不检
    lab20.start(db, U["name"])
    assert lab20.locked(db, U) and not lab20.locked(db, TEA)
    want = [x["cat"] for x in SP.single_source(db, "teach")]
    assert lab20.answer(db, U["name"], "l20_t1", {"cats": want})["score"] == 10
    SP.inspect(H, "teach", lid, False, U["name"])
    bad = len(SP.judge(SP.sample(db, "teach", lid)))
    assert lab20.answer(db, U["name"], "l20_t2", {"bad_count": bad})["score"] == 15
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    a = db.one("select * from anomaly where mode='teach' and rule='W3' and fkey=%s", (db.one("select lot from lot where id=%s", (lid,))["lot"],))
    _, st, _ = H.plan_snaps.take("teach")
    o = SP.options(db, "teach", a, st, P.context(db, "teach", dt.datetime.fromisoformat(st["factory_now"])))
    best = o["options"][[x["recommended"] for x in o["options"]].index(True)]["kind"]
    assert lab20.answer(db, U["name"], "l20_t3", {"option": best, "reason": "退货不花钱，交期来得及；备选太贵，质量风险要控制"})["score"] == 10
    assert not lab20.locked(db, U)
    aid = AC.create(db, "teach", U, "supplier_return", {"type": "supplier_return", "lot_id": lid}, None, None, None)
    AC.submit(db, aid, U, None)
    assert next(t for t in lab20.check(db, U["name"])["tasks"] if t["id"] == "l20_t4")["score"] == 5
    AC.approve(H, aid, TEA, TEA["name"])
    assert next(t for t in lab20.check(db, U["name"])["tasks"] if t["id"] == "l20_t4")["score"] == 15
    sc = {x["role"]: x for x in SP.scorecard(db, "teach") if x["cat"] == "bearings"}
    ans = {"tco_default": SP.tco(8, sc["default"]["price_index"], sc["default"]["hist_on_time"], sc["default"]["hist_pass"]),
           "tco_alt": SP.tco(8, sc["alt"]["price_index"], sc["alt"]["hist_on_time"], sc["alt"]["hist_pass"])}
    assert lab20.answer(db, U["name"], "l20_t5", ans)["score"] == 10
    st = lab20.check(db, U["name"])
    assert st["score"] == 60 == st["of"] and st["report_points"] == 40
    assert any(c["user"] == U["name"] for c in lab20.class_view(db))


def test_reset(env):
    from hub import supply as SP
    H, _ = env
    SP.reset(H.db, "teach")
    assert SP.enabled(H.db, "teach") is False and H.db.one("select count(*) as n from lot where mode='teach'")["n"] == 0
    assert {x["cat"] for x in SP.single_source(H.db, "teach")} == {"castings", "forgings", "hardware", "lubricant"}
    assert SP.enabled(H.db, "prod") is False


def test_lab20_documents_and_course():
    pytest.importorskip("docx")
    import io

    import docx

    from cae import labdoc
    g = labdoc.guide_docx("lab20")
    t = labdoc.report_template_docx("lab20")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "总拥有成本" in text and "任务 5" in text and "比对模式" in text
    src = open(__import__("hub.course", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert '"id": "lab20"' in src
