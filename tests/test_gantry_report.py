"""龙门取放机器人（案例 B）的报告、BOM 与对照页（ADR-0115 44.5.5 第三步，assist/gantry_report）：只读结果文件，
数与结果一致，缺的写“待确认”，参照只作参照。不联网、不调用 LLM、不重算。"""

import copy
import json
from pathlib import Path

import pytest

from assist import gantry_case
from assist import gantry_report as R

CASE = Path(__file__).resolve().parents[1] / "examples" / "robots" / "sewing-loader"
OUT = CASE / "out"


@pytest.fixture(scope="module")
def res():
    return R.load(OUT)


def test_bom_takes_masses_from_results(res):
    b = R.bom(res)
    parts = res["cad"]["cad"]["parts"]
    mods = [p for p in parts if p["kind"] == "module"]
    assert [r["role"] for r in b["purchased"]] == ["直线模组", "直线模组", "抓手"]
    assert [r["model"] for r in b["purchased"][:2]] == [res["cad"]["reverify"]["picks"][p["joint"]]["model"] for p in mods]
    assert b["purchased"][0]["mass_kg_each"] == res["cad"]["reverify"]["picks"]["j1_x"]["mass_kg"]
    assert b["purchased"][0]["mass_source"].startswith("src-festo")              # 质量带零件库的资料出处
    made = [p for p in parts if p["kind"] not in ("module", "gripper")]
    assert len(b["made"]) == len(made) == 7
    assert [r["drawing_no"] for r in b["made"]][:2] == ["SL-01", "SL-02"]
    assert b["made_mass_kg"] == pytest.approx(sum(p["mass_kg"] for p in made), abs=1e-4)
    assert b["purchased_mass_kg"] == pytest.approx(sum(p["mass_kg"] for p in res["cad"]["reverify"]["picks"].values()), abs=1e-4)
    assert b["total_mass_kg"] == pytest.approx(b["purchased_mass_kg"] + b["made_mass_kg"], abs=1e-4)
    # 抓手质量厂商没给：不估、不计，写明
    g = b["purchased"][2]
    assert g["mass_kg_each"] is None and b["mass_not_counted"] == ["抓手 SPF 15"]
    rows = R.bom_csv(b).splitlines()
    assert rows[3].split(",")[7] == ""                                          # CSV 里抓手质量一格空着，不写 0
    assert sum(1 for x in rows if ",未列入," in x) == len(R.NOT_LISTED)


def test_report_numbers_come_from_results(res):
    b = R.bom(res)
    md = R.report(res, b)
    for h in ("## 需求原话", "## 1 整机方案", "## 2 校核结论", "## 3 仿真数字与需求逐条对照", "## 4 三维模型与 BOM", "## 5 用时", "## 6 卡在哪里"):
        assert h in md
    rows = {r[0]: r for r in R.requirement_rows(res, b)}
    assert rows["节拍"][2].startswith(f"{res['build']['cycle_time']['total_s']:g} s") and rows["节拍"][3] == "通过"
    jd = res["cad"]["judge"]["deflection"]
    assert f"= {round(jd['total_mm'], 3):g} mm" in rows["放料定位精度"][2] and rows["放料定位精度"][3] == "通过"
    for k in ("不能损伤布料", "一次只取一片", "不能占用车间通道", "成本"):
        assert rows[k][3] == "待确认"
    lv = res["cad"]["reverify"]["loads_vs_step1"]["j1_x"]["moment_pitch_nm"]
    assert f"| j1_x | 俯仰力矩 N·m | {round(lv['step1'], 2):g} | {round(lv['cad'], 2):g} |" in md
    assert all(x in md for x in res["cad"]["open_items"])


def test_missing_data_is_not_guessed(res):
    r = copy.deepcopy(res)
    r.pop("timing", None)
    r["cad"].pop("frame_fea")
    r["cad"].pop("judge")
    r["build"]["gripper"]["checks"] = [c for c in r["build"]["gripper"]["checks"] if c["check"] != "G1"]
    b = R.bom(r)
    md = R.report(r, b)
    assert "待确认：没有 timing.json" in md and "待确认：有限元没跑" in md
    rows = {x[0]: x for x in R.requirement_rows(r, b)}
    assert rows["放料定位精度"][3] == "待确认" and rows["单片质量"][3] == "待确认"
    assert "门架有限元没跑" in R.open_items(r, b)


def test_comparison_reference_only(res):
    ref = R.load_reference(CASE / "reference.json")
    raw = json.loads((CASE / "reference.json").read_text(encoding="utf-8"))
    assert raw["accessed"] and raw["purpose"].startswith("同类")
    for r in raw["robots"]:
        assert r["url"].startswith("https://")
        assert all(p.get("quote") for f, p in r.items() if isinstance(p, dict))      # 每个数、每条说法都带原话
    rt = next(r for r in ref["robots"] if r["vendor"] == "Robotextile")
    assert (rt["cycle_s"]["min_std"], rt["cycle_s"]["max_std"]) == (2, 4)
    page = R.comparison(res, ref, R.bom(res))
    assert "只作参照" in page and "未公开" in page
    assert f"| **本案例 B（我们的方案）** | 台面上的 X–Z 两轴龙门（费斯托直线模组） | {res['build']['cycle_time']['total_s']:g}（要求 ≤ 3）" in page
    assert all(r["url"] in page for r in raw["robots"])


def test_saved_files_match_results():
    """保存的 report.md、bom.csv、bom.json、comparison.md 就是从保存的结果文件生成的"""
    res = R.load(OUT)
    b = R.bom(res)
    assert json.loads((OUT / "bom.json").read_text(encoding="utf-8")) == json.loads(json.dumps(b))
    assert (OUT / "bom.csv").read_text(encoding="utf-8") == R.bom_csv(b)
    assert (OUT / "report.md").read_text(encoding="utf-8") == R.report(res, b)
    assert (OUT / "comparison.md").read_text(encoding="utf-8") == R.comparison(res, R.load_reference(CASE / "reference.json"), b)
    t = res["timing"]
    assert t["status"] == "pass" and [s["step"] for s in t["steps"]] == list(gantry_case.STEPS)


def test_case_plan_order(tmp_path):
    steps = gantry_case.plan(tmp_path, Path("rec"), None)
    assert [s[0] for s in steps] == list(gantry_case.STEPS)
    assert steps[0][1] == "AI（回放录制）+ 代码" and {s[1] for s in steps[1:]} == {"代码"}
    from assist.robot_case import run

    calls = []
    t = run(tmp_path, steps=[(n, w, (lambda n=n: calls.append(n) or (1 if n == gantry_case.STEPS[1] else 0))) for n, w, _ in steps],
            ai="测试")
    assert t["status"] == "fail" and t["stopped_at"] == gantry_case.STEPS[1] and calls == list(gantry_case.STEPS[:2])
    assert t["ai"] == "测试"
