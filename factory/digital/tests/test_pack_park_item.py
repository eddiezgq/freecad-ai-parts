# -*- coding: utf-8 -*-
"""第 106 轮：清单物料的 pack（按包装买）与 park_item（向工业园兄弟厂下单时的对方物料号）——
校验；算料按包装数取整；下单换成对方物料号和件数；没写的物料不变。工厂数据在导入时读清单，所以在子进程里按电路板厂清单跑。"""
import copy
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
PCB = os.path.join(FAC, "plants", "wenquest-pcb.yaml")
sys.path[:0] = [FAC]
from factory import plant  # noqa: E402


def _raw():
    return yaml.safe_load(open(PCB, encoding="utf-8"))


def test_validation():
    assert not plant.validate(_raw())
    p = _raw()
    it = next(x for x in p["items"] if x["code"] == "IC-ENCIF")
    bad = copy.deepcopy(p)
    next(x for x in bad["items"] if x["code"] == "IC-ENCIF").pop("pack")
    assert any("pack" in e for e in plant.validate(bad))
    bad = copy.deepcopy(p)
    next(x for x in bad["items"] if x["code"] == "IC-ENCIF")["supplier"] = "ic"
    assert any("工业园" in e for e in plant.validate(bad))
    bad = copy.deepcopy(p)
    next(x for x in bad["items"] if x["code"] == "IC-ENCIF")["pack"] = 0
    assert any("正整数" in e for e in plant.validate(bad))
    assert it["pack"] == 34000


def test_lot_size_and_peer_mapping():
    code = r"""
import sys
sys.path[:0] = [{dig!r}, {fac!r}]
from hub import mrp, park
print(mrp.lot_size("IC-ENCIF"), mrp.lot_size("OSC-50M"), mrp.lot_size("PASTE-SAC305"))
print(park.to_peer("IC-ENCIF", 34000.0), park.to_peer("IC-ENCIF", 2.0), park.to_peer("IC-ENCIF", 34001.0), park.to_peer("OSC-50M", 7.0))
""".format(dig=DIG, fac=FAC)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=DIG, timeout=120,
                       env=dict(os.environ, WQ_PLANT_FILE=PCB))
    assert r.returncode == 0, r.stderr[-2000:]
    l1, l2 = r.stdout.strip().splitlines()
    assert l1.split() == ["34000", "10", "50"]                         # 写了 pack 的按包装；其余照旧（件 10、千克 50）
    assert l2 == "('WQ-ENCIF', 1.0) ('WQ-ENCIF', 1.0) ('WQ-ENCIF', 2.0) ('OSC-50M', 7.0)"
