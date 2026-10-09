# -*- coding: utf-8 -*-
"""浮动席位接口（ADR-0066 第 6 项）：授权文件装在工厂服务器上，FreeCAD 工作台来租、续、还。"""
import datetime as dt
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub import seats_api
from licensing import issue
from licensing.license import sign


def _setup(tmp_path, **kw):
    priv, pub = issue.keygen()
    lic = {"id": "L", "key_id": "t", "licensee": "示例机械", "issued": "2026-10-01", "expires": "2027-09-30",
           "kind": "floating", "seats": 2, "features": ["seats", "parts-subscription"]}
    lic.update(kw)
    path = tmp_path / "license.json"
    path.write_text(json.dumps(sign(lic, priv)), encoding="utf-8")
    clock = {"t": 0.0}
    S = seats_api.Seats(path, public_keys={"t": pub}, clock=lambda: clock["t"], today=lambda: dt.date(2026, 10, 9))
    app = FastAPI()
    seats_api.mount(app, S)
    return TestClient(app), clock, path, priv


def test_lease_renew_release_and_full(tmp_path):
    c, clock, _, _ = _setup(tmp_path)
    st = c.get("/api/seats").json()
    assert st["licensed"] and st["seats"] == 2 and st["used"] == 0
    a = c.post("/api/seats/lease", json={"client_id": "pc-a", "user": "张三", "host": "PC-A"}).json()
    assert a["licensee"] == "示例机械" and "parts-subscription" in a["features"]
    c.post("/api/seats/lease", json={"client_id": "pc-b", "user": "李四", "host": "PC-B"})
    r = c.post("/api/seats/lease", json={"client_id": "pc-c", "user": "王五", "host": "PC-C"})
    assert r.status_code == 409 and "席位已满" in r.json()["detail"]
    assert c.post("/api/seats/renew", json={"lease_id": a["lease_id"]}).status_code == 200
    assert c.post("/api/seats/release", json={"lease_id": a["lease_id"]}).json()["released"]
    assert c.post("/api/seats/lease", json={"client_id": "pc-c", "user": "王五", "host": "PC-C"}).status_code == 200
    clock["t"] += 3600                                       # 一小时没续租：全部收回
    assert c.post("/api/seats/renew", json={"lease_id": a["lease_id"]}).status_code == 404
    assert c.get("/api/seats").json()["used"] == 0


def test_no_or_bad_license(tmp_path):
    S = seats_api.Seats(tmp_path / "none.json", public_keys={})
    app = FastAPI()
    seats_api.mount(app, S)
    c = TestClient(app)
    assert c.get("/api/seats").json()["licensed"] is False
    assert c.post("/api/seats/lease", json={"client_id": "x"}).status_code == 403
    c, _, path, _ = _setup(tmp_path, expires="2026-10-01")
    r = c.post("/api/seats/lease", json={"client_id": "x"})
    assert r.status_code == 403 and "到期" in r.json()["detail"]
    c, _, path, _ = _setup(tmp_path)                       # 正常的一份，改了席位数 → 签名不对
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["license"]["seats"] = 100
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert c.post("/api/seats/lease", json={"client_id": "x"}).status_code == 403


def test_node_license_gives_no_seats(tmp_path):
    c, _, _, _ = _setup(tmp_path, kind="node", node="AAAA", seats=1)
    st = c.get("/api/seats").json()
    assert st["licensed"] is False and "浮动席位" in st["reason"]
