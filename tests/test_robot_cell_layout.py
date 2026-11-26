"""案例 B2 的取放布置（ADR-0115 44.5.6.1，assist/robot_cell.py）：取料区四角、侧偏、放料转向、节拍按最远的角。
不联网、不调用真实 AI。

参考值（手算）：取料区中心 (0, 0, 850)、长边沿 x，四角 (±600, ±400, 850)；放料点 (1500, 500, 850)：
沿长边分量 1500、侧偏 500；离放料点最远的角是 (−600, −400)（距离 √(2100² + 900²) ≈ 2284.7 mm）。
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from assist import robot_cell as RC
from assist import robot_design as RD

ROOT = Path(__file__).resolve().parents[1]
STATEMENT = (ROOT / "examples" / "robots" / "sewing-loader-xyz" / "requirement.txt").read_text(encoding="utf-8")
CASE_B = (ROOT / "examples" / "robots" / "sewing-loader" / "requirement.txt").read_text(encoding="utf-8")
CASE_A = (ROOT / "examples" / "robots" / "teaching-arm" / "requirement.txt").read_text(encoding="utf-8")


def _v(value, unit, quote):
    return {"value": value, "unit": unit, "quote": quote}


COND = {"kind": "other", "kind_quote": "裁片上下料机器人", "repeatability": _v(1, "mm", "放料定位精度 ±1 mm"),
        "for_people": [{"quote": "不能损伤布料"}, {"quote": "机器人不能占用车间通道"}]}
CELL = {"cycle": _v(3, "s", "节拍 3 s/片"), "part_mass": _v(100, "g", "单片质量不超过 100 g"),
        "part_length": _v(600, "mm", "最大 600 mm × 400 mm"), "part_width": _v(400, "mm", "600 mm × 400 mm"),
        "stack_height": _v(100, "mm", "每叠最高 100 mm"), "work_height": _v(850, "mm", "离地 850 mm"),
        "pick_to_place": _v(1500, "mm", "取料区中心到放料点水平距离 1500 mm"), "same_height": {"quote": "裁床台面和送料台面同高"}}
LAYOUT = {"area_length": _v(1200, "mm", "1200 mm × 800 mm 的取料区"), "area_width": _v(800, "mm", "1200 mm × 800 mm 的取料区"),
          "lateral_offset": _v(500, "mm", "比取料区中心偏 500 mm"), "max_rotation": _v(90, "°", "最多转 90°")}
FAR = [-600, -400, 850]
PLACE = [1500, 500, 850]


def concept(**over):
    """X–Y–Z 龙门加末端绕竖直轴的转动；基座原点在地面，横梁高 1300 mm"""
    def mv(name, a, b, t, dwell=0.0):
        return {"type": "cartesian_move", "name": name, "from_mm": a, "to_mm": b, "move_s": t, "dwell_s": dwell}

    up_far, up_place = [*FAR[:2], 1000], [*PLACE[:2], 1000]
    c = {"format": "robot-concept/1", "name": "三轴龙门加旋转", "kind": "gantry", "base": {"mount": "floor", "height_mm": 1300},
         "links": [{"id": "carriage", "length_mm": 200, "shape": "box", "section": {"width_mm": 80, "height_mm": 80}},
                   {"id": "slide", "length_mm": 300, "shape": "box", "section": {"width_mm": 60, "height_mm": 60}},
                   {"id": "mast", "length_mm": 500, "shape": "tube", "section": {"od_mm": 40}},
                   {"id": "wrist", "length_mm": 50, "shape": "tube", "section": {"od_mm": 40}}],
         "joints": [{"id": "jx", "type": "prismatic", "parent": "base", "child": "carriage", "origin_mm": [0, 0, 1300],
                     "axis": [1, 0, 0], "range_mm": [-700, 1600], "transmission": "belt_linear", "lead_mm": 100},
                    {"id": "jy", "type": "prismatic", "parent": "carriage", "child": "slide", "origin_mm": [0, 0, 0],
                     "axis": [0, 1, 0], "range_mm": [-450, 550], "transmission": "belt_linear", "lead_mm": 100},
                    {"id": "jz", "type": "prismatic", "parent": "slide", "child": "mast", "origin_mm": [0, 0, 0],
                     "axis": [0, 0, 1], "range_mm": [-460, 0], "transmission": "ballscrew", "lead_mm": 20},
                    {"id": "jc", "type": "revolute", "parent": "mast", "child": "wrist", "origin_mm": [0, 0, 0],
                     "axis": [0, 0, 1], "range_deg": [-90, 90]}],
         "end_effector": {"type": "vacuum", "parent": "wrist", "offset_mm": [0, 0, 0]},
         "workspace": {"points_mm": [[0, 0, 850], PLACE, [-600, -400, 850], [600, -400, 850], [600, 400, 850], [-600, 400, 850]]},
         "tasks": [mv("抬起", FAR, up_far, 0.2, 0.1), mv("平移并转向", up_far, up_place, 0.9), mv("放下", up_place, PLACE, 0.2, 0.1),
                   mv("抬起", PLACE, up_place, 0.2), mv("回最远一叠", up_place, up_far, 0.9), mv("落到取料位", up_far, FAR, 0.2)]}
    c.update(over)
    return c


def _cond():
    cond, rej, miss, _ = RD.check_conditions(COND, STATEMENT)
    assert not rej and not miss
    for f in (RC.check_cell(CELL, STATEMENT), RC.check_layout(LAYOUT, STATEMENT)):
        c2, rej, miss, _ = f
        assert not rej and not miss, rej
        cond.update(c2)
    return cond


def _st(ev):
    return {i["item"]: i for i in ev["items"]}


def test_layout_is_asked_only_when_the_statement_mentions_it():
    assert RC.needs_layout(STATEMENT)
    assert not RC.needs_layout(CASE_B) and not RC.needs_layout(CASE_A)       # 案例 A、B 的请求不变（录制按请求哈希回放）


def test_layout_conditions_are_checked_against_the_statement():
    cond = _cond()
    assert (cond["area_length"], cond["area_width"], cond["lateral_offset"], cond["max_rotation"]) == (1200, 800, 500, 90)
    _, rej, _, _ = RC.check_layout(dict(LAYOUT, max_rotation=_v(180, "°", "最多转 90°")), STATEMENT)
    assert any("最大转角" in r for r in rej)                                  # 编造的数不收
    _, _, miss, _ = RC.check_layout({k: v for k, v in LAYOUT.items() if k != "area_width"}, STATEMENT)
    assert miss == ["取料区宽"]
    _, rej, _, _ = RC.check_layout(dict(LAYOUT, area_length=_v(800, "mm", "1200 mm × 800 mm 的取料区"),
                                        area_width=_v(1200, "mm", "1200 mm × 800 mm 的取料区")), STATEMENT)
    assert any("宽比长大" in r for r in rej)


def test_a_three_axis_gantry_with_a_wrist_passes_screening():
    ev = RD.evaluate(concept(), _cond())
    st = _st(ev)
    for k in ("取料区四角", "取放距离（沿取料区长边）", "放料点侧偏（垂直于长边）", "取放两处同高", "节拍", "放料转向"):
        assert st[k]["status"] == "pass", (k, st[k])
    assert st["取放距离（沿取料区长边）"]["value"] == pytest.approx(1500) and st["放料点侧偏（垂直于长边）"]["value"] == pytest.approx(500)
    assert st["节拍"]["value"] == pytest.approx(0.2 + 0.1 + 0.9 + 0.2 + 0.1 + 0.2 + 0.9 + 0.2)
    assert any(k.startswith("角 1 上方一叠最高处") for k in st) and any(k.startswith("取料区角 4") for k in st)
    assert ev["overall"] != "fail", [i for i in ev["items"] if i["status"] == "fail"]
    assert RC.farthest_corner(concept(), _cond()) == FAR


def test_layout_mistakes_fail():
    cond = _cond()
    pts = concept()["workspace"]["points_mm"]
    assert _st(RD.evaluate(concept(workspace={"points_mm": pts[:2]}), cond))["取料区四角"]["status"] == "fail"
    moved = [pts[0], [1500, 300, 850], *pts[2:]]                                        # 侧偏 300 不是 500
    st = _st(RD.evaluate(concept(workspace={"points_mm": moved}), cond))
    assert st["放料点侧偏（垂直于长边）"]["status"] == "fail" and st["放料点侧偏（垂直于长边）"]["value"] == pytest.approx(300)
    small = [pts[0], pts[1], [-500, -400, 850], [500, -400, 850], [500, 400, 850], [-500, 400, 850]]   # 1000 × 800
    assert _st(RD.evaluate(concept(workspace={"points_mm": small}), cond))["取料区四角"]["status"] == "fail"
    c = concept()
    c["joints"][3]["range_deg"] = [-45, 30]
    assert _st(RD.evaluate(c, cond))["放料转向"]["status"] == "fail"
    c["joints"][3]["axis"] = [1, 0, 0]
    assert "没有轴线竖直" in _st(RD.evaluate(c, cond))["放料转向"]["note"]


def test_the_cycle_must_start_from_the_farthest_pile():
    c = concept()
    near = [-600, 400, 850]                                                             # 不是最远的角
    for t in c["tasks"]:
        for k in ("from_mm", "to_mm"):
            if t[k][:2] == FAR[:2]:
                t[k] = [near[0], near[1], t[k][2]]
    st = _st(RD.evaluate(c, _cond()))
    assert st["节拍"]["status"] == "fail" and "离放料点最远的取料区角" in st["节拍"]["note"]


def test_design_loop_asks_layout_then_screens():
    class _Script:
        def __init__(self, *answers):
            self.q, self.requests = list(answers), []

        def complete(self, req):
            self.requests.append(req)
            return {"tool_input": copy.deepcopy(self.q.pop(0)), "provider": "test", "model": req["model"]}

    c = _Script(COND, CELL, LAYOUT, {"candidates": [concept()], "recommend": 0, "reason": "三轴够到取料区各角，末端转向"})
    r = RD.design(STATEMENT, c)
    assert r["status"] == "pass", (r.get("rejected"), r.get("missing"))
    assert [q["tool"]["name"] for q in c.requests] == ["list_conditions", "list_cell_conditions", "list_cell_layout", "propose_robots"]
    user = c.requests[3]["user"]
    assert "取放布置的写法" in user and "取料区长 mm（沿长边）：1200" in user and "最多 90°" in user
    assert "取放布置的写法" not in RC.notes({k: v for k, v in r["conditions"].items() if k not in dict.fromkeys(x[0] for x in RC.LAYOUT_FIELDS)})
