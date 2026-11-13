# -*- coding: utf-8 -*-
"""第 166 轮：计算机厂（清单 wenquest-computer）——主板、内存条、机箱、笔记本壳、整机、整机柜都出测量值；CPU 满载温度、老化平均功耗由老化曲线算出、
曲线和测量值对得上；四种隐藏问题只在对应的设备上出偏差（点胶量少只在 dp-2 点的整机、测试座只在第 6 座），对症措施后消失、不对症的不消失；
设备类别；问题与措施按厂分；工业园买卖指向；AI 规则 CP1–CP4。"""
import json
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
COMP = os.path.join(FAC, "plants", "wenquest-computer.yaml")
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")

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
    while eng.q and clock.t < 200 * 86400:
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
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm"), "bi": d.get("bi"),
                   "result": d["result"]}} for d in ms], ensure_ascii=False))
"""


def _run(setup, plant=None):
    env = dict(os.environ, WQ_PLANT_FILE=plant or COMP)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    """按序列号排（喷粉线、老化房整批进出，测量记录的先后不一定是加工顺序）"""
    return [m["v"] for m in sorted(ms, key=lambda m: m["serial"]) if m["wo"] == wo and m["char"] == char]


def mean(a):
    return sum(a) / len(a)


def test_plant_check_and_equipment():
    sys.path[:0] = [FAC]
    from factory import equip, plant
    p = yaml.safe_load(open(COMP, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert kinds["xr-1"] == "xray" and kinds["mt-1"] == "memtest" and kinds["pb-1"] == "pressbrake" and kinds["dp-2"] == "dispense"
    assert kinds["rk-1"] == "racktest" and kinds["an-1"] == "anodize" and kinds["pc-1"] == "powdercoat" and kinds["bi-1"] == "burnin"
    assert "general" not in kinds.values() and len(kinds) == 29
    assert {"memtest", "racktest", "burnin"} <= set(equip.STAFFED_EXCEPT)


def test_park_links():
    """工业园：机器人厂控制柜里的工控机向计算机厂买（对方物料号 WQ-IPC），单价与计算机厂售价一致"""
    c = yaml.safe_load(open(COMP, encoding="utf-8"))
    r = yaml.safe_load(open(ROBOT, encoding="utf-8"))
    sell = {x["item"]: x["price"] for x in c["products"]}
    i = next(x for x in r["items"] if x["code"] == "IPC")
    assert r["suppliers"][i["supplier"]]["park"] == "wenquest-computer" and i["park_item"] == "WQ-IPC" and i["pack"] == 1
    assert i["price"] == sell["WQ-IPC"]
    cr5 = next(b for b in r["boms"] if b["item"] == "WQ-CR5")
    assert ["IPC", 1] in cr5["components"]


def test_all_items_measure_and_curve_matches():
    from sim import burnin
    ms = _run({"batches": [["MB-SV", 2], ["DIMM-32", 3], ["CHS-PC", 2], ["NBC-14", 2], ["WQ-PC1", 2], ["WQ-NB14", 2], ["WQ-SV2U", 2],
                           ["WQ-IPC", 1], ["WQ-RACK42", 1]]})
    items = {m["item"] for m in ms}
    assert items == {"MB-SV", "DIMM-32", "CHS-PC", "NBC-14", "WQ-PC1", "WQ-NB14", "WQ-SV2U", "WQ-IPC", "WQ-RACK42"}
    tm = [m for m in ms if m["char"] == "pc_tmax"]
    assert len(tm) == 7 and all(m["bi"] for m in tm)
    for m in tm:
        g = burnin.generate(m["bi"])
        assert abs(g["tmax"] - m["v"]) < 1e-6
        pav = next(x["v"] for x in ms if x["serial"] == m["serial"] and x["char"] == "pc_pavg")
        assert abs(g["pavg"] - pav) < 1e-6
    assert all(m["result"] == "pass" for m in ms), [m for m in ms if m["result"] != "pass"]       # 正常时全部合格
    sock = {m["on"] for m in ms if m["char"] == "mem_margin"}
    assert sock == {"测试座 1", "测试座 2", "测试座 3"}


def test_tim_only_on_dp2_and_fixed():
    ms = _run({"batches": [["WQ-PC1", 3, {"涂导热硅脂": "dp-1"}], ["WQ-PC1", 5, {"涂导热硅脂": "dp-2"}], ["WQ-PC1", 3, {"涂导热硅脂": "dp-1"}],
                           ["WQ-PC1", 3, {"涂导热硅脂": "dp-2"}], ["WQ-PC1", 3, {"涂导热硅脂": "dp-2"}], ["WQ-PC1", 3, {"涂导热硅脂": "dp-2"}]],
               "inject_at": {"1": ["tim_dp2"]}, "fix_at": {"3": "longer_burnin", "4": "fan_speed_up", "5": "clean_dp_needle"}})
    t = {w: _vals(ms, w, "pc_tmax") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4", "WO-5")}
    assert t["WO-1"][-1] > 88 and max(t["WO-0"]) < 81                    # dp-2 点的满载温度高
    assert max(t["WO-2"]) < 81                                            # 同时间 dp-1 照常
    assert min(t["WO-3"]) > 86 and min(t["WO-4"]) > 86                    # 老化加长、风扇调高都不对症
    assert max(t["WO-5"]) < 81                                            # 清洗针头后恢复
    on = {m["wo"]: m["on"] for m in ms if m["char"] == "pc_tmax"}
    assert on["WO-1"] == "dp-2" and on["WO-2"] == "dp-1"


def test_reflow_backgauge_socket_problems():
    ms = _run({"batches": [["MB-PC", 3], ["DIMM-32", 8], ["CHS-SV", 3], ["MB-PC", 5], ["DIMM-32", 8], ["CHS-SV", 4], ["MB-PC", 3], ["DIMM-32", 8],
                           ["CHS-SV", 3]],
               "inject_at": {"3": ["reflow_zone", "backgauge", "mt_socket"]},
               "fix_at": {"6": "repair_reflow_zone", "8": "recal_backgauge"}})
    assert max(_vals(ms, "WO-0", "mb_void")) < 16 and mean(_vals(ms, "WO-3", "mb_void")[-3:]) > 16
    assert max(_vals(ms, "WO-6", "mb_void")) < 16                          # 修温区后恢复
    assert max(abs(v) for v in _vals(ms, "WO-2", "chs_hole")) < 0.15 and max(_vals(ms, "WO-5", "chs_hole")) > 0.2
    assert max(abs(v) for v in _vals(ms, "WO-8", "chs_hole")) < 0.15       # 校后挡料后恢复
    m4 = [(m["on"], m["v"]) for m in ms if m["wo"] == "WO-7" and m["char"] == "mem_margin"]
    bad = [v for on, v in m4 if on == "测试座 6"]
    good = [v for on, v in m4 if on != "测试座 6"]
    assert bad and max(bad) < 30 and min(good) > 38                        # 修了回流炉后，只有第 6 座读数低（测试座还没换）
    assert all(on.startswith("测试座 ") for on, _ in m4)


def test_problems_and_fixes_per_plant():
    from sim import errors
    pc = errors.problems_for("wenquest-computer")
    assert set(pc) == {"tim_dp2", "reflow_zone", "backgauge", "mt_socket"}
    assert set(errors.problems_for("wenquest-motor")).isdisjoint(pc)
    fx = errors.fixes_for("wenquest-computer")
    assert {"clean_dp_needle", "repair_reflow_zone", "recal_backgauge", "replace_mt_socket", "longer_burnin", "fan_speed_up"} <= set(fx)
    assert "fix_tensioner" not in fx and "clean_dp_needle" not in errors.fixes_for("wenquest-motor")


def test_ai_rules_flag_injected_problems():
    """AI 巡检规则 CP1–CP4：把注入问题后的测量记录喂给规则，能报出对应的问题；正常时不报"""
    from hub.ont.rules import computer as R
    ms = _run({"batches": [["WQ-PC1", 4, {"涂导热硅脂": "dp-1"}], ["MB-PC", 3], ["DIMM-32", 8], ["CHS-PC", 3],
                           ["WQ-PC1", 6, {"涂导热硅脂": "dp-2"}], ["MB-PC", 6], ["DIMM-32", 16], ["CHS-PC", 6]],
               "inject_at": {"4": ["tim_dp2"], "5": ["reflow_zone", "backgauge"], "6": ["mt_socket"]},
               "fix_at": {"6": "repair_reflow_zone"}})

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
                          "upper_tol_mm": m["hi"], "lower_tol_mm": m["lo"], "item": m["item"]}} for m in reversed(sel)]
    doc = yaml.safe_load(open(os.path.join(DIG, "ontology", "rules", "computer.yaml"), encoding="utf-8"))["rules"]
    fns = {k: (getattr(R, v["fn"]), v["params"]) for k, v in doc.items() if v.get("fn")}
    assert set(fns) == {"CP1", "CP2", "CP3", "CP4"}
    good = Ctx(rows([m for m in ms if m["wo"] in ("WO-0", "WO-1", "WO-2", "WO-3")]))
    assert all(not f(good, p, {}) for f, p in fns.values())                 # 正常时不报
    hit = {k for k, (f, p) in fns.items() if f(Ctx(rows(ms)), p, {})}
    assert hit == {"CP1", "CP2", "CP3", "CP4"}, hit
    assert fns["CP1"][0](Ctx(rows(ms)), fns["CP1"][1], {})[0].subject == ("Machine", "dp-2")
    assert fns["CP4"][0](Ctx(rows(ms)), fns["CP4"][1], {})[0].subject == ("Machine", "mt-1")


def test_other_plants_not_touched():
    """老化曲线只算计算机厂的整机：别的厂的老化、测量照旧"""
    ms = _run({"batches": [["DRV-JOINT-B", 2]]}, plant=os.path.join(FAC, "plants", "wenquest-pcb.yaml"))
    assert ms and not any(m["bi"] for m in ms) and not any(m["char"].startswith("pc_") for m in ms)
