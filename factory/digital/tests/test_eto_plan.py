"""第 139 轮 139d：从交期倒排（手算对照）、最早能做完与松紧、晚了卡在哪、报价时粗算能否按期、工位负荷超能力、算料日期用倒排结果。"""
import datetime as dt

import pytest

from factory import data as F
from hub import eto_plan as P
from tests.test_eto_design import keep_master  # noqa: F401
from tests.test_eto_mrp import _erp, db  # noqa: F401

OP = "粗车 Rough turning"


@pytest.fixture
def tree(keep_master):  # noqa: F811
    """顶层 T（480 分/件）← 自制件 C（960 分/件）← 外购件 B（供应商提前期 L）"""
    sup = next(k for k, v in F.SUPPLIERS.items() if (v.get("lead") or 0) >= 7)
    F.ITEMS.update({"T": ("顶", "fg", "Nos", None, None, None, ""), "C": ("中", "make", "Nos", None, None, None, ""),
                    "B": ("料", "buy", "Nos", 1.0, sup, None, "")})
    F.ROUTINGS.update({"RT-T": [(OP, 480)], "RT-C": [(OP, 960)]})
    F.BOMS.update({"T": ("RT-T", [("C", 1)]), "C": ("RT-C", [("B", 2)])})
    return F.SUPPLIERS[sup]["lead"] * 5 // 7


def test_backward_and_forward_by_hand(tree):
    lead = tree
    today = dt.date(2026, 11, 16)                                  # 周一
    early_b = P.add_working_days(today, lead)
    c_fin = P.add_working_days(P.add_working_days(early_b, 1), 1)  # C 两天
    t_fin = P.add_working_days(c_fin, 1)                           # T 一天
    due = P.add_working_days(t_fin, 1)                             # 发货预留 1 天：刚好来得及
    t = P.schedule_tree("T", 1, due, today)
    mk = {x["item_code"]: x for x in t["make"]}
    assert mk["T"]["latest_finish"] == t_fin.isoformat() and mk["T"]["latest_start"] == t_fin.isoformat() and mk["T"]["days"] == 1
    assert mk["C"]["latest_finish"] == c_fin.isoformat() and mk["C"]["days"] == 2
    assert mk["C"]["latest_start"] == P.sub_working_days(c_fin, 1).isoformat()
    b = t["buy"][0]
    assert b["item_code"] == "B" and b["qty"] == 2 and b["need_by"] == early_b.isoformat() and b["late_days"] == 0
    assert t["earliest"] == due.isoformat() and t["slack_days"] == 0 and t["critical"] == ["T", "C", "B"]
    # 交期提前 3 个工作日：晚 3 天，卡在采购 B
    late = P.schedule_tree("T", 1, P.sub_working_days(due, 3), today)
    assert late["slack_days"] == -3
    msg = P._bottleneck(late, 0)
    assert msg.startswith("晚 3 个工作日") and "采购 B" in msg and "加工 C→T" in msg
    # 件数加倍：C 4 天
    assert {x["item_code"]: x for x in P.schedule_tree("T", 2, due, today)["make"]}["C"]["days"] == 4
    # 周末不算：交期落在周六按周五
    sat = due + dt.timedelta(days=(5 - due.weekday()) % 7)
    assert P.schedule_tree("T", 1, sat, today)["make"][-1]["latest_finish"] <= sat.isoformat()


def test_feasibility_at_quote(tree):
    lead = tree
    today = dt.date(2026, 11, 16)
    lines = [{"kind": "engineering", "desc": "设计", "hours": 12},                   # 2 天
             {"kind": "buyout", "item_code": "B", "qty_per": 2},                    # 提前期
             {"kind": "operation", "op": OP, "setup_min": 60, "run_min": 210}]      # (60 + 210 × 2) / 480 → 1 天
    f = P.feasibility({"qty": 2, "due_date": "2027-03-01"}, lines, today)
    assert (f["engineering_days"], f["purchase_days"], f["manufacturing_days"], f["ship_days"]) == (2, lead, 1, 1)
    assert f["earliest"] == P.add_working_days(today, 2 + lead + 1 + 1).isoformat() and f["ok"]
    f2 = P.feasibility({"qty": 2, "due_date": today.isoformat()}, lines + [{"kind": "outside", "desc": "喷涂"}], today)
    assert not f2["ok"] and f2["unknown"] == ["喷涂"] and f2["slack_days"] < 0


def test_load_and_mrp_dates(db, tree):  # noqa: F811
    import json

    from hub import eto as E
    from hub import eto_design as ED
    from hub import eto_mrp as EM
    from tests.test_eto import CFG
    j = E.new_job(db, "teach", "王销售", "示例·客户乙", "非标", "", 1, None, "2027-06-30", cfg=CFG)
    jn = j["job_no"]
    db.x("update eto_job set status='ordered', sales_order='SO-9' where mode='teach' and job_no=%s", (jn,))
    spec = {"items": [], "boms": [{"item": jn, "routing": [[OP, 480]], "components": [["C", 1]]}]}
    db.x("insert into eto_design (mode, job_no, rev, spec, status) values ('teach',%s,1,%s,'released')", (jn, json.dumps(spec)))
    ED.merge(jn, "非标", spec)
    t = P.schedule(db, "teach", jn, dt.date(2026, 11, 16))
    assert t["slack_days"] > 0 and t["bottleneck"] is None and [x["item_code"] for x in t["make"]][-1] == jn
    # 车床那周已经排满：本作业落在那周就标超
    wk = P.sub_working_days(dt.date.fromisoformat(t["make"][0]["latest_start"]), 0)
    _erp(db, "Work Order", "WO-BIG", docstatus=1, status="Not Started", production_item="C", qty=40,
         planned_start_date=(wk - dt.timedelta(days=wk.weekday())).isoformat(), expected_delivery_date=(wk - dt.timedelta(days=wk.weekday()) + dt.timedelta(days=4)).isoformat())
    rows = P.load(db, "teach", jn, dt.date(2026, 11, 16))["rows"]
    lathe = [r for r in rows if r["workstation"] == F.OPERATIONS[OP] and r["job_min"]]
    assert lathe and any(r["over"] for r in lathe)
    # 算料的工单日期按倒排（不早于今天）
    pv = EM.plan(db, "teach", jn)
    w = {x["production_item"]: x for x in pv["work_orders"]}
    mk = {x["item_code"]: x for x in P.schedule(db, "teach", jn)["make"]}
    assert w[jn]["planned_start_date"] == mk[jn]["latest_start"] > dt.date.today().isoformat()     # 交期远：按倒排的最晚开工


