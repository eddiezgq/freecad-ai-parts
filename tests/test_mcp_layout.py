"""M4b #85：FreeCAD 组的 MCP 工具与 REST 接口（place_component、connect_ports、check_interference、snapshot）。

不需要 FreeCAD 的测试用假后端；末尾标记 freecad 的测试经真实 headless worker 运行。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys

import pytest
import yaml
from fastmcp import Client
from fastmcp.exceptions import ToolError
from starlette.testclient import TestClient

from engine.golden import GOLDEN
from freecad_addon.core.scene import Scene
from freecad_addon.fc.client import WorkerError
from kb.library import JsonLibrary
from mcp_server import layout
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
SYS = yaml.safe_load((GOLDEN / "valid" / "m750-r25-d750.yaml").read_text(encoding="utf-8"))["system"]
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")


class FakeBackend:
    def __init__(self, error: WorkerError | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.error = error
        self.closed = False

    def call(self, method, params=None):
        self.calls.append((method, params))
        if self.error:
            raise self.error
        if method == "interference":
            return {"ok": True, "threshold_mm3": params["threshold_mm3"], "interferences": [], "pass_through": [],
                    "instances": sorted(i["instance"] for i in params["scene"]["instances"])}
        return {"view": params["view"], "width": params["width"], "height": params["height"],
                "png_base64": base64.b64encode(PNG).decode()}

    def close(self):
        self.closed = True


def _run(server, calls):
    async def go():
        out = []
        async with Client(server) as c:
            for name, args in calls:
                try:
                    res = await c.call_tool(name, args)
                    out.append(res)
                except ToolError as exc:
                    out.append(exc)
        return out

    return asyncio.run(go())


def _layout_calls() -> list:
    calls = [("place_component", {"instance": i["instance"], "component_id": i["component"]})
             for i in SYS["components"]]
    calls += [("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange"}),
              ("connect_ports", {"a": "motor.shaft", "b": "reducer.input_bore"}),
              ("place_component", {"instance": "drive", "position_mm": [150, 0, -60]})]
    return calls


def test_layout_via_mcp_equals_core():
    res = _run(create_server(lambda: LIB, lambda: None), _layout_calls())
    final = res[-1].data["layout"]
    s = Scene()
    for i in SYS["components"]:
        s.place(i["instance"], LIB.get(i["component"]))
    s.connect("motor.mount_flange", "reducer.motor_flange")
    s.connect("motor.shaft", "reducer.input_bore")
    pos = {i["instance"]: i["position_mm"] for i in final["instances"]}
    assert pos == {"drive": [150.0, 0.0, -60.0], "motor": [0.0, 0.0, 0.0], "reducer": [0.0, 0.0, 20.0]}
    assert pos["reducer"] == s.pose("reducer").to_dict()["position_mm"]
    assert [c["kind"] for c in final["connections"]] == ["face", "cylinder"]
    assert res[4].data["check"]["engagement_mm"] == 30.0


@pytest.mark.parametrize(("name", "args", "msg"), [
    ("place_component", {"instance": "m", "component_id": "test.nope.x.y"}, "组件不存在"),
    ("place_component", {"instance": "Motor", "component_id": "test.servo_motor.test-vendor.m400"}, "小写字母"),
    ("place_component", {"instance": "ghost"}, "须给出组件"),
    ("place_component", {"instance": "ghost", "remove": True}, "没有实例"),
    ("place_component", {"instance": "motor", "position_mm": [1, 2]}, "3 个数"),
    ("place_component", {"instance": "motor", "rotation_axis": [0, 0, 0], "rotation_deg": 5}, "零向量"),
    ("place_component", {"instance": "motor", "remove": True, "position_mm": [0, 0, 0]}, "remove"),
    ("connect_ports", {"a": "motor.power_in", "b": "drive.motor_out"}, "不是机械端口"),
    ("connect_ports", {"a": "motor.shaft", "b": "reducer.motor_flange"}, "不能配合"),
    ("connect_ports", {"a": "motor.mount_flange", "b": "reducer.motor_flange", "offset_mm": 2}, "offset_mm"),
    ("snapshot", {"view": "diagonal"}, "未知视角"),
])
def test_layout_tool_errors(name, args, msg):
    setup = [("place_component", {"instance": i["instance"], "component_id": i["component"]})
             for i in SYS["components"]]
    res = _run(create_server(lambda: LIB, FakeBackend), [*setup, (name, args)])
    assert isinstance(res[-1], ToolError) and msg in str(res[-1])


def test_geometry_tools_need_backend():
    res = _run(create_server(lambda: LIB, lambda: None), [
        ("check_interference", {}),
        ("place_component", {"instance": "motor", "component_id": "test.servo_motor.test-vendor.m400"}),
        ("check_interference", {}), ("snapshot", {})])
    assert "场景为空" in str(res[0])
    assert "未连接 FreeCAD" in str(res[2]) and "FAP_FREECAD=headless" in str(res[2])
    assert "未连接 FreeCAD" in str(res[3])


def test_backend_receives_full_scene_and_image_is_returned():
    fake = FakeBackend()
    res = _run(create_server(lambda: LIB, lambda: fake), [
        *_layout_calls(), ("check_interference", {"threshold_mm3": 2.5}),
        ("snapshot", {"view": "top", "width": 320, "height": 200})])
    method, params = fake.calls[0]
    assert method == "interference" and params["threshold_mm3"] == 2.5
    scene = Scene.from_dict(params["scene"])
    assert sorted(scene.instances) == ["drive", "motor", "reducer"] and len(scene.connections) == 2
    assert res[-2].data["ok"] is True
    image, text = res[-1].content
    assert image.type == "image" and image.mime_type == "image/png" and base64.b64decode(image.data) == PNG
    meta = json.loads(text.text)
    assert meta["view"] == "top" and meta["width"] == 320 and len(meta["layout"]["instances"]) == 3
    assert fake.calls[1][1]["view"] == "top"


@pytest.mark.parametrize(("kind", "msg"), [
    ("unavailable", "FreeCAD 后端出错（unavailable）"), ("timeout", "FreeCAD 后端出错（timeout）"),
    ("input", "坏场景"), ("snapshot", "坏场景")])
def test_worker_errors_are_reported(kind, msg):
    fake = FakeBackend(WorkerError(kind, "坏场景"))
    res = _run(create_server(lambda: LIB, lambda: fake), [
        ("place_component", {"instance": "motor", "component_id": "test.servo_motor.test-vendor.m400"}),
        ("check_interference", {})])
    assert msg in str(res[-1])


def test_default_backend(monkeypatch):
    monkeypatch.delenv("FAP_FREECAD", raising=False)
    assert layout.default_backend() is None
    monkeypatch.setenv("FAP_FREECAD", "none")
    assert layout.default_backend() is None
    monkeypatch.setenv("FAP_FREECAD", "headless")
    assert isinstance(layout.default_backend(), layout.HeadlessWorker)
    monkeypatch.setenv("FAP_FREECAD", "gui-please")
    with pytest.raises(layout.ToolBackendError, match="无效"):
        layout.default_backend()


def test_rest_layout_matches_mcp():
    fake = FakeBackend()
    with TestClient(create_server(lambda: LIB, lambda: None).http_app()) as c:
        for name, args in _layout_calls():
            path = "/api/layout/place" if name == "place_component" else "/api/layout/connect"
            r = c.post(path, json=args)
            assert r.status_code == 200, r.text
        rest_state = c.get("/api/layout").json()
        assert c.post("/api/layout/interference", json={}).status_code == 503
        assert c.post("/api/layout/place", json={"instance": "x", "bogus": 1}).status_code == 400
        assert c.post("/api/layout/place", json={"instance": "x", "component_id": "test.no.a.b"}).status_code == 404
        assert c.post("/api/layout/place", json={"instance": "motor", "remove": "yes"}).status_code == 400
    mcp_state = _run(create_server(lambda: LIB, lambda: None), _layout_calls())[-1].data["layout"]
    assert rest_state == mcp_state
    with TestClient(create_server(lambda: LIB, lambda: fake).http_app()) as c:
        c.post("/api/layout/place", json={"instance": "motor", "component_id": "test.servo_motor.test-vendor.m400"})
        r = c.post("/api/layout/snapshot", json={"view": "front", "width": 100, "height": 100})
        assert r.status_code == 200 and base64.b64decode(r.json()["png_base64"]) == PNG


# ------------------------------------------------------------------ 真实 FreeCAD


@pytest.mark.freecad
def test_agent_style_layout_with_real_freecad():
    if "FreeCAD" in sys.modules or os.environ.get("FAP_REQUIRE_FREECAD") == "1":
        os.environ.setdefault("FAP_FREECAD_PYTHON", sys.executable)
    w = layout.HeadlessWorker(timeout_s=180)
    try:
        calls = _layout_calls()[:-1] + [("check_interference", {}),
                                         ("place_component", {"instance": "drive", "position_mm": [150, 0, -60]}),
                                         ("check_interference", {}), ("snapshot", {"width": 200, "height": 160})]
        res = _run(create_server(lambda: LIB, lambda: w), calls)
        before, after = res[-4].data, res[-2].data
        assert not before["ok"] and {(i["a"], i["b"]) for i in before["interferences"]} == {
            ("drive", "motor"), ("drive", "reducer")}
        assert after["ok"] and after["interferences"] == []
        image = res[-1].content[0]
        assert image.type == "image" and base64.b64decode(image.data)[:4] == b"\x89PNG"
    finally:
        w.close()
