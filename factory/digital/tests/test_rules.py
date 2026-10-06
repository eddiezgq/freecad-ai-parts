# -*- coding: utf-8 -*-
"""第 17 轮 B 期：20 条规则逐条“该报 / 不该报”（不用数据库：假数据 + 假看板）。"""
import datetime as dt
import itertools

import pytest

from hub.ont import anomaly as A
from hub.ont import rules as R

NOW = dt.datetime(2026, 10, 20, 18, 0, tzinfo=dt.timezone.utc)      # 纽约 14:00
_seq = itertools.count(1)


def msg(type_, topic, data, ts, corr=None):
    return {"type": type_, "_topic": topic, "data": data, "ts": ts.isoformat(), "id": "m{}".format(next(_seq)), "_seq": next(_seq),
            "corr": corr}


class FakeDB:
    def __init__(self, msgs=(), docs=None, tables=None):
        self.msgs, self.docs, self.tables = list(msgs), docs or {}, tables or []

    def messages(self, types=None, since=None, until=None, mode=None, topic_like=None, corr=None, limit=None, order="asc"):
        def t(x):
            return dt.datetime.fromisoformat(x) if isinstance(x, str) else x
        out = [m for m in self.msgs if (not types or m["type"] in types) and (since is None or t(m["ts"]) >= t(since))
               and (until is None or t(m["ts"]) <= t(until)) and (corr is None or m.get("corr") == corr)]
        out.sort(key=lambda m: (m["ts"], m["_seq"]), reverse=order == "desc")
        return out[:limit] if limit else out

    def erp_docs(self, doctype, mode=None):
        return [{"data": d, "id": "d" + d["name"], "_seq": 1, "_topic": "wq/gearbox/office/erp/x"} for d in self.docs.get(doctype, [])]

    def q(self, sql, args=None):
        for pat, fn in self.tables:
            if pat in sql:
                return fn(args)
        raise AssertionError("没想到的查询：" + sql)

    def one(self, sql, args=None):
        r = self.q(sql, args)
        return r[0] if r else None


def run(rid, db=None, ov=None, params=None, now=NOW):
    cat = A.load_catalog()
    r = cat[rid]
    c = A.Ctx(db or FakeDB(), "teach", now)
    if ov is not None:
        c._c["ov"] = ov
    p = dict(r["params"], **(params or {}))
    return R.REG[r["fn"]](c, p, r)


def mach(unit, state="run", **k):
    return dict({"unit": unit, "code": unit.upper(), "state": state, "reason": None, "down_until_s": None, "queue": 0,
                 "bottleneck": False, "tool_life_left": 0.8, "ts": NOW.isoformat()}, **k)


# ---------------------------------------------------------------- 生产
def test_P1_down():
    ov = {"machines": [mach("cnc-l01-b", "fault", reason="主轴报警", down_until_s=600, queue=3), mach("grd-01")]}
    f = run("P1", ov=ov)
    assert [x.fkey for x in f] == ["cnc-l01-b"] and f[0].severity == "critical"
    assert run("P1", ov={"machines": [mach("grd-01")]}) == []


def test_P2_tool_life():
    assert [x.fkey for x in run("P2", ov={"machines": [mach("grd-01", tool_life_left=0.1)]})] == ["grd-01"]
    assert run("P2", ov={"machines": [mach("grd-01", "down", tool_life_left=0.1), mach("saw-01", "idle", tool_life_left=0.05)]}) == []


def test_P3_oee():
    m = {"cnc-l01-a": {"oee": 0.45, "availability": 0.5, "performance": 0.95, "quality": 1.0, "run_s": 9000, "setup_s": 900, "down_s": 5000},
         "saw-01": {"oee": 0.40, "availability": 0.4, "performance": 1, "quality": 1, "run_s": 1000, "setup_s": 0, "down_s": 0},
         "grd-01": {"oee": 0.8, "availability": 0.9, "performance": 0.9, "quality": 1, "run_s": 20000, "setup_s": 0, "down_s": 0}}
    f = run("P3", ov={"oee": {"machines": m}})
    assert [x.fkey for x in f] == ["cnc-l01-a"] and "停机和调整多" in f[0].detail     # saw-01 负荷不足 2 小时，不报


