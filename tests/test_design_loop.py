"""AI 自主设计阶梯轴的流程（ADR-0100 42.2）：模拟 AI（按脚本给条件与方案），条件核对与校核由代码做。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from assist import design as D
from tests.test_shaft_design import B6201, LS101, fake_kt, get

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "examples" / "ai-design" / "ls-upper-shaft" / "requirement.txt").read_text(encoding="utf-8")


def v(value, unit, quote):
    return {"value": value, "unit": unit, "quote": quote}


CONDS = {
    "speeds": [v(5000, "r/min", "最高转速 5000 r/min"), v(5500, "r/min", "提速到 5500 r/min")],
    "bearing_centers": [v(27, "mm", "z = 27 mm"), v(252, "mm", "z = 252 mm")],
    "crank_slider": {"z": v(11, "mm", "针杆曲柄装在 z = 11 mm"), "crank_radius": v(15.5, "mm", "曲柄半径 15.5 mm"),
                     "rod_length": v(55, "mm", "连杆长 55 mm"), "reciprocating_mass": v(0.12, "kg", "往复质量 0.12 kg"),
                     "balance_ratio": v(0.45, "", "平衡率 0.45")},
    "process_power": {"power": v(150, "W", "平均功率 150 W"), "z": v(11, "mm", "作用在 z = 11 mm")},
    "forces": [{"z": v(262, "mm", "同步带轮在 z = 262 mm"), "magnitude": v(120, "N", "张力之和 120 N"), "direction": "-y",
                "direction_quote": "方向铅垂向下"}],
    "drive_z": v(282, "mm", "轴端 z = 282 mm"),
    "masses": [{"name": "曲柄与平衡块", "z": v(11, "mm", "（z = 11 mm）"), "mass": v(0.15, "kg", "曲柄与平衡块 0.15 kg")},
               {"name": "挑线凸轮", "z": v(45, "mm", "（z = 45 mm）"), "mass": v(0.05, "kg", "挑线凸轮 0.05 kg")},
               {"name": "送布偏心轮", "z": v(150, "mm", "（z = 150 mm）"), "mass": v(0.08, "kg", "送布偏心轮 0.08 kg")},
               {"name": "同步带轮", "z": v(262, "mm", "（z = 262 mm）"), "mass": v(0.06, "kg", "同步带轮 0.06 kg")},
               {"name": "手轮与电机转子", "z": v(282, "mm", "（z = 282 mm）"), "mass": v(0.45, "kg", "手轮与电机转子 0.45 kg")}],
    "material": {"id": "45-QT", "quote": "材料 45 钢调质"}, "surface": {"finish": "ground", "quote": "轴颈磨削"},
    "required_safety": v(1.5, "", "安全系数不小于 1.5"), "critical_ratio": v(1.3, "", "最高转速的 1.3 倍"),
    "bearing_life": v(20000, "h", "轴承寿命不少于 20000 h"), "max_length": v(300, "mm", "总长不超过 300 mm"),
}
FIRST = copy.deepcopy(LS101)
FIRST["segments"][2]["length_mm"] = 205                      # 第一轮：轴身短了 10 mm，后轴承中心落在 242
FIRST["reason"] = "按条件排"
SECOND = dict(copy.deepcopy(LS101), reason="后轴承中心差 10 mm，轴身加长到 215")


class Script:
    def __init__(self, conds=CONDS, proposals=(FIRST, SECOND)):
        self.conds, self.props, self.requests = conds, list(proposals), []

    def complete(self, request):
        self.requests.append(request)
        if request["tool"]["name"] == "list_conditions":
            return {"id": "sim", "tool_input": copy.deepcopy(self.conds), "simulated": True}
        return {"id": "sim", "tool_input": copy.deepcopy(self.props.pop(0)), "simulated": True}


def test_conditions_checked_against_statement():
    c, rej, missing = D.check_conditions(copy.deepcopy(CONDS), TEXT)
    assert not rej and not missing
    assert c["speeds_rpm"] == [5000, 5500] and c["bearing_centers_mm"] == [27, 252]
    assert {"type": "force", "z_mm": 262, "fx_n": 0.0, "fy_n": -120} in c["loads"]
    assert c["material"] == "45-QT" and c["surface"] == "ground" and c["bearing_life_h"] == 20000
    assert len(c["masses"]) == 5 and c["max_length_mm"] == 300


@pytest.mark.parametrize("path,bad,msg", [
    (("speeds", 0), v(6000, "r/min", "最高转速 6000 r/min"), "不在原话"),
    (("bearing_centers", 1), v(250, "mm", "z = 252 mm"), "不在引用"),
    (("material",), {"id": "40Cr-QT", "quote": "材料 45 钢调质"}, "没有这个材料"),
])
def test_invented_conditions_rejected(path, bad, msg):
    c = copy.deepcopy(CONDS)
    tgt = c
    for k in path[:-1]:
        tgt = tgt[k]
    tgt[path[-1]] = bad
    _, rej, _ = D.check_conditions(c, TEXT)
    assert any(msg in r for r in rej)


def test_direction_needs_words():
    c = copy.deepcopy(CONDS)
    c["forces"][0]["direction"] = "+y"
    _, rej, _ = D.check_conditions(c, TEXT)
    assert any("方向" in r for r in rej)


def test_loop_fixes_with_feedback():
    ai = Script()
    out = D.design(TEXT, ai, [get(B6201)], get, kt=fake_kt)
    assert len(out["rounds"]) == 2 and out["rounds"][0]["overall"] == "fail"
    assert "轴承中心 z = 252" in out["rounds"][0]["feedback"]
    assert "第 1 轮你的方案" in ai.requests[2]["user"] and "轴承中心 z = 252" in ai.requests[2]["user"]   # 结论交回 AI
    assert out["status"] == "pass"                                    # 轴肩按 NSK 6201 的安装尺寸也合规
    segs = out["rounds"][-1]["segments"]
    assert [(s["d"], s["L"]) for s in segs] == [(10, 22), (12, 10), (16, 215), (12, 10), (10, 40)]
    assert "6201" in ai.requests[1]["user"]                            # 给 AI 的轴承表来自零件库


def test_stops_after_max_rounds():
    out = D.design(TEXT, Script(proposals=[FIRST] * 4), [get(B6201)], get, kt=fake_kt)
    assert out["status"] == "stuck" and len(out["rounds"]) == D.MAX_ROUNDS


def test_missing_conditions_ask_first():
    c = copy.deepcopy(CONDS)
    del c["material"]
    out = D.design(TEXT, Script(conds=c), [get(B6201)], get, kt=fake_kt)
    assert out["status"] == "needs_input" and any("材料" in q for q in out["missing"]) and not out["rounds"]


def test_ai_questions_do_not_block():
    c = copy.deepcopy(CONDS)
    c["questions"] = ["挑线凸轮的工作载荷没有给出，是否忽略？"]
    out = D.design(TEXT, Script(conds=c), [get(B6201)], get, kt=fake_kt)
    assert out["status"] == "pass" and out["questions"] == c["questions"] and out["assumptions"]


def test_recorded_real_model_run_passes(tmp_path):
    """回放 design-eval 用真实模型（Claude）的录制：条件 → 方案 → 有限元算应力集中 → 校核，几轮后全部通过。
    要本机有 gmsh 与 CalculiX；CI 中必须跑。"""
    import os

    from analysis.common.solvers import find_ccx
    from ingest.llm_extract import RecordedClient
    from kb.library import JsonLibrary

    if os.environ.get("CI"):
        import gmsh  # noqa: F401
        assert find_ccx(), "CI 中没有 ccx"
    else:
        pytest.importorskip("gmsh")
        if find_ccx() is None:
            pytest.skip("本机没有 CalculiX")
    lib = JsonLibrary(ROOT / "data" / "library")
    bearings = [c for c in lib.all() if c["category"] == "bearing"]
    res = D.design(TEXT, RecordedClient(D.RECORDINGS_DIR), bearings, lib.get)
    assert res["status"] == "pass" and not res["missing"]
    assert all(a.get("simulated") is False for a in res["ai"])
    last = res["rounds"][-1]
    assert last["overall"] == "pass" and all(i["status"] == "pass" for i in last["items"])
    seats = [s for s in last["proposal"]["segments"] if s.get("bearing")]
    assert seats and all(s["bearing"].startswith("bearing.nsk-ltd.") for s in seats)
    # 42.3：生成模型、回读逐段一致，出二维图与 BOM
    from assist import shaft_model

    g = shaft_model.generate(res, tmp_path, lib.get)
    assert g["readback"] == "pass" and g["delivered"], g["problems"]
    assert (tmp_path / "shaft.step").is_file() and (tmp_path / "drawing.svg").is_file()
    assert [r["kind"] for r in g["bom"]] == ["custom_part", "bearing"] and g["bom"][1]["qty"] == 2


def test_progress_reported_each_step():
    """界面要知道做到哪一步：列条件、每一轮提方案、每个台阶的有限元（已做 / 总数）"""
    seen = []
    out = D.design(TEXT, Script(), [get(B6201)], get, kt=fake_kt, progress=lambda t, d, n: seen.append((t, d, n)))
    assert out["status"] == "pass"
    assert seen[0] == ("AI 列设计条件", None, None)
    assert any(t.startswith("第 1 轮") and n is None for t, d, n in seen)
    steps = [(d, n) for t, d, n in seen if n]
    assert steps and steps[0][0] == 0 and all(0 <= d < n for d, n in steps)
