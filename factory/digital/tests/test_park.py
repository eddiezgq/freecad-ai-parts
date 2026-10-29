# -*- coding: utf-8 -*-
"""第 51 轮：问渠数字工业园——机器人厂的采购到货（供应链模块按清单起）、两厂互发订单（下单、接单、下达、发货回传、连不上的退路）。
卖方（减速器厂）在本进程按演示工厂跑；买方（机器人厂）在子进程里按机器人厂清单跑（工厂数据在导入时读清单）。需要 PostgreSQL。"""
import datetime as dt
import json
import os
import subprocess
import sys
import types

import pytest

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")


class FakeMes:
    def __init__(self):
        self.sent = []
        self.released = []

    def command(self, unit, command, mode, user, work_order=None, operation=None, **extra):
        self.sent.append(dict({"unit": unit, "command": command, "mode": mode, "work_order": work_order}, **extra))

    def release(self, name, mode, user, units=None):
        self.released.append(name)
        return [{"operation": "下料 Sawing", "unit": "saw-01", "name": "带锯床"}]


def _fresh(name):
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute("drop database if exists {} with (force)".format(name))
            c.execute("create database {}".format(name))
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    from hub.ai import Assistant
    from hub.db import DB
    db = DB(base + "/" + name)
    db.init()
    return types.SimpleNamespace(db=db, ai=Assistant(db, lambda *a: None, None), mes=FakeMes())


@pytest.fixture()
def seller(monkeypatch):
    monkeypatch.setenv("WQ_PARK_KEY", "k-test")
    monkeypatch.setenv("WQ_PARK_PEERS", "robot=http://robot.invalid")
    return _fresh("wq_park_seller_test")


def _order(**kw):
    return dict({"from_plant": "robot", "from_name": "问渠机器人厂 WenQuest Robotics (Demo)", "ref": "7", "po": "PUR-ORD-0001",
                 "item": "WQR-105", "qty": 10, "need_by": (dt.date.today() + dt.timedelta(days=14)).isoformat(), "mode": "teach"}, **kw)


def test_seller_accepts_releases_and_ships(seller, monkeypatch):
    from hub import finance as FN
    from hub import park as PK
    H = seller
    with pytest.raises(ValueError, match="不接"):
        PK.receive_order(H.db, _order(item="HD-CSF-32-100"))
    a = PK.receive_order(H.db, _order())
    assert PK.receive_order(H.db, _order())["id"] == a["id"]            # 同一批重发：同一张单
    now = dt.datetime.now(dt.timezone.utc)
    assert PK.tick(H, "teach", now)["accepted"] == []                    # 3 分钟内等计划员
    PK.tick(H, "teach", now + dt.timedelta(seconds=PK.AUTO_S + 1))
    o = PK.orders(H.db, "teach")[0]
    assert o["status"] == "accepted"
    p = H.db.one("select * from ai_proposal where proposal_id=(select proposal_id from park_order where id=%s)", (a["id"],))
    pv = p["preview"] if isinstance(p["preview"], dict) else json.loads(p["preview"])
    assert p["action"] == "create_order_and_plan" and p["status"] == "confirmed"
    assert pv["sales_order"]["customer"].startswith("问渠机器人厂") and pv["sales_order"]["new_customer"] and pv["sales_order"]["qty"] == 10
    assert [w["production_item"] for w in pv["work_orders"]] == ["SH-301"]       # 演示工厂的 WQR-105 照教学只下达输出轴
    # 桥接写进 ERPNext 之后：平台（自动接单）下达车间、开工
    H.db.x("update ai_proposal set status='executed', result=%s where proposal_id=%s",
           (json.dumps({"created": [["Sales Order", "SAL-ORD-9"], ["Work Order", "MFG-WO-9"]]}), p["proposal_id"]))
    PK.tick(H, "teach", now)
    o = PK.orders(H.db, "teach")[0]
    assert o["status"] == "released" and o["so"] == "SAL-ORD-9" and H.mes.released == ["MFG-WO-9"]
    assert any(c["command"] == "start" and c["work_order"] == "MFG-WO-9" for c in H.mes.sent)
    sent = []
    monkeypatch.setattr(PK, "_post", lambda plant, path, body: sent.append((plant, path, body)) or {"ok": True})
    monkeypatch.setattr(FN, "ready_orders", lambda db, mode, real_only=False: [])
    PK.tick(H, "teach", now)
    assert not sent and PK.orders(H.db, "teach")[0]["status"] == "released"      # 工单没做完不发货
    monkeypatch.setattr(FN, "ready_orders", lambda db, mode, real_only=False: [({"data": {"name": "SAL-ORD-9"}}, now)])
    PK.tick(H, "teach", now)
    (plant, path, body), = sent
    assert plant == "robot" and path == "/api/park/shipments" and body["ref"] == "7" and body["so"] == "SAL-ORD-9"
    assert body["lot"] == "WQR105-9" and len(body["serials"]) == 10 and body["serials"][0] == "WQR105-9-01"
    assert PK.orders(H.db, "teach")[0]["status"] == "shipped"


