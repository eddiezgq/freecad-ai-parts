# -*- coding: utf-8 -*-
"""第 18 轮 E3：设备维护与资产——失效率模型与仿真车间、风险与预期损失、保养时机三方案、保养工单（挂牌上锁 → 做完 → 验收解锁 → 运行小时清零）、
故障 → 维修单（挂牌上锁、等备件）、点检 → M3、态势与报告、AI 代理三个新工具、实验 18 自动评分。"""
import datetime as dt
import os
import random

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
MNT = {"name": "学生维修工", "role": "maintenance", "teacher": False, "mode": "teach"}
MNT2 = {"name": "学生维修工乙", "role": "maintenance", "teacher": False, "mode": "teach"}
PLN = {"name": "学生计划", "role": "planner", "teacher": False, "mode": "teach"}


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
        H, eng = EV.sandbox(DSN, name="wq_maint_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    h = Historian(H.db)
    eng.pub = lambda tp, ty, src, data, corr=None, ts=None: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts))
    return H, eng


# ---------------------------------------------------------------- 失效率模型与仿真车间
def test_reliability_math():
    from sim import reliability as REL
    rp = REL.params("grd-01")
    assert rp["beta"] == 3 and rp["eta_h"] == 900 and rp["pm_h"] == 500
    assert REL.cdf(0, 3, 900) == 0 and abs(REL.cdf(900, 3, 900) - (1 - 2.718281828 ** -1)) < 1e-6
    young, old = REL.cond_fail(0, 80, 3, 900), REL.cond_fail(700, 80, 3, 900)
    assert young < 0.01 < 0.1 < old < 0.2                                              # 磨损：越老越容易坏
    assert REL.hazard(700, 3, 900) > REL.hazard(100, 3, 900)
    assert REL.params("nope") is None
    assert all(REL.params(u)["modes"] for u in REL.PARAMS)


def _run(eng, clock, hours):
    end = clock.t + hours * 3600
    while clock.t < end:
        clock.t += 600
        eng.run_due()


def test_engine_aging_pm_done_and_snapshot():
    from tests_helpers import make_engine
    eng, clock, _ = make_engine(auto=True)
    m = eng.machines["grd-01"]
    h0 = m.run_h
    assert eng.command("grd-01", {"command": "set_run_h", "hours": 650})[0] and m.run_h == 650
    eng.set_reliability(0)
    _run(eng, clock, 4)
    assert m.state != "fault"                                                          # 系数 0：永远不坏
    assert eng.command("grd-01", {"command": "pm_done"})[0] and m.run_h == 0
    snap = eng.snapshot()
    assert snap["machines"]["grd-01"]["run_h"] == 0 and "rel_factor" in snap
    assert h0 > 0


def test_engine_overdue_machines_fail_more_often():
    """同样跑 40 小时，逾期的设备比刚保养过的坏得多（统计检验，固定种子）"""
    from tests_helpers import make_engine
    fails = {"old": 0, "new": 0}
    for seed in range(12):
        for kind, h in (("old", 1300), ("new", 0)):
            eng, clock, _ = make_engine(auto=True)
            eng.rel_rng = random.Random(seed)
            eng.set_reliability(3)
            eng.command("grd-01", {"command": "set_run_h", "hours": h})
            m = eng.machines["grd-01"]
            for _ in range(40):                                                    # 每做完一件按运行时间老化（这里直接按小时调）
                eng._age(m, clock.t, 1.0)
                if m.state == "fault" and m.fail_mode:
                    fails[kind] += 1
                    break
    assert fails["old"] > fails["new"] + 3, fails


# ---------------------------------------------------------------- 风险、方案
def test_risk_and_expected_loss(env):
    from hub import maint as MT
    H, _ = env
    rk = MT.risk(H.db, "teach", "grd-01", run_h=700, f=1)
    assert 0.15 < rk["p_fail"] < 0.18 and rk["p_after_pm"] < 0.001
    assert abs(rk["expected_loss_usd"] - rk["p_fail"] * (1200 + 480 / 60 * 200)) < 0.5
    assert rk["pm_usd"] == round(180 / 60 * 45 + 80, 2) and rk["overdue_h"] == 200
    assert MT.risk(H.db, "teach", "grd-01", run_h=700, f=5)["p_fail"] > 0.9
    with pytest.raises(KeyError):
        MT.risk(H.db, "teach", "nope")


