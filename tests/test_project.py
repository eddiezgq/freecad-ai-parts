"""方案记录、重建调用、场景差异（ADR-0049）：纯函数，用真实库与布局会话测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from freecad_addon.core.project import (
    FORMAT,
    ProjectError,
    clear_calls,
    diff,
    dumps,
    loads,
    rebuild_calls,
    record,
)
from kb.library import JsonLibrary
from mcp_server.layout import LayoutSession

LIB = JsonLibrary(Path(__file__).resolve().parent.parent / "data" / "library")
M6 = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R25 = "reducer.harmonic-drive-llc.csf-25-100-2uh"


def _session():
    s = LayoutSession(lambda: LIB, lambda: None)
    s.place("motor", M6)
    s.place("reducer", R25, [10, 20, 300], [1, 0, 0], 90)
    s.connect("motor.shaft", "reducer.input_bore")
    s.place("drive", "drive.yaskawa-america-inc.sgd7s-1r6a", [150, 0, -60], [0, 0, 1], 30)
    return s


def test_record_round_trip_and_rebuild_reproduces_the_scene():
    s = _session()
    rec = record(s.state(), {"output_torque_cont_nm": 25, "output_speed_rpm": 30}, {"overall": "unknown"},
                 LIB.get, "组件库：测试", "2026-10-05T10:00")
    text = dumps(rec)
    back = loads(text)
    assert back["format"] == FORMAT and set(back["components"]) == {M6, R25, "drive.yaskawa-america-inc.sgd7s-1r6a"}
    calls, missing = rebuild_calls(back, LIB.get)
    assert not missing and [c[0] for c in calls].count("connect_ports") == 1
    t = LayoutSession(lambda: LIB, lambda: None)
    for name, a in calls:
        if name == "place_component":
            t.place(a["instance"], a["component_id"], a["position_mm"], a["rotation_axis"], a["rotation_deg"])
        else:
            t.connect(a["a"], a["b"], a["roll_deg"], a["offset_mm"])
    assert not diff(s.state(), t.state())["changed"]


def test_missing_components_are_reported_not_substituted():
    rec = record(_session().state(), None, None, LIB.get)
    calls, missing = rebuild_calls(rec, lambda cid: None if cid == M6 else LIB.get(cid))
    assert missing and "motor" in missing[0]
    assert all(a.get("instance") != "motor" for _, a in calls) and not any(n == "connect_ports" for n, _ in calls)


def test_loads_rejects_other_formats():
    with pytest.raises(ProjectError):
        loads("{}")
    with pytest.raises(ProjectError):
        loads("not json")


def test_diff_lists_added_removed_moved_and_links():
    s = _session()
    before = s.state()
    s.place("drive", None, [200, 0, -60], [0, 0, 1], 30)
    s.place("motor2", M6, [0, 300, 0])
    after = s.state()
    d = diff(before, after)
    assert d["added"] == ["motor2"] and d["moved"] == ["drive"] and not d["removed"] and d["changed"]
    assert not diff(before, before)["changed"]
    assert clear_calls(after) == [("place_component", {"instance": n, "remove": True})
                                  for n in ("drive", "motor", "motor2", "reducer")]
