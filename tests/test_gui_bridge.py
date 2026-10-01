"""FreeCAD 界面桥接（ADR-0036）。

主作业：客户端协议、错误与 gui 后端下的视图同步（用测试内的假桥接）。
freecad 作业：在 Xvfb 下打开 FreeCAD 界面，启动真实桥接，经客户端与 MCP 工具调用。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import stat
import threading
import time

import pytest
from fastmcp import Client

from engine.golden import GOLDEN
from freecad_addon.fc.client import PREFIX, GuiBridgeClient, WorkerError, bridge_file
from kb.library import JsonLibrary
from mcp_server import layout
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
MOTOR = "test.servo_motor.test-vendor.m400"
REDUCER = "test.reducer.test-vendor.r20-100"


class FakeBridge:
    """按桥接协议应答的本机服务（不需要 FreeCAD）。"""

    def __init__(self, path, token="t0k", fail_sync=False):
        self.token, self.fail_sync, self.calls = token, fail_sync, []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        path.write_text(json.dumps({"host": "127.0.0.1", "port": self.port, "token": token, "pid": 1}))
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                f = conn.makefile("rw", encoding="utf-8")
                req = json.loads(f.readline())
                self.calls.append(req)
                if req.get("token") != self.token:
                    resp = {"id": req["id"], "error": {"kind": "auth", "message": "令牌不正确"}}
                elif req["method"] == "sync" and self.fail_sync:
                    resp = {"id": req["id"], "error": {"kind": "internal", "message": "文档被锁定"}}
                else:
                    resp = {"id": req["id"], "result": {"method": req["method"]}}
                f.write("FreeCAD 的启动信息\n" + PREFIX + json.dumps({"id": -1, "result": 0}) + "\n")
                f.write(PREFIX + json.dumps(resp, ensure_ascii=False) + "\n")
                f.flush()

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)  # 唤醒阻塞在 accept 上的线程
        except OSError:
            pass
        self.sock.close()


def test_bridge_file_location(monkeypatch, tmp_path):
    monkeypatch.delenv("FAP_BRIDGE_FILE", raising=False)
    assert bridge_file().parts[-2:] == (".freecad-ai-parts", "bridge.json")
    monkeypatch.setenv("FAP_BRIDGE_FILE", str(tmp_path / "b.json"))
    assert bridge_file() == tmp_path / "b.json"


def test_client_protocol_and_errors(tmp_path):
    path = tmp_path / "bridge.json"
    with pytest.raises(WorkerError, match="启用桥接") as exc:
        GuiBridgeClient(path=path).call("ping")
    assert exc.value.kind == "unavailable"
    path.write_text("{bad json")
    with pytest.raises(WorkerError, match="启用桥接"):
        GuiBridgeClient(path=path).call("ping")
    fake = FakeBridge(path)
    try:
        assert GuiBridgeClient(path=path).call("ping") == {"method": "ping"}
        assert fake.calls[-1]["token"] == "t0k"
        data = json.loads(path.read_text())
        path.write_text(json.dumps({**data, "token": "wrong"}))
        with pytest.raises(WorkerError, match="令牌不正确") as exc:
            GuiBridgeClient(path=path).call("ping")
        assert exc.value.kind == "auth"
    finally:
        fake.close()
    # 端口已占用但不监听：连接被拒绝（模拟 FreeCAD 已关闭而桥接文件还在）
    idle = socket.socket()
    idle.bind(("127.0.0.1", 0))
    try:
        path.write_text(json.dumps({"host": "127.0.0.1", "port": idle.getsockname()[1], "token": "t0k"}))
        with pytest.raises(WorkerError, match="连不上") as exc:
            GuiBridgeClient(path=path, timeout_s=2).call("ping")
        assert exc.value.kind == "unavailable"
    finally:
        idle.close()


def _mcp(calls, backend_factory):
    async def run():
        out = []
        async with Client(create_server(lambda: LIB, backend_factory)) as c:
            for name, args in calls:
                out.append((await c.call_tool(name, args)).data)
        return out

    return asyncio.run(run())


def test_gui_backend_syncs_view_after_layout_changes(tmp_path):
    path = tmp_path / "bridge.json"
    fake = FakeBridge(path)
    try:
        out = _mcp([("place_component", {"instance": "motor", "component_id": MOTOR}),
                    ("place_component", {"instance": "reducer", "component_id": REDUCER}),
                    ("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"})],
                   lambda: GuiBridgeClient(path=path))
        assert [o["view"] for o in out] == ["已同步到 FreeCAD"] * 3
        syncs = [c for c in fake.calls if c["method"] == "sync"]
        assert len(syncs) == 3 and len(syncs[-1]["params"]["scene"]["connections"]) == 1
    finally:
        fake.close()
    fake = FakeBridge(path, fail_sync=True)
    try:
        out = _mcp([("place_component", {"instance": "motor", "component_id": MOTOR})],
                   lambda: GuiBridgeClient(path=path))
        assert out[0]["view"].startswith("未同步到 FreeCAD") and out[0]["instance"] == "motor"
    finally:
        fake.close()


def test_headless_backend_does_not_sync():
    class Recorder:
        def __init__(self):
            self.calls = []

        def call(self, method, params=None):
            self.calls.append(method)
            return {}

        def close(self):
            pass

    rec = Recorder()
    out = _mcp([("place_component", {"instance": "motor", "component_id": MOTOR})], lambda: rec)
    assert "view" not in out[0] and rec.calls == []


def test_gui_mode_selected_by_env(monkeypatch):
    monkeypatch.setenv("FAP_FREECAD", "gui")
    assert isinstance(layout.default_backend(), GuiBridgeClient)


def test_invalid_mode_reported_on_geometry_call(monkeypatch):
    monkeypatch.setenv("FAP_FREECAD", "cloud")

    async def run():
        async with Client(create_server(lambda: LIB)) as c:
            await c.call_tool("place_component", {"instance": "motor", "component_id": MOTOR})
            try:
                await c.call_tool("check_interference", {})
            except Exception as exc:  # noqa: BLE001
                return str(exc)

    assert "FAP_FREECAD='cloud' 无效" in asyncio.run(run())


# ------------------------------------------------------------------ 真实 FreeCAD 界面


@pytest.fixture(scope="module")
def gui():
    import FreeCAD  # noqa: F401
    import FreeCADGui

    if not os.environ.get("DISPLAY"):
        pytest.skip("没有显示环境")
    FreeCADGui.showMainWindow()
    from PySide import QtWidgets

    return QtWidgets.QApplication.instance()


def _in_thread(app, fn):
    """在后台线程执行 fn，主线程处理 Qt 事件直到完成（模拟 FreeCAD 界面的事件循环）。"""
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=target)
    t.start()
    deadline = time.time() + 120
    while t.is_alive() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    t.join(timeout=1)
    if "error" in box:
        raise box["error"]
    return box["result"]


@pytest.mark.freecad
def test_main_thread_executor(gui):
    from freecad_addon.fc.mainthread import MainThreadExecutor, MainThreadTimeout

    ex = MainThreadExecutor()
    main = threading.current_thread()
    assert _in_thread(gui, lambda: ex.run(lambda: threading.current_thread() is main)) is True
    with pytest.raises(ZeroDivisionError):
        _in_thread(gui, lambda: ex.run(lambda: 1 / 0))
    assert ex.run(lambda: 7) == 7  # 主线程中直接执行
    # 主线程不处理事件时，提交方超时
    with pytest.raises(MainThreadTimeout):
        _in_thread_without_pump(lambda: ex.run(lambda: 1, timeout_s=0.2))


def _in_thread_without_pump(fn):
    box = {}
    t = threading.Thread(target=lambda: box.update(r=_capture(fn)))
    t.start()
    t.join()
    if isinstance(box["r"], BaseException):
        raise box["r"]
    return box["r"]


def _capture(fn):
    try:
        return fn()
    except BaseException as exc:  # noqa: BLE001
        return exc


@pytest.mark.freecad
def test_real_bridge_end_to_end(gui, tmp_path, monkeypatch):
    import FreeCAD

    from freecad_addon.fc.bridge import Bridge

    path = tmp_path / "bridge.json"
    bridge = Bridge(path)
    bridge.start()
    try:
        info = json.loads(path.read_text())
        assert info["port"] == bridge.port and len(info["token"]) == 32
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        client = GuiBridgeClient(path=path)
        assert _in_thread(gui, lambda: client.call("ping")) == {"freecad": "1.0.2"}
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({**info, "token": "0" * 32}))
        with pytest.raises(WorkerError, match="令牌"):
            _in_thread(gui, lambda: GuiBridgeClient(path=bad).call("ping"))

        monkeypatch.setenv("FAP_FREECAD", "gui")
        monkeypatch.setenv("FAP_BRIDGE_FILE", str(path))

        def agent():
            return _mcp([("place_component", {"instance": "motor", "component_id": MOTOR}),
                         ("place_component", {"instance": "reducer", "component_id": REDUCER}),
                         ("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"}),
                         ("check_interference", {})], layout.default_backend)

        out = _in_thread(gui, agent)
        assert out[2]["view"] == "已同步到 FreeCAD" and out[3]["ok"] is True
        doc = FreeCAD.getDocument("FapLayout")
        assert sorted(o.Name for o in doc.Objects) == ["motor", "reducer"]
        assert doc.getObject("reducer").Shape.Placement.Base.z == pytest.approx(20)
    finally:
        bridge.stop()
    assert not path.exists()
    with pytest.raises(WorkerError):
        GuiBridgeClient(path=path).call("ping")
