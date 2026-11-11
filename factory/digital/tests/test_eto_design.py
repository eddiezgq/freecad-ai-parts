"""第 139 轮 139b：接单（付款计划）、这一单的设计（检查、照估算起草、复制为新件）、设计发布（指纹、冻结、改版）、
设计没发布不能算料下工单、桥接 → 模拟 ERPNext（销售订单、新物料、物料清单）。"""
import json
import os

import pytest

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from tests.test_eto import BRIDGE_SCRIPT, CFG, DSN, mock_erp  # noqa: F401  （夹具）

JN = "JOB-2026-0042"


def spec_ok():
    return {"items": [{"code": JN + "-SH", "name": "输出轴（加长 40）", "kind": "make", "uom": "Nos"},
                      {"code": JN + "-FL", "name": "客户法兰", "kind": "buy", "uom": "Nos", "price": 40, "supplier": "steel"}],
            "boms": [{"item": JN, "routing": [["总装 Final assembly", 45], ["出厂检验 Final inspection", 10]],
                      "components": [["SA-100", 1], [JN + "-SH", 1], [JN + "-FL", 1], ["BOLT-M8x25", 4]]},
                     {"item": JN + "-SH", "routing": [["下料 Sawing", 3], ["粗车 Rough turning", 20]], "components": [["RM-45-D50", 4.4]]}]}


def test_check_design():
    errs, warns = ED.check(spec_ok(), JN)
    assert errs == [] and warns == []
    s = spec_ok()
    s["items"].append({"code": "X-1", "name": "", "kind": "paint", "uom": ""})
    s["boms"][0]["components"].append(["NOPE", 1])
    s["boms"][0]["routing"].append(["激光切割", 0])
    s["boms"][1]["components"].append([JN + "-SH", 1])                   # 自己用自己
    errs, _ = ED.check(s, JN)
    text = "；".join(errs)
    for k in ("以作业号开头", "类别", "名称", "单位", "NOPE", "激光切割", "每件分钟"):
        assert k in text, k
    s = spec_ok()
    s["boms"][1]["components"] = [[JN + "-SH2", 1]]
    s["items"].append({"code": JN + "-SH2", "name": "x", "kind": "make", "uom": "Nos"})
    s["boms"].append({"item": JN + "-SH2", "routing": [["下料 Sawing", 1]], "components": [[JN + "-SH", 1]]})
    assert any("循环" in e for e in ED.check(s, JN)[0])
    s = spec_ok()
    del s["items"][1]["price"], s["items"][1]["supplier"]
    errs, warns = ED.check(s, JN)
    assert not errs and len(warns) == 2                               # 没单价、没供应商：提醒，不挡
    assert ED.check({"items": [], "boms": []}, JN)[0] == ["要有作业 {} 本身的物料清单".format(JN)]


def test_fingerprint_and_bottom_up():
    a, b = spec_ok(), spec_ok()
    b["note"] = "说明不算进指纹"
    assert ED.fingerprint(a) == ED.fingerprint(b)
    b["boms"][1]["routing"][1][1] = 21
    assert ED.fingerprint(a) != ED.fingerprint(b)
    assert [x["item"] for x in ED.bottom_up(a)] == [JN + "-SH", JN]


