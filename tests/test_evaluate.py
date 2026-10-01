"""抽取准确率评测（issue #31）的测试。只用模拟响应检验评分代码，不联网。"""

from __future__ import annotations

import copy
import os

import pytest

from ingest.evaluate import _same, aggregate, expected_targets, main, render_markdown, score
from ingest.llm_extract import extract_document
from ingest.llm_simulate import SimulatedClient, proposals_from_answer, simulated_response
from ingest.synthetic import FontMissing, datasheets, find_font

DOC = "src-test-fixture"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    pytest.importorskip("reportlab")
    pytest.importorskip("pdfplumber")
    try:
        find_font("latin")
        find_font("cjk")
    except FontMissing:
        if os.environ.get("CI"):
            raise
        pytest.skip("本地未安装生成 PDF 所需的字体；CI 中必须运行")
    from ingest.pdf_extract import extract

    d = tmp_path_factory.mktemp("ev")
    out = []
    for s in datasheets(0):
        doc = extract(s.render(d / f"{s.id}.pdf"))
        out.append((s.answer, doc))
    return out


def _run(answer, doc, proposals=None):
    return extract_document(doc, answer["category"], DOC, SimulatedClient(simulated_response(answer, proposals)))


def _real(result):
    """把模拟结果当作真实响应（只为检验“通过”判定的逻辑）。"""
    r = copy.deepcopy(result)
    r["extractor"].pop("simulated", None)
    return r


def test_same():
    assert _same(1.0, 1.0005) and not _same(1.0, 1.01)
    assert _same(["a", "b"], ["b", "a"]) and not _same(["a"], ["a", "b"])
    assert _same(True, True) and not _same(True, 1)
    assert _same("harmonic", "harmonic") and not _same("harmonic", "planetary")


def test_perfect_simulated(runs):
    pairs = [(a, _run(a, d)) for a, d in runs]
    report = aggregate(pairs)
    o = report["overall"]
    assert o["key_accuracy"] == 1.0 and o["recall"] == 1.0 and o["precision"] == 1.0
    assert o["condition_accuracy"] == 1.0
    assert set(report["by_category"]) == {"servo_motor", "reducer", "drive", "bearing"}
    assert report["simulated"] is True and report["passed"] is False  # 模拟响应不得作为验收依据
    md = render_markdown(report)
    assert "模拟响应" in md and "逐字段" in md and "| reducer |" in md
    assert sum(b["expected"] for b in report["by_category"].values()) == o["expected"]


def test_counts_wrong_missed_extra(runs):
    answer, doc = next((a, d) for a, d in runs if a["category"] == "reducer")
    props = proposals_from_answer(answer)
    exp = expected_targets(answer)
    by_t = {p["target"]: p for p in props}
    # 漏掉减速比（关键字段）
    props = [p for p in props if p["target"] != "params/ratio"]
    # 额定扭矩的工况写错（值仍对）
    rt = by_t["params/rated_torque_nm"]
    rt_bad = dict(rt)
    rt_bad.pop("condition")
    props = [rt_bad if p is rt else p for p in props]
    result = _run(answer, doc, props)
    # 再人为放入一个读错的值和一个多抽的字段（评分只看结果，与核对无关）
    result = copy.deepcopy(result)
    mass = next(i for i in result["items"] if i["target"] == "params/mass_kg")
    mass["value"]["value"] *= 2
    extra = copy.deepcopy(mass)
    extra["target"] = "params/output_bearing_dynamic_load_rating_n"
    if extra["target"] not in exp:
        result["items"].append(extra)
    rows = score(answer, result)
    assert rows["params/ratio"]["outcome"] == "missed"
    assert rows["params/mass_kg"]["outcome"] == "wrong"
    if extra["target"] not in exp:
        assert rows[extra["target"]]["outcome"] == "extra"
    # 缺工况时 schema 要求 condition，该项被核对拒绝 → 漏
    assert rows["params/rated_torque_nm"]["outcome"] == "missed"
    assert rows["params/rated_torque_nm"]["condition_ok"] is False
    report = aggregate([(answer, _real(result))])
    k = report["overall"]
    assert k["key_correct"] == k["key_expected"] - 3  # 减速比、质量、额定扭矩
    assert report["passed"] is False


def test_threshold_pass(runs):
    pairs = [(a, _real(_run(a, d))) for a, d in runs]
    report = aggregate(pairs)
    assert report["simulated"] is False and report["passed"] is True
    assert all(s["key_accuracy"] in (1.0, None) for s in report["sheets"])  # 驱动器没有关键字段


def test_range_shape_must_match(runs):
    answer, doc = next((a, d) for a, d in runs if a["category"] == "drive")
    result = copy.deepcopy(_run(answer, doc))
    v = next(i for i in result["items"] if i["target"] == "ports/power_in/voltage_v")["value"]
    v.pop("max")
    assert score(answer, result)["ports/power_in/voltage_v"]["outcome"] == "wrong"


def test_cli(tmp_path, runs):
    rc = main(["--variants", "1", "--work", str(tmp_path / "w"), "--out", str(tmp_path / "o"), "--simulate"])
    assert rc == 1  # 模拟响应永远不算通过
    assert (tmp_path / "o" / "report.md").read_text(encoding="utf-8").startswith("# 抽取准确率评测")
    rc = main(["--variants", "1", "--work", str(tmp_path / "w"), "--out", str(tmp_path / "o2"),
               "--replay", str(tmp_path / "none")])
    assert rc == 2  # 没有真实录制


# ------------------------------------------------------------------ 等价规则（ADR-0038）


def test_equivalence_rules():
    from ingest.evaluate import _equivalent
    from ingest.llm_extract import Target

    sol = Target("params/safety_functions", "string_or_list", None, None, "", False)
    assert _equivalent(sol, ["STO"], "STO") and _equivalent(sol, "canopen", ["canopen"])
    assert _equivalent(sol, ["STO", "SS1"], ["SS1", "STO"])
    assert not _equivalent(sol, ["STO", "SS1"], "STO")
    free = Target("ports/bus/profile", "string", None, None, "", False)
    assert _equivalent(free, "cia402", "CiA 402") and not _equivalent(free, "cia402", "cia401")
    enum = Target("ports/bus/protocol", "string_or_list", None, ("ethercat", "canopen"), "", False)
    assert not _equivalent(enum, "ethercat", "EtherCAT")  # 有枚举时须与枚举值完全相同
    num = Target("params/mass_kg", "number", "kg", None, "", True)
    assert _equivalent(num, 1.0, 1.0005) and not _equivalent(num, 1.0, 1.01)  # 数值规则不变


def test_implicit_targets_not_scored_unless_wrong():
    from ingest.evaluate import expected_targets, score

    sheet = next(s for s in datasheets(0) if s.answer["category"] == "bearing")
    answer = sheet.answer
    implicit = next(t for t in answer["implicit"] if t.endswith("fit_system"))
    base = [{"target": t, "value": {"value": e["expected"]["value"]} if "value" in e["expected"] else e["expected"]}
            for t, e in expected_targets(answer).items()]
    ok = score(answer, {"items": [*base, {"target": implicit, "value": {"value": "bearing"}}]})
    assert ok[implicit]["outcome"] == "implicit"
    bad = score(answer, {"items": [*base, {"target": implicit, "value": {"value": "iso286"}}]})
    assert bad[implicit]["outcome"] == "extra"
