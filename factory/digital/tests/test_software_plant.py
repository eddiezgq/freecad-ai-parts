# -*- coding: utf-8 -*-
"""第 167 轮：软件公司（清单 wenquest-software）——版本在发布门禁、订阅在服务验收出测量值；测试通过率、中断延迟、内存增长速率由构建流水线模型算出，
服务延迟、错误率、可用性由 24 小时服务曲线算出，模型和测量值对得上；五种隐藏问题只在对应的设备上出偏差（时钟漂移只在 bld-3、缓存配置只在 hil-2、
吵闹的邻居只在 cl-a2、错误配置在 A 区两台），对症措施后消失、不对症的不消失；设备类别；问题与措施按厂分；工业园买卖指向；AI 规则 SW1–SW5。"""
import json
import os
import subprocess
import sys

import yaml

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
SOFT = os.path.join(FAC, "plants", "wenquest-software.yaml")
PLANTS = os.path.join(FAC, "plants")

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
                   "serial": d["part_serial"], "on": d.get("assembled_on"), "hi": d.get("upper_tol_mm"), "lo": d.get("lower_tol_mm"), "sw": d.get("sw"), "svc": d.get("svc"),
                   "result": d["result"]}} for d in ms], ensure_ascii=False))
"""


def _run(setup, plant=None):
    env = dict(os.environ, WQ_PLANT_FILE=plant or SOFT)
    r = subprocess.run([sys.executable, "-c", RUN.format(dig=DIG, fac=FAC, setup=repr(setup))], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout)


def _vals(ms, wo, char):
    return [m["v"] for m in sorted(ms, key=lambda m: m["serial"]) if m["wo"] == wo and m["char"] == char]


def mean(a):
    return sum(a) / len(a)


def test_plant_check_and_equipment():
    sys.path[:0] = [FAC]
    from factory import equip, plant
    p = yaml.safe_load(open(SOFT, encoding="utf-8"))
    assert not plant.validate(p)
    kinds = {u["id"]: equip.kind_of(u["id"]) for u in p["units"] if u.get("workstation")}
    assert kinds["bld-3"] == "buildsrv" and kinds["hil-2"] == "hilbench" and kinds["sk-1"] == "soak" and kinds["cl-a2"] == "cloudhost"
    assert kinds["dev-1"] == "devdesk" and kinds["rel-1"] == "release" and kinds["lic-1"] == "licsrv" and kinds["mon-1"] == "monitor"
    assert "general" not in kinds.values() and len(kinds) == 21
    assert {"buildsrv", "cloudhost", "hilbench"} <= set(equip.STAFFED_EXCEPT) and "devdesk" not in equip.STAFFED_EXCEPT


def test_park_links():
    """工业园：计算机厂买 OS 授权、机器人厂买机器人软件授权、电路板厂关节驱动板买实时 OS 授权；软件公司向计算机厂买整机柜；单价与卖方售价一致"""
    s = yaml.safe_load(open(SOFT, encoding="utf-8"))
    sell = {x["item"]: x["price"] for x in s["products"]}
    for plant, code, parent in (("wenquest-computer", "LIC-OS", "WQ-PC1"), ("wenquest-robot", "LIC-ROBOT", "WQ-CR5"),
                                ("wenquest-pcb", "LIC-RTOS", "DRV-JOINT-B")):
        p = yaml.safe_load(open(os.path.join(PLANTS, plant + ".yaml"), encoding="utf-8"))
        i = next(x for x in p["items"] if x["code"] == code)
        assert p["suppliers"][i["supplier"]]["park"] == "wenquest-software" and i["park_item"] == code and i["pack"] == 1
        assert i["price"] == sell[code]
        b = next(b for b in p["boms"] if b["item"] == parent)
        assert [code, 1] in b["components"]
    c = yaml.safe_load(open(os.path.join(PLANTS, "wenquest-computer.yaml"), encoding="utf-8"))
    rack = next(x for x in s["items"] if x["code"] == "RACK-CLOUD")
    assert s["suppliers"][rack["supplier"]]["park"] == "wenquest-computer" and rack["park_item"] == "WQ-RACK42"
    assert rack["price"] == next(x["price"] for x in c["products"] if x["item"] == "WQ-RACK42")


def test_all_items_measure_and_models_match():
    from sim import softsim
    ms = _run({"batches": [["REL-RTOS", 2], ["REL-ROBOT", 1], ["REL-OS", 2], ["REL-CLOUD", 1], ["REL-MES", 1], ["SUB-CLOUD", 3], ["SUB-MES", 2],
                           ["LIC-OS", 20], ["LIC-RTOS", 10]]})
    items = {m["item"] for m in ms}
    assert items == {"REL-RTOS", "REL-ROBOT", "REL-OS", "REL-CLOUD", "REL-MES", "SUB-CLOUD", "SUB-MES"}      # 授权签发不测量
    for m in ms:
        if m["char"] in ("sw_pass", "rtos_irq", "os_leak"):
            g = softsim.build(m["sw"])
            assert abs(g[{"sw_pass": "pass", "rtos_irq": "irq_max", "os_leak": "leak"}[m["char"]]] - m["v"]) < 1e-6
            assert m["sw"]["runner"] == m["on"] and m["on"].startswith("bld-")
        if m["char"] in ("cl_p99", "cl_err"):
            g = softsim.service(m["svc"])
            assert abs(g[{"cl_p99": "p99", "cl_err": "err"}[m["char"]]] - m["v"]) < 1e-6
            assert m["on"].startswith("cl-")
    assert {m["sw"]["bench"] for m in ms if m["char"] == "rtos_irq"} <= {"hil-1", "hil-2", "hil-3"}
    assert all(m["result"] == "pass" for m in ms), [m for m in ms if m["result"] != "pass"]       # 正常时全部合格


def test_clock_only_on_bld3_and_fixed():
    b3, b1 = {"编译与单元测试": "bld-3"}, {"编译与单元测试": "bld-1"}
    ms = _run({"batches": [["REL-RTOS", 3, b1], ["REL-RTOS", 4, b3], ["REL-RTOS", 3, b1], ["REL-RTOS", 3, b3], ["REL-RTOS", 3, b3]],
               "inject_at": {"1": ["bld_clock"]}, "fix_at": {"3": "rerun_tests", "4": "sync_ntp_bld3"}})
    v = {w: _vals(ms, w, "sw_pass") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4")}
    assert min(v["WO-0"]) > 99.8 and mean(v["WO-1"]) < 99.4                # bld-3 跑的偶发失败多
    assert min(v["WO-2"]) > 99.8                                            # 同时间 bld-1 照常
    assert mean(v["WO-3"]) < 99.4                                           # 重跑不对症
    assert min(v["WO-4"]) > 99.8                                            # 校时钟后恢复


def test_hil_cache_only_on_hil2():
    h2, h1 = {"硬件在环测试": "hil-2"}, {"硬件在环测试": "hil-1"}
    ms = _run({"batches": [["REL-RTOS", 3, h2], ["REL-RTOS", 3, h2], ["REL-RTOS", 3, h1], ["REL-RTOS", 3, h2]],
               "inject_at": {"1": ["hil_cache"]}, "fix_at": {"3": "fix_hil_cache"}})
    assert max(_vals(ms, "WO-0", "rtos_irq")) < 7.6 and min(_vals(ms, "WO-1", "rtos_irq")) > 7.6
    assert max(_vals(ms, "WO-2", "rtos_irq")) < 7.6 and max(_vals(ms, "WO-3", "rtos_irq")) < 7.6
    assert {m["sw"]["bench"] for m in ms if m["wo"] == "WO-1" and m["char"] == "rtos_irq"} == {"hil-2"}


def test_leak_after_commit_and_reverted():
    ms = _run({"batches": [["REL-OS", 2], ["REL-OS", 3], ["REL-CLOUD", 2], ["REL-OS", 2], ["REL-OS", 2]],
               "inject_at": {"1": ["mem_leak"]}, "fix_at": {"3": "add_capacity", "4": "revert_leak"}})
    assert max(_vals(ms, "WO-0", "os_leak")) < 1.2
    assert min(_vals(ms, "WO-1", "os_leak")) > 5 and min(_vals(ms, "WO-2", "os_leak")) > 5     # 所有过长稳压测的版本都涨
    assert min(_vals(ms, "WO-3", "os_leak")) > 5                            # 加机器不对症
    assert max(_vals(ms, "WO-4", "os_leak")) < 1.2                          # 回滚那次提交后恢复


def test_noisy_neighbor_and_bad_config():
    a2, a1, b1 = ({"资源开通": u} for u in ("cl-a2", "cl-a1", "cl-b1"))
    ms = _run({"batches": [["SUB-CLOUD", 3, a2], ["SUB-CLOUD", 3, a2], ["SUB-CLOUD", 3, a1], ["SUB-CLOUD", 3, b1], ["SUB-CLOUD", 3, a2],
                           ["SUB-CLOUD", 3, a1]],
               "inject_at": {"1": ["noisy_nb", "bad_config"]}, "fix_at": {"4": "isolate_tenant", "5": "rollback_config"}})
    p = {w: _vals(ms, w, "cl_p99") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4")}
    e = {w: _vals(ms, w, "cl_err") for w in ("WO-0", "WO-1", "WO-2", "WO-3", "WO-4", "WO-5")}
    assert max(p["WO-0"]) < 25 and min(p["WO-1"]) > 50                     # 只有 cl-a2 慢
    assert max(p["WO-2"]) < 25 and max(p["WO-3"]) < 25
    assert min(e["WO-1"]) > 0.1 and min(e["WO-2"]) > 0.1 and max(e["WO-3"]) < 0.05     # A 区两台都出错，B 区正常
    assert max(p["WO-4"]) < 25 and min(e["WO-4"]) > 0.1                     # 迁走租户：延迟好了，错误配置还在
    assert max(e["WO-5"]) < 0.05                                            # 回滚配置后恢复


def test_problems_and_fixes_per_plant():
    from sim import errors
    sw = errors.problems_for("wenquest-software")
    assert set(sw) == {"bld_clock", "mem_leak", "hil_cache", "noisy_nb", "bad_config"}
    assert set(errors.problems_for("wenquest-computer")).isdisjoint(sw)
    fx = errors.fixes_for("wenquest-software")
    assert {"sync_ntp_bld3", "revert_leak", "fix_hil_cache", "isolate_tenant", "rollback_config", "rerun_tests", "add_capacity", "widen_gate"} <= set(fx)
    assert "clean_dp_needle" not in fx and "sync_ntp_bld3" not in errors.fixes_for("wenquest-computer")


def test_ai_rules_flag_injected_problems():
    """AI 巡检规则 SW1–SW5：把注入问题后的测量记录喂给规则，能报出对应的问题；正常时不报"""
    from hub.ont.rules import software as R
    runs = {"编译与单元测试": None}
    batches, wo = [], 0
    for i in range(4):          # 正常：四台构建服务器、三台测试台、四台宿主机轮着用
        batches += [["REL-RTOS", 2, {"编译与单元测试": "bld-{}".format(i + 1), "硬件在环测试": "hil-{}".format(i % 3 + 1)}],
                    ["REL-OS", 1, {"编译与单元测试": "bld-{}".format(i + 1)}],
                    ["SUB-CLOUD", 2, {"资源开通": ("cl-a1", "cl-a2", "cl-b1", "cl-b2")[i]}]]
    n_good = len(batches)
    for i in range(4):
        batches += [["REL-RTOS", 2, {"编译与单元测试": "bld-{}".format(i + 1), "硬件在环测试": "hil-{}".format(i % 3 + 1)}],
                    ["REL-OS", 1, {"编译与单元测试": "bld-{}".format(i + 1)}],
                    ["SUB-CLOUD", 3, {"资源开通": ("cl-a1", "cl-a2", "cl-b1", "cl-b2")[i]}]]
    ms = _run({"batches": batches, "inject_at": {str(n_good): ["bld_clock", "mem_leak", "hil_cache", "noisy_nb", "bad_config"]}})
    del runs, wo

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
        return [{"data": {"characteristic": m["char"], "value_mm": m["v"], "part_serial": m["serial"], "assembled_on": m["on"], "sw": m["sw"],
                          "upper_tol_mm": m["hi"], "lower_tol_mm": m["lo"], "item": m["item"]}} for m in reversed(sel)]
    doc = yaml.safe_load(open(os.path.join(DIG, "ontology", "rules", "software.yaml"), encoding="utf-8"))["rules"]
    fns = {k: (getattr(R, v["fn"]), v["params"]) for k, v in doc.items() if v.get("fn")}
    assert set(fns) == {"SW1", "SW2", "SW3", "SW4", "SW5"}
    good_wos = {"WO-{}".format(i) for i in range(n_good)}
    good = Ctx(rows([m for m in ms if m["wo"] in good_wos]))
    assert all(not f(good, p, {}) for f, p in fns.values()), [k for k, (f, p) in fns.items() if f(good, p, {})]       # 正常时不报
    bad = Ctx(rows([m for m in ms if m["wo"] not in good_wos]))
    hit = {k: f(bad, p, {}) for k, (f, p) in fns.items()}
    assert all(hit.values()), [k for k, v in hit.items() if not v]
    assert hit["SW1"][0].subject == ("Machine", "bld-3") and hit["SW3"][0].subject == ("Machine", "hil-2")
    assert hit["SW4"][0].subject == ("Machine", "cl-a2") and hit["SW5"][0].values["zone"] == "A 区"


def test_other_plants_not_touched():
    """软件公司的模型只算软件公司的版本和订阅：别的厂照旧"""
    ms = _run({"batches": [["WQ-PC1", 1]]}, plant=os.path.join(PLANTS, "wenquest-computer.yaml"))
    assert ms and not any(m["sw"] or m["svc"] for m in ms)
