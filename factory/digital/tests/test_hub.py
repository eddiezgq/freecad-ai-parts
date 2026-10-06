# -*- coding: utf-8 -*-
"""枢纽的指标、算料、AI 规则回答：用独立的测试库，载入实验 7 情景后核对。需要本机 PostgreSQL（WQ_TEST_DB）。"""
import datetime as dt
import os

import pytest

import wqbus

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)     # 周二 10:30（纽约），月中


@pytest.fixture(scope="module")
def db():
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(base, autocommit=True) as c:
            c.execute("drop database if exists wq_test")
            c.execute("create database wq_test")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.historian import Historian
    from sim import scenario
    from tests_helpers import make_engine
    d = DB(DSN)
    d.init()
    h = Historian(d)
    eng, clock, _ = make_engine(auto=False)
    scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    return d


def test_overview_reflects_scenario(db):
    from hub import kpi
    ov = kpi.overview(db, NOW, "teach")
    grd = next(m for m in ov["machines"] if m["unit"] == "grd-01")
    assert grd["state"] == "down" and grd["reason"] == "换砂轮"
    k = {x["key"]: x for x in ov["kpis"]}
    assert abs(k["on_time"]["value"] - 11 / 12) < 1e-9
    assert 0 < k["oee"]["value"] < 1
    assert k["output"]["total"] >= 8
    so = {o["name"]: o for o in ov["orders"]}
    assert so["SAL-ORD-2026-00019"]["tone"] in ("warn", "bad")
    assert so["SAL-ORD-2026-00020"]["risk"].startswith("待排产")
    mat = {m["code"]: m for m in ov["materials"]}
    assert mat["BRG-6207"]["status"] == "低于安全库存"
    assert ov["quality"]["chart"]["points"] and ov["demo"]


def test_mrp_nets_stock_commitments_and_safety(db):
    from hub import mrp
    pv = mrp.plan_order(db, "示例·绿谷输送设备 GreenValley Conveyor (Demo)", "WQR-105", 10, "2026-10-15", now=NOW)
    rows = {r["item_code"]: r for r in pv["mrp"]}
    b = rows["BRG-6207"]
    assert b["gross"] == 20 and b["stock"] == 8 and b["safety"] == 10
    assert b["net"] == b["gross"] + b["committed"] + b["safety"] - b["stock"] - b["on_order"]
    mr = {m["item_code"]: m for m in pv["material_requests"]}
    assert mr["BRG-6207"]["qty"] % 10 == 0 and mr["BRG-6207"]["qty"] >= b["net"]
    assert pv["work_orders"] == [dict(pv["work_orders"][0], production_item="SH-301", qty=10)]
    assert {d["item_code"] for d in pv["deferred"]} >= {"SH-101", "GR-302"}


def test_rule_answers_cite_sources_and_teach_mode_does_not_do_the_work(db):
    from hub.ai import Assistant

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    sent = []
    a = Assistant(db, lambda *x: sent.append(x), NoLLM())
    r = a.chat([{"role": "user", "content": "SAL-ORD-2026-00019 为什么会延期？"}], mode="teach")
    assert r["answer"].startswith("提示")
    r = a.chat([{"role": "user", "content": "10 台 WQR-105，10 月 15 日交货"}], mode="teach")
    assert not r.get("proposals") and "不替你" in r["answer"]
    alerts = a.evaluate("teach", NOW)
    keys = {x["key"] for x in alerts}
    assert "down:grd-01" in keys and "stock:BRG-6207" in keys
    assert all(x["evidence"] for x in alerts if not x["key"].startswith("ncr:"))
    assert a.evaluate("teach", NOW) == []          # 两小时内不重复
