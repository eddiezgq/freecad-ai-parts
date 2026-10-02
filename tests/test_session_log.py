"""操作录制（ADR-0042，issue #146）：会话包格式、去密钥、改动来源、限频；末尾标记 freecad 的测试在 FreeCAD 中运行。"""

from __future__ import annotations

import json
import threading

import pytest

from freecad_addon.core.session_log import (
    FORMAT,
    REDACTED,
    RecorderError,
    SessionRecorder,
    read_session,
)

KEY = "sk-ant-api03-ABCDEFGHIJKLMNOP"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def rec(tmp_path):
    clock = Clock()
    r = SessionRecorder(tmp_path, clock=clock, env={"ANTHROPIC_API_KEY": "my-secret-key-123"})
    r.clock = clock
    return r


def test_session_package(rec, tmp_path):
    assert rec.event("note", text="x") is None  # 未录制时什么都不记
    d = rec.start({"library": "test"}, name="s1")
    assert d == tmp_path / "s1" and rec.active and (d / "snapshots").is_dir()
    rec.clock.t += 1.5
    rec.event("command", name="PartDesign_Pad")
    rec.chat("user", text="给关节选型")
    out = rec.stop(rating="modified", note="改了板厚")
    assert out == d and not rec.active
    s = read_session(d)
    assert s["meta"]["format"] == FORMAT and s["meta"]["events"] == 2 and s["meta"]["library"] == "test"
    assert [e["seq"] for e in s["events"]] == [1, 2] and s["events"][0]["t"] == 1.5
    assert s["events"][0] == {"seq": 1, "t": 1.5, "kind": "command", "name": "PartDesign_Pad"}
    assert s["outcome"]["rating"] == "modified" and s["outcome"]["note"] == "改了板厚"


def test_errors(rec):
    with pytest.raises(RecorderError):
        rec.stop()
    rec.start(name="a")
    with pytest.raises(RecorderError):
        rec.start(name="b")
    with pytest.raises(RecorderError):
        rec.event("video")
    with pytest.raises(RecorderError):
        rec.doc_change("D", "Box", "moved")
    with pytest.raises(RecorderError):
        rec.stop(rating="great")


def test_secrets_redacted_everywhere(rec):
    d = rec.start({"note": f"key {KEY}"}, name="s")
    rec.chat("tool_call", name="x", data={"api": "my-secret-key-123", "nested": [KEY]})
    rec.chat("assistant", text=f"密钥是 {KEY}")
    rec.note_result("verify_system", {"k": KEY})
    rec.stop(note="my-secret-key-123")
    blob = "".join(p.read_text(encoding="utf-8") for p in d.iterdir() if p.is_file())
    assert KEY not in blob and "my-secret-key-123" not in blob and blob.count(REDACTED) >= 5


def test_origin_marks_ai_tool_calls(rec):
    rec.start(name="s")
    rec.doc_change("D", "Box", "created", type_id="Part::Box")
    rec.begin_ai()
    rec.doc_change("D", "Box", "changed", "Length", 20)
    rec.end_ai()
    rec.end_ai()  # 多余的 end 不会变成负数
    rec.doc_change("D", "Box", "changed", "Length", 25)
    events = read_session(rec.stop())["events"]
    assert [e["origin"] for e in events] == ["user", "ai", "user"]
    assert events[0]["type"] == "Part::Box" and events[2]["value"] == "25"


def test_unchanged_values_not_repeated(rec):
    rec.start(name="s")
    assert rec.doc_change("D", "Box", "changed", "Length", 20)
    assert rec.doc_change("D", "Box", "changed", "Length", 20) is None
    assert rec.doc_change("D", "Box", "changed", "Width", 20)
    rec.doc_change("D", "Box", "deleted")
    assert rec.doc_change("D", "Box", "changed", "Length", 20)  # 删除后同名新对象重新记
    placement = {"position_mm": [0, 0, 5], "axis": [0, 0, 1], "angle_deg": 0}
    assert rec.doc_change("D", "Box", "changed", "Placement", placement)["value"] == placement
    assert rec.doc_change("D", "Box", "changed", "Label", "x" * 500)["value"].endswith("…")


