"""问渠CAM C1 第 5 步：AI 起草工艺——程序定工序和候选刀，AI 只挑刀、在样本范围里定参数，程序逐项核对（ADR-0104 第 2、7 节）。"""

from __future__ import annotations

import pytest

from analysis import cam
from analysis.cam import tools as TL
from assist import cam_process as CP

TURN = {"mode": "turn", "machine": "EX-LATHE", "segments": [[30, 40], [40, 60], [35, 25], [24, 30]], "chamfer_mm": 1,
        "kienzle": "C45E", "grooves": [{"z": -27, "width": 3, "d": 20}],
        "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 1.5}], "bore": {"segments": [[16, 20], [12, 15]]}}
MILL = {"mode": "mill", "machine": "EX-VMC", "kienzle": "C45E", "stock": {"box": [0, 0, 100, 60], "height": 40},
        "features": [{"type": "pocket", "rect": [20, 15, 80, 45], "corner_r": 6, "depth": 8},
                     {"type": "holes", "d": 8.5, "points": [[10, 10], [90, 50]], "depth": 20}]}
LIB = TL.load()


def _within(card_row, iso="P"):
    t = TL.get(LIB, card_row["tool"])
    p = card_row["params"]
    kw = {k: v for k, v in p.items() if k in ("vc", "f", "fz", "ap")}
    return TL.verdict(TL.check_cutting(t, iso, **kw)) == "pass"


def test_rule_draft_turning_runs_clean_and_stays_in_sample_ranges():
    d = CP.draft(TURN, "P")
    card = {c["id"]: c for c in d["card"]}
    assert card["rough"]["tool"] == "TR-CNMG" and card["finish"]["tool"] == "TR-VNMG"   # 粗车大刀尖圆角、精车小的
    assert card["groove1"]["tool"] == "GR3" and card["thread1"]["tool"] == "TH15"
    assert card["drill"]["tool"] == "DR10" and card["bore"]["tool"] == "BB12"
    # 规则值：样本范围的中间值；全部在范围内
    assert card["rough"]["params"]["vc"] == pytest.approx((150 + 250) / 2) and card["rough"]["params"]["f"] == pytest.approx(0.275)
    assert all(_within(c) for c in d["card"]) and not d["notes"]
    r = cam.run({**d["setup"], "post": "fanuc"})
    assert r["status"] == "ok"
    for p in r["data"]["programs"]:
        assert p["release"] is not None and not [c for c in p["checks"] if c["level"] == "error"]
    assert d["setup"]["grooves"][0]["tool_w"] == 3.0 and d["setup"]["bore"]["drill_d"] == 10.0
    assert d["setup"]["machine_sim"]["tools"]["4"] == {"tool": "TH15"}


def test_rule_draft_milling_respects_corner_radius_and_max_engagement():
    d = CP.draft(MILL, "P", tool_lengths={"EM10": 120, "DR8.5": 140})
    card = {c["id"]: c for c in d["card"]}
    # 型腔转角 R6 → 刀径 ≤ 12：库里 Ø10 最大；样本最大切宽 2.5 → stepover = 0.25
    assert card["f1"]["tool"] == "EM10" and card["f1"]["params"]["stepover"] == pytest.approx(0.25)
    assert card["f2"]["tool"] == "DR8.5"
    s = d["setup"]
    assert s["features"][0]["cut"]["z"] == 4 and s["machine_sim"]["tools"]["1"] == {"tool": "EM10", "length_mm": 120.0}
    s["machine_sim"]["work_offset_mm"] = [0, 0, 40]
    p = cam.run({**s, "post": "siemens"})["data"]["programs"][0]
    assert p["release"] is not None, [c["text"] for c in p["checks"]]


def test_ai_answer_is_checked_item_by_item():
    ai = {"ops": [
        {"id": "rough", "tool": "TR-CNMG", "vc": 220, "f": 0.35, "ap": 3.0, "reason": "粗车用大圆角刀片，偏效率"},
        {"id": "finish", "tool": "EM10", "vc": 250, "f": 0.1},                  # 铣刀不是候选
        {"id": "groove1", "tool": "GR3", "vc": 200, "f": 0.05},                 # vc 超出 80–150
        {"id": "thread1", "tool": "TH15", "vc": 100},
        {"id": "bore", "tool": "BB12", "vc": 150, "f": 0.1, "ap": 2.0},          # ap 超过样本最大 1.5
        {"id": "nonsense", "tool": "TR-CNMG", "vc": 100}],
        "explanation": "先粗后精，螺纹最后"}
    fake = CP.FakeClient(ai)
    d = CP.draft(TURN, "P", client=fake)
    card = {c["id"]: c for c in d["card"]}
    assert card["rough"]["params"] == {"vc": 220.0, "f": 0.35, "ap": 3.0} and "大圆角" in card["rough"]["reason"]
    assert card["finish"]["tool"] == "TR-VNMG"
    assert card["groove1"]["params"]["vc"] == pytest.approx(115.0)
    assert card["thread1"]["params"]["vc"] == 100.0
    assert card["bore"]["params"]["ap"] == pytest.approx(1.0) and card["bore"]["params"]["vc"] == 150.0
    assert card["drill"]["tool"] == "DR10"                                       # AI 没给：按规则
    text = "\n".join(d["notes"])
    for frag in ("EM10 不在候选里", "vc=200 不采用", "ap=2 不采用", "nonsense 不存在", "钻孔：AI 没给"):
        assert frag in text, frag
    assert all(_within(c) for c in d["card"])                                    # 采用的参数全在样本范围内
    assert d["by"].startswith("AI") and d["explanation"] == "先粗后精，螺纹最后"
    # 发给 AI 的只有候选刀：车削工序里不出现铣刀
    assert "EM10" not in fake.request["user"] and "TR-VNMG" in fake.request["user"]


def test_stepover_from_ai_is_capped_by_sample():
    fake = CP.FakeClient({"ops": [{"id": "f1", "tool": "EM10", "vc": 120, "fz": 0.05, "ap": 6, "stepover": 0.5},
                                  {"id": "f2", "tool": "DR8.5", "vc": 70, "f": 0.15}], "explanation": ""})
    d = CP.draft(MILL, "P", client=fake)
    f1 = next(c for c in d["card"] if c["id"] == "f1")
    assert f1["params"]["stepover"] == pytest.approx(0.25) and any("stepover=0.5 不采用" in n for n in d["notes"])
    assert f1["params"]["fz"] == 0.05 and f1["params"]["ap"] == 6.0


def test_no_data_for_material_group_is_unknown_and_missing_tool_refuses():
    d = CP.draft(TURN, "M")
    assert all(c["status"] == "unknown" for c in d["card"])
    assert any("样本没有 M 组的参数" in n and "待确认" in n for n in d["notes"])
    with pytest.raises(CP.ProcessError, match="刀具库里没有能用的刀"):
        CP.draft({**TURN, "threads": [{"z_start": 0, "z_end": -26, "d": 24, "pitch": 2.0}]}, "P")
