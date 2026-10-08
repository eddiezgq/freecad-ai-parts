# -*- coding: utf-8 -*-
"""工厂清单（本仓库 ADR-0064）：演示工厂导出的清单与代码逐项一致；用清单加载时各模块取值不变；校验能指出错处。"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
DIG = os.path.dirname(HERE)
FAC = os.path.dirname(DIG)
DEMO = os.path.join(FAC, "plants", "wenquest-gearbox.yaml")

DUMP = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
from factory import data as F
from wqbus import topics as T, layout as L
from sim import engine as E, calendar as C
from hub import kpi as K, process as P

def j(v):
    if isinstance(v, dict):
        return {{str(k): j(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}}
    if isinstance(v, (set, frozenset)):
        return sorted(j(x) for x in v)
    if isinstance(v, (list, tuple)):
        return [j(x) for x in v]
    return v

out = {{
  "WORKSTATIONS": F.WORKSTATIONS, "OPERATIONS": F.OPERATIONS, "INSPECTION_OPS": F.INSPECTION_OPS, "SHIFT": F.SHIFT,
  "SUPPLIERS": F.SUPPLIERS, "CUSTOMERS": F.CUSTOMERS,
  "UNITS": T.UNITS, "MACHINES": T.MACHINES, "PLC_UNITS": T.PLC_UNITS, "UNIT_AREA": T.UNIT_AREA,
  "LAYOUT": L.LAYOUT, "FLOOR": L.FLOOR, "AGV_HOME": L.AGV_HOME, "AISLES": L.AISLES, "CROSS_X": L.CROSS_X,
  "DOCK": {{u: L.dock(u) for u in L.LAYOUT}},
  "OP_UNITS": E.OP_UNITS, "CAPACITY": E.CAPACITY, "SETUP_MIN": E.SETUP_MIN, "WEAR_PER_PART": E.WEAR_PER_PART,
  "SPINDLE": E.SPINDLE, "TOOL_CHANGE_MIN": E.TOOL_CHANGE_MIN,
  "CAL": [C.DEF_START, C.DEF_END, C.DEF_DAYS, C.MAX_OT_MIN],
  "SHIFT_MIN": K.SHIFT_MIN, "TARGET": K.TARGET, "STAGE": P.STAGE, "WORKCENTER_POWER": P.WORKCENTER_POWER,
}}
print(json.dumps(j(out), ensure_ascii=False))
"""


def _dump(plant=None):
    env = {k: v for k, v in os.environ.items() if k != "WQ_PLANT_FILE"}
    if plant:
        env["WQ_PLANT_FILE"] = plant
    r = subprocess.run([sys.executable, "-c", DUMP.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_demo_plant_file_matches_code():
    """演示工厂的清单与代码里的常量逐项一致：用它加载，各模块的取值与不用清单时完全一样。"""
    plain, loaded = _dump(), _dump(DEMO)
    diff = [k for k in plain if plain[k] != loaded[k]]
    assert not diff, {k: (plain[k], loaded[k]) for k in diff[:3]}


def test_export_is_current():
    """仓库里的演示清单就是从代码导出的那份（代码改了要重新导出）。"""
    import yaml
    sys.path[:0] = [DIG, FAC]
    from factory import plant
    with open(DEMO, encoding="utf-8") as f:
        assert yaml.safe_load(f) == plant.export_demo()


def test_validate_points_at_errors(tmp_path):
    import yaml
    sys.path[:0] = [FAC]
    from factory import plant
    with open(DEMO, encoding="utf-8") as f:
        good = yaml.safe_load(f)
    assert plant.validate(good) == []
    bad = json.loads(json.dumps(good))
    bad["company"]["timezone"] = "Mars/Base"
    bad["company"]["abbr"] = "TOO-LONG-ABBR"
    bad["units"][1]["workstation"] = "不存在的工作站"
    bad["units"][2]["id"] = bad["units"][0]["id"]
    bad["operations"][0]["units"] = ["no-such-unit"]
    bad["operations"][1]["workstation"] = "也不存在"
    bad["units"][0]["layout"] = [999, 4, 4, 2.5]
    bad["kpi"]["oee"] = 75
    errs = plant.validate(bad)
    text = "\n".join(errs)
    for frag in ("company.timezone", "company.abbr", "units[1].workstation", "设备编号重复", "operations[0].units",
                 "operations[1].workstation", "units[0].layout：位置在车间外", "kpi.oee"):
        assert frag in text, (frag, text)
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    with pytest.raises(plant.PlantError, match="工厂清单有"):
        plant.load(str(p))
