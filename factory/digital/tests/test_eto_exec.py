"""第 139 轮 139e：作业的工单与设计版本（旧版物料清单不许下达）、作业单、设计工时、作业成本（估算对实际，实际取自仿真车间的报工）、
桥接 → 模拟 ERPNext（设计工时进 Timesheet）。"""
import json
import os

import pytest

from factory import data as F
from hub import eto as E
from hub import eto_design as ED
from hub import eto_exec as EX
from tests.test_eto import BRIDGE_SCRIPT, CFG, mock_erp  # noqa: F401
from tests.test_eto_design import keep_master  # noqa: F401
from tests.test_eto_mrp import _erp, db  # noqa: F401
from tests.test_sim import make_engine, run_to_end
from sim.engine import OP_UNITS

OPS = [["下料 Sawing", 3], ["粗车 Rough turning", 20], ["零件检验 Part inspection", 6]]


@pytest.fixture
def job(db, keep_master):  # noqa: F811
    EX.init(db)
    j = E.new_job(db, "teach", "王销售", "示例·客户丙", "非标轴", "", 2, None, "2027-01-29", cfg=CFG)
    jn = j["job_no"]
    lines = [{"kind": "material", "item_code": "RM-45-D50", "qty_per": 4},
             {"kind": "operation", "op": "粗车 Rough turning", "setup_min": 10, "run_min": 20},
             {"kind": "engineering", "desc": "改图", "hours": 3}]
    E.save_estimate(db, "teach", jn, lines, "", "王销售")
    db.x("update eto_job set status='ordered', quoted_rev=1, quotation='Q', sales_order='SO-1', project='PROJ-0042' where mode='teach' and job_no=%s", (jn,))
    spec = {"items": [], "boms": [{"item": jn, "routing": OPS, "components": [["RM-45-D50", 4]]}]}
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'released','fp1')", (jn, json.dumps(spec)))
    ED.merge(jn, "非标轴", spec)
    _erp(db, "BOM", "BOM-1", item=jn, docstatus=1, is_default=1, wq_fingerprint="fp1")
    _erp(db, "BOM", "BOM-0", item=jn, docstatus=1, is_default=0, wq_fingerprint="fp0")
    _erp(db, "Work Order", "WO-E1", docstatus=1, status="Not Started", project="PROJ-0042", production_item=jn, qty=2, bom_no="BOM-1",
         planned_start_date="2026-11-12")
    _erp(db, "Work Order", "WO-E0", docstatus=1, status="Not Started", project="PROJ-0042", production_item=jn, qty=1, bom_no="BOM-0",
         planned_start_date="2026-11-11")
    _erp(db, "Work Order", "WO-OTHER", docstatus=1, status="Not Started", project="PROJ-9", production_item="SH-301", qty=5)
    return jn


def test_work_orders_design_version_and_traveler(db, job):  # noqa: F811
    wos = {w["name"]: w for w in EX.work_orders(db, "teach", job)}
    assert set(wos) == {"WO-E1", "WO-E0"}                                         # 只要这个作业项目的
    assert wos["WO-E1"]["current_design"] is True and wos["WO-E0"]["current_design"] is False
    EX.release_check(db, "teach", job, "WO-E1")
    with pytest.raises(E.EtoError, match="旧版物料清单"):
        EX.release_check(db, "teach", job, "WO-E0")
    with pytest.raises(E.EtoError, match="不是这个作业"):
        EX.release_check(db, "teach", job, "WO-OTHER")
    t = EX.traveler(db, "teach", job, "WO-E1")
    assert t["fingerprint"] == "fp1" and t["design_rev"] == 1 and [o["operation"] for o in t["operations"]] == [o for o, _ in OPS]
    assert t["operations"][1]["total_min"] == 40 and t["components"][0]["qty"] == 8
    assert t["operations"][2]["inspection"] == ("零件检验 Part inspection" in F.INSPECTION_OPS)


