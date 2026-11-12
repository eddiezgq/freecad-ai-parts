# -*- coding: utf-8 -*-
"""第 155 轮：“设计与工艺”页在非演示工厂显示本厂产品——/api/products/structure 给出本厂全部有物料清单的物料、
物料清单（自制 / 外购）、工艺路线（分钟/件、设备、一次装几件）、标准成本；与算料、仿真同一份数据。"""
import json
import os
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)

CODE = ("import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import app\n"
        "print(json.dumps({{'s': app.products_structure(), 'r': app.routing({!r})}}, ensure_ascii=False, default=str))")


def _run(plant, item):
    env = dict(os.environ)
    if plant:
        env["WQ_PLANT_FILE"] = os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant))
    else:
        env.pop("WQ_PLANT_FILE", None)
    r = subprocess.run([sys.executable, "-c", CODE.format(DIG, FAC, item)], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def test_motor_plant():
    out = _run("motor", "WQ-SM200")
    s = out["s"]
    assert s["demo"] is False
    items = {x["item"]: x for x in s["items"]}
    assert sorted(items) == ["WQ-AM750", "WQ-SM100", "WQ-SM200", "WQ-SM400"]
    sm = items["WQ-SM200"]
    assert sm["product"] is True
    wire = [b for b in sm["bom"] if b["item_code"] == "WIRE-CU"][0]
    assert wire["qty"] == 0.3 and wire["made"] is False and wire["uom"]
    ops = {o["operation"].split(" ")[0]: o for o in sm["operations"]}
    assert ops["浸漆烘干"]["batch"] == 24 and ops["浸漆烘干"]["minutes"] == 180 and ops["绕线"]["units"] == ["wd-1", "wd-2"]
    assert sm["std_cost"]["material"] > 0 and sm["std_cost"]["operations"] > 0
    assert {o["operation"]: o["batch"] for o in out["r"]["operations"]}["浸漆烘干 Varnish & bake"] == 24


def test_robot_plant_made_parts_link():
    s = _run("robot", "WQJ-M")["s"]
    items = {x["item"]: x for x in s["items"]}
    prods = [x["item"] for x in s["items"] if x["product"]]
    assert s["items"][:len(prods)] == [items[p] for p in prods]           # 可接单的产品在前
    made = [b["item_code"] for x in s["items"] for b in x["bom"] if b["made"]]
    assert made and all(m in items for m in made)                          # 自制件都能点开看自己的清单


@pytest.mark.parametrize("plant", [None, "sensor", "pcb", "chip", "sewing"])
def test_every_plant_has_structure(plant):
    env = dict(os.environ)
    if plant:
        env["WQ_PLANT_FILE"] = os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant))
    else:
        env.pop("WQ_PLANT_FILE", None)
    code = "import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import app\nprint(json.dumps(app.products_structure(), ensure_ascii=False))".format(DIG, FAC)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    s = json.loads(r.stdout)
    assert s["items"] and any(x["product"] for x in s["items"])
    assert s["demo"] is (plant is None)
