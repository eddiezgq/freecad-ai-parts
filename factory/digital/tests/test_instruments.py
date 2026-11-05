# -*- coding: utf-8 -*-
"""第 82 轮（电子 E2）：虚拟仪器。网页模型（web/src/lib/instruments.js，用 Node 跑）给出的学生参数与服务器逐位一致；
像学生一样“做实验”（带仪器噪声）得到的结果能被核对判对；答错的判错；种子按人固定；服务接口与实验记录。"""
import json
import os
import shutil
import subprocess

import pytest

from cae import instruments as IN

DIG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(DIG, "web")
needs_node = pytest.mark.skipif(not shutil.which("node"), reason="没有 Node")


def _node(seeds, tasks):
    r = subprocess.run(["node", "tools/instr_check.mjs"], input=json.dumps({"seeds": seeds, "tasks": tasks}), capture_output=True,
                       text=True, cwd=WEB, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout)


def test_seed_is_per_user_and_stable():
    assert IN.seed_of("stu1") == IN.seed_of("stu1") != IN.seed_of("stu2")
    assert IN.variant("torque", 7) == IN.variant("torque", 7) != IN.variant("torque", 8)


def test_answers_follow_formulas():
    a, _ = IN.answers("encoder", 11)
    v = IN.variant("encoder", 11)
    assert a["cpr"] == 4 * 2500 and abs(a["z_ms"] - 60000 / v["rpm"]) < 1e-9 and a["dir"] in ("cw", "ccw")
    t, _ = IN.answers("torque", 11)
    assert 1.9 < t["s_mv_v"] < 2.1 and 0 < t["nl_pct"] < 0.2 and 0 < t["hys_pct"] < 0.2
    f, _ = IN.answers("tof", 11)
    assert abs(f["sd5avg"] - f["sd5"] / 4) < 1e-12


@needs_node
def test_node_variants_match_server():
    out = _node([0, 1, 2, 3, 12345, 4294967295], [])
    for s, o in out.items():
        for t in IN.TASKS:
            assert o["variant"][t] == IN.variant(t, int(s)), (s, t)


@needs_node
def test_node_student_measurements_pass_check():
    seeds = [1, 2, 3, 4, 5, 6]
    out = _node(seeds, ["torque", "encoder", "hall", "ntc", "tof"])
    for s, o in out.items():
        for t, res in o["result"].items():
            c = IN.check(t, int(s), res)
            assert c["all_ok"], (s, t, res, IN.answers(t, int(s))[0], c["rows"])


@needs_node
def test_node_imu_allan_recovers_arw_and_bias_instability():
    seeds = list(range(1, 21))
    out = _node(seeds, ["imu"])
    ok = 0
    for s, o in out.items():
        v, r = o["variant"]["imu"], o["result"]["imu"]
        assert abs(r["arw"] / v["arw"] - 1) < 0.05                 # −1/2 斜率段读 ARW，2 小时数据很准
        ok += IN.check("imu", int(s), r)["all_ok"]
    assert ok >= 17                                                   # 零偏不稳定性的估计本身有 ±30% 左右的散布


def test_wrong_answers_are_rejected():
    a, _ = IN.answers("encoder", 5)
    wrong = dict(a, dir="ccw" if a["dir"] == "cw" else "cw")
    rows = {r["key"]: r["ok"] for r in IN.check("encoder", 5, wrong)["rows"]}
    assert rows == {"dir": False, "rpm": True, "cpr": True, "z_ms": True}
    i, _ = IN.answers("imu", 5)
    assert not IN.check("imu", 5, dict(i, arw=i["arw"] / 60))["all_ok"]          # 单位没换成 °/√h
    assert not IN.check("torque", 5, {})["all_ok"]


def test_service_endpoints_and_record(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from cae import service
    monkeypatch.setattr(service, "DATA", str(tmp_path))
    with TestClient(service.app) as c:
        p = c.post("/instruments/params", json={"user": "stu1"}).json()
        assert p["seed"] == IN.seed_of("stu1") and len(p["tasks"]) == 6 and "arw" in p["labels"]
        right, _ = IN.answers("hall", IN.seed_of("stu1"))
        r = c.post("/instruments/check", json={"user": "stu1", "task": "hall", "answers": right}).json()
        assert r["all_ok"]
        assert not c.post("/instruments/check", json={"user": "stu2", "task": "hall", "answers": right}).json()["all_ok"]   # 别人的答案不对
        doc = c.post("/instruments/record", json={"user": "stu1", "task": "hall", "answers": right, "rows": [["直流", 10, 2.9]],
                                                  "columns": ["类型", "电流 A", "输出 V"], "who": "学生"})
        assert doc.status_code == 200 and doc.content[:2] == b"PK"
        assert c.post("/instruments/check", json={"task": "nope"}).status_code == 404
