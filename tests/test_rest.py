"""M4a #69：REST 接口，结果须与 MCP 工具（同一组函数）一致。"""

from __future__ import annotations

import json

import pytest
import yaml
from starlette.testclient import TestClient

from engine.golden import GOLDEN
from kb.library import JsonLibrary
from mcp_server import tools
from mcp_server.server import create_server

LIB = JsonLibrary(GOLDEN / "fixtures")
SYS = yaml.safe_load((GOLDEN / "valid" / "m400-r20-d400.yaml").read_text(encoding="utf-8"))["system"]
M200 = "test.servo_motor.test-vendor.m200"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_server(lambda: LIB).http_app()) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["stage"] == "M4a"


def test_search_and_get(client):
    params = {"rated_torque_nm": {"min": 1}}
    r = client.get("/api/components", params={"category": "servo_motor", "params": json.dumps(params)})
    assert r.status_code == 200
    assert r.json() == tools.search_components(LIB, category="servo_motor", params=params)
    r = client.get(f"/api/components/{M200}")
    assert r.json() == LIB.get(M200)


def test_compatible(client):
    r = client.get(f"/api/components/{M200}/ports/shaft/compatible", params={"include_unknown": "false"})
    assert r.json() == tools.find_compatible(LIB, M200, "shaft", include_unknown=False)


def test_compose_verify_export(client):
    req = SYS["requirement"]
    assert client.post("/api/compose", json={"requirement": req, "top_n": 2}).json() == \
        tools.compose_chain(LIB, req, top_n=2)
    assert client.post("/api/verify", json={"system": SYS, "lang": "en"}).json() == \
        tools.verify_system(LIB, SYS, lang="en")
    assert client.post("/api/export", json={"system": SYS, "format": "bom_json"}).json() == \
        tools.export_system(LIB, SYS, format="bom_json")


@pytest.mark.parametrize(("method", "url", "kw", "code"), [
    ("get", "/api/components/nope", {}, 404),
    ("get", f"/api/components/{M200}/ports/nope/compatible", {}, 404),
    ("get", "/api/components", {"params": {"category": "robot"}}, 400),
    ("get", "/api/components", {"params": {"foo": "1"}}, 400),
    ("get", "/api/components", {"params": {"category": "servo_motor", "params": "{bad"}}, 400),
    ("get", "/api/components", {"params": {"limit": "x"}}, 400),
    ("get", f"/api/components/{M200}/ports/shaft/compatible", {"params": {"via_adapters": "maybe"}}, 400),
    ("post", "/api/verify", {"content": "not json"}, 400),
    ("post", "/api/verify", {"json": [1]}, 400),
    ("post", "/api/verify", {"json": {}}, 400),
    ("post", "/api/verify", {"json": {"system": SYS, "extra": 1}}, 400),
    ("post", "/api/export", {"json": {"system": SYS, "format": "urdf"}}, 400),
])
def test_errors(client, method, url, kw, code):
    r = getattr(client, method)(url, **kw)
    assert r.status_code == code and r.json()["error"]


def test_main_parses_args(monkeypatch):
    import mcp_server.server as srv

    called = {}
    monkeypatch.setattr(srv.mcp, "run", lambda **kw: called.update(kw))
    srv.main(["--http", "--port", "8123"])
    assert called == {"transport": "http", "host": "127.0.0.1", "port": 8123}
    called.clear()
    srv.main([])
    assert called == {}
