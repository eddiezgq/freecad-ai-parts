# -*- coding: utf-8 -*-
"""第 47 轮：机器人厂的实验 24、25——关节的装配工位与谐波减速器批次、三种隐藏问题只在对应的工位 / 批次 / 测试台上出偏差、
对症措施后消失；多层标准成本；实验列表按工厂显示。仿真在子进程里按机器人厂清单跑（工厂数据在导入时读清单）。"""
import json
import os
import subprocess
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")

RUN = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from sim.engine import Engine, routing_for
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, wqbus.make(ty, src, data, mode="teach", corr=corr))), clock,
             mode="teach", auto_start=True, seed=5, status_every_s=1e9)
setup = {setup}
for k, v in setup.get("lot_used", {{}}).items():
    eng.errors.lot_used[k] = v
for p in setup.get("inject", []):
    eng.errors.inject(p)
for it, lot, q in setup.get("add_lots", []):        # 第 51 轮：仓库里的到货批次
    eng.errors.add_lot(it, lot, q)

def run(wo, ja, qty):
    ops = routing_for("WQJ-L")
    for op, _ in ops:
        unit = ja if op.startswith("关节装配") else "jt-1"
        ok, why = eng.command(unit, {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": "WQJ-L",
                                      "routing": ops}}, wo)
        assert ok, why
    while eng.q and clock.t < 30 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()

for i, (ja, qty) in enumerate(setup["batches"]):
    if setup.get("inject_before") == i:
        eng.errors.inject(setup["inject_late"])
    if setup.get("fix_before") == i:
        eng.errors.apply_fix(setup["fix"])
    run("WO-{{}}".format(i), ja, qty)
starts = [m["data"] for t, m in out if m["type"] == "machine.event" and m["data"]["event"] == "cycle_start" and m["data"]["op_index"] == 0]
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
if setup.get("lots_in_events"):
    print(json.dumps([(d.get("lots") or {{}}).get("HD-CSF-32-100") for d in starts]))
    sys.exit(0)
print(json.dumps([{{"wo": d["work_order"], "char": d["characteristic"], "v": d["value_mm"], "ja": d.get("assembled_on"),
                   "lot": d.get("lot"), "serial": d["part_serial"], "result": d["result"]}} for d in ms], ensure_ascii=False))
