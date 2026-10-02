"""相似会话检索（ADR-0042，issue #149）：排序确定、阈值、参考文字、对话引擎接入与关闭。"""

from __future__ import annotations

import pytest

from freecad_addon.core import retrieval as rv
from freecad_addon.core.session_log import SessionRecorder
from freecad_addon.gui.chat import ChatEngine, ScriptedLLM

KEY = "sk-ant-api03-SECRETSECRETSECRET"


def _record(root, name, request, *, rating="accepted", note="", component=None, edit=None, finish=True):
    rec = SessionRecorder(root, env={})
    rec.start(name=name)
    rec.chat("user", text=request)
    if component:
        rec.chat("tool_call", name="place_component", data={"instance": "motor", "component_id": component})
        rec.begin_ai()
        rec.doc_change("FapLayout", "motor", "created", type_id="Part::Feature")
        rec.end_ai()
    if edit:
        rec.doc_change("FapLayout", "motor", "changed", "Placement", edit)
    rec.note_result("verify_system", "可用：全部适用项通过")
    if finish:
        rec.stop(rating=rating, note=note)


@pytest.fixture
def root(tmp_path):
    _record(tmp_path, "a", "六轴机械臂第 2 关节：连续扭矩 25 N·m，输出转速 30 rpm，EtherCAT", note="板太厚",
            component="test.servo_motor.test-vendor.m200", edit={"position_mm": [0, 0, 12]}, rating="modified")
    _record(tmp_path, "b", "协作机器人腕部关节，48 V 直流，外径不超过 80 mm", rating="rejected", note="太大")
    _record(tmp_path, "c", "画一个法兰盘", rating=None)
    _record(tmp_path, "d", "六轴机械臂第 2 关节 25 N·m 30 rpm", finish=False)  # 未正常结束：不用
    return tmp_path


def test_terms():
    t = rv.terms("六轴机械臂 25 N·m 30 rpm EtherCAT")
    assert {"六轴", "机械", "25n·m", "30rpm", "ethercat"} <= t


def test_ranking_is_deterministic(root):
    sessions = rv.load(root)
    assert [s["session"] for s in sessions] == ["a", "b", "c"]
    hits = rv.similar("给六轴机械臂第 3 关节选型：连续扭矩 25 N·m，转速 30 rpm", sessions)
    assert [r["session"] for _, r in hits] == ["a"]
    assert rv.similar("给六轴机械臂第 3 关节选型：连续扭矩 25 N·m，转速 30 rpm", sessions) == hits
    assert rv.similar("今天天气怎样", sessions) == []
    boosted = rv.similar("关节", sessions, components={"test.servo_motor.test-vendor.m200"}, min_score=0.0)
    assert boosted[0][1]["session"] == "a"


def test_reference_text_contains_corrections_and_rejections(root):
    sessions = rv.load(root)
    text = rv.reference_text(rv.similar("机器人关节 48 V 直流 外径 80 mm", sessions, min_score=0.05) +
                             rv.similar("六轴机械臂第 2 关节 25 N·m 30 rpm", sessions))
    assert "未采纳" in text and "太大" in text and "修改后采纳" in text and "板太厚" in text
    assert "motor.Placement" in text and "verify_system 最后的结论" in text and "以本次工具的校验结果为准" in text
    assert rv.reference_text([]) == ""
    assert len(rv.reference_text(rv.similar("关节", sessions, min_score=0.0) * 50, max_chars=300)) == 300


def test_secrets_never_reach_hints(tmp_path):
    rec = SessionRecorder(tmp_path, env={})
    rec.start(name="k")
    rec.chat("user", text=f"六轴关节 {KEY}")
    rec.stop(rating="accepted")
    text = rv.SessionHints(tmp_path, min_score=0.0)("六轴关节")
    assert KEY not in text and "已隐去" in text


def test_engine_puts_hints_into_system_prompt(root):
    hints = rv.SessionHints(root)
    llm = ScriptedLLM([{"stop_reason": "end_turn", "content": [{"type": "text", "text": "好"}]},
                       {"stop_reason": "end_turn", "content": [{"type": "text", "text": "好"}]}])
    engine = ChatEngine(llm, [], lambda n, a: None, context=hints)
    events = engine.send("六轴机械臂第 2 关节，25 N·m，30 rpm")
    assert events[1].kind == "info" and hints.last_hits == ["a"]
    assert "相似会话" in llm.requests[0]["system"] and llm.requests[0]["system"].startswith(engine.system)
    engine.send("今天天气怎样")
    assert llm.requests[1]["system"] == engine.system  # 没有命中时不附加


def test_engine_survives_hint_errors():
    def boom(_):
        raise RuntimeError("坏了")

    llm = ScriptedLLM([{"stop_reason": "end_turn", "content": [{"type": "text", "text": "好"}]}])
    events = ChatEngine(llm, [], lambda n, a: None, context=boom).send("你好")
    assert [e.kind for e in events] == ["user", "info", "assistant"] and "跳过" in events[1].text


def test_default_hints_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("FAP_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("FAP_SESSION_HINTS", raising=False)
    hints = rv.default_hints()
    assert isinstance(hints, rv.SessionHints) and hints.root == tmp_path
    assert hints("六轴关节") == "" and hints.last_hits == []  # 目录为空
    monkeypatch.setenv("FAP_SESSION_HINTS", "0")
    assert rv.default_hints() is None
    assert rv.SessionHints(tmp_path / "missing")("关节") == ""
