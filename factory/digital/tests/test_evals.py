# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 2 步：AI 代理评测集——规则版每次推送全过。"""
import pytest

from tests.test_agent import NoLLM


def test_eval_set_loads_30_unique_items():
    from hub.ont import evals as EV
    items = EV.load()
    assert len(items) >= 30
    assert {x.get("as", "teacher") for x in items} >= {"teacher", "student"}
    assert len({x["domain"] for x in items}) >= 7


def test_rules_engine_passes_every_eval():
    """与服务器上“评测”按钮同一条路：临时库里载入实验 7 情景，逐题问规则版"""
    import os
    from hub.ont import evals as EV
    from hub.ont.agent import Agent
    pytest.importorskip("psycopg")
    dsn = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
    try:
        H, eng = EV.sandbox(dsn, name="wq_eval_test", llm=NoLLM())
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    res = EV.run(Agent(H, NoLLM()), H.db, engine="rules")
    bad = ["{} {}：{} —— {}".format(x["id"], x["q"], "；".join(x["why"]), x["answer"][:160]) for x in res["results"] if not x["ok"]]
    assert not bad, "\n".join(bad)
    row = H.db.one("select passed, total from ai_eval_run where id=%s", (res["id"],))
    assert row["passed"] == row["total"] == res["total"]


def test_grader_catches_wrong_answers():
    from hub.ont import evals as EV
    it = {"tools": ["impact"], "contains": ["{late_so}"], "not_contains": ["GRD-01"]}
    r = {"answer": "GRD-01 停了 [1]。", "tools": ["metrics"], "check": {"ok": True, "unverified": [], "bad_refs": []}, "actions": []}
    why = EV.grade(it, r, {"late_so": "SAL-ORD-2026-00019"})
    assert len(why) == 3
    r2 = {"answer": "已起草 [1]", "tools": [], "check": {"unverified": [{"sentence": "x", "numbers": ["999"]}], "bad_refs": [4]}, "actions": ["7"]}
    why2 = EV.grade({}, r2, {})
    assert any("不该起草" in w for w in why2) and any("999" in w for w in why2) and any("无效" in w for w in why2)
