"""数字孪生 · 预测性维护（ADR-0057，M10 第五步）：寿命与手算一致、变工况、假如、缺参数待确认、报警。不联网。

测试中的零件参数是测试数据（不进零件库）：额定寿命等按 ADR-0057 由企业补录。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import analysis
from analysis import twin
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")


def _pv(v, cond=None):
    out = {"value": v, "source": {"doc": "src-ent-test", "page": 1, "note": "测试数据"}, "method": "manual",
           "confidence": 1, "reviewed": True}
    if cond:
        out["condition"] = cond
    return out


REDUCER = {"id": "reducer.test.r", "category": "reducer", "vendor": "Test", "model": "R-25-100",
           "params": {"rated_life_h": _pv(7000, "L10"), "rated_torque_nm": _pv(67, "2000 rpm"),
                      "rated_input_speed_rpm": _pv(2000), "ratio": _pv(100), "repeated_peak_torque_nm": _pv(108),
                      "momentary_max_torque_nm": _pv(204), "avg_input_speed_limit_rpm": _pv(3500)}}
BEARING = {"id": "bearing.test.b", "category": "bearing", "vendor": "Test", "model": "6206",
           "params": {"dynamic_load_rating_n": _pv(20300), "bearing_kind": _pv("deep_groove_ball")}}


def _rows(n, inst="joint", **kw):
    return [{"instance": inst, "hours": 10.0, **kw} for _ in range(n)]


def test_reducer_life_matches_catalog_formula():
    recs = _rows(100, output_torque_avg_nm=30, output_torque_max_nm=60, output_speed_rpm=15)
    out = analysis.run("twin", {"parts": [{"instance": "joint", "component": REDUCER}], "records": recs})
    assert out["status"] == "ok"
    p = out["data"]["parts"][0]
    life = 7000 * (67 / 30) ** 3 * (2000 / (15 * 100))  # L = L_r·(T_r/T_av)³·(n_r/n_in)
    assert p["used_ratio"] == pytest.approx(1000 / life, rel=1e-9)
    assert p["life_at_recent_rate_h"] == pytest.approx(life, rel=1e-9)
    assert p["remaining_h"] == pytest.approx(life - 1000, rel=1e-9)
    assert p["status"] == "ok" and out["setup"]["parts"][0]["component"] == "reducer.test.r"


def test_variable_load_equals_cube_mean():
    recs = _rows(50, output_torque_avg_nm=20, output_speed_rpm=15) + _rows(50, output_torque_avg_nm=40,
                                                                            output_speed_rpm=15)
    p = twin.assess({"instance": "joint", "component": REDUCER}, recs)
    t_eq = ((20 ** 3 + 40 ** 3) / 2) ** (1 / 3)  # 当量扭矩：三次方平均
    life_eq = 7000 * (67 / t_eq) ** 3 * (2000 / 1500)
    assert p["used_ratio"] == pytest.approx(1000 / life_eq, rel=1e-9)


def test_whatif_lower_load():
    recs = _rows(100, output_torque_avg_nm=30, output_speed_rpm=15)
    out = analysis.run("twin", {"parts": [{"instance": "joint", "component": REDUCER}], "records": recs,
                                "whatif": {"load_factor": 0.8}})
    now, wi = out["data"]["parts"][0], out["data"]["whatif"]["parts"][0]
    assert wi["life_at_recent_rate_h"] / now["life_at_recent_rate_h"] == pytest.approx(1 / 0.8 ** 3, rel=1e-9)


def test_bearing_l10():
    recs = _rows(10, "brg", radial_load_n=2000, speed_rpm=500)
    p = twin.assess({"instance": "brg", "component": BEARING}, recs)
    l10 = (20300 / 2000) ** 3 * 1e6 / (60 * 500)  # ISO 281，球轴承
    assert p["life_at_recent_rate_h"] == pytest.approx(l10, rel=1e-9)
    roller = {**BEARING, "params": {**BEARING["params"], "bearing_kind": _pv("cylindrical_roller")}}
    assert twin.assess({"instance": "brg", "component": roller}, recs)["life_at_recent_rate_h"] == pytest.approx(
        (20300 / 2000) ** (10 / 3) * 1e6 / (60 * 500), rel=1e-9)


def test_alerts_and_status():
    over = _rows(5, output_torque_avg_nm=30, output_torque_max_nm=150, output_speed_rpm=15)
    p = twin.assess({"instance": "joint", "component": REDUCER}, over)
    assert p["status"] == "warn" and "启停允许峰值扭矩" in p["alerts"][0]["text"] and len(p["alerts"]) == 1
    worse = _rows(1, output_torque_avg_nm=30, output_torque_max_nm=250, output_speed_rpm=15)
    assert twin.assess({"instance": "joint", "component": REDUCER}, worse)["status"] == "severe"
    worn = _rows(400, output_torque_avg_nm=67, output_speed_rpm=20)  # 额定扭矩、输入 2000 rpm：4000 h
    p = twin.assess({"instance": "joint", "component": REDUCER}, worn)
    assert p["used_ratio"] == pytest.approx(4000 / 7000) and p["status"] == "ok"
    p = twin.assess({"instance": "joint", "component": REDUCER}, worn + _rows(200, output_torque_avg_nm=67,
                                                                              output_speed_rpm=20))
    assert p["status"] == "warn" and any("已用掉" in a["text"] for a in p["alerts"])


def test_public_library_reducer_is_unknown_until_filled():
    """公共库的减速器还没有额定寿命：待确认，并说明缺什么（ADR-0057 第 2 条）。"""
    system = {"components": [{"instance": "motor", "component": "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"},
                             {"instance": "reducer", "component": "reducer.harmonic-drive-llc.csf-25-100-2uh"}]}
    parts = twin.parts_from_system(system, LIB.get)
    assert [p["instance"] for p in parts] == ["reducer"]
    out = analysis.run("twin", {"parts": parts, "records": _rows(3, "reducer", output_torque_avg_nm=20,
                                                                  output_speed_rpm=15)})
    p = out["data"]["parts"][0]
    assert p["status"] == "unknown" and "rated_life_h" in p["missing"] and out["data"]["overall"] == "unknown"
    from mcp_server import tools

    via_tool = tools.run_analysis("twin", {"system": system, "records": []}, LIB)
    assert via_tool["data"]["parts"][0]["status"] == "unknown"


def test_csv_records(tmp_path):
    path = tmp_path / "run.csv"
    path.write_text("instance,hours,output_torque_avg_nm,output_torque_max_nm,output_speed_rpm,radial_load_n,speed_rpm\n"
                    "joint,8,30,60,15,,\nbrg,8,,,,2000,500\n,8,1,1,1,,\njoint,0,30,60,15,,\n", encoding="utf-8")
    rows = twin.read_csv(path)
    assert rows == [{"instance": "joint", "hours": 8.0, "output_torque_avg_nm": 30.0, "output_torque_max_nm": 60.0,
                     "output_speed_rpm": 15.0}, {"instance": "brg", "hours": 8.0, "radial_load_n": 2000.0,
                                                 "speed_rpm": 500.0}]


def test_twin_errors():
    assert analysis.run("twin", {"parts": []})["status"] == "failed"
    out = analysis.run("twin", {"parts": [{"instance": "joint", "component": REDUCER}], "records": [],
                                "whatif": {"load_factor": 0}})
    assert out["status"] == "failed"
