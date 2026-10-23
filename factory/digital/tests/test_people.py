# -*- coding: utf-8 -*-
"""第 18 轮 E4：人员与组织——车间“要有人”（缺人停、学徒 60%）、员工档案与技能矩阵、排班与出勤、缺口 → H2 → 四个方案、
调班 / 加班顶班 / 技能培训动作、态势与报告、AI 代理三个新工具、实验 19 自动评分、员工档案进 ERPNext 的提议。"""
import datetime as dt
import os

import pytest

from tests.test_agent import NoLLM

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
TEA = {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
LEAD = {"name": "学生班组长", "role": "lead", "teacher": False, "mode": "teach"}
LEAD2 = {"name": "学生班组长乙", "role": "lead", "teacher": False, "mode": "teach"}
PLN = {"name": "学生计划", "role": "planner", "teacher": False, "mode": "teach"}
OPR = {"name": "学生操作工", "role": "operator", "teacher": False, "mode": "teach"}


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
        H, eng = EV.sandbox(DSN, name="wq_people_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    H.mes = FakeMes()
    return H, eng


def _gap(db):
    return db.one("select * from anomaly where mode='teach' and rule='H2' and status in ('open','ack','doing') order by id limit 1")


# ---------------------------------------------------------------- 车间“要有人”
def test_staffing_shifts():
    from zoneinfo import ZoneInfo

    from sim import staffing as STF
    tz = ZoneInfo("America/New_York")
    t = dt.datetime(2026, 10, 21, 3, 0, tzinfo=tz)
    assert STF.shift_of(t) == (dt.date(2026, 10, 20), "night")                     # 半夜 3 点算前一天的晚班
    assert STF.shift_of(t.replace(hour=7)) == (dt.date(2026, 10, 21), "day")
    assert STF.next_change(t.replace(hour=7)).hour == 18
    s = STF.Staffing(True, {"2026-10-21|day|grd-01": 0, "2026-10-21|day|hob-01": 1})
    assert s.level("grd-01", t.replace(hour=9)) == 0 and s.level("hob-01", t.replace(hour=9)) == 1
    assert s.level("vmc-01", t.replace(hour=9)) == 2 and s.level("qc-01", t.replace(hour=9)) == 2      # 没下发的按有人；检验台不需要人
    assert STF.Staffing(False, {"2026-10-21|day|grd-01": 0}).level("grd-01", t.replace(hour=9)) == 2
    assert STF.Staffing.from_dict(s.to_dict()).levels == s.levels


def test_engine_no_staff_blocks_start_and_apprentice_is_slower():
    from sim import staffing as STF
    from tests_helpers import make_engine
    res = {}
    for lv in (2, 1, 0):
        eng, clock, out = make_engine(auto=True)
        local = eng.factory_dt(0).astimezone(eng.calendar.tzi)
        d, sh = STF.shift_of(local)
        keys = {"{}|{}|{}".format((d + dt.timedelta(days=i)).isoformat(), s, "saw-01"): lv for i in (-1, 0, 1, 2) for s in ("day", "night")}
        eng.set_staffing({"enabled": True, "levels": keys})
        eng.at(0, "release", work_order="WO-T", item="SH-301", qty=60)
        for _ in range(90):
            clock.t += 60
            eng.run_due()
        m = eng.machines["saw-01"]
        ends = [x for x in out if x[1]["type"] == "machine.event" and x[1]["data"].get("event") == "cycle_end" and "/saw-01/" in x[0]]
        res[lv] = (len(ends), m.no_staff)
    assert res[0][0] == 0 and res[0][1] is True                                      # 没人：一件也不做，停在“缺人”
    assert res[2][0] > res[1][0] > 0                                                  # 学徒慢
    eng, clock, out = make_engine(auto=True)
    snap = eng.snapshot()
    assert snap["staffing"]["enabled"] is False                                       # 默认关闭：和以前一样


# ---------------------------------------------------------------- 档案、技能、排班
def test_seed_employees_skills_posts(env):
    from hub import people as PE
    H, _ = env
    db = H.db
    es = PE.employees(db, "teach")
    assert len(es) == 30 and {e["dept"] for e in es} == {d for d, _ in PE.DEPTS}
    assert next(e for e in es if e["id"] == "P01")["shift"] == "day" and next(e for e in es if e["id"] == "P03")["shift"] == "night"
    assert {x["unit"] for x in PE.single_points(db, "teach")} == {"key-01", "hob-01", "hmc-01", "press-01"}
    m = PE.matrix(db, "teach")
    assert next(u for u in m["units"] if u["unit"] == "grd-01")["skilled"] == 2
    ro = PE.roster_for(db, "teach", PE.today(), "night")
    assert "hob-01" not in ro and ro["grd-01"]["emp_id"] == "P03"                   # 单点依赖的设备晚班不开
    assert PE.seed(db, "teach") is False


def test_leave_gap_levels_and_push(env):
    from hub import people as PE
    H, _ = env
    db = H.db
    g = [x for x in PE.gaps(db, "teach") if x["unit"] == "grd-01"]
    assert g and g[0]["emp_id"] == "P01" and "请假" in g[0]["why"]                  # 沙盘里王强下一个班请假
    d = dt.date.fromisoformat(g[0]["day"])
    lv = PE.levels(db, "teach", [d])
    assert lv["{}|{}|grd-01".format(g[0]["day"], g[0]["shift"])] == 0 and lv["{}|night|hob-01".format(g[0]["day"])] == 0
    n0 = len(H.mes.sent)
    PE.push(H, "teach")
    c = H.mes.sent[n0]
    assert c["command"] == "set_staffing" and c["enabled"] and c["replace"] and len(c["levels"]) == 9 * 2 * 11
    with pytest.raises(ValueError):
        PE.record_attendance(H, "teach", "P02", "sick")                               # 只记请假、迟到、缺勤，不记原因


def test_h2_anomaly_and_four_options(env):
    from hub import people as PE
    from hub.ont import plan as P
    H, _ = env
    a = _gap(H.db)
    assert a is not None and a["severity"] == "critical" and a["subject_key"] == "grd-01"
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    r = PE.options(H.db, "teach", a, st, ctx)
    kinds = [o["kind"] for o in r["options"]]
    assert kinds == ["none", "swap", "apprentice", "overtime"]
    sw = r["options"][1]
    assert sw["changes"][0]["type"] == "shift_swap" and sw["changes"][0]["emp_id"] == "P03" and "空出来" in sw["note"]
    ot = r["options"][3]
    assert any("加班顶班" in c["what"] and c["usd"] == 540 for c in ot["result"]["costs"])     # 12 小时 × $30 × 1.5
    assert r["recommended"] in ("B", "D") and not r["options"][0]["recommended"]


def test_plan_staff_change():
    from hub.ont import plan as P
    assert "staff" in P.CHANGE_TYPES


# ---------------------------------------------------------------- 动作
def test_swap_action_by_lead_fills_gap(env):
    from hub import people as PE
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    a = _gap(db)
    v = a["detail"]["values"]
    ch = {"type": "shift_swap", "day": v["day"], "shift": v["shift"], "unit": "grd-01", "emp_id": "P03"}
    with pytest.raises(AC.ActionError):
        AC.create(db, "teach", OPR, "shift_swap", ch)                                 # 操作工不能发起
    _, st, _ = H.plan_snaps.take("teach")
    tr = AC.trial(db, H.plan_snaps, "teach", [ch], st)
    assert tr["ok"]
    aid = AC.create(db, "teach", LEAD, "shift_swap", ch, None, a["id"], tr)
    AC.submit(db, aid, LEAD, tr)
    act = AC.get(db, aid)
    assert not AC.is_costly(act) and not AC.can_approve(PLN, act)[0] and AC.can_approve(LEAD2, act)[0]
    n0 = len(H.mes.sent)
    AC.approve(H, aid, LEAD2, LEAD2["name"])
    assert AC.get(db, aid)["status"] == "done"
    assert H.mes.sent[n0]["command"] == "set_staffing"
    d = dt.date.fromisoformat(v["day"])
    lv = PE.levels(db, "teach", [d])
    assert lv["{}|{}|grd-01".format(v["day"], v["shift"])] == 2
    assert lv["{}|night|grd-01".format(v["day"])] == 0                              # 张伟原来的晚班磨床空出来
    assert not [g for g in PE.gaps(db, "teach") if g["day"] == v["day"] and g["shift"] == v["shift"] and g["unit"] == "grd-01"]


def test_overtime_assign_costly_and_logged(env):
    from hub import people as PE
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    d = PE.today() + dt.timedelta(days=3)
    ch = {"type": "overtime_assign", "day": d.isoformat(), "shift": "night", "unit": "hob-01", "emp_id": "P02", "minutes": 600}
    aid = AC.create(db, "teach", PLN, "overtime_assign", ch, None, None, None)
    AC.submit(db, aid, PLN, None)
    act = AC.get(db, aid)
    assert AC.is_costly(act) and not AC.can_approve(LEAD, act)[0]
    AC.approve(H, aid, TEA, TEA["name"])
    assert PE.levels(db, "teach", [d])["{}|night|hob-01".format(d.isoformat())] == 2
    assert PE.overtime_week(db, "teach", d).get("P02") == 10.0
    with pytest.raises(ValueError):
        PE.exec_overtime(H, "teach", dict(ch, emp_id="P23", unit="grd-01"), TEA)      # 学徒不能加班顶班


def test_skill_training_and_single_points(env):
    from hub import people as PE
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    a = db.one("select * from anomaly where mode='teach' and rule='H1' and subject_key='key-01'")
    r = PE.training_options(db, "teach", a)
    ch = r["options"][0]["changes"][0]
    assert ch["type"] == "skill_training" and ch["emp_id"] == "P14" and r["options"][0]["result"]["cost_total"] == 1500
    tr = AC.trial(db, H.plan_snaps, "teach", [ch])
    aid = AC.create(db, "teach", LEAD, "skill_training", ch, None, a["id"], tr)
    AC.submit(db, aid, LEAD, tr)
    AC.approve(H, aid, TEA, TEA["name"])
    t = db.one("select * from skill_training where action_id=%s", (aid,))
    assert t["status"] == "doing" and PE.skills(db, "teach")[("P14", "key-01")] == 1
    db.x("update skill_training set started_at = now() - interval '3 hours' where id=%s", (t["id"],))
    got = PE.tick(H, "teach")
    assert t["id"] in got["passed"] and PE.skills(db, "teach")[("P14", "key-01")] == 2
    assert "key-01" not in {x["unit"] for x in PE.single_points(db, "teach")}
    with pytest.raises(ValueError):
        PE.exec_training(H, "teach", {"emp_id": "P14", "unit": "key-01"}, TEA)        # 已经会了


def test_simulator_attendance_once_per_shift(env):
    import random

    from hub import people as PE
    H, _ = env
    db = H.db

    class R(random.Random):
        def random(self):
            return 0.05                                                               # 都迟到
    st = PE._state(db, "teach")
    st.pop("att", None)
    PE._save_state(db, "teach", st)
    got = PE.tick(H, "teach", rng=R(1))
    assert got["late"] and not got["absent"]
    assert PE.tick(H, "teach", rng=R(1))["late"] == []                               # 这一班不再来
    assert PE.tick(H, "prod") == {"absent": [], "late": [], "passed": []}


# ---------------------------------------------------------------- 态势、报告、档案进 ERPNext
def test_kpis_situation_report(env):
    from hub import people as PE
    from hub.ont import report as RP
    from hub.ont import situation as SI
    H, _ = env
    k = PE.kpis(H.db, "teach")
    assert k["enabled"] and k["single_points"] == 3 and k["overtime_h_week"] >= 0
    now = dt.datetime.now(dt.timezone.utc)
    sit = SI.cards(H.db, H.ai.detector(), "teach", now)
    card = next(c for c in sit["cards"] if c["domain"] == "people")
    assert card["waiting"] is None and {m["key"] for m in card["metrics"]} == {"attendance", "gaps", "single_points", "overtime_h"}
    assert {"H1", "H5"} <= set(card["rules_live"])
    d = RP.build(H.db, "teach", "daily", now - dt.timedelta(days=1), now)
    assert d["people"] is not None and d["people"]["absences"] >= 1


def test_ensure_setup_proposal(env):
    from hub import people as PE
    H, _ = env
    pid = PE.ensure_setup(H, "teach")
    pv = H.db.one("select preview from ai_proposal where proposal_id=%s", (pid,))["preview"]
    assert len(pv["employees"]) == 30 and len(pv["departments"]) == 7 and "phone" in pv["employees"][0]
    assert PE.ensure_setup(H, "teach") == pid


def test_on_shift_holder_preferred(env):
    from hub import people as PE
    H, _ = env
    on = PE.on_shift_ids(H.db, "teach")
    d, sh = PE.now_shift()
    assert ("P06" in on) == (sh == "day") and ("P07" in on) == (sh == "night")


# ---------------------------------------------------------------- AI 代理
def test_agent_people_tools_and_intent(env):
    from hub.ont.agent import Agent, Rules, Run, Tools
    H, _ = env
    t = Tools(H, TEA, Run(TEA))
    s = t.people_skills()
    assert len(s["skills"]) == 11 and "hob-01" in s["single_points"]
    assert t.people_skills("grd-01")["skills"][0]["skilled"] == 2 and t.people_skills("qc-01").get("error")
    g = t.roster_gaps()
    assert "roster_gaps" in g and g["enabled"]
    # 本周确有一笔加班（前面的测试记在“今天 + 3 天”，周四以后会落到下周，所以这里自己记一笔今天的）
    from hub import people as PE
    H.db.x("insert into overtime_log (mode, day, emp_id, minutes, action_id) values (%s,%s,%s,%s,%s)", ("teach", PE.today(), "P02", 60, None))
    o = t.overtime_load()
    assert o["limit_h"] == 12 and any(x["emp_id"] == "P02" for x in o["overtime"])
    r = Rules(None, False)
    assert r.intent("这两天排班有没有缺人？") == "people" and r.intent("哪些设备只有一个人会开？") == "people"
    assert r.intent("服务工程师的排班怎么样？") != "people"
    out = Agent(H, NoLLM()).ask(LEAD, [{"role": "user", "content": "这两天排班有没有缺人？"}])
    assert out["answer"].startswith("提示") and not out["tools"]


# ---------------------------------------------------------------- 实验 19
def test_lab19_flow(env):
    from hub import lab19
    from hub import people as PE
    from hub.ont import actions as AC
    H, _ = env
    db = H.db
    U = {"name": "学生班组长丙", "role": "lead", "teacher": False, "mode": "teach"}
    with pytest.raises(PermissionError):
        lab19.inject(H, U, {})
    r = lab19.inject(H, TEA, {"enable": True, "emp_id": "P28"})                     # 田野：立加 + 卧加
    g = lab19.gap(db)
    assert g["emp_id"] == "P28" and g["unit"] in ("vmc-01", "hmc-01") and "请假" in r["text"]
    H.ai.detector().run("teach", dt.datetime.now(dt.timezone.utc))
    assert not lab19.locked(db, U)
    lab19.start(db, U["name"])
    assert lab19.locked(db, U) and not lab19.locked(db, TEA)
    sp = [x["unit"] for x in PE.single_points(db, "teach")]
    assert lab19.answer(db, U["name"], "l19_t1", {"units": sp})["score"] == 10
    assert lab19.answer(db, "学生丁", "l19_t1", {"units": ["grd-01"]})["score"] == 0
    parts = 12 * 60 // lab19.STD_MIN[g["unit"]]
    assert lab19.answer(db, U["name"], "l19_t2", {"hours": 12, "parts": parts})["score"] == 15
    best = lab19._system_choice(db, g)
    assert lab19.answer(db, U["name"], "l19_t3", {"option": best, "reason": "调人不花钱，订单交期不受影响，他原来的班要另外安排"})["score"] == 10
    assert not lab19.locked(db, U)
    # 任务 4：调班（学徒或熟练都行）→ 批准 → 这一班有人
    free, cross, appr = PE._candidates(db, "teach", dt.date.fromisoformat(g["day"]), g["shift"], g["unit"])
    who = (free or cross or appr)[0]["emp_id"]
    ch = {"type": "shift_swap", "day": g["day"], "shift": g["shift"], "unit": g["unit"], "emp_id": who}
    aid = AC.create(db, "teach", U, "shift_swap", ch, None, None, None)
    AC.submit(db, aid, U, None)
    assert next(t for t in lab19.check(db, U["name"])["tasks"] if t["id"] == "l19_t4")["score"] == 5
    AC.approve(H, aid, TEA, TEA["name"])
    assert next(t for t in lab19.check(db, U["name"])["tasks"] if t["id"] == "l19_t4")["score"] == 15
    # 任务 5：每台单点依赖的设备一个技能培训
    names = {"hob-01": "P22", "hmc-01": "P18", "press-01": "P20", "key-01": "P15"}
    for u in PE._state(db, "teach")["lab19_single"]:
        c = {"type": "skill_training", "emp_id": names[u], "unit": u, "hours": 40}
        x = AC.create(db, "teach", U, "skill_training", c, None, None, None)
        AC.submit(db, x, U, None)
    st = lab19.check(db, U["name"])
    assert st["score"] == 60 == st["of"] and st["report_points"] == 40
    assert any(c["user"] == U["name"] for c in lab19.class_view(db))


def test_reset_turns_staffing_off(env):
    from hub import people as PE
    H, _ = env
    db = H.db
    PE.reset(db, "teach")
    assert PE.enabled(db, "teach") is False
    assert db.one("select count(*) as n from attendance where mode='teach'")["n"] == 0
    assert {x["unit"] for x in PE.single_points(db, "teach")} == {"key-01", "hob-01", "hmc-01", "press-01"}


def test_lab19_documents_and_course():
    pytest.importorskip("docx")
    import io

    import docx

    from cae import labdoc
    g = labdoc.guide_docx("lab19")
    t = labdoc.report_template_docx("lab19")
    assert g[:2] == b"PK" and t[:2] == b"PK" and len(g) > 8000
    text = "\n".join(p.text for p in docx.Document(io.BytesIO(g)).paragraphs)
    assert "技能矩阵" in text and "任务 5" in text and "比对模式" in text
    src = open(__import__("hub.course", fromlist=["x"]).__file__, encoding="utf-8").read()
    assert '"id": "lab19"' in src
