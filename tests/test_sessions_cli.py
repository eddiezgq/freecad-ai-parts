"""录制会话的查看、导出与重放（ADR-0042，issue #148）。"""

from __future__ import annotations

import json

import pytest

from freecad_addon import sessions as sx
from freecad_addon.core.session_log import RecorderError, SessionRecorder, read_session


def _session(root, name, *, rating="modified"):
    rec = SessionRecorder(root, env={})
    rec.start({"library": "test"}, name=name)
    rec.chat("user", text="给第 2 关节选型并布局")
    rec.chat("tool_call", name="place_component", data={"instance": "motor"})
    rec.begin_ai()
    rec.doc_change("FapLayout", "motor", "created", type_id="Part::Feature")
    rec.doc_change("FapLayout", "motor", "changed", "Placement",
                   {"position_mm": [0, 0, 0], "axis": [0, 0, 1], "angle_deg": 0})
    rec.end_ai()
    rec.chat("tool_result", name="place_component", text="已放置 motor")
    rec.event("command", name="Std_Placement")
    rec.doc_change("FapLayout", "motor", "changed", "Placement",
                   {"position_mm": [0, 0, 12], "axis": [0, 0, 1], "angle_deg": 0})
    rec.doc_change("Other", "Pre", "changed", "Label", "existing")  # 会话前就有的对象
    rec.note_result("verify_system", "可用")
    if rating == "unfinished":
        return rec.directory
    return rec.stop(rating=rating, note="电机往上挪了 12 mm")


def test_list_show_export(tmp_path):
    _session(tmp_path, "a")
    _session(tmp_path, "b", rating=None)
    _session(tmp_path, "c", rating="unfinished")
    items = {i["session"]: i for i in sx.list_sessions(tmp_path)}
    assert set(items) == {"a", "b", "c"} and items["c"]["finished"] is False and items["a"]["rating"] == "modified"
    summary = sx.summarize(read_session(tmp_path / "a"))
    assert summary["changes_by_origin"] == {"ai": 2, "user": 2} and summary["commands"] == ["Std_Placement"]
    assert summary["tool_calls"] == ["place_component"]
    out = tmp_path / "ds.jsonl"
    assert sx.export(out, root=tmp_path) == 2  # 未正常结束的不导出
    assert sx.export(out, root=tmp_path, rated_only=True) == 1
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["format"] == sx.DATASET_FORMAT and row["request"] == "给第 2 关节选型并布局"
    assert row["rating"] == "modified" and row["results"] == {"verify_system": "可用"}
    assert [a["origin"] for a in row["actions"]] == ["ai", "ai", "user", "user"]
    edits = row["user_edits_after_ai"]
    assert [(e["object"], e["property"], e["value"]["position_mm"]) for e in edits] == [("motor", "Placement",
                                                                                           [0, 0, 12])]


def test_plan_replay(tmp_path):
    events = read_session(_session(tmp_path, "a"))["events"]
    steps = sx.plan_replay(events)  # 改动最多的文档是 FapLayout；会话前就有的对象不重放
    assert [s["op"] for s in steps] == ["create", "set", "set"]
    assert steps[-1]["value"]["position_mm"] == [0, 0, 12] and steps[-1]["origin"] == "user"
    assert sx.plan_replay(events, "Other") == []
    rec = SessionRecorder(tmp_path, env={})
    rec.start(name="d")
    rec.doc_change("D", "Box", "created", type_id="Part::Box")
    rec.doc_change("D", "Box", "changed", "Length", 20)
    rec.doc_change("D", "Box", "deleted")
    rec.doc_change("D", "Box", "changed", "Length", 30)  # 删除后的改动不重放
    steps = sx.plan_replay(read_session(rec.stop())["events"])
    assert [(s["op"], s.get("value")) for s in steps] == [("create", None), ("set", 20), ("delete", None)]


@pytest.mark.parametrize(("raw", "want"), [("20", 20), ("2.5", 2.5), ("25 mm", "25 mm"), ("我的电机", "我的电机"),
                                           ("True", True), ({"a": 1}, {"a": 1}), (3, 3)])
def test_parse_value(raw, want):
    assert sx.parse_value(raw) == want


def test_cli(tmp_path, monkeypatch, capsys):
    _session(tmp_path, "a")
    monkeypatch.setenv("FAP_SESSIONS_DIR", str(tmp_path))
    assert sx.main(["list"]) == 0 and "a  " in capsys.readouterr().out
    assert sx.main(["show", "a"]) == 0 and '"changes_by_origin"' in capsys.readouterr().out
    assert sx.main(["export", str(tmp_path / "o.jsonl")]) == 0 and "已导出 1" in capsys.readouterr().out
    assert sx.main(["show", "nope"]) == 1
    with pytest.raises(RecorderError):
        sx.resolve("nope", tmp_path)


@pytest.mark.freecad
def test_replay_rebuilds_objects(tmp_path):
    import FreeCAD

    from freecad_addon.fc.session_observers import Attachment

    rec = SessionRecorder(tmp_path, env={})
    rec.start(name="fc")
    att = Attachment(rec, gui=False)
    att.attach()
    try:
        doc = FreeCAD.newDocument("FapRecSrc")
        box = doc.addObject("Part::Box", "Box")
        box.Length = 25
        box.Placement = FreeCAD.Placement(FreeCAD.Vector(1, 2, 3), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30))
        cyl = doc.addObject("Part::Cylinder", "Cyl")
        cyl.Radius = 4
        doc.removeObject("Cyl")
        doc.recompute()
    finally:
        att.detach()
    path = rec.stop(rating="accepted")
    FreeCAD.closeDocument("FapRecSrc")
    steps = sx.plan_replay(read_session(path)["events"], "FapRecSrc")
    new, stats = sx.apply_replay(steps, "FapReplayTest")
    try:
        assert [o.Name for o in new.Objects] == ["Box"] and stats["create"] == 2 and stats["delete"] == 1
        b = new.getObject("Box")
        assert b.Length.Value == pytest.approx(25)
        assert list(b.Placement.Base) == pytest.approx([1, 2, 3])
        assert b.Placement.Rotation.Angle == pytest.approx(30 * 3.141592653589793 / 180)
        assert b.Shape.Volume == pytest.approx(25 * 10 * 10)
    finally:
        FreeCAD.closeDocument("FapReplayTest")
