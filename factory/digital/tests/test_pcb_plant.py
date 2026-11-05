# -*- coding: utf-8 -*-
"""第 85 轮（电子 E3）：电路板厂（清单 wenquest-pcb）——SMT 线和功能测试出测量值；四种隐藏问题只在对应的设备 / 卷号上出偏差，
对症措施后消失；设备类别；问题与措施按厂分。仿真在子进程里按电路板厂清单跑（工厂数据在导入时读清单）。"""
import json
import os
import subprocess
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
PCB = os.path.join(FAC, "plants", "wenquest-pcb.yaml")

RUN = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from sim.engine import Engine, routing_for, OP_UNITS
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
clock = Clock()
eng = Engine(lambda tp, ty, src, data, corr: out.append((tp, wqbus.make(ty, src, data, mode="teach", corr=corr))), clock,
             mode="teach", auto_start=True, seed=7, status_every_s=1e9)
eng.set_reliability(0)
setup = {setup}
for k, v in setup.get("lot_used", {{}}).items():
    eng.errors.lot_used[k] = v
for it, lot, q in setup.get("add_lots", []):
    eng.errors.add_lot(it, lot, q)

def run(wo, item, qty):
    ops = routing_for(item)
    for op, _ in ops:
        ok, why = eng.command(OP_UNITS[op][0], {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": item,
                                                 "routing": ops}}, wo)
        assert ok, why
    while eng.q and clock.t < 60 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()

for i, (item, qty) in enumerate(setup["batches"]):
    for p in setup.get("inject_at", {{}}).get(str(i), []):
        eng.errors.inject(p)
    if str(i) in setup.get("fix_at", {{}}):
        eng.errors.apply_fix(setup["fix_at"][str(i)])
    run("WO-{{}}".format(i), item, qty)
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"wo": d["work_order"], "item": d["item"], "op": d["operation"], "char": d["characteristic"], "v": d["value_mm"],
                   "lot": d.get("lot"), "result": d["result"], "unit": d["unit"]}} for d in ms], ensure_ascii=False))