def test_seller_manual_accept_and_auto_off(seller, monkeypatch):
    from hub import park as PK
    H = seller
    PK.set_auto(H.db, "teach", False)
    a = PK.receive_order(H.db, _order(ref="8"))
    PK.tick(H, "teach", dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1))
    assert PK.orders(H.db, "teach")[0]["status"] == "pending"                 # 自动接单关了：一直等
    r = PK.accept(H, "teach", a["id"], "学生计划")
    assert r["work_orders"] == 1
    with pytest.raises(ValueError):
        PK.accept(H, "teach", a["id"], "学生计划")
    pid = H.db.one("select proposal_id from park_order where id=%s", (a["id"],))["proposal_id"]
    H.db.x("update ai_proposal set status='executed', result=%s where proposal_id=%s",
           (json.dumps({"created": [["Sales Order", "SAL-ORD-8"], ["Work Order", "MFG-WO-8"]]}), pid))
    PK.tick(H, "teach")
    assert PK.orders(H.db, "teach")[0]["status"] == "released" and H.mes.released == []    # 学生接的单由学生自己下达


def test_park_endpoints_need_the_key(seller):
    from fastapi import FastAPI, Header
    from fastapi.testclient import TestClient
    from hub import park as PK
    app = FastAPI()

    def user_of(x_wq_token: str = Header(default="")):
        return {"name": "王老师", "role": "manager", "teacher": True, "mode": "teach"}
    PK.mount(app, seller, user_of, lambda u: u["name"])
    c = TestClient(app)
    assert c.post("/api/park/orders", json=_order(ref="9")).status_code == 403
    assert c.post("/api/park/orders", json=_order(ref="9"), headers={"X-WQ-Park-Key": "wrong"}).status_code == 403
    r = c.post("/api/park/orders", json=_order(ref="9"), headers={"X-WQ-Park-Key": "k-test"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert c.post("/api/park/orders", json=_order(ref="10", item="XX"), headers={"X-WQ-Park-Key": "k-test"}).status_code == 400
    s = c.get("/api/park").json()
    assert s["auto"] and s["orders"][0]["item"] == "WQR-105" and s["can_accept"]
    assert c.post("/api/park/auto", json={"on": False}).json() == {"auto": False}


BUYER = r"""
import datetime as dt, json, os, random, sys, types
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_park_buyer_test with (force)")
    c.execute("create database wq_park_buyer_test")
from hub.ai import Assistant
from hub.db import DB
from hub import park as PK, supply as SP
from factory import data as F
db = DB(BASE + "/wq_park_buyer_test")
db.init()
class Mes:
    sent = []
    def command(self, unit, command, mode, user, work_order=None, operation=None, **k):
        self.sent.append(dict(k, unit=unit, command=command))
H = types.SimpleNamespace(db=db, ai=Assistant(db, lambda *a: None, None), mes=Mes())
out = {{}}
# 供应链按清单：供应商的准时率、合格率、备选，来料检验模板
out["profiles"] = {{p["cat"] + "/" + p["role"]: [float(p["on_time_p"]), float(p["pass_p"]), p["active"]] for p in SP.profiles(db, "teach")}}
out["cat_name"] = SP.CAT_NAME["harmonic"]
pid = SP.ensure_setup(H, "teach")
pv = db.one("select preview from ai_proposal where proposal_id=%s", (pid,))["preview"] if pid else {{}}
pv = json.loads(pv) if isinstance(pv, str) else pv
out["setup"] = {{"suppliers": [s["name"] for s in pv.get("suppliers", [])], "templates": [t["name"] for t in pv.get("templates", [])]}}
gb = F.SUPPLIERS["gearbox"]["name"]
sent = []
def ok(plant, path, body):
    sent.append([plant, path, body])
    return {{"id": 41, "status": "pending"}}
def down(plant, path, body):
    raise ConnectionError("连不上")
now = dt.datetime.now(dt.timezone.utc)
r1 = SP.place_po(H, "teach", gb, [{{"item_code": "WQR-105", "qty": 10}}], "采购员")
db.x("update lot set po='PUR-ORD-0001' where id=%s", (r1["lots"][0],))
PK._post = ok
SP.tick(H, "teach", now=now, rng=random.Random(1))
SP.tick(H, "teach", now=now, rng=random.Random(1))         # 第二轮：已经送过，不重发
x = db.one("select * from lot where id=%s", (r1["lots"][0],))
out["sent"] = sent
out["after_send"] = [x["status"], x["park"]["state"], x["note"]]
out["ship"] = PK.receive_shipment(db, {{"ref": str(x["id"]), "mode": "teach", "so": "SAL-ORD-9", "lot": "WQR105-9", "serials": ["WQR105-9-01"]}})
x = db.one("select * from lot where id=%s", (r1["lots"][0],))
out["after_ship"] = [x["status"], x["lot"], x["park"]["serials"], float(x["late_days"])]
SP.tick(H, "teach", now=now + dt.timedelta(seconds=SP.DAY_S + 5), rng=random.Random(1))
x = db.one("select * from lot where id=%s", (r1["lots"][0],))
out["arrived"] = x["status"]
sm = SP.sample(db, "teach", x["id"])
out["template"] = [sm["template"], [p["specification"] for p in sm["params"]]]
# 连不上：按外部供应商处理
r2 = SP.place_po(H, "teach", gb, [{{"item_code": "WQR-105", "qty": 10}}], "采购员")
db.x("update lot set po='PUR-ORD-0002' where id=%s", (r2["lots"][0],))
PK._post = down
SP.tick(H, "teach", now=now, rng=random.Random(1))
y = db.one("select * from lot where id=%s", (r2["lots"][0],))
out["fallback"] = [y["status"], y["park"]["state"], y["note"], y["due_at"] is not None]
# 普通供应商不走工业园
r3 = SP.place_po(H, "teach", F.SUPPLIERS["harmonic"]["name"], [{{"item_code": "HD-CSF-32-100", "qty": 5}}], "采购员")
db.x("update lot set po='PUR-ORD-0003' where id=%s", (r3["lots"][0],))
SP.tick(H, "teach", now=now, rng=random.Random(1))
z = db.one("select * from lot where id=%s", (r3["lots"][0],))
out["plain"] = [z["status"], z["park"]]
# 合格入库的谐波减速器批次告诉仿真车间
db.x("update lot set status='accepted', qty_ok=5, qty_left=5, received_at=now() where id=%s", (z["id"],))
SP.tick(H, "teach", now=now, rng=random.Random(1))
SP.tick(H, "teach", now=now, rng=random.Random(1))
out["shop"] = [[m["command"], m.get("item"), m.get("lot"), m.get("qty")] for m in Mes.sent if m["command"] == "add_lot"]
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def test_buyer_robot_plant_supply_and_park():
    pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT, WQ_PARK_KEY="k-test", WQ_PARK_PEERS="wenquest-gearbox=http://gearbox.invalid")
    r = subprocess.run([sys.executable, "-c", BUYER.format(dig=DIG, fac=FAC, base=base)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=300)
    if r.returncode != 0 and "connection" in r.stderr.lower() and "refused" in r.stderr.lower():
        pytest.skip("没有可用的 PostgreSQL")
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["profiles"]["harmonic/default"] == [0.85, 0.9, True] and out["profiles"]["harmonic/alt"][2] is False
    assert out["profiles"]["metals/alt"][2] is True and out["cat_name"] == "谐波减速器"
    assert "示例·精密传动 Precision Drive (Demo)" in out["setup"]["suppliers"]
    assert set(out["setup"]["templates"]) == {"进货检验-metals", "进货检验-harmonic", "进货检验-servo", "进货检验-gearbox"}
    (plant, path, body), = out["sent"]
    assert plant == "wenquest-gearbox" and path == "/api/park/orders"
    assert body["item"] == "WQR-105" and body["qty"] == 10 and body["po"] == "PUR-ORD-0001" and body["from_name"].startswith("问渠机器人厂")
    assert out["after_send"][:2] == ["ordered", "sent"] and "工业园订单 41" in out["after_send"][2]
    assert out["after_ship"][:3] == ["transit", "WQR105-9", ["WQR105-9-01"]] and out["after_ship"][3] == 0
    assert out["arrived"] == "arrived"
    assert out["template"][0] == "进货检验-gearbox" and out["template"][1] == ["空载噪声 Noise (dB(A))", "渗漏检查 Leak check"]
    assert out["fallback"][:2] == ["transit", "fallback"] and "未连通，按外部供应商处理" in out["fallback"][2] and out["fallback"][3]
    assert out["plain"] == ["transit", None]
    assert len(out["shop"]) == 1 and out["shop"][0][:2] == ["add_lot", "HD-CSF-32-100"] and out["shop"][0][3] == 5


def test_manifest_supplier_fields_validated():
    from factory import plant as PL
    base = {"name": "x", "lead": 3}
    bad = [dict(base, on_time=1.5), dict(base, alt={"name": "y"}), dict(base, incoming=[{"name": "a", "lo": 2, "hi": 1}]),
           dict(base, incoming=[{"name": "a", "text": "ok", "lo": 1, "hi": 2}]), dict(base, park="Bad Id"), dict(base, alt={"name": "y", "price_index": 1.1,
                                                                                                                      "lead": 2, "active": "yes"})]
    for s in bad:
        assert PL._validate_supplier("suppliers.x", s), s
    good = dict(base, on_time=0.9, cat_name="轴承", park="wenquest-gearbox", alt={"name": "y", "price_index": 1.1, "lead": 2, "active": True},
                incoming=[{"name": "a", "unit": "mm", "lo": 1, "hi": 2}, {"name": "b", "text": "无锈蚀"}])
    assert PL._validate_supplier("suppliers.x", good) == []


def test_robot_manifest_excel_round_trip_keeps_supplier_fields(tmp_path):
    pytest.importorskip("openpyxl")
    import yaml
    from factory import plant_xlsx as X
    raw = yaml.safe_load(open(ROBOT, encoding="utf-8"))
    X.write_template(str(tmp_path / "r.xlsx"), raw)
    back, errs, _ = X.read_workbook(str(tmp_path / "r.xlsx"))
    assert not errs, errs
    assert back["suppliers"] == raw["suppliers"]