def test_draft_from_estimate_and_copy_as_new():
    lines = E.draft(None, {"requirement": "参照 WQR-105"})["lines"] + [{"kind": "outside", "desc": "喷涂", "unit_price": 85}]
    d = ED.from_estimate({"job_no": JN}, lines)
    rt, comps = F.BOMS["WQR-105"]
    assert d["boms"][0]["components"] == [[c, q] for c, q in comps] and d["outside"][0]["desc"] == "喷涂"
    assert ED.check(d, JN)[0] == []
    sub = next(c for c, _ in comps if c in F.BOMS)                    # 第一个自制部件
    d2 = ED.copy_as_new(d, JN, JN, sub, "A")
    assert JN + "-A" in [c for c, _ in d2["boms"][0]["components"]] and sub not in [c for c, _ in d2["boms"][0]["components"]]
    assert d2["boms"][1]["components"] == [[c, q] for c, q in F.BOMS[sub][1]] and ED.check(d2, JN)[0] == []
    assert d["boms"][0]["components"] == [[c, q] for c, q in comps]  # 原稿不动
    with pytest.raises(E.EtoError):
        ED.copy_as_new(d2, JN, JN, sub, "B")                          # 父件里已经没有它了
    with pytest.raises(E.EtoError):
        ED.copy_as_new(d, JN, JN, "BOLT-M8x25", "C")                  # 外购件不能复制
    # 没有照产品起草：估算行直接当子件和工艺，没编号的成本单新物料
    d3 = ED.from_estimate({"job_no": JN}, [{"kind": "material", "item_code": "RM-45-D50", "qty_per": 2},
                                            {"kind": "buyout", "desc": "非标法兰", "qty_per": 1, "unit_price": 40},
                                            {"kind": "operation", "op": "粗车 Rough turning", "setup_min": 10, "run_min": 15}])
    assert d3["items"][0]["code"] == JN + "-01" and d3["boms"][0]["routing"] == [["粗车 Rough turning", 15]]
    assert ED.check(d3, JN)[0] == []


@pytest.fixture(scope="module")
def db():
    pytest.importorskip("psycopg")
    import psycopg

    from hub.db import DB
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_etod_test with (force)")
            c.execute("create database wq_etod_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    d = DB(base + "/wq_etod_test")
    d.init()
    E.init(d)
    ED.init(d)
    return d


def _done(db, action, pid, pv, created):
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, status, decided_at, confirmed_by, result) "
         "values (%s,'teach',%s,'t',%s,'executed',now(),'王厂长',%s)",
         (pid, action, json.dumps(pv, ensure_ascii=False), json.dumps({"created": created})))
    (E.on_proposal_done if action == "eto_quote" else ED.on_proposal_done)(db, action, pv, "teach")


@pytest.fixture
def keep_master():
    """发布会把设计并入工厂主数据：测完还原，不影响别的测试"""
    saved = {k: dict(getattr(F, k)) for k in ("ITEMS", "BOMS", "ROUTINGS")}
    yield
    for k, v in saved.items():
        d = getattr(F, k)
        d.clear()
        d.update(v)


