# -*- coding: utf-8 -*-
"""第 147 轮：通用质量追因实验（hub/labq.py）——电机厂实验 35、传感器厂实验 36（第 148 轮加电路板厂实验 37、芯片封测厂实验 38），每种隐藏问题各走一遍：注入 → 判异 → 分层并说出设备 →
8D、对症措施、验证有效、关闭，满分 60；分层答错扣分；实验列表按厂显示。仿真在子进程里按各厂清单跑。"""
import json
import os
import subprocess
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
BASE = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test").rsplit("/", 1)[0]

LABQ = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists {dbn} with (force)")
    c.execute("create database {dbn}")
from hub.db import DB
from hub.historian import Historian
from hub import qproblem
import importlib
lab = importlib.import_module("hub." + {mod!r})
from sim.engine import Engine, routing_for, OP_UNITS
db = DB(BASE + "/" + {dbn!r})
db.init()
h = Historian(db)
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: h.handle(tp, wqbus.make(ty, src, data, mode="teach", corr=corr)), clock,
             mode="teach", auto_start=True, seed=11, status_every_s=1e9)
eng.set_reliability(0)
def send(cmd, **k):
    if cmd == "set_problem":
        eng.errors.inject(k["problem"], k.get("magnitude"))
    elif cmd == "apply_fix":
        eng.errors.apply_fix(k["fix"])
