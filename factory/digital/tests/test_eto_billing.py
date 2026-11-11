"""第 139 轮 139g：按里程碑分期开票（到了才能开、每期只开一次、存下的付款计划）、客户验收、作业收付与毛利、
外协按采购单算实际、作业订单不走整单自动开票、桥接 → 模拟 ERPNext（分期发票按金额、防超开、重发不重开）。"""
import json
import os

import pytest

from hub import eto as E
from hub import eto_billing as B
from hub import eto_exec as X
from tests.test_eto import BRIDGE_SCRIPT, mock_erp  # noqa: F401
from tests.test_eto_mrp import _erp, db  # noqa: F401

JN = "JOB-2026-0070"
SCHED = [{"key": "deposit", "description": "订金 Deposit", "invoice_portion": 30, "payment_amount": 3000.0, "on": "order", "due_date": "2026-11-10"},
         {"key": "ship", "description": "发货 Shipment", "invoice_portion": 60, "payment_amount": 6000.0, "on": "ship", "due_date": "2027-01-29"},
         {"key": "accept", "description": "验收 Acceptance", "invoice_portion": 10, "payment_amount": 1000.0, "on": "accept", "due_date": "2027-02-08"}]


def _job(db, outside=None):  # noqa: F811
    from hub import eto_quality as Q
    for m in (X, Q, B):
        m.init(db)
    db.x("delete from eto_job where job_no=%s", (JN,))
    db.x("delete from eto_design where job_no=%s", (JN,))
    db.x("delete from ai_proposal where preview->'job'->>'job_no'=%s", (JN,))
    B.reset(db, "teach")
    db.x("insert into eto_job (mode, job_no, customer, title, qty, qty_breaks, status, sales_order, project, due_date) "
         "values ('teach',%s,'示例·客户戊','非标减速器',2,'[2]','ordered','SO-70','PROJ-0070','2027-01-29')", (JN,))
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'draft','fp')",
         (JN, json.dumps({"items": [], "boms": [], "outside": outside or []})))


def _proposal(db, pid, action, pv, status="pending", result=None):  # noqa: F811
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, status, result) values (%s,'teach',%s,'t',%s,%s,%s)",
         (pid, action, json.dumps(pv, ensure_ascii=False), status, json.dumps(result) if result else None))


def test_milestones_invoice_once_and_acceptance(db):  # noqa: F811
    _job(db)
    assert B.milestones(db, "teach", JN) == []                         # 没有存下的付款计划、也没有执行过的接单提议
    _proposal(db, "P-o70", "eto_order", {"job": {"job_no": JN}, "sales_order": {"payment_schedule": SCHED}}, "executed")
    assert [m["key"] for m in B.milestones(db, "teach", JN)] == ["deposit", "ship", "accept"]   # 上线前接的单：取执行了的接单提议
    B.on_proposal_done(db, "eto_order", {"job": {"job_no": JN}, "sales_order": {"payment_schedule": SCHED}}, "teach")
    ms = {m["key"]: m for m in B.milestones(db, "teach", JN)}
    assert ms["deposit"]["state"] == "due" and ms["ship"]["state"] == "waiting" and ms["accept"]["state"] == "waiting"
    with pytest.raises(E.EtoError, match="发货"):
        B.invoice_preview(db, "teach", JN, "ship")
    with pytest.raises(E.EtoError, match="没有这一期"):
        B.invoice_preview(db, "teach", JN, "x")
    pv = B.invoice_preview(db, "teach", JN, "deposit", today=__import__("datetime").date(2026, 11, 12))
    assert pv["amount"] == 3000.0 and pv["pct"] == 30 and pv["due_date"] == "2026-11-12" and pv["job"]["project"] == "PROJ-0070"
    _proposal(db, "P-i70", "eto_invoice", pv)
    B.mark_invoicing(db, "teach", pv, "P-i70")
    assert B.milestones(db, "teach", JN)[0]["state"] == "drafted"
    with pytest.raises(E.EtoError, match="已经开过"):
        B.invoice_preview(db, "teach", JN, "deposit")
    db.x("update ai_proposal set status='rejected' where proposal_id='P-i70'")
    assert B.milestones(db, "teach", JN)[0]["state"] == "due"                       # 否决了可以重新起草
    db.x("update ai_proposal set status='executed', result=%s where proposal_id='P-i70'",
         (json.dumps({"created": [["Sales Invoice", "ACC-SINV-0001"]]}),))
    B.on_proposal_done(db, "eto_invoice", pv, "teach")
    m0 = B.milestones(db, "teach", JN)[0]
    assert m0["state"] == "invoiced" and m0["invoice"] == "ACC-SINV-0001"
    with pytest.raises(E.EtoError, match="还没发货"):
        B.accept(db, "teach", JN, "2027-02-01", "", "王销售")
    db.x("update eto_job set delivery_note='DN-1' where job_no=%s", (JN,))
    assert B.milestones(db, "teach", JN)[1]["state"] == "due"
    B.accept(db, "teach", JN, "2027-02-01", "客户现场验收", "王销售")
    assert B.milestones(db, "teach", JN)[2]["state"] == "due"
    assert B.is_eto_order(db, "teach", "SO-70") and not B.is_eto_order(db, "teach", "SO-OTHER")


