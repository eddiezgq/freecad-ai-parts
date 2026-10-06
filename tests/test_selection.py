"""选型面板的纯函数（ADR-0051 第 1 条）：需求表单互转、候选行、放入布局的调用序列。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from freecad_addon.core import requirement_form, selection
from freecad_addon.core.scene import Scene
from freecad_addon.core.system_layout import layout_system, mechanical_connections
from kb.library import JsonLibrary
from mcp_server import tools

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
REQ = json.loads((ROOT / "examples" / "joint-real-requirement.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------ 需求表单


def test_form_round_trip_keeps_only_filled_fields():
    req, err = requirement_form.from_texts({"output_torque_cont_nm": "25", "output_speed_rpm": " 30 ",
                                            "ambient_temp_c": "", "voltage_v": "200", "phases": "3"})
    assert err is None
    assert req == {"output_torque_cont_nm": 25.0, "output_speed_rpm": 30.0,
                   "supply": {"current_type": "ac", "voltage_v": 200.0, "phases": 3}}
    texts = requirement_form.to_texts(req)
    assert texts["output_torque_cont_nm"] == "25" and texts["voltage_v"] == "200" and texts["phases"] == "3"
    assert texts["ambient_temp_c"] == "" and texts["max_envelope_diameter_mm"] == ""
    assert requirement_form.from_texts(texts) == (req, None)


@pytest.mark.parametrize(("texts", "msg"), [
    ({"output_torque_cont_nm": "25"}, "输出转速"),
    ({"output_torque_cont_nm": "x", "output_speed_rpm": "30"}, "须为数字"),
    ({"output_torque_cont_nm": "25", "output_speed_rpm": "30", "voltage_v": "200", "phases": "2"}, "相数只能"),
    ({"output_torque_cont_nm": "25", "output_speed_rpm": "30", "phases": "3"}, "供电电压"),
])
def test_form_errors_give_no_requirement(texts, msg):
    req, err = requirement_form.from_texts(texts)
    assert req is None and msg in err


def test_dc_supply_and_diameter_limit():
    req, err = requirement_form.from_texts({"output_torque_cont_nm": "5", "output_speed_rpm": "60",
                                            "voltage_v": "48", "phases": "0", "max_envelope_diameter_mm": "90"})
    assert err is None
    assert req["supply"] == {"current_type": "dc", "voltage_v": 48.0, "phases": 0}
    assert req["max_envelope_diameter_mm"] == 90.0


def test_example_requirement_round_trips_through_the_form():
    texts = requirement_form.to_texts(REQ)
    req, err = requirement_form.from_texts(texts)
    assert err is None
    for key, _ in requirement_form.FIELDS:
        if key in REQ:
            assert req[key] == REQ[key]
    assert req["supply"] == REQ["supply"]


# ------------------------------------------------------------ 候选与放入布局


@pytest.fixture(scope="module")
def result():
    return tools.compose_chain(LIB, REQ, top_n=5, include_unknown=True)


def test_candidate_rows_name_parts_by_role(result):
    rows = selection.candidate_rows(result, LIB.get)
    assert len(rows) == result["count"] > 0
    first = rows[0]
    assert first.rank == 1 and first.status == "待确认"  # 真实样例：只有 C3（可配置法兰）待确认
    cells = selection.cells(first)
    assert len(cells) == len(selection.HEADERS)
    assert "SGM7J-02A" in cells[2] and "CSF-25-100-2UH" in cells[3] and "SGD7S-1R6A" in cells[4]
    assert cells[5] == "—"  # 没有转接件
    assert cells[6].endswith("kg")


def test_missing_mass_and_margin_show_unknown():
    row = selection.CandidateRow(1, "unknown", "待确认", {}, None, None, "", {})
    assert selection.cells(row)[-2:] == ["未知", "未知"]


def test_place_calls_clear_place_then_connect_in_layout_order(result):
    system = result["candidates"][0]["system"]
    current = {"instances": [{"instance": "old"}], "connections": []}
    calls, unmated = selection.place_calls(system, current, LIB.get)
    assert calls[0] == ("place_component", {"instance": "old", "remove": True})
    placed = [a["instance"] for n, a in calls if n == "place_component" and "component_id" in a]
    assert placed == [c["instance"] for c in system["components"]]
    ordered, skipped = mechanical_connections(system, LIB.get)
    assert [(a["a"], a["b"]) for n, a in calls if n == "connect_ports"] == [(c["a"], c["b"]) for c in ordered]
    assert skipped  # 电气、信号连接不参与布局
    cats = {c["instance"]: LIB.get(c["component"])["category"] for c in system["components"]}
    assert [cats[i] for i in unmated] == ["drive"]


def test_replaying_place_calls_matches_layout_system(result):
    """调用序列在场景中重放的结果与 system_layout 的布局一致（刚性组内相对位姿相同）。"""
    system = result["candidates"][0]["system"]
    calls, _ = selection.place_calls(system, {"instances": []}, LIB.get)
    scene = Scene()
    for name, args in calls:
        if name == "place_component":
            scene.place(args["instance"], LIB.get(args["component_id"]))
        else:
            scene.connect(args["a"], args["b"])
    ref, _ = layout_system(system, LIB.get)
    base = system["components"][0]["instance"]
    for item in system["components"]:
        n = item["instance"]
        if n in ref.group(base):
            got = scene.pose(base).inverse().compose(scene.pose(n))
            want = ref.pose(base).inverse().compose(ref.pose(n))
            assert got.translation == pytest.approx(want.translation, abs=1e-6)
            assert got.rotation == pytest.approx(want.rotation, abs=1e-9)


def test_side_calls_put_unmated_parts_beside_the_assembly():
    layout = {"instances": [
        {"instance": "motor", "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 0},
         "bbox_mm": {"min_mm": [-30, -30, 0], "max_mm": [30, 30, 100]}},
        {"instance": "drive", "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 90},
         "bbox_mm": {"min_mm": [-20, -75, 0], "max_mm": [20, 75, 160]}},
        {"instance": "drive2", "position_mm": [0, 0, 0], "rotation": {"axis": [0, 0, 1], "angle_deg": 0},
         "bbox_mm": {"min_mm": [0, 0, 0], "max_mm": [40, 150, 160]}},
        {"instance": "nobox", "position_mm": [0, 0, 0], "bbox_mm": None}]}
    calls = selection.side_calls(layout, ["drive", "drive2", "nobox"], gap_mm=50)
    assert calls[0] == ("place_component", {"instance": "drive", "position_mm": [100.0, 0, 0],
                                            "rotation_axis": [0, 0, 1], "rotation_deg": 90})
    assert calls[1][1]["position_mm"] == [170.0, 0, 0]  # 30 + 50 + 40 + 50 − 0
    assert len(calls) == 2  # 包络缺尺寸的不挪
