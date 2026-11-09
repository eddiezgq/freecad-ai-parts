# -*- coding: utf-8 -*-
"""第 125 轮（电子 E12）：传感器厂（清单 wenquest-sensor）——编码器、扭矩传感器出测量值；编码器的精度等由整圈误差曲线算出、曲线和测量值对得上；
四种隐藏问题只在对应的设备上出偏差（对心夹具磨损只在 cb-2 粘的编码器），对症措施后消失、不对症的不消失；设备类别；问题与措施按厂分；工业园买卖指向。"""
import json
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
SENSOR = os.path.join(FAC, "plants", "wenquest-sensor.yaml")
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

def run(wo, item, qty, bonder):
    ops = routing_for(item)
    for op, _ in ops:
        u = bonder if op.startswith("码盘粘接") else OP_UNITS[op][0]
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
    run("WO-{{}}".format(i), item, qty, rest[0] if rest else "cb-1")
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"wo": d["work_order"], "item": d["item"], "op": d["operation"], "char": d["characteristic"], "v": d["value_mm"],
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm"), "enc": d.get("enc"), "result": d["result"]}} for d in ms],
                 ensure_ascii=False))
"""


def _run(setup, plant=None):
    env = dict(os.environ, WQ_PLANT_FILE=plant or SENSOR)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    return [m["v"] for m in ms if m["wo"] == wo and m["char"] == char]


def test_plant_check_and_equipment():
    sys.path[:0] = [FAC]
    from factory import equip, plant
    p = yaml.safe_load(open(SENSOR, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert kinds["cb-2"] == "centering" and kinds["hm-1"] == "headmount" and kinds["ecal-1"] == "enccal" and kinds["dwt-1"] == "deadweight"
    assert kinds["cur-1"] == "cure" and kinds["pk-1"] == "pack" and "general" not in kinds.values()
    assert len([u for u in p["units"] if u.get("workstation")]) == 15


def test_park_links():
    """工业园：传感器厂的读头板向电路板厂买；机器人厂的编码器向传感器厂买（对方物料号 WQ-ENC17）"""
    s = yaml.safe_load(open(SENSOR, encoding="utf-8"))
    r = yaml.safe_load(open(ROBOT, encoding="utf-8"))
    rd = next(i for i in s["items"] if i["code"] == "ENC-RD")
    assert s["suppliers"][rd["supplier"]]["park"] == "wenquest-pcb"
    ea = next(i for i in r["items"] if i["code"] == "ENC-ABS")
    assert r["suppliers"][ea["supplier"]]["park"] == "wenquest-sensor" and ea["park_item"] == "WQ-ENC17" and ea["pack"] == 1
    assert {"WQ-ENC17", "WQ-TS"} == {x["item"] for x in s["products"]}


def test_encoder_values_come_from_curve():
    from sim import enccurve
    ms = _run({"batches": [["WQ-ENC17", 4], ["WQ-TS", 3]]})
    acc = [m for m in ms if m["char"] == "enc_acc"]
    assert len(acc) == 4 and all(m["enc"] for m in acc)
    for m in acc:
        g = enccurve.generate(m["enc"])
        assert abs(g["acc"] - m["v"]) < 1e-6
        for c in ("h1", "interp", "amp", "amp_min"):
            v = next(x["v"] for x in ms if x["serial"] == m["serial"] and x["char"] == "enc_" + c)
            assert abs(g[c] - v) < 1e-6                                     # 曲线与测量值一致
        assert m["v"] < 100 and m["enc"]["station"] == "cb-1"
    for c in ("ts_nonlin", "ts_hyst", "ts_zero", "ts_creep", "ts_tczero"):
        assert len(_vals(ms, "WO-1", c)) == 3


def test_fixture_wear_only_on_cb2_and_fixed():
    ms = _run({"batches": [["WQ-ENC17", 3, "cb-1"], ["WQ-ENC17", 6, "cb-2"], ["WQ-ENC17", 4, "cb-1"], ["WQ-ENC17", 3, "cb-2"], ["WQ-ENC17", 3, "cb-2"]],
               "inject_at": {"1": ["fixture_wear"]}, "fix_at": {"3": "redo_comp", "4": "replace_fixture"}})
    h = {w: _vals(ms, w, "enc_h1") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4")}
    assert h["WO-1"][-1] > 35 and max(h["WO-0"]) < 30                     # cb-2 粘的偏心变大
    assert max(h["WO-2"]) < 30                                              # 同时间 cb-1 照常
    assert min(h["WO-3"]) > 35                                              # 重做补偿表不对症
    assert max(h["WO-4"]) < 30                                              # 换夹具后恢复
    on = {m["wo"]: m["enc"]["station"] for m in ms if m["char"] == "enc_acc"}
    assert on["WO-1"] == "cb-2" and on["WO-2"] == "cb-1"


def test_gap_dirt_and_cure_problems():
    ms = _run({"batches": [["WQ-ENC17", 3], ["WQ-ENC17", 6], ["WQ-TS", 3], ["WQ-TS", 6], ["WQ-ENC17", 3], ["WQ-TS", 3]],
               "inject_at": {"1": ["gap_gauge", "ffu_clog"], "3": ["cure_low"]},
               "fix_at": {"4": "replace_gap_gauge", "5": "profile_cure"}})
    assert _vals(ms, "WO-1", "enc_amp")[-1] < 80 and min(_vals(ms, "WO-0", "enc_amp")) > 88
    assert _vals(ms, "WO-1", "enc_interp")[-1] > max(_vals(ms, "WO-0", "enc_interp"))
    assert min(_vals(ms, "WO-1", "enc_amp_min")) < 70                      # 污点：幅值掉坑
    assert min(_vals(ms, "WO-4", "enc_amp")) > 85                          # 换塞规后幅值回来
    assert _vals(ms, "WO-3", "ts_creep")[-1] > 0.1 and max(_vals(ms, "WO-2", "ts_creep")) < 0.07
    assert max(_vals(ms, "WO-5", "ts_creep")) < 0.07                       # 校炉温后恢复


def test_problems_and_fixes_per_plant():
    from sim import errors
    sn = errors.problems_for("wenquest-sensor")
    assert set(sn) == {"fixture_wear", "gap_gauge", "ffu_clog", "cure_low"}
    assert set(errors.problems_for("wenquest-chip")).isdisjoint(sn)
    fx = errors.fixes_for("wenquest-sensor")
    assert {"replace_fixture", "replace_gap_gauge", "replace_ffu", "profile_cure", "redo_comp"} <= set(fx)
    assert "clean_probe" not in fx and "replace_fixture" not in errors.fixes_for("wenquest-chip")


def test_ai_rules_flag_injected_problems():
    """AI 巡检规则 SN1–SN5：把仿真注入问题后的测量记录喂给规则，能报出对应的问题；正常时不报"""
    from hub.ont.rules import sensor as R
    ms = _run({"batches": [["WQ-ENC17", 8, "cb-1"], ["WQ-TS", 5], ["WQ-ENC17", 8, "cb-2"], ["WQ-TS", 5]],
               "inject_at": {"2": ["fixture_wear", "gap_gauge", "ffu_clog"], "3": ["cure_low"]}})

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
    doc = yaml.safe_load(open(os.path.join(DIG, "ontology", "rules", "sensor.yaml"), encoding="utf-8"))["rules"]
    fns = {k: (getattr(R, v["fn"]), v["params"]) for k, v in doc.items() if v.get("fn")}
    assert set(fns) == {"SN1", "SN2", "SN3", "SN4", "SN5"}
    good = Ctx(rows([m for m in ms if m["wo"] in ("WO-0", "WO-1")]))
    assert all(not f(good, p, {}) for f, p in fns.values())                 # 正常时不报
    bad = Ctx(rows(ms))
    hit = {k for k, (f, p) in fns.items() if f(bad, p, {})}
    assert hit == {"SN1", "SN2", "SN3", "SN4", "SN5"}, hit
    h1 = fns["SN2"][0](Ctx(rows(ms)), fns["SN2"][1], {})[0]
    assert h1.subject == ("Machine", "cb-2")


def test_pcb_read_head_board_not_touched():
    """电路板厂读头板 ENC-RD 的功能测试也有 enc_amp（Vpp）、enc_interp：不能套编码器曲线（11-09 演练里电路板厂 ENC-RD 卡在功能测试，就是这个）"""
    ms = _run({"batches": [["ENC-RD", 3]]}, plant=os.path.join(FAC, "plants", "wenquest-pcb.yaml"))
    amp = [m["v"] for m in ms if m["char"] == "enc_amp"]
    assert len(amp) == 3 and all(0.8 < v < 1.2 for v in amp)
    assert not any(m["enc"] for m in ms)
