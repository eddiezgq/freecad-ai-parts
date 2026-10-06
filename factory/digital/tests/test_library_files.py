# -*- coding: utf-8 -*-
"""零件库文件（第 2 轮 L14、约定 R6）：/library/ 下的文件、跨域头、缓存、越界。"""
import importlib
import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    lib = tmp_path / "library"
    (lib / "2026.10.0" / "A-BRG-DG").mkdir(parents=True)
    (lib / "latest.json").write_text(json.dumps({"version": "2026.10.0"}), encoding="utf-8")
    (lib / "2026.10.0" / "A-BRG-DG" / "6207.glb").write_bytes(b"glTF")
    (tmp_path / "secret.txt").write_text("no")
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_LIBRARY_DIR", str(lib))
    monkeypatch.setenv("WQ_LIBRARY_ORIGINS", "https://learn.example.com,https://factory.example.com")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    return TestClient(app_mod.app)


def test_files_cache_and_cors(client):
    r = client.get("/library/latest.json", headers={"Origin": "https://learn.example.com"})
    assert r.status_code == 200 and r.json()["version"] == "2026.10.0"
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["access-control-allow-origin"] == "https://learn.example.com"
    r = client.get("/library/2026.10.0/A-BRG-DG/6207.glb", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200 and r.content == b"glTF"
    assert r.headers["content-type"] == "model/gltf-binary"
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.head("/library/latest.json").status_code == 200
    assert client.options("/library/latest.json", headers={"Origin": "https://factory.example.com"}).status_code == 204


def test_other_origins_get_no_cors(client):
    r = client.get("/library/latest.json", headers={"Origin": "https://evil.example.org"})
    assert r.status_code == 200 and "access-control-allow-origin" not in r.headers


def test_no_escape_and_404(client):
    for p in ["/library/../secret.txt", "/library/%2e%2e/secret.txt", "/library/..%2fsecret.txt"]:
        assert client.get(p).content != b"no", p                  # 读不到库目录以外的文件
    for p in ["/library/.incoming/x", "/library/nope.json"]:
        assert client.get(p).status_code == 404, p
    from hub import library
    assert library.resolve("../secret.txt") is None and library.resolve("2026.10.0/../../secret.txt") is None
