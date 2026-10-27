# -*- coding: utf-8 -*-
"""工厂清单（第 30 轮 H-2，搬自 freecad-ai-parts 的 ADR-0064 测试）：演示工厂导出的清单与代码逐项一致；
用清单加载时各模块取值不变；校验能指出错处；企业工厂（示例缝纫机厂）里仿真、MRP 照常，教学功能不出现。

与那边的不同：那边的新产品经 hub/products.py 并入（这边不搬，第 30 轮 H-7），所以仿真一项直接在物料数据里加一件试件，
MRP 一项计划一件用料只来自清单里供应商的演示零件（输出轴 SH-301），核对的内容不变。"""
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
  "SPINDLE": E.SPINDLE, "TOOL_CHANGE_MIN": E.TOOL_CHANGE_MIN, "STORES": [E.RAW_STORE, E.FG_STORE],
  "SIM_MACHINES": E._MACHINE_UNITS,
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


def _approx(a, b):
    """Excel 存 15 位有效数字：浮点按相对误差比，其余逐项相等。"""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_approx(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_approx(x, y) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return isinstance(b, (int, float)) and abs(a - b) <= 1e-12 * max(1, abs(a))
    return a == b


def test_excel_template_round_trip(tmp_path):
    """Excel 模板（演示工厂填好）导入回来，与演示清单一致。"""
    sys.path[:0] = [FAC]
    from factory import plant, plant_xlsx as X
    x = tmp_path / "t.xlsx"
    X.write_template(str(x))
    assert _approx(plant.export_demo(), X.import_workbook(str(x)))


@pytest.mark.parametrize("name", ["wenquest-robot", "example-sewing"])
def test_plant_yaml_excel_round_trip(tmp_path, name):
    """第 45 轮：机器人厂、示例缝纫机厂的清单（含产品六张表）写成 Excel 再导入，逐项一致。"""
    import yaml
    sys.path[:0] = [FAC]
    from factory import plant_xlsx as X
    raw = yaml.safe_load(open(os.path.join(FAC, "plants", name + ".yaml"), encoding="utf-8"))
    x = tmp_path / "t.xlsx"
    X.write_template(str(x), raw)
    assert _approx(raw, X.import_workbook(str(x)))


def test_excel_errors_name_sheet_row_column(tmp_path):
    """填错的地方说清是哪张表第几行哪一列。"""
    from openpyxl import load_workbook
    sys.path[:0] = [FAC]
    from factory import plant, plant_xlsx as X
    x = tmp_path / "t.xlsx"
    X.write_template(str(x))
    wb = load_workbook(str(x))
    f = wb["工厂"]
    for r in range(2, f.max_row + 1):
        if f.cell(r, 1).value == "班次时段":
            f.cell(r, 2).value = "08:00-12:00, 25:00-17:00"
        if f.cell(r, 1).value == "时区":
            f.cell(r, 2).value = "Mars/Base"
    u = wb["设备"]
    hdr = [c.value for c in u[1]]
    u.cell(3, hdr.index("x（米）") + 1).value = "十"          # 第 3 行是第一台设备
    u.cell(4, hdr.index("区域") + 1).value = "厨房"
    u.cell(5, hdr.index("工作站") + 1).value = "没有的工作站"
    u.cell(6, hdr.index("y（米）") + 1).value = None             # 平面位置缺一项
    o = wb["工序"]
    o.cell(3, [c.value for c in o[1]].index("可用设备") + 1).value = "saw-01, no-such"
    wb.save(str(x))
    with pytest.raises(plant.PlantError) as ei:
        X.import_workbook(str(x))
    text = "\n".join(ei.value.errors)
    for frag in ("工厂表第", "“班次时段”：时间写成 08:00", "设备表第 3 行“x（米）”：要填数字", "设备表第 4 行“区域”：可选",
                 "设备表第 6 行“x / y / 宽 / 深”：这一组要填全"):
        assert frag in text, (frag, text)
    # 逐格的错改掉后，剩下的是清单层面的错，同样换成表与行
    wb = load_workbook(str(x))
    for r in range(2, wb["工厂"].max_row + 1):
        if wb["工厂"].cell(r, 1).value == "班次时段":
            wb["工厂"].cell(r, 2).value = "08:00-12:00, 13:00-17:00"
    u = wb["设备"]
    u.cell(3, hdr.index("x（米）") + 1).value = 10
    u.cell(4, hdr.index("区域") + 1).value = "机加工"
    u.cell(6, hdr.index("y（米）") + 1).value = 4
    wb.save(str(x))
    with pytest.raises(plant.PlantError) as ei:
        X.import_workbook(str(x))
    text = "\n".join(ei.value.errors)
    for frag in ("工厂表第 7 行“时区”：不认识的时区", "设备表第 5 行“工作站”：没有这个工作站", "工序表第 3 行“可用设备”：没有这台设备：no-such"):
        assert frag in text, (frag, text)


def test_unquoted_times_rejected():
    """YAML 里不加引号的 8:00:00 会被读成数字，校验要拦下。"""
    import yaml
    sys.path[:0] = [FAC]
    from factory import plant
    with open(DEMO, encoding="utf-8") as f:
        p = yaml.safe_load(f)
    p["shift"]["periods"] = yaml.safe_load("[[8:00:00, '12:00:00']]")
    assert any("带引号" in e for e in plant.validate(p))


def test_cli(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != "WQ_PLANT_FILE"}
    run = [sys.executable, "-m", "factory.plant"]
    x, y = str(tmp_path / "t.xlsx"), str(tmp_path / "p.yaml")
    for args in (["template", x], ["import", x, y], ["check", y]):
        r = subprocess.run(run + args, capture_output=True, text=True, cwd=FAC, env=env, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
    assert "清单无误" in r.stdout


TEXTS = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
from factory import plant
from hub import mrp
from hub.ai import Assistant
from hub.ont.agent import Agent
a = Assistant.__new__(Assistant)
g = Agent.__new__(Agent)
g.student = lambda u: False
print(json.dumps({{"name": plant.display_name(), "demo": plant.is_demo(), "company": mrp.COMPANY,
                  "ai": a._system("prod", "planner"), "agent": g._system({{"mode": "prod", "role": "planner"}}),
                  "tools": [t["name"] for t in g.tools_for({{"mode": "prod", "role": "manager", "teacher": True}})]}},
                 ensure_ascii=False))
"""


def _texts(plant=None):
    env = {k: v for k, v in os.environ.items() if k != "WQ_PLANT_FILE"}
    if plant:
        env["WQ_PLANT_FILE"] = plant
    r = subprocess.run([sys.executable, "-c", TEXTS.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_texts_follow_the_plant():
    """厂名、公司、AI 提示词随工厂清单（ADR-0064）；演示工厂（不设清单或用演示清单）不变。"""
    demo, demo_file = _texts(), _texts(DEMO)
    assert demo["name"] == demo_file["name"] == "问渠减速器厂" and demo["demo"]
    assert demo["company"] == "问渠减速器厂 WenQuest Gearbox (Demo)"
    assert "WQR-105" in demo["ai"] and "SH-301" in demo["agent"]
    assert "people_skills" in demo["tools"] and "ar_ap_cash" in demo["tools"]          # 第 30 轮：E1–E7 的工具只在演示工厂
    sew = _texts(os.path.join(FAC, "plants", "example-sewing.yaml"))
    assert sew["name"] == sew["company"] == "示例缝纫机厂" and not sew["demo"]
    for k in ("ai", "agent"):
        assert "“示例缝纫机厂”" in sew[k] and "WQR-105" not in sew[k] and "问渠减速器厂" not in sew[k], sew[k]
        assert "数控车床 CNC（2 台）" in sew[k] and "粗车 Rough turning" in sew[k]
    assert "people_skills" not in sew["tools"] and "ar_ap_cash" not in sew["tools"] and "simulate" in sew["tools"]


SIM = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from factory import data as F
from sim.engine import Engine, OP_UNITS, routing_for
F.ROUTINGS["RT-LS-T"] = [("下料 Sawing", 2), ("粗车 Rough turning", 10), ("调质 Quench & temper", 10),
                         ("精车 Finish turning", 9), ("磨外圆 Cylindrical grinding", 8), ("零件检验 Part inspection", 4)]
F.BOMS["LS-T"] = ("RT-LS-T", [("RM-45-D50", 0.6)])
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, wqbus.make(ty, src, data, mode="teach", corr=corr))), clock,
             mode="teach", auto_start=True, seed=1, status_every_s=1e9)
ops = routing_for("LS-T")
for op, _ in ops:
    ok, why = eng.command(OP_UNITS[op][0], {{"command": "dispatch", "work_order": "WO-T", "operation": op, "qty": 3,
                                            "item": "LS-T", "routing": ops}}, "WO-T")
    assert ok, why
while eng.q and clock.t < 3 * 86400:
    clock.t = max(clock.t, eng.next_event_time())
    eng.run_due()
ev = [m["data"] for t, m in out if m["type"] == "machine.event"]
print(json.dumps({{"machines": sorted(eng.machines), "agvs": sorted(eng.agvs),
                  "done": [e["operation"] for e in ev if e.get("event") == "op_complete"],
                  "last": any(e.get("last_op") for e in ev if e.get("event") == "op_complete"),
                  "units": sorted({{m["source"] for t, m in out}})}}, ensure_ascii=False))
"""


def test_sim_runs_an_enterprise_plant():
    """车间仿真按企业工厂的设备、物流小车、成品库跑完一张工单（ADR-0064 第 6 条）。"""
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "example-sewing.yaml"))
    r = subprocess.run([sys.executable, "-c", SIM.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["agvs"] == ["agv-1"] and "lathe-1" in out["machines"] and "cnc-l01-a" not in out["machines"]
    assert out["done"] == ["下料 Sawing", "粗车 Rough turning", "调质 Quench & temper", "精车 Finish turning",
                           "磨外圆 Cylindrical grinding", "零件检验 Part inspection"] and out["last"], out
    assert not any("cnc-l01" in u or "agv-01" in u for u in out["units"]), out["units"]


MRP = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
from hub import mrp
class O:
    def __init__(self, db, now, mode):
        import datetime as dt
        self.now = dt.datetime(2026, 10, 8, 9, tzinfo=dt.timezone.utc)
        self.pos = self.mrs = self.sos = self.wos = self.events = []
    def stock(self):
        return {{}}
mrp.Overview = O
pv = mrp.plan_order(None, "示例·华南服装设备经销", "SEW-DDL", 2, "2026-11-30")
print(json.dumps({{"wos": [w["production_item"] for w in pv["work_orders"]], "std": pv["std_cost_sh301"],
                  "company": pv["sales_order"]["company"], "rate": pv["sales_order"]["rate"],
                  "mr": sorted(m["item_code"] for m in pv["material_requests"])}}, ensure_ascii=False))
"""


def test_mrp_plans_an_enterprise_product():
    """企业工厂接单：MRP 不碰演示工厂的工艺（输出轴标准成本只在演示工厂算），销售订单记在清单的公司名下。"""
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "example-sewing.yaml"))
    r = subprocess.run([sys.executable, "-c", MRP.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["std"] is None and out["company"] == "示例缝纫机厂", out
    # 第 45 轮（清单第 2 版）：接的是清单里的成品，按清单的物料清单多层展开，下达全部自制件和成品本身，售价取清单
    assert sorted(out["wos"]) == ["HSG-HEAD", "LS-101", "LS-102", "SEW-DDL"] and out["rate"] == 2800, out
    assert {"BUY-MOTOR-DD", "RM-HT200-HEAD", "RM-45-D30"} <= set(out["mr"]), out     # 这里的库存快照是空的：外购件、原材料都要请购


MEAS = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from sim.engine import Engine, OP_UNITS, routing_for
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, wqbus.make(ty, src, data, mode="teach", corr=corr))), clock,
             mode="teach", auto_start=True, seed=3, status_every_s=1e9)
ops = routing_for("LS-101")
for op, _ in ops:
    ok, why = eng.command(OP_UNITS[op][0], {{"command": "dispatch", "work_order": "WO-M", "operation": op, "qty": 4,
                                            "item": "LS-101", "routing": ops}}, "WO-M")
    assert ok, why
while eng.q and clock.t < 3 * 86400:
    clock.t = max(clock.t, eng.next_event_time())
    eng.run_due()
ms = [(t, m["data"]) for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"topic": t, "char": d["characteristic"], "unit": d["unit"], "v": d["value_mm"], "lo": d["lower_tol_mm"],
                   "hi": d["upper_tol_mm"], "item": d["item"]}} for t, d in ms], ensure_ascii=False))
"""


def test_plant_measurements_are_synthesised():
    """第 45 轮：清单里写的测量特性，在那道工序做完每一件时由仿真车间合成测量值（名义 + 散布），发 quality.measurement"""
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "example-sewing.yaml"))
    r = subprocess.run([sys.executable, "-c", MEAS.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    ms = json.loads(r.stdout)
    assert len(ms) == 8 and {m["char"] for m in ms} == {"ls_bearing_d12", "ls_runout"}, ms   # 4 件 × 2 项
    assert all(m["item"] == "LS-101" and m["unit"] == "mm" and "/qc-1/measurement" in m["topic"] for m in ms), ms
    d = [m["v"] for m in ms if m["char"] == "ls_bearing_d12"]
    assert all(11.99 < v < 12.02 for v in d) and len(set(d)) > 1, d


TEACH = r"""
import json, os, sys
sys.path[:0] = [{dig!r}, {fac!r}]
os.environ["WQ_HUB_NO_START"] = "1"
os.environ.pop("WQ_AUTH", None)
from fastapi.testclient import TestClient
import hub.app as A
class _Teach:
    def start(self, name):
        pass
A.H.teach = _Teach()                    # 枢纽不启动（没有数据库）：实验 7 的登记换成空的
c = TestClient(A.app, raise_server_exceptions=False)
tok = c.post("/api/login", json={{"name": "测试", "role": "manager", "mode": "teach"}}).json()["token"]
h = {{"x-wq-token": tok}}
paths = ["/api/labs", "/api/lab15", "/api/lab23", "/api/story/state", "/api/finance/kpis", "/api/maint/assets",
         "/api/people/kpis", "/api/ehs/kpis", "/api/energy/kpis", "/api/supply/kpis", "/api/service/kpis", "/api/crm/pipeline",
         "/api/complaints", "/api/scenario/reset"]
out = {{"config": c.get("/api/config").json()["plant"],
       "mes": c.post("/api/mes/cmd", headers=h, json={{"unit": "sim", "command": "load_scenario"}}).status_code,
       "codes": {{p: (c.post(p, headers=h, json={{}}) if p.endswith("reset") else c.get(p, headers=h)).status_code for p in paths}},
       "layout": c.get("/api/layout").json()["units"]}}
if os.environ.get("WQ_PLANT_FILE"):     # 演示工厂会真的载入情景（要总线），这里只核对企业工厂拒绝
    from sim.main import Service
    s = Service.__new__(Service)
    s.mode = "teach"
    out["sim"] = list(s.sim_command({{"command": "load_scenario"}}, None))
print(json.dumps(out, ensure_ascii=False))
"""


def _teach(plant=None):
    env = {k: v for k, v in os.environ.items() if k not in ("WQ_PLANT_FILE", "WQ_AUTH")}
    if plant:
        env["WQ_PLANT_FILE"] = plant
    r = subprocess.run([sys.executable, "-c", TEACH.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env,
                       cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_teaching_features_hidden_on_enterprise_plant():
    """第 30 轮 H-2：企业工厂（示例缝纫机厂）里 E1–E7、实验 15–23、情景导演、实验 7 情景都不出现——
    接口 404、/api/config 告诉网页哪些入口不显示；工厂本身（车间布局、厂名）照常。"""
    out = _teach(os.path.join(FAC, "plants", "example-sewing.yaml"))
    cfg = out["config"]
    assert cfg["demo"] is False and cfg["name"] == cfg["company"] == "示例缝纫机厂" and cfg["currency"] == "CNY"
    for to in ("/labs", "/director", "/finance", "/maint", "/people", "/ehs", "/energy", "/supply", "/service", "/lab15", "/lab23", "/plc"):
        assert to in cfg["hidden"], to
    assert all(code == 404 for code in out["codes"].values()), out["codes"]
    assert out["mes"] == 400 and out["sim"][0] is False
    assert "lathe-1" in out["layout"] and "cnc-l01-a" not in out["layout"] and out["layout"]["lathe-1"].get("h")


def test_teaching_features_shown_on_demo_plant():
    """演示工厂：教学入口一个不少（hidden 为空），实验与任务的接口不被挡（不是 404）。"""
    out = _teach()
    assert out["config"]["demo"] is True and out["config"]["hidden"] == [] and out["config"]["name"] == "问渠减速器厂"
    assert out["codes"]["/api/labs"] != 404 and out["codes"]["/api/lab15"] != 404
    assert "cnc-l01-a" in out["layout"] and "h" not in out["layout"]["cnc-l01-a"]
