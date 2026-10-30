# -*- coding: utf-8 -*-
"""第 57 轮：实验 27“两厂之间的一张订单”——按正确答案拿 60 分、答错拿不到；请购单里没有 WQR-105 时取接单后的第一批。需要 PostgreSQL。"""
import datetime as dt
import json
import math
import os

import pytest

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")


@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute("drop database if exists wq_lab27_test with (force)")
            c.execute("create database wq_lab27_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    from hub.db import DB
    d = DB(base + "/wq_lab27_test")
    d.init()
    return d


def _proposal(db, user, item="WQ-AGV300", qty=2, wqr=10, mr="MAT-MR-0001", pid="p1"):
    pv = {"sales_order": {"item_code": item, "qty": qty},
          "material_requests": [{"item_code": "WQR-105", "qty": wqr}, {"item_code": "M-6000", "qty": 4}] if wqr else []}
    db.x("insert into ai_proposal (proposal_id, mode, action, preview, status, requested_by, result) values "
         "(%s,'teach','create_order_and_plan',%s,'executed',%s,%s)",
         (pid, json.dumps(pv), user, json.dumps({"created": [["Sales Order", "SAL-ORD-0007"], ["Material Request", mr]]})))


def _lot(db, mr, status="accepted", days=8.0, park_order=3):
    from hub import lab27
    from hub import supply as SP
    SP.init(db)
    o = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=5)
    db.x("insert into lot (mode, lot, po, mr, supplier, item, qty, qty_left, status, ordered_at, arrived_at, park) values "
         "('teach','LOT-R1','PUR-ORD-0001',%s,'gearbox',%s,10,10,%s,%s,%s,%s)",
         (mr, lab27.PART, status, o, o + dt.timedelta(seconds=days * SP.DAY_S),
          json.dumps({"state": "shipped", "peer": "wenquest-gearbox", "order": park_order})))


def _answers(lab27, st, user):
    dm = lab27.demand(user)
    ss = 1.65 * dm["sigma_d"] * math.sqrt(dm["lead_days"])
    return {"l27_t1": {"qty": st["order"]["wqr_request"]}, "l27_t2": {"order": "3"},
            "l27_t4": {"days": st["lot_days"], "on_time": st["lot_days"] <= 10},
            "l27_t5": {"ss": round(ss, 2), "rop": round(dm["d"] * 10 + ss, 2)}, "l27_t6": {"choice": "bullwhip"}}


def test_right_answers_get_60(db):
    from hub import lab27
    _proposal(db, "stu1")
    _lot(db, "MAT-MR-0001")
    st = lab27.status(db, "stu1")
    assert st["order"]["qty"] == 2 and st["order"]["wqr_request"] == 10 and st["order"]["sales_order"] == "SAL-ORD-0007"
    assert st["lot"]["status"] == "accepted" and abs(st["lot_days"] - 8.0) < 0.2
    for tid, a in _answers(lab27, st, "stu1").items():
        r = lab27.answer(db, "stu1", tid, a)
        assert r["score"] == 10, (tid, r)
    st = lab27.status(db, "stu1")
    assert st["score"] == 60
    assert [c["total"] for c in lab27.class_view(db)] == [60]


def test_wrong_answers_score_less(db):
    from hub import lab27
    _proposal(db, "stu2", qty=3)
    _lot(db, "MAT-MR-0001", status="arrived")
    st = lab27.status(db, "stu2")
    assert lab27.answer(db, "stu2", "l27_t1", {"qty": 10})["score"] == 5          # 订单要 2 台
    assert lab27.answer(db, "stu2", "l27_t2", {"order": "9"})["score"] == 5
    assert lab27.answer(db, "stu2", "l27_t4", {"days": st["lot_days"] + 3, "on_time": False})["score"] == 0
    assert lab27.answer(db, "stu2", "l27_t5", {"ss": 1, "rop": 1})["score"] == 0
    assert lab27.answer(db, "stu2", "l27_t6", {"choice": "price"})["score"] == 0
    assert lab27.status(db, "stu2")["score"] == 10                               # 任务 3 没入库不打勾


def test_no_order_and_fallback_lot(db):
    from hub import lab27
    assert lab27.answer(db, "stu3", "l27_t1", {"qty": 10})["score"] == 0
    _proposal(db, "stu3", wqr=0, mr="MAT-MR-0005")                                # 这张请购单里没有 WQR-105
    _lot(db, "MAT-MR-0009")                                                       # 后面的请购补的一批
    st = lab27.status(db, "stu3")
    assert st["lot"] and st["lot"]["status"] == "accepted"
    assert lab27.answer(db, "stu3", "l27_t1", {"qty": 0})["score"] == 10
