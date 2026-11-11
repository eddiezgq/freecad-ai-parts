# -*- coding: utf-8 -*-
"""第 128 轮（阶段 C1）：在页面上改工艺卡——边改边查（卡片能否生成 + AI 预检）、卡片导出 PDF（经学习平台网关的在线文档服务）、
每人每个零件一份草稿（要本机 PostgreSQL，没有就跳过草稿那一条）。"""
import importlib
import os

import pytest
import yaml

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_test_pe"
REF = os.path.join(os.path.dirname(__file__), "..", "std", "SH-301_process.yaml")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_AUTH", "local")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    c = TestClient(app_mod.app)
    c.headers["x-wq-token"] = app_mod._sign({"name": "学生甲", "uid": "S1", "teacher": False, "role": "engineer", "mode": "teach"})
    c.app_mod = app_mod
    yield c
    os.environ.pop("WQ_AUTH", None)
    importlib.reload(app_mod)


def plan():
    return yaml.safe_load(open(REF, encoding="utf-8"))


def test_live_check_finds_card_problems_and_review_errors(client):
    ok = client.post("/api/process/live", json={"plan": plan()}).json()
    assert ok["problems"] == [] and not [f for f in ok["findings"] if f["level"] == "error"]
    p = plan()
    for o in p["operations"]:
        o.pop("final_inspection", None)
    p["operations"][1].pop("minutes")
    bad = client.post("/api/process/live", json={"plan": p}).json()
    assert any("终检" in x for x in bad["problems"]) and any("工时" in x for x in bad["problems"])
    v1 = {"item": "SH-301", "operations": [{"seq": 10, "operation": "下料 Sawing", "workstation": "带锯床 SAW-01", "minutes": 3}]}
    assert "v2" in client.post("/api/process/live", json={"plan": v1}).json()["problems"][0]
    assert client.post("/api/process/live", json={"plan": {"x": 1}}).status_code == 400


def test_cards_pdf_goes_through_the_gateway(client, monkeypatch):
    p = plan()
    monkeypatch.delenv("WQ_PDF_URL", raising=False)
    assert client.post("/api/process/cards?fmt=pdf", json=p).status_code == 503       # not set up: export Word instead
    import httpx
    sent = {}

    def fake_post(url, content=None, headers=None, timeout=None):
        sent.update(url=url, auth=headers["Authorization"], docx=content[:2])
        return httpx.Response(200, content=b"%PDF-1.7 cards")
    monkeypatch.setenv("WQ_PDF_URL", "http://wq-gateway:8000/api/v1/internal/docx-to-pdf")
    monkeypatch.setenv("WQ_FACTORY_READ_KEY", "rk")
    monkeypatch.setattr(httpx, "post", fake_post)
    r = client.post("/api/process/cards?fmt=pdf", json=p)
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and "pdf" in r.headers["content-disposition"]
    assert sent == {"url": "http://wq-gateway:8000/api/v1/internal/docx-to-pdf", "auth": "Bearer rk", "docx": b"PK"}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(502, content=b"x"))
    assert client.post("/api/process/cards?fmt=pdf", json=p).status_code == 502


def test_drafts_per_person_and_part(client):
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(base, autocommit=True) as c:
            c.execute("drop database if exists wq_test_pe")
            c.execute("create database wq_test_pe")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    client.app_mod.H.db = d
    r = client.get("/api/process/drafts/SH-301").json()
    assert r["draft"] is False and r["plan"]["doc"]["number"] == "GY-SH301"                  # no draft yet: the reference
    p = r["plan"]
    p["operations"][1]["steps"][0]["vc"] = 110
    assert client.put("/api/process/drafts/SH-301", json={"plan": p}).json()["ok"]
    r = client.get("/api/process/drafts/SH-301").json()
    assert r["draft"] and r["plan"]["operations"][1]["steps"][0]["vc"] == 110
    assert client.get("/api/process/drafts/SH-301?start=reference").json()["plan"]["operations"][1]["steps"][0]["vc"] == 120
    other = client.app_mod._sign({"name": "学生乙", "uid": "S2", "teacher": False, "role": "engineer", "mode": "teach"})
    assert client.get("/api/process/drafts/SH-301", headers={"x-wq-token": other}).json()["draft"] is False   # each person their own
    assert client.put("/api/process/drafts/SH-101", json={"plan": p}).status_code == 400                     # the part must match
    assert client.delete("/api/process/drafts/SH-301").json()["ok"]
    assert client.get("/api/process/drafts/SH-301").json()["draft"] is False
    assert client.get("/api/process/drafts/NOPE").status_code == 404