"""


def _run(setup):
    env = dict(os.environ, WQ_PLANT_FILE=PCB)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, char, wo=None):
    return [m["v"] for m in ms if m["char"] == char and (wo is None or m["wo"] == wo)]


def _mean(ms, char, wo=None):
    v = _vals(ms, char, wo)
    assert v, (char, wo)
    return sum(v) / len(v)


def test_manifest_checks():
    r = subprocess.run([sys.executable, "-m", "factory.plant", "check", PCB], capture_output=True, text=True, cwd=FAC)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "13 道工序" in r.stdout and "3 种可接单的成品" in r.stdout


def test_smt_and_fct_measurements_normal():
    ms = _run({"batches": [["SMT-DRV", 12], ["DRV-JOINT", 12]]})
    smt = [m for m in ms if m["item"] == "SMT-DRV"]
    assert {m["op"] for m in smt} == {"自动光学检测 AOI"}
    assert {m["char"] for m in smt} == {"spi_volume", "spi_height", "reflow_peak", "reflow_tal", "offset_chip", "offset_ic", "aoi_defects"}
    assert abs(_mean(ms, "spi_volume") - 100) < 6 and abs(_mean(ms, "reflow_peak") - 245) < 2
    assert all(float(v).is_integer() and v >= 0 for v in _vals(ms, "aoi_defects"))           # 计数型
    fct = [m for m in ms if m["item"] == "DRV-JOINT"]
    assert {m["char"] for m in fct} == {"ict_shunt", "fct_vbus", "fct_isense", "fct_deadtime", "fct_enc", "fct_drift"}
    assert {m["op"] for m in fct} == {"功能测试 FCT"}
    assert {m["lot"] for m in fct} == {"SH-001"}                                              # 在线测试时认出采样电阻卷号
    assert all(m["result"] == "pass" for m in fct if m["char"] == "ict_shunt")


def test_stencil_clog_lowers_volume_and_wipe_fixes():
    ms = _run({"inject_at": {"0": ["stencil_clog"]}, "batches": [["SMT-DRV", 30]]})
    v = _vals(ms, "spi_volume")
    assert sum(v[:5]) / 5 > 88 and sum(v[-10:]) / 10 < 78                                  # 逐块下降
    assert sum(_vals(ms, "aoi_defects")) >= 3                                              # 少锡缺陷增多
    fixed = _run({"inject_at": {"0": ["stencil_clog"]}, "fix_at": {"1": "wipe_stencil"}, "batches": [["SMT-DRV", 20], ["SMT-DRV", 20]]})
    assert _mean(fixed, "spi_volume", "WO-1") > 94
    wrong = _run({"inject_at": {"0": ["stencil_clog"]}, "fix_at": {"1": "replace_squeegee"}, "batches": [["SMT-DRV", 20], ["SMT-DRV", 20]]})
    assert _mean(wrong, "spi_volume", "WO-1") < 80                                          # 不对症的措施没用


def test_reflow_drift_and_profile_fixes():
    ms = _run({"inject_at": {"0": ["reflow_drift"]}, "batches": [["SMT-AGV", 40]]})
    peak = _vals(ms, "reflow_peak")
    assert sum(peak[-10:]) / 10 < 236 and any(m["result"] == "fail" for m in ms if m["char"] == "reflow_peak")
    assert _mean(ms, "spi_volume") > 94                                                    # 印刷不受影响
    fixed = _run({"inject_at": {"0": ["reflow_drift"]}, "fix_at": {"1": "profile_oven"}, "batches": [["SMT-AGV", 30], ["SMT-AGV", 20]]})
    assert abs(_mean(fixed, "reflow_peak", "WO-1") - 245) < 1.5
    wrong = _run({"inject_at": {"0": ["reflow_drift"]}, "fix_at": {"1": "raise_peak"}, "batches": [["SMT-AGV", 30], ["SMT-AGV", 20]]})
    assert _mean(wrong, "reflow_peak", "WO-1") < 236


def test_nozzle_wear_only_on_pp2_parts():
    ms = _run({"inject_at": {"0": ["nozzle_wear"]}, "batches": [["SMT-DRV", 30]]})
    assert abs(_mean(ms, "offset_chip")) < 8                                              # PP-1 贴的片式元件正常
    assert _mean(ms, "offset_ic") > 25                                                      # PP-2 贴的 IC 偏移变大
    fixed = _run({"inject_at": {"0": ["nozzle_wear"]}, "fix_at": {"1": "replace_nozzle"}, "batches": [["SMT-DRV", 10], ["SMT-DRV", 20]]})
    assert abs(_mean(fixed, "offset_ic", "WO-1")) < 6


def test_shunt_lot_from_injected_reel_and_quarantine():
    base = _run({"lot_used": {"SH": 30}, "batches": [["DRV-JOINT", 10]]})
    assert {m["lot"] for m in base} == {"SH-002"}
    ms = _run({"lot_used": {"SH": 30}, "inject_at": {"0": ["shunt_lot"]}, "batches": [["DRV-JOINT", 10]]})
    assert _mean(ms, "ict_shunt") > 2.03 and _mean(ms, "fct_isense") > 1.8
    assert _mean(ms, "fct_vbus") < 0.3                                                      # 只影响电流采样
    fixed = _run({"lot_used": {"SH": 32}, "inject_at": {"0": ["shunt_lot"]}, "fix_at": {"1": "quarantine_shunt"},
                  "batches": [["DRV-JOINT", 2], ["DRV-JOINT", 10]]})
    after = [m for m in fixed if m["wo"] == "WO-1"]
    assert {m["lot"] for m in after} == {"SH-003"}                                          # 隔离后换下一卷
    assert abs(_mean(fixed, "ict_shunt", "WO-1") - 2.0) < 0.005
    enc = _run({"inject_at": {"0": ["shunt_lot"]}, "batches": [["ENC-RD", 5]]})            # 读头板不用采样电阻：不受影响
    assert not {m["lot"] for m in enc} - {None}


def test_warehouse_reels_used_first():
    ms = _run({"add_lots": [["RES-SHUNT", "L261105-0007", 9]], "batches": [["DRV-JOINT", 5]]})
    lots = [m["lot"] for m in ms if m["char"] == "ict_shunt"]
    assert sorted(lots) == ["L261105-0007"] * 3 + ["SH-001"] * 2                         # 每块 3 只：到货的一卷够 3 块，之后按顺序编卷


def test_problems_and_fixes_by_plant():
    sys.path[:0] = [DIG, FAC]
    from sim import errors as E
    pcb = E.problems_for("wenquest-pcb")
    assert set(pcb) == {"stencil_clog", "reflow_drift", "nozzle_wear", "shunt_lot"}
    assert set(E.problems_for("wenquest-robot")) == {"ja_torque", "hd_lot", "bench_zero"}
    demo = E.problems_for("wenquest-gearbox")
    assert "tailstock_offset" in demo and not set(demo) & set(pcb)
    f = E.fixes_for("wenquest-pcb")
    assert {"wipe_stencil", "profile_oven", "replace_nozzle", "quarantine_shunt", "retrain"} <= set(f)
    assert "align_tailstock" not in f and "recalibrate_torque" not in f
    g = E.fixes_for("wenquest-gearbox")
    assert "align_tailstock" in g and "wipe_stencil" not in g and "recalibrate_torque" not in g and "retrain" in g


def test_equipment_kinds():
    sys.path[:0] = [FAC]
    from factory import equip as Q
    kinds = {u: Q.kind_of(u) for u in ("sp-1", "spi-1", "pp-2", "rf-1", "aoi-1", "sw-1", "ict-1", "pg-1", "cc-1", "bi-1", "fct-1", "pk-1")}
    assert kinds == {"sp-1": "printer", "spi-1": "spi", "pp-2": "placer", "rf-1": "reflow", "aoi-1": "aoi", "sw-1": "selsolder",
                     "ict-1": "ict", "pg-1": "program", "cc-1": "coater", "bi-1": "burnin", "fct-1": "fct", "pk-1": "pack"}
    for k in set(kinds.values()):
        d = Q.KIND[k]
        assert d["hazards"] and d["modes"] and len(d["power"]) == 3 and d["pm_h"] > 0


RULES = RUN.split('ms = [m["data"]')[0] + r"""
from hub.ont import anomaly as A
from hub.ont import rules as R
import datetime as dt
cat = A.load_catalog()
class FakeDB:
    def messages(self, types=None, mode=None, order="asc", limit=None, **k):
        rows = [dict(m, _topic=t, _seq=i) for i, (t, m) in enumerate(out) if m["type"] in (types or [m["type"]])]
        if order == "desc":
            rows = rows[::-1]
        return rows[:limit] if limit else rows
