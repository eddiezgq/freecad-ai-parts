# -*- coding: utf-8 -*-
"""第 18 轮 E2：安全环保——员工与培训、风险评估、隐患 → 异常 → 推演方案、作业许可与资质、挂牌上锁（车间停机 / 解锁）、
动作与审批、教学模拟器、态势与报告、AI 代理三个新工具、实验 17 自动评分。"""
import datetime as dt
import os

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
SAF = {"name": "学生安全员", "role": "safety", "teacher": False, "mode": "teach"}
SAF2 = {"name": "学生安全员乙", "role": "safety", "teacher": False, "mode": "teach"}
PLN = {"name": "学生计划", "role": "planner", "teacher": False, "mode": "teach"}


class FakeMes:
    def __init__(self):
        self.sent = []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(dict({"unit": unit, "command": command, "mode": mode}, **extra))


@pytest.fixture(scope="module")
def env():
    pytest.importorskip("psycopg")
    from hub.ont import evals as EV
    try:
        H, eng = EV.sandbox(DSN, name="wq_ehs_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    return H, eng


def _major(db):
    return db.one("select * from safety_issue where mode='teach' and level='major' order by id limit 1")


def _e1(db, iid):
    return db.one("select * from anomaly where mode='teach' and rule='E1' and fkey=%s", ("SI-{:05d}".format(iid),))


# ---------------------------------------------------------------- 基础数据
def test_seed_people_trainings_hazards(env):
    from hub import ehs as EH
    H, _ = env
    ps = EH.people(H.db, "teach")
    assert len(ps) == 30 and {"操作工", "维修工", "安全员", "班组长"} <= {p["post"] for p in ps}       # 第 18 轮 E4：员工档案 30 人（E2 的 12 人工号不变）
    assert [p["name"] for p in ps if p["id"] in ("P01", "P12")] == ["王强", "冯涛"]
    assert "confined" in next(p for p in ps if p["id"] == "P07")["expired"]                     # 故事二：孙磊的受限空间已过期
    assert len(H.db.q("select id from hazard where mode='teach'")) == 12
    assert EH.qualified(H.db, "teach", "P07", "confined")[0] is False
    assert EH.qualified(H.db, "teach", "P06", "loto")[0] is True
    assert EH.seed(H.db, "teach") is False                                                       # 再调不会重复建


def test_risk_matrix():
    from hub import ehs as EH
    assert EH.risk(3, 5) == {"likelihood": 3, "severity": 5, "score": 15, "level": "重大"}
    assert EH.risk(2, 4)["level"] == "较大" and EH.risk(1, 5)["level"] == "一般"
    with pytest.raises(ValueError):
        EH.risk(0, 6)


# ---------------------------------------------------------------- 重大隐患 → 异常 → 方案
def test_major_issue_anomaly_chain_and_options(env):
    from hub import ehs as EH
    from hub.ont import anomaly as A
    from hub.ont import chain as CH
    from hub.ont import plan as P
    H, _ = env
    x = _major(H.db)
    a = _e1(H.db, x["id"])
    assert a is not None and a["severity"] == "critical" and a["subject_key"] == "grd-01"
    ch = CH.for_anomaly(A.Ctx(H.db, "teach"), a)
    assert any(n["type"] == "SafetyIssue" for n in ch["nodes"]) and ch["scope"].get("work_orders") is not None
    sid, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    r = EH.options(H.db, "teach", a, st, ctx)
    kinds = [o["kind"] for o in r["options"]]
    assert kinds[:3] == ["none", "lockout", "temp"]
    none = r["options"][0]
    assert not none["result"]["ok"] and not none["recommended"]                                  # 不处理只作对照
    lock = r["options"][1]
    assert lock["changes"][0]["type"] == "lockout" and lock["changes"][0]["minutes"] == x["fix_minutes"]
    assert any("安全整改人工" in c["what"] for c in lock["result"]["costs"])
    temp = r["options"][2]
    assert temp["changes"][0]["delay_minutes"] > 0 and any("临时防护" in c["what"] for c in temp["result"]["costs"])
    assert r["recommended"] in ("B", "D") and "先保安全" in r["reason"]


def test_plan_simulate_lockout_unlocks_after_fix(env):
    from hub.ont import plan as P
    H, _ = env
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    base = P.simulate(st, [], ctx)
    r = P.simulate(st, [{"type": "lockout", "unit": "key-01", "minutes": 600}], ctx)
    assert r["ok"] and any(c["usd"] == 450 for c in r["costs"])                                  # 600 分钟 × $45/小时
    fin = lambda res: max((w["finish"] or "") for w in res["work_orders"].values())               # noqa: E731
    assert fin(r) >= fin(base)


# ---------------------------------------------------------------- 作业许可与挂牌上锁
def test_permit_qualification_and_loto(env):
    from hub import ehs as EH
    H, _ = env
    db = H.db
    r = EH.request_permit(db, "teach", {"kind": "confined", "unit": "ht-01", "holder_id": "P07", "reason": "炉膛检修"}, "学生安全员")
    assert r["status"] == "blocked" and "已过期" in r["why"]
    with pytest.raises(PermissionError):
        EH.approve_permit(H, "teach", r["id"], "王老师")
    ok = EH.request_permit(db, "teach", {"kind": "confined", "unit": "ht-01", "holder_id": "P06", "reason": "炉膛检修"}, "学生安全员")
    assert ok["status"] == "requested"
    assert EH.approve_permit(H, "teach", ok["id"], "王老师")["status"] == "active"
    n0 = len(H.mes.sent)
    lo = EH.request_permit(db, "teach", {"kind": "loto", "unit": "key-01", "holder_id": "P06", "minutes": 90, "reason": "换联锁开关"}, "学生安全员")
    EH.approve_permit(H, "teach", lo["id"], "王老师")
    cmd = H.mes.sent[n0]
    assert cmd["unit"] == "key-01" and cmd["command"] == "lockout" and cmd["permit"] == lo["key"] and cmd["minutes"] == 90
    with pytest.raises(PermissionError):
        EH.close_permit(H, "teach", lo["id"], "学生安全员")                                       # 申请人不能自己解锁
    EH.close_permit(H, "teach", lo["id"], "王老师")
    assert H.mes.sent[-1]["command"] == "unlock" and H.mes.sent[-1]["unit"] == "key-01"
    for p in (ok["id"],):
        EH.close_permit(H, "teach", p, "王老师")


def test_engine_lockout_unlock_and_reset_refused():
    from tests_helpers import make_engine
    eng, clock, _ = make_engine(auto=True)
    ok, why = eng.command("grd-01", {"command": "lockout", "permit": "PTW-00009", "minutes": 30})
    m = eng.machines["grd-01"]
    assert ok and m.state == "down" and m.locked == "PTW-00009"
    assert eng.command("grd-01", {"command": "reset"})[0] is False
    clock.t += 3600
    eng.run_due()
    assert m.state == "down"                                     # 挂着锁不会自动恢复
    snap = eng.snapshot()
    assert snap["machines"]["grd-01"]["locked"] == "PTW-00009"
    assert eng.command("grd-01", {"command": "unlock"})[0] and m.state != "down" and m.locked is None
    assert eng.command("grd-01", {"command": "unlock"})[0] is False
    assert eng.command("grd-01", {"command": "lockout", "permit": "P2", "minutes": 10, "delay_minutes": 5})[0] and m.state != "down"
    clock.t += 400
    eng.run_due()
    assert m.state == "down" and m.locked == "P2"


# ---------------------------------------------------------------- 动作、模拟器整改、验收解锁
def test_lockout_action_fix_verify(env):
    from hub import ehs as EH
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    x = _major(db)
    a = _e1(db, x["id"])
    ch = {"type": "lockout", "unit": "grd-01", "minutes": x["fix_minutes"], "issue_id": x["id"], "reason": x["subject"]}
    with pytest.raises(AC.ActionError):
        AC.create(db, "teach", PLN, "lockout", ch)                                               # 计划员不能发起
    _, st, _ = H.plan_snaps.take("teach")
    tr = AC.trial(db, H.plan_snaps, "teach", [ch], st)
    assert tr["ok"] and tr["cost_total"] > 0
    aid = AC.create(db, "teach", SAF, "lockout", ch, None, a["id"], tr)
    AC.submit(db, aid, SAF, tr)
    act = AC.get(db, aid)
    assert AC.is_costly(act) and not AC.can_approve(SAF2, act)[0]
    n0 = len(H.mes.sent)
    AC.approve(H, aid, TEA, TEA["name"])
    assert AC.get(db, aid)["status"] == "done"
    assert H.mes.sent[n0]["command"] == "lockout" and H.mes.sent[n0]["unit"] == "grd-01"
    x = db.one("select * from safety_issue where id=%s", (x["id"],))
    assert x["permit_id"] and x["owner"] and x["status"] == "assigned"
    # 教学模拟器：持证维修工做完整改（把许可的开始时间往前拨）
    db.x("update work_permit set valid_from = now() - interval '2 hours' where id=%s", (x["permit_id"],))
    db.x("update ehs_sim set state='{}' where mode='teach'")
    EH.tick(H, "teach")
    x = db.one("select * from safety_issue where id=%s", (x["id"],))
    assert x["status"] == "fixed" and "维修工" in x["fixed_by"]
    with pytest.raises(PermissionError):
        EH.verify(H, "teach", x["id"], x["fixed_by"])
    out = EH.verify(H, "teach", x["id"], SAF["name"])
    assert out["closed"] == "SI-{:05d}".format(x["id"]) and H.mes.sent[-1]["command"] == "unlock"
    assert db.one("select status from work_permit where id=%s", (x["permit_id"],))["status"] == "closed"


def test_training_action_and_nosim_trial(env):
    from hub import ehs as EH
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    ch = {"type": "training_plan", "kind": "confined", "people": ["P07"]}
    tr = AC.trial(db, H.plan_snaps, "teach", [ch])
    assert tr["ok"] and tr["sales_orders"] == [] and "安排培训" in tr["checks"][0]["text"]
    aid = AC.create(db, "teach", SAF, "training_plan", ch, None, None, tr)
    AC.submit(db, aid, SAF, tr)
    act = AC.get(db, aid)
    assert not AC.is_costly(act) and AC.can_approve(SAF2, act)[0] and not AC.can_approve(PLN, act)[0]
    AC.approve(H, aid, SAF2, SAF2["name"])
    assert AC.get(db, aid)["status"] == "done"
    assert EH.qualified(db, "teach", "P07", "confined")[0] is True


def test_simulator_generates_issues_and_consumes(env):
    import random
    from hub import ehs as EH
    H, _ = env
    db = H.db
    n0 = db.one("select count(*) as n from safety_issue where mode='teach'")["n"]

    class R(random.Random):
        def random(self):
            return 0.001
    db.x("update ehs_sim set state='{}' where mode='teach'")
    got = EH.tick(H, "teach", rng=R(1))
    assert got["issues"] and got["incidents"]
    assert db.one("select count(*) as n from safety_issue where mode='teach'")["n"] == n0 + 1
    assert EH.tick(H, "teach", rng=R(1)) == {"issues": [], "incidents": []}                       # 一分钟内不再来
    assert EH.tick(H, "prod") == {}


def test_waste_dispose_and_kpis(env):
    from hub import ehs as EH
    H, _ = env
    db = H.db
    k = EH.kpis(db, "teach")
    assert k["waste_over"] >= 1 and k["training_due"] >= 1
    w = next(x for x in EH.wastes(db, "teach") if x["over_limit"])
    with pytest.raises(ValueError):
        EH.dispose(db, "teach", w["id"], "")
    EH.dispose(db, "teach", w["id"], "某某环保（危废经营许可证）")
    assert EH.kpis(db, "teach")["waste_over"] == k["waste_over"] - 1


def test_situation_card_and_report(env):
    from hub.ont import report as RP
    from hub.ont import situation as SI
    H, _ = env
    now = dt.datetime.now(dt.timezone.utc)
    sit = SI.cards(H.db, H.ai.detector(), "teach", now)
    card = next(c for c in sit["cards"] if c["domain"] == "ehs")
    assert card["waiting"] is None and {m["key"] for m in card["metrics"]} >= {"open_issues", "locked", "training_due"}
    assert {"E1", "E7"} <= set(card["rules_live"])
    d = RP.build(H.db, "teach", "daily", now - dt.timedelta(days=1), now)
    assert d["ehs"] is not None and d["ehs"]["new_issues"] >= 1


# ---------------------------------------------------------------- AI 代理
def test_agent_ehs_tools_and_intent(env):
    from hub.ont.agent import Agent, Rules, Run, Tools
    H, _ = env
    t = Tools(H, TEA, Run(TEA))
    o = t.ehs_overview()
    assert o["kpis"]["open_issues"] >= 1 and o["issues"]
    m = t.machine_safety("grd-01")
    assert {h["id"] for h in m["hazards"]} == {"HZ-01", "HZ-02"}
    assert t.machine_safety("nope").get("error")
    assert t.risk_assess(4, 5)["level"] == "重大" and t.risk_assess(9, 1).get("error")
    r = Rules(None, False)
    assert r.intent("现在有哪些安全隐患？") == "safety" and r.intent("外圆磨床有什么安全风险？") == "safety"
    assert r.intent("BRG-6207 低于安全库存了吗？") == "material"                                    # “安全库存”不算安全
    out = Agent(H, NoLLM()).ask(SAF, [{"role": "user", "content": "现在有哪些安全隐患？"}])
    assert out["answer"].startswith("提示") and not out["tools"]


# ---------------------------------------------------------------- 实验 17
def test_lab17_flow(env):
    from hub import ehs as EH
    from hub import lab17
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    U = {"name": "学生安全员丙", "role": "safety", "teacher": False, "mode": "teach"}
    with pytest.raises(PermissionError):
        lab17.inject(H, U, {})
    r = lab17.inject(H, TEA, {"unit": "grd-01", "issue_kind": "guard"})
    iid = r["id"]
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    assert not lab17.locked(db, U)
    lab17.start(db, U["name"])
    assert lab17.locked(db, U) and not lab17.locked(db, TEA)
    # 任务 1：HZ-01 砂轮破裂飞出（2 × 5）→ 防护缺失后可能性 3 → 15 重大
    r1 = lab17.answer(db, U["name"], "l17_t1", {"issue_id": iid, "hazard_id": "HZ-01", "likelihood": 3, "severity": 5, "level": "重大"})
    assert r1["score"] == 10, r1
    assert lab17.answer(db, "学生丁", "l17_t1", {"issue_id": iid, "hazard_id": "HZ-02", "likelihood": 2, "severity": 2, "level": "一般"})["score"] == 0
    # 任务 2：按系统因果链
    x = db.one("select * from safety_issue where id=%s", (iid,))
    wos, sos = lab17.scope(db, x)
    r2 = lab17.answer(db, U["name"], "l17_t2", {"work_orders": sorted(wos), "sales_orders": sorted(sos), "fix_minutes": x["fix_minutes"]})
    assert r2["score"] == 15, r2
    # 任务 3
    assert lab17.answer(db, U["name"], "l17_t3", {"option": "lockout", "reason": "短"})["score"] == 0
    r3 = lab17.answer(db, U["name"], "l17_t3", {"option": "lockout", "reason": "重大隐患有伤人风险必须先停，整改两小时，订单交期还来得及"})
    assert r3["score"] == 10 and not lab17.locked(db, U)
    # 任务 4：起草停机挂牌 → 老师批准 → 模拟器整改 → 自己验收
    ch = {"type": "lockout", "unit": "grd-01", "minutes": x["fix_minutes"], "issue_id": iid, "reason": x["subject"]}
    _, st, _ = H.plan_snaps.take("teach")
    aid = AC.create(db, "teach", U, "lockout", ch, None, (lab17._anomaly_for(db, iid) or {}).get("id"), AC.trial(db, H.plan_snaps, "teach", [ch], st))
    AC.submit(db, aid, U, None)
    assert next(t for t in lab17.check(db, U["name"])["tasks"] if t["id"] == "l17_t4")["score"] == 6
    AC.approve(H, aid, TEA, TEA["name"])
    x = db.one("select * from safety_issue where id=%s", (iid,))
    db.x("update work_permit set valid_from = now() - interval '2 hours' where id=%s", (x["permit_id"],))
    db.x("update ehs_sim set state='{}' where mode='teach'")
    EH.tick(H, "teach")
    EH.verify(H, "teach", iid, U["name"])
    assert next(t for t in lab17.check(db, U["name"])["tasks"] if t["id"] == "l17_t4")["score"] == 15
    # 任务 5：看板上的实际情况
    from hub import kpi
    late = 0
    for o in kpi.overview(db, None, "teach")["orders"]:
        if o["name"] in sos and o.get("projected"):
            late = max(late, (dt.date.fromisoformat(o["projected"][:10]) - dt.date.fromisoformat(o["delivery_date"][:10])).days)
    right = lab17.BUCKETS[0] if late <= 0 else (lab17.BUCKETS[1] if late == 1 else lab17.BUCKETS[2])
    assert lab17.answer(db, U["name"], "l17_t5", {"bucket": right})["score"] == 10
    st = lab17.check(db, U["name"])
    assert st["score"] == 60 == st["of"] and st["report_points"] == 40
    assert any(c["user"] == U["name"] for c in lab17.class_view(db))


def test_lab17_documents_and_course():
    pytest.importorskip("docx")
    import io

    import docx

    from cae import labdoc
    g = labdoc.guide_docx("lab17")
    t = labdoc.report_template_docx("lab17")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "挂牌上锁" in text and "任务 5" in text and "比对模式" in text
    src = open(__import__("hub.course", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert '"id": "lab17"' in src
