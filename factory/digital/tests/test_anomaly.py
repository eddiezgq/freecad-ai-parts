# -*- coding: utf-8 -*-
"""第 17 轮 B 期：异常与规则库——目录校验、原 AI 提醒迁移一致、生命周期、各条规则“该报 / 不该报”。"""
import datetime as dt
import os

import pytest

import wqbus

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_anom_test"
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)


def legacy_findings(db, mode, now):
    """第 17 轮 B 期之前 hub/ai.py 里 evaluate() 的检查逻辑（原样冻结在这里，用来核对迁移后的规则）"""
    from hub import kpi
    from wqbus.topics import unit_topic
    ov = kpi.overview(db, now, mode)
    now = dt.datetime.fromisoformat(ov["now"])
    found = []
    # 设备停机
    for m in ov["machines"]:
        if m["state"] in ("down", "fault"):
            mins = (m["down_until_s"] or 0) / 60
            found.append(("down:" + m["unit"], "critical" if m["state"] == "fault" else "warn",
                          "{} {}：{}".format(m["code"], "故障" if m["state"] == "fault" else "停机", m["reason"] or ""),
                          "预计还要约 {:.0f} 分钟（工厂时间）；排队 {} 件{}".format(
                              mins, m["queue"], "，是本周瓶颈" if m.get("bottleneck") else ""),
                          [{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}],
                          "查看受影响的订单；必要时安排加班或转移工序"))
        elif m["tool_life_left"] is not None and m["tool_life_left"] < 0.15 and m["state"] != "idle":
            found.append(("tool:" + m["unit"], "info", "{} 刀具剩余寿命 {:.0f}%".format(m["code"], m["tool_life_left"] * 100),
                          "按当前节拍约再加工 {} 件后需{}".format(
                              max(1, int(m["tool_life_left"] * 30)), "修整砂轮" if m["unit"] == "grd-01" else "换刀"),
                          [{"topic": unit_topic(m["unit"], "status"), "ts": m["ts"]}], "提前准备刀具，安排在换件间隙"))
    # 质量趋势
    ch = ov["quality"]["chart"]
    if ch.get("points") and len(ch["points"]) >= 5:
        band = (ch["upper"] - ch["lower"]) * 1000
        if ch["margin_um"] <= band * 0.25 and ch["shift_um"] >= 2:
            found.append(("trend:" + ch["characteristic"], "warn",
                          "{} 测量值上移，趋近上限".format(ch["title"]),
                          "最近 5 件均值 {:.4f} mm，比公差中值高 {:.1f} µm，距上限只余 {:.1f} µm，尚未超差".format(
                              ch["mean_last5"], ch["shift_um"], ch["margin_um"]),
                          [{"topic": ch["src"], "id": p["id"]} for p in ch["points"][-5:]],
                          "检查磨床 GRD-01 砂轮磨损，考虑提前修整"))
    for n in ov["quality"]["ncr"]:
        d = n["detail"]
        found.append(("ncr:" + n["ncr_id"], "warn", "不合格品 {}：{} 超差".format(n["ncr_id"], n["part_serial"]),
                      "{} 实测 {} mm，公差 {}–{}".format(d.get("name"), d.get("value_mm"), d.get("lower_tol_mm"),
                                                     d.get("upper_tol_mm")),
                      [{"topic": unit_topic("qc-01", "measurement"), "id": d.get("message_id")}],
                      "质检员评审：返修、报废或让步接收"))
    # 订单与物料
    for o in ov["orders"]:
        if o["tone"] == "bad":
            found.append(("late:" + o["name"], "warn", "{} 可能延期：{}".format(o["name"], o["risk"]),
                          "{} {} 台，交期 {}，预计 {} 完成；{}".format(
                              o["customer"].split(" ")[0], o["qty"], o["delivery_date"], o["projected"], o["work_orders"]),
                          [{"topic": "wq/gearbox/office/erp/sales_order", "name": o["name"]}],
                          "考虑加班、调整优先级或与客户沟通交期"))
    for mt in ov["materials"]:
        if mt["tone"] == "bad":
            found.append(("stock:" + mt["code"], "warn", "{} {}".format(mt["code"], mt["status"]),
                          "{} 库存 {}，安全库存 {}，在手工单与订单还需 {:g}".format(
                              mt["name"], mt["qty_text"], mt["safety"] if mt["safety"] is not None else "—", mt["need"]),
                          [{"topic": "wq/gearbox/office/erp/bin", "item": mt["code"]}], "起草请购单"))
    return found


