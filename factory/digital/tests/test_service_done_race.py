"""第 134 轮：模拟的现场工程师在 ERPNext 服务单建好之前就完工（加速运行），派工提议执行完时要补上“已解决”，且只补一次。"""
import json
import os
import types

import pytest

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")


@pytest.fixture(scope="module")
def H():
    pytest.importorskip("psycopg")
    import psycopg

    from hub import service as SV
    from hub.ai import Assistant
    from hub.db import DB
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_svrace_test with (force)")
            c.execute("create database wq_svrace_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    db = DB(base + "/wq_svrace_test")
    db.init()
    SV.init(db)
    from hub import twin as TW
    db.x(TW.SCHEMA)

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    return types.SimpleNamespace(db=db, ai=Assistant(db, lambda *a: None, NoLLM()), twin=None)


def test_done_before_issue_then_resolved_once(H):
    from hub import service as SV
    db = H.db
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, status) values ('P-SO1','teach','service_orders','t','{}','confirmed')")
    jid = db.one("insert into service_job (mode, serial, kind, status, proposal_id) values ('teach','S-1','inspect','planned','P-SO1') returning id")["id"]
    r = SV.complete_job(H, "teach", jid, "教学模拟器", day=__import__("datetime").date(2026, 11, 10))                      # 服务单还没建好：先不提“已解决”
    assert r["issue"] is None
    assert not db.one("select 1 as x from ai_proposal where action='service_order_done'")
    db.x("update ai_proposal set status='executed', result=%s where proposal_id='P-SO1'", (json.dumps({"created": [["Issue", "ISS-9"]]}),))
    SV.after_orders(H, "service_orders", {}, "teach")
    SV.after_orders(H, "service_orders", {}, "teach")                      # 再来一次不重复
    rows = db.q("select preview, status from ai_proposal where action='service_order_done'")
    assert len(rows) == 1 and rows[0]["preview"]["issue"] == "ISS-9" and rows[0]["status"] == "confirmed"
    assert db.one("select issue from service_job where id=%s", (jid,))["issue"] == "ISS-9"
    SV.after_orders(H, "purchase_order", {}, "teach")                     # 别的提议不管
