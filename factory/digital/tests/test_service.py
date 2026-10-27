# -*- coding: utf-8 -*-
"""第 18 轮 E1：客户与服务——合同条款、投诉 → 异常、追溯与排查范围、派工估算、服务动作与审批、教学模拟器、
客户通知（教学只记录）、态势卡与报告、AI 代理三个新工具、实验 16 自动评分。"""
import datetime as dt
import os

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
SVC = {"name": "学生售后", "role": "service", "teacher": False, "mode": "teach"}
SVC2 = {"name": "学生售后乙", "role": "service", "teacher": False, "mode": "teach"}
PLN = {"name": "学生计划", "role": "planner", "teacher": False, "mode": "teach"}


@pytest.fixture(scope="module")
def env():
    pytest.importorskip("psycopg")
    from hub.ont import evals as EV
    try:
        H, eng = EV.sandbox(DSN, name="wq_service_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    return H, eng


def _complaint(db):
    return db.one("select * from complaint where mode='teach' order by id limit 1")


def _c1(db, c):
    return db.one("select * from anomaly where mode='teach' and rule='C1' and detail->'values'->>'complaint'=%s", ("CP-{:05d}".format(c["id"]),))


def _advance(db, days):
    db.x("update field_clock set anchor_day=anchor_day + %s, paused=true where mode='teach'", (int(days),))


# ---------------------------------------------------------------- 合同条款
def test_contract_terms_drive_penalty_and_warranty(env):
    from factory import data as F
    from hub import crm
    H, _ = env
    rows = crm.contracts(H.db, "teach")
    assert len([c for c in rows if c["name"].startswith("CON-DEMO-")]) == 6
    summit = crm.terms_for(H.db, "teach", F.CUSTOMERS[1])
    assert summit["penalty_per_day"] == 200 and summit["warranty_months"] == 18
    pm = crm.penalty_map(H.db, "teach", [{"name": "SAL-ORD-2026-00019", "customer": F.CUSTOMERS[1]},
                                         {"name": "SAL-ORD-2026-00020", "customer": F.CUSTOMERS[2]}])
    assert pm == {"SAL-ORD-2026-00019": 200.0}                        # 推演的违约金读合同，不再写死
    assert crm.response_h(H.db, "teach", "东港码头 · 散货输送线") == 12
    assert crm.response_h(H.db, "teach", "没有合同的客户") == crm.DEFAULT_RESPONSE_H
    wu = crm.warranty_until(H.db, "teach", "东港码头 · 散货输送线", "2025-03-10")
    assert wu == dt.date(2027, 3, 10)                                  # 24 个月


# ---------------------------------------------------------------- 投诉 → C1 → 追溯链
def test_complaint_becomes_anomaly_with_field_chain(env):
    from hub import service as SV
    H, _ = env
    c = _complaint(H.db)
    assert c and c["serial"] and c["note"].startswith("proposal:")
    a = _c1(H.db, c)
    assert a is not None and a["subject_type"] == "FieldUnit" and a["subject_key"] == c["serial"]
    bad, others = SV.scope_units(H.db, "teach", a)
    assert bad == [c["serial"]] and len(others) >= 1                  # 同一片砂轮磨的轴还装在别的设备上
    p = H.db.one("select action, status from ai_proposal where proposal_id=%s", (c["note"].split(":", 1)[1],))
    assert p["action"] == "complaint_issue"                            # 进 ERPNext（Issue）走提议，自动确认


def test_service_options_estimate_and_recommend(env):
    from hub import service as SV
    H, _ = env
    a = _c1(H.db, _complaint(H.db))
    r = SV.anomaly_options(H.db, "teach", a)
    assert [o["kind"] for o in r["options"]] == ["repair_one", "repair_plus_check", "batch_check"]
    for o in r["options"]:
        s = o["service"]
        assert s["cost"]["total"] == pytest.approx(s["cost"]["labor"] + s["cost"]["travel"] + s["cost"]["parts"])
        assert s["cost"]["total"] == pytest.approx(s["cost"]["warranty"] + s["cost"]["billable"])
        types = [c["type"] for c in o["changes"]]
        assert types[0] == "service_batch" and ("customer_notice" in types) == (o["kind"] != "repair_one")
        if s["spares"]:
            assert "spare_ship" in types
    best = next(o for o in r["options"] if o["recommended"])
    assert not best["uncovered_high"]                                 # 推荐的方案不漏高风险设备
    assert r["recommended"] == best["key"] and "备件" in r["reason"]
    one = r["options"][0]["service"]
    assert one["units"] == 1 and one["cost"]["labor"] in (SV.LABOR_PER_JOB, 2 * SV.LABOR_PER_JOB)


def test_plan_jobs_respects_capacity(env):
    from hub import service as SV
    H, _ = env
    us = SV.units(H.db, "teach")
    north = [s for s, u in us.items() if u["region"] == "北部"]
    wanted = [{"serial": north[i % len(north)], "kind": "inspect", "region": "北部"} for i in range(9)]
    start = SV.field_today(H.db, "teach")
    plan = SV.plan_jobs(H.db, "teach", wanted, start)
    per = {}
    for p in plan:
        assert p["day"] and dt.date.fromisoformat(p["day"]).weekday() < 5     # 周末不排
        per.setdefault((p["engineer"], p["day"]), []).append(p)
    for (e, d), ps in per.items():
        assert len(ps) <= (1 if ps[0]["other_region"] else SV.SAME_REGION_PER_DAY)
    assert any(p["other_region"] for p in plan) or len({p["day"] for p in plan}) > 1


# ---------------------------------------------------------------- 服务动作与审批
def test_service_actions_permissions_and_execution(env):
    from hub import service as SV
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    c = _complaint(db)
    a = _c1(db, c)
    r = SV.anomaly_options(db, "teach", a)
    b = next(o for o in r["options"] if o["kind"] == "repair_plus_check")
    sb = next(x for x in b["changes"] if x["type"] == "service_batch")
    nt = next(x for x in b["changes"] if x["type"] == "customer_notice")
    with pytest.raises(AC.ActionError):
        AC.create(db, "teach", PLN, "service_batch", sb)              # 计划员不能发起服务动作
    tr = AC.trial(db, H.plan_snaps, "teach", [sb])
    assert tr["sales_orders"] == [] and tr["ok"] and tr["cost_total"] > 0
    aid = AC.create(db, "teach", SVC, "service_batch", sb, None, a["id"], tr)
    nid = AC.create(db, "teach", SVC, "customer_notice", nt, None, a["id"], AC.trial(db, H.plan_snaps, "teach", [nt]))
    act = db.one("select * from action where id=%s", (aid,))
    assert AC.is_costly(act) and not AC.can_approve(SVC2, act)[0]    # 多台派工花钱：只有厂长能批
    note = db.one("select * from action where id=%s", (nid,))
    assert not AC.is_costly(note) and AC.can_approve(SVC2, note)[0]
    assert not AC.can_approve(SVC, note)[0]                           # 不能批自己发起的
    for x in (aid, nid):
        AC.submit(db, x, SVC, None)
    AC.approve(H, aid, TEA, TEA["name"])
    AC.approve(H, nid, SVC2, SVC2["name"])
    act = db.one("select * from action where id=%s", (aid,))
    assert act["status"] in ("executing", "done"), act
    jobs = db.q("select * from service_job where action_id=%s", (aid,))
    assert len(jobs) == len(sb["jobs"]) and all(j["engineer"] and j["day"] for j in jobs)
    assert db.one("select action from ai_proposal where proposal_id=%s", (jobs[0]["proposal_id"],))["action"] == "service_orders"
    assert db.one("select status from complaint where id=%s", (c["id"],))["status"] == "doing"
    n = db.q("select * from customer_notice where action_id=%s", (nid,))
    assert n and all(x["status"] == "recorded" for x in n)            # 教学模式只记录，不发邮件
    assert db.one("select status from action where id=%s", (nid,))["status"] == "done"


def test_single_in_warranty_job_is_not_costly():
    from hub.ont import actions as AC
    a = {"type": "service_batch", "params": {"jobs": [{"serial": "X", "kind": "inspect"}], "in_warranty": True}}
    assert not AC.is_costly(a)
    assert AC.is_costly(dict(a, params=dict(a["params"], in_warranty=False)))


# ---------------------------------------------------------------- 教学模拟器：上门完工、回访、关投诉
def test_simulator_completes_jobs_and_scores_follow_ups(env):
    from hub import service as SV
    H, _ = env
    db = H.db
    planned = db.q("select * from service_job where mode='teach' and status='planned'")
    assert planned, "上一个测试应该派了工"
    last = max(j["day"] for j in planned)
    _advance(db, (last - SV.field_today(db, "teach")).days + 2)
    done = SV.tick(H, "teach")
    assert set(done["jobs"]) >= {j["id"] for j in planned}
    assert not db.q("select id from service_job where mode='teach' and status='planned' and day <= %s", (last,))
    c = _complaint(db)
    assert db.one("select status from complaint where id=%s", (c["id"],))["status"] == "closed"     # 服务做完自动关闭
    _advance(db, 2)
    SV.tick(H, "teach")
    sat = SV.satisfaction(db, "teach")
    assert sat["n"] >= 1 and 1 <= sat["avg"] <= 5
    k = SV.kpis(db, "teach")
    assert k["surveys"] >= 1 and k["warranty_cost"] >= 0 and k["open_jobs"] == 0


def test_notice_prod_without_email_is_kept_as_record(env):
    from hub import service as SV
    H, _ = env
    rows = SV.notice(H, "prod", ["东港码头 · 散货输送线"], "厂长", send=True, emails={})
    assert rows[0]["status"] == "recorded"                            # 没有邮箱：不发，记录下来请人工联系


# ---------------------------------------------------------------- AI 代理的三个新工具
def test_agent_customer_tools(env):
    from hub.ont.agent import Run, Tools
    H, _ = env
    t = Tools(H, TEA, Run(TEA))
    r = t.customer_360("港口")
    assert r["customer"].startswith("东港码头") and r["contract"]["response_h"] == 12 and r["counts"]["units"] >= 1
    assert t.customer_360("不存在的客户").get("error")
    c = _complaint(H.db)
    s = t.complaint_scope(complaint="CP-{:05d}".format(c["id"]))
    assert s["serial"] == c["serial"] and s["check_units"] and s["chain"]["summary"]
    e = t.service_estimate([c["serial"]], "inspect")
    assert e["units"] == 1 and e["days"] >= 1 and e["cost"]["total"] > 0
    assert t.service_estimate(["没有这台"]).get("error")


def test_agent_intents_and_student_hints(env):
    from hub.ont.agent import Agent, Rules
    H, _ = env
    r = Rules(None, False)
    assert r.intent("港口客户最近怎么了？") == "customer"
    assert r.intent("CP-00001 这批轴还装在谁家？") == "complaint"
    assert r.intent("派工程师上门点检要几天？") == "service"
    assert r.intent("SAL-ORD-2026-00019 为什么会晚？") == "late"             # 原有的问题不受影响
    stu = dict(SVC)
    out = Agent(H, NoLLM()).ask(stu, [{"role": "user", "content": "这批轴还装在谁家？"}])
    assert out["answer"].startswith("提示") and not out["tools"]


# ---------------------------------------------------------------- 态势卡、报告
def test_situation_and_report_have_service_section(env):
    from hub.ont import report as RP
    H, _ = env
    from hub.ont import situation as SI
    now = dt.datetime.now(dt.timezone.utc)
    d = RP.build(H.db, "teach", "day", now - dt.timedelta(days=1), now)
    data = d.get("data", d)
    assert data.get("service") is not None
    _ = SI


# ---------------------------------------------------------------- 批次投诉注入 + 实验 16
def test_inject_batch_then_lab16_scoring(env):
    from hub import lab16
    from hub import service as SV
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    SVC = {"name": "学生售后丙", "role": "service", "teacher": False, "mode": "teach"}
    with pytest.raises(PermissionError):
        lab16.inject(H, SVC, {})
    r = lab16.inject(H, TEA, {"n": 3})
    assert len(r["units"]) >= 2 and r["wheel"].startswith("grd-01/")
    _advance(db, 3)
    got = SV.tick(H, "teach")["complaints"]
    assert len(got) >= 2
    c = db.one("select * from complaint where id=%s", (got[0],))
    # 比对模式
    assert not lab16.locked(db, SVC)
    lab16.start(db, SVC["name"])
    assert lab16.locked(db, SVC) and not lab16.locked(db, TEA)
    # 任务 1：按系统追溯答
    t = lab16.trace(db, c["serial"])
    r1 = lab16.answer(db, SVC["name"], "l16_t1", {"complaint_id": c["id"], "units": t["units"], "wheel": t["wheels"][0] if t["wheels"] else None})
    assert r1["score"] == 15, r1
    assert lab16.answer(db, "学生丙", "l16_t1", {"complaint_id": c["id"], "units": [], "wheel": "grd-01/S9"})["score"] == 3
    # 任务 2：高风险
    us = SV.units(db, "teach")
    high = [s for s in t["units"] if s in us and SV.is_high(us[s])]
    assert lab16.answer(db, SVC["name"], "l16_t2", {"units": high})["score"] == 10
    # 任务 3：理由太短不行；选推荐的方案提交，比对模式解除
    from hub.ont import anomaly as A
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    _ = A
    a = lab16._anomaly_for(db, c)
    assert lab16.answer(db, SVC["name"], "l16_t3", {"option": "B", "reason": "短"})["score"] == 0
    ev = SV.anomaly_options(db, "teach", a)
    best = ev["recommended"]
    r3 = lab16.answer(db, SVC["name"], "l16_t3", {"option": best, "reason": "费用比整批排查低，高风险的设备都覆盖到了，客户只通知两家"})
    assert r3["score"] == 10 and not lab16.locked(db, SVC)
    # 任务 4：起草、提交、批准
    o = next(x for x in ev["options"] if x["key"] == best)
    ids = []
    for ch in o["changes"]:
        if ch["type"] in ("service_batch", "customer_notice"):
            ids.append((ch["type"], AC.create(db, "teach", SVC, ch["type"], ch, None, a["id"], AC.trial(db, H.plan_snaps, "teach", [ch]))))
    for _t, x in ids:
        AC.submit(db, x, SVC, None)
    assert next(t for t in lab16.check(db, SVC["name"])["tasks"] if t["id"] == "l16_t4")["score"] in (6, 8)
    for _t, x in ids:
        AC.approve(H, x, TEA, TEA["name"])
    s4 = next(t for t in lab16.check(db, SVC["name"])["tasks"] if t["id"] == "l16_t4")["score"]
    assert s4 >= 11                                                   # 派工执行（或执行中）+ 通知完成
    # 任务 5：上门完工、回访打分
    assert lab16.answer(db, SVC["name"], "l16_t5", {"bucket": lab16.BUCKETS[0]})["score"] == 0
    last = db.one("select max(day) as d from service_job where mode='teach' and status='planned'")["d"]
    _advance(db, (last - SV.field_today(db, "teach")).days + 3)
    SV.tick(H, "teach")
    _advance(db, 2)
    SV.tick(H, "teach")
    st = lab16.status(db, SVC["name"])
    acts = [x["id"] for x in lab16._my_actions(db, SVC["name"]) if x["type"] == "service_batch"]
    sc = [float(x["score"]) for x in db.q("select f.score from follow_up f join service_job j on j.id=f.job_id where j.action_id = any(%s) "
                                          "and f.score is not null", (acts,))]
    avg = sum(sc) / len(sc)
    right = lab16.BUCKETS[0] if avg >= 4.5 else (lab16.BUCKETS[1] if avg >= 3.5 else lab16.BUCKETS[2])
    assert lab16.answer(db, SVC["name"], "l16_t5", {"bucket": right})["score"] == 10
    st = lab16.check(db, SVC["name"])
    assert st["of"] == 60 and st["report_points"] == 40 and st["score"] >= 56
    assert any(x["user"] == SVC["name"] for x in lab16.class_view(db))


def test_lab16_documents():
    pytest.importorskip("docx")
    import io

    import docx

    from cae import labdoc
    g = labdoc.guide_docx("lab16")
    t = labdoc.report_template_docx("lab16")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "比对模式" in text and "任务 5" in text and "排查范围" in text