@pytest.fixture(scope="module")
def db():
    psycopg = pytest.importorskip("psycopg")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_anom_test with (force)")
            c.execute("create database wq_anom_test")
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.historian import Historian
    from sim import scenario
    from tests_helpers import make_engine
    d = DB(DSN)
    d.init()
    h = Historian(d)
    eng, clock, _ = make_engine(auto=False)
    scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    return d


def test_catalog_loads_33_live_rules_and_waiting_ones():
    from hub.ont import anomaly as A
    c = A.load_catalog()
    live = [r for r in c.values() if not r["waiting"]]
    assert len(live) == 61 == len(c)                                  # 第 18 轮 E1：C1–C5、R3；E2：E1–E7；E3：M2–M7；E4：H1–H5；E5：W3–W7；E6：N1–N6；E7：F2–F7
    assert {k for k, r in c.items() if not r["waiting"]} >= {"C1", "C2", "C3", "C4", "C5", "R3"}
    assert {k for k, r in c.items() if not r["waiting"]} >= {"E1", "E2", "E3", "E4", "E5", "E6", "E7"}
    assert not [k for k, r in c.items() if r["waiting"]]                                       # 第 18 轮 E7：财务上线，没有“待数据”的规则了
    assert {k for k, r in c.items() if not r["waiting"]} >= {"F1", "F2", "F3", "F4", "F5", "F6", "F7"}
    assert {k for k, r in c.items() if not r["waiting"]} >= {"N1", "N2", "N3", "N4", "N5", "N6"}
    assert {k for k, r in c.items() if not r["waiting"]} >= {"H1", "H2", "H3", "H4", "H5"}       # 第 18 轮 E4：人员领域上线


def test_catalog_rejects_missing_function(tmp_path):
    import shutil
    from hub.ont import anomaly as A
    d = tmp_path / "rules"
    shutil.copytree(A.RULE_DIR, d)
    (d / "zz.yaml").write_text("domain: production\nrules:\n  PX: {name: 测试, fn: no_such, severity: warn, role: [manager]}\n", encoding="utf-8")
    with pytest.raises(A.RuleError) as e:
        A.load_catalog(str(d))
    assert "no_such" in str(e.value)


def test_migrated_rules_match_legacy_ai_alerts(db):
    from hub.ont.anomaly import Detector
    old = {k: (lv, t, d, ev, h) for k, lv, t, d, ev, h in legacy_findings(db, "teach", NOW)}
    assert old, "实验 7 情景里原 AI 提醒应有内容"
    found, _ = Detector(db).detect("teach", NOW, only={"P1", "P2", "Q2", "Q3", "S1", "W1"})
    new = {}
    for rid, fs in found.items():
        assert fs is not None, rid
        for f in fs:
            new[f.alert_key] = (f.severity, f.title, f.detail, f.evidence, f.hint)
    assert set(new) == set(old)
    for k in old:
        lv, t, d, ev, h = old[k]
        nl, nt, nd, nev, nh = new[k]
        assert (nt, nd, nev, nh) == (t, d, ev, h), k
        # 级别：只有两处按细则升级——不合格品超过 2 小时未评审、订单晚于交期 2 天以上
        if nl != lv:
            assert (k.startswith("ncr:") or k.startswith("late:")) and nl == "critical", k