res = {{"catalog": sorted(k for k in cat if k.startswith("QE")), "waiting": sorted(k for k, r in cat.items() if r["waiting"] and k.startswith("QE"))}}
c = A.Ctx(FakeDB(), "teach", dt.datetime.now(dt.timezone.utc))
for rid in ("QE1", "QE2", "QE3", "QE4"):
    r = cat[rid]
    res[rid] = [[f.fkey, f.title + " " + str(f.detail), f.severity] for f in R.REG[r["fn"]](c, r["params"], r)]
print(json.dumps(res, ensure_ascii=False))
"""


def _rules(setup):
    env = dict(os.environ, WQ_PLANT_FILE=PCB)
    r = subprocess.run([sys.executable, "-c", RULES.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_ai_rules_quiet_when_normal():
    res = _rules({"batches": [["SMT-DRV", 60], ["SMT-DRV", 20], ["DRV-JOINT", 12]]})
    assert res["catalog"] == ["QE1", "QE2", "QE3", "QE4", "QE5"] and res["waiting"] == ["QE5"]
    assert not any(res[k] for k in ("QE1", "QE2", "QE3", "QE4")), res


def test_ai_rules_report_injected_problems():
    res = _rules({"inject_at": {"1": ["stencil_clog", "reflow_drift"]}, "batches": [["SMT-DRV", 60], ["SMT-DRV", 30]]})
    assert res["QE3"] and res["QE2"] and res["QE1"], res
    res = _rules({"inject_at": {"1": ["nozzle_wear"]}, "batches": [["SMT-DRV", 60], ["SMT-DRV", 25]]})
    assert res["QE1"] and not res["QE3"], res
    res = _rules({"lot_used": {"SH": 30}, "inject_at": {"0": ["shunt_lot"]}, "batches": [["DRV-JOINT", 12]]})
    assert res["QE4"] and "SH-002" in res["QE4"][0][1], res


def test_pcb_rules_not_in_other_plants():
    sys.path[:0] = [DIG, FAC]
    from hub.ont import anomaly as A
    assert not any(k.startswith("QE") for k in A.load_catalog())


def test_pcb_domains_with_db():
    """各领域按电路板厂的设备打开（第 59、61 轮的做法）：设备台账、电表、应收、危险源、人员排班"""
    import test_domains_robot as D
    o = D._run(PCB, D._fresh("wq_dom_pcb_test"))
    units = {"sp-1", "spi-1", "pp-1", "pp-2", "rf-1", "aoi-1", "sw-1", "ict-1", "pg-1", "cc-1", "bi-1", "fct-1", "pk-1"}
    assert set(o["rel"]) == units and set(o["power"]) == units and set(o["assets"]) == units
    assert o["power"]["rf-1"] == [30.0, 18.0, 2.0] and o["assets"]["pp-1"] == 250000
    assert o["open"] == ["/api/maint/assets", "/api/energy/overview", "/api/finance/kpis", "/api/ehs", "/api/people"]
    rows = {u: (n, v, pm) for u, n, v, pm in o["asset_rows"]}
    assert rows["pp-2"][0] == "多功能贴片机" and rows["bi-1"][2] == 1500
    assert dict(o["meters"])["E-RF-1"] == [30.0, 18.0, 2.0]
    assert o["ar"] and o["ar"][0][0].startswith("示例·工业机器人集成商")
    hz = {u for u, _ in o["hazards"]}
    assert {"rf-1", "sw-1", "cc-1", "fct-1"} <= hz
    assert "rf-1" not in o["needs"] and "bi-1" not in o["needs"] and "pp-1" in o["needs"]        # 回流炉、老化房不用人看着
    assert o["people_n"] > 10