def test_assets_ledger_and_m2_anomaly(env):
    from hub import maint as MT
    H, _ = env
    rows = {a["unit"]: a for a in MT.assets(H.db, "teach")}
    assert len(rows) == 13 and rows["grd-01"]["overdue_h"] > 0 and rows["grd-01"]["value"]
    a = H.db.one("select * from anomaly where mode='teach' and rule='M2' and subject_key='grd-01'")
    assert a is not None and a["status"] == "open"


def test_pm_options_three_and_recommend_pm(env):
    from hub import maint as MT
    from hub.ont import plan as P
    H, _ = env
    a = H.db.one("select * from anomaly where mode='teach' and rule='M2' and subject_key='grd-01'")
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    r = MT.options(H.db, "teach", a, st, ctx)
    assert [o["kind"] for o in r["options"]] == ["none", "pm_now", "pm_later"]
    none, now, later = r["options"]
    assert any("预期故障损失" in c["what"] for c in none["result"]["costs"]) and "if_fails" in none["result"]
    assert now["changes"][0]["type"] == "pm_order" and later["changes"][0]["delay_minutes"] > 0
    assert r["recommended"] in ("B", "C") and r["risk"]["p_fail"] > 0.1


def test_plan_simulate_pm_order_costs(env):
    from hub.ont import plan as P
    H, _ = env
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    r = P.simulate(st, [{"type": "pm_order", "unit": "grd-01", "minutes": 180}], ctx)
    assert r["ok"] and any("保养人工" in c["what"] and c["usd"] == 215 for c in r["costs"])


# ---------------------------------------------------------------- 保养工单：动作 → 挂牌 → 做完 → 验收
def test_pm_action_lockout_finish_verify(env):
    from hub import maint as MT
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    ch = {"type": "pm_order", "unit": "grd-01", "minutes": 180}
    with pytest.raises(AC.ActionError):
        AC.create(db, "teach", PLN, "pm_order", ch)                                      # 计划员不能发起
    _, st, _ = H.plan_snaps.take("teach")
    tr = AC.trial(db, H.plan_snaps, "teach", [ch], st)
    aid = AC.create(db, "teach", MNT, "pm_order", ch, None, None, tr)
    AC.submit(db, aid, MNT, tr)
    assert AC.is_costly(AC.get(db, aid)) and not AC.can_approve(MNT2, AC.get(db, aid))[0]
    n0 = len(H.mes.sent)
    AC.approve(H, aid, TEA, TEA["name"])
    assert AC.get(db, aid)["status"] == "done"
    assert H.mes.sent[n0]["command"] == "lockout" and H.mes.sent[n0]["unit"] == "grd-01"
    pm = db.one("select * from maint_pm where action_id=%s", (aid,))
    assert pm["status"] == "doing" and pm["permit_id"]
    with pytest.raises(ValueError):
        MT.verify_pm(H, "teach", pm["id"], MNT2["name"])                                  # 还没做完
    db.x("update work_permit set valid_from = now() - interval '2 hours' where id=%s", (pm["permit_id"],))
    got = MT.tick(H, "teach")
    assert pm["id"] in got["pms"]
    assert any(c["command"] == "pm_done" and c["unit"] == "grd-01" for c in H.mes.sent[n0:])
    pm = db.one("select * from maint_pm where id=%s", (pm["id"],))
    assert pm["status"] == "fixed"
    with pytest.raises(PermissionError):
        MT.verify_pm(H, "teach", pm["id"], pm["fixed_by"])
    MT.verify_pm(H, "teach", pm["id"], MNT2["name"])
    assert H.mes.sent[-1]["command"] == "unlock"
    assert db.one("select status from work_permit where id=%s", (pm["permit_id"],))["status"] == "closed"


def test_interval_change_action(env):
    from hub import maint as MT
    from hub.ont import actions as AC
    H, _ = env
    ch = {"type": "interval_change", "unit": "hob-01", "interval_h": 300}
    tr = AC.trial(H.db, H.plan_snaps, "teach", [ch])
    assert tr["ok"]
    aid = AC.create(H.db, "teach", MNT, "interval_change", ch, None, None, tr)
    AC.submit(H.db, aid, MNT, tr)
    AC.approve(H, aid, TEA, TEA["name"])
    assert MT.interval_of(H.db, "teach", "hob-01") == 300
    with pytest.raises(ValueError):
        MT.exec_interval(H, "teach", {"unit": "hob-01", "interval_h": 5}, TEA)


