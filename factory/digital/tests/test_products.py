# -*- coding: utf-8 -*-
"""工厂接收新产品（本仓库 ADR-0061）：方案 → 生产物料规格 → 登记并入主数据 → MRP 给出全部工单与采购。
MRP 那几项需要本机 PostgreSQL（WQ_TEST_DB），没有时跳过。"""
import copy
import datetime as dt
import os

import pytest

from factory import data as F

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_products"
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)
DESIGN = {
    "code": "cobot-j2", "revision": 1, "name": "协作机器人肩关节",
    "bom": [{"component_id": "servo_motor.yaskawa-electric-corporation.sgm7j-04a", "vendor": "Yaskawa Electric Corporation",
             "model": "SGM7J-04A", "quantity": 1, "source_docs": ["src-yaskawa"]},
            {"component_id": "reducer.harmonic-drive-llc.csf-25-100-2uh", "vendor": "Harmonic Drive LLC",
             "model": "CSF-25-100-2UH", "quantity": 1},
            {"component_id": "drive.yaskawa-america-inc.sgd7s-2r8a", "vendor": "Yaskawa America Inc.", "model": "SGD7S-2R8A",
             "quantity": 1}],
    "made_parts": [{"code": "RJ-201", "name": "机器人关节空心轴", "qty": 1, "material": "45 钢调质",
                    "raw": {"item_code": "RM-45-D50"}, "raw_qty": 1.2,
                    "routing": [["下料 Sawing", 3], ["粗车 Rough turning", 15], ["精车 Finish turning", 12],
                                ["零件检验 Part inspection", 5]]},
                   {"code": "J2-HSG", "name": "关节壳体", "qty": 1, "material": "6061-T6",
                    "raw": {"item_code": "RM-6061-B120", "name": "6061 方料 120×120×80", "uom": "Nos", "supplier": "steel"},
                    "raw_qty": 1, "routing": [["铣结合面 Face milling", 20], ["钻攻螺纹孔 Drilling & tapping", 15]]}],
    "assembly_routing": [["总装 Final assembly", 40], ["跑合试验 Run-in test", 20], ["出厂检验 Final inspection", 10]],
}


@pytest.fixture()
def clean_f():
    from hub import products
    saved = {k: copy.deepcopy(getattr(F, k)) for k in ("ITEMS", "BOMS", "ROUTINGS", "SUPPLIERS")}
    reg, raw = set(products._REGISTERED), dict(products._RAW)
    yield
    for k, v in saved.items():
        getattr(F, k).clear()
        getattr(F, k).update(v)
    products._REGISTERED.clear()
    products._REGISTERED.update(reg)
    products._RAW.clear()
    products._RAW.update(raw)


def test_build_spec(clean_f):
    from hub import products
    spec = products.build(DESIGN, {"purchase": {"reducer.harmonic-drive-llc.csf-25-100-2uh": {"lead_days": 28, "price": 900}},
                                   "price": 5200})
    items = {i["item_code"]: i for i in spec["items"]}
    assert spec["code"] == "COBOT-J2" and items["COBOT-J2"]["kind"] == "fg" and items["COBOT-J2"]["price"] == 5200
    assert items["CSF-25-100-2UH"]["kind"] == "buy" and items["CSF-25-100-2UH"]["price"] == 900
    assert items["SGM7J-04A"]["price"] is None and "RM-45-D50" not in items and items["RM-6061-B120"]["kind"] == "raw"
    assert all(i["item_group"] in F.ITEM_GROUPS for i in spec["items"])
    sup = {s["name"]: s for s in spec["suppliers"]}
    assert sup["Harmonic Drive LLC"]["lead"] == 28 and sup["Yaskawa Electric Corporation"]["lead"] is None
    assert any("交期待确认" in w for w in spec["warnings"])
    boms = {b["item"]: b for b in spec["boms"]}
    assert [b["item"] for b in spec["boms"]][-1] == "COBOT-J2"           # 自下而上
    assert boms["COBOT-J2"]["items"] == [["SGM7J-04A", 1], ["CSF-25-100-2UH", 1], ["SGD7S-2R8A", 1], ["RJ-201", 1], ["J2-HSG", 1]]
    assert spec["operations"]["总装 Final assembly"] == F.OPERATIONS["总装 Final assembly"]
    products.merge(spec)
    assert products.is_product("COBOT-J2") and F.BOMS["RJ-201"][1] == [("RM-45-D50", 1.2)]
    from sim.engine import routing_for
    assert [op for op, _ in routing_for("COBOT-J2")] == ["总装 Final assembly", "跑合试验 Run-in test", "出厂检验 Final inspection"]
    # ADR-0062：再次转为生产物料（新版本、或 ERP 换过库）时，登记产品带来的新原材料照样发给 ERP
    again = {i["item_code"]: i for i in products.build(dict(DESIGN, revision=2))["items"]}
    assert again["RM-6061-B120"]["kind"] == "raw" and again["RM-6061-B120"]["supplier"] == "steel"
    assert "RM-45-D50" not in again                                       # 工厂原有的原材料不发