def test_snapshot_rate_limit(rec):
    rec.start(name="s")
    p1 = rec.next_snapshot()
    assert p1.name == "0001.png"
    p1.write_bytes(b"png")
    rec.snapshot_saved(p1, view="D")
    rec.clock.t += 1.0
    assert rec.next_snapshot() is None
    rec.clock.t += 1.5
    assert rec.next_snapshot().name == "0002.png"
    s = read_session(rec.stop())
    assert s["meta"]["snapshots"] == 1
    assert s["events"][0] == {"seq": 1, "t": 0.0, "kind": "snapshot", "file": "snapshots/0001.png", "view": "D"}


def test_outcome_keeps_last_results(rec):
    rec.start(name="s")
    rec.note_result("verify_system", "有条件可用")
    rec.note_result("verify_system", "可用：全部适用项通过")
    out = read_session(rec.stop())["outcome"]
    assert out["last_results"] == {"verify_system": "可用：全部适用项通过"} and out["rating"] is None


def test_concurrent_writes_keep_order(rec):
    rec.start(name="s")

    def work(i):
        for j in range(50):
            rec.event("note", who=i, n=j)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    events = read_session(rec.stop())["events"]
    assert [e["seq"] for e in events] == list(range(1, 201))


def test_read_session_rejects_other_format(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"format": "session/0"}), encoding="utf-8")
    (d / "events.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(RecorderError):
        read_session(d)


def test_chat_events_from_panel(rec, monkeypatch):
    from freecad_addon.gui import recording
    from freecad_addon.gui.chat import Event

    monkeypatch.setattr(recording, "_recorder", rec)
    recording.chat_event(Event("user", "选型"))  # 未录制：忽略
    rec.start(name="s")
    recording.chat_event(Event("user", "给关节选型"))
    recording.chat_event(Event("tool_call", name="place_component", data={"instance": "motor"}))
    rec.doc_change("FapLayout", "motor", "created")  # 工具执行中：AI 的改动
    recording.chat_event(Event("tool_result", json.dumps({"verdict": "ok"}), name="verify_system", data=False))
    rec.doc_change("FapLayout", "motor", "changed", "Placement", "moved by hand")
    recording.chat_event(Event("assistant", "完成"))
    s = read_session(rec.stop())
    kinds = [(e["kind"], e.get("role"), e.get("origin")) for e in s["events"]]
    assert kinds == [("chat", "user", None), ("chat", "tool_call", None), ("doc_change", None, "ai"),
                     ("chat", "tool_result", None), ("doc_change", None, "user"), ("chat", "assistant", None)]
    assert "verify_system" in s["outcome"]["last_results"]


@pytest.mark.freecad
def test_document_observer_in_freecad(tmp_path):
    import FreeCAD

    from freecad_addon.fc.session_observers import Attachment

    rec = SessionRecorder(tmp_path, env={})
    rec.start(name="fc")
    att = Attachment(rec, gui=False)
    att.attach()
    try:
        doc = FreeCAD.newDocument("FapRecTest")
        box = doc.addObject("Part::Box", "Box")
        doc.recompute()
        rec.begin_ai()
        box.Length = 25
        box.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 5), FreeCAD.Rotation())
        rec.end_ai()
        doc.removeObject("Box")
        FreeCAD.closeDocument("FapRecTest")
    finally:
        att.detach()
    events = read_session(rec.stop())["events"]
    changes = [e for e in events if e["kind"] == "doc_change" and e["doc"] == "FapRecTest"]
    created = [e for e in changes if e["op"] == "created"]
    assert len(created) == 1 and created[0]["type"] == "Part::Box" and created[0]["origin"] == "user"
    length = [e for e in changes if e.get("property") == "Length"]
    assert length[-1]["value"] == "25 mm" and length[-1]["origin"] == "ai"
    placement = [e for e in changes if e.get("property") == "Placement"][-1]
    assert placement["value"]["position_mm"] == [0, 0, 5] and placement["origin"] == "ai"
    assert [e["object"] for e in changes if e["op"] == "deleted"] == ["Box"]
    assert not any(e.get("property") == "Shape" for e in changes)
