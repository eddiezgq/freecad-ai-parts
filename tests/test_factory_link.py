"""发布到工厂（ADR-0058，M10 第 6c 项）：发布内容、与工厂枢纽的接口约定（用工厂的 cad_link 检查）、登录上传发布流程。

工厂枢纽用本机回环地址上的假服务代替（不联网）；内容检查直接用 factory/digital/hub/cad_link.py，保证两边的约定一致。
"""

from __future__ import annotations

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

import pytest

from freecad_addon.core import factory_link
from kb.library import JsonLibrary

ROOT = Path(__file__).resolve().parent.parent
LIB = JsonLibrary(ROOT / "data" / "library")
M = "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6"
R = "reducer.harmonic-drive-llc.csf-25-100-2uh"
LAYOUT = {"instances": [{"instance": "motor", "component": M}, {"instance": "reducer", "component": R}],
          "connections": [{"a": "motor.mount_flange", "b": "reducer.motor_flange"}]}


def _cad_link():
    spec = importlib.util.spec_from_file_location("cad_link", ROOT / "factory" / "digital" / "hub" / "cad_link.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_payload_matches_factory_contract():
    data = factory_link.payload(LAYOUT, LIB.get, code="JOINT-2", name="第 2 关节",
                                origin=lambda cid: "enterprise" if cid == R else "public",
                                requirement={"output_torque_cont_nm": 25, "output_speed_rpm": 30},
                                checks={"overall": "unknown", "checks": [{"check": "C3", "status": "unknown"}]})
    assert [r["model"].split("（")[0] for r in data["bom"]] == ["SGM7J-02A", "CSF-25-100-2UH"]
    assert data["bom"][1]["library"] == "enterprise" and data["checks"]["overall"] == "unknown"
    assert "定制" in data["note"] or data["note"] == ""  # CSF-2UH 的电机法兰按配套件定制时附定制要求
    ok = _cad_link().validate(data)  # 工厂枢纽接受
    assert ok["code"] == "JOINT-2" and len(ok["bom"]) == 2
    with pytest.raises(factory_link.FactoryError):
        factory_link.payload({"instances": []}, LIB.get, code="X", name="x")


class _Hub(BaseHTTPRequestHandler):
    received: ClassVar[list] = []
    logins: ClassVar[list] = []
    cad = None

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        if self.path == "/api/login":
            b = json.loads(raw)
            _Hub.logins.append(b)
            return self._send(200, {"token": f"tok-{b['mode']}"})
        if not self.headers.get("x-wq-token", "").startswith("tok-"):
            return self._send(401, {"detail": "请先登录"})
        if self.path == "/api/files":
            assert b"ISO-10303" in raw
            return self._send(200, {"url": "/api/files/abc", "sha256": "abc", "size": len(raw)})
        if self.path == "/api/cad/release":
            body = json.loads(raw)
            try:
                _Hub.cad.validate(body)
            except _Hub.cad.CadError as e:
                return self._send(422, {"detail": str(e)})
            _Hub.received.append((self.headers["x-wq-token"], body))
            return self._send(200, {"code": body["code"], "revision": len(_Hub.received), "name": body["name"]})
        return self._send(404, {"detail": "no"})


@pytest.fixture()
def hub():
    _Hub.received, _Hub.logins, _Hub.cad = [], [], _cad_link()
    srv = HTTPServer(("127.0.0.1", 0), _Hub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_publish_flow(hub, tmp_path):
    step = tmp_path / "layout.step"
    step.write_text("ISO-10303-21;\nEND-ISO-10303-21;\n")
    data = factory_link.payload(LAYOUT, LIB.get, code="JOINT-2", name="第 2 关节")
    out = factory_link.publish(factory_link.HubClient(hub), "张工", "prod", data, step)
    assert out == {"code": "JOINT-2", "revision": 1, "name": "第 2 关节"}
    token, body = _Hub.received[0]
    assert token == "tok-prod" and _Hub.logins[0] == {"name": "张工", "role": "engineer", "mode": "prod"}
    assert body["files"][0]["url"] == "/api/files/abc"
    with pytest.raises(factory_link.FactoryError, match="422"):
        factory_link.publish(factory_link.HubClient(hub), "张工", "prod", {**data, "code": "坏 编号"})
    with pytest.raises(factory_link.FactoryError, match="发布人"):
        factory_link.publish(factory_link.HubClient(hub), " ", "prod", data)


def test_unreachable_factory():
    with pytest.raises(factory_link.FactoryError, match="连不上工厂"):
        factory_link.HubClient("http://127.0.0.1:9", timeout=2).login("张工")
