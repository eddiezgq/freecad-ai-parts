# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 1 步：AI 代理——工具、引用、数字核对、运行记录、规则版十类问题、教学模式、只起草不执行。"""
import datetime as dt
import json
import os
import types

import pytest

import wqbus

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]
NOW = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


class NoLLM:
    name = "rules"

    def available(self):
        return False


class FakeSnaps:
    def __init__(self, db, eng):
        self.db, self.eng = db, eng

    def take(self, mode, timeout=5.0):
        from psycopg.types.json import Jsonb
        st = json.loads(json.dumps(self.eng.snapshot()))
        r = self.db.one("insert into sim_snapshot (mode, ts, exact, state) values (%s, now(), true, %s) returning id", (mode, Jsonb(st)))
        return r["id"], st, True


@pytest.fixture(scope="module")
def env():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_agent_test with (force)")
            c.execute("create database wq_agent_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.ai import Assistant
    from hub.db import DB
    from hub.historian import Historian
    from hub.ont import actions as AC
    from hub.ont import agent as AG
    from hub.ont import plan as P
    from hub.ont.store import Store
    from hub.ont.sync import Sync
    from sim import scenario
    from tests_helpers import make_engine
    db = DB(BASE + "/wq_agent_test")
    db.init()
    P.init(db)
    AC.init(db)
    AG.init(db)
    h = Historian(db)
    eng, clock, _ = make_engine(auto=False)
    clock.t = scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    s = Sync(db, Store(db))
    s.init()
    s.replay()
    ai = Assistant(db, lambda *a: None, NoLLM())
    ai.detector().run("teach", NOW)
    H = types.SimpleNamespace(db=db, ai=ai, plan_snaps=FakeSnaps(db, eng), mes=None)
    return H, eng


def _u(name="王老师", role="manager", teacher=True, mode="teach"):
    return {"name": name, "role": role, "teacher": teacher, "mode": mode}


def _ask(H, q, u=None, llm=None, locked=None):
    from hub.ont.agent import Agent
    return Agent(H, llm or NoLLM(), locked=locked).ask(u or _u(), [{"role": "user", "content": q}])


def _down(db):
    return db.one("select * from anomaly where rule='P1' and subject_key='grd-01' and status in ('open','ack','doing')")


# ---------------------------------------------------------------- 数字核对
def test_number_check_flags_made_up_numbers_and_bad_refs():
    from hub.ont.agent import check_answer
    src = ['{"late_days": 1, "cost_total": 300.0, "oee": 0.8912, "down_s": 5400, "projected": "2026-10-08"}']
    ok = check_answer("晚 1 天 [1]，多花 $300 [2]，OEE 89%，停了 90 分钟（1.5 小时），预计 2026-10-08 交。", src, 2)
    assert ok["ok"], ok
    bad = check_answer("多花 $300 [1]。另外违约金 $999。", src, 1)
    assert not bad["ok"] and bad["unverified"][0]["numbers"] == ["999"]
    assert check_answer("见 [3]。", src, 2)["bad_refs"] == [3]


# ---------------------------------------------------------------- 规则版十类问题
QUESTIONS = [
    ("现在有哪些异常？", "anomalies", ["list_anomalies"]),
    ("外圆磨床停了影响什么？", "machine", ["impact", "compare_options"]),
    ("外圆磨床要是再停一天，哪张订单受影响？怎么办最划算？", "machine", ["compare_options"]),
    ("SAL-ORD-2026-00019 为什么会晚？", "late", ["metrics", "impact"]),
    ("本周瓶颈在哪？", "bottleneck", ["metrics"]),
    ("轴承 6207 够不够？", "material", ["metrics"]),
    ("质量怎么样？", "quality", ["metrics", "list_anomalies"]),
    ("GRD-01", "object", ["search_objects", "get_object"]),
    ("现在怎么样", "overview", ["metrics"]),
]


@pytest.mark.parametrize("q,intent,tools", QUESTIONS)
def test_rules_answer_with_citations_and_verified_numbers(env, q, intent, tools):
    from hub.ont.agent import Rules
    H, eng = env
    assert Rules(None, False).intent(q) == intent
    r = _ask(H, q)
    assert r["engine"] == "rules" and r["answer"] and "没答出来" not in r["answer"]
    assert set(tools) <= set(r["tools"]), r["tools"]
    assert r["refs"] and "[1]" in r["answer"]
    assert r["check"]["ok"], r["check"]
    run = H.db.one("select * from ai_run where id=%s", (r["run_id"],))
    assert run["question"] == q and [s["tool"] for s in run["steps"]] == r["tools"]


def test_handle_anomaly_compares_options_and_offers_draft(env):
    H, eng = env
    a = _down(H.db)
    r = _ask(H, "A-{:05d} 怎么处理？".format(a["id"]))
    assert "compare_options" in r["tools"] and "维修加急" in r["answer"] and r["check"]["ok"]
    sc = [x for x in r["refs"] if x["kind"] == "scenario"]
    assert len(sc) >= 2 and all(x["url"].startswith("/ont/sim?scenario=") for x in sc)
    assert H.db.one("select count(*) as n from scenario where created_by like 'AI 代理%%'")["n"] >= 2


def test_hypothetical_downtime_matches_breakdown_change(env):
    """“假如再停 N 分钟”：先改快照再推演，与在推演里加“假设停机”改动的结果一致"""
    from hub.ont import plan as P
    H, eng = env
    _, st, _ = H.plan_snaps.take("teach")
    ctx = P.context(H.db, "teach", dt.datetime.fromisoformat(st["factory_now"]))
    a = P.simulate(P.hypothesis(st, "grd-01", 1440), [], ctx)
    b = P.simulate(st, [{"type": "breakdown", "unit": "grd-01", "minutes": 1440}], ctx)
    base = P.simulate(st, [], ctx)
    fin = lambda r: r["work_orders"]["MFG-WO-2026-00016"]["finish"]           # noqa: E731
    assert fin(a) == fin(b) and fin(a) > fin(base)


def test_draft_only_never_submits_or_executes(env):
    H, eng = env
    a = _down(H.db)
    r = _ask(H, "起草 A-{:05d} 的方案 B".format(a["id"]))
    assert r["actions"], r["answer"]
    act = H.db.one("select * from action where id=%s", (int(r["actions"][0]),))
    assert act["status"] == "draft" and act["initiator"] == "王老师" and act["anomaly_id"] == a["id"]
    log = H.db.q("select kind from action_log where action_id=%s order by id", (act["id"],))
    assert [x["kind"] for x in log] == ["create", "agent"]


def test_student_gets_hints_not_answers(env):
    from hub.ont.agent import Agent
    H, eng = env
    stu = _u("学生甲", "planner", teacher=False)
    a = _down(H.db)
    for q in ["现在有哪些异常？", "外圆磨床停了影响什么？", "A-{:05d} 怎么处理？".format(a["id"]), "SAL-ORD-2026-00019 为什么会晚？",
              "轴承 6207 够不够？"]:
        r = _ask(H, q, stu)
        assert r["answer"].startswith("提示"), r["answer"]
        assert "compare_options" not in r["tools"]
    r = _ask(H, "起草 A-{:05d} 的方案 B".format(a["id"]), stu)
    assert not r["actions"] and "不代做" in r["answer"]
    names = [t["name"] for t in Agent(H, NoLLM()).tools_for(stu)]
    assert "draft_action" not in names and "propose_order" not in names


class FakeLLM:
    """测试替身模型：先调两个工具，再回答——其中一句编了一个数字"""
    name = "fake:test"

    def available(self):
        return True

    def run(self, system, messages, tools, call_tool, max_turns=6):
        assert "[n]" in system and any(t["name"] == "compare_options" for t in tools)
        a = call_tool("list_anomalies", {})
        down = next(x for x in a["anomalies"] if x["rule"] == "P1")
        o = call_tool("compare_options", {"anomaly_id": down["id"]})
        best = next(x for x in o["options"] if x.get("recommended"))
        return ("{} 停机 [{}]。建议 {}，多花 ${:,.0f} [{}]。\n另外估计还会损失 $12345。".format(
            down["key"], down["ref"], best["label"], best["cost_total"], best["ref"]), [])


def test_model_answer_is_checked_and_recorded(env):
    H, eng = env
    r = _ask(H, "磨床停了怎么办？", llm=FakeLLM())
    assert r["engine"] == "fake:test" and r["tools"] == ["list_anomalies", "compare_options"]
    assert not r["check"]["ok"] and r["check"]["unverified"][0]["numbers"] == ["12345"]
    run = H.db.one('select "check", engine from ai_run where id=%s', (r["run_id"],))
    assert run["engine"] == "fake:test" and run["check"]["ok"] is False


def test_compare_mode_hides_recommendation(env):
    H, eng = env
    a = _down(H.db)
    r = _ask(H, "A-{:05d} 怎么处理？".format(a["id"]), locked=lambda u, aid=None: True)
    step = H.db.one("select steps from ai_run where id=%s", (r["run_id"],))["steps"]
    out = next(s["output"] for s in step if s["tool"] == "compare_options")
    assert "reason" not in out and all("recommended" not in o for o in out["options"]) and "比对模式" in out["note"]
