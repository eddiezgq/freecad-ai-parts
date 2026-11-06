# -*- coding: utf-8 -*-
"""第 103 轮（电子 E9）：芯片封测厂（清单 wenquest-chip）——CP、FT 出测量值；CP 良率由晶圆图算出、图和良率对得上；
四种隐藏问题只在对应的设备上出偏差（探针卡磨损只坏一个测试位、劈刀磨损只在 wb-2 键合的批次），对症措施后消失；
设备类别；问题与措施按厂分。仿真在子进程里按芯片厂清单跑（工厂数据在导入时读清单）。"""
import json
import os
import subprocess
import sys

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
CHIP = os.path.join(FAC, "plants", "wenquest-chip.yaml")

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
        u = bonder if op.startswith("引线键合") else OP_UNITS[op][0]
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
    run("WO-{{}}".format(i), item, qty, rest[0] if rest else "wb-1")
ms = [m["data"] for t, m in out if m["type"] == "quality.measurement"]
print(json.dumps([{{"wo": d["work_order"], "item": d["item"], "op": d["operation"], "char": d["characteristic"], "v": d["value_mm"],
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "wafer": d.get("wafer"), "result": d["result"]}} for d in ms],
                 ensure_ascii=False))
"""


def _run(setup):
    env = dict(os.environ, WQ_PLANT_FILE=CHIP)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=600)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    return [m["v"] for m in ms if m["wo"] == wo and m["char"] == char]


def test_plant_check_and_equipment():
    sys.path[:0] = [FAC]
    import yaml
    from factory import equip, plant
    p = yaml.safe_load(open(CHIP, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert kinds["prb-1"] == "prober" and kinds["wb-2"] == "wirebond" and kinds["plt-1"] == "plating" and kinds["pl-1"] == "plasma"
    assert kinds["ft-1"] == "handler" and kinds["bi-1"] == "burnin" and "general" not in kinds.values()
    assert len([u for u in p["units"] if u.get("workstation")]) == 16


def test_cp_yield_comes_from_wafer_map():
    from sim import wafermap
    ms = _run({"batches": [["WAF-ENCIF-CP", 3]]})
    cp = [m for m in ms if m["char"] == "cp_yield"]
    assert len(cp) == 3 and all(m["wafer"] for m in cp)
    for m in cp:
        g = wafermap.render(m["wafer"])
        assert abs(g["yield_pct"] - m["v"]) < 1e-6 and g["total"] > 30000          # 图与良率一致
        assert 85 <= m["v"] <= 100
    rc = _vals(ms, "WO-0", "cp_contact")
    assert all(abs(x - 1.0) < 0.3 for x in rc)
    for c in ("cp_iddq", "cp_vtp", "cp_vtm"):
        assert len(_vals(ms, "WO-0", c)) == 3


def test_probe_wear_hits_one_site_and_is_fixed():
    ms = _run({"batches": [["WAF-ENCIF-CP", 3], ["WAF-ENCIF-CP", 8], ["WAF-ENCIF-CP", 3]],
               "inject_at": {"1": ["probe_wear"]}, "fix_at": {"2": "clean_probe"}})
    w1 = [m["wafer"] for m in ms if m["wo"] == "WO-1" and m["char"] == "cp_yield"]
    last = w1[-1]["site_fail_pct"]
    others = sorted(last[:5] + last[6:])
    assert last[5] > 3 * others[len(others) // 2] and last[5] > 15      # 第 6 个测试位失效集中
    y0, y1, y2 = (_vals(ms, w, "cp_yield") for w in ("WO-0", "WO-1", "WO-2"))
    assert y1[-1] < min(y0) - 4 and min(y2) > y1[-1] + 4                 # 良率掉下去，清洁探针后回来
    assert _vals(ms, "WO-1", "cp_contact")[-1] > max(_vals(ms, "WO-0", "cp_contact")) + 0.2


def test_capillary_wear_only_on_wb2_and_other_problems():
    ms = _run({"batches": [["WQ-ENCIF", 3, "wb-1"], ["WQ-ENCIF", 5, "wb-2"], ["WQ-ENCIF", 5, "wb-1"], ["WQ-ENCIF", 3, "wb-2"]],
               "inject_at": {"1": ["capillary_wear", "blade_wear", "emc_moisture"]},
               "fix_at": {"3": "replace_capillary"}})
    on = {m["wo"]: m["on"] for m in ms if m["char"] == "bond_pull"}
    assert on["WO-1"] == "wb-2" and on["WO-2"] == "wb-1"                 # 记下了哪台键合机（分层用）
    assert min(_vals(ms, "WO-1", "bond_pull")) < 3.5                    # wb-2 的劈刀磨损：拉力掉下去
    assert min(_vals(ms, "WO-2", "bond_pull")) > 5.0                    # 同时间 wb-1 的批次照常
    assert min(_vals(ms, "WO-3", "bond_pull")) > 5.0                    # 换劈刀后恢复
    assert max(_vals(ms, "WO-2", "chipping")) > 20 and max(_vals(ms, "WO-2", "mold_void")) > 3.0
    assert max(_vals(ms, "WO-0", "chipping")) < 17 and max(_vals(ms, "WO-0", "mold_void")) < 2.0
    for c in ("ft_yield", "ft_idd", "ft_hyst", "ball_shear"):
        assert len(_vals(ms, "WO-0", c)) == 3


def test_problems_and_fixes_per_plant():
    from sim import errors
    ch = errors.problems_for("wenquest-chip")
    assert set(ch) == {"probe_wear", "blade_wear", "capillary_wear", "emc_moisture"}
    assert set(errors.problems_for("wenquest-pcb")).isdisjoint(ch)
    fx = errors.fixes_for("wenquest-chip")
    assert {"clean_probe", "replace_blade", "replace_capillary", "emc_handling", "retest_cp"} <= set(fx)
    assert "wipe_stencil" not in fx and "clean_probe" not in errors.fixes_for("wenquest-pcb")
