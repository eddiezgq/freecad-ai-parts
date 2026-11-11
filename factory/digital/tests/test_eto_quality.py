"""第 139 轮 139f：检验计划（检查、照原件模板起草、AI 只写图纸上的、批准冻结、起草人不能自批）、检验判定（缺值未知）、
记录不可改只能作废、不合格开不合格品单、发货关口、合格证、桥接 → 模拟 ERPNext（质量检验单、发货单）。"""
import json
import os

import pytest

from factory import data as F
from hub import eto as E
from hub import eto_quality as Q
from tests.test_eto import BRIDGE_SCRIPT, CFG, mock_erp  # noqa: F401
from tests.test_eto_mrp import _erp, db  # noqa: F401

JN = "JOB-2026-0050"
CH = [{"code": "len", "name": "总长", "item": JN, "kind": "final", "nominal": 300, "lo": 299.8, "hi": 300.2, "unit": "mm"},
      {"code": "bore", "name": "孔径", "item": JN + "-SH", "kind": "both", "nominal": 35.01, "lo": 35.002, "hi": 35.018, "unit": "mm"}]
ITEMS = [JN, JN + "-SH"]


def test_check_plan_and_judge():
    assert Q.check_plan(CH, ITEMS, JN) == []
    bad = [dict(CH[0], code="Len"), dict(CH[1], lo=36), dict(CH[1], code="bore", item="X")]
    t = "；".join(Q.check_plan(bad, ITEMS, JN))
    assert "小写" in t and "下限" in t and "重复" in t and "不是这一单" in t
    assert any("至少要有一项终检" in e for e in Q.check_plan([CH[1]], ITEMS, JN))
    assert Q.check_plan([dict(CH[0], hi=None)], ITEMS, JN)[0].endswith("上下限都要写（数字）")
    r, rows = Q.judge(CH, {"len": 300.1}, "final", JN)
    assert r == "pass" and [x["code"] for x in rows] == ["len"]
    assert Q.judge(CH, {"len": 300.3}, "final", JN)[0] == "fail"
    assert Q.judge(CH, {}, "final", JN)[0] == "unknown"                         # 缺值不算合格
    assert Q.judge(CH, {"bore": 35.01}, "fai", JN + "-SH")[0] == "pass"         # “两者”的项首件也检
    assert Q.judge(CH, {"len": 300}, "fai", JN) == ("unknown", [])              # 作业本身没有首件项


def test_plan_from_templates_and_ai_draft():
    spec = {"items": [{"code": JN + "-SH", "name": "输出轴", "kind": "make", "uom": "Nos", "from": "SH-301"}]}
    d = Q.draft_plan(None, {"job_no": JN, "title": "t"}, ITEMS, spec, "")
    tmpl = F.inspection_templates()[F.ITEMS["SH-301"][5]]
    assert d["source"] == "rules" and len(d["chars"]) == len([p for p in tmpl if p.get("min") is not None])
    assert d["chars"][0]["lo"] == tmpl[0]["min"] and d["chars"][0]["item"] == JN + "-SH" and "终检" in d["note"]
    assert Q.check_plan(d["chars"], ITEMS, JN) == ["作业 {} 本身至少要有一项终检".format(JN)]   # 照抄的不够：要补作业本身的终检

    class FakeLLM:
        name = "fake"

        def available(self):
            return True

        def run(self, system, messages, tools, call, max_turns=6):
            assert "明确写了" in system and "图纸文字" in messages[0]["content"] and "Ø300±0.2" in messages[0]["content"]
            call("submit_plan", {"chars": [CH[0]], "note": "孔径公差图纸没写，请补"})
            return "", []
    d = Q.draft_plan(FakeLLM(), {"job_no": JN, "title": "t"}, ITEMS, spec, "总长 Ø300±0.2")
    assert d["chars"][0]["source"] == "ai" and d["note"].startswith("孔径")


def _job(db, jn=JN):
    Q.init(db)
    from hub import eto_design as ED
    ED.init(db)
    db.x("delete from eto_job where job_no=%s", (jn,))
    db.x("insert into eto_job (mode, job_no, customer, title, qty, qty_breaks, status, sales_order, project, due_date) "
         "values ('teach',%s,'示例·客户丁','非标轴',2,'[2]','ordered','SO-50','PROJ-0050','2027-01-29')", (jn,))
    db.x("insert into eto_design (mode, job_no, rev, spec, status, fingerprint) values ('teach',%s,1,%s,'released','fp') on conflict do nothing",
         (jn, json.dumps({"items": [{"code": jn + "-SH", "name": "轴", "kind": "make", "uom": "Nos"}], "boms": []})))
    wos = [{"name": "WO-T", "item": jn, "qty": 2, "produced": 2, "own": True},
           {"name": "WO-S", "item": jn + "-SH", "qty": 2, "produced": 2, "own": True}]
    return wos