n = [0]
def run(item, qty, pick=None):
    n[0] += 1
    wo = "WO-{{}}".format(n[0])
    ops = routing_for(item)
    for op, _ in ops:
        u = next((v for k, v in (pick or {{}}).items() if op.startswith(k)), OP_UNITS[op][0])
        ok, why = eng.command(u, {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": item, "routing": ops}}, wo)
        assert ok, why
    while eng.q and clock.t < 365 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()
PICKS = {picks!r}
def batch():
    for pk in PICKS:
        run({item!r}, {qty!r}, pk)
STU, TEA = "学生甲", {{"name": "王老师", "mode": "teach", "teacher": True}}
out = {{}}
batch()
out["inject_text"] = lab.inject(db, send, TEA, {kind!r})["text"]
for _ in range(3):
    batch()
sig = lab.signals(db, {item!r}, {char!r})
out["t1"] = lab.answer(db, STU, {pre!r} + "t1", {{"characteristic": {item!r} + "|" + {char!r}, "rule": sig[0]["rule"] if sig else 0}})["score"]
out["t2"] = lab.answer(db, STU, {pre!r} + "t2", {answer2})["score"]
out["t2_wrong"] = lab.answer(db, "学生乙", {pre!r} + "t2", {wrong2})["score"]
s = qproblem.create(db, "teach", STU, None, {item!r}, {char8d!r}, "数据异常", {{"d1": "我", "d2": "数据", "d3": "隔离", "d4": "原因", "d5": "措施"}})
qproblem.update(db, s["id"], {{}}, {fix!r})
qproblem.submit_fix(db, s["id"])
qproblem.decide_fix(db, send, s["id"], "王老师", True)
for _ in range(2):
    batch()
v = qproblem.verify(db, s["id"])
out["verify"] = {{"effective": v["effective"], "after": v["after"]}}
qproblem.update(db, s["id"], {{"d7": "防错"}})
qproblem.close(db, s["id"], "学生甲")
st = lab.check(db, STU)
out["tasks"] = {{t["id"]: t["score"] for t in st["tasks"]}}
out["score"] = st["score"]
out["chars"] = [c["value"] for c in st["characteristics"]]
out["strata"] = lab.strata(db, {item!r} + "|" + {char!r})
print(json.dumps(out, ensure_ascii=False, default=str))
"""


def _labq(plant, mod, kind, item, char, answer2, wrong2, fix, picks, qty=6, char8d=None):
    """plant 为 None：演示工厂（不指定清单）"""
    psycopg = pytest.importorskip("psycopg")
    try:
        psycopg.connect(BASE + "/postgres").close()
    except Exception:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL")
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant)))
    if plant is None:
        env.pop("WQ_PLANT_FILE")
    code = LABQ.format(dbn="wq_labq_{}_{}".format(mod, kind), dig=DIG, fac=FAC, base=BASE, mod=mod, pre=mod.replace("lab", "l") + "_", kind=kind, item=item, char=char, char8d=char8d or char,
                       answer2=repr(answer2), wrong2=repr(wrong2), fix=fix, picks=picks, qty=qty)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=1200)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _full(out):
    assert out["t1"] == 10 and out["t2"] == 15, out
    assert out["verify"]["effective"], out
    assert out["score"] == 60, out


WD = [{"绕线": "wd-1"}, {"绕线": "wd-2"}]
CB = [{"码盘粘接对心": "cb-1"}, {"码盘粘接对心": "cb-2"}]


@pytest.mark.parametrize("kind,char,layer,unit,fix", [
    ("wind_tension", "st_r_unbal", "station", "wd-2", "fix_tensioner"),
    ("varnish_low", "st_leak", "shared", "vo-1", "profile_varnish"),
    ("magnetizer_low", "mt_ke", "shared", "mz-1", "service_magnetizer"),
    ("mag_fixture", "mt_cog", "shared", "mg-1", "replace_mag_fixture"),
])
def test_lab35_motor(kind, char, layer, unit, fix):
    wrong = {"by": "shared" if layer == "station" else "station", "group": unit}
    out = _labq("motor", "lab35", kind, "WQ-SM200", char, {"by": layer, "group": unit}, wrong, fix, WD)
    _full(out)
    assert out["t2_wrong"] == 0, out
    if layer == "station":
        st = out["strata"]["station"]
        assert st["wd-2"]["mean"] > st["wd-1"]["mean"], st


@pytest.mark.parametrize("kind,item,char,layer,unit,fix", [
    ("fixture_wear", "WQ-ENC17", "enc_h1", "station", "cb-2", "replace_fixture"),
    ("gap_gauge", "WQ-ENC17", "enc_amp", "shared", "hm-1", "replace_gap_gauge"),
    ("ffu_clog", "WQ-ENC17", "enc_amp_min", "shared", "dcl-1", "replace_ffu"),
    ("cure_low", "WQ-TS", "ts_creep", "shared", "cur-1", "profile_cure"),
])
def test_lab36_sensor(kind, item, char, layer, unit, fix):
    wrong = {"by": layer, "group": "xx-9"}
    picks = CB if item == "WQ-ENC17" else [{}, {}]
    out = _labq("sensor", "lab36", kind, item, char, {"by": layer, "group": unit}, wrong, fix, picks)
    _full(out)
    assert out["t2_wrong"] == 10, out


@pytest.mark.parametrize("kind,item,char,fix,unit", [
    ("stencil_clog", "SMT-DRV", "spi_volume", "wipe_stencil", "sp-1"),
    ("reflow_drift", "SMT-DRV", "reflow_peak", "profile_oven", "rf-1"),
    ("nozzle_wear", "SMT-DRV", "offset_ic", "replace_nozzle", "pp-2"),
])
def test_lab37_pcb_process(kind, item, char, fix, unit):
    out = _labq("pcb", "lab37", kind, item, char, {"by": "shared", "group": unit}, {"by": "lot", "group": "SH-001"}, fix, [{}, {}])
    _full(out)
    assert out["t2_wrong"] == 0, out
    assert out["strata"] == {"lot": {}}, out["strata"]       # 贴片板不带批次：分批表是空的、没有按设备的表


def test_lab37_pcb_shunt_lot():
    """第 148 轮：按来料批次分层——说出偏了的那一卷得满分，说一卷没偏的（措施后换上的新卷）只得 10 分"""
    out = _labq("pcb", "lab37", "shunt_lot", "DRV-JOINT", "ict_shunt", {"by": "lot", "group": "SH-001"}, {"by": "lot", "group": "SH-999"},
                "quarantine_shunt", [{}, {}])
    _full(out)
    assert out["t2_wrong"] == 10, out
    lots = out["strata"]["lot"]
    assert lots["SH-001"]["mean"] > 2.02 and any(k != "SH-001" and abs(v["mean"] - 2.0) < 0.01 for k, v in lots.items()), lots


WB = [{"引线键合": "wb-1"}, {"引线键合": "wb-2"}]


@pytest.mark.parametrize("kind,item,char,layer,unit,fix", [
    ("capillary_wear", "WQ-ENCIF", "bond_pull", "station", "wb-2", "replace_capillary"),
    ("blade_wear", "WQ-ENCIF", "chipping", "shared", "dc-1", "replace_blade"),
    ("emc_moisture", "WQ-ENCIF", "mold_void", "shared", "mld-1", "emc_handling"),
    ("probe_wear", "WAF-ENCIF-CP", "cp_contact", "shared", "prb-1", "clean_probe"),
])
def test_lab38_chip(kind, item, char, layer, unit, fix):
    wrong = {"by": "shared" if layer == "station" else "station", "group": unit}
    out = _labq("chip", "lab38", kind, item, char, {"by": layer, "group": unit}, wrong, fix, WB if item == "WQ-ENCIF" else [{}, {}])
    _full(out)
    assert out["t2_wrong"] == 0, out
    if layer == "station":
        st = out["strata"]["station"]
        assert st["wb-2"]["mean"] < st["wb-1"]["mean"], st


@pytest.mark.parametrize("kind,char,unit,fix,char8d", [
    ("tailstock_offset", "bearing_seat_d35_r", "grd-01", "align_tailstock", "gear_seat_d40"),
    ("dressing_interval", "bearing_seat_d35", "grd-01", "shorten_dressing", None),
    ("thermal_warmup", "gear_seat_d40", "grd-01", "warm_up", None),
    ("center_hole", "runout_bearing", "grd-01", "lap_center_holes", None),
    ("wheel_dull", "ra_bearing", "grd-01", "sharp_dressing", None),
    ("locator_worn", "keyway_sym", "key-01", "replace_locator", None),
])
def test_lab41_gearbox(kind, char, unit, fix, char8d):
    """第 152 轮：演示工厂（减速器厂）输出轴——判异按均值–极差图；每道工序一台设备，分层答设备；说错设备只得 10 分"""
    wrong = {"by": "shared", "group": "key-01" if unit == "grd-01" else "grd-01"}
    out = _labq(None, "lab41", kind, "SH-301", char, {"by": "shared", "group": unit}, wrong, fix, [{}], qty=10, char8d=char8d)
    _full(out)
    assert out["t2_wrong"] == 10, out
    assert out["strata"] == {}, out["strata"]
    assert "SH-301|burn_bearing" not in out["chars"] and "SH-301|bearing_seat_d35_r" in out["chars"], out["chars"]


def test_lab41_any_affected_char_counts():
    """尾座偏移让左右轴承位、齿轮位一起偏：任务 1 答齿轮位也算对"""
    out = _labq(None, "lab41", "tailstock_offset", "SH-301", "gear_seat_d40", {"by": "shared", "group": "grd-01"},
                {"by": "station", "group": "grd-01"}, "align_tailstock", [{}], qty=10)
    _full(out)
    assert out["t2_wrong"] == 0, out


@pytest.mark.parametrize("plant,nos", [("motor", [35]), ("sensor", [36]), ("pcb", [37, 39]), ("chip", [38, 40]),
                                       ("gearbox", [7, 15, 16, 17, 18, 19, 20, 21, 22, 23, 33, 41])])
def test_quality_labs_listed_per_plant(plant, nos):
    code = ("import sys, json; sys.path[:0] = [{!r}, {!r}]\nfrom hub import labs_api as L\n"
            "print(json.dumps([l['no'] for l in L.labs_here()]))").format(DIG, FAC)
    env = dict(os.environ, WQ_PLANT_FILE=os.path.join(FAC, "plants", "wenquest-{}.yaml".format(plant)))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=DIG, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    assert json.loads(r.stdout) == nos


@pytest.mark.parametrize("lab", ["lab35", "lab36", "lab37", "lab38", "lab41"])
def test_quality_lab_docs(lab):
    sys.path[:0] = [DIG, FAC]
    from cae import labdoc
    assert len(labdoc.guide_docx(lab)) > 10000 and len(labdoc.report_template_docx(lab)) > 10000
