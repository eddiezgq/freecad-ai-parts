"""AI 提整机构型、代码初筛的循环（assist/robot_design.py，ADR-0115 44.2）。AI 用脚本模拟，不调用真实模型。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from assist import robot_design as RD

TEXT = (Path(__file__).parents[1] / "examples" / "robots" / "teaching-arm" / "requirement.txt").read_text(encoding="utf-8")
FIX = Path(__file__).parent / "fixtures" / "robot-concept" / "valid"
CONDS = {"kind": "serial_arm", "kind_quote": "教学用桌面机械臂",
         "dof": {"value": 5, "quote": "5 轴"}, "payload": {"value": 0.5, "unit": "kg", "quote": "末端负载 0.5 kg"},
         "reach": {"value": 350, "unit": "mm", "quote": "臂展 350 mm"},
         "repeatability": {"value": 0.5, "unit": "mm", "quote": "末端重复定位精度 ±0.5 mm"},
         "mount": {"where": "桌面", "quote": "装在桌面上"}, "module_reuse": {"quote": "同一种关节模组重复使用"},
         "for_people": [{"quote": "全部自制件能在普通数控车床、铣床上加工"}, {"quote": "外购件成本尽量低"}],
         "questions": ["臂展是否包含夹爪？"]}


def arm(reach_scale=1.0, groups=True):
    c = copy.deepcopy(json.loads((FIX / "serial_arm_5axis.json").read_text(encoding="utf-8"))["instance"])
    c.pop("workspace", None)
    c.pop("tasks", None)
    for j in c["joints"]:
        j["origin_mm"] = [x * reach_scale for x in j["origin_mm"]]
        if not groups:
            j.pop("module_group", None)
    return c


class Script:
    def __init__(self, rounds, conds=CONDS):
        self.conds, self.rounds, self.requests = conds, list(rounds), []

    def complete(self, request):
        self.requests.append(request)
        if request["tool"]["name"] == "list_conditions":
            return {"id": "sim", "tool_input": copy.deepcopy(self.conds), "simulated": True}
        return {"id": "sim", "tool_input": copy.deepcopy(self.rounds.pop(0)), "simulated": True}


def test_conditions_checked_against_statement():
    c, rej, miss, quotes = RD.check_conditions(copy.deepcopy(CONDS), TEXT)
    assert not rej and not miss
    assert c == {"kind": "serial_arm", "dof": 5, "payload": 0.5, "reach": 350, "repeatability": 0.5, "mount": "table",
                 "module_reuse": True, "for_people": ["全部自制件能在普通数控车床、铣床上加工", "外购件成本尽量低"]}
    assert len(quotes) == 7


@pytest.mark.parametrize("key,bad", [("payload", {"value": 5, "unit": "kg", "quote": "末端负载 5 kg"}),
                                     ("reach", {"value": 350, "unit": "mm", "quote": "臂长 350 mm"}),
                                     ("mount", {"where": "地面", "quote": "装在地面上"})])
def test_numbers_not_in_statement_are_rejected(key, bad):
    _, rej, _, _ = RD.check_conditions({**copy.deepcopy(CONDS), key: bad}, TEXT)
    assert rej


def test_reach_point_singular_or_unreachable_fails_and_longer_arm_passes():
    cond, *_ = RD.check_conditions(copy.deepcopy(CONDS), TEXT)
    short = RD.evaluate(arm(), cond)                     # 样例臂最远约 160+150+40+60 = 410 mm，比 350 大：够得着
    by = {i["item"]: i for i in short["items"]}
    assert by["自由度"]["status"] == "pass" and by["安装方式"]["status"] == "pass" and by["关节模组复用"]["status"] == "pass"
    assert by["臂展点（安装面上 r = 350 mm）"]["status"] == "pass"
    assert RD._passes(short)                                # 只剩“选件后才能判”的重复定位精度
    tiny = RD.evaluate(arm(reach_scale=0.6), cond)           # 缩小：够不着 350
    assert not RD._passes(tiny) and any(i["item"].startswith("臂展点") and i["status"] == "fail" for i in tiny["items"])


def test_module_reuse_required():
    cond, *_ = RD.check_conditions(copy.deepcopy(CONDS), TEXT)
    ev = RD.evaluate(arm(groups=False), cond)
    assert next(i for i in ev["items"] if i["item"] == "关节模组复用")["status"] == "fail"


def test_loop_feeds_back_and_adopts_recommended_passing_candidate():
    bad, good = arm(reach_scale=0.6), arm()
    ai = Script([{"candidates": [bad], "recommend": 0, "reason": "先试短臂"},
                 {"candidates": [bad, good], "recommend": 1, "reason": "加长"}])
    res = RD.design(TEXT, ai)
    assert res["status"] == "pass" and res["chosen_round"] == 2 and res["chosen_candidate"] == 1 and not res["chosen_note"]
    second = ai.requests[2]["user"]
    assert "第 1 轮你的构型" in second and "臂展点" in second           # 上一轮没通过的项交回 AI


def test_recommended_candidate_that_fails_is_not_adopted():
    ai = Script([{"candidates": [arm(), arm(reach_scale=0.6)], "recommend": 1, "reason": "推荐短的"}])
    res = RD.design(TEXT, ai)
    assert res["chosen_candidate"] == 0 and "没通过初筛" in res["chosen_note"]


def test_stuck_after_four_rounds_and_bad_formats():
    ai = Script([{"candidates": [{"format": "robot-concept/1"}], "recommend": 0, "reason": "x"}] * 2
                + [{"candidates": [], "recommend": 0, "reason": "x"}, {"candidates": [arm(reach_scale=0.6)], "recommend": 0, "reason": "x"}])
    res = RD.design(TEXT, ai)
    assert res["status"] == "stuck" and len(res["rounds"]) == 4
    assert "格式" in res["rounds"][0]["feedback"] or "结构" in res["rounds"][0]["feedback"]


def test_missing_conditions_stop_before_design():
    ai = Script([], conds={"kind": "serial_arm", "kind_quote": "教学用桌面机械臂"})
    res = RD.design(TEXT, ai)
    assert res["status"] == "needs_input" and set(res["missing"]) == {"自由度", "末端负载", "臂展"} and len(ai.requests) == 1
