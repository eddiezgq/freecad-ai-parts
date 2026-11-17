"""运动副候选（几何规则）与 AI 草稿核对（ADR-0097 D5b）：纯 Python。"""

from __future__ import annotations

import pytest

from analysis.mbd import mates as MT
from assist import mbd_mates as AM


def cyl(p, a, r, t, convex):
    return {"kind": "cylinder", "point": list(p), "axis": list(a), "radius": r, "t": list(t), "convex": convex}


def plane(p, n):
    return {"kind": "plane", "point": list(p), "normal": list(n), "area": 100.0}


def part(pid, faces, vol=1000.0):
    return {"id": pid, "label": pid, "volume_mm3": vol, "faces": faces}


def test_pin_in_hole_gives_revolute_with_cylindrical_alternative():
    A = part("frame", [cyl((0, 0, 0), (1, 0, 0), 3.05, (0, 10), False)], 5000)
    B = part("lever", [cyl((5, 0, 0), (-1, 0, 0), 3.0, (-2, 8), True)])
    found = MT.find_candidates([A, B])
    (c,) = found["candidates"]
    assert c["type"] == "revolute" and c["alternatives"] == ["cylindrical"]
    assert abs(c["axis"][0]) == pytest.approx(1)
    assert c["point_mm"] == pytest.approx([3.5, 0, 0])            # 轴 x ∈ [−3, 7]、孔 x ∈ [0, 10] → 重叠 [0, 7] 的中点
    assert found["ground"]["part"] == "frame" and found["unconnected"] == []


def test_radius_mismatch_or_offset_axis_is_not_a_joint():
    A = part("a", [cyl((0, 0, 0), (0, 0, 1), 5.0, (0, 10), False)])
    assert MT.find_candidates([A, part("b", [cyl((0, 0, 0), (0, 0, 1), 3.0, (0, 10), True)])])["candidates"] == []
    assert MT.find_candidates([A, part("b", [cyl((0, 0.1, 0), (0, 0, 1), 5.0, (0, 10), True)])])["candidates"] == []
    assert MT.find_candidates([A, part("b", [cyl((0, 0, 20), (0, 0, 1), 5.0, (0, 10), True)])])["candidates"] == []


def test_two_pins_make_fixed_and_ball_in_socket_makes_spherical():
    A = part("a", [cyl((0, 0, 0), (0, 0, 1), 2, (0, 5), False), cyl((20, 0, 0), (0, 0, 1), 2, (0, 5), False)])
    B = part("b", [cyl((0, 0, 0), (0, 0, 1), 2, (0, 5), True), cyl((20, 0, 0), (0, 0, 1), 2, (0, 5), True)])
    assert [c["type"] for c in MT.find_candidates([A, B])["candidates"]] == ["fixed"]
    S = part("s", [{"kind": "sphere", "center": [1, 2, 3], "radius": 8.0, "convex": True}])
    C = part("c", [{"kind": "sphere", "center": [1, 2, 3], "radius": 8.1, "convex": False}])
    (c,) = MT.find_candidates([S, C])["candidates"]
    assert c["type"] == "spherical" and c["point_mm"] == [1, 2, 3]


def test_dovetail_like_plane_contacts_make_a_slider():
    rail = part("rail", [plane((0, 0, 0), (0, 0, 1)), plane((0, 5, 2), (0, 1, 0))], 9000)
    car = part("car", [plane((3, 0, 0), (0, 0, -1)), plane((3, 5, 4), (0, -1, 0))])
    (c,) = MT.find_candidates([rail, car])["candidates"]
    assert c["type"] == "translational" and abs(c["axis"][0]) == pytest.approx(1)


def test_to_assembly_joints_checks_type():
    A = part("frame", [cyl((0, 0, 0), (1, 0, 0), 3.0, (0, 10), False)])
    B = part("lever", [cyl((0, 0, 0), (1, 0, 0), 3.0, (0, 10), True)])
    found = MT.find_candidates([A, B])
    assert MT.to_assembly_joints(found, [{"id": "c1", "type": "cylindrical"}])[0]["type"] == "cylindrical"
    with pytest.raises(ValueError):
        MT.to_assembly_joints(found, [{"id": "c1", "type": "spherical"}])
    with pytest.raises(ValueError):
        MT.to_assembly_joints(found, [{"id": "c9"}])


def _two():
    A = part("frame", [cyl((0, 0, 0), (1, 0, 0), 3.0, (0, 10), False)], 9000)
    B = part("crank", [cyl((0, 0, 0), (1, 0, 0), 3.0, (0, 10), True), cyl((0, 20, 0), (1, 0, 0), 2.0, (0, 5), True)])
    C = part("lever", [cyl((0, 20, 0), (1, 0, 0), 2.0, (0, 5), False)])
    parts = [A, B, C]
    return parts, MT.find_candidates(parts)


def test_ai_draft_is_checked_against_candidates():
    parts, found = _two()
    ai = AM.FakeClient({"ground": "frame", "explanation": "曲柄绕机架转，挑线杆挂在曲柄销上",
                        "accept": [{"id": "c1", "type": "revolute", "name": "主轴轴承"},
                                   {"id": "c2", "type": "spherical", "name": "曲柄销"},
                                   {"id": "c7", "type": "revolute", "name": "编出来的"}]})
    d = AM.draft(parts, found, ai)
    assert d["ground"] == "frame"
    assert [(a["id"], a["type"], a["name"]) for a in d["accept"]] == [("c1", "revolute", "主轴轴承"), ("c2", "revolute", "曲柄销")]
    assert any("c7" in n for n in d["notes"]) and any("spherical" in n for n in d["notes"])
    req = AM.build_request(parts, found)
    assert "c1" in req["user"] and "同轴" in req["user"] and req["tool"]["name"] == AM.TOOL_NAME


def test_ai_silence_and_bad_ground_fall_back_to_rules():
    parts, found = _two()
    d = AM.draft(parts, found, AM.FakeClient({"ground": "nope", "explanation": "", "accept": []}))
    assert d["ground"] == "frame"
    assert {a["id"] for a in d["accept"]} == {"c1", "c2"}
    assert AM.draft(parts, found)["by"].startswith("规则")