def test_lifecycle_dedup_escalate_autoresolve_reopen(db):
    from hub.ont.anomaly import Detector, Finding
    D = Detector(db)
    D.init()
    r = D.rule("P1")
    t0 = NOW
    f = Finding("x-01", "X-01 停机", severity="warn", subject=("Machine", "x-01"))
    assert len(D._apply("teach", r, [f], t0)) == 1                       # 新开，发提醒
    assert D._apply("teach", r, [f], t0) == []                            # 再报：不重复
    a = db.one("select * from anomaly where rule='P1' and fkey='x-01'")
    assert a["hits"] == 2 and a["status"] == "open"
    f2 = Finding("x-01", "X-01 故障", severity="critical", subject=("Machine", "x-01"))
    assert len(D._apply("teach", r, [f2], t0)) == 1                       # 升级：再发
    D._apply("teach", r, [], t0)                                          # 消失一轮：还开着
    assert db.one("select status from anomaly where id=%s", (a["id"],))["status"] == "open"
    D._apply("teach", r, [f2], t0)                                        # 又出现：计数清零
    D._apply("teach", r, [], t0)
    D._apply("teach", r, [], t0)                                          # 连续两轮消失：自动解除
    a = db.one("select * from anomaly where id=%s", (a["id"],))
    assert a["status"] == "resolved" and "自动解除" in a["closed_reason"]
    # 人工关闭后 24 小时内复现：重开同一个
    D._apply("teach", r, [f], t0)
    b = db.one("select * from anomaly where rule='P1' and fkey='x-01' and status='open'")
    assert b["id"] != a["id"]
    with pytest.raises(Exception):
        D.act(b["id"], "厂长", "close", "")                               # 关闭要写原因
    D.act(b["id"], "厂长", "close", "换了编码器", now=t0)
    assert len(D._apply("teach", r, [f], t0 + dt.timedelta(hours=3))) == 1
    b2 = db.one("select * from anomaly where id=%s", (b["id"],))
    assert b2["status"] == "open" and b2["reopened"] == 1
    kinds = [n["kind"] for n in D.notes(b["id"])]
    assert kinds == ["open", "close", "reopen"]


def test_rule_config_changes_are_audited(db):
    from hub.ont.anomaly import Detector, RuleError
    D = Detector(db)
    D.init()
    from hub.ont.store import Store
    Store(db).init()
    r = D.set_rule("P5", "王老师", params={"above": 3})
    assert r["params"]["above"] == 3
    D.set_rule("P5", "王老师", enabled=False)
    assert not D.rule("P5")["enabled"]
    ch = db.q("select field, old, new from rule_change where rule='P5' order by id")
    assert [(c["field"], c["old"], c["new"]) for c in ch] == [("params.above", 6, 3), ("enabled", True, False)]
    D.catalog["F2"] = dict(D.catalog["F2"], waiting=True)                # 第 18 轮 E7 起规则库没有“待数据”的了：临时当它是待数据
    with pytest.raises(RuleError):
        D.set_rule("F2", "王老师", enabled=True)                          # 待数据的规则不能启用
    D.set_rule("P5", "王老师", enabled=True, params={"above": 6})


def test_evaluate_publishes_alerts_once(db):
    from hub.ai import Assistant

    class NoLLM:
        name = "rules"

        def available(self):
            return False
    db.x("delete from anomaly")
    sent = []
    a = Assistant(db, lambda *x: sent.append(x), NoLLM())
    alerts = a.evaluate("teach", NOW)
    keys = {x["key"] for x in alerts}
    assert "down:grd-01" in keys and "stock:BRG-6207" in keys
    assert all(x["anomaly_id"] for x in alerts)
    assert len(sent) == len(alerts) and all(s[1] == "ai.alert" for s in sent)
    assert a.evaluate("teach", NOW) == []
    st = a.detector().stats
    assert not [k for k, v in st.items() if v["error"] and k not in ("V1", "V2", "V3")], st
