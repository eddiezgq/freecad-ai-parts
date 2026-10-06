# -*- coding: utf-8 -*-
"""第 8 轮企业版：通用发布、STEP→网页模型、两版差异、提交—批注—审批—生效。需要本机 PostgreSQL（WQ_TEST_DB）。"""
import os
import tempfile

import pytest

import wqbus

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_plm_test"


@pytest.fixture()
def db():
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("build123d")
    try:
        with psycopg.connect(DSN.rsplit("/", 1)[0] + "/postgres", autocommit=True) as c:
            c.execute("drop database if exists wq_plm_test with (force)")
            c.execute("create database wq_plm_test")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    d = DB(DSN)
    d.init()
    return d


def _emitter(db):
    out = []

    def emit(tp, type_, data):
        msg = wqbus.make(type_, "plm", data, mode=_emitter.mode)
        db.insert_message(tp, msg)
        out.append((tp, msg))
    return emit, out


def _step(length=40.0, hole=0.0):
    import build123d as bd
    s = bd.Box(length, 20, 10)
    if hole:
        s = s - bd.Cylinder(hole, 20)
    p = os.path.join(tempfile.mkdtemp(), "p.step")
    bd.export_step(s, p)
    return open(p, "rb").read()


def test_item_info():
    from hub import plm
    assert plm.item_info("SH-301")["operations"][0].startswith("下料")
    assert plm.item_info("NO-SUCH") is None
    assert plm.item_info("X-1", lambda i: "外部物料")["name"] == "外部物料"


def test_teach_mode_releases_at_once(db):
    from hub import plm
    _emitter.mode = "teach"
    emit, out = _emitter(db)
    s = plm.submit(db, emit, "teach", "工艺员·A", "u1", "CAP-52-T", step=_step(), note="首版")
    assert s["status"] == "approved" and s["revision"] == 2
    assert [m["type"] for _, m in out] == ["design.release"]
    kinds = {f["kind"] for f in s["files"]}
    assert {"step", "glb"} <= kinds
    glb = plm.load_file(db, next(f for f in s["files"] if f["kind"] == "glb")["url"])
    assert glb[:4] == b"glTF"


def test_prod_review_flow(db):
    from hub import plm
    _emitter.mode = "prod"
    emit, out = _emitter(db)
    first = plm.submit(db, emit, "prod", "工艺员·A", "u1", "CAP-52-T", step=_step(40), note="首版")
    assert first["status"] == "pending" and out[-1][1]["type"] == "design.submit"
    with pytest.raises(PermissionError):                                  # 不能批准自己的
        plm.approve(db, emit, first["id"], "审批人·A", approver_uid="u1")
    plm.comment(db, first["id"], "审批人·B", "孔位要再核一下", {"x": 1, "y": 2, "z": 3})
    with pytest.raises(ValueError):                                       # 有没处理的批注
        plm.approve(db, emit, first["id"], "审批人·B", approver_uid="u2")
    cid = plm.get(db, first["id"])["comments"][0]["id"]
    plm.resolve_comment(db, first["id"], cid)
    ok = plm.approve(db, emit, first["id"], "审批人·B", "可以", approver_uid="u2")
    assert ok["status"] == "approved" and ok["revision"] == 2
    assert [m["type"] for _, m in out[-2:]] == ["design.release", "design.review"]
    rel = out[-2][1]["data"]
    assert rel["revision"] == 2 and {f["kind"] for f in rel["files"]} == {"step"}         # 网页模型不挂到 ERPNext

    # 第二版：长 40 → 50、开孔；差异标出；带加工程序
    second = plm.submit(db, emit, "prod", "工艺员·A", "u1", "CAP-52-T", step=_step(50, 3), note="加长并开孔",
                        gcode=b"G0 X0\n", operation="铣键槽 Keyway milling")
    assert second["diff"]["changed"] and second["diff"]["changed_area_mm2"] > 0
    assert any(f["kind"] == "diff" for f in second["files"]) and second["gcode"]["machine"] == "key-01"
    with pytest.raises(ValueError):                                       # 退回要写原因
        plm.decide(db, emit, second["id"], "审批人·B", "rejected", "")
    r = plm.decide(db, emit, second["id"], "审批人·B", "rejected", "孔太小")
    assert r["status"] == "rejected" and out[-1][1]["data"]["decision"] == "rejected"
    with pytest.raises(ValueError):
        plm.approve(db, emit, second["id"], "审批人·B", approver_uid="u2")

    third = plm.submit(db, emit, "prod", "工艺员·A", "u1", "CAP-52-T", step=_step(50, 4), note="孔改大")
    done = plm.approve(db, emit, third["id"], "审批人·B", approver_uid="u2")
    assert done["revision"] == 3 and plm.current_revision(db, "prod", "CAP-52-T") == 3
    assert plm.current_revision(db, "teach", "CAP-52-T") == 1                # 两种模式分开记


def test_gcode_needs_operation_and_bad_step(db):
    from hub import plm
    _emitter.mode = "prod"
    emit, _ = _emitter(db)
    with pytest.raises(ValueError):
        plm.submit(db, emit, "prod", "a", "u1", "CAP-52-T", step=_step(), gcode=b"G0")
    with pytest.raises(ValueError):
        plm.submit(db, emit, "prod", "a", "u1", "CAP-52-T", step=b"not a step file")


def test_role_rules(monkeypatch):
    """学生：教学模式四个岗位；企业成员：生产模式只用授权的角色；老师：全部"""
    import importlib
    from fastapi import HTTPException
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    import hub.app as A
    A = importlib.reload(A)
    A.check_allowed(True, "approver", "prod")
    A.check_allowed(False, "planner", "teach")
    A.check_allowed(False, "approver", "prod", ["approver", "engineer"])
    for args in ((False, "approver", "teach"), (False, "planner", "prod"), (False, "sales", "prod", ["approver"]),
                 (False, "manager", "prod", ["manager"]) if False else (False, "manager", "teach")):
        with pytest.raises(HTTPException):
            A.check_allowed(*args)


def test_class_factory_bits(monkeypatch):
    """第 10 轮：Caddy 只给已建的班级工厂发证书；班级任课老师按老师对待"""
    import importlib
    from fastapi.testclient import TestClient
    monkeypatch.setenv("WQ_HUB_NO_START", "1")
    monkeypatch.setenv("WQ_CLASS_IDS", "pilot g2")
    monkeypatch.setenv("WQ_FACTORY_NAME", "试点班")
    import hub.app as A
    A = importlib.reload(A)
    c = TestClient(A.app)
    assert c.get("/api/caddy/ask", params={"domain": "pilot.factory.example.com"}).status_code == 200
    assert c.get("/api/caddy/ask", params={"domain": "g2.erp.example.com"}).status_code == 200
    for d in ("evil.factory.example.com", "pilot.example.com", "pilot.learn.example.com"):
        assert c.get("/api/caddy/ask", params={"domain": d}).status_code == 404
    assert c.get("/api/config").json()["factory_name"] == "试点班"
    for k in ("WQ_CLASS_IDS", "WQ_FACTORY_NAME"):
        monkeypatch.delenv(k)
    importlib.reload(A)
