"""第 139 轮 139c：按作业号专料专用的算料（逐层净需求、通用件用自由库存、本单专用件只认挂在作业上的供应、外协转请购）、
长周期件提前采购、桥接 → 模拟 ERPNext（工单、请购单都挂作业号）。"""
import datetime as dt
import json
import os

import pytest

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub import eto_mrp as EM
from tests.test_eto import BRIDGE_SCRIPT, CFG, DSN, mock_erp  # noqa: F401  （夹具）
from tests.test_eto_design import keep_master  # noqa: F401


@pytest.fixture(scope="module")
def db():
    pytest.importorskip("psycopg")
    import psycopg

    from hub.db import DB
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_etom_test with (force)")
            c.execute("create database wq_etom_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    d = DB(base + "/wq_etom_test")
    d.init()
    E.init(d)
    ED.init(d)
    return d


def _erp(db, doctype, name, **data):
    import wqbus
    msg = wqbus.make("erp.doc", "bridge", dict({"doctype": doctype, "name": name, "action": "updated"}, **data), mode="teach",
                     ts=dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"))
    db.insert_message("wq/gearbox/office/erp/doc", msg)


def _released_job(db, sup):
    j = E.new_job(db, "teach", "王销售", "示例·客户甲", "非标减速器", "", 2, None, "2027-03-30", cfg=CFG)
    jn = j["job_no"]
    db.x("update eto_job set status='ordered', quoted_rev=1, quotation='Q', sales_order='SO-1' where mode='teach' and job_no=%s", (jn,))
    spec = {"items": [{"code": jn + "-SH", "name": "输出轴", "kind": "make", "uom": "Nos"},
                      {"code": jn + "-FL", "name": "法兰", "kind": "buy", "uom": "Nos", "price": 40, "supplier": sup}],
            "boms": [{"item": jn, "routing": [["总装 Final assembly", 45]],
                      "components": [["SA-100", 1], [jn + "-SH", 1], ["BOLT-M8x25", 4], [jn + "-FL", 1]]},
                     {"item": jn + "-SH", "routing": [["粗车 Rough turning", 20]], "components": [["RM-45-D50", 4.4]]}],
            "outside": [{"desc": "喷涂", "unit_price": 85, "lead_days": 7}]}
    ED.save(db, "teach", jn, spec, "李设计")
    return jn, spec


def test_job_mrp_nets_level_by_level(db, keep_master):  # noqa: F811
    sup = next(k for k, v in F.SUPPLIERS.items() if (v.get("lead") or 0) >= 15)
    jn, spec = _released_job(db, sup)
    with pytest.raises(E.EtoError, match="还没发布"):
        EM.plan(db, "teach", jn)
    db.x("update eto_design set status='released', fingerprint='fp' where job_no=%s", (jn,))
    ED.merge(jn, "非标减速器", spec)
    _erp(db, "Bin", "b1", item_code="SA-100", warehouse="w", actual_qty=1)
    _erp(db, "Bin", "b2", item_code="BOLT-M8x25", warehouse="w", actual_qty=100)
    pv = EM.plan(db, "teach", jn)
    wo = {w["production_item"]: w["qty"] for w in pv["work_orders"]}
    mr = {m["item_code"]: m for m in pv["material_requests"]}
    assert wo[jn] == 2 and wo[jn + "-SH"] == 2 and wo["SA-100"] == 1        # 输入轴组件库存 1：只做 1 个
    sa_child = F.BOMS["SA-100"][1][0][0]
    assert next(r for r in pv["mrp"] if r["item_code"] == sa_child)["gross"] == F.BOMS["SA-100"][1][0][1] * 1   # 只按净需求往下展开
    assert "BOLT-M8x25" not in mr                                            # 库存够
    assert mr[jn + "-FL"]["qty"] == 2 and mr[jn + "-FL"]["wh"] == "purchased"   # 专用件不凑批量
    assert mr["RM-45-D50"]["qty"] == F.PACK.get("RM-45-D50", 50) or mr["RM-45-D50"]["qty"] % 50 == 0
    assert mr[jn + "-OS01"]["service"] and mr[jn + "-OS01"]["qty"] == 2 and pv["service_items"][0]["code"] == jn + "-OS01"
    own = {r["item_code"]: r for r in pv["mrp"]}
    assert own[jn + "-FL"]["own"] and own[jn + "-FL"]["free_stock"] == 0
    # 已经挂在作业上的供应：不重复下
    _erp(db, "Material Request", "MR-1", docstatus=1, status="Pending", project=jn,
         items=[{"item_code": jn + "-FL", "qty": 2}, {"item_code": jn + "-OS01", "qty": 2}])
    _erp(db, "Work Order", "WO-1", docstatus=1, status="Not Started", project=jn, production_item=jn + "-SH", qty=2)
    _erp(db, "Bin", "b3", item_code=jn + "-FL", warehouse="w", actual_qty=5)       # 别处的库存不给专用件用
    pv = EM.plan(db, "teach", jn)
    mr = {m["item_code"] for m in pv["material_requests"]}
    wo = {w["production_item"] for w in pv["work_orders"]}
    assert jn + "-FL" not in mr and jn + "-OS01" not in mr and jn + "-SH" not in wo and "RM-45-D50" not in mr
    # 别的订单占了库存：通用件不能用
    _erp(db, "Sales Order", "SO-X", docstatus=1, status="To Deliver and Bill", customer="c", items=[{"item_code": "BOLT-M8x25", "qty": 95, "delivered_qty": 0}])
    pv = EM.plan(db, "teach", jn)
    bolt = next(r for r in pv["mrp"] if r["item_code"] == "BOLT-M8x25")
    assert bolt["free_stock"] == 5 - F.SAFETY_STOCK.get("BOLT-M8x25", 0) and any(m["item_code"] == "BOLT-M8x25" for m in pv["material_requests"])
    # 本作业自己的订单不算“别的订单占用”
    _erp(db, "Sales Order", "SO-1", docstatus=1, status="To Deliver and Bill", customer="c", project=jn, items=[{"item_code": jn, "qty": 2, "delivered_qty": 0}])
    assert next(r for r in EM.plan(db, "teach", jn)["mrp"] if r["item_code"] == "BOLT-M8x25")["free_stock"] == bolt["free_stock"]


def test_early_buy_long_lead_only(db, keep_master):  # noqa: F811
    long_sup = next(k for k, v in F.SUPPLIERS.items() if (v.get("lead") or 0) >= 15)
    short_sup = next(k for k, v in F.SUPPLIERS.items() if v.get("lead") is not None and v["lead"] < 15)
    jn, spec = _released_job(db, long_sup)
    pv = EM.early_buy_preview(db, "teach", jn, [jn + "-FL"])
    r = pv["material_requests"][0]
    assert r["qty"] == 2 and r["new_item"]["code"] == jn + "-FL" and "未发布" in r["reason"] and pv["job"]["design_status"] == "draft"
    spec["items"][1]["supplier"] = short_sup
    ED.save(db, "teach", jn, spec, "李设计")
    with pytest.raises(E.EtoError, match="不算长周期件"):
        EM.early_buy_preview(db, "teach", jn, [jn + "-FL"])
    with pytest.raises(E.EtoError, match="自制件"):
        EM.early_buy_preview(db, "teach", jn, [jn + "-SH"])
    with pytest.raises(E.EtoError, match="没用在"):
        EM.early_buy_preview(db, "teach", jn, ["BRG-6205"])
    db.x("update eto_design set status='released' where job_no=%s", (jn,))
    with pytest.raises(E.EtoError, match="已经发布"):
        EM.early_buy_preview(db, "teach", jn, [jn + "-FL"])


def test_bridge_materials(mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    jn = "JOB-2026-0077"
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    pv = {"job": {"job_no": jn, "sales_order": "SO-77"},
          "work_orders": [{"production_item": "SH-301", "qty": 2, "planned_start_date": "2026-11-11", "expected_delivery_date": "2026-11-12",
                           "warehouse": "semi", "sources": {"RM-45-D50": "raw"}}],
          "material_requests": [{"item_code": "RM-45-D50", "qty": 50, "uom": "Kg", "schedule_date": "2026-11-20", "wh": "raw"},
                                {"item_code": jn + "-OS01", "qty": 2, "uom": "Nos", "schedule_date": "2026-11-18", "wh": "purchased", "service": True}],
          "service_items": [{"code": jn + "-OS01", "name": "外协 喷涂"}]}
    msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-M1", "action": "eto_materials", "preview": pv}}
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    first, _ = json.loads(r.stdout)
    assert not any(x["action"] == "failed" for x in first), [x.get("error") for x in first]
    assert [c[0] for c in first[-1]["created"]] == ["Item", "Work Order", "Material Request"]
    wo = M.db["Work Order"][first[-1]["created"][1][1]]
    assert wo["project"] == jn and wo["wq_sales_order"] == "SO-77"
    mr = M.db["Material Request"][first[-1]["created"][2][1]]
    assert all(i["project"] == jn for i in mr["items"]) and M.db["Item"][jn + "-OS01"]["is_stock_item"] == 0
    assert first[-1]["project"] == jn                                       # 读回的请购单带作业号
