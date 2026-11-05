# -*- coding: utf-8 -*-
"""第 88 轮：电路板厂功能测试台——测试程序按车间记录复现、复测核对（读得对不对、判定对不对）、复测记录进单件档案。"""
import os
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIG)

from hub import fct  # noqa: E402


def _m(serial, code, v, lo, hi, nom, lot="SH-002"):
    return {"type": "quality.measurement", "ts": "2026-11-05T10:00:00Z", "data": {
        "part_serial": serial, "item": "DRV-JOINT", "operation": "功能测试 FCT", "characteristic": code, "value_mm": v,
        "lower_tol_mm": lo, "upper_tol_mm": hi, "nominal_mm": nom, "result": "pass" if lo <= v <= hi else "fail", "lot": lot,
        "work_order": "WO-1"}}


class FakeDB:
    def __init__(self, shunt=2.004, isense=0.3):
        self.rows = []
        self.saved = []
        for s, sh, ie in (("DRV-0001", shunt, isense), ("DRV-0002", 2.051, 2.6)):
            self.rows += [_m(s, "ict_shunt", sh, 1.98, 2.02, 2.0), _m(s, "fct_vbus", 0.12, -1, 1, 0), _m(s, "fct_isense", ie, -2, 2, 0),
                          _m(s, "fct_deadtime", 203.0, 160, 240, 200), _m(s, "fct_enc", 0.3, -2, 2, 0), _m(s, "fct_drift", 8.0, -50, 50, 0)]
        self.rows.append({"type": "quality.measurement", "ts": "x", "data": dict(_m("SMT-1", "spi_volume", 99, 70, 130, 100)["data"],
                                                                                 item="SMT-DRV", operation="自动光学检测 AOI")})

    def messages(self, types=None, mode=None, order="asc", limit=None):
        return list(reversed(self.rows)) if order == "desc" else list(self.rows)

    def q(self, sql, args=None):
        return [{"ts": "2026-11-05", "user_name": u, "verdict": v, "readings": r, "check_rows": c} for (_, u, s, _, r, v, c) in self.saved
                if s == args[0]]

    def x(self, sql, args=None):
        self.saved.append(tuple(getattr(a, "obj", a) for a in args))


def test_boards_and_case():
    db = FakeDB()
    b = fct.boards(db, "teach")
    assert {x["serial"] for x in b} == {"DRV-0001", "DRV-0002"}
    assert next(x for x in b if x["serial"] == "DRV-0002")["fail"] == 2
    c = fct.case(db, "teach", "DRV-0001")
    assert [s["key"] for s in c["steps"]] == ["ict_shunt", "fct_vbus", "fct_isense", "fct_deadtime", "fct_enc", "fct_drift"]
    assert c["steps"][0]["true"] == 2.004 and c["board"]["lot"] == "SH-002"


def test_retest_checks_readings_and_verdict():
    db = FakeDB()
    ok = fct.retest(db, "teach", "s1", "DRV-0001", {"ict_shunt": 2.005, "fct_vbus": 0.1, "fct_isense": 0.35, "fct_deadtime": 200}, "pass")
    assert ok["verdict_ok"] and ok["all_close"] and ok["should_be"] == "pass"
    bad = fct.retest(db, "teach", "s1", "DRV-0002", {"ict_shunt": 2.05, "fct_vbus": 0.1, "fct_isense": 2.6, "fct_deadtime": 203}, "pass")
    assert not bad["verdict_ok"] and bad["should_be"] == "fail"                      # 采样电阻那一卷超差：应判不合格
    off = fct.retest(db, "teach", "s1", "DRV-0001", {"ict_shunt": 2.1, "fct_vbus": 0.1, "fct_isense": 0.3, "fct_deadtime": 260}, "pass")
    assert not off["all_close"] and [r["key"] for r in off["rows"] if not r["close"]] == ["ict_shunt", "fct_deadtime"]
    assert len(fct.retests(db, "DRV-0001")) == 2 and len(db.saved) == 3               # 复测记录进单件档案


def test_unknown_board():
    import pytest
    with pytest.raises(KeyError):
        fct.case(FakeDB(), "teach", "NOPE")
