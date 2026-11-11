# -*- coding: utf-8 -*-
"""第 139 轮 139a：按单设计（ETO）的作业号与估算——估算计算（手算对照）、未知项不能报价、AI 不给价格、
没有模型时照现有产品起草、报价改版留底、报价提议内容。"""
import json
import os

import pytest

from factory import data as F
from hub import eto as E

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
CFG = {"prefix": "JOB-", "contingency_pct": 10, "markup_pct": 30, "engineering_rate_per_h": 65, "valid_days": 30,
       "milestones": [{"key": "deposit", "name": "订金", "pct": 30, "on": "order"}], "example": True}
OP = "粗车 Rough turning"


def test_compute_matches_hand_calculation():
    rate = sum(F.WORKSTATIONS[F.OPERATIONS[OP]][1])                     # 数控车床 18 + 24 + 6 = 48 $/h
    assert rate == 48
    lines = [
        {"kind": "material", "item_code": "RM-45-D50", "qty_per": 3.5},                     # 主数据单价 1.6 $/kg
        {"kind": "buyout", "desc": "客户指定法兰", "qty_per": 1, "unit_price": 40},
        {"kind": "operation", "op": OP, "setup_min": 30, "run_min": 12},
        {"kind": "outside", "desc": "表面发黑", "unit_price": 5},
        {"kind": "engineering", "desc": "改图", "hours": 4},
    ]
    r = E.compute(lines, [1, 10], CFG)
    assert r["can_quote"] and not r["errors"] and not r["unknown"]
    assert r["lines"][0]["unit_price"] == 1.6 and r["lines"][0]["price_from"] == "物料主数据"
    b1, b10 = r["breaks"]
    # 1 件：材料 5.6 + 40；工序 (30 + 12) / 60 × 48 = 33.6；外协 5；设计 4 × 65 = 260
    assert (b1["material"], b1["operations"], b1["outside"], b1["engineering"]) == (45.6, 33.6, 5, 260)
    sub = 45.6 + 33.6 + 5 + 260
    assert b1["subtotal"] == round(sub, 2) and b1["cost"] == round(sub * 1.1, 2) and b1["price"] == round(sub * 1.1 * 1.3, 2)
    # 10 件：调整一批一次、设计一次性，所以单价比 1 件低
    assert b10["operations"] == round((30 + 120) / 60 * 48, 2) and b10["engineering"] == 260
    assert b10["unit_price"] < b1["unit_price"] and b1["margin_pct"] == round(0.3 / 1.3 * 100, 1)


def test_unknown_blocks_quote_and_nothing_is_guessed():
    lines = [{"kind": "buyout", "desc": "非标轴承座", "qty_per": 2},                      # 没有单价
             {"kind": "operation", "op": OP, "run_min": 10},                            # 没有调整时间
             {"kind": "engineering", "desc": "设计", "hours": 2}]
    r = E.compute(lines, [5], dict(CFG, engineering_rate_per_h=None))
    assert not r["can_quote"]
    assert len(r["unknown"]) == 3 and "单价" in r["unknown"][0] and "调整时间" in r["unknown"][1] and "设计费率" in r["unknown"][2]
    b = r["breaks"][0]
    assert b["material"] is None and b["operations"] is None and b["engineering"] is None and b["price"] is None
    # 企业工厂没配加价率：一样是未知，不按演示值算
    r2 = E.compute([{"kind": "outside", "desc": "x", "unit_price": 3}], [1], {"prefix": "JOB-"})
    assert not r2["can_quote"] and any("加价率" in u for u in r2["unknown"]) and r2["breaks"][0]["price"] is None


