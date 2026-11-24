"""整机案例的报告与 BOM（ADR-0115 44.3 之二第 7 步）：只读结果文件，数与结果一致，缺的写“待确认”"""

import copy
import json
from pathlib import Path

import pytest

from assist import robot_case
from assist import robot_report as R

OUT = Path(__file__).resolve().parents[1] / "examples" / "robots" / "teaching-arm" / "out"


@pytest.fixture(scope="module")
def res():
    r = R.load(OUT)
    r.pop("timing", None)
    return r


def _holes(cad):
    n = 0
    for p in cad["parts"]:
        for i in (p.get("interfaces") or {}).values():
            if i.get("type") == "holes":
                n += len(i["centers"])
    return n


def test_bom_masses_add_up_to_the_assembly(res):
    b = R.bom(res)
    assert b["total_mass_kg"] == pytest.approx(res["cad"]["mass_kg"], abs=1e-3)
    assert b["purchased_mass_kg"] + b["made_mass_kg"] == pytest.approx(b["total_mass_kg"], abs=1e-4)
    acts = [p for p in res["cad"]["parts"] if p["kind"] == "actuator"]
    assert sum(r["qty"] for r in b["purchased"]) == len(acts) == 5
    assert len(b["made"]) == len(res["cad"]["parts"]) - len(acts)
    assert [r["drawing_no"] for r in b["made"]][:2] == ["TA-01", "TA-02"]
    assert b["purchased"][0]["mass_source"].startswith("src-robotis")        # 质量带零件库的资料出处


def test_screws_are_counted_from_the_assembly_holes_and_have_no_invented_length(res):
    b = R.bom(res)
    assert sum(r["qty"] for r in b["fasteners"]) == _holes(res["cad"]) == 84
    for r in b["fasteners"]:
        assert "length_mm" not in r and "待定" in r["note"]
    csv = R.bom_csv(b)
    assert csv.count("紧固件") == len(b["fasteners"]) and "未列入" in csv


def test_report_numbers_come_from_the_result_files(res):
    b = R.bom(res)
    md = R.report(res, b)
    assert "None" not in md and "null" not in md
    for x in res["fea"]["items"]:
        assert f"| {x['part']} | 通过 |" in md
    j2 = next(x for x in res["verify"]["compare"] if x["joint"] == "j2")
    assert f"| j2 | {j2['peak_est_nm']:g} | {j2['peak_nm']:g} |" in md
    s2 = next(c for c in next(iter(res["verify"]["checks"].values()))["checks"] if c["check"] == "S2")
    assert s2["status"] == "unknown" and "选件 S2 待确认" in md
    rows = {r[0]: r for r in R.requirement_rows(res)}
    assert rows["外购件成本尽量低"][3] == "待确认"
    assert rows["关节最高角速度"][3] == "通过"
    assert "## 5 用时" in md and "没有 timing.json" in md


def test_missing_results_are_reported_as_unknown_not_guessed(res):
    r = copy.deepcopy(res)
    r.pop("fea")
    r["build"]["repeatability"].pop("worst_mm")
    md = R.report(r, R.bom(r))
    assert "待确认：没有 fea-result.json" in md and "支架有限元没跑" in md
    assert "最坏 ±待确认 mm" in md and "None" not in md


def test_timing_table(res):
    r = dict(res, timing={"machine": "4 核", "date": "2026-11-23", "ai": "回放",
                          "steps": [{"step": "构型", "who": "AI", "seconds": 2.0}, {"step": "选件", "who": "代码", "seconds": 3.5}]})
    md = R.report(r, R.bom(r))
    assert "| 构型 | AI | 2 |" in md and "合计 5.5 s" in md


def test_case_runner_times_each_step_and_stops_at_a_failure(tmp_path):
    ticks = iter(range(100))
    calls = []
    steps = [("一", "代码", lambda: calls.append(1) or 0), ("二", "代码", lambda: calls.append(2) or 3),
             ("三", "代码", lambda: calls.append(3) or 0)]
    t = robot_case.run(tmp_path, steps=steps, clock=lambda: float(next(ticks)))
    assert calls == [1, 2] and t["status"] == "fail" and t["stopped_at"] == "二"
    assert [s["seconds"] for s in t["steps"]] == [1.0, 1.0] and t["steps"][1]["exit_code"] == 3
    saved = json.loads((tmp_path / "out" / "timing.json").read_text(encoding="utf-8"))
    assert saved["status"] == "fail" and saved["machine"]
