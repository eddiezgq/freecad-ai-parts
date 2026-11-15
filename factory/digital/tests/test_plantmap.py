# -*- coding: utf-8 -*-
"""第 171 轮：3D 车间的车间分区、工艺文件数据（/api/plantmap）。每座厂单独起子进程（清单在导入时读）。"""
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
from hub import plantmap
d = plantmap.build()
print(json.dumps(d, ensure_ascii=False, default=list))
"""


def _build(plant):
    env = dict(os.environ)
    env["WQ_PLANT_FILE"] = str(PLANTS / f"{plant}.yaml") if plant else ""
    out = subprocess.run([sys.executable, "-c", CODE], cwd=HERE, env=env, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("plant", [None, "wenquest-robot", "wenquest-pcb", "wenquest-chip", "wenquest-sensor", "wenquest-motor",
                                   "wenquest-computer", "wenquest-software", "wenquest-sewing"])
def test_every_unit_in_a_zone_and_every_routing_step_has_a_machine(plant):
    d = _build(plant)
    zone_ids = {z["id"] for z in d["zones"]}
    assert d["units"] and all(v["zone"] in zone_ids for v in d["units"].values())
    assert sum(len(z["units"]) for z in d["zones"]) == len(d["units"])
    for item, b in d["boms"].items():
        for op, _m in d["routings"][b["routing"]]:
            assert d["ops"][op]["units"], (item, op)
    # 每台设备做的（零件, 工序）都在那个零件的工艺路线上
    for u, js in d["jobs"].items():
        for it, op, i in js:
            assert d["routings"][d["boms"][it]["routing"]][i][0] == op


def test_sewing_zones_match_whiteboard_and_procdocs_cover_every_doc_step():
    d = _build("wenquest-sewing")
    names = [z["name"] for z in d["zones"]]
    assert names[:5] == ["① 机壳铸造车间", "② 机壳加工车间", "③ 关键零件加工车间", "④ 平缝机装配车间", "⑤ 包缝机装配车间"]
    assert not any(z.get("auto") for z in d["zones"])
    pd = d["procdocs"]
    assert pd and len(pd["docrows"]) == 175
    # 计量室抽检对得上计量室的设备
    metro = next(z for z in d["zones"] if z["id"] == "metro")
    assert all(r["unit"] in metro["units"] for r in pd["metro"]["rows"])


def test_demo_plant_has_one_auto_zone_and_output_shaft_chars():
    d = _build(None)
    assert len(d["zones"]) == 1 and d["zones"][0]["auto"]
    assert len(d["meas"]["SH-301|零件检验 Part inspection"]) >= 6
    assert d["procdocs"] is None
