"""第 150 轮 150a：设计变更处理——建议规则（纯函数，六种情况）、变更损失手算、没处理完挡住再发布和再算料、
处理后“照用”的旧版工单可以下达、桥接 → 模拟 ERPNext（取消、停止、改量、关闭）。"""
import json
import os

import pytest

from hub import eto as E
from hub import eto_change as EC
from hub import eto_design as ED
from hub import eto_exec as EX
from hub import eto_mrp as EM
from tests.test_eto import BRIDGE_SCRIPT, CFG, mock_erp  # noqa: F401
from tests.test_eto_design import keep_master  # noqa: F401
from tests.test_eto_mrp import _erp, db  # noqa: F401

JN = "JOB-2026-0050"


# ---------------------------------------------------------------- 纯函数
def test_explode_and_changed():
    boms = {JN: ([("总装 Final assembly", 30.0)], [(JN + "-SH", 1.0), ("RM-45-D50", 2.0)]),
            JN + "-SH": ([("粗车 Rough turning", 20.0)], [("RM-45-D50", 4.4)])}
    need = EC.explode(JN, 3, boms)
    assert need[JN] == 3 and need[JN + "-SH"] == 3 and need["RM-45-D50"] == pytest.approx(3 * 2 + 3 * 4.4)
    new = dict(boms, **{JN + "-SH": ([("粗车 Rough turning", 25.0)], [("RM-45-D50", 4.4)])})
    assert EC.changed(boms, new, JN + "-SH") and not EC.changed(boms, new, JN)
    assert EC.changed(boms, {JN: boms[JN]}, JN + "-SH")                     # 新版里没有了也算变了


def test_suggest_rules_and_loss_by_hand():
    wos = [{"name": "WO-A", "item": JN + "-SH", "qty": 2, "started": False, "spent": None},   # 改了、没开工 → 换新版
           {"name": "WO-B", "item": JN + "-SH", "qty": 2, "started": True, "spent": 31.5},   # 改了、已开工 → 照用（可停止）
           {"name": "WO-C", "item": JN, "qty": 2, "started": False, "spent": None},          # 没变 → 照用
           {"name": "WO-D", "item": JN + "-OLD", "qty": 2, "started": True, "spent": 12.0}]  # 新版不要了、已开工 → 停止
    need_old = {JN: 2, JN + "-SH": 2, JN + "-OLD": 2, JN + "-PL": 4, "RM-45-D50": 10, "BRG-6206": 4}
    need_new = {JN: 2, JN + "-SH": 2, JN + "-PL": 1, "RM-45-D50": 6, "BRG-6206": 4}
    buys = [{"doctype": "Material Request", "name": "MR-1", "lines": [{"item_code": "RM-45-D50", "qty": 3, "received": 0, "rate": None}]},
            {"doctype": "Purchase Order", "name": "PO-2", "lines": [{"item_code": "RM-45-D50", "qty": 7, "received": 0, "rate": 1.6}]},
            {"doctype": "Purchase Order", "name": "PO-1", "lines": [{"item_code": JN + "-PL", "qty": 4, "received": 4, "rate": 12.5}]},
            {"doctype": "Purchase Order", "name": "PO-0", "lines": [{"item_code": "BRG-6206", "qty": 4, "received": 0, "rate": 6}]}]
    rows = {r["name"]: r for r in EC.suggest(JN, wos, buys, need_old, need_new, {JN + "-SH", JN + "-OLD"})}
    assert rows["WO-A"]["suggest"] == "renew" and rows["WO-A"]["options"] == ["renew", "keep"]
    assert rows["WO-B"]["suggest"] == "keep" and "stop" in rows["WO-B"]["options"] and rows["WO-B"]["loss"]["stop"] == 31.5
    assert rows["WO-C"]["suggest"] == "keep" and rows["WO-C"]["options"] == ["keep"]
    assert rows["WO-D"]["suggest"] == "stop" and rows["WO-D"]["loss"]["stop"] == 12.0
    # 原材料少用 4：请购单 3 全扣 → 取消；再从采购单扣 1 → 改量 7 → 6
    assert rows["MR-1"]["suggest"] == "cancel"
    assert rows["PO-2"]["suggest"] == "qty" and rows["PO-2"]["lines"][0]["new_qty"] == 6 and rows["PO-2"]["loss"]["qty"] == 0
    # 本单专用件少用 3，可 4 件都到了：关闭；多出的 3 件 × 12.5 = 37.5 记变更损失
    assert rows["PO-1"]["suggest"] == "close" and rows["PO-1"]["loss"]["close"] == 37.5
    # 轴承用量没变：照用，不用处理
    assert rows["PO-0"]["suggest"] == "keep" and rows["PO-0"]["needs"] is False


