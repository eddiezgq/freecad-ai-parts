# -*- coding: utf-8 -*-
"""第 134 轮：问渠缝纫机厂（清单 wenquest-sewing）——按《缝纫机厂工艺方案》建的五个车间；铸件、机壳、关键零件、整机出测量值；
五种隐藏问题只在对应的设备上出偏差（定位销磨损只在 hmc-3 精镗的平缝机壳），对症措施后消失、不对症的不消失；设备类别；问题与措施按厂分；AI 巡检。"""
import json
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
SEW = os.path.join(FAC, "plants", "wenquest-sewing.yaml")

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
             mode="teach", auto_start=True, seed=11, status_every_s=1e9)
eng.set_reliability(0)
setup = {setup}

def run(wo, item, qty, pick):
    ops = routing_for(item)
    for op, _ in ops:
        u = next((v for k, v in pick.items() if op.startswith(k)), OP_UNITS[op][0])
        ok, why = eng.command(u, {{"command": "dispatch", "work_order": wo, "operation": op, "qty": qty, "item": item, "routing": ops}}, wo)
        assert ok, why
    while eng.q and clock.t < 120 * 86400:
        clock.t = max(clock.t, eng.next_event_time())
        eng.run_due()

for i, (item, qty, *rest) in enumerate(setup["batches"]):
    for p in setup.get("inject_at", {{}}).get(str(i), []):
        eng.errors.inject(p)
    if str(i) in setup.get("fix_at", {{}}):
        eng.errors.apply_fix(setup["fix_at"][str(i)])
    run("WO-{{}}".format(i), item, qty, rest[0] if rest else {{}})
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"wo": d["work_order"], "item": d["item"], "op": d["operation"], "char": d["characteristic"], "v": d["value_mm"],
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm"),
                   "result": d["result"]}} for d in ms], ensure_ascii=False))
