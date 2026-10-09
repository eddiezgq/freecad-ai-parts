# -*- coding: utf-8 -*-
"""第 4 轮课程接口：钥匙、字段、分页、不含姓名、嵌入凭证与回放、零件库对照。需要本机 PostgreSQL（WQ_TEST_DB）。"""
import datetime as dt
import importlib
import json
import os

import pytest

import wqbus

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0] + "/wq_test_course"
NOW = dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.timezone.utc)
KEY = "test-read-key"
AUTH = {"Authorization": "Bearer " + KEY}


@pytest.fixture(scope="module")
def db():
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0] + "/postgres"
    try:
        with psycopg.connect(base, autocommit=True) as c:
            c.execute("drop database if exists wq_test_course")
            c.execute("create database wq_test_course")
    except psycopg.OperationalError:
        pytest.skip("没有可用的 PostgreSQL")
    from hub.db import DB
    from hub.historian import Historian
    from sim import scenario
    from tests_helpers import make_engine
    d = DB(DSN)
    d.init()
    h = Historian(d)
    eng, clock, _ = make_engine(auto=False)
    scenario.load(eng, lambda tp, ty, src, data, corr, ts: h.handle(tp, wqbus.make(ty, src, data, corr=corr, ts=ts)), now=NOW)
    # 本地版（填名字登录）总线上会有姓名：课程接口也不能带出来（C4）
    h.handle(wqbus.topic("machining", "grd-01", "event"), wqbus.make(
        "machine.event", "mes/王小明", {"event": "alarm", "message": "测试报警", "code": "A1"},
        ts=(NOW - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")))
    # 一次设计发布（FreeCAD 宏的格式），附 G 代码文件
    d.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s)",
        ("a" * 64, "SH-301-rev2-keyway.nc", "text/plain", 12, b"G0 X0\nG1 X10\nM30\n"))
    d.x("insert into stored_file (sha256, name, mime, size, content) values (%s,%s,%s,%s,%s)",
        ("b" * 64, "SH-301-rev2-drawing.svg", "image/svg+xml", 5, b"<svg/>"))
    ts = (NOW - dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    h.handle("wq/gearbox/design/sh-301/release", wqbus.make("design.release", "workbench/王小明", {
        "item": "SH-301", "revision": 2, "params": {"keyway": {"length": 42}}, "bom": [], "author": "王小明",
        "change_note": "键槽长 45 → 42 mm", "files": [{"kind": "drawing", "name": "SH-301-rev2-drawing.svg", "sha256": "b" * 64,
                                                   "url": "/api/files/" + "b" * 64}]}, ts=ts))
    h.handle("wq/gearbox/design/sh-301/gcode", wqbus.make("design.gcode", "workbench/王小明", {
        "item": "SH-301", "revision": 2, "operation": "铣键槽 Keyway milling", "machine": "key-01",
        "gcode_ref": "/api/files/" + "a" * 64, "sha256": "a" * 64, "est_time_s": 540}, ts=ts))
    return d


@pytest.fixture(scope="module")
def client(db, tmp_path_factory):
    lib = tmp_path_factory.mktemp("library")
    (lib / "2026.10.0").mkdir()
    (lib / "latest.json").write_text(json.dumps({"version": "2026.10.0", "index": "library/2026.10.0/index.json"}))
    (lib / "2026.10.0" / "index.json").write_text(json.dumps({"items": [
        {"ref": "A-BRG-DG/6207", "erp_items": ["BRG-6207"]}, {"ref": "A-KEY-FLAT/12x8x45", "erp_items": ["KEY-12x8x45"]}]}))
    mp = pytest.MonkeyPatch()
    mp.setenv("WQ_HUB_NO_START", "1")
    mp.setenv("WQ_FACTORY_READ_KEY", KEY)
    mp.setenv("WQ_LIBRARY_DIR", str(lib))
    mp.setenv("WQ_PUBLIC_URL", "https://factory.example.com")
    mp.setenv("WQ_SECRET", "s3")
    import hub.app as app_mod
    app_mod = importlib.reload(app_mod)
    app_mod.H.db = db
    from hub import course
    course.LIB.at = 0
    yield TestClient(app_mod.app)
    mp.undo()


def test_key_required(client):
    for h in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": KEY}):
        assert client.get("/api/course/products", headers=h).status_code == 401
    r = client.get("/api/course/products", headers=AUTH)
    assert r.status_code == 200
    j = r.json()
    assert j["as_of"].endswith("Z") and j["source"] == ["factory-data"]
    p = j["items"][0]
    assert p["code"] == "WQR-105" and p["name"]["zh"].startswith("二级圆柱齿轮减速器")
    assert abs(p["specs"]["ratio"] - 10.5) < 1e-9 and p["specs"]["input_speed_rpm"] == 1450


def test_product_detail(client):
    j = client.get("/api/course/products/WQR-105", headers=AUTH).json()
    assert j["bom"]["item_code"] == "WQR-105" and j["bom"]["kind"] == "fg"
    sa300 = next(c for c in j["bom"]["children"] if c["item_code"] == "SA-300")
    brg = next(c for c in sa300["children"] if c["item_code"] == "BRG-6207")
    assert brg["kind"] == "buy" and brg["qty"] == 2 and brg["library_ref"] == "A-BRG-DG/6207"     # C9
    assert j["bom"]["library_ref"] is None
    assert j["routings"]["SH-301"][0] == {"seq": 1, "operation": {"zh": "下料", "en": "Sawing"}, "workstation": "saw-01", "minutes": 3}
    ws = {w["unit"]: w for w in j["workstations"]}
    assert ws["cnc-l01"]["capacity"] == 2 and ws["cnc-l01"]["units"] == ["cnc-l01-a", "cnc-l01-b"]
    q = next(x for x in j["quality_plans"] if x["item_code"] == "SH-301")
    c = next(x for x in q["characteristics"] if "Ø35" in x["name"]["zh"])
    assert c["min"] == 35.002 and c["max"] == 35.018 and c["unit"] == "mm" and c["gauge"] == "三坐标"
    assert j["std_cost"]["SH-301"]["material"] == 4.48 and j["std_cost"]["SH-301"]["currency"] == "USD"
    assert j["std_cost"]["WQR-105"]["total"] > j["std_cost"]["SA-300"]["total"]
    assert client.get("/api/course/products/SH-301", headers=AUTH).status_code == 404


def test_designs_cases_layout(client):
    j = client.get("/api/course/designs/sh-301", headers=AUTH).json()
    r = j["revisions"][-1]
    assert r["revision"] == 2 and r["author_role"] == "engineer" and r["change_note"].startswith("键槽长")
    kinds = {f["kind"]: f for f in r["files"]}
    assert kinds["svg"]["url"] == "https://factory.example.com/api/files/" + "b" * 64
    assert kinds["gcode"]["name"] == "SH-301-rev2-keyway.nc" and r["gcode"]["lines"] == 3
    assert "王小明" not in json.dumps(j, ensure_ascii=False)
    c = client.get("/api/course/cases", headers=AUTH).json()["items"]
    assert c[0]["id"] == "lab7" and c[0]["mode"] == "teach"
    assert c[1]["id"] == "lab8" and c[1]["guide_url"].endswith("/api/cae/lab8/guide.docx") and c[1]["tool_url"].endswith("/cae")
    assert c[2]["id"] == "lab9" and c[2]["tool_url"].endswith("/mbd")
    assert c[3]["id"] == "lab10" and c[3]["tool_url"].endswith("/cam") and c[3]["report_template_url"].endswith("/api/cae/lab10/report-template.docx")
    assert c[4]["id"] == "lab11" and c[4]["tool_url"].endswith("/opt") and c[4]["guide_url"].endswith("/api/cae/lab11/guide.docx")
    assert c[5]["id"] == "lab12" and c[5]["tool_url"].endswith("/cae") and "RJ-201" in c[5]["products"]
    assert c[6]["id"] == "lab13" and c[6]["tool_url"].endswith("/twin") and c[6]["guide_url"].endswith("/api/cae/lab13/guide.docx")
    l15 = next(x for x in c if x["id"] == "lab15")                 # 第 17 轮 D 期：实验 15
    assert l15["tool_url"].endswith("/lab15") and l15["guide_url"].endswith("/api/cae/lab15/guide.docx")
    assert l15["report_template_url"].endswith("/api/cae/lab15/report-template.docx") and l15["mode"] == "teach"
    l16 = next(x for x in c if x["id"] == "lab16")                 # 第 18 轮 E1：实验 16
    assert l16["tool_url"].endswith("/lab16") and l16["guide_url"].endswith("/api/cae/lab16/guide.docx")
    assert l16["report_template_url"].endswith("/api/cae/lab16/report-template.docx") and l16["mode"] == "teach"
    l17 = next(x for x in c if x["id"] == "lab17")                 # 第 18 轮 E2：实验 17
    assert l17["tool_url"].endswith("/lab17") and l17["guide_url"].endswith("/api/cae/lab17/guide.docx")
    l18 = next(x for x in c if x["id"] == "lab18")                 # 第 18 轮 E3：实验 18
    assert l18["tool_url"].endswith("/lab18") and l18["report_template_url"].endswith("/api/cae/lab18/report-template.docx")
    l19 = next(x for x in c if x["id"] == "lab19")                 # 第 18 轮 E4：实验 19
    assert l19["tool_url"].endswith("/lab19") and l19["guide_url"].endswith("/api/cae/lab19/guide.docx")
    l20 = next(x for x in c if x["id"] == "lab20")                 # 第 18 轮 E5：实验 20
    assert l20["tool_url"].endswith("/lab20") and l20["guide_url"].endswith("/api/cae/lab20/guide.docx")
    lay = client.get("/api/course/layout", headers=AUTH).json()
    assert lay["floor"] == {"w_m": 50, "d_m": 28}
    grd = next(u for u in lay["units"] if u["unit"] == "grd-01")
    assert grd["name"]["zh"] == "外圆磨床" and grd["operations"][0]["zh"] == "磨外圆"
    assert lay["agv_home"]["agv-01"] == {"x_m": 7, "y_m": 9}


def _data(client, kind, **kw):
    q = {"case": "lab7", "kind": kind, "from": (NOW - dt.timedelta(days=8)).isoformat(), "to": NOW.isoformat(), **kw}
    r = client.get("/api/course/data", params=q, headers=AUTH)
    assert r.status_code == 200, r.text
    return r.json()


def test_data_kinds(client):
    m = _data(client, "measurement")
    assert m["source"] == "historian" and m["rows"] and m["next"] is None
    assert set(m["rows"][0]) == {"ts", "part_serial", "item", "work_order", "characteristic", "name", "nominal_mm",
                                 "lower_tol_mm", "upper_tol_mm", "value_mm", "result"}
    ev = _data(client, "event")["rows"]
    kinds = {e["event"] for e in ev}
    assert {"cycle_start", "cycle_end", "state"} <= kinds
    alarm = next(e for e in ev if e["event"] == "alarm" and e["code"] == "A1")
    assert alarm["actor_role"] == "user"
    assert "王小明" not in json.dumps(ev, ensure_ascii=False)                 # C4
    assert {e["actor_role"] for e in ev} <= {"sim", "system", "user", "planner", "engineer", "operator", "quality", "manager", "ai"}
    o = _data(client, "order")["rows"]
    assert {x["doctype"] for x in o} >= {"Sales Order", "Work Order"}
    so = next(x for x in o if x["doctype"] == "Sales Order")
    assert so["customer"] and so["delivery_date"] and so["item_code"] == "WQR-105"
    k = _data(client, "kpi", **{"from": (NOW - dt.timedelta(days=2)).isoformat()})["rows"]
    assert k and set(k[-1]) == {"date", "otd", "oee", "fpy", "wip", "output", "cost_variance_pct"}
    assert k[-1]["date"] == "2026-10-20"


def test_paging(client, monkeypatch):
    from hub import course
    full = _data(client, "measurement")["rows"]
    monkeypatch.setattr(course, "PAGE_MAX", 5)
    p1 = _data(client, "measurement")
    p2 = _data(client, "measurement", page=2)
    assert len(p1["rows"]) == 5 and p1["next"] == 2 and p1["rows"] + p2["rows"] == full[:10]
    assert client.get("/api/course/data", params={"case": "prod"}, headers=AUTH).status_code == 404     # C10
    assert client.get("/api/course/data", params={"kind": "salary"}, headers=AUTH).status_code == 400


def test_embed_token_and_replay(client):
    assert client.get("/api/course/embed-token").status_code == 401
    t = client.get("/api/course/embed-token", params={"ttl": 99999}, headers=AUTH).json()
    exp = dt.datetime.fromisoformat(t["expires"].replace("Z", "+00:00"))
    assert dt.timedelta(minutes=29) < exp - dt.datetime.now(dt.timezone.utc) <= dt.timedelta(minutes=30)   # 最长 30 分钟
    t0 = (NOW - dt.timedelta(hours=3)).isoformat()
    assert client.get("/api/embed/replay", params={"t0": t0}).status_code == 401
    assert client.get("/api/embed/replay", params={"t0": t0, "token": t["token"] + "x"}).status_code == 401
    r = client.get("/api/embed/replay", params={"t0": t0, "token": t["token"], "minutes": 60}).json()
    units = {x["unit"] for x in r["rows"] if x["kind"] == "machine"}
    assert len(units) >= 10                                          # 开头补上了每台设备当时的状态
    from hub import course
    tok, _ = course.embed_token(60)
    assert course.check_embed_token(tok)
    raw, _sig = tok.split(".")
    assert not course.check_embed_token(raw + "." + "0" * 32)
    assert client.get("/api/embed/config").json()["mode"] == "teach"


def test_embed_page_frame_ancestors(client):
    import hub.app as app_mod
    if not os.path.isdir(app_mod.WEB_DIST):
        pytest.skip("网页还没有构建")
    r = client.get("/embed/workshop")
    assert r.status_code == 200 and "frame-ancestors" in r.headers.get("content-security-policy", "")
