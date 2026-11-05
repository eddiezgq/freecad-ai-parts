# -*- coding: utf-8 -*-
"""第 79 轮（电子 E1）：电路分析。6 道驱动板例题的仿真读数与手算公式在题目写明的范围内；网表检查拒绝读写文件、运行命令；
蒙特卡洛固定种子可复现；浏览器 ngspice（WebAssembly，网页同一个模块）与服务器 ngspice 的读数差 < 0.1%；服务接口与计算书。"""
import json
import os
import shutil
import subprocess

import pytest

from cae import circuit as C

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(DIG, "web")
needs_ngspice = pytest.mark.skipif(not shutil.which("ngspice"), reason="没有装 ngspice")


def test_examples_are_ascii_and_have_six():
    assert [v["no"] for v in C.EXAMPLES.values()] == [1, 2, 3, 4, 5, 6]
    for k in C.EXAMPLES:
        b = C.build(k)
        for net in b["netlists"].values():
            assert net.isascii(), k                       # 浏览器引擎按字符数写文件，多字节字符会截断网表
            assert not C.check_netlist(net)[0], (k, C.check_netlist(net)[0])
        assert {n for n, _ in b["checks"]} <= set(b["formulas"])


def test_params_clamped_and_motor_data_used():
    b = C.build("sense", {"gain": 1e9, "rs_mohm": -5})
    assert b["params"]["gain"] == 100 and b["params"]["rs_mohm"] == 0.5
    assert abs(C.i_peak() - 4.46 / C.BOARD["kt"]) < 1e-9          # 峰值力矩取 cae/motors.py 的伺服 400 W


@needs_ngspice
@pytest.mark.parametrize("key", list(C.EXAMPLES))
def test_simulation_matches_formulas(key):
    r = C.simulate(key)
    for a, v in r["by_analysis"].items():
        assert not v["errors"], (key, a, v["errors"])
        assert v["plots"], (key, a)
    for row in r["compare"]:
        assert row["ok"], (key, row)


@needs_ngspice
def test_current_loop_saturates_at_bus_voltage():
    r = C.simulate("current_loop")
    assert r["derived"]["saturated"] and abs(r["meas"]["u_max"] - C.BOARD["vbus"]) < 1e-6
    small = C.simulate("current_loop", {"i_ref": 2.0})
    assert not small["derived"]["saturated"] and small["meas"]["u_max"] < C.BOARD["vbus"]


def test_netlist_check_blocks_files_and_commands():
    bad = "t\nR1 a 0 1k\n.include /etc/passwd\n.control\nshell rm -rf /\n.endc\n.op\n.end\n"
    errs, _ = C.check_netlist(bad)
    assert any(".include" in e for e in errs) and any(".control" in e for e in errs) and any("shell" in e for e in errs)
    errs, nodes = C.check_netlist("t\nV1 in 0 1\nR1 in out 1k\nR2 out 0 1k\n.op\n.end\n")
    assert errs == [] and nodes == ["in", "out"]
    assert C.check_netlist("t\nR1 a 0 1k\n.end\n")[0]                      # 没有分析语句


@needs_ngspice
def test_free_netlist_runs_and_reads_measurements():
    r = C.run("divider\nV1 in 0 10\nR1 in out 1k\nR2 out 0 3k\n.op\n.dc V1 0 10 1\n.meas dc vo FIND v(out) AT=10\n.end\n")
    assert abs(r["meas"]["vo"] - 7.5) < 1e-6
    assert any("v(out)" in p["names"] for p in r["plots"])


@needs_ngspice
def test_montecarlo_reproducible_and_spread_matches_tolerance():
    a = C.montecarlo("sense", n=60, seed=3)
    b = C.montecarlo("sense", n=60, seed=3)
    assert a["mean"] == b["mean"] and a["std"] == b["std"] and a["n"] == 60
    assert a["lo3"] < a["nominal"] < a["hi3"] and a["std"] > 0
    with pytest.raises(ValueError):
        C.montecarlo("buck")


def test_raw_parser_complex_and_real():
    raw = ("Title: t\nDate: x\nPlotname: AC Analysis\nFlags: complex\nNo. Variables: 2\nNo. Points: 2\nVariables:\n"
           "\t0\tfrequency\tfrequency\n\t1\tv(out)\tvoltage\nValues:\n0\t1.0,0.0\n\t0.5,-0.5\n1\t2.0,0.0\n\t0.25,-0.25\n")
    p = C.parse_raw_ascii(raw)[0]
    assert p["complex"] and p["data"]["v(out)"] == [[0.5, -0.5], [0.25, -0.25]]
    assert C.parse_meas("g_peak = 1.5e+01 at= 2.3e+03\nstack = 0 bytes\n", {"g_peak"}) == {"g_peak": 15.0, "g_peak_at": 2300.0}


@needs_ngspice
def test_browser_engine_matches_server():
    """浏览器用的 src/lib/spice.js（eecircuit-engine）跑同样的网表，读数与服务器 ngspice 差 < 0.1%"""
    if not shutil.which("node") or not os.path.isdir(os.path.join(WEB, "node_modules", "eecircuit-engine")):
        pytest.skip("网页依赖没装（CI 在 npm ci 之后单独跑这一项）")
    nets = {k + "." + a: n for k in C.EXAMPLES for a, n in C.build(k)["netlists"].items()}
    r = subprocess.run(["node", "tools/spice_check.mjs"], input=json.dumps(nets), capture_output=True, text=True, cwd=WEB, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    br = json.loads(r.stdout)
    for k, net in nets.items():
        sv = C.run(net, vectors=False)["meas"]
        assert sv, k
        for m, v in sv.items():
            if m.endswith("_at") and not m.startswith("g_peak"):
                continue                                  # 最大 / 最小值“出现在哪一刻”可能落在相邻两点，不比
            assert abs(br[k][m] - v) <= 1e-3 * max(abs(v), 1e-12), (k, m, v, br[k][m])


@needs_ngspice
def test_service_endpoints_and_report():
    from fastapi.testclient import TestClient
    from cae import service
    with TestClient(service.app) as c:
        ex = c.get("/circuit/examples").json()
        assert len(ex["examples"]) == 6 and ex["server_ngspice"]
        b = c.post("/circuit/examples/gate/build", json={"params": {"rg_ohm": 22}}).json()
        assert b["params"]["rg_ohm"] == 22 and b["formulas"]["t_on"] is None and "qgd" in b["netlists"]
        meas = {}
        for net in b["netlists"].values():
            meas.update(c.post("/circuit/run", json={"netlist": net}).json()["meas"])
        rows = c.post("/circuit/examples/gate/compare", json={"params": {"rg_ohm": 22}, "meas": meas}).json()["compare"]
        assert all(r["ok"] for r in rows) and next(r for r in rows if r["name"] == "t_on")["formula"] > 0
        assert c.post("/circuit/run", json={"netlist": "t\n.include x\n.op\n.end\n"}).status_code == 400
        rep = c.post("/circuit/examples/sense/report", json={"meas": {}})
        assert rep.status_code == 200 and rep.content[:2] == b"PK"
        assert c.post("/circuit/examples/nope/build", json={}).status_code == 404