def test_order_design_release_flow(db, keep_master):
    import datetime as dt

    from hub import mrp
    j = E.new_job(db, "teach", "王销售", "示例·客户甲", "非标减速器", "参照 WQR-105", 2, [5], "2026-12-30", cfg=CFG)
    jn = j["job_no"]
    E.save_estimate(db, "teach", jn, [{"kind": "material", "item_code": "RM-45-D50", "qty_per": 3},
                                      {"kind": "outside", "desc": "喷涂", "unit_price": 85}], "", "王销售")
    with pytest.raises(E.EtoError):
        ED.order_preview(db, "teach", jn)                             # 还没报价
    _done(db, "eto_quote", "P-Q1", E.quote_preview(db, "teach", jn, CFG), [["Project", jn], ["Item", jn], ["Quotation", "SAL-QTN-1"]])
    pv = ED.order_preview(db, "teach", jn, today=dt.date(2026, 11, 10))
    so = pv["sales_order"]
    ps = so["payment_schedule"]
    assert so["project"] == jn and so["quotation"] == "SAL-QTN-1" and so["delivery_date"] == "2026-12-30"
    assert [p["invoice_portion"] for p in ps] == [30, 60, 10] and round(sum(p["payment_amount"] for p in ps), 2) == so["amount"]
    assert ps[0]["due_date"] == "2026-11-10" and ps[1]["due_date"] == "2026-12-30" and ps[2]["due_date"] == "2027-01-09"   # 验收 = 交期 + 10 天
    assert len({p["due_date"] for p in ps}) == len(ps)                     # ERPNext 不许两期同一天
    with pytest.raises(E.EtoError):
        ED.order_preview(db, "teach", jn, "2026-01-01", today=dt.date(2026, 11, 10))       # 交期早于今天
    # 没接单不能发布
    ED.save(db, "teach", jn, {"items": [], "boms": [{"item": jn, "routing": [["总装 Final assembly", 30]], "components": [["SA-100", 1]]}]}, "李设计")
    with pytest.raises(E.EtoError):
        ED.release_preview(db, "teach", jn)
    _done(db, "eto_order", "P-O1", pv, [["Sales Order", "SAL-ORD-1"]])
    j = E.job(db, "teach", jn)
    assert (j["status"], j["sales_order"]) == ("ordered", "SAL-ORD-1")
    with pytest.raises(E.EtoError):
        ED.order_preview(db, "teach", jn)                             # 不重复接单
    # 设计没发布：不能算料下工单
    with pytest.raises(ValueError, match="设计还没发布"):
        mrp.plan_order(db, "c", jn, 2, "2026-12-30", "teach")
    # 设计有错：不能发布
    ED.save(db, "teach", jn, {"items": [], "boms": [{"item": jn, "routing": [["激光切割", 30]], "components": [["SA-100", 1]]}]}, "李设计")
    with pytest.raises(E.EtoError, match="没通过检查"):
        ED.release_preview(db, "teach", jn)
    s = {"items": [{"code": jn + "-SH", "name": "输出轴（加长）", "kind": "make", "uom": "Nos"}],
         "boms": [{"item": jn, "routing": [["总装 Final assembly", 45]], "components": [["SA-100", 1], [jn + "-SH", 1]]},
                  {"item": jn + "-SH", "routing": [["粗车 Rough turning", 20]], "components": [["RM-45-D50", 4.4]]}]}
    assert ED.save(db, "teach", jn, s, "李设计") == 1                 # 没发布：同一版覆盖
    # 第 150 轮 150d：本单新件要有批准的图纸才能发布；草稿里的新件“设计发布与审批”认得
    with pytest.raises(E.EtoError, match="图纸"):
        ED.release_preview(db, "teach", jn)
    assert ED.draft_item(db, "teach", jn + "-SH") == "输出轴（加长）" and ED.draft_item(db, "teach", jn + "-ZZ") is None
    from hub import plm
    plm.submit(db, lambda *a: None, "teach", "李设计", "u-li", jn + "-SH", drawing=b"<svg xmlns='http://www.w3.org/2000/svg'/>",
               drawing_name="SH.svg", note="加长 40 mm")                 # 教学模式提交即批准
    dr, miss = ED.drawings(db, "teach", s)
    assert not miss and dr[jn + "-SH"]["rev"] == 2 and dr[jn + "-SH"]["by"] == "李设计"
    rp = ED.release_preview(db, "teach", jn)
    assert rp["drawings"] == dr and rp["fingerprint"] == ED.fingerprint(s, dr) != ED.fingerprint(s)     # 图纸版本算进指纹
    assert [b["item"] for b in rp["boms"]] == [jn + "-SH", jn]
    assert rp["boms"][0]["operations"][0]["workstation"] == F.OPERATIONS["粗车 Rough turning"] and rp["boms"][1]["components"][1]["new"]
    _done(db, "eto_release", "P-R1", rp, [["Item", jn + "-SH"], ["BOM", "BOM-x"], ["BOM", "BOM-y"]])
    r = ED.released(db, "teach", jn)
    assert r["rev"] == 1 and r["fingerprint"] == rp["fingerprint"] and r["released_by"] == "王厂长" and r["drawings"] == dr
    assert F.BOMS[jn][1] == [("SA-100", 1.0), (jn + "-SH", 1.0)] and F.ITEMS[jn + "-SH"][1] == "make"
    with pytest.raises(E.EtoError):
        ED.release_preview(db, "teach", jn)                           # 同一版不重复发布
    # 发布后改：出第 2 版，第 1 版原样
    s["boms"][1]["routing"][0][1] = 25
    assert ED.save(db, "teach", jn, s, "李设计") == 2
    assert ED.released(db, "teach", jn)["spec"]["boms"][1]["routing"][0][1] == 20
    d = ED.detail(db, "teach", jn)
    assert d["design"]["rev"] == 2 and d["design"]["status"] == "draft" and d["fingerprint_now"] != r["fingerprint"]
    # 发布后的作业可以算料（物料清单已并入主数据）
    out = mrp.plan_order(db, "c", jn, 2, "2026-12-30", "teach")
    assert any(r_["item_code"] == "RM-45-D50" for r_ in out["mrp"])
    # 重启后从库里并回主数据
    del F.BOMS[jn], F.ITEMS[jn + "-SH"]
    ED.load_all(db)
    assert jn in F.BOMS and jn + "-SH" in F.ITEMS


