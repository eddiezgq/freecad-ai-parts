# -*- coding: utf-8 -*-
"""第 55 轮：整机运动学标定。标准题：名义正运动学与独立写法一致；已知偏差、没有噪声时辨识后位置完全复原；有噪声时零位偏差辨识到
噪声量级；位姿集中、太少时条件数变大、标定效果变差；关节测试台零位漂 30″，辨识出的零位一起偏约 30″；仿真车间整机标定出数；
实验 26 六个任务答对拿 60 分（用测试数据库，机器人厂清单在子进程里）。"""
import json
import math
import os
import subprocess
import sys

import numpy as np
import pytest

from sim import calib as C

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAC = os.path.dirname(DIG)
ROBOT = os.path.join(FAC, "plants", "wenquest-robot.yaml")
DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")


def _fk_independent(q):
    """另一种写法：齐次变换逐项写开（与 calib.fk 不共用代码）"""
    T = np.eye(4)
    for qi, n in zip(q, C.NOMINAL):
        c, s, ca, sa = math.cos(qi), math.sin(qi), math.cos(n["alpha"]), math.sin(n["alpha"])
        A = np.array([[c, -s * ca, s * sa, n["a"] * c], [s, c * ca, -c * sa, n["a"] * s], [0, sa, ca, n["d"]], [0, 0, 0, 1]])
        T = T.dot(A)
    return T[:3, :3].dot(C.TOOL) + T[:3, 3]


def test_nominal_fk_matches_independent_and_hand_case():
    for q in C.poses("fk-check", 10):
        assert np.allclose(C.fk(q), _fk_independent(q), atol=1e-12)
    # 手算（全零位）：J1 偏距 150 后 Rx(90°) 让 z 轴指向基座 −y；大臂 −400、小臂 −360 沿 x → (−760, 0, 150)；
    # J4 偏距 120 沿 −y → (−760, −120, 150)，Rx(90°) 后 z 指向 −z；J5 偏距 100 → (−760, −120, 50)，Rx(−90°) 后 z 指向 −y；
    # J6 偏距 90 → (−760, −210, 50)；工具点 (50, 0, 100)：x 不变 +50，z 指向 −y → (−710, −310, 50) mm
    assert np.allclose(C.fk([0.0] * 6) * 1000, [-710, -310, 50], atol=1e-9)


def test_noiseless_identification_restores_positions(monkeypatch):
    monkeypatch.setattr(C, "SIG_TRACKER", 0.0)
    monkeypatch.setattr(C, "SIG_UNMODELED", 0.0)
    r = C.case("CR5-STD-1", [10, -20, 30, 5, 0, -15])
    assert r["rank"] == 21 and r["params"] == 24              # 相邻平行轴 J2–J4 的偏距只分得出和（24 − 3 = 21）
    assert r["before_mean_mm"] > 0.5 and r["after_max_mm"] < 1e-4


def test_zero_offsets_identified_to_noise_level():
    for s in ("CR5-STD-2", "CR5-STD-3", "CR5-STD-4"):
        r = C.case(s, [12, -8, 20, -15, 5, 0], detail=True)
        for i in range(4):                                    # J1–J4 的零位：差在 0.01° 以内（噪声 0.02 mm、臂长约 0.8 m）
            assert abs(r["identified"][i]["dtheta_deg"] - r["_truth"][i]["dtheta_deg"]) < 0.01, (s, i)
        assert 0.5 < r["before_mean_mm"] < 2.5 and r["after_mean_mm"] < 0.2 and r["pass"]


def test_pose_choice_matters():
    full = [C.case("CR5-P-%d" % i, None, 30, "full") for i in range(4)]
    clus = [C.case("CR5-P-%d" % i, None, 30, "cluster") for i in range(4)]
    few = [C.case("CR5-P-%d" % i, None, 8, "full") for i in range(4)]
    for a, b, c in zip(full, clus, few):
        assert b["cond"] > 20 * a["cond"] and c["cond"] > a["cond"]
    mean = lambda rs: sum(x["after_mean_mm"] for x in rs) / len(rs)     # noqa: E731
    assert mean(clus) > 3 * mean(full) and mean(few) > mean(full)


def test_bench_zero_drift_shows_in_identified_zero_offsets():
    a = C.case("CR5-Z", [0] * 6, detail=True)["identified"]
    b = C.case("CR5-Z", [30] * 6, detail=True)["identified"]
    for i in range(5):
        assert abs((b[i]["dtheta_deg"] - a[i]["dtheta_deg"]) * 3600 - 30) < 3, i


SIM = r"""
import json, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import wqbus
from factory import data as F
from sim.engine import Engine
from sim import calib as C
out = []
class Clock:
    t = 0.0
    def now(self):
        return self.t
eng = Engine(lambda tp, ty, src, data, corr: out.append(data), Clock(), mode="teach", auto_start=True, seed=3, status_every_s=1e9)
for item, v in (("WQJ-L", 11.0), ("WQJ-L", -7.0), ("WQJ-M", 4.0), ("WQJ-S", 9.0), ("WQJ-S", -3.0), ("WQJ-S", 1.5), ("WQJ-S", 99.0)):
    eng.errors.note_joint_zero(item, v)
class W: item = "WQ-CR5"; name = "WO-CR5"
class P: serial = "WQCR5-T-0001"; wo = W(); err = None
class J: wo = W(); op = "整机标定 Robot calibration"
p = P()
eng.errors.on_process("ra-1", p, 0.0)            # 整机装配：装进 6 台关节
spec = F.MEASURE[("WQ-CR5", "整机标定 Robot calibration")]
eng._measure_chars(p, "cal-1", J(), spec, None)
m = [d for d in out if d.get("characteristic") == "cr_abs"][0]
ref = C.case(p.serial, [11.0, -7.0, 4.0, 9.0, -3.0, 1.5])
print(json.dumps({{"value": m["value_mm"], "calib": m["calib"], "ref": ref["after_mean_mm"], "before": ref["before_mean_mm"],
                  "left": eng.errors.zero_fifo.get("S")}}))
"""


