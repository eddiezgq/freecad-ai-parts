"""取放类需求的条件与初筛（ADR-0115 44.5.1，assist/robot_cell.py）。不联网、不调用真实 AI。"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from assist import robot_cell as RC
from assist import robot_design as RD

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = (ROOT / "examples" / "robots" / "sewing-loader" / "requirement.txt").read_text(encoding="utf-8")


def _v(value, unit, quote):
    return {"value": value, "unit": unit, "quote": quote}


CELL = {"cycle": _v(3, "s", "节拍 3 s/片"), "part_mass": _v(100, "g", "单片质量不超过 100 g"),
        "part_length": _v(600, "mm", "最大 600 mm × 400 mm"), "part_width": _v(400, "mm", "600 mm × 400 mm"),
        "stack_height": _v(100, "mm", "一叠最高 100 mm"), "work_height": _v(850, "mm", "离地 850 mm"),
        "pick_to_place": _v(1500, "mm", "水平距离 1500 mm"), "same_height": {"quote": "裁床台面和送料台面同高"}}
COND = {"kind": "other", "kind_quote": "裁片上下料机器人", "repeatability": _v(1, "mm", "放料定位精度 ±1 mm"),
        "for_people": [{"quote": "不能损伤布料"}, {"quote": "机器人不能占用车间通道"}]}


def gantry(**over):
    """一台龙门：x 沿横梁、y 横向、z 上下；基座原点在地面，横梁高 1300 mm"""
    c = {"format": "robot-concept/1", "name": "悬挂龙门", "kind": "gantry", "base": {"mount": "floor", "height_mm": 1300},
         "links": [{"id": "carriage", "length_mm": 200, "shape": "box", "section": {"width_mm": 80, "height_mm": 80}},
                   {"id": "slide", "length_mm": 300, "shape": "box", "section": {"width_mm": 60, "height_mm": 60}},
                   {"id": "mast", "length_mm": 500, "shape": "tube", "section": {"od_mm": 40}}],
         "joints": [{"id": "jx", "type": "prismatic", "parent": "base", "child": "carriage", "origin_mm": [0, 0, 1300],
                     "axis": [1, 0, 0], "range_mm": [-100, 1600], "transmission": "belt_linear", "lead_mm": 100},
                    {"id": "jy", "type": "prismatic", "parent": "carriage", "child": "slide", "origin_mm": [0, 0, 0],
                     "axis": [0, 1, 0], "range_mm": [-250, 250], "transmission": "belt_linear", "lead_mm": 100},
                    {"id": "jz", "type": "prismatic", "parent": "slide", "child": "mast", "origin_mm": [0, 0, 0],
                     "axis": [0, 0, 1], "range_mm": [-460, 0], "transmission": "ballscrew", "lead_mm": 20}],
         "end_effector": {"type": "needle", "parent": "mast", "offset_mm": [0, 0, 0]},
         "workspace": {"points_mm": [[0, 0, 850], [1500, 0, 850]]},
         "tasks": [{"type": "cartesian_move", "name": "抬起", "from_mm": [0, 0, 850], "to_mm": [0, 0, 1000], "move_s": 0.3, "dwell_s": 0.2},
                   {"type": "cartesian_move", "name": "平移", "from_mm": [0, 0, 1000], "to_mm": [1500, 0, 1000], "move_s": 0.9},
                   {"type": "cartesian_move", "name": "放下", "from_mm": [1500, 0, 1000], "to_mm": [1500, 0, 850], "move_s": 0.3,
                    "dwell_s": 0.2},
                   {"type": "cartesian_move", "name": "回取料位", "from_mm": [1500, 0, 850], "to_mm": [0, 0, 850], "move_s": 0.9}]}
    c.update(over)
    return c


def _cond():
    cond, rej, miss, _ = RD.check_conditions(COND, STATEMENT)
    assert not rej and not miss
    c2, rej, miss, _ = RC.check_cell(CELL, STATEMENT)
    assert not rej and not miss, rej
    cond.update(c2)
    return cond


def test_cell_conditions_are_checked_against_the_statement():
    cond = _cond()
    assert cond["cycle"] == 3 and cond["part_mass"] == pytest.approx(0.1) and cond["pick_to_place"] == 1500
    assert cond["same_height"] and cond["stack_height"] == 100 and cond["work_height"] == 850
    bad = dict(CELL, cycle=_v(2.5, "s", "节拍 3 s/片"))
    _, rej, _, _ = RC.check_cell(bad, STATEMENT)
    assert any("节拍" in r for r in rej)                                  # 编造的数不收
    _, _, miss, _ = RC.check_cell({k: v for k, v in CELL.items() if k != "pick_to_place"}, STATEMENT)
    assert miss == ["取料区到放料区的水平距离"]


def test_only_non_arm_requirements_ask_for_cell_conditions():
    assert RC.applies({"kind": "other"}) and RC.applies({"kind": "gantry"})
    assert not RC.applies({"kind": "serial_arm"}) and not RC.applies({"kind": "mobile_base"}) and not RC.applies({})


def test_a_gantry_that_meets_the_cycle_passes_screening():
    ev = RD.evaluate(gantry(), _cond())
    st = {i["item"].split("（")[0].split(" ")[0]: i["status"] for i in ev["items"]}
    assert st["取放水平距离"] == st["取放两处同高"] == st["节拍"] == "pass", ev["items"]
    assert st["取料点"] == st["放料点"] == st["一叠最高处"] == "pass"
    assert st["取料点高度"] == "pass"
    assert RD._passes(ev), ev["items"]
    cyc = next(i for i in ev["items"] if i["item"] == "节拍")
    assert cyc["value"] == pytest.approx(2.8)
    speed = next(i for i in ev["items"] if i["item"].startswith("节拍里末端"))
    assert speed["status"] == "unknown" and "选件后" in speed["note"] and speed["value"].startswith("2.22 m/s")


def test_too_slow_or_open_loop_or_wrong_distance_fails():
    cond = _cond()
    slow = gantry()
    slow["tasks"][1]["move_s"] = 1.2
    assert not RD._passes(RD.evaluate(slow, cond))
    openl = gantry()
    openl["tasks"] = openl["tasks"][:3]
    ev = RD.evaluate(openl, cond)
    assert any(i["item"] == "节拍" and "首尾相连" in i["note"] for i in ev["items"])
    near = gantry(workspace={"points_mm": [[0, 0, 850], [1400, 0, 850]]})
    ev = RD.evaluate(near, cond)
    assert next(i for i in ev["items"] if i["item"] == "取放水平距离")["status"] == "fail"
    low = gantry(workspace={"points_mm": [[0, 0, 800], [1500, 0, 800]]})
    assert next(i for i in RD.evaluate(low, cond)["items"] if i["item"].startswith("取料点高度"))["status"] == "fail"


def test_stack_top_out_of_stroke_fails():
    c = gantry()
    c["joints"][2]["range_mm"] = [-460, -400]                 # 抬不到一叠最高处
    ev = RD.evaluate(c, _cond())
    assert next(i for i in ev["items"] if i["item"].startswith("一叠最高处"))["status"] == "fail"


def test_gripping_force_lower_bound_uses_the_cycle_acceleration():
    ev = RD.evaluate(gantry(), _cond())
    f = next(i for i in ev["items"] if i["item"] == "抓取力")
    _, a = RC.trapezoid(1500, 0.9)
    assert f["status"] == "unknown" and f["value"] == f"至少 {0.1 * (RC.G + a) * 2:.2f} N"


class _Script:
    def __init__(self, *tool_inputs):
        self.q = list(tool_inputs)
        self.requests = []

    def complete(self, req):
        self.requests.append(req)
        return {"tool_input": copy.deepcopy(self.q.pop(0)), "provider": "test", "model": req["model"]}


def test_design_loop_asks_cell_conditions_then_screens():
    c = _Script(COND, CELL, {"candidates": [gantry()], "recommend": 0, "reason": "龙门跨在裁床和送料台上方，不占通道"})
    r = RD.design(STATEMENT, c)
    assert r["status"] == "pass" and r["conditions"]["cycle"] == 3, r.get("rejected")
    assert [q["prompt_version"] for q in c.requests] == [RD.PROMPT_VERSION, RC.PROMPT_VERSION, RD.PROMPT_VERSION]
    user = c.requests[2]["user"]
    assert "节拍 s：3" in user and "取放的写法" in user and "一体化关节模组的装配要点" not in user


def test_arm_requests_are_unchanged():
    """案例 A 的请求一个字不改（录制按请求哈希回放）：串联臂不问取放条件，提议里仍是关节模组的装配要点"""
    from ingest.llm_extract import request_key

    cond = {"kind": "serial_arm", "dof": 5.0, "payload": 0.5, "reach": 350.0}
    req = RD.proposal_request(cond, [])
    assert "取放的写法" not in req["user"] and "一体化关节模组" in req["user"]
    keys = {p.stem for p in RD.RECORDINGS_DIR.glob("*.json")}
    statement = (ROOT / "examples" / "robots" / "teaching-arm" / "requirement.txt").read_text(encoding="utf-8")
    assert request_key(RD.conditions_request(statement)) in keys


def test_a_converted_payload_in_the_first_list_does_not_block_a_pick_and_place_design():
    """CI 上真实 AI 第一次把“100 g”写成负载 0.1 kg（换算过的数不收）：取放类的负载改由取放条件按原话单位列，不挡设计"""
    first = dict(COND, payload=_v(0.1, "kg", "裁片单片质量不超过 100 g"))
    c = _Script(first, CELL, {"candidates": [gantry()], "recommend": 0, "reason": "x"})
    r = RD.design(STATEMENT, c)
    assert r["status"] == "pass" and "payload" not in r["conditions"] and r["conditions"]["part_mass"] == pytest.approx(0.1)
