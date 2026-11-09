# -*- coding: utf-8 -*-
"""第 123 轮：实验 31“关节终检抱闸报警的排查”——标准答案取自第 114 轮固件仿真结果；三种故障每人打乱；全对 60 分；
答错拿不到；处置没做对不能复测。评分部分需要 PostgreSQL。"""
import os
import sys

import pytest

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DIG)
from hub import lab31 as L  # noqa: E402

DSN = os.environ.get("WQ_TEST_DB", "postgresql://postgres@localhost:5433/wq_test")


def test_truth_from_firmware_sim():
    s = L.sim()
    assert s is not None, "第 114 轮固件仿真结果应在 designs/drv-joint-b/fw/out/sim_motor.json"
    assert [a[2] for a in L.alarms(s["brk_open"])][-1] == 1
    assert [a[2] for a in L.alarms(s["brk_short"])][-1] == 2
    assert [a[2] for a in L.alarms(s["brk_fet"])] == [2, 3]           # 先过流、后抱不住
    assert all(a[1] == 7 for sc in L.SCEN for a in L.alarms(s[sc]))
    t = L.short_times()
    assert 0 < t["engage_ms"] < t["off_ms"] < 300                      # 先抱住、后关输出
    assert max(s["brk_open"]["series"]["brake_i"]) == 0                # 断线：线圈一直没电流
    assert s["brk_boot"]["passed"]
    fw = L.fw_times()                                                     # 页上波形算出的答案与固件自己记的一致（±15 ms）
    assert abs(fw["engage_ms"] - t["engage_ms"]) <= 15 and abs(fw["off_ms"] - t["off_ms"]) <= 15, (fw, t)


def test_case_shuffled_and_complete():
    seen = set()
    for u in ("a", "b", "c", "d", "e", "f", "g", "h"):
        cs = L.case(u)
        assert sorted(j["scenario"] for j in cs["joints"]) == sorted(L.SCEN)
        assert [j["size"] for j in cs["joints"]] == ["L", "M", "S"]
        seen.add(tuple(j["scenario"] for j in cs["joints"]))
    assert len(seen) > 1
    st_rec = L.record(L.sim()["brk_short"])
    assert "text" not in st_rec["frames"][0]                             # 只给原始报文
    assert len(st_rec["series"]["t"]) <= 260


def _db():
    psycopg = pytest.importorskip("psycopg")
    base = DSN.rsplit("/", 1)[0]
    name = "wq_lab31_test"
    try:
        with psycopg.connect(base + "/postgres", autocommit=True, connect_timeout=3) as c:
            c.execute("drop database if exists {} with (force)".format(name))
            c.execute("create database {}".format(name))
    except Exception as e:  # noqa: BLE001
        pytest.skip("没有可用的 PostgreSQL：{}".format(e))
    from hub.db import DB
    db = DB(base + "/" + name)
    db.init()
    return db


def _right(user):
    cs = L.case(user)
    s = L.sim()
    a1, a2, a5 = {}, {}, {}
    for j in cs["joints"]:
        last = L.alarms(s[j["scenario"]])[-1]
        a1[j["serial"]] = {"code": "0x{:02X}".format(last[1]), "sub": "{:02d}".format(last[2])}
        a2[j["serial"]] = L.TRUTH[j["scenario"]]["part"]
        a5[j["serial"]] = L.TRUTH[j["scenario"]]["action"]
    return a1, a2, a5


def test_lab31_grading():
    db = _db()
    a1, a2, a5 = _right("stu")
    # 答错：拿不到；处置没做对不能复测
    w2 = {k: "ok" for k in a2}
    assert L.answer(db, "stu2", "l31_t2", w2)["score"] == 0
    assert L.answer(db, "stu2", "l31_t4", {"choice": "delay"})["score"] == 0
    assert L.answer(db, "stu2", "l31_t3", {"engage_ms": 500, "off_ms": 900})["score"] == 0
    assert L.answer(db, "stu2", "l31_t6", {})["score"] == 0
    # 别人的答案套不到自己的三台上（序列号不同）
    assert L.answer(db, "stu2", "l31_t1", a1)["score"] == 0
    # 全对
    t = L.short_times()
    sc = [L.answer(db, "stu", "l31_t1", a1)["score"], L.answer(db, "stu", "l31_t2", a2)["score"],
          L.answer(db, "stu", "l31_t3", {"engage_ms": t["engage_ms"] + 10, "off_ms": t["off_ms"] - 10})["score"],
          L.answer(db, "stu", "l31_t4", {"choice": "cmd_vs_current"})["score"],
          L.answer(db, "stu", "l31_t5", a5)["score"]]
    r6 = L.answer(db, "stu", "l31_t6", {})
    sc.append(r6["score"])
    assert sc == [10] * 6
    assert all(r["ok"] for r in r6["retest"]["rows"])
    st = L.status(db, "stu")
    assert st["score"] == 60 and st["retest"] and not st["sim_missing"]
    assert len(st["joints"]) == 3 and all("record" in j for j in st["joints"])
    assert any(c["user"] == "stu" and c["total"] == 60 for c in L.class_view(db))
