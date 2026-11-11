"""第 139 轮 139h：实验 33“一张非标订单：从询价到收款”——自动分按事实（估算无未知、接单带付款计划、发布的设计有复制的新件、
有实际工序成本、终检合格、订金已开票），学生填的数和平台算的比；只升不降；没填作业号的任务不给分。"""
import json

import pytest

from hub import eto as E
from hub import eto_billing as EB
from hub import eto_exec as EX
from hub import eto_plan as EP
from hub import eto_quality as EQ
from hub import lab33 as L
from tests.test_eto_mrp import db  # noqa: F401  （夹具）

U = "wq_lab33_学生"
SCHED = [{"key": "deposit", "description": "订金 Deposit", "invoice_portion": 30, "payment_amount": 351.78, "on": "order", "due_date": "2026-11-10"},
         {"key": "ship", "description": "发货 Shipment", "invoice_portion": 60, "payment_amount": 703.56, "on": "ship", "due_date": "2027-01-29"},
         {"key": "accept", "description": "验收 Acceptance", "invoice_portion": 10, "payment_amount": 117.26, "on": "accept", "due_date": "2027-02-08"}]


def test_auto_scores_pure():
    assert L.auto_scores(None, 0) == {}
    f = {"can_quote": True, "ordered": True, "schedule": 3, "released": True, "copied": ["J-SH"], "final_pass": 1, "deposit_invoiced": True}
    assert L.auto_scores(f, 12.5) == {"l33_t1": 5, "l33_t2": 10, "l33_t3": 8, "l33_t4": 10, "l33_t5": 6}
    g = dict(f, can_quote=False, schedule=0, copied=[], final_pass=0, deposit_invoiced=False)
    assert L.auto_scores(g, 0) == {"l33_t1": 0, "l33_t2": 5, "l33_t3": 0, "l33_t4": 0, "l33_t5": 0}
    assert sum(t["points"] for t in L.TASKS) == 60 and L.REPORT_POINTS == 40


def _fresh(db):  # noqa: F811
    for m in (EX, EQ, EB):
        m.init(db)
    db.x("delete from task_result where user_name=%s", (U,))


def test_lab33_flow(db, monkeypatch):  # noqa: F811
    _fresh(db)
    st = L.check(db, U)
    assert st["score"] == 0 and st["job_no"] is None and st["of"] == 60
    assert L.answer(db, U, "l33_t3", {"earliest": "2026-12-01"})["score"] == 0          # 没填作业号
    assert L.answer(db, U, "l33_t1", {"job_no": "JOB-9999-0001", "price": 1})["score"] == 0

    j = E.new_job(db, "teach", "销售·学生", "示例·客户己", "非标减速器", "加长输出轴", 2, [2], "2027-01-29")
    jn = j["job_no"]
    lines = [{"kind": "outside", "desc": "喷涂", "unit_price": 85}, {"kind": "engineering", "desc": "改图", "hours": None}]
    E.save_estimate(db, "teach", jn, lines, "", "销售·学生")
    r = L.answer(db, U, "l33_t1", {"job_no": jn.lower(), "price": 1172.6})
    assert r["score"] == 0 and "未知" in r["feedback"] and L.job_no(db, U) == jn                  # 有未知：记下作业号，不给分
    lines[1]["hours"] = 10
    E.save_estimate(db, "teach", jn, lines, "", "销售·学生")
    # 手算：小计 85 × 2 + 10 × 65 = 820；× 1.1 × 1.3 = 1172.60
    assert L.answer(db, U, "l33_t1", {"job_no": jn, "price": 1170})["score"] == 5
    assert L.answer(db, U, "l33_t1", {"job_no": jn, "price": 1172.6})["score"] == 10
    assert L.answer(db, U, "l33_t1", {"job_no": jn, "price": 1})["score"] == 10                   # 只升不降

    # 任务 2：接单、带付款计划
    db.x("update eto_job set status='ordered', quoted_rev=1, sales_order='SO-L33', payment_schedule=%s where mode='teach' and job_no=%s",
         (json.dumps(SCHED, ensure_ascii=False), jn))
    monkeypatch.setattr(EX, "cost", lambda db_, mode, job_no: {"actual": {"operations": 0.0}, "estimate": {"operations": 40.0}})
    st = L.check(db, U)
    assert {t["id"]: t["score"] for t in st["tasks"]}["l33_t2"] == 10

    # 任务 3：发布的设计里有复制的新件；最早交货日期和平台一致
    spec = {"items": [{"code": jn + "-SH", "name": "输出轴（专用）", "kind": "make", "uom": "Nos", "from": "SH-301"}], "boms": [], "outside": []}
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'released','fp')",
         (jn, json.dumps(spec, ensure_ascii=False)))
    monkeypatch.setattr(EP, "schedule", lambda db_, mode, job_no, today=None: {"earliest": "2026-12-11"})
    assert L.answer(db, U, "l33_t3", {"earliest": "2026-12-10"})["score"] == 8
    assert L.answer(db, U, "l33_t3", {"earliest": "2026-12-11"})["score"] == 15

    # 任务 4：车间没报工不能答；有实际工序成本、终检合格 1 件、差额对
    assert L.answer(db, U, "l33_t4", {"diff": -5})["score"] == 0
    monkeypatch.setattr(EX, "cost", lambda db_, mode, job_no: {"actual": {"operations": 34.87}, "estimate": {"operations": 40.0}})
    db.x("insert into eto_insp (mode, job_no, kind, work_order, item, piece, plan_rev, readings, result, inspector) "
         "values ('teach',%s,'final','WO-1',%s,1,1,'{}','pass','质检甲')", (jn, jn))
    assert L.answer(db, U, "l33_t4", {"diff": 5.13})["score"] == 10                               # 符号反了
    assert L.answer(db, U, "l33_t4", {"diff": -5.13})["score"] == 15

    # 任务 5：订金开票；原因选里程碑
    assert L.answer(db, U, "l33_t5", {"reason": "erp"})["score"] == 0
    db.x("insert into eto_invoice (mode, job_no, key, amount, invoice) values ('teach',%s,'deposit',351.78,'ACC-SINV-1')", (jn,))
    assert L.answer(db, U, "l33_t5", {"reason": "milestone"})["score"] == 10                     # 订金已开票 6 + 原因 4
    st = L.check(db, U)
    assert {t["id"]: t["score"] for t in st["tasks"]} == {"l33_t1": 10, "l33_t2": 10, "l33_t3": 15, "l33_t4": 15, "l33_t5": 10}
    assert st["score"] == 60 and st["job_no"] == jn
    assert [c["total"] for c in L.class_view(db) if c["user"] == U] == [60]
    with pytest.raises(KeyError):
        L.answer(db, U, "l33_t2", {})