def test_records_ncr_lock_ship_and_certificate(db):  # noqa: F811
    wos = _job(db)
    with pytest.raises(E.EtoError, match="还没批准"):
        Q.record(db, "teach", JN, "final", "WO-T", 1, {"len": 300}, "质检甲", wos)
    Q.save_plan(db, "teach", JN, CH, "质检甲")
    with pytest.raises(E.EtoError, match="不能自己批准"):
        Q.approve_plan(db, "teach", JN, "质检甲")
    assert Q.approve_plan(db, "teach", JN, "质检乙") == 1
    assert Q.save_plan(db, "teach", JN, CH + [dict(CH[0], code="len2")], "质检甲") == 2      # 批准后再改：新版本
    assert Q.plan_approved(db, "teach", JN)["rev"] == 1
    job = E.job(db, "teach", JN)
    rec = lambda: Q.records(db, "teach", JN)  # noqa: E731
    block = Q.ship_check(job, wos, Q.plan_approved(db, "teach", JN), rec())
    assert "WO-S（{}-SH）首件检验还没合格".format(JN) in block and "终检合格 0 / 2 件" in block
    with pytest.raises(E.EtoError, match="只检第 1 件"):
        Q.record(db, "teach", JN, "fai", "WO-S", 2, {}, "质检甲", wos)
    with pytest.raises(E.EtoError, match="终检只检作业本身"):
        Q.record(db, "teach", JN, "final", "WO-S", 1, {}, "质检甲", wos)
    assert Q.record(db, "teach", JN, "fai", "WO-S", 1, {"bore": 35.01}, "质检甲", wos)["result"] == "pass"
    ok1 = Q.record(db, "teach", JN, "final", "WO-T", 1, {"len": 300.05}, "质检甲", wos)
    bad = Q.record(db, "teach", JN, "final", "WO-T", 2, {"len": 300.5}, "质检甲", wos)
    assert ok1["result"] == "pass" and bad["result"] == "fail" and bad["ncr_id"]
    ncr = db.one("select * from ncr where ncr_id=%s", (bad["ncr_id"],))
    assert ncr["part_serial"] == "WO-T#2" and ncr["detail"]["failed"][0]["code"] == "len"
    block = Q.ship_check(job, wos, Q.plan_approved(db, "teach", JN), rec())
    assert block == ["终检合格 1 / 2 件", "不合格品单还没处置：" + bad["ncr_id"]]
    # 记录不能改、不能删，只能作废
    with pytest.raises(Exception, match="不能改"):
        db.x("update eto_insp set result='pass' where id=%s", (bad["id"],))
    with pytest.raises(Exception, match="不能删除"):
        db.x("delete from eto_insp where id=%s", (bad["id"],))
    with pytest.raises(E.EtoError, match="原因"):
        Q.void(db, "teach", ok1["id"], "质检甲", "")
    # 让步接收：算终检合格
    db.x("update ncr set status='use_as_is' where ncr_id=%s", (bad["ncr_id"],))
    assert Q.ship_check(job, wos, Q.plan_approved(db, "teach", JN), rec()) == []
    pv = Q.ship_preview(db, "teach", JN, wos)
    assert pv["sales_order"] == "SO-50" and pv["qty"] == 2
    cert = Q.certificate(job, Q.plan_approved(db, "teach", JN), rec(), None)
    assert [p["piece"] for p in cert["pieces"]] == [1, 2] and cert["pieces"][1]["concession"] and cert["plan_approved_by"] == "质检乙"
    # 作废第 1 件的终检：又不够数
    Q.void(db, "teach", ok1["id"], "质检甲", "量具没校准，重测")
    with pytest.raises(E.EtoError):
        Q.void(db, "teach", ok1["id"], "质检甲", "再作废一次")
    assert "终检合格 1 / 2 件" in Q.ship_check(job, wos, Q.plan_approved(db, "teach", JN), rec())
    # 完工不够也挡
    assert any("完工 1 / 2" in x for x in Q.ship_check(job, [dict(wos[0], produced=1), wos[1]], Q.plan_approved(db, "teach", JN), rec()))
    Q.reset(db, "teach")
    assert Q.records(db, "teach", JN) == []


def test_bridge_inspection_and_ship(mock_erp):  # noqa: F811
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    ws = next(iter(M.db["Workstation"]))
    M.db.setdefault("Job Card", {})["JC-Q1"] = {"name": "JC-Q1", "work_order": "WO-Q", "operation": "出厂检验 Final inspection", "workstation": ws,
                                                "for_quantity": 2, "docstatus": 0, "time_logs": []}
    so = {"name": "SO-Q", "customer": "示例·客户丁", "company": "c", "docstatus": 1, "status": "To Deliver and Bill",
          "items": [{"name": "r1", "item_code": JN, "qty": 2, "rate": 100, "delivered_qty": 0, "warehouse": "w"}]}
    M.db.setdefault("Sales Order", {})["SO-Q"] = so

    def run(action, pv):
        msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-" + action, "action": action, "preview": pv}}
        r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        return json.loads(r.stdout)[0]
    out = run("eto_inspection", {"job": {"job_no": JN}, "inspection_id": 1, "kind": "final", "work_order": "WO-Q", "item": JN, "piece": 1,
                                 "operation": "出厂检验 Final inspection", "result": "pass", "inspector": "质检甲", "day": "2026-11-12",
                                 "readings": [{"spec": "总长 (mm)", "lo": 299.8, "hi": 300.2, "value": 300.05, "result": "pass"}]})
    assert not any(x["action"] == "failed" for x in out), [x.get("error") for x in out]
    qi = M.db["Quality Inspection"][out[-1]["created"][0][1]]
    assert qi["reference_name"] == "JC-Q1" and qi["status"] == "Accepted" and "总长 (mm)" in M.db["Quality Inspection Parameter"]
    out = run("eto_ship", {"job": {"job_no": JN}, "sales_order": "SO-Q", "qty": 2, "day": "2026-11-12"})
    assert not any(x["action"] == "failed" for x in out), [x.get("error") for x in out]
    dn = M.db["Delivery Note"][out[-1]["created"][0][1]]
    assert dn["docstatus"] == 1 and dn["items"][0]["qty"] == 2 and so["per_delivered"] == 100 and out[-1]["sales_orders"] == ["SO-Q"]