def test_job_cost_from_shop_events(db, job):  # noqa: F811
    from hub.historian import Historian
    eng, clock, out = make_engine(mode="teach")
    for op, _ in OPS:
        ok, why = eng.command(OP_UNITS[op][0], {"command": "dispatch", "work_order": "WO-E1", "operation": op, "qty": 2, "item": job,
                                                "routing": OPS}, "WO-E1")
        assert ok, why
    run_to_end(eng, clock)
    h = Historian(db)
    for tp, msg in out:
        h.handle(tp, msg)
    for k in range(2):
        EX.record_hours(db, "teach", {"job": {"job_no": job}, "hours": 1.5, "note": "改图", "who": "李设计", "day": "2026-11-12"}, "P-H{}".format(k))
    c = EX.cost(db, "teach", job)
    est, act = c["estimate"], c["actual"]
    assert est["material"] == round(4 * 1.6 * 2, 2) and est["engineering"] == 3 * 65 and est["rev"] == 1
    line = next(x for x in c["work_orders"] if x["work_order"] == "WO-E1")
    assert line["done"] == 2 and line["material"] == round(4 * 1.6 * 2, 2) and line["operations_actual"] > line["operations_std"] > 0
    assert act["material"] == line["material"] and act["engineering_hours"] == 3 and act["engineering"] == 3 * 65
    # 139g：设计里没有外协，外协实际就是 0、合计可算（有外协但没下采购单时是“未知”，见 test_eto_billing）
    assert act["outside"] == 0.0 and not any("外协" in u for u in c["unknown"])
    assert act["total"] == round(act["material"] + act["operations"] + act["engineering"], 2)


def test_hours_rules_and_bridge_timesheet(db, job, mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    with pytest.raises(E.EtoError):
        EX.hours_preview(db, "teach", job, 30, "", "李设计")
    pv = EX.hours_preview(db, "teach", job, 2, "出图", "李设计", "2026-11-12")
    assert pv["job"]["project"] == "PROJ-0042" and pv["key"]
    url, M = mock_erp
    M.db.setdefault("Project", {})["PROJ-0042"] = {"name": "PROJ-0042", "project_name": job}
    msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-TS1", "action": "eto_hours", "preview": pv}}
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    first, _ = json.loads(r.stdout)
    assert not any(x["action"] == "failed" for x in first), [x.get("error") for x in first]
    ts = M.db["Timesheet"][first[-1]["created"][0][1]]
    assert ts["time_logs"][0]["project"] == "PROJ-0042" and ts["time_logs"][0]["hours"] == 2 and first[-1]["projects"] == ["PROJ-0042"]
    # 执行完：记进作业的设计工时，只记一次
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview, status) values ('P-TS1','teach','eto_hours','t',%s,'executed')",
         (json.dumps(pv, ensure_ascii=False),))
    n0 = len(EX.hours(db, "teach", job))
    EX.on_proposal_done(db, "eto_hours", pv, "teach")
    EX.on_proposal_done(db, "eto_hours", pv, "teach")
    assert len(EX.hours(db, "teach", job)) == n0 + 1


def test_bridge_summary_keeps_bom_fingerprint():
    """真 ERPNext 演练 42888610320 查出：summarize 里有两个 case 'BOM'，前一个不带指纹，作业工单永远认不出发布版。
    这里直接调桥接的 summarize，并查整个 switch 没有重复的 case。"""
    import re
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which(os.environ.get("WQ_NODE", "node")):
        pytest.skip("需要 node")
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    src = erp_js.read_text(encoding="utf-8")
    body = src[src.index("function summarize("):]
    body = body[:body.index("\n}\n")]
    cases = re.findall(r"case '([^']+)':", body)
    assert len(cases) == len(set(cases)), sorted({c for c in cases if cases.count(c) > 1})
    js = ("const {summarize} = require(process.argv[1]);"
          "console.log(JSON.stringify(summarize('BOM', {item: 'J', is_default: 1, docstatus: 1, wq_fingerprint: 'fp9', project: 'P',"
          " items: [{item_code: 'A', qty: 2}]})));")
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", js, str(erp_js)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr[-1000:]
    d = json.loads(r.stdout)
    assert d["wq_fingerprint"] == "fp9" and d["project"] == "P" and d["items"] == [{"item_code": "A", "qty": 2}]


def test_traveler_shows_approved_drawing(db, job):  # noqa: F811
    """第 150 轮 150d：作业单写出按哪张批准的图做（发布时记下的图纸版本）"""
    assert EX.traveler(db, "teach", job, "WO-E1")["drawing"] is None
    db.x("update eto_design set drawings=%s where mode='teach' and job_no=%s and rev=1",
         (json.dumps({job: {"rev": 3, "by": "王审批", "at": "2026-11-11", "submission": "s1"}}), job))
    d = EX.traveler(db, "teach", job, "WO-E1")["drawing"]
    assert d == {"rev": 3, "by": "王审批", "at": "2026-11-11", "submission": "s1"}