"""


def _run(setup):
    env = dict(os.environ, WQ_PLANT_FILE=SEW)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    return [m["v"] for m in ms if m["wo"] == wo and m["char"] == char]


def _mean(v):
    return sum(v) / len(v)


def test_plant_check_workshops_and_equipment():
    sys.path[:0] = [FAC]
    from factory import equip, plant
    p = yaml.safe_load(open(SEW, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert "general" not in kinds.values()
    assert len(kinds) >= 140
    assert kinds["ind-1"] == "induction" and kinds["mold-1"] == "molding" and kinds["age-1"] == "furnace" and kinds["hmc-3"] == "mc"
    assert kinds["tap-1"] == "mc" and kinds["wash-1"] == "washer" and kinds["leak-1"] == "leaktest" and kinds["grd-9"] == "grinder"
    assert kinds["asm-a01"] == "assembly" and kinds["adj-1"] == "adjust" and kinds["rin-1"] == "sewrunin" and kinds["eol-4"] == "eoltest"
    # 工艺方案：平缝机壳精镗用 5 台卧加，包缝 2 台；平缝总装 12 个工位；平缝机跑合 15 台
    ops = {o["name"]: o["units"] for o in p["operations"]}
    assert len(next(v for k, v in ops.items() if k.startswith("LS80"))) == 5
    assert len(next(v for k, v in ops.items() if k.startswith("OL80"))) == 2
    assert len([k for k in ops if k.startswith("LA-A") and k[4].isdigit()]) == 12
    assert len(next(v for k, v in ops.items() if k.startswith("LA-RUN"))) == 15
    # 机壳路线：粗加工后第二次时效、精镗在钻攻之后、面漆在终检之后（11-09 Eddie 指正）
    rt = next(r for r in p["routings"] if r["name"].startswith("RT-机壳 平缝"))
    names = [s[0].split(" ")[0] for s in rt["steps"]]
    assert names.index("LS30") < names.index("H40") < names.index("LS50") < names.index("LS70") < names.index("LS80")
    assert names.index("H110") < names.index("H115")


def test_measurements_flow():
    parts = ["CAST-LS", "CAST-OL", "HSG-LS", "HSG-OL", "LS-101", "LS-102", "OL-101", "LS-201", "OL-201", "LS-301", "LS-401", "OL-401"]
    ms = _run({"batches": [[x, 1] for x in parts] + [["WQ-LS", 2], ["WQ-OL", 1]]})
    items = {m["item"] for m in ms}
    assert {"CAST-LS", "CAST-OL", "HSG-LS", "HSG-OL", "LS-101", "LS-102", "OL-101", "LS-201", "OL-201", "LS-301", "LS-401", "OL-401",
            "WQ-LS", "WQ-OL"} <= items
    assert len(_vals(ms, "WO-12", "lsa_gap")) == 2 and len(_vals(ms, "WO-13", "ola_knife")) == 1
    bad = [m for m in ms if m["result"] != "pass"]
    assert len(bad) <= len(ms) * 0.02, bad[:3]                               # 没注入问题：只有散布里偶尔的超差
    on = {m["on"] for m in ms if m["char"] == "hs_pos"}
    assert on and on <= {"hmc-1", "hmc-2", "hmc-3", "hmc-4", "hmc-5"}          # 记下精镗那台卧加


def test_hmc_pin_only_on_hmc3_and_fixed():
    b3 = {"LS30": "hmc-3", "LS80": "hmc-3"}
    b1 = {"LS30": "hmc-1", "LS80": "hmc-1"}
    ms = _run({"batches": [["HSG-LS", 3, b3], ["HSG-LS", 6, b3], ["HSG-LS", 4, b1], ["HSG-LS", 4, b3], ["HSG-LS", 4, b3]],
               "inject_at": {"1": ["hmc_pin"]}, "fix_at": {"3": "rebore", "4": "replace_hmc_pins"}})
    h = {w: _vals(ms, w, "hs_pos") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4")}
    assert max(h["WO-0"]) < 0.026 and _mean(h["WO-1"][-3:]) > 0.030                 # hmc-3 镗的位置度漂到超差
    assert max(h["WO-2"]) < 0.026                                             # 同时 hmc-1 照常
    assert min(h["WO-3"]) > 0.028                                             # 返镗不对症
    assert max(h["WO-4"]) < 0.026                                             # 换定位销后恢复


def test_foundry_and_heat_treat_problems():
    ms = _run({"batches": [["CAST-LS", 4], ["CAST-LS", 8], ["CAST-LS", 4], ["HSG-LS", 3], ["HSG-LS", 5], ["HSG-LS", 3], ["LS-101", 3], ["LS-101", 6],
                           ["LS-101", 3]],
               "inject_at": {"1": ["sand_moist", "inoc_fade"], "4": ["age_tc"], "7": ["ind_coil"]},
               "fix_at": {"2": "control_sand_water", "5": "calibrate_age_tc", "8": "replace_ind_coil"}})
    assert _mean(_vals(ms, "WO-1", "cast_moist")[-4:]) > 3.8 and max(_vals(ms, "WO-0", "cast_moist")) < 3.75
    assert sum(_vals(ms, "WO-1", "cast_pores")) >= 2 and sum(_vals(ms, "WO-0", "cast_pores")) == 0
    assert _mean(_vals(ms, "WO-1", "cast_hb")[-4:]) > 232                    # 孕育衰退：硬度高
    assert max(_vals(ms, "WO-2", "cast_moist")) < 3.75                      # 控好水分后恢复
    assert _mean(_vals(ms, "WO-2", "cast_hb")) > 230                        # 只修了混砂机，孕育问题还在
    assert _mean(_vals(ms, "WO-4", "hs_flat")[-3:]) > _mean(_vals(ms, "WO-3", "hs_flat")) + 0.005 and _mean(_vals(ms, "WO-3", "hs_flat")) < 0.016
    assert _mean(_vals(ms, "WO-4", "hs_coax_up")[-3:]) > _mean(_vals(ms, "WO-3", "hs_coax_up")) + 0.003
    assert _mean(_vals(ms, "WO-5", "hs_flat")) < 0.016                      # 校热电偶后恢复
    assert _mean(_vals(ms, "WO-7", "ls_hrc")[-3:]) < 50 and min(_vals(ms, "WO-6", "ls_hrc")) > 50.5
    assert min(_vals(ms, "WO-8", "ls_hrc")) > 50.5


def test_problems_and_fixes_per_plant():
    from sim import errors
    sw = errors.problems_for("wenquest-sewing")
    assert set(sw) == {"sand_moist", "inoc_fade", "hmc_pin", "age_tc", "ind_coil"}
    assert set(errors.problems_for("wenquest-motor")).isdisjoint(sw)
    fx = errors.fixes_for("wenquest-sewing")
    assert {"control_sand_water", "dry_inoculant", "replace_hmc_pins", "calibrate_age_tc", "replace_ind_coil", "rebore"} <= set(fx)
    assert "replace_mag_fixture" not in fx and "replace_hmc_pins" not in errors.fixes_for("wenquest-motor")


def test_ai_rules_flag_injected_problems():
    """AI 巡检 SW1–SW5：注入问题后的测量记录喂给规则能报出；正常时不报；SW3 指向 hmc-3"""
    from hub.ont.rules import sewing as R
    b3 = {"LS30": "hmc-3", "LS80": "hmc-3"}
    b1 = {"LS30": "hmc-1", "LS80": "hmc-1"}
    ms = _run({"batches": [["CAST-LS", 8], ["HSG-LS", 4, b1], ["HSG-LS", 4, b3], ["LS-101", 6],
                           ["CAST-LS", 8], ["HSG-LS", 6, b1], ["HSG-LS", 8, b3], ["LS-101", 8]],
               "inject_at": {"4": ["sand_moist", "inoc_fade", "age_tc", "hmc_pin", "ind_coil"]}})

    class Ctx:
        mode = "teach"

        def __init__(self, rows):
            self.rows = rows
            self._c = {}

        def get(self, name, fn):
            return self._c.setdefault(name, fn())

        @property
        def db(self):
            rows = self.rows

            class D:
                def messages(self, *a, **k):
                    return rows
            return D()

    def rows(sel):
        return [{"data": {"characteristic": m["char"], "value_mm": m["v"], "part_serial": m["serial"], "assembled_on": m["on"],
                          "upper_tol_mm": m["hi"], "lower_tol_mm": m["lo"]}} for m in reversed(sel)]
    doc = yaml.safe_load(open(os.path.join(DIG, "ontology", "rules", "sewing.yaml"), encoding="utf-8"))["rules"]
    fns = {k: (getattr(R, v["fn"]), v["params"]) for k, v in doc.items() if v.get("fn")}
    assert set(fns) == {"SW1", "SW2", "SW3", "SW4", "SW5"}
    good = Ctx(rows([m for m in ms if m["wo"] in ("WO-0", "WO-1", "WO-2", "WO-3")]))
    assert all(not f(good, p, {}) for f, p in fns.values())
    bad = Ctx(rows(ms))
    hit = {k for k, (f, p) in fns.items() if f(bad, p, {})}
    assert hit == {"SW1", "SW2", "SW3", "SW4", "SW5"}, hit
    assert fns["SW3"][0](Ctx(rows(ms)), fns["SW3"][1], {})[0].subject == ("Machine", "hmc-3")