# ---------------------------------------------------------------- 第 150 轮 150c：多张作业抢工位
def test_suggest_conflict_by_hand():
    row = {"workstation": "数控车床 CNC-L01", "week": "2026-11-16", "capacity_min": 2400, "total_min": 3000, "jobs": {"J-A": 1800, "J-B": 1200}}
    # 超 600 分；一天能力 480 分 → 挪开 2 个工作日；J-A 松紧 5 最大（new_earliest：最早完工 2026-11-20 周五 + 2 → 2026-11-24）
    s = P.suggest_conflict(row, {"J-A": 5, "J-B": 2}, {"J-A": "2026-11-20", "J-B": "2026-11-27"}, {"J-A": "2026-11-30", "J-B": "2026-12-01"})
    assert s["action"] == "delay" and s["job_no"] == "J-A" and s["delay_days"] == 2 and s["over_min"] == 600 and s["new_earliest"] == "2026-11-24"
    # 最松的也只有 1 天余量：推迟赶不上，建议加班或外协，缺 600 分
    s = P.suggest_conflict(row, {"J-A": 1, "J-B": 0}, {"J-A": "2026-11-20", "J-B": "2026-11-27"}, {"J-A": "x", "J-B": "y"})
    assert s["action"] == "overtime" and s["job_no"] == "J-A" and "缺 600 分钟" in s["text"]
    assert P.suggest_conflict(row, {"J-A": None, "J-B": None}, {}, {})["action"] == "unknown"     # 松紧算不出：不猜
    assert P.suggest_conflict(dict(row, total_min=2400), {"J-A": 5}, {"J-A": "2026-11-20"}, {"J-A": "x"}) is None   # 没超：不出建议


def test_other_jobs_count_in_load_and_quote(db, tree):  # noqa: F811
    import json

    from hub import eto as E
    from hub import eto_design as ED
    from tests.test_eto import CFG
    today = dt.date(2026, 11, 16)
    j = E.new_job(db, "teach", "王销售", "示例·客户乙", "非标甲", "", 1, None, "2026-12-04", cfg=CFG)
    jn = j["job_no"]
    db.x("update eto_job set status='ordered', sales_order='SO-A', project='PROJ-A' where mode='teach' and job_no=%s", (jn,))
    spec = {"items": [], "boms": [{"item": jn, "routing": [[OP, 2400]], "components": [["B", 1]]}]}
    db.x("insert into eto_design (mode, job_no, rev, spec, status) values ('teach',%s,1,%s,'released')", (jn, json.dumps(spec)))
    ED.merge(jn, "非标甲", spec)
    # 另两张已接单、设计没发布的作业：估算里车床各 2400 分，交期同一周（车床 2 台，一周能力 4800 分；三张每天各占 480 分）
    others = []
    for k in "BC":
        o = E.new_job(db, "teach", "王销售", "示例·客户" + k, "非标" + k, "", 1, None, "2026-12-04", cfg=CFG)
        E.save_estimate(db, "teach", o["job_no"], [{"kind": "operation", "op": OP, "setup_min": 0, "run_min": 2400}], "", "王销售")
        db.x("update eto_job set status='ordered', sales_order=%s, project=%s where mode='teach' and job_no=%s", ("SO-" + k, "PROJ-" + k, o["job_no"]))
        others.append(o["job_no"])
    on = others[0]
    rows = [r for r in P.load(db, "teach", jn, today)["rows"] if r["workstation"] == F.OPERATIONS[OP] and r["over"] and r["job_min"]]
    assert rows, "两张作业都落在同一周的车床上，应该超"
    r = rows[0]
    jobs = {x["job_no"]: x for x in r["jobs"]}
    assert set(jobs) >= {jn, *others} and all(jobs[k]["min"] > 0 for k in others)
    best = max(v["slack_days"] for v in jobs.values())
    assert r["suggestion"]["action"] == "delay" and jobs[r["suggestion"]["job_no"]]["slack_days"] == best      # 推迟松紧最大的那张
    # 没接单的作业（还在报价）：报价页看得到车床那周不够
    q = E.new_job(db, "teach", "王销售", "示例·客户丁", "非标丙", "", 1, None, "2026-12-04", cfg=CFG)
    E.save_estimate(db, "teach", q["job_no"], [{"kind": "operation", "op": OP, "setup_min": 0, "run_min": 2400}], "", "王销售")
    cap = P.quote_capacity(db, "teach", E.job(db, "teach", q["job_no"]), [{"kind": "operation", "op": OP, "run_min": 2400}], today)
    assert any(c["workstation"] == F.OPERATIONS[OP] and c["short_min"] > 0 for c in cap)
