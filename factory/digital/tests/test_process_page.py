# -*- coding: utf-8 -*-
"""第 13 轮 8.8（3a）：“工艺规程与 AI 评审”页的接口——下载参照工艺规程原文，上传 YAML 预检（不记录）；
YAML 里的日期等转成文字；不是工艺规程的给出明白的错误。枢纽不启动总线和数据库（WQ_HUB_NO_START=1），只测不碰数据库的部分。"""
import importlib
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "local")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    tok = app_mod._sign({"name": "学生甲", "uid": "S1", "teacher": False, "role": "engineer", "mode": "prod"})
    c.headers["x-wq-token"] = tok
    yield c
    os.environ.pop("WQ_AUTH", None)
    importlib.reload(app_mod)


def test_reference_and_precheck(client):
    r = client.get("/api/process/reference/SH-301")
    assert r.status_code == 200
    text = r.json()["yaml"]
    assert "operations" in text and "tolerance_chart" in text
    ok = client.post("/api/process/check", json={"yaml": text}).json()
    assert not [f for f in ok["findings"] if f["level"] == "error"]
    plan = yaml.safe_load(text)
    next(c for c in plan["tolerance_chart"]["cuts"] if abs(c["seq"] - 40.3) < 1e-9).update(es=0.3, ei=-0.3)
    plan["doc"]["date"] = __import__("datetime").date(2026, 10, 5)          # 不带引号的日期
    bad = client.post("/api/process/check", json={"yaml": yaml.safe_dump(plan, allow_unicode=True)}).json()
    assert any(f["rule"] == "尺寸链" and f["level"] == "error" for f in bad["findings"])
    assert bad["suggested_score"] < ok["suggested_score"]


def test_bad_uploads(client):
    assert client.post("/api/process/check", json={"yaml": "a: [1, 2"}).status_code == 400
    r = client.post("/api/process/check", json={"yaml": "x: 1"})
    assert r.status_code == 400 and "工艺规程" in r.json()["detail"]
    assert client.get("/api/process/reference/NOPE").status_code == 404