def test_build_rejects(clean_f):
    from hub import products
    bad = copy.deepcopy(DESIGN)
    bad["made_parts"][0]["routing"] = [["激光切割", 3]]
    with pytest.raises(products.ProductError, match="不是工厂现有工序"):
        products.build(bad)
    bad = copy.deepcopy(DESIGN)
    bad["made_parts"][1]["raw"] = {"item_code": "RM-NEW"}
    with pytest.raises(products.ProductError, match="新原材料"):
        products.build(bad)
    bad = copy.deepcopy(DESIGN)
    bad["code"] = "WQR-105"
    with pytest.raises(products.ProductError, match="原有物料"):
        products.build(bad)
    bad = copy.deepcopy(DESIGN)
    bad["assembly_routing"] = []
    with pytest.raises(products.ProductError, match="没有工艺路线"):
        products.build(bad)


def test_cad_release_keeps_made_parts():
    from hub import cad_link
    d = cad_link.validate({"code": "cobot-j2", "name": "肩关节", "bom": DESIGN["bom"], "made_parts": DESIGN["made_parts"],
                           "assembly_routing": DESIGN["assembly_routing"]})
    assert d["made_parts"][0]["code"] == "RJ-201" and d["assembly_routing"][0][0] == "总装 Final assembly"
    with pytest.raises(cad_link.CadError):
        cad_link.validate({"code": "x", "name": "x", "bom": DESIGN["bom"], "made_parts": [{"name": "无编号"}]})


@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(base, autocommit=True) as c:
            c.execute("drop database if exists wq_products with (force)")
            c.execute("create database wq_products")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


def test_register_and_mrp_releases_everything(db, clean_f):
    from hub import mrp, products
    products.init(db)
    spec = products.build(DESIGN, {"purchase": {"reducer.harmonic-drive-llc.csf-25-100-2uh": {"lead_days": 28}}, "price": 5200})
    products.register(db, spec, "teach")
    assert [p["code"] for p in products.products(db)] == ["COBOT-J2"]
    pv = mrp.plan_order(db, F.CUSTOMERS[0], "COBOT-J2", 4, "2026-11-30", now=NOW)
    wos = {w["production_item"]: w for w in pv["work_orders"]}
    assert set(wos) == {"COBOT-J2", "RJ-201", "J2-HSG"} and not pv["deferred"]
    assert wos["COBOT-J2"]["warehouse"] == "fg" and wos["RJ-201"]["warehouse"] == "semi"
    assert wos["COBOT-J2"]["sources"] == {"SGM7J-04A": "raw", "CSF-25-100-2UH": "raw", "SGD7S-2R8A": "raw",
                                          "RJ-201": "semi", "J2-HSG": "semi"}
    mrs = {m["item_code"]: m for m in pv["material_requests"]}
    assert {"SGM7J-04A", "CSF-25-100-2UH", "SGD7S-2R8A", "RM-6061-B120"} <= set(mrs)
    assert any("SGM7J-04A 的采购交期待确认" in w for w in pv["warnings"])
    assert pv["sales_order"]["rate"] == 5200 and pv["sales_order"]["amount"] == 20800
    # 枢纽重启：登记表并回主数据
    F.ITEMS.pop("COBOT-J2")
    products._REGISTERED.clear()
    products.load_all(db)
    assert products.is_product("COBOT-J2")


def test_proposal_done_registers(db, clean_f):
    import json

    from hub import products
    from hub.ai import Assistant
    products.init(db)
    spec = products.build(DESIGN)
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, requested_by) values (%s,%s,%s,%s,%s,%s)",
         ("P-TEST0001", "teach", "cad_to_erp", "t", json.dumps(spec, ensure_ascii=False), "测试"))
    a = Assistant.__new__(Assistant)
    a.db = db
    a.on_erp_result({"corr": "P-TEST0001", "data": {"action": "submitted", "doctype": "BOM", "proposal_done": True,
                                                    "created": [["BOM", "BOM-COBOT-J2-001"]]}})
    assert db.one("select status from ai_proposal where proposal_id='P-TEST0001'")["status"] == "executed"
    assert products.is_product("COBOT-J2")