def test_line_errors():
    r = E.compute([{"kind": "operation", "op": "激光切割", "setup_min": 1, "run_min": 1},
                   {"kind": "material", "item_code": "NOPE-1", "qty_per": 1, "unit_price": 2},
                   {"kind": "material", "item_code": "RM-45-D50", "qty_per": -1},
                   {"kind": "outside", "unit_price": 1}, {"kind": "paint"}], [1], CFG)
    assert not r["can_quote"] and len(r["errors"]) == 5
    assert "不在本厂工序表" in r["errors"][0] and "不在物料主数据" in r["errors"][1] and "负数" in r["errors"][2]
    with pytest.raises(E.EtoError):
        E.compute([], [0], CFG)
    with pytest.raises(E.EtoError):
        E.compute([], [1, 2, 3, 4, 5, 6], CFG)
    assert not E.compute([], [1], CFG)["can_quote"]          # 没有估算行也不能报


def test_draft_from_existing_product_without_llm():
    d = E.draft(None, {"requirement": "参照 wqr-105，输出轴加长 40 mm，法兰按客户图纸", "qty": 2})
    assert d["source"] == "rules" and "WQR-105" in d["note"]
    kinds = {x["kind"] for x in d["lines"]}
    assert kinds == {"material", "buyout", "operation"}
    shaft = [x for x in d["lines"] if x["kind"] == "operation" and x["desc"].startswith("SH-301")]
    assert [x["op"] for x in shaft] == [op for op, _ in F.ROUTINGS[F.BOMS["SH-301"][0]]]
    r = E.compute(d["lines"], [1], CFG)
    assert not r["errors"]
    assert E.draft(None, {"requirement": "做一个夹具"})["lines"] == []


class FakeLLM:
    name = "fake"

    def __init__(self, args):
        self.args = args

    def available(self):
        return True

    def run(self, system, messages, tools, call_tool, max_turns=6):
        assert "粗车 Rough turning" in system and "不要写任何价格" in system
        call_tool("submit_estimate", self.args)
        return "", []


def test_ai_draft_never_carries_prices():
    llm = FakeLLM({"note": "法兰尺寸要客户确认", "lines": [
        {"kind": "material", "item_code": "RM-45-D50", "qty_per": 4, "unit_price": 999},
        {"kind": "operation", "op": OP, "setup_min": 20, "run_min": 15, "rate_h": 1},
        {"kind": "outside", "desc": "发黑", "price": 3}]})
    d = E.draft(llm, {"customer": "c", "title": "t", "qty": 1, "requirement": "x"})
    assert d["source"] == "ai:fake" and d["note"] == "法兰尺寸要客户确认"
    assert all("unit_price" not in x and "rate_h" not in x and "price" not in x and x["source"] == "ai" for x in d["lines"])
    r = E.compute(d["lines"], [1], CFG)
    assert r["lines"][0]["unit_price"] == 1.6 and r["lines"][1]["rate_h"] == 48     # 价格只来自主数据
    assert not r["can_quote"] and "外协" in r["unknown"][0]                          # 外协单价 AI 给了也不算，要人填


# ---------------------------------------------------------------- 数据库
@pytest.fixture(scope="module")
def db():
    pytest.importorskip("psycopg")
    import psycopg
    from hub.db import DB
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_eto_test with (force)")
            c.execute("create database wq_eto_test")
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    d = DB(base + "/wq_eto_test")
    d.init()
    E.init(d)
    from hub import eto_design, eto_exec, eto_quality
    for m in (eto_design, eto_exec, eto_quality):                # 接口测试要用到后面几段的表（枢纽启动时一起建）
        m.init(d)
    return d