def test_sim_calibration_station_uses_calib_and_joint_zeros():
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", SIM.format(dig=DIG, fac=FAC)], capture_output=True, text=True, env=env, cwd=DIG, timeout=120)
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["calib"]["zero_arcsec"] == [11.0, -7.0, 4.0, 9.0, -3.0, 1.5]           # J1、J2 大关节，J3 中，J4–J6 小关节，先进先出
    assert abs(out["value"] - out["ref"]) < 1e-4 and out["calib"]["before_mm"] == out["before"]
    assert out["left"] == [99.0]


LAB = r"""
import json, math, sys
sys.path[:0] = [{dig!r}, {fac!r}]
import psycopg, wqbus
BASE = {base!r}
with psycopg.connect(BASE + "/postgres", autocommit=True) as c:
    c.execute("drop database if exists wq_lab26_test with (force)")
    c.execute("create database wq_lab26_test")
from hub.db import DB
from hub.historian import Historian
from hub import lab26
from sim import calib as C
db = DB(BASE + "/wq_lab26_test")
db.init()
h = Historian(db)
Z = [5.0, -12.0, 8.0, 3.0, -6.0, 2.0]
for k, serial in enumerate(("WQCR5-A", "WQCR5-B")):
    cal = C.case(serial, Z)
    h.handle("wq/gearbox/quality/cal-1/measurement", wqbus.make("quality.measurement", "sim/cal-1", {{
        "part_serial": serial, "item": "WQ-CR5", "work_order": "WO-%d" % k, "operation": "整机标定 Robot calibration", "characteristic": "cr_abs",
        "name": "标定后绝对定位误差", "unit": "mm", "nominal_mm": 0.12, "lower_tol_mm": 0, "upper_tol_mm": 0.5, "value_mm": cal["after_mean_mm"],
        "result": "pass", "calib": {{"zero_arcsec": Z, "before_mm": cal["before_mean_mm"]}}}}, mode="teach"))
STU = "学生甲"
out = {{"robots": [r["serial"] for r in lab26.robots(db, "teach")]}}
lab26.pick(db, STU, "WQCR5-A")
serial = lab26.my_robot(db, STU)
q = [math.radians(x) for x in lab26.fk_question(serial)]
x, y, z = (C.fk(q) * 1000).tolist()
out["t1"] = lab26.answer(db, STU, "l26_t1", {{"x": x, "y": y, "z": z + 0.2}})["score"]
out["t2_early"] = lab26.answer(db, STU, "l26_t2", {{"larger": "cluster"}})["score"]
for n, sp in ((30, "full"), (30, "cluster"), (8, "full")):
    lab26.note_try(db, STU, serial, n, sp, lab26.case(db, "teach", serial, n, sp))
out["t2"] = lab26.answer(db, STU, "l26_t2", {{"larger": "cluster"}})["score"]
res = lab26.case(db, "teach", serial)
top = [r["joint"] for r in sorted(res["identified"], key=lambda r: -abs(r["dtheta_deg"]))[:2]]
out["t3"] = lab26.answer(db, STU, "l26_t3", {{"joints": top}})["score"]
out["t4"] = lab26.answer(db, STU, "l26_t4", {{"after_mm": res["after_mean_mm"], "pass": res["pass"]}})["score"]
out["t5"] = lab26.answer(db, STU, "l26_t5", {{"choice": "worse_ill"}})["score"]
out["t6"] = lab26.answer(db, STU, "l26_t6", {{"choice": "bench"}})["score"]
out["wrong_t1"] = lab26.answer(db, "学生乙", "l26_t1", {{"x": x + 30, "y": y, "z": z}})["score"]
st = lab26.status(db, STU)
out["score"] = st["score"]
out["truth_hidden"] = "truth" not in res and "_truth" not in res
out["teacher_truth"] = "truth" in lab26.case(db, "teach", serial, teacher=True)
print(json.dumps(out, ensure_ascii=False))
"""


def test_lab26_full_marks():
    pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    env = dict(os.environ, WQ_PLANT_FILE=ROBOT)
    r = subprocess.run([sys.executable, "-c", LAB.format(dig=DIG, fac=FAC, base=base)], capture_output=True, text=True, env=env, cwd=DIG, timeout=300)
    if r.returncode != 0 and "connection" in r.stderr.lower():
        pytest.skip("没有可用的 PostgreSQL")
    assert r.returncode == 0, r.stderr[-3000:]
    out = json.loads(r.stdout)
    assert out["robots"] == ["WQCR5-B", "WQCR5-A"]
    assert out["t2_early"] == 0 and out["wrong_t1"] == 0
    assert [out[k] for k in ("t1", "t2", "t3", "t4", "t5", "t6")] == [10] * 6 and out["score"] == 60
    assert out["truth_hidden"] and out["teacher_truth"]
