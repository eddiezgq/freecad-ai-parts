# -*- coding: utf-8 -*-
"""第 167c 轮：厂情中枢按厂分开——减速器现场设备的规则 V1、V2 只在减速器厂的规则目录里；运营总览“本周完工”没有工单时写本厂的成品。"""
import json
import os
import subprocess
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)

def _catalog(plant_file):
    env = dict(os.environ)
    env.pop("WQ_PLANT_FILE", None)
    if plant_file:
        env["WQ_PLANT_FILE"] = plant_file
    code = ("import json, sys; sys.path[:0] = [{!r}, {!r}]\n"
            "from hub.ont import anomaly as A\n"
            "from factory import data as F\n"
            "print(json.dumps({{'rules': sorted(A.load_catalog()), 'first': next(iter(F.PRODUCTS), None)}}))").format(DIG, FAC)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_field_rules_only_in_gearbox():
    soft = _catalog(os.path.join(FAC, "plants", "wenquest-software.yaml"))
    assert "V1" not in soft["rules"] and "V2" not in soft["rules"] and {"SW1", "SW5"} <= set(soft["rules"])
    comp = _catalog(os.path.join(FAC, "plants", "wenquest-computer.yaml"))
    assert "V1" not in comp["rules"] and "CP1" in comp["rules"]
    gear = _catalog(None)
    assert {"V1", "V2"} <= set(gear["rules"]) and "SW1" not in gear["rules"]


def test_overview_label_falls_back_to_own_product():
    """没有工单时，“本周完工”写本厂的第一种成品（软件公司 REL-RTOS），不是减速器厂的 SH-301"""
    assert _catalog(os.path.join(FAC, "plants", "wenquest-software.yaml"))["first"] == "REL-RTOS"
    src = open(os.path.join(DIG, "hub", "kpi.py"), encoding="utf-8").read()
    assert 'item = items[0] if items else (next(iter(F.PRODUCTS), None) or "SH-301")' in src