# ---------------------------------------------------------------- 故障 → 维修单（挂牌、等备件）
def test_failure_scan_repair_with_loto_and_waiting_parts(env):
    from hub import maint as MT
    H, eng = env
    db = H.db
    db.x("update maint_sim set state = state - 'seq' where mode='teach'")
    m = eng.machines["saw-01"]
    eng._go_down(m, eng.clock.now(), 5400, "故障：锯带断裂", "fault",
                 extra={"failure": "F-SAW-1", "failure_name": "锯带断裂", "part": "BRG-6207", "run_h_pm": 420.0})
    n0 = len(H.mes.sent)
    rids = MT.scan_failures(H, "teach")
    assert len(rids) == 1
    r = db.one("select * from maint_repair where id=%s", (rids[0],))
    assert r["source"] == "failure" and r["permit_id"] and r["parts"][0]["item_code"] == "BRG-6207"
    assert any(c["command"] == "lockout" and c["unit"] == "saw-01" for c in H.mes.sent[n0:])
    f = db.one("select * from maint_failure where repair_id=%s", (r["id"],))
    assert f["code"] == "F-SAW-1" and f["run_h"] == 420
    assert MT.scan_failures(H, "teach") == []                                           # 不重复开
    # 备件不够：等备件 → M5
    db.x("update maint_repair set parts=%s where id=%s", ('[{"item_code": "BRG-6207", "qty": 999}]', r["id"]))
    with pytest.raises(ValueError):
        MT.finish_repair(H, "teach", r["id"], "维修工")
    assert db.one("select status from maint_repair where id=%s", (r["id"],))["status"] == "waiting_parts"
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    a = db.one("select * from anomaly where mode='teach' and rule='M5' and fkey=%s", ("MR-{:05d}".format(r["id"]),))
    assert a is not None
    opts = MT.parts_options(db, "teach", a)
    assert opts["recommended"] == "A" and opts["options"][0]["changes"][0]["type"] == "urgent_purchase"
    # 备件到了：做完 → 验收
    db.x("update maint_repair set parts='[]' where id=%s", (r["id"],))
    MT.finish_repair(H, "teach", r["id"], "维修工")
    with pytest.raises(PermissionError):
        MT.verify_repair(H, "teach", r["id"], "维修工")
    MT.verify_repair(H, "teach", r["id"], MNT2["name"])
    assert db.one("select status from maint_repair where id=%s", (r["id"],))["status"] == "closed"


# ---------------------------------------------------------------- 点检 → M3
def test_inspection_abnormal_m3_and_options(env):
    from hub import maint as MT
    H, _ = env
    db = H.db
    items = MT.checklist(db, "teach", "hob-01")
    assert "没有异响、异常振动" in items
    ok = MT.inspect(db, "teach", "hob-01", [], "操作工")
    assert ok["abnormal"] == []
    bad = MT.inspect(db, "teach", "hob-01", [{"item": "没有异响、异常振动", "ok": False, "note": "主轴有异响"}], "操作工")
    assert len(bad["abnormal"]) == 1
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    a = db.one("select * from anomaly where mode='teach' and rule='M3' and fkey=%s", (bad["key"],))
    assert a is not None and a["subject_key"] == "hob-01"
    r = MT.inspection_options(db, "teach", a)
    assert r["options"][0]["changes"][0]["type"] == "repair_order" and r["recommended"] == "A"
    MT.inspection_watch(db, bad["id"], "王老师")
    assert db.one("select status from maint_inspection where id=%s", (bad["id"],))["status"] == "watch"
    with pytest.raises(KeyError):
        MT.checklist(db, "teach", "nope")


def test_simulator_inspects_every_five_minutes(env):
    from hub import maint as MT
    H, _ = env

    class R(random.Random):
        def random(self):
            return 0.01
    H.db.x("update maint_sim set state = state - 'insp' where mode='teach'")
    got = MT.tick(H, "teach", rng=R(1))
    assert len(got["inspections"]) == 1
    assert MT.tick(H, "teach", rng=R(1))["inspections"] == []
    assert MT.tick(H, "prod") == {}


def test_teacher_controls(env):
    from hub import maint as MT
    H, _ = env
    MT.set_factor(H, "teach", 5, "王老师")
    assert MT.factor(H.db, "teach") == 5 and H.mes.sent[-1] == {"unit": "sim", "command": "set_reliability", "mode": "teach", "factor": 5.0}
    r = MT.inject_overdue(H, "teach", "hob-01", 900, "王老师")
    assert "HOB-01" in r["text"] and H.mes.sent[-1]["command"] == "set_run_h" and H.mes.sent[-1]["hours"] == 900
    with pytest.raises(ValueError):
        MT.inject_overdue(H, "teach", "nope", 1, "王老师")
    MT.set_factor(H, "teach", 0, "王老师")