def test_job_estimate_revisions_and_quote(db):
    with pytest.raises(E.EtoError):
        E.new_job(db, "teach", "u", "", "x", "", 1)
    j = E.new_job(db, "teach", "王销售", "示例·客户甲", "非标减速器", "参照 WQR-105", 2, [1, 5], "2026-12-20", cfg=CFG)
    assert j["job_no"].startswith("JOB-") and j["job_no"].endswith("-0001") and j["qty_breaks"] == [1, 2, 5]
    j2 = E.new_job(db, "teach", "王销售", "示例·客户乙", "夹具", "", 1, cfg=CFG)
    assert j2["job_no"].endswith("-0002")
    jn = j["job_no"]
    with pytest.raises(E.EtoError):
        E.quote_preview(db, "teach", jn, CFG)                     # 还没有估算行
    lines = [{"kind": "material", "item_code": "RM-45-D50", "qty_per": 3},
             {"kind": "operation", "op": OP, "setup_min": 30, "run_min": 12},
             {"kind": "buyout", "desc": "法兰", "qty_per": 1}]
    assert E.save_estimate(db, "teach", jn, lines, "", "王销售") == 1
    with pytest.raises(E.EtoError) as ei:
        E.quote_preview(db, "teach", jn, CFG)                     # 法兰没有单价：不能报
    assert "单价" in str(ei.value)
    lines[2]["unit_price"] = 40
    assert E.save_estimate(db, "teach", jn, lines, "", "王销售") == 1          # 没报出去：覆盖同一版
    pv = E.quote_preview(db, "teach", jn, CFG)
    assert pv["item"]["item_code"] == jn and pv["project"]["project_name"] == jn and pv["job"]["rev"] == 1
    b2 = next(b for b in pv["breaks"] if b["qty"] == 2)
    assert pv["quotation"]["qty"] == 2 and pv["quotation"]["rate"] == b2["unit_price"] and pv["quotation"]["amount"] == b2["price"]
    assert "5 件" in pv["quotation"]["terms"] and "订金 30%" in pv["quotation"]["terms"] and "示例" in pv["quotation"]["terms"]
    # 报价提议在等确认：不能再改、不能再报
    db.x("insert into ai_proposal (proposal_id, mode, action, title, preview) values ('P-ETO1','teach','eto_quote','t',%s)",
         (json.dumps(pv, ensure_ascii=False),))
    assert E.job(db, "teach", jn)["status"] == "quoting" and E.jobs(db, "teach")[-1]["status"] == "quoting"
    with pytest.raises(E.EtoError):
        E.save_estimate(db, "teach", jn, lines, "", "王销售")
    with pytest.raises(E.EtoError):
        E.quote_preview(db, "teach", jn, CFG)
    # 桥接执行完：记为已报价、冻结第 1 版
    db.x("update ai_proposal set status='executed', decided_at=now(), result=%s where proposal_id='P-ETO1'",
         (json.dumps({"created": [["Project", jn], ["Item", jn], ["Quotation", "SAL-QTN-2026-00009"]]}),))
    E.on_proposal_done(db, "eto_quote", pv, "teach")
    j = E.job(db, "teach", jn)
    assert (j["status"], j["quoted_rev"], j["project"], j["quotation"]) == ("quoted", 1, jn, "SAL-QTN-2026-00009")
    d = E.detail(db, "teach", jn, CFG)
    assert d["frozen"]
    with pytest.raises(E.EtoError):
        E.quote_preview(db, "teach", jn, CFG)                     # 同一版不重复报
    # 改价：出第 2 版，第 1 版原样留着
    lines[0]["qty_per"] = 4
    assert E.save_estimate(db, "teach", jn, lines, "客户改了长度", "王销售") == 2
    assert [r["rev"] for r in E.revisions(db, "teach", jn)] == [1, 2]
    v1 = db.one("select lines from eto_estimate where mode='teach' and job_no=%s and rev=1", (jn,))["lines"]
    assert v1[0]["qty_per"] == 3
    assert E.job(db, "teach", jn)["status"] == "estimating" and not E.detail(db, "teach", jn, CFG)["frozen"]
    assert E.quote_preview(db, "teach", jn, CFG)["job"]["rev"] == 2
    assert E.jobs(db, "prod") == []                                # 教学与生产分开
    E.reset(db, "teach")
    assert E.jobs(db, "teach") == []


