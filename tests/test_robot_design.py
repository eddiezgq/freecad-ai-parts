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
         "repeatability": {"value": 1, "unit": "mm", "quote": "末端重复定位精度 ±1 mm"},
         "joint_speed": {"value": 60, "unit": "°/s", "quote": "关节最高角速度 60°/s"},
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
    assert c == {"kind": "serial_arm", "dof": 5, "payload": 0.5, "reach": 350, "repeatability": 1, "mount": "table",
                 "module_reuse": True, "for_people": ["全部自制件能在普通数控车床、铣床上加工", "外购件成本尽量低"],
                 "joint_speed": pytest.approx(10.0)}                                   # 60°/s = 10 rpm
    assert len(quotes) == 8


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


def test_stuck_after_the_round_budget_and_bad_formats():
    bad = ([{"candidates": [{"format": "robot-concept/1"}], "recommend": 0, "reason": "x"}] * 2
           + [{"candidates": [], "recommend": 0, "reason": "x"}, {"candidates": [arm(reach_scale=0.6)], "recommend": 0, "reason": "x"}])
    ai = Script((bad * 2)[:RD.MAX_ROUNDS])
    res = RD.design(TEXT, ai)
    assert res["status"] == "stuck" and len(res["rounds"]) == RD.MAX_ROUNDS
    assert "格式" in res["rounds"][0]["feedback"] or "结构" in res["rounds"][0]["feedback"]


def test_missing_conditions_stop_before_design():
    ai = Script([], conds={"kind": "serial_arm", "kind_quote": "教学用桌面机械臂"})
    res = RD.design(TEXT, ai)
    assert res["status"] == "needs_input" and set(res["missing"]) == {"自由度", "末端负载", "臂展"} and len(ai.requests) == 1


def test_unknown_link_material_fails():
    cond, *_ = RD.check_conditions(copy.deepcopy(CONDS), TEXT)
    c = arm()
    c["links"][1]["material"] = "aluminum_6061"
    ev = RD.evaluate(c, cond)
    assert next(i for i in ev["items"] if i["item"] == "杆件材料")["status"] == "fail"
    assert "6061-T6" in RD.proposal_request(cond, [])["user"]                     # 材料库的 id 交给 AI 选


def test_teaching_arm_recording_replays_to_pass():
    """案例 A 的真实 AI 录制（design-eval run 45192126945，2 轮）：重放得同一结论；不调用真实模型。
    选件与装配校核每轮约半分钟，这里按保存的结果逐轮回放（真正重算采用构型的在 test_case_a_loop_fixed_the_wrist_with_build_feedback）"""
    from analysis.robot import screen
    from ingest.llm_extract import RecordedClient

    saved = json.loads((Path(__file__).parents[1] / "examples" / "robots" / "teaching-arm" / "out"
                        / "concept-result.json").read_text(encoding="utf-8"))
    verdicts = [rd["build"] for rd in saved["rounds"] if "build" in rd]

    def after(concept, cond):
        return dict(verdicts.pop(0))

    res = RD.design(TEXT, RecordedClient(RD.RECORDINGS_DIR), model=RD.DEFAULT_MODEL, after_screen=after)
    assert res["status"] == "pass" and res["chosen_round"] == 2 and not verdicts
    c = res["chosen"]
    assert c["kind"] == "serial_arm" and len(c["joints"]) == 5
    assert screen(c, 0.5)["overall"] in ("pass", "unknown")
    assert RD._passes(RD.evaluate(c, res["conditions"]))
    assert saved["chosen"] == c


def test_build_check_failure_goes_back_to_ai():
    """初筛通过、但选件与装配校核没通过：不采用，没通过的项与模组外形交回 AI，下一轮通过才采用（ADR-0115 44.3 之二）"""
    calls = []

    def after(concept, cond):
        calls.append(concept["name"])
        if len(calls) == 1:
            return {"ok": False, "items": ["装配：j5 共线装不上"], "summary": "选 XM540-W270：壳体宽 33.5 mm"}
        return {"ok": True, "items": [], "summary": ""}

    ai = Script([{"candidates": [arm()], "recommend": 0, "reason": "第一版"}, {"candidates": [arm()], "recommend": 0, "reason": "改腕部"}])
    res = RD.design(TEXT, ai, after_screen=after)
    assert res["status"] == "pass" and res["chosen_round"] == 2 and len(calls) == 2
    assert res["rounds"][0]["build"]["ok"] is False and res["rounds"][1]["build"]["ok"] is True
    second = ai.requests[2]["user"]
    assert "选件、装配后没通过" in second and "j5 共线装不上" in second and "壳体宽 33.5 mm" in second


def test_case_a_loop_fixed_the_wrist_with_build_feedback():
    """真实 AI 第 1 轮：转台、腕杆太短，放不下支架与套管 → 交回 AI；第 2 轮采用的构型重新算一遍（选件、装配、三维、真实质量复核）也通过"""
    from assist.robot_build import build_check

    res = json.loads((Path(__file__).parents[1] / "examples" / "robots" / "teaching-arm" / "out" / "concept-result.json")
                     .read_text(encoding="utf-8"))
    first = res["rounds"][0]["build"]
    assert first["ok"] is False and any("放不下" in x for x in first["items"])
    assert "XM540" in first["summary"] or "XH540" in first["summary"] or "XD540" in first["summary"]
    bc = build_check(res["chosen"], res["conditions"])
    assert bc["ok"] is True and not bc["items"]
    assert bc["result"]["cad"]["status"] == "pass" and bc["result"]["verify"]["status"] != "fail"