def test_P4_tool_change_rate():
    tc = lambda u, h: msg("machine.event", "wq/gearbox/machining/{}/event".format(u), {"event": "tool_change"}, NOW - dt.timedelta(hours=h))
    evs = [tc("cnc-l01-a", h) for h in (1, 2, 3)] + [tc("cnc-l01-a", 30)] + [tc("key-01", h) for h in (1, 2, 3)] + \
          [tc("key-01", 24 * d) for d in range(1, 7) for _ in range(2)]
    f = run("P4", db=FakeDB(evs))
    assert [x.fkey for x in f] == ["cnc-l01-a"]                       # key-01 平时每天 2 次，今天 3 次不算异常


def test_P5_backlog():
    assert [x.fkey for x in run("P5", ov={"machines": [mach("grd-01", queue=8, bottleneck=True)]})] == ["grd-01"]
    assert run("P5", ov={"machines": [mach("grd-01", queue=5, bottleneck=True), mach("saw-01", queue=9)]}) == []


# ---------------------------------------------------------------- 质量
def meas(char, vals, start=NOW - dt.timedelta(hours=20)):
    from sim.errors import CHARS
    _, name, nom, lo, hi = next(c for c in CHARS if c[0] == char)
    return [msg("quality.measurement", "wq/gearbox/quality/qc-01/measurement",
                {"part_serial": "SH301-T-{:03d}".format(i), "item": "SH-301", "characteristic": char, "name": name, "nominal_mm": nom,
                 "lower_tol_mm": lo, "upper_tol_mm": hi, "value_mm": v, "result": "pass" if lo <= v <= hi else "fail"},
                start + dt.timedelta(minutes=10 * i)) for i, v in enumerate(vals)]


def test_Q1_spc():
    import random
    rnd = random.Random(1)
    stable = [35.010 + rnd.gauss(0, 0.0008) for _ in range(60)]
    f = run("Q1", db=FakeDB(meas("bearing_seat_d35", stable + [35.010 + 0.0045 + rnd.gauss(0, 0.0003) for _ in range(10)])))
    assert [x.values["characteristic"] for x in f] == ["bearing_seat_d35"] and 1 in f[0].values["rules"] and f[0].severity == "critical"
    assert run("Q1", db=FakeDB(meas("bearing_seat_d35", stable))) == []


def test_Q2_near_limit():
    ch = {"points": [{"id": i} for i in range(6)], "upper": 35.018, "lower": 35.002, "margin_um": 2.0, "shift_um": 6.0,
          "characteristic": "bearing_seat_d35", "title": "Ø35", "mean_last5": 35.016, "src": "t"}
    assert len(run("Q2", ov={"quality": {"chart": ch}})) == 1
    assert run("Q2", ov={"quality": {"chart": dict(ch, margin_um=6.0)}}) == []


def test_Q3_ncr_escalates_after_2h():
    n = lambda h: {"ncr_id": "NCR-1", "part_serial": "SH301-1", "detail": {"name": "Ø35"}, "created_at": (NOW - dt.timedelta(hours=h)).isoformat()}
    assert run("Q3", ov={"quality": {"ncr": [n(1)]}})[0].severity == "warn"
    assert run("Q3", ov={"quality": {"ncr": [n(3)]}})[0].severity == "critical"
    assert run("Q3", ov={"quality": {"ncr": []}}) == []


def test_Q4_fpy():
    vals = [35.010] * 18 + [35.020, 35.021]                          # 20 件里 2 件超差：90%
    f = run("Q4", db=FakeDB(meas("bearing_seat_d35", vals)))
    assert len(f) == 1 and f[0].values["fpy"] == 0.9 and len(f[0].values["bad"]) == 2
    assert run("Q4", db=FakeDB(meas("bearing_seat_d35", [35.010] * 20))) == []
    assert run("Q4", db=FakeDB(meas("bearing_seat_d35", [35.010] * 5 + [35.020]))) == []     # 不够 10 件


