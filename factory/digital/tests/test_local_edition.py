# -*- coding: utf-8 -*-
"""本地版（本仓库 ADR-0058）：/api/config 给出 edition，网页据此显示“本地版”；启动脚本生成 .env 的规则。"""
import importlib
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

LOCAL = Path(__file__).resolve().parents[2] / "local"


@pytest.fixture()
def hub(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.ai = None
    yield app_mod
    importlib.reload(app_mod)


def test_edition_in_config(hub, monkeypatch):
    c = TestClient(hub.app)
    assert c.get("/api/config").json()["edition"] == "server"
    monkeypatch.setenv("WQ_EDITION", "local")
    assert c.get("/api/config").json()["edition"] == "local"


def test_start_scripts_use_mock_erp_and_local_edition():
    sh = (LOCAL / "start.sh").read_text(encoding="utf-8")
    ps = (LOCAL / "start.ps1").read_text(encoding="utf-8")
    for s in (sh, ps):
        assert "WQ_EDITION" in s and "mock-erpnext:8091" in s and "--profile" in s and "/api/health" in s
    assert "WQ_SECRET" in sh and "urandom" in sh  # 登录签名密钥随机生成，不用示例值
    web = (Path(__file__).resolve().parents[1] / "web" / "src" / "App.vue").read_text(encoding="utf-8")
    assert "cfg.edition === 'local'" in web and "本地版" in web