# ---------------------------------------------------------------- 态势、报告
def test_kpis_situation_and_report(env):
    from hub import maint as MT
    from hub.ont import report as RP
    from hub.ont import situation as SI
    H, _ = env
    k = MT.kpis(H.db, "teach")
    assert "grd-01" in k["overdue_units"] or k["overdue"] >= 0
    assert k["mtbf"] is not None                                                      # 上面开过一条故障
    now = dt.datetime.now(dt.timezone.utc)
    sit = SI.cards(H.db, H.ai.detector(), "teach", now)
    card = next(c for c in sit["cards"] if c["domain"] == "maintenance")
    assert {m["key"] for m in card["metrics"]} >= {"pm_overdue", "open_repairs", "mtbf"}
    assert {"M2", "M7"} <= set(card["rules_live"])
    d = RP.build(H.db, "teach", "daily", now - dt.timedelta(days=1), now)
    assert d["maint"] is not None and d["maint"]["failures"] >= 1


# ---------------------------------------------------------------- AI 代理
def test_agent_maint_tools_and_intent(env):
    from hub.ont.agent import Agent, Rules, Run, Tools
    H, _ = env
    t = Tools(H, TEA, Run(TEA))
    o = t.maint_overview()
    assert o["kpis"] and len(o["machines"]) == 13 and o["machines"][0]["overdue_h"] > 0
    fr = t.failure_risk("GRD-01", 160)
    assert 0 < fr["p_fail"] < 1 and fr["horizon_h"] == 160
    assert t.failure_risk("nope").get("error")
    rs = t.repairs_spares()
    assert "repairs" in rs
    r = Rules(None, False)
    assert r.intent("外圆磨床未来两周坏掉的概率多大？") == "maint" and r.intent("哪些设备保养逾期了？") == "maint"
    assert r.intent("WQR105-0007 要上门点检吗？") != "maint"
    out = Agent(H, NoLLM()).ask(MNT, [{"role": "user", "content": "哪些设备保养逾期了？"}])
    assert out["answer"].startswith("提示") and not out["tools"]


# ---------------------------------------------------------------- 实验 18
def test_lab18_flow(env):
    from hub import lab18
    from hub import maint as MT
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    U = {"name": "学生维修工丙", "role": "maintenance", "teacher": False, "mode": "teach"}
    with pytest.raises(PermissionError):
        lab18.inject(H, U, {})
    lab18.inject(H, TEA, {"factor": 1, "unit": "grd-01", "hours": 0})
    assert MT.factor(db, "teach") == 1
    assert not lab18.locked(db, U)
    lab18.start(db, U["name"])
    assert lab18.locked(db, U) and not lab18.locked(db, TEA)
    rk = MT.risk(db, "teach", "grd-01")
    r1 = lab18.answer(db, U["name"], "l18_t1", {"unit": "grd-01", "run_h": rk["run_h"], "p_fail": rk["p_fail"] * 100, "loss": rk["expected_loss_usd"]})
    assert r1["score"] == 15, r1
    assert lab18.answer(db, "学生丁", "l18_t1", {"unit": "grd-01", "run_h": 1, "p_fail": 90, "loss": 1})["score"] == 0
    assert lab18.answer(db, U["name"], "l18_t2", {"option": "pm_now", "reason": "短"})["score"] == 0
    best = lab18._system_choice(db, "grd-01")
    r2 = lab18.answer(db, U["name"], "l18_t2", {"option": best, "reason": "坏掉的概率不小，预期损失比保养的费用高，交期还来得及"})
    assert r2["score"] == 10 and not lab18.locked(db, U)
    # 任务 3：保养工单 → 批准 → 模拟器做完 → 自己验收
    ch = {"type": "pm_order", "unit": "grd-01", "minutes": 180}
    aid = AC.create(db, "teach", U, "pm_order", ch, None, None, None)
    AC.submit(db, aid, U, None)
    assert next(t for t in lab18.check(db, U["name"])["tasks"] if t["id"] == "l18_t3")["score"] == 5
    AC.approve(H, aid, TEA, TEA["name"])
    pm = db.one("select * from maint_pm where action_id=%s", (aid,))
    db.x("update work_permit set valid_from = now() - interval '2 hours' where id=%s", (pm["permit_id"],))
    MT.tick(H, "teach")
    MT.verify_pm(H, "teach", pm["id"], U["name"])
    # 车间收到 pm_done 后状态里运行小时清零（这里直接发一条状态）
    _status(H, "grd-01", 0.0)
    assert next(t for t in lab18.check(db, U["name"])["tasks"] if t["id"] == "l18_t3")["score"] == 15
    # 任务 4、5
    st = lab18.status(db, U["name"])
    other = lab18._other(db, "grd-01")
    assert other and other != "grd-01"
    r4 = lab18.answer(db, U["name"], "l18_t4", {"mine": 0, "other": 0})
    assert r4["score"] == 10, r4
    m = MT.mtbf(db, "teach")
    assert lab18.answer(db, U["name"], "l18_t5", {"mtbf": m})["score"] == 10
    st = lab18.check(db, U["name"])
    assert st["score"] == 60 == st["of"] and st["report_points"] == 40
    assert any(c["user"] == U["name"] for c in lab18.class_view(db))
    lab18.inject(H, TEA, {"factor": 0})