def test_Q5_8d_stale():
    rows = [{"id": "Q8D-1", "title": "a", "status": "D4", "created_at": NOW - dt.timedelta(days=9), "item": "SH-301"},
            {"id": "Q8D-2", "title": "b", "status": "D2", "created_at": NOW - dt.timedelta(days=2), "item": "SH-301"}]
    assert [x.fkey for x in run("Q5", db=FakeDB(tables=[("quality_8d", lambda a: rows)]))] == ["Q8D-1"]


# ---------------------------------------------------------------- 销售、计划、供应
def order(name, tone, delivery, projected):
    return {"name": name, "tone": tone, "risk": "预计晚", "customer": "峰顶 Peak", "qty": 10, "delivery_date": delivery,
            "projected": projected, "work_orders": "WO-1", "short": None}


def test_S1_order_late():
    f = run("S1", ov={"orders": [order("SO-1", "bad", "2026-10-20", "2026-10-21"), order("SO-2", "bad", "2026-10-20", "2026-10-25"),
                                 order("SO-3", "warn", "2026-10-20", "2026-10-20")]})
    assert {x.fkey: x.severity for x in f} == {"SO-1": "warn", "SO-2": "critical"}


def test_S2_wo_overdue():
    docs = {"Work Order": [{"name": "WO-1", "expected_delivery_date": "2026-10-18", "status": "In Process", "qty": 10, "production_item": "SH-301"},
                           {"name": "WO-2", "expected_delivery_date": "2026-10-18", "status": "Completed", "qty": 10},
                           {"name": "WO-3", "expected_delivery_date": "2026-10-25", "status": "In Process", "qty": 10},
                           {"name": "WO-4", "expected_delivery_date": "2026-10-01", "status": "In Process", "qty": 10, "demo": True}]}
    f = run("S2", db=FakeDB(docs=docs))
    assert [x.fkey for x in f] == ["WO-1"] and f[0].values["days"] == 2


def test_W1_stock():
    mt = lambda c, tone: {"code": c, "tone": tone, "status": "低于安全库存", "name": c, "qty_text": "8", "safety": 10, "need": 20, "qty": 8}
    assert [x.fkey for x in run("W1", ov={"materials": [mt("BRG-6207", "bad"), mt("RM-1", "good")]})] == ["BRG-6207"]


def test_W2_po_late():
    docs = {"Purchase Order": [
        {"name": "PO-1", "supplier": "洛轴", "status": "To Receive and Bill",
         "items": [{"item_code": "BRG-6207", "qty": 20, "received_qty": 0, "schedule_date": "2026-10-15"}]},
        {"name": "PO-2", "supplier": "洛轴", "status": "To Receive and Bill",
         "items": [{"item_code": "BRG-6207", "qty": 20, "received_qty": 20, "schedule_date": "2026-10-15"}]},
        {"name": "PO-3", "supplier": "洛轴", "status": "To Receive and Bill",
         "items": [{"item_code": "BRG-6207", "qty": 20, "received_qty": 0, "schedule_date": "2026-10-28"}]}]}
    f = run("W2", db=FakeDB(docs=docs))
    assert [x.fkey for x in f] == ["PO-1"] and ("Supplier", "洛轴") in f[0].about


# ---------------------------------------------------------------- 服务
def unit(serial, health, customer="港口 Port", kind="bearing"):
    return {"serial": serial, "health": health, "customer": customer, "site": "port",
            "alerts": [{"title": "中间轴轴承 B 损伤加快", "level": health, "kind": kind}] if health != "green" else []}


def test_V1_field_alarm(monkeypatch):
    from hub import twin as TW
    monkeypatch.setattr(TW, "fleet", lambda db, mode: [unit("U1", "red"), unit("U2", "yellow"), unit("U3", "green")])
    f = run("V1")
    assert {x.fkey: x.severity for x in f} == {"U1": "critical", "U2": "warn"}