def test_money_and_outside_actual(db):  # noqa: F811
    _job(db, outside=[{"desc": "喷涂", "unit_price": 85, "lead_days": 7}])
    B.on_proposal_done(db, "eto_order", {"job": {"job_no": JN}, "sales_order": {"payment_schedule": SCHED}}, "teach")
    db.x("insert into eto_invoice (mode, job_no, key, amount, proposal_id, invoice) values ('teach',%s,'deposit',3000,'P','SI-70A')", (JN,))
    _erp(db, "Sales Invoice", "SI-70A", docstatus=1, grand_total=3000, outstanding_amount=1000)
    _erp(db, "Sales Invoice", "SI-OTHER", docstatus=1, grand_total=500, outstanding_amount=0)        # 别的订单的发票不算
    m = B.money(db, "teach", JN, {"actual": {"total": 7200.0}})
    assert m["order_amount"] == 10000.0 and m["invoiced"] == 3000.0 and m["received"] == 2000.0 and m["receivable"] == 1000.0
    assert m["not_invoiced"] == 7000.0 and m["margin"] == 2800.0 and m["margin_pct"] == 28.0
    assert B.money(db, "teach", JN, {"actual": {"total": None}})["margin"] is None                  # 成本未知，毛利也未知
    j = E.job(db, "teach", JN)
    assert X.outside_actual(db, "teach", j) == (0.0, [], [])                                         # 设计没发布：没有外协
    db.x("update eto_design set status='released' where job_no=%s", (JN,))
    amt, why, _ = X.outside_actual(db, "teach", j)
    assert amt is None and "还没下采购单" in why[0]
    _erp(db, "Purchase Order", "PO-70", docstatus=1, project="PROJ-0070", items=[{"item_code": JN + "-OS01", "qty": 2}])
    amt, why, _ = X.outside_actual(db, "teach", j)
    assert amt is None and "没有单价" in why[0]
    _erp(db, "Purchase Order", "PO-70", docstatus=1, project="PROJ-0070", items=[{"item_code": JN + "-OS01", "qty": 2, "rate": 80}])
    assert X.outside_actual(db, "teach", j) == (160.0, [], [JN + "-OS01"])            # 第 150 轮：发票没到，按采购单并标出来


def test_finance_skips_eto_orders(db):  # noqa: F811
    from hub import finance as FN
    _job(db)

    class H:
        pass
    H.db = db
    FN.init(db)
    assert FN.make_sales_invoice(H, "teach", {"data": {"name": "SO-70", "customer": "示例·客户戊", "items": []}}) is None