# ---------------------------------------------------------------- 桥接 → 模拟 ERPNext（需要 node）
BRIDGE_SCRIPT = """
const {ERP} = require(process.argv[1]);
const e = new ERP({url: process.argv[2], log: () => {}});
const m = JSON.parse(process.argv[3]);
(async () => {
  const a = await e.execProposal(m);
  const b = await e.execProposal(m);               // 再执行一次：Project、物料不重建
  console.log(JSON.stringify([a.map((x) => x.payload.data), b.map((x) => x.payload.data)]));
})().catch((err) => { console.error(err); process.exit(1); });
"""


@pytest.fixture(scope="module")
def mock_erp():
    import shutil
    import socket
    import threading
    import time
    if not shutil.which(os.environ.get("WQ_NODE", "node")):
        pytest.skip("需要 node")
    uvicorn = pytest.importorskip("uvicorn")
    from mock_erpnext.server import M, app
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield "http://127.0.0.1:{}".format(port), M
    srv.should_exit = True


def test_bridge_creates_project_item_and_quotation(mock_erp):
    import subprocess
    from pathlib import Path
    url, M = mock_erp
    pv = {"job": {"job_no": "JOB-2026-0007", "title": "非标减速器", "customer": "示例·客户甲 (Demo)", "qty": 2, "due_date": "2026-12-20", "rev": 1},
          "item": {"item_code": "JOB-2026-0007", "item_name": "非标减速器", "item_group": F.KIND_GROUP["fg"], "stock_uom": "Nos",
                   "description": "参照 WQR-105"},
          "project": {"project_name": "JOB-2026-0007", "customer": "示例·客户甲 (Demo)", "expected_end_date": "2026-12-20", "notes": "x"},
          "quotation": {"party": "示例·客户甲 (Demo)", "transaction_date": "2026-11-10", "valid_till": "2026-12-10", "qty": 2,
                        "rate": 1234.5, "amount": 2469, "terms": "数量阶梯"}}
    msg = {"mode": "teach", "data": {"status": "confirmed", "proposal_id": "P-ETOB1", "action": "eto_quote", "preview": pv}}
    erp_js = Path(__file__).resolve().parents[1] / "bridge" / "lib" / "erp.js"
    r = subprocess.run([os.environ.get("WQ_NODE", "node"), "-e", BRIDGE_SCRIPT, str(erp_js), url, json.dumps(msg, ensure_ascii=False)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    first, again = json.loads(r.stdout)
    assert first[-1]["proposal_done"] and [c[0] for c in first[-1]["created"]] == ["Project", "Item", "Quotation"]
    assert not any(x["action"] == "failed" for x in first + again)
    assert [x["doctype"] for x in again] == ["Quotation"]                  # 第二次只多一张报价单
    pname = first[-1]["created"][0][1]
    assert pname.startswith("PROJ-")                                        # 真 ERPNext 按编号规则给项目起名，不等于作业号
    proj = M.db["Project"][pname]
    assert proj["project_name"] == "JOB-2026-0007"
    assert proj["customer"] == "示例·客户甲 (Demo)" and proj["status"] == "Open"
    assert M.db["Item"]["JOB-2026-0007"]["item_group"] == F.KIND_GROUP["fg"]
    q = M.db["Quotation"][first[-1]["created"][2][1]]
    assert q["docstatus"] == 1 and q["wq_job"] == "JOB-2026-0007" and q["items"][0]["rate"] == 1234.5 and q["terms"] == "数量阶梯"
    assert first[-1]["wq_job"] == "JOB-2026-0007"


def test_api_flow_to_quoted(db, monkeypatch):
    from fastapi.testclient import TestClient

    import hub.app as A
    from hub.ai import Assistant

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    sent = []
    monkeypatch.setattr(A.H, "db", db)
    monkeypatch.setattr(A.H, "ai", Assistant(db, lambda *a: sent.append(a), NoLLM()))
    c = TestClient(A.app)

    def tok(role, teacher=False):
        return {"X-WQ-Token": A._sign({"name": "测试" + role, "role": role, "mode": "teach", "teacher": teacher, "exp": 9e12})}
    S, OPR = tok("sales"), tok("operator")
    assert c.post("/api/eto/jobs", json={"customer": "c", "title": "t", "qty": 1}, headers=OPR).status_code == 403
    assert c.post("/api/eto/jobs", json={"customer": "c", "title": "t", "qty": 0}, headers=S).status_code == 400
    j = c.post("/api/eto/jobs", json={"customer": "示例·客户丙", "title": "非标减速器", "requirement": "参照 WQR-105，速比改 12",
                                      "qty": 2, "qty_breaks": [10], "due_date": "2026-12-30"}, headers=S).json()
    jn = j["job_no"]
    assert c.get("/api/eto/jobs", headers=OPR).json()[0]["job_no"] == jn       # 大家都能看
    d = c.post("/api/eto/jobs/{}/draft".format(jn), headers=S).json()
    assert d["source"] == "rules" and d["lines"]
    r = c.put("/api/eto/jobs/{}/estimate".format(jn), json={"lines": d["lines"], "note": d["note"], "source": d["source"]}, headers=S).json()
    assert r["estimate"]["rev"] == 1 and [b["qty"] for b in r["result"]["breaks"]] == [2, 10]
    cfg = c.get("/api/eto/config", headers=S).json()
    assert cfg["example"] and cfg["markup_pct"] == 30
    # 照产品起草的：装配、加工中心等工位没有标准调整时间，标未知，估算员补上才能报
    assert not r["result"]["can_quote"] and any("调整时间" in x for x in r["result"]["unknown"])
    assert c.post("/api/eto/jobs/{}/quote".format(jn), headers=S).status_code == 409
    for ln in d["lines"]:
        if ln["kind"] == "operation" and ln.get("setup_min") is None:
            ln["setup_min"] = 15
        if ln["kind"] in ("material", "buyout") and not (F.ITEMS[ln["item_code"]][3] or 0):
            ln["unit_price"] = 1
    r = c.put("/api/eto/jobs/{}/estimate".format(jn), json={"lines": d["lines"]}, headers=S).json()
    assert r["result"]["can_quote"], r["result"]["unknown"]
    q = c.post("/api/eto/jobs/{}/quote".format(jn), headers=S).json()
    assert q["preview"]["quotation"]["qty"] == 2 and q["title"].startswith("报价 " + jn)
    assert c.get("/api/eto/jobs/" + jn, headers=S).json()["job"]["status"] == "quoting"
    assert c.post("/api/proposals/{}/confirm".format(q["proposal_id"]), headers=S).json()["status"] == "confirmed"
    A.H.ai.on_erp_result({"corr": q["proposal_id"], "data": {"doctype": "Quotation", "name": "SAL-QTN-1", "action": "submitted",
                                                             "proposal_done": True,
                                                             "created": [["Project", jn], ["Item", jn], ["Quotation", "SAL-QTN-1"]]}})
    j = c.get("/api/eto/jobs/" + jn, headers=S).json()
    assert (j["job"]["status"], j["job"]["quotation"], j["frozen"]) == ("quoted", "SAL-QTN-1", True)
    assert c.get("/api/eto/jobs/JOB-NOPE", headers=S).status_code == 404


def test_plant_manifest_eto_section():
    from factory import plant as P
    assert P._validate_eto(None) == [] and F.ETO["markup_pct"] == 30
    assert P._validate_eto(F.ETO) == []
    bad = P._validate_eto({"prefix": "1x", "markup_pct": -1, "valid_days": 0, "ship_days": "1",
                           "milestones": [{"key": "a", "name": "订金", "pct": 30, "on": "order"},
                                          {"key": "a", "name": "尾款", "pct": 60, "on": "later"}]})
    text = "；".join(bad)
    assert "prefix" in text and "markup_pct" in text and "valid_days" in text and "代号重复" in text and ".on" in text and "等于 100" in text and "ship_days" in text
    assert E.config()["example"] and E.config()["configured"]
