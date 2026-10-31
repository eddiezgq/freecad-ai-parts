# -*- coding: utf-8 -*-
"""第 59 轮：机器人厂打开设备维护（E3）、能源（E6）、经营财务（E7）——设备数据按类别缺省值 + 清单覆盖（factory/equip.py），
演示工厂（减速器厂）的数原样不动。机器人厂在子进程里按清单跑（工厂数据在导入时读清单）。需要 PostgreSQL 的那一项没有库时跳过。"""
import json
import os
import subprocess
import sys

import pytest

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")

RUN = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
out = {{}}
from sim import reliability as R, energy as SE
from hub import maint as MT, energy as EG, finance as FN
from hub import app as A
out["rel"] = sorted(R.PARAMS)
out["power"] = {{u: list(v) for u, v in SE.POWER.items()}}
out["assets"] = MT.ASSETS
out["custs"] = FN.CUSTS
out["credit"] = FN.CREDIT
out["price"] = FN.PRICE
out["contract"] = EG.PARAMS["contract_kw"]
out["demo"] = A.DEMO_PLANT
out["open"] = [p for p in ("/api/maint/assets", "/api/energy/overview", "/api/finance/kpis", "/api/ehs", "/api/people") if not A.teach_only(p)]
if {db!r}:
    from hub.db import DB
    db = DB({db!r})
    db.init()
    from hub.ont import actions as AC
    AC.init(db)
    out["asset_rows"] = [(a["unit"], a["name"], a["value"], a["pm_h"]) for a in MT.assets(db, "teach")]
    out["meters"] = [(m["code"], m["power"]) for m in EG.meters(db, "teach")]
    FN.seed(db, "teach")
    out["ar"] = [(r["party"], float(r["amount"])) for r in db.q("select party, amount from invoice where mode='teach' and opening order by id")]
    out["kpis"] = sorted(FN.kpis(db, "teach"))
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _run(plant, db=""):
    env = dict(os.environ)
    env.pop("WQ_PLANT_FILE", None)
    if plant:
        env["WQ_PLANT_FILE"] = plant
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, db=db)], capture_output=True, text=True, env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def _fresh(name):
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute("drop database if exists {} with (force)".format(name))
            c.execute("create database {}".format(name))
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    return base + "/" + name


def test_demo_plant_unchanged():
    o = _run(None)
    assert o["assets"]["grd-01"] == 120000 and o["assets"]["ht-01"] == 95000
    assert o["power"]["ht-01"] == [110.0, 35.0, 35.0] and o["power"]["cnc-l01-a"] == [15.0, 5.5, 0.6]
    assert "grd-01" in o["rel"] and o["contract"] == 220.0 and o["price"] == 1650.0
    assert o["demo"] is True                     # 演示工厂不走 404 的门（中间件只管企业工厂）


def test_robot_plant_equipment_and_gating():
    o = _run(ROBOT)
    units = {"saw-r1", "cnc-r1", "cnc-r2", "vmc-r1", "vmc-r2", "grd-r1", "cmm-r1", "ja-1", "ja-2", "jt-1", "ra-1", "cal-1", "run-r1", "aa-1", "at-1"}
    assert set(o["rel"]) == units and set(o["power"]) == units and set(o["assets"]) == units
    assert o["power"]["grd-r1"] == [11.0, 4.0, 0.5] and o["assets"]["cal-1"] == 150000
    assert o["custs"][0].startswith("示例·汽车零部件厂") and o["price"] == 18000.0
    assert list(o["credit"].values()) == [72000.0, 54000.0, 45000.0]
    assert 50 <= o["contract"] < 220
    assert o["open"] == ["/api/maint/assets", "/api/energy/overview", "/api/finance/kpis"]       # 安全环保、人员下一轮


def test_robot_plant_pages_with_db():
    o = _run(ROBOT, _fresh("wq_dom_robot_test"))
    rows = {u: (n, v, pm) for u, n, v, pm in o["asset_rows"]}
    assert rows["cnc-r1"] == ("数控车床 1 号", 65000, 600) and rows["ja-1"][2] == 1000
    meters = dict(o["meters"])
    assert meters["E-RUN-R1"] == [12.0, 1.5, 0.3] and meters["E-TOTAL"] is None
    assert [p for p, _ in o["ar"]][0].startswith("示例·汽车零部件厂") and o["ar"][0][1] == 18000.0
    assert o["kpis"]


def test_manifest_equipment_fields_validated():
    from factory import equip
    assert equip.validate_unit("units[0]", {"maint": {"value": 5000, "pm_text": "查"}, "power_kw": [3, 1, 0.2]}) == []
    errs = equip.validate_unit("units[0]", {"maint": {"value": -1, "foo": 1}, "power_kw": [3, 1]})
    assert len(errs) == 3
    p = equip.profiles([{"id": "cnc-r9", "name": "车床", "workstation": "W", "maint": {"value": 1234}, "power_kw": [9, 3, 0.4]},
                        {"id": "xyz-1", "name": "别的", "workstation": "W"}, {"id": "agv-1", "name": "小车"}])
    assert p["cnc-r9"]["kind"] == "lathe" and p["cnc-r9"]["value"] == 1234 and p["cnc-r9"]["power"] == (9, 3, 0.4)
    assert p["xyz-1"]["kind"] == "general" and "agv-1" not in p
    assert equip.kind_of("cal-1") == "calib" and equip.kind_of("run-r1") == "runin" and equip.kind_of("at-1") == "agvtest"
    assert equip.kind_of("aa-1") == "assembly" and equip.kind_of("ra-1") == "assembly"