def test_V2_same_batch(monkeypatch):
    from hub import twin as TW
    shaft = {"U1": "S1", "U2": "S2", "U3": "S3"}
    wheel = {"S1": "grd-01/3", "S2": "grd-01/3", "S3": "grd-01/4"}
    wo = {"S1": "WO-A", "S2": "WO-B", "S3": "WO-B"}
    db = FakeDB(tables=[("PartSerial.installed_in", lambda a: [{"src_key": shaft[a[1]]}] if a[1] in shaft else []),
                        ("PartSerial.processed", lambda a: [{"props": {"tool": wheel[a[1]], "machine": "grd-01"}}]),
                        ("type='PartSerial' and key", lambda a: [{"wo": wo[a[1]]}])])
    monkeypatch.setattr(TW, "fleet", lambda d, mode: [unit("U1", "red"), unit("U2", "yellow"), unit("U3", "green")])
    f = run("V2", db=db)
    assert [(x.subject, x.values["units"]) for x in f] == [(("Tool", "grd-01/3"), ["U1", "U2"])]
    monkeypatch.setattr(TW, "fleet", lambda d, mode: [unit("U1", "red"), unit("U2", "green")])
    assert run("V2", db=db) == []
    monkeypatch.setattr(TW, "fleet", lambda d, mode: [unit("U1", "red"), unit("U2", "yellow", kind="oil")])
    assert run("V2", db=db) == []                                    # 换油过期与批次无关


def test_V3_service_overdue():
    clock = [{"paused": True, "anchor_day": dt.date(2027, 3, 10), "anchor_real": NOW, "days_per_min": 1}]
    ev = [{"id": 1, "serial": "U1", "day": dt.date(2027, 3, 1), "title": "换轴承", "status": "ordered", "detail": {"issue": "ISS-1"}},
          {"id": 2, "serial": "U2", "day": dt.date(2027, 3, 8), "title": "换油", "status": "ordered", "detail": {"issue": "ISS-2"}}]
    f = run("V3", db=FakeDB(tables=[("field_clock", lambda a: clock), ("twin_event", lambda a: ev)]))
    assert [x.fkey for x in f] == ["ISS-1"]


# ---------------------------------------------------------------- 维护、财务、研发
def test_M1_repeat_down():
    ev = lambda u, h, e="alarm": msg("machine.event", "wq/gearbox/machining/{}/event".format(u), {"event": e, "message": "卡料"},
                                     NOW - dt.timedelta(hours=h))
    f = run("M1", db=FakeDB([ev("saw-01", h) for h in (1, 5, 9)] + [ev("grd-01", h) for h in (1, 30, 40)] + [ev("ht-01", 1, "recover")]))
    assert [x.fkey for x in f] == ["saw-01"]


def test_F1_cost_variance(monkeypatch):
    from hub import mrp
    k = {"WO-1": {"std_cost": 500, "actual_cost": 580, "variance_pct": 16.0, "lines": [{"operation": "磨外圆", "variance": 50}]},
         "WO-2": {"std_cost": 500, "actual_cost": 520, "variance_pct": 4.0, "lines": []}}
    monkeypatch.setattr(mrp, "wo_cost", lambda db, w, mode="teach": k.get(w))
    f = run("F1", db=FakeDB(docs={"Work Order": [{"name": "WO-1"}, {"name": "WO-2"}, {"name": "WO-3"}]}))
    assert [x.fkey for x in f] == ["WO-1"] and "磨外圆" in f[0].detail


def test_D1_revision_in_wip():
    rel = msg("design.release", "wq/gearbox/design/sh-301/release", {"item": "SH-301", "revision": 3}, NOW - dt.timedelta(hours=1))
    st = lambda wo, h: msg("machine.event", "wq/gearbox/machining/saw-01/event", {"event": "cycle_start", "part_serial": wo + "-1"},
                           NOW - dt.timedelta(hours=h), corr=wo)
    docs = {"Work Order": [{"name": "WO-A", "production_item": "SH-301", "status": "In Process"},
                           {"name": "WO-B", "production_item": "SH-301", "status": "In Process"},
                           {"name": "WO-C", "production_item": "SH-301", "status": "Completed"}]}
    f = run("D1", db=FakeDB([rel, st("WO-A", 2), st("WO-B", 0.5), st("WO-C", 3)], docs))
    assert [x.fkey for x in f] == ["WO-A:3"]                         # WO-B 是改版后才开工的


def test_every_live_rule_has_a_test():
    import sys
    names = {n for n in dir(sys.modules[__name__]) if n.startswith("test_")}
    for rid, r in A.load_catalog().items():
        if not r["waiting"]:
            assert any(n.startswith("test_{}_".format(rid)) for n in names), rid