def test_bridge_invoices_installments(mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    M.db.setdefault("Sales Order", {})["SO-B"] = {"name": "SO-B", "customer": "示例·客户戊", "company": "c", "docstatus": 1, "status": "To Deliver and Bill",
                                                  "items": [{"name": "rb1", "item_code": JN, "qty": 2, "rate": 5000, "delivered_qty": 0, "warehouse": "w"}]}

    def run(key, pct, amount):
        pv = {"job": {"job_no": JN, "title": "非标减速器", "project": None}, "sales_order": "SO-B", "key": key, "description": key, "pct": pct,
              "amount": amount, "posting_date": "2026-11-12", "due_date": "2026-11-20"}
        msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-" + key, "action": "eto_invoice", "preview": pv}}
        r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(r.stdout)
    a, b = run("deposit", 30, 3000)                                    # 执行两次：第二次认出已开的那张，不重开
    assert not any(x["action"] == "failed" for x in a + b), [x.get("error") for x in a + b]
    si = M.db["Sales Invoice"][a[-1]["created"][0][1]]
    assert si["grand_total"] == 3000 and si["items"][0]["qty"] == 1 and si["items"][0]["so_detail"] == "rb1" and si["due_date"] == "2026-11-20"
    assert b[-1]["created"][0][1] == si["name"] and M.db["Sales Order"]["SO-B"]["per_billed"] == 30
    run("ship", 60, 6000)
    a, _ = run("accept", 10, 1000)
    assert M.db["Sales Order"]["SO-B"]["per_billed"] == 100
    a, _ = run("extra", 1, 100)                                         # 订单已经开满：再开就是超开
    assert a[-1]["action"] == "failed"


# ---------------------------------------------------------------- 第 150 轮 150b：采购发票对账
def test_purchase_invoices_drive_actual_cost(db):  # noqa: F811
    _job(db, outside=[{"desc": "喷涂", "unit_price": 85, "lead_days": 7}])
    db.x("update eto_design set status='released' where job_no=%s", (JN,))
    db.x("update eto_job set project='PROJ-0071' where job_no=%s", (JN,))          # 和上一条测试的采购单分开
    j = E.job(db, "teach", JN)
    _erp(db, "Purchase Order", "PO-71", docstatus=1, project="PROJ-0071", supplier="示例·喷涂厂",
         items=[{"item_code": JN + "-OS01", "qty": 2, "rate": 80}, {"item_code": JN + "-PL", "qty": 4, "rate": 12.5}])
    _erp(db, "Purchase Order", "PO-OTHER", docstatus=1, project="PROJ-9", items=[{"item_code": JN + "-PL", "qty": 9, "rate": 1}])  # 别的项目不算
    lines = {r["item_code"]: r for r in X.purchase_lines(db, "teach", j)}
    assert set(lines) == {JN + "-OS01", JN + "-PL"} and lines[JN + "-OS01"]["status"] == "pending"
    assert X.buy_price(list(lines.values()), JN + "-PL") == (12.5, "po")
    # 外协发票到了一件，单价 92（比采购单贵 12）：已开票的按发票、没开票的按采购单
    _erp(db, "Purchase Invoice", "PINV-1", docstatus=1, items=[{"item_code": JN + "-OS01", "qty": 1, "rate": 92, "amount": 92, "purchase_order": "PO-71"}])
    lines = {r["item_code"]: r for r in X.purchase_lines(db, "teach", j)}
    os1 = lines[JN + "-OS01"]
    assert os1["status"] == "partly" and os1["invoiced_qty"] == 1 and os1["invoice_amount"] == 92 and os1["diff"] == 12.0
    assert X.outside_actual(db, "teach", j) == (172.0, [], [JN + "-OS01"])            # 92 + 1 × 80
    # 第二张发票开齐；专料发票 4 × 13.0
    _erp(db, "Purchase Invoice", "PINV-2", docstatus=1, items=[{"item_code": JN + "-OS01", "qty": 1, "rate": 92, "amount": 92, "purchase_order": "PO-71"},
                                                               {"item_code": JN + "-PL", "qty": 4, "rate": 13, "amount": 52, "purchase_order": "PO-71"}])
    _erp(db, "Purchase Invoice", "PINV-X", docstatus=0, items=[{"item_code": JN + "-PL", "qty": 4, "rate": 99, "amount": 396, "purchase_order": "PO-71"}])  # 草稿不算
    lines = {r["item_code"]: r for r in X.purchase_lines(db, "teach", j)}
    assert lines[JN + "-OS01"]["status"] == "invoiced" and lines[JN + "-OS01"]["diff"] == 24.0 and lines[JN + "-OS01"]["invoices"] == ["PINV-1", "PINV-2"]
    assert lines[JN + "-PL"]["diff"] == 2.0 and X.buy_price(list(lines.values()), JN + "-PL") == (13.0, "invoice")
    assert X.outside_actual(db, "teach", j) == (184.0, [], [])                         # 全按发票，没有“发票未到”
    # 毛利跟着成本走
    assert B.money(db, "teach", JN, {"actual": {"total": 184.0}})["actual_cost"] == 184.0
