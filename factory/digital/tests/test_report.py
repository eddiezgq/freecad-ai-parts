# -*- coding: utf-8 -*-
"""第 17 轮 D 期第 4 步：厂情日报 / 经营周报——数字与看板、异常表、动作表逐项一致；定时；文字里的数字都有出处。"""
import datetime as dt
import json

from hub import kpi
from tests.test_agent import env  # noqa: F401  —— 实验 7 情景


def test_daily_numbers_match_dashboard_and_tables(env):  # noqa: F811
    from hub.ont import report as RP
    from hub.ont.agent import check_answer
    H, eng = env
    db = H.db
    RP.init(db)
    rid = RP.generate(db, "teach", "daily", by="王老师", notify=False)
    r = db.one("select * from report where id=%s", (rid,))
    d = r["data"]
    end = r["period_end"]
    ov = kpi.overview(db, end, "teach")
    k = {x["key"]: x for x in ov["kpis"]}
    assert d["kpis"]["oee"] == ov["oee"]["value"] and d["kpis"]["on_time"] == ov["on_time"]["value"]
    assert d["kpis"]["output_week"] == k["output"]["value"] and d["kpis"]["wip"] == ov["wip"]["now"]
    assert d["kpis"]["down_machines"] == ["GRD-01"]
    n_open = db.one("select count(*) as n from anomaly where mode='teach' and first_seen < %s and (closed_at is null or closed_at >= %s)", (end, end))["n"]
    n_new = db.one("select count(*) as n from anomaly where mode='teach' and first_seen >= %s and first_seen < %s", (r["period_start"], end))["n"]
    assert d["anomalies"]["open"] == n_open and d["anomalies"]["new"] == n_new and n_open > 0
    assert sum(v["open"] for v in d["anomalies"]["by_domain"].values()) == n_open
    n_act = db.one("select count(*) as n from action where mode='teach' and ((created_at >= %s and created_at < %s) or "
                   "(executed_at >= %s and executed_at < %s))", (r["period_start"], end, r["period_start"], end))["n"]
    assert d["actions"]["total"] == n_act
    assert [o["name"] for o in d["risk_orders"]] == [o["name"] for o in ov["orders"] if o["tone"] in ("bad", "warn")]
    assert "BRG-6207" in [m["code"] for m in d["low_materials"]]
    assert 1 <= len(d["focus"]) <= 3
    # 文字里的数字都在数据里
    chk = check_answer(r["text"], [json.dumps(d, ensure_ascii=False, default=str)], 0)
    assert not chk["unverified"], chk
    assert r["engine"] == "rules" and r["title"].startswith("厂情日报")


def test_weekly_has_trends_recurring_and_cost(env):  # noqa: F811
    from hub.ont import report as RP
    H, eng = env
    rid = RP.generate(H.db, "teach", "weekly", notify=False)
    d = H.db.one("select data from report where id=%s", (rid,))["data"]
    assert set(d) >= {"trends", "recurring", "rule_hits", "cost_top"}
    assert d["rule_hits"] and all(isinstance(v, int) for v in d["rule_hits"].values())
    for c in d["cost_top"]:
        assert c["work_order"].startswith("MFG-WO-")


def test_schedule_daily_0730_weekly_monday_0800(env):  # noqa: F811
    from hub.ont import report as RP
    H, eng = env
    db = H.db
    tz = kpi.TZ
    tue_0729 = dt.datetime(2026, 10, 13, 7, 29, tzinfo=tz)
    tue_0731 = dt.datetime(2026, 10, 13, 7, 31, tzinfo=tz)
    mon_0805 = dt.datetime(2026, 10, 19, 8, 5, tzinfo=tz)
    assert RP.due(db, "teach", tue_0731) == []                     # 教学模式不定时
    assert RP.due(db, "prod", tue_0729) == []
    assert RP.due(db, "prod", tue_0731) == ["daily"]
    rid = RP.generate(db, "prod", "daily", now=tue_0731, notify=False)
    s = db.one("select period_start, period_end, title from report where id=%s", (rid,))
    assert s["period_start"].astimezone(tz).date() == dt.date(2026, 10, 12) and s["period_end"].astimezone(tz).date() == dt.date(2026, 10, 13)
    assert s["title"] == "厂情日报 2026-10-12"
    assert RP.due(db, "prod", tue_0731) == []                      # 生成过就不再生成
    assert RP.due(db, "prod", mon_0805) == ["daily", "weekly"]
    rid = RP.generate(db, "prod", "weekly", now=mon_0805, notify=False)
    w = db.one("select period_start from report where id=%s", (rid,))
    assert w["period_start"].astimezone(tz).date() == dt.date(2026, 10, 12)
