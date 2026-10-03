"""对话面板（ADR-0036）：对话循环、进程内工具调用、安装程序；末尾标记 freecad 的测试在 FreeCAD 界面中运行面板。

LLM 一律用脚本回放（ScriptedLLM），不联网、不调用真实 LLM（CLAUDE.md）。
"""

from __future__ import annotations

import base64
import itertools
import json
import os
import runpy
import sys
import time

import pytest

from engine.golden import GOLDEN
from freecad_addon import install
from freecad_addon.gui.chat import (
    AnthropicChat,
    ChatEngine,
    ScriptedLLM,
    ToolOutcome,
    mcp_tools_to_anthropic,
    summarize,
)
from freecad_addon.gui.tools_client import InProcessTools
from kb.library import JsonLibrary
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAAABJRU5ErkJggg==")
MOTOR = "test.servo_motor.test-vendor.m400"
REDUCER = "test.reducer.test-vendor.r20-100"


class FakeBackend:
    syncs_view = False

    def call(self, method, params=None):
        if method == "snapshot":
            return {"view": params["view"], "width": params["width"], "height": params["height"],
                    "png_base64": base64.b64encode(PNG).decode()}
        return {"ok": True, "interferences": [], "pass_through": [], "threshold_mm3": 1.0, "instances": []}

    def close(self):
        pass


def use(i, name, args):
    return {"type": "tool_use", "id": f"t{i}", "name": name, "input": args}


def reply(*blocks, stop="tool_use"):
    return {"stop_reason": stop, "content": list(blocks)}


@pytest.fixture()
def tools():
    t = InProcessTools(create_server(lambda: LIB, FakeBackend))
    yield t
    t.close()


def _engine(tools, script, **kw):
    llm = ScriptedLLM(script)
    return llm, ChatEngine(llm, mcp_tools_to_anthropic(tools.list_tools()), tools.call, **kw)


def test_tool_list_conversion(tools):
    converted = mcp_tools_to_anthropic(tools.list_tools())
    names = {t["name"] for t in converted}
    assert {"compose_chain", "place_component", "connect_ports", "check_interference", "snapshot"} <= names
    place = next(t for t in converted if t["name"] == "place_component")
    assert place["input_schema"]["type"] == "object" and "instance" in place["input_schema"]["properties"]