"""


def _run(setup):
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _mean(ms, char, **kw):
    v = [m["v"] for m in ms if m["char"] == char and all(m.get(k) == x for k, x in kw.items())]
    assert v, (char, kw)
    return sum(v) / len(v)


def test_joints_record_station_and_lot():
    ms = _run({"batches": [("ja-1", 6), ("ja-2", 6)]})
    bl = [m for m in ms if m["char"] == "joint_backlash"]
    assert len(bl) == 12
    assert {m["ja"] for m in bl} == {"ja-1", "ja-2"}
    assert [m["lot"] for m in bl] == ["HD-L-001"] * 8 + ["HD-L-002"] * 4       # 每批 8 台，按装配顺序
    assert abs(_mean(ms, "joint_backlash", ja="ja-1") - _mean(ms, "joint_backlash", ja="ja-2")) < 0.15   # 正常时两个工位一样


def test_torque_problem_only_on_ja2_and_fix_works():
    ms = _run({"inject": ["ja_torque"], "batches": [("ja-1", 8), ("ja-2", 8)]})
    assert _mean(ms, "joint_backlash", ja="ja-2") - _mean(ms, "joint_backlash", ja="ja-1") > 0.25
    fixed = _run({"inject": ["ja_torque"], "fix": "recalibrate_torque", "fix_before": 0, "batches": [("ja-2", 8)]})
    assert _mean(fixed, "joint_backlash", ja="ja-2") < 0.8
    wrong = _run({"inject": ["ja_torque"], "fix": "add_grease", "fix_before": 0, "batches": [("ja-2", 8)]})
    assert _mean(wrong, "joint_backlash", ja="ja-2") > 0.85                    # 不对症的措施没用


def test_lot_problem_only_from_injected_lot_and_quarantine_works():
    ms = _run({"lot_used": {"L": 8}, "inject": ["hd_lot"], "batches": [("ja-1", 8)]})
    assert {m["lot"] for m in ms} == {"HD-L-002"}
    assert _mean(ms, "joint_backlash") > 0.85
    before = _run({"batches": [("ja-1", 8)]})                                   # 第 1 批（没问题）
    assert _mean(before, "joint_backlash") < 0.8
    fixed = _run({"lot_used": {"L": 3}, "inject": ["hd_lot"], "fix": "quarantine_lot", "fix_before": 0, "batches": [("ja-1", 8)]})
    assert {m["lot"] for m in fixed} == {"HD-L-002"}                            # 隔离后剩下的第 1 批不用了，换第 2 批
    assert _mean(fixed, "joint_backlash") < 0.8


def test_real_lots_fifo_and_lot_problem():
    """第 51 轮 S-7：仓库有到货批次时，关节按先进先出用到货批次（批号就是来料的批号），开工事件带上批次；
    “一批减速器背隙偏大”从注入时在用的那一批起；隔离后那一批剩下的不用了，换下一批"""
    lots = [["HD-CSF-32-100", "L261028-0001", 5], ["HD-CSF-32-100", "L261028-0002", 10]]
    ev = _run({"add_lots": lots, "batches": [("ja-1", 4), ("ja-2", 6)], "lots_in_events": True})
    assert ev == ["L261028-0001"] * 5 + ["L261028-0002"] * 5
    ms = _run({"add_lots": lots, "batches": [("ja-1", 4), ("ja-1", 6)], "inject_before": 1, "inject_late": "hd_lot"})
    bl = [m for m in ms if m["char"] == "joint_backlash"]
    assert [m["lot"] for m in bl] == ["L261028-0001"] * 5 + ["L261028-0002"] * 5
    assert sum(m["v"] for m in bl[:4]) / 4 < 0.8 and sum(m["v"] for m in bl[4:]) / 6 > 0.85     # 注入时在用第 1 批：从它起都偏大
    fixed = _run({"add_lots": lots, "inject": ["hd_lot"], "fix": "quarantine_lot", "fix_before": 1, "batches": [("ja-1", 4), ("ja-1", 6)]})
    bl = [m for m in fixed if m["char"] == "joint_backlash"]
    assert [m["lot"] for m in bl] == ["L261028-0001"] * 4 + ["L261028-0002"] * 6      # 第 1 批剩下的 1 台不用了
    assert sum(m["v"] for m in bl[4:]) / 6 < 0.8
    mixed = _run({"add_lots": [["HD-CSF-32-100", "L261028-0003", 2]], "batches": [("ja-1", 4)]})
    assert [m["lot"] for m in mixed if m["char"] == "joint_backlash"] == ["L261028-0003"] * 2 + ["HD-L-001"] * 2   # 到货批次用完再用库里的


def test_bench_zero_drifts_for_all_joints_and_fix_works():
    ms = _run({"inject": ["bench_zero"], "batches": [("ja-1", 6), ("ja-2", 6)]})
    z = [m["v"] for m in ms if m["char"] == "joint_zero"]
    assert sum(z[-4:]) / 4 - sum(z[:4]) / 4 > 5                                # 逐台偏移，两个工位都有
    assert abs(_mean(ms, "joint_backlash", ja="ja-2") - _mean(ms, "joint_backlash", ja="ja-1")) < 0.15
    fixed = _run({"inject": ["bench_zero"], "fix": "recalibrate_bench", "fix_before": 0, "batches": [("ja-1", 8)]})
    assert abs(_mean(fixed, "joint_zero")) < 6


def test_catalog_is_per_plant():
    from sim import errors as ERR
    assert set(ERR.problems_for("wenquest-robot")) == {"ja_torque", "hd_lot", "bench_zero"}
    assert set(ERR.problems_for(None)) == {"tailstock_offset", "dressing_interval", "thermal_warmup", "locator_worn", "center_hole"}
    assert "recalibrate_torque" not in ERR.fixes_for(None) and "align_tailstock" not in ERR.fixes_for("wenquest-robot")
    for p, v in ERR.problems_for("wenquest-robot").items():
        assert v["fix"] in ERR.fixes_for("wenquest-robot"), p


STD = r"""
import json, sys, yaml
sys.path[:0] = [{dig!r}, {fac!r}]
from hub import mrp, course
raw = yaml.safe_load(open({plant!r}, encoding="utf-8"))
items = {{i["code"]: i for i in raw["items"]}}
boms = {{b["item"]: b for b in raw["boms"]}}
from factory import data as F
from hub.kpi import rate_per_hour
from sim.engine import OP_UNITS
routes = {{r["name"]: r["steps"] for r in raw["routings"]}}
def roll(code):
    if code not in boms:
        return items[code].get("price") or 0, 0
    m = o = 0
    for c, q in boms[code]["components"]:
        a, b = roll(c)
        m += q * a
        o += q * b
    o += sum(mins / 60 * rate_per_hour(OP_UNITS[op][0]) for op, mins in routes[boms[code]["routing"]])
    return m, o
r = mrp.std_rollup("WQ-CR5")
c = course.std_cost("WQ-CR5")
print(json.dumps({{"mine": roll("WQ-CR5"), "rollup": [r["material"], r["operations"]], "course": [c["material"], c["operations"]],
                  "unit": mrp.std_unit_cost("WQ-CR5")}}))