def _status(H, unit, run_h):
    import wqbus
    from hub.historian import Historian
    from wqbus import unit_topic
    last = H.db.one("select payload from bus_message where type='machine.status' and mode='teach' and topic=%s order by ts desc limit 1",
                    (unit_topic(unit, "status"),))
    data = dict(last["payload"]["data"], run_h_pm=run_h)
    Historian(H.db).handle(unit_topic(unit, "status"), wqbus.make("machine.status", "sim/" + unit, data))


def test_lab18_documents_and_course():
    pytest.importorskip("docx")
    import io

    import docx

    from cae import labdoc
    g = labdoc.guide_docx("lab18")
    t = labdoc.report_template_docx("lab18")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "威布尔" in text and "任务 5" in text and "比对模式" in text
    src = open(__import__("hub.course", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert '"id": "lab18"' in src


def test_verify_refused_keeps_order_open(env):
    """解锁人不对（申请许可的人）：验收被拦下，维修单不关、锁还在"""
    from hub import maint as MT
    H, _ = env
    db = H.db
    rid = MT.open_repair(H, "teach", "press-01", "manual", "闭环：压力机检查", [], "学生维修工")
    MT.finish_repair(H, "teach", rid, "王老师")
    with pytest.raises(PermissionError):
        MT.verify_repair(H, "teach", rid, "学生维修工")
    r = db.one("select * from maint_repair where id=%s", (rid,))
    assert r["status"] == "fixed" and db.one("select status from work_permit where id=%s", (r["permit_id"],))["status"] == "active"
    MT.verify_repair(H, "teach", rid, "学生维修工乙")
    assert db.one("select status from maint_repair where id=%s", (rid,))["status"] == "closed"


def test_failure_repair_auto_verified_and_reset_turns_reliability_off(env):
    """模拟器：故障维修做完 3 分钟没人验收，班组长替验收解锁；情景重置后可靠性关闭，旧故障不再开单"""
    from hub import maint as MT
    H, eng = env
    db = H.db
    MT.reset(db, "teach")
    assert MT.factor(db, "teach") == 0
    eng._go_down(eng.machines["ht-01"], eng.clock.now(), 600, "故障：加热元件", "fault",
                 extra={"failure": "F-HT-1", "failure_name": "加热元件烧断", "part": None, "run_h_pm": 900.0})
    rid = MT.scan_failures(H, "teach")[0]
    MT.finish_repair(H, "teach", rid, "维修工（教学模拟器）")
    db.x("update maint_repair set fixed_at = now() - interval '5 minutes' where id=%s", (rid,))
    got = MT.tick(H, "teach")
    assert rid in got["repairs"] and db.one("select status from maint_repair where id=%s", (rid,))["status"] == "closed"
    assert any(c["command"] == "set_reliability" and c["factor"] == 0 for c in H.mes.sent)
    MT.reset(db, "teach")
    assert MT.scan_failures(H, "teach") == []
    db.x("delete from maint_sim where mode='teach'")
    assert MT.factor(db, "teach") == 1 and MT.factor(db, "prod") == 0                   # 教学模式默认会坏


def test_ensure_setup_resends_when_bridge_missed_it(env):
    """建台账的提议确认了 3 分钟还没执行（桥接没收到）就重发；资产都读回来以后不再发"""
    from hub import maint as MT
    H, _ = env
    db = H.db
    db.x("delete from maint_sim where mode='teach'")
    p1 = MT.ensure_setup(H, "teach")
    assert p1 and db.one("select status from ai_proposal where proposal_id=%s", (p1,))["status"] == "confirmed"
    assert MT.ensure_setup(H, "teach") == p1
    db.x("update maint_sim set state = jsonb_set(state, '{setup_at}', to_jsonb(extract(epoch from now()) - 200)) where mode='teach'")
    p2 = MT.ensure_setup(H, "teach")
    assert p2 and p2 != p1
    pv = db.one("select preview from ai_proposal where proposal_id=%s", (p2,))["preview"]
    assert len(pv["assets"]) == 13
