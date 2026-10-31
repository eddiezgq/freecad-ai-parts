# -*- coding: utf-8 -*-
"""第 58 轮：负载跑合台（sim/runin.py、hub/lab28.py）。标准题：辨识出的库仑摩擦复原关节测试台的值、黏性摩擦复原这台的真值；
写回模型后均方根差降到测量噪声的量级；同一出厂编号结果一样；测试台摩擦的 σ 与机器人厂清单一致；力矩裕量按减速器额定、关节上限判；
仿真车间装整机时把关节测试台测得的空载摩擦力矩先进先出带进整机标定的测量；实验 28 六个任务答对拿 60 分（测试数据库，子进程）。"""
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from cae import wqcr5 as W
from sim import runin as R

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")
BENCH = [1.31, 1.05, 0.86, 0.47, 0.33, 0.41]


def test_identification_recovers_bench_and_true_viscous():
    c = R.case("WQCR5-T-0001", BENCH)
    truth = c["_truth"]
    assert truth["fc"] == BENCH
    for i, j in enumerate(c["joints"]):
        assert abs(j["fc_hat"] - BENCH[i]) < 0.05, (j["joint"], j["fc_hat"])
        assert abs(j["fv_hat"] - truth["fv"][i]) < 0.1 * truth["fv"][i] + 0.05, (j["joint"], j["fv_hat"], truth["fv"][i])
        assert j["rms_diff_updated"] < 1.5 * j["noise_sigma"], j            # 写回模型后只剩测量噪声
        assert j["rms_diff"] > j["rms_diff_updated"]
    assert c["bench_known"]


def test_deterministic_and_fallback():
    a, b = R.case("WQCR5-X", BENCH, detail=False), R.case("WQCR5-X", BENCH, detail=False)
    assert a == b
    c = R.case("WQCR5-X", None)                                              # 没有测试台记录：按名义值和 σ 由出厂编号补
    assert not c["bench_known"] and c["_truth"]["fc"] == R.case("WQCR5-X", None)["_truth"]["fc"]
    fv0 = R.nominal_friction()[1]
    assert all(0.6 * n - 1e-9 <= v <= 1.6 * n + 1e-9 for v, n in zip(c["_truth"]["fv"], fv0))


def test_friction_sigma_and_nominal_match_plant():
    txt = open(ROBOT, encoding="utf-8").read()
    for size in "LMS":
        seg = txt.split("item: WQJ-" + size + "\n  operation: 关节测试", 1)[1].split("- item:", 1)[0]
        line = [ln for ln in seg.splitlines() if "joint_friction" in ln][0]
        assert "sigma: " + str(R.FRIC_SIGMA[size]) + "}" in line, (size, line)
        assert "nominal: {},".format(W.MODULES[size]["frictionloss"]) in line, (size, line)


def test_torque_margin_against_gear_rating():
    c = R.case("WQCR5-T-0001", BENCH, detail=False)
    for j, s in zip(c["joints"], W.JOINT_MODULE):
        assert j["rated"] == W.MODULES[s]["gear"][1]
        assert j["pass"] == (j["rms_meas"] <= j["rated"] and j["peak_meas"] <= j["limit"])
    J2 = c["joints"][1]
    assert 5 < J2["rms_meas"] < J2["rated"] and J2["peak_meas"] < J2["limit"]  # 5 kg 负载：肩关节有明显力矩，仍在裕量内
    assert c["pass"]


def test_simulated_torque_is_the_library_model():
    """“仿真”就是零件库模型：刚体部分用 mj_inverse 算，和在同一模型上正向积分时的驱动力矩一致（抽一个点核对 M q̈ + C + g）"""
    import mujoco
    t, Q, QD, QDD = R.motion()
    k = len(t) // 3
    tau = R._rigid_torque(Q[k], QD[k], QDD[k])
    xml = W.mjcf(friction=False).replace("<!--TOOL-->", W.runin_load_xml())
    m = mujoco.MjModel.from_xml_string(xml)
    d = mujoco.MjData(m)
    d.qpos[:6], d.qvel[:6] = Q[k], QD[k]
    mujoco.mj_forward(m, d)
    qdd = np.zeros(m.nv); qdd[:6] = QDD[k]
    Mq = np.zeros(m.nv)
    mujoco.mj_mulM(m, d, Mq, qdd)
    assert np.allclose(Mq[:6] + d.qfrc_bias[:6], tau, atol=1e-6)


SIM = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from factory import data as F
from sim.engine import Engine
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
eng = Engine(lambda tp, ty, src, data, corr: out.append(data), Clock(), mode="teach", auto_start=True, seed=3, status_every_s=1e9)
for item, v in (("WQJ-L", 1.31), ("WQJ-L", 1.05), ("WQJ-M", 0.86), ("WQJ-S", 0.47), ("WQJ-S", 0.33), ("WQJ-S", 0.41), ("WQJ-S", 0.5)):
    eng.errors.note_joint_friction(item, v)
