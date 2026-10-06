# -*- coding: utf-8 -*-
"""FreeCAD 选型方案发布到工厂（本仓库 ADR-0058，M10 第 6c 项）：内容检查、版本号、总线消息、列表与详情。"""
import datetime as dt
import importlib

import pytest

from hub import cad_link
from wqbus import envelope

BOM = [{"component_id": "servo_motor.yaskawa-electric-corporation.sgm7j-02a-6", "category": "servo_motor",
        "vendor": "Yaskawa Electric Corporation", "model": "SGM7J-02A", "quantity": 1, "instances": ["motor"],
        "unit_mass_kg": 0.9, "source_docs": ["src-yaskawa-sgm7j"], "all_params_reviewed": True, "library": "public"},
       {"component_id": "reducer.harmonic-drive-llc.csf-25-100-2uh", "category": "reducer", "vendor": "Harmonic Drive LLC",
        "model": "CSF-25-100-2UH", "quantity": 1, "instances": ["reducer"], "unit_mass_kg": None,
        "source_docs": ["src-hd-csg-csf-gear-units"], "all_params_reviewed": True, "library": "enterprise"}]


class FakeDB:
    """内存里的 cad_design 表：只实现本模块用到的三条 SQL。"""

    def __init__(self):
        self.rows = []

    def one(self, sql, args):
        mode, code = args
        revs = [r["revision"] for r in self.rows if r["mode"] == mode and r["code"] == code]
        return {"r": max(revs) if revs else None}

    def x(self, sql, args):
        import json
        mode, code, rev, name, author, data = args
        self.rows.append({"mode": mode, "code": code, "revision": rev, "name": name, "author": author,
                          "ts": dt.datetime.now(dt.timezone.utc), "data": json.loads(data)})
        return 1

    def q(self, sql, args):
        if "distinct on" in sql:
            (mode,) = args
            last = {}
            for r in self.rows:
                if r["mode"] == mode and (r["code"] not in last or r["revision"] > last[r["code"]]["revision"]):
                    last[r["code"]] = r
            return list(last.values())
        mode, code = args
        return sorted((r for r in self.rows if r["mode"] == mode and r["code"] == code), key=lambda r: -r["revision"])


def test_validate():
    ok = cad_link.validate({"code": "JOINT-2", "name": "第 2 关节", "bom": BOM})
    assert ok["code"] == "JOINT-2" and len(ok["bom"]) == 2 and ok["files"] == []
    for bad in ({"code": "a b", "name": "x", "bom": BOM}, {"code": "J", "name": " ", "bom": BOM},
                {"code": "J", "name": "x", "bom": []}, {"code": "J", "name": "x", "bom": [{"model": "M"}]},
                {"code": "J", "name": "x", "bom": [dict(BOM[0], quantity=0)]},
                {"code": "J", "name": "x", "bom": BOM, "files": [{"url": "http://evil/x.step"}]}):
        with pytest.raises(cad_link.CadError):
            cad_link.validate(bad)


def test_release_versions_and_bus_message():
    db, sent = FakeDB(), []

    def emit(tp, type_, data):
        sent.append((tp, envelope.make(type_, "freecad", data, mode="prod")))

    body = {"code": "JOINT-2", "name": "第 2 关节", "bom": BOM, "checks": {"overall": "unknown"},
            "files": [{"kind": "step", "name": "joint.step", "url": "/api/files/abc", "sha256": "abc", "size": 10}]}
    assert cad_link.release(db, emit, "prod", "张工", body)["revision"] == 1
    assert cad_link.release(db, emit, "prod", "张工", dict(body, note="换减速器"))["revision"] == 2
    assert cad_link.release(db, emit, "teach", "李工", body)["revision"] == 1  # 演示与生产分开计
    tp, msg = sent[0]
    assert tp == "wq/gearbox/design/cad-joint-2/release" and msg["type"] == "cad.release"
    assert msg["data"]["checks_overall"] == "unknown" and msg["data"]["bom"][1]["library"] == "enterprise"
    lst = cad_link.designs(db, "prod")
    assert [(d["code"], d["revision"], d["parts"]) for d in lst] == [("JOINT-2", 2, 2)]
    d = cad_link.design(db, "prod", "JOINT-2")
    assert d["revision"] == 2 and [h["revision"] for h in d["history"]] == [2, 1] and d["note"] == "换减速器"
    assert cad_link.design(db, "prod", "NOPE") is None


def test_endpoints(monkeypatch):
    fastapi = pytest.importorskip("fastapi")  # noqa: F841
    from fastapi.testclient import TestClient
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_SECRET", "test-secret")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.db = FakeDB()
    sent = []

    class Bus:
        def publish_msg(self, tp, msg):
            sent.append((tp, msg))

    class Hist:
        def handle(self, tp, msg):
            pass

    app_mod.H.bus, app_mod.H.hist = Bus(), Hist()
    c = TestClient(app_mod.app)
    tok = c.post("/api/login", json={"name": "张工", "role": "engineer", "mode": "prod"}).json()["token"]
    h = {"x-wq-token": tok}
    assert c.post("/api/cad/release", json={"code": "J", "name": "x", "bom": []}, headers=h).status_code == 422
    r = c.post("/api/cad/release", json={"code": "JOINT-2", "name": "第 2 关节", "bom": BOM}, headers=h)
    assert r.status_code == 200 and r.json()["revision"] == 1
    assert c.get("/api/cad/designs", headers=h).json()[0]["code"] == "JOINT-2"
    assert c.get("/api/cad/designs/JOINT-2", headers=h).json()["bom"][0]["model"] == "SGM7J-02A"
    assert c.get("/api/cad/designs/NOPE", headers=h).status_code == 404
    assert sent and sent[0][1]["type"] == "cad.release" and sent[0][1]["mode"] == "prod"
    assert c.post("/api/cad/release", json={"code": "J", "name": "x", "bom": BOM}).status_code in (401, 403)
    importlib.reload(app_mod)