def test_suggest_cancel_po_and_unknown_rate():
    need_old, need_new = {JN + "-PL": 2, JN + "-BX": 1}, {}
    buys = [{"doctype": "Purchase Order", "name": "PO-9", "lines": [{"item_code": JN + "-PL", "qty": 2, "received": 0, "rate": 5}]},
            {"doctype": "Purchase Order", "name": "PO-8", "lines": [{"item_code": JN + "-BX", "qty": 1, "received": 1, "rate": None}]}]
    rows = {r["name"]: r for r in EC.suggest(JN, [], buys, need_old, need_new, set())}
    assert rows["PO-9"]["suggest"] == "cancel" and rows["PO-9"]["loss"]["cancel"] == 0
    assert rows["PO-8"]["suggest"] == "close" and rows["PO-8"]["loss"]["close"] is None and rows["PO-8"]["loss_unknown"]   # 单价缺：未知，不当 0


# ---------------------------------------------------------------- 数据库：发布第 2 版 → 处理 → 放行
@pytest.fixture
def changed_job(db, keep_master):  # noqa: F811
    EX.init(db)
    EC.init(db)
    j = E.new_job(db, "teach", "王销售", "示例·客户丙", "非标轴", "", 2, None, "2027-01-29", cfg=CFG)
    jn = j["job_no"]
    db.x("update eto_job set status='ordered', quoted_rev=1, quotation='Q', sales_order='SO-1', project='PROJ-0050' where mode='teach' and job_no=%s", (jn,))
    v1 = {"items": [{"code": jn + "-PL", "name": "压板", "kind": "buy", "uom": "Nos", "price": 10}],
          "boms": [{"item": jn, "routing": [["粗车 Rough turning", 20]], "components": [["RM-45-D50", 4], [jn + "-PL", 1]]}]}
    v2 = {"items": [], "boms": [{"item": jn, "routing": [["粗车 Rough turning", 25]], "components": [["RM-45-D50", 3]]}]}
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'released','fp1')", (jn, json.dumps(v1)))
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,2,%s,'released','fp2')", (jn, json.dumps(v2)))
    ED.merge(jn, "非标轴", v1)
    ED.merge(jn, "非标轴", v2)
    _erp(db, "BOM", "BOM-1", item=jn, docstatus=1, is_default=0, wq_fingerprint="fp1")
    _erp(db, "BOM", "BOM-2", item=jn, docstatus=1, is_default=1, wq_fingerprint="fp2")
    _erp(db, "Work Order", "WO-1", docstatus=1, status="Not Started", project="PROJ-0050", production_item=jn, qty=2, bom_no="BOM-1",
         planned_start_date="2026-11-12")
    _erp(db, "Material Request", "MR-1", docstatus=1, status="Pending", project="PROJ-0050",
         items=[{"item_code": "RM-45-D50", "qty": 8, "project": "PROJ-0050"}])
    _erp(db, "Purchase Order", "PO-1", docstatus=1, status="To Receive and Bill", project="PROJ-0050", transaction_date="2026-11-11",
         items=[{"item_code": jn + "-PL", "qty": 2, "received_qty": 1, "rate": 10}])
    return jn


def test_change_plan_gates_and_record(db, changed_job):  # noqa: F811
    jn = changed_job
    p = EC.plan(db, "teach", jn)
    rows = {r["name"]: r for r in p["rows"]}
    assert p["rev"] == 2 and p["from_rev"] == 1 and jn in p["changed_items"]
    assert rows["WO-1"]["suggest"] == "renew"
    assert rows["MR-1"]["suggest"] == "cancel"                                  # 原材料 8 → 6
    assert rows["PO-1"]["suggest"] == "close" and rows["PO-1"]["loss"]["close"] == 10.0     # 压板不要了，到了 1 件 × 10
    assert p["open"] == 3
    # 没处理完：不能再算料，也不能再发布
    with pytest.raises(E.EtoError, match="设计变更"):
        EM.plan(db, "teach", jn)
    ED.save(db, "teach", jn, {"items": [], "boms": [{"item": jn, "routing": [["粗车 Rough turning", 24]], "components": [["RM-45-D50", 3]]}]}, "李工艺")
    with pytest.raises(E.EtoError, match="没处理"):
        ED.release_preview(db, "teach", jn)
    with pytest.raises(E.EtoError, match="旧版物料清单"):
        EX.release_check(db, "teach", jn, "WO-1")
    with pytest.raises(E.EtoError, match="只能选"):
        EC.preview(db, "teach", jn, {"Work Order/WO-1": "qty"}, "张计划")
    pv = EC.preview(db, "teach", jn, {"Work Order/WO-1": "keep"}, "张计划")   # 工单照用（老师可以这样教“让步”）
    acts = {a["name"]: a for a in pv["actions"]}
    assert acts["WO-1"]["action"] == "keep" and acts["MR-1"]["action"] == "cancel" and acts["PO-1"]["action"] == "close"
    EC.record(db, "teach", pv, "P-C1")
    p2 = EC.plan(db, "teach", jn)
    assert p2["open"] == 0 and all(r["decided"] for r in p2["rows"] if r["needs"])
    EX.release_check(db, "teach", jn, "WO-1")                                   # 选了照用：旧版工单可以下达
    lo = EC.loss(db, "teach", jn)
    assert lo["amount"] == 10.0 and not lo["unknown"]
    with pytest.raises(E.EtoError, match="都已处理"):
        EC.preview(db, "teach", jn, {}, "张计划")