class W: item = "WQ-CR5"; name = "WO-CR5"
class P: serial = "WQCR5-T-0002"; wo = W(); err = None
class J: wo = W(); op = "整机标定 Robot calibration"
p = P()
eng.errors.on_process("ra-1", p, 0.0)
spec = F.MEASURE[("WQ-CR5", "整机标定 Robot calibration")]
eng._measure_chars(p, "cal-1", J(), spec, None)
m = [d for d in out if d.get("characteristic") == "cr_abs"][0]
print(json.dumps({{"friction": m["calib"]["friction_nm"], "left": eng.errors.fric_fifo.get("S")}}))
"""


def test_sim_assembly_carries_bench_friction():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", SIM.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["friction"] == BENCH and out["left"] == [0.5]


LAB = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_lab28_test with (force)")
    c.execute("create database wq_lab28_test")
from hub.db import DB
from hub.historian import Historian
from hub import lab28
from sim import calib as C
db = DB(BASE + "/wq_lab28_test")
db.init()
h = Historian(db)
Z = [5.0, -12.0, 8.0, 3.0, -6.0, 2.0]
F = {bench!r}
for k, serial in enumerate(("WQCR5-A", "WQCR5-B")):
    cal = C.case(serial, Z)
    h.handle("wq/gearbox/quality/cal-1/measurement", wqbus.make("quality.measurement", "sim/cal-1", {{
        "part_serial": serial, "item": "WQ-CR5", "work_order": "WO-%d" % k, "operation": "整机标定 Robot calibration", "characteristic": "cr_abs",
        "name": "标定后绝对定位误差", "unit": "mm", "nominal_mm": 0.12, "lower_tol_mm": 0, "upper_tol_mm": 0.5, "value_mm": cal["after_mean_mm"],
        "result": "pass", "calib": {{"zero_arcsec": Z, "before_mm": cal["before_mean_mm"], "friction_nm": F}}}}, mode="teach"))
STU = "学生甲"
out = {{"robots": [r["serial"] for r in lab28.robots(db, "teach")]}}
lab28.pick(db, STU, "WQCR5-A")
c = lab28.case(db, "teach", "WQCR5-A")
out["bench_used"] = [j["fc_bench"] for j in c["joints"]] == F
J = {{j["joint"]: j for j in c["joints"]}}
out["t1_wrong"] = lab28.answer(db, "学生乙", "l28_t1", {{"peak": J["J2"]["peak_sim"] * 1.5}})["score"]
out["t1"] = lab28.answer(db, STU, "l28_t1", {{"peak": J["J2"]["peak_meas"] * 1.01}})["score"]
out["t2"] = lab28.answer(db, STU, "l28_t2", {{"joint": max(c["joints"], key=lambda j: j["rms_diff"])["joint"]}})["score"]
out["t3"] = lab28.answer(db, STU, "l28_t3", {{"fc": J["J1"]["fc_hat"], "fv": J["J1"]["fv_hat"] * 1.02}})["score"]
out["t4"] = lab28.answer(db, STU, "l28_t4", {{"choice": "viscous"}})["score"]
out["t5"] = lab28.answer(db, STU, "l28_t5", {{"rms": J["J2"]["rms_meas"], "pass": c["pass"]}})["score"]
out["t6"] = lab28.answer(db, STU, "l28_t6", {{"choice": "noise"}})["score"]
out["score"] = lab28.status(db, STU)["score"]
out["truth_hidden"] = "truth" not in c and "_truth" not in c
out["teacher_truth"] = "truth" in lab28.case(db, "teach", "WQCR5-A", teacher=True)
csv = lab28.csv_text(db, "teach", "WQCR5-A").splitlines()
out["csv"] = [len(csv), len(csv[0].split(","))]
out["class"] = lab28.class_view(db)
print(json.dumps(out, ensure_ascii=False))
"""


def test_lab28_full_marks():
    pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", LAB.format(dig=DIG, fac=FAC, base=base, bench=BENCH)], capture_output=True, text=True,
                       env=env, cwd=DIG, timeout=300)
    if r.returncode != 0 and "connection" in r.stderr.lower():
        pytest.skip("没有可用的 PostgreSQL")
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["robots"] == ["WQCR5-B", "WQCR5-A"] and out["bench_used"]
    assert out["t1_wrong"] == 0
    assert [out[k] for k in ("t1", "t2", "t3", "t4", "t5", "t6")] == [10] * 6 and out["score"] == 60
    assert out["truth_hidden"] and out["teacher_truth"]
    n = int(round(W.runin_duration() * R.HZ)) // 2 + 1
    assert out["csv"] == [n + 1, 1 + 6 * 4]
    assert [c["user"] for c in out["class"]] == ["学生乙", "学生甲"] and out["class"][1]["total"] == 60