"""


def test_multilevel_standard_cost():
    """L-6：WQ-CR5 的标准成本 = 各层逐项相加（按清单原文独立算一遍核对）；每张工单的标准单件成本 = 逐层材料 + 本层工序"""
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", STD.format(dig=DIG, fac=FAC, plant=ROBOT)], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    for a, b in zip(out["mine"], out["rollup"]):
        assert abs(a - b) < 1e-6
    for a, b in zip(out["course"], out["rollup"]):
        assert abs(a - b) < 0.01
    assert abs(out["unit"][0] - out["mine"][0]) < 0.01 and out["unit"][1] < out["mine"][1]


def test_robot_labs_listed_only_in_robot_plant():
    code = ("import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import labs_api as L\n"
            "print(json.dumps([l['no'] for l in L.labs_here()]))").format(DIG, FAC)
    got = {}
    for name, path in (("robot", ROBOT), ("gear", "")):
        env = dict(os.environ, WQ_PLANT_FILE=path)
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=60)
        assert r.returncode == 0, r.stderr[-2000:]
        got[name] = json.loads(r.stdout)
    assert got["robot"] == [24, 25, 26, 27, 28] and got["gear"] == [7, 15, 16, 17, 18, 19, 20, 21, 22, 23]


LAB25 = r"""
import json, os, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_lab25_test with (force)")
    c.execute("create database wq_lab25_test")
from hub.db import DB
from hub.historian import Historian
from hub import lab25, qproblem
from sim.engine import Engine, routing_for
db = DB(BASE + "/wq_lab25_test")
db.init()
h = Historian(db)
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: h.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
             mode="teach", auto_start=True, seed=11, status_every_s=1e9)
def send(cmd, **k):
    if cmd == "set_problem":
        eng.errors.inject(k["problem"], k.get("magnitude"))
    elif cmd == "apply_fix":
        eng.errors.apply_fix(k["fix"])
n = [0]
def run(ja, qty):
    n[0] += 1
    wo = "WO-{{}}".format(n[0])
    ops = routing_for("WQJ-L")
    for op, _ in ops:
        unit = ja if op.startswith("关节装配") else "jt-1"
        assert eng.command(unit, {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": "WQJ-L", "routing": ops}}, wo)[0]
    while eng.q and clock.t < 60 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()
STU, TEA = "学生甲", {{"name": "王老师", "mode": "teach", "teacher": True}}
out = {{}}
run("ja-1", 6)
lab25.inject(db, send, TEA, {kind!r})
for _ in range(3):
    run("ja-1", 6)
    run("ja-2", 6)
sig = lab25.signals(db, "WQJ-L", {char!r})
out["t1"] = lab25.answer(db, STU, "l25_t1", {{"characteristic": "WQJ-L|" + {char!r}, "rule": sig[0]["rule"] if sig else 0}})["score"]
out["t2"] = lab25.answer(db, STU, "l25_t2", {answer2})["score"]
out["t2_wrong"] = lab25.answer(db, "学生乙", "l25_t2", {{"by": "station", "group": "ja-1"}})["score"]
s = qproblem.create(db, "teach", STU, None, "WQJ-L", {char!r}, "关节数据异常", {{"d1": "我", "d2": "数据", "d3": "复测", "d4": "原因", "d5": "校准"}})
qproblem.update(db, s["id"], {{}}, {fix!r})
qproblem.submit_fix(db, s["id"])
qproblem.decide_fix(db, send, s["id"], "王老师", True)
for _ in range(2):
    run("ja-1", 6)
    run("ja-2", 6)
v = qproblem.verify(db, s["id"])
out["verify"] = {{"effective": v["effective"], "after": v["after"]}}
qproblem.update(db, s["id"], {{"d7": "扭力扳手每班校准"}})
try:
    qproblem.close(db, s["id"], "学生甲")
except ValueError as e:
    out["close_err"] = str(e)
st = lab25.check(db, STU)
out["tasks"] = {{t["id"]: t["score"] for t in st["tasks"]}}
out["score"] = st["score"]
out["strata"] = lab25.strata(db, "WQJ-L|joint_backlash")
print(json.dumps(out, ensure_ascii=False, default=str))
"""

BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]


def _lab25(kind, char, answer2, fix):
    import pytest
    psycopg = pytest.importorskip("psycopg")
    try:
        psycopg.connect(BASE + "/postgres").close()
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", LAB25.format(dig=DIG, fac=FAC, base=BASE, kind=kind, char=char, answer2=repr(answer2), fix=fix)],
                       capture_output=True, text=True, env=env, cwd=DIG, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def test_lab25_full_marks_for_station_problem():
    out = _lab25("ja_torque", "joint_backlash", {"by": "station", "group": "ja-2"}, "recalibrate_torque")
    assert out["t1"] == 10 and out["t2"] == 15 and out["t2_wrong"] == 10, out
    assert out["verify"]["effective"], out
    assert out["score"] == 60, out
    st = out["strata"]["station"]
    assert st["ja-2"]["mean"] - st["ja-1"]["mean"] > 0.2, st


def test_lab25_bench_problem_layer_is_sequence():
    out = _lab25("bench_zero", "joint_zero", {"by": "sequence"}, "recalibrate_bench")
    assert out["t1"] == 10 and out["t2"] == 15, out
    assert out["verify"]["effective"] and out["score"] == 60, out


def test_lab25_lot_problem():
    out = _lab25("hd_lot", "joint_backlash", {"by": "lot", "group": "HD-L-002"}, "quarantine_lot")
    assert out["t1"] == 10 and out["t2"] == 15, out
    assert out["verify"]["effective"] and out["score"] == 60, out
