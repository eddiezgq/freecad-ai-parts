"""AI 设计关节空心轴的流程（ADR-0100 42.5 第 5 步）：模拟 AI；条件核对、载荷（动力学）、校核与“再要最轻”由代码做。"""

from __future__ import annotations

import pytest

pytest.importorskip("mujoco")

from assist import joint_design as JD
from tests.test_shaft_joint import B6009, B6010, fake_kt

TEXT = JD.EXAMPLE.read_text(encoding="utf-8")
RED = {"id": "reducer.test.csf-25-100-2uh", "category": "reducer", "model": "CSF-25-100-2UH",
       "params": {"momentary_max_torque_nm": {"value": 284}}}
LIB = {c["id"]: c for c in (B6009, B6010, RED)}


def v(value, unit, quote):
    return {"value": value, "unit": unit, "quote": quote}


CONDS = {
    "reducer_model": {"model": "CSF-25-100-2UH", "quote": "谐波减速器 CSF-25-100-2UH"},
    "links": [{"length": v(425, "mm", "大臂长 425 mm"), "mass": v(8.393, "kg", "质量 8.393 kg")},
              {"length": v(392.25, "mm", "小臂长 392.25 mm"), "mass": v(2.275, "kg", "质量 2.275 kg")}],
    "tip_masses": [{"name": "负载", "mass": v(4, "kg", "末端负载 4 kg")}, {"name": "腕部模组", "mass": v(2.626, "kg", "共 2.626 kg")}],
    "pose_a": {"j2": v(20, "°", "j2 = 20°"), "j3": v(-34, "°", "j3 = -34°")},
    "pose_b": {"j2": v(54, "°", "j2 = 54°"), "j3": v(-75, "°", "j3 = -75°")},
    "move_time": v(1.0, "s", "用 1.0 s"), "dwell_time": v(0.5, "s", "停 0.5 s"),
    "reach": v(850, "mm", "工作半径 850 mm"), "displacement_budget": v(0.20, "mm", "不超过 0.20 mm"),
    "material": {"id": "40Cr-QT", "quote": "材料 40Cr 调质"}, "surface": {"finish": "machined", "quote": "轴颈车削"},
    "required_safety": v(1.5, "", "不小于 1.5"), "bearing_life": v(20000, "h", "不少于 20000 h"),
}


class Script:
    def __init__(self, proposals, conds=CONDS):
        self.conds, self.props, self.requests = conds, list(proposals), []

    def complete(self, req):
        self.requests.append(req)
        if req["tool"]["name"] == "list_conditions":
            return {"tool_input": self.conds, "simulated": True}
        return {"tool_input": self.props.pop(0), "simulated": True}


def P(bearing, bore, r=1.0, why="按条件选"):
    return {"bearing": bearing, "bore_mm": bore, "fillet_mm": r, "reason": why}


def test_conditions_checked_and_loads_from_dynamics():
    c, rej, missing = JD.check_conditions(CONDS, TEXT, LIB.get, [RED])
    assert not rej and not missing
    assert c["arm"]["payload_kg"] == pytest.approx(6.626) and c["T_stop_nm"] == 284 and c["budget_mm"] == 0.20
    k = JD.loads(c)
    assert 30 < k["T_peak_nm"] < 300 and k["F_peak_n"] > 9.81 * (8.393 + 2.275 + 6.626) * 0.9


def test_invented_numbers_rejected():
    bad = dict(CONDS, reach=v(900, "mm", "工作半径 900 mm"))
    _, rej, _ = JD.check_conditions(bad, TEXT, LIB.get, [RED])
    assert any("工作半径" in x for x in rej)


def test_fail_then_pass_then_lighter_round():
    ai = Script([P("bearing.test.6009", 30), P("bearing.test.6010", 30), P("bearing.test.6010", 32, why="减重：内孔加大"),
                 P("bearing.test.6010", 32, why="已经最轻")])
    out = JD.design(TEXT, ai, [B6009, B6010], [RED], LIB.get, kt=fake_kt)
    assert out["status"] == "pass"
    ov = [r["overall"] for r in out["rounds"]]
    assert ov == ["fail", "pass", "pass", "pass"] and out["rounds"][2]["lighter_round"]
    assert out["chosen_round"] == 3                                               # 第 4 轮没更轻：采用第 3 轮
    assert "越轻越好" in ai.requests[3]["user"]                                    # 通过后交回 AI 要更轻
    chosen = out["rounds"][out["chosen_round"] - 1]
    assert chosen["overall"] == "pass" and all(r["mass_kg"] >= chosen["mass_kg"] - 1e-9 for r in out["rounds"] if r["overall"] == "pass")


def test_lighter_attempts_that_fail_use_up_three_rounds_and_keep_previous():
    ai = Script([P("bearing.test.6010", 30), P("bearing.test.6009", 34, why="减重"), P("bearing.test.6009", 35, why="再试"),
                 P("bearing.test.6009", 36, why="再试")])
    out = JD.design(TEXT, ai, [B6009, B6010], [RED], LIB.get, kt=fake_kt)
    if out["rounds"][0]["overall"] != "pass":
        pytest.skip("这组示意载荷下 6010/30 本身没通过刚度")
    assert [r["overall"] for r in out["rounds"]] == ["pass", "fail", "fail", "fail"]      # 减重最多 3 轮，没通过的可以再改
    assert out["status"] == "pass" and out["chosen_round"] == 1 and not ai.props       # 3 轮用完停下，采用通过的第 1 轮


def test_failed_lighter_attempt_can_be_fixed_within_three_rounds():
    ai = Script([P("bearing.test.6010", 30), P("bearing.test.6009", 34, why="减重"), P("bearing.test.6010", 32, why="改回 6010、内孔加大"),
                 P("bearing.test.6010", 32, why="已经最轻")])
    out = JD.design(TEXT, ai, [B6009, B6010], [RED], LIB.get, kt=fake_kt)
    if out["rounds"][0]["overall"] != "pass":
        pytest.skip("这组示意载荷下 6010/30 本身没通过刚度")
    assert [r["overall"] for r in out["rounds"]][:3] == ["pass", "fail", "pass"]
    assert out["chosen_round"] == 3 and out["rounds"][-1].get("unchanged")          # 原样交回：停


def test_missing_conditions_stop_before_design():
    c = dict(CONDS)
    c.pop("pose_b")
    out = JD.design(TEXT, Script([], conds=c), [B6010], [RED], LIB.get, kt=fake_kt)
    assert out["status"] == "needs_input" and not out["rounds"]
