# -*- coding: utf-8 -*-
"""第 171d 轮：每座厂的主零件、主产品（设计工具默认打开主零件）。每座厂单独起子进程（清单在导入时读）。"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
PLANTS = HERE.parent / "plants"
CODE = r"""
import json, sys
sys.path[:0] = ['.', '..']
from factory import data as F, plant as P
print(json.dumps({"part": P.main_part(), "product": P.main_product(), "make": P.make_items(),
                  "items": list(F.ITEMS), "boms": list(F.BOMS), "products": list(F.PRODUCTS)}, ensure_ascii=False))
"""


def _run(plant):
    env = dict(os.environ)
    env["WQ_PLANT_FILE"] = str(PLANTS / f"{plant}.yaml") if plant else ""
    out = subprocess.run([sys.executable, "-c", CODE], cwd=HERE, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_demo_plant_keeps_sh301():
    d = _run(None)
    assert (d["part"], d["product"]) == ("SH-301", "WQR-105")


@pytest.mark.parametrize("plant", ["wenquest-robot", "wenquest-pcb", "wenquest-chip", "wenquest-sensor", "wenquest-motor",
                                   "wenquest-computer", "wenquest-software", "wenquest-sewing"])
def test_main_part_is_a_routed_item_of_this_plant(plant):
    d = _run(plant)
    assert d["part"] in d["boms"] and d["part"] != "SH-301"
    assert d["product"] == d["products"][0]
    assert {m[0] for m in d["make"]} == set(d["boms"]) & set(d["items"])
    assert d["make"][0][0] == d["part"]