def test_bridge_order_and_release(mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    jn = "JOB-2026-0099"
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    M.db.setdefault("Item", {})[jn] = {"name": jn, "item_code": jn, "docstatus": 0}

    def run(action, pv):
        msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-" + action, "action": action, "preview": pv}}
        r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(r.stdout)
    so = {"customer": "示例·客户甲 (Demo)", "item_code": jn, "qty": 2, "rate": 1000, "amount": 2000, "transaction_date": "2026-11-10",
          "delivery_date": "2026-12-30", "project": jn, "quotation": "SAL-QTN-X",
          "payment_schedule": [{"description": "订金", "invoice_portion": 30, "payment_amount": 600, "due_date": "2026-11-10"},
                               {"description": "发货", "invoice_portion": 70, "payment_amount": 1400, "due_date": "2026-12-30"}]}
    bad = dict(so, payment_schedule=[dict(p, due_date="2026-12-30") for p in so["payment_schedule"]])
    dup, _ = run("eto_order", {"job": {"job_no": jn}, "sales_order": bad})
    assert dup[-1]["action"] == "failed" and "duplicate due dates" in dup[-1]["error"]       # 模拟 ERPNext 和真的一样拦
    first, _ = run("eto_order", {"job": {"job_no": jn}, "sales_order": so})
    sod = M.db["Sales Order"][first[-1]["created"][0][1]]
    assert sod["project"] == jn and [p["invoice_portion"] for p in sod["payment_schedule"]] == [30, 70] and first[-1]["project"] == jn
    pv = {"job": {"job_no": jn, "rev": 1}, "fingerprint": "fp1",
          "items": [{"code": jn + "-SH", "name": "轴", "kind": "make", "uom": "Nos", "price": None, "item_group": F.KIND_GROUP["make"]}],
          "boms": [{"item": jn + "-SH", "components": [{"item_code": "RM-45-D50", "qty": 4.4, "uom": "Kg", "new": False}],
                    "operations": [{"operation": "粗车 Rough turning", "workstation": "数控车床 CNC-L01", "time_in_mins": 20, "hour_rate": 48}]},
                   {"item": jn, "components": [{"item_code": jn + "-SH", "qty": 1, "uom": "Nos", "new": True}],
                    "operations": [{"operation": "总装 Final assembly", "workstation": "装配工位 ASM-01", "time_in_mins": 45, "hour_rate": 34}]}]}
    first, again = run("eto_release", pv)
    kinds = [c[0] for c in first[-1]["created"]]
    assert kinds == ["Item", "BOM", "BOM"] and not any(x["action"] == "failed" for x in first + again)
    top = M.db["BOM"][first[-1]["created"][2][1]]
    assert top["wq_fingerprint"] == "fp1" and top["items"][0]["bom_no"] == first[-1]["created"][1][1] and top["is_default"] == 1
    assert len([b for b in M.db["BOM"].values() if b["item"] == jn]) == 1          # 再执行一次：同一指纹不重建


def test_require_drawing_switch(monkeypatch):
    """第 150 轮 150d：清单 eto.require_drawing，没写为开；写 false 关掉；不是 true / false 报错"""
    from factory import plant as P
    monkeypatch.setattr(F, "ETO", {"prefix": "JOB-"}, raising=False)
    assert ED.require_drawing() is True
    monkeypatch.setattr(F, "ETO", {"prefix": "JOB-", "require_drawing": False}, raising=False)
    assert ED.require_drawing() is False
    assert P._validate_eto({"require_drawing": True}) == []
    assert any("require_drawing" in e for e in P._validate_eto({"require_drawing": "yes"}))