def test_no_change_with_one_release(db, keep_master):  # noqa: F811
    EC.init(db)
    j = E.new_job(db, "teach", "王销售", "示例·客户丙", "非标轴", "", 1, None, "2027-01-29", cfg=CFG)
    jn = j["job_no"]
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'released','fpA')",
         (jn, json.dumps({"items": [], "boms": [{"item": jn, "routing": [["粗车 Rough turning", 20]], "components": [["RM-45-D50", 4]]}]})))
    assert EC.plan(db, "teach", jn)["rows"] == [] and EC.open_count(db, "teach", jn) == 0


# ---------------------------------------------------------------- 桥接 → 模拟 ERPNext
def test_bridge_change_actions(mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    M.db.setdefault("Work Order", {}).update({
        "WO-C1": {"name": "WO-C1", "docstatus": 1, "status": "Not Started", "production_item": JN, "qty": 2, "produced_qty": 0},
        "WO-C2": {"name": "WO-C2", "docstatus": 1, "status": "In Process", "production_item": JN, "qty": 2, "produced_qty": 1}})
    M.db.setdefault("Material Request", {})["MR-C1"] = {"name": "MR-C1", "docstatus": 1, "status": "Pending", "items": []}
    M.db.setdefault("Purchase Order", {}).update({
        "PO-C1": {"name": "PO-C1", "docstatus": 1, "status": "To Receive and Bill",
                  "items": [{"name": "r1", "idx": 1, "item_code": "RM-45-D50", "qty": 7, "received_qty": 0, "rate": 1.6},
                            {"name": "r2", "idx": 2, "item_code": "BRG-6206", "qty": 4, "received_qty": 0, "rate": 6}]},
        "PO-C2": {"name": "PO-C2", "docstatus": 1, "status": "To Receive and Bill",
                  "items": [{"name": "r3", "idx": 1, "item_code": JN + "-PL", "qty": 4, "received_qty": 4, "rate": 12.5}]}})
    pv = {"job": {"job_no": JN, "rev": 2},
          "actions": [{"doctype": "Work Order", "name": "WO-C1", "action": "renew"},
                      {"doctype": "Work Order", "name": "WO-C2", "action": "stop"},
                      {"doctype": "Material Request", "name": "MR-C1", "action": "cancel"},
                      {"doctype": "Purchase Order", "name": "PO-C1", "action": "qty", "lines": [{"item_code": "RM-45-D50", "qty": 6}]},
                      {"doctype": "Purchase Order", "name": "PO-C2", "action": "close"},
                      {"doctype": "Work Order", "name": "WO-KEEP", "action": "keep"}]}
    msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-CHG", "action": "eto_change", "preview": pv}}
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    first, again = json.loads(r.stdout)
    assert not any(x["action"] == "failed" for x in first + again), first + again
    assert M.db["Work Order"]["WO-C1"]["docstatus"] == 2 and M.db["Work Order"]["WO-C2"]["status"] == "Stopped"
    assert M.db["Material Request"]["MR-C1"]["docstatus"] == 2
    assert [(i["item_code"], i["qty"]) for i in M.db["Purchase Order"]["PO-C1"]["items"]] == [("RM-45-D50", 6), ("BRG-6206", 4)]
    assert M.db["Purchase Order"]["PO-C2"]["status"] == "Closed"
    assert first[-1]["proposal_done"] and len(first[-1]["created"]) == 5        # “照用”不动 ERPNext
