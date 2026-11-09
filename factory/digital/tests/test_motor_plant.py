# -*- coding: utf-8 -*-
"""第 131 轮：电机厂（清单 wenquest-motor）——电机出测量值；反电势常数、三相不平衡、THD、齿槽转矩由终检波形算出、波形和测量值对得上；
四种隐藏问题只在对应的设备上出偏差（张力不稳只在 wd-2 绕的定子），对症措施后消失、不对症的不消失；设备类别；问题与措施按厂分；工业园买卖指向。"""
import json
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
MOTOR = os.path.join(FAC, "plants", "wenquest-motor.yaml")
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

def run(wo, item, qty, winder):
    ops = routing_for(item)
    for op, _ in ops:
        u = winder if op.startswith("绕线") else OP_UNITS[op][0]
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
    run("WO-{{}}".format(i), item, qty, rest[0] if rest else "wd-1")
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"wo": d["work_order"], "item": d["item"], "op": d["operation"], "char": d["characteristic"], "v": d["value_mm"],
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm"), "mw": d.get("mw"), "result": d["result"]}} for d in ms],
                 ensure_ascii=False))
"""


def _run(setup, plant=None):
    env = dict(os.environ, WQ_PLANT_FILE=plant or MOTOR)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    return [m["v"] for m in ms if m["wo"] == wo and m["char"] == char]


def test_plant_check_and_equipment():
    sys.path[:0] = [FAC]
    from factory import equip, plant
    p = yaml.safe_load(open(MOTOR, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert kinds["wd-2"] == "winder" and kinds["mz-1"] == "magnetizer" and kinds["dyn-1"] == "dyno" and kinds["vo-1"] == "varnish"
    assert kinds["asm-1"] == "assembly" and kinds["pk-1"] == "pack" and "general" not in kinds.values()
    assert len([u for u in p["units"] if u.get("workstation")]) == 14
    assert "varnish" in equip.STAFFED_EXCEPT


def test_park_links():
    """工业园：机器人厂的四种电机向电机厂买（对方物料号 WQ-SM100/200/400、WQ-AM750），单价不变"""
    m = yaml.safe_load(open(MOTOR, encoding="utf-8"))
    r = yaml.safe_load(open(ROBOT, encoding="utf-8"))
    want = {"MTR-SV-100": ("WQ-SM100", 190), "MTR-SV-200": ("WQ-SM200", 240), "MTR-SV-400": ("WQ-SM400", 320), "MTR-AGV-750": ("WQ-AM750", 380)}
    sell = {x["item"]: x["price"] for x in m["products"]}
    for code, (it, price) in want.items():
        i = next(x for x in r["items"] if x["code"] == code)
        assert r["suppliers"][i["supplier"]]["park"] == "wenquest-motor" and i["park_item"] == it and i["pack"] == 1
        assert i["price"] == price == sell[it]


def test_wave_values_come_from_curve():
    from sim import motorwave
    ms = _run({"batches": [["WQ-SM200", 3], ["WQ-AM750", 2]]})
    ke = [m for m in ms if m["char"] == "mt_ke"]
    assert len(ke) == 5 and all(m["mw"] for m in ke)
    for m in ke:
        g = motorwave.generate(m["mw"])
        for c in ("ke", "unbal", "thd", "cog"):
            v = next(x["v"] for x in ms if x["serial"] == m["serial"] and x["char"] == "mt_" + c)
            assert abs(g[c] - v) < 1e-6                                     # 波形与测量值一致
        assert 95 < m["v"] < 105 and m["on"] == "wd-1"
    assert all(m["result"] == "pass" for m in ms)                          # 正常时全部合格
    assert not _vals(ms, "WO-1", "brk_hold") and len(_vals(ms, "WO-0", "brk_hold")) == 3     # AGV 电机没有抱闸


def test_wind_tension_only_on_wd2_and_fixed():
    ms = _run({"batches": [["WQ-SM400", 3, "wd-1"], ["WQ-SM400", 6, "wd-2"], ["WQ-SM400", 4, "wd-1"], ["WQ-SM400", 3, "wd-2"], ["WQ-SM400", 3, "wd-2"]],
               "inject_at": {"1": ["wind_tension"]}, "fix_at": {"3": "widen_mft", "4": "fix_tensioner"}})
    r = {w: _vals(ms, w, "st_r_unbal") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4")}
    assert r["WO-1"][-1] > 1.5 and max(r["WO-0"]) < 1.0                    # wd-2 绕的不平衡变大
    assert max(r["WO-2"]) < 1.0                                             # 同时间 wd-1 照常
    assert min(r["WO-3"]) > 1.2                                             # 终检放宽不对症
    assert max(r["WO-4"]) < 1.0                                             # 修张力器后恢复
    on = {m["wo"]: m["on"] for m in ms if m["char"] == "st_r_unbal"}
    assert on["WO-1"] == "wd-2" and on["WO-2"] == "wd-1"


def test_magnet_magnetizer_and_varnish_problems():
    ms = _run({"batches": [["WQ-SM200", 3], ["WQ-SM200", 6], ["WQ-SM200", 3], ["WQ-SM200", 3], ["WQ-SM200", 3]],
               "inject_at": {"1": ["mag_fixture", "magnetizer_low", "varnish_low"]},
               "fix_at": {"2": "comp_drive", "3": "rebake", "4": "replace_mag_fixture"}})
    mean = lambda a: sum(a) / len(a)                                       # noqa: E731
    assert mean(_vals(ms, "WO-1", "mt_cog")[-4:]) > 2.5 and max(_vals(ms, "WO-0", "mt_cog")) < 2.0
    assert mean(_vals(ms, "WO-1", "mt_thd")[-4:]) > 5 and max(_vals(ms, "WO-0", "mt_thd")) < 4
    assert mean(_vals(ms, "WO-2", "mt_cog")) > 2.5                         # 驱动器补偿不对症
    assert _vals(ms, "WO-1", "mt_ke")[-1] < 95 and min(_vals(ms, "WO-0", "mt_ke")) > 97
    assert mean(_vals(ms, "WO-1", "mt_i0")[-3:]) > mean(_vals(ms, "WO-0", "mt_i0")) + 0.05
    assert mean(_vals(ms, "WO-1", "st_leak")[-3:]) > 1.0 and max(_vals(ms, "WO-0", "st_leak")) < 0.5
    assert min(_vals(ms, "WO-3", "st_leak")) > 0.7                         # 原炉温再烘不对症
    assert max(_vals(ms, "WO-4", "mt_cog")) < 2.0                          # 换工装后齿槽转矩恢复
    assert max(_vals(ms, "WO-4", "mt_ke")) < 95                            # 充磁机还没修


def test_problems_and_fixes_per_plant():
    from sim import errors
    mt = errors.problems_for("wenquest-motor")
    assert set(mt) == {"mag_fixture", "magnetizer_low", "wind_tension", "varnish_low"}
    assert set(errors.problems_for("wenquest-sensor")).isdisjoint(mt)
    fx = errors.fixes_for("wenquest-motor")
    assert {"replace_mag_fixture", "service_magnetizer", "fix_tensioner", "profile_varnish", "comp_drive"} <= set(fx)
    assert "replace_fixture" not in fx and "fix_tensioner" not in errors.fixes_for("wenquest-sensor")


def test_ai_rules_flag_injected_problems():
    """AI 巡检规则 MT1–MT4：把仿真注入问题后的测量记录喂给规则，能报出对应的问题；正常时不报"""
    from hub.ont.rules import motor as R
    ms = _run({"batches": [["WQ-SM200", 8, "wd-1"], ["WQ-SM200", 8, "wd-2"]],
               "inject_at": {"1": ["mag_fixture", "magnetizer_low", "wind_tension", "varnish_low"]}})

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
    doc = yaml.safe_load(open(os.path.join(DIG, "ontology", "rules", "motor.yaml"), encoding="utf-8"))["rules"]
    fns = {k: (getattr(R, v["fn"]), v["params"]) for k, v in doc.items() if v.get("fn")}
    assert set(fns) == {"MT1", "MT2", "MT3", "MT4"}
    good = Ctx(rows([m for m in ms if m["wo"] == "WO-0"]))
    assert all(not f(good, p, {}) for f, p in fns.values())                 # 正常时不报
    bad = Ctx(rows(ms))
    hit = {k for k, (f, p) in fns.items() if f(bad, p, {})}
    assert hit == {"MT1", "MT2", "MT3", "MT4"}, hit
    r = fns["MT2"][0](Ctx(rows(ms)), fns["MT2"][1], {})[0]
    assert r.subject == ("Machine", "wd-2")


def test_sensor_and_pcb_not_touched():
    """电机终检波形只算电机厂的四种电机：别的厂测量照旧"""
    ms = _run({"batches": [["WQ-ENC17", 2, "cb-1"]]}, plant=os.path.join(FAC, "plants", "wenquest-sensor.yaml"))
    assert ms and not any(m["mw"] for m in ms)