def test_layout_conversation(tools):
    llm, engine = _engine(tools, [
        reply({"type": "text", "text": "先放置电机与减速器。"}, use(1, "place_component",
                                                         {"instance": "motor", "component_id": MOTOR}),
              use(2, "place_component", {"instance": "reducer", "component_id": REDUCER})),
        reply(use(3, "connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"})),
        reply(use(4, "snapshot", {"view": "iso", "width": 200, "height": 150})),
        reply({"type": "text", "text": "布局完成，减速器在 z=20 mm。"}, stop="end_turn"),
    ])
    events = engine.send("把 m400 和 r20 装在一起")
    kinds = [e.kind for e in events]
    assert kinds == ["user", "assistant", "tool_call", "tool_result", "tool_call", "tool_result", "tool_call",
                     "tool_result", "tool_call", "tool_result", "assistant"]
    connect_result = json.loads(events[7].text)
    pos = {i["instance"]: i["position_mm"] for i in connect_result["layout"]["instances"]}
    assert pos["reducer"] == [0.0, 0.0, 20.0]
    assert events[9].images == [PNG]
    # 第二次请求：带上第一轮两个工具的结果，id 对应
    second = llm.requests[1]["messages"]
    results = second[-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"] and second[-1]["role"] == "user"
    image_block = llm.requests[3]["messages"][-1]["content"][0]["content"][-1]
    assert image_block["type"] == "image" and base64.b64decode(image_block["source"]["data"]) == PNG
    assert llm.requests[0]["system"].startswith("你是 FreeCAD 中的机电零件选型与布局助手")
    roles = [m["role"] for m in engine.messages]
    assert all(a != b for a, b in itertools.pairwise(roles))


def test_tool_error_is_reported_to_llm(tools):
    llm, engine = _engine(tools, [
        reply(use(1, "place_component", {"instance": "motor", "component_id": "test.nope.x.y"})),
        reply({"type": "text", "text": "组件不存在。"}, stop="end_turn"),
    ])
    events = engine.send("放一个不存在的组件")
    result = next(e for e in events if e.kind == "tool_result")
    assert result.data is True and "组件不存在" in result.text
    sent = llm.requests[1]["messages"][-1]["content"][0]
    assert sent["is_error"] is True


def test_tool_call_limit_and_followup(tools):
    loop = [reply(use(i, "place_component", {"instance": f"m{i}", "component_id": MOTOR})) for i in range(1, 4)]
    _, engine = _engine(tools, [*loop, reply({"type": "text", "text": "好的"}, stop="end_turn")],
                          max_tool_calls=2)
    events = engine.send("放很多电机")
    assert events[-1].kind == "error" and "超过 2 次" in events[-1].text
    assert sum(e.kind == "tool_call" for e in events) == 2
    engine.send("继续")
    roles = [m["role"] for m in engine.messages]
    assert all(a != b for a, b in itertools.pairwise(roles))
    assert engine.messages[-2]["content"][-1] == {"type": "text", "text": "继续"}


def test_llm_failure_rolls_back_turn(tools):
    class Boom:
        def create(self, **kw):
            raise ConnectionError("网络不通")

    engine = ChatEngine(Boom(), [], tools.call)
    events = engine.send("你好")
    assert events[-1].kind == "error" and "网络不通" in events[-1].text and engine.messages == []


def test_summaries():
    assert summarize("place_component", json.dumps({"instance": "m", "moved": ["m", "r"], "view": "已同步到 FreeCAD"})) \
        == "已放置 m（随之移动：m、r）；已同步到 FreeCAD"
    assert summarize("place_component", json.dumps({"removed": "m"})) == "已删除 m"
    assert summarize("connect_ports", json.dumps({"a": "x.p", "b": "y.q", "kind": "face", "moved": []})) \
        == "已配合 x.p ↔ y.q（face，移动：无（只核对对齐））"
    hit = {"interferences": [{"a": "d", "b": "m", "volume_mm3": 12.5}], "pass_through": [{"instance": "plate"}]}
    assert summarize("check_interference", json.dumps(hit)) == "干涉 d–m 12.5 mm³；需有通孔：plate"
    assert summarize("check_interference", json.dumps({"interferences": []})) == "无干涉"
    assert summarize("snapshot", json.dumps({"view": "iso", "width": 1, "height": 2})) == "截图（iso，1×2）"
    assert summarize("verify_system", json.dumps({"explanation": "可用：全部通过。\n细节"})) == "可用：全部通过。"
    assert summarize("export_system", json.dumps({"filename": "a.urdf"})) == "已导出 a.urdf"
    cand = {"candidates": [{"overall": "pass", "system": {"components": [{"component": "a"}, {"component": "b"}]}}]}
    assert summarize("compose_chain", json.dumps(cand)) == "1 个候选方案；方案 1（pass）：a、b"
    assert summarize("compose_chain", json.dumps({"candidates": []})) == "没有找到满足需求的方案"
    assert summarize("x", "组件不存在", True) == "组件不存在"
    assert summarize("x", "纯文本") == "纯文本"
    assert len(summarize("get_component", json.dumps({"k": "v" * 500}))) == 160


def test_tool_outcome_content():
    assert ToolOutcome().to_content() == [{"type": "text", "text": "（无输出）"}]
    c = ToolOutcome(["a"], [b"x"]).to_content()
    assert c[0] == {"type": "text", "text": "a"} and c[1]["source"]["data"] == base64.b64encode(b"x").decode()


def test_anthropic_chat_requires_key(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("freecad_addon.gui.chat._load_dotenv", lambda: None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicChat()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    monkeypatch.setitem(sys.modules, "anthropic", None)  # 模拟未安装
    with pytest.raises(RuntimeError, match="pip install"):
        AnthropicChat()


# ------------------------------------------------------------------ 安装


def test_install_and_uninstall(tmp_path):
    target = install.install(tmp_path)
    src = (target / "InitGui.py").read_text(encoding="utf-8")
    assert target.name == "FreeCADAIParts" and install.MARKER in src
    assert repr(str(install.REPO_ROOT)) in src and "register()" in src
    compile(src, "InitGui.py", "exec")
    assert install.uninstall(tmp_path) and not target.exists()
    assert install.uninstall(tmp_path) is False
    foreign = tmp_path / "FreeCADAIParts"
    foreign.mkdir()
    (foreign / "InitGui.py").write_text("# 别人的插件\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="未删除"):
        install.uninstall(tmp_path)


def test_install_cli(tmp_path, capsys):
    assert install.main(["--mod-dir", str(tmp_path)]) == 0
    assert "AI Parts" in capsys.readouterr().out
    assert install.main(["--mod-dir", str(tmp_path), "--uninstall"]) == 0


@pytest.mark.parametrize(("platform", "env", "tail"), [
    ("linux", {"XDG_DATA_HOME": "/x/data"}, "/x/data/FreeCAD/Mod"),
    ("darwin", {}, "Library/Application Support/FreeCAD/Mod"),
    ("win32", {"APPDATA": "C:/Users/u/AppData/Roaming"}, "C:/Users/u/AppData/Roaming/FreeCAD/Mod"),
])
def test_default_mod_dir(monkeypatch, platform, env, tail):
    monkeypatch.setattr(install.sys, "platform", platform)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert install.default_mod_dir().as_posix().endswith(tail)


def test_default_mod_dirs_include_versioned(monkeypatch, tmp_path, capsys):
    """FreeCAD 1.1 起用户目录按版本分开（v1-1/），已有的版本目录都装上。"""
    monkeypatch.setattr(install.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert install.default_mod_dirs() == [tmp_path / "FreeCAD" / "Mod"]
    for d in ("v1-1", "v1-2", "vfoo", "macros"):
        (tmp_path / "FreeCAD" / d).mkdir(parents=True)
    root = tmp_path / "FreeCAD"
    assert install.default_mod_dirs() == [root / "Mod", root / "v1-1" / "Mod", root / "v1-2" / "Mod"]
    assert install.main([]) == 0
    assert (root / "v1-1" / "Mod" / "FreeCADAIParts" / "InitGui.py").is_file()
    assert "v1-2" in capsys.readouterr().out
    assert install.main(["--uninstall"]) == 0
    assert not (root / "v1-1" / "Mod" / "FreeCADAIParts").exists()


# ------------------------------------------------------------------ FreeCAD 界面


@pytest.fixture(scope="module")
def gui():
    import FreeCAD  # noqa: F401
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def _pump_until(app, cond, timeout=120):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert cond(), "超时"


@pytest.mark.freecad
def test_workbench_registers_from_generated_initgui(gui, tmp_path):
    import FreeCADGui

    target = install.install(tmp_path)
    runpy.run_path(str(target / "InitGui.py"))  # 与 FreeCAD 启动时执行 InitGui.py 相同
    assert "AiPartsWorkbench" in FreeCADGui.listWorkbenches()
    FreeCADGui.activateWorkbench("AiPartsWorkbench")
    assert {"FAP_ChatPanel", "FAP_Bridge", "FAP_Record", "FAP_RecordVideo"} <= set(FreeCADGui.listCommands())


@pytest.mark.freecad
def test_bridge_command_toggles(gui, tmp_path, monkeypatch):
    from freecad_addon.gui.workbench import BridgeCommand

    path = tmp_path / "bridge.json"
    monkeypatch.setenv("FAP_BRIDGE_FILE", str(path))
    cmd = BridgeCommand()
    cmd.Activated()
    assert path.exists()
    cmd.Activated()
    assert not path.exists()


@pytest.mark.freecad
def test_panel_conversation_lays_out_in_freecad(gui):
    import FreeCAD

    from freecad_addon.gui.panel import ChatPanel

    script = [
        reply(use(1, "place_component", {"instance": "motor", "component_id": MOTOR}),
              use(2, "place_component", {"instance": "reducer", "component_id": REDUCER})),
        reply(use(3, "connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"}),
              use(4, "check_interference", {})),
        reply(use(5, "snapshot", {"view": "iso", "width": 240, "height": 180})),
        reply({"type": "text", "text": "布局完成，没有干涉。"}, stop="end_turn"),
    ]
    panel = ChatPanel(llm_factory=lambda: ScriptedLLM(script), library_factory=lambda: LIB)
    try:
        assert "虚构测试组件" in panel.header.text() or "FAP_LIBRARY" in panel.header.text()
        assert panel.send("装配 m400 与 r20")
        assert panel.send("再来一次") is False  # 进行中不接受新消息
        _pump_until(gui, lambda: not panel.busy)
        text = panel.transcript.toPlainText()
        for word in ("你：", "调用 place_component", "调用 connect_ports", "调用 check_interference", "调用 snapshot",
                     "布局完成，没有干涉"):
            assert word in text
        assert "→ 无干涉" in text and "→ 已配合 motor.mount_flange ↔ reducer.motor_flange" in text
        doc = FreeCAD.getDocument("FapLayout")  # 布局实时显示在当前 FreeCAD 中
        assert sorted(o.Name for o in doc.Objects) == ["motor", "reducer"]
        assert doc.getObject("reducer").Shape.Placement.Base.z == pytest.approx(20)
        import re

        assert re.findall(r'<img src="([^"]+)"', panel.transcript.toHtml()) == ["fap-image:snapshot-1"], text
    finally:
        panel.close()


@pytest.mark.freecad
def test_recording_a_panel_conversation(gui, tmp_path, monkeypatch):
    """操作录制（ADR-0042）：AI 工具调用造成的文档改动标为 ai，之后的手工改动标为 user；状态栏有标记。"""
    import FreeCAD
    import FreeCADGui

    from freecad_addon.core.session_log import read_session
    from freecad_addon.gui import recording
    from freecad_addon.gui.panel import ChatPanel

    monkeypatch.setenv("FAP_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(recording, "_recorder", None)
    script = [
        reply(use(1, "place_component", {"instance": "motor", "component_id": MOTOR})),
        reply({"type": "text", "text": "已放置。"}, stop="end_turn"),
    ]
    panel = ChatPanel(llm_factory=lambda: ScriptedLLM(script), library_factory=lambda: LIB)
    path = recording.start()
    try:
        bar = FreeCADGui.getMainWindow().statusBar()
        assert any(w.text() == "● 录制中" for w in bar.findChildren(type(recording._indicator)))
        assert panel.send("放一个电机")
        _pump_until(gui, lambda: not panel.busy)
        obj = FreeCAD.getDocument("FapLayout").getObject("motor")
        obj.Label = "我的电机"  # 用户手工改动
        gui.processEvents()
    finally:
        out = recording.stop("modified", "改了名字")
        panel.close()
    assert out == path and recording._indicator is None
    s = read_session(path)
    roles = [e.get("role") for e in s["events"] if e["kind"] == "chat"]
    assert roles == ["user", "tool_call", "tool_result", "assistant"]
    layout = [e for e in s["events"] if e["kind"] == "doc_change" and e["doc"] == "FapLayout"]
    assert any(e["op"] == "created" and e["object"] == "motor" and e["origin"] == "ai" for e in layout)
    label = [e for e in layout if e.get("property") == "Label" and e["value"] == "我的电机"]
    assert label and label[-1]["origin"] == "user"
    assert s["outcome"]["rating"] == "modified" and s["meta"]["freecad_version"].startswith("1.0")


@pytest.mark.freecad
def test_recording_with_video(gui, tmp_path, monkeypatch):
    """可选视频（ADR-0042）：有 ffmpeg 时生成 video.mp4；没有时说明原因，其余照常录制。"""
    import stat
    import textwrap

    from freecad_addon.core.session_log import read_session
    from freecad_addon.gui import recording

    fake = tmp_path / "ffmpeg"
    fake.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys
        sys.stdin.read(1)
        open(sys.argv[-1], "wb").write(b"fake-mp4")
    """), encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("FAP_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(recording, "_recorder", None)

    monkeypatch.setenv("FAP_FFMPEG", str(fake))
    path = recording.start(video=True)
    out = read_session(recording.stop())["outcome"]
    assert out["video"] == "video.mp4" and (path / "video.mp4").read_bytes() == b"fake-mp4"

    monkeypatch.delenv("FAP_FFMPEG")
    monkeypatch.setattr("shutil.which", lambda name: None)
    path = recording.start(video=True)
    s = read_session(recording.stop())
    assert s["outcome"]["video"] is None and "ffmpeg" in s["outcome"]["video_error"]
    assert s["events"][0]["kind"] == "note" and s["events"][0]["what"] == "video_unavailable"
    assert not (path / "video.mp4").exists()


@pytest.mark.freecad
def test_panel_reports_missing_key(gui, monkeypatch):
    from freecad_addon.gui import chat
    from freecad_addon.gui.panel import ChatPanel

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(chat, "_load_dotenv", lambda: None)
    panel = ChatPanel(llm_factory=chat.AnthropicChat, library_factory=lambda: LIB)
    try:
        assert panel.send("你好") is False
        assert "ANTHROPIC_API_KEY" in panel.transcript.toPlainText()
    finally:
        panel.close()


def test_truncated_tool_use_is_not_left_dangling(tools):
    """响应被截断（max_tokens）却带着 tool_use：不执行，也不留下没有结果的 tool_use（#104 评审）。"""
    llm, engine = _engine(tools, [
        reply({"type": "text", "text": "先放置"}, use(1, "place_component", {"instance": "m", "component_id": MOTOR}),
              stop="max_tokens"),
        reply({"type": "text", "text": "好的"}, stop="end_turn"),
    ])
    events = engine.send("放一个电机")
    assert [e.kind for e in events] == ["user", "assistant", "error"] and "截断" in events[-1].text
    engine.send("继续")
    sent = llm.requests[1]["messages"]
    assert not any(b.get("type") == "tool_use" for m in sent if isinstance(m["content"], list) for b in m["content"])
    roles = [m["role"] for m in engine.messages]
    assert all(a != b for a, b in itertools.pairwise(roles))


def test_empty_response_keeps_roles_alternating(tools):
    _, engine = _engine(tools, [reply(stop="end_turn"), reply({"type": "text", "text": "好"}, stop="end_turn")])
    engine.send("你好")
    assert engine.messages == []
    engine.send("在吗")
    assert [m["role"] for m in engine.messages] == ["user", "assistant"]


@pytest.mark.freecad
def test_demo_driver_replay_runs(tmp_path):
    """录屏用的演示驱动（#105）：回放模式在 FreeCAD 界面中跑完一轮对话。"""
    import subprocess

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("FAP_LIBRARY", None)
    env.pop("DATABASE_URL", None)
    out = subprocess.run([sys.executable, "-m", "freecad_addon.gui.demo_driver", "--pause", "0", "--hold", "0"],
                         env=env, capture_output=True, text=True, timeout=300, check=False)
    assert out.returncode == 0, out.stderr[-2000:]


def test_scripted_demo_matches_sample_system():
    from freecad_addon.gui import demo_driver

    script = demo_driver.scripted_responses()
    assert script[-1]["stop_reason"] == "end_turn"
    names = [b["name"] for r in script for b in r["content"] if b["type"] == "tool_use"]
    assert names[0] == "compose_chain" and names[-1] == "verify_system" and "snapshot" in names
    ids = [b["id"] for r in script for b in r["content"] if b["type"] == "tool_use"]
    assert len(ids) == len(set(ids))


def test_tool_call_limit_env(monkeypatch):
    from freecad_addon.gui import chat

    monkeypatch.delenv("FAP_CHAT_MAX_TOOLS", raising=False)
    assert chat.tool_call_limit() == chat.MAX_TOOL_CALLS == 40
    monkeypatch.setenv("FAP_CHAT_MAX_TOOLS", "60")
    assert chat.tool_call_limit() == 60 and chat.ChatEngine(None, [], lambda n, a: None).max_tool_calls == 60
    for bad in ("0", "-3", "abc"):
        monkeypatch.setenv("FAP_CHAT_MAX_TOOLS", bad)
        assert chat.tool_call_limit() == 40
